from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
import math

import numpy as np
import pandas as pd

from backend.strategies.authentic.supertrend_flip_authentic import (
    SupertrendFlipAuthenticConfig,
    compute_supertrend,
)

STRATEGY_ID = "tradinglab_dema200_supertrend12x3_video_v1"
SOURCE_VIDEO_ID = "g-PLctW8aU0"
SOURCE_CONTRACT_PATH = "research/user_supplied_pullback_video_bundle_v1.json"


@dataclass(frozen=True)
class TradingLabDEMASupertrendConfig:
    dema_length: int = 200
    atr_length: int = 12
    factor: float = 3.0
    trade_direction: str = "Both"
    early_entry_enabled: bool = False
    early_entry_max_bars: int = 0

    def validate(self) -> None:
        if isinstance(self.dema_length, bool) or int(self.dema_length) < 2:
            raise ValueError("DEMA_LENGTH_INVALID")
        if isinstance(self.atr_length, bool) or int(self.atr_length) < 1:
            raise ValueError("ATR_LENGTH_INVALID")
        if not math.isfinite(float(self.factor)) or float(self.factor) <= 0:
            raise ValueError("SUPERTREND_FACTOR_INVALID")
        if self.trade_direction not in {"Long", "Short", "Both"}:
            raise ValueError("TRADE_DIRECTION_INVALID")
        if isinstance(self.early_entry_max_bars, bool) or int(self.early_entry_max_bars) < 0:
            raise ValueError("EARLY_ENTRY_MAX_BARS_INVALID")
        if self.early_entry_enabled and int(self.early_entry_max_bars) < 1:
            raise ValueError("EARLY_ENTRY_WINDOW_REQUIRED")


def _validated_ohlc(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or not isinstance(frame, pd.DataFrame) or frame.empty:
        raise ValueError("OHLC_FRAME_EMPTY")
    required = ("open", "high", "low", "close")
    if any(column not in frame.columns for column in required):
        raise ValueError("OHLC_COLUMNS_MISSING")
    result = frame.copy()
    for column in required:
        result[column] = pd.to_numeric(result[column], errors="coerce").astype(float)
    values = result.loc[:, list(required)].to_numpy(float)
    if not np.isfinite(values).all():
        raise ValueError("OHLC_NONFINITE")
    if (result["high"] < result["low"]).any():
        raise ValueError("OHLC_HIGH_BELOW_LOW")
    if ((result["open"] < result["low"]) | (result["open"] > result["high"])).any():
        raise ValueError("OHLC_OPEN_OUTSIDE_RANGE")
    if ((result["close"] < result["low"]) | (result["close"] > result["high"])).any():
        raise ValueError("OHLC_CLOSE_OUTSIDE_RANGE")
    return result


def compute_dema(close: pd.Series, length: int) -> pd.Series:
    numeric = pd.to_numeric(close, errors="coerce").astype(float)
    if not np.isfinite(numeric.to_numpy(float)).all():
        raise ValueError("DEMA_INPUT_NONFINITE")
    ema1 = numeric.ewm(span=int(length), adjust=False, min_periods=int(length)).mean()
    ema2 = ema1.ewm(span=int(length), adjust=False, min_periods=int(length)).mean()
    result = 2.0 * ema1 - ema2
    result.name = "dema"
    return result


def _recent_aligned_flip(
    flip: pd.Series,
    aligned_state: pd.Series,
    cross: pd.Series,
    max_bars: int,
) -> pd.Series:
    output = pd.Series(False, index=flip.index, dtype=bool)
    age: Optional[int] = None
    for position in range(len(flip)):
        if bool(flip.iloc[position]):
            age = 0
        elif age is not None:
            age += 1
        if age is not None and age <= max_bars and bool(aligned_state.iloc[position]) and bool(cross.iloc[position]):
            output.iloc[position] = True
            age = None
        elif age is not None and age > max_bars:
            age = None
    return output


def compute_video_contract_signals(
    frame: pd.DataFrame,
    config: Optional[TradingLabDEMASupertrendConfig] = None,
) -> pd.DataFrame:
    cfg = config or TradingLabDEMASupertrendConfig()
    cfg.validate()
    validated = _validated_ohlc(frame)
    close = validated["close"]
    dema = compute_dema(close, cfg.dema_length)
    supertrend = compute_supertrend(
        validated,
        SupertrendFlipAuthenticConfig(
            atr_length=cfg.atr_length,
            factor=cfg.factor,
            control_notional=1.0,
        ),
    )

    bullish = supertrend["direction"] == 1
    bearish = supertrend["direction"] == -1
    close_above = close > dema
    close_below = close < dema

    primary_long = supertrend["flip_up"] & close_above
    primary_short = supertrend["flip_down"] & close_below

    cross_above = (close > dema) & (close.shift(1) <= dema.shift(1))
    cross_below = (close < dema) & (close.shift(1) >= dema.shift(1))
    early_long = pd.Series(False, index=validated.index, dtype=bool)
    early_short = pd.Series(False, index=validated.index, dtype=bool)
    if cfg.early_entry_enabled:
        early_long = _recent_aligned_flip(
            supertrend["flip_up"],
            bullish,
            cross_above,
            int(cfg.early_entry_max_bars),
        )
        early_short = _recent_aligned_flip(
            supertrend["flip_down"],
            bearish,
            cross_below,
            int(cfg.early_entry_max_bars),
        )

    long_allowed = cfg.trade_direction in {"Long", "Both"}
    short_allowed = cfg.trade_direction in {"Short", "Both"}
    entry_long = ((primary_long | early_long) & long_allowed).fillna(False)
    entry_short = ((primary_short | early_short) & short_allowed).fillna(False)

    stop_line = supertrend["supertrend_line"].astype(float)
    valid_long_stop = bullish & (stop_line < close)
    valid_short_stop = bearish & (stop_line > close)

    return pd.DataFrame(
        {
            "dema": dema,
            "supertrend_direction": supertrend["direction"],
            "supertrend_line": stop_line,
            "supertrend_flip_up": supertrend["flip_up"],
            "supertrend_flip_down": supertrend["flip_down"],
            "close_above_dema": close_above.fillna(False),
            "close_below_dema": close_below.fillna(False),
            "primary_long": primary_long.fillna(False),
            "primary_short": primary_short.fillna(False),
            "early_long": early_long.fillna(False),
            "early_short": early_short.fillna(False),
            "entry_long": entry_long.astype(bool),
            "entry_short": entry_short.astype(bool),
            "valid_long_stop": valid_long_stop.fillna(False),
            "valid_short_stop": valid_short_stop.fillna(False),
            "trailing_stop": stop_line,
        },
        index=validated.index,
    )
