"""Synthetic-only regressions for the cumulative entry adapter."""
from copy import deepcopy
import math
import unittest

from backend.research.rebuild import keltner_cumulative_entry_adapter_v1 as n
from backend.research.rebuild import parallel_exit_keltner_v1 as d
from backend.research.rebuild.test_parallel_exit_keltner_v1 import bars, bundle


def replay(rows, signals, **kwargs):
    return n.replay(rows, signals, eval_start_ms=0,
                    eval_end_ms=rows[-1]["bar_close_ts"], **kwargs)


class KeltnerCumulativeEntryTests(unittest.TestCase):
    def test_runner_charge_preserves_D_common_costs_and_separates_new_origin(self):
        from backend.research.rebuild import keltner_cumulative_entry_v1 as runner
        from backend.research.rebuild.test_break_channel_source_v1 import COSTS, policy
        rows = bars(43); rows[0]["close"] = 99.0
        b = bundle(rows, [0, 3, 16, 35])
        b["ema20"][5] = 100.0; b["ema20"][-1] = 100.0
        p = policy(); p["development_interval_ms"] = [0, 43 * d.BAR]
        data, bundles = {"TEST": rows}, {"TEST": b}
        prior = runner.previous.replay_stage("KELTNER", bundles, data, COSTS, p,
                                              0, 43 * d.BAR, "FULL")
        disabled = runner.replay(data, bundles, COSTS, p, 0, 43 * d.BAR,
                                 "DISABLED", enabled=False)
        runner.assert_D_parity(disabled, prior)
        common = runner.replay(data, bundles, COSTS, p, 0, 43 * d.BAR,
                               "N_COMMON_D", common={"TEST": [0, 16, 35]})
        full = runner.replay(data, bundles, COSTS, p, 0, 43 * d.BAR, "N_FULL")
        self.assertEqual([t["signal_index"] for t in common["trades"]], [16])
        self.assertEqual([t["signal_index"] for t in full["trades"]], [3, 16])
        baseline = {t["origin_key"]: t for t in prior["trades"]}
        retained = common["trades"][0]
        for field in ("entry_ts", "entry_price", "exit_ts", "exit_price", "gross_bps",
                      "net_bps", "cost_bps", "funding_bps", "cost2x_net_bps", "hold_ms"):
            self.assertEqual(retained[field], baseline[retained["origin_key"]][field])
        self.assertEqual(retained["candidate_id"], n.RULE_ID)
        self.assertEqual(retained["evidence_type"], "REUSED_DEV_ENTRY_REPAIR")
        raw_new = d.replay(rows, b, eval_start_ms=0, eval_end_ms=43 * d.BAR,
                           fixed_signal_indices=[3])
        charged_new = runner.previous.charge_result(raw_new, "TEST", d.LANE, "CHECK",
                                                     p, COSTS, rows)["trades"][0]
        self.assertEqual(full["trades"][0]["origin_key"], charged_new["origin_key"])
        for field in ("net_bps", "cost_bps", "funding_bps", "hold_ms", "cost2x_net_bps"):
            self.assertEqual(full["trades"][0][field], charged_new[field])
        opened = common["open_observations"][0]
        self.assertEqual(opened["origin_key"], prior["open_observations"][0]["origin_key"])
        for field in ("hypothetical_liquidation_net_mark_bps", "modeled_funding_accrued_bps",
                      "hypothetical_liquidation_cost_bps"):
            self.assertEqual(opened[field], prior["open_observations"][0][field])
        self.assertFalse(opened["actual_exit"])
        self.assertEqual(opened["pending_exit_signal_ts"], 43 * d.BAR)

    def test_disabled_result_exactly_equals_D_including_events_and_trace(self):
        rows = bars(43); b = bundle(rows, [0, 3, 16, 35])
        rows[0]["close"] = 99.0
        b["ema20"][1] = 100.0
        b["ema20"][-1] = 100.0
        for common in (None, [0, 16, 35]):
            expected = d.replay(rows, b, eval_start_ms=0, eval_end_ms=43 * d.BAR,
                                enable_change=True, fixed_signal_indices=common)
            self.assertEqual(replay(rows, b, enabled=False,
                                    common_signal_indices=common), expected)

    def test_upper_lower_and_exact_midpoint(self):
        for close, admitted in ((101.0, True), (99.0, False), (100.0, True)):
            with self.subTest(close=close):
                rows = bars(20); rows[0]["close"] = close
                r = replay(rows, bundle(rows, [0]))
                self.assertEqual(len(r["trades"]), int(admitted))
                self.assertEqual(r["events"][0]["admission"], admitted)
                self.assertEqual(r["events"][0]["entry_observation"][n.FEATURE], admitted)
                self.assertEqual(r["events"][0]["entry_observation"]["known_at_ts"], d.BAR)

    def test_current_row_formula_matches_existing_geometry_primitive(self):
        rows = bars(5)
        for close in (98.0, 99.0, 100.0, 101.0, 102.0):
            rows[3]["close"] = close
            self.assertEqual(n.entry_observation(rows[3])[n.FEATURE],
                             d.old.geometry(rows, 3, "long")[n.FEATURE])

    def test_veto_releases_slot_and_new_signal_uses_unchanged_D_path(self):
        rows = bars(35); rows[0]["close"] = 99.0
        b = bundle(rows, [0, 3, 16]); b["ema20"][5] = 100.0
        prior = d.replay(rows, b, eval_start_ms=0, eval_end_ms=35 * d.BAR)
        actual = replay(rows, b)
        self.assertEqual([t["signal_index"] for t in prior["trades"]], [0, 16])
        self.assertEqual([t["signal_index"] for t in actual["trades"]], [3, 16])
        new = actual["trades"][0]
        diagnostic = d.replay(rows, b, eval_start_ms=0, eval_end_ms=35 * d.BAR,
                             fixed_signal_indices=[3])
        self.assertEqual(new, diagnostic["trades"][0])
        self.assertEqual(new["entry_index"], 4)
        self.assertEqual(new["exit_index"], 6)
        self.assertEqual(new["exit_reason"], "EMA20_NOT_ABOVE_EMA50_NEXT_OPEN")
        self.assertEqual(actual["trades"][1], prior["trades"][1])

    def test_unchanged_timeout_and_shared_origins_have_exact_path_parity(self):
        rows = bars(43); b = bundle(rows, [0, 3, 16, 35])
        b["ema20"][1] = 100.0
        p = d.replay(rows, b, eval_start_ms=0, eval_end_ms=43 * d.BAR)
        r = replay(rows, b)
        for field in ("trades", "open_positions", "trace"):
            self.assertEqual(r[field], p[field])
        self.assertEqual(r["trades"][1]["exit_index"], 15)

    def test_signal_denominator_and_veto_occupancy_are_exclusive(self):
        rows = bars(30); rows[3]["close"] = 99.0
        b = bundle(rows, [0, 3, 4, 16])
        r = replay(rows, b)
        self.assertEqual(len(r["events"]), 4)
        self.assertEqual(r["audit"]["original_signal_count"], 4)
        self.assertEqual(r["audit"]["raw_signals"], 4)
        self.assertEqual(r["audit"]["entry_veto_count"], 1)
        self.assertEqual(r["audit"]["occupancy_exclusion_count"], 1)
        self.assertEqual(r["events"][1]["exclusion_reason"], n.VETO_REASON)
        self.assertEqual(r["events"][2]["exclusion_reason"], "SIGNAL_DURING_OPEN")
        self.assertEqual(r["audit"]["completed"] + r["audit"]["open"]
                         + r["audit"]["excluded"], 4)

    def test_common_opportunity_view_excludes_new_origins(self):
        rows = bars(35); rows[0]["close"] = 99.0
        b = bundle(rows, [0, 3, 16])
        r = replay(rows, b, common_signal_indices=[0, 16])
        self.assertEqual([t["signal_index"] for t in r["trades"]], [16])
        self.assertEqual([e["signal_index"] for e in r["events"]], [0, 16])
        self.assertEqual(r["audit"]["raw_signals"], 2)
        self.assertEqual(r["audit"]["original_signal_count"], 3)
        self.assertEqual(r["audit"]["comparison_mode"], "COMMON_D_ADMITTED_OPPORTUNITIES")
        self.assertFalse(r["audit"]["same_entry_exit_comparison"])

    def test_common_empty_and_invalid_origins(self):
        rows = bars(20); b = bundle(rows, [0, 3])
        r = replay(rows, b, common_signal_indices=[])
        self.assertEqual(r["events"], [])
        self.assertEqual(r["audit"]["original_signal_count"], 2)
        for bad in ([0, 0], [1], [True], [0.0]):
            with self.assertRaisesRegex(RuntimeError, "COMMON_ORIGINS_INVALID"):
                replay(rows, b, common_signal_indices=bad)

    def test_pending_terminal_open_is_exact_D_and_never_forced_closed(self):
        rows = bars(6); b = bundle(rows, [0]); b["ema20"][-1] = 100.0
        p = d.replay(rows, b, eval_start_ms=0, eval_end_ms=6 * d.BAR)
        r = replay(rows, b)
        self.assertEqual(r["open_positions"], p["open_positions"])
        self.assertEqual(r["trades"], [])
        self.assertEqual(r["open_positions"][0]["pending_exit_signal_ts"], 6 * d.BAR)
        self.assertFalse(r["open_positions"][0]["terminal_liquidation"])

    def test_nonfinite_or_inconsistent_geometry_fails_closed(self):
        for name, value in (("close", float("nan")), ("high", float("inf")),
                            ("low", None), ("close", True), ("close", 103.0)):
            row = bars(1)[0]; row[name] = value
            with self.assertRaisesRegex(RuntimeError, "ENTRY_GEOMETRY"):
                n.entry_observation(row)

    def test_original_invalid_signal_cannot_hide_behind_entry_veto(self):
        rows = bars(20); rows[-1]["close"] = 99.0
        with self.assertRaisesRegex(RuntimeError, "SIGNAL_INVALID_OR_FUTURE"):
            replay(rows, bundle(rows, [19]))
        with self.assertRaisesRegex(RuntimeError, "PARTITION_ROW_FORBIDDEN"):
            n.replay(rows, bundle(rows, [0]), eval_start_ms=0,
                     eval_end_ms=19 * d.BAR)

    def test_boolean_flag_required_and_inputs_unchanged(self):
        rows = bars(20); b = bundle(rows, [0]); before = deepcopy((rows, b))
        with self.assertRaisesRegex(RuntimeError, "ENABLE_BOOL_REQUIRED"):
            replay(rows, b, enabled=1)
        replay(rows, b)
        self.assertEqual((rows, b), before)

    def test_real_bundle_and_eligibility_are_prefix_invariant(self):
        rows = bars(310)
        for i, row in enumerate(rows):
            px = 100 + 8 * math.sin(i / 7) + i / 100
            row.update(open=px, close=px, high=px + 1, low=px - 1)
        full = n.build_bundle(rows, d.PARENT_SPEC, eval_start_ms=0,
                              eval_end_ms=310 * d.BAR)
        prefix = n.build_bundle(rows[:280], d.PARENT_SPEC, eval_start_ms=0,
                                eval_end_ms=280 * d.BAR)
        self.assertEqual(prefix["signals"],
                         [s for s in full["signals"] if s["signal_ts"] < 280 * d.BAR])
        a = replay(rows, full)
        b = replay(rows[:280], prefix)
        self.assertEqual([e["entry_observation"] for e in b["events"]],
                         [e["entry_observation"] for e in a["events"]
                          if e["signal_ts"] < 280 * d.BAR])
        self.assertEqual([t for t in b["trades"] if t["exit_ts"] < 280 * d.BAR],
                         [t for t in a["trades"] if t["exit_ts"] < 280 * d.BAR])


if __name__ == "__main__":
    unittest.main()
