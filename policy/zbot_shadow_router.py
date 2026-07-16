from __future__ import annotations

from types import MappingProxyType
from typing import Sequence

from canonical import zbot
from policy.zbot_shadow_types import (
    ObserverRoutePlan,
    ShadowObserverEnvelope,
    ShadowObserverPolicy,
    ShadowSnapshot,
)
from policy.zbot_shadow_validation import validate_shadow_snapshot

POLICY_OWNER = "policy/zbot_shadow_router.py"
OBSERVER_ONLY = True
PROPOSAL_ONLY = True
PROVIDER_INVOCATION_ENABLED = False
RUNTIME_BINDING_ENABLED = False
SHADOW_STATE_MUTATION_ENABLED = False
LEDGER_WRITE_ENABLED = False
EXECUTION_AUTHORITY = "none"
ORDER_AUTHORITY = "none"
SAME_EPOCH_AUTO_APPLY = False
HUMAN_APPROVAL_REQUIRED = True


def _hold(snapshot: ShadowSnapshot, reasons: Sequence[str]) -> ShadowObserverEnvelope:
    return ShadowObserverEnvelope(
        state="HOLD",
        action="hold",
        reason_codes=tuple(sorted(set(reasons))),
        snapshot_id=snapshot.snapshot_id,
        epoch_id=snapshot.epoch_id,
        route_plans=(),
        closed_delta=0,
        point_in_time_valid=False,
        source_lineage_valid=False,
        count_integrity_valid=False,
        ledger_integrity_valid=False,
        sgrade_valid=False,
        observer_only=True,
        proposal_only=True,
        provider_invocation_enabled=False,
        runtime_binding_enabled=False,
        shadow_state_mutation_enabled=False,
        ledger_write_enabled=False,
        execution_authority="none",
        order_authority="none",
        same_epoch_auto_apply=False,
        human_approval_required=True,
        fail_closed=True,
    )


def _build_route(
    snapshot: ShadowSnapshot,
    *,
    trigger_kind: str,
    task_kind: str,
) -> ObserverRoutePlan | None:
    evidence = (
        zbot.EvidenceItem(
            evidence_id=f"shadow:{snapshot.snapshot_id}",
            source_ref=snapshot.shadow_source_ref,
            available_at_ms=snapshot.observed_at_ms,
            schema_version=snapshot.schema_version,
        ),
        zbot.EvidenceItem(
            evidence_id=f"market:{snapshot.snapshot_id}",
            source_ref=snapshot.market_source_ref,
            available_at_ms=snapshot.observed_at_ms,
            schema_version=snapshot.schema_version,
        ),
        zbot.EvidenceItem(
            evidence_id=f"position:{snapshot.snapshot_id}",
            source_ref=snapshot.position_source_ref,
            available_at_ms=snapshot.observed_at_ms,
            schema_version=snapshot.schema_version,
        ),
        zbot.EvidenceItem(
            evidence_id=f"ledger:{snapshot.ledger_sha256}",
            source_ref=snapshot.ledger_source_ref,
            available_at_ms=snapshot.observed_at_ms,
            schema_version=snapshot.schema_version,
        ),
    )
    request = zbot.ZBotTaskRequest(
        request_id=f"zbot.shadow.{snapshot.snapshot_id}.{task_kind}",
        task_kind=task_kind,
        decision_ts_ms=snapshot.observed_at_ms,
        epoch_id=snapshot.epoch_id,
        evidence=evidence,
        payload=MappingProxyType({
            "snapshot_id": snapshot.snapshot_id,
            "epoch_id": snapshot.epoch_id,
            "candidate_count": snapshot.candidate_count,
            "open_count": snapshot.open_count,
            "closed_count": snapshot.closed_count,
            "pnl_r": snapshot.pnl_r,
            "ledger_row_count": snapshot.ledger_row_count,
            "trigger_kind": trigger_kind,
        }),
        requested_action="hold",
    )
    decision = zbot.build_provider_requests(request)
    if decision.state != "PROPOSAL_READY":
        return None
    if decision.runtime_enabled or decision.execution_authority != "none" or decision.order_authority != "none":
        return None
    return ObserverRoutePlan(
        route_id=f"route:{snapshot.snapshot_id}:{trigger_kind}",
        trigger_kind=trigger_kind,
        task_kind=task_kind,
        request_id=decision.request_id,
        required_providers=decision.required_providers,
        evidence_ids=decision.input_evidence_ids,
        source_refs=decision.source_refs,
        proposed_action=decision.action,
        provider_request_count=len(decision.provider_requests),
        provider_invocation_enabled=False,
    )


def build_shadow_observer_plan(
    snapshot: ShadowSnapshot,
    *,
    now_ms: int,
    policy: ShadowObserverPolicy,
    sgrade_ready: bool,
    previous_snapshot: ShadowSnapshot | None = None,
) -> ShadowObserverEnvelope:
    validation = validate_shadow_snapshot(
        snapshot,
        now_ms=now_ms,
        policy=policy,
        sgrade_ready=sgrade_ready,
        previous_snapshot=previous_snapshot,
    )
    if validation.state != "READY":
        return _hold(snapshot, validation.reason_codes)

    route_specs: list[tuple[str, str]] = [("snapshot_tick", "market_context_review")]
    if snapshot.open_count > 0:
        route_specs.append(("active_position", "risk_review"))
    if validation.closed_delta > 0:
        route_specs.append(("closed_trade_delta", "post_trade_explanation"))
        if snapshot.closed_count >= policy.optimization_min_closed:
            route_specs.append(("optimization_sample_ready", "optimization_candidate_review"))

    plans: list[ObserverRoutePlan] = []
    for trigger_kind, task_kind in route_specs:
        plan = _build_route(snapshot, trigger_kind=trigger_kind, task_kind=task_kind)
        if plan is None:
            return _hold(snapshot, ("ZBOT_ROUTE_PLAN_INVALID",))
        plans.append(plan)

    return ShadowObserverEnvelope(
        state="PLAN_READY",
        action="hold",
        reason_codes=("ZBOT_SHADOW_OBSERVER_GATE_READY",),
        snapshot_id=snapshot.snapshot_id,
        epoch_id=snapshot.epoch_id,
        route_plans=tuple(plans),
        closed_delta=validation.closed_delta,
        point_in_time_valid=True,
        source_lineage_valid=True,
        count_integrity_valid=True,
        ledger_integrity_valid=True,
        sgrade_valid=True,
        observer_only=True,
        proposal_only=True,
        provider_invocation_enabled=False,
        runtime_binding_enabled=False,
        shadow_state_mutation_enabled=False,
        ledger_write_enabled=False,
        execution_authority="none",
        order_authority="none",
        same_epoch_auto_apply=False,
        human_approval_required=True,
        fail_closed=True,
    )
