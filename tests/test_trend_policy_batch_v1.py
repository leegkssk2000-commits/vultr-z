from __future__ import annotations

import unittest

from backend.research.rebuild.policy_kernel_v1 import (
    control_delayed_entry,
    control_direction_flip,
    control_time_placebo,
    evaluator_adapter_sha,
)
from backend.research.rebuild.trend_policy_batch_v1 import (
    FeatureSnapshot,
    build_supertrend_pullback_intent,
    build_trend_ma_macd_intent,
    build_trend_rider_intent,
    compute_supertrend_pullback_feature,
    compute_trend_ma_macd_feature,
    compute_trend_rider_feature,
)

SRC = "historical-r7-policy-source-sha"
COST = 10.0
NOW = 10_000_000_000


def bars(n: int = 90):
    out = []
    px = 100.0
    for i in range(n):
        drift = 0.20 if i < n - 8 else (-0.10 if i < n - 3 else 0.35)
        o = px
        c = px + drift
        out.append({"ts_ms": NOW - (n - 1 - i) * 3_600_000, "open": o,
                    "high": max(o, c) + 0.30, "low": min(o, c) - 0.30,
                    "close": c, "volume": 1000.0 + i})
        px = c
    return out


def feature(sid: str) -> FeatureSnapshot:
    common = dict(strategy_id=sid, symbol="BTC-USDT", signal_ts=NOW, fresh=True,
                  close=100.0, atr=1.0, feature_sha=f"fixture-{sid}")
    if sid == "supertrend_pullback":
        values = {"long_reclaim": True, "short_reclaim": False, "pullback_depth_atr": 0.8,
                  "chase_atr": 0.5}
    elif sid == "trend_ma_macd":
        values = {"long_cross": True, "short_cross": False, "impulse_atr": 0.08,
                  "chase_atr": 0.4}
    else:
        values = {"long_confirm": True, "short_confirm": False, "st_gap_atr": 0.8,
                  "chase_atr": 0.6}
    return FeatureSnapshot(values=values, **common)


CASES = [
    ("supertrend_pullback", build_supertrend_pullback_intent),
    ("trend_ma_macd", build_trend_ma_macd_intent),
    ("trend_rider", build_trend_rider_intent),
]


class TrendPolicyBatchV1Tests(unittest.TestCase):
    def test_planted_edge_positive_control_and_parity(self):
        for sid, builder in CASES:
            with self.subTest(strategy_id=sid):
                intent = builder(feature(sid), policy_source_sha=SRC, verified_round_trip_cost_bps=COST)
                self.assertFalse(intent.no_trade)
                self.assertEqual(intent.side, "long")
                self.assertGreaterEqual(intent.cost_budget_ratio, 1.25)
                self.assertEqual(intent.pyramiding, {"enabled": False, "adverse_add": False})
                self.assertEqual(evaluator_adapter_sha(intent), intent.sha)
                recomputed_risk_bps = abs(intent.sl - 100.0) / 100.0 * 10_000.0
                self.assertAlmostEqual(recomputed_risk_bps, intent.risk_size["risk_distance_bps"])

                flipped = control_direction_flip(intent)
                placebo = control_time_placebo(intent, 7 * 3_600_000)
                delayed = control_delayed_entry(intent, 2, 3_600_000)
                self.assertEqual(flipped.side, "short")
                self.assertNotEqual(flipped.sha, intent.sha)
                self.assertNotEqual(placebo.signal_ts, intent.signal_ts)
                self.assertNotEqual(placebo.sha, intent.sha)
                self.assertNotEqual(delayed.signal_ts, intent.signal_ts)
                self.assertNotEqual(delayed.sha, intent.sha)

    def test_stale_missing_cost_and_strategy_mismatch_fail_closed(self):
        for sid, builder in CASES:
            with self.subTest(strategy_id=sid):
                current = feature(sid)
                stale = FeatureSnapshot(current.strategy_id, current.symbol, current.signal_ts, False,
                                        current.close, current.atr, current.values, current.feature_sha)
                intent = builder(stale, policy_source_sha=SRC, verified_round_trip_cost_bps=COST)
                self.assertTrue(intent.no_trade)
                self.assertIn("STALE_SOURCE_FAIL_CLOSED", intent.reason_codes)
                with self.assertRaisesRegex(ValueError, "VERIFIED_COST_AUTHORITY_REQUIRED"):
                    builder(feature(sid), policy_source_sha=SRC, verified_round_trip_cost_bps=0.0)
                wrong = feature("trend_rider" if sid != "trend_rider" else "trend_ma_macd")
                with self.assertRaisesRegex(ValueError, "FEATURE_STRATEGY_MISMATCH"):
                    builder(wrong, policy_source_sha=SRC, verified_round_trip_cost_bps=COST)

    def test_feature_ssot_closed_bar_determinism_and_duplicate_guard(self):
        xs = bars()
        fns = [compute_supertrend_pullback_feature, compute_trend_ma_macd_feature, compute_trend_rider_feature]
        for fn in fns:
            a = fn(xs, symbol="BTC-USDT", now_ts_ms=NOW)
            b = fn(xs, symbol="BTC-USDT", now_ts_ms=NOW)
            self.assertEqual(a.feature_sha, b.feature_sha)
            self.assertEqual(a.signal_ts, xs[-1]["ts_ms"])
        dup = list(xs)
        dup[-1] = dict(dup[-1], ts_ms=dup[-2]["ts_ms"])
        for fn in fns:
            with self.assertRaisesRegex(ValueError, "BAR_TS_NON_MONOTONIC_OR_DUPLICATE"):
                fn(dup, symbol="BTC-USDT", now_ts_ms=NOW)

    def test_source_method_fidelity_fields_exist(self):
        xs = bars()
        a = compute_supertrend_pullback_feature(xs, symbol="BTC-USDT", now_ts_ms=NOW)
        b = compute_trend_ma_macd_feature(xs, symbol="BTC-USDT", now_ts_ms=NOW)
        c = compute_trend_rider_feature(xs, symbol="BTC-USDT", now_ts_ms=NOW)
        self.assertTrue({"supertrend", "direction", "ema50", "long_reclaim", "short_reclaim"} <= set(a.values))
        self.assertTrue({"ema_fast", "ema_slow", "hist", "hist_prev", "long_cross", "short_cross"} <= set(b.values))
        self.assertTrue({"supertrend", "direction", "ema50", "long_confirm", "short_confirm"} <= set(c.values))


if __name__ == "__main__":
    unittest.main()
