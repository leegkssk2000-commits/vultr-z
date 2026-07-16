from __future__ import annotations

from policy import zbot_response as response


def expectation() -> response.ResponseExpectation:
    return response.ResponseExpectation(
        request_id="zbot.r54.bool",
        task_kind="risk_review",
        provider_ids=("openai",),
        prompt_id="zbot.risk_review",
        prompt_version="r53.1",
        response_schema_id="zbot.review.v1",
        decision_ts_ms=10000,
        received_at_ms=10200,
        evidence_ids=("evidence.r54.bool",),
        source_refs=("cf:zbot:r54:bool",),
    )


def payload() -> dict:
    return {
        "provider_id": "openai",
        "request_id": "zbot.r54.bool",
        "task_kind": "risk_review",
        "prompt_id": "zbot.risk_review",
        "prompt_version": "r53.1",
        "response_schema_id": "zbot.review.v1",
        "model_id": "openai.test",
        "generated_at_ms": 10100,
        "recommendation_action": "hold",
        "confidence": 0.8,
        "thesis": "Bounded review.",
        "risks": ["reversal"],
        "evidence_ids": ["evidence.r54.bool"],
        "source_refs": ["cf:zbot:r54:bool"],
        "input_tokens": 10,
        "output_tokens": 10,
        "cost_micro_usd": 1,
    }


def test_boolean_confidence_is_not_accepted_as_numeric() -> None:
    value = payload()
    value["confidence"] = True
    result = response.normalize_provider_response(value, expectation())
    assert result.state == "HOLD"


def test_boolean_usage_is_not_accepted_as_integer() -> None:
    value = payload()
    value["input_tokens"] = True
    result = response.normalize_provider_response(value, expectation())
    assert result.state == "HOLD"
