from __future__ import annotations

import unittest

from backend.research.rebuild.policy_kernel_v1 import (
    control_delayed_entry, control_direction_flip, control_time_placebo,
    evaluator_adapter_sha, validate_bars,
)
from backend.research.rebuild.reversal_range_policy_batch_v1 import (
    FeatureSnapshot, ReversalRangeConfig, SUPPORTED, build_intent, compute_feature,
)


def bars(n: int = 48):
    out=[]
    base=100.0
    for i in range(n):
        c=base + ((i % 8)-4)*0.08
        out.append({"ts_ms":1_800_000_000_000+i*300_000,"open":c-0.04,"high":c+0.25,"low":c-0.25,"close":c,"volume":100+i})
    return out


def snap(sid: str, values: dict):
    return FeatureSnapshot(sid,"BTCUSDT",1_800_000_000_000,True,100.0,2.0,values,"feature-sha")


class ReversalRangeR2T(unittest.TestCase):
    def test_deterministic_feature_fixtures(self):
        data=bars()
        now=data[-1]["ts_ms"]
        for sid in SUPPORTED:
            a=compute_feature(sid,data,symbol="BTCUSDT",now_ts_ms=now)
            b=compute_feature(sid,data,symbol="BTCUSDT",now_ts_ms=now)
            self.assertEqual(a.feature_sha,b.feature_sha,sid)
            self.assertTrue(a.fresh,sid)

    def test_duplicate_fail_closed(self):
        data=bars()
        data[-1]["ts_ms"]=data[-2]["ts_ms"]
        with self.assertRaisesRegex(ValueError,"BAR_TS_NON_MONOTONIC_OR_DUPLICATE"):
            validate_bars(data,minimum=40)

    def test_verified_cost_authority_required(self):
        s=snap("range_fade",{"range_width_atr":4.0,"range_position":0.1,"rsi":35.0,"reclaim_up":True,"reclaim_down":False})
        with self.assertRaisesRegex(ValueError,"VERIFIED_COST_AUTHORITY_REQUIRED"):
            build_intent(s,policy_source_sha="abc",verified_round_trip_cost_bps=0.0)

    def test_stale_missing_fail_closed(self):
        cfg=ReversalRangeConfig()
        data=bars()
        s=compute_feature("range_fade",data,symbol="BTCUSDT",now_ts_ms=data[-1]["ts_ms"]+3*cfg.timeframe_ms)
        i=build_intent(s,policy_source_sha="abc",verified_round_trip_cost_bps=10.0)
        self.assertTrue(i.no_trade)
        self.assertIn("STALE_SOURCE",i.reason_codes)

    def test_planted_edge_each_strategy_and_intent_parity(self):
        planted={
            "range_fade":{"range_width_atr":4.0,"range_position":0.08,"rsi":34.0,"reclaim_up":True,"reclaim_down":False},
            "fvg_revert":{"bull_gap_atr":0.0,"bear_gap_atr":0.8,"reclaim_up":True,"reclaim_down":False},
            "pivot_reversal":{"near_low":0.1,"near_high":3.0,"lower_wick_body":2.5,"upper_wick_body":0.2},
            "rsi_swing_fail":{"rsi":35.0,"failed_low":True,"failed_high":False},
        }
        for sid,vals in planted.items():
            i=build_intent(snap(sid,vals),policy_source_sha=f"src-{sid}",verified_round_trip_cost_bps=10.0)
            self.assertFalse(i.no_trade,sid)
            self.assertEqual(i.side,"long",sid)
            self.assertGreaterEqual(i.cost_budget_ratio,1.25,sid)
            self.assertEqual(evaluator_adapter_sha(i),i.sha,sid)
            self.assertFalse(i.pyramiding["enabled"],sid)
            self.assertFalse(i.pyramiding["adverse_add"],sid)

    def test_negative_controls_are_separate_and_deterministic(self):
        i=build_intent(snap("range_fade",{"range_width_atr":4.0,"range_position":0.08,"rsi":34.0,"reclaim_up":True,"reclaim_down":False}),
                       policy_source_sha="src",verified_round_trip_cost_bps=10.0)
        self.assertEqual(control_direction_flip(i).side,"short")
        self.assertEqual(control_time_placebo(i,900_000).signal_ts,i.signal_ts+900_000)
        self.assertEqual(control_delayed_entry(i,2,300_000).signal_ts,i.signal_ts+600_000)
        self.assertNotEqual(control_direction_flip(i).sha,i.sha)

    def test_independent_risk_recompute(self):
        i=build_intent(snap("pivot_reversal",{"near_low":0.1,"near_high":3.0,"lower_wick_body":2.5,"upper_wick_body":0.2}),
                       policy_source_sha="src",verified_round_trip_cost_bps=10.0)
        stop_bps=abs(i.sl-100.0)/100.0*10_000.0
        move_bps=abs(i.tp-100.0)/100.0*10_000.0
        self.assertAlmostEqual(stop_bps,i.risk_size["stop_distance_bps"],places=9)
        self.assertAlmostEqual(move_bps,i.move_budget_bps,places=9)
        self.assertAlmostEqual(move_bps/10.0,i.cost_budget_ratio,places=9)


if __name__ == "__main__":
    unittest.main()
