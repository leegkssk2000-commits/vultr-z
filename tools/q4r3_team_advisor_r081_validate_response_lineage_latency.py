#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from canonical.teams.binding import BOT_CLASS_REGISTRY, TeamDecisionContext, build_binding_plan
from canonical.teams.registry import TEAM_REGISTRY

LINEAGE_FIELDS = (
    "decision_id", "position_id", "event_id", "parent_event_id", "event_ts",
    "symbol", "side", "strategy_id", "method_id", "skill_id", "team_id",
    "team_role", "data_state", "freshness_ms", "latency_ms",
)


def write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def context() -> TeamDecisionContext:
    return TeamDecisionContext(
        decision_id="r081.decision",
        position_id="r081.position",
        event_id="r081.event",
        parent_event_id="r081.parent",
        event_ts="2026-07-15T00:00:00+00:00",
        symbol="BTCUSDT",
        side="long",
        strategy_id="strategy.r081",
        method_id="method.r081",
        skill_id="skill.r081",
        data_state="FRESH",
        freshness_ms=10,
        latency_ms=20,
        source_ids=("src:r081",),
        evidence_ids=("evidence:r081",),
    )


def evidence() -> dict[str, dict[str, Any]]:
    return {
        "LBot": {
            "trend_thesis": "continuation", "hold_reduce_posture": "hold",
            "invalidation_flags": [], "suggested_action": "hold", "confidence": 0.7,
        },
        "MBot": {
            "method_fit": "fit", "range_state": "trend", "timing_quality": 0.8,
            "conflict_flags": [], "suggested_action": "hold", "confidence": 0.7,
        },
        "OBot": {
            "breakout_quality": 0.8, "anomaly_flags": [], "mfe_mae_context": {},
            "suggested_action": "hold", "confidence": 0.7,
        },
        "SBot": {
            "hard_violations": [], "soft_penalties": [], "risk_state": "normal",
            "suggested_action": "hold", "confidence": 0.7,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    blockers: list[str] = []
    checks = 0
    team_reports: dict[str, Any] = {}
    for team_id in TEAM_REGISTRY:
        plan = build_binding_plan(team_id, context(), evidence())
        responses: dict[str, Any] = {}
        for bound in plan.voting_requests:
            response = BOT_CLASS_REGISTRY[bound.bot_id]().evaluate(bound.request)
            if response.bot_id != bound.bot_id:
                blockers.append(f"{team_id}:{bound.bot_id}:BOT_ID_MISMATCH")
            if response.contract_version != "canonical-bot/1.1.0":
                blockers.append(f"{team_id}:{bound.bot_id}:CONTRACT_VERSION_MISMATCH")
            for field in LINEAGE_FIELDS:
                checks += 1
                if getattr(response, field) != getattr(bound.request, field):
                    blockers.append(f"{team_id}:{bound.bot_id}:LINEAGE_MISMATCH:{field}")
            if response.authority != "advisory_only" or response.direct_order_allowed:
                blockers.append(f"{team_id}:{bound.bot_id}:AUTHORITY_INVALID")
            responses[bound.bot_id] = {
                "team_role": response.team_role,
                "contract_version": response.contract_version,
                "freshness_ms": response.freshness_ms,
                "latency_ms": response.latency_ms,
            }
        team_reports[team_id] = responses

    state = "PASS" if not blockers else "HOLD"
    payload = {
        "schema": "q4r3_team_advisor_r081_response_lineage_latency_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": state,
        "verdict": "R081_RESPONSE_LINEAGE_LATENCY_CLOSED" if state == "PASS" else "R081_RESPONSE_LINEAGE_LATENCY_BLOCKED",
        "blockers": blockers,
        "report": {
            "team_count": len(team_reports),
            "bot_response_count": sum(len(value) for value in team_reports.values()),
            "lineage_field_count": len(LINEAGE_FIELDS),
            "lineage_check_count": checks,
            "contract_version": "canonical-bot/1.1.0",
            "latency_required": True,
            "response_lineage_complete": not blockers,
            "teams": team_reports,
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
        "blocker_count": len(blockers),
        "bot_response_count": payload["report"]["bot_response_count"],
        "lineage_check_count": checks,
    }, sort_keys=True))
    return 0 if state == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
