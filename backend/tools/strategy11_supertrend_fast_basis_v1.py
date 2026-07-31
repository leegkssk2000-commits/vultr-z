from __future__ import annotations

import numpy as np
import pandas as pd


def authentic_supertrend_fast(frame: pd.DataFrame, length: int = 10, multiplier: float = 3.0) -> pd.DataFrame:
    if length < 2:
        raise ValueError("ATR_LENGTH_MIN_2")
    if multiplier <= 0:
        raise ValueError("MULTIPLIER_POSITIVE_REQUIRED")
    high = pd.to_numeric(frame["high"], errors="raise").to_numpy(dtype="float64", copy=True)
    low = pd.to_numeric(frame["low"], errors="raise").to_numpy(dtype="float64", copy=True)
    close = pd.to_numeric(frame["close"], errors="raise").to_numpy(dtype="float64", copy=True)
    size = len(frame)
    tr = high - low
    if size > 1:
        tr[1:] = np.maximum.reduce((tr[1:], np.abs(high[1:] - close[:-1]), np.abs(low[1:] - close[:-1])))
    atr = np.full(size, np.nan, dtype="float64")
    if size < length:
        return pd.DataFrame({
            "atr": atr,
            "final_upper": np.full(size, np.nan),
            "final_lower": np.full(size, np.nan),
            "direction": np.full(size, np.nan),
            "supertrend": np.full(size, np.nan),
        }, index=frame.index)
    start = length - 1
    atr[start] = float(np.mean(tr[:length]))
    for index in range(start + 1, size):
        atr[index] = ((atr[index - 1] * (length - 1)) + tr[index]) / length
    hl2 = (high + low) / 2.0
    basic_upper = hl2 + multiplier * atr
    basic_lower = hl2 - multiplier * atr
    final_upper = np.full(size, np.nan, dtype="float64")
    final_lower = np.full(size, np.nan, dtype="float64")
    direction = np.full(size, np.nan, dtype="float64")
    supertrend = np.full(size, np.nan, dtype="float64")
    final_upper[start] = basic_upper[start]
    final_lower[start] = basic_lower[start]
    direction[start] = 1.0
    supertrend[start] = final_lower[start]
    for index in range(start + 1, size):
        previous_upper = final_upper[index - 1]
        previous_lower = final_lower[index - 1]
        upper = basic_upper[index]
        lower = basic_lower[index]
        final_upper[index] = upper if (upper < previous_upper or close[index - 1] > previous_upper) else previous_upper
        final_lower[index] = lower if (lower > previous_lower or close[index - 1] < previous_lower) else previous_lower
        if supertrend[index - 1] == previous_upper:
            if close[index] <= final_upper[index]:
                direction[index] = -1.0
                supertrend[index] = final_upper[index]
            else:
                direction[index] = 1.0
                supertrend[index] = final_lower[index]
        else:
            if close[index] >= final_lower[index]:
                direction[index] = 1.0
                supertrend[index] = final_lower[index]
            else:
                direction[index] = -1.0
                supertrend[index] = final_upper[index]
    return pd.DataFrame({
        "atr": atr,
        "final_upper": final_upper,
        "final_lower": final_lower,
        "direction": direction,
        "supertrend": supertrend,
    }, index=frame.index)
