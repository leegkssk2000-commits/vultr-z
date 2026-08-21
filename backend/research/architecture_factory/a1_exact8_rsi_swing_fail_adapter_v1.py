from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping, Sequence

from backend.research.architecture_factory.a1_exact8_common_adapter_v1 import (
    ChildFeatureSnapshot, child_feature, frozen_parent_geometry, positive_number, wrap_intent,
)
from backend.research.rebuild.reversal_range_policy_batch_v1 import (
    ReversalRangeConfig, build_intent, compute_feature,
)


CHILD_ID = "rsi_swing_fail__jump_regime_exclusion_v1"
POLICY_SCHEMA_VERSION = "zel.rsi_swing_fail.jump_regime_exclusion.policy.v1"


@dataclass(frozen=True)
class JumpRegimeExclusionPolicyConfig(ReversalRangeConfig):
    jump_lookback: int = 8640
    jump_quantile: float = 0.99


def _abs_log_return(previous: Mapping[str, Any], current: Mapping[str, Any]) -> float:
    return abs(math.log(positive_number(current, "close") / positive_number(previous, "close")))


def _nearest_rank(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(quantile * len(ordered)) - 1))
    return ordered[index]


def compute_feature_snapshot(
    bars: Sequence[Mapping[str, Any]], *, symbol: str, now_ts_ms: int,
    config: JumpRegimeExclusionPolicyConfig | None = None,
) -> ChildFeatureSnapshot:
    cfg = config or JumpRegimeExclusionPolicyConfig()
    if cfg.jump_lookback != 8640 or cfg.jump_quantile != 0.99:
        raise ValueError("PREREGISTERED_JUMP_AXIS_REQUIRED")
    if len(bars) < cfg.jump_lookback + 2:
        raise ValueError("JUMP_HISTORY_8640_RETURNS_REQUIRED")
    parent = compute_feature("rsi_swing_fail", bars, symbol=symbol, now_ts_ms=now_ts_ms, config=cfg)
    history = bars[-(cfg.jump_lookback + 2):-1]
    prior_returns = [_abs_log_return(history[i - 1], history[i]) for i in range(1, len(history))]
    reference = _nearest_rank(prior_returns, cfg.jump_quantile)
    signal_return = _abs_log_return(bars[-2], bars[-1])
    return child_feature(
        parent=parent, child_id=CHILD_ID, axis_name="absolute_log_return",
        axis_value=signal_return, axis_reference=reference, axis_pass=signal_return <= reference,
    )


def build_decision_intent(
    feature: ChildFeatureSnapshot, *, policy_source_sha: str,
    verified_round_trip_cost_bps: float,
    config: JumpRegimeExclusionPolicyConfig | None = None,
) -> Any:
    cfg = config or JumpRegimeExclusionPolicyConfig()
    parent = build_intent(feature.parent, policy_source_sha=policy_source_sha,
                          verified_round_trip_cost_bps=verified_round_trip_cost_bps, config=cfg)
    return wrap_intent(
        parent, feature, child_id=CHILD_ID, policy_schema=POLICY_SCHEMA_VERSION,
        entry_suffix="signal_abs_log_return_lte_prior8640_p99", pass_reason="NON_JUMP_REGIME_PASS",
        block_reason="JUMP_REGIME_BLOCK",
    )


__all__ = ["CHILD_ID", "JumpRegimeExclusionPolicyConfig", "build_decision_intent", "compute_feature_snapshot", "frozen_parent_geometry"]
