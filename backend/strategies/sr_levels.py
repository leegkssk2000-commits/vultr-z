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
class SrLevelsConfig:
    lookback: int = 50
    atr_len: int = 14
    vol_ma_len: int = 50
    ema_len: int = 34
    min_bars: int = 90
    vol_mult: float = 1.80
    beam_vol_mult: float = 2.30
    min_atr_pct: float = 0.22
    max_atr_pct: float = 6.20
    breakout_buffer_atr: float = 0.12
    retest_reclaim_atr: float = 0.18
    max_chase_dist_atr: float = 1.80
    fail_break_reject_atr: float = 0.20
    stop_atr_mult: float = 1.20
    trail_atr_mult: float = 0.90
    base_rr: float = 2.00
    beam_rr: float = 2.60
    long_base_size: float = 0.48
    short_base_size: float = 0.32
    beam_bonus_long: float = 0.16
    beam_bonus_short: float = 0.10
    scale_in_size_long: float = 0.22
    scale_in_size_short: float = 0.14
    dip_add_size_long: float = 0.14
    dip_add_size_short: float = 0.10
    reduce_size_long: float = 0.25
    reduce_size_short: float = 0.20
    scale_in_progress_min: float = 0.35
    max_add_count: int = 2
    max_pyramiding: int = 2
    beam_body_ratio_min: float = 0.42
    beam_close_location_min: float = 0.62


def strategy(
    df: pd.DataFrame,
    *,
    state: Optional[Dict[str, Any]] = None,
    risk_action: str = "hold",
    config: Optional[SrLevelsConfig] = None,
) -> Dict[str, Any]:
    cfg = config or SrLevelsConfig()
    frame = prepare_ohlcv(df, require_volume=True)
    if frame is None:
        return invalid_result("sr_levels_invalid_input", cfg.max_pyramiding)
    need = max(cfg.min_bars, cfg.lookback + 2, cfg.vol_ma_len + 2, cfg.ema_len + 5)
    if len(frame) < need:
        return invalid_result("sr_levels_not_enough_bars", cfg.max_pyramiding, tags=["warmup"])
    if str(risk_action or "hold").lower() in {"block", "stop", "rollback"}:
        return invalid_result(f"risk_gate_{risk_action}", cfg.max_pyramiding, tags=["risk_gated"])

    frame["atr"] = atr(frame, cfg.atr_len)
    frame["ema"] = ema(frame["close"], cfg.ema_len)
    # Shift prevents the current breakout volume from inflating its own baseline.
    frame["vol_ma_prior"] = frame["volume"].shift(1).rolling(
        cfg.vol_ma_len, min_periods=cfg.vol_ma_len
    ).mean()

    last, prev = frame.iloc[-1], frame.iloc[-2]
    prior = frame.iloc[-(cfg.lookback + 1):-1]
    swing_high = to_float(prior["high"].max())
    swing_low = to_float(prior["low"].min())
    price = to_float(last["close"])
    open_ = to_float(last["open"])
    high = to_float(last["high"])
    low = to_float(last["low"])
    volume = to_float(last["volume"])
    vol_ma = to_float(last["vol_ma_prior"])
    atr_now = to_float(last["atr"])
    ema_now = to_float(last["ema"])
    ema_prev = to_float(prev["ema"])
    prev_close = to_float(prev["close"])
    if min(price, vol_ma, atr_now, ema_now, swing_high, swing_low) <= 0:
        return invalid_result("sr_levels_indicator_nan", cfg.max_pyramiding, tags=["indicator_nan"])

    atr_pct = atr_now / max(price, 1e-9) * 100.0
    trend_long = price > ema_now and ema_now > ema_prev
    trend_short = price < ema_now and ema_now < ema_prev
    long_break = price > swing_high + atr_now * cfg.breakout_buffer_atr
    short_break = price < swing_low - atr_now * cfg.breakout_buffer_atr
    reclaim_long = prev_close <= swing_high and price > swing_high + atr_now * cfg.retest_reclaim_atr
    reclaim_short = prev_close >= swing_low and price < swing_low - atr_now * cfg.retest_reclaim_atr
    big_vol = volume >= vol_ma * cfg.vol_mult
    beam_vol = volume >= vol_ma * cfg.beam_vol_mult
    dist_from_ema_atr = abs(price - ema_now) / max(atr_now, 1e-9)
    candle_body_ratio = body_ratio(open_, price, low, high)
    close_loc = close_location(price, low, high)
    long_setup = long_break and big_vol and trend_long
    short_setup = short_break and big_vol and trend_short
    long_beam = (
        long_setup and beam_vol
        and candle_body_ratio >= cfg.beam_body_ratio_min
        and close_loc >= cfg.beam_close_location_min
    )
    short_beam = (
        short_setup and beam_vol
        and candle_body_ratio >= cfg.beam_body_ratio_min
        and (1.0 - close_loc) >= cfg.beam_close_location_min
    )
    vol_ok = cfg.min_atr_pct <= atr_pct <= cfg.max_atr_pct
    late_chase_block = dist_from_ema_atr > cfg.max_chase_dist_atr
    failed_long = prev_close > swing_high and price < swing_high - atr_now * cfg.fail_break_reject_atr
    failed_short = prev_close < swing_low and price > swing_low + atr_now * cfg.fail_break_reject_atr

    pos = infer_position_state(state)
    in_long = pos["position_side"] == "long" and pos["position_qty"] > 0
    in_short = pos["position_side"] == "short" and pos["position_qty"] > 0
    can_add_more = pos["add_count"] < cfg.max_add_count
    indicators = {
        "price": round(price, 6),
        "swing_high_prior": round(swing_high, 6),
        "swing_low_prior": round(swing_low, 6),
        "prior_sr_window_excludes_signal_bar": True,
        "volume": round(volume, 6),
        "vol_ma_prior": round(vol_ma, 6),
        "volume_baseline_excludes_signal_bar": True,
        "big_vol": big_vol,
        "beam_vol": beam_vol,
        "atr": round(atr_now, 6),
        "atr_pct": round(atr_pct, 6),
        "ema": round(ema_now, 6),
        "trend_long": trend_long,
        "trend_short": trend_short,
        "long_break": long_break,
        "short_break": short_break,
        "reclaim_long": reclaim_long,
        "reclaim_short": reclaim_short,
        "long_setup": long_setup,
        "short_setup": short_setup,
        "long_beam": long_beam,
        "short_beam": short_beam,
        "dist_from_ema_atr": round(dist_from_ema_atr, 6),
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
                            pyramiding=cfg.max_pyramiding, why="sr_levels_volatility_out_of_range",
                            skill="none", confidence=0.0, tags=["volatility_gate"], indicators=indicators)
    if late_chase_block and (long_setup or short_setup):
        return build_result(side=None, action="hold", size=0.0, entry=price, sl=price, tp=price,
                            pyramiding=cfg.max_pyramiding, why="sr_levels_late_chase_block",
                            skill="none", confidence=0.0, tags=["late_chase_block"], indicators=indicators)

    long_sl = min(swing_high - atr_now * cfg.stop_atr_mult, ema_now - atr_now * cfg.trail_atr_mult, low)
    short_sl = max(swing_low + atr_now * cfg.stop_atr_mult, ema_now + atr_now * cfg.trail_atr_mult, high)
    long_risk = max(price - long_sl, atr_now * 0.45)
    short_risk = max(short_sl - price, atr_now * 0.45)
    long_tp = price + long_risk * (cfg.beam_rr if long_beam else cfg.base_rr)
    short_tp = price - short_risk * (cfg.beam_rr if short_beam else cfg.base_rr)

    if in_long and failed_long:
        return build_result(side="long", action="reduce", size=cfg.reduce_size_long, entry=price,
                            sl=long_sl, tp=long_tp, pyramiding=cfg.max_pyramiding,
                            why="sr_levels_failed_long_break_reduce", skill="failed_break_reduce",
                            confidence=0.72, tags=["sr", "failed_break", "reduce", "long"], indicators=indicators)
    if in_short and failed_short:
        return build_result(side="short", action="reduce", size=cfg.reduce_size_short, entry=price,
                            sl=short_sl, tp=short_tp, pyramiding=cfg.max_pyramiding,
                            why="sr_levels_failed_short_break_reduce", skill="failed_break_reduce",
                            confidence=0.68, tags=["sr", "failed_break", "reduce", "short"], indicators=indicators)
    if in_long and can_add_more and trend_long and reclaim_long:
        size = cfg.scale_in_size_long if price > swing_high + atr_now else cfg.dip_add_size_long
        skill = "scale_in" if price > swing_high + atr_now else "dip_add"
        return build_result(side="long", action="add", size=size, entry=price, sl=long_sl, tp=long_tp,
                            pyramiding=cfg.max_pyramiding, why="sr_levels_long_add", skill=skill,
                            confidence=0.64, tags=["sr", "add", "long"], indicators=indicators)
    if in_short and can_add_more and trend_short and reclaim_short:
        size = cfg.scale_in_size_short if price < swing_low - atr_now else cfg.dip_add_size_short
        skill = "scale_in" if price < swing_low - atr_now else "dip_add"
        return build_result(side="short", action="add", size=size, entry=price, sl=short_sl, tp=short_tp,
                            pyramiding=cfg.max_pyramiding, why="sr_levels_short_add", skill=skill,
                            confidence=0.58, tags=["sr", "add", "short"], indicators=indicators)
    if long_setup and not in_long and not in_short:
        return build_result(side="long", action="enter",
                            size=cfg.long_base_size + (cfg.beam_bonus_long if long_beam else 0.0),
                            entry=price, sl=long_sl, tp=long_tp, pyramiding=cfg.max_pyramiding,
                            why="sr_break_long", skill="long_beam" if long_beam else "sr_breakout",
                            confidence=0.82 if long_beam else 0.70,
                            tags=["sr", "breakout", "long"], indicators=indicators)
    if short_setup and not in_long and not in_short:
        return build_result(side="short", action="enter",
                            size=cfg.short_base_size + (cfg.beam_bonus_short if short_beam else 0.0),
                            entry=price, sl=short_sl, tp=short_tp, pyramiding=cfg.max_pyramiding,
                            why="sr_break_short", skill="short_beam" if short_beam else "sr_breakout",
                            confidence=0.76 if short_beam else 0.64,
                            tags=["sr", "breakout", "short"], indicators=indicators)
    hold_reason = "sr_levels_no_setup"
    if long_break and not big_vol:
        hold_reason = "long_break_without_volume"
    elif short_break and not big_vol:
        hold_reason = "short_break_without_volume"
    return build_result(side=None, action="hold", size=0.0, entry=price, sl=price, tp=price,
                        pyramiding=cfg.max_pyramiding, why=hold_reason, skill="none",
                        confidence=0.0, tags=["hold"], indicators=indicators)


class SrLevelsLBotStrategy(LBotStrategyBase):
    strategy_name = "sr_levels"

    def decide(self, ctx: DecisionContext) -> StrategyDecision:
        return decision_from_context(ctx, strategy, SrLevelsConfig(), self.strategy_name)


__all__ = ["SrLevelsConfig", "SrLevelsLBotStrategy", "strategy"]
