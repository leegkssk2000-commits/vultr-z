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

STRATEGY_ID = "js_techtrading_supertrend_pullback_authentic"
SOURCE_COMMIT = "69969aeaf271b2f7b5a7632a1bde43069a0cbe26"
SOURCE_BLOB_SHA = "b9a53b75c1af44354fa54d9f919c8e27e0bb8bb5"
SOURCE_LOCAL_SNAPSHOT = "research/external_sources/js_techtrading_supertrend_strategy_basic_v5.pine"


@dataclass(frozen=True)
class JSTechTradingSupertrendPullbackConfig:
    strategy_type: str = "Pullback"
    atr_length: int = 10
    factor: float = 3.0
    ema_enabled: bool = True
    ema_length: int = 200
    rsi_enabled: bool = True
    rsi_length: int = 14
    rsi_buy_level: float = 50.0
    rsi_sell_level: float = 50.0
    trade_direction: str = "Both"
    stop_loss_pct: float = 1.0
    take_profit_pct: float = 1.0
    equity_qty_pct: float = 1.0

    def validate(self) -> None:
        if self.strategy_type not in {"Pullback", "Simple"}:
            raise ValueError("STRATEGY_TYPE_INVALID")
        if self.trade_direction not in {"Long", "Short", "Both"}:
            raise ValueError("TRADE_DIRECTION_INVALID")
        if isinstance(self.atr_length, bool) or int(self.atr_length) < 1:
            raise ValueError("ATR_LENGTH_INVALID")
        if isinstance(self.ema_length, bool) or int(self.ema_length) < 1:
            raise ValueError("EMA_LENGTH_INVALID")
        if isinstance(self.rsi_length, bool) or int(self.rsi_length) < 1:
            raise ValueError("RSI_LENGTH_INVALID")
        for name, value in (
            ("factor", self.factor),
            ("stop_loss_pct", self.stop_loss_pct),
            ("take_profit_pct", self.take_profit_pct),
            ("equity_qty_pct", self.equity_qty_pct),
        ):
            if not math.isfinite(float(value)) or float(value) <= 0:
                raise ValueError(f"{name.upper()}_INVALID")


def _numeric(series: pd.Series) -> pd.Series:
    result = pd.to_numeric(series, errors="coerce").astype("float64")
    values = result.to_numpy(float)
    if not np.isfinite(values).all():
        raise ValueError("SOURCE_NONFINITE")
    return result


def pine_ema(source: pd.Series, length: int) -> pd.Series:
    """Pine ta.ema-compatible recursion seeded from the first finite source value."""
    values = _numeric(source)
    alpha = 2.0 / (float(length) + 1.0)
    output = pd.Series(np.nan, index=values.index, dtype="float64", name="ema")
    previous: Optional[float] = None
    for position, value in enumerate(values.to_numpy(float)):
        if previous is None:
            previous = float(value)
        else:
            previous = alpha * float(value) + (1.0 - alpha) * previous
        output.iloc[position] = previous
    return output


def pine_rma_with_na(source: pd.Series, length: int) -> pd.Series:
    """Pine ta.rma behavior for a series whose initial values can be na."""
    numeric = pd.to_numeric(source, errors="coerce").astype("float64")
    output = pd.Series(np.nan, index=numeric.index, dtype="float64", name="rma")
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
        if not math.isfinite(value):
            output.iloc[position] = previous
            continue
        previous = alpha * value + (1.0 - alpha) * previous
        output.iloc[position] = previous
    return output


def pine_rsi(source: pd.Series, length: int) -> pd.Series:
    values = _numeric(source)
    change = values.diff()
    gain = change.where(change >= 0.0, 0.0)
    loss = (-change).where(change < 0.0, 0.0)
    gain.iloc[0] = np.nan
    loss.iloc[0] = np.nan
    average_gain = pine_rma_with_na(gain, length)
    average_loss = pine_rma_with_na(loss, length)
    result = pd.Series(np.nan, index=values.index, dtype="float64", name="rsi")
    valid = average_gain.notna() & average_loss.notna()
    both_zero = valid & (average_gain == 0.0) & (average_loss == 0.0)
    only_loss_zero = valid & (average_loss == 0.0) & (average_gain > 0.0)
    only_gain_zero = valid & (average_gain == 0.0) & (average_loss > 0.0)
    ordinary = valid & ~(both_zero | only_loss_zero | only_gain_zero)
    result.loc[both_zero] = 50.0
    result.loc[only_loss_zero] = 100.0
    result.loc[only_gain_zero] = 0.0
    rs = average_gain.loc[ordinary] / average_loss.loc[ordinary]
    result.loc[ordinary] = 100.0 - (100.0 / (1.0 + rs))
    return result


def _crossunder(left: pd.Series, right: pd.Series) -> pd.Series:
    return ((left < right) & (left.shift(1) >= right.shift(1))).fillna(False)


def _crossover(left: pd.Series, right: pd.Series) -> pd.Series:
    return ((left > right) & (left.shift(1) <= right.shift(1))).fillna(False)


def compute_source_locked_signals(
    frame: pd.DataFrame,
    config: Optional[JSTechTradingSupertrendPullbackConfig] = None,
) -> pd.DataFrame:
    cfg = config or JSTechTradingSupertrendPullbackConfig()
    cfg.validate()
    required = ("open", "high", "low", "close")
    if frame is None or not isinstance(frame, pd.DataFrame) or frame.empty:
        raise ValueError("OHLC_FRAME_EMPTY")
    if any(column not in frame.columns for column in required):
        raise ValueError("OHLC_COLUMNS_MISSING")

    high = _numeric(frame["high"])
    low = _numeric(frame["low"])
    close = _numeric(frame["close"])
    supertrend = compute_supertrend(
        frame,
        SupertrendFlipAuthenticConfig(
            atr_length=cfg.atr_length,
            factor=cfg.factor,
            control_notional=1.0,
        ),
    )

    uptrend = supertrend["direction"] == 1
    downtrend = supertrend["direction"] == -1
    long_line = supertrend["supertrend_line"].where(uptrend)
    short_line = supertrend["supertrend_line"].where(downtrend)

    # Exact Pine semantics:
    # ta.crossunder(low[1], long) and high > high[1]
    # ta.crossover(high[1], short) and low < low[1]
    pullback_long = _crossunder(low.shift(1), long_line) & (high > high.shift(1)) & uptrend
    pullback_short = _crossover(high.shift(1), short_line) & (low < low.shift(1)) & downtrend

    ema = pine_ema(close, cfg.ema_length)
    rsi = pine_rsi(close, cfg.rsi_length)
    ema_long = (close > ema) if cfg.ema_enabled else pd.Series(True, index=frame.index)
    ema_short = (close < ema) if cfg.ema_enabled else pd.Series(True, index=frame.index)
    rsi_long = (rsi >= cfg.rsi_buy_level) if cfg.rsi_enabled else pd.Series(True, index=frame.index)
    rsi_short = (rsi <= cfg.rsi_sell_level) if cfg.rsi_enabled else pd.Series(True, index=frame.index)

    direction_previous = supertrend["direction"].shift(1)
    simple_long = uptrend & (direction_previous == -1)
    simple_short = downtrend & (direction_previous == 1)
    raw_long = pullback_long if cfg.strategy_type == "Pullback" else simple_long
    raw_short = pullback_short if cfg.strategy_type == "Pullback" else simple_short

    long_allowed = cfg.trade_direction in {"Long", "Both"}
    short_allowed = cfg.trade_direction in {"Short", "Both"}
    entry_long = (raw_long & ema_long & rsi_long & long_allowed).fillna(False)
    entry_short = (raw_short & ema_short & rsi_short & short_allowed).fillna(False)

    return pd.DataFrame(
        {
            "supertrend_line": supertrend["supertrend_line"],
            "direction": supertrend["direction"],
            "ema": ema,
            "rsi": rsi,
            "pullback_long": pullback_long.fillna(False),
            "pullback_short": pullback_short.fillna(False),
            "ema_long": ema_long.fillna(False),
            "ema_short": ema_short.fillna(False),
            "rsi_long": rsi_long.fillna(False),
            "rsi_short": rsi_short.fillna(False),
            "entry_long": entry_long,
            "entry_short": entry_short,
        },
        index=frame.index,
    )
