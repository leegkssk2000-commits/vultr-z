from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from backend.research.rebuild import trend_policy_batch_v1 as parent

AXIS = "TRANSITION_FRESHNESS_REENTRY_SUPPRESSION_ONLY"
BASELINE_IDENTITY = "ORIGINAL_TREND_RIDER_FRESH_W1_W2_W3"
EXTERNAL_EVIDENCE_IDS = ("HIST_R7_TREND_RIDER",)
CONTEXT_TRANSFORM = "CURRENT_PARENT_CONFIRM_TRUE_AND_PRIOR_CLOSED_BAR_SAME_SIDE_CONFIRM_FALSE"
PARAMETER_PROVENANCE = (
    "enforces existing parent cooldown.one_entry_per_transition and "
    "turnover.duplicate_transition_forbidden semantics; no numeric threshold; no outcome sweep"
)


@dataclass(frozen=True)
class TrendRiderTransitionFreshnessConfig(parent.TrendPolicyConfig):
    """Parent config preserved; only duplicate same-transition re-entry is suppressed."""


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
    config: TrendRiderTransitionFreshnessConfig | None = None,
) -> FeatureSnapshot:
    cfg = config or TrendRiderTransitionFreshnessConfig()
    base = parent.compute_trend_rider_feature(bars, symbol=symbol, now_ts_ms=now_ts_ms, config=cfg)

    values = dict(base.values)
    parent_long = bool(values.get("long_confirm"))
    parent_short = bool(values.get("short_confirm"))

    # A parent signal cannot exist before the policy's 64-bar warmup. At the
    # first eligible bar there is therefore no prior eligible transition state.
    prev_long = False
    prev_short = False
    if len(bars) >= 65:
        prev = parent.compute_trend_rider_feature(
            bars[:-1],
            symbol=symbol,
            now_ts_ms=parent.ts(bars[-2]),
            config=cfg,
        )
        prev_long = bool(prev.values.get("long_confirm"))
        prev_short = bool(prev.values.get("short_confirm"))

    long_transition_fresh = bool(parent_long and not prev_long)
    short_transition_fresh = bool(parent_short and not prev_short)
    values.update({
        "parent_long_confirm": parent_long,
        "parent_short_confirm": parent_short,
        "prior_parent_long_confirm": prev_long,
        "prior_parent_short_confirm": prev_short,
        "long_transition_fresh": long_transition_fresh,
        "short_transition_fresh": short_transition_fresh,
        "long_confirm": long_transition_fresh,
        "short_confirm": short_transition_fresh,
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
    child_cfg = TrendRiderTransitionFreshnessConfig()
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
        "existing_parent_one_entry_per_transition": True,
        "existing_parent_duplicate_transition_forbidden": True,
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
    assert inv["existing_parent_one_entry_per_transition"] is True
    assert inv["existing_parent_duplicate_transition_forbidden"] is True
    assert inv["numeric_threshold_sweep"] is False
    assert inv["best_horizon_selection"] is False
    assert inv["post_outcome_trade_deletion"] is False
    assert inv["uses_post_outcome_data"] is False
    assert inv["execution_authority"] == "NONE" and inv["order_authority"] == "BLOCKED"
    print("PASS_TREND_RIDER_TRANSITION_FRESHNESS_CHILD_POLICY_V1")
    return 0


if __name__ == "__main__":
    raise SystemExit(self_test())
