from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
import math

import numpy as np
import pandas as pd

from backend.strategies.authentic.supertrend_flip_authentic import (
    DOWN,
    UP,
    SupertrendFlipAuthenticConfig,
    compute_supertrend,
)

STRATEGY_ID = "trading_nerd_mtf_supertrend_video"
CONTRACT_PATH = "research/trading_nerd_mtf_supertrend_video_contract_v1.json"
YOUTUBE_VIDEO_ID = "Yl5WCVMllC4"
TRADINGVIEW_SCRIPT_ID = "cPjnon3O-MTF-Supertrend-Trading-Nerd"


@dataclass(frozen=True)
class TradingNerdMTFSupertrendConfig:
    atr_length: int = 10
    factor: float = 3.0
    lower_timeframe_min: int = 5
    higher_timeframe_min: int = 60
    trade_direction: str = "Both"
    trade_higher_timeframe_flip: bool = False
    use_adx_filter: bool = False
    adx_length: int = 14
    adx_threshold: float = 20.0

    def validate(self) -> None:
        if isinstance(self.atr_length, bool) or int(self.atr_length) < 1:
            raise ValueError("ATR_LENGTH_INVALID")
        if not math.isfinite(float(self.factor)) or float(self.factor) <= 0:
            raise ValueError("SUPERTREND_FACTOR_INVALID")
        if isinstance(self.lower_timeframe_min, bool) or int(self.lower_timeframe_min) < 1:
            raise ValueError("LOWER_TIMEFRAME_INVALID")
        if isinstance(self.higher_timeframe_min, bool) or int(self.higher_timeframe_min) <= int(self.lower_timeframe_min):
            raise ValueError("HIGHER_TIMEFRAME_INVALID")
        if int(self.higher_timeframe_min) % int(self.lower_timeframe_min) != 0:
            raise ValueError("TIMEFRAME_RATIO_NOT_INTEGER")
        if self.trade_direction not in {"Long", "Short", "Both"}:
            raise ValueError("TRADE_DIRECTION_INVALID")
        if isinstance(self.adx_length, bool) or int(self.adx_length) < 1:
            raise ValueError("ADX_LENGTH_INVALID")
        if not math.isfinite(float(self.adx_threshold)) or float(self.adx_threshold) < 0:
            raise ValueError("ADX_THRESHOLD_INVALID")


def _validated_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or not isinstance(frame, pd.DataFrame) or frame.empty:
        raise ValueError("OHLC_FRAME_EMPTY")
    required = ("open", "high", "low", "close")
    if any(column not in frame.columns for column in required):
        raise ValueError("OHLC_COLUMNS_MISSING")
    result = frame.copy()
    for column in required:
        result[column] = pd.to_numeric(result[column], errors="coerce").astype(float)
    if not np.isfinite(result.loc[:, list(required)].to_numpy(float)).all():
        raise ValueError("OHLC_NONFINITE")
    if (result["high"] < result["low"]).any():
        raise ValueError("OHLC_HIGH_BELOW_LOW")
    return result


def _bar_close_ms(frame: pd.DataFrame, timeframe_min: int) -> pd.Series:
    if "bar_close_ts" in frame.columns:
        close_ms = pd.to_numeric(frame["bar_close_ts"], errors="coerce")
    elif "ts_ms" in frame.columns:
        close_ms = pd.to_numeric(frame["ts_ms"], errors="coerce") + int(timeframe_min) * 60_000
    elif isinstance(frame.index, pd.DatetimeIndex):
        close_ms = pd.Series(
            frame.index.astype("int64") // 1_000_000 + int(timeframe_min) * 60_000,
            index=frame.index,
            dtype="int64",
        )
    else:
        raise ValueError("BAR_CLOSE_TIMESTAMP_MISSING")
    if close_ms.isna().any():
        raise ValueError("BAR_CLOSE_TIMESTAMP_NONFINITE")
    return close_ms.astype("int64")


def _wilder_rma_allow_warmup(values: pd.Series, length: int) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce").astype(float)
    output = pd.Series(np.nan, index=numeric.index, dtype="float64")
    finite_positions = [i for i, value in enumerate(numeric.to_numpy(float)) if math.isfinite(value)]
    if len(finite_positions) < length:
        return output
    seed_positions = finite_positions[:length]
    seed_position = seed_positions[-1]
    previous = float(numeric.iloc[seed_positions].mean())
    output.iloc[seed_position] = previous
    alpha = 1.0 / float(length)
    for position in range(seed_position + 1, len(numeric)):
        value = float(numeric.iloc[position])
        if math.isfinite(value):
            previous = alpha * value + (1.0 - alpha) * previous
        output.iloc[position] = previous
    return output


def compute_adx(frame: pd.DataFrame, length: int = 14) -> pd.Series:
    validated = _validated_frame(frame)
    high = validated["high"]
    low = validated["low"]
    close = validated["close"]
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0.0), up_move, 0.0),
        index=validated.index,
        dtype="float64",
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0.0), down_move, 0.0),
        index=validated.index,
        dtype="float64",
    )
    plus_dm.iloc[0] = np.nan
    minus_dm.iloc[0] = np.nan
    previous_close = close.shift(1)
    true_range = pd.concat(
        [high - low, (high - previous_close).abs(), (low - previous_close).abs()],
        axis=1,
    ).max(axis=1, skipna=True)
    true_range.iloc[0] = np.nan
    atr = _wilder_rma_allow_warmup(true_range, length)
    plus = 100.0 * _wilder_rma_allow_warmup(plus_dm, length) / atr
    minus = 100.0 * _wilder_rma_allow_warmup(minus_dm, length) / atr
    denominator = (plus + minus).replace(0.0, np.nan)
    dx = 100.0 * (plus - minus).abs() / denominator
    adx = _wilder_rma_allow_warmup(dx, length)
    adx.name = "adx"
    return adx


def _align_confirmed_higher_timeframe(
    lower_frame: pd.DataFrame,
    higher_frame: pd.DataFrame,
    higher_indicator: pd.DataFrame,
    lower_timeframe_min: int,
    higher_timeframe_min: int,
) -> pd.DataFrame:
    lower_close = _bar_close_ms(lower_frame, lower_timeframe_min)
    higher_close = _bar_close_ms(higher_frame, higher_timeframe_min)
    source = pd.DataFrame(
        {
            "higher_close_ms": higher_close.to_numpy(np.int64),
            "higher_direction": higher_indicator["direction"].to_numpy(float),
            "higher_flip_up": higher_indicator["flip_up"].to_numpy(bool),
            "higher_flip_down": higher_indicator["flip_down"].to_numpy(bool),
            "higher_supertrend_line": higher_indicator["supertrend_line"].to_numpy(float),
        }
    ).sort_values("higher_close_ms")
    target = pd.DataFrame(
        {
            "lower_position": np.arange(len(lower_frame), dtype=np.int64),
            "lower_close_ms": lower_close.to_numpy(np.int64),
        }
    ).sort_values("lower_close_ms")
    aligned = pd.merge_asof(
        target,
        source,
        left_on="lower_close_ms",
        right_on="higher_close_ms",
        direction="backward",
        allow_exact_matches=True,
    ).sort_values("lower_position")
    aligned.index = lower_frame.index
    return aligned


def compute_video_contract_signals(
    lower_frame: pd.DataFrame,
    higher_frame: pd.DataFrame,
    config: Optional[TradingNerdMTFSupertrendConfig] = None,
) -> pd.DataFrame:
    cfg = config or TradingNerdMTFSupertrendConfig()
    cfg.validate()
    lower = _validated_frame(lower_frame)
    higher = _validated_frame(higher_frame)

    indicator_config = SupertrendFlipAuthenticConfig(
        atr_length=cfg.atr_length,
        factor=cfg.factor,
        control_notional=1.0,
    )
    lower_indicator = compute_supertrend(lower, indicator_config)
    higher_indicator = compute_supertrend(higher, indicator_config)
    aligned = _align_confirmed_higher_timeframe(
        lower,
        higher,
        higher_indicator,
        cfg.lower_timeframe_min,
        cfg.higher_timeframe_min,
    )

    higher_bullish = aligned["higher_direction"] == UP
    higher_bearish = aligned["higher_direction"] == DOWN
    base_long = higher_bullish & lower_indicator["flip_up"]
    base_short = higher_bearish & lower_indicator["flip_down"]

    if cfg.trade_higher_timeframe_flip:
        base_long = base_long | (aligned["higher_flip_up"].fillna(False) & (lower_indicator["direction"] == UP))
        base_short = base_short | (aligned["higher_flip_down"].fillna(False) & (lower_indicator["direction"] == DOWN))

    adx = compute_adx(lower, cfg.adx_length)
    adx_pass = (adx >= float(cfg.adx_threshold)).fillna(False) if cfg.use_adx_filter else pd.Series(True, index=lower.index)
    long_allowed = cfg.trade_direction in {"Long", "Both"}
    short_allowed = cfg.trade_direction in {"Short", "Both"}
    entry_long = (base_long & adx_pass & long_allowed).fillna(False)
    entry_short = (base_short & adx_pass & short_allowed).fillna(False)

    return pd.DataFrame(
        {
            "lower_direction": lower_indicator["direction"],
            "lower_flip_up": lower_indicator["flip_up"],
            "lower_flip_down": lower_indicator["flip_down"],
            "lower_supertrend_line": lower_indicator["supertrend_line"],
            "higher_direction_confirmed": aligned["higher_direction"],
            "higher_flip_up_confirmed": aligned["higher_flip_up"].fillna(False),
            "higher_flip_down_confirmed": aligned["higher_flip_down"].fillna(False),
            "higher_supertrend_line_confirmed": aligned["higher_supertrend_line"],
            "adx": adx,
            "adx_pass": adx_pass,
            "entry_long": entry_long,
            "entry_short": entry_short,
            "trailing_stop": lower_indicator["supertrend_line"],
        },
        index=lower.index,
    )
