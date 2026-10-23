from __future__ import annotations

from dataclasses import asdict, dataclass
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

HOUR_MS = 3_600_000


@dataclass(frozen=True)
class TrendPolicyConfig:
    timeframe_ms: int = HOUR_MS
    atr_len: int = 14
    ema_fast_len: int = 21
    ema_slow_len: int = 55
    ema_trend_len: int = 50
    supertrend_len: int = 10
    supertrend_mult: float = 3.0
    max_stale_intervals: int = 2
    risk_fraction_of_equity: float = 0.005
    max_notional_fraction_of_equity: float = 0.15
    min_cost_budget_ratio: float = 1.25
    timeout_bars: int = 48

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
    "supertrend_pullback": (
        "HIST_R7_SUPERTREND_PULLBACK",
        "TSMOM_MOSKOWITZ_OSOI_PEDERSEN",
        "BINGX_FEE_SCHEDULE",
    ),
    "trend_ma_macd": (
        "HIST_R7_TREND_MA_MACD",
        "TSMOM_MOSKOWITZ_OSOI_PEDERSEN",
        "BINGX_FEE_SCHEDULE",
    ),
    "trend_rider": (
        "HIST_R7_TREND_RIDER",
        "TSMOM_MOSKOWITZ_OSOI_PEDERSEN",
        "BINGX_FEE_SCHEDULE",
    ),
}


def _fresh(signal_ts: int, now_ts_ms: int, cfg: TrendPolicyConfig) -> bool:
    return 0 <= int(now_ts_ms) - int(signal_ts) <= cfg.max_stale_intervals * cfg.timeframe_ms


def _macd_hist(closes: Sequence[float]) -> list[float]:
    fast = ema(closes, 12)
    slow = ema(closes, 26)
    macd = [a - b for a, b in zip(fast, slow)]
    signal = ema(macd, 9)
    return [a - b for a, b in zip(macd, signal)]


def _supertrend_state(bars: Sequence[Mapping[str, Any]], cfg: TrendPolicyConfig) -> tuple[float, int]:
    validate_bars(bars, minimum=max(cfg.supertrend_len + 3, 20))
    highs = [f(b, "high") for b in bars]
    lows = [f(b, "low") for b in bars]
    closes = [f(b, "close") for b in bars]
    line = (highs[0] + lows[0]) / 2.0
    direction = 1
    final_upper = line
    final_lower = line
    prev_line = line
    prev_close = closes[0]
    for i in range(1, len(bars)):
        a = atr(bars[: i + 1], min(cfg.supertrend_len, i + 1))
        hl2 = (highs[i] + lows[i]) / 2.0
        upper = hl2 + cfg.supertrend_mult * a
        lower = hl2 - cfg.supertrend_mult * a
        final_upper = upper if upper < final_upper or prev_close > final_upper else final_upper
        final_lower = lower if lower > final_lower or prev_close < final_lower else final_lower
        if prev_line == final_upper:
            if closes[i] <= final_upper:
                line, direction = final_upper, -1
            else:
                line, direction = final_lower, 1
        else:
            if closes[i] >= final_lower:
                line, direction = final_lower, 1
            else:
                line, direction = final_upper, -1
        prev_line, prev_close = line, closes[i]
    return float(line), int(direction)


def _snapshot(strategy_id: str, symbol: str, bars: Sequence[Mapping[str, Any]], now_ts_ms: int,
              close: float, a: float, values: Mapping[str, Any], cfg: TrendPolicyConfig) -> FeatureSnapshot:
    signal_ts = ts(bars[-1])
    body = {"strategy_id": strategy_id, "symbol": symbol, "signal_ts": signal_ts,
            "close": close, "atr": a, "values": values}
    return FeatureSnapshot(strategy_id, symbol, signal_ts, _fresh(signal_ts, now_ts_ms, cfg),
                           close, a, values, digest(body))


def compute_supertrend_pullback_feature(bars: Sequence[Mapping[str, Any]], *, symbol: str, now_ts_ms: int,
                                        config: TrendPolicyConfig | None = None) -> FeatureSnapshot:
    cfg = config or TrendPolicyConfig()
    validate_bars(bars, minimum=64)
    closes = [f(b, "close") for b in bars]
    a = atr(bars, cfg.atr_len)
    trend = ema(closes, cfg.ema_trend_len)
    st, direction = _supertrend_state(bars, cfg)
    close = closes[-1]
    prev_close = closes[-2]
    long_align = direction == 1 and close > trend[-1] and trend[-1] > trend[-2]
    short_align = direction == -1 and close < trend[-1] and trend[-1] < trend[-2]
    pullback_depth_atr = abs(prev_close - trend[-2]) / max(a, 1e-12)
    long_reclaim = long_align and prev_close <= trend[-2] + 0.75 * a and close > prev_close
    short_reclaim = short_align and prev_close >= trend[-2] - 0.75 * a and close < prev_close
    values = {"supertrend": st, "direction": direction, "ema50": trend[-1],
              "pullback_depth_atr": pullback_depth_atr, "long_reclaim": long_reclaim,
              "short_reclaim": short_reclaim, "chase_atr": abs(close - trend[-1]) / max(a, 1e-12)}
    return _snapshot("supertrend_pullback", symbol, bars, now_ts_ms, close, a, values, cfg)


def compute_trend_ma_macd_feature(bars: Sequence[Mapping[str, Any]], *, symbol: str, now_ts_ms: int,
                                  config: TrendPolicyConfig | None = None) -> FeatureSnapshot:
    cfg = config or TrendPolicyConfig()
    validate_bars(bars, minimum=64)
    closes = [f(b, "close") for b in bars]
    a = atr(bars, cfg.atr_len)
    fast = ema(closes, cfg.ema_fast_len)
    slow = ema(closes, cfg.ema_slow_len)
    hist = _macd_hist(closes)
    close = closes[-1]
    long_cross = close > fast[-1] > slow[-1] and hist[-2] <= 0 < hist[-1]
    short_cross = close < fast[-1] < slow[-1] and hist[-2] >= 0 > hist[-1]
    impulse_atr = abs(hist[-1] - hist[-2]) / max(a, 1e-12)
    values = {"ema_fast": fast[-1], "ema_slow": slow[-1], "hist": hist[-1],
              "hist_prev": hist[-2], "long_cross": long_cross, "short_cross": short_cross,
              "impulse_atr": impulse_atr, "chase_atr": abs(close - fast[-1]) / max(a, 1e-12)}
    return _snapshot("trend_ma_macd", symbol, bars, now_ts_ms, close, a, values, cfg)


def compute_trend_rider_feature(bars: Sequence[Mapping[str, Any]], *, symbol: str, now_ts_ms: int,
                                config: TrendPolicyConfig | None = None) -> FeatureSnapshot:
    cfg = config or TrendPolicyConfig()
    validate_bars(bars, minimum=64)
    closes = [f(b, "close") for b in bars]
    a = atr(bars, cfg.atr_len)
    trend = ema(closes, cfg.ema_trend_len)
    st, direction = _supertrend_state(bars, cfg)
    close = closes[-1]
    prev = bars[-2]
    prev_green = f(prev, "close") >= f(prev, "open")
    prev_red = f(prev, "close") <= f(prev, "open")
    long_confirm = direction == 1 and close > st and close > trend[-1] and trend[-1] > trend[-2] and prev_green
    short_confirm = direction == -1 and close < st and close < trend[-1] and trend[-1] < trend[-2] and prev_red
    values = {"supertrend": st, "direction": direction, "ema50": trend[-1],
              "long_confirm": long_confirm, "short_confirm": short_confirm,
              "st_gap_atr": abs(close - st) / max(a, 1e-12),
              "chase_atr": abs(close - trend[-1]) / max(a, 1e-12)}
    return _snapshot("trend_rider", symbol, bars, now_ts_ms, close, a, values, cfg)


def _build(feature: FeatureSnapshot, *, policy_source_sha: str, verified_round_trip_cost_bps: float,
           config: TrendPolicyConfig | None = None) -> DecisionIntent:
    cfg = config or TrendPolicyConfig()
    validate_authority(policy_source_sha=policy_source_sha,
                       verified_round_trip_cost_bps=verified_round_trip_cost_bps)
    sid = feature.strategy_id
    if sid not in EVIDENCE:
        raise ValueError("UNKNOWN_STRATEGY")
    schema = f"zel.{sid}.policy.v1"
    entry_rule = {
        "supertrend_pullback": "closed_bar_supertrend_ema_pullback_reclaim",
        "trend_ma_macd": "closed_bar_ema21_55_macd_histogram_cross",
        "trend_rider": "closed_bar_supertrend_ema_continuation_confirmation",
    }[sid]
    strength_norm = "causal_signal_quality_over_atr_clipped_0_2_then_divide_2"
    if not feature.fresh:
        return hold_intent(strategy_id=sid, policy_schema=schema, source_sha=policy_source_sha,
                           config_sha=cfg.sha, feature_sha=feature.feature_sha, evidence_ids=EVIDENCE[sid],
                           symbol=feature.symbol, signal_ts=feature.signal_ts, entry_rule=entry_rule,
                           strength_normalization=strength_norm, regime="NO_TRADE_STALE",
                           reasons=("STALE_SOURCE_FAIL_CLOSED",), verified_cost_bps=verified_round_trip_cost_bps,
                           timeout_bars=cfg.timeout_bars, risk_fraction=cfg.risk_fraction_of_equity,
                           exposure_cap=cfg.max_notional_fraction_of_equity)
    v = feature.values
    if sid == "supertrend_pullback":
        long_ok = bool(v["long_reclaim"] and 0.15 <= float(v["pullback_depth_atr"]) <= 2.0 and float(v["chase_atr"]) <= 1.5)
        short_ok = bool(v["short_reclaim"] and 0.15 <= float(v["pullback_depth_atr"]) <= 2.0 and float(v["chase_atr"]) <= 1.5)
        strength_raw = min(2.0, float(v["pullback_depth_atr"]) + 0.5)
        regime = "SUPERTREND_PULLBACK_CONTINUATION"
    elif sid == "trend_ma_macd":
        long_ok = bool(v["long_cross"] and float(v["chase_atr"]) <= 1.5)
        short_ok = bool(v["short_cross"] and float(v["chase_atr"]) <= 1.5)
        strength_raw = min(2.0, 0.5 + 10.0 * float(v["impulse_atr"]))
        regime = "EMA_MACD_TREND_REACCELERATION"
    else:
        long_ok = bool(v["long_confirm"] and float(v["st_gap_atr"]) >= 0.10 and float(v["chase_atr"]) <= 2.0)
        short_ok = bool(v["short_confirm"] and float(v["st_gap_atr"]) >= 0.10 and float(v["chase_atr"]) <= 2.0)
        strength_raw = min(2.0, float(v["st_gap_atr"]))
        regime = "SUPERTREND_EMA_PERSISTENCE"

    if long_ok == short_ok:
        return hold_intent(strategy_id=sid, policy_schema=schema, source_sha=policy_source_sha,
                           config_sha=cfg.sha, feature_sha=feature.feature_sha, evidence_ids=EVIDENCE[sid],
                           symbol=feature.symbol, signal_ts=feature.signal_ts, entry_rule=entry_rule,
                           strength_normalization=strength_norm, regime="NO_TRADE",
                           reasons=("NO_UNAMBIGUOUS_ENTRY",), verified_cost_bps=verified_round_trip_cost_bps,
                           timeout_bars=cfg.timeout_bars, risk_fraction=cfg.risk_fraction_of_equity,
                           exposure_cap=cfg.max_notional_fraction_of_equity)
    side = "long" if long_ok else "short"
    entry = feature.close
    stop = entry - 1.5 * feature.atr if side == "long" else entry + 1.5 * feature.atr
    notional, risk_distance_bps = risk_geometry(entry=entry, stop=stop,
                                                 risk_fraction=cfg.risk_fraction_of_equity,
                                                 exposure_cap=cfg.max_notional_fraction_of_equity)
    move_budget_bps = risk_distance_bps * 2.0
    ratio = move_budget_bps / verified_round_trip_cost_bps
    if ratio < cfg.min_cost_budget_ratio:
        return hold_intent(strategy_id=sid, policy_schema=schema, source_sha=policy_source_sha,
                           config_sha=cfg.sha, feature_sha=feature.feature_sha, evidence_ids=EVIDENCE[sid],
                           symbol=feature.symbol, signal_ts=feature.signal_ts, entry_rule=entry_rule,
                           strength_normalization=strength_norm, regime="NO_TRADE_COST",
                           reasons=("STRUCTURAL_COST_BUDGET_BELOW_MIN",), verified_cost_bps=verified_round_trip_cost_bps,
                           timeout_bars=cfg.timeout_bars, risk_fraction=cfg.risk_fraction_of_equity,
                           exposure_cap=cfg.max_notional_fraction_of_equity)
    return DecisionIntent(
        schema_version=schema, strategy_id=sid, source_sha=policy_source_sha, config_sha=cfg.sha,
        feature_sha=feature.feature_sha, evidence_ids=EVIDENCE[sid], symbol=feature.symbol, side=side,
        signal_ts=feature.signal_ts, entry_rule=entry_rule,
        entry_strength=min(1.0, max(0.0, strength_raw) / 2.0), strength_normalization=strength_norm,
        regime=regime, no_trade=False,
        invalidation={"initial_stop": stop, "hard_no_adverse_add": True},
        risk_size={"risk_fraction_of_equity": cfg.risk_fraction_of_equity,
                   "risk_distance_bps": risk_distance_bps},
        exposure={"notional_fraction_of_equity": notional, "cap": cfg.max_notional_fraction_of_equity},
        sl=stop, tp=None, timeout={"bars": cfg.timeout_bars}, partial={"enabled": False},
        trailing={"enabled": True, "type": "atr_structure_after_favorable_progress"},
        runner={"enabled": True, "take_profit_owned_by_policy": False},
        pyramiding={"enabled": False, "adverse_add": False},
        cooldown={"bars": 2, "one_entry_per_transition": True},
        turnover={"duplicate_transition_forbidden": True, "max_new_entries_per_bar": 1},
        reason_codes=("ENTRY_POLICY_PASS",), verified_round_trip_cost_bps=float(verified_round_trip_cost_bps),
        move_budget_bps=move_budget_bps, cost_budget_ratio=ratio,
    )


def build_supertrend_pullback_intent(feature: FeatureSnapshot, **kwargs: Any) -> DecisionIntent:
    if feature.strategy_id != "supertrend_pullback":
        raise ValueError("FEATURE_STRATEGY_MISMATCH")
    return _build(feature, **kwargs)


def build_trend_ma_macd_intent(feature: FeatureSnapshot, **kwargs: Any) -> DecisionIntent:
    if feature.strategy_id != "trend_ma_macd":
        raise ValueError("FEATURE_STRATEGY_MISMATCH")
    return _build(feature, **kwargs)


def build_trend_rider_intent(feature: FeatureSnapshot, **kwargs: Any) -> DecisionIntent:
    if feature.strategy_id != "trend_rider":
        raise ValueError("FEATURE_STRATEGY_MISMATCH")
    return _build(feature, **kwargs)
