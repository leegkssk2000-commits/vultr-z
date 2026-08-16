from __future__ import annotations

import unittest

from backend.research.rebuild.indicator_core_policy_batch_v1 import (
    FeatureSnapshot,
    IndicatorCoreConfig,
    SUPPORTED,
    build_intent,
    compute_feature,
)
from backend.research.rebuild.policy_kernel_v1 import (
    control_delayed_entry,
    control_direction_flip,
    control_time_placebo,
    evaluator_adapter_sha,
    validate_bars,
)


def bars(n: int = 140):
    out=[]
    base=100.0
    for i in range(n):
        drift=i*0.015
        wave=((i % 10)-5)*0.03
        c=base+drift+wave
        out.append({
            "ts_ms":1_800_000_000_000+i*300_000,
            "open":c-0.04,
            "high":c+0.28,
            "low":c-0.28,
            "close":c,
            "volume":100.0+(i % 17)*4.0,
        })
    return out


def snap(sid: str, values: dict):
    return FeatureSnapshot(sid,"BTCUSDT",1_800_000_000_000,True,100.0,2.0,values,"feature-sha")


PLANTED={
    "alpha_combo":{
        "trend_long":True,"trend_short":False,
        "breakout_long":True,"breakout_short":False,
        "reclaim_long":True,"reclaim_short":False,
        "rsi":60.0,"atr_pct":1.0,"dist_fast_atr":0.5,
    },
    "ema_ribbon_scalp":{
        "long_ribbon":True,"short_ribbon":False,
        "reclaim_long":True,"reclaim_short":False,
        "body_atr":0.8,"atr_pct":1.0,"dist_e21_atr":0.2,
    },
    "mfi_rsi_div":{
        "failed_low":True,"failed_high":False,
        "rsi":35.0,"rsi_improving":True,"rsi_weakening":False,
        "mfi":35.0,"mfi_improving":True,"mfi_weakening":False,
        "atr_pct":1.0,
    },
    "obv_trend":{
        "trend_long":True,"trend_short":False,
        "obv_slope":100.0,"price_move":1.0,"volume_ratio":1.5,
        "breakout_long":True,"breakout_short":False,"atr_pct":1.0,
    },
}


class IndicatorCoreR2T(unittest.TestCase):
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
            validate_bars(data,minimum=120)

    def test_verified_cost_authority_required(self):
        with self.assertRaisesRegex(ValueError,"VERIFIED_COST_AUTHORITY_REQUIRED"):
            build_intent(snap("alpha_combo",PLANTED["alpha_combo"]),
                         policy_source_sha="abc",verified_round_trip_cost_bps=0.0)

    def test_source_authority_required(self):
        with self.assertRaisesRegex(ValueError,"SOURCE_SHA_REQUIRED"):
            build_intent(snap("ema_ribbon_scalp",PLANTED["ema_ribbon_scalp"]),
                         policy_source_sha="",verified_round_trip_cost_bps=10.0)

    def test_stale_missing_fail_closed(self):
        cfg=IndicatorCoreConfig()
        data=bars()
        s=compute_feature("obv_trend",data,symbol="BTCUSDT",
                          now_ts_ms=data[-1]["ts_ms"]+3*cfg.timeframe_ms)
        i=build_intent(s,policy_source_sha="abc",verified_round_trip_cost_bps=10.0)
        self.assertTrue(i.no_trade)
        self.assertIn("STALE_SOURCE",i.reason_codes)

    def test_negative_volume_fail_closed(self):
        data=bars()
        data[-1]["volume"]=-1.0
        with self.assertRaisesRegex(ValueError,"BAR_FIELD_INVALID:volume|BAR_VOLUME_NEGATIVE"):
            compute_feature("obv_trend",data,symbol="BTCUSDT",now_ts_ms=data[-1]["ts_ms"])

    def test_planted_edge_each_strategy_and_intent_parity(self):
        for sid,vals in PLANTED.items():
            i=build_intent(snap(sid,vals),policy_source_sha=f"src-{sid}",
                           verified_round_trip_cost_bps=10.0)
            self.assertFalse(i.no_trade,sid)
            self.assertEqual(i.side,"long",sid)
            self.assertGreaterEqual(i.cost_budget_ratio,1.25,sid)
            self.assertEqual(evaluator_adapter_sha(i),i.sha,sid)
            self.assertFalse(i.pyramiding["enabled"],sid)
            self.assertFalse(i.pyramiding["adverse_add"],sid)
            self.assertFalse(i.partial["enabled"],sid)
            self.assertFalse(i.trailing["enabled"],sid)

    def test_negative_controls_are_separate_and_deterministic(self):
        i=build_intent(snap("alpha_combo",PLANTED["alpha_combo"]),
                       policy_source_sha="src",verified_round_trip_cost_bps=10.0)
        self.assertEqual(control_direction_flip(i).side,"short")
        self.assertEqual(control_time_placebo(i,900_000).signal_ts,i.signal_ts+900_000)
        self.assertEqual(control_delayed_entry(i,2,300_000).signal_ts,i.signal_ts+600_000)
        self.assertNotEqual(control_direction_flip(i).sha,i.sha)

    def test_independent_risk_recompute_each_strategy(self):
        for sid,vals in PLANTED.items():
            i=build_intent(snap(sid,vals),policy_source_sha=f"src-{sid}",
                           verified_round_trip_cost_bps=10.0)
            stop_bps=abs(i.sl-100.0)/100.0*10_000.0
            move_bps=abs(i.tp-100.0)/100.0*10_000.0
            self.assertAlmostEqual(stop_bps,i.risk_size["stop_distance_bps"],places=9,sid)
            self.assertAlmostEqual(move_bps,i.move_budget_bps,places=9,sid)
            self.assertAlmostEqual(move_bps/10.0,i.cost_budget_ratio,places=9,sid)


if __name__ == "__main__":
    unittest.main()
