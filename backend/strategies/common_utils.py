from __future__ import annotations

from typing import Final

import pandas as pd


_EPSILON: Final[float] = 1e-12


def ema(series: pd.Series, length: int) -> pd.Series:
    """Causal exponential moving average used by canonical Strategy25 modules."""
    if int(length) <= 0:
        raise ValueError("EMA_LENGTH_INVALID")
    return series.astype(float).ewm(span=int(length), adjust=False, min_periods=int(length)).mean()


def atr(frame: pd.DataFrame, length: int) -> pd.Series:
    """Causal true range with the repository rolling-mean ATR convention."""
    if int(length) <= 0:
        raise ValueError("ATR_LENGTH_INVALID")
    required = {"high", "low", "close"}
    if not required.issubset(frame.columns):
        missing = sorted(required.difference(frame.columns))
        raise ValueError(f"ATR_COLUMNS_MISSING:{','.join(missing)}")

    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    close = frame["close"].astype(float)
    previous_close = close.shift(1)
    true_range = pd.concat(
        (
            high - low,
            (high - previous_close).abs(),
            (low - previous_close).abs(),
        ),
        axis=1,
    ).max(axis=1)
    return true_range.rolling(int(length), min_periods=int(length)).mean()


def rsi(series: pd.Series, length: int = 14) -> pd.Series:
    """Causal Wilder RSI with explicit warm-up and stable zero-loss handling."""
    length = int(length)
    if length <= 0:
        raise ValueError("RSI_LENGTH_INVALID")
    values = series.astype(float)
    delta = values.diff()
    gains = delta.clip(lower=0.0)
    losses = -delta.clip(upper=0.0)
    average_gain = gains.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()
    average_loss = losses.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()
    relative_strength = average_gain / average_loss.where(average_loss.abs() > _EPSILON)
    output = 100.0 - (100.0 / (1.0 + relative_strength))
    output = output.where(average_loss.abs() > _EPSILON, 100.0)
    output = output.where(average_gain.abs() > _EPSILON, 0.0)
    both_zero = (average_gain.abs() <= _EPSILON) & (average_loss.abs() <= _EPSILON)
    return output.where(~both_zero, 50.0)


def bollinger(series: pd.Series, length: int = 20, multiplier: float = 2.0) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Causal Bollinger middle, upper, and lower bands."""
    length = int(length)
    multiplier = float(multiplier)
    if length <= 1:
        raise ValueError("BOLLINGER_LENGTH_INVALID")
    if multiplier <= 0.0:
        raise ValueError("BOLLINGER_MULTIPLIER_INVALID")
    values = series.astype(float)
    middle = values.rolling(length, min_periods=length).mean()
    deviation = values.rolling(length, min_periods=length).std(ddof=0)
    upper = middle + multiplier * deviation
    lower = middle - multiplier * deviation
    return middle, upper, lower


def macd(
    series: pd.Series,
    fast_length: int = 12,
    slow_length: int = 26,
    signal_length: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Causal MACD line, signal line, and histogram."""
    fast_length = int(fast_length)
    slow_length = int(slow_length)
    signal_length = int(signal_length)
    if fast_length <= 0 or slow_length <= fast_length or signal_length <= 0:
        raise ValueError("MACD_LENGTH_CONTRACT_INVALID")
    values = series.astype(float)
    fast = values.ewm(span=fast_length, adjust=False, min_periods=fast_length).mean()
    slow = values.ewm(span=slow_length, adjust=False, min_periods=slow_length).mean()
    line = fast - slow
    signal = line.ewm(span=signal_length, adjust=False, min_periods=signal_length).mean()
    histogram = line - signal
    return line, signal, histogram
