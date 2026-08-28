"""Fail-closed TeamBot authority boundary for Z-OS.

Strategies produce raw alpha candidates only.  They never carry execution
authority.  A candidate may cross into the execution path only after an
explicit Alpha/Beta/Gamma/Delta TeamBot decision proves that all four role
slots (LBot/MBot/OBot/SBot) participated, the team approved the candidate, and
SBot did not veto it.

ZBot is deliberately outside this contract: it is an advisor/trace layer and
cannot replace a TeamBot role or grant execution authority.
"""

from __future__ import annotations

from typing import Any, Mapping


TEAM_LAYOUT: dict[str, dict[str, str]] = {
    "Alpha": {"lead": "LBot", "support": "MBot", "watcher": "OBot", "guard": "SBot"},
    "Beta": {"lead": "MBot", "support": "LBot", "watcher": "OBot", "guard": "SBot"},
    "Gamma": {"lead": "OBot", "support": "MBot", "watcher": "LBot", "guard": "SBot"},
    "Delta": {"lead": "SBot", "support": "OBot", "watcher": "MBot", "reserve": "LBot"},
}

BOT_ROLES: dict[str, str] = {
    "LBot": "lead/trend: primary trend-confirm candidate and hold/reduce posture",
    "MBot": "method/confirm: setup-method validation, range support and reduce logic",
    "OBot": "observer/context: breakout probe, venue thinness, momentum scout and veto context",
    "SBot": "safety/guard: recovery guard, hedge reserve, blocked state and LKG boundary",
}

REQUIRED_BOTS = frozenset(BOT_ROLES)
TEAM_AUTHORITY = "team_bot_consensus"
BLOCK_REASON = "team_bot_hierarchy_required"


def _blocked(reason: str, *, team: str | None = None, missing: list[str] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": False,
        "approved": False,
        "execution_eligible": False,
        "execution_authority": "none",
        "reason": reason,
        "next_layer": "team_bot",
        "zbot_authority": "advisor_only",
    }
    if team is not None:
        payload["team"] = team
    if missing:
        payload["missing_roles"] = missing
    return payload


def authorize_team_signal(
    raw_signal: Mapping[str, Any] | None,
    team_decision: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Validate TeamBot provenance and return a normalized executable intent.

    This function does not implement trading intelligence.  It is an authority
    boundary: upstream TeamBots own the decision; this layer only verifies that
    the required hierarchy is present and fail-closes every bypass.
    """
    if not isinstance(raw_signal, Mapping):
        return _blocked("invalid_raw_strategy_signal")

    side = raw_signal.get("side")
    if side not in {"buy", "sell"}:
        return _blocked("raw_strategy_has_no_actionable_side")

    if not isinstance(team_decision, Mapping):
        return _blocked(BLOCK_REASON)

    team = team_decision.get("team")
    if team not in TEAM_LAYOUT:
        return _blocked("unknown_team", team=str(team) if team is not None else None)

    roles = team_decision.get("roles")
    if not isinstance(roles, Mapping):
        return _blocked("missing_team_bot_roles", team=team, missing=sorted(REQUIRED_BOTS))

    missing = sorted(role for role in REQUIRED_BOTS if role not in roles or roles.get(role) is None)
    if missing:
        return _blocked("missing_team_bot_roles", team=team, missing=missing)

    if team_decision.get("approved") is not True:
        return _blocked("team_not_approved", team=team)

    team_side = team_decision.get("side")
    if team_side != side:
        return _blocked("team_strategy_side_mismatch", team=team)

    sbot = roles.get("SBot")
    if isinstance(sbot, Mapping) and sbot.get("veto") is True:
        return _blocked("sbot_veto", team=team)
    if sbot is False:
        return _blocked("sbot_veto", team=team)

    return {
        "ok": True,
        "approved": True,
        "execution_eligible": True,
        "execution_authority": TEAM_AUTHORITY,
        "source": TEAM_AUTHORITY,
        "team": team,
        "side": side,
        "confidence": team_decision.get("confidence", raw_signal.get("confidence", 0.0)),
        "roles": dict(roles),
        "strategy_signal": dict(raw_signal),
        "zbot_authority": "advisor_only",
        "next_layer": "z_os_risk_execution",
    }
