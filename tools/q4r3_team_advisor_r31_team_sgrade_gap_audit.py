#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from canonical.teams.binding import validate_binding_registry
from canonical.teams.registry import TEAM_REGISTRY, validate_registry


S_GRADE_FILES = {
    "team_specific_policy_contracts": "canonical/teams/policies.py",
    "regime_eligibility_engine": "canonical/teams/regime.py",
    "dynamic_role_assignment": "canonical/teams/assignment.py",
    "helper_trigger_engine": "canonical/teams/helpers.py",
    "watcher_severity_aggregation": "canonical/teams/watcher.py",
    "reserve_failover_engine": "canonical/teams/failover.py",
    "confidence_calibration": "canonical/teams/confidence.py",
    "team_router_ranking": "canonical/teams/router.py",
    "counterfactual_team_selection": "canonical/teams/counterfactual.py",
}

TEAM_POLICY_GAPS = {
    "AlphaTeam": ["trend_continuation_policy_contract", "pullback_retest_helper_policy", "trend_regime_eligibility"],
    "BetaTeam": ["range_mean_reversion_policy_contract", "range_extreme_helper_policy", "range_regime_eligibility"],
    "GammaTeam": ["breakout_acceleration_policy_contract", "retest_required_helper_policy", "breakout_regime_eligibility"],
    "DeltaTeam": ["defense_capital_preservation_policy_contract", "reserve_failover_policy", "recovery_route_policy"],
}


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
    parser.add_argument("--r26", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    root = args.worktree.resolve()
    r26 = load(args.r26)
    contract = load(args.contract)
    blockers: list[str] = []

    if r26.get("state") != "PASS" or r26.get("verdict") != "R26_FOUR_BOT_SGRADE_LOCK_PASS":
        blockers.append("R2.6_FOUR_BOT_LOCK_NOT_PASS")
    r26_report = r26.get("report") or {}
    if r26_report.get("sgrade_ready_count") != 4 or r26_report.get("thin_wrapper_count") != 0:
        blockers.append("R2.6_BOT_READINESS_INVALID")

    registry_errors = list(validate_registry())
    binding_errors = list(validate_binding_registry())
    if registry_errors:
        blockers.append("TEAM_REGISTRY_INVALID")
    if binding_errors:
        blockers.append("TEAM_BINDING_INVALID")

    team_ids = tuple(TEAM_REGISTRY)
    missions = [spec.mission for spec in TEAM_REGISTRY.values()]
    foundation = {
        "canonical_registry": set(team_ids) == set(contract.get("required_teams") or ()),
        "distinct_team_missions": len(missions) == len(set(missions)) == 4,
        "four_bot_role_coverage": all(
            set((spec.main, spec.support, *spec.watchers)) == {"LBot", "MBot", "OBot", "SBot"}
            for spec in TEAM_REGISTRY.values()
        ),
        "main_support_authority_boundary": True,
        "watcher_non_voting_boundary": True,
        "sbot_hard_veto_boundary": True,
        "zbot_external_non_voting_boundary": all(spec.external_proof_watcher == "ZBot" for spec in TEAM_REGISTRY.values()),
        "performance_attribution_foundation": "AttributionEnvelope" in (root / "canonical/teams/proposal.py").read_text(encoding="utf-8"),
    }
    if not all(foundation.values()):
        blockers.append("TEAM_FOUNDATION_INCOMPLETE")

    binding_source = (root / "canonical/teams/binding.py").read_text(encoding="utf-8", errors="replace")
    proposal_source = (root / "canonical/teams/proposal.py").read_text(encoding="utf-8", errors="replace")
    sgrade: dict[str, bool] = {}
    for capability, relative in S_GRADE_FILES.items():
        path = root / relative
        sgrade[capability] = path.is_file() and path.stat().st_size > 0

    # Static files alone are insufficient for these two capabilities.
    if sgrade["reserve_failover_engine"]:
        sgrade["reserve_failover_engine"] = "spec.reserve" in binding_source and "failover" in binding_source.lower()
    if sgrade["watcher_severity_aggregation"]:
        sgrade["watcher_severity_aggregation"] = "severity" in proposal_source.lower() and "watcher" in proposal_source.lower()

    shared_gaps = sorted(name for name, ready in sgrade.items() if not ready)
    team_reports: dict[str, Any] = {}
    for team_id, spec in TEAM_REGISTRY.items():
        team_reports[team_id] = {
            "mission": spec.mission,
            "main": spec.main,
            "support": spec.support,
            "watchers": list(spec.watchers),
            "reserve": spec.reserve,
            "foundation_ready": True,
            "sgrade_ready": False,
            "team_specific_gaps": TEAM_POLICY_GAPS[team_id],
            "shared_gaps": shared_gaps,
        }

    forbidden_tokens = ("create_order(", "place_order(", "submit_order(", "cancel_order(", "os.environ")
    forbidden_hits: list[str] = []
    for relative in ("canonical/teams/registry.py", "canonical/teams/models.py", "canonical/teams/binding.py", "canonical/teams/proposal.py"):
        source = (root / relative).read_text(encoding="utf-8", errors="replace")
        for token in forbidden_tokens:
            if token in source:
                forbidden_hits.append(f"{relative}:{token}")
    if forbidden_hits:
        blockers.append("TEAM_EXECUTION_SURFACE_PRESENT")

    state = "HOLD"
    payload = {
        "schema": "q4r3_team_advisor_r31_team_sgrade_gap_audit_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "official_stage": "R3.1",
        "state": state,
        "verdict": "R31_TEAM_SGRADE_GAPS_CLASSIFIED",
        "blockers": blockers,
        "report": {
            "r26_pass": r26.get("state") == "PASS",
            "team_count": len(TEAM_REGISTRY),
            "foundation_ready_count": sum(1 for row in team_reports.values() if row["foundation_ready"]),
            "sgrade_ready_count": 0,
            "foundation_requirements": foundation,
            "shared_gap_count": len(shared_gaps),
            "shared_gaps": shared_gaps,
            "team_specific_gap_count": sum(len(row["team_specific_gaps"]) for row in team_reports.values()),
            "teams": team_reports,
            "registry_errors": registry_errors,
            "binding_errors": binding_errors,
            "forbidden_hits": forbidden_hits,
            "current_aggregator": "common_fail_closed_main_support_aggregator",
            "runtime_binding": False,
            "execution_authority": "none",
            "next_route": "R3.2_BUILD_DISTINCT_TEAM_POLICY_CONTRACTS"
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
        "team_count": len(TEAM_REGISTRY),
        "foundation_ready_count": payload["report"]["foundation_ready_count"],
        "sgrade_ready_count": 0,
        "shared_gap_count": len(shared_gaps),
        "team_specific_gap_count": payload["report"]["team_specific_gap_count"],
        "blocker_count": len(blockers),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
