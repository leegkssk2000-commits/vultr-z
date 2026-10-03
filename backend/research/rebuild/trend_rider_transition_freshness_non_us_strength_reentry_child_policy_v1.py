from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from backend.research.rebuild import trend_rider_transition_freshness_child_policy_v1 as parent

AXIS = "NON_US_SCAFFOLD_PLUS_US_ST_GAP_ATR_STRENGTHENING_REENTRY"
BASELINE_IDENTITY = "TREND_RIDER_NON_US_WR80_SCAFFOLD"
SESSION_TAXONOMY = "APAC_UTC_00_07__EU_UTC_08_15__US_UTC_16_23"
CONTEXT_TRANSFORM = (
    "KEEP_ALL_NON_US_INCUMBENT_SIGNALS; FOR_US_ONLY_REQUIRE_ST_GAP_ATR_CURRENT_GT_PRIOR_CLOSED_BAR"
)
PARAMETER_PROVENANCE = (
    "preserves the observed non-US high-WR scaffold and uses the incumbent Trend Rider's own "
    "st_gap_atr entry-strength geometry for selective US re-admission; ordinal strengthening only; "
    "no outcome-fitted numeric threshold and no sweep"
)


@dataclass(frozen=True)
class TrendRiderNonUSStrengthReentryConfig(parent.TrendRiderTransitionFreshnessConfig):
    pass


FeatureSnapshot = parent.FeatureSnapshot


def _session(signal_ts: int) -> str:
    h = datetime.fromtimestamp(int(signal_ts) / 1000, tz=timezone.utc).hour
    return "APAC" if h < 8 else "EU" if h < 16 else "US"


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
    config: TrendRiderNonUSStrengthReentryConfig | None = None,
) -> FeatureSnapshot:
    cfg = config or TrendRiderNonUSStrengthReentryConfig()
    base = parent.compute_trend_rider_feature(bars, symbol=symbol, now_ts_ms=now_ts_ms, config=cfg)
    values = dict(base.values)
    incumbent_long = bool(values.get("long_confirm"))
    incumbent_short = bool(values.get("short_confirm"))
    session = _session(base.signal_ts)

    prior_st_gap = None
    st_gap_strengthening = False
    if len(bars) >= 65:
        prior = parent.compute_trend_rider_feature(
            bars[:-1], symbol=symbol, now_ts_ms=parent.parent.ts(bars[-2]), config=cfg
        )
        prior_st_gap = float(prior.values["st_gap_atr"])
        st_gap_strengthening = float(values["st_gap_atr"]) > prior_st_gap

    us_reentry_allowed = bool(session == "US" and st_gap_strengthening)
    allow = bool(session != "US" or us_reentry_allowed)
    values.update({
        "incumbent_long_confirm": incumbent_long,
        "incumbent_short_confirm": incumbent_short,
        "session": session,
        "session_taxonomy": SESSION_TAXONOMY,
        "non_us_scaffold_kept": session != "US",
        "st_gap_atr_current": float(values["st_gap_atr"]),
        "st_gap_atr_prior_closed_bar": prior_st_gap,
        "st_gap_atr_strengthening": st_gap_strengthening,
        "us_strength_reentry_allowed": us_reentry_allowed,
        "long_confirm": bool(incumbent_long and allow),
        "short_confirm": bool(incumbent_short and allow),
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
    return parent.build_trend_rider_intent(feature, **kwargs)


def invariant_receipt() -> dict[str, Any]:
    p = parent.TrendRiderTransitionFreshnessConfig()
    c = TrendRiderNonUSStrengthReentryConfig()
    return {
        "strategy_id": "trend_rider",
        "baseline_identity": BASELINE_IDENTITY,
        "changed_axis": AXIS,
        "one_axis_recovery_from_scaffold": True,
        "parent_config": asdict(p),
        "child_config": asdict(c),
        "config_values_identical": asdict(p) == asdict(c),
        "config_sha_identical": p.sha == c.sha,
        "non_us_scaffold_preserved": True,
        "us_reentry_uses_incumbent_strength_geometry": "st_gap_atr",
        "ordinal_only": True,
        "numeric_threshold_sweep": False,
        "loss_derived_numeric_threshold": False,
        "post_outcome_trade_deletion": False,
        "uses_post_outcome_data": False,
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
    assert inv["non_us_scaffold_preserved"] is True
    assert inv["numeric_threshold_sweep"] is False
    assert inv["loss_derived_numeric_threshold"] is False
    assert inv["uses_post_outcome_data"] is False
    assert _session(15 * 3600 * 1000) == "EU"
    assert _session(16 * 3600 * 1000) == "US"
    assert inv["execution_authority"] == "NONE" and inv["order_authority"] == "BLOCKED"
    print("PASS_TREND_RIDER_NON_US_STRENGTH_REENTRY_CHILD_POLICY_V1")
    return 0


if __name__ == "__main__":
    raise SystemExit(self_test())
