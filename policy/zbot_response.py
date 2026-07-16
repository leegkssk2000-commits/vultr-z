from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

POLICY_OWNER = "policy/zbot_response.py"
RUNTIME_ENABLED = False
PROVIDER_INVOCATION_ENABLED = False
ALLOWED_ACTIONS = frozenset({
    "reduce25", "partial30", "hold", "stop", "route_change", "rollback", "block"
})
REQUIRED_KEYS = frozenset({
    "provider_id",
    "request_id",
    "task_kind",
    "prompt_id",
    "prompt_version",
    "response_schema_id",
    "model_id",
    "generated_at_ms",
    "recommendation_action",
    "confidence",
    "thesis",
    "risks",
    "evidence_ids",
    "source_refs",
    "input_tokens",
    "output_tokens",
    "cost_micro_usd",
})


@dataclass(frozen=True)
class ResponseExpectation:
    request_id: str
    task_kind: str
    provider_ids: tuple[str, ...]
    prompt_id: str
    prompt_version: str
    response_schema_id: str
    decision_ts_ms: int
    received_at_ms: int
    evidence_ids: tuple[str, ...]
    source_refs: tuple[str, ...]


@dataclass(frozen=True)
class NormalizedProviderResponse:
    provider_id: str
    request_id: str
    task_kind: str
    prompt_id: str
    prompt_version: str
    response_schema_id: str
    model_id: str
    generated_at_ms: int
    recommendation_action: str
    confidence: float
    thesis: str
    risks: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    source_refs: tuple[str, ...]
    input_tokens: int
    output_tokens: int
    cost_micro_usd: int
    response_hash: str


@dataclass(frozen=True)
class NormalizationResult:
    state: str
    reason_codes: tuple[str, ...]
    response: NormalizedProviderResponse | None
    schema_valid: bool
    lineage_valid: bool
    point_in_time_valid: bool
    fail_closed: bool


def _text(value: Any, *, max_len: int) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:max_len]


def _string_tuple(value: Any, *, max_items: int, max_len: int) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    normalized = []
    for item in value[:max_items]:
        text = _text(item, max_len=max_len)
        if text:
            normalized.append(text)
    return tuple(normalized)


def _canonical_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(dict(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def normalize_provider_response(
    raw: Mapping[str, Any],
    expectation: ResponseExpectation,
) -> NormalizationResult:
    reasons: list[str] = []
    keys = set(raw)
    missing = REQUIRED_KEYS - keys
    extra = keys - REQUIRED_KEYS
    if missing:
        reasons.append("RESPONSE_REQUIRED_FIELD_MISSING")
    if extra:
        reasons.append("RESPONSE_UNEXPECTED_FIELD")

    provider_id = _text(raw.get("provider_id"), max_len=64)
    request_id = _text(raw.get("request_id"), max_len=128)
    task_kind = _text(raw.get("task_kind"), max_len=128)
    prompt_id = _text(raw.get("prompt_id"), max_len=128)
    prompt_version = _text(raw.get("prompt_version"), max_len=64)
    response_schema_id = _text(raw.get("response_schema_id"), max_len=128)
    model_id = _text(raw.get("model_id"), max_len=128)
    thesis = _text(raw.get("thesis"), max_len=4000)
    action = _text(raw.get("recommendation_action"), max_len=32)
    risks = _string_tuple(raw.get("risks"), max_items=16, max_len=512)
    evidence_ids = tuple(sorted(set(_string_tuple(raw.get("evidence_ids"), max_items=64, max_len=128))))
    source_refs = tuple(sorted(set(_string_tuple(raw.get("source_refs"), max_items=64, max_len=256))))

    try:
        generated_at_ms = int(raw.get("generated_at_ms"))
    except (TypeError, ValueError):
        generated_at_ms = -1
        reasons.append("RESPONSE_TIMESTAMP_INVALID")
    try:
        confidence = float(raw.get("confidence"))
    except (TypeError, ValueError):
        confidence = -1.0
        reasons.append("RESPONSE_CONFIDENCE_INVALID")
    try:
        input_tokens = int(raw.get("input_tokens"))
        output_tokens = int(raw.get("output_tokens"))
        cost_micro_usd = int(raw.get("cost_micro_usd"))
    except (TypeError, ValueError):
        input_tokens = output_tokens = cost_micro_usd = -1
        reasons.append("RESPONSE_USAGE_INVALID")

    if provider_id not in set(expectation.provider_ids):
        reasons.append("RESPONSE_PROVIDER_UNEXPECTED")
    if request_id != expectation.request_id:
        reasons.append("RESPONSE_REQUEST_ID_MISMATCH")
    if task_kind != expectation.task_kind:
        reasons.append("RESPONSE_TASK_KIND_MISMATCH")
    if prompt_id != expectation.prompt_id or prompt_version != expectation.prompt_version:
        reasons.append("RESPONSE_PROMPT_VERSION_MISMATCH")
    if response_schema_id != expectation.response_schema_id:
        reasons.append("RESPONSE_SCHEMA_ID_MISMATCH")
    if not model_id:
        reasons.append("RESPONSE_MODEL_ID_MISSING")
    if action not in ALLOWED_ACTIONS:
        reasons.append("RESPONSE_ACTION_OUTSIDE_POLICY")
    if not 0.0 <= confidence <= 1.0:
        reasons.append("RESPONSE_CONFIDENCE_OUT_OF_RANGE")
    if not thesis:
        reasons.append("RESPONSE_THESIS_MISSING")
    if not risks:
        reasons.append("RESPONSE_RISKS_MISSING")
    if evidence_ids != tuple(sorted(set(expectation.evidence_ids))):
        reasons.append("RESPONSE_EVIDENCE_LINEAGE_MISMATCH")
    if source_refs != tuple(sorted(set(expectation.source_refs))):
        reasons.append("RESPONSE_SOURCE_LINEAGE_MISMATCH")
    if generated_at_ms < expectation.decision_ts_ms or generated_at_ms > expectation.received_at_ms:
        reasons.append("RESPONSE_POINT_IN_TIME_INVALID")
    if min(input_tokens, output_tokens, cost_micro_usd) < 0:
        reasons.append("RESPONSE_USAGE_NEGATIVE")

    if reasons:
        return NormalizationResult(
            state="HOLD",
            reason_codes=tuple(sorted(set(reasons))),
            response=None,
            schema_valid=False,
            lineage_valid=False,
            point_in_time_valid=False,
            fail_closed=True,
        )

    canonical = {
        "provider_id": provider_id,
        "request_id": request_id,
        "task_kind": task_kind,
        "prompt_id": prompt_id,
        "prompt_version": prompt_version,
        "response_schema_id": response_schema_id,
        "model_id": model_id,
        "generated_at_ms": generated_at_ms,
        "recommendation_action": action,
        "confidence": round(confidence, 8),
        "thesis": thesis,
        "risks": risks,
        "evidence_ids": evidence_ids,
        "source_refs": source_refs,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_micro_usd": cost_micro_usd,
    }
    response = NormalizedProviderResponse(
        provider_id=provider_id,
        request_id=request_id,
        task_kind=task_kind,
        prompt_id=prompt_id,
        prompt_version=prompt_version,
        response_schema_id=response_schema_id,
        model_id=model_id,
        generated_at_ms=generated_at_ms,
        recommendation_action=action,
        confidence=round(confidence, 8),
        thesis=thesis,
        risks=risks,
        evidence_ids=evidence_ids,
        source_refs=source_refs,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_micro_usd=cost_micro_usd,
        response_hash=_canonical_hash(canonical),
    )
    return NormalizationResult(
        state="NORMALIZED",
        reason_codes=("RESPONSE_NORMALIZED",),
        response=response,
        schema_valid=True,
        lineage_valid=True,
        point_in_time_valid=True,
        fail_closed=True,
    )


def normalize_response_set(
    raw_responses: Sequence[Mapping[str, Any]],
    expectation: ResponseExpectation,
) -> tuple[NormalizationResult, ...]:
    return tuple(normalize_provider_response(raw, expectation) for raw in raw_responses)
