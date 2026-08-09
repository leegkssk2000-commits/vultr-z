from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class AlphaFamilySpec:
    name: str
    status: str
    symbols: Tuple[str, ...]
    timeframe: str
    causal_features_only: bool = True
    fill_model: str = "closed_bar_signal_then_next_bar_open"
    same_bar_fill: bool = False
    cost_admission_required: bool = True
    source_binding_required: bool = False
    pairs_adapter_required: bool = False
    research_only: bool = True
    execution_authority: str = "NONE"
    order_authority: str = "BLOCKED"


ALPHA_FAMILIES = {
    "trend_momentum": AlphaFamilySpec(
        name="trend_momentum",
        status="BASE_RESEARCH_ALLOWED",
        symbols=("BTCUSDT", "ETHUSDT"),
        timeframe="15m",
    ),
    "carry_flow": AlphaFamilySpec(
        name="carry_flow",
        status="SOURCE_BINDING_REQUIRED",
        symbols=("BTCUSDT", "ETHUSDT"),
        timeframe="15m",
        source_binding_required=True,
    ),
    "relative_value_psa": AlphaFamilySpec(
        name="relative_value_psa",
        status="SOURCE_BINDING_REQUIRED",
        symbols=("BTCUSDT", "ETHUSDT"),
        timeframe="15m",
        source_binding_required=True,
        pairs_adapter_required=True,
    ),
}


def get_alpha_family(name: str) -> AlphaFamilySpec:
    try:
        return ALPHA_FAMILIES[name]
    except KeyError as exc:
        allowed = ", ".join(sorted(ALPHA_FAMILIES))
        raise ValueError(f"alpha family not allowed: {name}; allowed={allowed}") from exc
