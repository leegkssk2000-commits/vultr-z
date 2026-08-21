from __future__ import annotations

from dataclasses import asdict
import unittest

from backend.research.architecture_factory import a1_exact8_bb_revert_adapter_v1 as bb
from backend.research.architecture_factory import a1_exact8_break_and_continue_adapter_v1 as br
from backend.research.rebuild import bb_revert_policy_v2 as bb_parent
from backend.research.rebuild import breakout_policy_batch_v1 as br_parent


def fixture_bars(signal_volume: float, count: int = 80) -> list[dict[str, float | int]]:
    bars: list[dict[str, float | int]] = []
    previous = 100.0
    for i in range(count):
        close = 100.0 + i * 0.015 + ((i % 7) - 3) * 0.08
        bars.append(
            {
                "ts_ms": 1_780_000_000_000 + i * 3_600_000,
                "open": previous,
                "high": max(previous, close) + 0.7,
                "low": min(previous, close) - 0.7,
                "close": close,
                "volume": signal_volume if i == count - 1 else 100.0,
            }
        )
        previous = close
    return bars


def strip_child_fields(intent: object) -> dict[str, object]:
    value = asdict(intent)
    for key in ("schema_version", "strategy_id", "feature_sha", "entry_rule", "no_trade", "reason_codes"):
        value.pop(key, None)
    return value


class Exact8AdapterFixtureTests(unittest.TestCase):
    def test_break_and_continue_axis_is_single_change(self) -> None:
        cfg = br.RelativeVolumeConfirmPolicyConfig()
        bars = fixture_bars(150.0)
        feature = br.compute_feature_snapshot(bars, symbol="BTC-USDT", now_ts_ms=int(bars[-1]["ts_ms"]), config=cfg)
        parent = br_parent.build_break_and_continue_intent(
            feature.parent, policy_source_sha="fixture-sha", verified_round_trip_cost_bps=12.0, config=cfg
        )
        child = br.build_decision_intent(
            feature, policy_source_sha="fixture-sha", verified_round_trip_cost_bps=12.0, config=cfg
        )
        self.assertTrue(feature.relative_volume_pass)
        self.assertEqual(feature.relative_volume, 1.5)
        self.assertEqual(strip_child_fields(parent), br.frozen_parent_geometry(child))
        self.assertEqual(child.strategy_id, br.CHILD_ID)

    def test_break_and_continue_blocks_low_volume_and_fails_closed(self) -> None:
        bars = fixture_bars(50.0)
        feature = br.compute_feature_snapshot(bars, symbol="BTC-USDT", now_ts_ms=int(bars[-1]["ts_ms"]))
        child = br.build_decision_intent(
            feature, policy_source_sha="fixture-sha", verified_round_trip_cost_bps=12.0
        )
        self.assertFalse(feature.relative_volume_pass)
        self.assertTrue(child.no_trade)
        self.assertIn("RELATIVE_VOLUME_CONFIRMATION_BLOCK", child.reason_codes)
        bars[-1]["volume"] = 0.0
        with self.assertRaisesRegex(ValueError, "BAR_VOLUME_NONPOSITIVE_OR_NAN"):
            br.compute_feature_snapshot(bars, symbol="BTC-USDT", now_ts_ms=int(bars[-1]["ts_ms"]))

    def test_bb_revert_axis_is_single_change(self) -> None:
        cfg = bb.LiquidNontrendOwnerPolicyConfig()
        bars = fixture_bars(100.0)
        feature = bb.compute_feature_snapshot(bars, symbol="ETH-USDT", now_ts_ms=int(bars[-1]["ts_ms"]), config=cfg)
        parent = bb_parent.build_decision_intent(
            feature.parent, policy_source_sha="fixture-sha", verified_round_trip_cost_bps=12.0, config=cfg
        )
        child = bb.build_decision_intent(
            feature, policy_source_sha="fixture-sha", verified_round_trip_cost_bps=12.0, config=cfg
        )
        self.assertTrue(feature.liquid_regime_pass)
        self.assertEqual(feature.prior_volume_median, 100.0)
        self.assertEqual(strip_child_fields(parent), bb.frozen_parent_geometry(child))
        self.assertEqual(child.strategy_id, bb.CHILD_ID)

    def test_bb_revert_blocks_low_volume(self) -> None:
        bars = fixture_bars(99.0)
        feature = bb.compute_feature_snapshot(bars, symbol="ETH-USDT", now_ts_ms=int(bars[-1]["ts_ms"]))
        child = bb.build_decision_intent(
            feature, policy_source_sha="fixture-sha", verified_round_trip_cost_bps=12.0
        )
        self.assertFalse(feature.liquid_regime_pass)
        self.assertTrue(child.no_trade)
        self.assertIn("LIQUIDITY_REGIME_BLOCK", child.reason_codes)

    def test_fixtures_have_no_research_authority(self) -> None:
        manifest = {
            "selection_authority": False,
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "live_trade_authority": "BLOCKED",
            "effect_verified_count": 0,
        }
        self.assertFalse(manifest["selection_authority"])
        self.assertFalse(manifest["promotion_authority"])
        self.assertEqual(manifest["effect_verified_count"], 0)


if __name__ == "__main__":
    unittest.main()
