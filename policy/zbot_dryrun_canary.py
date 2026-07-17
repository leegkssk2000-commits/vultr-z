from __future__ import annotations

from typing import Mapping, Sequence

from policy import zbot_arbitration
from policy import zbot_budget
from policy import zbot_response
from policy.zbot_dryrun_transport import compile_dryrun_packets
from policy.zbot_dryrun_types import (
    DryRunPacket,
    DryRunTransportPolicy,
    ProviderDryRunCanaryEnvelope,
    RouteDryRunResult,
)
from policy.zbot_shadow_types import ObserverRoutePlan, ShadowObserverEnvelope

POLICY_OWNER = "policy/zbot_dryrun_canary.py"
OBSERVER_ONLY = True
PROPOSAL_ONLY = True
PROVIDER_INVOCATION_ENABLED = False
CREDENTIAL_RESOLUTION_ENABLED = False
RUNTIME_BINDING_ENABLED = False
SHADOW_STATE_MUTATION_ENABLED = False
LEDGER_WRITE_ENABLED = False
EXECUTION_AUTHORITY = "none"
ORDER_AUTHORITY = "none"
SAME_EPOCH_AUTO_APPLY = False
HUMAN_APPROVAL_REQUIRED = True


def _route_result(
    plan: ObserverRoutePlan,
    *,
    reasons: Sequence[str],
    packets: Sequence[DryRunPacket] = (),
    normalized_count: int = 0,
    arbitration_state: str = "NOT_RUN",
    budget_valid: bool = False,
    idempotency_valid: bool = False,
    provider_isolation_valid: bool = False,
    response_path_valid: bool = False,
    idempotency_key: str = "",
) -> RouteDryRunResult:
    state = "READY" if not reasons else "HOLD"
    return RouteDryRunResult(
        state=state,
        reason_codes=tuple(sorted(set(reasons))) if reasons else ("DRYRUN_ROUTE_READY",),
        route_id=plan.route_id,
        request_id=plan.request_id,
        packet_count=len(packets),
        normalized_response_count=normalized_count,
        arbitration_state=arbitration_state,
        budget_valid=budget_valid,
        idempotency_valid=idempotency_valid,
        provider_isolation_valid=provider_isolation_valid,
        response_path_valid=response_path_valid,
        network_call_count=sum(1 for packet in packets if packet.network_call_performed),
        credential_material_count=sum(1 for packet in packets if packet.credential_material_present),
        idempotency_key=idempotency_key,
        packets=tuple(packets),
    )


def _fixture_response(
    packet: DryRunPacket,
    plan: ObserverRoutePlan,
    *,
    generated_at_ms: int,
) -> dict[str, object]:
    confidence = 0.82 if packet.provider_id == "openai" else 0.80
    return {
        "provider_id": packet.provider_id,
        "request_id": packet.request_id,
        "task_kind": packet.task_kind,
        "prompt_id": packet.prompt_id,
        "prompt_version": packet.prompt_version,
        "response_schema_id": packet.response_schema_id,
        "model_id": packet.model_alias,
        "generated_at_ms": generated_at_ms,
        "recommendation_action": "hold",
        "confidence": confidence,
        "thesis": f"Dry-run fixture for {plan.trigger_kind}; no provider network call.",
        "risks": ["dry-run fixture only", "human approval required"],
        "evidence_ids": list(plan.evidence_ids),
        "source_refs": list(plan.source_refs),
        "input_tokens": packet.estimated_input_tokens,
        "output_tokens": packet.requested_output_tokens,
        "cost_micro_usd": packet.projected_cost_micro_usd,
    }


def _evaluate_route(
    plan: ObserverRoutePlan,
    *,
    epoch_id: str,
    decision_ts_ms: int,
    transport_policy: DryRunTransportPolicy,
    usage: Mapping[str, zbot_budget.UsageSnapshot],
    prices: Mapping[str, zbot_budget.ProviderPrice],
    budget_policy: zbot_budget.BudgetPolicy,
    arbitration_policy: zbot_arbitration.ArbitrationPolicy,
    prior_idempotency_keys: Sequence[str],
) -> RouteDryRunResult:
    reasons: list[str] = []
    budget = zbot_budget.evaluate_budget(
        plan.required_providers,
        estimated_input_tokens=transport_policy.estimated_input_tokens,
        requested_output_tokens=transport_policy.requested_output_tokens,
        usage=usage,
        prices=prices,
        policy=budget_policy,
    )
    budget_valid = budget.state == "READY" and budget.token_budget_valid and budget.cost_budget_valid
    if not budget_valid:
        reasons.extend(budget.reason_codes)

    transport = compile_dryrun_packets(
        plan,
        epoch_id=epoch_id,
        transport_policy=transport_policy,
        provider_prices=prices,
        prior_idempotency_keys=prior_idempotency_keys,
    )
    if transport.state != "READY":
        reasons.extend(transport.reason_codes)
    if reasons:
        return _route_result(
            plan,
            reasons=reasons,
            packets=transport.packets,
            budget_valid=budget_valid,
            idempotency_valid=transport.state == "READY",
            provider_isolation_valid=transport.provider_isolation_valid,
            idempotency_key=transport.idempotency_key,
        )

    received_at_ms = decision_ts_ms + transport_policy.response_delay_ms
    generated_at_ms = decision_ts_ms + transport_policy.response_delay_ms // 2
    expectation = zbot_response.ResponseExpectation(
        request_id=plan.request_id,
        task_kind=plan.task_kind,
        provider_ids=plan.required_providers,
        prompt_id=transport.packets[0].prompt_id,
        prompt_version=transport.packets[0].prompt_version,
        response_schema_id=transport.packets[0].response_schema_id,
        decision_ts_ms=decision_ts_ms,
        received_at_ms=received_at_ms,
        evidence_ids=plan.evidence_ids,
        source_refs=plan.source_refs,
    )
    raw = tuple(
        _fixture_response(packet, plan, generated_at_ms=generated_at_ms)
        for packet in transport.packets
    )
    normalized = zbot_response.normalize_response_set(raw, expectation)
    normalized_count = sum(1 for result in normalized if result.state == "NORMALIZED")
    if normalized_count != len(transport.packets):
        reasons.append("DRYRUN_RESPONSE_NORMALIZATION_FAILED")

    arbitration_state = "NOT_REQUIRED_SINGLE_PROVIDER"
    response_path_valid = normalized_count == len(transport.packets)
    if len(plan.required_providers) > 1 and response_path_valid:
        arbitration = zbot_arbitration.arbitrate_responses(
            normalized,
            expected_provider_ids=plan.required_providers,
            policy=arbitration_policy,
        )
        arbitration_state = arbitration.state
        if arbitration.state != "PROPOSAL_READY":
            reasons.extend(arbitration.reason_codes)
        response_path_valid = arbitration.state == "PROPOSAL_READY"
    elif len(plan.required_providers) == 1 and response_path_valid:
        only = normalized[0]
        response_path_valid = only.response is not None and only.response.provider_id == plan.required_providers[0]
        if not response_path_valid:
            reasons.append("DRYRUN_SINGLE_PROVIDER_RESPONSE_INVALID")

    return _route_result(
        plan,
        reasons=reasons,
        packets=transport.packets,
        normalized_count=normalized_count,
        arbitration_state=arbitration_state,
        budget_valid=budget_valid,
        idempotency_valid=True,
        provider_isolation_valid=transport.provider_isolation_valid,
        response_path_valid=response_path_valid,
        idempotency_key=transport.idempotency_key,
    )


def evaluate_provider_dryrun_canary(
    observer: ShadowObserverEnvelope,
    *,
    decision_ts_ms: int,
    transport_policy: DryRunTransportPolicy,
    usage: Mapping[str, zbot_budget.UsageSnapshot],
    prices: Mapping[str, zbot_budget.ProviderPrice],
    budget_policy: zbot_budget.BudgetPolicy,
    arbitration_policy: zbot_arbitration.ArbitrationPolicy,
    prior_idempotency_keys: Sequence[str] = (),
) -> ProviderDryRunCanaryEnvelope:
    reasons: list[str] = []
    if observer.state != "PLAN_READY" or not observer.route_plans:
        reasons.append("R61_OBSERVER_PLAN_NOT_READY")
    if not all((
        observer.observer_only,
        observer.proposal_only,
        observer.point_in_time_valid,
        observer.source_lineage_valid,
        observer.count_integrity_valid,
        observer.ledger_integrity_valid,
        observer.sgrade_valid,
        observer.human_approval_required,
        observer.fail_closed,
    )):
        reasons.append("R61_OBSERVER_INTEGRITY_INVALID")
    if any((
        observer.provider_invocation_enabled,
        observer.runtime_binding_enabled,
        observer.shadow_state_mutation_enabled,
        observer.ledger_write_enabled,
        observer.same_epoch_auto_apply,
    )):
        reasons.append("R61_OBSERVER_AUTHORITY_BOUNDARY_INVALID")
    if observer.execution_authority != "none" or observer.order_authority != "none":
        reasons.append("R61_OBSERVER_AUTHORITY_INVALID")
    if decision_ts_ms < 0:
        reasons.append("DRYRUN_DECISION_TIMESTAMP_INVALID")

    route_ids = tuple(plan.route_id for plan in observer.route_plans)
    request_ids = tuple(plan.request_id for plan in observer.route_plans)
    if len(set(route_ids)) != len(route_ids) or len(set(request_ids)) != len(request_ids):
        reasons.append("DRYRUN_DUPLICATE_ROUTE_OR_REQUEST")

    route_results: list[RouteDryRunResult] = []
    working_usage = dict(usage)
    seen_keys = set(prior_idempotency_keys)
    if not reasons:
        for plan in observer.route_plans:
            result = _evaluate_route(
                plan,
                epoch_id=observer.epoch_id,
                decision_ts_ms=decision_ts_ms,
                transport_policy=transport_policy,
                usage=working_usage,
                prices=prices,
                budget_policy=budget_policy,
                arbitration_policy=arbitration_policy,
                prior_idempotency_keys=tuple(seen_keys),
            )
            route_results.append(result)
            if result.idempotency_key:
                seen_keys.add(result.idempotency_key)
            if result.state == "READY":
                for packet in result.packets:
                    previous = working_usage[packet.provider_id]
                    working_usage[packet.provider_id] = zbot_budget.UsageSnapshot(
                        provider_id=packet.provider_id,
                        input_tokens=previous.input_tokens + packet.estimated_input_tokens,
                        output_tokens=previous.output_tokens + packet.requested_output_tokens,
                        cost_micro_usd=previous.cost_micro_usd + packet.projected_cost_micro_usd,
                    )
            else:
                reasons.extend(result.reason_codes)

    provider_packet_count = sum(result.packet_count for result in route_results)
    normalized_count = sum(result.normalized_response_count for result in route_results)
    arbitration_count = sum(1 for result in route_results if result.arbitration_state == "PROPOSAL_READY")
    network_count = sum(result.network_call_count for result in route_results)
    credential_count = sum(result.credential_material_count for result in route_results)
    if network_count != 0:
        reasons.append("DRYRUN_NETWORK_CALL_DETECTED")
    if credential_count != 0:
        reasons.append("DRYRUN_CREDENTIAL_MATERIAL_DETECTED")

    all_ready = bool(route_results) and all(result.state == "READY" for result in route_results)
    budget_ready = all_ready and all(result.budget_valid for result in route_results)
    idempotency_ready = all_ready and all(result.idempotency_valid for result in route_results)
    serialization_ready = all_ready and provider_packet_count == normalized_count
    isolation_ready = all_ready and all(result.provider_isolation_valid for result in route_results)
    response_ready = all_ready and all(result.response_path_valid for result in route_results)
    arbitration_ready = response_ready and all(
        result.arbitration_state in {"PROPOSAL_READY", "NOT_REQUIRED_SINGLE_PROVIDER"}
        for result in route_results
    )
    state = "PASS" if not reasons and all_ready else "HOLD"
    return ProviderDryRunCanaryEnvelope(
        state=state,
        action="hold",
        reason_codes=tuple(sorted(set(reasons))) if reasons else ("ZBOT_PROVIDER_DRYRUN_CANARY_PASS",),
        snapshot_id=observer.snapshot_id,
        epoch_id=observer.epoch_id,
        route_results=tuple(route_results),
        route_count=len(route_results),
        provider_packet_count=provider_packet_count,
        normalized_response_count=normalized_count,
        dual_provider_arbitration_count=arbitration_count,
        network_call_count=network_count,
        credential_material_count=credential_count,
        budget_preflight_ready=budget_ready,
        idempotency_preflight_ready=idempotency_ready,
        serialization_ready=serialization_ready,
        provider_isolation_ready=isolation_ready,
        response_normalization_ready=response_ready,
        arbitration_ready=arbitration_ready,
        observer_only=True,
        proposal_only=True,
        provider_invocation_enabled=False,
        credential_resolution_enabled=False,
        runtime_binding_enabled=False,
        shadow_state_mutation_enabled=False,
        ledger_write_enabled=False,
        execution_authority="none",
        order_authority="none",
        same_epoch_auto_apply=False,
        human_approval_required=True,
        fail_closed=True,
    )
