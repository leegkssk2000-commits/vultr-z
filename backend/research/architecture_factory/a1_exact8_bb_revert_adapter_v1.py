from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import json
import math
from statistics import median
from typing import Any, Mapping, Sequence

from backend.research.rebuild.bb_revert_policy_v2 import (
    BbRevertPolicyConfig,
    FeatureSnapshot as ParentFeatureSnapshot,
    build_decision_intent as build_parent_intent,
    compute_feature_snapshot as compute_parent_feature,
)


PARENT_ID = "bb_revert"
CHILD_ID = "bb_revert__liquid_nontrend_owner_v1"
POLICY_SCHEMA_VERSION = "zel.bb_revert.liquid_nontrend_owner.policy.v1"


@dataclass(frozen=True)
class LiquidNontrendOwnerPolicyConfig(BbRevertPolicyConfig):
    """Parent geometry plus the single preregistered liquidity axis."""

    liquidity_volume_lookback: int = 20


@dataclass(frozen=True)
class FeatureSnapshot:
    parent: ParentFeatureSnapshot
    signal_volume: float
    prior_volume_median: float
    liquid_regime_pass: bool
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
    config: LiquidNontrendOwnerPolicyConfig | None = None,
) -> FeatureSnapshot:
    cfg = config or LiquidNontrendOwnerPolicyConfig()
    if cfg.liquidity_volume_lookback != 20:
        raise ValueError("PREREGISTERED_LIQUIDITY_AXIS_REQUIRED")
    if len(bars) < cfg.liquidity_volume_lookback + 1:
        raise ValueError("VOLUME_WARMUP_INSUFFICIENT")
    parent = compute_parent_feature(bars, symbol=symbol, now_ts_ms=now_ts_ms, config=cfg)
    signal_volume = _positive_volume(bars[-1])
    prior = [_positive_volume(x) for x in bars[-(cfg.liquidity_volume_lookback + 1) : -1]]
    prior_median = float(median(prior))
    passed = signal_volume >= prior_median
    body = {
        "child_id": CHILD_ID,
        "parent_feature_sha": parent.feature_sha,
        "signal_ts": parent.signal_ts,
        "signal_volume": signal_volume,
        "prior_volume_median": prior_median,
        "liquidity_volume_lookback": cfg.liquidity_volume_lookback,
        "liquid_regime_pass": passed,
    }
    return FeatureSnapshot(parent, signal_volume, prior_median, passed, _digest(body))


def build_decision_intent(
    feature: FeatureSnapshot,
    *,
    policy_source_sha: str,
    verified_round_trip_cost_bps: float,
    config: LiquidNontrendOwnerPolicyConfig | None = None,
) -> Any:
    cfg = config or LiquidNontrendOwnerPolicyConfig()
    parent = build_parent_intent(
        feature.parent,
        policy_source_sha=policy_source_sha,
        verified_round_trip_cost_bps=verified_round_trip_cost_bps,
        config=cfg,
    )
    axis_reason = "LIQUIDITY_REGIME_PASS" if feature.liquid_regime_pass else "LIQUIDITY_REGIME_BLOCK"
    return replace(
        parent,
        schema_version=POLICY_SCHEMA_VERSION,
        strategy_id=CHILD_ID,
        feature_sha=feature.feature_sha,
        entry_rule=parent.entry_rule + ";signal_volume_gte_prior20_median",
        no_trade=bool(parent.no_trade or not feature.liquid_regime_pass),
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
    "LiquidNontrendOwnerPolicyConfig",
    "build_decision_intent",
    "compute_feature_snapshot",
    "frozen_parent_geometry",
]
