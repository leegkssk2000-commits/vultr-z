"""Research-only feature and strategy-policy SSOT for ZEL intraday studies.

This module has no runtime, registry, Shadow, Paper, Live, execution or order
authority.  It owns closed-bar features and emits immutable DecisionIntent
objects.  Execution adapters may consume an intent but may not alter its
strategy economics.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from math import isfinite
from statistics import fmean
from typing import Literal, Sequence

Side = Literal["long", "short", "hold"]
FEATURE_SCHEMA_VERSION = "zel.feature.momentum.v1"
STRATEGY_POLICY_VERSION = "zel.strategy.momentum.v1"


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
        if self.ts <= 0 or self.volume < 0 or not all(isfinite(v) for v in values):
            raise ValueError("invalid OHLCV")
        if self.low > self.high or self.low > min(self.open, self.close) or self.high < max(self.open, self.close):
            raise ValueError("invalid OHLC envelope")


@dataclass(frozen=True)
class FeatureVector:
    feature_schema_version: str
    signal_ts: int
    atr: float
    directional_efficiency: float
    regime_return: float
    breakout_reference: float
    breakout_distance_atr: float
    expansion_atr: float
    relative_volume: float


@dataclass(frozen=True)
class StrategyConfig:
    regime_lookback: int = 24
    breakout_lookback: int = 20
    directional_efficiency_min: float = 0.35
    breakout_buffer_atr: float = 0.0
    expansion_atr_min: float = 0.8
    relative_volume_min: float = 1.3
    stop_atr_multiple: float = 1.1
    target_r: float = 1.6
    max_hold_bars: int = 12
    expected_move_to_cost_min: float = 2.0
    quality_cutoff: float = 0.0

    def validate(self) -> None:
        if self.regime_lookback < 2 or self.breakout_lookback < 2:
            raise ValueError("invalid lookback")
        for value in (
            self.directional_efficiency_min,
            self.breakout_buffer_atr,
            self.expansion_atr_min,
            self.relative_volume_min,
            self.stop_atr_multiple,
            self.target_r,
            self.expected_move_to_cost_min,
            self.quality_cutoff,
        ):
            if not isfinite(value) or value < 0:
                raise ValueError("invalid strategy parameter")
        if self.max_hold_bars <= 0:
            raise ValueError("invalid max_hold_bars")


@dataclass(frozen=True)
class DecisionIntent:
    strategy_policy_version: str
    feature_schema_version: str
    symbol: str
    side: Side
    signal_ts: int
    reason: str
    entry_policy: str
    entry_reference: float | None
    invalidation_price: float | None
    planned_risk: float | None
    target_price: float | None
    target_r: float | None
    max_hold_bars: int | None
    expected_move_pct: float | None
    all_in_cost_pct: float
    expected_move_to_cost: float | None
    quality_score: float | None
    config_sha256: str

    def sha256(self) -> str:
        raw = json.dumps(asdict(self), sort_keys=True, separators=(",", ":")).encode()
        return sha256(raw).hexdigest()


def _validate_series(bars: Sequence[Bar]) -> None:
    previous = -1
    for bar in bars:
        bar.validate()
        if bar.ts <= previous:
            raise ValueError("timestamps not strictly increasing")
        previous = bar.ts


def true_ranges(bars: Sequence[Bar]) -> tuple[float, ...]:
    _validate_series(bars)
    values: list[float] = []
    for index, bar in enumerate(bars):
        previous_close = bars[index - 1].close if index else bar.close
        values.append(max(bar.high - bar.low, abs(bar.high - previous_close), abs(bar.low - previous_close)))
    return tuple(values)


def atr(bars: Sequence[Bar], period: int = 14) -> float:
    if period <= 0 or len(bars) < period + 1:
        raise ValueError("insufficient bars for ATR")
    return fmean(true_ranges(bars)[-period:])


def directional_efficiency(bars: Sequence[Bar]) -> float:
    _validate_series(bars)
    if len(bars) < 2:
        raise ValueError("insufficient bars for directional efficiency")
    net = abs(bars[-1].close - bars[0].close)
    path = sum(abs(bars[i].close - bars[i - 1].close) for i in range(1, len(bars)))
    return net / path if path > 0 else 0.0


def compute_features(regime_15m: Sequence[Bar], setup_5m: Sequence[Bar], config: StrategyConfig) -> FeatureVector:
    config.validate()
    _validate_series(regime_15m)
    _validate_series(setup_5m)
    if len(regime_15m) < config.regime_lookback or len(setup_5m) < max(config.breakout_lookback + 1, 15):
        raise ValueError("insufficient closed bars")
    regime = regime_15m[-config.regime_lookback:]
    confirm = setup_5m[-1]
    history = setup_5m[-(config.breakout_lookback + 1):-1]
    current_atr = atr(setup_5m, 14)
    volume_reference = fmean(bar.volume for bar in history)
    breakout_reference = max(bar.high for bar in history)
    return FeatureVector(
        feature_schema_version=FEATURE_SCHEMA_VERSION,
        signal_ts=confirm.ts,
        atr=current_atr,
        directional_efficiency=directional_efficiency(regime),
        regime_return=regime[-1].close / regime[0].close - 1.0,
        breakout_reference=breakout_reference,
        breakout_distance_atr=(confirm.close - breakout_reference) / current_atr if current_atr > 0 else 0.0,
        expansion_atr=max(confirm.close - confirm.open, 0.0) / current_atr if current_atr > 0 else 0.0,
        relative_volume=confirm.volume / volume_reference if volume_reference > 0 else 0.0,
    )


def _config_sha(config: StrategyConfig) -> str:
    raw = json.dumps(asdict(config), sort_keys=True, separators=(",", ":")).encode()
    return sha256(raw).hexdigest()


def decide_momentum_long(
    symbol: str,
    regime_15m: Sequence[Bar],
    setup_5m: Sequence[Bar],
    config: StrategyConfig,
    all_in_cost_pct: float,
) -> DecisionIntent:
    if not symbol or not isfinite(all_in_cost_pct) or all_in_cost_pct <= 0:
        raise ValueError("invalid symbol or all-in cost")
    config.validate()
    features = compute_features(regime_15m, setup_5m, config)
    confirm = setup_5m[-1]
    config_sha = _config_sha(config)

    def hold(reason: str) -> DecisionIntent:
        return DecisionIntent(
            STRATEGY_POLICY_VERSION, FEATURE_SCHEMA_VERSION, symbol, "hold", confirm.ts, reason,
            "NEXT_ELIGIBLE_BAR", None, None, None, None, None, None, None,
            all_in_cost_pct, None, None, config_sha,
        )

    if features.regime_return <= 0 or features.directional_efficiency < config.directional_efficiency_min:
        return hold("REGIME_NOT_DIRECTIONAL_UP")
    if features.breakout_distance_atr <= config.breakout_buffer_atr:
        return hold("BREAKOUT_NOT_CONFIRMED")
    if features.expansion_atr < config.expansion_atr_min:
        return hold("EXPANSION_TOO_SMALL")
    if features.relative_volume < config.relative_volume_min:
        return hold("RELATIVE_VOLUME_TOO_LOW")

    entry_reference = confirm.close
    structural_stop = min(bar.low for bar in setup_5m[-4:])
    atr_stop = entry_reference - config.stop_atr_multiple * features.atr
    invalidation = max(structural_stop, atr_stop)
    planned_risk = entry_reference - invalidation
    if planned_risk <= 0:
        return hold("NON_POSITIVE_PLANNED_RISK")
    target_price = entry_reference + config.target_r * planned_risk
    expected_move_pct = (target_price / entry_reference - 1.0) * 100.0
    expected_move_to_cost = expected_move_pct / all_in_cost_pct
    if expected_move_to_cost < config.expected_move_to_cost_min:
        return hold("EXPECTED_MOVE_DOES_NOT_CLEAR_COST")

    # One owner only: strategy policy owns quality and cutoff.
    quality_score = expected_move_to_cost * features.relative_volume
    if quality_score < config.quality_cutoff:
        return hold("QUALITY_BELOW_STRATEGY_CUTOFF")

    return DecisionIntent(
        STRATEGY_POLICY_VERSION, FEATURE_SCHEMA_VERSION, symbol, "long", confirm.ts,
        "PASS_MOMENTUM_LONG", "NEXT_ELIGIBLE_BAR", entry_reference, invalidation,
        planned_risk, target_price, config.target_r, config.max_hold_bars,
        expected_move_pct, all_in_cost_pct, expected_move_to_cost, quality_score,
        config_sha,
    )


__all__ = [
    "Bar", "FeatureVector", "StrategyConfig", "DecisionIntent", "true_ranges", "atr",
    "directional_efficiency", "compute_features", "decide_momentum_long",
    "FEATURE_SCHEMA_VERSION", "STRATEGY_POLICY_VERSION",
]
