from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional

import pandas as pd

from backend.strategies._route_a_video_common import (
    atr,
    candle_metrics,
    ema,
    enter,
    histogram_expansion,
    hold,
    macd,
    prepare_frame,
    pullback_near_ema,
    risk_target,
    safe_float,
    swing_stop,
    trend_chop_score,
)

STRATEGY_NAME = "rayner_hist_momentum"


@dataclass(frozen=True)
class RaynerHistMomentumConfig:
    ema_length: int = 60
    macd_fast: int = 1
    macd_slow: int = 60
    macd_signal: int = 9
    atr_length: int = 14
    min_bars: int = 160
    pullback_lookback: int = 8
    max_pullback_distance_atr: float = 0.85
    histogram_lookback: int = 7
    histogram_min_expansion_ratio: float = 1.35
    swing_lookback: int = 10
    stop_buffer_atr: float = 0.08
    reward_r: float = 2.0
    max_chop_score: float = 0.38
    min_atr_pct: float = 0.10
    max_atr_pct: float = 4.50


def strategy(
    df: pd.DataFrame,
    *,
    state: Optional[Dict[str, Any]] = None,
    risk_action: str = "hold",
    config: Optional[RaynerHistMomentumConfig] = None,
) -> Dict[str, Any]:
    """Faithful entry core for the Rayner Teo 60 EMA + MACD histogram method.

    Source mechanics preserved:
    - 60 EMA trend filter.
    - MACD fast/slow/signal = 1/60/9.
    - Enter only after a pullback toward the EMA and a clearly expanding
      same-direction histogram bar.
    - Block EMA whipsaw/chop.
    - Swing high/low stop and 2R native target.
    - Emit histogram-peak exit metadata for a separate causal exit observer.

    The recommended source timeframe is 1h. The caller remains responsible for
    resampling completed candles and for all execution authority.
    """
    cfg = config or RaynerHistMomentumConfig()
    frame, blocked = prepare_frame(
        df,
        strategy_name=STRATEGY_NAME,
        min_bars=cfg.min_bars,
        state=state,
        risk_action=risk_action,
    )
    if blocked is not None or frame is None:
        return blocked or hold(STRATEGY_NAME, "rayner_hist_momentum_invalid_input")

    close = frame["close"]
    baseline = ema(close, cfg.ema_length)
    _, _, histogram = macd(
        close,
        cfg.macd_fast,
        cfg.macd_slow,
        cfg.macd_signal,
    )
    atr_series = atr(frame, cfg.atr_length)

    price = safe_float(close.iloc[-1])
    ema_now = safe_float(baseline.iloc[-1])
    atr_now = safe_float(atr_series.iloc[-1])
    hist_now = safe_float(histogram.iloc[-1])
    if None in {price, ema_now, atr_now, hist_now}:
        return hold(STRATEGY_NAME, "rayner_hist_momentum_indicator_nan")

    assert price is not None and ema_now is not None and atr_now is not None
    if min(price, ema_now, atr_now) <= 0:
        return hold(STRATEGY_NAME, "rayner_hist_momentum_indicator_nan")

    atr_pct = atr_now / price * 100.0
    if not cfg.min_atr_pct <= atr_pct <= cfg.max_atr_pct:
        return hold(
            STRATEGY_NAME,
            "rayner_hist_momentum_volatility_out_of_range",
            atr_pct=atr_pct,
        )

    chop_score = trend_chop_score(close, baseline, lookback=20)
    if chop_score > cfg.max_chop_score:
        return hold(
            STRATEGY_NAME,
            "rayner_hist_momentum_ema_whipsaw",
            chop_score=chop_score,
        )

    side = "long" if price > ema_now else "short"
    pullback_ok, pullback_meta = pullback_near_ema(
        frame,
        baseline,
        side=side,
        atr_now=atr_now,
        lookback=cfg.pullback_lookback,
        max_distance_atr=cfg.max_pullback_distance_atr,
    )
    if not pullback_ok:
        return hold(
            STRATEGY_NAME,
            "rayner_hist_momentum_no_valid_pullback",
            side_candidate=side,
            **pullback_meta,
        )

    expansion_ok, hist_meta = histogram_expansion(
        histogram,
        side=side,
        lookback=cfg.histogram_lookback,
        min_ratio=cfg.histogram_min_expansion_ratio,
    )
    if not expansion_ok:
        return hold(
            STRATEGY_NAME,
            "rayner_hist_momentum_histogram_not_expanding",
            side_candidate=side,
            **hist_meta,
        )

    candle = candle_metrics(frame)
    confirmation = candle["bullish"] > 0 if side == "long" else candle["bearish"] > 0
    if not confirmation:
        return hold(
            STRATEGY_NAME,
            "rayner_hist_momentum_confirmation_candle_missing",
            side_candidate=side,
        )

    entry_price = price
    stop_price = swing_stop(
        frame.iloc[:-1],
        side,
        cfg.swing_lookback,
        cfg.stop_buffer_atr,
        atr_now,
    )
    if (side == "long" and stop_price >= entry_price) or (
        side == "short" and stop_price <= entry_price
    ):
        return hold(STRATEGY_NAME, "rayner_hist_momentum_invalid_swing_stop")

    target_price = risk_target(entry_price, stop_price, side, cfg.reward_r)
    prior_abs_hist = histogram.iloc[-12:-1].abs().dropna()
    nearest_hist_peak = float(prior_abs_hist.max()) if not prior_abs_hist.empty else abs(float(hist_now))

    return enter(
        STRATEGY_NAME,
        side,
        entry_price,
        stop_price,
        target_price,
        "rayner_hist_momentum_pullback_hist_expansion",
        timeframe_hint="1h",
        source_profile="video_11_rayner_teo",
        config=asdict(cfg),
        ema60=ema_now,
        atr_pct=atr_pct,
        chop_score=chop_score,
        histogram=float(hist_now),
        histogram_peak_reference=nearest_hist_peak,
        exit_observer="histogram_peak_break_or_fixed_rr",
        **pullback_meta,
        **hist_meta,
    )
