"""Synthetic timing, ownership, prefix and unfinished-state regressions."""
from copy import deepcopy
import math
import unittest

from backend.research.rebuild import parallel_exit_keltner_v1 as k


def bars(n):
    return [{"bar_open_ts": i * k.BAR, "bar_close_ts": (i + 1) * k.BAR,
             "open": 100.0, "high": 102.0, "low": 98.0, "close": 100.0,
             "volume": 1.0} for i in range(n)]


def bundle(rows, indices):
    return {"signals": [{"signal_index": i, "signal_ts": rows[i]["bar_close_ts"]}
                        for i in indices],
            "ema20": [101.0] * len(rows), "ema50": [100.0] * len(rows)}


def replay(rows, b, **kwargs):
    return k.replay(rows, b, eval_start_ms=0,
                    eval_end_ms=rows[-1]["bar_close_ts"], **kwargs)


class KeltnerExitTests(unittest.TestCase):
    def test_runner_charges_full_replay_new_origin_funding_and_pending_mark(self):
        # Synthetic cross-module contract: lifecycle -> shared charge -> daily
        # valuation. A new freed-slot entry is counted; a pending tail remains
        # an observation with full hypothetical cost, never a closed trade.
        from backend.research.rebuild import parallel_exit_dev_v1 as runner
        from backend.research.rebuild.test_break_channel_source_v1 import policy, COSTS
        rows = bars(43); b = bundle(rows, [0, 3, 16, 35])
        b["ema20"][1] = 100.0; b["ema20"][-1] = 100.0
        p = policy(); p["development_interval_ms"] = [0, 43 * k.BAR]
        original = deepcopy(rows)
        parent = runner.replay_stage("KELTNER", {"TEST": b}, {"TEST": rows},
                                     COSTS, p, 0, 43 * k.BAR, "P")
        child = runner.replay_stage("KELTNER", {"TEST": b}, {"TEST": rows},
                                    COSTS, p, 0, 43 * k.BAR, "FULL")
        self.assertEqual((len(parent["trades"]), len(child["trades"])), (2, 3))
        self.assertEqual([t["signal_index"] for t in child["trades"]], [0, 3, 16])
        self.assertEqual(parent["trades"][0]["funding_bps"], 18.0)
        self.assertEqual(child["trades"][0]["funding_bps"], 3.0)
        self.assertEqual((parent["trades"][0]["cost_bps"], child["trades"][0]["cost_bps"]),
                         (31.0, 20.0))
        self.assertEqual(child["trades"][0]["cost2x_net_bps"], -40.0)
        self.assertEqual(len(child["open_observations"]), 1)
        opened = child["open_observations"][0]
        self.assertFalse(opened["actual_exit"])
        self.assertNotIn("net_bps", opened)
        self.assertEqual(opened["pending_exit_signal_ts"], 43 * k.BAR)
        self.assertEqual(opened["modeled_funding_accrued_bps"], 9.0)
        self.assertEqual(opened["hypothetical_liquidation_net_mark_bps"], -22.0)
        self.assertEqual(opened["hypothetical_liquidation_cost2x_net_mark_bps"], -44.0)
        self.assertIsNone(opened["entry_side_cost_bps"])
        self.assertEqual(opened["lane_id"], k.LANE)
        self.assertEqual(opened["origin_key"], runner.source.prior.previous.source_key(opened))
        stage = runner.metrics.build_stage(child["trades"], child["open_observations"],
                                            child["events"], {"TEST": rows}, COSTS, p,
                                            ["TEST"], 0, 43 * k.BAR)
        self.assertEqual(stage["metrics"]["base_cost"]["completed_T"], 3)
        self.assertAlmostEqual(stage["daily"][-1]["cumulative_net_mark_bps"],
                               sum(t["net_bps"] for t in child["trades"]) - 22.0)
        self.assertEqual(rows, original)

    def test_disabled_closed_ledger_exact_shared_parity_and_tail_mark(self):
        rows = bars(43)
        indices = [0, 5, 12, 13, 22, 30]
        actual = replay(rows, bundle(rows, indices), enable_change=False)
        expected = k.old.common.evaluate_development_events(
            rows, indices, split_start_ms=0, split_end_ms=43 * k.BAR,
            interval_ms=k.BAR, hold_bars=12)
        self.assertEqual(actual["trades"], expected["trades"])
        self.assertEqual([t["signal_index"] for t in actual["trades"]], [0, 13])
        self.assertEqual(actual["open_positions"][0]["signal_index"], 30)
        self.assertEqual(actual["open_positions"][0]["censor_reason"],
                         "ORIGINAL_STRICT_END_TIMEOUT_AT_BOUNDARY")
        self.assertFalse(actual["open_positions"][0]["terminal_liquidation"])

    def test_first_held_close_equality_exits_next_open_and_excludes_exit_range(self):
        rows = bars(20)
        rows[2].update(open=17.0, high=500.0, low=1.0, close=499.0)
        b = bundle(rows, [0]); b["ema20"][1] = 100.0
        actual = replay(rows, b)
        t = actual["trades"][0]
        self.assertEqual((t["entry_index"], t["exit_index"]), (1, 2))
        self.assertEqual(t["exit_price"], 17.0)
        self.assertEqual(t["exit_ts"], rows[1]["bar_close_ts"])
        self.assertEqual(t["exit_ts"], rows[2]["bar_open_ts"])
        self.assertAlmostEqual(t["mfe_bps"], 200.0)
        self.assertAlmostEqual(t["mae_bps"], -8300.0)
        self.assertEqual(len([x for x in actual["trace"]
                              if x["kind"] == "TREND_INVALIDATION_CLOSE"]), 1)

    def test_signal_before_entry_cannot_trigger_exit(self):
        rows = bars(20); b = bundle(rows, [0]); b["ema20"][0] = 99.0
        t = replay(rows, b)["trades"][0]
        self.assertEqual(t["exit_index"], 12)
        self.assertNotIn("exit_trigger", t)

    def test_native_timeout_at_same_close_precedes_trigger(self):
        rows = bars(20); b = bundle(rows, [0]); b["ema20"][12] = 99.0
        r = replay(rows, b)
        self.assertEqual(r["trades"][0]["exit_ts"], 13 * k.BAR)
        self.assertFalse(any(x["kind"] == "TREND_INVALIDATION_CLOSE" for x in r["trace"]))

    def test_prior_close_trigger_exits_at_timeout_bar_open(self):
        rows = bars(20); b = bundle(rows, [0]); b["ema20"][11] = 99.0
        t = replay(rows, b)["trades"][0]
        self.assertEqual(t["exit_index"], 12)
        self.assertEqual(t["exit_ts"], 12 * k.BAR)
        self.assertEqual(t["hold_ms"], 11 * k.BAR)

    def test_original_exit_bar_ownership_is_preserved(self):
        rows = bars(25); b = bundle(rows, [0, 2, 3]); b["ema20"][1] = 100.0
        r = replay(rows, b)
        self.assertEqual([x["signal_index"] for x in r["trades"]], [0, 3])
        self.assertEqual(r["events"][1]["exclusion_reason"], "SIGNAL_DURING_OPEN")
        self.assertEqual(r["trades"][1]["entry_index"], 4)

    def test_fixed_origins_are_explicit_diagnostic_ownership(self):
        rows = bars(25); b = bundle(rows, [0, 3])
        full = replay(rows, b, enable_change=False)
        fixed = replay(rows, b, enable_change=False, fixed_signal_indices=[0, 3])
        self.assertEqual(len(full["trades"]), 1)
        self.assertEqual(len(fixed["trades"]), 2)
        self.assertIsNone(fixed["audit"]["same_symbol_max_positions"])
        self.assertTrue(fixed["audit"]["fixed_origins_independent_diagnostic_positions"])

    def test_final_close_trigger_retains_pending_open_not_future_fill(self):
        rows = bars(6); b = bundle(rows, [0]); b["ema20"][-1] = 100.0
        r = replay(rows, b)
        self.assertEqual(r["trades"], [])
        o = r["open_positions"][0]
        self.assertEqual(o["pending_exit_signal_ts"], 6 * k.BAR)
        self.assertEqual(o["mark_ts"], 6 * k.BAR)
        self.assertFalse(o["terminal_liquidation"])
        self.assertNotIn("exit_ts", o)
        self.assertEqual(r["audit"]["pending_exit_at_end"], 1)

    def test_exact_boundary_timeout_preserves_parent_strict_end(self):
        rows = bars(13); b = bundle(rows, [0]); b["ema20"][-1] = 99.0
        r = replay(rows, b)
        self.assertEqual(r["trades"], [])
        self.assertEqual(r["audit"]["strict_boundary_timeout_marks"], 1)
        self.assertIsNone(r["open_positions"][0]["pending_exit_signal_ts"])
        self.assertEqual(r["open_positions"][0]["native_hold_bars"], 12)

    def test_new_calendar_flat_start_includes_exact_boundary_signal_only(self):
        rows = bars(30); b = bundle(rows, [9, 20])
        r = k.replay(rows, b, eval_start_ms=10 * k.BAR,
                     eval_end_ms=30 * k.BAR, enable_change=False)
        self.assertEqual(r["trades"][0]["entry_ts"], 10 * k.BAR)
        invalid = bundle(rows, [8, 9])
        with self.assertRaisesRegex(RuntimeError, "SIGNAL_INVALID_OR_FUTURE"):
            k.replay(rows, invalid, eval_start_ms=10 * k.BAR,
                     eval_end_ms=30 * k.BAR)

    def test_future_rows_missing_bar_and_end_signal_fail_closed(self):
        rows = bars(20)
        with self.assertRaisesRegex(RuntimeError, "PARTITION_ROW_FORBIDDEN"):
            k.replay(rows, bundle(rows, [0]), eval_start_ms=0, eval_end_ms=19 * k.BAR)
        missing = rows[:4] + rows[5:]
        with self.assertRaisesRegex(RuntimeError, "GAP_DUPLICATE_OR_ORDER"):
            replay(missing, bundle(missing, [0]))
        with self.assertRaisesRegex(RuntimeError, "SIGNAL_INVALID_OR_FUTURE"):
            replay(rows, bundle(rows, [19]))

    def test_nonfinite_feature_and_mutated_parent_spec_are_rejected(self):
        rows = bars(20); b = bundle(rows, [0]); b["ema20"][1] = float("nan")
        with self.assertRaisesRegex(RuntimeError, "FEATURE_MISSING_OR_NONFINITE"):
            replay(rows, b)
        wrong = deepcopy(k.PARENT_SPEC); wrong["max_hold_bars"] = 13
        with self.assertRaisesRegex(RuntimeError, "ORIGINAL_SPEC_DRIFT"):
            k.build_bundle(rows, wrong, eval_start_ms=0, eval_end_ms=20 * k.BAR)

    def test_real_dsl_bounded_ema_seed_and_prefix_causality(self):
        rows = bars(310)
        for i, row in enumerate(rows):
            px = 100.0 + 8.0 * math.sin(i / 7.0) + i / 100.0
            row.update(open=px, close=px, high=px + 1.0, low=px - 1.0)
        full = k.build_bundle(rows, k.PARENT_SPEC, eval_start_ms=0,
                              eval_end_ms=310 * k.BAR)
        prefix = k.build_bundle(rows[:280], k.PARENT_SPEC, eval_start_ms=0,
                                eval_end_ms=280 * k.BAR)
        for name, length in (("ema20", 20), ("ema50", 50)):
            self.assertEqual(prefix[name], full[name][:280])
            values = [r["close"] for r in rows[260 - 4 * length + 1:261]]
            expected = values[0]
            alpha = 2.0 / (length + 1.0)
            for value in values[1:]:
                expected = alpha * value + (1.0 - alpha) * expected
            self.assertEqual(full[name][260], expected)
        self.assertEqual(prefix["signals"],
                         [s for s in full["signals"] if s["signal_ts"] < 280 * k.BAR])
        self.assertTrue(all(s["signal_index"] >= 239 for s in full["signals"]))


if __name__ == "__main__":
    unittest.main()
