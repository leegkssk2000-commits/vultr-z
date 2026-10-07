"""Artificial rows only. Never import a repository market loader or archive."""
import copy
import unittest
from datetime import datetime, timezone

from eth_session_adapter_draft import DraftError, HOUR, eth_session_targets, funding_for_signed_exposure, replay_eth_sessions, unit_transition

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


if __name__ == "__main__":
    unittest.main()
