from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import pandas as pd

from backend.strategies.semantic_common import (
    DecisionContext,
    LBotStrategyBase,
    StrategyDecision,
    atr,
    build_result,
    close_location,
    decision_from_context,
    ema,
    infer_position_state,
    invalid_result,
    prepare_ohlcv,
    to_float,
)


@dataclass
class PivotReversalConfig:
    window: int = 9
    pivot_span: int = 3
    atr_len: int = 14
    ema_fast_len: int = 21
    ema_slow_len: int = 55
    min_bars: int = 90
    min_atr_pct: float = 0.14
    max_atr_pct: float = 5.20
    pivot_zone_pct: float = 0.0022
    min_reclaim_atr: float = 0.12
    max_chase_dist_atr: float = 1.35
    fail_pivot_break_atr: float = 0.20
    wick_body_min: float = 1.60
    beam_wick_body_min: float = 2.20
    beam_close_location_min: float = 0.62
    stop_atr_mult: float = 0.58
    trail_atr_mult: float = 0.42
    base_rr: float = 1.90
    beam_rr: float = 2.40
    long_base_size: float = 0.44
    short_base_size: float = 0.34
    beam_bonus_long: float = 0.12
    beam_bonus_short: float = 0.10
    add_size_long: float = 0.12
    add_size_short: float = 0.10
    reduce_size_long: float = 0.22
    reduce_size_short: float = 0.20
    max_add_count: int = 1
    max_pyramiding: int = 2


def _last_confirmed_pivots(frame: pd.DataFrame, cfg: PivotReversalConfig) -> Tuple[Optional[Tuple[int, float]], Optional[Tuple[int, float]]]:
    span = max(int(cfg.pivot_span), 1)
    start = max(span, len(frame) - max(cfg.window * 4, 36))
    end = len(frame) - span - 1  # excludes the signal bar and requires right-side confirmation
    last_high: Optional[Tuple[int, float]] = None
    last_low: Optional[Tuple[int, float]] = None
    for i in range(start, end + 1):
        high_window = frame["high"].iloc[i - span:i + span + 1]
        low_window = frame["low"].iloc[i - span:i + span + 1]
        high_value = to_float(frame["high"].iloc[i])
        low_value = to_float(frame["low"].iloc[i])
        if high_value == to_float(high_window.max()) and int((high_window == high_value).sum()) == 1:
            last_high = (i, high_value)
        if low_value == to_float(low_window.min()) and int((low_window == low_value).sum()) == 1:
            last_low = (i, low_value)
    return last_high, last_low


def strategy(
    df: pd.DataFrame,
    *,
    state: Optional[Dict[str, Any]] = None,
    risk_action: str = "hold",
    config: Optional[PivotReversalConfig] = None,
) -> Dict[str, Any]:
    cfg = config or PivotReversalConfig()
    frame = prepare_ohlcv(df)
    if frame is None:
        return invalid_result("pivot_invalid_input", cfg.max_pyramiding)
    if len(frame) < max(cfg.min_bars, cfg.window * 4, cfg.ema_slow_len + 5):
        return invalid_result("pivot_short", cfg.max_pyramiding, tags=["warmup"])
    if str(risk_action or "hold").lower() in {"block", "stop", "rollback"}:
        return invalid_result(f"risk_gate_{risk_action}", cfg.max_pyramiding, tags=["risk_gated"])

    frame["atr"] = atr(frame, cfg.atr_len)
    frame["ema_fast"] = ema(frame["close"], cfg.ema_fast_len)
    frame["ema_slow"] = ema(frame["close"], cfg.ema_slow_len)
    last, prev = frame.iloc[-1], frame.iloc[-2]
    pivot_high, pivot_low = _last_confirmed_pivots(frame, cfg)
    if pivot_high is None or pivot_low is None:
        return invalid_result("pivot_confirmed_structure_missing", cfg.max_pyramiding, tags=["pivot_gate"])

    high_idx, swing_high = pivot_high
    low_idx, swing_low = pivot_low
    price = to_float(last["close"])
    open_ = to_float(last["open"])
    high = to_float(last["high"])
    low = to_float(last["low"])
    prev_close = to_float(prev["close"])
    atr_now = to_float(last["atr"])
    ema_fast = to_float(last["ema_fast"])
    ema_slow = to_float(last["ema_slow"])
    ema_fast_prev = to_float(prev["ema_fast"])
    ema_slow_prev = to_float(prev["ema_slow"])
    if min(price, atr_now, ema_fast, ema_slow, swing_high, swing_low) <= 0:
        return invalid_result("pivot_indicator_nan", cfg.max_pyramiding, tags=["indicator_nan"])

    zone_high = max(swing_high * cfg.pivot_zone_pct, atr_now * 0.12)
    zone_low = max(swing_low * cfg.pivot_zone_pct, atr_now * 0.12)
    body = max(abs(price - open_), atr_now * 0.02)
    upper_wick = max(high - max(price, open_), 0.0)
    lower_wick = max(min(price, open_) - low, 0.0)
    close_loc = close_location(price, low, high)
    trend_long = price > ema_fast > ema_slow and ema_fast >= ema_fast_prev and ema_slow >= ema_slow_prev
    trend_short = price < ema_fast < ema_slow and ema_fast <= ema_fast_prev and ema_slow <= ema_slow_prev

    touched_high = high >= swing_high - zone_high and price < swing_high
    touched_low = low <= swing_low + zone_low and price > swing_low
    bearish_reject = price < open_ and upper_wick >= body * cfg.wick_body_min
    bullish_reject = price > open_ and lower_wick >= body * cfg.wick_body_min
    short_reclaim = price < prev_close - atr_now * cfg.min_reclaim_atr
    long_reclaim = price > prev_close + atr_now * cfg.min_reclaim_atr
    short_setup = touched_high and bearish_reject and short_reclaim and not trend_long
    long_setup = touched_low and bullish_reject and long_reclaim and not trend_short
    short_beam = (
        short_setup and upper_wick >= body * cfg.beam_wick_body_min
        and (1.0 - close_loc) >= cfg.beam_close_location_min
    )
    long_beam = (
        long_setup and lower_wick >= body * cfg.beam_wick_body_min
        and close_loc >= cfg.beam_close_location_min
    )
    atr_pct = atr_now / max(price, 1e-9) * 100.0
    dist_from_fast_atr = abs(price - ema_fast) / max(atr_now, 1e-9)
    vol_ok = cfg.min_atr_pct <= atr_pct <= cfg.max_atr_pct
    late_chase_block = dist_from_fast_atr > cfg.max_chase_dist_atr
    failed_long = price < swing_low - atr_now * cfg.fail_pivot_break_atr
    failed_short = price > swing_high + atr_now * cfg.fail_pivot_break_atr

    pos = infer_position_state(state)
    in_long = pos["position_side"] == "long" and pos["position_qty"] > 0
    in_short = pos["position_side"] == "short" and pos["position_qty"] > 0
    can_add_more = pos["add_count"] < cfg.max_add_count
    indicators = {
        "price": round(price, 6),
        "atr": round(atr_now, 6),
        "atr_pct": round(atr_pct, 6),
        "ema_fast": round(ema_fast, 6),
        "ema_slow": round(ema_slow, 6),
        "confirmed_pivot_span": cfg.pivot_span,
        "pivot_high_index": high_idx,
        "pivot_low_index": low_idx,
        "swing_high_confirmed": round(swing_high, 6),
        "swing_low_confirmed": round(swing_low, 6),
        "confirmed_pivots_exclude_signal_bar": True,
        "touched_high": touched_high,
        "touched_low": touched_low,
        "upper_wick": round(upper_wick, 6),
        "lower_wick": round(lower_wick, 6),
        "bearish_reject": bearish_reject,
        "bullish_reject": bullish_reject,
        "short_setup": short_setup,
        "long_setup": long_setup,
        "short_beam": short_beam,
        "long_beam": long_beam,
        "late_chase_block": late_chase_block,
        "failed_long": failed_long,
        "failed_short": failed_short,
        "position_side": pos["position_side"],
        "position_qty": pos["position_qty"],
        "avg_entry": pos["avg_entry"],
        "add_count": pos["add_count"],
    }
    if not vol_ok:
        return build_result(side=None, action="hold", size=0.0, entry=price, sl=price, tp=price,
                            pyramiding=cfg.max_pyramiding, why="pivot_volatility_out_of_range",
                            skill="none", confidence=0.0, tags=["volatility_gate"], indicators=indicators)
    if late_chase_block and (long_setup or short_setup):
        return build_result(side=None, action="hold", size=0.0, entry=price, sl=price, tp=price,
                            pyramiding=cfg.max_pyramiding, why="pivot_late_chase_block",
                            skill="none", confidence=0.0, tags=["late_chase_block"], indicators=indicators)

    long_sl = min(swing_low - atr_now * cfg.stop_atr_mult, low)
    short_sl = max(swing_high + atr_now * cfg.stop_atr_mult, high)
    long_risk = max(price - long_sl, atr_now * 0.35)
    short_risk = max(short_sl - price, atr_now * 0.35)
    long_tp = price + long_risk * (cfg.beam_rr if long_beam else cfg.base_rr)
    short_tp = price - short_risk * (cfg.beam_rr if short_beam else cfg.base_rr)

    if in_long and failed_long:
        return build_result(side="long", action="reduce", size=cfg.reduce_size_long, entry=price,
                            sl=long_sl, tp=long_tp, pyramiding=cfg.max_pyramiding,
                            why="pivot_failed_long_reduce", skill="pivot_break_reduce", confidence=0.70,
                            tags=["pivot", "reduce", "long"], indicators=indicators)
    if in_short and failed_short:
        return build_result(side="short", action="reduce", size=cfg.reduce_size_short, entry=price,
                            sl=short_sl, tp=short_tp, pyramiding=cfg.max_pyramiding,
                            why="pivot_failed_short_reduce", skill="pivot_break_reduce", confidence=0.66,
                            tags=["pivot", "reduce", "short"], indicators=indicators)
    if in_long and can_add_more and long_setup:
        return build_result(side="long", action="add", size=cfg.add_size_long, entry=price,
                            sl=long_sl, tp=long_tp, pyramiding=cfg.max_pyramiding,
                            why="pivot_long_add", skill="pivot_add", confidence=0.60,
                            tags=["pivot", "add", "long"], indicators=indicators)
    if in_short and can_add_more and short_setup:
        return build_result(side="short", action="add", size=cfg.add_size_short, entry=price,
                            sl=short_sl, tp=short_tp, pyramiding=cfg.max_pyramiding,
                            why="pivot_short_add", skill="pivot_add", confidence=0.56,
                            tags=["pivot", "add", "short"], indicators=indicators)
    if long_setup and not in_long and not in_short:
        return build_result(side="long", action="enter",
                            size=cfg.long_base_size + (cfg.beam_bonus_long if long_beam else 0.0),
                            entry=price, sl=long_sl, tp=long_tp, pyramiding=cfg.max_pyramiding,
                            why="pivot_reversal_long", skill="long_beam" if long_beam else "pivot_reversal",
                            confidence=0.82 if long_beam else 0.68,
                            tags=["pivot", "confirmed", "long"], indicators=indicators)
    if short_setup and not in_long and not in_short:
        return build_result(side="short", action="enter",
                            size=cfg.short_base_size + (cfg.beam_bonus_short if short_beam else 0.0),
                            entry=price, sl=short_sl, tp=short_tp, pyramiding=cfg.max_pyramiding,
                            why="pivot_reversal_short", skill="short_beam" if short_beam else "pivot_reversal",
                            confidence=0.78 if short_beam else 0.64,
                            tags=["pivot", "confirmed", "short"], indicators=indicators)
    return build_result(side=None, action="hold", size=0.0, entry=price, sl=price, tp=price,
                        pyramiding=cfg.max_pyramiding, why="pivot_no_setup", skill="none",
                        confidence=0.0, tags=["hold"], indicators=indicators)


class PivotReversalLBotStrategy(LBotStrategyBase):
    strategy_name = "pivot_reversal"

    def decide(self, ctx: DecisionContext) -> StrategyDecision:
        return decision_from_context(ctx, strategy, PivotReversalConfig(), self.strategy_name)


__all__ = ["PivotReversalConfig", "PivotReversalLBotStrategy", "strategy"]
