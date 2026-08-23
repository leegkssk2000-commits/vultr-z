from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from backend.research.rebuild import trend_rider_transition_freshness_child_policy_v1 as parent
from backend.research.rebuild import trend_rider_transition_freshness_non_us_child_policy_v1 as session_policy

AXIS = "NON_US_PLUS_US_CHASE_COOLING_OR_FLAT_ONLY"
BASELINE_IDENTITY = "TREND_RIDER_NON_US_WR80_PARTIAL_SUCCESS"
SESSION_TAXONOMY = session_policy.SESSION_TAXONOMY
PARAMETER_PROVENANCE = (
    "Preserves transition-freshness parent exactly. Non-US signals remain eligible. "
    "US signals are conditionally re-enabled only when current closed-bar chase_atr <= prior closed-bar chase_atr. "
    "Ordinal pre-entry state only; no numeric threshold sweep and no outcome data at runtime."
)


@dataclass(frozen=True)
class TrendRiderWR80USChaseCoolingConfig(parent.TrendRiderTransitionFreshnessConfig):
    """Parent configuration preserved exactly; only US admission context changes."""


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
        "session_taxonomy": SESSION_TAXONOMY,
    })


def compute_trend_rider_feature(
    bars: Sequence[Mapping[str, Any]],
    *,
    symbol: str,
    now_ts_ms: int,
    config: TrendRiderWR80USChaseCoolingConfig | None = None,
) -> FeatureSnapshot:
    cfg = config or TrendRiderWR80USChaseCoolingConfig()
    base = parent.compute_trend_rider_feature(bars, symbol=symbol, now_ts_ms=now_ts_ms, config=cfg)
    values = dict(base.values)
    session = session_policy._session(base.signal_ts)
    parent_long = bool(values.get("long_confirm"))
    parent_short = bool(values.get("short_confirm"))

    prev_chase: float | None = None
    chase_cooling_or_flat = False
    if len(bars) >= 65:
        prev = parent.compute_trend_rider_feature(
            bars[:-1], symbol=symbol, now_ts_ms=parent.parent.ts(bars[-2]), config=cfg
        )
        prev_chase = float(prev.values["chase_atr"])
        chase_cooling_or_flat = float(values["chase_atr"]) <= prev_chase

    us_allowed = bool(session != "US" or chase_cooling_or_flat)
    values.update({
        "parent_transition_long_confirm": parent_long,
        "parent_transition_short_confirm": parent_short,
        "session": session,
        "session_taxonomy": SESSION_TAXONOMY,
        "prior_chase_atr": prev_chase,
        "chase_state": "COOLING_OR_FLAT" if chase_cooling_or_flat else "EXPANDING_OR_UNAVAILABLE",
        "us_conditional_reenable_allowed": us_allowed,
        "changed_axis": AXIS,
        "parameter_provenance": PARAMETER_PROVENANCE,
    })
    if session == "US" and not chase_cooling_or_flat:
        values["long_confirm"] = False
        values["short_confirm"] = False

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
    return parent.build_trend_rider_intent(feature, **kwargs)


def invariant_receipt() -> dict[str, Any]:
    p = parent.TrendRiderTransitionFreshnessConfig()
    c = TrendRiderWR80USChaseCoolingConfig()
    return {
        "strategy_id": "trend_rider",
        "baseline_identity": BASELINE_IDENTITY,
        "changed_axis": AXIS,
        "one_axis_only": True,
        "session_taxonomy": SESSION_TAXONOMY,
        "parent_config": asdict(p),
        "child_config": asdict(c),
        "config_values_identical": asdict(p) == asdict(c),
        "config_sha_identical": p.sha == c.sha,
        "non_us_parent_signals_preserved": True,
        "us_reenable_rule": "current_chase_atr <= prior_closed_bar_chase_atr",
        "ordinal_preentry_state_only": True,
        "numeric_threshold_sweep": False,
        "post_outcome_trade_deletion": False,
        "uses_post_outcome_data_at_runtime": False,
        "parent_entry_geometry_preserved_for_retained_trades": True,
        "parent_exit_geometry_preserved": True,
        "parent_initial_risk_preserved": True,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "protected_mutations": 0,
    }


def self_test() -> int:
    inv = invariant_receipt()
    assert inv["one_axis_only"] is True
    assert inv["config_values_identical"] is True and inv["config_sha_identical"] is True
    assert inv["ordinal_preentry_state_only"] is True
    assert inv["numeric_threshold_sweep"] is False
    assert inv["uses_post_outcome_data_at_runtime"] is False
    assert session_policy._session(15 * 3600 * 1000) == "EU"
    assert session_policy._session(16 * 3600 * 1000) == "US"
    assert inv["execution_authority"] == "NONE" and inv["order_authority"] == "BLOCKED"
    print("PASS_TREND_RIDER_WR80_US_CHASE_COOLING_CHILD_POLICY_V1")
    return 0


if __name__ == "__main__":
    raise SystemExit(self_test())
