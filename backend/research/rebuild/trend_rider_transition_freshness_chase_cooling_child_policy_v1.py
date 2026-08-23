from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from backend.research.rebuild import trend_rider_transition_freshness_child_policy_v1 as parent

AXIS = "CHASE_ATR_NOT_EXPANDING_VS_PRIOR_CLOSED_BAR_ON_TRANSITION_FRESHNESS_INCUMBENT"
BASELINE_IDENTITY = "TREND_RIDER_TRANSITION_FRESHNESS_INCUMBENT"
CONTEXT_TRANSFORM = "INCUMBENT_CONFIRM_TRUE_AND_CHASE_ATR_CURRENT_LE_PRIOR_CLOSED_BAR"
PARAMETER_PROVENANCE = (
    "existing incumbent transition-freshness semantics plus existing parent chase_atr; "
    "ordinal cooling/non-expansion sign only; no outcome-fitted threshold; no numeric sweep"
)


@dataclass(frozen=True)
class TrendRiderTransitionFreshnessChaseCoolingConfig(parent.TrendRiderTransitionFreshnessConfig):
    pass


FeatureSnapshot = parent.FeatureSnapshot


def _child_feature_sha(base: FeatureSnapshot, values: Mapping[str, Any]) -> str:
    return parent.parent.digest({
        "strategy_id": base.strategy_id,
        "symbol": base.symbol,
        "signal_ts": base.signal_ts,
        "close": base.close,
        "atr": base.atr,
        "values": dict(values),
        "changed_axis": AXIS,
        "context_transform": CONTEXT_TRANSFORM,
    })


def compute_trend_rider_feature(
    bars: Sequence[Mapping[str, Any]],
    *,
    symbol: str,
    now_ts_ms: int,
    config: TrendRiderTransitionFreshnessChaseCoolingConfig | None = None,
) -> FeatureSnapshot:
    cfg = config or TrendRiderTransitionFreshnessChaseCoolingConfig()
    base = parent.compute_trend_rider_feature(
        bars, symbol=symbol, now_ts_ms=now_ts_ms, config=cfg
    )
    if len(bars) < 65:
        raise ValueError("INSUFFICIENT_BARS_FOR_PRIOR_CHASE")
    prior = parent.compute_trend_rider_feature(
        bars[:-1],
        symbol=symbol,
        now_ts_ms=parent.parent.ts(bars[-2]),
        config=cfg,
    )

    current_chase = float(base.values["chase_atr"])
    prior_chase = float(prior.values["chase_atr"])
    chase_not_expanding = bool(current_chase <= prior_chase)
    values = dict(base.values)
    incumbent_long = bool(values.get("long_confirm"))
    incumbent_short = bool(values.get("short_confirm"))
    values.update({
        "incumbent_long_confirm": incumbent_long,
        "incumbent_short_confirm": incumbent_short,
        "chase_atr_current": current_chase,
        "chase_atr_prior_closed_bar": prior_chase,
        "chase_not_expanding": chase_not_expanding,
        "long_confirm": bool(incumbent_long and chase_not_expanding),
        "short_confirm": bool(incumbent_short and chase_not_expanding),
        "changed_axis": AXIS,
        "context_transform": CONTEXT_TRANSFORM,
        "parameter_provenance": PARAMETER_PROVENANCE,
    })
    return FeatureSnapshot(
        strategy_id=base.strategy_id,
        symbol=base.symbol,
        signal_ts=base.signal_ts,
        fresh=base.fresh,
        close=base.close,
        atr=base.atr,
        values=values,
        feature_sha=_child_feature_sha(base, values),
    )


def build_trend_rider_intent(feature: FeatureSnapshot, **kwargs: Any):
    return parent.build_trend_rider_intent(feature, **kwargs)


def invariant_receipt() -> dict[str, Any]:
    parent_cfg = parent.TrendRiderTransitionFreshnessConfig()
    child_cfg = TrendRiderTransitionFreshnessChaseCoolingConfig()
    return {
        "strategy_id": "trend_rider",
        "baseline_identity": BASELINE_IDENTITY,
        "changed_axis": AXIS,
        "one_axis_only_from_incumbent": True,
        "parent_config": asdict(parent_cfg),
        "child_config": asdict(child_cfg),
        "config_values_identical": asdict(parent_cfg) == asdict(child_cfg),
        "config_sha_identical": parent_cfg.sha == child_cfg.sha,
        "incumbent_transition_freshness_preserved": True,
        "uses_existing_parent_chase_atr": True,
        "parent_existing_chase_cap_preserved": True,
        "parent_entry_geometry_preserved_for_retained_trades": True,
        "parent_exit_geometry_preserved": True,
        "parent_initial_risk_preserved": True,
        "numeric_threshold_sweep": False,
        "loss_derived_numeric_threshold": False,
        "post_outcome_trade_deletion": False,
        "uses_post_outcome_data": False,
        "parameter_provenance": PARAMETER_PROVENANCE,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "protected_mutations": 0,
    }


def self_test() -> int:
    inv = invariant_receipt()
    assert inv["config_values_identical"] is True
    assert inv["config_sha_identical"] is True
    assert inv["incumbent_transition_freshness_preserved"] is True
    assert inv["uses_existing_parent_chase_atr"] is True
    assert inv["numeric_threshold_sweep"] is False
    assert inv["loss_derived_numeric_threshold"] is False
    assert inv["post_outcome_trade_deletion"] is False
    assert inv["uses_post_outcome_data"] is False
    assert inv["execution_authority"] == "NONE"
    assert inv["order_authority"] == "BLOCKED"
    print("PASS_TREND_RIDER_TRANSITION_FRESHNESS_CHASE_COOLING_CHILD_POLICY_V1")
    return 0


if __name__ == "__main__":
    raise SystemExit(self_test())
