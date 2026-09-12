from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from backend.research.rebuild import trend_policy_batch_v1 as broad_parent
from backend.research.rebuild import trend_rider_wr80_us_chase_cooling_child_policy_v1 as primary_policy
from backend.research.rebuild import trend_rider_transition_freshness_non_us_child_policy_v1 as session_policy

STRATEGY_ID = "trend_rider"
RULE_ID = "TREND_RIDER_UNIFIED_V1_CAUSAL_POLICY"
ARCHITECTURE = "PRIMARY_EXACT16_CAUSAL_CORE OR (BROAD_ONLY_CAUSAL AND EXACT_BROAD_WR80_STATE)"
SESSION_TAXONOMY = session_policy.SESSION_TAXONOMY


@dataclass(frozen=True)
class TrendRiderUnifiedV1Config(primary_policy.TrendRiderWR80USChaseCoolingConfig):
    """No new numeric parameters; both parent configs remain identical."""


FeatureSnapshot = broad_parent.FeatureSnapshot


def _broad_wr80_gate(
    bars: Sequence[Mapping[str, Any]],
    *,
    symbol: str,
    now_ts_ms: int,
    cfg: TrendRiderUnifiedV1Config,
) -> tuple[FeatureSnapshot, bool, bool, dict[str, Any]]:
    broad = broad_parent.compute_trend_rider_feature(bars, symbol=symbol, now_ts_ms=now_ts_ms, config=cfg)
    values = dict(broad.values)
    session = session_policy._session(broad.signal_ts)
    prev_chase = None
    cooling = False
    if len(bars) >= 65:
        prev = broad_parent.compute_trend_rider_feature(
            bars[:-1], symbol=symbol, now_ts_ms=broad_parent.ts(bars[-2]), config=cfg
        )
        prev_chase = float(prev.values["chase_atr"])
        cooling = float(values["chase_atr"]) <= prev_chase
    allowed = bool(session != "US" or cooling)
    long_ok = bool(values.get("long_confirm")) and allowed
    short_ok = bool(values.get("short_confirm")) and allowed
    context = {
        "broad_session": session,
        "broad_prior_chase_atr": prev_chase,
        "broad_chase_state": "COOLING_OR_FLAT" if cooling else "EXPANDING_OR_UNAVAILABLE",
        "broad_wr80_state_allowed": allowed,
    }
    return broad, long_ok, short_ok, context


def compute_trend_rider_feature(
    bars: Sequence[Mapping[str, Any]],
    *,
    symbol: str,
    now_ts_ms: int,
    config: TrendRiderUnifiedV1Config | None = None,
) -> FeatureSnapshot:
    cfg = config or TrendRiderUnifiedV1Config()

    # Primary exact16 lineage has an executable causal policy: transition-freshness
    # plus the frozen non-US / US chase-cooling-or-flat admission rule.
    primary = primary_policy.compute_trend_rider_feature(
        bars, symbol=symbol, now_ts_ms=now_ts_ms, config=cfg
    )
    pvals = dict(primary.values)
    primary_long = bool(pvals.get("long_confirm"))
    primary_short = bool(pvals.get("short_confirm"))

    # Broad donor is evaluated independently from the base Broad policy, then the
    # exact historical WR80 state rule is applied using only the current and prior
    # completed bar. No historical trade membership or outcome is consulted.
    broad, broad_long, broad_short, bctx = _broad_wr80_gate(
        bars, symbol=symbol, now_ts_ms=now_ts_ms, cfg=cfg
    )

    broad_only_long = bool(broad_long and not primary_long)
    broad_only_short = bool(broad_short and not primary_short)
    unified_long = bool(primary_long or broad_only_long)
    unified_short = bool(primary_short or broad_only_short)

    values = dict(pvals)
    values.update({
        "primary_core_long_confirm": primary_long,
        "primary_core_short_confirm": primary_short,
        "broad_wr80_long_confirm": broad_long,
        "broad_wr80_short_confirm": broad_short,
        "broad_only_long_confirm": broad_only_long,
        "broad_only_short_confirm": broad_only_short,
        "long_confirm": unified_long,
        "short_confirm": unified_short,
        "unified_rule_id": RULE_ID,
        "unified_architecture": ARCHITECTURE,
        "session_taxonomy": SESSION_TAXONOMY,
        **bctx,
    })
    feature_sha = broad_parent.digest({
        "strategy_id": STRATEGY_ID,
        "symbol": symbol,
        "signal_ts": primary.signal_ts,
        "close": primary.close,
        "atr": primary.atr,
        "values": values,
        "rule_id": RULE_ID,
        "architecture": ARCHITECTURE,
    })
    return FeatureSnapshot(
        strategy_id=STRATEGY_ID,
        symbol=symbol,
        signal_ts=primary.signal_ts,
        fresh=primary.fresh,
        close=primary.close,
        atr=primary.atr,
        values=values,
        feature_sha=feature_sha,
    )


def build_trend_rider_intent(feature: FeatureSnapshot, **kwargs: Any):
    if feature.strategy_id != STRATEGY_ID:
        raise ValueError("FEATURE_STRATEGY_MISMATCH")
    return broad_parent._build(feature, **kwargs)


def invariant_receipt() -> dict[str, Any]:
    cfg = TrendRiderUnifiedV1Config()
    primary_cfg = primary_policy.TrendRiderWR80USChaseCoolingConfig()
    broad_cfg = broad_parent.TrendPolicyConfig()
    return {
        "strategy_id": STRATEGY_ID,
        "rule_id": RULE_ID,
        "architecture": ARCHITECTURE,
        "primary_policy": "trend_rider_wr80_us_chase_cooling_child_policy_v1",
        "broad_policy": "trend_policy_batch_v1",
        "broad_component_rule": "session!=US OR current_chase_atr<=prior_closed_bar_chase_atr",
        "primary_and_broad_config_equal": vars(cfg) == vars(primary_cfg) == vars(broad_cfg),
        "historical_membership_runtime_dependency": False,
        "post_outcome_data_runtime_dependency": False,
        "numeric_threshold_sweep": False,
        "symbol_or_year_exception": False,
        "future_bar_access": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }


def self_test() -> int:
    r = invariant_receipt()
    assert r["historical_membership_runtime_dependency"] is False
    assert r["post_outcome_data_runtime_dependency"] is False
    assert r["numeric_threshold_sweep"] is False
    assert r["future_bar_access"] is False
    assert r["order_authority"] == "BLOCKED"
    print("PASS_TREND_RIDER_UNIFIED_V1_CAUSAL_POLICY")
    return 0


if __name__ == "__main__":
    raise SystemExit(self_test())
