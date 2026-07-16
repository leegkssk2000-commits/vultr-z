from __future__ import annotations

from dataclasses import dataclass

POLICY_OWNER = "policy/zbot_shadow_types.py"


@dataclass(frozen=True)
class ShadowSnapshot:
    snapshot_id: str
    epoch_id: str
    observed_at_ms: int
    schema_version: str
    shadow_source_ref: str
    market_source_ref: str
    position_source_ref: str
    ledger_source_ref: str
    candidate_count: int
    open_count: int
    closed_count: int
    pnl_r: float
    ledger_row_count: int
    ledger_sha256: str


@dataclass(frozen=True)
class ShadowObserverPolicy:
    snapshot_max_age_ms: int
    max_future_skew_ms: int
    optimization_min_closed: int
    policy_ref: str


@dataclass(frozen=True)
class ObserverRoutePlan:
    route_id: str
    trigger_kind: str
    task_kind: str
    request_id: str
    required_providers: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    source_refs: tuple[str, ...]
    proposed_action: str
    provider_request_count: int
    provider_invocation_enabled: bool


@dataclass(frozen=True)
class ShadowObserverEnvelope:
    state: str
    action: str
    reason_codes: tuple[str, ...]
    snapshot_id: str
    epoch_id: str
    route_plans: tuple[ObserverRoutePlan, ...]
    closed_delta: int
    point_in_time_valid: bool
    source_lineage_valid: bool
    count_integrity_valid: bool
    ledger_integrity_valid: bool
    sgrade_valid: bool
    observer_only: bool
    proposal_only: bool
    provider_invocation_enabled: bool
    runtime_binding_enabled: bool
    shadow_state_mutation_enabled: bool
    ledger_write_enabled: bool
    execution_authority: str
    order_authority: str
    same_epoch_auto_apply: bool
    human_approval_required: bool
    fail_closed: bool
