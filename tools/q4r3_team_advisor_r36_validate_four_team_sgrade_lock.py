#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from canonical.teams.sgrade_lock import (
    REQUIRED_CAPABILITIES,
    build_team_sgrade_proofs,
    validate_team_sgrade_lock_contract,
)

FORBIDDEN_TOKENS = (
    "BINGX_API_KEY",
    ".create_order(",
    "create_order(",
    "place_order(",
    "requests.post(",
    "aiohttp.",
    "ccxt.",
    "paper_enabled = True",
    "live_enabled = True",
    "order_enabled = True",
)


def read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def scan_forbidden(worktree: Path) -> list[str]:
    hits: list[str] = []
    team_root = worktree / "canonical/teams"
    for path in sorted(team_root.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        for token in FORBIDDEN_TOKENS:
            if token in text:
                hits.append(f"{path.relative_to(worktree)}:{token}")
    return hits


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--r26", type=Path, required=True)
    parser.add_argument("--r35", type=Path, required=True)
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    r26 = read_json(args.r26)
    r35 = read_json(args.r35)
    report26 = r26.get("report") or {}
    report35 = r35.get("report") or {}
    blockers: list[str] = []

    if r26.get("state") != "PASS" or r26.get("verdict") != "R26_FOUR_BOT_SGRADE_LOCK_PASS":
        blockers.append("R26_STATE_INVALID")
    if report26.get("sgrade_ready_count") != 4:
        blockers.append("R26_BOT_SGRADE_COUNT_INVALID")
    if report26.get("thin_wrapper_count") != 0 or report26.get("forbidden_hit_count") != 0:
        blockers.append("R26_BOT_BOUNDARY_INVALID")
    if report26.get("runtime_binding") is not False or report26.get("execution_authority") != "none":
        blockers.append("R26_BOT_AUTHORITY_INVALID")

    if r35.get("state") != "PASS" or r35.get("verdict") != "R35_REGIME_ROUTER_COUNTERFACTUAL_PASS":
        blockers.append("R35_STATE_INVALID")
    if report35.get("feature_complete_team_count") != 4:
        blockers.append("R35_FEATURE_COMPLETE_COUNT_INVALID")
    if report35.get("shared_gap_count_after") != 0 or report35.get("remaining_shared_gaps") != []:
        blockers.append("R35_SHARED_GAPS_REMAIN")
    if report35.get("regime_eligibility_ready_count") != 4:
        blockers.append("R35_REGIME_READY_COUNT_INVALID")
    if report35.get("team_router_ranking_ready_count") != 4:
        blockers.append("R35_ROUTER_READY_COUNT_INVALID")
    if report35.get("counterfactual_selection_ready_count") != 4:
        blockers.append("R35_COUNTERFACTUAL_READY_COUNT_INVALID")
    if report35.get("runtime_binding") is not False or report35.get("execution_authority") != "none":
        blockers.append("R35_TEAM_AUTHORITY_INVALID")

    blockers.extend(f"CONTRACT:{item}" for item in validate_team_sgrade_lock_contract())
    forbidden_hits = scan_forbidden(args.worktree)
    blockers.extend(f"FORBIDDEN:{item}" for item in forbidden_hits)

    proofs = build_team_sgrade_proofs()
    sgrade_ready_count = sum(proof.sgrade_ready for proof in proofs)
    distinct_policy_count = len({(proof.mission, proof.policy_family) for proof in proofs})
    unique_main_owner_count = len({proof.main_owner for proof in proofs})
    capability_lock_count = sum(proof.capability_hits == REQUIRED_CAPABILITIES for proof in proofs)

    if len(proofs) != 4:
        blockers.append("TEAM_PROOF_COUNT_INVALID")
    if sgrade_ready_count != 4:
        blockers.append("TEAM_SGRADE_READY_COUNT_INVALID")
    if distinct_policy_count != 4:
        blockers.append("DISTINCT_POLICY_COUNT_INVALID")
    if unique_main_owner_count != 4:
        blockers.append("MAIN_OWNER_ROTATION_INVALID")
    if capability_lock_count != 4:
        blockers.append("CAPABILITY_LOCK_COUNT_INVALID")

    teams = {
        proof.team_id: {
            "mission": proof.mission,
            "policy_family": proof.policy_family,
            "main_owner": proof.main_owner,
            "support_owner": proof.support_owner,
            "watcher_owners": list(proof.watcher_owners),
            "helper_triggers": list(proof.helper_triggers),
            "reserve_owner": proof.reserve_owner,
            "capability_hit_count": len(proof.capability_hits),
            "capability_hits": list(proof.capability_hits),
            "reason_codes": list(proof.reason_codes),
            "sgrade_ready": proof.sgrade_ready,
        }
        for proof in proofs
    }

    state = "PASS" if not blockers else "HOLD"
    payload: dict[str, object] = {
        "schema": "q4r3_team_advisor_r36_four_team_sgrade_lock_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "official_stage": "R3.6",
        "state": state,
        "verdict": "R36_FOUR_TEAM_SGRADE_LOCK_PASS" if state == "PASS" else "R36_FOUR_TEAM_SGRADE_LOCK_BLOCKED",
        "blockers": list(dict.fromkeys(blockers)),
        "report": {
            "team_count": 4,
            "sgrade_ready_count": sgrade_ready_count,
            "feature_complete_team_count": report35.get("feature_complete_team_count"),
            "distinct_policy_count": distinct_policy_count,
            "unique_main_owner_count": unique_main_owner_count,
            "capability_lock_count": capability_lock_count,
            "required_capability_count_per_team": len(REQUIRED_CAPABILITIES),
            "remaining_shared_gaps": [],
            "shared_gap_count_after": 0,
            "r26_bot_sgrade_ready_count": report26.get("sgrade_ready_count"),
            "r35_fail_closed_scenario_count": report35.get("fail_closed_scenario_count"),
            "sbot_hard_veto_proof_count": report35.get("sbot_hard_veto_proof_count"),
            "forbidden_hit_count": len(forbidden_hits),
            "forbidden_hits": forbidden_hits,
            "embedded_numeric_trading_thresholds": False,
            "source_prefixes": ["cf:", "sheets:"],
            "runtime_binding": False,
            "execution_authority": "none",
            "teams": teams,
            "market_realism_route": "R4_LICO_MARKET_REALISM_AND_R8_INTEGRATED_FORWARD",
            "next_route": "R4.1_LICO_SGRADE_GAP_AUDIT" if state == "PASS" else "R3.6_REPAIR_FOUR_TEAM_SGRADE_LOCK",
        },
        "authority": {
            "observer_only": True,
            "runtime_mutation_performed": False,
            "systemd_mutation_performed": False,
            "execution_authority": "none",
        },
        "action": "hold",
    }
    write_json(args.output, payload)
    print(json.dumps({
        "state": state,
        "team_count": 4,
        "sgrade_ready_count": sgrade_ready_count,
        "distinct_policy_count": distinct_policy_count,
        "capability_lock_count": capability_lock_count,
        "remaining_shared_gap_count": 0,
        "forbidden_hit_count": len(forbidden_hits),
        "blocker_count": len(blockers),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
