from __future__ import annotations

import unittest

from backend.research.rebuild.turtle_trend_policy_v2 import (
    TurtleTrendPolicyConfig,
    build_decision_intent,
    compute_feature_snapshot,
    delayed_entry_control,
    direction_flip_control,
    evaluator_adapter_sha,
    time_placebo_control,
)


HOUR_MS = 3_600_000


def _bar(ts: int, close: float, *, spread: float = 0.6) -> dict[str, float | int]:
    return {
        "ts_ms": ts,
        "open": close - 0.05,
        "high": close + spread,
        "low": close - spread,
        "close": close,
    }


def _long_breakout_bars(count: int = 80) -> list[dict[str, float | int]]:
    bars: list[dict[str, float | int]] = []
    start = 1_700_000_000_000
    for idx in range(count - 1):
        close = 100.0 + idx * 0.01
        bars.append(_bar(start + idx * HOUR_MS, close))
    bars.append(_bar(start + (count - 1) * HOUR_MS, 104.0, spread=0.7))
    return bars


def _short_breakout_bars(count: int = 80) -> list[dict[str, float | int]]:
    bars: list[dict[str, float | int]] = []
    start = 1_700_000_000_000
    for idx in range(count - 1):
        close = 104.0 - idx * 0.01
        bars.append(_bar(start + idx * HOUR_MS, close))
    bars.append(_bar(start + (count - 1) * HOUR_MS, 99.0, spread=0.7))
    return bars


class TurtleTrendPolicyV2Test(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = TurtleTrendPolicyConfig()

    def test_planted_edge_long_breakout_and_policy_adapter_parity(self) -> None:
        bars = _long_breakout_bars()
        feature = compute_feature_snapshot(
            bars,
            symbol="BTCUSDT",
            now_ts_ms=int(bars[-1]["ts_ms"]),
            config=self.cfg,
        )
        self.assertTrue(feature.breakout_long)
        self.assertTrue(feature.trend_long)
        self.assertFalse(feature.breakout_short)
        intent = build_decision_intent(
            feature,
            policy_source_sha="fixture-source-sha",
            verified_round_trip_cost_bps=10.0,
            config=self.cfg,
        )
        self.assertFalse(intent.no_trade)
        self.assertEqual(intent.side, "long")
        self.assertGreater(intent.sl or 0.0, 0.0)
        self.assertLess(intent.sl or 0.0, feature.close)
        self.assertIsNone(intent.tp)
        self.assertTrue(intent.runner["enabled"])
        self.assertTrue(intent.pyramiding["profitable_only"])
        self.assertFalse(intent.pyramiding["adverse_add"])
        self.assertGreaterEqual(intent.cost_budget_ratio, self.cfg.min_cost_budget_ratio)
        self.assertEqual(intent.sha, evaluator_adapter_sha(intent))

    def test_short_breakout_symmetry(self) -> None:
        bars = _short_breakout_bars()
        feature = compute_feature_snapshot(
            bars,
            symbol="ETHUSDT",
            now_ts_ms=int(bars[-1]["ts_ms"]),
            config=self.cfg,
        )
        intent = build_decision_intent(
            feature,
            policy_source_sha="fixture-source-sha",
            verified_round_trip_cost_bps=10.0,
            config=self.cfg,
        )
        self.assertFalse(intent.no_trade)
        self.assertEqual(intent.side, "short")
        self.assertGreater(intent.sl or 0.0, feature.close)

    def test_signal_bar_is_excluded_from_its_own_donchian_channel(self) -> None:
        bars = _long_breakout_bars()
        signal_high = float(bars[-1]["high"])
        feature = compute_feature_snapshot(
            bars,
            symbol="BTCUSDT",
            now_ts_ms=int(bars[-1]["ts_ms"]),
            config=self.cfg,
        )
        self.assertLess(feature.entry_high, signal_high)
        self.assertTrue(feature.breakout_long)

    def test_duplicate_and_non_monotonic_timestamp_fail_closed(self) -> None:
        bars = _long_breakout_bars()
        bars[-1]["ts_ms"] = bars[-2]["ts_ms"]
        with self.assertRaisesRegex(ValueError, "BAR_TS_NON_MONOTONIC_OR_DUPLICATE"):
            compute_feature_snapshot(
                bars,
                symbol="BTCUSDT",
                now_ts_ms=int(bars[-1]["ts_ms"]),
                config=self.cfg,
            )

    def test_warmup_fail_closed(self) -> None:
        bars = _long_breakout_bars(count=20)
        with self.assertRaisesRegex(ValueError, "WARMUP_INSUFFICIENT"):
            compute_feature_snapshot(
                bars,
                symbol="BTCUSDT",
                now_ts_ms=int(bars[-1]["ts_ms"]),
                config=self.cfg,
            )

    def test_stale_source_returns_no_trade(self) -> None:
        bars = _long_breakout_bars()
        feature = compute_feature_snapshot(
            bars,
            symbol="BTCUSDT",
            now_ts_ms=int(bars[-1]["ts_ms"]) + 3 * HOUR_MS,
            config=self.cfg,
        )
        self.assertFalse(feature.fresh)
        intent = build_decision_intent(
            feature,
            policy_source_sha="fixture-source-sha",
            verified_round_trip_cost_bps=10.0,
            config=self.cfg,
        )
        self.assertTrue(intent.no_trade)
        self.assertIn("STALE_SOURCE_FAIL_CLOSED", intent.reason_codes)

    def test_cost_budget_cannot_be_rescued_by_lowering_outcome_logic(self) -> None:
        bars = _long_breakout_bars()
        feature = compute_feature_snapshot(
            bars,
            symbol="BTCUSDT",
            now_ts_ms=int(bars[-1]["ts_ms"]),
            config=self.cfg,
        )
        intent = build_decision_intent(
            feature,
            policy_source_sha="fixture-source-sha",
            verified_round_trip_cost_bps=10_000.0,
            config=self.cfg,
        )
        self.assertTrue(intent.no_trade)
        self.assertIn("STRUCTURAL_COST_BUDGET_BELOW_MIN", intent.reason_codes)

    def test_controls_are_deterministic_and_do_not_mutate_base_intent(self) -> None:
        bars = _long_breakout_bars()
        feature = compute_feature_snapshot(
            bars,
            symbol="BTCUSDT",
            now_ts_ms=int(bars[-1]["ts_ms"]),
            config=self.cfg,
        )
        base = build_decision_intent(
            feature,
            policy_source_sha="fixture-source-sha",
            verified_round_trip_cost_bps=10.0,
            config=self.cfg,
        )
        base_sha = base.sha
        flipped = direction_flip_control(base)
        placebo = time_placebo_control(base, HOUR_MS // 2)
        delayed = delayed_entry_control(base, 1, HOUR_MS)
        self.assertEqual(base.sha, base_sha)
        self.assertEqual(flipped.side, "short")
        self.assertNotEqual(flipped.sha, base_sha)
        self.assertNotEqual(placebo.signal_ts, base.signal_ts)
        self.assertNotEqual(delayed.signal_ts, base.signal_ts)
        self.assertIn("CONTROL_DIRECTION_FLIP", flipped.reason_codes)
        self.assertIn("CONTROL_TIME_PLACEBO", placebo.reason_codes)
        self.assertIn("CONTROL_DELAYED_ENTRY", delayed.reason_codes)

    def test_missing_verified_cost_authority_fails_closed(self) -> None:
        bars = _long_breakout_bars()
        feature = compute_feature_snapshot(
            bars,
            symbol="BTCUSDT",
            now_ts_ms=int(bars[-1]["ts_ms"]),
            config=self.cfg,
        )
        with self.assertRaisesRegex(ValueError, "VERIFIED_COST_AUTHORITY_REQUIRED"):
            build_decision_intent(
                feature,
                policy_source_sha="fixture-source-sha",
                verified_round_trip_cost_bps=0.0,
                config=self.cfg,
            )


if __name__ == "__main__":
    unittest.main()
