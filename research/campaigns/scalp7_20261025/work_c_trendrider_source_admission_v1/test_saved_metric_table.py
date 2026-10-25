"""Finite saved-accounting fixtures only; no market data, strategy, or replay."""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import saved_metric_table as accounting


def fixture():
    def timestamp(month, day, hour):
        return int(datetime(2026, month, day, hour, tzinfo=timezone.utc).timestamp() * 1000)

    def opportunity(symbol, signal_ts, values):
        key = f"{symbol}|long|{signal_ts}"
        legs = []
        for index, (gross, cost) in enumerate(values):
            legs.append({"opportunity_key": key, "symbol": symbol,
                         "kind": "PRIMARY_LONG" if index == 0 else "REVERSAL_SHORT",
                         "side": "long" if index == 0 else "short",
                         "entry_ts": signal_ts + (index + 1) * 3_600_000,
                         "exit_bar_ts": timestamp(12, 1, index),
                         "gross_bps": gross, "modeled_cost_bps": cost, "Net2_bps": gross - 2 * cost})
        return {"key": key, "symbol": symbol, "signal_ts": signal_ts,
                "Net2_bps": sum(leg["Net2_bps"] for leg in legs), "legs": legs}

    accepted = [opportunity("AAA-USDT", timestamp(9, 30, 23), [(30.0, 3.0), (-6.0, 2.0)]),
                opportunity("BBB-USDT", timestamp(10, 1, 1), [(60.0, 4.0)])]
    # Deliberately distinct metric sentinels verify copying, not re-estimation.
    metrics = {
        "Net2_sum_trade_bps": 66.0, "accepted_opportunities": 2, "total_legs": 3,
        "long_legs": 2, "reverse_short_legs": 1, "PF2_opportunity": 7.25,
        "WR2_opportunity": 0.123, "DD2_realized_exit_leg_bps": 999.0,
        "max_loss_streak_opportunity": 8, "max_loss_streak_leg": 9,
        "worst_loss_R_from_long_risk": -107.5, "max_win_R_from_long_risk": 23.75,
        "Net2_excluding_top2_bps": -300.0, "largest_2_opportunity_winners_bps": 366.0,
        "largest_loss_opportunity_bps": -235.0,
        "by_month_Net2": {"2026-09": 14.0, "2026-10": 52.0},
        "admissions": {"accepted": 2, "rejected": 0, "available_source_opportunities": 2},
    }
    freeze = "a" * 64
    result = {"schema": "zel.trendrider.unified_one_owner_causal_rescue.result.v1",
              "freeze_sha256": freeze, "stage_economics": {stage: copy.deepcopy(metrics) for stage in accounting.STAGES},
              "source_inputs": {"counts": {"LIQUID_SELECTED": 1, "DELAYED_SELECTED": 1, "EXACT_SIGNAL_DEDUPED": 0}},
              "source_timing": {"historical_real_received_at": "UNKNOWN", "market_1h_seen_to": timestamp(10, 2, 0),
                                "source_api_calls_this_eval": 0},
              "limitation": "SYNTHETIC_SAVED_ACCOUNTING_FIXTURE_NOT_PROFIT",
              "opportunity_comparison": {stage: {"common_T": 2, "new_accepted_original_opportunities_T": 0,
                  "original_admissions_lost": 0, "original_lost_winner_T": 0, "original_lost_winner_net2": 0.0,
                  "common_net2_delta_bps": 0.0, "total_net2_delta_bps": 0.0} for stage in accounting.STAGES[1:]}}
    stripped = {key: copy.deepcopy(value) for key, value in metrics.items() if key != "admissions"}
    robustness = {"schema": "zel.trendrider.unified_rescue.robustness.v1", "source_freeze_sha256": freeze,
                  "source_result_sha256": "pending-byte-pin", "baseline_metrics": copy.deepcopy(stripped),
                  "full_metrics": copy.deepcopy(stripped), "fully_new_unseen_OOS": False,
                  "realized_broker_fee_funding": False}
    traces = {"schema": "zel.trendrider.unified.causal_exit_trace.v1", "freeze_sha256": freeze,
              "not_canonical_trade_ledger": True, "live_order_authority": "BLOCKED",
              "stages": {stage: {"accepted": copy.deepcopy(accepted), "rejected": []} for stage in accounting.STAGES}}
    failed = {"schema": "zel.trendrider.unified.stop_cost_screen_result.v1", "fresh_prospective": False,
              "actual_fee_unknown": True, "base_S4": copy.deepcopy(stripped), "one_axis_S4": copy.deepcopy(stripped),
              "cost_stop_preentry_rejected_T": 1, "original_S4_acceptances_removed_by_filter_T": 1,
              "removed_prior_winners_T": 1, "removed_prior_winner_net2": 14.0}
    return dict(result=result, robustness=robustness, traces=traces, failed_filter=failed)


def write_fixture(directory):
    documents = fixture()
    raw_result = json.dumps(documents["result"], sort_keys=True).encode()
    documents["robustness"]["source_result_sha256"] = hashlib.sha256(raw_result).hexdigest()
    paths, hashes = {}, {}
    for key, name in accounting.FILES.items():
        raw = raw_result if key == "result" else json.dumps(documents[key], sort_keys=True).encode()
        if key == "traces":
            raw = gzip.compress(raw, mtime=0)
        path = Path(directory) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        paths[key] = path
        hashes[key] = hashlib.sha256(raw).hexdigest()
    return paths, hashes


class SavedMetricAccountingTests(unittest.TestCase):
    def test_sealed_gross_cost_net1_net2_and_symbol_month_reconcile(self):
        inputs = fixture()
        before = copy.deepcopy(inputs)
        report = accounting.build_table(**inputs)
        self.assertEqual(len(report["rows"]), 7)
        for row in report["rows"][:5]:
            self.assertEqual(row["gross_bps_sum"], 84.0)
            self.assertEqual(row["modeled_cost_bps_sum"], 9.0)
            self.assertEqual(row["net1_bps_sum"], 75.0)
            self.assertEqual(row["net2_bps_sum"], 66.0)
            self.assertEqual(row["by_symbol_net2_bps"], {"AAA-USDT": 14.0, "BBB-USDT": 52.0})
            self.assertEqual(row["by_signal_month_net2_bps"], {"2026-09": 14.0, "2026-10": 52.0})
            self.assertNotIn("2026-12", row["by_signal_month_net2_bps"])
        self.assertEqual(inputs, before)

    def test_pf_wr_dd_streak_and_original_r_are_copied_not_new_risk_or_nav(self):
        report = accounting.build_table(**fixture())
        copied = report["rows"][0]["copied_saved_metrics"]
        self.assertEqual(copied["PF2_opportunity"], 7.25)
        self.assertEqual(copied["WR2_opportunity"], 0.123)
        self.assertEqual(copied["DD2_realized_exit_leg_bps"], 999.0)
        self.assertEqual(copied["worst_loss_R_from_long_risk"], -107.5)
        self.assertEqual(copied["max_win_R_from_long_risk"], 23.75)
        self.assertIn("ONE_THIRD", report["units"]["bps"])
        self.assertIn("NOT_ACCOUNT_NAV", report["units"]["bps"])
        self.assertIn("NO_NEW_R_DERIVED", report["units"]["R"])
        self.assertFalse(report["metric_provenance"]["saved_metrics_recomputed"])

    def test_all_pins_checked_before_parsing_and_missing_input_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            paths, hashes = write_fixture(directory)
            paths["robustness"].write_bytes(paths["robustness"].read_bytes() + b"\n")
            with mock.patch.object(accounting, "decode_json", side_effect=AssertionError("must not parse before all pins")):
                with self.assertRaisesRegex(accounting.AccountingError, "INPUT_SHA256_MISMATCH:robustness"):
                    accounting.audit_paths(**paths, expected_sha256=hashes)
            paths["result"].unlink()
            with self.assertRaises(OSError):
                accounting.audit_paths(**paths, expected_sha256=hashes)

    def test_actual_fixture_bytes_link_to_robustness_and_remain_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            paths, hashes = write_fixture(directory)
            before = {key: path.read_bytes() for key, path in paths.items()}
            report = accounting.audit_paths(**paths, expected_sha256=hashes)
            self.assertEqual(report["input_sha256"], hashes)
            self.assertEqual({key: path.read_bytes() for key, path in paths.items()}, before)
            document = json.loads(paths["robustness"].read_bytes())
            document["source_result_sha256"] = "0" * 64
            raw = json.dumps(document).encode()
            paths["robustness"].write_bytes(raw)
            hashes["robustness"] = hashlib.sha256(raw).hexdigest()
            with self.assertRaisesRegex(accounting.AccountingError, "ROBUSTNESS_RESULT_BYTES"):
                accounting.audit_paths(**paths, expected_sha256=hashes)

    def test_duplicate_opportunity_or_duplicate_leg_cannot_inflate_accounting(self):
        for duplicate in ("opportunity", "leg"):
            with self.subTest(duplicate=duplicate):
                data = fixture()
                accepted = data["traces"]["stages"]["S0"]["accepted"]
                if duplicate == "opportunity":
                    accepted.append(copy.deepcopy(accepted[0]))
                else:
                    accepted[0]["legs"].append(copy.deepcopy(accepted[0]["legs"][0]))
                with self.assertRaisesRegex(accounting.AccountingError, "DUPLICATE_"):
                    accounting.build_table(**data)

    def test_net2_leg_opportunity_and_saved_total_tampering_are_rejected(self):
        for level in ("leg", "opportunity", "saved"):
            with self.subTest(level=level):
                data = fixture()
                opportunity = data["traces"]["stages"]["S0"]["accepted"][0]
                if level == "leg":
                    opportunity["legs"][0]["Net2_bps"] += 1
                elif level == "opportunity":
                    opportunity["Net2_bps"] += 1
                else:
                    data["result"]["stage_economics"]["S0"]["Net2_sum_trade_bps"] += 1
                with self.assertRaisesRegex(accounting.AccountingError, "RECONCILIATION_MISMATCH"):
                    accounting.build_table(**data)

    def test_saved_month_and_source_population_mismatch_fail_closed(self):
        data = fixture()
        data["result"]["stage_economics"]["S0"]["by_month_Net2"] = {"2026-12": 66.0}
        with self.assertRaisesRegex(accounting.AccountingError, "SIGNAL_MONTH_NET2"):
            accounting.build_table(**data)
        data = fixture()
        data["result"]["source_inputs"]["counts"]["DELAYED_SELECTED"] += 1
        with self.assertRaisesRegex(accounting.AccountingError, "SOURCE_POPULATION"):
            accounting.build_table(**data)

    def test_no_trade_based_rate_window_and_no_actual_funding_or_new_source_claim(self):
        report = accounting.build_table(**fixture())
        self.assertFalse(report["window_inferred_from_trades"])
        self.assertIn("UNBOUND", report["source_last_1h_bar_closure"])
        self.assertIsNone(report["rows"][0]["opportunities_per_day"])
        self.assertIsNone(report["rows"][0]["legs_per_day"])
        self.assertFalse(report["fully_new_unseen_OOS"])
        self.assertFalse(report["realized_broker_fee_funding"])
        self.assertFalse(report["new_economic_run_eligible"])
        self.assertEqual(report["economic_runs"], 0)
        fresh = report["rows"][-1]
        self.assertEqual(fresh["stage"], "S4_REALISTIC_NEW_SOURCE")
        self.assertEqual(fresh["classification"], "NOT_RUN")
        self.assertTrue(all(fresh[key] is None for key in accounting.ARITHMETIC_FIELDS))
        self.assertTrue(all(value is None for value in fresh["copied_saved_metrics"].values()))

    def test_any_explicit_window_is_rejected_until_eligible_window_is_bound(self):
        start = int(datetime(2026, 9, 30, tzinfo=timezone.utc).timestamp() * 1000)
        for window in ({}, {"start_ms": 0, "end_ms": 2 * 86_400_000, "authority": "ARBITRARY_1970"},
                       {"start_ms": start, "end_ms": start + 2 * 86_400_000, "authority": "PLAUSIBLE_BUT_UNCERTIFIED_2026"}):
            with self.subTest(window=window), self.assertRaisesRegex(accounting.AccountingError, "ELIGIBLE_WINDOW_UNBOUND"):
                accounting.build_table(**fixture(), window_bounds=window)

    def test_failed_filter_missing_legs_stays_null_and_diffs_are_preserved(self):
        data = fixture()
        report = accounting.build_table(**data)
        filtered = report["rows"][-2]
        self.assertIsNone(filtered["gross_bps_sum"])
        self.assertIsNone(filtered["modeled_cost_bps_sum"])
        self.assertIsNone(filtered["net1_bps_sum"])
        self.assertIsNone(filtered["by_symbol_net2_bps"])
        self.assertEqual(filtered["net2_bps_sum"], 66.0)
        self.assertEqual(filtered["comparison_vs_saved_S4"]["removed_prior_winner_net2"], 14.0)
        self.assertEqual(report["rows"][1]["comparison_vs_S0"], data["result"]["opportunity_comparison"]["S1"])

    def test_missing_stage_missing_metric_and_duplicate_json_key_rejected(self):
        data = fixture()
        del data["traces"]["stages"]["S3"]
        with self.assertRaisesRegex(accounting.AccountingError, "ALL_S0_S4_STAGES_REQUIRED"):
            accounting.build_table(**data)
        data = fixture()
        del data["result"]["stage_economics"]["S0"]["DD2_realized_exit_leg_bps"]
        with self.assertRaises(KeyError):
            accounting.build_table(**data)
        with self.assertRaisesRegex(accounting.AccountingError, "DUPLICATE_JSON_KEY"):
            accounting.decode_json(b'{"same": 1, "same": 2}')


if __name__ == "__main__":
    unittest.main()
