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
    macd,
    prepare_frame,
    risk_target,
    safe_float,
    swing_stop,
    trend_chop_score,
)

STRATEGY_NAME = "raschke_macd_ema200"


@dataclass(frozen=True)
class RaschkeMacdEma200Config:
    ema_length: int = 200
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    atr_length: int = 14
    min_bars: int = 260
    swing_lookback: int = 12
    stop_buffer_atr: float = 0.08
    reward_r: float = 2.0
    max_ema_distance_atr: float = 3.0
    max_chop_score: float = 0.42
    min_cross_separation_atr: float = 0.002


def strategy(
    df: pd.DataFrame,
    *,
    state: Optional[Dict[str, Any]] = None,
    risk_action: str = "hold",
    config: Optional[RaschkeMacdEma200Config] = None,
) -> Dict[str, Any]:
    """Linda Raschke-style MACD cross with a 200 EMA trend filter.

    Preserved source rules:
    - Long only above EMA200 and on a MACD bullish cross below zero.
    - Short only below EMA200 and on a MACD bearish cross above zero.
    - Reject EMA200 whipsaw/chop and highly extended entries.
    - Use the prior swing for the stop and a 2R target.

    The video's proprietary PDM marker is not available in the repository.
    A causal candle-direction confirmation is emitted as an explicit proxy and
    is labeled in metadata rather than represented as an exact reproduction.
    """
    cfg = config or RaschkeMacdEma200Config()
    frame, blocked = prepare_frame(
        df,
        strategy_name=STRATEGY_NAME,
        min_bars=cfg.min_bars,
        state=state,
        risk_action=risk_action,
    )
    if blocked is not None or frame is None:
        return blocked or hold(STRATEGY_NAME, "raschke_macd_ema200_invalid_input")

    close = frame["close"]
    baseline = ema(close, cfg.ema_length)
    line, signal_line, histogram = macd(
        close,
        cfg.macd_fast,
        cfg.macd_slow,
        cfg.macd_signal,
    )
    atr_series = atr(frame, cfg.atr_length)

    price = safe_float(close.iloc[-1])
    ema_now = safe_float(baseline.iloc[-1])
    atr_now = safe_float(atr_series.iloc[-1])
    line_now = safe_float(line.iloc[-1])
    line_prev = safe_float(line.iloc[-2])
    signal_now = safe_float(signal_line.iloc[-1])
    signal_prev = safe_float(signal_line.iloc[-2])
    hist_now = safe_float(histogram.iloc[-1])
    if None in {
        price,
        ema_now,
        atr_now,
        line_now,
        line_prev,
        signal_now,
        signal_prev,
        hist_now,
    }:
        return hold(STRATEGY_NAME, "raschke_macd_ema200_indicator_nan")

    assert price is not None and ema_now is not None and atr_now is not None
    assert line_now is not None and line_prev is not None
    assert signal_now is not None and signal_prev is not None

    chop_score = trend_chop_score(close, baseline, lookback=30)
    if chop_score > cfg.max_chop_score:
        return hold(
            STRATEGY_NAME,
            "raschke_macd_ema200_whipsaw",
            chop_score=chop_score,
        )

    distance_atr = abs(price - ema_now) / max(atr_now, 1e-12)
    if distance_atr > cfg.max_ema_distance_atr:
        return hold(
            STRATEGY_NAME,
            "raschke_macd_ema200_overextended",
            ema_distance_atr=distance_atr,
        )

    bull_cross = line_prev <= signal_prev and line_now > signal_now and line_now < 0
    bear_cross = line_prev >= signal_prev and line_now < signal_now and line_now > 0
    spread_atr = abs(line_now - signal_now) / max(atr_now, 1e-12)
    if spread_atr < cfg.min_cross_separation_atr:
        return hold(
            STRATEGY_NAME,
            "raschke_macd_ema200_cross_too_weak",
            macd_signal_spread_atr=spread_atr,
        )

    candle = candle_metrics(frame)
    long_ok = price > ema_now and bull_cross and candle["bullish"] > 0
    short_ok = price < ema_now and bear_cross and candle["bearish"] > 0
    if not (long_ok or short_ok):
        return hold(
            STRATEGY_NAME,
            "raschke_macd_ema200_no_confirmed_cross",
            price_above_ema200=bool(price > ema_now),
            bull_cross=bull_cross,
            bear_cross=bear_cross,
        )

    side = "long" if long_ok else "short"
    stop_price = swing_stop(
        frame.iloc[:-1],
        side,
        cfg.swing_lookback,
        cfg.stop_buffer_atr,
        atr_now,
    )
    if (side == "long" and stop_price >= price) or (
        side == "short" and stop_price <= price
    ):
        return hold(STRATEGY_NAME, "raschke_macd_ema200_invalid_swing_stop")

    target_price = risk_target(price, stop_price, side, cfg.reward_r)
    return enter(
        STRATEGY_NAME,
        side,
        price,
        stop_price,
        target_price,
        "raschke_macd_ema200_zero_zone_cross",
        timeframe_hint="15m_to_1h",
        source_profile="video_2_linda_raschke",
        fidelity="exact_core_plus_explicit_pdm_proxy",
        unavailable_source_component="proprietary_pdm_marker",
        proxy_component="confirmation_candle_direction",
        config=asdict(cfg),
        ema200=ema_now,
        ema_distance_atr=distance_atr,
        macd_line=line_now,
        macd_signal=signal_now,
        macd_histogram=float(hist_now),
        macd_signal_spread_atr=spread_atr,
        chop_score=chop_score,
    )
