"""Research-only momentum breakout/continuation candidate for ZEL Scalp reset.

This module is isolated from canonical strategy/runtime registries. It consumes
closed OHLCV bars only and emits a deterministic next-bar research decision.
No Shadow, Paper, Live, execution, or order authority exists.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from statistics import fmean
from typing import Iterable, Literal, Sequence

Side = Literal["long", "short", "hold"]


@dataclass(frozen=True)
class Bar:
    ts: int
    open: float
    high: float
    low: float
    close: float
    volume: float

    def validate(self) -> None:
        values = (self.open, self.high, self.low, self.close, self.volume)
        if not all(isfinite(v) for v in values):
            raise ValueError("non-finite OHLCV")
        if self.ts <= 0 or self.volume < 0:
            raise ValueError("invalid timestamp/volume")
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close):
            raise ValueError("invalid OHLC envelope")
        if self.low > self.high:
            raise ValueError("low above high")


@dataclass(frozen=True)
class Config:
    regime_lookback: int
    directional_efficiency_min: float
    breakout_lookback: int
    breakout_buffer_atr: float
    expansion_atr_multiple: float
    relative_volume_min: float
    stop_atr_multiple: float
    target_r: float
    max_hold_bars: int
    expected_move_to_cost_min: float

    def validate(self) -> None:
        if self.regime_lookback not in (12, 24, 48):
            raise ValueError("regime_lookback outside sealed bounds")
        if self.directional_efficiency_min not in (0.20, 0.35, 0.50):
            raise ValueError("directional efficiency outside sealed bounds")
        if self.breakout_lookback not in (12, 24, 36):
            raise ValueError("breakout_lookback outside sealed bounds")
        if self.breakout_buffer_atr not in (0.0, 0.10, 0.20):
            raise ValueError("breakout buffer outside sealed bounds")
        if self.expansion_atr_multiple not in (0.8, 1.2, 1.6):
            raise ValueError("expansion ATR outside sealed bounds")
        if self.relative_volume_min not in (1.0, 1.3, 1.6):
            raise ValueError("relative volume outside sealed bounds")
        if self.stop_atr_multiple not in (0.8, 1.1, 1.4):
            raise ValueError("stop ATR outside sealed bounds")
        if self.target_r not in (1.2, 1.6, 2.0):
            raise ValueError("target R outside sealed bounds")
        if self.max_hold_bars not in (6, 12, 18):
            raise ValueError("hold bars outside sealed bounds")
        if self.expected_move_to_cost_min not in (2.0, 3.0, 4.0):
            raise ValueError("cost multiple outside sealed bounds")


@dataclass(frozen=True)
class Decision:
    action: Side
    reason: str
    entry_reference: float | None = None
    stop_price: float | None = None
    target_price: float | None = None
    max_hold_bars: int | None = None
    expected_move_pct: float | None = None
    all_in_cost_pct: float | None = None
    expected_move_to_cost: float | None = None
    breakout_reference: float | None = None
    relative_volume: float | None = None


def _validate_series(bars: Iterable[Bar]) -> tuple[Bar, ...]:
    series = tuple(bars)
    previous_ts = -1
    for bar in series:
        bar.validate()
        if bar.ts <= previous_ts:
            raise ValueError("timestamps not strictly increasing")
        previous_ts = bar.ts
    return series


def _true_ranges(bars: Sequence[Bar]) -> list[float]:
    out: list[float] = []
    for i, bar in enumerate(bars):
        previous_close = bars[i - 1].close if i else bar.close
        out.append(max(bar.high - bar.low, abs(bar.high - previous_close), abs(bar.low - previous_close)))
    return out


def _atr(bars: Sequence[Bar], period: int = 14) -> float:
    if len(bars) < period + 1:
        raise ValueError("insufficient bars for ATR")
    return fmean(_true_ranges(bars[-period:]))


def _directional_efficiency(bars: Sequence[Bar]) -> float:
    if len(bars) < 2:
        return 0.0
    net = abs(bars[-1].close - bars[0].close)
    path = sum(abs(bars[i].close - bars[i - 1].close) for i in range(1, len(bars)))
    return net / path if path > 0 else 0.0


def decide_long(
    regime_15m: Iterable[Bar],
    setup_5m: Iterable[Bar],
    config: Config,
    all_in_cost_pct: float,
) -> Decision:
    """Evaluate a long breakout signal using closed bars only.

    The last setup bar is the breakout confirmation bar. Any fill is delegated to
    the replay adapter on the next eligible 3m/5m bar.
    """
    config.validate()
    regime = _validate_series(regime_15m)
    setup = _validate_series(setup_5m)
    if all_in_cost_pct <= 0 or not isfinite(all_in_cost_pct):
        raise ValueError("invalid all-in cost")
    required_setup = max(config.breakout_lookback + 2, 22)
    if len(regime) < max(config.regime_lookback, 15) or len(setup) < required_setup:
        return Decision("hold", "INSUFFICIENT_CLOSED_BARS")

    regime_window = regime[-config.regime_lookback :]
    efficiency = _directional_efficiency(regime_window)
    if regime_window[-1].close <= regime_window[0].close or efficiency < config.directional_efficiency_min:
        return Decision("hold", "REGIME_NOT_DIRECTIONAL_UP")

    atr = _atr(setup, 14)
    if atr <= 0:
        return Decision("hold", "NON_POSITIVE_ATR")

    confirm = setup[-1]
    history = setup[-(config.breakout_lookback + 1) : -1]
    breakout_reference = max(bar.high for bar in history)
    threshold = breakout_reference + config.breakout_buffer_atr * atr
    if confirm.close <= threshold:
        return Decision("hold", "BREAKOUT_NOT_CONFIRMED", breakout_reference=breakout_reference)

    body = max(confirm.close - confirm.open, 0.0)
    if body < config.expansion_atr_multiple * atr:
        return Decision("hold", "EXPANSION_TOO_SMALL", breakout_reference=breakout_reference)

    volume_reference = fmean(bar.volume for bar in history)
    relative_volume = confirm.volume / volume_reference if volume_reference > 0 else 0.0
    if relative_volume < config.relative_volume_min:
        return Decision(
            "hold",
            "RELATIVE_VOLUME_TOO_LOW",
            breakout_reference=breakout_reference,
            relative_volume=relative_volume,
        )

    entry_reference = confirm.close
    structural_stop = min(bar.low for bar in setup[-4:])
    atr_stop = entry_reference - config.stop_atr_multiple * atr
    stop_price = max(structural_stop, atr_stop)
    risk = entry_reference - stop_price
    if risk <= 0:
        return Decision("hold", "NON_POSITIVE_PLANNED_RISK")

    target_price = entry_reference + config.target_r * risk
    expected_move_pct = (target_price - entry_reference) / entry_reference * 100.0
    ratio = expected_move_pct / all_in_cost_pct
    if ratio < config.expected_move_to_cost_min:
        return Decision(
            "hold",
            "EXPECTED_MOVE_DOES_NOT_CLEAR_COST",
            expected_move_pct=expected_move_pct,
            all_in_cost_pct=all_in_cost_pct,
            expected_move_to_cost=ratio,
            breakout_reference=breakout_reference,
            relative_volume=relative_volume,
        )

    return Decision(
        "long",
        "PASS_MOMENTUM_BREAKOUT_CONTINUATION_LONG_NEXT_BAR_ONLY",
        entry_reference=entry_reference,
        stop_price=stop_price,
        target_price=target_price,
        max_hold_bars=config.max_hold_bars,
        expected_move_pct=expected_move_pct,
        all_in_cost_pct=all_in_cost_pct,
        expected_move_to_cost=ratio,
        breakout_reference=breakout_reference,
        relative_volume=relative_volume,
    )


__all__ = ["Bar", "Config", "Decision", "decide_long"]
