"""Synthetic regressions and mandatory pinned current255/new256 archive fixtures."""
import copy
import importlib.util
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import unittest

_spec = importlib.util.spec_from_file_location("current_trendrider_attribution", Path(__file__).with_name("attribution.py"))
subject = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(subject)


def row(name, gross, cost=0, entry=0, exit=1, signal=None):
    return {"symbol": name, "side": "long", "signal_ts": entry if signal is None else signal,
            "entry_ts": entry, "exit_ts": exit, "entry": 100, "exit": 100,
            "gross_bps": gross, "realized_cost_bps": cost,
            "net_bps": str(Decimal(str(gross)) - Decimal(str(cost))),
            "intent_sha": name + "_intent", "feature_sha": name + "_feature",
            "cost_snapshot_sha": "snapshot", "reason": "SL"}


def receipt(rows, **extra):
    return {"completed_trades": len(rows), "trades": rows, **extra}


def ms(date):
    return int(datetime.fromisoformat(date).replace(tzinfo=timezone.utc).timestamp() * 1000)


def report(rows):
    return subject.build_attribution(receipt(rows), "SYNTHETIC_TEST")


class AttributionTests(unittest.TestCase):
    def test_cost_2x_not_cost_3x_and_no_extra_funding(self):
        item = row("A", 30, 8)
        item["funding_cost_bps"] = 123  # Untrusted extra field is not added to the stored total.
        result = report([item])
        self.assertEqual(Decimal(result["cost_1x"]["net_sum_trade_bps"]), 22)
        self.assertEqual(Decimal(result["cost_2x_posthoc"]["net_sum_trade_bps"]), 14)
        self.assertIsNone(result["fee_funding_component_split"])

    def test_original_exit_and_tie_cohort_drawdown_have_different_units(self):
        result = report([row("A", -10, exit=1), row("B", 20, exit=3), row("C", -10, exit=2)])
        curves = result["cost_1x"]["chronology"]
        self.assertEqual(Decimal(curves["original_receipt_order"]["drawdown_sum_trade_bps"]), 10)
        self.assertEqual(Decimal(curves["exit_bar_individual"]["drawdown_sum_trade_bps"]), 20)
        self.assertEqual(curves["original_receipt_order"]["max_consecutive_negative_observations"], 1)
        self.assertEqual(curves["exit_bar_cohort"]["max_consecutive_negative_observations"], 2)
        tied = report([row("A", -10), row("B", 10)])["cost_1x"]["chronology"]
        self.assertEqual(Decimal(tied["exit_bar_individual"]["drawdown_sum_trade_bps"]), 10)
        self.assertEqual(Decimal(tied["exit_bar_cohort"]["drawdown_sum_trade_bps"]), 0)
        self.assertIsNone(tied["account_drawdown"])

    def test_equal_timestamp_exits_before_entries_and_zero_span_not_leaked(self):
        data = [row("A", -10, entry=0, exit=10), row("B", 5, entry=10, exit=20),
                row("C", -4, entry=10, exit=10)]
        occ = report(data)["same_time_occupancy_diagnostic"]
        self.assertEqual(occ["maximum_simultaneously_active_closed_rows"], 1)
        self.assertEqual(occ["zero_bar_span_count"], 1)
        event = next(r for r in occ["timeline"] if r["ts_ms"] == 10)
        self.assertEqual(event["active_after_exits_before_entries"], 0)
        self.assertEqual(event["active_after_all_same_time_events"], 1)
        self.assertEqual(occ["timeline"][-1]["active_after_all_same_time_events"], 0)
        self.assertEqual(occ["closed_row_position_milliseconds"], 20)

    def test_worst_active_members_are_retrospective_final_outcomes(self):
        data = [row("A", -10, entry=0, exit=20), row("B", -20, entry=10, exit=30)]
        occ = report(data)["same_time_occupancy_diagnostic"]
        worst = occ["worst_active_cohorts_by_final_member_outcome"]["cost_1x"][0]
        self.assertEqual(occ["maximum_simultaneously_active_closed_rows"], 2)
        self.assertEqual(worst["active_count"], 2)
        self.assertEqual((worst["start_ts"], worst["end_ts"]), (10, 20))
        self.assertEqual(Decimal(worst["retrospective_member_final_outcomes"]["net_1x_bps"]), -30)
        self.assertFalse(occ["candidate_capacity_or_admission_claim"])

    def test_entry_and_exit_month_differ_without_moving_or_filtering_rows(self):
        result = report([row("A", 20, entry=ms("2026-09-30T23:00"), exit=ms("2026-10-01T01:00"))])
        self.assertEqual(result["monthly"]["entry_month_utc"][0]["group"], "2026-09")
        self.assertEqual(result["monthly"]["exit_bar_month_utc"][0]["group"], "2026-10")
        self.assertEqual(len(result["september_winners"]["entry_month_basis"]), 1)
        self.assertEqual(result["september_winners"]["exit_month_basis"], [])

    def test_october_cluster_keeps_mixed_winners_and_losers_in_same_cohort(self):
        t = ms("2026-10-01T00:00")
        result = report([row("A", -20, entry=t, exit=t + 1), row("B", 10, entry=t, exit=t + 1),
                         row("C", 1, entry=t, exit=t + 2), row("D", -4, entry=t, exit=t + 3)])
        groups = result["october_loser_clusters_retrospective"]["cost_1x"]
        runs = groups["consecutive_negative_exit_cohort_runs"]
        self.assertEqual(groups["loser_count"], 2)
        self.assertEqual(len(runs), 2)
        self.assertEqual(runs[0]["trades"], 2)
        self.assertEqual(Decimal(runs[0]["outcomes"]["net_1x_bps"]), -10)

    def test_leave_group_out_and_top_rank_do_not_delete_baseline_winners(self):
        data = [row("A", 20), row("B", 10), row("C", -25)]
        before = copy.deepcopy(data)
        result = report(data)
        drop = result["top_winner_drop_diagnostic"]["cost_1x"][0]
        self.assertEqual(Decimal(drop["descriptive_remaining_net_trade_bps"]), -15)
        self.assertEqual(result["baseline_retention"]["retained_rows"], 3)
        self.assertEqual(len(result["baseline_retention"]["cost_1x_all_winner_identities"]), 2)
        self.assertEqual(data, before)
        result["rows"][0]["saved_row"]["entry"] = -1
        self.assertEqual(data, before)

    def test_no_large_definition_or_recovery_trace_is_invented(self):
        result = report([row("A", 1000)])
        self.assertIsNone(result["baseline_retention"]["large_ordinary_winner_classification"]["large_count"])
        self.assertIsNone(result["rows"][0]["retrospective_only"]["MFE"])
        self.assertIsNone(result["rows"][0]["retrospective_only"]["outcome_available_ts"])
        self.assertEqual(result["negative_control"]["new_control_run"], "NOT_RUN")

    def test_empty_and_no_loss_profit_factor_and_flat_loss_streak(self):
        empty = report([])
        self.assertIsNone(empty["cost_1x"]["net_per_trade_bps"])
        self.assertEqual(empty["same_time_occupancy_diagnostic"]["maximum_simultaneously_active_closed_rows"], 0)
        self.assertIsNone(report([row("A", 1)])["cost_1x"]["profit_factor"])
        flat = report([row("A", -1, exit=1), row("B", 0, exit=2), row("C", -1, exit=3)])
        self.assertEqual(flat["cost_1x"]["chronology"]["exit_bar_cohort"]["max_consecutive_negative_observations"], 1)

    def test_malformed_count_duplicate_proxy_and_time_are_rejected(self):
        base = row("A", 10)
        for bad in (receipt([base, copy.deepcopy(base)]), receipt([row("A", 1, entry=2, exit=1)]),
                    {"trades": [base], "completed_trades": 2}):
            with self.assertRaises(ValueError):
                subject.build_attribution(bad, "BAD")
        for value in (True, "NaN", "Infinity"):
            bad = row("A", 10)
            bad["realized_cost_bps"] = value
            with self.assertRaises(ValueError):
                report([bad])

    def test_snapshot_common_removed_added_cost_decomposition_exact(self):
        old = receipt([row("A", 30, 10), row("B", -5, 1)])
        new_a = row("A", 29, 8)
        new_a["intent_sha"] = "changed_native_intent"
        new = receipt([new_a, row("C", -3, 1)])
        before = copy.deepcopy((old, new))
        result = subject.compare_snapshots(old, new)
        self.assertEqual((result["common_events"], result["removed_events"], result["new_events"]), (1, 1, 1))
        self.assertEqual(result["classification"], "ROLLING_RECOMPUTED_NOT_APPEND_ONLY")
        dec = result["decomposition"]
        self.assertEqual(Decimal(dec["common_delta"]["net_1x_bps"]), 1)
        self.assertEqual(Decimal(dec["observed_total_delta"]["net_1x_bps"]), 3)
        self.assertEqual(dec["observed_total_delta"], dec["common_delta_plus_added_minus_removed"])
        self.assertEqual((old, new), before)
        self.assertFalse(result["economic_improvement_or_alpha_claim"])

    def test_winner_retention_distinguishes_removed_worsened_and_nonpositive(self):
        t = ms("2026-09-01T00:00")
        old = receipt([row("A", 10, entry=t, exit=t + 1), row("B", 10, entry=t, exit=t + 1),
                       row("C", 10, entry=t, exit=t + 1)])
        new = receipt([row("A", 9, entry=t, exit=t + 1), row("B", 1, 2, entry=t, exit=t + 1)])
        result = subject.compare_snapshots(old, new)["september_winner_retention"]["entry_month_1x"]
        self.assertEqual(result["baseline_winners"], 3)
        self.assertEqual(result["proxy_retained"], 2)
        self.assertEqual(result["positive_retained"], 1)
        self.assertEqual(result["status_counts"], {"NONPOSITIVE": 1, "POSITIVE_WORSENED": 1, "REMOVED": 1})

    def test_append_only_is_distinguished_from_recomputed_old_rows(self):
        old = receipt([row("A", 10)])
        same = subject.compare_snapshots(old, copy.deepcopy(old))
        self.assertEqual(same["classification"], "IDENTICAL_ROWS")
        added = receipt(old["trades"] + [row("B", -3, entry=2, exit=3)])
        self.assertEqual(subject.compare_snapshots(old, added)["classification"], "APPEND_ONLY_ROWS")
        altered = copy.deepcopy(added)
        altered["trades"][0]["feature_sha"] = "different"
        self.assertEqual(subject.compare_snapshots(old, altered)["classification"], "ROLLING_RECOMPUTED_NOT_APPEND_ONLY")

    def test_decimal_precision_and_json_serializability(self):
        data = [row(str(i), "1.123456789012345678901234567890123456789", entry=i, exit=i + 1) for i in range(255)]
        result = report(data)
        self.assertEqual(result["cost_1x"]["gross_sum_trade_bps"], "286.481481198148148119814814811981481481195")
        json.dumps(result, allow_nan=False)


class ActualCurrentSnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parent
        guard_spec = importlib.util.spec_from_file_location("current_trendrider_receipt_guard", root / "receipt_guard.py")
        guard = importlib.util.module_from_spec(guard_spec)
        guard_spec.loader.exec_module(guard)
        cls.receipts = [guard.load_pinned_bundle(root, label)["receipt"] for label in ("current255", "later256")]
        cls.reports = [subject.build_attribution(r, label) for r, label in zip(cls.receipts, ("current255", "later256"))]
        cls.comparison = subject.compare_snapshots(*cls.receipts)

    def test_current_inputs_counts_metrics_and_two_cost_case(self):
        expected = [(255, 56, "1184.9203927069446158", "-3464.5019834632120582"),
                    (256, 57, "1366.3469831938250648", "-3120.4696221756017302")]
        for result, (n, wins, one, two) in zip(self.reports, expected):
            self.assertEqual(result["cost_1x"]["trades"], n)
            self.assertEqual(result["cost_1x"]["wins"], wins)
            self.assertEqual(result["cost_1x"]["net_sum_trade_bps"], one)
            self.assertEqual(result["cost_2x_posthoc"]["net_sum_trade_bps"], two)

    def test_full_rows_and_winners_kept_and_actual_occupancy(self):
        for result, source, zero in zip(self.reports, self.receipts, (21, 20)):
            self.assertEqual([row["saved_row"] for row in result["rows"]], source["trades"])
            self.assertEqual(result["baseline_retention"]["baseline_rows"], len(source["trades"]))
            self.assertEqual(len(result["baseline_retention"]["cost_1x_all_winner_identities"]), result["cost_1x"]["wins"])
            self.assertEqual(result["same_time_occupancy_diagnostic"]["zero_bar_span_count"], zero)
            self.assertEqual(result["same_time_occupancy_diagnostic"]["maximum_simultaneously_active_closed_rows"], 12)

    def test_current_actual_roll_is_not_append_only(self):
        result = self.comparison
        self.assertEqual((result["common_events"], result["removed_events"], result["new_events"]), (249, 6, 7))
        self.assertEqual(result["classification"], "ROLLING_RECOMPUTED_NOT_APPEND_ONLY")
        self.assertEqual(result["common_field_change_counts"]["realized_cost_bps"], 149)
        self.assertEqual(result["common_field_change_counts"]["gross_bps"], 61)
        self.assertEqual(result["decomposition"]["observed_total_delta"], result["decomposition"]["common_delta_plus_added_minus_removed"])
        self.assertFalse(result["source_windows_equal"])

    def test_current_actual_month_clocks_and_entry_vs_exit_dd(self):
        for result, entry_oct, exit_oct, entry_dd, exit_dd in zip(
                self.reports, (141, 143), (147, 149),
                ("19015.3956943475242352", "19032.1068698548636002"),
                ("18735.0264323405102442", "18751.7480362383588792")):
            month = result["monthly"]
            self.assertEqual(next(r for r in month["entry_month_utc"] if r["group"] == "2026-10")["cost_1x"]["trades"], entry_oct)
            self.assertEqual(next(r for r in month["exit_bar_month_utc"] if r["group"] == "2026-10")["cost_1x"]["trades"], exit_oct)
            chronology = result["cost_1x"]["chronology"]
            self.assertEqual(chronology["original_receipt_order"]["drawdown_sum_trade_bps"], entry_dd)
            self.assertEqual(chronology["exit_bar_cohort"]["drawdown_sum_trade_bps"], exit_dd)
            self.assertEqual(chronology["exit_bar_cohort"]["max_consecutive_negative_observations"], 24)

    def test_current_september_winners_not_removed_by_this_snapshot_roll(self):
        retention = self.comparison["september_winner_retention"]["entry_month_1x"]
        self.assertEqual(retention["baseline_winners"], 34)
        self.assertEqual(retention["proxy_retained"], 34)
        self.assertEqual(retention["positive_retained"], 34)
        self.assertEqual(retention["status_counts"]["POSITIVE_WORSENED"], 11)
        self.assertIsNone(retention["large_ordinary_classification"]["large_count"])


if __name__ == "__main__":
    unittest.main()
