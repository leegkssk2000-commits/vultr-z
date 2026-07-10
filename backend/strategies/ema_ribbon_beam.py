from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class EmaRibbonBeamConfig:
    ema_fast_len: int = 8
    ema_mid_len: int = 21
    ema_slow_len: int = 55
    atr_len: int = 14
    min_bars: int = 120

    min_atr_pct: float = 0.12
    max_atr_pct: float = 5.50

    slope_lookback: int = 3
    min_fast_slope_atr: float = 0.08
    min_mid_slope_atr: float = 0.03

    compression_lookback: int = 40
    compression_recent_bars: int = 8
    compression_quantile: float = 0.35
    min_expansion_ratio: float = 1.15
    min_ribbon_width_atr: float = 0.15
    max_ribbon_width_atr: float = 1.60

    reclaim_buffer_atr: float = 0.05
    max_chase_dist_atr: float = 1.20

    beam_body_atr: float = 0.65
    beam_range_atr: float = 0.95
    beam_close_location_min: float = 0.68

    stop_atr_mult: float = 1.35
    structural_lookback: int = 8
    structural_buffer_atr: float = 0.10
    base_rr: float = 2.20
    beam_rr: float = 2.80

    long_base_size: float = 0.50
    short_base_size: float = 0.35
    beam_bonus_long: float = 0.15
    beam_bonus_short: float = 0.10


_REQUIRED_COLUMNS = {"open", "high", "low", "close", "volume"}


def _hold(reason: str, **extra: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "action": "hold",
        "side": "",
        "entry": None,
        "sl": None,
        "tp": None,
        "why": reason,
        "strategy": "ema_ribbon_beam",
        "family": "trend_expansion",
    }
    payload.update(extra)
    return payload


def _position_side(state: Optional[Dict[str, Any]]) -> str:
    if not isinstance(state, dict):
        return ""

    direct = state.get("position_side") or state.get("side")
    if direct:
        return str(direct).lower()

    position = state.get("position")
    if isinstance(position, dict):
        nested = position.get("side") or position.get("position_side")
        if nested:
            return str(nested).lower()

    return ""


def _atr(frame: pd.DataFrame, length: int) -> pd.Series:
    previous_close = frame["close"].shift(1)
    true_range = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - previous_close).abs(),
            (frame["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    return true_range.ewm(
        alpha=1.0 / max(int(length), 1),
        adjust=False,
        min_periods=max(int(length), 1),
    ).mean()


def _safe_float(value: Any) -> Optional[float]:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None

    if not np.isfinite(parsed):
        return None

    return parsed


def strategy(
    df: pd.DataFrame,
    *,
    state: Optional[Dict[str, Any]] = None,
    risk_action: str = "hold",
    config: Optional[EmaRibbonBeamConfig] = None,
) -> Dict[str, Any]:
    """
    Entry-only EMA Ribbon/Beam strategy.

    The strategy uses only completed/current rows supplied by the caller:
    no look-ahead, no mutation, no registry/order side effects, and no
    scale-in. It emits native ATR/structure-based SL and RR-based TP.
    """
    cfg = config or EmaRibbonBeamConfig()

    if not isinstance(df, pd.DataFrame) or df.empty:
        return _hold("ema_ribbon_beam_invalid_input")

    if not _REQUIRED_COLUMNS.issubset(df.columns):
        return _hold("ema_ribbon_beam_invalid_input")

    if str(risk_action or "hold").lower() not in {"", "hold", "none"}:
        return _hold(
            "ema_ribbon_beam_risk_blocked",
            risk_action=str(risk_action),
        )

    existing_side = _position_side(state)
    if existing_side in {"long", "short"}:
        return _hold(
            "ema_ribbon_beam_position_already_open",
            position_side=existing_side,
        )

    minimum = max(
        cfg.min_bars,
        cfg.ema_slow_len + cfg.slope_lookback + 5,
        cfg.compression_lookback + cfg.compression_recent_bars + 5,
        cfg.atr_len + 5,
    )
    if len(df) < minimum:
        return _hold(
            "ema_ribbon_beam_not_enough_bars",
            bars=len(df),
            required=minimum,
        )

    frame = df.copy()
    for column in _REQUIRED_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    if frame[list(_REQUIRED_COLUMNS)].isna().any().any():
        return _hold("ema_ribbon_beam_indicator_nan")

    if (
        (frame[["open", "high", "low", "close"]] <= 0).any().any()
        or (frame["high"] < frame["low"]).any()
    ):
        return _hold("ema_ribbon_beam_invalid_price")

    close = frame["close"]
    ema_fast = close.ewm(
        span=cfg.ema_fast_len,
        adjust=False,
        min_periods=cfg.ema_fast_len,
    ).mean()
    ema_mid = close.ewm(
        span=cfg.ema_mid_len,
        adjust=False,
        min_periods=cfg.ema_mid_len,
    ).mean()
    ema_slow = close.ewm(
        span=cfg.ema_slow_len,
        adjust=False,
        min_periods=cfg.ema_slow_len,
    ).mean()
    atr = _atr(frame, cfg.atr_len)

    price = _safe_float(close.iloc[-1])
    atr_now = _safe_float(atr.iloc[-1])
    fast_now = _safe_float(ema_fast.iloc[-1])
    mid_now = _safe_float(ema_mid.iloc[-1])
    slow_now = _safe_float(ema_slow.iloc[-1])

    if None in {price, atr_now, fast_now, mid_now, slow_now}:
        return _hold("ema_ribbon_beam_indicator_nan")

    assert price is not None
    assert atr_now is not None
    assert fast_now is not None
    assert mid_now is not None
    assert slow_now is not None

    if min(price, atr_now, fast_now, mid_now, slow_now) <= 0:
        return _hold("ema_ribbon_beam_indicator_nan")

    atr_pct = atr_now / price * 100.0
    if not cfg.min_atr_pct <= atr_pct <= cfg.max_atr_pct:
        return _hold(
            "ema_ribbon_beam_volatility_out_of_range",
            atr_pct=atr_pct,
        )

    ribbon_top = pd.concat([ema_fast, ema_mid, ema_slow], axis=1).max(axis=1)
    ribbon_bottom = pd.concat([ema_fast, ema_mid, ema_slow], axis=1).min(axis=1)
    ribbon_width_atr = (ribbon_top - ribbon_bottom) / atr.replace(0, np.nan)

    width_now = _safe_float(ribbon_width_atr.iloc[-1])
    if width_now is None:
        return _hold("ema_ribbon_beam_indicator_nan")

    if not cfg.min_ribbon_width_atr <= width_now <= cfg.max_ribbon_width_atr:
        return _hold(
            "ema_ribbon_beam_ribbon_width_out_of_range",
            ribbon_width_atr=width_now,
        )

    lookback = cfg.slope_lookback
    fast_then = _safe_float(ema_fast.iloc[-1 - lookback])
    mid_then = _safe_float(ema_mid.iloc[-1 - lookback])
    if fast_then is None or mid_then is None:
        return _hold("ema_ribbon_beam_indicator_nan")

    fast_slope_atr = (fast_now - fast_then) / atr_now
    mid_slope_atr = (mid_now - mid_then) / atr_now

    trend_long = (
        fast_now > mid_now > slow_now
        and fast_slope_atr >= cfg.min_fast_slope_atr
        and mid_slope_atr >= cfg.min_mid_slope_atr
    )
    trend_short = (
        fast_now < mid_now < slow_now
        and fast_slope_atr <= -cfg.min_fast_slope_atr
        and mid_slope_atr <= -cfg.min_mid_slope_atr
    )

    if not (trend_long or trend_short):
        return _hold(
            "ema_ribbon_beam_trend_not_aligned",
            fast_slope_atr=fast_slope_atr,
            mid_slope_atr=mid_slope_atr,
        )

    history = ribbon_width_atr.iloc[
        -(cfg.compression_lookback + cfg.compression_recent_bars) : -1
    ].dropna()

    if len(history) < cfg.compression_lookback:
        return _hold("ema_ribbon_beam_indicator_nan")

    compression_threshold = float(
        history.iloc[-cfg.compression_lookback :].quantile(
            cfg.compression_quantile
        )
    )
    recent_width = ribbon_width_atr.iloc[
        -(cfg.compression_recent_bars + 1) : -1
    ].dropna()

    compressed_recently = (
        not recent_width.empty
        and float(recent_width.min()) <= compression_threshold
    )

    prior_width = ribbon_width_atr.iloc[-4:-1].dropna()
    prior_mean = float(prior_width.mean()) if not prior_width.empty else np.nan
    expansion_ratio = (
        width_now / prior_mean
        if np.isfinite(prior_mean) and prior_mean > 0
        else np.nan
    )

    if not compressed_recently:
        return _hold(
            "ema_ribbon_beam_no_recent_compression",
            compression_threshold=compression_threshold,
            ribbon_width_atr=width_now,
        )

    if not np.isfinite(expansion_ratio) or expansion_ratio < cfg.min_expansion_ratio:
        return _hold(
            "ema_ribbon_beam_expansion_too_weak",
            expansion_ratio=expansion_ratio,
        )

    current = frame.iloc[-1]
    previous = frame.iloc[-2]

    open_now = float(current["open"])
    high_now = float(current["high"])
    low_now = float(current["low"])
    close_now = float(current["close"])
    previous_close = float(previous["close"])

    candle_range = max(high_now - low_now, 1e-12)
    body = abs(close_now - open_now)
    close_location = (close_now - low_now) / candle_range

    top_now = float(ribbon_top.iloc[-1])
    bottom_now = float(ribbon_bottom.iloc[-1])
    top_prev = float(ribbon_top.iloc[-2])
    bottom_prev = float(ribbon_bottom.iloc[-2])

    long_reclaim = (
        previous_close <= top_prev + cfg.reclaim_buffer_atr * atr_now
        and low_now <= top_now + cfg.reclaim_buffer_atr * atr_now
        and close_now > top_now + cfg.reclaim_buffer_atr * atr_now
    )
    short_reclaim = (
        previous_close >= bottom_prev - cfg.reclaim_buffer_atr * atr_now
        and high_now >= bottom_now - cfg.reclaim_buffer_atr * atr_now
        and close_now < bottom_now - cfg.reclaim_buffer_atr * atr_now
    )

    beam_long = (
        close_now > open_now
        and body / atr_now >= cfg.beam_body_atr
        and candle_range / atr_now >= cfg.beam_range_atr
        and close_location >= cfg.beam_close_location_min
    )
    beam_short = (
        close_now < open_now
        and body / atr_now >= cfg.beam_body_atr
        and candle_range / atr_now >= cfg.beam_range_atr
        and close_location <= 1.0 - cfg.beam_close_location_min
    )

    long_setup = trend_long and (long_reclaim or beam_long)
    short_setup = trend_short and (short_reclaim or beam_short)

    if not (long_setup or short_setup):
        return _hold(
            "ema_ribbon_beam_no_reclaim_or_beam",
            long_reclaim=long_reclaim,
            short_reclaim=short_reclaim,
            beam_long=beam_long,
            beam_short=beam_short,
        )

    if long_setup:
        chase_dist_atr = max(0.0, (close_now - top_now) / atr_now)
        if chase_dist_atr > cfg.max_chase_dist_atr:
            return _hold(
                "ema_ribbon_beam_late_chase_block",
                side="long",
                chase_dist_atr=chase_dist_atr,
            )

        recent_low = float(
            frame["low"].iloc[-cfg.structural_lookback :].min()
        )
        structural_sl = min(recent_low, slow_now) - (
            cfg.structural_buffer_atr * atr_now
        )
        atr_sl = close_now - cfg.stop_atr_mult * atr_now
        sl = max(structural_sl, atr_sl)
        sl = min(sl, close_now - 0.10 * atr_now)

        risk = close_now - sl
        if risk <= 0:
            return _hold("ema_ribbon_beam_invalid_risk")

        beam = bool(beam_long)
        rr = cfg.beam_rr if beam else cfg.base_rr
        tp = close_now + risk * rr
        size = min(
            1.0,
            cfg.long_base_size + (cfg.beam_bonus_long if beam else 0.0),
        )
        reason = (
            "ema_ribbon_beam_long_beam"
            if beam
            else "ema_ribbon_beam_long_reclaim"
        )
        side = "long"

    else:
        chase_dist_atr = max(0.0, (bottom_now - close_now) / atr_now)
        if chase_dist_atr > cfg.max_chase_dist_atr:
            return _hold(
                "ema_ribbon_beam_late_chase_block",
                side="short",
                chase_dist_atr=chase_dist_atr,
            )

        recent_high = float(
            frame["high"].iloc[-cfg.structural_lookback :].max()
        )
        structural_sl = max(recent_high, slow_now) + (
            cfg.structural_buffer_atr * atr_now
        )
        atr_sl = close_now + cfg.stop_atr_mult * atr_now
        sl = min(structural_sl, atr_sl)
        sl = max(sl, close_now + 0.10 * atr_now)

        risk = sl - close_now
        if risk <= 0:
            return _hold("ema_ribbon_beam_invalid_risk")

        beam = bool(beam_short)
        rr = cfg.beam_rr if beam else cfg.base_rr
        tp = close_now - risk * rr
        size = min(
            1.0,
            cfg.short_base_size + (cfg.beam_bonus_short if beam else 0.0),
        )
        reason = (
            "ema_ribbon_beam_short_beam"
            if beam
            else "ema_ribbon_beam_short_reclaim"
        )
        side = "short"

    return {
        "action": "enter",
        "side": side,
        "entry": float(close_now),
        "sl": float(sl),
        "tp": float(tp),
        "why": reason,
        "strategy": "ema_ribbon_beam",
        "family": "trend_expansion",
        "beam": beam,
        "rr": float(rr),
        "size": float(size),
        "risk_pct": float(abs(close_now - sl) / close_now * 100.0),
        "atr_pct": float(atr_pct),
        "ribbon_width_atr": float(width_now),
        "expansion_ratio": float(expansion_ratio),
        "fast_slope_atr": float(fast_slope_atr),
        "mid_slope_atr": float(mid_slope_atr),
        "config": asdict(cfg),
    }


__all__ = ["EmaRibbonBeamConfig", "strategy"]
