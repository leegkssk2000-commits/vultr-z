from __future__ import annotations

from dataclasses import dataclass
import math
from statistics import median
from typing import Any, Mapping, Sequence

from backend.research.architecture_factory.a1_exact8_common_adapter_v1 import (
    ChildFeatureSnapshot, child_feature, frozen_parent_geometry, positive_number, wrap_intent,
)
from backend.research.rebuild.reversal_range_policy_batch_v1 import (
    ReversalRangeConfig, build_intent, compute_feature,
)


CHILD_ID = "range_fade__liquidity_regime_owner_v1"
POLICY_SCHEMA_VERSION = "zel.range_fade.liquidity_regime_owner.policy.v1"


@dataclass(frozen=True)
class LiquidityRegimeOwnerPolicyConfig(ReversalRangeConfig):
    amihud_lookback: int = 20


def _amihud(previous: Mapping[str, Any], current: Mapping[str, Any]) -> float:
    prev_close = positive_number(previous, "close")
    close = positive_number(current, "close")
    volume = positive_number(current, "volume")
    return abs(math.log(close / prev_close)) / (close * volume)


def compute_feature_snapshot(
    bars: Sequence[Mapping[str, Any]], *, symbol: str, now_ts_ms: int,
    config: LiquidityRegimeOwnerPolicyConfig | None = None,
) -> ChildFeatureSnapshot:
    cfg = config or LiquidityRegimeOwnerPolicyConfig()
    if cfg.amihud_lookback != 20 or len(bars) < 22:
        raise ValueError("PREREGISTERED_AMIHUD_AXIS_OR_WARMUP_REQUIRED")
    parent = compute_feature("range_fade", bars, symbol=symbol, now_ts_ms=now_ts_ms, config=cfg)
    window = bars[-22:]
    prior_values = [_amihud(window[i - 1], window[i]) for i in range(1, 21)]
    signal_value = _amihud(window[-2], window[-1])
    reference = float(median(prior_values))
    return child_feature(
        parent=parent, child_id=CHILD_ID, axis_name="amihud_proxy",
        axis_value=signal_value, axis_reference=reference, axis_pass=signal_value <= reference,
    )


def build_decision_intent(
    feature: ChildFeatureSnapshot, *, policy_source_sha: str,
    verified_round_trip_cost_bps: float,
    config: LiquidityRegimeOwnerPolicyConfig | None = None,
) -> Any:
    cfg = config or LiquidityRegimeOwnerPolicyConfig()
    parent = build_intent(feature.parent, policy_source_sha=policy_source_sha,
                          verified_round_trip_cost_bps=verified_round_trip_cost_bps, config=cfg)
    return wrap_intent(
        parent, feature, child_id=CHILD_ID, policy_schema=POLICY_SCHEMA_VERSION,
        entry_suffix="signal_amihud_lte_prior20_median", pass_reason="LIQUIDITY_REGIME_PASS",
        block_reason="ILLIQUID_REGIME_BLOCK",
    )


__all__ = ["CHILD_ID", "LiquidityRegimeOwnerPolicyConfig", "build_decision_intent", "compute_feature_snapshot", "frozen_parent_geometry"]
