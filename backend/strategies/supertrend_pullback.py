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
class SupertrendPullbackConfig:
    st_len: int = 10
    st_mult: float = 3.0
    ema_len: int = 50
    atr_len: int = 14
    swing_lookback: int = 10
    pullback_pct: float = 0.50
    min_bars: int = 100
    min_atr_pct: float = 0.20
    max_atr_pct: float = 5.20
    min_pullback_depth_atr: float = 0.35
    max_pullback_dist_from_ema_atr: float = 1.40
    reclaim_atr_min: float = 0.18
    stop_atr_buffer: float = 0.35
    trail_atr_mult: float = 0.90
    base_rr: float = 2.40
    beam_rr: float = 3.00
    long_base_size: float = 0.52
    short_base_size: float = 0.34
    beam_bonus_long: float = 0.14
    beam_bonus_short: float = 0.10
    scale_in_size_long: float = 0.22
    scale_in_size_short: float = 0.14
    dip_add_size_long: float = 0.16
    dip_add_size_short: float = 0.10
    scale_in_progress_min: float = 0.32
    dip_add_reclaim_atr: float = 0.20
    max_adverse_atr_for_dip: float = 1.00
    beam_body_ratio_min: float = 0.36
    beam_close_location_min: float = 0.58
    max_add_count: int = 2
    max_pyramiding: int = 4


def _supertrend(frame: pd.DataFrame, length: int, multiplier: float) -> pd.DataFrame:
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    close = frame["close"].astype(float)
    atr_series = atr(frame, length)
    hl2 = (high + low) / 2.0
    basic_upper = hl2 + multiplier * atr_series
    basic_lower = hl2 - multiplier * atr_series
    final_upper = basic_upper.copy()
    final_lower = basic_lower.copy()
    direction = pd.Series(index=frame.index, dtype="float64")
    line = pd.Series(index=frame.index, dtype="float64")

    for i in range(len(frame)):
        if i == 0 or pd.isna(atr_series.iloc[i]):
            direction.iloc[i] = 1.0
            line.iloc[i] = basic_lower.iloc[i]
            continue
        prev_close = close.iloc[i - 1]
        if basic_upper.iloc[i] < final_upper.iloc[i - 1] or prev_close > final_upper.iloc[i - 1]:
            final_upper.iloc[i] = basic_upper.iloc[i]
        else:
            final_upper.iloc[i] = final_upper.iloc[i - 1]
        if basic_lower.iloc[i] > final_lower.iloc[i - 1] or prev_close < final_lower.iloc[i - 1]:
            final_lower.iloc[i] = basic_lower.iloc[i]
        else:
            final_lower.iloc[i] = final_lower.iloc[i - 1]

        prior_line = line.iloc[i - 1]
        if prior_line == final_upper.iloc[i - 1]:
            if close.iloc[i] <= final_upper.iloc[i]:
                line.iloc[i] = final_upper.iloc[i]
                direction.iloc[i] = -1.0
            else:
                line.iloc[i] = final_lower.iloc[i]
                direction.iloc[i] = 1.0
        else:
            if close.iloc[i] >= final_lower.iloc[i]:
                line.iloc[i] = final_lower.iloc[i]
                direction.iloc[i] = 1.0
            else:
                line.iloc[i] = final_upper.iloc[i]
                direction.iloc[i] = -1.0
    return pd.DataFrame({"supertrend": line, "direction": direction, "atr": atr_series})


def strategy(
    df: pd.DataFrame,
    *,
    state: Optional[Dict[str, Any]] = None,
    risk_action: str = "hold",
    config: Optional[SupertrendPullbackConfig] = None,
) -> Dict[str, Any]:
    cfg = config or SupertrendPullbackConfig()
    frame = prepare_ohlcv(df)
    if frame is None:
        return invalid_result("st_pullback_invalid_input", cfg.max_pyramiding)
    if len(frame) < max(cfg.min_bars, cfg.swing_lookback + cfg.st_len + 10, cfg.ema_len + 10):
        return invalid_result("st_pullback_short", cfg.max_pyramiding, tags=["warmup"])
    if str(risk_action or "hold").lower() in {"block", "stop", "rollback"}:
        return invalid_result(f"risk_gate_{risk_action}", cfg.max_pyramiding, tags=["risk_gated"])

    st = _supertrend(frame, cfg.st_len, cfg.st_mult)
    frame["st"] = st["supertrend"]
    frame["dir"] = st["direction"]
    frame["atr"] = st["atr"]
    frame["trend_ma"] = ema(frame["close"], cfg.ema_len)
    last, prev = frame.iloc[-1], frame.iloc[-2]
    prior = frame.iloc[-(cfg.swing_lookback + 1):-1]

    price = to_float(last["close"])
    open_ = to_float(last["open"])
    high = to_float(last["high"])
    low = to_float(last["low"])
    prev_close = to_float(prev["close"])
    st_now = to_float(last["st"])
    dir_now = int(to_float(last["dir"]))
    atr_now = to_float(last["atr"])
    trend_ma = to_float(last["trend_ma"])
    trend_ma_prev = to_float(prev["trend_ma"])
    swing_high = to_float(prior["high"].max())
    swing_low = to_float(prior["low"].min())
    if min(price, st_now, atr_now, trend_ma, swing_high, swing_low) <= 0:
        return invalid_result("st_pullback_indicator_nan", cfg.max_pyramiding, tags=["indicator_nan"])

    trend_long = dir_now == 1 and price > trend_ma and trend_ma > trend_ma_prev
    trend_short = dir_now == -1 and price < trend_ma and trend_ma < trend_ma_prev
    long_reference = max(st_now, trend_ma)
    short_reference = min(st_now, trend_ma)
    pullback_level_long = swing_high - (swing_high - long_reference) * cfg.pullback_pct
    pullback_level_short = swing_low + (short_reference - swing_low) * cfg.pullback_pct
    depth_long_atr = (swing_high - low) / max(atr_now, 1e-9)
    depth_short_atr = (high - swing_low) / max(atr_now, 1e-9)
    dist_from_ma_atr = abs(price - trend_ma) / max(atr_now, 1e-9)
    long_pullback_zone = trend_long and low <= pullback_level_long and price >= long_reference
    short_pullback_zone = trend_short and high >= pullback_level_short and price <= short_reference
    long_quality = depth_long_atr >= cfg.min_pullback_depth_atr and dist_from_ma_atr <= cfg.max_pullback_dist_from_ema_atr
    short_quality = depth_short_atr >= cfg.min_pullback_depth_atr and dist_from_ma_atr <= cfg.max_pullback_dist_from_ema_atr
    long_reclaim = long_pullback_zone and long_quality and price > prev_close + atr_now * cfg.reclaim_atr_min
    short_reclaim = short_pullback_zone and short_quality and price < prev_close - atr_now * cfg.reclaim_atr_min

    # Optional causal geometry produced by the integrated OOS pipeline. It may
    # strengthen confidence but never bypasses the canonical Supertrend trigger.
    long_geometry = any(bool(last.get(name, False)) for name in (
        "sr_touch", "trendline_touch", "ma50_touch", "counter_trend_break_up"
    ))
    short_geometry = any(bool(last.get(name, False)) for name in (
        "sr_touch", "trendline_touch", "ma50_touch", "counter_trend_break_down"
    ))
    geometry_available = any(name in frame.columns for name in (
        "sr_touch", "trendline_touch", "ma50_touch",
        "counter_trend_break_up", "counter_trend_break_down"
    ))
    candle_body_ratio = body_ratio(open_, price, low, high)
    close_loc = close_location(price, low, high)
    long_beam = (
        long_reclaim and candle_body_ratio >= cfg.beam_body_ratio_min
        and close_loc >= cfg.beam_close_location_min
        and (long_geometry if geometry_available else True)
    )
    short_beam = (
        short_reclaim and candle_body_ratio >= cfg.beam_body_ratio_min
        and (1.0 - close_loc) >= cfg.beam_close_location_min
        and (short_geometry if geometry_available else True)
    )
    atr_pct = atr_now / max(price, 1e-9) * 100.0
    vol_ok = cfg.min_atr_pct <= atr_pct <= cfg.max_atr_pct

    pos = infer_position_state(state)
    in_long = pos["position_side"] == "long" and pos["position_qty"] > 0
    in_short = pos["position_side"] == "short" and pos["position_qty"] > 0
    can_add_more = pos["add_count"] < cfg.max_add_count
    indicators = {
        "price": round(price, 6),
        "st": round(st_now, 6),
        "dir": dir_now,
        "atr": round(atr_now, 6),
        "atr_pct": round(atr_pct, 6),
        "trend_ma": round(trend_ma, 6),
        "swing_high_prior": round(swing_high, 6),
        "swing_low_prior": round(swing_low, 6),
        "prior_swing_excludes_signal_bar": True,
        "pullback_level_long": round(pullback_level_long, 6),
        "pullback_level_short": round(pullback_level_short, 6),
        "depth_long_atr": round(depth_long_atr, 6),
        "depth_short_atr": round(depth_short_atr, 6),
        "dist_from_ma_atr": round(dist_from_ma_atr, 6),
        "trend_long": trend_long,
        "trend_short": trend_short,
        "long_pullback_zone": long_pullback_zone,
        "short_pullback_zone": short_pullback_zone,
        "long_quality": long_quality,
        "short_quality": short_quality,
        "long_reclaim": long_reclaim,
        "short_reclaim": short_reclaim,
        "geometry_available": geometry_available,
        "long_geometry": long_geometry,
        "short_geometry": short_geometry,
        "long_beam": long_beam,
        "short_beam": short_beam,
        "position_side": pos["position_side"],
        "position_qty": pos["position_qty"],
        "avg_entry": pos["avg_entry"],
        "add_count": pos["add_count"],
    }
    if not vol_ok:
        return build_result(side=None, action="hold", size=0.0, entry=price, sl=price, tp=price,
                            pyramiding=cfg.max_pyramiding, why="st_pullback_volatility_out_of_range",
                            skill="none", confidence=0.0, tags=["volatility_gate"], indicators=indicators)

    long_sl = min(st_now - atr_now * cfg.stop_atr_buffer, trend_ma - atr_now * cfg.trail_atr_mult, low)
    short_sl = max(st_now + atr_now * cfg.stop_atr_buffer, trend_ma + atr_now * cfg.trail_atr_mult, high)
    long_risk = max(price - long_sl, atr_now * 0.40)
    short_risk = max(short_sl - price, atr_now * 0.40)
    long_tp = price + long_risk * (cfg.beam_rr if long_beam else cfg.base_rr)
    short_tp = price - short_risk * (cfg.beam_rr if short_beam else cfg.base_rr)
    failed_long = in_long and (dir_now == -1 or price < st_now)
    failed_short = in_short and (dir_now == 1 or price > st_now)

    if failed_long:
        return build_result(side="long", action="reduce", size=0.25, entry=price, sl=long_sl, tp=long_tp,
                            pyramiding=cfg.max_pyramiding, why="st_pullback_failed_long_reduce",
                            skill="supertrend_flip_reduce", confidence=0.74,
                            tags=["supertrend", "reduce", "long"], indicators=indicators)
    if failed_short:
        return build_result(side="short", action="reduce", size=0.20, entry=price, sl=short_sl, tp=short_tp,
                            pyramiding=cfg.max_pyramiding, why="st_pullback_failed_short_reduce",
                            skill="supertrend_flip_reduce", confidence=0.70,
                            tags=["supertrend", "reduce", "short"], indicators=indicators)
    if in_long and can_add_more and pos["avg_entry"] > 0:
        progress = (price - pos["avg_entry"]) / max(long_tp - pos["avg_entry"], 1e-9)
        if progress >= cfg.scale_in_progress_min and trend_long:
            return build_result(side="long", action="add", size=cfg.scale_in_size_long, entry=price,
                                sl=long_sl, tp=long_tp, pyramiding=cfg.max_pyramiding,
                                why="st_pullback_long_scale_in", skill="scale_in", confidence=0.66,
                                tags=["supertrend", "add", "long"], indicators=indicators)
        if low <= trend_ma and price >= trend_ma + atr_now * cfg.dip_add_reclaim_atr and price >= pos["avg_entry"] - atr_now * cfg.max_adverse_atr_for_dip:
            return build_result(side="long", action="add", size=cfg.dip_add_size_long, entry=price,
                                sl=long_sl, tp=long_tp, pyramiding=cfg.max_pyramiding,
                                why="st_pullback_long_dip_add", skill="dip_add", confidence=0.62,
                                tags=["supertrend", "add", "long"], indicators=indicators)
    if in_short and can_add_more and pos["avg_entry"] > 0:
        progress = (pos["avg_entry"] - price) / max(pos["avg_entry"] - short_tp, 1e-9)
        if progress >= cfg.scale_in_progress_min and trend_short:
            return build_result(side="short", action="add", size=cfg.scale_in_size_short, entry=price,
                                sl=short_sl, tp=short_tp, pyramiding=cfg.max_pyramiding,
                                why="st_pullback_short_scale_in", skill="scale_in", confidence=0.60,
                                tags=["supertrend", "add", "short"], indicators=indicators)
        if high >= trend_ma and price <= trend_ma - atr_now * cfg.dip_add_reclaim_atr and price <= pos["avg_entry"] + atr_now * cfg.max_adverse_atr_for_dip:
            return build_result(side="short", action="add", size=cfg.dip_add_size_short, entry=price,
                                sl=short_sl, tp=short_tp, pyramiding=cfg.max_pyramiding,
                                why="st_pullback_short_dip_add", skill="dip_add", confidence=0.56,
                                tags=["supertrend", "add", "short"], indicators=indicators)
    if long_reclaim and not in_long and not in_short:
        return build_result(side="long", action="enter",
                            size=cfg.long_base_size + (cfg.beam_bonus_long if long_beam else 0.0),
                            entry=price, sl=long_sl, tp=long_tp, pyramiding=cfg.max_pyramiding,
                            why="st_pullback_long", skill="long_beam" if long_beam else "pullback_entry",
                            confidence=0.84 if long_beam else 0.70,
                            tags=["supertrend", "causal_pullback", "long"], indicators=indicators)
    if short_reclaim and not in_long and not in_short:
        return build_result(side="short", action="enter",
                            size=cfg.short_base_size + (cfg.beam_bonus_short if short_beam else 0.0),
                            entry=price, sl=short_sl, tp=short_tp, pyramiding=cfg.max_pyramiding,
                            why="st_pullback_short", skill="short_beam" if short_beam else "pullback_entry",
                            confidence=0.80 if short_beam else 0.66,
                            tags=["supertrend", "causal_pullback", "short"], indicators=indicators)
    return build_result(side=None, action="hold", size=0.0, entry=price, sl=price, tp=price,
                        pyramiding=cfg.max_pyramiding, why="st_pullback_no_setup", skill="none",
                        confidence=0.0, tags=["hold"], indicators=indicators)


class SupertrendPullbackLBotStrategy(LBotStrategyBase):
    strategy_name = "supertrend_pullback"

    def decide(self, ctx: DecisionContext) -> StrategyDecision:
        return decision_from_context(ctx, strategy, SupertrendPullbackConfig(), self.strategy_name)


__all__ = ["SupertrendPullbackConfig", "SupertrendPullbackLBotStrategy", "strategy", "_supertrend"]
