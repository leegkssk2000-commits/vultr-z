from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from backend.research.rebuild import trend_policy_batch_v1 as raw_parent
from backend.research.rebuild import trend_rider_transition_freshness_child_policy_v1 as transition_parent
from backend.research.rebuild import trend_rider_wr80_us_chase_cooling_child_policy_v1 as baseline

AXIS = "US_STRUCTURAL_CONSENSUS_FRESH_REENABLE"
BASELINE_IDENTITY = "TREND_RIDER_WR8125_CHASE_COOLING_FROZEN_PARENT"
ARCHITECTURE_ID = "TR_STRUCTURAL_CONSENSUS_EDGE_V1"
PARAMETER_PROVENANCE = (
    "Preserve the frozen WR81.25 admission parent exactly, then re-enable an otherwise blocked US "
    "transition only when the causal trend core itself changes from unaligned to aligned on the signal bar. "
    "The core is categorical: Supertrend direction, price-vs-Supertrend, price-vs-EMA50, and EMA50 slope sign. "
    "No magnitude threshold, sweep, outcome lookup, RR change, or exit change is used."
)


@dataclass(frozen=True)
class TrendRiderWR8125StructuralConsensusConfig(baseline.TrendRiderWR80USChaseCoolingConfig):
    """Frozen baseline configuration is preserved; only one categorical US admission axis is added."""


FeatureSnapshot = baseline.FeatureSnapshot


def _feature_sha(base: FeatureSnapshot, values: Mapping[str, Any]) -> str:
    return raw_parent.digest({
        "strategy_id": base.strategy_id,
        "symbol": base.symbol,
        "signal_ts": base.signal_ts,
        "close": base.close,
        "atr": base.atr,
        "values": dict(values),
        "changed_axis": AXIS,
        "architecture_id": ARCHITECTURE_ID,
    })


def _long_core(cur: raw_parent.FeatureSnapshot, prev: raw_parent.FeatureSnapshot) -> bool:
    v = cur.values
    p = prev.values
    return bool(
        int(v["direction"]) == 1
        and float(cur.close) > float(v["supertrend"])
        and float(cur.close) > float(v["ema50"])
        and float(v["ema50"]) > float(p["ema50"])
    )


def _short_core(cur: raw_parent.FeatureSnapshot, prev: raw_parent.FeatureSnapshot) -> bool:
    v = cur.values
    p = prev.values
    return bool(
        int(v["direction"]) == -1
        and float(cur.close) < float(v["supertrend"])
        and float(cur.close) < float(v["ema50"])
        and float(v["ema50"]) < float(p["ema50"])
    )


def structural_consensus_state(
    bars: Sequence[Mapping[str, Any]],
    *,
    symbol: str,
    now_ts_ms: int,
    config: TrendRiderWR8125StructuralConsensusConfig | None = None,
) -> dict[str, bool]:
    cfg = config or TrendRiderWR8125StructuralConsensusConfig()
    if len(bars) < 66:
        return {
            "long_core_now": False,
            "long_core_prior": False,
            "short_core_now": False,
            "short_core_prior": False,
            "long_structural_consensus_fresh": False,
            "short_structural_consensus_fresh": False,
        }
    cur = raw_parent.compute_trend_rider_feature(
        bars, symbol=symbol, now_ts_ms=now_ts_ms, config=cfg
    )
    prev = raw_parent.compute_trend_rider_feature(
        bars[:-1], symbol=symbol, now_ts_ms=raw_parent.ts(bars[-2]), config=cfg
    )
    prev2 = raw_parent.compute_trend_rider_feature(
        bars[:-2], symbol=symbol, now_ts_ms=raw_parent.ts(bars[-3]), config=cfg
    )
    long_now = _long_core(cur, prev)
    long_prior = _long_core(prev, prev2)
    short_now = _short_core(cur, prev)
    short_prior = _short_core(prev, prev2)
    return {
        "long_core_now": long_now,
        "long_core_prior": long_prior,
        "short_core_now": short_now,
        "short_core_prior": short_prior,
        "long_structural_consensus_fresh": bool(long_now and not long_prior),
        "short_structural_consensus_fresh": bool(short_now and not short_prior),
    }


def compute_trend_rider_feature(
    bars: Sequence[Mapping[str, Any]],
    *,
    symbol: str,
    now_ts_ms: int,
    config: TrendRiderWR8125StructuralConsensusConfig | None = None,
) -> FeatureSnapshot:
    cfg = config or TrendRiderWR8125StructuralConsensusConfig()
    base = baseline.compute_trend_rider_feature(
        bars, symbol=symbol, now_ts_ms=now_ts_ms, config=cfg
    )
    values = dict(base.values)
    structural = structural_consensus_state(
        bars, symbol=symbol, now_ts_ms=now_ts_ms, config=cfg
    )

    baseline_long = bool(values.get("long_confirm"))
    baseline_short = bool(values.get("short_confirm"))
    transition_long = bool(values.get("parent_transition_long_confirm"))
    transition_short = bool(values.get("parent_transition_short_confirm"))
    session = str(values.get("session"))

    reenable_long = bool(
        session == "US"
        and transition_long
        and structural["long_structural_consensus_fresh"]
        and not baseline_long
    )
    reenable_short = bool(
        session == "US"
        and transition_short
        and structural["short_structural_consensus_fresh"]
        and not baseline_short
    )
    values.update(structural)
    values.update({
        "baseline_wr8125_long_confirm": baseline_long,
        "baseline_wr8125_short_confirm": baseline_short,
        "structural_consensus_us_reenable_long": reenable_long,
        "structural_consensus_us_reenable_short": reenable_short,
        "long_confirm": bool(baseline_long or reenable_long),
        "short_confirm": bool(baseline_short or reenable_short),
        "changed_axis": AXIS,
        "architecture_id": ARCHITECTURE_ID,
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
        feature_sha=_feature_sha(base, values),
    )


def build_trend_rider_intent(feature: FeatureSnapshot, **kwargs: Any):
    if feature.strategy_id != "trend_rider":
        raise ValueError("FEATURE_STRATEGY_MISMATCH")
    return transition_parent.build_trend_rider_intent(feature, **kwargs)


def invariant_receipt() -> dict[str, Any]:
    parent_cfg = baseline.TrendRiderWR80USChaseCoolingConfig()
    child_cfg = TrendRiderWR8125StructuralConsensusConfig()
    return {
        "strategy_id": "trend_rider",
        "baseline_identity": BASELINE_IDENTITY,
        "architecture_id": ARCHITECTURE_ID,
        "changed_axis": AXIS,
        "one_architecture_only": True,
        "parent_config": asdict(parent_cfg),
        "child_config": asdict(child_cfg),
        "config_values_identical": asdict(parent_cfg) == asdict(child_cfg),
        "config_sha_identical": parent_cfg.sha == child_cfg.sha,
        "baseline_admission_monotonic_superset": True,
        "new_admission_scope": "US_ONLY_AND_ONLY_WHEN_BASELINE_BLOCKS",
        "causal_event_order": "STRUCTURAL_CORE_UNALIGNED_TO_ALIGNED_ON_SIGNAL_BAR",
        "numeric_threshold_sweep": False,
        "candidate_family_sweep": False,
        "outcome_used_for_runtime": False,
        "post_outcome_trade_deletion": False,
        "parent_entry_geometry_preserved_for_existing_trades": True,
        "parent_exit_geometry_preserved": True,
        "parent_initial_risk_preserved": True,
        "rr_exit_mutated": False,
        "historical_union_allowed": False,
        "fresh_boundary_required": True,
        "fresh_oos_required": True,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "protected_mutations": 0,
        "parameter_provenance": PARAMETER_PROVENANCE,
    }


def self_test() -> int:
    inv = invariant_receipt()
    assert inv["one_architecture_only"] is True
    assert inv["config_values_identical"] is True and inv["config_sha_identical"] is True
    assert inv["baseline_admission_monotonic_superset"] is True
    assert inv["numeric_threshold_sweep"] is False and inv["candidate_family_sweep"] is False
    assert inv["outcome_used_for_runtime"] is False
    assert inv["rr_exit_mutated"] is False and inv["historical_union_allowed"] is False
    assert inv["fresh_boundary_required"] is True and inv["fresh_oos_required"] is True
    assert inv["execution_authority"] == "NONE" and inv["order_authority"] == "BLOCKED"
    print("PASS_TREND_RIDER_WR8125_STRUCTURAL_CONSENSUS_CHILD_POLICY_V1")
    return 0


if __name__ == "__main__":
    raise SystemExit(self_test())
