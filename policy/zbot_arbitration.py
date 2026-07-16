from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from policy.zbot_response import NormalizationResult, NormalizedProviderResponse

POLICY_OWNER = "policy/zbot_arbitration.py"
RUNTIME_ENABLED = False
EXECUTION_AUTHORITY = "none"
ORDER_AUTHORITY = "none"
HUMAN_APPROVAL_REQUIRED = True


@dataclass(frozen=True)
class ArbitrationPolicy:
    min_provider_confidence: float
    min_consensus_confidence: float
    max_confidence_spread: float
    require_unanimous_action: bool
    policy_ref: str


@dataclass(frozen=True)
class ArbitrationResult:
    state: str
    action: str
    proposed_action: str
    reason_codes: tuple[str, ...]
    provider_ids: tuple[str, ...]
    provider_actions: tuple[str, ...]
    provider_confidences: tuple[float, ...]
    response_hashes: tuple[str, ...]
    consensus_confidence: float
    confidence_spread: float
    disagreement: bool
    total_input_tokens: int
    total_output_tokens: int
    total_cost_micro_usd: int
    human_approval_required: bool
    execution_authority: str
    order_authority: str
    runtime_enabled: bool


def _hold(
    reasons: Sequence[str],
    responses: Sequence[NormalizedProviderResponse] = (),
    *,
    proposed_action: str = "hold",
) -> ArbitrationResult:
    confidences = tuple(item.confidence for item in responses)
    spread = max(confidences) - min(confidences) if confidences else 0.0
    return ArbitrationResult(
        state="HOLD",
        action="hold",
        proposed_action=proposed_action,
        reason_codes=tuple(sorted(set(reasons))),
        provider_ids=tuple(item.provider_id for item in responses),
        provider_actions=tuple(item.recommendation_action for item in responses),
        provider_confidences=confidences,
        response_hashes=tuple(item.response_hash for item in responses),
        consensus_confidence=sum(confidences) / len(confidences) if confidences else 0.0,
        confidence_spread=spread,
        disagreement=len({item.recommendation_action for item in responses}) > 1,
        total_input_tokens=sum(item.input_tokens for item in responses),
        total_output_tokens=sum(item.output_tokens for item in responses),
        total_cost_micro_usd=sum(item.cost_micro_usd for item in responses),
        human_approval_required=True,
        execution_authority="none",
        order_authority="none",
        runtime_enabled=False,
    )


def arbitrate_responses(
    normalized: Sequence[NormalizationResult],
    *,
    expected_provider_ids: tuple[str, ...],
    policy: ArbitrationPolicy,
) -> ArbitrationResult:
    reasons: list[str] = []
    if not policy.policy_ref or ":" not in policy.policy_ref:
        reasons.append("ARBITRATION_POLICY_REF_INVALID")
    if not 0.0 <= policy.min_provider_confidence <= 1.0:
        reasons.append("ARBITRATION_MIN_PROVIDER_CONFIDENCE_INVALID")
    if not 0.0 <= policy.min_consensus_confidence <= 1.0:
        reasons.append("ARBITRATION_MIN_CONSENSUS_CONFIDENCE_INVALID")
    if not 0.0 <= policy.max_confidence_spread <= 1.0:
        reasons.append("ARBITRATION_CONFIDENCE_SPREAD_INVALID")
    if not expected_provider_ids or len(set(expected_provider_ids)) != len(expected_provider_ids):
        reasons.append("ARBITRATION_EXPECTED_PROVIDER_SET_INVALID")

    responses: list[NormalizedProviderResponse] = []
    for result in normalized:
        if result.state != "NORMALIZED" or result.response is None:
            reasons.append("ARBITRATION_INPUT_NOT_NORMALIZED")
            continue
        if not result.schema_valid or not result.lineage_valid or not result.point_in_time_valid:
            reasons.append("ARBITRATION_INPUT_INTEGRITY_INVALID")
            continue
        responses.append(result.response)

    provider_ids = tuple(item.provider_id for item in responses)
    if len(provider_ids) != len(set(provider_ids)):
        reasons.append("ARBITRATION_DUPLICATE_PROVIDER_RESPONSE")
    if set(provider_ids) != set(expected_provider_ids):
        reasons.append("ARBITRATION_PROVIDER_SET_MISMATCH")
    request_ids = {item.request_id for item in responses}
    task_kinds = {item.task_kind for item in responses}
    prompt_versions = {(item.prompt_id, item.prompt_version, item.response_schema_id) for item in responses}
    evidence_sets = {item.evidence_ids for item in responses}
    source_sets = {item.source_refs for item in responses}
    if len(request_ids) > 1 or len(task_kinds) > 1 or len(prompt_versions) > 1:
        reasons.append("ARBITRATION_RESPONSE_IDENTITY_MISMATCH")
    if len(evidence_sets) > 1 or len(source_sets) > 1:
        reasons.append("ARBITRATION_LINEAGE_MISMATCH")
    if reasons:
        return _hold(reasons, responses)

    confidences = tuple(item.confidence for item in responses)
    actions = tuple(item.recommendation_action for item in responses)
    consensus_confidence = sum(confidences) / len(confidences)
    confidence_spread = max(confidences) - min(confidences)
    if any(value < policy.min_provider_confidence for value in confidences):
        return _hold(("PROVIDER_CONFIDENCE_BELOW_MIN",), responses)
    if consensus_confidence < policy.min_consensus_confidence:
        return _hold(("CONSENSUS_CONFIDENCE_BELOW_MIN",), responses)
    if confidence_spread > policy.max_confidence_spread:
        return _hold(("PROVIDER_CONFIDENCE_SPREAD_EXCEEDED",), responses, proposed_action="route_change")
    if policy.require_unanimous_action and len(set(actions)) != 1:
        return _hold(("PROVIDER_ACTION_DISAGREEMENT",), responses, proposed_action="route_change")

    agreed_action = actions[0]
    return ArbitrationResult(
        state="PROPOSAL_READY",
        action="hold",
        proposed_action=agreed_action,
        reason_codes=("PROVIDER_CONSENSUS_READY",),
        provider_ids=provider_ids,
        provider_actions=actions,
        provider_confidences=confidences,
        response_hashes=tuple(item.response_hash for item in responses),
        consensus_confidence=round(consensus_confidence, 8),
        confidence_spread=round(confidence_spread, 8),
        disagreement=False,
        total_input_tokens=sum(item.input_tokens for item in responses),
        total_output_tokens=sum(item.output_tokens for item in responses),
        total_cost_micro_usd=sum(item.cost_micro_usd for item in responses),
        human_approval_required=HUMAN_APPROVAL_REQUIRED,
        execution_authority=EXECUTION_AUTHORITY,
        order_authority=ORDER_AUTHORITY,
        runtime_enabled=RUNTIME_ENABLED,
    )
