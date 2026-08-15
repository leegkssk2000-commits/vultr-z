from __future__ import annotations

import unittest

from backend.research.rebuild.breakout_policy_batch_v1 import (
    BreakoutPolicyConfig,
    FeatureSnapshot,
    build_break_and_continue_intent,
    build_keltner_trend_intent,
    build_squeeze_break_intent,
    compute_break_and_continue_feature,
    evaluator_adapter_sha,
)
from backend.research.rebuild.policy_kernel_v1 import (
    control_delayed_entry,
    control_direction_flip,
    control_time_placebo,
    digest,
)

HOUR_MS = 3_600_000


def _bars(n: int = 80) -> list[dict[str, float | int]]:
    out = []
    start = 1_700_000_000_000
    for i in range(n):
        c = 100.0 + i * 0.02
        out.append({"ts_ms": start+i*HOUR_MS, "open": c-0.1, "high": c+0.4,
                    "low": c-0.4, "close": c, "volume": 1000.0+i})
    return out


def _feature(strategy_id: str, values: dict, *, fresh: bool = True,
             close: float = 100.0, atr: float = 1.0) -> FeatureSnapshot:
    body = {"strategy_id": strategy_id, "symbol": "BTCUSDT", "signal_ts": 1_800_000_000_000,
            "close": close, "atr": atr, "values": values}
    return FeatureSnapshot(strategy_id, "BTCUSDT", 1_800_000_000_000, fresh,
                           close, atr, values, digest(body))


class BreakoutPolicyBatchV1Test(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = BreakoutPolicyConfig()
        self.kw = {"policy_source_sha": "fixture-policy-sha",
                   "verified_round_trip_cost_bps": 10.0, "config": self.cfg}

    def test_break_and_continue_planted_edge_parity_and_metric_recompute(self) -> None:
        feature = _feature("break_and_continue", {
            "long_break": True, "short_break": False, "box_height_atr": 2.0,
            "chase_atr": 0.3, "prior_high": 99.7, "prior_low": 96.0,
            "box_high": 99.5, "box_low": 97.5, "ema_fast": 99.0, "ema_slow": 98.0,
        })
        intent = build_break_and_continue_intent(feature, **self.kw)
        self.assertFalse(intent.no_trade)
        self.assertEqual(intent.side, "long")
        self.assertEqual(intent.sha, evaluator_adapter_sha(intent))
        recomputed_risk_bps = abs(feature.close - float(intent.sl)) / feature.close * 10_000.0
        self.assertAlmostEqual(recomputed_risk_bps, float(intent.risk_size["risk_distance_bps"]), places=9)
        self.assertGreaterEqual(intent.cost_budget_ratio, self.cfg.min_cost_budget_ratio)
        self.assertFalse(intent.pyramiding["adverse_add"])

    def test_keltner_planted_edge_and_parity(self) -> None:
        feature = _feature("keltner_trend", {
            "long_break": False, "short_break": True, "expansion_ratio": 1.2,
            "chase_atr": 0.4, "center": 101.0, "upper": 102.5, "lower": 99.5,
            "ema_fast": 99.0, "ema_slow": 100.0,
        })
        intent = build_keltner_trend_intent(feature, **self.kw)
        self.assertFalse(intent.no_trade)
        self.assertEqual(intent.side, "short")
        self.assertEqual(intent.sha, evaluator_adapter_sha(intent))
        self.assertGreater(float(intent.sl), feature.close)

    def test_squeeze_planted_edge_and_parity(self) -> None:
        feature = _feature("squeeze_break", {
            "long_release": True, "short_release": False, "impulse_atr": 0.8,
            "prev_squeeze": True, "now_squeeze": False,
            "bb_upper": 99.6, "bb_lower": 96.0, "kc_upper": 99.4, "kc_lower": 96.2,
            "ema_fast": 99.0, "ema_slow": 98.0,
        })
        intent = build_squeeze_break_intent(feature, **self.kw)
        self.assertFalse(intent.no_trade)
        self.assertEqual(intent.side, "long")
        self.assertEqual(intent.sha, evaluator_adapter_sha(intent))
        self.assertTrue(intent.runner["enabled"])

    def test_stale_fail_closed_all_three(self) -> None:
        fixtures = [
            (build_break_and_continue_intent, _feature("break_and_continue", {"long_break": True, "short_break": False, "box_height_atr": 2.0, "chase_atr": 0.2}, fresh=False)),
            (build_keltner_trend_intent, _feature("keltner_trend", {"long_break": True, "short_break": False, "expansion_ratio": 1.2, "chase_atr": 0.2}, fresh=False)),
            (build_squeeze_break_intent, _feature("squeeze_break", {"long_release": True, "short_release": False, "impulse_atr": 0.8}, fresh=False)),
        ]
        for builder, feature in fixtures:
            intent = builder(feature, **self.kw)
            self.assertTrue(intent.no_trade)
            self.assertIn("STALE_SOURCE_FAIL_CLOSED", intent.reason_codes)

    def test_cost_authority_and_cost_budget_fail_closed(self) -> None:
        feature = _feature("keltner_trend", {"long_break": True, "short_break": False,
                                             "expansion_ratio": 1.1, "chase_atr": 0.2})
        with self.assertRaisesRegex(ValueError, "VERIFIED_COST_AUTHORITY_REQUIRED"):
            build_keltner_trend_intent(feature, policy_source_sha="fixture",
                                       verified_round_trip_cost_bps=0.0, config=self.cfg)
        intent = build_keltner_trend_intent(feature, policy_source_sha="fixture",
                                             verified_round_trip_cost_bps=10_000.0, config=self.cfg)
        self.assertTrue(intent.no_trade)
        self.assertIn("STRUCTURAL_COST_BUDGET_BELOW_MIN", intent.reason_codes)

    def test_duplicate_timestamp_and_missing_data_fail_closed(self) -> None:
        bars = _bars()
        bars[-1]["ts_ms"] = bars[-2]["ts_ms"]
        with self.assertRaisesRegex(ValueError, "BAR_TS_NON_MONOTONIC_OR_DUPLICATE"):
            compute_break_and_continue_feature(bars, symbol="BTCUSDT",
                                               now_ts_ms=int(bars[-1]["ts_ms"]), config=self.cfg)
        bars = _bars()
        del bars[-1]["close"]
        with self.assertRaisesRegex(ValueError, "BAR_FIELD_INVALID:close"):
            compute_break_and_continue_feature(bars, symbol="BTCUSDT",
                                               now_ts_ms=int(bars[-1]["ts_ms"]), config=self.cfg)

    def test_negative_controls_are_deterministic_non_mutating(self) -> None:
        feature = _feature("squeeze_break", {"long_release": True, "short_release": False,
                                             "impulse_atr": 0.8})
        base = build_squeeze_break_intent(feature, **self.kw)
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
