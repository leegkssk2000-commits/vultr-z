"""Z-OS risk authority boundary.

The legacy ``risk_check`` hook is kept for compatibility. The executable path
uses ``authorize_execution`` so a TeamBot-approved signal still cannot reach an
executor unless an explicit Z-OS risk decision is present and bound to the same
strategy candidate.

This module intentionally does not invent risk thresholds or optional advisor
modules. Threshold logic belongs to the existing SSOT/risk implementation;
this boundary only enforces provenance and fail-closed ordering.
"""

from __future__ import annotations

from typing import Any, Mapping


RISK_AUTHORITY = "z_os_risk_gate"
RISK_BLOCK_REASON = "z_os_risk_gate_required"
TEAM_AUTHORITY = "team_bot_consensus"


def risk_check():
    # TODO: position size / SL / exposure / DD checks remain SSOT-owned.
    print("risk check")


def _blocked(reason: str) -> dict[str, Any]:
    return {
        "ok": False,
        "approved": False,
        "execution_eligible": False,
        "execution_authority": "none",
        "reason": reason,
        "next_layer": "z_os_risk",
    }


def authorize_execution(
    team_signal: Mapping[str, Any] | None,
    risk_decision: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Authorize executor routing only after TeamBot and Z-OS risk approval."""
    if not isinstance(team_signal, Mapping):
        return _blocked("invalid_team_signal")
    if team_signal.get("execution_eligible") is not True:
        return _blocked("team_signal_not_execution_eligible")
    if team_signal.get("execution_authority") != TEAM_AUTHORITY:
        return _blocked("invalid_team_signal_authority")

    strategy = team_signal.get("strategy")
    candidate_id = team_signal.get("candidate_id")
    if not strategy or not candidate_id:
        return _blocked("team_signal_identity_missing")

    if not isinstance(risk_decision, Mapping):
        return _blocked(RISK_BLOCK_REASON)
    if risk_decision.get("strategy") != strategy:
        return _blocked("risk_strategy_identity_mismatch")
    if risk_decision.get("candidate_id") != candidate_id:
        return _blocked("risk_candidate_identity_mismatch")
    if risk_decision.get("approved") is not True:
        return _blocked("z_os_risk_not_approved")
    if risk_decision.get("execution_eligible") is not True:
        return _blocked("z_os_risk_not_execution_eligible")
    if risk_decision.get("authority") != RISK_AUTHORITY:
        return _blocked("invalid_z_os_risk_authority")

    return {
        "ok": True,
        "approved": True,
        "execution_eligible": True,
        "execution_authority": RISK_AUTHORITY,
        "source": RISK_AUTHORITY,
        "strategy": strategy,
        "candidate_id": candidate_id,
        "team_signal": dict(team_signal),
        "risk_decision": dict(risk_decision),
        "side": team_signal.get("side"),
        "confidence": team_signal.get("confidence"),
        "team": team_signal.get("team"),
        "next_layer": "executor",
    }


def validate_execution_signal(signal: Mapping[str, Any] | None) -> tuple[bool, str]:
    """Validate a normalized final signal at any executor entry point."""
    if not isinstance(signal, Mapping):
        return False, "invalid_execution_signal"
    if signal.get("execution_eligible") is not True:
        return False, "z_os_risk_not_execution_eligible"
    if signal.get("execution_authority") != RISK_AUTHORITY:
        return False, "invalid_z_os_risk_authority"
    if signal.get("next_layer") != "executor":
        return False, "invalid_execution_signal_route"

    strategy = signal.get("strategy")
    candidate_id = signal.get("candidate_id")
    if not strategy or not candidate_id:
        return False, "execution_signal_identity_missing"

    team_signal = signal.get("team_signal")
    if not isinstance(team_signal, Mapping):
        return False, "team_signal_missing"
    if team_signal.get("execution_authority") != TEAM_AUTHORITY:
        return False, "invalid_team_signal_authority"
    if team_signal.get("execution_eligible") is not True:
        return False, "team_signal_not_execution_eligible"
    if team_signal.get("strategy") != strategy or team_signal.get("candidate_id") != candidate_id:
        return False, "team_execution_identity_mismatch"

    risk_decision = signal.get("risk_decision")
    if not isinstance(risk_decision, Mapping):
        return False, RISK_BLOCK_REASON
    if risk_decision.get("authority") != RISK_AUTHORITY:
        return False, "invalid_z_os_risk_authority"
    if risk_decision.get("approved") is not True or risk_decision.get("execution_eligible") is not True:
        return False, "z_os_risk_not_approved"
    if risk_decision.get("strategy") != strategy or risk_decision.get("candidate_id") != candidate_id:
        return False, "risk_execution_identity_mismatch"

    if signal.get("side") not in {"buy", "sell"} or team_signal.get("side") != signal.get("side"):
        return False, "execution_side_mismatch"
    return True, "ok"
