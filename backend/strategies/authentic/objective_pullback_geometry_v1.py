from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional, Sequence, Tuple
import math

import pandas as pd


GEOMETRY_ID = "objective_pullback_geometry_v1"
AUTHORITY = "RESEARCH_ONLY_NO_EXECUTION"

REQUIRED_OUTPUT_COLUMNS = (
    "structure_long",
    "structure_short",
    "sr_touch",
    "trendline_touch",
    "ma50_touch",
    "counter_trend_break_up",
    "counter_trend_break_down",
)


@dataclass(frozen=True)
class ObjectivePullbackGeometryConfig:
    atr_length: int = 14
    pivot_left: int = 3
    pivot_right: int = 3
    level_memory: int = 6
    touch_tolerance_atr: float = 0.25
    ma_length: int = 50
    ma_kind: str = "SMA"
    counter_window: int = 8
    counter_break_buffer_atr: float = 0.05

    def validate(self) -> None:
        if int(self.atr_length) < 2:
            raise ValueError("ATR_LENGTH_INVALID")
        if int(self.pivot_left) < 1 or int(self.pivot_right) < 1:
            raise ValueError("PIVOT_CONFIRMATION_INVALID")
        if int(self.level_memory) < 2:
            raise ValueError("LEVEL_MEMORY_INVALID")
        if float(self.touch_tolerance_atr) <= 0:
            raise ValueError("TOUCH_TOLERANCE_INVALID")
        if int(self.ma_length) < 2:
            raise ValueError("MA_LENGTH_INVALID")
        if str(self.ma_kind).upper() not in {"SMA", "EMA"}:
            raise ValueError("MA_KIND_INVALID")
        if int(self.counter_window) < 3:
            raise ValueError("COUNTER_WINDOW_INVALID")
        if float(self.counter_break_buffer_atr) < 0:
            raise ValueError("COUNTER_BREAK_BUFFER_INVALID")


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _validated_ohlc(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or not isinstance(frame, pd.DataFrame) or frame.empty:
        raise ValueError("FRAME_EMPTY")
    missing = [column for column in ("open", "high", "low", "close") if column not in frame.columns]
    if missing:
        raise ValueError("OHLC_MISSING:" + ",".join(missing))
    result = frame.copy()
    for column in ("open", "high", "low", "close"):
        result[column] = pd.to_numeric(result[column], errors="coerce").astype(float)
    if not bool(result[["open", "high", "low", "close"]].apply(lambda s: s.map(_finite)).to_numpy().all()):
        raise ValueError("OHLC_NONFINITE")
    if bool((result["high"] < result["low"]).any()):
        raise ValueError("OHLC_HIGH_BELOW_LOW")
    if bool(((result["open"] < result["low"]) | (result["open"] > result["high"])).any()):
        raise ValueError("OHLC_OPEN_OUTSIDE_RANGE")
    if bool(((result["close"] < result["low"]) | (result["close"] > result["high"])).any()):
        raise ValueError("OHLC_CLOSE_OUTSIDE_RANGE")
    return result


def _true_range(frame: pd.DataFrame) -> pd.Series:
    previous_close = frame["close"].shift(1)
    return pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - previous_close).abs(),
            (frame["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1, skipna=True)


def _wilder_rma(values: pd.Series, length: int) -> pd.Series:
    numeric = values.astype(float)
    output = pd.Series(float("nan"), index=numeric.index, dtype="float64")
    if len(numeric) < length:
        return output
    seed_index = length - 1
    seed = float(numeric.iloc[:length].mean())
    output.iloc[seed_index] = seed
    previous = seed
    for position in range(seed_index + 1, len(numeric)):
        previous = ((previous * (length - 1)) + float(numeric.iloc[position])) / length
        output.iloc[position] = previous
    return output


def _moving_average(values: pd.Series, length: int, kind: str) -> pd.Series:
    if kind.upper() == "EMA":
        return values.astype(float).ewm(span=length, adjust=False, min_periods=length).mean()
    return values.astype(float).rolling(length, min_periods=length).mean()


def _strict_local_max(values: Sequence[float], center: int, left: int, right: int) -> bool:
    current = float(values[center])
    peers = [float(values[i]) for i in range(center - left, center + right + 1) if i != center]
    return bool(peers) and all(current > peer for peer in peers)


def _strict_local_min(values: Sequence[float], center: int, left: int, right: int) -> bool:
    current = float(values[center])
    peers = [float(values[i]) for i in range(center - left, center + right + 1) if i != center]
    return bool(peers) and all(current < peer for peer in peers)


def _project_line(first: Tuple[int, float], second: Tuple[int, float], position: int) -> float:
    x1, y1 = first
    x2, y2 = second
    if x2 <= x1:
        return float("nan")
    slope = (float(y2) - float(y1)) / float(x2 - x1)
    return float(y2) + slope * float(position - x2)


def _line_touch(low: float, high: float, line: float, tolerance: float) -> bool:
    if not _finite(line):
        return False
    return low <= line + tolerance and high >= line - tolerance


def _near_level(low: float, high: float, close: float, levels: Sequence[float], tolerance: float) -> bool:
    for level in levels:
        if low <= level + tolerance and high >= level - tolerance:
            return True
        if abs(close - level) <= tolerance:
            return True
    return False


def _linear_projection(values: Sequence[float]) -> Tuple[float, float]:
    n = len(values)
    if n < 2:
        return float("nan"), float("nan")
    x_mean = (n - 1) / 2.0
    y_mean = sum(float(value) for value in values) / n
    denominator = sum((i - x_mean) ** 2 for i in range(n))
    if denominator <= 0:
        return 0.0, float(values[-1])
    slope = sum((i - x_mean) * (float(values[i]) - y_mean) for i in range(n)) / denominator
    intercept = y_mean - slope * x_mean
    return float(slope), float(intercept + slope * n)


def compute_objective_geometry(
    frame: pd.DataFrame,
    config: Optional[ObjectivePullbackGeometryConfig] = None,
) -> pd.DataFrame:
    cfg = config or ObjectivePullbackGeometryConfig()
    cfg.validate()
    validated = _validated_ohlc(frame)
    n = len(validated)

    high_values = validated["high"].astype(float).tolist()
    low_values = validated["low"].astype(float).tolist()
    close_values = validated["close"].astype(float).tolist()
    atr = _wilder_rma(_true_range(validated), cfg.atr_length)
    ma50 = _moving_average(validated["close"], cfg.ma_length, cfg.ma_kind)

    structure_long = [False] * n
    structure_short = [False] * n
    sr_touch = [False] * n
    trendline_touch = [False] * n
    ma50_touch = [False] * n
    counter_break_up = [False] * n
    counter_break_down = [False] * n
    confirmed_high_value = [float("nan")] * n
    confirmed_low_value = [float("nan")] * n
    trendline_support = [float("nan")] * n
    trendline_resistance = [float("nan")] * n

    pivot_highs: List[Tuple[int, float]] = []
    pivot_lows: List[Tuple[int, float]] = []

    for i in range(n):
        candidate = i - cfg.pivot_right
        if candidate >= cfg.pivot_left:
            if _strict_local_max(high_values, candidate, cfg.pivot_left, cfg.pivot_right):
                pivot_highs.append((candidate, high_values[candidate]))
                confirmed_high_value[i] = high_values[candidate]
            if _strict_local_min(low_values, candidate, cfg.pivot_left, cfg.pivot_right):
                pivot_lows.append((candidate, low_values[candidate]))
                confirmed_low_value[i] = low_values[candidate]

        if len(pivot_highs) >= 2 and len(pivot_lows) >= 2:
            structure_long[i] = pivot_highs[-1][1] > pivot_highs[-2][1] and pivot_lows[-1][1] > pivot_lows[-2][1]
            structure_short[i] = pivot_highs[-1][1] < pivot_highs[-2][1] and pivot_lows[-1][1] < pivot_lows[-2][1]

        atr_now = float(atr.iloc[i]) if _finite(atr.iloc[i]) else float("nan")
        tolerance = atr_now * cfg.touch_tolerance_atr if _finite(atr_now) else float("nan")
        if not _finite(tolerance):
            continue

        recent_levels = [value for _, value in (pivot_highs + pivot_lows)[-cfg.level_memory:]]
        sr_touch[i] = _near_level(low_values[i], high_values[i], close_values[i], recent_levels, tolerance)

        if len(pivot_lows) >= 2:
            trendline_support[i] = _project_line(pivot_lows[-2], pivot_lows[-1], i)
        if len(pivot_highs) >= 2:
            trendline_resistance[i] = _project_line(pivot_highs[-2], pivot_highs[-1], i)
        trendline_touch[i] = (
            _line_touch(low_values[i], high_values[i], trendline_support[i], tolerance)
            or _line_touch(low_values[i], high_values[i], trendline_resistance[i], tolerance)
        )

        ma_value = float(ma50.iloc[i]) if _finite(ma50.iloc[i]) else float("nan")
        ma50_touch[i] = _line_touch(low_values[i], high_values[i], ma_value, tolerance)

        if i >= cfg.counter_window:
            prior_highs = high_values[i - cfg.counter_window : i]
            prior_lows = low_values[i - cfg.counter_window : i]
            high_slope, high_projection = _linear_projection(prior_highs)
            low_slope, low_projection = _linear_projection(prior_lows)
            previous_close = close_values[i - 1]
            high_previous_projection = high_projection - high_slope
            low_previous_projection = low_projection - low_slope
            buffer = atr_now * cfg.counter_break_buffer_atr
            counter_break_up[i] = (
                structure_long[i]
                and high_slope < 0.0
                and previous_close <= high_previous_projection + buffer
                and close_values[i] > high_projection + buffer
            )
            counter_break_down[i] = (
                structure_short[i]
                and low_slope > 0.0
                and previous_close >= low_previous_projection - buffer
                and close_values[i] < low_projection - buffer
            )

    return pd.DataFrame(
        {
            "structure_long": pd.Series(structure_long, index=validated.index, dtype=bool),
            "structure_short": pd.Series(structure_short, index=validated.index, dtype=bool),
            "sr_touch": pd.Series(sr_touch, index=validated.index, dtype=bool),
            "trendline_touch": pd.Series(trendline_touch, index=validated.index, dtype=bool),
            "ma50_touch": pd.Series(ma50_touch, index=validated.index, dtype=bool),
            "counter_trend_break_up": pd.Series(counter_break_up, index=validated.index, dtype=bool),
            "counter_trend_break_down": pd.Series(counter_break_down, index=validated.index, dtype=bool),
            "geometry_atr": atr,
            "geometry_ma50": ma50,
            "confirmed_pivot_high": pd.Series(confirmed_high_value, index=validated.index, dtype="float64"),
            "confirmed_pivot_low": pd.Series(confirmed_low_value, index=validated.index, dtype="float64"),
            "trendline_support": pd.Series(trendline_support, index=validated.index, dtype="float64"),
            "trendline_resistance": pd.Series(trendline_resistance, index=validated.index, dtype="float64"),
        },
        index=validated.index,
    )


def attach_objective_geometry(
    frame: pd.DataFrame,
    config: Optional[ObjectivePullbackGeometryConfig] = None,
) -> pd.DataFrame:
    validated = _validated_ohlc(frame)
    geometry = compute_objective_geometry(validated, config)
    result = validated.copy()
    for column in geometry.columns:
        result[column] = geometry[column]
    return result


__all__ = [
    "AUTHORITY",
    "GEOMETRY_ID",
    "ObjectivePullbackGeometryConfig",
    "REQUIRED_OUTPUT_COLUMNS",
    "attach_objective_geometry",
    "compute_objective_geometry",
]
