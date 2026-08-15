from __future__ import annotations

import unittest

from backend.research.rebuild.policy_kernel_v1 import (
    control_delayed_entry, control_direction_flip, control_time_placebo, evaluator_adapter_sha,
)
from backend.research.rebuild.microstructure_policy_batch_v1 import (
    FeatureSnapshot,
    build_liquidity_sweep_intent,
    build_scalp_snap_intent,
    build_vol_spike_fade_intent,
    compute_liquidity_sweep_feature,
    compute_scalp_snap_feature,
    compute_vol_spike_fade_feature,
)

SRC = "historical-r7-microstructure-source-sha"
COST = 10.0
NOW = 20_000_000_000


def bars(n: int = 80):
    out = []
    px = 100.0
    for i in range(n):
        drift = 0.06 if i < n - 3 else (0.9 if i == n - 3 else (-0.55 if i == n - 2 else 0.20))
        o = px
        c = px + drift
        out.append({"ts_ms": NOW - (n - 1 - i) * 300_000, "open": o,
                    "high": max(o, c) + 0.25, "low": min(o, c) - 0.25,
                    "close": c, "volume": 1000.0 + 5.0 * i})
        px = c
    return out


def planted(sid: str) -> FeatureSnapshot:
    common = dict(strategy_id=sid, symbol="BTC-USDT", signal_ts=NOW, fresh=True,
                  close=100.0, atr=1.0, feature_sha=f"fixture-{sid}")
    if sid == "liquidity_sweep":
        values = {"lower_sweep": True, "upper_sweep": False, "long_reclaim": True,
                  "short_reclaim": False, "wick_atr": 1.0}
    elif sid == "scalp_snap":
        values = {"snap_long": True, "snap_short": False, "drive_atr": 1.2,
                  "reversal_atr": 0.7, "volume_ratio": 1.5}
    else:
        values = {"long_fade": True, "short_fade": False, "volume_ratio": 2.5,
                  "body_atr": 1.0, "trend_stretch_atr": 1.5}
    return FeatureSnapshot(values=values, **common)


CASES = [
    ("liquidity_sweep", build_liquidity_sweep_intent),
    ("scalp_snap", build_scalp_snap_intent),
    ("vol_spike_fade", build_vol_spike_fade_intent),
]


class MicrostructurePolicyBatchV1Tests(unittest.TestCase):
    def test_planted_edge_parity_controls_and_risk_recompute(self):
        for sid, builder in CASES:
            with self.subTest(strategy_id=sid):
                intent = builder(planted(sid), policy_source_sha=SRC, verified_round_trip_cost_bps=COST)
                self.assertFalse(intent.no_trade)
                self.assertEqual(intent.side, "long")
                self.assertGreaterEqual(intent.cost_budget_ratio, 1.25)
                self.assertEqual(intent.pyramiding, {"enabled": False, "adverse_add": False})
                self.assertEqual(evaluator_adapter_sha(intent), intent.sha)
                risk_bps = abs(intent.sl - 100.0) / 100.0 * 10_000.0
                self.assertAlmostEqual(risk_bps, intent.risk_size["risk_distance_bps"])
                self.assertEqual(control_direction_flip(intent).side, "short")
                self.assertNotEqual(control_time_placebo(intent, 7 * 300_000).sha, intent.sha)
                self.assertNotEqual(control_delayed_entry(intent, 2, 300_000).sha, intent.sha)

    def test_stale_cost_and_strategy_mismatch_fail_closed(self):
        for sid, builder in CASES:
            with self.subTest(strategy_id=sid):
                x = planted(sid)
                stale = FeatureSnapshot(x.strategy_id, x.symbol, x.signal_ts, False, x.close, x.atr, x.values, x.feature_sha)
                intent = builder(stale, policy_source_sha=SRC, verified_round_trip_cost_bps=COST)
                self.assertTrue(intent.no_trade)
                self.assertIn("STALE_SOURCE_FAIL_CLOSED", intent.reason_codes)
                with self.assertRaisesRegex(ValueError, "VERIFIED_COST_AUTHORITY_REQUIRED"):
                    builder(planted(sid), policy_source_sha=SRC, verified_round_trip_cost_bps=0.0)
                wrong_sid = "scalp_snap" if sid != "scalp_snap" else "liquidity_sweep"
                with self.assertRaisesRegex(ValueError, "FEATURE_STRATEGY_MISMATCH"):
                    builder(planted(wrong_sid), policy_source_sha=SRC, verified_round_trip_cost_bps=COST)

    def test_feature_ssot_determinism_closed_bar_and_duplicate_guard(self):
        xs = bars()
        fns = [compute_liquidity_sweep_feature, compute_scalp_snap_feature, compute_vol_spike_fade_feature]
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

    def test_source_method_fields_exist(self):
        xs = bars()
        a = compute_liquidity_sweep_feature(xs, symbol="BTC-USDT", now_ts_ms=NOW)
        b = compute_scalp_snap_feature(xs, symbol="BTC-USDT", now_ts_ms=NOW)
        c = compute_vol_spike_fade_feature(xs, symbol="BTC-USDT", now_ts_ms=NOW)
        self.assertTrue({"upper_sweep", "lower_sweep", "long_reclaim", "short_reclaim"} <= set(a.values))
        self.assertTrue({"snap_long", "snap_short", "drive_atr", "reversal_atr", "volume_ratio"} <= set(b.values))
        self.assertTrue({"long_fade", "short_fade", "volume_ratio", "body_atr", "trend_stretch_atr"} <= set(c.values))


if __name__ == "__main__":
    unittest.main()
