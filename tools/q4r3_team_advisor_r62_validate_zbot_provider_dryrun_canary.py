#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

from policy import zbot_arbitration, zbot_budget
from policy.zbot_dryrun_canary import evaluate_provider_dryrun_canary
from policy.zbot_dryrun_transport import contains_secret_material
from policy.zbot_dryrun_types import DryRunTransportPolicy
from policy.zbot_shadow_router import build_shadow_observer_plan
from policy.zbot_shadow_types import ShadowObserverPolicy, ShadowSnapshot

SCHEMA = "q4r3_team_advisor_r62_zbot_provider_dryrun_canary_v1"


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def sample_observer():
    previous = ShadowSnapshot(
        "r62.prev", "shadow.r62", 9900, "r62-validator",
        "cf:shadow:r62", "cf:market:r62", "cf:position:r62", "sheets:ledger:r62",
        10, 1, 5, 4.0, 100, "sha256:" + "a" * 64,
    )
    current = ShadowSnapshot(
        "r62.current", "shadow.r62", 10000, "r62-validator",
        "cf:shadow:r62", "cf:market:r62", "cf:position:r62", "sheets:ledger:r62",
        11, 1, 6, 4.5, 101, "sha256:" + "b" * 64,
    )
    return build_shadow_observer_plan(
        current,
        now_ms=10020,
        policy=ShadowObserverPolicy(1000, 0, 6, "sheets:zbot:shadow-observer"),
        sgrade_ready=True,
        previous_snapshot=previous,
    )


def usage():
    return {
        "openai": zbot_budget.UsageSnapshot("openai", 100, 50, 100),
        "gemini": zbot_budget.UsageSnapshot("gemini", 100, 50, 100),
    }


def prices():
    return {
        "openai": zbot_budget.ProviderPrice("openai", 10, 20, "sheets:zbot:price:openai"),
        "gemini": zbot_budget.ProviderPrice("gemini", 5, 10, "sheets:zbot:price:gemini"),
    }


def budget_policy(**changes):
    values = dict(
        daily_token_limit=100000,
        daily_cost_micro_usd_limit=100000,
        per_request_token_limit=3000,
        max_input_tokens=2000,
        max_output_tokens=1000,
        budget_ref="sheets:zbot:budget",
    )
    values.update(changes)
    return zbot_budget.BudgetPolicy(**values)


def transport_policy(**changes):
    values = dict(
        estimated_input_tokens=500,
        requested_output_tokens=200,
        response_delay_ms=100,
        policy_ref="sheets:zbot:dryrun-transport",
    )
    values.update(changes)
    return DryRunTransportPolicy(**values)


def arbitration_policy(**changes):
    values = dict(
        min_provider_confidence=0.5,
        min_consensus_confidence=0.6,
        max_confidence_spread=0.2,
        require_unanimous_action=True,
        policy_ref="sheets:zbot:arbitration",
    )
    values.update(changes)
    return zbot_arbitration.ArbitrationPolicy(**values)


def evaluate(observer_value=None, *, budget=None, transport=None, arbitration=None, prior_keys=()):
    return evaluate_provider_dryrun_canary(
        observer_value or sample_observer(),
        decision_ts_ms=10000,
        transport_policy=transport or transport_policy(),
        usage=usage(),
        prices=prices(),
        budget_policy=budget or budget_policy(),
        arbitration_policy=arbitration or arbitration_policy(),
        prior_idempotency_keys=prior_keys,
    )


def fail_closed_count() -> int:
    observer = sample_observer()
    baseline = evaluate(observer)
    if (
        observer.state != "PLAN_READY"
        or len(observer.route_plans) != 4
        or baseline.state != "PASS"
        or not baseline.route_results
    ):
        return 0

    passed = 0
    if evaluate(observer, budget=budget_policy(daily_token_limit=1000)).state == "HOLD":
        passed += 1
    if evaluate(observer, prior_keys=(baseline.route_results[0].idempotency_key,)).state == "HOLD":
        passed += 1
    if evaluate(replace(observer, provider_invocation_enabled=True)).state == "HOLD":
        passed += 1
    if evaluate(replace(observer, route_plans=(observer.route_plans[0], observer.route_plans[0]))).state == "HOLD":
        passed += 1
    first = replace(
        observer.route_plans[0],
        required_providers=("openai", "unknown"),
        provider_request_count=2,
    )
    if evaluate(replace(observer, route_plans=(first, *observer.route_plans[1:]))).state == "HOLD":
        passed += 1
    if evaluate(observer, transport=transport_policy(requested_output_tokens=0)).state == "HOLD":
        passed += 1
    if evaluate(observer, arbitration=arbitration_policy(max_confidence_spread=0.0)).state == "HOLD":
        passed += 1
    if contains_secret_material({"authorization": "Bearer blocked"}):
        passed += 1
    return passed


def validate(r61_path: Path, contract_path: Path) -> dict[str, Any]:
    blockers: list[str] = []
    r61 = read_json(r61_path)
    contract = read_json(contract_path)
    r61_report = r61.get("report", {})
    if r61.get("state") != "PASS" or r61.get("blockers"):
        blockers.append("R61_PASS_NOT_PROVEN")
    if r61_report.get("next_route") != "R6.2_ZBOT_PROVIDER_DRYRUN_CANARY":
        blockers.append("R61_NEXT_ROUTE_INVALID")
    if r61_report.get("route_count") != 4 or r61_report.get("planned_provider_request_count") != 7:
        blockers.append("R61_ROUTE_FIXTURE_INVALID")
    if r61_report.get("provider_invocation_enabled") is not False or r61_report.get("runtime_binding") is not False:
        blockers.append("R61_BOUNDARY_INVALID")

    if contract.get("schema") != "q4r3_zbot_provider_dryrun_canary_v1":
        blockers.append("R62_CONTRACT_SCHEMA_INVALID")
    authority = contract.get("authority", {})
    forbidden_true = (
        authority.get("provider_invocation_enabled"),
        authority.get("network_call_enabled"),
        authority.get("credential_resolution_enabled"),
        authority.get("runtime_binding_enabled"),
        authority.get("shadow_state_mutation_enabled"),
        authority.get("ledger_write_enabled"),
        authority.get("same_epoch_auto_apply"),
    )
    if any(value is not False for value in forbidden_true):
        blockers.append("R62_CONTRACT_BOUNDARY_INVALID")
    if authority.get("execution_authority") != "none" or authority.get("order_authority") != "none":
        blockers.append("R62_CONTRACT_AUTHORITY_INVALID")

    result = evaluate()
    expected = contract.get("expected_fixture", {})
    if result.state != "PASS":
        blockers.extend(result.reason_codes)
    if result.route_count != expected.get("route_count"):
        blockers.append("R62_ROUTE_COUNT_INVALID")
    if result.provider_packet_count != expected.get("provider_packet_count"):
        blockers.append("R62_PROVIDER_PACKET_COUNT_INVALID")
    if result.normalized_response_count != expected.get("normalized_response_count"):
        blockers.append("R62_NORMALIZED_RESPONSE_COUNT_INVALID")
    if result.dual_provider_arbitration_count != expected.get("dual_provider_arbitration_count"):
        blockers.append("R62_ARBITRATION_COUNT_INVALID")
    if result.network_call_count != 0 or result.credential_material_count != 0:
        blockers.append("R62_ZERO_NETWORK_CREDENTIAL_ASSERTION_FAILED")
    fail_closed = fail_closed_count()
    if fail_closed != 8:
        blockers.append("R62_FAIL_CLOSED_SCENARIOS_INCOMPLETE")

    state = "PASS" if not blockers else "HOLD"
    return {
        "schema": SCHEMA,
        "official_stage": "R6.2",
        "state": state,
        "verdict": "R62_ZBOT_PROVIDER_DRYRUN_CANARY_PASS" if state == "PASS" else "R62_ZBOT_PROVIDER_DRYRUN_CANARY_HOLD",
        "action": "hold",
        "authority": {
            "observer_only": True,
            "proposal_only": True,
            "provider_invocation_enabled": False,
            "network_call_enabled": False,
            "credential_resolution_enabled": False,
            "runtime_binding_enabled": False,
            "shadow_state_mutation_enabled": False,
            "ledger_write_enabled": False,
            "execution_authority": "none",
            "order_authority": "none",
            "same_epoch_auto_apply": False,
            "human_approval_required": True,
            "runtime_mutation_performed": False,
            "systemd_mutation_performed": False,
        },
        "blockers": sorted(set(blockers)),
        "report": {
            "r61_prerequisite_ready": r61.get("state") == "PASS",
            "provider_request_serialization_ready": result.serialization_ready,
            "provider_adapter_isolation_ready": result.provider_isolation_ready,
            "token_cost_budget_preflight_ready": result.budget_preflight_ready,
            "idempotency_dedup_preflight_ready": result.idempotency_preflight_ready,
            "credential_material_exclusion_ready": result.credential_material_count == 0,
            "network_call_zero_ready": result.network_call_count == 0,
            "response_fixture_normalization_ready": result.response_normalization_ready,
            "dual_provider_arbitration_ready": result.arbitration_ready,
            "route_count": result.route_count,
            "provider_packet_count": result.provider_packet_count,
            "normalized_response_count": result.normalized_response_count,
            "dual_provider_arbitration_count": result.dual_provider_arbitration_count,
            "network_call_count": result.network_call_count,
            "credential_material_count": result.credential_material_count,
            "fail_closed_scenario_count": fail_closed,
            "external_provider_call_performed": False,
            "next_route": "R6.3_ZBOT_EXTERNAL_CANARY_APPROVAL_GATE",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--r61", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = validate(args.r61.resolve(), args.contract.resolve())
    atomic_json(args.output.resolve(), payload)
    print(json.dumps({
        "state": payload["state"],
        "blocker_count": len(payload["blockers"]),
        "route_count": payload["report"]["route_count"],
        "provider_packet_count": payload["report"]["provider_packet_count"],
        "network_call_count": payload["report"]["network_call_count"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
