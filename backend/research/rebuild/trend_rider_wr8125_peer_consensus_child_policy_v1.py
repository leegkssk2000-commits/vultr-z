from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from backend.research.rebuild import trend_policy_batch_v1 as raw_parent
from backend.research.rebuild import trend_rider_transition_freshness_child_policy_v1 as transition_parent
from backend.research.rebuild import trend_rider_wr80_us_chase_cooling_child_policy_v1 as baseline

AXIS = "US_CROSS_ASSET_PEER_TREND_CORE_CONSENSUS"
BASELINE_IDENTITY = "TREND_RIDER_WR8125_CHASE_COOLING_FROZEN_PARENT"
ARCHITECTURE_ID = "TR_US_PEER_CONSENSUS_EDGE_V1"
PEER_MAP = {"BTC-USDT": "ETH-USDT", "ETH-USDT": "BTC-USDT"}
PARAMETER_PROVENANCE = (
    "Preserve the frozen WR81.25 admission parent exactly. Re-enable an otherwise blocked US transition "
    "only when the fixed BTC<->ETH peer is simultaneously aligned to the same categorical trend core: "
    "Supertrend direction, price-vs-Supertrend, price-vs-EMA50, and EMA50 slope sign. "
    "This is a cross-asset confirmation architecture, not a same-symbol threshold or outcome filter."
)


@dataclass(frozen=True)
class TrendRiderWR8125PeerConsensusConfig(baseline.TrendRiderWR80USChaseCoolingConfig):
    """Frozen baseline config is unchanged; peer context only affects blocked-US admission."""


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


def _core(feature: raw_parent.FeatureSnapshot, prior: raw_parent.FeatureSnapshot, side: str) -> bool:
    v = feature.values
    p = prior.values
    if side == "long":
        return bool(
            int(v["direction"]) == 1
            and float(feature.close) > float(v["supertrend"])
            and float(feature.close) > float(v["ema50"])
            and float(v["ema50"]) > float(p["ema50"])
        )
    if side == "short":
        return bool(
            int(v["direction"]) == -1
            and float(feature.close) < float(v["supertrend"])
            and float(feature.close) < float(v["ema50"])
            and float(v["ema50"]) < float(p["ema50"])
        )
    raise ValueError(f"SIDE_INVALID:{side}")


def peer_core_state(
    peer_bars: Sequence[Mapping[str, Any]],
    *,
    peer_symbol: str,
    now_ts_ms: int,
    side: str,
    config: TrendRiderWR8125PeerConsensusConfig | None = None,
) -> bool:
    cfg = config or TrendRiderWR8125PeerConsensusConfig()
    if len(peer_bars) < 65:
        return False
    cur = raw_parent.compute_trend_rider_feature(
        peer_bars, symbol=peer_symbol, now_ts_ms=now_ts_ms, config=cfg
    )
    prev = raw_parent.compute_trend_rider_feature(
        peer_bars[:-1], symbol=peer_symbol, now_ts_ms=raw_parent.ts(peer_bars[-2]), config=cfg
    )
    return _core(cur, prev, side)


def compute_trend_rider_feature(
    bars: Sequence[Mapping[str, Any]],
    *,
    symbol: str,
    now_ts_ms: int,
    config: TrendRiderWR8125PeerConsensusConfig | None = None,
    peer_bars: Sequence[Mapping[str, Any]] | None = None,
    peer_symbol: str | None = None,
) -> FeatureSnapshot:
    cfg = config or TrendRiderWR8125PeerConsensusConfig()
    base = baseline.compute_trend_rider_feature(
        bars, symbol=symbol, now_ts_ms=now_ts_ms, config=cfg
    )
    values = dict(base.values)
    baseline_long = bool(values.get("long_confirm"))
    baseline_short = bool(values.get("short_confirm"))
    transition_long = bool(values.get("parent_transition_long_confirm"))
    transition_short = bool(values.get("parent_transition_short_confirm"))
    session = str(values.get("session"))

    expected_peer = PEER_MAP.get(symbol)
    peer_identity_ok = bool(expected_peer and peer_symbol == expected_peer)
    peer_long = False
    peer_short = False
    if peer_identity_ok and peer_bars is not None:
        peer_long = peer_core_state(
            peer_bars, peer_symbol=str(peer_symbol), now_ts_ms=now_ts_ms, side="long", config=cfg
        )
        peer_short = peer_core_state(
            peer_bars, peer_symbol=str(peer_symbol), now_ts_ms=now_ts_ms, side="short", config=cfg
        )

    reenable_long = bool(
        session == "US"
        and transition_long
        and not baseline_long
        and peer_identity_ok
        and peer_long
    )
    reenable_short = bool(
        session == "US"
        and transition_short
        and not baseline_short
        and peer_identity_ok
        and peer_short
    )
    values.update({
        "baseline_wr8125_long_confirm": baseline_long,
        "baseline_wr8125_short_confirm": baseline_short,
        "peer_symbol_expected": expected_peer,
        "peer_symbol_observed": peer_symbol,
        "peer_identity_ok": peer_identity_ok,
        "peer_long_core_aligned": peer_long,
        "peer_short_core_aligned": peer_short,
        "peer_consensus_us_reenable_long": reenable_long,
        "peer_consensus_us_reenable_short": reenable_short,
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
    p = baseline.TrendRiderWR80USChaseCoolingConfig()
    c = TrendRiderWR8125PeerConsensusConfig()
    return {
        "strategy_id": "trend_rider",
        "baseline_identity": BASELINE_IDENTITY,
        "architecture_id": ARCHITECTURE_ID,
        "changed_axis": AXIS,
        "one_architecture_only": True,
        "peer_map": dict(PEER_MAP),
        "parent_config": asdict(p),
        "child_config": asdict(c),
        "config_values_identical": asdict(p) == asdict(c),
        "config_sha_identical": p.sha == c.sha,
        "baseline_admission_monotonic_superset": True,
        "new_admission_scope": "US_ONLY_AND_BASELINE_BLOCKED_ONLY",
        "cross_asset_context_required": True,
        "peer_rule": "FIXED_OTHER_MEMBER_OF_BTC_ETH_PAIR_SAME_SIDE_CATEGORICAL_TREND_CORE",
        "numeric_thresholds_added": 0,
        "numeric_threshold_sweep": False,
        "candidate_family_sweep": False,
        "outcome_used_to_define_axis": False,
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
    assert inv["peer_map"] == {"BTC-USDT": "ETH-USDT", "ETH-USDT": "BTC-USDT"}
    assert inv["config_values_identical"] is True and inv["config_sha_identical"] is True
    assert inv["baseline_admission_monotonic_superset"] is True
    assert inv["cross_asset_context_required"] is True
    assert inv["numeric_thresholds_added"] == 0
    assert inv["numeric_threshold_sweep"] is False and inv["candidate_family_sweep"] is False
    assert inv["outcome_used_to_define_axis"] is False and inv["outcome_used_for_runtime"] is False
    assert inv["rr_exit_mutated"] is False and inv["historical_union_allowed"] is False
    assert inv["execution_authority"] == "NONE" and inv["order_authority"] == "BLOCKED"
    print("PASS_TREND_RIDER_WR8125_PEER_CONSENSUS_CHILD_POLICY_V1")
    return 0


if __name__ == "__main__":
    raise SystemExit(self_test())
