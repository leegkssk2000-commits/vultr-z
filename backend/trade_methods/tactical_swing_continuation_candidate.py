from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


METHOD_ID = "tactical_swing/continuation"
REQUIRED_CONTEXT = (
    "strategy_id",
    "symbol",
    "side",
    "regime",
    "htf_trend",
    "structure_state",
    "pullback_reclaim",
    "atr_pct",
    "realized_vol_pct",
    "spread_bps",
    "slippage_bps",
    "funding_8h_pct",
    "position_size_pct",
    "leverage",
)


@dataclass(frozen=True)
class TacticalSwingContinuationCandidate:
    method: str = "tactical_swing"
    method_subtype: str = "continuation"
    profile_version: str = "1.0.0-candidate"
    observer_only: bool = True
    activation_allowed: bool = False
    runtime_mutation_allowed: bool = False
    order_authority: str = "blocked"
    execution_authority: str = "none"
    entry_style: str = "htf_trend_pullback_reclaim_continuation"
    hold_horizon: str = "4h_to_3d"
    risk_mode: str = "fail_closed_swing_continuation"
    target_r: float = 2.5
    size_multiplier: float = 0.5
    execution_overlays: tuple[str, ...] = (
        "htf_trend_gate",
        "market_structure_gate",
        "pullback_reclaim_gate",
        "volatility_gate",
        "liquidity_cost_gate",
        "funding_gate",
        "time_stop",
    )


PROFILE = TacticalSwingContinuationCandidate()


def validate_candidate_profile() -> dict[str, Any]:
    payload = asdict(PROFILE)
    if payload["method"] != "tactical_swing":
        raise ValueError("TACTICAL_SWING_METHOD_MISMATCH")
    if payload["method_subtype"] != "continuation":
        raise ValueError("TACTICAL_SWING_SUBTYPE_MISMATCH")
    if payload["observer_only"] is not True:
        raise ValueError("TACTICAL_SWING_NOT_OBSERVER_ONLY")
    if payload["activation_allowed"] is not False:
        raise ValueError("TACTICAL_SWING_ACTIVATION_UNSAFE")
    if payload["runtime_mutation_allowed"] is not False:
        raise ValueError("TACTICAL_SWING_RUNTIME_MUTATION_UNSAFE")
    if payload["order_authority"] != "blocked":
        raise ValueError("TACTICAL_SWING_ORDER_AUTHORITY_UNSAFE")
    if payload["execution_authority"] != "none":
        raise ValueError("TACTICAL_SWING_EXECUTION_AUTHORITY_UNSAFE")
    if payload["target_r"] <= 0 or not 0 < payload["size_multiplier"] <= 1:
        raise ValueError("TACTICAL_SWING_RISK_CONTRACT_INVALID")
    payload["method_id"] = METHOD_ID
    payload["required_context"] = list(REQUIRED_CONTEXT)
    payload["profile_state"] = "candidate_declaration_only"
    payload["runtime_trigger_proven"] = False
    payload["runtime_outcome_join_proven"] = False
    return payload


def project_observer(context: Mapping[str, Any]) -> dict[str, Any]:
    missing = [key for key in REQUIRED_CONTEXT if context.get(key) is None]
    base = validate_candidate_profile()
    base.update(
        {
            "action": "hold",
            "missing_context": missing,
            "candidate_ready": not missing,
            "block_reason": "MISSING_CONTEXT" if missing else "FORWARD_EVIDENCE_REQUIRED",
        }
    )
    return base
