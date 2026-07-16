from __future__ import annotations

from dataclasses import dataclass

POLICY_OWNER = "policy/zbot_dryrun_types.py"


@dataclass(frozen=True)
class DryRunTransportPolicy:
    estimated_input_tokens: int
    requested_output_tokens: int
    response_delay_ms: int
    policy_ref: str


@dataclass(frozen=True)
class DryRunPacket:
    route_id: str
    provider_id: str
    request_id: str
    task_kind: str
    prompt_id: str
    prompt_version: str
    response_schema_id: str
    endpoint_alias: str
    model_alias: str
    headers: tuple[tuple[str, str], ...]
    body_json: str
    body_sha256: str
    idempotency_key: str
    dispatch_key: str
    estimated_input_tokens: int
    requested_output_tokens: int
    projected_cost_micro_usd: int
    network_call_performed: bool
    credential_material_present: bool


@dataclass(frozen=True)
class TransportCompileResult:
    state: str
    reason_codes: tuple[str, ...]
    route_id: str
    idempotency_key: str
    packets: tuple[DryRunPacket, ...]
    provider_isolation_valid: bool
    credential_boundary_valid: bool
    network_call_count: int
    fail_closed: bool


@dataclass(frozen=True)
class RouteDryRunResult:
    state: str
    reason_codes: tuple[str, ...]
    route_id: str
    request_id: str
    packet_count: int
    normalized_response_count: int
    arbitration_state: str
    budget_valid: bool
    idempotency_valid: bool
    provider_isolation_valid: bool
    response_path_valid: bool
    network_call_count: int
    credential_material_count: int
    idempotency_key: str
    packets: tuple[DryRunPacket, ...]


@dataclass(frozen=True)
class ProviderDryRunCanaryEnvelope:
    state: str
    action: str
    reason_codes: tuple[str, ...]
    snapshot_id: str
    epoch_id: str
    route_results: tuple[RouteDryRunResult, ...]
    route_count: int
    provider_packet_count: int
    normalized_response_count: int
    dual_provider_arbitration_count: int
    network_call_count: int
    credential_material_count: int
    budget_preflight_ready: bool
    idempotency_preflight_ready: bool
    serialization_ready: bool
    provider_isolation_ready: bool
    response_normalization_ready: bool
    arbitration_ready: bool
    observer_only: bool
    proposal_only: bool
    provider_invocation_enabled: bool
    credential_resolution_enabled: bool
    runtime_binding_enabled: bool
    shadow_state_mutation_enabled: bool
    ledger_write_enabled: bool
    execution_authority: str
    order_authority: str
    same_epoch_auto_apply: bool
    human_approval_required: bool
    fail_closed: bool
