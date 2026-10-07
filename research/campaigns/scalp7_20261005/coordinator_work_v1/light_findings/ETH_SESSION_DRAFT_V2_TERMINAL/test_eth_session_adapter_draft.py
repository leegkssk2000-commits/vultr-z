"""Artificial rows only. Never import a repository market loader or archive."""
import copy
import unittest
from datetime import datetime, timezone

from eth_session_adapter_draft import DraftError, HOUR, eth_session_targets, funding_for_signed_exposure, replay_eth_sessions, terminal_eth_report, unit_transition

BASE = int(datetime(2026, 1, 13, tzinfo=timezone.utc).timestamp() * 1000)


def artificial_rows(hours=72, day_return=0.2):
    rows = []
    for i in range(hours):
        stamp = BASE + i * HOUR
        # Completed 04:00 and16:00 closes represent05/17 boundary prices.
        closing = 100.0 * (1 + day_return) if i % 24 == 16 else 100.0
        rows.append({"open_ts_ms": stamp, "close_ts_ms": stamp + HOUR,
                     "available_ts_ms": stamp + HOUR, "segment_id": "ARTIFICIAL",
                     "open": 100.0 + i, "close": closing})
    return rows


def run(rows, start=17, end=72, funding=()):
    return replay_eth_sessions(rows, funding, start_ms=BASE + start * HOUR,
                               end_ms=BASE + end * HOUR, roundtrip_cost_bps=14.0)


def rate(stamp, value, mark=100):
    return {"symbol": "ETH-USDT", "fundingTime": stamp, "fundingRate": str(value), "markPrice": str(mark)}


class ArtificialContractTests(unittest.TestCase):
    def test_day_direction_uses_previous_completed_day_not_current_or_future(self):
        rows = artificial_rows()
        original = [x for x in eth_session_targets(rows) if x["boundary_ts_ms"] <= BASE + 29 * HOUR]
        changed = copy.deepcopy(rows)
        for row in changed[29:]:
            row["open"] *= 2
            row["close"] *= 3
        self.assertEqual(original, [x for x in eth_session_targets(changed) if x["boundary_ts_ms"] <= BASE + 29 * HOUR])
        decision = original[-1]
        self.assertEqual(decision["desired_units"], -1)
        self.assertEqual(decision["dependency_close_ts_ms"], [BASE + 5 * HOUR, BASE + 17 * HOUR])

    def test_night_direction_and_fill_do_not_wait_for_current_candle_close(self):
        rows = artificial_rows(18)
        rows[17]["close"] = 9999.0
        rows[17]["available_ts_ms"] = BASE + 100 * HOUR
        result = run(rows, end=18)
        self.assertEqual(result["orders"][0]["execution_ts_ms"], BASE + 17 * HOUR)
        self.assertEqual(result["orders"][0]["desired_units"], 1)

    def test_both_dependency_receipts_gate_first_later_observed_open(self):
        for dependency in (4, 16):
            with self.subTest(dependency=dependency):
                rows = artificial_rows(36)
                rows[dependency]["available_ts_ms"] = BASE + 31 * HOUR + 1
                result = run(rows, end=36)
                flip = result["orders"][1]
                self.assertEqual(flip["signal_available_ts_ms"] if "signal_available_ts_ms" in flip else flip["available_ts_ms"], BASE + 31 * HOUR + 1)
                self.assertEqual(flip["execution_ts_ms"], BASE + 32 * HOUR)

    def test_same_side_keeps_entry_quantity_and_cost(self):
        result = run(artificial_rows(48, day_return=-0.2), end=48)
        self.assertEqual(len(result["orders"]), 1)
        self.assertEqual(result["trades"], [])
        self.assertEqual(result["turnover_units"], 1)
        self.assertEqual(result["paid_trading_cost_bps"], 7)
        self.assertEqual(len(result["same_side_boundaries"]), 2)
        self.assertEqual(result["open_position"]["entry_ts_ms"], BASE + 17 * HOUR)
        self.assertEqual(result["open_position"]["entry_price"], 117)

    def test_all_nine_quantity_transitions_reconcile_zero_single_double_leg(self):
        expected = {(-1, -1): (0, 0), (-1, 0): (1, 7), (-1, 1): (2, 14),
                    (0, -1): (1, 7), (0, 0): (0, 0), (0, 1): (1, 7),
                    (1, -1): (2, 14), (1, 0): (1, 7), (1, 1): (0, 0)}
        for pair, outcome in expected.items():
            with self.subTest(pair=pair):
                self.assertEqual(unit_transition(*pair, 14), outcome)

    def test_flip_cost_is_two_legs_closed_plus_open_entry_reconciles(self):
        result = run(artificial_rows(36), end=36)
        self.assertEqual([x["quantity"] for x in result["orders"]], [1, 2])
        self.assertEqual([x["cost_bps"] for x in result["orders"]], [7, 14])
        self.assertEqual(result["closed_trading_cost_bps"], 14)
        self.assertEqual(result["open_entry_cost_bps"], 7)
        self.assertEqual(result["paid_trading_cost_bps"], 21)
        self.assertEqual(result["trades"][0]["exit_ts_ms"], BASE + 29 * HOUR)
        self.assertEqual(result["open_position"]["side"], "SHORT")

    def test_zero_day_return_goes_cash_not_missing_input(self):
        result = run(artificial_rows(36, day_return=0), end=36)
        self.assertEqual([x["desired_units"] for x in result["orders"]], [1, 0])
        self.assertIsNone(result["open_position"])
        self.assertEqual(result["paid_trading_cost_bps"], 14)

    def test_short_exit_sign_and_cost_stress_does_not_stress_funding(self):
        rows = artificial_rows(48)
        settlement = BASE + 34 * HOUR
        result = run(rows, end=48, funding=[rate(settlement, 0.001, 129)])
        short = result["trades"][1]
        self.assertEqual(short["side"], "SHORT")
        self.assertAlmostEqual(short["gross_bps"], -(141 / 129 - 1) * 10_000)
        self.assertAlmostEqual(short["funding_bps"], -10)
        self.assertEqual(short["cost_bps"], 14)
        net2 = short["gross_bps"] - 2 * short["cost_bps"] - short["funding_bps"]
        self.assertAlmostEqual(short["net_bps"] - net2, 14)
        self.assertEqual(result["paid_trading_cost_bps"], 35)
        self.assertEqual(result["closed_trading_cost_bps"] + result["open_entry_cost_bps"], 35)

    def test_signed_funding_interior_and_adverse_entry_exit(self):
        rates = [rate(100, -0.001, 110), rate(200, -0.001, 110), rate(300, -0.001, 110)]
        for side, expected in ((1, (-11.0, 1)), (-1, (33.0, 3))):
            exposure = {"entry_ts_ms": 100, "exit_ts_ms": 300, "entry_price": 100, "signed_units": side}
            value, count = funding_for_signed_exposure(exposure, rates, end_ms=400, closed=True)
            self.assertAlmostEqual(value, expected[0])
            self.assertEqual(count, expected[1])

    def test_exact_flip_funding_chooses_one_adverse_owner_not_two(self):
        stamp = BASE + 29 * HOUR
        for signed_rate in (-0.001, 0.001):
            with self.subTest(rate=signed_rate):
                result = run(artificial_rows(36), end=36, funding=[rate(stamp, signed_rate)])
                old = result["trades"][0]
                new = result["open_position"]
                settlements = old["funding_settlements"] + new["funding_settlements"]
                self.assertEqual(settlements, 1)
                self.assertGreaterEqual(old["funding_bps"], 0)
                self.assertGreaterEqual(new["funding_bps_to_end_exclusive"], 0)
                self.assertEqual(old["cost_bps"], 14)

    def test_same_side_session_boundary_retains_signed_credit(self):
        stamp = BASE + 29 * HOUR
        result = run(artificial_rows(36, day_return=-0.2), end=36, funding=[rate(stamp, -0.001, 117)])
        self.assertAlmostEqual(result["open_position"]["funding_bps_to_end_exclusive"], -10)
        self.assertEqual(result["open_position"]["funding_settlements"], 1)

    def test_end_position_cost_preserved_without_force_close_or_after_end(self):
        rows = artificial_rows(36)
        end = BASE + 36 * HOUR
        first = run(rows, end=36, funding=[rate(end, 0.999)])
        later = run(artificial_rows(50), end=36, funding=[rate(end, 0.999)])
        self.assertEqual(first, later)
        self.assertEqual(first["unresolved_end"], 1)
        self.assertEqual(first["disposition"], "BLOCKED_TERMINAL_UNRESOLVED")
        self.assertEqual(first["open_position"]["funding_bps_to_end_exclusive"], 0)
        self.assertEqual(first["open_entry_cost_bps"], 7)

    def test_expired_target_not_filled_at_next_session(self):
        rows = artificial_rows(48)
        rows[16]["available_ts_ms"] = BASE + 42 * HOUR
        result = run(rows, end=48)
        self.assertEqual(len(result["orders"]), 1)
        self.assertEqual(result["expired_targets"][0]["boundary_ts_ms"], BASE + 29 * HOUR)
        self.assertEqual(result["open_position"]["side"], "LONG")

    def test_pending_end_is_preserved_without_extra_fee(self):
        rows = artificial_rows(30)
        rows[16]["available_ts_ms"] = BASE + 32 * HOUR
        result = run(rows, end=30)
        self.assertIsNotNone(result["pending_target"])
        self.assertEqual(result["paid_trading_cost_bps"], 7)
        self.assertEqual(result["trades"], [])

    def test_gap_quarantines_exact_open_state_no_fabricated_exit(self):
        rows = artificial_rows(36)
        rows.pop(22)
        result = run(rows, end=36)
        self.assertEqual(result["disposition"], "BLOCKED_SOURCE_GAP")
        self.assertEqual(result["trades"], [])
        self.assertEqual(result["open_position"]["entry_ts_ms"], BASE + 17 * HOUR)
        self.assertEqual(result["open_entry_cost_bps"], 7)

    def test_segment_change_has_same_unresolved_gap_guard(self):
        rows = artificial_rows(36)
        for row in rows[22:]:
            row["segment_id"] = "ARTIFICIAL_NEW_SEGMENT"
        result = run(rows, end=36)
        self.assertEqual(result["disposition"], "BLOCKED_SOURCE_GAP")
        self.assertEqual(len(result["orders"]), 1)

    def test_off_grid_and_nonfinite_close_reject_instead_of_cash(self):
        for kind in ("off_grid", "nan_close", "zero_close"):
            with self.subTest(kind=kind):
                rows = artificial_rows(36)
                if kind == "off_grid":
                    rows[5]["open_ts_ms"] += 60_000
                else:
                    rows[4]["close"] = float("nan") if kind == "nan_close" else 0
                with self.assertRaises(DraftError):
                    run(rows, end=36)

    def test_duplicate_or_wrong_symbol_funding_rejects(self):
        stamp = BASE + 20 * HOUR
        with self.assertRaises(DraftError):
            run(artificial_rows(36), end=36, funding=[rate(stamp, 0.001), rate(stamp, 0.001)])
        wrong = rate(stamp, 0.001)
        wrong["symbol"] = "BTC-USDT"
        with self.assertRaises(DraftError):
            run(artificial_rows(36), end=36, funding=[wrong])

    def test_integer_segment_ids_from_existing_common_source_are_supported(self):
        rows = artificial_rows(36)
        for row in rows:
            row["segment_id"] = 7
        self.assertEqual(len(run(rows, end=36)["orders"]), 2)

    def test_missing_terminal_price_coverage_rejects_before_funding_accrual(self):
        with self.assertRaisesRegex(DraftError, "SOURCE_COVERAGE"):
            run(artificial_rows(18), end=36, funding=[rate(BASE + 30 * HOUR, 0.001)])

    def test_target_expiring_exactly_end_is_expired_not_filled_or_pending(self):
        rows = artificial_rows(41)
        rows[16]["available_ts_ms"] = BASE + 42 * HOUR
        result = run(rows, end=41)
        self.assertIsNone(result["pending_target"])
        self.assertEqual(result["expired_targets"][0]["boundary_ts_ms"], BASE + 29 * HOUR)
        self.assertEqual(result["paid_trading_cost_bps"], 7)

    def test_malformed_signed_exposure_and_funding_fail_as_draft_errors(self):
        valid = {"entry_ts_ms": 100, "exit_ts_ms": 300, "entry_price": 100, "signed_units": 1}
        for wrong_side in (True, 1.9, "1"):
            with self.subTest(side=wrong_side), self.assertRaises(DraftError):
                funding_for_signed_exposure({**valid, "signed_units": wrong_side}, [], end_ms=400, closed=True)
        with self.assertRaises(DraftError):
            funding_for_signed_exposure({**valid, "entry_ts_ms": 300, "exit_ts_ms": 100}, [], end_ms=400, closed=True)
        with self.assertRaises(DraftError):
            funding_for_signed_exposure(valid, [None], end_ms=400, closed=True)


class TerminalArtificialTests(unittest.TestCase):
    def marked_example(self):
        rows = artificial_rows(36)
        rows[17]["open"] = 100.0
        rows[29]["open"] = 101.0
        rows[35]["close"] = 103.02
        result = run(rows, end=36, funding=[rate(BASE + 32 * HOUR, -0.0005, 101)])
        return rows, result

    def test_positive_closed_negative_open_not_hidden_and_state_unchanged(self):
        rows, result = self.marked_example()
        before = copy.deepcopy(result)
        report = terminal_eth_report(result, rows, end_ms=BASE + 36 * HOUR)
        self.assertEqual(result, before)
        self.assertEqual(report["completed_trade_count"], 1)
        self.assertAlmostEqual(report["closed_realized"]["net_1x_bps"], 86)
        scenario = report["cost_scenarios"]["reference_1x"]
        self.assertAlmostEqual(scenario["open_marked_net_bps"], -212)
        self.assertAlmostEqual(scenario["combined_entry_normalized_bps"], -126)
        self.assertAlmostEqual(scenario["realized_cashflows_before_unrealized_mark_bps"], 74)
        self.assertEqual(report["preserved_replay_disposition"], "BLOCKED_TERMINAL_UNRESOLVED")
        self.assertEqual(report["preserved_unresolved_end"], 1)
        self.assertEqual(report["economic_disposition"], "NOT_EVALUATED_REPORT_ONLY_NO_NEW_THRESHOLD")
        self.assertIsNone(report["account_nav"])
        self.assertEqual(report["completed_trades_added"], 0)

    def test_receipt_exact_end_marks_but_adds_no_exit_fee_or_closed_trade(self):
        rows, result = self.marked_example()
        end = BASE + 36 * HOUR
        report = terminal_eth_report(result, rows, end_ms=end)
        mark = report["open_mark"]
        self.assertEqual(mark["mark_close_ts_ms"], end)
        self.assertEqual(mark["mark_available_ts_ms"], end)
        self.assertTrue(mark["position_still_open"])
        self.assertTrue(mark["mark_is_exact_end_close"])
        self.assertEqual(mark["hypothetical_exit_fee_bps"], 0)
        self.assertEqual(report["exit_orders_added"], 0)

    def test_latest_close_not_latest_receipt_and_late_body_never_read(self):
        class Unreceived(dict):
            def __getitem__(self, key):
                if key == "close":
                    raise AssertionError("UNRECEIVED_CLOSE_BODY_READ")
                return super().__getitem__(key)
        rows, result = self.marked_example()
        end = BASE + 36 * HOUR
        rows[30]["available_ts_ms"] = end
        rows[34]["close"] = 102.0
        rows[35]["available_ts_ms"] = end + 1
        rows[35] = Unreceived(rows[35])
        report = terminal_eth_report(result, rows, end_ms=end)
        mark = report["open_mark"]
        self.assertEqual(mark["mark_close_ts_ms"], BASE + 35 * HOUR)
        self.assertEqual(mark["mark_price"], 102)
        self.assertFalse(mark["mark_is_exact_end_close"])
        self.assertEqual(mark["mark_age_at_end_ms"], HOUR)

    def test_no_post_entry_causal_mark_means_unknown_not_zero(self):
        rows, result = self.marked_example()
        end = BASE + 36 * HOUR
        for row in rows[29:]:
            row["available_ts_ms"] = end + HOUR
        report = terminal_eth_report(result, rows, end_ms=end)
        self.assertEqual(report["report_status"], "BLOCKED_NO_POST_ENTRY_CAUSAL_MARK")
        self.assertIsNone(report["open_mark"])
        self.assertIsNone(report["cost_scenarios"])
        self.assertAlmostEqual(report["closed_realized"]["net_1x_bps"], 86)

    def test_gap_lineage_or_quarantine_never_becomes_valued_success(self):
        rows = artificial_rows(36)
        rows.pop(22)
        result = run(rows, end=36)
        report = terminal_eth_report(result, rows, end_ms=BASE + 36 * HOUR)
        self.assertEqual(report["report_status"], "BLOCKED_OCCUPIED_SOURCE_GAP")
        self.assertIsNone(report["cost_scenarios"])
        full_rows, full_result = self.marked_example()
        full_rows[33]["segment_id"] = "CHANGED_AFTER_REPLAY"
        changed = terminal_eth_report(full_result, full_rows, end_ms=BASE + 36 * HOUR)
        self.assertEqual(changed["report_status"], "BLOCKED_MARK_SOURCE_LINEAGE")
        self.assertIsNone(changed["cost_scenarios"])

    def test_missing_open_or_closed_funding_never_defaults_to_zero(self):
        rows, result = self.marked_example()
        del result["open_position"]["funding_bps_to_end_exclusive"]
        report = terminal_eth_report(result, rows, end_ms=BASE + 36 * HOUR)
        self.assertEqual(report["report_status"], "BLOCKED_OPEN_FUNDING_OR_MARK_FIELDS")
        self.assertIsNone(report["cost_scenarios"])
        rows, result = self.marked_example()
        del result["trades"][0]["funding_bps"]
        report = terminal_eth_report(result, rows, end_ms=BASE + 36 * HOUR)
        self.assertEqual(report["report_status"], "BLOCKED_ACCOUNTING_FIELDS_OR_FEE_RECONCILIATION")
        self.assertIsNone(report["cost_scenarios"])

    def test_cost_stress_doubles_paid_fees_only_and_signed_funding_unchanged(self):
        rows, result = self.marked_example()
        report = terminal_eth_report(result, rows, end_ms=BASE + 36 * HOUR)
        one = report["cost_scenarios"]["reference_1x"]
        two = report["cost_scenarios"]["reference_2x"]
        self.assertEqual(one["all_signed_funding_debit_bps"], two["all_signed_funding_debit_bps"])
        self.assertAlmostEqual(one["combined_entry_normalized_bps"] - two["combined_entry_normalized_bps"], 21)
        self.assertEqual(two["all_already_paid_trading_fee_bps"], 42)

    def test_after_end_body_not_read_and_end_funding_excluded_both_signs(self):
        rows, result = self.marked_example()
        end = BASE + 36 * HOUR
        baseline = terminal_eth_report(result, rows, end_ms=end)
        # No close/receipt/segment fields: touching this future body would fail.
        self.assertEqual(baseline, terminal_eth_report(result, rows + [{"open_ts_ms": end}], end_ms=end))
        for signed_rate in (-0.001, 0.001):
            result_with_end = run(rows, end=36, funding=[rate(BASE + 32 * HOUR, -0.0005, 101), rate(end, signed_rate)])
            report = terminal_eth_report(result_with_end, rows, end_ms=end)
            self.assertEqual(report["cost_scenarios"], baseline["cost_scenarios"])

    def test_forged_total_fee_or_wrong_end_is_blocked(self):
        rows, result = self.marked_example()
        result["paid_trading_cost_bps"] += 7
        report = terminal_eth_report(result, rows, end_ms=BASE + 36 * HOUR)
        self.assertEqual(report["report_status"], "BLOCKED_ACCOUNTING_FIELDS_OR_FEE_RECONCILIATION")
        with self.assertRaises(DraftError):
            terminal_eth_report(result, rows, end_ms=BASE + 37 * HOUR)


if __name__ == "__main__":
    unittest.main()
