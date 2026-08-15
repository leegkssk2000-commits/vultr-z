from __future__ import annotations

import unittest

from backend.research.rebuild.bb_revert_policy_v2 import (
    BbRevertPolicyConfig,
    build_decision_intent,
    compute_feature_snapshot,
    delayed_entry_control,
    direction_flip_control,
    evaluator_adapter_sha,
    regime_permutation_control,
    time_placebo_control,
)


HOUR_MS = 3_600_000


def _bar(ts: int, close: float, *, spread: float = 0.4) -> dict[str, float | int]:
    return {
        "ts_ms": ts,
        "open": close,
        "high": close + spread,
        "low": close - spread,
        "close": close,
    }


def _long_reclaim_bars(count: int = 80) -> list[dict[str, float | int]]:
    start = 1_700_000_000_000
    bars = [_bar(start + i * HOUR_MS, 100.0 + (0.03 if i % 2 else -0.03)) for i in range(count - 2)]
    bars.append(_bar(start + (count - 2) * HOUR_MS, 94.0, spread=0.7))
    bars.append(_bar(start + (count - 1) * HOUR_MS, 97.5, spread=0.7))
    return bars


def _short_reclaim_bars(count: int = 80) -> list[dict[str, float | int]]:
    start = 1_700_000_000_000
    bars = [_bar(start + i * HOUR_MS, 100.0 + (0.03 if i % 2 else -0.03)) for i in range(count - 2)]
    bars.append(_bar(start + (count - 2) * HOUR_MS, 106.0, spread=0.7))
    bars.append(_bar(start + (count - 1) * HOUR_MS, 102.5, spread=0.7))
    return bars


class BbRevertPolicyV2Test(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = BbRevertPolicyConfig()

    def test_planted_edge_long_reclaim_and_policy_adapter_parity(self) -> None:
        bars = _long_reclaim_bars()
        feature = compute_feature_snapshot(bars, symbol="BTCUSDT", now_ts_ms=int(bars[-1]["ts_ms"]), config=self.cfg)
        self.assertTrue(feature.reclaim_long)
        self.assertTrue(feature.non_trending)
        intent = build_decision_intent(feature, policy_source_sha="fixture-source", verified_round_trip_cost_bps=10.0, config=self.cfg)
        self.assertFalse(intent.no_trade)
        self.assertEqual(intent.side, "long")
        self.assertLess(intent.sl or 0.0, feature.close)
        self.assertGreater(intent.tp or 0.0, feature.close)
        self.assertFalse(intent.pyramiding["enabled"])
        self.assertFalse(intent.pyramiding["adverse_add"])
        self.assertEqual(intent.sha, evaluator_adapter_sha(intent))

    def test_short_reclaim_symmetry(self) -> None:
        bars = _short_reclaim_bars()
        feature = compute_feature_snapshot(bars, symbol="ETHUSDT", now_ts_ms=int(bars[-1]["ts_ms"]), config=self.cfg)
        self.assertTrue(feature.reclaim_short)
        intent = build_decision_intent(feature, policy_source_sha="fixture-source", verified_round_trip_cost_bps=10.0, config=self.cfg)
        self.assertFalse(intent.no_trade)
        self.assertEqual(intent.side, "short")
        self.assertGreater(intent.sl or 0.0, feature.close)
        self.assertLess(intent.tp or 1e9, feature.close)

    def test_duplicate_timestamp_fails_closed(self) -> None:
        bars = _long_reclaim_bars()
        bars[-1]["ts_ms"] = bars[-2]["ts_ms"]
        with self.assertRaisesRegex(ValueError, "BAR_TS_NON_MONOTONIC_OR_DUPLICATE"):
            compute_feature_snapshot(bars, symbol="BTCUSDT", now_ts_ms=int(bars[-1]["ts_ms"]), config=self.cfg)

    def test_warmup_fails_closed(self) -> None:
        bars = _long_reclaim_bars(20)
        with self.assertRaisesRegex(ValueError, "WARMUP_INSUFFICIENT"):
            compute_feature_snapshot(bars, symbol="BTCUSDT", now_ts_ms=int(bars[-1]["ts_ms"]), config=self.cfg)

    def test_stale_source_is_no_trade(self) -> None:
        bars = _long_reclaim_bars()
        feature = compute_feature_snapshot(bars, symbol="BTCUSDT", now_ts_ms=int(bars[-1]["ts_ms"]) + 3 * HOUR_MS, config=self.cfg)
        self.assertFalse(feature.fresh)
        intent = build_decision_intent(feature, policy_source_sha="fixture-source", verified_round_trip_cost_bps=10.0, config=self.cfg)
        self.assertTrue(intent.no_trade)
        self.assertIn("STALE_SOURCE_FAIL_CLOSED", intent.reason_codes)

    def test_verified_cost_authority_required(self) -> None:
        bars = _long_reclaim_bars()
        feature = compute_feature_snapshot(bars, symbol="BTCUSDT", now_ts_ms=int(bars[-1]["ts_ms"]), config=self.cfg)
        with self.assertRaisesRegex(ValueError, "VERIFIED_COST_AUTHORITY_REQUIRED"):
            build_decision_intent(feature, policy_source_sha="fixture-source", verified_round_trip_cost_bps=0.0, config=self.cfg)

    def test_structural_cost_budget_blocks_candidate(self) -> None:
        bars = _long_reclaim_bars()
        feature = compute_feature_snapshot(bars, symbol="BTCUSDT", now_ts_ms=int(bars[-1]["ts_ms"]), config=self.cfg)
        intent = build_decision_intent(feature, policy_source_sha="fixture-source", verified_round_trip_cost_bps=10_000.0, config=self.cfg)
        self.assertTrue(intent.no_trade)
        self.assertIn("STRUCTURAL_COST_BUDGET_BELOW_MIN", intent.reason_codes)

    def test_negative_controls_are_deterministic_and_non_mutating(self) -> None:
        bars = _long_reclaim_bars()
        feature = compute_feature_snapshot(bars, symbol="BTCUSDT", now_ts_ms=int(bars[-1]["ts_ms"]), config=self.cfg)
        base = build_decision_intent(feature, policy_source_sha="fixture-source", verified_round_trip_cost_bps=10.0, config=self.cfg)
        base_sha = base.sha
        flipped = direction_flip_control(base)
        placebo = time_placebo_control(base, HOUR_MS // 2)
        permuted = regime_permutation_control(base)
        delayed = delayed_entry_control(base, 1, HOUR_MS)
        self.assertEqual(base.sha, base_sha)
        self.assertEqual(flipped.side, "short")
        self.assertNotEqual(flipped.sha, base_sha)
        self.assertNotEqual(placebo.signal_ts, base.signal_ts)
        self.assertNotEqual(permuted.regime, base.regime)
        self.assertNotEqual(delayed.signal_ts, base.signal_ts)
        self.assertIn("CONTROL_DIRECTION_FLIP", flipped.reason_codes)
        self.assertIn("CONTROL_TIME_PLACEBO", placebo.reason_codes)
        self.assertIn("CONTROL_REGIME_PERMUTATION", permuted.reason_codes)
        self.assertIn("CONTROL_DELAYED_ENTRY", delayed.reason_codes)


if __name__ == "__main__":
    unittest.main()
