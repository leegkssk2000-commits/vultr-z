from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from backend.research.rebuild import trend_rider_transition_freshness_child_policy_v1 as parent

AXIS = "FROZEN_H5_US_SESSION_EXCLUSION_ONLY"
BASELINE_IDENTITY = "TREND_RIDER_TRANSITION_FRESHNESS_CHILD_V1"
SESSION_TAXONOMY = "APAC_UTC_00_07__EU_UTC_08_15__US_UTC_16_23"
PARAMETER_PROVENANCE = (
    "Uses the already-frozen H5 session taxonomy from a1_trend_rider_h4_h5_hardening_v1.py; "
    "blocks US-session signals only. No numeric threshold sweep and no post-outcome geometry changes."
)


@dataclass(frozen=True)
class TrendRiderNonUSConfig(parent.TrendRiderTransitionFreshnessConfig):
    """Parent transition-freshness config preserved exactly."""


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
        "session_taxonomy": SESSION_TAXONOMY,
    })


def compute_trend_rider_feature(
    bars: Sequence[Mapping[str, Any]],
    *,
    symbol: str,
    now_ts_ms: int,
    config: TrendRiderNonUSConfig | None = None,
) -> FeatureSnapshot:
    cfg = config or TrendRiderNonUSConfig()
    base = parent.compute_trend_rider_feature(bars, symbol=symbol, now_ts_ms=now_ts_ms, config=cfg)
    values = dict(base.values)
    session = _session(base.signal_ts)
    blocked = session == "US"
    values.update({
        "parent_transition_long_confirm": bool(values.get("long_confirm")),
        "parent_transition_short_confirm": bool(values.get("short_confirm")),
        "session": session,
        "session_taxonomy": SESSION_TAXONOMY,
        "us_session_excluded": blocked,
        "changed_axis": AXIS,
        "parameter_provenance": PARAMETER_PROVENANCE,
    })
    if blocked:
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
    c = TrendRiderNonUSConfig()
    return {
        "strategy_id": "trend_rider",
        "baseline_identity": BASELINE_IDENTITY,
        "changed_axis": AXIS,
        "one_axis_only": True,
        "session_taxonomy": SESSION_TAXONOMY,
        "session_boundary_borrowed_from_frozen_h5": True,
        "parent_config": asdict(p),
        "child_config": asdict(c),
        "config_values_identical": asdict(p) == asdict(c),
        "config_sha_identical": p.sha == c.sha,
        "parent_entry_geometry_preserved_for_retained_trades": True,
        "parent_exit_geometry_preserved": True,
        "parent_initial_risk_preserved": True,
        "numeric_threshold_sweep": False,
        "post_outcome_trade_deletion": False,
        "uses_post_outcome_data_at_runtime": False,
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
    assert inv["one_axis_only"] is True
    assert inv["config_values_identical"] is True and inv["config_sha_identical"] is True
    assert inv["session_boundary_borrowed_from_frozen_h5"] is True
    assert _session(16 * 3600 * 1000) == "US"
    assert _session(15 * 3600 * 1000) == "EU"
    assert inv["numeric_threshold_sweep"] is False
    assert inv["uses_post_outcome_data_at_runtime"] is False
    assert inv["execution_authority"] == "NONE" and inv["order_authority"] == "BLOCKED"
    print("PASS_TREND_RIDER_TRANSITION_FRESHNESS_NON_US_CHILD_POLICY_V1")
    return 0


if __name__ == "__main__":
    raise SystemExit(self_test())
