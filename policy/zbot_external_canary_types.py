from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExternalCanaryApprovalPolicy:
    allowed_providers: tuple[str, ...]
    allowed_routes: tuple[str, ...]
    min_window_ms: int
    max_window_ms: int
    max_calls_total: int
    max_calls_per_provider: int
    max_input_tokens: int
    max_output_tokens: int
    max_cost_micro_usd: int
    policy_ref: str


@dataclass(frozen=True)
class ExternalCanaryApprovalCandidate:
    approval_id: str
    requested_at_ms: int
    approved_at_ms: int
    expires_at_ms: int
    approved_by: str
    approval_nonce: str
    approval_ref: str
    providers: tuple[str, ...]
    routes: tuple[str, ...]
    max_calls_total: int
    max_calls_per_provider: int
    max_input_tokens: int
    max_output_tokens: int
    max_cost_micro_usd: int
    credential_refs: tuple[tuple[str, str], ...]
    kill_switch_ref: str
    rollback_ref: str
    dryrun_evidence_sha256: str


@dataclass(frozen=True)
class ExternalCanaryApprovalGateResult:
    state: str
    action: str
    reason_codes: tuple[str, ...]
    approval_eligible: bool
    replay_blocked: bool
    scope_valid: bool
    budget_valid: bool
    credential_refs_valid: bool
    evidence_lineage_valid: bool
    kill_switch_valid: bool
    rollback_valid: bool
    provider_invocation_enabled: bool
    network_call_enabled: bool
    credential_resolution_enabled: bool
    execution_authority: str
    order_authority: str
