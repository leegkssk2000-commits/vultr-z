from __future__ import annotations

import copy
from typing import Any, Mapping

from backend.contracts.strategy11_source_binding_contract_v1 import (
    SAFETY,
    SCHEMA_VERSION as BINDING_SCHEMA_VERSION,
    SourceBindingError,
    bind_package,
    canonical_sha,
    validate_authority,
    validate_source,
)

ADAPTER_INPUT_SCHEMA = "strategy11.real_w1_exact_sha_adapter.input.v1"
ADAPTER_OUTPUT_SCHEMA = "strategy11.real_w1_exact_sha_adapter.output.v1"
PASS_STATES = {"PASS_W1_PRIMARY_CONFIRMATION", "PASS_W1_PRIMARY_CAUSAL_REPLAY"}
REQUIRED_CONTEXT_SOURCES = {
    "proposal_context",
    "classifier_evidence",
    "correlation_ledger",
    "portfolio_policy",
    "source_ledger",
    "source_history",
    "role_lineage",
    "role_messages",
    "model_risk_baseline",
    "model_risk_policy",
}


class RealW1AdapterError(ValueError):
    pass


def _fail(code: str, detail: str = "") -> None:
    raise RealW1AdapterError(f"{code}:{detail}" if detail else code)


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail("OBJECT_REQUIRED", name)
    return dict(value)


def _string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail("STRING_REQUIRED", name)
    return value.strip()


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail("NUMBER_REQUIRED", name)
    return float(value)


def _integer(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        _fail("INT_REQUIRED", name)
    return value


def _sha(value: Any, name: str) -> str:
    result = _string(value, name).lower()
    if len(result) != 64 or any(char not in "0123456789abcdef" for char in result):
        _fail("SHA256_REQUIRED", name)
    return result


def _normalized_source(source_id: str, value: Any) -> dict[str, Any]:
    try:
        return validate_source(source_id, value)
    except SourceBindingError as exc:
        raise RealW1AdapterError(str(exc)) from exc


def _variant(primary: Mapping[str, Any], candidate_id: str) -> dict[str, Any]:
    active = primary.get("active_candidate_queue")
    if not isinstance(active, list) or candidate_id not in active:
        _fail("CANDIDATE_NOT_ACTIVE", candidate_id)
    variants = primary.get("variants")
    if not isinstance(variants, list):
        _fail("PRIMARY_VARIANTS_REQUIRED")
    matches = [dict(row) for row in variants if isinstance(row, Mapping) and str(row.get("variant_id")) == candidate_id]
    if len(matches) != 1:
        _fail("PRIMARY_VARIANT_MATCH_COUNT", f"{candidate_id}:{len(matches)}")
    return matches[0]


def _extract_proposal(
    primary_source: Mapping[str, Any],
    primary: Mapping[str, Any],
    candidate: Mapping[str, Any],
    context_source: Mapping[str, Any],
) -> dict[str, Any]:
    context = _mapping(context_source["document"], "proposal_context.document")
    required = {"producer", "market", "confidence", "cost_envelope", "risk_context", "lineage", "reason_codes", "metadata"}
    missing = sorted(required - set(context))
    if missing:
        _fail("PROPOSAL_CONTEXT_FIELDS_MISSING", ",".join(missing))

    cumulative = _mapping(candidate.get("cumulative_F1_F2_F3_W1"), "variant.cumulative_F1_F2_F3_W1")
    w1 = _mapping(candidate.get("W1"), "variant.W1")
    stress = _mapping(candidate.get("W1_stress_2x_p95_plus_one"), "variant.W1_stress_2x_p95_plus_one")
    gate = _mapping(candidate.get("W1_confirmation_gate"), "variant.W1_confirmation_gate")
    w1_loss = _mapping(w1.get("loss_metrics"), "variant.W1.loss_metrics")
    stress_loss = _mapping(stress.get("loss_metrics"), "variant.W1_stress.loss_metrics")
    risk_context = _mapping(context["risk_context"], "proposal_context.risk_context")
    lineage_context = _mapping(context["lineage"], "proposal_context.lineage")

    candidate_sha = _sha(candidate.get("candidate_config_sha256"), "variant.candidate_config_sha256")
    manifest_sha = _sha(primary.get("source_w1_manifest_sha256"), "primary.source_w1_manifest_sha256")
    if candidate.get("source_w1_manifest_sha256") not in {None, manifest_sha}:
        _fail("VARIANT_W1_MANIFEST_SHA_MISMATCH")

    source_run_id = _string(primary.get("source_w1_run_id"), "primary.source_w1_run_id")
    source_head_sha = _string(primary.get("source_w1_head_sha"), "primary.source_w1_head_sha")
    if source_run_id != primary_source["run_id"]:
        _fail("PRIMARY_SOURCE_RUN_ID_MISMATCH")

    total_windows = 4
    proposal = {
        "schema_version": "strategy11.strategy_proposal.v1",
        "proposal_id": f"w1.{primary['strategy_id']}.{candidate['variant_id']}.{source_run_id}",
        "strategy_id": _string(primary.get("strategy_id"), "primary.strategy_id"),
        "candidate_sha": candidate_sha,
        "producer": copy.deepcopy(context["producer"]),
        "market": copy.deepcopy(context["market"]),
        "edge": {
            "trades": _integer(cumulative.get("trade_count"), "cumulative.trade_count"),
            "win_rate_pct": _number(cumulative.get("win_rate_pct"), "cumulative.win_rate_pct"),
            "net_pct": _number(cumulative.get("net_return_pct_sum"), "cumulative.net_return_pct_sum"),
            "profit_factor": _number(cumulative.get("net_profit_factor"), "cumulative.net_profit_factor"),
            "payoff": _number(cumulative.get("payoff_ratio"), "cumulative.payoff_ratio"),
            "positive_windows": _integer(cumulative.get("positive_windows"), "cumulative.positive_windows"),
            "total_windows": total_windows,
            "retention_pct": _number(gate.get("trade_retention_pct"), "gate.trade_retention_pct"),
        },
        "confidence": copy.deepcopy(context["confidence"]),
        "cost_envelope": copy.deepcopy(context["cost_envelope"]),
        "risk_envelope": {
            "max_drawdown_pct": _number(cumulative.get("max_drawdown_pct"), "cumulative.max_drawdown_pct"),
            "avg_loss_r": _number(cumulative.get("avg_loss_R"), "cumulative.avg_loss_R"),
            "worst_loss_r": _number(cumulative.get("worst_net_loss_R"), "cumulative.worst_net_loss_R"),
            "stress_worst_loss_r": _number(stress_loss.get("normal_worst_net_loss_R"), "stress_loss.normal_worst_net_loss_R"),
            "joint_tail_budget_pct": _number(risk_context.get("joint_tail_budget_pct"), "risk_context.joint_tail_budget_pct"),
            "max_exposure_pct": _number(risk_context.get("max_exposure_pct"), "risk_context.max_exposure_pct"),
        },
        "lineage": {
            "strategy_source_sha": _sha(lineage_context.get("strategy_source_sha"), "lineage.strategy_source_sha"),
            "candidate_config_sha": candidate_sha,
            "data_sha": _sha(lineage_context.get("data_sha"), "lineage.data_sha"),
            "window_sha": _sha(lineage_context.get("window_sha"), "lineage.window_sha"),
            "source_manifest_sha": manifest_sha,
            "run_id": source_run_id,
            "artifact": primary_source["artifact"],
            "data_epoch": _string(lineage_context.get("data_epoch"), "lineage.data_epoch"),
        },
        "proposal_state": "REQUEST_EVALUATION",
        "reason_codes": copy.deepcopy(context["reason_codes"]),
        "authority": {
            "stage": "RESEARCH",
            "research_only": True,
            "promotion_authority": False,
            "execution_allowed": False,
            "order_authority": "BLOCKED",
            "protected_mutations": 0,
        },
        "metadata": {
            **copy.deepcopy(context["metadata"]),
            "adapter": "strategy11.real_w1_exact_sha_adapter.v1",
            "candidate_id": candidate["variant_id"],
            "primary_source_head_sha": source_head_sha,
            "primary_artifact_sha": primary_source["artifact_sha"],
            "proposal_context_artifact_sha": context_source["artifact_sha"],
            "field_origins": {
                "edge": {"source_artifact": primary_source["artifact"], "source_sha": primary_source["artifact_sha"], "field_path": "variants[].cumulative_F1_F2_F3_W1"},
                "risk_replay": {"source_artifact": primary_source["artifact"], "source_sha": primary_source["artifact_sha"], "field_path": "variants[].W1/W1_stress_2x_p95_plus_one"},
                "market_confidence_cost": {"source_artifact": context_source["artifact"], "source_sha": context_source["artifact_sha"], "field_path": "$"},
            },
        },
    }
    if proposal["risk_envelope"]["worst_loss_r"] > 0.0:
        _fail("WORST_LOSS_SIGN_INVALID")
    if proposal["risk_envelope"]["avg_loss_r"] > 0.0:
        _fail("AVG_LOSS_SIGN_INVALID")
    if proposal["edge"]["positive_windows"] > total_windows:
        _fail("POSITIVE_WINDOWS_EXCEED_TOTAL")
    return proposal


def _adapter_source(primary: Mapping[str, Any], context: Mapping[str, Any], proposal: Mapping[str, Any]) -> dict[str, Any]:
    document = copy.deepcopy(proposal)
    return {
        "source_kind": "DETERMINISTIC_PROPOSAL_ADAPTER",
        "artifact": f"w1-proposal-adapter-{primary['strategy_id']}-{proposal['metadata']['candidate_id']}",
        "run_id": _string(primary.get("source_w1_run_id"), "primary.source_w1_run_id"),
        "artifact_sha": canonical_sha(document),
        "document": document,
        "transform": "DETERMINISTIC_ADAPTER",
        "inference_used": False,
        "private_fields_present": False,
        "stale": False,
    }


def adapt(value: Mapping[str, Any]) -> dict[str, Any]:
    payload = _mapping(value, "adapter_input")
    allowed = {"schema_version", "candidate_id", "source_status", "primary_summary", "context_sources", "authority"}
    missing = sorted(allowed - set(payload))
    extra = sorted(set(payload) - allowed)
    if missing:
        _fail("ADAPTER_FIELDS_MISSING", ",".join(missing))
    if extra:
        _fail("ADAPTER_EXTRA_FIELDS", ",".join(extra))
    if payload.get("schema_version") != ADAPTER_INPUT_SCHEMA:
        _fail("ADAPTER_SCHEMA_MISMATCH")
    candidate_id = _string(payload.get("candidate_id"), "candidate_id")
    try:
        authority = validate_authority(payload.get("authority"))
    except SourceBindingError as exc:
        raise RealW1AdapterError(str(exc)) from exc

    source_status = _normalized_source("source_status", payload.get("source_status"))
    source_document = _mapping(source_status["document"], "source_status.document")
    state = _string(source_document.get("state"), "source_status.state")
    blockers = source_document.get("blockers")
    if blockers not in ([], None):
        _fail("SOURCE_STATUS_BLOCKED", str(blockers))

    if state == "WAIT_DATA":
        result = {
            "schema_version": ADAPTER_OUTPUT_SCHEMA,
            "state": "PASS_REAL_W1_EXACT_SHA_ADAPTER_WAIT_DATA",
            "candidate_id": candidate_id,
            "available_non_overlap_bars": _integer(source_document.get("available_non_overlap_bars"), "source_status.available_non_overlap_bars"),
            "missing_bars": _integer(source_document.get("missing_bars"), "source_status.missing_bars"),
            "next_eligible_window_end": source_document.get("next_eligible_window_end"),
            "source_status_artifact": source_status["artifact"],
            "source_status_sha": source_status["artifact_sha"],
            "proposal_created": False,
            "bound_package_created": False,
            "next": "RERUN_AFTER_SHARED_W1_PASS",
            "runtime_bound": False,
            **SAFETY,
        }
        result["adapter_result_sha"] = canonical_sha(result)
        return result

    if state != "PASS":
        _fail("SOURCE_STATUS_NOT_PASS_OR_WAIT", state)
    source_manifest_sha = _sha(source_document.get("W1_manifest_sha256"), "source_status.W1_manifest_sha256")

    primary_source = _normalized_source("primary_summary", payload.get("primary_summary"))
    primary = _mapping(primary_source["document"], "primary_summary.document")
    primary_state = _string(primary.get("state"), "primary.state")
    if primary_state not in PASS_STATES:
        _fail("PRIMARY_SUMMARY_NOT_PASS", primary_state)
    if primary.get("blockers") not in ([], None):
        _fail("PRIMARY_SUMMARY_BLOCKED", str(primary.get("blockers")))
    if _sha(primary.get("source_w1_manifest_sha256"), "primary.source_w1_manifest_sha256") != source_manifest_sha:
        _fail("SHARED_W1_MANIFEST_SHA_MISMATCH")
    if _string(primary.get("source_w1_run_id"), "primary.source_w1_run_id") != source_status["run_id"]:
        _fail("SHARED_W1_RUN_ID_MISMATCH")

    raw_context_sources = payload.get("context_sources")
    if not isinstance(raw_context_sources, Mapping):
        _fail("CONTEXT_SOURCES_REQUIRED")
    missing_context = sorted(REQUIRED_CONTEXT_SOURCES - set(raw_context_sources))
    extra_context = sorted(set(raw_context_sources) - REQUIRED_CONTEXT_SOURCES)
    if missing_context:
        _fail("CONTEXT_SOURCES_MISSING", ",".join(missing_context))
    if extra_context:
        _fail("CONTEXT_SOURCES_EXTRA", ",".join(extra_context))
    context_sources = {
        source_id: _normalized_source(source_id, raw_context_sources[source_id])
        for source_id in sorted(REQUIRED_CONTEXT_SOURCES)
    }

    candidate = _variant(primary, candidate_id)
    proposal = _extract_proposal(primary_source, primary, candidate, context_sources["proposal_context"])
    proposal_source = _adapter_source(primary, context_sources["proposal_context"], proposal)

    package_sources = {
        "proposal": proposal_source,
        "classifier_evidence": copy.deepcopy(raw_context_sources["classifier_evidence"]),
        "correlation_ledger": copy.deepcopy(raw_context_sources["correlation_ledger"]),
        "portfolio_policy": copy.deepcopy(raw_context_sources["portfolio_policy"]),
        "source_ledger": copy.deepcopy(raw_context_sources["source_ledger"]),
        "source_history": copy.deepcopy(raw_context_sources["source_history"]),
        "role_lineage": copy.deepcopy(raw_context_sources["role_lineage"]),
        "role_messages": copy.deepcopy(raw_context_sources["role_messages"]),
        "model_risk_baseline": copy.deepcopy(raw_context_sources["model_risk_baseline"]),
        "model_risk_policy": copy.deepcopy(raw_context_sources["model_risk_policy"]),
    }
    package = {
        "schema_version": BINDING_SCHEMA_VERSION,
        "package_id": f"real-w1.{primary['strategy_id']}.{candidate_id}.{primary['source_w1_run_id']}",
        "sources": package_sources,
        "group_bindings": {
            "proposal_core": {"source_id": "proposal", "field_path": "$"},
            "classifier_evidence": {"source_id": "classifier_evidence", "field_path": "$"},
            "correlation_ledger": {"source_id": "correlation_ledger", "field_path": "$"},
            "portfolio_policy": {"source_id": "portfolio_policy", "field_path": "$"},
            "source_ledger": {"source_id": "source_ledger", "field_path": "$"},
            "source_history": {"source_id": "source_history", "field_path": "$"},
            "role_lineage": {"source_id": "role_lineage", "field_path": "$"},
            "role_messages": {"source_id": "role_messages", "field_path": "$"},
            "model_risk_baseline": {"source_id": "model_risk_baseline", "field_path": "$"},
            "model_risk_policy": {"source_id": "model_risk_policy", "field_path": "$"},
        },
        "authority": authority,
    }
    try:
        bound = bind_package(package)
    except SourceBindingError as exc:
        raise RealW1AdapterError(str(exc)) from exc

    result = {
        "schema_version": ADAPTER_OUTPUT_SCHEMA,
        "state": "PASS_REAL_W1_EXACT_SHA_SOURCE_BINDING",
        "candidate_id": candidate_id,
        "strategy_id": primary["strategy_id"],
        "source_w1_run_id": primary["source_w1_run_id"],
        "source_w1_head_sha": primary["source_w1_head_sha"],
        "source_w1_manifest_sha": source_manifest_sha,
        "source_status_artifact_sha": source_status["artifact_sha"],
        "primary_summary_artifact_sha": primary_source["artifact_sha"],
        "proposal_context_artifact_sha": context_sources["proposal_context"]["artifact_sha"],
        "candidate_sha": proposal["candidate_sha"],
        "bound_package": bound,
        "proposal_created": True,
        "bound_package_created": True,
        "all_values_source_bound": bound["all_values_source_bound"],
        "inference_used": False,
        "next": "W2_W3_NEW_SEALED_EVIDENCE_BINDING_OR_CLASSIFIER_HOLD",
        "runtime_bound": False,
        **SAFETY,
    }
    result["adapter_result_sha"] = canonical_sha({
        "candidate_id": candidate_id,
        "source_w1_manifest_sha": source_manifest_sha,
        "bound_package_sha": bound["package_sha"],
        "binding_manifest_sha": bound["binding_manifest_sha"],
    })
    return result
