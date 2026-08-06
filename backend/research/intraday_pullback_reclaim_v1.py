"""Research-only pullback/reclaim candidate for ZEL Scalp reset.

This module is deliberately isolated from canonical strategy/runtime registries. It
uses closed OHLCV bars only and emits a deterministic research signal plus a
fully explicit risk plan. No order, Paper, Shadow, or Live authority exists.
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
    impulse_atr_multiple: float
    pullback_fraction: float
    reclaim_confirmation: Literal["close", "close_plus_range"]
    stop_atr_multiple: float
    target_r: float
    max_hold_bars: int
    expected_move_to_cost_min: float

    def validate(self) -> None:
        if self.regime_lookback not in (12, 24, 48):
            raise ValueError("regime_lookback outside sealed bounds")
        if self.directional_efficiency_min not in (0.20, 0.35, 0.50):
            raise ValueError("directional efficiency outside sealed bounds")
        if self.impulse_atr_multiple not in (0.8, 1.2, 1.6):
            raise ValueError("impulse ATR outside sealed bounds")
        if self.pullback_fraction not in (0.25, 0.40, 0.55):
            raise ValueError("pullback fraction outside sealed bounds")
        if self.reclaim_confirmation not in ("close", "close_plus_range"):
            raise ValueError("unsupported reclaim confirmation")
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


def _validate_series(bars: Iterable[Bar]) -> tuple[Bar, ...]:
    series = tuple(bars)
    previous_ts = -1
    for bar in series:
        bar.validate()
        if bar.ts <= previous_ts:
            raise ValueError("timestamps not strictly increasing")
        previous_ts = bar.ts
    return series


def decide_long(
    regime_15m: Iterable[Bar],
    setup_5m: Iterable[Bar],
    config: Config,
    all_in_cost_pct: float,
) -> Decision:
    """Evaluate a long-only generation-1 signal using closed bars.

    The final setup bar is the reclaim-confirmation bar. Execution is explicitly
    deferred to the next eligible bar by the replay adapter; this function never
    uses the next bar or any future MFE/MAE information.
    """
    config.validate()
    regime = _validate_series(regime_15m)
    setup = _validate_series(setup_5m)
    if all_in_cost_pct <= 0 or not isfinite(all_in_cost_pct):
        raise ValueError("invalid all-in cost")
    if len(regime) < max(config.regime_lookback, 15) or len(setup) < 18:
        return Decision("hold", "INSUFFICIENT_CLOSED_BARS")

    regime_window = regime[-config.regime_lookback :]
    efficiency = _directional_efficiency(regime_window)
    regime_up = regime_window[-1].close > regime_window[0].close
    if not regime_up or efficiency < config.directional_efficiency_min:
        return Decision("hold", "REGIME_NOT_DIRECTIONAL_UP")

    atr = _atr(setup, 14)
    if atr <= 0:
        return Decision("hold", "NON_POSITIVE_ATR")

    # Search only the closed pre-confirmation setup window. The impulse is the
    # strongest prior rise; no future bar participates in its construction.
    pre = setup[-17:-1]
    impulse_low_idx = min(range(len(pre) - 2), key=lambda i: pre[i].low)
    subsequent = pre[impulse_low_idx + 1 :]
    if len(subsequent) < 3:
        return Decision("hold", "NO_COMPLETE_IMPULSE_PULLBACK")
    impulse_high_rel = max(range(len(subsequent)), key=lambda i: subsequent[i].high)
    impulse_high_idx = impulse_low_idx + 1 + impulse_high_rel
    impulse_low = pre[impulse_low_idx].low
    impulse_high = pre[impulse_high_idx].high
    impulse = impulse_high - impulse_low
    if impulse < config.impulse_atr_multiple * atr:
        return Decision("hold", "IMPULSE_TOO_SMALL")

    after_peak = pre[impulse_high_idx + 1 :]
    if not after_peak:
        return Decision("hold", "NO_PULLBACK_AFTER_IMPULSE")
    pullback_low = min(bar.low for bar in after_peak)
    depth = (impulse_high - pullback_low) / impulse
    if depth <= 0 or depth > config.pullback_fraction:
        return Decision("hold", "PULLBACK_DEPTH_OUTSIDE_BOUND")

    reclaim_reference = max(bar.high for bar in after_peak[:-1] or after_peak)
    confirm = setup[-1]
    reclaimed = confirm.close > reclaim_reference
    if config.reclaim_confirmation == "close_plus_range":
        reclaimed = reclaimed and (confirm.close - confirm.open) >= 0.25 * atr
    if not reclaimed:
        return Decision("hold", "RECLAIM_NOT_CONFIRMED")

    entry_reference = confirm.close
    structural_stop = pullback_low
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
        )

    return Decision(
        "long",
        "PASS_PULLBACK_RECLAIM_LONG_NEXT_BAR_ONLY",
        entry_reference=entry_reference,
        stop_price=stop_price,
        target_price=target_price,
        max_hold_bars=config.max_hold_bars,
        expected_move_pct=expected_move_pct,
        all_in_cost_pct=all_in_cost_pct,
        expected_move_to_cost=ratio,
    )


__all__ = ["Bar", "Config", "Decision", "decide_long"]
