#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from canonical.teams.policy_contracts import TEAM_POLICY_REGISTRY
from canonical.teams.role_engine import (
    REMAINING_SHARED_GAPS,
    ROLE_ENGINE_VERSION,
    RoleAssignmentRequest,
    assign_team_roles,
    validate_role_engine_contract,
)

SOURCES = ("cf:r33", "sheets:r33")
EVIDENCE = ("evidence:r33",)
EXPECTED_GAPS = {
    "confidence_calibration", "counterfactual_team_selection",
    "dynamic_role_assignment", "helper_trigger_engine",
    "regime_eligibility_engine", "reserve_failover_engine",
    "team_router_ranking", "watcher_severity_aggregation",
}


def load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def request(team_id: str, **kwargs: object) -> RoleAssignmentRequest:
    return RoleAssignmentRequest(
        team_id=team_id, regime=str(kwargs.pop("regime", "test_regime")),
        source_ids=kwargs.pop("source_ids", SOURCES),
        evidence_ids=kwargs.pop("evidence_ids", EVIDENCE), **kwargs,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--r32", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    blockers: list[str] = []
    r32 = load(args.r32)
    report32 = r32.get("report") or {}
    if r32.get("state") != "PASS" or r32.get("verdict") != "R32_DISTINCT_TEAM_POLICY_CONTRACTS_PASS":
        blockers.append("R32_NOT_PASS")
    if report32.get("policy_contract_ready_count") != 4:
        blockers.append("R32_POLICY_COUNT_INVALID")
    if set(report32.get("remaining_shared_gaps") or ()) != EXPECTED_GAPS:
        blockers.append("R32_GAP_SET_INVALID")
    blockers.extend(f"ROLE:{item}" for item in validate_role_engine_contract())

    canonical_ready = 0
    helper_ready = 0
    teams: dict[str, dict] = {}
    for team_id, policy in TEAM_POLICY_REGISTRY.items():
        canonical = assign_team_roles(request(team_id))
        trigger = next(iter(policy.helper_trigger_map))
        helper = assign_team_roles(request(team_id, active_triggers=(trigger,)))
        canonical_ready += int(canonical.decision_ready)
        helper_ready += int(helper.decision_ready and helper.helper == policy.helper_trigger_map[trigger])
        teams[team_id] = {
            "main": canonical.canonical_main, "support": canonical.canonical_support,
            "watchers": list(canonical.active_watchers), "helper": helper.helper,
            "helper_trigger": helper.helper_trigger, "reserve": policy.reserve_owner,
        }

    failures = (
        assign_team_roles(request("AlphaTeam", source_ids=("cf:r33",))),
        assign_team_roles(request("BetaTeam", data_state="STALE")),
        assign_team_roles(request("GammaTeam", unavailable_bots=("OBot",))),
        assign_team_roles(request("AlphaTeam", unavailable_bots=("MBot",))),
        assign_team_roles(request("BetaTeam", unavailable_bots=("SBot",))),
        assign_team_roles(request("GammaTeam", active_triggers=("unknown",))),
    )
    if any(not plan.fail_closed or plan.action != "hold" for plan in failures):
        blockers.append("FAIL_CLOSED_SCENARIO_INVALID")
    reserve = assign_team_roles(request("DeltaTeam", unavailable_bots=("SBot",)))
    if not (reserve.reserve_used and reserve.mode == "reserve_recovery" and reserve.fail_closed):
        blockers.append("DELTA_RESERVE_INVALID")
    if canonical_ready != 4 or helper_ready != 4:
        blockers.append("ROLE_ASSIGNMENT_COUNT_INVALID")

    state = "PASS" if not blockers else "HOLD"
    payload = {
        "schema": "q4r3_team_advisor_r33_dynamic_role_helper_reserve_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(), "official_stage": "R3.3",
        "state": state,
        "verdict": "R33_DYNAMIC_ROLE_HELPER_RESERVE_PASS" if state == "PASS" else "R33_DYNAMIC_ROLE_HELPER_RESERVE_BLOCKED",
        "blockers": blockers,
        "report": {
            "team_count": 4, "canonical_assignment_ready_count": canonical_ready,
            "helper_assignment_ready_count": helper_ready,
            "dynamic_role_engine_ready_count": 4 if state == "PASS" else 0,
            "helper_trigger_engine_ready": state == "PASS",
            "reserve_failover_engine_ready": state == "PASS",
            "delta_reserve_mode": "reserve_recovery_hold",
            "fail_closed_scenario_count": len(failures) + 1,
            "shared_gap_count_before": 8,
            "shared_gap_count_after": len(REMAINING_SHARED_GAPS) if state == "PASS" else 8,
            "closed_shared_gaps": ["dynamic_role_assignment", "helper_trigger_engine", "reserve_failover_engine"] if state == "PASS" else [],
            "remaining_shared_gaps": list(REMAINING_SHARED_GAPS) if state == "PASS" else sorted(EXPECTED_GAPS),
            "contract_version": ROLE_ENGINE_VERSION, "cf_sheets_parity_required": True,
            "embedded_numeric_trading_thresholds": False, "teams": teams,
            "sgrade_ready_count": 0, "runtime_binding": False, "execution_authority": "none",
            "next_route": "R3.4_WATCHER_SEVERITY_AND_CONFIDENCE_CALIBRATION" if state == "PASS" else "R3.3_REPAIR_DYNAMIC_ROLE_HELPER_RESERVE",
        },
        "authority": {"observer_only": True, "runtime_mutation_performed": False, "systemd_mutation_performed": False, "execution_authority": "none"},
        "action": "hold",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.output.with_suffix(args.output.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, args.output)
    print(json.dumps({"state": state, "team_count": 4, "dynamic_role_engine_ready_count": payload["report"]["dynamic_role_engine_ready_count"], "helper_assignment_ready_count": helper_ready, "fail_closed_scenario_count": len(failures) + 1, "remaining_shared_gap_count": payload["report"]["shared_gap_count_after"], "blocker_count": len(blockers)}, sort_keys=True))
    return 0 if state == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
