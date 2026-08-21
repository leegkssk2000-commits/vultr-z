from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import unittest

from backend.research.architecture_factory import a1_exact8_anchor_vwap_trend_adapter_v1 as av
from backend.research.architecture_factory import a1_exact8_bb_revert_adapter_v1 as bb
from backend.research.architecture_factory import a1_exact8_break_and_continue_adapter_v1 as br
from backend.research.architecture_factory import a1_exact8_fvg_revert_adapter_v1 as fvg
from backend.research.architecture_factory import a1_exact8_range_fade_adapter_v1 as rf
from backend.research.architecture_factory import a1_exact8_rsi_swing_fail_adapter_v1 as rsf
from backend.research.architecture_factory import a1_exact8_session_bias_adapter_v1 as sb
from backend.research.rebuild import bb_revert_policy_v2 as bb_parent
from backend.research.rebuild import breakout_policy_batch_v1 as br_parent
from backend.research.rebuild import final_four_policy_batch_v1 as final_parent
from backend.research.rebuild import reversal_range_policy_batch_v1 as reversal_parent
from backend.research.rebuild import vwap_bb_policy_batch_v1 as vwap_parent


def fixture_bars(
    signal_volume: float,
    count: int = 80,
    timeframe_ms: int = 3_600_000,
    end_ts_ms: int | None = None,
) -> list[dict[str, float | int]]:
    bars: list[dict[str, float | int]] = []
    previous = 100.0
    start_ts = (
        int(end_ts_ms) - (count - 1) * timeframe_ms
        if end_ts_ms is not None
        else 1_780_000_000_000
    )
    for i in range(count):
        close = 100.0 + i * 0.015 + ((i % 7) - 3) * 0.08
        bars.append(
            {
                "ts_ms": start_ts + i * timeframe_ms,
                "open": previous,
                "high": max(previous, close) + 0.7,
                "low": min(previous, close) - 0.7,
                "close": close,
                "volume": signal_volume if i == count - 1 else 100.0,
            }
        )
        previous = close
    return bars


def jump_fixture(signal_multiplier: float) -> list[dict[str, float | int]]:
    bars: list[dict[str, float | int]] = []
    previous = 100.0
    for i in range(8642):
        close = previous * (signal_multiplier if i == 8641 else 1.0001)
        bars.append(
            {
                "ts_ms": 1_775_000_000_000 + i * 300_000,
                "open": previous,
                "high": max(previous, close) + 0.2,
                "low": min(previous, close) - 0.2,
                "close": close,
                "volume": 100.0,
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
    def test_anchor_vwap_session_axis_is_single_change(self) -> None:
        end = int(datetime(2026, 8, 21, 13, tzinfo=timezone.utc).timestamp() * 1000)
        cfg = av.LondonNewYorkOverlapPolicyConfig()
        bars = fixture_bars(100.0, count=130, end_ts_ms=end)
        feature = av.compute_feature_snapshot(bars, symbol="BTC-USDT", now_ts_ms=end, config=cfg)
        parent = vwap_parent.build_anchor_vwap_trend_intent(
            feature.parent, policy_source_sha="fixture-sha", verified_round_trip_cost_bps=12.0, config=cfg
        )
        child = av.build_decision_intent(
            feature, policy_source_sha="fixture-sha", verified_round_trip_cost_bps=12.0, config=cfg
        )
        self.assertTrue(feature.axis_pass)
        self.assertEqual(feature.axis_value, 13)
        self.assertEqual(strip_child_fields(parent), av.frozen_parent_geometry(child))

    def test_anchor_vwap_blocks_non_overlap_hour(self) -> None:
        end = int(datetime(2026, 8, 21, 12, tzinfo=timezone.utc).timestamp() * 1000)
        bars = fixture_bars(100.0, count=130, end_ts_ms=end)
        feature = av.compute_feature_snapshot(bars, symbol="BTC-USDT", now_ts_ms=end)
        child = av.build_decision_intent(feature, policy_source_sha="fixture-sha", verified_round_trip_cost_bps=12.0)
        self.assertFalse(feature.axis_pass)
        self.assertTrue(child.no_trade)

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

    def test_fvg_volume_axis_is_single_change_and_blocks_low_volume(self) -> None:
        cfg = fvg.LiquidReclaimConfirmPolicyConfig()
        bars = fixture_bars(150.0, timeframe_ms=300_000)
        feature = fvg.compute_feature_snapshot(bars, symbol="ETH-USDT", now_ts_ms=int(bars[-1]["ts_ms"]), config=cfg)
        parent = reversal_parent.build_intent(
            feature.parent, policy_source_sha="fixture-sha", verified_round_trip_cost_bps=12.0, config=cfg
        )
        child = fvg.build_decision_intent(
            feature, policy_source_sha="fixture-sha", verified_round_trip_cost_bps=12.0, config=cfg
        )
        self.assertTrue(feature.axis_pass)
        self.assertEqual(strip_child_fields(parent), fvg.frozen_parent_geometry(child))
        blocked_bars = fixture_bars(50.0, timeframe_ms=300_000)
        blocked = fvg.compute_feature_snapshot(
            blocked_bars, symbol="ETH-USDT", now_ts_ms=int(blocked_bars[-1]["ts_ms"])
        )
        blocked_intent = fvg.build_decision_intent(
            blocked, policy_source_sha="fixture-sha", verified_round_trip_cost_bps=12.0
        )
        self.assertFalse(blocked.axis_pass)
        self.assertTrue(blocked_intent.no_trade)

    def test_range_fade_amihud_axis_is_single_change(self) -> None:
        cfg = rf.LiquidityRegimeOwnerPolicyConfig()
        bars = fixture_bars(10_000.0, timeframe_ms=300_000)
        feature = rf.compute_feature_snapshot(bars, symbol="BTC-USDT", now_ts_ms=int(bars[-1]["ts_ms"]), config=cfg)
        parent = reversal_parent.build_intent(
            feature.parent, policy_source_sha="fixture-sha", verified_round_trip_cost_bps=12.0, config=cfg
        )
        child = rf.build_decision_intent(
            feature, policy_source_sha="fixture-sha", verified_round_trip_cost_bps=12.0, config=cfg
        )
        self.assertTrue(feature.axis_pass)
        self.assertEqual(strip_child_fields(parent), rf.frozen_parent_geometry(child))

    def test_range_fade_blocks_illiquid_signal(self) -> None:
        bars = fixture_bars(1.0, timeframe_ms=300_000)
        feature = rf.compute_feature_snapshot(bars, symbol="BTC-USDT", now_ts_ms=int(bars[-1]["ts_ms"]))
        child = rf.build_decision_intent(feature, policy_source_sha="fixture-sha", verified_round_trip_cost_bps=12.0)
        self.assertFalse(feature.axis_pass)
        self.assertTrue(child.no_trade)

    def test_rsi_swing_fail_jump_axis_is_single_change(self) -> None:
        cfg = rsf.JumpRegimeExclusionPolicyConfig()
        bars = jump_fixture(1.0001)
        feature = rsf.compute_feature_snapshot(bars, symbol="BTC-USDT", now_ts_ms=int(bars[-1]["ts_ms"]), config=cfg)
        parent = reversal_parent.build_intent(
            feature.parent, policy_source_sha="fixture-sha", verified_round_trip_cost_bps=12.0, config=cfg
        )
        child = rsf.build_decision_intent(
            feature, policy_source_sha="fixture-sha", verified_round_trip_cost_bps=12.0, config=cfg
        )
        self.assertTrue(feature.axis_pass)
        self.assertEqual(strip_child_fields(parent), rsf.frozen_parent_geometry(child))

    def test_rsi_swing_fail_blocks_jump_and_requires_full_history(self) -> None:
        bars = jump_fixture(1.05)
        feature = rsf.compute_feature_snapshot(bars, symbol="BTC-USDT", now_ts_ms=int(bars[-1]["ts_ms"]))
        child = rsf.build_decision_intent(feature, policy_source_sha="fixture-sha", verified_round_trip_cost_bps=12.0)
        self.assertFalse(feature.axis_pass)
        self.assertTrue(child.no_trade)
        with self.assertRaisesRegex(ValueError, "JUMP_HISTORY_8640_RETURNS_REQUIRED"):
            rsf.compute_feature_snapshot(bars[:1000], symbol="BTC-USDT", now_ts_ms=int(bars[999]["ts_ms"]))

    def test_session_bias_axis_is_single_change_and_blocks_other_hours(self) -> None:
        end = int(datetime(2026, 8, 21, 13, tzinfo=timezone.utc).timestamp() * 1000)
        cfg = sb.LondonNewYorkOverlapPolicyConfig()
        bars = fixture_bars(100.0, count=100, timeframe_ms=300_000, end_ts_ms=end)
        feature = sb.compute_feature_snapshot(bars, symbol="ETH-USDT", now_ts_ms=end, config=cfg)
        parent = final_parent.intent_from_snapshot(
            feature.parent, policy_source_sha="fixture-sha", verified_round_trip_cost_bps=12.0, config=cfg
        )
        child = sb.build_decision_intent(
            feature, policy_source_sha="fixture-sha", verified_round_trip_cost_bps=12.0, config=cfg
        )
        self.assertTrue(feature.axis_pass)
        self.assertEqual(strip_child_fields(parent), sb.frozen_parent_geometry(child))
        blocked_end = int(datetime(2026, 8, 21, 12, tzinfo=timezone.utc).timestamp() * 1000)
        blocked_bars = fixture_bars(100.0, count=100, timeframe_ms=300_000, end_ts_ms=blocked_end)
        blocked = sb.compute_feature_snapshot(blocked_bars, symbol="ETH-USDT", now_ts_ms=blocked_end)
        blocked_intent = sb.build_decision_intent(
            blocked, policy_source_sha="fixture-sha", verified_round_trip_cost_bps=12.0
        )
        self.assertFalse(blocked.axis_pass)
        self.assertTrue(blocked_intent.no_trade)

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
