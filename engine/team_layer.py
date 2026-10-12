"""Fail-closed TeamBot authority boundary for Z-OS.

Strategies produce raw candidates only. They never carry execution authority.
A candidate may cross into the Z-OS risk layer only after an explicit
Alpha/Beta/Gamma/Delta team decision proves the preserved TeamBot topology:

- one support bot
- exactly three watcher bots
- one helper bot

The contract is structural only. It does not invent bot identities, trading
thresholds, or strategy logic. Every slot must name a concrete bot and provide
affirmative participation evidence; a bot identity cannot fill multiple slots.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence


TEAM_NAMES = frozenset({"Alpha", "Beta", "Gamma", "Delta"})
TEAM_TOPOLOGY = {"support": 1, "watchers": 3, "helper": 1}
TEAM_AUTHORITY = "team_bot_consensus"
BLOCK_REASON = "team_bot_hierarchy_required"


def build_candidate_id(strategy_name: str, raw_signal: Mapping[str, Any] | None) -> str | None:
    """Build a stable identity for one raw strategy candidate."""
    if not strategy_name or not isinstance(raw_signal, Mapping):
        return None
    try:
        canonical = json.dumps(dict(raw_signal), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    except (TypeError, ValueError):
        return None
    material = f"{strategy_name}|{canonical}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()[:24]


def _blocked(reason: str, *, team: str | None = None, detail: Any = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": False,
        "approved": False,
        "execution_eligible": False,
        "execution_authority": "none",
        "reason": reason,
        "next_layer": "team_bot",
    }
    if team is not None:
        payload["team"] = team
    if detail is not None:
        payload["detail"] = detail
    return payload


def _participant_bot_id(evidence: Any) -> str | None:
    if not isinstance(evidence, Mapping):
        return None
    if evidence.get("participated") is not True:
        return None
    bot_id = evidence.get("bot")
    if not isinstance(bot_id, str) or not bot_id.strip():
        return None
    return bot_id.strip()


def _validate_team_bots(team_bots: Any) -> tuple[bool, str, dict[str, Any] | None]:
    if not isinstance(team_bots, Mapping):
        return False, "missing_team_bot_slots", None

    expected_keys = set(TEAM_TOPOLOGY)
    actual_keys = set(team_bots)
    if actual_keys != expected_keys:
        return False, "team_bot_slot_mismatch", {
            "expected": sorted(expected_keys),
            "actual": sorted(actual_keys),
        }

    support = team_bots.get("support")
    helper = team_bots.get("helper")
    watchers = team_bots.get("watchers")

    support_id = _participant_bot_id(support)
    if support_id is None:
        return False, "invalid_support_bot_evidence", None

    helper_id = _participant_bot_id(helper)
    if helper_id is None:
        return False, "invalid_helper_bot_evidence", None

    if not isinstance(watchers, Sequence) or isinstance(watchers, (str, bytes)) or len(watchers) != 3:
        count = len(watchers) if isinstance(watchers, Sequence) and not isinstance(watchers, (str, bytes)) else None
        return False, "watcher_count_mismatch", {"expected": 3, "actual": count}

    watcher_ids: list[str] = []
    for index, watcher in enumerate(watchers):
        watcher_id = _participant_bot_id(watcher)
        if watcher_id is None:
            return False, "invalid_watcher_bot_evidence", {"index": index}
        watcher_ids.append(watcher_id)

    all_ids = [support_id, *watcher_ids, helper_id]
    if len(set(all_ids)) != len(all_ids):
        return False, "duplicate_team_bot_identity", {"bot_ids": all_ids}

    normalized = {
        "support": dict(support),
        "watchers": [dict(watcher) for watcher in watchers],
        "helper": dict(helper),
    }
    return True, "ok", normalized


def authorize_team_signal(
    raw_signal: Mapping[str, Any] | None,
    team_decision: Mapping[str, Any] | None,
    *,
    strategy_name: str | None = None,
) -> dict[str, Any]:
    """Validate candidate identity and the five-slot TeamBot decision."""
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
    if team not in TEAM_NAMES:
        return _blocked("unknown_team", team=str(team) if team is not None else None)

    bots_ok, bots_reason, bots_payload = _validate_team_bots(team_decision.get("team_bots"))
    if not bots_ok:
        return _blocked(bots_reason, team=team, detail=bots_payload)

    if team_decision.get("approved") is not True:
        return _blocked("team_not_approved", team=team)

    if team_decision.get("side") != side:
        return _blocked("team_strategy_side_mismatch", team=team)

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
        "team_bots": bots_payload,
        "strategy_signal": dict(raw_signal),
        "next_layer": "z_os_risk_execution",
    }
