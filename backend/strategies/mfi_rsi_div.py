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
    mfi,
    prepare_ohlcv,
    rsi,
    to_float,
)


@dataclass
class MfiRsiDivConfig:
    length: int = 14
    swing_lookback: int = 28
    atr_len: int = 14
    ema_fast_len: int = 21
    ema_slow_len: int = 55
    min_bars: int = 100
    min_atr_pct: float = 0.14
    max_atr_pct: float = 5.20
    bull_rsi_gate: float = 42.0
    bear_rsi_gate: float = 58.0
    bull_mfi_gate: float = 45.0
    bear_mfi_gate: float = 55.0
    min_div_buffer_pct: float = 0.0012
    reclaim_atr_min: float = 0.14
    max_chase_dist_atr: float = 1.35
    fail_div_reject_atr: float = 0.22
    beam_rsi_delta: float = 5.0
    beam_mfi_delta: float = 6.0
    beam_body_ratio_min: float = 0.36
    beam_close_location_min: float = 0.60
    stop_atr_mult: float = 0.70
    trail_atr_mult: float = 0.46
    base_rr: float = 2.20
    beam_rr: float = 2.80
    long_base_size: float = 0.48
    short_base_size: float = 0.34
    beam_bonus_long: float = 0.12
    beam_bonus_short: float = 0.10
    add_size_long: float = 0.14
    add_size_short: float = 0.10
    reduce_size_long: float = 0.24
    reduce_size_short: float = 0.20
    max_add_count: int = 1
    max_pyramiding: int = 2


def strategy(
    df: pd.DataFrame,
    *,
    state: Optional[Dict[str, Any]] = None,
    risk_action: str = "hold",
    config: Optional[MfiRsiDivConfig] = None,
) -> Dict[str, Any]:
    cfg = config or MfiRsiDivConfig()
    frame = prepare_ohlcv(df, require_volume=True)
    if frame is None:
        return invalid_result("mfi_rsi_div_invalid_input", cfg.max_pyramiding)
    if len(frame) < max(cfg.min_bars, cfg.swing_lookback + cfg.length + 5, cfg.ema_slow_len + 5):
        return invalid_result("mfi_rsi_div_short", cfg.max_pyramiding, tags=["warmup"])
    if str(risk_action or "hold").lower() in {"block", "stop", "rollback"}:
        return invalid_result(f"risk_gate_{risk_action}", cfg.max_pyramiding, tags=["risk_gated"])

    frame["mfi"] = mfi(frame, cfg.length)
    frame["rsi"] = rsi(frame["close"], cfg.length)
    frame["atr"] = atr(frame, cfg.atr_len)
    frame["ema_fast"] = ema(frame["close"], cfg.ema_fast_len)
    frame["ema_slow"] = ema(frame["close"], cfg.ema_slow_len)

    last, prev = frame.iloc[-1], frame.iloc[-2]
    # The comparison swing must be fully prior to the signal bar. Including the
    # signal bar makes price < min(low) and price > max(high) mathematically unreachable.
    prior = frame.iloc[-(cfg.swing_lookback + 1):-1]
    swing_low_idx = prior["low"].idxmin()
    swing_high_idx = prior["high"].idxmax()

    price = to_float(last["close"])
    open_ = to_float(last["open"])
    high = to_float(last["high"])
    low = to_float(last["low"])
    prev_close = to_float(prev["close"])
    atr_now = to_float(last["atr"])
    mfi_now = to_float(last["mfi"], 50.0)
    rsi_now = to_float(last["rsi"], 50.0)
    ema_fast = to_float(last["ema_fast"])
    ema_slow = to_float(last["ema_slow"])
    ema_fast_prev = to_float(prev["ema_fast"])
    ema_slow_prev = to_float(prev["ema_slow"])
    swing_low_price = to_float(frame.loc[swing_low_idx, "low"])
    swing_high_price = to_float(frame.loc[swing_high_idx, "high"])
    swing_low_mfi = to_float(frame.loc[swing_low_idx, "mfi"], 50.0)
    swing_high_mfi = to_float(frame.loc[swing_high_idx, "mfi"], 50.0)
    swing_low_rsi = to_float(frame.loc[swing_low_idx, "rsi"], 50.0)
    swing_high_rsi = to_float(frame.loc[swing_high_idx, "rsi"], 50.0)
    if min(price, atr_now, ema_fast, ema_slow, swing_low_price, swing_high_price) <= 0:
        return invalid_result("mfi_rsi_div_indicator_nan", cfg.max_pyramiding, tags=["indicator_nan"])

    price_makes_lower_low = price < swing_low_price * (1.0 - cfg.min_div_buffer_pct)
    price_makes_higher_high = price > swing_high_price * (1.0 + cfg.min_div_buffer_pct)
    bull_mfi_div = mfi_now > swing_low_mfi
    bull_rsi_div = rsi_now > swing_low_rsi
    bear_mfi_div = mfi_now < swing_high_mfi
    bear_rsi_div = rsi_now < swing_high_rsi
    long_reclaim = price > prev_close + atr_now * cfg.reclaim_atr_min
    short_reclaim = price < prev_close - atr_now * cfg.reclaim_atr_min
    trend_long = price > ema_fast > ema_slow and ema_fast >= ema_fast_prev and ema_slow >= ema_slow_prev
    trend_short = price < ema_fast < ema_slow and ema_fast <= ema_fast_prev and ema_slow <= ema_slow_prev

    long_setup = (
        price_makes_lower_low and bull_mfi_div and bull_rsi_div
        and mfi_now <= cfg.bull_mfi_gate and rsi_now <= cfg.bull_rsi_gate
        and long_reclaim and not trend_short
    )
    short_setup = (
        price_makes_higher_high and bear_mfi_div and bear_rsi_div
        and mfi_now >= cfg.bear_mfi_gate and rsi_now >= cfg.bear_rsi_gate
        and short_reclaim and not trend_long
    )
    candle_body_ratio = body_ratio(open_, price, low, high)
    close_loc = close_location(price, low, high)
    long_beam = (
        long_setup and (rsi_now - swing_low_rsi) >= cfg.beam_rsi_delta
        and (mfi_now - swing_low_mfi) >= cfg.beam_mfi_delta
        and candle_body_ratio >= cfg.beam_body_ratio_min
        and close_loc >= cfg.beam_close_location_min
    )
    short_beam = (
        short_setup and (swing_high_rsi - rsi_now) >= cfg.beam_rsi_delta
        and (swing_high_mfi - mfi_now) >= cfg.beam_mfi_delta
        and candle_body_ratio >= cfg.beam_body_ratio_min
        and (1.0 - close_loc) >= cfg.beam_close_location_min
    )

    atr_pct = atr_now / max(price, 1e-9) * 100.0
    dist_from_fast_atr = abs(price - ema_fast) / max(atr_now, 1e-9)
    vol_ok = cfg.min_atr_pct <= atr_pct <= cfg.max_atr_pct
    late_chase_block = dist_from_fast_atr > cfg.max_chase_dist_atr
    failed_long = price < swing_low_price - atr_now * cfg.fail_div_reject_atr and not long_reclaim
    failed_short = price > swing_high_price + atr_now * cfg.fail_div_reject_atr and not short_reclaim
    pos = infer_position_state(state)
    in_long = pos["position_side"] == "long" and pos["position_qty"] > 0
    in_short = pos["position_side"] == "short" and pos["position_qty"] > 0
    can_add_more = pos["add_count"] < cfg.max_add_count

    indicators = {
        "price": round(price, 6),
        "atr": round(atr_now, 6),
        "atr_pct": round(atr_pct, 6),
        "mfi": round(mfi_now, 6),
        "rsi": round(rsi_now, 6),
        "ema_fast": round(ema_fast, 6),
        "ema_slow": round(ema_slow, 6),
        "prior_swing_window_excludes_signal_bar": True,
        "swing_low_index": str(swing_low_idx),
        "swing_high_index": str(swing_high_idx),
        "swing_low_price": round(swing_low_price, 6),
        "swing_high_price": round(swing_high_price, 6),
        "swing_low_mfi": round(swing_low_mfi, 6),
        "swing_high_mfi": round(swing_high_mfi, 6),
        "swing_low_rsi": round(swing_low_rsi, 6),
        "swing_high_rsi": round(swing_high_rsi, 6),
        "price_makes_lower_low": price_makes_lower_low,
        "price_makes_higher_high": price_makes_higher_high,
        "bull_mfi_div": bull_mfi_div,
        "bull_rsi_div": bull_rsi_div,
        "bear_mfi_div": bear_mfi_div,
        "bear_rsi_div": bear_rsi_div,
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
                            pyramiding=cfg.max_pyramiding, why="mfi_rsi_div_volatility_out_of_range",
                            skill="none", confidence=0.0, tags=["volatility_gate"], indicators=indicators)
    if late_chase_block and (long_setup or short_setup):
        return build_result(side=None, action="hold", size=0.0, entry=price, sl=price, tp=price,
                            pyramiding=cfg.max_pyramiding, why="mfi_rsi_div_late_chase_block",
                            skill="none", confidence=0.0, tags=["late_chase_block"], indicators=indicators)

    long_sl = min(swing_low_price - atr_now * cfg.stop_atr_mult, ema_fast - atr_now * cfg.trail_atr_mult, low)
    short_sl = max(swing_high_price + atr_now * cfg.stop_atr_mult, ema_fast + atr_now * cfg.trail_atr_mult, high)
    long_risk = max(price - long_sl, atr_now * 0.28)
    short_risk = max(short_sl - price, atr_now * 0.28)
    long_tp = price + long_risk * (cfg.beam_rr if long_beam else cfg.base_rr)
    short_tp = price - short_risk * (cfg.beam_rr if short_beam else cfg.base_rr)

    if in_long and failed_long:
        return build_result(side="long", action="reduce", size=cfg.reduce_size_long, entry=price,
                            sl=long_sl, tp=long_tp, pyramiding=cfg.max_pyramiding,
                            why="mfi_rsi_div_failed_long_reduce", skill="failed_div_reduce", confidence=0.68,
                            tags=["mfi", "rsi", "div", "reduce", "long"], indicators=indicators)
    if in_short and failed_short:
        return build_result(side="short", action="reduce", size=cfg.reduce_size_short, entry=price,
                            sl=short_sl, tp=short_tp, pyramiding=cfg.max_pyramiding,
                            why="mfi_rsi_div_failed_short_reduce", skill="failed_div_reduce", confidence=0.64,
                            tags=["mfi", "rsi", "div", "reduce", "short"], indicators=indicators)
    if in_long and can_add_more and long_setup:
        return build_result(side="long", action="add", size=cfg.add_size_long, entry=price,
                            sl=long_sl, tp=long_tp, pyramiding=cfg.max_pyramiding,
                            why="mfi_rsi_div_long_add", skill="dip_add", confidence=0.60,
                            tags=["mfi", "rsi", "div", "add", "long"], indicators=indicators)
    if in_short and can_add_more and short_setup:
        return build_result(side="short", action="add", size=cfg.add_size_short, entry=price,
                            sl=short_sl, tp=short_tp, pyramiding=cfg.max_pyramiding,
                            why="mfi_rsi_div_short_add", skill="dip_add", confidence=0.56,
                            tags=["mfi", "rsi", "div", "add", "short"], indicators=indicators)
    if long_setup and not in_long and not in_short:
        return build_result(side="long", action="enter",
                            size=cfg.long_base_size + (cfg.beam_bonus_long if long_beam else 0.0),
                            entry=price, sl=long_sl, tp=long_tp, pyramiding=cfg.max_pyramiding,
                            why="mfi_rsi_bull_div", skill="long_beam" if long_beam else "dual_div_reclaim",
                            confidence=0.84 if long_beam else 0.70,
                            tags=["mfi", "rsi", "div", "long"], indicators=indicators)
    if short_setup and not in_long and not in_short:
        return build_result(side="short", action="enter",
                            size=cfg.short_base_size + (cfg.beam_bonus_short if short_beam else 0.0),
                            entry=price, sl=short_sl, tp=short_tp, pyramiding=cfg.max_pyramiding,
                            why="mfi_rsi_bear_div", skill="short_beam" if short_beam else "dual_div_reclaim",
                            confidence=0.80 if short_beam else 0.66,
                            tags=["mfi", "rsi", "div", "short"], indicators=indicators)
    return build_result(side=None, action="hold", size=0.0, entry=price, sl=price, tp=price,
                        pyramiding=cfg.max_pyramiding, why="mfi_rsi_div_no_setup", skill="none",
                        confidence=0.0, tags=["hold"], indicators=indicators)


class MfiRsiDivLBotStrategy(LBotStrategyBase):
    strategy_name = "mfi_rsi_div"

    def decide(self, ctx: DecisionContext) -> StrategyDecision:
        return decision_from_context(ctx, strategy, MfiRsiDivConfig(), self.strategy_name)


__all__ = ["MfiRsiDivConfig", "MfiRsiDivLBotStrategy", "strategy"]
