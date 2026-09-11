"""Synthetic tests only: no market files, API, or policy economic execution."""
from copy import deepcopy
import unittest

from backend.research.rebuild import trendrider_common_genes_v1 as genes

HOUR = 3_600_000
IDS = list(genes.GENES)


def snapshot(i=64, *, hour=16, p=False, b=True, gap=2.0, previous_gap=1.0,
             chase=1.0, previous_chase=1.0, atr=2.0, previous_atr=1.0):
    stamp = ((i // 24) * 24 + hour) * HOUR
    result = {"symbol": "SYNTH", "side": "long", "signal_index": i,
              "signal_ts": stamp, "b_actionable": b, "p_actionable": p,
              "current_features": {"atr": atr, "close": 100.0,
                  "values": {"st_gap_atr": gap, "chase_atr": chase}},
              "prior_features": {"atr": previous_atr, "close": 100.0,
                  "values": {"st_gap_atr": previous_gap, "chase_atr": previous_chase}},
              "lanes": {"B_COMMON": {"intent_sha": genes.digest([i, "intent"]),
                  "intent": {"regime": "SYNTHETIC_ONLY"}}}}
    result["snapshot_sha"] = genes.digest(result)
    return result


def campaign(s, net, *, partition="DEV_A", status="COMPLETED"):
    stamp = s["signal_ts"]
    return {"symbol": s["symbol"], "side": s["side"], "signal_ts": stamp,
            "signal_index": s["signal_index"], "partition": partition,
            "selected_lane": "B_COMMON", "snapshot_sha": s["snapshot_sha"],
            "intent_sha": s["lanes"]["B_COMMON"]["intent_sha"],
            "status": status, "exit_available_ts": stamp + 2 * HOUR,
            "net_bps": net if status == "COMPLETED" else None,
            "terminal_net_bps": net, "cost2_net_bps": net - 1 if status == "COMPLETED" else None,
            "cost2_terminal_net_bps": net - 1, "hold_hours": 1,
            "intent_exposure": {"notional_fraction_of_equity": 0.15},
            "mark_path": [{"ts": stamp + 2 * HOUR, "net_bps": net, "cost2_net_bps": net - 1}]}


def saved(signals, campaigns, *, partition="DEV_A", occupied=()):
    actual = {(c["symbol"], c["signal_ts"], c["side"]): c for c in campaigns}
    events = []
    for s in signals:
        k = (s["symbol"], s["signal_ts"], s["side"])
        events.append({"symbol": s["symbol"], "signal_ts": s["signal_ts"], "side": s["side"],
                       "status": "OWNERSHIP_REJECTED" if s["signal_index"] in occupied else actual.get(k, {}).get("status", "NO_SIGNAL")})
    return {"partition": partition, "start_index": 64, "end_exclusive": 200,
            "campaigns": campaigns, "events": events}


def passing_report(gene_id, *, partition="DEV_A", expectancy=10, pf=2, wr=.7,
                   dd=10, tail=-10, retention=.8, top10=.8, concentration=.4):
    return {"gene_id": gene_id, "partition": partition, "integrity": "PASS",
            "ordinary_winner_retention": retention, "top10_winner_retention": top10,
            "metrics": {"expectancy_bps": expectancy, "PF": pf, "PF_infinite": False,
                "payoff": 2, "payoff_infinite": False, "closed_cost2_net_bps": 20,
                "WR": wr, "marked_DD_bps": dd, "closed_DD_bps": dd,
                "loss_tail_10pct_mean_bps": tail,
                "top1_positive_contribution_fraction": concentration},
            "receipt_sha": genes.digest([gene_id, partition])}


class GeneBoundaryTests(unittest.TestCase):
    def test_native_session_timestamp_and_us_boundary(self):
        s = snapshot(hour=15, chase=2, previous_chase=1)
        s["decision_ts"] = s["signal_ts"] + HOUR
        self.assertTrue(genes.gene_accepts(s, IDS[1]))
        self.assertFalse(genes.gene_accepts(snapshot(hour=16, chase=2), IDS[1]))
        self.assertTrue(genes.gene_accepts(snapshot(hour=23, chase=1), IDS[1]))

    def test_missing_previous_is_not_cooling_but_non_us_native_or_survives(self):
        s = snapshot()
        s.pop("prior_features")
        self.assertFalse(genes.gene_accepts(s, IDS[1]))
        self.assertFalse(genes.gene_accepts(s, IDS[3]))
        s["signal_ts"] = 15 * HOUR
        self.assertTrue(genes.gene_accepts(s, IDS[1]))

    def test_exact_equality_directions(self):
        s = snapshot(gap=1, previous_gap=1, chase=1, atr=1, previous_atr=1)
        self.assertFalse(genes.gene_accepts(s, IDS[2]))
        self.assertTrue(genes.gene_accepts(s, IDS[3]))
        self.assertFalse(genes.gene_accepts(s, IDS[4]))
        self.assertTrue(genes.gene_accepts(s, IDS[5]))

    def test_atr_is_normalized_by_close(self):
        s = snapshot(atr=2, previous_atr=1)
        s["current_features"]["close"] = 300
        self.assertFalse(genes.gene_accepts(s, IDS[4]))
        s["current_features"]["close"] = 0
        self.assertFalse(genes.gene_accepts(s, IDS[4]))

    def test_nonfinite_and_boolean_features_fail_closed(self):
        for invalid in (None, True, float("nan"), float("inf")):
            s = snapshot()
            s["current_features"]["values"]["chase_atr"] = invalid
            self.assertFalse(genes.gene_accepts(s, IDS[3]))

    def test_outcomes_do_not_change_admission(self):
        s = snapshot()
        expected = [genes.gene_accepts(s, g) for g in IDS]
        s.update(net_bps=-1e99, winner=False, future_close=1e99, exit_reason="SL")
        self.assertEqual(expected, [genes.gene_accepts(s, g) for g in IDS])

    def test_orthogonality_is_conservative_and_and_only(self):
        self.assertFalse(genes.orthogonal(IDS[1], IDS[3]))
        for g in (IDS[1], IDS[2], IDS[3]):
            self.assertFalse(genes.orthogonal(IDS[5], g))
        for g in (IDS[1], IDS[2], IDS[3], IDS[5]):
            self.assertTrue(genes.orthogonal(IDS[4], g))
        self.assertFalse(genes.orthogonal(IDS[0], IDS[4]))
        s = snapshot(chase=2, previous_chase=1)
        self.assertIsNone(genes.union_admission(s, [IDS[3], IDS[4]]))
        s["p_actionable"] = True
        self.assertEqual("P_COMMON", genes.union_admission(s, [IDS[3], IDS[4]]))
        with self.assertRaisesRegex(ValueError, "NOT_ORTHOGONAL"):
            genes.union_admission(s, [IDS[1], IDS[3]])

    def test_unknown_gene_and_empty_union_rejected(self):
        with self.assertRaises(ValueError):
            genes.gene_accepts(snapshot(), "PREENTRY_3BAR_DIRECTIONAL_PERSISTENCE_TRUE")
        with self.assertRaises(ValueError):
            genes.union_admission(snapshot(), [])


class SavedScreenTests(unittest.TestCase):
    def test_screen_uses_raw_b_only_not_trade_set_difference_or_occupancy(self):
        a, core, blocked = snapshot(i=64), snapshot(i=65, hour=17, p=True), snapshot(i=66, hour=18)
        rows = [campaign(a, 10), campaign(core, 999)]
        report = genes.screen(saved([a, core, blocked], rows, occupied=(66,)), [a, core, blocked], "DEV_A", IDS[3])
        self.assertEqual(2, report["eligible_B_only_signals"])
        self.assertEqual(2, report["admitted_B_only_signals"])
        self.assertEqual(1, report["admitted_occupied_signals"])
        self.assertEqual(1, report["admitted_executed_T"])
        self.assertEqual(10, report["metrics"]["closed_net_bps"])
        self.assertEqual(1, report["P_overlap_signals"])
        self.assertEqual(0, report["new_or_displaced_trades"])

    def test_transition_gene_cannot_add_b_only_even_profitable(self):
        s = snapshot()
        r = genes.screen(saved([s], [campaign(s, 100)]), [s], "DEV_A", IDS[0])
        self.assertEqual(0, r["admitted_B_only_signals"])
        self.assertFalse(r["pass"])
        self.assertEqual("NO_ADDITIONAL_OPPORTUNITIES_BY_DEFINITION", r["state"])

    def test_empty_winner_denominator_never_becomes_full_retention(self):
        s = snapshot()
        for rows in ([], [campaign(s, -10)]):
            r = genes.screen(saved([s], rows), [s], "DEV_A", IDS[3])
            self.assertIsNone(r["ordinary_winner_retention"])
            self.assertIsNone(r["top10_winner_retention"])
            self.assertFalse(r["pass"])

    def test_positive_outcome_does_not_hide_removed_top_winner(self):
        signals = [snapshot(i=64 + i, hour=i, chase=2 if i == 0 else 1) for i in range(12)]
        rows = [campaign(s, 100 if i == 0 else 10) for i, s in enumerate(signals)]
        r = genes.screen(saved(signals, rows), signals, "DEV_A", IDS[3])
        self.assertEqual(11, r["admitted_executed_T"])
        self.assertAlmostEqual(110 / 210, r["ordinary_winner_retention"])
        self.assertAlmostEqual(10 / 110, r["top10_winner_retention"])
        self.assertEqual(100, r["clipped_winner_bps"])
        self.assertFalse(r["pass"])

    def test_open_censor_separate_from_completed_expectancy(self):
        a, b = snapshot(i=64), snapshot(i=65, hour=17)
        rows = [campaign(a, 20), campaign(b, -100, status="OPEN_CENSORED")]
        r = genes.screen(saved([a, b], rows), [a, b], "DEV_A", IDS[3])
        self.assertEqual(1, r["metrics"]["completed_T"])
        self.assertEqual(1, r["metrics"]["open_censored_T"])
        self.assertEqual(20, r["metrics"]["expectancy_bps"])
        self.assertEqual(-80, r["metrics"]["terminal_net_bps"])
        self.assertEqual(100, r["metrics"]["marked_DD_bps"])

    def test_marked_curve_keeps_closed_cash_when_next_trade_starts(self):
        a, b = snapshot(i=64), snapshot(i=65, hour=17)
        rows = [campaign(a, 20), campaign(b, -7)]
        r = genes.screen(saved([a, b], rows), [a, b], "DEV_A", IDS[3])
        self.assertEqual(7, r["metrics"]["marked_DD_bps"])
        self.assertEqual(13, r["metrics"]["terminal_net_bps"])

    def test_duplicate_and_hash_drift_fail_integrity(self):
        a = snapshot()
        c = campaign(a, 10)
        r = genes.screen(saved([a], [c, c]), [a], "DEV_A", IDS[3])
        self.assertEqual("FAIL", r["integrity"])
        self.assertFalse(r["pass"])
        c["intent_sha"] = "bad"
        r = genes.screen(saved([a], [c]), [a], "DEV_A", IDS[3])
        self.assertIn("CAMPAIGN_HASH_LINEAGE", r["integrity_errors"])

    def test_partition_bound_excludes_confirmation_signals(self):
        a, future = snapshot(), snapshot(i=200, hour=3)
        r = genes.screen(saved([a], [campaign(a, 10)]), [a, future], "DEV_A", IDS[3])
        self.assertEqual(1, r["eligible_B_only_signals"])
        with self.assertRaises(ValueError):
            genes.screen(saved([a], []), [a], "DEV_B", IDS[3])

    def test_nonfinite_outcome_cannot_enter_json_receipt(self):
        s = snapshot()
        with self.assertRaises(ValueError):
            genes.screen(saved([s], [campaign(s, float("nan"))]), [s], "DEV_A", IDS[3])


class SelectionTests(unittest.TestCase):
    def test_exact_gate_boundaries(self):
        r = passing_report(IDS[2], retention=.6, top10=.6, pf=1)
        r["metrics"]["payoff"] = 1
        self.assertTrue(all(genes.hard_gate(r).values()))
        r["metrics"]["closed_cost2_net_bps"] = 0
        self.assertFalse(all(genes.hard_gate(r).values()))

    def test_pareto_removes_dominated_before_simplicity_tie_break(self):
        strong = passing_report(IDS[1], expectancy=20)
        weak = passing_report(IDS[2], expectancy=10)
        self.assertEqual([IDS[1]], genes.select_a([weak, strong])["ordered_survivors"])

    def test_frontier_tie_break_is_axes_then_concentration_then_dd_then_id(self):
        a = passing_report(IDS[1], expectancy=30, concentration=.2)
        b = passing_report(IDS[2], expectancy=20, concentration=.3, dd=5)
        c = passing_report(IDS[4], expectancy=10, concentration=.1)
        result = genes.select_a([a, b, c])
        self.assertEqual([IDS[4], IDS[2]], result["ordered_survivors"])
        self.assertTrue(result["U2_orthogonal"])

    def test_confirm_b_preserves_frozen_a_rank_even_if_b_reverses_performance(self):
        selection = {"ordered_survivors": [IDS[2], IDS[4]], "receipt_sha": "frozen"}
        reports = [passing_report(IDS[4], partition="DEV_B", expectancy=1000),
                   passing_report(IDS[2], partition="DEV_B", expectancy=1)]
        result = genes.confirm_b(selection, reports)
        self.assertEqual([IDS[2], IDS[4]], result["confirmed_A_order"])
        self.assertEqual(IDS[2], result["best_gene"])
        self.assertFalse(result["B_rerank"])

    def test_confirmation_drops_failure_without_rule_rescue(self):
        selection = {"ordered_survivors": [IDS[2], IDS[4]]}
        reports = [passing_report(IDS[2], partition="DEV_B", top10=.59),
                   passing_report(IDS[4], partition="DEV_B")]
        self.assertEqual([IDS[4]], genes.confirm_b(selection, reports)["confirmed_A_order"])
        with self.assertRaises(ValueError):
            genes.confirm_b(selection, reports + [passing_report(IDS[3], partition="DEV_B")])

    def test_selection_cannot_consume_b_or_more_than_six_or_duplicates(self):
        with self.assertRaises(ValueError):
            genes.select_a([passing_report(IDS[2], partition="DEV_B")])
        with self.assertRaises(ValueError):
            genes.select_a([passing_report(IDS[2])] * 2)

    def test_recipe_has_no_tuned_numeric_feature_thresholds(self):
        recipe = genes.recipe()
        self.assertEqual(6, len(recipe["genes"]))
        self.assertEqual("AND_ONLY; DISJOINT_INPUT_AXES; NO_G1_EMPTY_GENE", recipe["u2_semantics"])
        self.assertIn("PREENTRY_3BAR_DIRECTIONAL_PERSISTENCE_TRUE", recipe["forbidden"])


if __name__ == "__main__":
    unittest.main()
