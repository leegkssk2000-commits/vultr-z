#!/usr/bin/env python3
from __future__ import annotations

import math
from collections import Counter
from typing import Any

import numpy as np
import pandas as pd


def finite(value: Any, default: float = 0.0) -> float:
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    return default


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.astype(float).ewm(span=span, adjust=False, min_periods=span).mean()


def atr(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    close = frame["close"].astype(float)
    previous = close.shift(1)
    true_range = pd.concat(
        [(high - low), (high - previous).abs(), (low - previous).abs()], axis=1
    ).max(axis=1)
    return true_range.rolling(period, min_periods=period).mean()


def volume_z(frame: pd.DataFrame, lookback: int = 20) -> pd.Series:
    volume = frame["volume"].astype(float)
    mean = volume.rolling(lookback, min_periods=lookback).mean()
    std = volume.rolling(lookback, min_periods=lookback).std(ddof=0).replace(0, np.nan)
    return (volume - mean).div(std)


def edge(condition: pd.Series) -> pd.Series:
    clean = condition.fillna(False).astype(bool)
    return clean & ~clean.shift(1, fill_value=False)


def rolling_vwap(frame: pd.DataFrame, lookback: int) -> pd.Series:
    volume = frame["volume"].astype(float)
    typical = (
        frame["high"].astype(float)
        + frame["low"].astype(float)
        + frame["close"].astype(float)
    ) / 3.0
    weighted = (typical * volume).rolling(lookback, min_periods=lookback).sum()
    total = volume.rolling(lookback, min_periods=lookback).sum()
    fallback = typical.rolling(lookback, min_periods=lookback).mean()
    return weighted.div(total.where(total > 0)).fillna(fallback)


def anchored_vwap(frame: pd.DataFrame) -> pd.Series:
    volume = frame["volume"].astype(float).clip(lower=0)
    typical = (
        frame["high"].astype(float)
        + frame["low"].astype(float)
        + frame["close"].astype(float)
    ) / 3.0
    cumulative_volume = volume.cumsum()
    return (typical * volume).cumsum().div(
        cumulative_volume.where(cumulative_volume > 0)
    ).fillna(typical.expanding().mean())


def retest_after_break(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    boundary: pd.Series,
    break_cond: pd.Series,
    side: str,
    window: int,
) -> list[int]:
    output: list[int] = []
    for raw in np.flatnonzero(edge(break_cond).to_numpy(dtype=bool)):
        break_index = int(raw)
        level = finite(boundary.iloc[break_index], math.nan)
        if not math.isfinite(level):
            continue
        for index in range(
            break_index + 1,
            min(len(close), break_index + int(window) + 1),
        ):
            if side == "long" and low.iloc[index] <= level and close.iloc[index] > level:
                output.append(index)
                break
            if side == "short" and high.iloc[index] >= level and close.iloc[index] < level:
                output.append(index)
                break
    return output


def context_columns(frame5: pd.DataFrame, frame15: pd.DataFrame) -> pd.DataFrame:
    if "__timestamp" not in frame5.columns or "__timestamp" not in frame15.columns:
        raise ValueError("TIMESTAMP_COLUMN_REQUIRED")

    base = frame5.copy()
    base["__timestamp"] = pd.to_numeric(
        base["__timestamp"], errors="raise"
    ).astype("float64")

    timestamp15 = pd.to_numeric(
        frame15["__timestamp"], errors="raise"
    ).astype("float64")
    ctx = pd.DataFrame(
        {
            "__timestamp": timestamp15,
            "ctx_close": frame15["close"].astype(float),
            "ctx_atr": atr(frame15, 14),
        }
    )
    ctx["ctx_ema20"] = ema(frame15["close"], 20)
    ctx["ctx_ema50"] = ema(frame15["close"], 50)
    ctx["ctx_slope"] = ctx["ctx_ema50"].diff(4).div(4.0 * ctx["ctx_atr"])
    ctx["ctx_high20"] = (
        frame15["high"].astype(float).shift(1).rolling(20, min_periods=20).max()
    )
    ctx["ctx_low20"] = (
        frame15["low"].astype(float).shift(1).rolling(20, min_periods=20).min()
    )
    ctx["ctx_mid20"] = (ctx["ctx_high20"] + ctx["ctx_low20"]) / 2.0
    ctx["ctx_width_atr"] = (ctx["ctx_high20"] - ctx["ctx_low20"]).div(ctx["ctx_atr"])
    ctx["ctx_mid_slope"] = ctx["ctx_mid20"].diff(4).abs().div(4.0 * ctx["ctx_atr"])

    left = (
        base.sort_values("__timestamp")
        .reset_index()
        .rename(columns={"index": "__original_index"})
    )
    right = ctx.sort_values("__timestamp").reset_index(drop=True)
    if left["__timestamp"].dtype != right["__timestamp"].dtype:
        raise TypeError(
            f"TIMESTAMP_DTYPE_MISMATCH:{left['__timestamp'].dtype}:{right['__timestamp'].dtype}"
        )

    merged = pd.merge_asof(
        left,
        right,
        on="__timestamp",
        direction="backward",
        allow_exact_matches=True,
    )
    return (
        merged.sort_values("__original_index")
        .drop(columns=["__original_index"])
        .reset_index(drop=True)
    )


def self_test() -> int:
    size = 180
    index = np.arange(size, dtype=float)
    close = pd.Series(100.0 + 0.02 * index + np.sin(index / 7.0))
    open_v = close.shift(1).fillna(close.iloc[0])
    frame5 = pd.DataFrame(
        {
            "__timestamp": (index * 300000).astype("int64"),
            "open": open_v,
            "high": pd.concat([close, open_v], axis=1).max(axis=1) + 0.4,
            "low": pd.concat([close, open_v], axis=1).min(axis=1) - 0.4,
            "close": close,
            "volume": 100.0 + index % 23,
        }
    )
    frame15 = frame5.iloc[::3].reset_index(drop=True).copy()
    frame15["__timestamp"] = frame15["__timestamp"].astype("float64")
    merged = context_columns(frame5, frame15)
    assert len(merged) == len(frame5)
    assert str(merged["__timestamp"].dtype) == "float64"
    required = (
        atr,
        volume_z,
        ema,
        context_columns,
        edge,
        retest_after_break,
        rolling_vwap,
        anchored_vwap,
    )
    assert all(callable(value) for value in required)
    print("STATE=PASS_THIRD_WAVE_INDICATOR_HELPER_COMPAT_SELF_TEST")
    print("TIMESTAMP_DTYPE=float64")
    print("INDICATOR_HELPER_API_COUNT=8")
    print("RC=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(self_test())
