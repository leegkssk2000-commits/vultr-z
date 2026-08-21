from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Any, Mapping, Sequence

from backend.research.architecture_factory.a1_exact8_common_adapter_v1 import (
    ChildFeatureSnapshot, child_feature, frozen_parent_geometry, positive_number, wrap_intent,
)
from backend.research.rebuild.reversal_range_policy_batch_v1 import (
    ReversalRangeConfig, build_intent, compute_feature,
)


CHILD_ID = "fvg_revert__liquid_reclaim_confirm_v1"
POLICY_SCHEMA_VERSION = "zel.fvg_revert.liquid_reclaim_confirm.policy.v1"


@dataclass(frozen=True)
class LiquidReclaimConfirmPolicyConfig(ReversalRangeConfig):
    volume_lookback: int = 20


def compute_feature_snapshot(
    bars: Sequence[Mapping[str, Any]], *, symbol: str, now_ts_ms: int,
    config: LiquidReclaimConfirmPolicyConfig | None = None,
) -> ChildFeatureSnapshot:
    cfg = config or LiquidReclaimConfirmPolicyConfig()
    if cfg.volume_lookback != 20 or len(bars) < 21:
        raise ValueError("PREREGISTERED_VOLUME_AXIS_OR_WARMUP_REQUIRED")
    parent = compute_feature("fvg_revert", bars, symbol=symbol, now_ts_ms=now_ts_ms, config=cfg)
    signal_volume = positive_number(bars[-1], "volume")
    reference = float(median(positive_number(x, "volume") for x in bars[-21:-1]))
    return child_feature(
        parent=parent, child_id=CHILD_ID, axis_name="signal_volume",
        axis_value=signal_volume, axis_reference=reference, axis_pass=signal_volume >= reference,
    )


def build_decision_intent(
    feature: ChildFeatureSnapshot, *, policy_source_sha: str,
    verified_round_trip_cost_bps: float,
    config: LiquidReclaimConfirmPolicyConfig | None = None,
) -> Any:
    cfg = config or LiquidReclaimConfirmPolicyConfig()
    parent = build_intent(feature.parent, policy_source_sha=policy_source_sha,
                          verified_round_trip_cost_bps=verified_round_trip_cost_bps, config=cfg)
    return wrap_intent(
        parent, feature, child_id=CHILD_ID, policy_schema=POLICY_SCHEMA_VERSION,
        entry_suffix="signal_volume_gte_prior20_median", pass_reason="LIQUID_RECLAIM_PASS",
        block_reason="LIQUID_RECLAIM_BLOCK",
    )


__all__ = ["CHILD_ID", "LiquidReclaimConfirmPolicyConfig", "build_decision_intent", "compute_feature_snapshot", "frozen_parent_geometry"]
