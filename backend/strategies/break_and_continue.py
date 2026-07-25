from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

import pandas as pd

from backend.strategies.semantic_common import (
    DecisionContext,
    LBotStrategyBase,
    StrategyDecision,
    atr,
    body_ratio,
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
class BreakAndContinueConfig:
    breakout_bars: int = 4
    box_bars: int = 5
    atr_len: int = 14
    ema_fast_len: int = 21
    ema_slow_len: int = 55
    min_bars: int = 100
    min_atr_pct: float = 0.14
    max_atr_pct: float = 5.50
    breakout_strength_atr_mult: float = 0.75
    box_max_height_atr_mult: float = 2.20
    breakout_buffer_atr: float = 0.08
    reclaim_atr_min: float = 0.12
    max_chase_dist_atr: float = 1.40
    fail_box_reject_atr: float = 0.22
    beam_body_ratio_min: float = 0.40
    beam_close_location_min: float = 0.62
    beam_breakout_strength_atr_mult: float = 1.05
    stop_atr_mult: float = 0.52
    trail_atr_mult: float = 0.36
    base_rr: float = 2.10
    beam_rr: float = 2.70
    long_base_size: float = 0.52
    short_base_size: float = 0.36
    beam_bonus_long: float = 0.14
    beam_bonus_short: float = 0.10
    add_size_long: float = 0.14
    add_size_short: float = 0.10
    reduce_size_long: float = 0.24
    reduce_size_short: float = 0.20
    max_add_count: int = 1
    max_pyramiding: int = 3


def strategy(
    df: pd.DataFrame,
    *,
    state: Optional[Dict[str, Any]] = None,
    risk_action: str = "hold",
    config: Optional[BreakAndContinueConfig] = None,
) -> Dict[str, Any]:
    cfg = config or BreakAndContinueConfig()
    frame = prepare_ohlcv(df)
    if frame is None:
        return invalid_result("bnc_invalid_input", cfg.max_pyramiding)
    need = max(
        cfg.min_bars,
        cfg.ema_slow_len + 5,
        cfg.breakout_bars + cfg.box_bars + 2,
    )
    if len(frame) < need:
        return invalid_result("bnc_short", cfg.max_pyramiding, tags=["warmup"])
    if str(risk_action or "hold").lower() in {"block", "stop", "rollback"}:
        return invalid_result(f"risk_gate_{risk_action}", cfg.max_pyramiding, tags=["risk_gated"])

    frame["atr"] = atr(frame, cfg.atr_len)
    frame["ema_fast"] = ema(frame["close"], cfg.ema_fast_len)
    frame["ema_slow"] = ema(frame["close"], cfg.ema_slow_len)

    last = frame.iloc[-1]
    prev = frame.iloc[-2]
    history = frame.iloc[:-1]
    box = history.iloc[-cfg.box_bars:]
    breakout = history.iloc[-(cfg.breakout_bars + cfg.box_bars):-cfg.box_bars]

    price = to_float(last["close"])
    open_ = to_float(last["open"])
    high = to_float(last["high"])
    low = to_float(last["low"])
    prev_close = to_float(prev["close"])
    atr_now = to_float(last["atr"])
    ema_fast_now = to_float(last["ema_fast"])
    ema_slow_now = to_float(last["ema_slow"])
    ema_fast_prev = to_float(prev["ema_fast"])
    ema_slow_prev = to_float(prev["ema_slow"])
    if min(price, atr_now, ema_fast_now, ema_slow_now) <= 0:
        return invalid_result("bnc_indicator_nan", cfg.max_pyramiding, tags=["indicator_nan"])

    breakout_move = to_float(breakout["close"].iloc[-1]) - to_float(breakout["close"].iloc[0])
    breakout_strength_atr = breakout_move / max(atr_now, 1e-9)
    up_break = breakout_strength_atr > cfg.breakout_bars * cfg.breakout_strength_atr_mult
    down_break = breakout_strength_atr < -cfg.breakout_bars * cfg.breakout_strength_atr_mult

    box_high = to_float(box["high"].max())
    box_low = to_float(box["low"].min())
    box_mid = (box_high + box_low) / 2.0
    box_height_atr = (box_high - box_low) / max(atr_now, 1e-9)
    tight_box = box_height_atr <= cfg.box_max_height_atr_mult

    trend_long = (
        price > ema_fast_now > ema_slow_now
        and ema_fast_now >= ema_fast_prev
        and ema_slow_now >= ema_slow_prev
    )
    trend_short = (
        price < ema_fast_now < ema_slow_now
        and ema_fast_now <= ema_fast_prev
        and ema_slow_now <= ema_slow_prev
    )
    long_breakout_now = price > box_high + atr_now * cfg.breakout_buffer_atr
    short_breakout_now = price < box_low - atr_now * cfg.breakout_buffer_atr
    long_reclaim = price > prev_close + atr_now * cfg.reclaim_atr_min
    short_reclaim = price < prev_close - atr_now * cfg.reclaim_atr_min

    long_setup = up_break and tight_box and long_breakout_now and long_reclaim and trend_long
    short_setup = down_break and tight_box and short_breakout_now and short_reclaim and trend_short
    candle_body_ratio = body_ratio(open_, price, low, high)
    close_loc = close_location(price, low, high)
    long_beam = (
        long_setup
        and breakout_strength_atr >= cfg.breakout_bars * cfg.beam_breakout_strength_atr_mult
        and candle_body_ratio >= cfg.beam_body_ratio_min
        and close_loc >= cfg.beam_close_location_min
    )
    short_beam = (
        short_setup
        and breakout_strength_atr <= -cfg.breakout_bars * cfg.beam_breakout_strength_atr_mult
        and candle_body_ratio >= cfg.beam_body_ratio_min
        and (1.0 - close_loc) >= cfg.beam_close_location_min
    )

    atr_pct = atr_now / max(price, 1e-9) * 100.0
    dist_from_fast_atr = abs(price - ema_fast_now) / max(atr_now, 1e-9)
    vol_ok = cfg.min_atr_pct <= atr_pct <= cfg.max_atr_pct
    late_chase_block = dist_from_fast_atr > cfg.max_chase_dist_atr
    failed_long = price < box_low - atr_now * cfg.fail_box_reject_atr
    failed_short = price > box_high + atr_now * cfg.fail_box_reject_atr

    pos = infer_position_state(state)
    in_long = pos["position_side"] == "long" and pos["position_qty"] > 0
    in_short = pos["position_side"] == "short" and pos["position_qty"] > 0
    can_add_more = pos["add_count"] < cfg.max_add_count
    indicators = {
        "price": round(price, 6),
        "atr": round(atr_now, 6),
        "atr_pct": round(atr_pct, 6),
        "ema_fast": round(ema_fast_now, 6),
        "ema_slow": round(ema_slow_now, 6),
        "breakout_strength_atr": round(breakout_strength_atr, 6),
        "box_high_prior": round(box_high, 6),
        "box_low_prior": round(box_low, 6),
        "box_mid_prior": round(box_mid, 6),
        "box_height_atr": round(box_height_atr, 6),
        "box_excludes_signal_bar": True,
        "up_break": up_break,
        "down_break": down_break,
        "tight_box": tight_box,
        "trend_long": trend_long,
        "trend_short": trend_short,
        "long_breakout_now": long_breakout_now,
        "short_breakout_now": short_breakout_now,
        "long_setup": long_setup,
        "short_setup": short_setup,
        "long_beam": long_beam,
        "short_beam": short_beam,
        "late_chase_block": late_chase_block,
        "failed_long": failed_long,
        "failed_short": failed_short,
        "position_side": pos["position_side"],
        "position_qty": pos["position_qty"],
        "add_count": pos["add_count"],
    }
    if not vol_ok:
        return build_result(side=None, action="hold", size=0.0, entry=price, sl=price, tp=price,
                            pyramiding=cfg.max_pyramiding, why="bnc_volatility_out_of_range",
                            skill="none", confidence=0.0, tags=["volatility_gate"], indicators=indicators)
    if late_chase_block and (long_setup or short_setup):
        return build_result(side=None, action="hold", size=0.0, entry=price, sl=price, tp=price,
                            pyramiding=cfg.max_pyramiding, why="bnc_late_chase_block",
                            skill="none", confidence=0.0, tags=["late_chase_block"], indicators=indicators)

    long_sl = min(box_low - atr_now * cfg.fail_box_reject_atr, price - atr_now * cfg.stop_atr_mult)
    short_sl = max(box_high + atr_now * cfg.fail_box_reject_atr, price + atr_now * cfg.stop_atr_mult)
    long_risk = max(price - long_sl, atr_now * 0.35)
    short_risk = max(short_sl - price, atr_now * 0.35)
    long_tp = price + long_risk * (cfg.beam_rr if long_beam else cfg.base_rr)
    short_tp = price - short_risk * (cfg.beam_rr if short_beam else cfg.base_rr)

    if in_long and failed_long:
        return build_result(side="long", action="reduce", size=cfg.reduce_size_long, entry=price,
                            sl=long_sl, tp=long_tp, pyramiding=cfg.max_pyramiding,
                            why="bnc_failed_long_reduce", skill="failed_break_reduce", confidence=0.70,
                            tags=["break_continue", "reduce", "long"], indicators=indicators)
    if in_short and failed_short:
        return build_result(side="short", action="reduce", size=cfg.reduce_size_short, entry=price,
                            sl=short_sl, tp=short_tp, pyramiding=cfg.max_pyramiding,
                            why="bnc_failed_short_reduce", skill="failed_break_reduce", confidence=0.66,
                            tags=["break_continue", "reduce", "short"], indicators=indicators)
    if in_long and can_add_more and trend_long and low <= box_high and price > box_high:
        return build_result(side="long", action="add", size=cfg.add_size_long, entry=price,
                            sl=long_sl, tp=long_tp, pyramiding=cfg.max_pyramiding,
                            why="bnc_long_retest_add", skill="retest_add", confidence=0.62,
                            tags=["break_continue", "add", "long"], indicators=indicators)
    if in_short and can_add_more and trend_short and high >= box_low and price < box_low:
        return build_result(side="short", action="add", size=cfg.add_size_short, entry=price,
                            sl=short_sl, tp=short_tp, pyramiding=cfg.max_pyramiding,
                            why="bnc_short_retest_add", skill="retest_add", confidence=0.58,
                            tags=["break_continue", "add", "short"], indicators=indicators)
    if long_setup and not in_long and not in_short:
        return build_result(side="long", action="enter",
                            size=cfg.long_base_size + (cfg.beam_bonus_long if long_beam else 0.0),
                            entry=price, sl=long_sl, tp=long_tp, pyramiding=cfg.max_pyramiding,
                            why="bnc_long", skill="long_beam" if long_beam else "break_continue",
                            confidence=0.84 if long_beam else 0.70,
                            tags=["break_continue", "long"], indicators=indicators)
    if short_setup and not in_long and not in_short:
        return build_result(side="short", action="enter",
                            size=cfg.short_base_size + (cfg.beam_bonus_short if short_beam else 0.0),
                            entry=price, sl=short_sl, tp=short_tp, pyramiding=cfg.max_pyramiding,
                            why="bnc_short", skill="short_beam" if short_beam else "break_continue",
                            confidence=0.80 if short_beam else 0.66,
                            tags=["break_continue", "short"], indicators=indicators)
    return build_result(side=None, action="hold", size=0.0, entry=price, sl=price, tp=price,
                        pyramiding=cfg.max_pyramiding, why="bnc_no_setup", skill="none",
                        confidence=0.0, tags=["hold"], indicators=indicators)


class BreakAndContinueLBotStrategy(LBotStrategyBase):
    strategy_name = "break_and_continue"

    def decide(self, ctx: DecisionContext) -> StrategyDecision:
        return decision_from_context(ctx, strategy, BreakAndContinueConfig(), self.strategy_name)


__all__ = ["BreakAndContinueConfig", "BreakAndContinueLBotStrategy", "strategy"]
