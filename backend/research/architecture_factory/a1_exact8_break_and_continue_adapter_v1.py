from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import json
import math
from typing import Any, Mapping, Sequence

from backend.research.rebuild.breakout_policy_batch_v1 import (
    BreakoutPolicyConfig,
    FeatureSnapshot as ParentFeatureSnapshot,
    build_break_and_continue_intent,
    compute_break_and_continue_feature,
)


PARENT_ID = "break_and_continue"
CHILD_ID = "break_and_continue__relative_volume_confirm_v1"
POLICY_SCHEMA_VERSION = "zel.break_and_continue.relative_volume_confirm.policy.v1"


@dataclass(frozen=True)
class RelativeVolumeConfirmPolicyConfig(BreakoutPolicyConfig):
    """Parent geometry plus the single preregistered relative-volume axis."""

    relative_volume_floor: float = 1.0
    relative_volume_lookback: int = 20


@dataclass(frozen=True)
class FeatureSnapshot:
    parent: ParentFeatureSnapshot
    signal_volume: float
    prior_volume_mean: float
    relative_volume: float
    relative_volume_pass: bool
    feature_sha: str


def _digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _positive_volume(bar: Mapping[str, Any]) -> float:
    try:
        value = float(bar["volume"])
    except Exception as exc:
        raise ValueError("BAR_VOLUME_INVALID") from exc
    if not math.isfinite(value) or value <= 0:
        raise ValueError("BAR_VOLUME_NONPOSITIVE_OR_NAN")
    return value


def compute_feature_snapshot(
    bars: Sequence[Mapping[str, Any]],
    *,
    symbol: str,
    now_ts_ms: int,
    config: RelativeVolumeConfirmPolicyConfig | None = None,
) -> FeatureSnapshot:
    cfg = config or RelativeVolumeConfirmPolicyConfig()
    if cfg.relative_volume_floor != 1.0 or cfg.relative_volume_lookback != 20:
        raise ValueError("PREREGISTERED_RELATIVE_VOLUME_AXIS_REQUIRED")
    if len(bars) < cfg.relative_volume_lookback + 1:
        raise ValueError("VOLUME_WARMUP_INSUFFICIENT")
    parent = compute_break_and_continue_feature(
        bars, symbol=symbol, now_ts_ms=now_ts_ms, config=cfg
    )
    signal_volume = _positive_volume(bars[-1])
    prior = [_positive_volume(x) for x in bars[-(cfg.relative_volume_lookback + 1) : -1]]
    prior_mean = sum(prior) / len(prior)
    relative_volume = signal_volume / prior_mean
    passed = relative_volume >= cfg.relative_volume_floor
    body = {
        "child_id": CHILD_ID,
        "parent_feature_sha": parent.feature_sha,
        "signal_ts": parent.signal_ts,
        "signal_volume": signal_volume,
        "prior_volume_mean": prior_mean,
        "relative_volume": relative_volume,
        "relative_volume_floor": cfg.relative_volume_floor,
        "relative_volume_lookback": cfg.relative_volume_lookback,
        "relative_volume_pass": passed,
    }
    return FeatureSnapshot(parent, signal_volume, prior_mean, relative_volume, passed, _digest(body))


def build_decision_intent(
    feature: FeatureSnapshot,
    *,
    policy_source_sha: str,
    verified_round_trip_cost_bps: float,
    config: RelativeVolumeConfirmPolicyConfig | None = None,
) -> Any:
    cfg = config or RelativeVolumeConfirmPolicyConfig()
    parent = build_break_and_continue_intent(
        feature.parent,
        policy_source_sha=policy_source_sha,
        verified_round_trip_cost_bps=verified_round_trip_cost_bps,
        config=cfg,
    )
    axis_reason = (
        "RELATIVE_VOLUME_CONFIRMATION_PASS"
        if feature.relative_volume_pass
        else "RELATIVE_VOLUME_CONFIRMATION_BLOCK"
    )
    return replace(
        parent,
        schema_version=POLICY_SCHEMA_VERSION,
        strategy_id=CHILD_ID,
        feature_sha=feature.feature_sha,
        entry_rule=parent.entry_rule + ";signal_volume_over_prior20_mean_gte_1",
        no_trade=bool(parent.no_trade or not feature.relative_volume_pass),
        reason_codes=parent.reason_codes + (axis_reason,),
    )


def frozen_parent_geometry(intent: Any) -> dict[str, Any]:
    """Deterministic fixture helper; it is not promotion or alpha evidence."""
    value = asdict(intent)
    for key in ("schema_version", "strategy_id", "feature_sha", "entry_rule", "no_trade", "reason_codes"):
        value.pop(key, None)
    return value


__all__ = [
    "CHILD_ID",
    "FeatureSnapshot",
    "RelativeVolumeConfirmPolicyConfig",
    "build_decision_intent",
    "compute_feature_snapshot",
    "frozen_parent_geometry",
]
