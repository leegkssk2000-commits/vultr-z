from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from backend.strategies._route_a_video_common import (
    atr,
    candle_metrics,
    enter,
    hold,
    prepare_frame,
    risk_target,
    safe_float,
    swing_stop,
)

STRATEGY_NAME = "alligator_trend_pullback"


@dataclass(frozen=True)
class AlligatorTrendConfig:
    jaw_length: int = 13
    jaw_shift: int = 8
    teeth_length: int = 8
    teeth_shift: int = 5
    lips_length: int = 5
    lips_shift: int = 3
    atr_length: int = 14
    min_bars: int = 120
    pullback_lookback: int = 8
    min_width_atr: float = 0.22
    min_slope_atr: float = 0.02
    max_chase_atr: float = 1.25
    swing_lookback: int = 10
    stop_buffer_atr: float = 0.08
    reward_r: float = 2.0


def _smma(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(
        alpha=1.0 / max(int(length), 1),
        adjust=False,
        min_periods=max(int(length), 1),
    ).mean()


def strategy(
    df: pd.DataFrame,
    *,
    state: Optional[Dict[str, Any]] = None,
    risk_action: str = "hold",
    config: Optional[AlligatorTrendConfig] = None,
) -> Dict[str, Any]:
    """Causal Bill Williams Alligator trend/pullback strategy.

    SMMA values are shifted only with already-completed historical values. No
    future candle is referenced. The line spacing and slope veto the sleeping
    alligator/chop regime described in the source video.
    """
    cfg = config or AlligatorTrendConfig()
    frame, blocked = prepare_frame(
        df,
        strategy_name=STRATEGY_NAME,
        min_bars=cfg.min_bars,
        state=state,
        risk_action=risk_action,
    )
    if blocked is not None or frame is None:
        return blocked or hold(STRATEGY_NAME, "alligator_trend_pullback_invalid_input")

    median_price = (frame["high"] + frame["low"]) / 2.0
    jaw = _smma(median_price, cfg.jaw_length).shift(cfg.jaw_shift)
    teeth = _smma(median_price, cfg.teeth_length).shift(cfg.teeth_shift)
    lips = _smma(median_price, cfg.lips_length).shift(cfg.lips_shift)
    atr_series = atr(frame, cfg.atr_length)

    price = safe_float(frame["close"].iloc[-1])
    jaw_now = safe_float(jaw.iloc[-1])
    teeth_now = safe_float(teeth.iloc[-1])
    lips_now = safe_float(lips.iloc[-1])
    atr_now = safe_float(atr_series.iloc[-1])
    jaw_prev = safe_float(jaw.iloc[-4])
    teeth_prev = safe_float(teeth.iloc[-4])
    lips_prev = safe_float(lips.iloc[-4])
    if None in {
        price,
        jaw_now,
        teeth_now,
        lips_now,
        atr_now,
        jaw_prev,
        teeth_prev,
        lips_prev,
    }:
        return hold(STRATEGY_NAME, "alligator_trend_pullback_indicator_nan")

    assert price is not None and jaw_now is not None and teeth_now is not None
    assert lips_now is not None and atr_now is not None
    assert jaw_prev is not None and teeth_prev is not None and lips_prev is not None

    long_stack = lips_now > teeth_now > jaw_now
    short_stack = lips_now < teeth_now < jaw_now
    if not (long_stack or short_stack):
        return hold(STRATEGY_NAME, "alligator_trend_pullback_lines_tangled")

    width_atr = (max(lips_now, teeth_now, jaw_now) - min(lips_now, teeth_now, jaw_now)) / max(atr_now, 1e-12)
    slopes = np.array(
        [
            (lips_now - lips_prev) / max(atr_now, 1e-12),
            (teeth_now - teeth_prev) / max(atr_now, 1e-12),
            (jaw_now - jaw_prev) / max(atr_now, 1e-12),
        ]
    )
    if width_atr < cfg.min_width_atr or float(np.mean(np.abs(slopes))) < cfg.min_slope_atr:
        return hold(
            STRATEGY_NAME,
            "alligator_trend_pullback_sleeping",
            width_atr=width_atr,
            mean_abs_slope_atr=float(np.mean(np.abs(slopes))),
        )

    side = "long" if long_stack else "short"
    recent = frame.iloc[-cfg.pullback_lookback :]
    teeth_recent = teeth.iloc[-cfg.pullback_lookback :]
    lips_recent = lips.iloc[-cfg.pullback_lookback :]
    if side == "long":
        touched = bool(
            (recent["low"].to_numpy() <= teeth_recent.to_numpy()).any()
            or (recent["low"].to_numpy() <= lips_recent.to_numpy()).any()
        )
        reclaimed = price > lips_now
        chase_atr = (price - lips_now) / max(atr_now, 1e-12)
    else:
        touched = bool(
            (recent["high"].to_numpy() >= teeth_recent.to_numpy()).any()
            or (recent["high"].to_numpy() >= lips_recent.to_numpy()).any()
        )
        reclaimed = price < lips_now
        chase_atr = (lips_now - price) / max(atr_now, 1e-12)

    if not touched or not reclaimed or chase_atr > cfg.max_chase_atr:
        return hold(
            STRATEGY_NAME,
            "alligator_trend_pullback_no_reclaim",
            side_candidate=side,
            pullback_touched=touched,
            reclaimed=reclaimed,
            chase_atr=chase_atr,
        )

    candle = candle_metrics(frame)
    confirmation = candle["bullish"] > 0 if side == "long" else candle["bearish"] > 0
    if not confirmation:
        return hold(
            STRATEGY_NAME,
            "alligator_trend_pullback_confirmation_missing",
            side_candidate=side,
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
        return hold(STRATEGY_NAME, "alligator_trend_pullback_invalid_stop")

    target_price = risk_target(price, stop_price, side, cfg.reward_r)
    return enter(
        STRATEGY_NAME,
        side,
        price,
        stop_price,
        target_price,
        "alligator_trend_pullback_reclaim",
        timeframe_hint="15m_to_1h",
        source_profile="video_1_bill_williams_alligator",
        fidelity="causal_public_alligator_core",
        config=asdict(cfg),
        jaw=jaw_now,
        teeth=teeth_now,
        lips=lips_now,
        width_atr=width_atr,
        mean_abs_slope_atr=float(np.mean(np.abs(slopes))),
        chase_atr=chase_atr,
    )
