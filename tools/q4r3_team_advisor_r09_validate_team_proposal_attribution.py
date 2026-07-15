#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from canonical.teams.binding import TeamDecisionContext, build_binding_plan
from canonical.teams.proposal import TEAM_PROPOSAL_VERSION, build_team_proposal
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
        decision_id="r09.decision", position_id="r09.position", event_id="r09.event",
        parent_event_id="r09.parent", event_ts="2026-07-15T00:00:00+00:00",
        symbol="BTCUSDT", side="long", strategy_id="strategy.r09",
        method_id="method.r09", skill_id="skill.r09", data_state="FRESH",
        freshness_ms=10, latency_ms=20, source_ids=("src:r09",),
        evidence_ids=("evidence:r09",),
    )


def evidence() -> dict[str, dict[str, Any]]:
    return {
        "LBot": {"trend_thesis": "continuation", "hold_reduce_posture": "hold", "invalidation_flags": [], "suggested_action": "hold", "confidence": 0.8},
        "MBot": {"method_fit": "fit", "range_state": "trend", "timing_quality": 0.9, "conflict_flags": [], "suggested_action": "hold", "confidence": 0.7},
        "OBot": {"breakout_quality": 0.8, "anomaly_flags": [], "mfe_mae_context": {}, "suggested_action": "hold", "confidence": 0.6},
        "SBot": {"hard_violations": [], "soft_penalties": [], "risk_state": "normal", "suggested_action": "hold", "confidence": 0.9},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--r082", type=Path, required=True)
    parser.add_argument("--matrix", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    r082 = load(args.r082)
    matrix = load(args.matrix)
    blockers: list[str] = []
    if r082.get("state") != "PASS" or r082.get("verdict") != "R082_TEAM_ROLE_AUTHORITY_LOCK_PASS":
        blockers.append("R082_ROLE_AUTHORITY_NOT_PASS")
    expected = {
        "team_count": 4,
        "generic_decision_authority_count": 8,
        "watch_only_count": 8,
        "helper_non_voting_count": 4,
        "sbot_hard_veto_capability_count": 4,
    }
    report082 = r082.get("report") or {}
    for key, value in expected.items():
        if report082.get(key) != value:
            blockers.append(f"R082_{key.upper()}_INVALID")

    required_layers = {"strategy", "method", "skill", "team", "team_bot", "ZBot", "Zico", "Lico", "Zlice"}
    layers = matrix.get("layers") or {}
    if matrix.get("schema") != "q4r3_performance_attribution_matrix_v1" or set(layers) != required_layers:
        blockers.append("PERFORMANCE_MATRIX_INVALID")
    zlice = matrix.get("zlice_role") or {}
    if zlice.get("canonical_role") != "append_only_evidence_lineage_replay_and_outcome_join":
        blockers.append("ZLICE_ROLE_INVALID")
    if zlice.get("signal_generation_allowed") is not False or zlice.get("order_authority") != "none":
        blockers.append("ZLICE_AUTHORITY_INVALID")

    proposals: dict[str, Any] = {}
    proposal_ids: set[str] = set()
    attribution_ids: set[str] = set()
    for team_id in TEAM_REGISTRY:
        proposal = build_team_proposal(build_binding_plan(team_id, context(), evidence()))
        if proposal.contract_version != TEAM_PROPOSAL_VERSION:
            blockers.append(f"{team_id}:VERSION_INVALID")
        if proposal.proposed_action != "hold" or proposal.support_result != "confirm":
            blockers.append(f"{team_id}:AGGREGATION_INVALID")
        if len(proposal.watcher_observations) != 2:
            blockers.append(f"{team_id}:WATCHER_COUNT_INVALID")
        types = [item.component_type for item in proposal.attribution.component_refs]
        if types.count("team_bot") != 4:
            blockers.append(f"{team_id}:TEAM_BOT_ATTRIBUTION_INVALID")
        for name in ("strategy", "method", "skill", "team"):
            if types.count(name) != 1:
                blockers.append(f"{team_id}:{name.upper()}_ATTRIBUTION_INVALID")
        proposal_ids.add(proposal.proposal_id)
        attribution_ids.add(proposal.attribution.attribution_id)
        proposals[team_id] = {
            "proposal_id": proposal.proposal_id,
            "attribution_id": proposal.attribution.attribution_id,
            "main": proposal.main_bot_id,
            "support": proposal.support_bot_id,
            "watchers": [item.bot_id for item in proposal.watcher_observations],
            "action": proposal.proposed_action,
            "component_ref_count": len(proposal.attribution.component_refs),
        }
    if len(proposal_ids) != 4 or len(attribution_ids) != 4:
        blockers.append("ID_COLLISION")

    state = "PASS" if not blockers else "HOLD"
    payload = {
        "schema": "q4r3_team_advisor_r09_team_proposal_attribution_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": state,
        "verdict": "R09_TEAM_PROPOSAL_ATTRIBUTION_LOCK_PASS" if state == "PASS" else "R09_TEAM_PROPOSAL_ATTRIBUTION_BLOCKED",
        "blockers": blockers,
        "report": {
            "team_proposal_count": len(proposals),
            "unique_proposal_id_count": len(proposal_ids),
            "unique_attribution_id_count": len(attribution_ids),
            "performance_layer_count": len(layers),
            "performance_layers": sorted(layers),
            "single_global_leaderboard_allowed": False,
            "zlice_role": zlice.get("canonical_role"),
            "proposals": proposals,
            "runtime_binding": False,
            "next_route": "R10_ZLICE_EVENT_LEDGER_CORE_THEN_LICO_ZBOT_ZICO_ATTRIBUTION_BINDINGS"
        },
        "authority": {"observer_only": True, "runtime_mutation_performed": False, "systemd_mutation_performed": False, "execution_authority": "none"},
        "action": "hold"
    }
    write(args.output, payload)
    print(json.dumps({"state": state, "blocker_count": len(blockers), "team_proposal_count": len(proposals), "performance_layer_count": len(layers)}, sort_keys=True))
    return 0 if state == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
