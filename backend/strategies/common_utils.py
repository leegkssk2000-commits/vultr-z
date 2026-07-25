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
    """Causal true-range input with the repository's rolling-mean ATR convention."""
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
    result = true_range.rolling(int(length), min_periods=int(length)).mean()
    return result.where(result.abs() > _EPSILON, result)
