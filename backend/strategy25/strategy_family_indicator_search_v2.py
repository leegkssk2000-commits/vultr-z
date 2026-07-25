from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence

import pandas as pd

from backend.strategy25 import strategy_family_indicator_search_v1 as v1


FAMILY_MAP = v1.FAMILY_MAP
FAMILY_VARIANTS = v1.FAMILY_VARIANTS
VariantSpec = v1.VariantSpec
_CONTEXT_CACHE: dict[tuple[int, int, int, str], dict[str, bool]] = {}
_CACHE_LIMIT = 20000


def _timestamp_value(value: Any) -> int:
    timestamp = pd.Timestamp(value)
    return int(timestamp.value)


def context_flags(history: pd.DataFrame, side: str) -> dict[str, bool]:
    if history is None or history.empty or "timestamp" not in history.columns:
        return v1.context_flags(history, side)
    key = (
        _timestamp_value(history["timestamp"].iloc[0]),
        _timestamp_value(history["timestamp"].iloc[-1]),
        len(history),
        str(side).lower(),
    )
    cached = _CONTEXT_CACHE.get(key)
    if cached is not None:
        return cached
    result = v1.context_flags(history, side)
    if len(_CONTEXT_CACHE) >= _CACHE_LIMIT:
        _CONTEXT_CACHE.clear()
    _CONTEXT_CACHE[key] = result
    return result


def variant_allows(spec: VariantSpec, history: pd.DataFrame, result: Mapping[str, Any]) -> bool:
    action = str(result.get("action") or "hold").lower()
    if action != "enter":
        return True
    side = str(result.get("side") or "long").lower()
    flags = context_flags(history, side)
    return all(flags.get(name) is True for name in spec.required) and all(flags.get(name) is not True for name in spec.forbidden)


def wrap_strategy(strategy: Callable[..., dict[str, Any]], spec: VariantSpec) -> Callable[..., dict[str, Any]]:
    def wrapped(history: pd.DataFrame, *args: Any, **kwargs: Any) -> dict[str, Any]:
        result = strategy(history, *args, **kwargs)
        if not isinstance(result, Mapping):
            raise TypeError("STRATEGY_RESULT_MAPPING_REQUIRED")
        output = dict(result)
        allowed = variant_allows(spec, history, output)
        indicators = dict(output.get("indicators") or {})
        indicators["family_variant_id"] = spec.variant_id
        indicators["family_variant_allowed"] = allowed
        if not allowed and str(output.get("action") or "hold").lower() == "enter":
            indicators["pre_variant_side"] = output.get("side")
            indicators["pre_variant_why"] = output.get("why")
            output.update(
                {
                    "side": None,
                    "action": "hold",
                    "size": 0.0,
                    "why": f"family_variant_block:{spec.variant_id}",
                    "skill": "none",
                    "confidence": 0.0,
                }
            )
        output["indicators"] = indicators
        return output

    wrapped.__name__ = f"{getattr(strategy, '__name__', 'strategy')}__{spec.variant_id.lower()}"
    return wrapped


def variants_for(strategy_id: str) -> Sequence[VariantSpec]:
    return v1.variants_for(strategy_id)
