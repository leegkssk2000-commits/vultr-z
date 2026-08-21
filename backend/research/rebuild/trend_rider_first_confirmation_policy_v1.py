from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from backend.research.rebuild import trend_policy_batch_v1 as base


@dataclass(frozen=True)
class TrendRiderFirstConfirmationConfig(base.TrendPolicyConfig):
    pass


def compute_trend_rider_feature(
    bars: Sequence[Mapping[str, Any]],
    *,
    symbol: str,
    now_ts_ms: int,
    config: TrendRiderFirstConfirmationConfig | None = None,
) -> base.FeatureSnapshot:
    cfg = config or TrendRiderFirstConfirmationConfig()
    current = base.compute_trend_rider_feature(bars, symbol=symbol, now_ts_ms=now_ts_ms, config=cfg)
    previous = base.compute_trend_rider_feature(
        bars[:-1], symbol=symbol, now_ts_ms=int(bars[-2]["ts_ms"]), config=cfg
    )
    values = dict(current.values)
    values["persistent_long_confirm"] = bool(current.values["long_confirm"])
    values["persistent_short_confirm"] = bool(current.values["short_confirm"])
    values["long_confirm"] = bool(current.values["long_confirm"] and not previous.values["long_confirm"])
    values["short_confirm"] = bool(current.values["short_confirm"] and not previous.values["short_confirm"])
    values["transition_only"] = True
    return base._snapshot(
        "trend_rider",
        symbol,
        bars,
        now_ts_ms,
        current.close,
        current.atr,
        values,
        cfg,
    )


def build_trend_rider_intent(
    feature: base.FeatureSnapshot,
    *,
    policy_source_sha: str,
    verified_round_trip_cost_bps: float,
    config: TrendRiderFirstConfirmationConfig | None = None,
) -> Any:
    return base.build_trend_rider_intent(
        feature,
        policy_source_sha=policy_source_sha,
        verified_round_trip_cost_bps=verified_round_trip_cost_bps,
        config=config or TrendRiderFirstConfirmationConfig(),
    )
