#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from canonical.teams.binding import TeamDecisionContext, build_binding_plan, validate_binding_registry
from canonical.teams.registry import TEAM_REGISTRY


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


def sample_context() -> TeamDecisionContext:
    return TeamDecisionContext(
        decision_id="r08.validation",
        position_id="r08.position",
        event_id="r08.event",
        parent_event_id="r08.parent",
        event_ts="2026-07-15T00:00:00+00:00",
        symbol="BTCUSDT",
        side="long",
        strategy_id="strategy.validation",
        method_id="method.validation",
        skill_id="skill.validation",
        data_state="FRESH",
        freshness_ms=1,
        source_ids=("src:r08",),
        evidence_ids=("evidence:r08",),
    )


def sample_evidence() -> dict[str, dict[str, Any]]:
    return {
        "LBot": {"trend_thesis": {}, "hold_reduce_posture": "hold", "invalidation_flags": []},
        "MBot": {"method_fit": {}, "range_state": "trend", "timing_quality": 1.0, "conflict_flags": []},
        "OBot": {"breakout_quality": 1.0, "anomaly_flags": [], "mfe_mae_context": {}},
        "SBot": {"hard_violations": [], "soft_penalties": [], "risk_state": "normal"},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--r05", type=Path, required=True)
    parser.add_argument("--r061", type=Path, required=True)
    parser.add_argument("--r07", type=Path, required=True)
    parser.add_argument("--binding-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    r05 = load(args.r05)
    r061 = load(args.r061)
    r07 = load(args.r07)
    blockers: list[str] = list(validate_binding_registry())

    if r05.get("state") != "PASS" or r05.get("package_owner_count") != 4:
        blockers.append("R05_TEAM_PACKAGE_INVALID")
    if r061.get("state") != "PASS" or r061.get("summary", {}).get("core_owner_count") != 4:
        blockers.append("R061_BOT_BOUNDARY_INVALID")
    if r061.get("summary", {}).get("unresolved_boundary_count") != 0:
        blockers.append("R061_UNRESOLVED_BOUNDARY_PRESENT")
    if r07.get("state") != "PASS" or r07.get("report", {}).get("owner_count") != 4:
        blockers.append("R07_BOT_PACKAGE_INVALID")
    if r07.get("report", {}).get("runtime_binding") is not False:
        blockers.append("R07_RUNTIME_BINDING_ENABLED")

    plans: dict[str, Any] = {}
    for team_id in TEAM_REGISTRY:
        plan = build_binding_plan(team_id, sample_context(), sample_evidence())
        voting = [item.bot_id for item in plan.voting_requests]
        if len(voting) != 4 or set(voting) != {"LBot", "MBot", "OBot", "SBot"}:
            blockers.append(f"{team_id}:BINDING_COVERAGE_INVALID")
        if plan.external_proof_watcher != "ZBot" or plan.zbot_team_vote_allowed:
            blockers.append(f"{team_id}:ZBOT_EXTERNAL_POLICY_INVALID")
        if plan.runtime_enabled or plan.execution_authority != "none":
            blockers.append(f"{team_id}:AUTHORITY_INVALID")
        plans[team_id] = {
            "main": plan.main.bot_id,
            "support": plan.support.bot_id,
            "watchers": [item.bot_id for item in plan.watchers],
            "voting_count": len(plan.voting_requests),
            "external_proof_watcher": plan.external_proof_watcher,
        }

    source = args.binding_source.read_text(encoding="utf-8")
    forbidden = [token for token in ("create_order(", "place_order(", "cancel_order(", "submit_order(") if token in source]
    if forbidden:
        blockers.append("FORBIDDEN_EXECUTION_SURFACE")

    state = "PASS" if not blockers else "HOLD"
    payload = {
        "schema": "q4r3_team_advisor_r08_team_bot_typed_binding_validation_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": state,
        "verdict": "R08_TEAM_BOT_TYPED_BINDING_LOCK_PASS" if state == "PASS" else "R08_TEAM_BOT_TYPED_BINDING_BLOCKED",
        "blockers": blockers,
        "report": {
            "team_binding_count": len(plans),
            "bot_owner_count": 4,
            "plans": plans,
            "zbot_external_only": True,
            "helper_extra_vote_allowed": False,
            "forbidden_hits": forbidden,
            "runtime_binding": False,
            "next_route": "BUILD_TEAM_PROPOSAL_AGGREGATOR_WITHOUT_RUNTIME_ACTIVATION",
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
        "verdict": payload["verdict"],
        "blocker_count": len(blockers),
        "team_binding_count": len(plans),
        "bot_owner_count": 4,
    }, sort_keys=True))
    return 0 if state == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
