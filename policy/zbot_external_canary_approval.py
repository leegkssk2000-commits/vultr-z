from __future__ import annotations

import re
from dataclasses import fields
from typing import Any

from policy.zbot_external_canary_types import (
    ExternalCanaryApprovalCandidate,
    ExternalCanaryApprovalGateResult,
    ExternalCanaryApprovalPolicy,
)

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_NONCE = re.compile(r"^[0-9a-f]{32,128}$")
_SECRET_PATTERNS = (
    re.compile(r"(?:^|[\s=:])Bearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE),
    re.compile(r"(?:^|[\s=:])sk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"AIza[0-9A-Za-z_-]{20,}"),
)


def _valid_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _all_strings(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, tuple):
        result: list[str] = []
        for item in value:
            result.extend(_all_strings(item))
        return tuple(result)
    return ()


def contains_secret_material(candidate: ExternalCanaryApprovalCandidate) -> bool:
    values: list[str] = []
    for field in fields(candidate):
        values.extend(_all_strings(getattr(candidate, field.name)))
    return any(pattern.search(value) for value in values for pattern in _SECRET_PATTERNS)


def evaluate_external_canary_approval(
    candidate: ExternalCanaryApprovalCandidate,
    *,
    now_ms: int,
    policy: ExternalCanaryApprovalPolicy,
    prior_nonces: tuple[str, ...] = (),
) -> ExternalCanaryApprovalGateResult:
    reasons: list[str] = []

    if not _valid_int(now_ms) or now_ms < 0:
        reasons.append("NOW_MS_INVALID")
    if not candidate.approval_id.startswith("approval.r63."):
        reasons.append("APPROVAL_ID_INVALID")
    if not candidate.approved_by.startswith("human:"):
        reasons.append("HUMAN_APPROVER_INVALID")
    if not candidate.approval_ref.startswith(("cf:", "sheets:")):
        reasons.append("APPROVAL_SOURCE_REF_INVALID")
    if not _NONCE.fullmatch(candidate.approval_nonce):
        reasons.append("APPROVAL_NONCE_INVALID")
    replay_blocked = candidate.approval_nonce in set(prior_nonces)
    if replay_blocked:
        reasons.append("APPROVAL_NONCE_REPLAY")

    timestamps = (
        candidate.requested_at_ms,
        candidate.approved_at_ms,
        candidate.expires_at_ms,
    )
    if not all(_valid_int(value) and value >= 0 for value in timestamps):
        reasons.append("APPROVAL_TIMESTAMP_INVALID")
    else:
        window_ms = candidate.expires_at_ms - candidate.requested_at_ms
        if not (policy.min_window_ms <= window_ms <= policy.max_window_ms):
            reasons.append("APPROVAL_WINDOW_INVALID")
        if not (
            candidate.requested_at_ms
            <= candidate.approved_at_ms
            <= candidate.expires_at_ms
        ):
            reasons.append("APPROVAL_SEQUENCE_INVALID")
        if now_ms < candidate.approved_at_ms:
            reasons.append("APPROVAL_NOT_ACTIVE")
        if now_ms > candidate.expires_at_ms:
            reasons.append("APPROVAL_EXPIRED")

    provider_set = set(candidate.providers)
    route_set = set(candidate.routes)
    scope_valid = bool(provider_set) and bool(route_set)
    if len(provider_set) != len(candidate.providers):
        reasons.append("DUPLICATE_PROVIDER_SCOPE")
        scope_valid = False
    if len(route_set) != len(candidate.routes):
        reasons.append("DUPLICATE_ROUTE_SCOPE")
        scope_valid = False
    if not provider_set.issubset(set(policy.allowed_providers)):
        reasons.append("PROVIDER_SCOPE_FORBIDDEN")
        scope_valid = False
    if not route_set.issubset(set(policy.allowed_routes)):
        reasons.append("ROUTE_SCOPE_FORBIDDEN")
        scope_valid = False

    numeric_limits = (
        candidate.max_calls_total,
        candidate.max_calls_per_provider,
        candidate.max_input_tokens,
        candidate.max_output_tokens,
        candidate.max_cost_micro_usd,
    )
    budget_valid = all(_valid_int(value) and value > 0 for value in numeric_limits)
    if not budget_valid:
        reasons.append("CANARY_LIMIT_INVALID")
    else:
        if candidate.max_calls_total > policy.max_calls_total:
            reasons.append("TOTAL_CALL_LIMIT_EXCEEDED")
            budget_valid = False
        if candidate.max_calls_per_provider > policy.max_calls_per_provider:
            reasons.append("PROVIDER_CALL_LIMIT_EXCEEDED")
            budget_valid = False
        if candidate.max_input_tokens > policy.max_input_tokens:
            reasons.append("INPUT_TOKEN_LIMIT_EXCEEDED")
            budget_valid = False
        if candidate.max_output_tokens > policy.max_output_tokens:
            reasons.append("OUTPUT_TOKEN_LIMIT_EXCEEDED")
            budget_valid = False
        if candidate.max_cost_micro_usd > policy.max_cost_micro_usd:
            reasons.append("COST_LIMIT_EXCEEDED")
            budget_valid = False
        if candidate.max_calls_total > candidate.max_calls_per_provider * len(provider_set):
            reasons.append("CALL_DISTRIBUTION_INVALID")
            budget_valid = False

    credential_map = dict(candidate.credential_refs)
    credential_refs_valid = (
        len(credential_map) == len(candidate.credential_refs)
        and set(credential_map) == provider_set
        and all(value.startswith("secret-ref:") for value in credential_map.values())
    )
    if not credential_refs_valid:
        reasons.append("CREDENTIAL_REFERENCE_INVALID")
    if contains_secret_material(candidate):
        reasons.append("SECRET_MATERIAL_PRESENT")
        credential_refs_valid = False

    evidence_lineage_valid = bool(_SHA256.fullmatch(candidate.dryrun_evidence_sha256))
    if not evidence_lineage_valid:
        reasons.append("DRYRUN_EVIDENCE_DIGEST_INVALID")

    kill_switch_valid = candidate.kill_switch_ref.startswith(("cf:", "sheets:"))
    rollback_valid = candidate.rollback_ref.startswith(("cf:", "sheets:"))
    if not kill_switch_valid:
        reasons.append("KILL_SWITCH_REF_INVALID")
    if not rollback_valid:
        reasons.append("ROLLBACK_REF_INVALID")

    if not policy.policy_ref.startswith(("cf:", "sheets:")):
        reasons.append("POLICY_REF_INVALID")

    state = "APPROVAL_ELIGIBLE" if not reasons else "HOLD"
    return ExternalCanaryApprovalGateResult(
        state=state,
        action="hold",
        reason_codes=tuple(sorted(set(reasons))),
        approval_eligible=state == "APPROVAL_ELIGIBLE",
        replay_blocked=replay_blocked,
        scope_valid=scope_valid,
        budget_valid=budget_valid,
        credential_refs_valid=credential_refs_valid,
        evidence_lineage_valid=evidence_lineage_valid,
        kill_switch_valid=kill_switch_valid,
        rollback_valid=rollback_valid,
        provider_invocation_enabled=False,
        network_call_enabled=False,
        credential_resolution_enabled=False,
        execution_authority="none",
        order_authority="none",
    )
