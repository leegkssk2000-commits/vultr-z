from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from backend.research.rebuild import trend_policy_batch_v1 as base
from backend.research.rebuild import trend_rider_first_confirmation_policy_v1 as parent


CANDIDATE_IDENTITY = "trend_rider_first_confirmation_liquid6_long_only_risk_budget_v1"


@dataclass(frozen=True)
class TrendRiderFirstConfirmationLongOnlyConfig(parent.TrendRiderFirstConfirmationConfig):
    pass


def compute_trend_rider_feature(
    bars: Sequence[Mapping[str, Any]],
    *,
    symbol: str,
    now_ts_ms: int,
    config: TrendRiderFirstConfirmationLongOnlyConfig | None = None,
) -> base.FeatureSnapshot:
    cfg = config or TrendRiderFirstConfirmationLongOnlyConfig()
    feature = parent.compute_trend_rider_feature(
        bars, symbol=symbol, now_ts_ms=now_ts_ms, config=cfg
    )
    values = dict(feature.values)
    values["parent_short_confirm"] = bool(values["short_confirm"])
    values["short_confirm"] = False
    values["long_only_admission"] = True
    values["candidate_identity"] = CANDIDATE_IDENTITY
    return base._snapshot(
        "trend_rider",
        symbol,
        bars,
        now_ts_ms,
        feature.close,
        feature.atr,
        values,
        cfg,
    )


def build_trend_rider_intent(
    feature: base.FeatureSnapshot,
    *,
    policy_source_sha: str,
    verified_round_trip_cost_bps: float,
    config: TrendRiderFirstConfirmationLongOnlyConfig | None = None,
) -> Any:
    return parent.build_trend_rider_intent(
        feature,
        policy_source_sha=policy_source_sha,
        verified_round_trip_cost_bps=verified_round_trip_cost_bps,
        config=config or TrendRiderFirstConfirmationLongOnlyConfig(),
    )

