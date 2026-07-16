#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

from policy.zbot_shadow_router import build_shadow_observer_plan
from policy.zbot_shadow_types import ShadowObserverPolicy, ShadowSnapshot

SCHEMA = "q4r3_team_advisor_r61_zbot_shadow_observer_integration_gate_v1"
EXPECTED_ROUTES = {
    "market_context_review",
    "risk_review",
    "post_trade_explanation",
    "optimization_candidate_review",
}


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def gate_policy() -> ShadowObserverPolicy:
    return ShadowObserverPolicy(1000, 50, 200, "sheets:zbot:shadow_observer_policy")


def snapshot(snapshot_id: str, observed_at_ms: int, closed_count: int, ledger_rows: int) -> ShadowSnapshot:
    return ShadowSnapshot(
        snapshot_id=snapshot_id,
        epoch_id="q4.shadow.validator",
        observed_at_ms=observed_at_ms,
        schema_version="r61-validator",
        shadow_source_ref="cf:shadow:status",
        market_source_ref="cf:market:snapshot",
        position_source_ref="cf:paper:position",
        ledger_source_ref="cf:formal:ledger",
        candidate_count=5,
        open_count=1,
        closed_count=closed_count,
        pnl_r=10.5,
        ledger_row_count=ledger_rows,
        ledger_sha256="sha256:" + "b" * 64,
    )


def validate(r55_path: Path, contract_path: Path) -> dict[str, Any]:
    blockers: list[str] = []
    r55 = read_json(r55_path)
    contract = read_json(contract_path)
    report55 = r55.get("report", {})
    if r55.get("state") != "PASS" or r55.get("blockers"):
        blockers.append("R55_PASS_NOT_PROVEN")
    if report55.get("next_route") != "R6.1_ZBOT_SHADOW_OBSERVER_INTEGRATION_GATE":
        blockers.append("R55_NEXT_ROUTE_INVALID")
    if report55.get("sgrade_ready") is not True:
        blockers.append("R55_SGRADE_NOT_READY")
    if report55.get("ready_surface_count") != 24 or report55.get("remaining_surface_count") != 0:
        blockers.append("R55_SURFACE_COUNT_INVALID")

    if contract.get("schema") != "q4r3_zbot_shadow_observer_integration_gate_v1":
        blockers.append("R61_CONTRACT_SCHEMA_INVALID")
    authority = contract.get("authority", {})
    false_fields = (
        "provider_invocation_enabled",
        "runtime_binding_enabled",
        "shadow_state_mutation_enabled",
        "ledger_write_enabled",
        "same_epoch_auto_apply",
    )
    if any(authority.get(key) is not False for key in false_fields):
        blockers.append("R61_WRITE_RUNTIME_BOUNDARY_INVALID")
    if authority.get("execution_authority") != "none" or authority.get("order_authority") != "none":
        blockers.append("R61_AUTHORITY_BOUNDARY_INVALID")
    if contract.get("next_stage") != "R6.2_ZBOT_PROVIDER_DRYRUN_CANARY":
        blockers.append("R61_NEXT_STAGE_INVALID")

    previous = snapshot("shadow.r61.001", 9900, 199, 299)
    current = snapshot("shadow.r61.002", 10000, 200, 300)
    ready = build_shadow_observer_plan(
        current,
        now_ms=10020,
        policy=gate_policy(),
        sgrade_ready=True,
        previous_snapshot=previous,
    )
    routes = {row.task_kind for row in ready.route_plans}
    route_ready = (
        ready.state == "PLAN_READY"
        and routes == EXPECTED_ROUTES
        and ready.action == "hold"
        and ready.closed_delta == 1
        and all(not row.provider_invocation_enabled for row in ready.route_plans)
    )
    boundary_ready = (
        not ready.provider_invocation_enabled
        and not ready.runtime_binding_enabled
        and not ready.shadow_state_mutation_enabled
        and not ready.ledger_write_enabled
        and ready.execution_authority == "none"
        and ready.order_authority == "none"
        and not ready.same_epoch_auto_apply
    )
    fail_closed = (
        build_shadow_observer_plan(
            replace(current, observed_at_ms=8000),
            now_ms=10020,
            policy=gate_policy(),
            sgrade_ready=True,
        ),
        build_shadow_observer_plan(
            replace(current, shadow_source_ref="other:shadow"),
            now_ms=10020,
            policy=gate_policy(),
            sgrade_ready=True,
        ),
        build_shadow_observer_plan(
            replace(current, closed_count=198),
            now_ms=10020,
            policy=gate_policy(),
            sgrade_ready=True,
            previous_snapshot=previous,
        ),
        build_shadow_observer_plan(
            replace(current, ledger_row_count=298),
            now_ms=10020,
            policy=gate_policy(),
            sgrade_ready=True,
            previous_snapshot=previous,
        ),
        build_shadow_observer_plan(
            current,
            now_ms=10020,
            policy=gate_policy(),
            sgrade_ready=False,
        ),
    )
    fail_closed_ready = all(row.state == "HOLD" and row.fail_closed for row in fail_closed)
    if not route_ready:
        blockers.append("R61_EVENT_ROUTE_PLAN_NOT_READY")
    if not boundary_ready:
        blockers.append("R61_OBSERVER_BOUNDARY_NOT_READY")
    if not fail_closed_ready:
        blockers.append("R61_FAIL_CLOSED_SCENARIOS_NOT_READY")

    state = "PASS" if not blockers else "HOLD"
    return {
        "schema": SCHEMA,
        "official_stage": "R6.1",
        "state": state,
        "verdict": "R61_ZBOT_SHADOW_OBSERVER_INTEGRATION_GATE_PASS" if state == "PASS" else "R61_ZBOT_SHADOW_OBSERVER_INTEGRATION_GATE_HOLD",
        "action": "hold",
        "authority": {
            "observer_only": True,
            "proposal_only": True,
            "provider_invocation_enabled": False,
            "runtime_binding_enabled": False,
            "shadow_state_mutation_enabled": False,
            "ledger_write_enabled": False,
            "execution_authority": "none",
            "order_authority": "none",
            "same_epoch_auto_apply": False,
            "human_approval_required": True,
            "runtime_mutation_performed": False,
            "systemd_mutation_performed": False
        },
        "blockers": sorted(set(blockers)),
        "report": {
            "r55_sgrade_prerequisite_ready": report55.get("sgrade_ready") is True,
            "shadow_snapshot_contract_ready": route_ready,
            "point_in_time_gate_ready": ready.point_in_time_valid,
            "source_lineage_gate_ready": ready.source_lineage_valid,
            "count_integrity_gate_ready": ready.count_integrity_valid,
            "ledger_integrity_gate_ready": ready.ledger_integrity_valid,
            "event_route_plan_ready": route_ready,
            "observer_boundary_ready": boundary_ready,
            "route_count": len(ready.route_plans),
            "planned_provider_request_count": sum(row.provider_request_count for row in ready.route_plans),
            "fail_closed_scenario_count": len(fail_closed),
            "provider_invocation_enabled": False,
            "runtime_binding": False,
            "next_route": "R6.2_ZBOT_PROVIDER_DRYRUN_CANARY"
        }
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--r55", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = validate(args.r55.resolve(), args.contract.resolve())
    atomic_json(args.output.resolve(), payload)
    print(json.dumps({
        "state": payload["state"],
        "blocker_count": len(payload["blockers"]),
        "route_count": payload["report"]["route_count"],
        "fail_closed_scenario_count": payload["report"]["fail_closed_scenario_count"],
        "provider_invocation_enabled": payload["report"]["provider_invocation_enabled"]
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
