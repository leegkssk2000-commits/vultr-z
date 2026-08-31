from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import numpy as np
import pandas as pd

REQUIRED_COLUMNS = {"open", "high", "low", "close", "volume"}


def hold(strategy_name: str, reason: str, **extra: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "action": "hold",
        "side": "",
        "entry": None,
        "sl": None,
        "tp": None,
        "why": reason,
        "strategy": strategy_name,
        "family": "trend_pullback",
    }
    payload.update(extra)
    return payload


def enter(
    strategy_name: str,
    side: str,
    entry_price: float,
    stop_price: float,
    target_price: float,
    reason: str,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "action": "enter",
        "side": side,
        "entry": float(entry_price),
        "sl": float(stop_price),
        "tp": float(target_price),
        "why": reason,
        "strategy": strategy_name,
        "family": "trend_pullback",
    }
    payload.update(extra)
    return payload


def position_side(state: Optional[Dict[str, Any]]) -> str:
    if not isinstance(state, dict):
        return ""
    direct = state.get("position_side") or state.get("side")
    if direct:
        return str(direct).lower()
    nested = state.get("position")
    if isinstance(nested, dict):
        value = nested.get("position_side") or nested.get("side")
        if value:
            return str(value).lower()
    return ""


def prepare_frame(
    df: pd.DataFrame,
    *,
    strategy_name: str,
    min_bars: int,
    state: Optional[Dict[str, Any]],
    risk_action: str,
) -> Tuple[Optional[pd.DataFrame], Optional[Dict[str, Any]]]:
    if not isinstance(df, pd.DataFrame) or df.empty:
        return None, hold(strategy_name, f"{strategy_name}_invalid_input")
    if not REQUIRED_COLUMNS.issubset(df.columns):
        return None, hold(strategy_name, f"{strategy_name}_invalid_input")
    if str(risk_action or "hold").lower() not in {"", "hold", "none"}:
        return None, hold(
            strategy_name,
            f"{strategy_name}_risk_blocked",
            risk_action=str(risk_action),
        )
    existing = position_side(state)
    if existing in {"long", "short"}:
        return None, hold(
            strategy_name,
            f"{strategy_name}_position_already_open",
            position_side=existing,
        )
    if len(df) < int(min_bars):
        return None, hold(
            strategy_name,
            f"{strategy_name}_not_enough_bars",
            bars=int(len(df)),
            required=int(min_bars),
        )

    frame = df.copy()
    for column in REQUIRED_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if frame[list(REQUIRED_COLUMNS)].isna().any().any():
        return None, hold(strategy_name, f"{strategy_name}_indicator_nan")
    prices = frame[["open", "high", "low", "close"]]
    if (prices <= 0).any().any() or (frame["high"] < frame["low"]).any():
        return None, hold(strategy_name, f"{strategy_name}_invalid_price")
    if (frame["volume"] < 0).any():
        return None, hold(strategy_name, f"{strategy_name}_invalid_volume")
    return frame.reset_index(drop=True), None


def ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(
        span=max(int(length), 1),
        adjust=False,
        min_periods=max(int(length), 1),
    ).mean()


def macd(
    close: pd.Series,
    fast: int,
    slow: int,
    signal: int,
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    line = ema(close, fast) - ema(close, slow)
    signal_line = ema(line, signal)
    histogram = line - signal_line
    return line, signal_line, histogram


def atr(frame: pd.DataFrame, length: int = 14) -> pd.Series:
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


def adx(frame: pd.DataFrame, length: int = 14) -> pd.Series:
    high = frame["high"]
    low = frame["low"]
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0.0),
        index=frame.index,
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0),
        index=frame.index,
    )
    tr = atr(frame, 1)
    tr_smoothed = tr.ewm(
        alpha=1.0 / max(int(length), 1),
        adjust=False,
        min_periods=max(int(length), 1),
    ).mean()
    plus_di = 100.0 * plus_dm.ewm(
        alpha=1.0 / max(int(length), 1),
        adjust=False,
        min_periods=max(int(length), 1),
    ).mean() / tr_smoothed.replace(0, np.nan)
    minus_di = 100.0 * minus_dm.ewm(
        alpha=1.0 / max(int(length), 1),
        adjust=False,
        min_periods=max(int(length), 1),
    ).mean() / tr_smoothed.replace(0, np.nan)
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(
        alpha=1.0 / max(int(length), 1),
        adjust=False,
        min_periods=max(int(length), 1),
    ).mean()


def safe_float(value: Any) -> Optional[float]:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if np.isfinite(result) else None


def swing_stop(
    frame: pd.DataFrame,
    side: str,
    lookback: int,
    buffer_atr: float,
    atr_now: float,
) -> float:
    window = frame.iloc[-max(int(lookback), 2) :]
    if side == "long":
        return float(window["low"].min() - float(buffer_atr) * atr_now)
    return float(window["high"].max() + float(buffer_atr) * atr_now)


def risk_target(entry_price: float, stop_price: float, side: str, rr: float) -> float:
    risk = abs(float(entry_price) - float(stop_price))
    if side == "long":
        return float(entry_price + risk * float(rr))
    return float(entry_price - risk * float(rr))


def candle_metrics(frame: pd.DataFrame) -> Dict[str, float]:
    row = frame.iloc[-1]
    open_price = float(row["open"])
    high = float(row["high"])
    low = float(row["low"])
    close = float(row["close"])
    span = max(high - low, 1e-12)
    return {
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "body": abs(close - open_price),
        "range": span,
        "close_location": (close - low) / span,
        "bullish": float(close > open_price),
        "bearish": float(close < open_price),
    }


def histogram_expansion(
    histogram: pd.Series,
    *,
    side: str,
    lookback: int,
    min_ratio: float,
) -> Tuple[bool, Dict[str, float]]:
    now = safe_float(histogram.iloc[-1])
    previous = safe_float(histogram.iloc[-2])
    history = histogram.iloc[-max(int(lookback), 3) - 1 : -1].dropna()
    if now is None or previous is None or history.empty:
        return False, {"hist_now": float("nan")}
    reference = float(history.abs().median())
    reference = max(reference, 1e-12)
    ratio = abs(now) / reference
    color_ok = now > 0 if side == "long" else now < 0
    growing = abs(now) > abs(previous)
    crossed = previous <= 0 < now if side == "long" else previous >= 0 > now
    valid = color_ok and growing and ratio >= float(min_ratio) and (crossed or abs(now) >= abs(previous) * 1.05)
    return valid, {
        "hist_now": now,
        "hist_previous": previous,
        "hist_reference": reference,
        "hist_expansion_ratio": ratio,
        "hist_crossed_zero": float(crossed),
    }


def pullback_near_ema(
    frame: pd.DataFrame,
    ema_series: pd.Series,
    *,
    side: str,
    atr_now: float,
    lookback: int,
    max_distance_atr: float,
) -> Tuple[bool, Dict[str, float]]:
    recent = frame.iloc[-max(int(lookback), 2) :]
    ema_recent = ema_series.iloc[-max(int(lookback), 2) :]
    close_now = float(frame["close"].iloc[-1])
    ema_now = float(ema_series.iloc[-1])
    distance = abs(close_now - ema_now) / max(float(atr_now), 1e-12)
    if side == "long":
        touched = bool((recent["low"].to_numpy() <= ema_recent.to_numpy()).any())
        reclaimed = close_now > ema_now
    else:
        touched = bool((recent["high"].to_numpy() >= ema_recent.to_numpy()).any())
        reclaimed = close_now < ema_now
    valid = touched and reclaimed and distance <= float(max_distance_atr)
    return valid, {
        "ema_distance_atr": distance,
        "pullback_touched": float(touched),
        "pullback_reclaimed": float(reclaimed),
    }


def trend_chop_score(close: pd.Series, baseline: pd.Series, lookback: int) -> float:
    window = close.iloc[-max(int(lookback), 5) :]
    base = baseline.iloc[-max(int(lookback), 5) :]
    if len(window) < 5:
        return 1.0
    relation = np.sign(window.to_numpy() - base.to_numpy())
    flips = int(np.sum(relation[1:] != relation[:-1]))
    return float(flips / max(len(relation) - 1, 1))
