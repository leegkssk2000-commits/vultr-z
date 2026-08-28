"""Z-OS risk authority boundary.

The legacy ``risk_check`` hook is kept for compatibility.  The executable path
uses ``authorize_execution`` so a TeamBot-approved signal still cannot reach an
executor unless an explicit Z-OS risk decision is present.

This module intentionally does not invent risk thresholds.  Threshold logic
belongs to the existing SSOT/risk implementation; this boundary only enforces
provenance and fail-closed ordering.
"""

from __future__ import annotations

from typing import Any, Mapping


RISK_AUTHORITY = "z_os_risk_gate"
RISK_BLOCK_REASON = "z_os_risk_gate_required"


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
    if team_signal.get("execution_authority") != "team_bot_consensus":
        return _blocked("invalid_team_signal_authority")

    if not isinstance(risk_decision, Mapping):
        return _blocked(RISK_BLOCK_REASON)
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
        "team_signal": dict(team_signal),
        "risk_decision": dict(risk_decision),
        "side": team_signal.get("side"),
        "team": team_signal.get("team"),
        "zbot_authority": "advisor_only",
        "next_layer": "executor",
    }
