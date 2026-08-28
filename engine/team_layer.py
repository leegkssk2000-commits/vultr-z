"""Fail-closed TeamBot authority boundary for Z-OS.

Strategies produce raw alpha candidates only. They never carry execution
authority. A candidate may cross into the execution path only after an
explicit Alpha/Beta/Gamma/Delta TeamBot decision proves that all four role
slots (LBot/MBot/OBot/SBot) participated, the decision is bound to the exact
strategy candidate, the team approved it, and SBot explicitly did not veto it.

ZBot is deliberately outside this contract: it is an advisor/trace layer and
cannot replace a TeamBot role or grant execution authority.
"""

from __future__ import annotations

import hashlib
import json
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


def build_candidate_id(strategy_name: str, raw_signal: Mapping[str, Any] | None) -> str | None:
    """Build a stable identity for one raw strategy candidate.

    Non-JSON-compatible candidates fail closed instead of receiving an unstable
    identity. TeamBot and Z-OS approvals must refer to this exact id.
    """
    if not strategy_name or not isinstance(raw_signal, Mapping):
        return None
    try:
        canonical = json.dumps(dict(raw_signal), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    except (TypeError, ValueError):
        return None
    material = f"{strategy_name}|{canonical}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()[:24]


def _blocked(
    reason: str,
    *,
    team: str | None = None,
    missing: list[str] | None = None,
    invalid: list[str] | None = None,
) -> dict[str, Any]:
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
    if invalid:
        payload["invalid_roles"] = invalid
    return payload


def authorize_team_signal(
    raw_signal: Mapping[str, Any] | None,
    team_decision: Mapping[str, Any] | None,
    *,
    strategy_name: str | None = None,
) -> dict[str, Any]:
    """Validate TeamBot provenance and return a normalized TeamBot signal.

    This function does not implement trading intelligence. Upstream TeamBots
    own the decision; this boundary verifies identity, participation and veto
    evidence and fail-closes every bypass.
    """
    if not isinstance(raw_signal, Mapping):
        return _blocked("invalid_raw_strategy_signal")

    side = raw_signal.get("side")
    if side not in {"buy", "sell"}:
        return _blocked("raw_strategy_has_no_actionable_side")

    if not strategy_name:
        return _blocked("strategy_identity_required")

    candidate_id = build_candidate_id(strategy_name, raw_signal)
    if candidate_id is None:
        return _blocked("candidate_identity_unavailable")

    if not isinstance(team_decision, Mapping):
        return _blocked(BLOCK_REASON)

    if team_decision.get("strategy") != strategy_name:
        return _blocked("team_strategy_identity_mismatch")
    if team_decision.get("candidate_id") != candidate_id:
        return _blocked("team_candidate_identity_mismatch")

    team = team_decision.get("team")
    if team not in TEAM_LAYOUT:
        return _blocked("unknown_team", team=str(team) if team is not None else None)

    roles = team_decision.get("roles")
    if not isinstance(roles, Mapping):
        return _blocked("missing_team_bot_roles", team=team, missing=sorted(REQUIRED_BOTS))

    missing = sorted(role for role in REQUIRED_BOTS if role not in roles or roles.get(role) is None)
    if missing:
        return _blocked("missing_team_bot_roles", team=team, missing=missing)

    invalid = sorted(
        role
        for role in REQUIRED_BOTS
        if not isinstance(roles.get(role), Mapping) or roles[role].get("participated") is not True
    )
    if invalid:
        return _blocked("invalid_team_bot_evidence", team=team, invalid=invalid)

    if team_decision.get("approved") is not True:
        return _blocked("team_not_approved", team=team)

    team_side = team_decision.get("side")
    if team_side != side:
        return _blocked("team_strategy_side_mismatch", team=team)

    sbot = roles["SBot"]
    if sbot.get("veto") is True:
        return _blocked("sbot_veto", team=team)
    if sbot.get("veto") is not False:
        return _blocked("sbot_non_veto_evidence_required", team=team, invalid=["SBot"])

    return {
        "ok": True,
        "approved": True,
        "execution_eligible": True,
        "execution_authority": TEAM_AUTHORITY,
        "source": TEAM_AUTHORITY,
        "team": team,
        "strategy": strategy_name,
        "candidate_id": candidate_id,
        "side": side,
        "confidence": team_decision.get("confidence", raw_signal.get("confidence", 0.0)),
        "roles": dict(roles),
        "strategy_signal": dict(raw_signal),
        "zbot_authority": "advisor_only",
        "next_layer": "z_os_risk_execution",
    }
