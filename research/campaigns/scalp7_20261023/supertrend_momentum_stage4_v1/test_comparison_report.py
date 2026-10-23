"""Synthetic post-run rows only; no strategy replay or real Stage3 calculation."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import comparison_report as report


def fixture(parent_gross=(100., 0.), child_gross=(120., 10.)):
    manifest = {"parent_identity": "synthetic_parent", "child_identity": "synthetic_h12_child",
                "input_sha256": "a" * 64, "bounds": {"start_ms": 0, "end_ms": 86_400_000},
                "symbols": list(report.FROZEN_SYMBOLS),
                "six_symbol_cohort": list(report.OBSERVED_SIX),
                "normalization": report.NORMALIZATION, "comparison_protocol": report.PROTOCOL,
                "model_cost_bps": {"1x": 20., "2x": 40.}, "large_winner_reference_ids": ["p0"]}
    parent, child = [], []
    for i, gross in enumerate(parent_gross):
        parent.append({"trade_id": f"p{i}", "signal_identity": manifest["parent_identity"],
                       "original_signal_identity": manifest["parent_identity"], "symbol": manifest["symbols"][i],
                       "signal_ts_ms": 100 + i, "entry_ts_ms": 200 + i,
                       "exit_ts_ms": 300 + 10 * i, "outcome_available_ts_ms": 300 + 10 * i,
                       "gross_trade_bps": gross, "normalization": report.NORMALIZATION})
    for i, gross in enumerate(child_gross):
        child.append({**deepcopy(parent[i]), "trade_id": f"c{i}", "signal_identity": manifest["child_identity"],
                      "gross_trade_bps": gross, "parent_trade_id": f"p{i}"})
    return parent, child, manifest


def compare(parent, child, manifest, **unfinished):
    counts = {k: [] for k in ("unresolved_parent", "unresolved_child", "censored_parent", "censored_child")}
    counts.update(unfinished)
    return report.compare(parent, child, manifest, **counts)


class ComparisonTests(unittest.TestCase):
    def test_fixed_cost_metrics_model_label_and_no_nav_invention(self):
        result = compare(*fixture())
        self.assertEqual(result["metrics"]["parent"]["1x"]["Net_bps"], 60.)
        self.assertEqual(result["metrics"]["parent"]["2x"]["Net_bps"], 20.)
        self.assertAlmostEqual(result["metrics"]["child"]["2x"]["PF"], 80 / 30)
        self.assertEqual(result["classification"], "A_REVIEW_REQUIRED")
        self.assertIn("MODELED_FIXED_COST", result["execution_model"])
        for key in ("actual_fee_bps", "actual_funding_bps", "account_NAV_return", "account_NAV_DD", "MTM_DD"):
            self.assertIsNone(result[key])
        self.assertFalse(result["promotion"])

    def test_improved_net_with_worse_pf_and_dd_stays_review_not_hidden(self):
        result = compare(*fixture(child_gross=(200., -90.)))
        self.assertGreater(result["metrics"]["delta"]["2x"]["Net_bps"], 0)
        self.assertLess(result["metrics"]["delta"]["2x"]["PF"], 0)
        self.assertGreater(result["metrics"]["delta"]["2x"]["realized_exit_cohort_trade_bps_DD"], 0)
        self.assertEqual(result["classification"], "A_REVIEW_REQUIRED")

    def test_same_exit_timestamp_groups_dd_and_cohort_streak(self):
        parent, child, manifest = fixture((80., -20., -10., 100.), (90., -10., -5., 110.))
        parent[1]["exit_ts_ms"] = parent[1]["outcome_available_ts_ms"] = parent[0]["exit_ts_ms"]
        result = compare(parent, child, manifest)
        metrics = result["metrics"]["parent"]["1x"]
        self.assertEqual(metrics["realized_exit_cohort_trade_bps_DD"], 30.)
        self.assertEqual(metrics["row_streak_order_dependent"]["max_consecutive_negative"], 2)
        self.assertEqual(metrics["exit_cohort_streak"]["max_consecutive_negative"], 1)
        self.assertIn("tie-order dependent", result["streak_note"])

    def test_simultaneous_negative_cohort_report_is_explicit(self):
        parent, child, manifest = fixture((30., -30.), (40., -20.))
        parent[1]["exit_ts_ms"] = parent[1]["outcome_available_ts_ms"] = parent[0]["exit_ts_ms"]
        rows = compare(parent, child, manifest)["metrics"]["parent"]["1x"]["simultaneous_negative_cohorts"]
        self.assertEqual(rows, [{"exit_ts_ms": 300, "trade_count": 2, "negative_trade_count": 1, "cohort_net_bps": -40.}])

    def test_cost2_nonimprovement_rejected_and_unfinished_holds(self):
        parent, child, manifest = fixture(child_gross=(100., 0.))
        self.assertEqual(compare(parent, child, manifest)["classification"], "REJECT_NO_COST2_IMPROVEMENT")
        result = compare(parent, child, manifest, unresolved_child=[{"symbol": "BTC-USDT"}], censored_parent=[{"symbol": "LINK-USDT"}])
        self.assertEqual(result["classification"], "HOLD_INCOMPLETE")
        self.assertEqual(result["unfinished_counts"]["child_unresolved"], 1)
        self.assertEqual(result["unfinished_counts"]["parent_censored"], 1)
        self.assertEqual(result["unfinished_position_clock_validation"]["child"], "UNKNOWN_MISSING_ENTRY_CLOCK")

    def test_large_winner_damage_visible_even_if_total_net_improves(self):
        result = compare(*fixture(child_gross=(10., 300.)))
        group = result["winner_retention_post_run_only"]["preregistered_large_winners"]
        row = group["paired_values"][0]
        self.assertEqual(row["parent_trade_id"], "p0")
        self.assertEqual(row["child_net_bps"]["1x"], -10.)
        self.assertFalse(row["child_positive"]["1x"])
        self.assertEqual(group["paired_count"], 1)
        self.assertEqual(group["retained_positive_count"], {"1x": 0, "2x": 0})
        self.assertEqual(group["parent_net_sum"], {"1x": 80., "2x": 60.})
        self.assertEqual(group["child_paired_net_sum"], {"1x": -10., "2x": -30.})
        self.assertNotIn("retained_count", group)
        self.assertEqual(result["classification"], "A_REVIEW_REQUIRED")

    def test_new_and_missing_entries_reconcile_without_filtering_seventh_symbol(self):
        parent, child, manifest = fixture((100., 50.), (120., 60.))
        child.pop(1)
        child.append({**deepcopy(child[0]), "trade_id": "new", "symbol": "LINK-USDT", "signal_ts_ms": 150,
                      "gross_trade_bps": 90., "parent_trade_id": None})
        result = compare(parent, child, manifest)
        self.assertEqual(result["new_child_trade_ids"], ["new"])
        self.assertEqual(result["missing_parent_trade_ids"], ["p1"])
        self.assertTrue(result["full_chronology_attribution"]["2x"]["reconciled"])
        self.assertEqual(result["metrics"]["child"]["2x"]["T"], 2)
        self.assertEqual(result["six_symbol_post_run_diagnostic"]["child"]["2x"]["T"], 1)
        self.assertEqual(result["winner_retention_post_run_only"]["ordinary_parent_winners_1x"]["missing_parent_ids"], ["p1"])
        self.assertEqual(result["winner_retention_post_run_only"]["ordinary_parent_winners_1x"]["child_paired_net_sum"], {"1x": 0., "2x": 0.})
        self.assertFalse(result["universe_contract"]["runtime_symbol_filter_applied"])

    def test_bad_pins_bounds_costs_references_and_links_fail(self):
        cases = (
            (lambda p, c, m: m.update(input_sha256="bad"), "SHA256"),
            (lambda p, c, m: m["bounds"].update(end_ms=0), "BOUNDARY"),
            (lambda p, c, m: m["model_cost_bps"].update({"2x": 21.}), "COST_DRIFT"),
            (lambda p, c, m: m.update(large_winner_reference_ids=["not_parent"]), "REFERENCE"),
            (lambda p, c, m: c[0].update(symbol="LINK-USDT"), "PARENT_LINK"),
            (lambda p, c, m: c[0].update(parent_trade_id=None), "REQUIRES_LINK"),
            (lambda p, c, m: c[0].update(original_signal_identity="other"), "IDENTITY"),
            (lambda p, c, m: c[0].update(exit_ts_ms=86_400_000, outcome_available_ts_ms=86_400_000), "BOUNDARY"),
            (lambda p, c, m: m["bounds"].update(start_ms=101), "BOUNDARY"),
            (lambda p, c, m: p[0].update(exit_ts_ms=p[0]["entry_ts_ms"]), "BOUNDARY"),
        )
        for mutate, error in cases:
            p, c, m = fixture()
            mutate(p, c, m)
            with self.subTest(error=error), self.assertRaisesRegex(ValueError, error):
                compare(p, c, m)

    def test_same_count_wrong_symbol_populations_are_rejected(self):
        for field, replacement, expected in (
            ("symbols", "XRP-USDT", "SEVEN_SYMBOL"),
            ("six_symbol_cohort", "LINK-USDT", "SIX_SYMBOL"),
        ):
            parent, child, manifest = fixture()
            manifest[field][0] = replacement
            self.assertEqual(len(manifest[field]), 7 if field == "symbols" else 6)
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, expected):
                compare(parent, child, manifest)

    def test_changed_entry_early_exit_and_closed_overlap_are_rejected(self):
        cases = (
            (lambda p, c, m: c[0].update(entry_ts_ms=201), "EXIT_ONLY_AXIS"),
            (lambda p, c, m: c[0].update(exit_ts_ms=299), "EXIT_ONLY_AXIS"),
            (lambda p, c, m: p[1].update(symbol=p[0]["symbol"]), "CLOSED_POSITION_OVERLAP"),
            (lambda p, c, m: c.append({**deepcopy(c[0]), "trade_id": "new_overlap", "signal_ts_ms": 150,
                                      "entry_ts_ms": 250, "exit_ts_ms": 400, "outcome_available_ts_ms": 400,
                                      "parent_trade_id": None}), "CLOSED_POSITION_OVERLAP"),
        )
        for mutate, error in cases:
            parent, child, manifest = fixture()
            mutate(parent, child, manifest)
            with self.subTest(error=error), self.assertRaisesRegex(ValueError, error):
                compare(parent, child, manifest)

    def test_known_unfinished_intervals_cannot_overlap_closed_or_each_other(self):
        parent, child, manifest = fixture()
        symbol = parent[0]["symbol"]
        with self.assertRaisesRegex(ValueError, "CLOSED_UNFINISHED_POSITION_OVERLAP"):
            compare(parent, child, manifest, unresolved_child=[{"symbol": symbol, "entry_ts_ms": 250}])
        with self.assertRaisesRegex(ValueError, "UNFINISHED_POSITION_OVERLAP"):
            compare(parent, child, manifest,
                    unresolved_child=[{"symbol": "LINK-USDT", "entry_ts_ms": 400}],
                    censored_child=[{"symbol": "LINK-USDT", "entry_ts_ms": 500}])
        result = compare(parent, child, manifest, unresolved_child=[{"symbol": symbol, "entry_ts_ms": 400}])
        self.assertEqual(result["classification"], "HOLD_INCOMPLETE")
        self.assertEqual(result["unfinished_position_clock_validation"]["child"], "KNOWN_INTERVALS_CHECKED")

    def test_post_run_comparison_does_not_mutate_inputs_and_empty_pf_is_null(self):
        inputs = fixture()
        saved = deepcopy(inputs)
        result = compare(*inputs)
        self.assertEqual(inputs, saved)
        result["frozen_manifest"]["symbols"].clear()
        self.assertEqual(inputs, saved)
        manifest = deepcopy(saved[2])
        manifest["large_winner_reference_ids"] = []
        empty = compare([], [], manifest)
        self.assertIsNone(empty["metrics"]["parent"]["2x"]["PF"])
        self.assertEqual(empty["universe_contract"]["parent_traded_symbols"], [])
        self.assertEqual(len(empty["universe_contract"]["allowed_symbols"]), 7)


if __name__ == "__main__":
    unittest.main(verbosity=2)
