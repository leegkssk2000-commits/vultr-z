from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Sequence

ZBOT_OWNER = "canonical/zbot.py"
OBSERVER_ONLY = True
PROPOSAL_ONLY = True
EXECUTION_AUTHORITY = "none"
ORDER_AUTHORITY = "none"
RUNTIME_ENABLED = False
SAME_EPOCH_AUTO_APPLY = False
HUMAN_APPROVAL_REQUIRED = True
ALLOWED_ACTIONS = frozenset({
    "reduce25", "partial30", "hold", "stop", "route_change", "rollback", "block"
})
PROVIDER_IDS = ("openai", "gemini")
PRIVATE_FIELD_MARKERS = ("credential", "private", "authorization", "secret")


@dataclass(frozen=True)
class ProviderAdapterSpec:
    provider_id: str
    adapter_kind: str
    credential_handle: str
    external_paid_provider: bool
    receives_peer_output: bool
    execution_authority: str
    runtime_enabled: bool


@dataclass(frozen=True)
class RouteRule:
    task_kind: str
    provider_ids: tuple[str, ...]
    independent_analysis: bool
    human_approval_required: bool
    proposal_only: bool


@dataclass(frozen=True)
class EvidenceItem:
    evidence_id: str
    source_ref: str
    available_at_ms: int
    schema_version: str


@dataclass(frozen=True)
class ZBotTaskRequest:
    request_id: str
    task_kind: str
    decision_ts_ms: int
    epoch_id: str
    evidence: tuple[EvidenceItem, ...]
    payload: Mapping[str, Any]
    requested_action: str


@dataclass(frozen=True)
class ProviderRequest:
    provider_id: str
    request_id: str
    task_kind: str
    decision_ts_ms: int
    evidence_ids: tuple[str, ...]
    source_refs: tuple[str, ...]
    sanitized_payload: Mapping[str, Any]
    isolation_group: str
    peer_output_included: bool
    credential_handle: str


@dataclass(frozen=True)
class ZBotDecisionEnvelope:
    state: str
    action: str
    reason_codes: tuple[str, ...]
    request_id: str
    task_kind: str
    epoch_id: str
    provider_requests: tuple[ProviderRequest, ...]
    required_providers: tuple[str, ...]
    input_evidence_ids: tuple[str, ...]
    source_refs: tuple[str, ...]
    point_in_time_valid: bool
    input_lineage_valid: bool
    privacy_boundary_valid: bool
    dual_provider_independent: bool
    human_approval_required: bool
    proposal_only: bool
    observer_only: bool
    execution_authority: str
    order_authority: str
    same_epoch_auto_apply: bool
    runtime_enabled: bool


PROVIDER_REGISTRY = MappingProxyType({
    "openai": ProviderAdapterSpec(
        provider_id="openai",
        adapter_kind="OpenAIProviderAdapter",
        credential_handle="credential-ref:zbot/openai",
        external_paid_provider=True,
        receives_peer_output=False,
        execution_authority="none",
        runtime_enabled=False,
    ),
    "gemini": ProviderAdapterSpec(
        provider_id="gemini",
        adapter_kind="GeminiProviderAdapter",
        credential_handle="credential-ref:zbot/gemini",
        external_paid_provider=True,
        receives_peer_output=False,
        execution_authority="none",
        runtime_enabled=False,
    ),
})

ROUTE_POLICY = MappingProxyType({
    "market_context_review": RouteRule(
        task_kind="market_context_review",
        provider_ids=PROVIDER_IDS,
        independent_analysis=True,
        human_approval_required=True,
        proposal_only=True,
    ),
    "strategy_counterargument": RouteRule(
        task_kind="strategy_counterargument",
        provider_ids=PROVIDER_IDS,
        independent_analysis=True,
        human_approval_required=True,
        proposal_only=True,
    ),
    "risk_review": RouteRule(
        task_kind="risk_review",
        provider_ids=PROVIDER_IDS,
        independent_analysis=True,
        human_approval_required=True,
        proposal_only=True,
    ),
    "optimization_candidate_review": RouteRule(
        task_kind="optimization_candidate_review",
        provider_ids=PROVIDER_IDS,
        independent_analysis=True,
        human_approval_required=True,
        proposal_only=True,
    ),
    "post_trade_explanation": RouteRule(
        task_kind="post_trade_explanation",
        provider_ids=("openai",),
        independent_analysis=False,
        human_approval_required=True,
        proposal_only=True,
    ),
})


def _contains_private_field(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized = str(key).lower()
            if any(marker in normalized for marker in PRIVATE_FIELD_MARKERS):
                return True
            if _contains_private_field(nested):
                return True
    elif isinstance(value, (list, tuple)):
        return any(_contains_private_field(item) for item in value)
    return False


def _hold(request: ZBotTaskRequest, reasons: Sequence[str]) -> ZBotDecisionEnvelope:
    return ZBotDecisionEnvelope(
        state="HOLD",
        action="hold",
        reason_codes=tuple(sorted(set(reasons))),
        request_id=request.request_id,
        task_kind=request.task_kind,
        epoch_id=request.epoch_id,
        provider_requests=(),
        required_providers=(),
        input_evidence_ids=tuple(sorted({item.evidence_id for item in request.evidence})),
        source_refs=tuple(sorted({item.source_ref for item in request.evidence})),
        point_in_time_valid=False,
        input_lineage_valid=False,
        privacy_boundary_valid=False,
        dual_provider_independent=False,
        human_approval_required=HUMAN_APPROVAL_REQUIRED,
        proposal_only=PROPOSAL_ONLY,
        observer_only=OBSERVER_ONLY,
        execution_authority=EXECUTION_AUTHORITY,
        order_authority=ORDER_AUTHORITY,
        same_epoch_auto_apply=SAME_EPOCH_AUTO_APPLY,
        runtime_enabled=RUNTIME_ENABLED,
    )


def build_provider_requests(request: ZBotTaskRequest) -> ZBotDecisionEnvelope:
    reasons: list[str] = []
    rule = ROUTE_POLICY.get(request.task_kind)
    if not request.request_id or not request.epoch_id:
        reasons.append("REQUEST_IDENTITY_MISSING")
    if request.decision_ts_ms < 0:
        reasons.append("DECISION_TIMESTAMP_INVALID")
    if rule is None:
        reasons.append("TASK_ROUTE_UNREGISTERED")
    if request.requested_action not in ALLOWED_ACTIONS:
        reasons.append("ACTION_OUTSIDE_POLICY")
    if not request.evidence:
        reasons.append("INPUT_EVIDENCE_MISSING")

    evidence_ids: set[str] = set()
    source_refs: set[str] = set()
    for item in request.evidence:
        if not item.evidence_id or item.evidence_id in evidence_ids:
            reasons.append("EVIDENCE_ID_INVALID_OR_DUPLICATE")
        evidence_ids.add(item.evidence_id)
        if not item.source_ref or ":" not in item.source_ref:
            reasons.append("EVIDENCE_SOURCE_REF_INVALID")
        source_refs.add(item.source_ref)
        if not item.schema_version:
            reasons.append("EVIDENCE_SCHEMA_MISSING")
        if item.available_at_ms < 0 or item.available_at_ms > request.decision_ts_ms:
            reasons.append("POINT_IN_TIME_VIOLATION")
    if _contains_private_field(request.payload):
        reasons.append("PRIVACY_BOUNDARY_VIOLATION")

    if reasons:
        return _hold(request, reasons)
    assert rule is not None

    provider_requests: list[ProviderRequest] = []
    for provider_id in rule.provider_ids:
        adapter = PROVIDER_REGISTRY.get(provider_id)
        if adapter is None:
            return _hold(request, ("PROVIDER_NOT_REGISTERED",))
        provider_requests.append(ProviderRequest(
            provider_id=provider_id,
            request_id=request.request_id,
            task_kind=request.task_kind,
            decision_ts_ms=request.decision_ts_ms,
            evidence_ids=tuple(sorted(evidence_ids)),
            source_refs=tuple(sorted(source_refs)),
            sanitized_payload=MappingProxyType(dict(request.payload)),
            isolation_group=f"{request.request_id}:{provider_id}",
            peer_output_included=False,
            credential_handle=adapter.credential_handle,
        ))

    dual_independent = (
        set(rule.provider_ids) == set(PROVIDER_IDS)
        and rule.independent_analysis
        and len({item.isolation_group for item in provider_requests}) == len(PROVIDER_IDS)
        and all(not item.peer_output_included for item in provider_requests)
    )
    if rule.independent_analysis and not dual_independent:
        return _hold(request, ("DUAL_PROVIDER_INDEPENDENCE_INVALID",))

    return ZBotDecisionEnvelope(
        state="PROPOSAL_READY",
        action=request.requested_action,
        reason_codes=("CANONICAL_PROVIDER_POLICY_READY",),
        request_id=request.request_id,
        task_kind=request.task_kind,
        epoch_id=request.epoch_id,
        provider_requests=tuple(provider_requests),
        required_providers=tuple(rule.provider_ids),
        input_evidence_ids=tuple(sorted(evidence_ids)),
        source_refs=tuple(sorted(source_refs)),
        point_in_time_valid=True,
        input_lineage_valid=True,
        privacy_boundary_valid=True,
        dual_provider_independent=dual_independent,
        human_approval_required=rule.human_approval_required,
        proposal_only=rule.proposal_only,
        observer_only=OBSERVER_ONLY,
        execution_authority=EXECUTION_AUTHORITY,
        order_authority=ORDER_AUTHORITY,
        same_epoch_auto_apply=SAME_EPOCH_AUTO_APPLY,
        runtime_enabled=RUNTIME_ENABLED,
    )
