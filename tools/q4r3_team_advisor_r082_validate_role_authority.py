#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from canonical.teams.binding import ROLE_AUTHORITY_VERSION, TeamDecisionContext, build_binding_plan
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


def context() -> TeamDecisionContext:
    return TeamDecisionContext(
        decision_id="r082.decision",
        position_id="r082.position",
        event_id="r082.event",
        parent_event_id="r082.parent",
        event_ts="2026-07-15T00:00:00+00:00",
        symbol="BTCUSDT",
        side="long",
        strategy_id="strategy.r082",
        method_id="method.r082",
        skill_id="skill.r082",
        data_state="FRESH",
        freshness_ms=10,
        latency_ms=20,
        source_ids=("src:r082",),
        evidence_ids=("evidence:r082",),
    )


def evidence() -> dict[str, dict[str, Any]]:
    return {
        "LBot": {"trend_thesis": "continuation", "hold_reduce_posture": "hold", "invalidation_flags": []},
        "MBot": {"method_fit": "fit", "range_state": "trend", "timing_quality": 0.8, "conflict_flags": []},
        "OBot": {"breakout_quality": 0.8, "anomaly_flags": [], "mfe_mae_context": {}},
        "SBot": {"hard_violations": [], "soft_penalties": [], "risk_state": "normal"},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--r081", type=Path, required=True)
    parser.add_argument("--binding-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    r081 = load(args.r081)
    blockers: list[str] = []
    if r081.get("state") != "PASS" or r081.get("verdict") != "R081_RESPONSE_LINEAGE_LATENCY_CLOSED":
        blockers.append("R081_NOT_PASS")
    report081 = r081.get("report") or {}
    if report081.get("bot_response_count") != 16 or report081.get("lineage_check_count") != 240:
        blockers.append("R081_LINEAGE_PARITY_INVALID")

    teams: dict[str, Any] = {}
    decision_authority_count = 0
    watch_only_count = 0
    hard_veto_capability_count = 0
    helper_non_voting_count = 0

    for team_id, spec in TEAM_REGISTRY.items():
        helper_bot = spec.conditional_helpers[0]
        helper_trigger = spec.helper_triggers[0]
        plan = build_binding_plan(
            team_id,
            context(),
            evidence(),
            helper_bot=helper_bot,
            helper_trigger=helper_trigger,
        )
        internal = plan.all_internal_requests
        core = plan.decision_requests + plan.watch_requests
        if len(core) != 4 or {item.bot_id for item in core} != {"LBot", "MBot", "OBot", "SBot"}:
            blockers.append(f"{team_id}:FOUR_BOT_COVERAGE_INVALID")
        if len(plan.decision_requests) != 2:
            blockers.append(f"{team_id}:DECISION_AUTHORITY_COUNT_INVALID")
        if len(plan.watch_requests) != 2:
            blockers.append(f"{team_id}:WATCH_COUNT_INVALID")
        if not plan.main.proposal_owner or not plan.main.generic_vote_eligible:
            blockers.append(f"{team_id}:MAIN_AUTHORITY_INVALID")
        if not plan.support.support_validator or not plan.support.generic_vote_eligible:
            blockers.append(f"{team_id}:SUPPORT_AUTHORITY_INVALID")
        if any(not item.watch_only or item.generic_vote_eligible for item in plan.watch_requests):
            blockers.append(f"{team_id}:WATCHER_AUTHORITY_INVALID")
        if plan.helper is None or not plan.helper.helper_only or plan.helper.generic_vote_eligible:
            blockers.append(f"{team_id}:HELPER_AUTHORITY_INVALID")
        sbot = next((item for item in internal if item.bot_id == "SBot" and not item.helper_only), None)
        if sbot is None or not sbot.hard_veto_capable:
            blockers.append(f"{team_id}:SBOT_HARD_VETO_CAPABILITY_INVALID")
        if plan.external_proof_watcher != "ZBot" or plan.zbot_team_vote_allowed:
            blockers.append(f"{team_id}:ZBOT_EXTERNAL_POLICY_INVALID")
        if plan.runtime_enabled or plan.execution_authority != "none":
            blockers.append(f"{team_id}:AUTHORITY_SURFACE_INVALID")

        decision_authority_count += len(plan.decision_requests)
        watch_only_count += len(plan.watch_requests)
        hard_veto_capability_count += int(bool(sbot and sbot.hard_veto_capable))
        helper_non_voting_count += int(bool(plan.helper and not plan.helper.generic_vote_eligible))
        teams[team_id] = {
            "main": plan.main.bot_id,
            "support": plan.support.bot_id,
            "watchers": [item.bot_id for item in plan.watch_requests],
            "helper": plan.helper.bot_id if plan.helper else None,
            "generic_decision_authority_count": len(plan.decision_requests),
            "watch_only_count": len(plan.watch_requests),
            "sbot_hard_veto_capable": bool(sbot and sbot.hard_veto_capable),
        }

    source = args.binding_source.read_text(encoding="utf-8")
    forbidden = [token for token in ("create_order(", "place_order(", "cancel_order(", "submit_order(") if token in source]
    if forbidden:
        blockers.append("FORBIDDEN_EXECUTION_SURFACE")

    state = "PASS" if not blockers else "HOLD"
    payload = {
        "schema": "q4r3_team_advisor_r082_role_authority_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": state,
        "verdict": "R082_TEAM_ROLE_AUTHORITY_LOCK_PASS" if state == "PASS" else "R082_TEAM_ROLE_AUTHORITY_BLOCKED",
        "blockers": blockers,
        "report": {
            "team_count": len(teams),
            "role_authority_version": ROLE_AUTHORITY_VERSION,
            "generic_decision_authority_count": decision_authority_count,
            "watch_only_count": watch_only_count,
            "helper_non_voting_count": helper_non_voting_count,
            "sbot_hard_veto_capability_count": hard_veto_capability_count,
            "zbot_external_only": True,
            "teams": teams,
            "next_route": "BUILD_TEAM_PROPOSAL_AGGREGATOR_WITH_ROLE_SEMANTICS",
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
        "blocker_count": len(blockers),
        "team_count": len(teams),
        "decision_authority_count": decision_authority_count,
        "watch_only_count": watch_only_count,
    }, sort_keys=True))
    return 0 if state == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
