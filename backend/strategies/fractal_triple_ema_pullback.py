from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional

import pandas as pd

from backend.strategies._route_a_video_common import (
    atr,
    candle_metrics,
    ema,
    enter,
    hold,
    prepare_frame,
    risk_target,
    safe_float,
    swing_stop,
    trend_chop_score,
)

STRATEGY_NAME = "fractal_triple_ema_pullback"


@dataclass(frozen=True)
class FractalTripleEmaConfig:
    ema_fast: int = 20
    ema_mid: int = 50
    ema_slow: int = 100
    atr_length: int = 14
    min_bars: int = 180
    pullback_lookback: int = 8
    max_reclaim_distance_atr: float = 1.15
    swing_lookback: int = 12
    stop_buffer_atr: float = 0.08
    reward_r: float = 2.0
    max_chop_score: float = 0.36


def _confirmed_fractal(frame: pd.DataFrame, side: str) -> bool:
    """Classical five-bar Williams fractal confirmed without look-ahead.

    At the current completed candle, the pivot at index -3 has two completed
    candles on each side. This deliberately avoids reading future bars.
    """
    if len(frame) < 5:
        return False
    window = frame.iloc[-5:]
    pivot = window.iloc[2]
    if side == "long":
        value = float(pivot["low"])
        return value < float(window.iloc[0]["low"]) and value < float(window.iloc[1]["low"]) and value <= float(window.iloc[3]["low"]) and value <= float(window.iloc[4]["low"])
    value = float(pivot["high"])
    return value > float(window.iloc[0]["high"]) and value > float(window.iloc[1]["high"]) and value >= float(window.iloc[3]["high"]) and value >= float(window.iloc[4]["high"])


def strategy(
    df: pd.DataFrame,
    *,
    state: Optional[Dict[str, Any]] = None,
    risk_action: str = "hold",
    config: Optional[FractalTripleEmaConfig] = None,
) -> Dict[str, Any]:
    """Bill Williams confirmed-fractal pullback in a 20/50/100 EMA trend."""
    cfg = config or FractalTripleEmaConfig()
    frame, blocked = prepare_frame(
        df,
        strategy_name=STRATEGY_NAME,
        min_bars=cfg.min_bars,
        state=state,
        risk_action=risk_action,
    )
    if blocked is not None or frame is None:
        return blocked or hold(STRATEGY_NAME, "fractal_triple_ema_pullback_invalid_input")

    close = frame["close"]
    e20 = ema(close, cfg.ema_fast)
    e50 = ema(close, cfg.ema_mid)
    e100 = ema(close, cfg.ema_slow)
    atr_series = atr(frame, cfg.atr_length)

    price = safe_float(close.iloc[-1])
    fast_now = safe_float(e20.iloc[-1])
    mid_now = safe_float(e50.iloc[-1])
    slow_now = safe_float(e100.iloc[-1])
    atr_now = safe_float(atr_series.iloc[-1])
    if None in {price, fast_now, mid_now, slow_now, atr_now}:
        return hold(STRATEGY_NAME, "fractal_triple_ema_pullback_indicator_nan")

    assert price is not None and fast_now is not None and mid_now is not None
    assert slow_now is not None and atr_now is not None

    long_trend = fast_now > mid_now > slow_now
    short_trend = fast_now < mid_now < slow_now
    if not (long_trend or short_trend):
        return hold(STRATEGY_NAME, "fractal_triple_ema_pullback_ema_stack_missing")

    side = "long" if long_trend else "short"
    chop_score = max(
        trend_chop_score(close, e20, lookback=24),
        trend_chop_score(close, e50, lookback=24),
    )
    if chop_score > cfg.max_chop_score:
        return hold(
            STRATEGY_NAME,
            "fractal_triple_ema_pullback_chop",
            chop_score=chop_score,
        )

    recent = frame.iloc[-cfg.pullback_lookback :]
    e20_recent = e20.iloc[-cfg.pullback_lookback :]
    e50_recent = e50.iloc[-cfg.pullback_lookback :]
    if side == "long":
        touched = bool(
            (recent["low"].to_numpy() <= e20_recent.to_numpy()).any()
            or (recent["low"].to_numpy() <= e50_recent.to_numpy()).any()
        )
        reclaimed = price > fast_now
        distance = (price - fast_now) / max(atr_now, 1e-12)
    else:
        touched = bool(
            (recent["high"].to_numpy() >= e20_recent.to_numpy()).any()
            or (recent["high"].to_numpy() >= e50_recent.to_numpy()).any()
        )
        reclaimed = price < fast_now
        distance = (fast_now - price) / max(atr_now, 1e-12)

    if not touched or not reclaimed or distance > cfg.max_reclaim_distance_atr:
        return hold(
            STRATEGY_NAME,
            "fractal_triple_ema_pullback_no_valid_reclaim",
            side_candidate=side,
            pullback_touched=touched,
            reclaimed=reclaimed,
            reclaim_distance_atr=distance,
        )

    if not _confirmed_fractal(frame, side):
        return hold(
            STRATEGY_NAME,
            "fractal_triple_ema_pullback_fractal_not_confirmed",
            side_candidate=side,
        )

    candle = candle_metrics(frame)
    confirmation = candle["bullish"] > 0 if side == "long" else candle["bearish"] > 0
    if not confirmation:
        return hold(
            STRATEGY_NAME,
            "fractal_triple_ema_pullback_confirmation_candle_missing",
            side_candidate=side,
        )

    stop_price = swing_stop(
        frame.iloc[:-1],
        side,
        cfg.swing_lookback,
        cfg.stop_buffer_atr,
        atr_now,
    )
    if side == "long":
        stop_price = min(stop_price, mid_now - cfg.stop_buffer_atr * atr_now)
    else:
        stop_price = max(stop_price, mid_now + cfg.stop_buffer_atr * atr_now)

    if (side == "long" and stop_price >= price) or (
        side == "short" and stop_price <= price
    ):
        return hold(STRATEGY_NAME, "fractal_triple_ema_pullback_invalid_stop")

    target_price = risk_target(price, stop_price, side, cfg.reward_r)
    return enter(
        STRATEGY_NAME,
        side,
        price,
        stop_price,
        target_price,
        "fractal_triple_ema_pullback_confirmed",
        timeframe_hint="15m_to_1h",
        source_profile="video_3_bill_williams_fractal",
        fidelity="exact_public_fractal_and_ema_core",
        config=asdict(cfg),
        ema20=fast_now,
        ema50=mid_now,
        ema100=slow_now,
        reclaim_distance_atr=distance,
        chop_score=chop_score,
    )
