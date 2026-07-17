#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

from policy.zbot_external_canary_approval import evaluate_external_canary_approval
from policy.zbot_external_canary_types import (
    ExternalCanaryApprovalCandidate,
    ExternalCanaryApprovalPolicy,
)

SCHEMA = "q4r3_team_advisor_r63_zbot_external_canary_approval_gate_v1"


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def digest(path: Path) -> str:
    value = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"sha256:{value}"


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def build_policy(contract: Mapping[str, Any]) -> ExternalCanaryApprovalPolicy:
    value = contract.get("approval_policy", {})
    return ExternalCanaryApprovalPolicy(
        allowed_providers=tuple(value.get("allowed_providers", ())),
        allowed_routes=tuple(value.get("allowed_routes", ())),
        min_window_ms=value.get("min_window_ms", 0),
        max_window_ms=value.get("max_window_ms", 0),
        max_calls_total=value.get("max_calls_total", 0),
        max_calls_per_provider=value.get("max_calls_per_provider", 0),
        max_input_tokens=value.get("max_input_tokens", 0),
        max_output_tokens=value.get("max_output_tokens", 0),
        max_cost_micro_usd=value.get("max_cost_micro_usd", 0),
        policy_ref=value.get("policy_ref", ""),
    )


def build_candidate(contract: Mapping[str, Any], r62_digest: str) -> ExternalCanaryApprovalCandidate:
    value = contract.get("fixture", {})
    credential_refs = value.get("credential_refs", {})
    return ExternalCanaryApprovalCandidate(
        approval_id=value.get("approval_id", ""),
        requested_at_ms=value.get("requested_at_ms", -1),
        approved_at_ms=value.get("approved_at_ms", -1),
        expires_at_ms=value.get("expires_at_ms", -1),
        approved_by=value.get("approved_by", ""),
        approval_nonce=value.get("approval_nonce", ""),
        approval_ref=value.get("approval_ref", ""),
        providers=tuple(value.get("providers", ())),
        routes=tuple(value.get("routes", ())),
        max_calls_total=value.get("max_calls_total", 0),
        max_calls_per_provider=value.get("max_calls_per_provider", 0),
        max_input_tokens=value.get("max_input_tokens", 0),
        max_output_tokens=value.get("max_output_tokens", 0),
        max_cost_micro_usd=value.get("max_cost_micro_usd", 0),
        credential_refs=tuple(sorted(credential_refs.items())),
        kill_switch_ref=value.get("kill_switch_ref", ""),
        rollback_ref=value.get("rollback_ref", ""),
        dryrun_evidence_sha256=r62_digest,
    )


def fail_closed_count(
    candidate: ExternalCanaryApprovalCandidate,
    policy: ExternalCanaryApprovalPolicy,
    now_ms: int,
) -> int:
    scenarios = (
        replace(candidate, expires_at_ms=now_ms - 1),
        replace(candidate, approved_by="service:zbot"),
        replace(candidate, providers=("openai", "unknown")),
        replace(candidate, routes=("optimization_candidate_review",)),
        replace(candidate, max_calls_total=policy.max_calls_total + 1),
        replace(candidate, max_cost_micro_usd=policy.max_cost_micro_usd + 1),
        replace(candidate, credential_refs=(("openai", "secret-ref:zbot/openai"),)),
        replace(candidate, credential_refs=(("openai", "sk-abcdefgh12345678"), ("gemini", "secret-ref:zbot/gemini"))),
        replace(candidate, dryrun_evidence_sha256="invalid"),
        replace(candidate, kill_switch_ref="missing"),
        replace(candidate, rollback_ref="missing"),
        replace(candidate, approval_ref="local:approval"),
    )
    passed = sum(
        evaluate_external_canary_approval(item, now_ms=now_ms, policy=policy).state == "HOLD"
        for item in scenarios
    )
    replay = evaluate_external_canary_approval(
        candidate,
        now_ms=now_ms,
        policy=policy,
        prior_nonces=(candidate.approval_nonce,),
    )
    return passed if replay.state == "HOLD" and replay.replay_blocked else passed - 1


def validate(r62_path: Path, contract_path: Path) -> dict[str, Any]:
    blockers: list[str] = []
    r62 = read_json(r62_path)
    contract = read_json(contract_path)
    report = r62.get("report", {})

    if r62.get("state") != "PASS" or r62.get("blockers"):
        blockers.append("R62_PASS_NOT_PROVEN")
    if r62.get("schema") != "q4r3_team_advisor_r62_zbot_provider_dryrun_canary_v1":
        blockers.append("R62_SCHEMA_INVALID")
    if report.get("next_route") != "R6.3_ZBOT_EXTERNAL_CANARY_APPROVAL_GATE":
        blockers.append("R62_NEXT_ROUTE_INVALID")
    expected_r62 = {
        "route_count": 4,
        "provider_packet_count": 7,
        "normalized_response_count": 7,
        "dual_provider_arbitration_count": 3,
        "network_call_count": 0,
        "credential_material_count": 0,
        "fail_closed_scenario_count": 8,
    }
    for key, expected in expected_r62.items():
        if report.get(key) != expected:
            blockers.append(f"R62_{key.upper()}_INVALID")
    if report.get("external_provider_call_performed") is not False:
        blockers.append("R62_EXTERNAL_CALL_BOUNDARY_INVALID")

    if contract.get("schema") != "q4r3_zbot_external_canary_approval_gate_v1":
        blockers.append("R63_CONTRACT_SCHEMA_INVALID")
    authority = contract.get("authority", {})
    false_keys = (
        "provider_invocation_enabled",
        "network_call_enabled",
        "credential_resolution_enabled",
        "runtime_binding_enabled",
        "shadow_state_mutation_enabled",
        "ledger_write_enabled",
        "same_epoch_auto_apply",
        "external_canary_approved",
    )
    if any(authority.get(key) is not False for key in false_keys):
        blockers.append("R63_AUTHORITY_BOUNDARY_INVALID")
    if authority.get("execution_authority") != "none" or authority.get("order_authority") != "none":
        blockers.append("R63_ORDER_AUTHORITY_INVALID")

    r62_digest = digest(r62_path)
    policy = build_policy(contract)
    candidate = build_candidate(contract, r62_digest)
    now_ms = candidate.approved_at_ms + 1000
    result = evaluate_external_canary_approval(candidate, now_ms=now_ms, policy=policy)
    if result.state != "APPROVAL_ELIGIBLE":
        blockers.extend(result.reason_codes)

    fail_closed = fail_closed_count(candidate, policy, now_ms)
    expected_fail_closed = contract.get("expected", {}).get("fail_closed_scenario_count")
    if fail_closed != expected_fail_closed:
        blockers.append("R63_FAIL_CLOSED_SCENARIOS_INCOMPLETE")

    state = "PASS" if not blockers else "HOLD"
    return {
        "schema": SCHEMA,
        "official_stage": "R6.3",
        "state": state,
        "verdict": "R63_ZBOT_EXTERNAL_CANARY_APPROVAL_GATE_PASS" if state == "PASS" else "R63_ZBOT_EXTERNAL_CANARY_APPROVAL_GATE_HOLD",
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
            "external_canary_approved": False,
            "runtime_mutation_performed": False,
            "systemd_mutation_performed": False,
        },
        "blockers": sorted(set(blockers)),
        "report": {
            "r62_prerequisite_ready": r62.get("state") == "PASS",
            "r62_evidence_sha256": r62_digest,
            "approval_gate_ready": result.state == "APPROVAL_ELIGIBLE",
            "approval_eligible_fixture": result.approval_eligible,
            "replay_protection_ready": True,
            "scope_guard_ready": result.scope_valid,
            "budget_guard_ready": result.budget_valid,
            "credential_reference_guard_ready": result.credential_refs_valid,
            "evidence_lineage_ready": result.evidence_lineage_valid,
            "kill_switch_guard_ready": result.kill_switch_valid,
            "rollback_guard_ready": result.rollback_valid,
            "fail_closed_scenario_count": fail_closed,
            "external_canary_approved": False,
            "provider_invocation_enabled": False,
            "network_call_count": 0,
            "credential_resolution_count": 0,
            "next_route": "R6.4_ZBOT_EXTERNAL_CANARY_APPROVAL_ARTIFACT_BIND",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--r62", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = validate(args.r62.resolve(), args.contract.resolve())
    atomic_json(args.output.resolve(), payload)
    print(json.dumps({
        "state": payload["state"],
        "blocker_count": len(payload["blockers"]),
        "approval_gate_ready": payload["report"]["approval_gate_ready"],
        "fail_closed_scenario_count": payload["report"]["fail_closed_scenario_count"],
        "network_call_count": payload["report"]["network_call_count"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
