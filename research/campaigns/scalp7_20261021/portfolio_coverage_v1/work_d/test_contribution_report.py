"""Synthetic saved-ledger tests. No market data, strategy replay or order calls."""

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from datetime import datetime


MODULE = Path(__file__).with_name("contribution_report.py")


def ms(value):
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)


def row(identity="A", *, signal="2026-01-02T12:00:00Z", entry=None,
        exit="2026-01-02T13:00:00Z", side=1, symbol="BTC-USDT", gross=12.0,
        cost=2.0, **extra):
    value = {
        "identity": identity,
        "partition": "rolling",
        "symbol": symbol,
        "side": side,
        "signal_ts_ms": ms(signal),
        "entry_ts_ms": ms(entry or signal),
        "exit_ts_ms": ms(exit) if exit else None,
        "outcome_available_ts_ms": ms(exit) if exit else None,
        "gross_bps": gross,
        "cost_bps": cost,
        "net_bps": gross - cost,
        "regime": "SYNTHETIC",
    }
    value.update(extra)
    return value


def manifest(labels=("A", "B"), *, start="2026-01-01T00:00:00Z",
             end="2026-01-05T00:00:00Z", baseline=("A",)):
    return {
        "schema": "zel.work_d.input.v1",
        "window_utc": [start, end],
        "baseline_labels": list(baseline),
        "sources": [{
            "label": label,
            "identity": label,
            "identity_field": "identity",
            "ref": "1" * 40,
            "path": f"{label}.json",
            "sha256": "0" * 64,
            "array": "trades",
            "partition": "rolling",
            "row_semantics": "one_position_lifecycle",
            "cost": {
                "model": "SYNTHETIC_FIXED_COST",
                "source_ref": "1" * 40,
                "source_path": "synthetic_cost.json",
                "source_sha256": "2" * 64,
                "unit": "equal_notional_trade_bps",
                "net_formula": "gross_bps - multiplier * cost_bps",
            },
        } for label in labels],
        "candidate_slots": [{"label": "future", "status": "NOT_RUN"}],
    }


class ContributionReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("contribution_report", MODULE)
        cls.report = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = cls.report
        spec.loader.exec_module(cls.report)

    def analyze(self, rows, config=None):
        config = config or manifest(tuple(rows))
        payloads = {name: {"trades": values, "unresolved": []}
                    for name, values in rows.items()}
        return self.report.analyze_sources(config, payloads)

    @staticmethod
    def utc(result, label=None):
        scope = (result["standalone"][label] if label else
                 result["unconstrained_union_not_portfolio"])
        return scope["coverage"]["UTC"]

    def test_simultaneous_same_symbol_same_side_is_conflict_not_extra_opportunity(self):
        result = self.analyze({"A": [row("A")], "B": [row("B")]})
        self.assertEqual(self.utc(result)["entries"], 2)
        pairs = result["collisions"]["cross_strategy_same_symbol_holding_pairs"]
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]["side_relation"], "same")
        self.assertEqual(pairs[0]["overlap_minutes"], 60)
        self.assertEqual(result["opportunities"]["proxy_cluster_count"], 1)
        self.assertIsNone(result["opportunities"]["independent_count"])
        self.assertEqual(result["shared_account"]["status"], "UNKNOWN")
        self.assertIsNone(result["shared_account"]["net1x_trade_bps"])

    def test_opposite_direction_conflict_preserves_long_and_short(self):
        result = self.analyze({"A": [row("A", side=1)], "B": [row("B", side=-1)]})
        pairs = result["collisions"]["cross_strategy_same_symbol_holding_pairs"]
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]["side_relation"], "opposite")
        self.assertEqual(result["standalone"]["A"]["directions"]["long"]["entries"], 1)
        self.assertEqual(result["standalone"]["B"]["directions"]["short"]["entries"], 1)
        self.assertEqual(result["opportunities"]["proxy_cluster_count"], 2)

    def test_shared_opportunity_identity_deduplicates_renamed_strategies(self):
        result = self.analyze({
            "A": [row("A", opportunity_id="source-signal-17")],
            "B": [row("B", opportunity_id="source-signal-17")],
        })
        self.assertEqual(self.utc(result)["entries"], 2)
        self.assertEqual(result["opportunities"]["independent_count"], 1)
        self.assertEqual(result["opportunities"]["proxy_cluster_count"], 1)

    def test_partial_fill_exit_dca_handoff_do_not_multiply_position_or_profit(self):
        base = row("A", position_id="p1", opportunity_id="o1")
        events = [row("A", event_type=kind, parent_position_id="p1",
                      position_id=f"event-{kind}", gross=9999)
                  for kind in ("partial_fill", "partial_exit", "dca", "handoff")]
        result = self.analyze({"A": [base, *events]})
        self.assertEqual(self.utc(result)["entries"], 1)
        self.assertEqual(result["standalone"]["A"]["lifecycle"]["completed_in_window"], 1)
        self.assertEqual(result["opportunities"]["independent_count"], 1)
        economics = result["standalone"]["A"]["economics"]
        self.assertEqual(economics["net1x_trade_bps"], 10)
        self.assertEqual(economics["net2x_trade_bps"], 8)

    def test_identical_position_rows_collapse_but_conflicting_duplicate_fails(self):
        base = row("A", position_id="p1")
        result = self.analyze({"A": [base, copy.deepcopy(base)]})
        self.assertEqual(self.utc(result)["entries"], 1)
        changed = copy.deepcopy(base)
        changed["exit_ts_ms"] += 1000
        changed["outcome_available_ts_ms"] += 1000
        with self.assertRaises(ValueError):
            self.analyze({"A": [base, changed]})

    def test_pending_signal_is_not_an_entry_and_open_position_has_unknown_profit(self):
        pending = row("A", event_type="pending", entry_ts_ms=None,
                      exit=None, gross_bps=None, cost_bps=None, net_bps=None)
        entered = row("A", signal="2026-01-03T10:00:00Z", exit=None,
                      gross_bps=None, cost_bps=None, net_bps=None)
        result = self.analyze({"A": [pending, entered]})
        life = result["standalone"]["A"]["lifecycle"]
        self.assertEqual(life["entries_in_window"], 1)
        self.assertEqual(life["completed_in_window"], 0)
        self.assertEqual(life["pending_positions"], 1)
        self.assertEqual(life["open_at_end"], 1)
        self.assertIsNone(result["standalone"]["A"]["economics"]["net1x_trade_bps"])

    def test_all_calendar_days_remain_in_frequency_denominator(self):
        result = self.analyze({"A": [row("A")]})
        cov = self.utc(result)
        self.assertEqual(cov["calendar_days"], 4)
        self.assertEqual(cov["entries"], 1)
        self.assertEqual(cov["zero_days"], 3)
        self.assertEqual(cov["median_entries_per_day"], 0)
        self.assertEqual(cov["days_lt3"], 4)
        self.assertEqual(cov["days_ge3"], 0)
        self.assertEqual(cov["longest_zero_entry_run"]["days"], 2)
        self.assertEqual(cov["longest_zero_entry_run"]["start_date"], "2026-01-03")

    def test_empty_ledger_is_zero_coverage_not_a_missing_day(self):
        result = self.analyze({"A": []})
        cov = self.utc(result)
        self.assertEqual(cov["calendar_days"], 4)
        self.assertEqual(cov["zero_days"], 4)
        self.assertEqual(cov["longest_zero_entry_run"]["days"], 4)

    def test_half_open_entry_window_and_touching_holding_intervals(self):
        rows = [
            row("A", signal="2026-01-01T00:00:00Z", exit="2026-01-01T01:00:00Z"),
            row("A", signal="2026-01-01T01:00:00Z", exit="2026-01-01T02:00:00Z"),
            row("A", signal="2026-01-05T00:00:00Z", exit="2026-01-05T01:00:00Z"),
        ]
        result = self.analyze({"A": rows})
        self.assertEqual(self.utc(result)["entries"], 2)
        self.assertEqual(len(result["collisions"]["same_symbol_holding_pairs"]), 0)

    def test_late_outcome_does_not_extend_occupancy_or_leak_realized_profit(self):
        a = row("A", outcome_available_ts_ms=ms("2026-01-06T00:00:00Z"))
        b = row("B", signal="2026-01-02T13:00:00Z", exit="2026-01-02T14:00:00Z")
        result = self.analyze({"A": [a], "B": [b]})
        life = result["standalone"]["A"]["lifecycle"]
        self.assertEqual(life["completed_in_window"], 1)
        self.assertEqual(life["outcomes_known_in_window"], 0)
        self.assertIsNone(result["standalone"]["A"]["economics"]["net1x_trade_bps"])
        self.assertEqual(len(result["collisions"]["cross_strategy_same_symbol_holding_pairs"]), 0)

    def test_future_pnl_cannot_select_or_change_coverage_conflicts(self):
        rows = {"A": [row("A", gross=-100)], "B": [row("B", gross=100)]}
        before = self.analyze(rows)
        changed = copy.deepcopy(rows)
        for values in changed.values():
            values[0]["gross_bps"] *= -1000
            values[0]["net_bps"] = values[0]["gross_bps"] - values[0]["cost_bps"]
        after = self.analyze(changed)
        self.assertEqual(self.utc(before), self.utc(after))
        self.assertEqual(before["opportunities"], after["opportunities"])
        for key in ("same_symbol_holding_pairs", "cross_strategy_same_symbol_holding_pairs",
                    "same_signal_clusters", "same_timestamp_signal_groups"):
            self.assertEqual(before["collisions"][key], after["collisions"][key])
        self.assertEqual(before["shared_account"], after["shared_account"])

    def test_candidate_additional_dates_and_net_remain_descriptive_not_shared_profit(self):
        config = manifest(("A", "B", "C"), baseline=("A", "B"))
        rows = {
            "A": [row("A")],
            "B": [row("B", symbol="SOL-USDT", signal="2026-01-02T15:00:00Z",
                      exit="2026-01-02T16:00:00Z")],
            "C": [row("C", gross=102),
                  row("C", symbol="ETH-USDT", signal="2026-01-03T12:00:00Z",
                      exit="2026-01-03T13:00:00Z", gross=-3)],
        }
        result = self.analyze(rows, config)
        contribution = result["candidate_contribution"]["C"]
        self.assertEqual(contribution["date_coverage"]["UTC"]["additional_entry_dates"],
                         ["2026-01-03"])
        self.assertEqual(contribution["same_symbol_overlap_pairs"], 1)
        self.assertEqual(contribution["nonoverlap_saved_entries"], 1)
        self.assertEqual(contribution["raw_additive_economics"]["net1x_trade_bps"], 95)
        self.assertEqual(contribution["nonoverlap_saved_entries_economics"]["net1x_trade_bps"], -5)
        self.assertIsNone(contribution["shared_incremental_net1x_trade_bps"])
        self.assertEqual(result["candidate_slots"], [{"label": "future", "status": "NOT_RUN"}])

    def test_partition_filter_excludes_validation_even_when_dates_match(self):
        result = self.analyze({"A": [row("A"), row("A", partition="validation",
                                                   signal="2026-01-03T12:00:00Z",
                                                   exit="2026-01-03T13:00:00Z")]})
        self.assertEqual(self.utc(result)["entries"], 1)

    def test_missing_partition_cannot_silently_become_empty_coverage(self):
        value = row("A")
        value.pop("partition")
        with self.assertRaises(ValueError):
            self.analyze({"A": [value]})

    def test_empty_opportunity_id_cannot_certify_independence(self):
        with self.assertRaises(ValueError):
            self.analyze({"A": [row("A", opportunity_id="")]})

    def test_wrong_identity_or_invalid_timestamp_fails(self):
        with self.assertRaises(ValueError):
            self.analyze({"A": [row("WRONG")]})
        with self.assertRaises(ValueError):
            self.analyze({"A": [row("A", signal_ts_ms=None)]})
        with self.assertRaises(ValueError):
            self.analyze({"A": [row("A", exit="2026-01-02T11:00:00Z")]})

    def test_management_identity_is_pinned_instead_of_parent_display_name(self):
        config = manifest(("A",))
        config["sources"][0]["identity_field"] = "management_comparison_identity"
        result = self.analyze({"A": [row("parent", management_comparison_identity="A")]}, config)
        self.assertEqual(self.utc(result)["entries"], 1)
        with self.assertRaises(ValueError):
            self.analyze({"A": [row("A", management_comparison_identity="WRONG")]}, config)

    def test_outcome_before_exit_or_signal_after_entry_fails(self):
        with self.assertRaises(ValueError):
            self.analyze({"A": [row("A", outcome_available_ts_ms=ms("2026-01-02T11:00:00Z"))]})
        with self.assertRaises(ValueError):
            self.analyze({"A": [row("A", entry="2026-01-02T11:00:00Z")]})

    def test_cost_integrity_missing_is_unknown_nonfinite_or_negative_fails(self):
        value = row("A")
        value.pop("cost_bps")
        result = self.analyze({"A": [value]})
        self.assertIsNone(result["standalone"]["A"]["economics"]["net1x_trade_bps"])
        for invalid in (-1, float("nan"), float("inf")):
            with self.subTest(cost=invalid), self.assertRaises(ValueError):
                self.analyze({"A": [row("A", cost_bps=invalid)]})

    def test_explicit_net_must_agree_with_bound_cost_formula(self):
        with self.assertRaises(ValueError):
            self.analyze({"A": [row("A", net_bps=100000)]})

    def test_berlin_includes_both_partial_edge_dates(self):
        result = self.analyze({"A": [row("A")]})
        cov = result["unconstrained_union_not_portfolio"]["coverage"]["Europe/Berlin"]
        self.assertEqual(cov["calendar_days"], 5)
        self.assertEqual(cov["entries"], 1)
        self.assertEqual(cov["zero_days"], 4)
        self.assertEqual([(x["date"], x["covered_hours"]) for x in cov["partial_dates"]],
                         [("2026-01-01", 23), ("2026-01-05", 1)])

    def test_dst_spring_window_is_one_berlin_calendar_day(self):
        config = manifest(("A",), start="2026-03-28T23:00:00Z", end="2026-03-29T22:00:00Z")
        rows = [row("A", signal="2026-03-29T00:30:00Z", exit="2026-03-29T00:45:00Z"),
                row("A", signal="2026-03-29T01:30:00Z", exit="2026-03-29T01:45:00Z")]
        result = self.analyze({"A": rows}, config)
        cov = result["unconstrained_union_not_portfolio"]["coverage"]["Europe/Berlin"]
        self.assertEqual(cov["calendar_days"], 1)
        self.assertEqual(cov["entry_dates"], ["2026-03-29"])
        self.assertEqual(cov["entries"], 2)
        self.assertEqual([(x["date"], x["covered_hours"], x["nominal_day_hours"])
                          for x in cov["dst_days"]], [("2026-03-29", 23, 23)])
        self.assertEqual(cov["partial_dates"], [])
        self.assertEqual(len(result["collisions"]["same_symbol_holding_pairs"]), 0)

    def test_dst_fall_repeated_local_hour_is_not_same_instant(self):
        config = manifest(("A",), start="2026-10-24T22:00:00Z", end="2026-10-25T23:00:00Z")
        rows = [row("A", signal="2026-10-25T00:30:00Z", exit="2026-10-25T00:45:00Z"),
                row("A", signal="2026-10-25T01:30:00Z", exit="2026-10-25T01:45:00Z")]
        result = self.analyze({"A": rows}, config)
        cov = result["unconstrained_union_not_portfolio"]["coverage"]["Europe/Berlin"]
        self.assertEqual(cov["calendar_days"], 1)
        self.assertEqual(cov["entry_dates"], ["2026-10-25"])
        self.assertEqual(cov["entries"], 2)
        self.assertEqual([(x["date"], x["covered_hours"], x["nominal_day_hours"])
                          for x in cov["dst_days"]], [("2026-10-25", 25, 25)])
        self.assertEqual(cov["partial_dates"], [])
        self.assertEqual(result["opportunities"]["proxy_cluster_count"], 2)
        self.assertEqual(len(result["collisions"]["same_timestamp_signal_groups"]), 0)

    def test_ledger_sha_is_checked_before_reporting(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = manifest(("A",))
            raw = json.dumps({"trades": [row("A")], "unresolved": []}).encode()
            (root / "A.json").write_bytes(raw)
            config["sources"][0]["sha256"] = hashlib.sha256(raw).hexdigest()
            cost = b'{"model":"SYNTHETIC_FIXED_COST"}'
            (root / "synthetic_cost.json").write_bytes(cost)
            config["sources"][0]["cost"]["source_sha256"] = hashlib.sha256(cost).hexdigest()
            self.report.run(config, root, root / "out")
            self.assertTrue((root / "out" / "CONTRIBUTION.json").exists())
            self.assertTrue((root / "out" / "DAILY_COVERAGE.csv").exists())
            (root / "A.json").write_bytes(raw + b" ")
            with self.assertRaises(ValueError):
                self.report.run(config, root, root / "out-tampered")
            (root / "A.json").write_bytes(raw)
            (root / "synthetic_cost.json").write_bytes(cost + b" ")
            with self.assertRaises(ValueError):
                self.report.run(config, root, root / "out-cost-tampered")


if __name__ == "__main__":
    unittest.main()

