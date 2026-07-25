from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

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
class AnchorVwapTrendConfig:
    lookback: int = 120
    pivot_span: int = 3
    ema_fast_len: int = 21
    ema_slow_len: int = 55
    atr_len: int = 14
    min_bars: int = 150
    min_atr_pct: float = 0.12
    max_atr_pct: float = 5.40
    beam_body_atr: float = 0.72
    beam_body_ratio_min: float = 0.36
    beam_close_location_min: float = 0.60
    reclaim_atr_min: float = 0.10
    max_chase_dist_atr: float = 1.55
    add_pullback_atr: float = 0.42
    fail_anchor_break_atr: float = 0.26
    stop_atr_mult: float = 0.92
    trail_atr_mult: float = 0.54
    base_rr: float = 2.20
    beam_rr: float = 2.80
    long_base_size: float = 0.54
    short_base_size: float = 0.38
    beam_bonus_long: float = 0.14
    beam_bonus_short: float = 0.10
    add_size_long: float = 0.14
    add_size_short: float = 0.10
    reduce_size_long: float = 0.24
    reduce_size_short: float = 0.20
    max_add_count: int = 1
    max_pyramiding: int = 3


def _confirmed_anchor_positions(frame: pd.DataFrame, cfg: AnchorVwapTrendConfig) -> Tuple[Optional[int], Optional[int]]:
    span = max(int(cfg.pivot_span), 1)
    start = max(span, len(frame) - cfg.lookback)
    end = len(frame) - span - 1
    low_pos: Optional[int] = None
    high_pos: Optional[int] = None
    for i in range(start, end + 1):
        highs = frame["high"].iloc[i - span:i + span + 1]
        lows = frame["low"].iloc[i - span:i + span + 1]
        high_value = to_float(frame["high"].iloc[i])
        low_value = to_float(frame["low"].iloc[i])
        if high_value == to_float(highs.max()) and int((highs == high_value).sum()) == 1:
            high_pos = i
        if low_value == to_float(lows.min()) and int((lows == low_value).sum()) == 1:
            low_pos = i
    return low_pos, high_pos


def _anchored_vwap(frame: pd.DataFrame, start_pos: int) -> Optional[float]:
    part = frame.iloc[start_pos:].copy()
    volume = part["volume"].astype(float)
    total_volume = float(volume.sum())
    if total_volume <= 0:
        return None
    typical = (part["high"] + part["low"] + part["close"]) / 3.0
    return float((typical * volume).sum() / total_volume)


def strategy(
    df: pd.DataFrame,
    *,
    state: Optional[Dict[str, Any]] = None,
    risk_action: str = "hold",
    config: Optional[AnchorVwapTrendConfig] = None,
) -> Dict[str, Any]:
    cfg = config or AnchorVwapTrendConfig()
    frame = prepare_ohlcv(df, require_volume=True)
    if frame is None:
        return invalid_result("avwap_invalid_input", cfg.max_pyramiding)
    if len(frame) < max(cfg.min_bars, cfg.lookback + 10, cfg.ema_slow_len + 5):
        return invalid_result("avwap_short", cfg.max_pyramiding, tags=["warmup"])
    if str(risk_action or "hold").lower() in {"block", "stop", "rollback"}:
        return invalid_result(f"risk_gate_{risk_action}", cfg.max_pyramiding, tags=["risk_gated"])

    frame["atr"] = atr(frame, cfg.atr_len)
    frame["ema_fast"] = ema(frame["close"], cfg.ema_fast_len)
    frame["ema_slow"] = ema(frame["close"], cfg.ema_slow_len)
    low_anchor_pos, high_anchor_pos = _confirmed_anchor_positions(frame, cfg)
    if low_anchor_pos is None or high_anchor_pos is None:
        return invalid_result("avwap_confirmed_anchor_missing", cfg.max_pyramiding, tags=["anchor_gate"])
    avwap_long = _anchored_vwap(frame, low_anchor_pos)
    avwap_short = _anchored_vwap(frame, high_anchor_pos)
    if avwap_long is None or avwap_short is None:
        return invalid_result("avwap_zero_volume_anchor", cfg.max_pyramiding, tags=["volume_gate"])

    last, prev = frame.iloc[-1], frame.iloc[-2]
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
    if min(price, atr_now, ema_fast_now, ema_slow_now, avwap_long, avwap_short) <= 0:
        return invalid_result("avwap_indicator_nan", cfg.max_pyramiding, tags=["indicator_nan"])

    atr_pct = atr_now / max(price, 1e-9) * 100.0
    trend_long = price > ema_fast_now > ema_slow_now and ema_fast_now >= ema_fast_prev and ema_slow_now >= ema_slow_prev
    trend_short = price < ema_fast_now < ema_slow_now and ema_fast_now <= ema_fast_prev and ema_slow_now <= ema_slow_prev
    long_reclaim = price > prev_close + atr_now * cfg.reclaim_atr_min
    short_reclaim = price < prev_close - atr_now * cfg.reclaim_atr_min
    dist_long_atr = abs(price - avwap_long) / max(atr_now, 1e-9)
    dist_short_atr = abs(price - avwap_short) / max(atr_now, 1e-9)
    long_setup = trend_long and price > avwap_long and long_reclaim
    short_setup = trend_short and price < avwap_short and short_reclaim
    candle_body_atr = abs(price - open_) / max(atr_now, 1e-9)
    candle_body_ratio = body_ratio(open_, price, low, high)
    close_loc = close_location(price, low, high)
    long_beam = (
        long_setup and candle_body_atr >= cfg.beam_body_atr
        and candle_body_ratio >= cfg.beam_body_ratio_min
        and close_loc >= cfg.beam_close_location_min
    )
    short_beam = (
        short_setup and candle_body_atr >= cfg.beam_body_atr
        and candle_body_ratio >= cfg.beam_body_ratio_min
        and (1.0 - close_loc) >= cfg.beam_close_location_min
    )
    vol_ok = cfg.min_atr_pct <= atr_pct <= cfg.max_atr_pct
    late_chase_long = long_setup and dist_long_atr > cfg.max_chase_dist_atr
    late_chase_short = short_setup and dist_short_atr > cfg.max_chase_dist_atr
    failed_long = price < avwap_long - atr_now * cfg.fail_anchor_break_atr
    failed_short = price > avwap_short + atr_now * cfg.fail_anchor_break_atr

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
        "avwap_long": round(avwap_long, 6),
        "avwap_short": round(avwap_short, 6),
        "long_anchor_position": low_anchor_pos,
        "short_anchor_position": high_anchor_pos,
        "confirmed_anchor_span": cfg.pivot_span,
        "anchors_are_confirmed_and_index_safe": True,
        "trend_long": trend_long,
        "trend_short": trend_short,
        "long_setup": long_setup,
        "short_setup": short_setup,
        "long_beam": long_beam,
        "short_beam": short_beam,
        "dist_long_avwap_atr": round(dist_long_atr, 6),
        "dist_short_avwap_atr": round(dist_short_atr, 6),
        "late_chase_long": late_chase_long,
        "late_chase_short": late_chase_short,
        "failed_long": failed_long,
        "failed_short": failed_short,
        "position_side": pos["position_side"],
        "position_qty": pos["position_qty"],
        "avg_entry": pos["avg_entry"],
        "add_count": pos["add_count"],
    }
    if not vol_ok:
        return build_result(side=None, action="hold", size=0.0, entry=price, sl=price, tp=price,
                            pyramiding=cfg.max_pyramiding, why="avwap_volatility_out_of_range",
                            skill="none", confidence=0.0, tags=["volatility_gate"], indicators=indicators)
    if late_chase_long or late_chase_short:
        return build_result(side=None, action="hold", size=0.0, entry=price, sl=price, tp=price,
                            pyramiding=cfg.max_pyramiding, why="avwap_late_chase_block",
                            skill="none", confidence=0.0, tags=["late_chase_block"], indicators=indicators)

    long_sl = min(avwap_long - atr_now * cfg.stop_atr_mult, ema_slow_now - atr_now * cfg.trail_atr_mult, low)
    short_sl = max(avwap_short + atr_now * cfg.stop_atr_mult, ema_slow_now + atr_now * cfg.trail_atr_mult, high)
    long_risk = max(price - long_sl, atr_now * 0.40)
    short_risk = max(short_sl - price, atr_now * 0.40)
    long_tp = price + long_risk * (cfg.beam_rr if long_beam else cfg.base_rr)
    short_tp = price - short_risk * (cfg.beam_rr if short_beam else cfg.base_rr)

    if in_long and failed_long:
        return build_result(side="long", action="reduce", size=cfg.reduce_size_long, entry=price,
                            sl=long_sl, tp=long_tp, pyramiding=cfg.max_pyramiding,
                            why="avwap_failed_long_reduce", skill="anchor_break_reduce", confidence=0.72,
                            tags=["avwap", "reduce", "long"], indicators=indicators)
    if in_short and failed_short:
        return build_result(side="short", action="reduce", size=cfg.reduce_size_short, entry=price,
                            sl=short_sl, tp=short_tp, pyramiding=cfg.max_pyramiding,
                            why="avwap_failed_short_reduce", skill="anchor_break_reduce", confidence=0.68,
                            tags=["avwap", "reduce", "short"], indicators=indicators)
    if in_long and can_add_more and trend_long and price >= avwap_long and dist_long_atr <= cfg.add_pullback_atr:
        return build_result(side="long", action="add", size=cfg.add_size_long, entry=price,
                            sl=long_sl, tp=long_tp, pyramiding=cfg.max_pyramiding,
                            why="avwap_long_pullback_add", skill="anchor_add", confidence=0.62,
                            tags=["avwap", "add", "long"], indicators=indicators)
    if in_short and can_add_more and trend_short and price <= avwap_short and dist_short_atr <= cfg.add_pullback_atr:
        return build_result(side="short", action="add", size=cfg.add_size_short, entry=price,
                            sl=short_sl, tp=short_tp, pyramiding=cfg.max_pyramiding,
                            why="avwap_short_pullback_add", skill="anchor_add", confidence=0.58,
                            tags=["avwap", "add", "short"], indicators=indicators)
    if long_setup and not in_long and not in_short:
        return build_result(side="long", action="enter",
                            size=cfg.long_base_size + (cfg.beam_bonus_long if long_beam else 0.0),
                            entry=price, sl=long_sl, tp=long_tp, pyramiding=cfg.max_pyramiding,
                            why="avwap_trend_long", skill="long_beam" if long_beam else "anchor_vwap_trend",
                            confidence=0.84 if long_beam else 0.70,
                            tags=["avwap", "confirmed_anchor", "long"], indicators=indicators)
    if short_setup and not in_long and not in_short:
        return build_result(side="short", action="enter",
                            size=cfg.short_base_size + (cfg.beam_bonus_short if short_beam else 0.0),
                            entry=price, sl=short_sl, tp=short_tp, pyramiding=cfg.max_pyramiding,
                            why="avwap_trend_short", skill="short_beam" if short_beam else "anchor_vwap_trend",
                            confidence=0.80 if short_beam else 0.66,
                            tags=["avwap", "confirmed_anchor", "short"], indicators=indicators)
    return build_result(side=None, action="hold", size=0.0, entry=price, sl=price, tp=price,
                        pyramiding=cfg.max_pyramiding, why="avwap_no_setup", skill="none",
                        confidence=0.0, tags=["hold"], indicators=indicators)


class AnchorVwapTrendLBotStrategy(LBotStrategyBase):
    strategy_name = "anchor_vwap_trend"

    def decide(self, ctx: DecisionContext) -> StrategyDecision:
        return decision_from_context(ctx, strategy, AnchorVwapTrendConfig(), self.strategy_name)


__all__ = ["AnchorVwapTrendConfig", "AnchorVwapTrendLBotStrategy", "strategy"]
