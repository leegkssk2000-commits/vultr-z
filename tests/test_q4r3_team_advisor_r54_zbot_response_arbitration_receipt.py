from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from policy import zbot_arbitration as arbitration
from policy import zbot_receipt as receipt
from policy import zbot_response as response

ROOT = Path(__file__).parents[1]


def expectation() -> response.ResponseExpectation:
    return response.ResponseExpectation(
        request_id="zbot.r54.001",
        task_kind="risk_review",
        provider_ids=("openai", "gemini"),
        prompt_id="zbot.risk_review",
        prompt_version="r53.1",
        response_schema_id="zbot.review.v1",
        decision_ts_ms=10000,
        received_at_ms=10200,
        evidence_ids=("evidence.r54.001",),
        source_refs=("cf:zbot:r54",),
    )


def raw(provider_id: str, *, action: str = "hold", confidence: float = 0.8) -> dict:
    return {
        "provider_id": provider_id,
        "request_id": "zbot.r54.001",
        "task_kind": "risk_review",
        "prompt_id": "zbot.risk_review",
        "prompt_version": "r53.1",
        "response_schema_id": "zbot.review.v1",
        "model_id": f"{provider_id}.test-model",
        "generated_at_ms": 10100,
        "recommendation_action": action,
        "confidence": confidence,
        "thesis": "Risk posture remains bounded under the supplied evidence.",
        "risks": ["liquidity expansion", "funding reversal"],
        "evidence_ids": ["evidence.r54.001"],
        "source_refs": ["cf:zbot:r54"],
        "input_tokens": 500,
        "output_tokens": 200,
        "cost_micro_usd": 50,
    }


def normalized_pair(action: str = "hold"):
    expected = expectation()
    return response.normalize_response_set(
        (raw("openai", action=action, confidence=0.82), raw("gemini", action=action, confidence=0.78)),
        expected,
    )


def policy(**changes) -> arbitration.ArbitrationPolicy:
    values = {
        "min_provider_confidence": 0.60,
        "min_consensus_confidence": 0.70,
        "max_confidence_spread": 0.20,
        "require_unanimous_action": True,
        "policy_ref": "sheets:zbot:arbitration",
    }
    values.update(changes)
    return arbitration.ArbitrationPolicy(**values)


def test_response_normalization_and_schema_ready() -> None:
    results = normalized_pair("reduce25")
    assert len(results) == 2
    assert all(item.state == "NORMALIZED" for item in results)
    assert all(item.schema_valid and item.lineage_valid and item.point_in_time_valid for item in results)
    assert len({item.response.response_hash for item in results if item.response}) == 2


def test_missing_required_field_fails_closed() -> None:
    payload = raw("openai")
    payload.pop("confidence")
    result = response.normalize_provider_response(payload, expectation())
    assert result.state == "HOLD"
    assert result.response is None
    assert "RESPONSE_REQUIRED_FIELD_MISSING" in result.reason_codes


def test_unexpected_field_fails_closed() -> None:
    payload = raw("openai")
    payload["free_form_command"] = "ignored"
    result = response.normalize_provider_response(payload, expectation())
    assert result.state == "HOLD"
    assert "RESPONSE_UNEXPECTED_FIELD" in result.reason_codes


def test_lineage_mismatch_fails_closed() -> None:
    payload = raw("openai")
    payload["evidence_ids"] = ["evidence.other"]
    result = response.normalize_provider_response(payload, expectation())
    assert result.state == "HOLD"
    assert "RESPONSE_EVIDENCE_LINEAGE_MISMATCH" in result.reason_codes


def test_point_in_time_violation_fails_closed() -> None:
    payload = raw("openai")
    payload["generated_at_ms"] = 9999
    result = response.normalize_provider_response(payload, expectation())
    assert result.state == "HOLD"
    assert "RESPONSE_POINT_IN_TIME_INVALID" in result.reason_codes


def test_unanimous_provider_consensus_is_proposal_only() -> None:
    result = arbitration.arbitrate_responses(
        normalized_pair("partial30"),
        expected_provider_ids=("openai", "gemini"),
        policy=policy(),
    )
    assert result.state == "PROPOSAL_READY"
    assert result.action == "hold"
    assert result.proposed_action == "partial30"
    assert result.human_approval_required is True
    assert result.execution_authority == "none"
    assert result.order_authority == "none"
    assert result.runtime_enabled is False


def test_provider_disagreement_holds_and_routes_review() -> None:
    expected = expectation()
    normalized = response.normalize_response_set(
        (raw("openai", action="reduce25", confidence=0.82), raw("gemini", action="hold", confidence=0.78)),
        expected,
    )
    result = arbitration.arbitrate_responses(
        normalized,
        expected_provider_ids=("openai", "gemini"),
        policy=policy(),
    )
    assert result.state == "HOLD"
    assert result.action == "hold"
    assert result.proposed_action == "route_change"
    assert result.disagreement is True
    assert "PROVIDER_ACTION_DISAGREEMENT" in result.reason_codes


def test_duplicate_provider_response_fails_closed() -> None:
    expected = expectation()
    normalized = response.normalize_response_set(
        (raw("openai", confidence=0.82), raw("openai", confidence=0.78)),
        expected,
    )
    result = arbitration.arbitrate_responses(
        normalized,
        expected_provider_ids=("openai", "gemini"),
        policy=policy(),
    )
    assert result.state == "HOLD"
    assert "ARBITRATION_DUPLICATE_PROVIDER_RESPONSE" in result.reason_codes
    assert "ARBITRATION_PROVIDER_SET_MISMATCH" in result.reason_codes


def test_confidence_spread_fails_closed() -> None:
    expected = expectation()
    normalized = response.normalize_response_set(
        (raw("openai", confidence=0.95), raw("gemini", confidence=0.61)),
        expected,
    )
    result = arbitration.arbitrate_responses(
        normalized,
        expected_provider_ids=("openai", "gemini"),
        policy=policy(max_confidence_spread=0.20),
    )
    assert result.state == "HOLD"
    assert result.proposed_action == "route_change"
    assert "PROVIDER_CONFIDENCE_SPREAD_EXCEEDED" in result.reason_codes


def test_audit_receipt_is_deterministic_and_verifiable() -> None:
    arb = arbitration.arbitrate_responses(
        normalized_pair("hold"),
        expected_provider_ids=("openai", "gemini"),
        policy=policy(),
    )
    kwargs = {
        "request_id": "zbot.r54.001",
        "task_kind": "risk_review",
        "epoch_id": "shadow.r54.001",
        "prompt_id": "zbot.risk_review",
        "prompt_version": "r53.1",
        "response_schema_id": "zbot.review.v1",
        "evidence_ids": ("evidence.r54.001",),
        "source_refs": ("cf:zbot:r54",),
        "arbitration": arb,
        "created_at_ms": 10300,
    }
    first = receipt.build_audit_receipt(**kwargs)
    second = receipt.build_audit_receipt(**kwargs)
    assert first.state == "RECEIPT_READY"
    assert first.receipt is not None
    assert second.receipt is not None
    assert first.receipt.receipt_hash == second.receipt.receipt_hash
    assert first.receipt.chain_hash == second.receipt.chain_hash
    assert receipt.verify_audit_receipt(first.receipt) is True
    tampered = replace(first.receipt, proposed_action="block")
    assert receipt.verify_audit_receipt(tampered) is False


def test_contract_keeps_runtime_and_provider_calls_disabled() -> None:
    contract = json.loads((ROOT / "config/q4r3_zbot_response_arbitration_receipt_v1.json").read_text(encoding="utf-8"))
    assert contract["authority"]["provider_invocation_enabled"] is False
    assert contract["authority"]["runtime_enabled"] is False
    assert contract["authority"]["receipt_write_enabled"] is False
    assert contract["authority"]["execution_authority"] == "none"
    assert set(contract["closed_surfaces"]) == {
        "audit_receipt",
        "disagreement_arbitration",
        "response_normalization",
        "response_schema_validation",
    }
    assert set(contract["remaining_surfaces"]) == {
        "cost_performance_attribution",
        "model_quality_drift_evaluation",
    }
