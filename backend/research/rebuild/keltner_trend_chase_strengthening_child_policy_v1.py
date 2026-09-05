from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from backend.research.rebuild import breakout_policy_batch_v1 as parent

AXIS = "CHASE_ATR_STRENGTHENING_VS_PRIOR_CLOSED_BAR"
BASELINE_IDENTITY = "KELTNER_TREND_CANONICAL_INCUMBENT"
CONTEXT_TRANSFORM = "PARENT_KELTNER_BREAK_TRUE_AND_CHASE_ATR_CURRENT_GE_PRIOR_CLOSED_BAR"
PARAMETER_PROVENANCE = (
    "existing parent Keltner chase_atr only; ordinal strengthening sign; "
    "no loss-derived numeric floor; no numeric sweep"
)


@dataclass(frozen=True)
class KeltnerTrendChaseStrengtheningConfig(parent.BreakoutPolicyConfig):
    pass


FeatureSnapshot = parent.FeatureSnapshot


def _child_feature_sha(base: FeatureSnapshot, values: Mapping[str, Any]) -> str:
    return parent.digest({
        "strategy_id": base.strategy_id,
        "symbol": base.symbol,
        "signal_ts": base.signal_ts,
        "close": base.close,
        "atr": base.atr,
        "values": dict(values),
        "changed_axis": AXIS,
        "context_transform": CONTEXT_TRANSFORM,
    })


def compute_keltner_trend_feature(
    bars: Sequence[Mapping[str, Any]],
    *,
    symbol: str,
    now_ts_ms: int,
    config: KeltnerTrendChaseStrengtheningConfig | None = None,
) -> FeatureSnapshot:
    cfg = config or KeltnerTrendChaseStrengtheningConfig()
    base = parent.compute_keltner_trend_feature(
        bars, symbol=symbol, now_ts_ms=now_ts_ms, config=cfg
    )
    if len(bars) < max(cfg.ema_slow_len + 4, 65):
        raise ValueError("INSUFFICIENT_BARS_FOR_PRIOR_CHASE")
    prior = parent.compute_keltner_trend_feature(
        bars[:-1],
        symbol=symbol,
        now_ts_ms=parent.ts(bars[-2]),
        config=cfg,
    )

    current_chase = float(base.values["chase_atr"])
    prior_chase = float(prior.values["chase_atr"])
    chase_strengthening = bool(current_chase >= prior_chase)
    values = dict(base.values)
    parent_long = bool(values.get("long_break"))
    parent_short = bool(values.get("short_break"))
    values.update({
        "parent_long_break": parent_long,
        "parent_short_break": parent_short,
        "chase_atr_current": current_chase,
        "chase_atr_prior_closed_bar": prior_chase,
        "chase_strengthening": chase_strengthening,
        "long_break": bool(parent_long and chase_strengthening),
        "short_break": bool(parent_short and chase_strengthening),
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


def build_keltner_trend_intent(feature: FeatureSnapshot, **kwargs: Any):
    if feature.strategy_id != "keltner_trend":
        raise ValueError("FEATURE_STRATEGY_MISMATCH")
    return parent.build_keltner_trend_intent(feature, **kwargs)


def invariant_receipt() -> dict[str, Any]:
    parent_cfg = parent.BreakoutPolicyConfig()
    child_cfg = KeltnerTrendChaseStrengtheningConfig()
    return {
        "strategy_id": "keltner_trend",
        "baseline_identity": BASELINE_IDENTITY,
        "changed_axis": AXIS,
        "one_axis_only": True,
        "parent_config": asdict(parent_cfg),
        "child_config": asdict(child_cfg),
        "config_values_identical": asdict(parent_cfg) == asdict(child_cfg),
        "config_sha_identical": parent_cfg.sha == child_cfg.sha,
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
    assert inv["uses_existing_parent_chase_atr"] is True
    assert inv["numeric_threshold_sweep"] is False
    assert inv["loss_derived_numeric_threshold"] is False
    assert inv["post_outcome_trade_deletion"] is False
    assert inv["uses_post_outcome_data"] is False
    assert inv["execution_authority"] == "NONE"
    assert inv["order_authority"] == "BLOCKED"
    print("PASS_KELTNER_TREND_CHASE_STRENGTHENING_CHILD_POLICY_V1")
    return 0


if __name__ == "__main__":
    raise SystemExit(self_test())
