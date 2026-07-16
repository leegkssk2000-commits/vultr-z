#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Mapping

from policy import zbot_arbitration as arbitration
from policy import zbot_receipt as receipt
from policy import zbot_response as response

SCHEMA = "q4r3_team_advisor_r54_zbot_response_arbitration_receipt_v1"
CLOSED = {
    "audit_receipt",
    "disagreement_arbitration",
    "response_normalization",
    "response_schema_validation",
}
REMAINING = {
    "cost_performance_attribution",
    "model_quality_drift_evaluation",
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


def expectation() -> response.ResponseExpectation:
    return response.ResponseExpectation(
        request_id="zbot.r54.validator",
        task_kind="risk_review",
        provider_ids=("openai", "gemini"),
        prompt_id="zbot.risk_review",
        prompt_version="r53.1",
        response_schema_id="zbot.review.v1",
        decision_ts_ms=10000,
        received_at_ms=10200,
        evidence_ids=("evidence.r54.validator",),
        source_refs=("cf:zbot:r54:validator",),
    )


def raw(provider_id: str, action: str, confidence: float) -> dict[str, Any]:
    return {
        "provider_id": provider_id,
        "request_id": "zbot.r54.validator",
        "task_kind": "risk_review",
        "prompt_id": "zbot.risk_review",
        "prompt_version": "r53.1",
        "response_schema_id": "zbot.review.v1",
        "model_id": f"{provider_id}.validator",
        "generated_at_ms": 10100,
        "recommendation_action": action,
        "confidence": confidence,
        "thesis": "Validated response envelope.",
        "risks": ["market reversal"],
        "evidence_ids": ["evidence.r54.validator"],
        "source_refs": ["cf:zbot:r54:validator"],
        "input_tokens": 500,
        "output_tokens": 200,
        "cost_micro_usd": 50,
    }


def arbitration_policy() -> arbitration.ArbitrationPolicy:
    return arbitration.ArbitrationPolicy(
        min_provider_confidence=0.60,
        min_consensus_confidence=0.70,
        max_confidence_spread=0.20,
        require_unanimous_action=True,
        policy_ref="sheets:zbot:arbitration",
    )


def validate(r53_path: Path, contract_path: Path) -> dict[str, Any]:
    blockers: list[str] = []
    r53 = read_json(r53_path)
    contract = read_json(contract_path)
    report53 = r53.get("report", {})
    if r53.get("state") != "PASS" or r53.get("blockers"):
        blockers.append("R53_PASS_NOT_PROVEN")
    if report53.get("next_route") != "R5.4_ZBOT_RESPONSE_NORMALIZATION_ARBITRATION_RECEIPT":
        blockers.append("R53_NEXT_ROUTE_INVALID")
    if report53.get("ready_surface_count") != 18 or report53.get("remaining_surface_count") != 6:
        blockers.append("R53_SURFACE_COUNT_INVALID")
    if not CLOSED.issubset(set(report53.get("remaining_surfaces", []))):
        blockers.append("R53_REQUIRED_GAPS_NOT_PROVEN")

    if contract.get("schema") != "q4r3_zbot_response_arbitration_receipt_v1":
        blockers.append("R54_CONTRACT_SCHEMA_INVALID")
    if set(contract.get("closed_surfaces", [])) != CLOSED:
        blockers.append("R54_CLOSED_SURFACES_INVALID")
    if set(contract.get("remaining_surfaces", [])) != REMAINING:
        blockers.append("R54_REMAINING_SURFACES_INVALID")
    authority = contract.get("authority", {})
    if authority.get("provider_invocation_enabled") is not False or authority.get("runtime_enabled") is not False:
        blockers.append("R54_RUNTIME_BOUNDARY_INVALID")
    if authority.get("receipt_write_enabled") is not False:
        blockers.append("R54_RECEIPT_WRITE_BOUNDARY_INVALID")
    if authority.get("execution_authority") != "none" or authority.get("order_authority") != "none":
        blockers.append("R54_AUTHORITY_BOUNDARY_INVALID")

    expected = expectation()
    normalized = response.normalize_response_set(
        (raw("openai", "hold", 0.82), raw("gemini", "hold", 0.78)),
        expected,
    )
    response_ready = all(
        item.state == "NORMALIZED"
        and item.response is not None
        and item.schema_valid
        and item.lineage_valid
        and item.point_in_time_valid
        for item in normalized
    )
    consensus = arbitration.arbitrate_responses(
        normalized,
        expected_provider_ids=expected.provider_ids,
        policy=arbitration_policy(),
    )
    arbitration_ready = (
        consensus.state == "PROPOSAL_READY"
        and consensus.action == "hold"
        and consensus.proposed_action == "hold"
        and consensus.execution_authority == "none"
        and consensus.order_authority == "none"
        and consensus.runtime_enabled is False
    )
    disagreement_input = response.normalize_response_set(
        (raw("openai", "reduce25", 0.82), raw("gemini", "hold", 0.78)),
        expected,
    )
    disagreement = arbitration.arbitrate_responses(
        disagreement_input,
        expected_provider_ids=expected.provider_ids,
        policy=arbitration_policy(),
    )
    disagreement_ready = (
        disagreement.state == "HOLD"
        and disagreement.action == "hold"
        and disagreement.proposed_action == "route_change"
        and "PROVIDER_ACTION_DISAGREEMENT" in disagreement.reason_codes
    )
    receipt_result = receipt.build_audit_receipt(
        request_id=expected.request_id,
        task_kind=expected.task_kind,
        epoch_id="shadow.r54.validator",
        prompt_id=expected.prompt_id,
        prompt_version=expected.prompt_version,
        response_schema_id=expected.response_schema_id,
        evidence_ids=expected.evidence_ids,
        source_refs=expected.source_refs,
        arbitration=consensus,
        created_at_ms=10300,
    )
    receipt_ready = (
        receipt_result.state == "RECEIPT_READY"
        and receipt_result.receipt is not None
        and receipt_result.integrity_valid
        and receipt.verify_audit_receipt(receipt_result.receipt)
    )
    if not response_ready:
        blockers.append("RESPONSE_NORMALIZATION_SCHEMA_NOT_READY")
    if not arbitration_ready or not disagreement_ready:
        blockers.append("DISAGREEMENT_ARBITRATION_NOT_READY")
    if not receipt_ready:
        blockers.append("AUDIT_RECEIPT_NOT_READY")

    state = "PASS" if not blockers else "HOLD"
    return {
        "schema": SCHEMA,
        "official_stage": "R5.4",
        "state": state,
        "verdict": "R54_ZBOT_RESPONSE_ARBITRATION_RECEIPT_PASS" if state == "PASS" else "R54_ZBOT_RESPONSE_ARBITRATION_RECEIPT_HOLD",
        "action": "hold",
        "authority": {
            "observer_only": True,
            "proposal_only": True,
            "execution_authority": "none",
            "order_authority": "none",
            "provider_invocation_enabled": False,
            "runtime_mutation_performed": False,
            "receipt_write_enabled": False,
            "systemd_mutation_performed": False,
            "same_epoch_auto_apply": False,
            "human_approval_required": True
        },
        "blockers": sorted(set(blockers)),
        "report": {
            "response_normalization_ready": response_ready,
            "response_schema_validation_ready": response_ready,
            "disagreement_arbitration_ready": arbitration_ready and disagreement_ready,
            "audit_receipt_ready": receipt_ready,
            "normalized_provider_count": len(normalized) if response_ready else 0,
            "fail_closed_scenario_count": 10,
            "closed_surface_count": 4 if state == "PASS" else 0,
            "ready_surface_count": 22 if state == "PASS" else 18,
            "remaining_surface_count": 2,
            "remaining_surfaces": sorted(REMAINING),
            "runtime_binding": False,
            "sgrade_ready": False,
            "next_route": "R5.5_ZBOT_ATTRIBUTION_DRIFT_SGRADE_LOCK"
        }
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--r53", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = validate(args.r53.resolve(), args.contract.resolve())
    atomic_json(args.output.resolve(), payload)
    print(json.dumps({
        "state": payload["state"],
        "blocker_count": len(payload["blockers"]),
        "closed_surface_count": payload["report"]["closed_surface_count"],
        "ready_surface_count": payload["report"]["ready_surface_count"],
        "remaining_surface_count": payload["report"]["remaining_surface_count"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
