from __future__ import annotations

import dataclasses
import inspect
import math
from collections import Counter
from typing import Any, Callable, Mapping

import pandas as pd

VERSION = "STRATEGY11_REGIME_EDGE_ROUTER_V3"


def classify_regime(history: pd.DataFrame) -> str:
    if history is None or len(history) < 60:
        return "WARMUP"
    close = pd.to_numeric(history["close"], errors="coerce")
    high = pd.to_numeric(history["high"], errors="coerce")
    low = pd.to_numeric(history["low"], errors="coerce")
    if close.isna().any() or high.isna().any() or low.isna().any():
        return "INVALID"
    ema20 = close.ewm(span=20, adjust=False).mean()
    ema55 = close.ewm(span=55, adjust=False).mean()
    previous = close.shift(1)
    tr = pd.concat([(high - low).abs(), (high - previous).abs(), (low - previous).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14, min_periods=14).mean()
    atr_pct = float(atr.iloc[-1] / max(float(close.iloc[-1]), 1e-12))
    ratios = (atr / close).dropna().tail(120)
    median_atr_pct = float(ratios.median()) if not ratios.empty else atr_pct
    separation = abs(float(ema20.iloc[-1] - ema55.iloc[-1])) / max(float(atr.iloc[-1]), 1e-12)
    slope20 = float(ema20.iloc[-1] - ema20.iloc[-6]) / max(float(atr.iloc[-1]), 1e-12)
    if median_atr_pct > 0 and atr_pct >= median_atr_pct * 1.5:
        return "HIGH_VOL"
    if median_atr_pct > 0 and atr_pct <= median_atr_pct * 0.65:
        return "LOW_VOL"
    if separation >= 0.75 and slope20 > 0.20:
        return "TREND_UP"
    if separation >= 0.75 and slope20 < -0.20:
        return "TREND_DOWN"
    hour = pd.Timestamp(history.iloc[-1].get("timestamp", pd.Timestamp.now(tz="UTC"))).hour
    return "SESSION_ACTIVE" if hour in {7, 8, 9, 13, 14, 15} else "RANGE"


class ConfigStrategyWrapper:
    def __init__(self, strategy: Callable[..., Mapping[str, Any]], config_class: type[Any], field: str | None = None, mutation_value: Any = None, regime_scope: str | None = None) -> None:
        if not dataclasses.is_dataclass(config_class):
            raise TypeError("CONFIG_CLASS_NOT_DATACLASS")
        self.strategy = strategy
        self.config_class = config_class
        self.base_config = config_class()
        self.field = field
        self.mutation_value = mutation_value
        self.regime_scope = regime_scope
        self.counts: Counter[str] = Counter()
        self.hold_reasons: Counter[str] = Counter()
        self.signature = inspect.signature(strategy)
        if "config" not in self.signature.parameters:
            raise TypeError("STRATEGY_CONFIG_PARAMETER_MISSING")

    def reset(self) -> None:
        self.counts.clear()
        self.hold_reasons.clear()

    def diagnostics(self) -> dict[str, Any]:
        return {"counts": dict(sorted(self.counts.items())), "hold_reasons": dict(self.hold_reasons.most_common(20))}

    def __call__(self, history: pd.DataFrame, state: Mapping[str, Any] | None = None, risk_action: str = "hold") -> dict[str, Any]:
        regime = classify_regime(history)
        use_mutation = self.field is not None and (self.regime_scope is None or self.regime_scope == regime)
        config = dataclasses.replace(self.base_config, **{self.field: self.mutation_value}) if use_mutation else self.base_config
        attempts = (
            lambda: self.strategy(history, state=dict(state or {}), risk_action=risk_action, config=config),
            lambda: self.strategy(history, state=dict(state or {}), config=config),
            lambda: self.strategy(history, risk_action=risk_action, config=config),
            lambda: self.strategy(history, config=config),
        )
        last: Exception | None = None
        for attempt in attempts:
            try:
                value = attempt()
                if not isinstance(value, dict):
                    raise TypeError("STRATEGY_RESULT_NOT_DICT")
                action = str(value.get("action") or "hold").lower()
                side = str(value.get("side") or "none").lower()
                self.counts["calls"] += 1
                self.counts[f"regime:{regime}"] += 1
                self.counts[f"action:{action}"] += 1
                self.counts[f"side:{side}"] += 1
                self.counts["mutation_calls" if use_mutation else "base_calls"] += 1
                if action == "hold":
                    self.hold_reasons[str(value.get("why") or "unknown")] += 1
                return value
            except TypeError as exc:
                last = exc
        raise RuntimeError(f"STRATEGY_CALL_FAILED:{type(last).__name__}:{last}")
