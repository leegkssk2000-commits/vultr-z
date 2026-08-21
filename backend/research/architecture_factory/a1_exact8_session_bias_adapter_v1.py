from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from backend.research.architecture_factory.a1_exact8_common_adapter_v1 import (
    ChildFeatureSnapshot, child_feature, frozen_parent_geometry, wrap_intent,
)
from backend.research.rebuild.final_four_policy_batch_v1 import (
    FinalFourConfig, features, intent_from_snapshot,
)


CHILD_ID = "session_bias__lny_overlap_owner_v1"
POLICY_SCHEMA_VERSION = "zel.session_bias.lny_overlap_owner.policy.v1"
ALLOWED_UTC_HOURS = (13, 14, 15)


@dataclass(frozen=True)
class LondonNewYorkOverlapPolicyConfig(FinalFourConfig):
    allowed_utc_hours: tuple[int, ...] = ALLOWED_UTC_HOURS


def compute_feature_snapshot(
    bars: Sequence[Mapping[str, Any]], *, symbol: str, now_ts_ms: int,
    config: LondonNewYorkOverlapPolicyConfig | None = None,
) -> ChildFeatureSnapshot:
    cfg = config or LondonNewYorkOverlapPolicyConfig()
    if tuple(cfg.allowed_utc_hours) != ALLOWED_UTC_HOURS:
        raise ValueError("PREREGISTERED_SESSION_AXIS_REQUIRED")
    parent = features("session_bias", bars, symbol=symbol, now_ms=now_ts_ms, config=cfg)
    hour = datetime.fromtimestamp(parent.signal_ts / 1000.0, tz=timezone.utc).hour
    return child_feature(
        parent=parent, child_id=CHILD_ID, axis_name="signal_utc_hour",
        axis_value=hour, axis_reference="13,14,15", axis_pass=hour in ALLOWED_UTC_HOURS,
    )


def build_decision_intent(
    feature: ChildFeatureSnapshot, *, policy_source_sha: str,
    verified_round_trip_cost_bps: float,
    config: LondonNewYorkOverlapPolicyConfig | None = None,
) -> Any:
    cfg = config or LondonNewYorkOverlapPolicyConfig()
    parent = intent_from_snapshot(feature.parent, policy_source_sha=policy_source_sha,
                                  verified_round_trip_cost_bps=verified_round_trip_cost_bps, config=cfg)
    return wrap_intent(
        parent, feature, child_id=CHILD_ID, policy_schema=POLICY_SCHEMA_VERSION,
        entry_suffix="signal_utc_hour_in_13_14_15", pass_reason="LNY_OVERLAP_PASS",
        block_reason="LNY_OVERLAP_BLOCK",
    )


__all__ = ["CHILD_ID", "LondonNewYorkOverlapPolicyConfig", "build_decision_intent", "compute_feature_snapshot", "frozen_parent_geometry"]
