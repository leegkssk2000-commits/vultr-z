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
class FvgRevertConfig:
    lookback: int = 30
    atr_len: int = 14
    ema_fast_len: int = 21
    ema_slow_len: int = 55
    min_bars: int = 100
    min_atr_pct: float = 0.14
    max_atr_pct: float = 5.40
    min_gap_atr: float = 0.32
    min_gap_pct: float = 0.0012
    fill_enter_pct: float = 0.18
    fill_mid_pct: float = 0.50
    fill_deep_pct: float = 0.78
    reclaim_atr_min: float = 0.10
    max_chase_dist_atr: float = 1.30
    fail_gap_break_atr: float = 0.22
    beam_fill_pct: float = 0.60
    beam_body_ratio_min: float = 0.36
    beam_close_location_min: float = 0.60
    stop_atr_mult: float = 0.44
    trail_atr_mult: float = 0.30
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


def _latest_three_candle_gap(frame: pd.DataFrame, cfg: FvgRevertConfig, atr_now: float, price: float) -> Optional[Dict[str, Any]]:
    start = max(2, len(frame) - cfg.lookback - 1)
    # The signal bar is reserved for mitigation/reversion. A valid FVG is formed
    # by candle i-2 and candle i, with candle i-1 as the displacement candle.
    for i in range(len(frame) - 2, start - 1, -1):
        left_high = to_float(frame["high"].iloc[i - 2])
        left_low = to_float(frame["low"].iloc[i - 2])
        right_high = to_float(frame["high"].iloc[i])
        right_low = to_float(frame["low"].iloc[i])
        middle_open = to_float(frame["open"].iloc[i - 1])
        middle_close = to_float(frame["close"].iloc[i - 1])
        middle_body_atr = abs(middle_close - middle_open) / max(atr_now, 1e-9)

        if right_low > left_high:
            gap_low, gap_high, direction = left_high, right_low, "up"
        elif right_high < left_low:
            gap_low, gap_high, direction = right_high, left_low, "down"
        else:
            continue
        gap_size = gap_high - gap_low
        if gap_size < atr_now * cfg.min_gap_atr:
            continue
        if gap_size / max(price, 1e-9) < cfg.min_gap_pct:
            continue
        return {
            "gap_index": i,
            "gap_direction": direction,
            "gap_low": gap_low,
            "gap_high": gap_high,
            "gap_size": gap_size,
            "middle_body_atr": middle_body_atr,
        }
    return None


def strategy(
    df: pd.DataFrame,
    *,
    state: Optional[Dict[str, Any]] = None,
    risk_action: str = "hold",
    config: Optional[FvgRevertConfig] = None,
) -> Dict[str, Any]:
    cfg = config or FvgRevertConfig()
    frame = prepare_ohlcv(df)
    if frame is None:
        return invalid_result("fvg_invalid_input", cfg.max_pyramiding)
    if len(frame) < max(cfg.min_bars, cfg.lookback + 5, cfg.ema_slow_len + 5):
        return invalid_result("fvg_short", cfg.max_pyramiding, tags=["warmup"])
    if str(risk_action or "hold").lower() in {"block", "stop", "rollback"}:
        return invalid_result(f"risk_gate_{risk_action}", cfg.max_pyramiding, tags=["risk_gated"])

    frame["atr"] = atr(frame, cfg.atr_len)
    frame["ema_fast"] = ema(frame["close"], cfg.ema_fast_len)
    frame["ema_slow"] = ema(frame["close"], cfg.ema_slow_len)
    last, prev = frame.iloc[-1], frame.iloc[-2]
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
    if min(price, atr_now, ema_fast, ema_slow) <= 0:
        return invalid_result("fvg_indicator_nan", cfg.max_pyramiding, tags=["indicator_nan"])

    gap = _latest_three_candle_gap(frame, cfg, atr_now, price)
    if gap is None:
        return build_result(side=None, action="hold", size=0.0, entry=price, sl=price, tp=price,
                            pyramiding=cfg.max_pyramiding, why="fvg_no_three_candle_gap",
                            skill="none", confidence=0.0, tags=["hold"],
                            indicators={"three_candle_fvg": False})

    gap_low = to_float(gap["gap_low"])
    gap_high = to_float(gap["gap_high"])
    gap_range = max(gap_high - gap_low, 1e-9)
    direction = str(gap["gap_direction"])
    in_gap = gap_low < price < gap_high
    if direction == "up":
        fill_pct = (gap_high - price) / gap_range
    else:
        fill_pct = (price - gap_low) / gap_range
    fill_pct = max(0.0, min(fill_pct, 1.5))

    trend_long = price > ema_fast > ema_slow and ema_fast >= ema_fast_prev and ema_slow >= ema_slow_prev
    trend_short = price < ema_fast < ema_slow and ema_fast <= ema_fast_prev and ema_slow <= ema_slow_prev
    long_reclaim = price > prev_close + atr_now * cfg.reclaim_atr_min
    short_reclaim = price < prev_close - atr_now * cfg.reclaim_atr_min
    start_fill = fill_pct >= cfg.fill_enter_pct
    deep_fill = fill_pct >= cfg.fill_deep_pct
    mid_fill = fill_pct >= cfg.fill_mid_pct

    # fvg_revert deliberately fades the imbalance toward full fill.
    short_setup = direction == "up" and in_gap and start_fill and short_reclaim and not trend_long
    long_setup = direction == "down" and in_gap and start_fill and long_reclaim and not trend_short
    candle_body_ratio = body_ratio(open_, price, low, high)
    close_loc = close_location(price, low, high)
    short_beam = (
        short_setup and fill_pct >= cfg.beam_fill_pct
        and candle_body_ratio >= cfg.beam_body_ratio_min
        and (1.0 - close_loc) >= cfg.beam_close_location_min
    )
    long_beam = (
        long_setup and fill_pct >= cfg.beam_fill_pct
        and candle_body_ratio >= cfg.beam_body_ratio_min
        and close_loc >= cfg.beam_close_location_min
    )

    atr_pct = atr_now / max(price, 1e-9) * 100.0
    dist_from_fast_atr = abs(price - ema_fast) / max(atr_now, 1e-9)
    vol_ok = cfg.min_atr_pct <= atr_pct <= cfg.max_atr_pct
    late_chase_block = dist_from_fast_atr > cfg.max_chase_dist_atr
    failed_long = direction == "down" and price < gap_low - atr_now * cfg.fail_gap_break_atr
    failed_short = direction == "up" and price > gap_high + atr_now * cfg.fail_gap_break_atr
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
        "three_candle_fvg": True,
        "gap_direction": direction,
        "gap_index": int(gap["gap_index"]),
        "gap_low": round(gap_low, 6),
        "gap_high": round(gap_high, 6),
        "gap_size": round(to_float(gap["gap_size"]), 6),
        "middle_body_atr": round(to_float(gap["middle_body_atr"]), 6),
        "signal_bar_excluded_from_gap_discovery": True,
        "in_gap": in_gap,
        "fill_pct": round(fill_pct, 6),
        "mid_fill": mid_fill,
        "deep_fill": deep_fill,
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
                            pyramiding=cfg.max_pyramiding, why="fvg_volatility_out_of_range",
                            skill="none", confidence=0.0, tags=["volatility_gate"], indicators=indicators)
    if late_chase_block and (long_setup or short_setup):
        return build_result(side=None, action="hold", size=0.0, entry=price, sl=price, tp=price,
                            pyramiding=cfg.max_pyramiding, why="fvg_late_chase_block",
                            skill="none", confidence=0.0, tags=["late_chase_block"], indicators=indicators)

    long_sl = min(gap_low - atr_now * cfg.stop_atr_mult, low)
    short_sl = max(gap_high + atr_now * cfg.stop_atr_mult, high)
    long_risk = max(price - long_sl, atr_now * 0.30)
    short_risk = max(short_sl - price, atr_now * 0.30)
    long_tp = price + long_risk * (cfg.beam_rr if long_beam else cfg.base_rr)
    short_tp = price - short_risk * (cfg.beam_rr if short_beam else cfg.base_rr)

    if in_long and failed_long:
        return build_result(side="long", action="reduce", size=cfg.reduce_size_long, entry=price,
                            sl=long_sl, tp=long_tp, pyramiding=cfg.max_pyramiding,
                            why="fvg_failed_long_reduce", skill="failed_gap_reduce", confidence=0.70,
                            tags=["fvg", "reduce", "long"], indicators=indicators)
    if in_short and failed_short:
        return build_result(side="short", action="reduce", size=cfg.reduce_size_short, entry=price,
                            sl=short_sl, tp=short_tp, pyramiding=cfg.max_pyramiding,
                            why="fvg_failed_short_reduce", skill="failed_gap_reduce", confidence=0.66,
                            tags=["fvg", "reduce", "short"], indicators=indicators)
    if in_long and can_add_more and long_setup and deep_fill:
        return build_result(side="long", action="add", size=cfg.add_size_long, entry=price,
                            sl=long_sl, tp=long_tp, pyramiding=cfg.max_pyramiding,
                            why="fvg_long_deep_fill_add", skill="gap_add", confidence=0.60,
                            tags=["fvg", "add", "long"], indicators=indicators)
    if in_short and can_add_more and short_setup and deep_fill:
        return build_result(side="short", action="add", size=cfg.add_size_short, entry=price,
                            sl=short_sl, tp=short_tp, pyramiding=cfg.max_pyramiding,
                            why="fvg_short_deep_fill_add", skill="gap_add", confidence=0.56,
                            tags=["fvg", "add", "short"], indicators=indicators)
    if long_setup and not in_long and not in_short:
        return build_result(side="long", action="enter",
                            size=cfg.long_base_size + (cfg.beam_bonus_long if long_beam else 0.0),
                            entry=price, sl=long_sl, tp=long_tp, pyramiding=cfg.max_pyramiding,
                            why="fvg_down_gap_revert_long", skill="long_beam" if long_beam else "fvg_revert",
                            confidence=0.82 if long_beam else 0.68,
                            tags=["fvg", "three_candle", "long"], indicators=indicators)
    if short_setup and not in_long and not in_short:
        return build_result(side="short", action="enter",
                            size=cfg.short_base_size + (cfg.beam_bonus_short if short_beam else 0.0),
                            entry=price, sl=short_sl, tp=short_tp, pyramiding=cfg.max_pyramiding,
                            why="fvg_up_gap_revert_short", skill="short_beam" if short_beam else "fvg_revert",
                            confidence=0.78 if short_beam else 0.64,
                            tags=["fvg", "three_candle", "short"], indicators=indicators)
    return build_result(side=None, action="hold", size=0.0, entry=price, sl=price, tp=price,
                        pyramiding=cfg.max_pyramiding, why="fvg_no_setup", skill="none",
                        confidence=0.0, tags=["hold"], indicators=indicators)


class FvgRevertLBotStrategy(LBotStrategyBase):
    strategy_name = "fvg_revert"

    def decide(self, ctx: DecisionContext) -> StrategyDecision:
        return decision_from_context(ctx, strategy, FvgRevertConfig(), self.strategy_name)


__all__ = ["FvgRevertConfig", "FvgRevertLBotStrategy", "strategy"]
