from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from policy import zbot_idempotency
from policy import zbot_prompt
from policy.zbot_budget import ProviderPrice, project_cost
from policy.zbot_dryrun_types import (
    DryRunPacket,
    DryRunTransportPolicy,
    TransportCompileResult,
)
from policy.zbot_shadow_types import ObserverRoutePlan

POLICY_OWNER = "policy/zbot_dryrun_transport.py"
NETWORK_CALL_ENABLED = False
CREDENTIAL_RESOLUTION_ENABLED = False
RUNTIME_ENABLED = False


@dataclass(frozen=True)
class ProviderDryRunSpec:
    provider_id: str
    endpoint_alias: str
    model_alias: str
    adapter_schema: str


@dataclass(frozen=True)
class _DecisionStub:
    state: str
    request_id: str
    task_kind: str
    epoch_id: str
    required_providers: tuple[str, ...]
    input_evidence_ids: tuple[str, ...]


PROVIDER_DRYRUN_SPECS = MappingProxyType({
    "openai": ProviderDryRunSpec(
        provider_id="openai",
        endpoint_alias="openai.responses",
        model_alias="openai:zbot-primary",
        adapter_schema="openai.responses.dryrun.v1",
    ),
    "gemini": ProviderDryRunSpec(
        provider_id="gemini",
        endpoint_alias="gemini.generate_content",
        model_alias="gemini:zbot-primary",
        adapter_schema="gemini.generate_content.dryrun.v1",
    ),
})

_SECRET_MARKERS = (
    "authorization",
    "api_key",
    "x-api-key",
    "secret",
    "credential",
    "bearer",
    "access_token",
)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def contains_secret_material(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized = str(key).lower()
            if any(marker in normalized for marker in _SECRET_MARKERS):
                return True
            if contains_secret_material(nested):
                return True
        return False
    if isinstance(value, (list, tuple)):
        return any(contains_secret_material(item) for item in value)
    if isinstance(value, str):
        lowered = value.lower()
        return lowered.startswith(("bearer ", "sk-"))
    return False


def _provider_body(
    plan: ObserverRoutePlan,
    *,
    spec: ProviderDryRunSpec,
    prompt: zbot_prompt.PromptSpec,
    transport_policy: DryRunTransportPolicy,
) -> dict[str, Any]:
    common = {
        "request_id": plan.request_id,
        "route_id": plan.route_id,
        "task_kind": plan.task_kind,
        "prompt_id": prompt.prompt_id,
        "prompt_version": prompt.version,
        "prompt_template_hash": prompt.template_hash,
        "response_schema_id": prompt.response_schema_id,
        "evidence_ids": list(plan.evidence_ids),
        "source_refs": list(plan.source_refs),
        "requested_action": "hold",
    }
    if spec.provider_id == "openai":
        return {
            "adapter_schema": spec.adapter_schema,
            "model_alias": spec.model_alias,
            "input": [
                {"role": "system", "content_ref": prompt.template_hash},
                {"role": "user", "input": common},
            ],
            "response_schema_id": prompt.response_schema_id,
            "max_output_tokens": transport_policy.requested_output_tokens,
            "temperature": 0,
        }
    return {
        "adapter_schema": spec.adapter_schema,
        "model_alias": spec.model_alias,
        "contents": [
            {"role": "user", "parts": [{"prompt_ref": prompt.template_hash}, {"input": common}]},
        ],
        "generation_config": {
            "response_schema_id": prompt.response_schema_id,
            "max_output_tokens": transport_policy.requested_output_tokens,
            "temperature": 0,
        },
    }


def compile_dryrun_packets(
    plan: ObserverRoutePlan,
    *,
    epoch_id: str,
    transport_policy: DryRunTransportPolicy,
    provider_prices: Mapping[str, ProviderPrice],
    prior_idempotency_keys: Sequence[str] = (),
) -> TransportCompileResult:
    reasons: list[str] = []
    if not plan.route_id or not plan.request_id or not epoch_id:
        reasons.append("DRYRUN_ROUTE_IDENTITY_INVALID")
    if plan.provider_invocation_enabled:
        reasons.append("DRYRUN_SOURCE_PLAN_INVOCATION_ENABLED")
    if plan.proposed_action != "hold":
        reasons.append("DRYRUN_SOURCE_ACTION_NOT_HOLD")
    if plan.provider_request_count != len(plan.required_providers):
        reasons.append("DRYRUN_PROVIDER_COUNT_MISMATCH")
    if not plan.required_providers or len(set(plan.required_providers)) != len(plan.required_providers):
        reasons.append("DRYRUN_PROVIDER_SET_INVALID")
    if transport_policy.estimated_input_tokens <= 0 or transport_policy.requested_output_tokens <= 0:
        reasons.append("DRYRUN_TOKEN_ESTIMATE_INVALID")
    if transport_policy.response_delay_ms < 0 or not transport_policy.policy_ref:
        reasons.append("DRYRUN_TRANSPORT_POLICY_INVALID")

    prompt = zbot_prompt.get_prompt(plan.task_kind)
    if prompt is None:
        reasons.append("DRYRUN_PROMPT_UNREGISTERED")
    decision = _DecisionStub(
        state="PROPOSAL_READY",
        request_id=plan.request_id,
        task_kind=plan.task_kind,
        epoch_id=epoch_id,
        required_providers=plan.required_providers,
        input_evidence_ids=plan.evidence_ids,
    )
    idempotency = zbot_idempotency.evaluate_idempotency(
        decision,
        prompt_id=prompt.prompt_id if prompt else "",
        prompt_version=prompt.version if prompt else "",
        prior_keys=prior_idempotency_keys,
    )
    if idempotency.state != "READY":
        reasons.extend(idempotency.reason_codes)

    packets: list[DryRunPacket] = []
    if not reasons and prompt is not None:
        for provider_id in plan.required_providers:
            spec = PROVIDER_DRYRUN_SPECS.get(provider_id)
            price = provider_prices.get(provider_id)
            if spec is None:
                reasons.append("DRYRUN_PROVIDER_SPEC_MISSING")
                continue
            if price is None or price.provider_id != provider_id or not price.price_ref:
                reasons.append("DRYRUN_PROVIDER_PRICE_INVALID")
                continue
            dispatch_key = _sha256(f"{idempotency.idempotency_key}:{provider_id}")
            headers = (
                ("content-type", "application/json"),
                ("x-zbot-request-id", plan.request_id),
                ("x-zbot-dispatch-key", dispatch_key),
            )
            body = _provider_body(
                plan,
                spec=spec,
                prompt=prompt,
                transport_policy=transport_policy,
            )
            body_json = _canonical_json(body)
            credential_present = contains_secret_material(body) or contains_secret_material(headers)
            if credential_present:
                reasons.append("DRYRUN_CREDENTIAL_MATERIAL_PRESENT")
            packets.append(DryRunPacket(
                route_id=plan.route_id,
                provider_id=provider_id,
                request_id=plan.request_id,
                task_kind=plan.task_kind,
                prompt_id=prompt.prompt_id,
                prompt_version=prompt.version,
                response_schema_id=prompt.response_schema_id,
                endpoint_alias=spec.endpoint_alias,
                model_alias=spec.model_alias,
                headers=headers,
                body_json=body_json,
                body_sha256=_sha256(body_json),
                idempotency_key=idempotency.idempotency_key,
                dispatch_key=dispatch_key,
                estimated_input_tokens=transport_policy.estimated_input_tokens,
                requested_output_tokens=transport_policy.requested_output_tokens,
                projected_cost_micro_usd=project_cost(
                    transport_policy.estimated_input_tokens,
                    transport_policy.requested_output_tokens,
                    price,
                ),
                network_call_performed=False,
                credential_material_present=credential_present,
            ))

    isolation_valid = (
        len(packets) == len(plan.required_providers)
        and len({packet.dispatch_key for packet in packets}) == len(packets)
        and len({packet.provider_id for packet in packets}) == len(packets)
    )
    credential_valid = all(not packet.credential_material_present for packet in packets)
    if packets and not isolation_valid:
        reasons.append("DRYRUN_PROVIDER_ISOLATION_INVALID")
    if packets and not credential_valid:
        reasons.append("DRYRUN_CREDENTIAL_BOUNDARY_INVALID")
    if any(packet.network_call_performed for packet in packets):
        reasons.append("DRYRUN_NETWORK_CALL_DETECTED")

    state = "READY" if not reasons else "HOLD"
    return TransportCompileResult(
        state=state,
        reason_codes=tuple(sorted(set(reasons))) if reasons else ("DRYRUN_TRANSPORT_READY",),
        route_id=plan.route_id,
        idempotency_key=idempotency.idempotency_key,
        packets=tuple(packets),
        provider_isolation_valid=isolation_valid and not reasons,
        credential_boundary_valid=credential_valid and not reasons,
        network_call_count=sum(1 for packet in packets if packet.network_call_performed),
        fail_closed=True,
    )

