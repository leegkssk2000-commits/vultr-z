from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from policy.zbot_attribution import AttributionResult
from policy.zbot_drift import DriftResult

POLICY_OWNER = "policy/zbot_sgrade.py"
RUNTIME_ENABLED = False
PROVIDER_INVOCATION_ENABLED = False
EXECUTION_AUTHORITY = "none"
ORDER_AUTHORITY = "none"
TOTAL_SURFACE_COUNT = 24


@dataclass(frozen=True)
class SGradeLockResult:
    state: str
    reason_codes: tuple[str, ...]
    ready_surface_count: int
    remaining_surface_count: int
    attribution_ready: bool
    quality_drift_ready: bool
    observer_only: bool
    proposal_only: bool
    provider_invocation_enabled: bool
    runtime_enabled: bool
    execution_authority: str
    order_authority: str
    human_approval_required: bool
    same_epoch_auto_apply: bool
    sgrade_ready: bool
    fail_closed: bool


def evaluate_sgrade_lock(
    *,
    prior_ready_surface_count: int,
    closed_surfaces: Sequence[str],
    attribution: AttributionResult,
    drift: DriftResult,
    observer_only: bool,
    proposal_only: bool,
    provider_invocation_enabled: bool,
    runtime_enabled: bool,
    execution_authority: str,
    order_authority: str,
    human_approval_required: bool,
    same_epoch_auto_apply: bool,
) -> SGradeLockResult:
    reasons: list[str] = []
    expected_closed = {"cost_performance_attribution", "model_quality_drift_evaluation"}
    if set(closed_surfaces) != expected_closed:
        reasons.append("SGRADE_CLOSED_SURFACE_SET_INVALID")
    if prior_ready_surface_count != TOTAL_SURFACE_COUNT - len(expected_closed):
        reasons.append("SGRADE_PRIOR_SURFACE_COUNT_INVALID")
    ready_surface_count = prior_ready_surface_count + len(expected_closed)
    if ready_surface_count != TOTAL_SURFACE_COUNT:
        reasons.append("SGRADE_TOTAL_SURFACE_COUNT_INVALID")
    if attribution.state != "READY" or not attribution.attribution_ready:
        reasons.append("SGRADE_ATTRIBUTION_NOT_READY")
    if drift.state != "READY" or not drift.quality_drift_ready or drift.drifted_provider_count != 0:
        reasons.append("SGRADE_DRIFT_NOT_READY")
    if not observer_only or not proposal_only:
        reasons.append("SGRADE_OBSERVER_PROPOSAL_BOUNDARY_INVALID")
    if provider_invocation_enabled or runtime_enabled:
        reasons.append("SGRADE_RUNTIME_PROVIDER_BOUNDARY_INVALID")
    if execution_authority != "none" or order_authority != "none":
        reasons.append("SGRADE_AUTHORITY_BOUNDARY_INVALID")
    if not human_approval_required or same_epoch_auto_apply:
        reasons.append("SGRADE_APPROVAL_BOUNDARY_INVALID")

    state = "PASS" if not reasons else "HOLD"
    return SGradeLockResult(
        state=state,
        reason_codes=tuple(sorted(set(reasons))) if reasons else ("ZBOT_SGRADE_LOCK_PASS",),
        ready_surface_count=ready_surface_count if not reasons else prior_ready_surface_count,
        remaining_surface_count=0 if not reasons else TOTAL_SURFACE_COUNT - prior_ready_surface_count,
        attribution_ready=attribution.attribution_ready,
        quality_drift_ready=drift.quality_drift_ready and drift.drifted_provider_count == 0,
        observer_only=observer_only,
        proposal_only=proposal_only,
        provider_invocation_enabled=provider_invocation_enabled,
        runtime_enabled=runtime_enabled,
        execution_authority=execution_authority,
        order_authority=order_authority,
        human_approval_required=human_approval_required,
        same_epoch_auto_apply=same_epoch_auto_apply,
        sgrade_ready=not reasons,
        fail_closed=True,
    )
