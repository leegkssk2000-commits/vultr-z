#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Mapping

from canonical import zbot
from policy import zbot_budget as budget
from policy import zbot_idempotency as idempotency
from policy import zbot_prompt as prompt
from policy import zbot_reliability as reliability

SCHEMA = "q4r3_team_advisor_r53_zbot_reliability_budget_prompt_idempotency_v1"
CLOSED = {
    "budget_token_accounting",
    "idempotency_cache_dedup",
    "prompt_versioning",
    "timeout_retry_circuit_breaker",
}
REMAINING = {
    "audit_receipt",
    "cost_performance_attribution",
    "disagreement_arbitration",
    "model_quality_drift_evaluation",
    "response_normalization",
    "response_schema_validation",
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


def sample_decision():
    evidence = zbot.EvidenceItem(
        evidence_id="evidence.r53.validator",
        source_ref="cf:zbot:r53:validator",
        available_at_ms=9900,
        schema_version="r53-validator",
    )
    request = zbot.ZBotTaskRequest(
        request_id="zbot.r53.validator",
        task_kind="risk_review",
        decision_ts_ms=10000,
        epoch_id="shadow.r53.validator",
        evidence=(evidence,),
        payload={"symbol": "BTCUSDT", "mode": "review"},
        requested_action="hold",
    )
    return zbot.build_provider_requests(request)


def validate(r52_path: Path, contract_path: Path) -> dict[str, Any]:
    blockers: list[str] = []
    r52 = read_json(r52_path)
    contract = read_json(contract_path)
    report52 = r52.get("report", {})
    if r52.get("state") != "PASS" or r52.get("blockers"):
        blockers.append("R52_PASS_NOT_PROVEN")
    if report52.get("next_route") != "R5.3_ZBOT_RELIABILITY_BUDGET_PROMPT_IDEMPOTENCY":
        blockers.append("R52_NEXT_ROUTE_INVALID")
    if report52.get("ready_surface_count") != 14 or report52.get("remaining_surface_count") != 10:
        blockers.append("R52_SURFACE_COUNT_INVALID")
    if not CLOSED.issubset(set(report52.get("remaining_surfaces", []))):
        blockers.append("R52_REQUIRED_GAPS_NOT_PROVEN")
    if contract.get("schema") != "q4r3_zbot_reliability_budget_prompt_idempotency_v1":
        blockers.append("R53_CONTRACT_SCHEMA_INVALID")
    if set(contract.get("closed_surfaces", [])) != CLOSED:
        blockers.append("R53_CLOSED_SURFACES_INVALID")
    if set(contract.get("remaining_surfaces", [])) != REMAINING:
        blockers.append("R53_REMAINING_SURFACES_INVALID")
    authority = contract.get("authority", {})
    if authority.get("provider_invocation_enabled") is not False or authority.get("runtime_enabled") is not False:
        blockers.append("R53_RUNTIME_BOUNDARY_INVALID")

    decision = sample_decision()
    prompt_ready = prompt.validate_prompt_registry() == () and set(prompt.PROMPT_REGISTRY) == set(zbot.ROUTE_POLICY)
    budget_result = budget.evaluate_budget(
        decision.required_providers,
        estimated_input_tokens=500,
        requested_output_tokens=200,
        usage={
            "openai": budget.UsageSnapshot("openai", 100, 50, 100),
            "gemini": budget.UsageSnapshot("gemini", 100, 50, 100),
        },
        prices={
            "openai": budget.ProviderPrice("openai", 10, 20, "sheets:zbot:price:openai"),
            "gemini": budget.ProviderPrice("gemini", 5, 10, "sheets:zbot:price:gemini"),
        },
        policy=budget.BudgetPolicy(10000, 10000, 3000, 2000, 1000, "sheets:zbot:budget"),
    )
    reliability_result = reliability.evaluate_reliability(
        decision.required_providers,
        now_ms=10000,
        health={
            "openai": reliability.ProviderHealth("openai", "ready", 0, 0, 9900),
            "gemini": reliability.ProviderHealth("gemini", "ready", 0, 0, 9900),
        },
        policy=reliability.ReliabilityPolicy(15000, 3, 250, 1000, 3, 60000, 1000, "sheets:zbot:reliability"),
    )
    spec = prompt.get_prompt(decision.task_kind)
    first = idempotency.evaluate_idempotency(
        decision,
        prompt_id=spec.prompt_id if spec else "",
        prompt_version=spec.version if spec else "",
        prior_keys=(),
    )
    second = idempotency.evaluate_idempotency(
        decision,
        prompt_id=spec.prompt_id if spec else "",
        prompt_version=spec.version if spec else "",
        prior_keys=(first.idempotency_key,),
    )
    budget_ready = budget_result.state == "READY" and budget_result.token_budget_valid and budget_result.cost_budget_valid
    reliability_ready = reliability_result.state == "READY" and reliability_result.retry_backoff_ms == (250, 500)
    idempotency_ready = first.state == "READY" and second.state == "HOLD" and second.duplicate_blocked
    if not prompt_ready:
        blockers.append("PROMPT_VERSIONING_NOT_READY")
    if not budget_ready:
        blockers.append("BUDGET_ACCOUNTING_NOT_READY")
    if not reliability_ready:
        blockers.append("RELIABILITY_POLICY_NOT_READY")
    if not idempotency_ready:
        blockers.append("IDEMPOTENCY_DEDUP_NOT_READY")

    state = "PASS" if not blockers else "HOLD"
    return {
        "schema": SCHEMA,
        "official_stage": "R5.3",
        "state": state,
        "verdict": "R53_ZBOT_RELIABILITY_BUDGET_PROMPT_IDEMPOTENCY_PASS" if state == "PASS" else "R53_ZBOT_RELIABILITY_BUDGET_PROMPT_IDEMPOTENCY_HOLD",
        "action": "hold",
        "authority": {
            "observer_only": True,
            "proposal_only": True,
            "execution_authority": "none",
            "order_authority": "none",
            "provider_invocation_enabled": False,
            "runtime_mutation_performed": False,
            "systemd_mutation_performed": False,
            "same_epoch_auto_apply": False,
            "human_approval_required": True
        },
        "blockers": sorted(set(blockers)),
        "report": {
            "prompt_registry_count": len(prompt.PROMPT_REGISTRY),
            "prompt_versioning_ready": prompt_ready,
            "budget_token_accounting_ready": budget_ready,
            "timeout_retry_circuit_breaker_ready": reliability_ready,
            "idempotency_cache_dedup_ready": idempotency_ready,
            "closed_surface_count": 4 if state == "PASS" else 0,
            "ready_surface_count": 18 if state == "PASS" else 14,
            "remaining_surface_count": 6,
            "remaining_surfaces": sorted(REMAINING),
            "runtime_binding": False,
            "sgrade_ready": False,
            "next_route": "R5.4_ZBOT_RESPONSE_NORMALIZATION_ARBITRATION_RECEIPT"
        }
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--r52", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = validate(args.r52.resolve(), args.contract.resolve())
    atomic_json(args.output.resolve(), payload)
    print(json.dumps({
        "state": payload["state"],
        "blocker_count": len(payload["blockers"]),
        "closed_surface_count": payload["report"]["closed_surface_count"],
        "ready_surface_count": payload["report"]["ready_surface_count"],
        "remaining_surface_count": payload["report"]["remaining_surface_count"]
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
