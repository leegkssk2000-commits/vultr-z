from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional

import pandas as pd

from backend.strategies._route_a_video_common import (
    adx,
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
_ALLOWED_CONFIRMATION_MODES = {
    "source_core",
    "candle_direction",
    "body_close",
    "trend_strength",
    "pdm_proxy_v1",
}


@dataclass(frozen=True)
class RaschkeMacdEma200Config:
    ema_length: int = 200
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    atr_length: int = 14
    adx_length: int = 14
    min_bars: int = 260
    swing_lookback: int = 12
    stop_buffer_atr: float = 0.08
    reward_r: float = 2.0
    max_ema_distance_atr: float = 3.0
    max_chop_score: float = 0.42
    min_cross_separation_atr: float = 0.002

    # The source video references a proprietary PDM marker whose formula is not
    # available. Research may compare only these pre-declared causal proxies.
    confirmation_mode: str = "candle_direction"
    min_body_atr: float = 0.10
    long_close_location_min: float = 0.60
    short_close_location_max: float = 0.40
    min_adx: float = 17.0
    ema_slope_lookback: int = 5
    min_ema_slope_atr: float = 0.015
    volume_lookback: int = 20
    min_volume_ratio: float = 0.80


def _confirmation(
    *,
    mode: str,
    side: str,
    directional_candle: bool,
    body_atr: float,
    close_location: float,
    adx_now: float,
    ema_slope_atr: float,
    volume_ratio: float,
    spread_accelerating: bool,
    cfg: RaschkeMacdEma200Config,
) -> bool:
    if mode == "source_core":
        return True
    if mode == "candle_direction":
        return directional_candle

    strong_close = (
        close_location >= cfg.long_close_location_min
        if side == "long"
        else close_location <= cfg.short_close_location_max
    )
    body_close = (
        directional_candle
        and body_atr >= cfg.min_body_atr
        and strong_close
    )
    slope_ok = (
        ema_slope_atr >= cfg.min_ema_slope_atr
        if side == "long"
        else ema_slope_atr <= -cfg.min_ema_slope_atr
    )
    trend_strength = directional_candle and adx_now >= cfg.min_adx and slope_ok

    if mode == "body_close":
        return body_close
    if mode == "trend_strength":
        return trend_strength
    if mode == "pdm_proxy_v1":
        return (
            body_close
            and trend_strength
            and volume_ratio >= cfg.min_volume_ratio
            and spread_accelerating
        )
    return False


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

    The video's proprietary PDM marker is not available. The exact public core
    and a small, pre-declared set of causal proxy modes are exposed separately;
    no proxy is represented as a faithful reproduction of PDM.
    """
    cfg = config or RaschkeMacdEma200Config()
    mode = str(cfg.confirmation_mode)
    if mode not in _ALLOWED_CONFIRMATION_MODES:
        return hold(
            STRATEGY_NAME,
            "raschke_macd_ema200_invalid_confirmation_mode",
            confirmation_mode=mode,
        )

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
    adx_series = adx(frame, cfg.adx_length)

    price = safe_float(close.iloc[-1])
    ema_now = safe_float(baseline.iloc[-1])
    atr_now = safe_float(atr_series.iloc[-1])
    adx_now = safe_float(adx_series.iloc[-1])
    line_now = safe_float(line.iloc[-1])
    line_prev = safe_float(line.iloc[-2])
    signal_now = safe_float(signal_line.iloc[-1])
    signal_prev = safe_float(signal_line.iloc[-2])
    hist_now = safe_float(histogram.iloc[-1])
    hist_prev = safe_float(histogram.iloc[-2])
    ema_then = safe_float(baseline.iloc[-1 - cfg.ema_slope_lookback])
    if None in {
        price,
        ema_now,
        atr_now,
        adx_now,
        line_now,
        line_prev,
        signal_now,
        signal_prev,
        hist_now,
        hist_prev,
        ema_then,
    }:
        return hold(STRATEGY_NAME, "raschke_macd_ema200_indicator_nan")

    assert price is not None and ema_now is not None and atr_now is not None
    assert adx_now is not None and ema_then is not None
    assert line_now is not None and line_prev is not None
    assert signal_now is not None and signal_prev is not None
    assert hist_now is not None and hist_prev is not None

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
    prior_spread_atr = abs(line_prev - signal_prev) / max(atr_now, 1e-12)
    spread_accelerating = spread_atr > prior_spread_atr
    if spread_atr < cfg.min_cross_separation_atr:
        return hold(
            STRATEGY_NAME,
            "raschke_macd_ema200_cross_too_weak",
            macd_signal_spread_atr=spread_atr,
        )

    long_core = price > ema_now and bull_cross
    short_core = price < ema_now and bear_cross
    if not (long_core or short_core):
        return hold(
            STRATEGY_NAME,
            "raschke_macd_ema200_no_source_cross",
            price_above_ema200=bool(price > ema_now),
            bull_cross=bull_cross,
            bear_cross=bear_cross,
        )

    side = "long" if long_core else "short"
    candle = candle_metrics(frame)
    directional_candle = (
        candle["bullish"] > 0 if side == "long" else candle["bearish"] > 0
    )
    body_atr = float(candle["body"] / max(atr_now, 1e-12))
    ema_slope_atr = float((ema_now - ema_then) / max(atr_now, 1e-12))
    volume_reference = frame["volume"].iloc[-cfg.volume_lookback - 1 : -1].median()
    volume_ratio = float(
        frame["volume"].iloc[-1] / max(float(volume_reference), 1e-12)
    )

    confirmed = _confirmation(
        mode=mode,
        side=side,
        directional_candle=directional_candle,
        body_atr=body_atr,
        close_location=float(candle["close_location"]),
        adx_now=float(adx_now),
        ema_slope_atr=ema_slope_atr,
        volume_ratio=volume_ratio,
        spread_accelerating=spread_accelerating,
        cfg=cfg,
    )
    if not confirmed:
        return hold(
            STRATEGY_NAME,
            "raschke_macd_ema200_proxy_not_confirmed",
            side_candidate=side,
            confirmation_mode=mode,
            directional_candle=directional_candle,
            candle_body_atr=body_atr,
            close_location=float(candle["close_location"]),
            adx=float(adx_now),
            ema_slope_atr=ema_slope_atr,
            volume_ratio=volume_ratio,
            macd_spread_accelerating=spread_accelerating,
        )

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
        timeframe_hint="1h",
        source_profile="video_2_linda_raschke",
        fidelity="exact_public_core_plus_explicit_proxy_mode",
        unavailable_source_component="proprietary_pdm_marker",
        proxy_component=mode,
        confirmation_mode=mode,
        config=asdict(cfg),
        ema200=ema_now,
        ema_distance_atr=distance_atr,
        ema_slope_atr=ema_slope_atr,
        adx=float(adx_now),
        candle_body_atr=body_atr,
        close_location=float(candle["close_location"]),
        volume_ratio=volume_ratio,
        macd_line=line_now,
        macd_signal=signal_now,
        macd_histogram=float(hist_now),
        macd_signal_spread_atr=spread_atr,
        macd_signal_spread_prev_atr=prior_spread_atr,
        macd_spread_accelerating=spread_accelerating,
        chop_score=chop_score,
    )
