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
    rsi,
    to_float,
)


@dataclass
class RangeFadeConfig:
    lookback: int = 60
    atr_len: int = 14
    rsi_len: int = 14
    ema_fast_len: int = 21
    ema_slow_len: int = 55
    min_bars: int = 100
    max_box_pct: float = 2.00
    max_atr_pct: float = 1.20
    min_atr_pct: float = 0.08
    upper_zone_pct: float = 0.80
    lower_zone_pct: float = 0.20
    mid_zone_pct: float = 0.50
    long_rsi_max: float = 40.0
    short_rsi_min: float = 60.0
    beam_long_rsi_max: float = 34.0
    beam_short_rsi_min: float = 66.0
    reclaim_atr_min: float = 0.10
    max_chase_dist_atr: float = 1.00
    fail_range_break_atr: float = 0.22
    ema_fast_flat_atr: float = 0.18
    ema_slow_flat_atr: float = 0.14
    stop_atr_mult: float = 0.80
    trail_atr_mult: float = 0.55
    base_rr: float = 1.50
    beam_rr: float = 2.00
    long_base_size: float = 0.44
    short_base_size: float = 0.34
    beam_bonus_long: float = 0.12
    beam_bonus_short: float = 0.10
    add_size_long: float = 0.14
    add_size_short: float = 0.10
    reduce_size_long: float = 0.22
    reduce_size_short: float = 0.20
    max_add_count: int = 3
    max_pyramiding: int = 4
    beam_body_ratio_min: float = 0.34
    beam_close_location_min: float = 0.58


def strategy(
    df: pd.DataFrame,
    *,
    state: Optional[Dict[str, Any]] = None,
    risk_action: str = "hold",
    config: Optional[RangeFadeConfig] = None,
) -> Dict[str, Any]:
    cfg = config or RangeFadeConfig()
    frame = prepare_ohlcv(df)
    if frame is None:
        return invalid_result("range_invalid_input", cfg.max_pyramiding)
    if len(frame) < max(cfg.min_bars, cfg.lookback + 2, cfg.ema_slow_len + 5):
        return invalid_result("range_short", cfg.max_pyramiding, tags=["warmup"])
    if str(risk_action or "hold").lower() in {"block", "stop", "rollback"}:
        return invalid_result(f"risk_gate_{risk_action}", cfg.max_pyramiding, tags=["risk_gated"])

    frame["atr"] = atr(frame, cfg.atr_len)
    frame["rsi"] = rsi(frame["close"], cfg.rsi_len)
    frame["ema_fast"] = ema(frame["close"], cfg.ema_fast_len)
    frame["ema_slow"] = ema(frame["close"], cfg.ema_slow_len)
    last, prev = frame.iloc[-1], frame.iloc[-2]
    prior = frame.iloc[-(cfg.lookback + 1):-1]

    high_max = to_float(prior["high"].max())
    low_min = to_float(prior["low"].min())
    box_height = high_max - low_min
    price = to_float(last["close"])
    open_ = to_float(last["open"])
    high = to_float(last["high"])
    low = to_float(last["low"])
    prev_close = to_float(prev["close"])
    atr_now = to_float(last["atr"])
    rsi_now = to_float(last["rsi"], 50.0)
    ema_fast = to_float(last["ema_fast"])
    ema_slow = to_float(last["ema_slow"])
    ema_fast_prev = to_float(prev["ema_fast"])
    ema_slow_prev = to_float(prev["ema_slow"])
    if min(price, atr_now, high_max, low_min, ema_fast, ema_slow) <= 0 or box_height <= 0:
        return invalid_result("range_indicator_nan", cfg.max_pyramiding, tags=["indicator_nan"])

    box_pct = box_height / max(price, 1e-9) * 100.0
    atr_pct = atr_now / max(price, 1e-9) * 100.0
    upper_zone = low_min + box_height * cfg.upper_zone_pct
    lower_zone = low_min + box_height * cfg.lower_zone_pct
    mid_zone = low_min + box_height * cfg.mid_zone_pct
    ema_flat = (
        abs(ema_fast - ema_fast_prev) <= atr_now * cfg.ema_fast_flat_atr
        and abs(ema_slow - ema_slow_prev) <= atr_now * cfg.ema_slow_flat_atr
    )
    sideways_ok = (
        box_pct <= cfg.max_box_pct
        and cfg.min_atr_pct <= atr_pct <= cfg.max_atr_pct
        and ema_flat
    )
    reclaim_up = price > prev_close + atr_now * cfg.reclaim_atr_min
    reclaim_down = price < prev_close - atr_now * cfg.reclaim_atr_min
    slight_up = ema_fast >= ema_slow
    slight_down = ema_fast <= ema_slow
    long_setup = sideways_ok and price <= lower_zone and rsi_now < cfg.long_rsi_max and reclaim_up and slight_up
    short_setup = sideways_ok and price >= upper_zone and rsi_now > cfg.short_rsi_min and reclaim_down and slight_down
    candle_body_ratio = body_ratio(open_, price, low, high)
    close_loc = close_location(price, low, high)
    long_beam = (
        long_setup and rsi_now <= cfg.beam_long_rsi_max
        and candle_body_ratio >= cfg.beam_body_ratio_min
        and close_loc >= cfg.beam_close_location_min
    )
    short_beam = (
        short_setup and rsi_now >= cfg.beam_short_rsi_min
        and candle_body_ratio >= cfg.beam_body_ratio_min
        and (1.0 - close_loc) >= cfg.beam_close_location_min
    )
    dist_from_mid_atr = abs(price - mid_zone) / max(atr_now, 1e-9)
    dist_from_fast_atr = abs(price - ema_fast) / max(atr_now, 1e-9)
    late_chase_block = dist_from_mid_atr > cfg.max_chase_dist_atr or dist_from_fast_atr > cfg.max_chase_dist_atr
    range_break_up = price > high_max + atr_now * cfg.fail_range_break_atr
    range_break_down = price < low_min - atr_now * cfg.fail_range_break_atr

    pos = infer_position_state(state)
    in_long = pos["position_side"] == "long" and pos["position_qty"] > 0
    in_short = pos["position_side"] == "short" and pos["position_qty"] > 0
    can_add_more = pos["add_count"] < cfg.max_add_count
    indicators = {
        "price": round(price, 6),
        "atr": round(atr_now, 6),
        "atr_pct": round(atr_pct, 6),
        "rsi": round(rsi_now, 6),
        "ema_fast": round(ema_fast, 6),
        "ema_slow": round(ema_slow, 6),
        "range_high_prior": round(high_max, 6),
        "range_low_prior": round(low_min, 6),
        "prior_range_excludes_signal_bar": True,
        "box_pct": round(box_pct, 6),
        "upper_zone": round(upper_zone, 6),
        "lower_zone": round(lower_zone, 6),
        "mid_zone": round(mid_zone, 6),
        "ema_flat": ema_flat,
        "sideways_ok": sideways_ok,
        "range_regime_required": True,
        "long_setup": long_setup,
        "short_setup": short_setup,
        "long_beam": long_beam,
        "short_beam": short_beam,
        "late_chase_block": late_chase_block,
        "range_break_up": range_break_up,
        "range_break_down": range_break_down,
        "position_side": pos["position_side"],
        "position_qty": pos["position_qty"],
        "avg_entry": pos["avg_entry"],
        "add_count": pos["add_count"],
    }
    if not sideways_ok:
        return build_result(side=None, action="hold", size=0.0, entry=price, sl=price, tp=price,
                            pyramiding=cfg.max_pyramiding, why="range_regime_required",
                            skill="none", confidence=0.0, tags=["range_gate"], indicators=indicators)
    if late_chase_block and (long_setup or short_setup):
        return build_result(side=None, action="hold", size=0.0, entry=price, sl=price, tp=price,
                            pyramiding=cfg.max_pyramiding, why="range_late_chase_block",
                            skill="none", confidence=0.0, tags=["late_chase_block"], indicators=indicators)

    long_sl = min(low_min - atr_now * cfg.stop_atr_mult, low)
    short_sl = max(high_max + atr_now * cfg.stop_atr_mult, high)
    long_risk = max(price - long_sl, atr_now * 0.35)
    short_risk = max(short_sl - price, atr_now * 0.35)
    long_tp = min(mid_zone, price + long_risk * (cfg.beam_rr if long_beam else cfg.base_rr))
    short_tp = max(mid_zone, price - short_risk * (cfg.beam_rr if short_beam else cfg.base_rr))

    if in_long and range_break_down:
        return build_result(side="long", action="reduce", size=cfg.reduce_size_long, entry=price,
                            sl=long_sl, tp=long_tp, pyramiding=cfg.max_pyramiding,
                            why="range_failed_long_reduce", skill="range_break_reduce", confidence=0.72,
                            tags=["range", "reduce", "long"], indicators=indicators)
    if in_short and range_break_up:
        return build_result(side="short", action="reduce", size=cfg.reduce_size_short, entry=price,
                            sl=short_sl, tp=short_tp, pyramiding=cfg.max_pyramiding,
                            why="range_failed_short_reduce", skill="range_break_reduce", confidence=0.68,
                            tags=["range", "reduce", "short"], indicators=indicators)
    if in_long and can_add_more and long_setup:
        return build_result(side="long", action="add", size=cfg.add_size_long, entry=price,
                            sl=long_sl, tp=long_tp, pyramiding=cfg.max_pyramiding,
                            why="range_long_add", skill="range_add", confidence=0.60,
                            tags=["range", "add", "long"], indicators=indicators)
    if in_short and can_add_more and short_setup:
        return build_result(side="short", action="add", size=cfg.add_size_short, entry=price,
                            sl=short_sl, tp=short_tp, pyramiding=cfg.max_pyramiding,
                            why="range_short_add", skill="range_add", confidence=0.56,
                            tags=["range", "add", "short"], indicators=indicators)
    if long_setup and not in_long and not in_short:
        return build_result(side="long", action="enter",
                            size=cfg.long_base_size + (cfg.beam_bonus_long if long_beam else 0.0),
                            entry=price, sl=long_sl, tp=long_tp, pyramiding=cfg.max_pyramiding,
                            why="range_fade_long", skill="long_beam" if long_beam else "range_fade",
                            confidence=0.80 if long_beam else 0.66,
                            tags=["range", "fade", "long"], indicators=indicators)
    if short_setup and not in_long and not in_short:
        return build_result(side="short", action="enter",
                            size=cfg.short_base_size + (cfg.beam_bonus_short if short_beam else 0.0),
                            entry=price, sl=short_sl, tp=short_tp, pyramiding=cfg.max_pyramiding,
                            why="range_fade_short", skill="short_beam" if short_beam else "range_fade",
                            confidence=0.76 if short_beam else 0.62,
                            tags=["range", "fade", "short"], indicators=indicators)
    return build_result(side=None, action="hold", size=0.0, entry=price, sl=price, tp=price,
                        pyramiding=cfg.max_pyramiding, why="range_no_setup", skill="none",
                        confidence=0.0, tags=["hold"], indicators=indicators)


class RangeFadeLBotStrategy(LBotStrategyBase):
    strategy_name = "range_fade"

    def decide(self, ctx: DecisionContext) -> StrategyDecision:
        return decision_from_context(ctx, strategy, RangeFadeConfig(), self.strategy_name)


__all__ = ["RangeFadeConfig", "RangeFadeLBotStrategy", "strategy"]
