from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from backend.research.rebuild import microstructure_policy_batch_v1 as base
from backend.research.rebuild.policy_kernel_v1 import DecisionIntent, digest, hold_intent, risk_geometry, validate_authority


@dataclass(frozen=True)
class LiquiditySweepCascadeConfig(base.MicroPolicyConfig):
    """Single-axis v2: direction/trigger follows stop-cascade continuation; all risk/cost geometry stays v1."""

    @property
    def sha(self) -> str:
        return digest(asdict(self))


FeatureSnapshot = base.FeatureSnapshot

EVIDENCE = (
    "HIST_R7_LIQUIDITY_SWEEP",
    "DOI_10.1016_J.JIMONFIN.2004.12.002",
    "ARXIV_1011.6402",
    "BINGX_FEE_SCHEDULE",
)


def compute_liquidity_sweep_feature(bars: Any, *, symbol: str, now_ts_ms: int,
                                    config: LiquiditySweepCascadeConfig | None = None) -> FeatureSnapshot:
    cfg = config or LiquiditySweepCascadeConfig()
    return base.compute_liquidity_sweep_feature(bars, symbol=symbol, now_ts_ms=now_ts_ms, config=cfg)


def build_liquidity_sweep_intent(feature: FeatureSnapshot, *, policy_source_sha: str,
                                 verified_round_trip_cost_bps: float,
                                 config: LiquiditySweepCascadeConfig | None = None) -> DecisionIntent:
    cfg = config or LiquiditySweepCascadeConfig()
    validate_authority(policy_source_sha=policy_source_sha,
                       verified_round_trip_cost_bps=verified_round_trip_cost_bps)
    if feature.strategy_id != "liquidity_sweep":
        raise ValueError("FEATURE_STRATEGY_MISMATCH")
    schema = "zel.liquidity_sweep.policy.v2.stop_cascade_continuation"
    entry_rule = "closed_bar_prior_extreme_sweep_stop_cascade_continuation"
    if not feature.fresh:
        return hold_intent(strategy_id="liquidity_sweep", policy_schema=schema, source_sha=policy_source_sha,
                           config_sha=cfg.sha, feature_sha=feature.feature_sha, evidence_ids=EVIDENCE,
                           symbol=feature.symbol, signal_ts=feature.signal_ts, entry_rule=entry_rule,
                           strength_normalization="wick_atr_clipped_0_1", regime="NO_TRADE_STALE",
                           reasons=("STALE_SOURCE_FAIL_CLOSED",), verified_cost_bps=verified_round_trip_cost_bps,
                           timeout_bars=cfg.timeout_bars, risk_fraction=cfg.risk_fraction_of_equity,
                           exposure_cap=cfg.max_notional_fraction_of_equity)

    v = feature.values
    # SINGLE CAUSAL AXIS ONLY: v1 faded a sweep after an extra prior-close reclaim gate.
    # v2 follows the documented positive-feedback stop cascade in the sweep direction.
    long_ok = bool(v["upper_sweep"])
    short_ok = bool(v["lower_sweep"])
    strength = min(1.0, float(v["wick_atr"]) / 1.5)
    if long_ok == short_ok:
        return hold_intent(strategy_id="liquidity_sweep", policy_schema=schema, source_sha=policy_source_sha,
                           config_sha=cfg.sha, feature_sha=feature.feature_sha, evidence_ids=EVIDENCE,
                           symbol=feature.symbol, signal_ts=feature.signal_ts, entry_rule=entry_rule,
                           strength_normalization="wick_atr_clipped_0_1", regime="NO_TRADE",
                           reasons=("NO_UNAMBIGUOUS_SWEEP",), verified_cost_bps=verified_round_trip_cost_bps,
                           timeout_bars=cfg.timeout_bars, risk_fraction=cfg.risk_fraction_of_equity,
                           exposure_cap=cfg.max_notional_fraction_of_equity)

    side = "long" if long_ok else "short"
    entry = feature.close
    stop = entry - 1.25 * feature.atr if side == "long" else entry + 1.25 * feature.atr
    notional, risk_distance_bps = risk_geometry(entry=entry, stop=stop,
                                                 risk_fraction=cfg.risk_fraction_of_equity,
                                                 exposure_cap=cfg.max_notional_fraction_of_equity)
    move_budget_bps = 2.0 * risk_distance_bps
    ratio = move_budget_bps / verified_round_trip_cost_bps
    if ratio < cfg.min_cost_budget_ratio:
        return hold_intent(strategy_id="liquidity_sweep", policy_schema=schema, source_sha=policy_source_sha,
                           config_sha=cfg.sha, feature_sha=feature.feature_sha, evidence_ids=EVIDENCE,
                           symbol=feature.symbol, signal_ts=feature.signal_ts, entry_rule=entry_rule,
                           strength_normalization="wick_atr_clipped_0_1", regime="NO_TRADE_COST",
                           reasons=("STRUCTURAL_COST_BUDGET_BELOW_MIN",), verified_cost_bps=verified_round_trip_cost_bps,
                           timeout_bars=cfg.timeout_bars, risk_fraction=cfg.risk_fraction_of_equity,
                           exposure_cap=cfg.max_notional_fraction_of_equity)

    return DecisionIntent(
        schema_version=schema, strategy_id="liquidity_sweep", source_sha=policy_source_sha,
        config_sha=cfg.sha, feature_sha=feature.feature_sha, evidence_ids=EVIDENCE,
        symbol=feature.symbol, side=side, signal_ts=feature.signal_ts, entry_rule=entry_rule,
        entry_strength=strength, strength_normalization="wick_atr_clipped_0_1",
        regime="STOP_CASCADE_CONTINUATION", no_trade=False,
        invalidation={"initial_stop": stop, "hard_no_adverse_add": True},
        risk_size={"risk_fraction_of_equity": cfg.risk_fraction_of_equity,
                   "risk_distance_bps": risk_distance_bps},
        exposure={"notional_fraction_of_equity": notional, "cap": cfg.max_notional_fraction_of_equity},
        sl=stop, tp=None, timeout={"bars": cfg.timeout_bars}, partial={"enabled": False},
        trailing={"enabled": False}, runner={"enabled": False},
        pyramiding={"enabled": False, "adverse_add": False},
        cooldown={"bars": 3, "one_entry_per_transition": True},
        turnover={"duplicate_transition_forbidden": True, "max_new_entries_per_bar": 1},
        reason_codes=("ENTRY_POLICY_PASS", "AXIS_STOP_CASCADE_CONTINUATION"),
        verified_round_trip_cost_bps=float(verified_round_trip_cost_bps),
        move_budget_bps=move_budget_bps, cost_budget_ratio=ratio,
    )
