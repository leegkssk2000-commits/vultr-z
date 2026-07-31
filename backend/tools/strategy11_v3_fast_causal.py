from __future__ import annotations

import dataclasses
import sys
from typing import Any, Mapping

import pandas as pd

from backend.tools.strategy11_regime_edge_router_v3 import ConfigStrategyWrapper as BaseWrapper

VERSION = "STRATEGY11_V3_FAST_CAUSAL"


def _frame_regimes(frame: pd.DataFrame) -> list[str]:
    close = pd.to_numeric(frame["close"], errors="coerce")
    high = pd.to_numeric(frame["high"], errors="coerce")
    low = pd.to_numeric(frame["low"], errors="coerce")
    ema20 = close.ewm(span=20, adjust=False).mean()
    ema55 = close.ewm(span=55, adjust=False).mean()
    previous = close.shift(1)
    tr = pd.concat([(high - low).abs(), (high - previous).abs(), (low - previous).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14, min_periods=14).mean()
    ratios = atr / close
    median_atr = ratios.rolling(120, min_periods=1).median()
    separation = (ema20 - ema55).abs() / atr.clip(lower=1e-12)
    slope20 = (ema20 - ema20.shift(5)) / atr.clip(lower=1e-12)
    timestamps = frame.get("timestamp")
    hours = pd.Series([0] * len(frame), index=frame.index) if timestamps is None else pd.to_datetime(timestamps, utc=True).dt.hour
    invalid_prefix = (close.isna() | high.isna() | low.isna()).cummax()
    result: list[str] = []
    for i in range(len(frame)):
        if i + 1 < 60:
            result.append("WARMUP")
            continue
        if bool(invalid_prefix.iloc[i]):
            result.append("INVALID")
            continue
        price = max(float(close.iloc[i]), 1e-12)
        atr_value = float(atr.iloc[i])
        atr_pct = atr_value / price
        median = float(median_atr.iloc[i])
        sep = float(separation.iloc[i])
        slope = float(slope20.iloc[i])
        if median > 0 and atr_pct >= median * 1.5:
            regime = "HIGH_VOL"
        elif median > 0 and atr_pct <= median * 0.65:
            regime = "LOW_VOL"
        elif sep >= 0.75 and slope > 0.20:
            regime = "TREND_UP"
        elif sep >= 0.75 and slope < -0.20:
            regime = "TREND_DOWN"
        else:
            regime = "SESSION_ACTIVE" if int(hours.iloc[i]) in {7, 8, 9, 13, 14, 15} else "RANGE"
        result.append(regime)
    return result


class FastCausalConfigStrategyWrapper(BaseWrapper):
    """Reuse full-frame causal indicators while preserving prefix decisions."""

    def __init__(self, strategy: Any, config_class: type[Any], field: str | None = None, mutation_value: Any = None, regime_scope: str | None = None) -> None:
        super().__init__(strategy, config_class, field, mutation_value, regime_scope)
        module = sys.modules.get(getattr(strategy, "__module__", ""))
        if module is None:
            raise RuntimeError("FAST_WRAPPER_STRATEGY_MODULE_MISSING")
        self.module = module
        if hasattr(module, "_supertrend") and not hasattr(module, "_v3_original_supertrend"):
            setattr(module, "_v3_original_supertrend", getattr(module, "_supertrend"))
        if hasattr(module, "_ema") and not hasattr(module, "_v3_original_ema"):
            setattr(module, "_v3_original_ema", getattr(module, "_ema"))
        self.original_supertrend = getattr(module, "_v3_original_supertrend", None)
        self.original_ema = getattr(module, "_v3_original_ema", None)
        self.frame_cache: dict[int, dict[str, Any]] = {}
        self.current: dict[str, Any] | None = None
        if self.original_supertrend is not None:
            setattr(module, "_supertrend", self._supertrend_proxy)
        if self.original_ema is not None:
            setattr(module, "_ema", self._ema_proxy)

    def reset(self) -> None:
        super().reset()
        self.current = None

    def prepare_frame(self, frame: pd.DataFrame) -> None:
        key = id(frame)
        cached = self.frame_cache.get(key)
        if cached is None:
            st_lengths = {int(getattr(self.base_config, "st_len", 10))}
            st_multipliers = {float(getattr(self.base_config, "st_mult", 3.0))}
            ema_lengths = {int(getattr(self.base_config, "ema_len", 50))}
            if self.field == "st_len":
                st_lengths.add(int(self.mutation_value))
            if self.field == "st_mult":
                st_multipliers.add(float(self.mutation_value))
            if self.field == "ema_len":
                ema_lengths.add(int(self.mutation_value))
            supertrends: dict[tuple[int, float], pd.DataFrame] = {}
            if self.original_supertrend is not None:
                for length in sorted(st_lengths):
                    for multiplier in sorted(st_multipliers):
                        supertrends[(length, multiplier)] = self.original_supertrend(frame, length, multiplier)
            emas: dict[int, pd.Series] = {}
            if self.original_ema is not None:
                close = pd.to_numeric(frame["close"], errors="raise")
                for length in sorted(ema_lengths):
                    emas[length] = self.original_ema(close, length)
            cached = {"frame": frame, "supertrends": supertrends, "emas": emas, "regimes": _frame_regimes(frame)}
            self.frame_cache[key] = cached
        self.current = cached

    def _prefix_ok(self, value: Any) -> bool:
        if self.current is None:
            return False
        frame = self.current["frame"]
        n = len(value)
        if n <= 0 or n > len(frame):
            return False
        try:
            return float(value["close"].iloc[-1]) == float(frame["close"].iloc[n - 1])
        except Exception:
            return False

    def _supertrend_proxy(self, df: pd.DataFrame, length: int, multiplier: float) -> pd.DataFrame:
        key = (int(length), float(multiplier))
        if self._prefix_ok(df) and key in self.current["supertrends"]:
            output = self.current["supertrends"][key].iloc[: len(df)].copy()
            output.index = df.index
            return output
        return self.original_supertrend(df, length, multiplier)

    def _ema_proxy(self, series: pd.Series, length: int) -> pd.Series:
        if self.current is not None and int(length) in self.current["emas"] and 0 < len(series) <= len(self.current["frame"]):
            frame = self.current["frame"]
            try:
                if float(series.iloc[-1]) == float(frame["close"].iloc[len(series) - 1]):
                    output = self.current["emas"][int(length)].iloc[: len(series)].copy()
                    output.index = series.index
                    return output
            except Exception:
                pass
        return self.original_ema(series, length)

    def __call__(self, history: pd.DataFrame, state: Mapping[str, Any] | None = None, risk_action: str = "hold") -> dict[str, Any]:
        if self.current is None:
            self.prepare_frame(history)
        n = len(history)
        regimes = self.current.get("regimes", []) if self.current else []
        regime = regimes[n - 1] if 0 < n <= len(regimes) else "INVALID"
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


def install_exact_prepare(exact: Any) -> Any:
    original_replay = exact._replay
    if getattr(original_replay, "_v3_fast_prepare", False):
        return exact

    def prepared_replay(frame: pd.DataFrame, features: pd.DataFrame, strategy: Any, *args: Any, **kwargs: Any) -> Any:
        prepare = getattr(strategy, "prepare_frame", None)
        if callable(prepare):
            prepare(frame)
        return original_replay(frame, features, strategy, *args, **kwargs)

    prepared_replay._v3_fast_prepare = True  # type: ignore[attr-defined]
    exact._replay = prepared_replay
    return exact
