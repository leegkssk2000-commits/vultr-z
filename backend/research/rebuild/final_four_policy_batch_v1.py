from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from backend.research.rebuild.policy_kernel_v1 import (
    DecisionIntent,
    atr,
    digest,
    ema,
    f,
    hold_intent,
    risk_geometry,
    ts,
    validate_authority,
    validate_bars,
)

FIVE_MIN_MS = 300_000
SUPPORTED = ("grid_rebalance", "rbreaker_like", "session_bias", "sr_levels")


@dataclass(frozen=True)
class FinalFourConfig:
    timeframe_ms: int = FIVE_MIN_MS
    atr_len: int = 14
    max_stale_intervals: int = 2
    risk_fraction_of_equity: float = 0.0035
    max_notional_fraction_of_equity: float = 0.10
    min_cost_budget_ratio: float = 1.25
    timeout_bars: int = 36

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
    side: str
    regime: str
    strength: float
    entry_rule: str
    stop_mult: float
    rr: float
    values: Mapping[str, Any]
    feature_sha: str


EVIDENCE = {
    "grid_rebalance": ("HIST_R7_FINAL4", "GRID_DGT_2025", "BINGX_FEE_SCHEDULE"),
    "rbreaker_like": ("HIST_R7_FINAL4", "SR_WILEY", "PRICE_BARRIERS", "BINGX_FEE_SCHEDULE"),
    "session_bias": ("HIST_R7_FINAL4", "BTC_INTRADAY_2019", "BTC_INTRADAY_2022", "CRYPTO_PERIODICITY", "BINGX_FEE_SCHEDULE"),
    "sr_levels": ("HIST_R7_FINAL4", "SR_WILEY", "PRICE_BARRIERS", "BINGX_FEE_SCHEDULE"),
}

POLICY_SCHEMA = "zel.complete_policy.final_four.v2"


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(x)))


def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs)


def _fresh(last_ts: int, now_ms: int, cfg: FinalFourConfig) -> bool:
    return 0 <= now_ms - last_ts <= cfg.timeframe_ms * cfg.max_stale_intervals


def _base_series(bars: Sequence[Mapping[str, Any]], minimum: int) -> tuple[list[float], list[float], list[float], list[float], list[float]]:
    validate_bars(bars, minimum=minimum)
    opens = [f(b, "open") for b in bars]
    highs = [f(b, "high") for b in bars]
    lows = [f(b, "low") for b in bars]
    closes = [f(b, "close") for b in bars]
    volumes = [f(b, "volume", positive=False) if "volume" in b else 0.0 for b in bars]
    return opens, highs, lows, closes, volumes


def _feature_sha(payload: Mapping[str, Any]) -> str:
    return digest(payload)


def _grid_features(bars: Sequence[Mapping[str, Any]], symbol: str, now_ms: int, cfg: FinalFourConfig) -> FeatureSnapshot:
    opens, highs, lows, closes, volumes = _base_series(bars, 120)
    a = atr(bars, cfg.atr_len)
    price = closes[-1]
    prev = closes[-2]
    anchor = _mean(closes[-97:-1])
    grid_step = max(price * 0.0030, a * 0.55)
    k = (price - anchor) / max(grid_step, 1e-12)
    ef = ema(closes, 21)
    es = ema(closes, 55)
    trend_long = price > ef[-1] > es[-1] and ef[-1] >= ef[-2]
    trend_short = price < ef[-1] < es[-1] and ef[-1] <= ef[-2]
    reclaim_long = price > prev + a * 0.10
    reclaim_short = price < prev - a * 0.10
    side = "flat"
    if k <= -1.10 and reclaim_long and not trend_short:
        side = "long"
    elif k >= 1.10 and reclaim_short and not trend_long:
        side = "short"
    chase = abs(k) > 2.40 and abs(price - ef[-1]) / max(a, 1e-12) > 2.40
    atr_pct = a / price * 100.0
    valid_regime = 0.10 <= atr_pct <= 3.20 and not chase
    if not valid_regime:
        side = "flat"
    strength = _clamp((abs(k) - 1.10) / 1.40) if side != "flat" else 0.0
    values = {"anchor": anchor, "grid_step": grid_step, "k": k, "atr_pct": atr_pct, "trend_long": trend_long, "trend_short": trend_short, "chase": chase}
    return FeatureSnapshot("grid_rebalance", symbol, ts(bars[-1]), _fresh(ts(bars[-1]), now_ms, cfg), price, a, side, "bounded_range" if valid_regime else "no_trade", strength, "anchor_excursion_reclaim", 1.25 * grid_step / max(a, 1e-12), 1.50, values, _feature_sha(values))


def _rbreaker_features(bars: Sequence[Mapping[str, Any]], symbol: str, now_ms: int, cfg: FinalFourConfig) -> FeatureSnapshot:
    opens, highs, lows, closes, volumes = _base_series(bars, 90)
    a = atr(bars, cfg.atr_len)
    price = closes[-1]
    prior_hi = max(highs[-49:-1])
    prior_lo = min(lows[-49:-1])
    ef = ema(closes, 21)
    es = ema(closes, 55)
    buffer = a * 0.12
    long_break = price > prior_hi + buffer and price > ef[-1] > es[-1]
    short_break = price < prior_lo - buffer and price < ef[-1] < es[-1]
    prev_close = closes[-2]
    long_reversal = lows[-1] < prior_lo - a * 0.22 and price > prior_lo + a * 0.16 and price > prev_close
    short_reversal = highs[-1] > prior_hi + a * 0.22 and price < prior_hi - a * 0.16 and price < prev_close
    side = "long" if (long_break or long_reversal) else "short" if (short_break or short_reversal) else "flat"
    dist = max((price - prior_hi) / max(a, 1e-12), (prior_lo - price) / max(a, 1e-12), 0.0)
    chase = dist > 1.70
    atr_pct = a / price * 100.0
    valid_regime = 0.18 <= atr_pct <= 5.80 and not chase
    if not valid_regime:
        side = "flat"
    strength = _clamp(abs(price - (prior_hi if side == "long" else prior_lo if side == "short" else price)) / max(a * 1.5, 1e-12)) if side != "flat" else 0.0
    mode = "breakout" if long_break or short_break else "failed_break_reversal" if long_reversal or short_reversal else "none"
    values = {"prior_hi": prior_hi, "prior_lo": prior_lo, "mode": mode, "atr_pct": atr_pct, "chase": chase}
    return FeatureSnapshot("rbreaker_like", symbol, ts(bars[-1]), _fresh(ts(bars[-1]), now_ms, cfg), price, a, side, mode if valid_regime else "no_trade", strength, "prior_range_break_or_reclaim", 0.95, 2.00, values, _feature_sha(values))


def _session_name(signal_ts: int) -> str:
    hour = datetime.fromtimestamp(signal_ts / 1000.0, tz=timezone.utc).hour
    if 0 <= hour < 8:
        return "asia"
    if 8 <= hour < 13:
        return "london"
    if 13 <= hour < 16:
        return "london_newyork_overlap"
    if 16 <= hour < 21:
        return "newyork"
    return "offpeak"


def _session_features(bars: Sequence[Mapping[str, Any]], symbol: str, now_ms: int, cfg: FinalFourConfig) -> FeatureSnapshot:
    opens, highs, lows, closes, volumes = _base_series(bars, 90)
    a = atr(bars, cfg.atr_len)
    price = closes[-1]
    prior_hi = max(highs[-25:-1])
    prior_lo = min(lows[-25:-1])
    ef = ema(closes, 21)
    es = ema(closes, 55)
    long_ok = price > prior_hi + a * 0.10 and price > closes[-2] + a * 0.16 and price > ef[-1] > es[-1]
    short_ok = price < prior_lo - a * 0.10 and price < closes[-2] - a * 0.16 and price < ef[-1] < es[-1]
    side = "long" if long_ok else "short" if short_ok else "flat"
    session = _session_name(ts(bars[-1]))
    atr_pct = a / price * 100.0
    chase = abs(price - ef[-1]) / max(a, 1e-12) > 1.70
    valid_regime = 0.18 <= atr_pct <= 5.50 and not chase
    if not valid_regime:
        side = "flat"
    strength = _clamp(abs(price - (prior_hi if side == "long" else prior_lo if side == "short" else price)) / max(a, 1e-12)) if side != "flat" else 0.0
    values = {"session": session, "prior_hi": prior_hi, "prior_lo": prior_lo, "atr_pct": atr_pct, "chase": chase}
    return FeatureSnapshot("session_bias", symbol, ts(bars[-1]), _fresh(ts(bars[-1]), now_ms, cfg), price, a, side, session if valid_regime else "no_trade", strength, "session_range_expansion", 1.15, 1.90, values, _feature_sha(values))


def _sr_features(bars: Sequence[Mapping[str, Any]], symbol: str, now_ms: int, cfg: FinalFourConfig) -> FeatureSnapshot:
    opens, highs, lows, closes, volumes = _base_series(bars, 90)
    if any(v < 0 for v in volumes) or sum(volumes[-50:]) <= 0:
        raise ValueError("VOLUME_UNAVAILABLE")
    a = atr(bars, cfg.atr_len)
    price = closes[-1]
    prior_hi = max(highs[-51:-1])
    prior_lo = min(lows[-51:-1])
    vol_ma = _mean(volumes[-51:-1])
    rel_vol = volumes[-1] / max(vol_ma, 1e-12)
    e = ema(closes, 34)
    long_ok = price > prior_hi + a * 0.12 and rel_vol >= 1.80 and price > e[-1] and e[-1] > e[-2]
    short_ok = price < prior_lo - a * 0.12 and rel_vol >= 1.80 and price < e[-1] and e[-1] < e[-2]
    side = "long" if long_ok else "short" if short_ok else "flat"
    atr_pct = a / price * 100.0
    chase = abs(price - e[-1]) / max(a, 1e-12) > 1.80
    valid_regime = 0.22 <= atr_pct <= 6.20 and not chase
    if not valid_regime:
        side = "flat"
    strength = _clamp((rel_vol - 1.80) / 1.50) if side != "flat" else 0.0
    values = {"prior_hi": prior_hi, "prior_lo": prior_lo, "relative_volume": rel_vol, "atr_pct": atr_pct, "chase": chase}
    return FeatureSnapshot("sr_levels", symbol, ts(bars[-1]), _fresh(ts(bars[-1]), now_ms, cfg), price, a, side, "volume_confirmed_breakout" if valid_regime else "no_trade", strength, "prior_sr_break_volume_confirmed", 1.20, 2.00, values, _feature_sha(values))


def features(strategy_id: str, bars: Sequence[Mapping[str, Any]], *, symbol: str, now_ms: int, config: FinalFourConfig | None = None) -> FeatureSnapshot:
    cfg = config or FinalFourConfig()
    if strategy_id not in SUPPORTED:
        raise ValueError("UNSUPPORTED_STRATEGY")
    fn = {"grid_rebalance": _grid_features, "rbreaker_like": _rbreaker_features, "session_bias": _session_features, "sr_levels": _sr_features}[strategy_id]
    return fn(bars, symbol, now_ms, cfg)


def intent_from_snapshot(snapshot: FeatureSnapshot, *, policy_source_sha: str, verified_round_trip_cost_bps: float, config: FinalFourConfig | None = None) -> DecisionIntent:
    cfg = config or FinalFourConfig()
    validate_authority(policy_source_sha=policy_source_sha, verified_round_trip_cost_bps=verified_round_trip_cost_bps)
    if not snapshot.fresh or snapshot.side == "flat":
        reasons = ("STALE_INPUT",) if not snapshot.fresh else ("NO_QUALIFYING_EVENT",)
        return hold_intent(strategy_id=snapshot.strategy_id, policy_schema=POLICY_SCHEMA, source_sha=policy_source_sha, config_sha=cfg.sha, feature_sha=snapshot.feature_sha, evidence_ids=EVIDENCE[snapshot.strategy_id], symbol=snapshot.symbol, signal_ts=snapshot.signal_ts, entry_rule=snapshot.entry_rule, strength_normalization="bounded_0_1", regime=snapshot.regime, reasons=reasons, verified_cost_bps=verified_round_trip_cost_bps, timeout_bars=cfg.timeout_bars, risk_fraction=cfg.risk_fraction_of_equity, exposure_cap=cfg.max_notional_fraction_of_equity)
    stop = snapshot.close - snapshot.atr * snapshot.stop_mult if snapshot.side == "long" else snapshot.close + snapshot.atr * snapshot.stop_mult
    notional, stop_bps = risk_geometry(entry=snapshot.close, stop=stop, risk_fraction=cfg.risk_fraction_of_equity, exposure_cap=cfg.max_notional_fraction_of_equity)
    target_distance = abs(snapshot.close - stop) * snapshot.rr
    tp = snapshot.close + target_distance if snapshot.side == "long" else snapshot.close - target_distance
    move_budget_bps = target_distance / snapshot.close * 10_000.0
    ratio = move_budget_bps / verified_round_trip_cost_bps
    if ratio < cfg.min_cost_budget_ratio:
        return hold_intent(strategy_id=snapshot.strategy_id, policy_schema=POLICY_SCHEMA, source_sha=policy_source_sha, config_sha=cfg.sha, feature_sha=snapshot.feature_sha, evidence_ids=EVIDENCE[snapshot.strategy_id], symbol=snapshot.symbol, signal_ts=snapshot.signal_ts, entry_rule=snapshot.entry_rule, strength_normalization="bounded_0_1", regime="cost_infeasible", reasons=("COST_BUDGET_FAIL",), verified_cost_bps=verified_round_trip_cost_bps, timeout_bars=cfg.timeout_bars, risk_fraction=cfg.risk_fraction_of_equity, exposure_cap=cfg.max_notional_fraction_of_equity)
    return DecisionIntent(schema_version=POLICY_SCHEMA, strategy_id=snapshot.strategy_id, source_sha=policy_source_sha, config_sha=cfg.sha, feature_sha=snapshot.feature_sha, evidence_ids=EVIDENCE[snapshot.strategy_id], symbol=snapshot.symbol, side=snapshot.side, signal_ts=snapshot.signal_ts, entry_rule=snapshot.entry_rule, entry_strength=snapshot.strength, strength_normalization="bounded_0_1", regime=snapshot.regime, no_trade=False, invalidation={"type": "structural_stop", "stop_atr_mult": snapshot.stop_mult}, risk_size={"risk_fraction_of_equity": cfg.risk_fraction_of_equity, "stop_distance_bps": stop_bps}, exposure={"notional_fraction_of_equity": notional, "cap": cfg.max_notional_fraction_of_equity}, sl=stop, tp=tp, timeout={"bars": cfg.timeout_bars}, partial={"enabled": False}, trailing={"enabled": False}, runner={"enabled": False}, pyramiding={"enabled": False, "adverse_add": False}, cooldown={"one_entry_per_transition": True}, turnover={"duplicate_transition_forbidden": True}, reason_codes=("QUALIFYING_CLOSED_BAR", snapshot.regime), verified_round_trip_cost_bps=float(verified_round_trip_cost_bps), move_budget_bps=move_budget_bps, cost_budget_ratio=ratio)


def evaluate(strategy_id: str, bars: Sequence[Mapping[str, Any]], *, symbol: str, now_ms: int, policy_source_sha: str, verified_round_trip_cost_bps: float, config: FinalFourConfig | None = None) -> DecisionIntent:
    cfg = config or FinalFourConfig()
    try:
        snap = features(strategy_id, bars, symbol=symbol, now_ms=now_ms, config=cfg)
    except ValueError as exc:
        validate_authority(policy_source_sha=policy_source_sha, verified_round_trip_cost_bps=verified_round_trip_cost_bps)
        signal_ts = ts(bars[-1]) if bars else int(now_ms)
        feature_sha = digest({"strategy_id": strategy_id, "error": str(exc), "signal_ts": signal_ts})
        return hold_intent(strategy_id=strategy_id, policy_schema=POLICY_SCHEMA, source_sha=policy_source_sha, config_sha=cfg.sha, feature_sha=feature_sha, evidence_ids=EVIDENCE.get(strategy_id, ()), symbol=symbol, signal_ts=signal_ts, entry_rule="fail_closed", strength_normalization="bounded_0_1", regime="invalid_input", reasons=(str(exc),), verified_cost_bps=verified_round_trip_cost_bps, timeout_bars=cfg.timeout_bars, risk_fraction=cfg.risk_fraction_of_equity, exposure_cap=cfg.max_notional_fraction_of_equity)
    return intent_from_snapshot(snap, policy_source_sha=policy_source_sha, verified_round_trip_cost_bps=verified_round_trip_cost_bps, config=cfg)
