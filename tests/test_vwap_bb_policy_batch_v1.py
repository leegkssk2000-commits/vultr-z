from __future__ import annotations

import unittest

from backend.research.rebuild.vwap_bb_policy_batch_v1 import (
    CommonPolicyConfig,
    FeatureSnapshot,
    build_anchor_vwap_trend_intent,
    build_bb_revert_intent,
    build_vwap_revert_intent,
    compute_bb_revert_feature,
    control_delayed_entry,
    control_direction_flip,
    control_time_placebo,
    evaluator_adapter_sha,
)
from backend.research.rebuild.policy_kernel_v1 import digest

HOUR_MS = 3_600_000


def _bars(n: int = 80) -> list[dict[str, float | int]]:
    out = []
    start = 1_700_000_000_000
    for i in range(n):
        c = 100.0 + i * 0.01
        out.append({"ts_ms":start+i*HOUR_MS,"open":c-0.1,"high":c+0.4,"low":c-0.4,"close":c,"volume":1000.0+i})
    return out


def _feature(strategy_id: str, values: dict, *, fresh: bool = True, close: float = 100.0, atr: float = 1.0) -> FeatureSnapshot:
    body = {"strategy_id":strategy_id,"symbol":"BTCUSDT","signal_ts":1_800_000_000_000,"close":close,"atr":atr,"values":values}
    return FeatureSnapshot(strategy_id, "BTCUSDT", 1_800_000_000_000, fresh, close, atr, values, digest(body))


class RebuildBatchPolicyV1Test(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = CommonPolicyConfig()
        self.kw = {"policy_source_sha":"fixture-policy-sha","verified_round_trip_cost_bps":10.0,"config":self.cfg}

    def test_anchor_vwap_planted_edge_and_parity(self) -> None:
        feature = _feature("anchor_vwap_trend", {
            "long_cross":True,"short_cross":False,"trend_long":True,"trend_short":False,
            "dist_long_atr":0.55,"dist_short_atr":-0.2,"avwap_long":99.45,"avwap_short":101.0,
        })
        intent = build_anchor_vwap_trend_intent(feature, **self.kw)
        self.assertFalse(intent.no_trade)
        self.assertEqual(intent.side, "long")
        self.assertLess(intent.sl or 0.0, feature.close)
        self.assertTrue(intent.runner["enabled"])
        self.assertFalse(intent.pyramiding["enabled"])
        self.assertEqual(intent.sha, evaluator_adapter_sha(intent))

    def test_vwap_revert_planted_edge_and_parity(self) -> None:
        feature = _feature("vwap_revert", {
            "long_reclaim":True,"short_reclaim":False,"trend_veto_long":False,"trend_veto_short":False,
            "vwap":102.0,"extension_atr":-1.4,"prev_extension_atr":-2.0,"rsi":36.0,
        })
        intent = build_vwap_revert_intent(feature, **self.kw)
        self.assertFalse(intent.no_trade)
        self.assertEqual(intent.side, "long")
        self.assertGreater(intent.tp or 0.0, feature.close)
        self.assertEqual(intent.sha, evaluator_adapter_sha(intent))

    def test_bb_revert_planted_edge_and_parity(self) -> None:
        feature = _feature("bb_revert", {
            "long_reclaim":False,"short_reclaim":True,"trend_veto_long":False,"trend_veto_short":False,
            "mid":98.0,"upper":101.0,"lower":95.0,"rsi":68.0,"band_width_atr":6.0,
        }, close=100.0)
        intent = build_bb_revert_intent(feature, **self.kw)
        self.assertFalse(intent.no_trade)
        self.assertEqual(intent.side, "short")
        self.assertLess(intent.tp or 999.0, feature.close)
        self.assertEqual(intent.sha, evaluator_adapter_sha(intent))

    def test_stale_fail_closed_for_all_three(self) -> None:
        fixtures = [
            (build_anchor_vwap_trend_intent, _feature("anchor_vwap_trend", {"long_cross":True,"short_cross":False,"trend_long":True,"trend_short":False,"dist_long_atr":0.5,"dist_short_atr":0.0,"avwap_long":99.5,"avwap_short":101.0}, fresh=False)),
            (build_vwap_revert_intent, _feature("vwap_revert", {"long_reclaim":True,"short_reclaim":False,"trend_veto_long":False,"trend_veto_short":False,"vwap":102.0,"extension_atr":-1.5,"prev_extension_atr":-2.0,"rsi":35.0}, fresh=False)),
            (build_bb_revert_intent, _feature("bb_revert", {"long_reclaim":True,"short_reclaim":False,"trend_veto_long":False,"trend_veto_short":False,"mid":102.0,"upper":105.0,"lower":99.0,"rsi":30.0,"band_width_atr":6.0}, fresh=False)),
        ]
        for builder, feature in fixtures:
            intent = builder(feature, **self.kw)
            self.assertTrue(intent.no_trade)
            self.assertIn("STALE_SOURCE_FAIL_CLOSED", intent.reason_codes)

    def test_cost_budget_fail_closed(self) -> None:
        feature = _feature("vwap_revert", {"long_reclaim":True,"short_reclaim":False,"trend_veto_long":False,"trend_veto_short":False,"vwap":100.5,"extension_atr":-1.5,"prev_extension_atr":-2.0,"rsi":35.0})
        intent = build_vwap_revert_intent(feature, policy_source_sha="fixture", verified_round_trip_cost_bps=10_000.0, config=self.cfg)
        self.assertTrue(intent.no_trade)
        self.assertIn("STRUCTURAL_COST_BUDGET_BELOW_MIN", intent.reason_codes)

    def test_missing_cost_authority_fails_closed(self) -> None:
        feature = _feature("bb_revert", {"long_reclaim":True,"short_reclaim":False,"trend_veto_long":False,"trend_veto_short":False,"mid":102.0,"upper":105.0,"lower":99.0,"rsi":30.0,"band_width_atr":6.0})
        with self.assertRaisesRegex(ValueError, "VERIFIED_COST_AUTHORITY_REQUIRED"):
            build_bb_revert_intent(feature, policy_source_sha="fixture", verified_round_trip_cost_bps=0.0, config=self.cfg)

    def test_duplicate_timestamp_feature_fails_closed(self) -> None:
        bars = _bars()
        bars[-1]["ts_ms"] = bars[-2]["ts_ms"]
        with self.assertRaisesRegex(ValueError, "BAR_TS_NON_MONOTONIC_OR_DUPLICATE"):
            compute_bb_revert_feature(bars, symbol="BTCUSDT", now_ts_ms=int(bars[-1]["ts_ms"]), config=self.cfg)

    def test_negative_controls_are_deterministic_and_non_mutating(self) -> None:
        feature = _feature("anchor_vwap_trend", {"long_cross":True,"short_cross":False,"trend_long":True,"trend_short":False,"dist_long_atr":0.5,"dist_short_atr":0.0,"avwap_long":99.5,"avwap_short":101.0})
        base = build_anchor_vwap_trend_intent(feature, **self.kw)
        base_sha = base.sha
        flip = control_direction_flip(base)
        placebo = control_time_placebo(base, HOUR_MS // 2)
        delayed = control_delayed_entry(base, 1, HOUR_MS)
        self.assertEqual(base.sha, base_sha)
        self.assertEqual(flip.side, "short")
        self.assertNotEqual(flip.sha, base_sha)
        self.assertNotEqual(placebo.signal_ts, base.signal_ts)
        self.assertNotEqual(delayed.signal_ts, base.signal_ts)
        self.assertIn("CONTROL_DIRECTION_FLIP", flip.reason_codes)
        self.assertIn("CONTROL_TIME_PLACEBO", placebo.reason_codes)
        self.assertIn("CONTROL_DELAYED_ENTRY", delayed.reason_codes)


if __name__ == "__main__":
    unittest.main()
