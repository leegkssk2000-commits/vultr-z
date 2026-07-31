from __future__ import annotations

import copy
import dataclasses
import json
import sys
from typing import Any, Mapping

import pandas as pd

from backend.tools.strategy11_regime_edge_router_v3 import (
    ConfigStrategyWrapper as BaseWrapper,
    classify_regime,
)

VERSION = "STRATEGY11_V3_ROLLING_CAUSAL_CACHE"


class FastCausalConfigStrategyWrapper(BaseWrapper):
    """Cache exact rolling-history computations without changing decisions."""

    def __init__(
        self,
        strategy: Any,
        config_class: type[Any],
        field: str | None = None,
        mutation_value: Any = None,
        regime_scope: str | None = None,
    ) -> None:
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
        self.current_frame_id: int | None = None
        self.supertrend_cache: dict[tuple[Any, ...], pd.DataFrame] = {}
        self.ema_cache: dict[tuple[Any, ...], pd.Series] = {}
        self.regime_cache: dict[tuple[Any, ...], str] = {}
        self.decision_cache: dict[tuple[Any, ...], dict[str, Any]] = {}
        self.cache_hits = {"supertrend": 0, "ema": 0, "regime": 0, "decision": 0}
        if self.original_supertrend is not None:
            setattr(module, "_supertrend", self._supertrend_proxy)
        if self.original_ema is not None:
            setattr(module, "_ema", self._ema_proxy)

    def reset(self) -> None:
        super().reset()
        self.current_frame_id = None

    def prepare_frame(self, frame: pd.DataFrame) -> None:
        self.current_frame_id = id(frame)

    def _window_key(self, value: pd.DataFrame | pd.Series) -> tuple[Any, ...]:
        if self.current_frame_id is None:
            raise RuntimeError("FAST_WRAPPER_FRAME_NOT_PREPARED")
        if len(value) <= 0:
            return (self.current_frame_id, 0, None, None)
        index = value.index
        return (self.current_frame_id, len(value), repr(index[0]), repr(index[-1]))

    def _supertrend_proxy(self, df: pd.DataFrame, length: int, multiplier: float) -> pd.DataFrame:
        key = (*self._window_key(df), int(length), float(multiplier))
        cached = self.supertrend_cache.get(key)
        if cached is None:
            cached = self.original_supertrend(df, length, multiplier).copy(deep=True)
            self.supertrend_cache[key] = cached
        else:
            self.cache_hits["supertrend"] += 1
        output = cached.copy(deep=True)
        output.index = df.index
        return output

    def _ema_proxy(self, series: pd.Series, length: int) -> pd.Series:
        key = (*self._window_key(series), int(length))
        cached = self.ema_cache.get(key)
        if cached is None:
            cached = self.original_ema(series, length).copy(deep=True)
            self.ema_cache[key] = cached
        else:
            self.cache_hits["ema"] += 1
        output = cached.copy(deep=True)
        output.index = series.index
        return output

    def _regime(self, history: pd.DataFrame) -> str:
        key = self._window_key(history)
        cached = self.regime_cache.get(key)
        if cached is None:
            cached = classify_regime(history)
            self.regime_cache[key] = cached
        else:
            self.cache_hits["regime"] += 1
        return cached

    @staticmethod
    def _state_key(state: Mapping[str, Any] | None) -> str:
        return json.dumps(dict(state or {}), sort_keys=True, separators=(",", ":"), default=str)

    def _record(self, value: Mapping[str, Any], regime: str, use_mutation: bool) -> None:
        action = str(value.get("action") or "hold").lower()
        side = str(value.get("side") or "none").lower()
        self.counts["calls"] += 1
        self.counts[f"regime:{regime}"] += 1
        self.counts[f"action:{action}"] += 1
        self.counts[f"side:{side}"] += 1
        self.counts["mutation_calls" if use_mutation else "base_calls"] += 1
        if action == "hold":
            self.hold_reasons[str(value.get("why") or "unknown")] += 1

    def __call__(
        self,
        history: pd.DataFrame,
        state: Mapping[str, Any] | None = None,
        risk_action: str = "hold",
    ) -> dict[str, Any]:
        if self.current_frame_id is None:
            self.prepare_frame(history)
        regime = self._regime(history)
        use_mutation = self.field is not None and (self.regime_scope is None or self.regime_scope == regime)
        config = (
            dataclasses.replace(self.base_config, **{self.field: self.mutation_value})
            if use_mutation
            else self.base_config
        )
        decision_key = (
            *self._window_key(history),
            self._state_key(state),
            str(risk_action),
            bool(use_mutation),
        )
        cached = self.decision_cache.get(decision_key)
        if cached is not None:
            self.cache_hits["decision"] += 1
            value = copy.deepcopy(cached)
            self._record(value, regime, use_mutation)
            return value

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
                self.decision_cache[decision_key] = copy.deepcopy(value)
                self._record(value, regime, use_mutation)
                return value
            except TypeError as exc:
                last = exc
        raise RuntimeError(f"STRATEGY_CALL_FAILED:{type(last).__name__}:{last}")


def install_exact_prepare(exact: Any) -> Any:
    original_replay = exact._replay
    if getattr(original_replay, "_v3_fast_prepare", False):
        return exact

    def prepared_replay(
        frame: pd.DataFrame,
        features: pd.DataFrame,
        strategy: Any,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        prepare = getattr(strategy, "prepare_frame", None)
        if callable(prepare):
            prepare(frame)
        return original_replay(frame, features, strategy, *args, **kwargs)

    prepared_replay._v3_fast_prepare = True  # type: ignore[attr-defined]
    exact._replay = prepared_replay
    return exact
