from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from backend.research.rebuild.policy_kernel_v1 import (
    DecisionIntent, atr, digest, f, hold_intent, risk_geometry, rsi, ts,
    validate_authority, validate_bars,
)

FIVE_MIN_MS = 300_000
SUPPORTED = ("range_fade", "fvg_revert", "pivot_reversal", "rsi_swing_fail")


@dataclass(frozen=True)
class ReversalRangeConfig:
    timeframe_ms: int = FIVE_MIN_MS
    atr_len: int = 14
    lookback: int = 20
    max_stale_intervals: int = 2
    risk_fraction_of_equity: float = 0.0035
    max_notional_fraction_of_equity: float = 0.10
    min_cost_budget_ratio: float = 1.25
    timeout_bars: int = 24

    @property
    def sha(self) -> str:
        return digest(asdict(self))


@dataclass(frozen=True)
class FeatureSnapshot:
    strategy_id: str
    symbol: str
    signal_ts: int
    fresh: bool
    close: float
    atr: float
    values: Mapping[str, Any]
    feature_sha: str


EVIDENCE = {
    "range_fade": ("HIST_R7_RANGE_FADE", "EVIDENCE_MEAN_REVERSION_RANGE", "BINGX_FEE_SCHEDULE"),
    "fvg_revert": ("HIST_R7_FVG_REVERT", "EVIDENCE_IMBALANCE_REVERSION", "BINGX_FEE_SCHEDULE"),
    "pivot_reversal": ("HIST_R7_PIVOT_REVERSAL", "EVIDENCE_SUPPORT_RESISTANCE_REVERSAL", "BINGX_FEE_SCHEDULE"),
    "rsi_swing_fail": ("HIST_R7_RSI_SWING_FAIL", "EVIDENCE_MOMENTUM_FAILURE", "BINGX_FEE_SCHEDULE"),
}


def _fresh(signal_ts: int, now_ts_ms: int, cfg: ReversalRangeConfig) -> bool:
    return 0 <= int(now_ts_ms) - int(signal_ts) <= cfg.max_stale_intervals * cfg.timeframe_ms


def _snapshot(strategy_id: str, symbol: str, bars: Sequence[Mapping[str, Any]], now_ts_ms: int,
              values: Mapping[str, Any], cfg: ReversalRangeConfig) -> FeatureSnapshot:
    signal_ts = ts(bars[-1])
    close = f(bars[-1], "close")
    a = atr(bars, cfg.atr_len)
    body = {"strategy_id": strategy_id, "symbol": symbol, "signal_ts": signal_ts,
            "close": close, "atr": a, "values": values}
    return FeatureSnapshot(strategy_id, symbol, signal_ts, _fresh(signal_ts, now_ts_ms, cfg),
                           close, a, values, digest(body))


def compute_feature(strategy_id: str, bars: Sequence[Mapping[str, Any]], *, symbol: str,
                    now_ts_ms: int, config: ReversalRangeConfig | None = None) -> FeatureSnapshot:
    if strategy_id not in SUPPORTED:
        raise ValueError("UNSUPPORTED_STRATEGY")
    cfg = config or ReversalRangeConfig()
    validate_bars(bars, minimum=max(40, cfg.lookback + cfg.atr_len + 4))
    last = bars[-1]
    prev = bars[-2]
    hist = bars[-(cfg.lookback + 1):-1]
    close = f(last, "close")
    a = atr(bars, cfg.atr_len)
    high_ref = max(f(x, "high") for x in hist)
    low_ref = min(f(x, "low") for x in hist)
    prev_close = f(prev, "close")
    rv = rsi([f(x, "close") for x in bars], 14)
    body = close - f(last, "open")
    upper_wick = f(last, "high") - max(close, f(last, "open"))
    lower_wick = min(close, f(last, "open")) - f(last, "low")
    if strategy_id == "range_fade":
        width = high_ref - low_ref
        pos = (close - low_ref) / max(width, 1e-12)
        values = {"range_position": pos, "range_width_atr": width / a, "rsi": rv,
                  "reclaim_up": close > prev_close, "reclaim_down": close < prev_close}
    elif strategy_id == "fvg_revert":
        b2 = bars[-3]
        bull_gap = max(0.0, f(prev, "low") - f(b2, "high"))
        bear_gap = max(0.0, f(b2, "low") - f(prev, "high"))
        values = {"bull_gap_atr": bull_gap / a, "bear_gap_atr": bear_gap / a,
                  "reclaim_up": body > 0, "reclaim_down": body < 0}
    elif strategy_id == "pivot_reversal":
        values = {"near_low": abs(close - low_ref) / a, "near_high": abs(high_ref - close) / a,
                  "lower_wick_body": lower_wick / max(abs(body), 1e-12),
                  "upper_wick_body": upper_wick / max(abs(body), 1e-12)}
    else:
        values = {"rsi": rv, "failed_low": f(last, "low") < low_ref and close > low_ref,
                  "failed_high": f(last, "high") > high_ref and close < high_ref}
    return _snapshot(strategy_id, symbol, bars, now_ts_ms, values, cfg)


def build_intent(snapshot: FeatureSnapshot, *, policy_source_sha: str,
                 verified_round_trip_cost_bps: float,
                 config: ReversalRangeConfig | None = None) -> DecisionIntent:
    cfg = config or ReversalRangeConfig()
    validate_authority(policy_source_sha=policy_source_sha,
                       verified_round_trip_cost_bps=verified_round_trip_cost_bps)
    sid = snapshot.strategy_id
    if sid not in SUPPORTED:
        raise ValueError("UNSUPPORTED_STRATEGY")
    if not snapshot.fresh:
        return hold_intent(strategy_id=sid, policy_schema="zel.decision_intent.v2",
            source_sha=policy_source_sha, config_sha=cfg.sha, feature_sha=snapshot.feature_sha,
            evidence_ids=EVIDENCE[sid], symbol=snapshot.symbol, signal_ts=snapshot.signal_ts,
            entry_rule=f"{sid}:closed_bar_reversal", strength_normalization="bounded_0_1",
            regime="STALE", reasons=("STALE_SOURCE",), verified_cost_bps=verified_round_trip_cost_bps,
            timeout_bars=cfg.timeout_bars, risk_fraction=cfg.risk_fraction_of_equity,
            exposure_cap=cfg.max_notional_fraction_of_equity)

    v = snapshot.values
    side = "flat"
    strength = 0.0
    regime = "NO_TRADE"
    if sid == "range_fade":
        if v["range_width_atr"] <= 8.0 and v["range_position"] <= 0.18 and v["rsi"] <= 42 and v["reclaim_up"]:
            side, strength, regime = "long", min(1.0, (0.18-v["range_position"])/0.18 + 0.4), "RANGE_EXTREME_RECLAIM"
        elif v["range_width_atr"] <= 8.0 and v["range_position"] >= 0.82 and v["rsi"] >= 58 and v["reclaim_down"]:
            side, strength, regime = "short", min(1.0, (v["range_position"]-0.82)/0.18 + 0.4), "RANGE_EXTREME_RECLAIM"
    elif sid == "fvg_revert":
        if v["bull_gap_atr"] >= 0.25 and v["reclaim_down"]:
            side, strength, regime = "short", min(1.0, v["bull_gap_atr"]), "GAP_REVERSION"
        elif v["bear_gap_atr"] >= 0.25 and v["reclaim_up"]:
            side, strength, regime = "long", min(1.0, v["bear_gap_atr"]), "GAP_REVERSION"
    elif sid == "pivot_reversal":
        if v["near_low"] <= 0.35 and v["lower_wick_body"] >= 1.5:
            side, strength, regime = "long", min(1.0, v["lower_wick_body"] / 3.0), "PIVOT_REJECTION"
        elif v["near_high"] <= 0.35 and v["upper_wick_body"] >= 1.5:
            side, strength, regime = "short", min(1.0, v["upper_wick_body"] / 3.0), "PIVOT_REJECTION"
    else:
        if v["failed_low"] and v["rsi"] < 45:
            side, strength, regime = "long", min(1.0, (45-v["rsi"])/25 + 0.4), "SWING_FAILURE"
        elif v["failed_high"] and v["rsi"] > 55:
            side, strength, regime = "short", min(1.0, (v["rsi"]-55)/25 + 0.4), "SWING_FAILURE"

    if side == "flat":
        return hold_intent(strategy_id=sid, policy_schema="zel.decision_intent.v2",
            source_sha=policy_source_sha, config_sha=cfg.sha, feature_sha=snapshot.feature_sha,
            evidence_ids=EVIDENCE[sid], symbol=snapshot.symbol, signal_ts=snapshot.signal_ts,
            entry_rule=f"{sid}:closed_bar_reversal", strength_normalization="bounded_0_1",
            regime=regime, reasons=("NO_QUALIFYING_REVERSAL",), verified_cost_bps=verified_round_trip_cost_bps,
            timeout_bars=cfg.timeout_bars, risk_fraction=cfg.risk_fraction_of_equity,
            exposure_cap=cfg.max_notional_fraction_of_equity)

    stop = snapshot.close - snapshot.atr * 0.8 if side == "long" else snapshot.close + snapshot.atr * 0.8
    tp = snapshot.close + snapshot.atr * 1.6 if side == "long" else snapshot.close - snapshot.atr * 1.6
    notional, stop_bps = risk_geometry(entry=snapshot.close, stop=stop,
        risk_fraction=cfg.risk_fraction_of_equity, exposure_cap=cfg.max_notional_fraction_of_equity)
    move_budget_bps = abs(tp - snapshot.close) / snapshot.close * 10_000.0
    ratio = move_budget_bps / verified_round_trip_cost_bps
    if ratio < cfg.min_cost_budget_ratio:
        return hold_intent(strategy_id=sid, policy_schema="zel.decision_intent.v2",
            source_sha=policy_source_sha, config_sha=cfg.sha, feature_sha=snapshot.feature_sha,
            evidence_ids=EVIDENCE[sid], symbol=snapshot.symbol, signal_ts=snapshot.signal_ts,
            entry_rule=f"{sid}:closed_bar_reversal", strength_normalization="bounded_0_1",
            regime=regime, reasons=("COST_BUDGET_FAIL",), verified_cost_bps=verified_round_trip_cost_bps,
            timeout_bars=cfg.timeout_bars, risk_fraction=cfg.risk_fraction_of_equity,
            exposure_cap=cfg.max_notional_fraction_of_equity)
    return DecisionIntent(schema_version="zel.decision_intent.v2", strategy_id=sid,
        source_sha=policy_source_sha, config_sha=cfg.sha, feature_sha=snapshot.feature_sha,
        evidence_ids=EVIDENCE[sid], symbol=snapshot.symbol, side=side, signal_ts=snapshot.signal_ts,
        entry_rule=f"{sid}:closed_bar_reversal", entry_strength=float(strength),
        strength_normalization="bounded_0_1", regime=regime, no_trade=False,
        invalidation={"type":"structural_atr_stop","atr_multiple":0.8},
        risk_size={"risk_fraction_of_equity":cfg.risk_fraction_of_equity,"stop_distance_bps":stop_bps},
        exposure={"notional_fraction_of_equity":notional,"cap":cfg.max_notional_fraction_of_equity},
        sl=stop, tp=tp, timeout={"bars":cfg.timeout_bars}, partial={"enabled":False},
        trailing={"enabled":False}, runner={"enabled":False},
        pyramiding={"enabled":False,"adverse_add":False}, cooldown={"one_entry_per_transition":True},
        turnover={"duplicate_transition_forbidden":True}, reason_codes=("QUALIFYING_REVERSAL",),
        verified_round_trip_cost_bps=float(verified_round_trip_cost_bps),
        move_budget_bps=move_budget_bps, cost_budget_ratio=ratio)
