from __future__ import annotations

from typing import Any, Callable, Dict, List

from backend.strategies.alpha_combo import strategy as alpha_combo
from backend.strategies.anchor_vwap_trend import strategy as anchor_vwap_trend
from backend.strategies.bb_revert import strategy as bb_revert
from backend.strategies.break_and_continue import strategy as break_and_continue
from backend.strategies.ema_ribbon_scalp import strategy as ema_ribbon_scalp
from backend.strategies.fvg_revert import strategy as fvg_revert
from backend.strategies.grid_rebalance import strategy as grid_rebalance
from backend.strategies.keltner_trend import strategy as keltner_trend
from backend.strategies.liquidity_sweep import strategy as liquidity_sweep
from backend.strategies.mfi_rsi_div import strategy as mfi_rsi_div
from backend.strategies.obv_trend import strategy as obv_trend
from backend.strategies.pivot_reversal import strategy as pivot_reversal
from backend.strategies.range_fade import strategy as range_fade
from backend.strategies.rbreaker_like import strategy as rbreaker_like
from backend.strategies.rsi_swing_fail import strategy as rsi_swing_fail
from backend.strategies.scalp_snap import strategy as scalp_snap
from backend.strategies.session_bias import strategy as session_bias
from backend.strategies.squeeze_break import strategy as squeeze_break
from backend.strategies.sr_levels import strategy as sr_levels
from backend.strategies.supertrend_pullback import strategy as supertrend_pullback
from backend.strategies.test_paper_flow import strategy as test_paper_flow
from backend.strategies.trend_ma_macd import strategy as trend_ma_macd
from backend.strategies.trend_rider import strategy as trend_rider
from backend.strategies.turtle_trend import strategy as turtle_trend
from backend.strategies.vol_spike_fade import strategy as vol_spike_fade
from backend.strategies.vwap_revert import strategy as vwap_revert


StrategyFn = Callable[..., Dict[str, Any]]


def normalize_strategy_name(name: str) -> str:
    return str(name or "").strip().lower().replace("-", "_").replace(" ", "_")


def canonical_strategy_name(name: str) -> str:
    return normalize_strategy_name(name)


STRATEGY_MODULES: Dict[str, StrategyFn] = {
    "alpha_combo": alpha_combo,
    "anchor_vwap_trend": anchor_vwap_trend,
    "bb_revert": bb_revert,
    "break_and_continue": break_and_continue,
    "ema_ribbon_scalp": ema_ribbon_scalp,
    "fvg_revert": fvg_revert,
    "grid_rebalance": grid_rebalance,
    "keltner_trend": keltner_trend,
    "liquidity_sweep": liquidity_sweep,
    "mfi_rsi_div": mfi_rsi_div,
    "obv_trend": obv_trend,
    "pivot_reversal": pivot_reversal,
    "range_fade": range_fade,
    "rbreaker_like": rbreaker_like,
    "rsi_swing_fail": rsi_swing_fail,
    "scalp_snap": scalp_snap,
    "session_bias": session_bias,
    "squeeze_break": squeeze_break,
    "sr_levels": sr_levels,
    "supertrend_pullback": supertrend_pullback,
    "test_paper_flow": test_paper_flow,
    "trend_ma_macd": trend_ma_macd,
    "trend_rider": trend_rider,
    "turtle_trend": turtle_trend,
    "vol_spike_fade": vol_spike_fade,
    "vwap_revert": vwap_revert,
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
