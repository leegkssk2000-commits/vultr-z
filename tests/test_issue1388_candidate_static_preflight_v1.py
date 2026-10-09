"""No API/no PnL: regress incorrect AI proposal semantics before economic work."""
from __future__ import annotations

import unittest

from ops.issue1388_candidate_static_preflight_v1 import (
    _guaranteed_false, inspect_spec, audit_saved
)

class CandidatePreflightTests(unittest.TestCase):
    def test_roc_close_comma_n_is_not_callable(self):
        r=inspect_spec({"entry_rule":"ema(close,20)>ema(close,50) and roc(close,3)<0",
                        "bar_interval":"30m"})
        self.assertIn("EXECUTOR_FUNCTION_ARITY_MISMATCH:roc",r["hard_issues"])
        self.assertEqual(r["formal_economic_credit"],0)

    def test_valid_roc_one_arg_not_blocked(self):
        r=inspect_spec({"entry_rule":"ema(close,20)>ema(close,50) and roc(3)<0",
                        "bar_interval":"30m"})
        self.assertEqual(r["hard_issues"],[])

    def test_self_inclusive_strict_breakout_cannot_trade(self):
        for rule in ["close > highest(close,20)", "close > highest(high,20)",
                     "high > highest(high,20)", "low < lowest(low,20)"]:
            with self.subTest(rule=rule):
                self.assertIn("UNREACHABLE_CURRENT_BAR_EXTREME",
                    inspect_spec({"entry_rule":rule,"bar_interval":"1h"})["hard_issues"])

    def test_near_breakout_with_greater_equal_is_possible(self):
        r=inspect_spec({"entry_rule":"close >= highest(close,20)","bar_interval":"1h"})
        self.assertEqual(r["hard_issues"],[])

    def test_or_fallback_still_possible(self):
        r=inspect_spec({"entry_rule":"close > highest(close,20) or close > ema(close,20)",
                        "bar_interval":"1h"})
        self.assertEqual(r["hard_issues"],[])

    def test_outside_issue_scope_separate_from_bad_dsl(self):
        for tf in ["4h","1d"]:
            r=inspect_spec({"entry_rule":"ema(close,20)>ema(close,50)","bar_interval":tf})
            self.assertIn("OUTSIDE_CURRENT_ISSUE1388_TIMEFRAME:"+tf,r["hard_issues"])

    def test_invalid_feature_roc_and_invalid_exit_still_block_even_when_entry_works(self):
        spec={"entry_rule":"close>open","bar_interval":"30m",
              "features":[{"name":"r","formula":"roc(close,3)"}],
              "side_rule":"long",
              "exit_rule":"roc(close,4)>0"}
        findings=inspect_spec(spec)["hard_issues"]
        self.assertIn("EXECUTOR_FUNCTION_ARITY_MISMATCH:roc@FEATURE:r",findings)
        self.assertIn("EXECUTOR_FUNCTION_ARITY_MISMATCH:roc@EXIT",findings)

    def test_invalid_side_formula_blocks_without_market_evaluation(self):
        spec={"entry_rule":"close>open","bar_interval":"30m",
              "features":[],"side_rule":"long if roc(close,3)>0 else short",
              "exit_rule":"time_stop"}
        self.assertIn("EXECUTOR_FUNCTION_ARITY_MISMATCH:roc@SIDE",inspect_spec(spec)["hard_issues"])

    def test_saved_historical_candidate_fingerprint_and_failure_composition(self):
        data=audit_saved()
        self.assertEqual(len(data["candidates"]),5)
        self.assertEqual(data["blocked"],5)
        self.assertEqual(data["not_static_blocked"],0)
        byid={r["strategy_id"]:r["static"]["hard_issues"] for r in data["candidates"]}
        self.assertIn("EXECUTOR_FUNCTION_ARITY_MISMATCH:roc",byid["supertrend_pullback"])
        self.assertIn("EXECUTOR_FUNCTION_ARITY_MISMATCH:roc",byid["keltner_trend"])
        for name in ("trend_rider","break_and_continue","trend_ma_macd"):
            self.assertIn("UNREACHABLE_CURRENT_BAR_EXTREME",byid[name])
        self.assertEqual(data["formal_survivor_credit"],0)

if __name__ == "__main__":
    unittest.main()
