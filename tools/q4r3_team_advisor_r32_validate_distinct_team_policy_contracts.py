#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from canonical.teams.policy_contracts import (
    CANONICAL_SOURCES,
    TEAM_POLICY_REGISTRY,
    TEAM_POLICY_VERSION,
    validate_team_policy_registry,
)

EXPECTED_R31_SHARED_GAPS = {
    "confidence_calibration",
    "counterfactual_team_selection",
    "dynamic_role_assignment",
    "helper_trigger_engine",
    "regime_eligibility_engine",
    "reserve_failover_engine",
    "team_router_ranking",
    "team_specific_policy_contracts",
    "watcher_severity_aggregation",
}
REMAINING_SHARED_GAPS = tuple(sorted(EXPECTED_R31_SHARED_GAPS - {"team_specific_policy_contracts"}))


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
    parser.add_argument("--r31", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    blockers: list[str] = []
    r31 = load(args.r31)
    r31_report = r31.get("report") or {}
    if r31.get("state") != "HOLD" or r31.get("verdict") != "R31_TEAM_SGRADE_GAPS_CLASSIFIED":
        blockers.append("R31_CLASSIFICATION_INVALID")
    if r31_report.get("foundation_ready_count") != 4:
        blockers.append("R31_FOUNDATION_COUNT_INVALID")
    if set(r31_report.get("shared_gaps") or ()) != EXPECTED_R31_SHARED_GAPS:
        blockers.append("R31_SHARED_GAP_SET_INVALID")
    if r31_report.get("team_specific_gap_count") != 12:
        blockers.append("R31_TEAM_SPECIFIC_GAP_COUNT_INVALID")

    policy_errors = list(validate_team_policy_registry())
    blockers.extend(f"POLICY:{error}" for error in policy_errors)

    teams: dict[str, Any] = {}
    identities: set[tuple[Any, ...]] = set()
    for team_id, policy in TEAM_POLICY_REGISTRY.items():
        identity = (policy.policy_family, policy.primary_objective, policy.eligible_regimes)
        identities.add(identity)
        teams[team_id] = {
            "mission": policy.mission,
            "policy_family": policy.policy_family,
            "primary_objective": policy.primary_objective,
            "eligible_regimes": list(policy.eligible_regimes),
            "excluded_regimes": list(policy.excluded_regimes),
            "main_owner": policy.main_owner,
            "support_owner": policy.support_owner,
            "watcher_count": len(policy.watcher_priorities),
            "helper_trigger_count": len(policy.helper_trigger_map),
            "reserve_owner": policy.reserve_owner,
            "recovery_route_count": len(policy.recovery_routes),
            "allowed_actions": sorted(policy.allowed_actions),
            "authority": policy.authority,
            "runtime_enabled": policy.runtime_enabled,
            "execution_authority": policy.execution_authority,
        }
        if policy.runtime_enabled or policy.execution_authority != "none" or policy.authority != "advisory_only":
            blockers.append(f"{team_id}_AUTHORITY_INVALID")

    if len(identities) != 4:
        blockers.append("TEAM_POLICY_IDENTITY_COLLISION")

    state = "PASS" if not blockers else "HOLD"
    payload = {
        "schema": "q4r3_team_advisor_r32_distinct_team_policy_contracts_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "official_stage": "R3.2",
        "state": state,
        "verdict": "R32_DISTINCT_TEAM_POLICY_CONTRACTS_PASS" if state == "PASS" else "R32_DISTINCT_TEAM_POLICY_CONTRACTS_BLOCKED",
        "blockers": blockers,
        "report": {
            "previous_stage": "R3.1",
            "team_count": len(TEAM_POLICY_REGISTRY),
            "policy_contract_ready_count": len(TEAM_POLICY_REGISTRY) if state == "PASS" else 0,
            "distinct_policy_identity_count": len(identities),
            "team_specific_gap_count_before": 12,
            "team_specific_gap_count_after": 0 if state == "PASS" else 12,
            "shared_gap_count_before": 9,
            "shared_gap_count_after": len(REMAINING_SHARED_GAPS) if state == "PASS" else 9,
            "remaining_shared_gaps": list(REMAINING_SHARED_GAPS) if state == "PASS" else sorted(EXPECTED_R31_SHARED_GAPS),
            "contract_version": TEAM_POLICY_VERSION,
            "source_prefixes": list(CANONICAL_SOURCES),
            "embedded_numeric_trading_thresholds": False,
            "teams": teams,
            "sgrade_ready_count": 0,
            "runtime_binding": False,
            "execution_authority": "none",
            "next_route": "R3.3_DYNAMIC_ROLE_HELPER_AND_RESERVE_ENGINE" if state == "PASS" else "R3.2_REPAIR_DISTINCT_TEAM_POLICY_CONTRACTS",
        },
        "authority": {
            "observer_only": True,
            "runtime_mutation_performed": False,
            "systemd_mutation_performed": False,
            "execution_authority": "none",
        },
        "action": "hold",
    }
    write(args.output, payload)
    print(json.dumps({
        "state": state,
        "team_count": payload["report"]["team_count"],
        "policy_contract_ready_count": payload["report"]["policy_contract_ready_count"],
        "distinct_policy_identity_count": payload["report"]["distinct_policy_identity_count"],
        "remaining_shared_gap_count": payload["report"]["shared_gap_count_after"],
        "blocker_count": len(blockers),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
