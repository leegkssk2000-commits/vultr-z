#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

UTC = timezone.utc
EXPECTED_TEAMS = {"AlphaTeam", "BetaTeam", "GammaTeam", "DeltaTeam"}
EXPECTED_MAIN = {
    "AlphaTeam": "LBot",
    "BetaTeam": "MBot",
    "GammaTeam": "OBot",
    "DeltaTeam": "SBot",
}
EXPECTED_SUPPORT = {
    "AlphaTeam": "MBot",
    "BetaTeam": "LBot",
    "GammaTeam": "MBot",
    "DeltaTeam": "OBot",
}
TEAM_BOTS = {"LBot", "MBot", "OBot", "SBot"}


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return digest


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def validate(contract: dict[str, Any], recovery: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    blockers: list[str] = []
    teams = contract.get("teams")
    if contract.get("schema") != "q4r3_team_canonical_contract_v1":
        blockers.append("CONTRACT_SCHEMA_INVALID")
    if contract.get("status") != "design_locked_not_activated":
        blockers.append("CONTRACT_STATUS_INVALID")
    if not isinstance(teams, dict) or set(teams) != EXPECTED_TEAMS:
        blockers.append("TEAM_SET_INVALID")
        teams = teams if isinstance(teams, dict) else {}

    rules = contract.get("global_rules") or {}
    if rules.get("team_bots") != ["LBot", "MBot", "OBot", "SBot"]:
        blockers.append("TEAM_BOT_SET_INVALID")
    if rules.get("zbot_is_team_bot") is not False:
        blockers.append("ZBOT_TEAM_MEMBERSHIP_INVALID")
    if rules.get("zbot_team_vote_allowed") is not False:
        blockers.append("ZBOT_VOTE_POLICY_INVALID")
    if rules.get("helper_extra_vote_allowed") is not False:
        blockers.append("HELPER_DOUBLE_VOTE_POLICY_INVALID")
    if rules.get("sbot_hard_veto_precedence") is not True:
        blockers.append("SBOT_VETO_POLICY_INVALID")
    if rules.get("runtime_activation_allowed") is not False:
        blockers.append("R04_RUNTIME_ACTIVATION_FORBIDDEN")
    if rules.get("execution_authority") != "none":
        blockers.append("EXECUTION_AUTHORITY_INVALID")

    team_summary: dict[str, Any] = {}
    main_bots: list[str] = []
    for team in sorted(EXPECTED_TEAMS):
        row = teams.get(team) if isinstance(teams, dict) else None
        if not isinstance(row, dict):
            blockers.append(f"{team}:CONTRACT_MISSING")
            continue
        main = row.get("main")
        support = row.get("support")
        watchers = row.get("watchers")
        external = row.get("external_proof_watcher")
        helpers = row.get("conditional_helpers")
        triggers = row.get("helper_triggers")
        if main != EXPECTED_MAIN[team]:
            blockers.append(f"{team}:MAIN_INVALID")
        if support != EXPECTED_SUPPORT[team]:
            blockers.append(f"{team}:SUPPORT_INVALID")
        if main not in TEAM_BOTS or support not in TEAM_BOTS or main == support:
            blockers.append(f"{team}:MAIN_SUPPORT_SET_INVALID")
        if not isinstance(watchers, list) or len(watchers) != 2:
            blockers.append(f"{team}:INTERNAL_WATCHER_COUNT_INVALID")
            watchers = watchers if isinstance(watchers, list) else []
        if any(bot not in TEAM_BOTS for bot in watchers):
            blockers.append(f"{team}:INTERNAL_WATCHER_INVALID")
        if external != "ZBot":
            blockers.append(f"{team}:EXTERNAL_PROOF_WATCHER_INVALID")
        if not isinstance(helpers, list) or not helpers or any(bot not in TEAM_BOTS for bot in helpers):
            blockers.append(f"{team}:HELPER_POLICY_INVALID")
        if not isinstance(triggers, list) or not triggers:
            blockers.append(f"{team}:HELPER_TRIGGER_MISSING")
        main_bots.append(str(main))
        team_summary[team] = {
            "mission": row.get("mission"),
            "main": main,
            "support": support,
            "internal_watchers": watchers,
            "external_proof_watcher": external,
            "conditional_helpers": helpers,
            "helper_trigger_count": len(triggers) if isinstance(triggers, list) else 0,
        }

    if set(main_bots) != TEAM_BOTS or len(main_bots) != 4:
        blockers.append("MAIN_ROLE_ROTATION_INVALID")

    required_fields = contract.get("team_proposal_required_fields")
    required_minimum = {
        "decision_id", "position_id", "strategy_id", "method_id", "skill_id",
        "team_id", "main_thesis", "main_action", "support_result", "watcher_flags",
        "confidence", "abstain", "veto", "reason_codes", "freshness_ms", "latency_ms",
        "source_ids", "evidence_ids",
    }
    if not isinstance(required_fields, list) or not required_minimum.issubset(set(required_fields)):
        blockers.append("TEAM_PROPOSAL_CONTRACT_INCOMPLETE")

    if recovery.get("schema") != "q4r3_team_advisor_r03_team_assignment_recovery_v1":
        blockers.append("R03_EVIDENCE_SCHEMA_INVALID")
    if recovery.get("source_sha_parity_count") != 2:
        blockers.append("R03_SOURCE_PARITY_INVALID")
    if recovery.get("complete_explicit_assignment_count") != 0:
        blockers.append("R03_EXPLICIT_ASSIGNMENT_ASSUMPTION_INVALID")
    if recovery.get("next_route") != "BUILD_CANONICAL_TEAM_CONTRACT_FROM_RECOVERED_EVIDENCE_WITHOUT_GUESSING":
        blockers.append("R03_NEXT_ROUTE_INVALID")

    basis = contract.get("source_basis") or {}
    if basis.get("runtime_explicit_assignment_count") != 0:
        blockers.append("SOURCE_BASIS_EXPLICIT_COUNT_INVALID")
    if basis.get("runtime_weight_inference_used") is not False:
        blockers.append("RUNTIME_WEIGHT_INFERENCE_FORBIDDEN")
    if not basis.get("approved_semantic_contract"):
        blockers.append("APPROVED_SEMANTIC_CONTRACT_MISSING")

    summary = {
        "team_count": len(team_summary),
        "main_role_rotation": sorted(main_bots),
        "zbot_external_only": rules.get("zbot_is_team_bot") is False and rules.get("zbot_team_vote_allowed") is False,
        "team_summary": team_summary,
        "proposal_required_field_count": len(required_fields) if isinstance(required_fields, list) else 0,
    }
    return blockers, summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--recovery", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    contract = read_json(args.contract)
    recovery = read_json(args.recovery)
    blockers, summary = validate(contract, recovery)
    passed = not blockers
    payload = {
        "schema": "q4r3_team_advisor_r04_canonical_team_contract_validation_v1",
        "generated_at": now_iso(),
        "state": "PASS" if passed else "HOLD",
        "verdict": "R04_CANONICAL_TEAM_CONTRACT_LOCK_PASS" if passed else "R04_CANONICAL_TEAM_CONTRACT_INVALID",
        "contract_sha256": sha256(args.contract),
        "recovery_sha256": sha256(args.recovery),
        "blockers": blockers,
        "summary": summary,
        "authority": {
            "observer_only": True,
            "runtime_mutation_performed": False,
            "systemd_mutation_performed": False,
            "paper_enabled": False,
            "live_enabled": False,
            "execution_authority": "none",
        },
        "action": "hold",
    }
    atomic_json(args.output, payload)
    print(json.dumps({
        "state": payload["state"],
        "verdict": payload["verdict"],
        "blocker_count": len(blockers),
        "team_count": summary["team_count"],
        "zbot_external_only": summary["zbot_external_only"],
    }, ensure_ascii=False, sort_keys=True))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
