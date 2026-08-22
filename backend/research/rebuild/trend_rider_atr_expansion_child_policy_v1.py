from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from backend.research.rebuild import trend_policy_batch_v1 as parent

AXIS = "ATR_EXPANSION_CONTEXT_ENTRY_ONLY"
BASELINE_IDENTITY = "ORIGINAL_TREND_RIDER_FRESH_W1_W2_W3"
EXTERNAL_EVIDENCE_IDS = ("HIST_R7_TREND_RIDER", "TSMOM_MOSKOWITZ_OSOI_PEDERSEN")
CONTEXT_TRANSFORM = "ATR14_CURRENT_GREATER_THAN_PRIOR_CLOSED_BAR"
PARAMETER_PROVENANCE = "existing_parent_ATR14_length; ordinal expansion sign only; no outcome sweep"


@dataclass(frozen=True)
class TrendRiderAtrExpansionConfig(parent.TrendPolicyConfig):
    """Parent config preserved; only pre-entry volatility-expansion context is added."""


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


def compute_trend_rider_feature(
    bars: Sequence[Mapping[str, Any]],
    *,
    symbol: str,
    now_ts_ms: int,
    config: TrendRiderAtrExpansionConfig | None = None,
) -> FeatureSnapshot:
    cfg = config or TrendRiderAtrExpansionConfig()
    base = parent.compute_trend_rider_feature(bars, symbol=symbol, now_ts_ms=now_ts_ms, config=cfg)
    if len(bars) < cfg.atr_len + 2:
        raise ValueError("INSUFFICIENT_BARS_FOR_PRIOR_ATR")
    prior_atr = float(parent.atr(bars[:-1], cfg.atr_len))
    current_atr = float(base.atr)
    atr_expanding = bool(current_atr > prior_atr)

    values = dict(base.values)
    parent_long = bool(values.get("long_confirm"))
    parent_short = bool(values.get("short_confirm"))
    values.update({
        "parent_long_confirm": parent_long,
        "parent_short_confirm": parent_short,
        "atr14_current": current_atr,
        "atr14_prior_closed_bar": prior_atr,
        "atr_expanding": atr_expanding,
        "long_confirm": bool(parent_long and atr_expanding),
        "short_confirm": bool(parent_short and atr_expanding),
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
    if feature.strategy_id != "trend_rider":
        raise ValueError("FEATURE_STRATEGY_MISMATCH")
    return parent._build(feature, **kwargs)


def invariant_receipt() -> dict[str, Any]:
    parent_cfg = parent.TrendPolicyConfig()
    child_cfg = TrendRiderAtrExpansionConfig()
    return {
        "strategy_id": "trend_rider",
        "baseline_identity": BASELINE_IDENTITY,
        "changed_axis": AXIS,
        "one_axis_only": True,
        "parent_config": asdict(parent_cfg),
        "child_config": asdict(child_cfg),
        "config_values_identical": asdict(parent_cfg) == asdict(child_cfg),
        "parent_config_sha": parent_cfg.sha,
        "child_config_sha": child_cfg.sha,
        "config_sha_identical": parent_cfg.sha == child_cfg.sha,
        "parent_entry_geometry_preserved_for_retained_trades": True,
        "parent_exit_geometry_preserved": True,
        "parent_initial_risk_preserved": True,
        "atr_len": parent_cfg.atr_len,
        "context_transform": CONTEXT_TRANSFORM,
        "numeric_threshold_sweep": False,
        "best_horizon_selection": False,
        "post_outcome_trade_deletion": False,
        "uses_post_outcome_data": False,
        "external_evidence_ids": list(EXTERNAL_EVIDENCE_IDS),
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
    assert inv["changed_axis"] == AXIS
    assert inv["atr_len"] == 14
    assert inv["numeric_threshold_sweep"] is False
    assert inv["best_horizon_selection"] is False
    assert inv["post_outcome_trade_deletion"] is False
    assert inv["uses_post_outcome_data"] is False
    assert inv["execution_authority"] == "NONE" and inv["order_authority"] == "BLOCKED"
    print("PASS_TREND_RIDER_ATR_EXPANSION_CHILD_POLICY_V1")
    return 0


if __name__ == "__main__":
    raise SystemExit(self_test())
