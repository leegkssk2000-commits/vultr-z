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
class VolSpikeFadeConfig:
    vol_lookback: int = 30
    atr_len: int = 14
    ema_fast_len: int = 20
    ema_slow_len: int = 55
    min_bars: int = 90
    vol_mult: float = 2.40
    atr_spike_mult: float = 1.40
    min_atr_pct: float = 0.25
    max_atr_pct: float = 6.50
    max_trend_stretch_pct: float = 4.80
    peak_body_atr_min: float = 0.80
    reversal_body_atr_min: float = 0.30
    reversal_close_location_min: float = 0.58
    wick_ratio_max: float = 0.45
    reclaim_atr_min: float = 0.20
    base_rr: float = 1.60
    beam_rr: float = 2.10
    stop_atr_mult: float = 0.45
    long_base_size: float = 0.32
    short_base_size: float = 0.28
    beam_bonus_long: float = 0.12
    beam_bonus_short: float = 0.10
    scale_in_size_long: float = 0.16
    scale_in_size_short: float = 0.12
    water_add_size_long: float = 0.10
    water_add_size_short: float = 0.08
    max_add_count: int = 2
    max_pyramiding: int = 2
    enable_water_add: bool = False
    water_add_extension_atr: float = 1.80
    progress_to_mean_min: float = 0.35


def _upper_wick_ratio(open_: float, close: float, low: float, high: float) -> float:
    return max(high - max(open_, close), 0.0) / max(high - low, 1e-9)


def _lower_wick_ratio(open_: float, close: float, low: float, high: float) -> float:
    return max(min(open_, close) - low, 0.0) / max(high - low, 1e-9)


def strategy(
    df: pd.DataFrame,
    *,
    state: Optional[Dict[str, Any]] = None,
    risk_action: str = "hold",
    config: Optional[VolSpikeFadeConfig] = None,
) -> Dict[str, Any]:
    cfg = config or VolSpikeFadeConfig()
    frame = prepare_ohlcv(df, require_volume=True)
    if frame is None:
        return invalid_result("volfade_invalid_input", cfg.max_pyramiding)
    need = max(cfg.min_bars, cfg.vol_lookback + 3, cfg.ema_slow_len + 5)
    if len(frame) < need:
        return invalid_result("volfade_not_enough_bars", cfg.max_pyramiding, tags=["warmup"])
    if str(risk_action or "hold").lower() in {"block", "stop", "rollback"}:
        return invalid_result(f"risk_gate_{risk_action}", cfg.max_pyramiding, tags=["risk_gated"])

    frame["atr"] = atr(frame, cfg.atr_len)
    frame["ema_fast"] = ema(frame["close"], cfg.ema_fast_len)
    frame["ema_slow"] = ema(frame["close"], cfg.ema_slow_len)
    # Both baselines are causal for the candidate spike candle.
    frame["vol_ma_prior"] = frame["volume"].shift(1).rolling(
        cfg.vol_lookback, min_periods=cfg.vol_lookback
    ).mean()
    frame["atr_ma_prior"] = frame["atr"].shift(1).rolling(
        cfg.vol_lookback, min_periods=cfg.vol_lookback
    ).mean()

    last, spike = frame.iloc[-1], frame.iloc[-2]
    price = to_float(last["close"])
    open_ = to_float(last["open"])
    high = to_float(last["high"])
    low = to_float(last["low"])
    atr_now = to_float(last["atr"])
    ema_fast = to_float(last["ema_fast"])
    ema_slow = to_float(last["ema_slow"])

    spike_open = to_float(spike["open"])
    spike_close = to_float(spike["close"])
    spike_high = to_float(spike["high"])
    spike_low = to_float(spike["low"])
    spike_volume = to_float(spike["volume"])
    spike_atr = to_float(spike["atr"])
    spike_vol_ma = to_float(spike["vol_ma_prior"])
    spike_atr_ma = to_float(spike["atr_ma_prior"])
    if min(price, atr_now, ema_fast, ema_slow, spike_atr, spike_vol_ma, spike_atr_ma) <= 0:
        return invalid_result("volfade_indicator_nan", cfg.max_pyramiding, tags=["indicator_nan"])

    spike_body_atr = abs(spike_close - spike_open) / max(spike_atr, 1e-9)
    spike_close_loc = close_location(spike_close, spike_low, spike_high)
    spike_upper_wick = _upper_wick_ratio(spike_open, spike_close, spike_low, spike_high)
    spike_lower_wick = _lower_wick_ratio(spike_open, spike_close, spike_low, spike_high)
    volume_spike = spike_volume >= spike_vol_ma * cfg.vol_mult
    atr_spike = spike_atr >= spike_atr_ma * cfg.atr_spike_mult
    spike_ok = volume_spike and atr_spike
    bullish_spike = (
        spike_ok and spike_close > spike_open
        and spike_body_atr >= cfg.peak_body_atr_min
        and spike_upper_wick <= cfg.wick_ratio_max
        and spike_close_loc >= 0.60
    )
    bearish_spike = (
        spike_ok and spike_close < spike_open
        and spike_body_atr >= cfg.peak_body_atr_min
        and spike_lower_wick <= cfg.wick_ratio_max
        and spike_close_loc <= 0.40
    )

    reversal_body_atr = abs(price - open_) / max(atr_now, 1e-9)
    reversal_close_loc = close_location(price, low, high)
    current_bearish_reversal = (
        price < open_
        and price < spike_close - atr_now * cfg.reclaim_atr_min
        and reversal_body_atr >= cfg.reversal_body_atr_min
        and reversal_close_loc <= 1.0 - cfg.reversal_close_location_min
    )
    current_bullish_reversal = (
        price > open_
        and price > spike_close + atr_now * cfg.reclaim_atr_min
        and reversal_body_atr >= cfg.reversal_body_atr_min
        and reversal_close_loc >= cfg.reversal_close_location_min
    )
    short_setup = bullish_spike and current_bearish_reversal
    long_setup = bearish_spike and current_bullish_reversal
    short_beam = short_setup and price < (spike_open + spike_close) / 2.0
    long_beam = long_setup and price > (spike_open + spike_close) / 2.0

    trend_up = price > ema_fast > ema_slow
    trend_down = price < ema_fast < ema_slow
    trend_stretch_pct = abs(price - ema_slow) / max(ema_slow, 1e-9) * 100.0
    long_veto = trend_down and trend_stretch_pct >= cfg.max_trend_stretch_pct
    short_veto = trend_up and trend_stretch_pct >= cfg.max_trend_stretch_pct
    atr_pct = atr_now / max(price, 1e-9) * 100.0
    vol_ok = cfg.min_atr_pct <= atr_pct <= cfg.max_atr_pct

    pos = infer_position_state(state)
    in_long = pos["position_side"] == "long" and pos["position_qty"] > 0
    in_short = pos["position_side"] == "short" and pos["position_qty"] > 0
    can_add_more = pos["add_count"] < cfg.max_add_count
    mean_price = (spike_open + spike_close) / 2.0
    indicators = {
        "price": round(price, 6),
        "atr": round(atr_now, 6),
        "atr_pct": round(atr_pct, 6),
        "ema_fast": round(ema_fast, 6),
        "ema_slow": round(ema_slow, 6),
        "spike_bar_offset": -2,
        "signal_bar_offset": -1,
        "spike_and_reversal_are_distinct_bars": True,
        "spike_volume": round(spike_volume, 6),
        "spike_vol_ma_prior": round(spike_vol_ma, 6),
        "spike_atr": round(spike_atr, 6),
        "spike_atr_ma_prior": round(spike_atr_ma, 6),
        "volume_spike": volume_spike,
        "atr_spike": atr_spike,
        "bullish_spike": bullish_spike,
        "bearish_spike": bearish_spike,
        "current_bearish_reversal": current_bearish_reversal,
        "current_bullish_reversal": current_bullish_reversal,
        "long_setup": long_setup,
        "short_setup": short_setup,
        "long_beam": long_beam,
        "short_beam": short_beam,
        "trend_up": trend_up,
        "trend_down": trend_down,
        "trend_stretch_pct": round(trend_stretch_pct, 6),
        "long_veto": long_veto,
        "short_veto": short_veto,
        "mean_price": round(mean_price, 6),
        "position_side": pos["position_side"],
        "position_qty": pos["position_qty"],
        "avg_entry": pos["avg_entry"],
        "add_count": pos["add_count"],
    }
    if not vol_ok:
        return build_result(side=None, action="hold", size=0.0, entry=price, sl=price, tp=price,
                            pyramiding=cfg.max_pyramiding, why="volfade_volatility_out_of_range",
                            skill="none", confidence=0.0, tags=["volatility_gate"], indicators=indicators)
    if long_veto and long_setup:
        return build_result(side=None, action="hold", size=0.0, entry=price, sl=price, tp=price,
                            pyramiding=cfg.max_pyramiding, why="volfade_long_trend_veto",
                            skill="none", confidence=0.0, tags=["trend_veto"], indicators=indicators)
    if short_veto and short_setup:
        return build_result(side=None, action="hold", size=0.0, entry=price, sl=price, tp=price,
                            pyramiding=cfg.max_pyramiding, why="volfade_short_trend_veto",
                            skill="none", confidence=0.0, tags=["trend_veto"], indicators=indicators)

    long_sl = min(spike_low - atr_now * cfg.stop_atr_mult, low)
    short_sl = max(spike_high + atr_now * cfg.stop_atr_mult, high)
    long_risk = max(price - long_sl, atr_now * 0.35)
    short_risk = max(short_sl - price, atr_now * 0.35)
    long_tp = max(mean_price, price + long_risk * (cfg.beam_rr if long_beam else cfg.base_rr))
    short_tp = min(mean_price, price - short_risk * (cfg.beam_rr if short_beam else cfg.base_rr))

    failed_long = in_long and price < spike_low - atr_now * 0.15
    failed_short = in_short and price > spike_high + atr_now * 0.15
    if failed_long:
        return build_result(side="long", action="reduce", size=0.25, entry=price, sl=long_sl, tp=long_tp,
                            pyramiding=cfg.max_pyramiding, why="volfade_failed_long_reduce",
                            skill="failed_fade_reduce", confidence=0.72,
                            tags=["volume_spike", "fade", "reduce", "long"], indicators=indicators)
    if failed_short:
        return build_result(side="short", action="reduce", size=0.20, entry=price, sl=short_sl, tp=short_tp,
                            pyramiding=cfg.max_pyramiding, why="volfade_failed_short_reduce",
                            skill="failed_fade_reduce", confidence=0.68,
                            tags=["volume_spike", "fade", "reduce", "short"], indicators=indicators)
    if in_long and can_add_more and long_setup and price > pos["avg_entry"]:
        return build_result(side="long", action="add", size=cfg.scale_in_size_long, entry=price,
                            sl=long_sl, tp=long_tp, pyramiding=cfg.max_pyramiding,
                            why="volfade_long_scale_in", skill="scale_in", confidence=0.60,
                            tags=["volume_spike", "fade", "add", "long"], indicators=indicators)
    if in_short and can_add_more and short_setup and price < pos["avg_entry"]:
        return build_result(side="short", action="add", size=cfg.scale_in_size_short, entry=price,
                            sl=short_sl, tp=short_tp, pyramiding=cfg.max_pyramiding,
                            why="volfade_short_scale_in", skill="scale_in", confidence=0.56,
                            tags=["volume_spike", "fade", "add", "short"], indicators=indicators)
    if long_setup and not in_long and not in_short:
        return build_result(side="long", action="enter",
                            size=cfg.long_base_size + (cfg.beam_bonus_long if long_beam else 0.0),
                            entry=price, sl=long_sl, tp=long_tp, pyramiding=cfg.max_pyramiding,
                            why="vol_spike_fade_long_confirmed", skill="long_beam" if long_beam else "vol_spike_fade",
                            confidence=0.82 if long_beam else 0.68,
                            tags=["volume_spike", "post_spike_reversal", "long"], indicators=indicators)
    if short_setup and not in_long and not in_short:
        return build_result(side="short", action="enter",
                            size=cfg.short_base_size + (cfg.beam_bonus_short if short_beam else 0.0),
                            entry=price, sl=short_sl, tp=short_tp, pyramiding=cfg.max_pyramiding,
                            why="vol_spike_fade_short_confirmed", skill="short_beam" if short_beam else "vol_spike_fade",
                            confidence=0.78 if short_beam else 0.64,
                            tags=["volume_spike", "post_spike_reversal", "short"], indicators=indicators)
    return build_result(side=None, action="hold", size=0.0, entry=price, sl=price, tp=price,
                        pyramiding=cfg.max_pyramiding, why="volfade_no_confirmed_reversal",
                        skill="none", confidence=0.0, tags=["hold"], indicators=indicators)


class VolSpikeFadeLBotStrategy(LBotStrategyBase):
    strategy_name = "vol_spike_fade"

    def decide(self, ctx: DecisionContext) -> StrategyDecision:
        return decision_from_context(ctx, strategy, VolSpikeFadeConfig(), self.strategy_name)


__all__ = ["VolSpikeFadeConfig", "VolSpikeFadeLBotStrategy", "strategy"]
