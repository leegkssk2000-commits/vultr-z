from __future__ import annotations

from typing import Dict, List


REGISTRY_VERSION = "phase4.strategy_catalog.v1"

L_POOL = [
    "trend_ma_macd",
    "trend_rider",
    "turtle_trend",
    "anchor_vwap_trend",
    "keltner_trend",
    "obv_trend",
    "supertrend_pullback",
]

M_POOL = [
    "bb_revert",
    "vwap_revert",
    "fvg_revert",
    "pivot_reversal",
    "range_fade",
    "mfi_rsi_div",
    "rsi_swing_fail",
    "sr_levels",
]

O_POOL = [
    "break_and_continue",
    "squeeze_break",
    "orb_breakout",
    "liquidity_sweep",
]

S_POOL = [
    "ema_ribbon_scalp",
    "scalp_snap",
    "session_bias",
]

HELPER_POOL = [
    "regime_guard",
    "risk_decay_guard",
    "venue_guard",
    "freeze_guard",
]

FAMILY_TO_POOL: Dict[str, List[str]] = {
    "L": L_POOL,
    "M": M_POOL,
    "O": O_POOL,
    "S": S_POOL,
    "HELPER": HELPER_POOL,
}


def normalize_strategy_name(name: str | None) -> str:
    text = str(name or "").strip().lower()
    return text.replace(" ", "_").replace("-", "_")


def classify_strategy_family(strategy_name: str | None) -> str:
    name = normalize_strategy_name(strategy_name)

    if name in L_POOL:
        return "L"
    if name in M_POOL:
        return "M"
    if name in O_POOL:
        return "O"
    if name in S_POOL:
        return "S"
    if name in HELPER_POOL:
        return "HELPER"

    if "revert" in name or "fade" in name or "pivot" in name or "div" in name:
        return "M"
    if "break" in name or "orb" in name or "sweep" in name:
        return "O"
    if "scalp" in name or "session" in name:
        return "S"
    if "guard" in name or "watch" in name or "freeze" in name:
        return "HELPER"
    return "L"


def get_pool_by_family(family: str) -> List[str]:
    return list(FAMILY_TO_POOL.get(str(family or "L").upper(), L_POOL))


def get_pool_by_strategy(strategy_name: str | None) -> List[str]:
    family = classify_strategy_family(strategy_name)
    return get_pool_by_family(family)
