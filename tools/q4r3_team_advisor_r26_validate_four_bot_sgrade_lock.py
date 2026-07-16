#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from canonical.bots.contracts import ALLOWED_ACTIONS, CONTRACT_VERSION
from canonical.bots.lbot import CAPABILITY_TAGS as L_CAPS, LBOT_ALLOWED_ACTIONS, LBot
from canonical.bots.mbot import CAPABILITY_TAGS as M_CAPS, MBOT_ALLOWED_ACTIONS, MBot
from canonical.bots.obot import CAPABILITY_TAGS as O_CAPS, OBOT_ALLOWED_ACTIONS, OBot
from canonical.bots.sbot import ACTION_PRIORITY as S_ACTIONS, CAPABILITY_TAGS as S_CAPS, SBot

BOT_FILES = {
    "LBot": "canonical/bots/lbot.py",
    "MBot": "canonical/bots/mbot.py",
    "OBot": "canonical/bots/obot.py",
    "SBot": "canonical/bots/sbot.py",
}
BOT_CLASSES = {"LBot": LBot, "MBot": MBot, "OBot": OBot, "SBot": SBot}
CAPABILITIES = {"LBot": L_CAPS, "MBot": M_CAPS, "OBot": O_CAPS, "SBot": S_CAPS}
EXPECTED_STATUS = {
    "R2.2": ("R22_SBOT_SGRADE_LOCK_PASS", "sbot_sgrade_ready", 8),
    "R2.3": ("R23_LBOT_SGRADE_LOCK_PASS", "lbot_sgrade_ready", 6),
    "R2.4": ("R24_MBOT_SGRADE_LOCK_PASS", "mbot_sgrade_ready", 6),
    "R2.5": ("R25_OBOT_SGRADE_LOCK_PASS", "obot_sgrade_ready", 7),
}
FORBIDDEN_TOKENS = (
    "create_order(", "place_order(", "submit_order(", "cancel_order(",
    "ccxt.", "BINGX_API_KEY", "BINGX_SECRET", "os.environ.get(",
)


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--r22", type=Path, required=True)
    parser.add_argument("--r23", type=Path, required=True)
    parser.add_argument("--r24", type=Path, required=True)
    parser.add_argument("--r25", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    blockers: list[str] = []
    statuses = {
        "R2.2": load(args.r22),
        "R2.3": load(args.r23),
        "R2.4": load(args.r24),
        "R2.5": load(args.r25),
    }
    for stage, payload in statuses.items():
        verdict, ready_key, capability_count = EXPECTED_STATUS[stage]
        report = payload.get("report") or {}
        if payload.get("state") != "PASS" or payload.get("verdict") != verdict:
            blockers.append(f"{stage}_NOT_PASS")
        if report.get(ready_key) is not True:
            blockers.append(f"{stage}_{ready_key.upper()}_FALSE")
        if report.get("capability_hit_count") != capability_count:
            blockers.append(f"{stage}_CAPABILITY_COUNT_INVALID")
        if report.get("runtime_binding") is not False or report.get("execution_authority") != "none":
            blockers.append(f"{stage}_AUTHORITY_INVALID")

    contract = load(args.contract)
    expected_actions = sorted(ALLOWED_ACTIONS)
    if contract.get("schema") != "q4r3_four_bot_sgrade_lock_v1":
        blockers.append("LOCK_SCHEMA_INVALID")
    if contract.get("official_stage") != "R2.6" or contract.get("contract_version") != CONTRACT_VERSION:
        blockers.append("LOCK_VERSION_INVALID")
    if sorted(contract.get("allowed_actions") or []) != expected_actions:
        blockers.append("LOCK_ACTION_ENUM_INVALID")
    if contract.get("source_prefixes") != ["cf:", "sheets:"]:
        blockers.append("LOCK_SOURCE_PREFIX_INVALID")

    ordinary_actions = frozenset({"hold", "reduce25", "partial30", "route_change"})
    if LBOT_ALLOWED_ACTIONS != ordinary_actions or MBOT_ALLOWED_ACTIONS != ordinary_actions or OBOT_ALLOWED_ACTIONS != ordinary_actions:
        blockers.append("ORDINARY_BOT_ACTION_BOUNDARY_INVALID")
    if frozenset(S_ACTIONS) != ALLOWED_ACTIONS:
        blockers.append("SBOT_ACTION_BOUNDARY_INVALID")

    owners = {bot_id: cls() for bot_id, cls in BOT_CLASSES.items()}
    if len({owner.bot_id for owner in owners.values()}) != 4:
        blockers.append("BOT_OWNER_ID_COLLISION")
    if len({owner.semantic_role for owner in owners.values()}) != 4:
        blockers.append("BOT_SEMANTIC_ROLE_COLLISION")

    bot_report: dict[str, Any] = {}
    forbidden_hits: list[str] = []
    thin_wrappers: list[str] = []
    for bot_id, relative in BOT_FILES.items():
        path = args.worktree / relative
        source = path.read_text(encoding="utf-8", errors="replace")
        lower = source.lower()
        caps = tuple(CAPABILITIES[bot_id])
        hits = sorted(cap for cap in caps if cap.lower() in lower)
        if len(hits) != len(caps):
            blockers.append(f"{bot_id}_CAPABILITY_SOURCE_GAP")
        if "advisory_assessment(" in source:
            thin_wrappers.append(bot_id)
            blockers.append(f"{bot_id}_THIN_WRAPPER_REMAINS")
        if 'CANONICAL_SOURCES = ("cf:", "sheets:")' not in source:
            blockers.append(f"{bot_id}_SOURCE_POLICY_INVALID")
        for token in FORBIDDEN_TOKENS:
            if token in source:
                forbidden_hits.append(f"{bot_id}:{token}")
        owner = owners[bot_id]
        bot_report[bot_id] = {
            "path": relative,
            "semantic_role": owner.semantic_role,
            "required_evidence_count": len(owner.required_evidence),
            "required_capability_count": len(caps),
            "capability_hit_count": len(hits),
            "capability_hits": hits,
            "thin_wrapper": bot_id in thin_wrappers,
        }
    if forbidden_hits:
        blockers.append("FORBIDDEN_EXECUTION_SURFACE")

    state = "PASS" if not blockers else "HOLD"
    payload = {
        "schema": "q4r3_team_advisor_r26_four_bot_sgrade_lock_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "official_stage": "R2.6",
        "state": state,
        "verdict": "R26_FOUR_BOT_SGRADE_LOCK_PASS" if state == "PASS" else "R26_FOUR_BOT_SGRADE_LOCK_BLOCKED",
        "blockers": blockers,
        "report": {
            "previous_stage_pass_count": sum(1 for row in statuses.values() if row.get("state") == "PASS"),
            "bot_count": len(owners),
            "sgrade_ready_count": 4 if state == "PASS" else 0,
            "unique_owner_count": len({owner.bot_id for owner in owners.values()}),
            "unique_semantic_role_count": len({owner.semantic_role for owner in owners.values()}),
            "thin_wrapper_count": len(thin_wrappers),
            "forbidden_hit_count": len(forbidden_hits),
            "contract_version": CONTRACT_VERSION,
            "source_prefixes": ["cf:", "sheets:"],
            "bots": bot_report,
            "runtime_binding": False,
            "execution_authority": "none",
            "next_route": "R3.1_TEAM_SGRADE_GAP_AUDIT",
            "market_realism_route": "R4_LICO_MARKET_REALISM_AND_R8_INTEGRATED_FORWARD"
        },
        "authority": {
            "observer_only": True,
            "runtime_mutation_performed": False,
            "systemd_mutation_performed": False,
            "execution_authority": "none"
        },
        "action": "hold"
    }
    write(args.output, payload)
    print(json.dumps({
        "state": state,
        "blocker_count": len(blockers),
        "bot_count": len(owners),
        "sgrade_ready_count": payload["report"]["sgrade_ready_count"],
        "thin_wrapper_count": len(thin_wrappers),
        "forbidden_hit_count": len(forbidden_hits)
    }, sort_keys=True))
    return 0 if state == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
