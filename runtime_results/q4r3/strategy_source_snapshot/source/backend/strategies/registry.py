from __future__ import annotations

from typing import Any, Callable, Dict, List


StrategyFn = Callable[..., Dict[str, Any]]


def _hold_stub(name: str, exc: Exception | None = None) -> StrategyFn:
    def _fn(df=None, **kwargs) -> Dict[str, Any]:
        return {
            "side": None,
            "action": "hold",
            "size": 0.0,
            "entry": 0.0,
            "sl": 0.0,
            "tp": 0.0,
            "pyramiding": 0,
            "why": f"registry_import_error:{name}",
            "skill": "none",
            "confidence": 0.0,
            "tags": ["registry_import_error"],
            "indicators": {"error": str(exc) if exc else ""},
            "raw": {"error": str(exc) if exc else ""},
        }
    return _fn

try:
    from backend.strategies.atr_trail import strategy as atr_trail
except Exception as e:  # pragma: no cover
    atr_trail = _hold_stub("atr_trail", e)

try:
    from backend.strategies.breakout import strategy as breakout
except Exception as e:  # pragma: no cover
    breakout = _hold_stub("breakout", e)

try:
    from backend.strategies.calendar_bias import strategy as calendar_bias
except Exception as e:  # pragma: no cover
    calendar_bias = _hold_stub("calendar_bias", e)

try:
    from backend.strategies.fvg import strategy as fvg
except Exception as e:  # pragma: no cover
    fvg = _hold_stub("fvg", e)

try:
    from backend.strategies.init import strategy as init_strategy
except Exception as e:  # pragma: no cover
    init_strategy = _hold_stub("init", e)

try:
    from backend.strategies.macd_gate import strategy as macd_gate
except Exception as e:  # pragma: no cover
    macd_gate = _hold_stub("macd_gate", e)

try:
    from backend.strategies.meanrev import strategy as meanrev
except Exception as e:  # pragma: no cover
    meanrev = _hold_stub("meanrev", e)

try:
    from backend.strategies.momentum import strategy as momentum
except Exception as e:  # pragma: no cover
    momentum = _hold_stub("momentum", e)

try:
    from backend.strategies.position_sizer import strategy as position_sizer
except Exception as e:  # pragma: no cover
    position_sizer = _hold_stub("position_sizer", e)

try:
    from backend.strategies.rsi_gate import strategy as rsi_gate
except Exception as e:  # pragma: no cover
    rsi_gate = _hold_stub("rsi_gate", e)

try:
    from backend.strategies.vol_filter import strategy as vol_filter
except Exception as e:  # pragma: no cover
    vol_filter = _hold_stub("vol_filter", e)


def normalize_strategy_name(name: str) -> str:
    return str(name or "").strip().lower().replace("-", "_").replace(" ", "_")


def canonical_strategy_name(name: str) -> str:
    return normalize_strategy_name(name)


STRATEGY_MODULES = {
    "atr_trail": atr_trail,
    "breakout": breakout,
    "calendar_bias": calendar_bias,
    "fvg": fvg,
    "init": init_strategy,
    "macd_gate": macd_gate,
    "meanrev": meanrev,
    "momentum": momentum,
    "position_sizer": position_sizer,
    "rsi_gate": rsi_gate,
    "vol_filter": vol_filter,
}

STRATEGIES = STRATEGY_MODULES


def list_strategies() -> List[str]:
    return sorted(STRATEGY_MODULES.keys())


def has_strategy(name: str) -> bool:
    return canonical_strategy_name(name) in STRATEGY_MODULES


def get_strategy(name: str) -> StrategyFn:
    key = canonical_strategy_name(name)
    if key not in STRATEGY_MODULES:
        raise KeyError(f"strategy not registered: {name}")
    return STRATEGY_MODULES[key]


def get_strategy_callable(name: str) -> StrategyFn:
    return get_strategy(name)


def _normalize_result(result: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(result or {})
    out.setdefault("side", None)
    out.setdefault("action", "hold")
    out.setdefault("size", 0.0)
    out.setdefault("entry", 0.0)
    out.setdefault("sl", 0.0)
    out.setdefault("tp", 0.0)
    out.setdefault("pyramiding", 0)
    out.setdefault("why", "")
    out.setdefault("skill", "none")
    out.setdefault("confidence", 0.0)
    out.setdefault("tags", [])
    out.setdefault("indicators", {})
    out.setdefault("raw", dict(out))
    return out


def run_strategy(name: str, df, **kwargs) -> Dict[str, Any]:
    fn = get_strategy(name)
    result = fn(df, **kwargs)
    if not isinstance(result, dict):
        raise TypeError(f"strategy must return dict: {name}")
    return _normalize_result(result)


def smoke_test_all(df, symbol: str = "BTCUSDT", **kwargs) -> Dict[str, Dict[str, Any]]:
    results: Dict[str, Dict[str, Any]] = {}
    for name in list_strategies():
        try:
            results[name] = run_strategy(name, df, symbol=symbol, **kwargs)
        except Exception as e:
            results[name] = {
                "side": None,
                "action": "hold",
                "size": 0.0,
                "entry": 0.0,
                "sl": 0.0,
                "tp": 0.0,
                "pyramiding": 0,
                "why": f"smoke_test_error:{type(e).__name__}",
                "skill": "none",
                "confidence": 0.0,
                "tags": ["smoke_test_error"],
                "indicators": {"error": str(e)},
                "raw": {"error": str(e)},
            }
    return results


__all__ = [
    "STRATEGIES",
    "STRATEGY_MODULES",
    "normalize_strategy_name",
    "canonical_strategy_name",
    "list_strategies",
    "has_strategy",
    "get_strategy",
    "get_strategy_callable",
    "run_strategy",
    "smoke_test_all",
]
