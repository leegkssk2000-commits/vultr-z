from __future__ import annotations

import copy
from typing import Any, Mapping, Sequence

from backend.contracts.strategy11_role_boundary_zbot_zico_lico_zlice_v1 import (
    role_manifest,
    validate_message,
)
from backend.contracts.strategy11_source_binding_contract_v1 import (
    SAFETY,
    SourceBindingError,
    attribution_history_envelope,
    canonical_sha,
    validate_authority,
    validate_source,
    validate_source_history,
)
from backend.contracts.strategy11_strategy_proposal_contract_v1 import seal_proposal
from backend.research.strategy11_attribution_ledger_v1 import build_projection
from backend.research.strategy11_ensemble_correlation_analyzer_v1 import analyze_candidates
from backend.research.strategy11_global_candidate_classifier_v1 import classify_candidate
from backend.research.strategy11_model_risk_governance_v1 import evaluate_model_risk
from backend.research.strategy11_portfolio_governor_v1 import govern

INPUT_SCHEMA = "strategy11.source_bound_multicandidate_orchestrator.input.v1"
OUTPUT_SCHEMA = "strategy11.source_bound_multicandidate_orchestrator.output.v1"
ELIGIBLE_CLASSIFICATIONS = {"CORE", "SYNTHESIS"}
REQUIRED_GROUPS = {
    "proposal_core",
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


class MulticandidateOrchestratorError(ValueError):
    pass


def _fail(code: str, detail: str = "") -> None:
    raise MulticandidateOrchestratorError(f"{code}:{detail}" if detail else code)


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail("OBJECT_REQUIRED", name)
    return dict(value)


def _string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail("STRING_REQUIRED", name)
    return value.strip()


def _sha(value: Any, name: str) -> str:
    result = _string(value, name).lower()
    if len(result) != 64 or any(char not in "0123456789abcdef" for char in result):
        _fail("SHA256_REQUIRED", name)
    return result


def _authority(value: Any) -> dict[str, Any]:
    try:
        return validate_authority(value)
    except SourceBindingError as exc:
        raise MulticandidateOrchestratorError(str(exc)) from exc


def _hold(
    code: str,
    *,
    candidate_count: int,
    classifications: Mapping[str, str] | None = None,
    details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    result = {
        "schema_version": OUTPUT_SCHEMA,
        "state": code,
        "candidate_count": candidate_count,
        "classifications": dict(classifications or {}),
        "details": dict(details or {}),
        "shadow_20c_ready": False,
        "runtime_bound": False,
        "automatic_shadow_start": False,
        "next": "WAIT_FOR_COMPLETE_SHARED_EVIDENCE_OR_SECOND_ELIGIBLE_CANDIDATE",
        **SAFETY,
    }
    result["orchestrator_sha"] = canonical_sha(result)
    return result


def _validate_bound_package(value: Any, index: int) -> dict[str, Any]:
    package = _mapping(value, f"candidate_adapters[{index}].bound_package")
    if package.get("status") != "PASS_STRICT_SOURCE_BINDING":
        _fail("BOUND_PACKAGE_NOT_PASS", str(index))
    for key, expected in SAFETY.items():
        if package.get(key) != expected:
            _fail("BOUND_PACKAGE_SAFETY_MISMATCH", f"{index}:{key}")
    if package.get("runtime_bound") is not False:
        _fail("BOUND_PACKAGE_RUNTIME_BOUND", str(index))
    if package.get("all_values_source_bound") is not True:
        _fail("BOUND_PACKAGE_NOT_FULLY_SOURCE_BOUND", str(index))
    if package.get("inference_used") is not False:
        _fail("BOUND_PACKAGE_INFERENCE_USED", str(index))
    groups = _mapping(package.get("groups"), f"candidate_adapters[{index}].bound_package.groups")
    missing = sorted(REQUIRED_GROUPS - set(groups))
    extra = sorted(set(groups) - REQUIRED_GROUPS)
    if missing:
        _fail("BOUND_PACKAGE_GROUPS_MISSING", f"{index}:{','.join(missing)}")
    if extra:
        _fail("BOUND_PACKAGE_GROUPS_EXTRA", f"{index}:{','.join(extra)}")
    binding_manifest_sha = _sha(package.get("binding_manifest_sha"), f"candidate_adapters[{index}].binding_manifest_sha")
    package_sha = _sha(package.get("package_sha"), f"candidate_adapters[{index}].package_sha")
    computed_package_sha = canonical_sha({
        "groups": groups,
        "binding_manifest_sha": binding_manifest_sha,
        "authority": {**SAFETY, "runtime_bound": False},
    })
    if package_sha != computed_package_sha:
        _fail("BOUND_PACKAGE_SHA_MISMATCH", str(index))
    return package


def _validate_adapter(value: Any, index: int) -> dict[str, Any]:
    adapter = _mapping(value, f"candidate_adapters[{index}]")
    if adapter.get("state") != "PASS_REAL_W1_EXACT_SHA_SOURCE_BINDING":
        _fail("CANDIDATE_ADAPTER_NOT_PASS", f"{index}:{adapter.get('state')}")
    for key, expected in SAFETY.items():
        if adapter.get(key) != expected:
            _fail("CANDIDATE_ADAPTER_SAFETY_MISMATCH", f"{index}:{key}")
    if adapter.get("runtime_bound") is not False:
        _fail("CANDIDATE_ADAPTER_RUNTIME_BOUND", str(index))
    package = _validate_bound_package(adapter.get("bound_package"), index)
    candidate_id = _string(adapter.get("candidate_id"), f"candidate_adapters[{index}].candidate_id")
    candidate_sha = _sha(adapter.get("candidate_sha"), f"candidate_adapters[{index}].candidate_sha")
    proposal = _mapping(package["groups"]["proposal_core"], f"candidate_adapters[{index}].proposal_core")
    if proposal.get("candidate_sha") != candidate_sha:
        _fail("ADAPTER_PROPOSAL_CANDIDATE_SHA_MISMATCH", candidate_id)
    if proposal.get("metadata", {}).get("candidate_id") != candidate_id:
        _fail("ADAPTER_PROPOSAL_CANDIDATE_ID_MISMATCH", candidate_id)
    manifest_sha = _sha(adapter.get("source_w1_manifest_sha"), f"candidate_adapters[{index}].source_w1_manifest_sha")
    if proposal.get("lineage", {}).get("source_manifest_sha") != manifest_sha:
        _fail("ADAPTER_PROPOSAL_MANIFEST_SHA_MISMATCH", candidate_id)
    return {
        "adapter": adapter,
        "package": package,
        "candidate_id": candidate_id,
        "candidate_sha": candidate_sha,
        "strategy_id": _string(adapter.get("strategy_id"), f"candidate_adapters[{index}].strategy_id"),
        "source_w1_run_id": _string(adapter.get("source_w1_run_id"), f"candidate_adapters[{index}].source_w1_run_id"),
        "source_w1_head_sha": _string(adapter.get("source_w1_head_sha"), f"candidate_adapters[{index}].source_w1_head_sha"),
        "source_w1_manifest_sha": manifest_sha,
    }


def _shared_value(rows: Sequence[dict[str, Any]], path: Sequence[str], code: str) -> Any:
    values: list[Any] = []
    for row in rows:
        current: Any = row
        for token in path:
            if not isinstance(current, Mapping) or token not in current:
                _fail("SHARED_FIELD_MISSING", f"{code}:{'.'.join(path)}")
            current = current[token]
        values.append(current)
    fingerprints = {canonical_sha(value) for value in values}
    if len(fingerprints) != 1:
        _fail(code)
    return copy.deepcopy(values[0])


def _policy_consensus(rows: Sequence[dict[str, Any]], policy_key: str) -> dict[str, Any]:
    policies = [
        _mapping(row["package"]["groups"]["portfolio_policy"].get(policy_key), f"portfolio_policy.{policy_key}")
        for row in rows
    ]
    if len({canonical_sha(policy) for policy in policies}) != 1:
        _fail("POLICY_SHA_MISMATCH", policy_key)
    return policies[0]


def _material(
    row: dict[str, Any],
    proposal: Mapping[str, Any],
    classification: Mapping[str, Any],
) -> dict[str, Any]:
    context = _mapping(
        row["package"]["groups"]["portfolio_policy"].get("material_context"),
        f"{row['strategy_id']}.portfolio_policy.material_context",
    )
    required = {
        "material_id",
        "net_after_cost",
        "joint_tail_dd_pct",
        "cost_pct",
        "capacity_score",
        "incumbent_weight",
        "material_sealed",
        "material_seal_sha",
        "material_seal_candidate_sha",
    }
    missing = sorted(required - set(context))
    if missing:
        _fail("MATERIAL_CONTEXT_FIELDS_MISSING", f"{row['strategy_id']}:{','.join(missing)}")
    if context["material_sealed"] is not True:
        _fail("MATERIAL_NOT_SEALED", row["strategy_id"])
    seal_sha = _sha(context["material_seal_sha"], f"{row['strategy_id']}.material_seal_sha")
    seal_candidate_sha = _sha(
        context["material_seal_candidate_sha"],
        f"{row['strategy_id']}.material_seal_candidate_sha",
    )
    if seal_candidate_sha != proposal["candidate_sha"]:
        _fail("MATERIAL_SEAL_CANDIDATE_SHA_MISMATCH", row["strategy_id"])
    expected_seal = canonical_sha({
        "material_id": context["material_id"],
        "candidate_sha": proposal["candidate_sha"],
        "classification_sha": classification["classification_sha"],
        "source_manifest_sha": proposal["lineage"]["source_manifest_sha"],
    })
    if seal_sha != expected_seal:
        _fail("MATERIAL_SEAL_SHA_MISMATCH", row["strategy_id"])
    return {
        "material_id": _string(context["material_id"], f"{row['strategy_id']}.material_id"),
        "classification": classification["classification"],
        "material_sealed": True,
        "net_after_cost": context["net_after_cost"],
        "confidence": proposal["confidence"]["score"],
        "uncertainty": proposal["confidence"]["uncertainty"],
        "dd_pct": proposal["risk_envelope"]["max_drawdown_pct"],
        "joint_tail_dd_pct": context["joint_tail_dd_pct"],
        "cost_pct": context["cost_pct"],
        "capacity_score": context["capacity_score"],
        "incumbent_weight": context["incumbent_weight"],
        "material_seal_sha": seal_sha,
    }


def orchestrate(value: Mapping[str, Any]) -> dict[str, Any]:
    payload = _mapping(value, "orchestrator_input")
    allowed = {"schema_version", "candidate_adapters", "portfolio_source_history", "authority"}
    missing = sorted(allowed - set(payload))
    extra = sorted(set(payload) - allowed)
    if missing:
        _fail("ORCHESTRATOR_FIELDS_MISSING", ",".join(missing))
    if extra:
        _fail("ORCHESTRATOR_EXTRA_FIELDS", ",".join(extra))
    if payload.get("schema_version") != INPUT_SCHEMA:
        _fail("ORCHESTRATOR_SCHEMA_MISMATCH")
    _authority(payload.get("authority"))

    raw_adapters = payload.get("candidate_adapters")
    if not isinstance(raw_adapters, list) or not raw_adapters:
        _fail("CANDIDATE_ADAPTERS_REQUIRED")
    rows = [_validate_adapter(adapter, index) for index, adapter in enumerate(raw_adapters)]
    strategy_ids = [row["strategy_id"] for row in rows]
    if len(set(strategy_ids)) != len(strategy_ids):
        _fail("DUPLICATE_STRATEGY_ID")
    candidate_shas = [row["candidate_sha"] for row in rows]
    if len(set(candidate_shas)) != len(candidate_shas):
        _fail("DUPLICATE_CANDIDATE_SHA")

    shared_w1_manifest_sha = _shared_value(rows, ["source_w1_manifest_sha"], "SHARED_W1_MANIFEST_SHA_MISMATCH")
    shared_w1_run_id = _shared_value(rows, ["source_w1_run_id"], "SHARED_W1_RUN_ID_MISMATCH")
    shared_data_sha = _shared_value(
        rows,
        ["package", "groups", "proposal_core", "lineage", "data_sha"],
        "SHARED_DATA_SHA_MISMATCH",
    )
    shared_window_sha = _shared_value(
        rows,
        ["package", "groups", "proposal_core", "lineage", "window_sha"],
        "SHARED_WINDOW_SHA_MISMATCH",
    )
    shared_proposal_manifest_sha = _shared_value(
        rows,
        ["package", "groups", "proposal_core", "lineage", "source_manifest_sha"],
        "SHARED_PROPOSAL_MANIFEST_SHA_MISMATCH",
    )
    if shared_proposal_manifest_sha != shared_w1_manifest_sha:
        _fail("W1_AND_PROPOSAL_MANIFEST_SHA_MISMATCH")
    shared_evidence_manifest_sha = _shared_value(
        rows,
        ["package", "groups", "classifier_evidence", "evidence_manifest_sha"],
        "SHARED_EVIDENCE_MANIFEST_SHA_MISMATCH",
    )

    classifier_policy = _policy_consensus(rows, "classifier")
    correlation_policy = _policy_consensus(rows, "correlation")
    governor_policy = _policy_consensus(rows, "governor")
    model_risk_policy = _shared_value(
        rows,
        ["package", "groups", "model_risk_policy"],
        "MODEL_RISK_POLICY_SHA_MISMATCH",
    )

    proposals: dict[str, dict[str, Any]] = {}
    classifications: dict[str, dict[str, Any]] = {}
    for row in rows:
        proposal = seal_proposal(row["package"]["groups"]["proposal_core"])
        if proposal["strategy_id"] != row["strategy_id"]:
            _fail("STRATEGY_ID_MISMATCH", row["strategy_id"])
        classification = classify_candidate(
            proposal,
            row["package"]["groups"]["classifier_evidence"],
            classifier_policy,
        )
        proposals[row["strategy_id"]] = proposal
        classifications[row["strategy_id"]] = classification

    classification_names = {
        strategy_id: classification["classification"]
        for strategy_id, classification in classifications.items()
    }
    eligible_rows = [
        row for row in rows
        if classification_names[row["strategy_id"]] in ELIGIBLE_CLASSIFICATIONS
    ]
    if len(eligible_rows) < 2:
        return _hold(
            "HOLD_MULTICANDIDATE_INSUFFICIENT_ELIGIBLE",
            candidate_count=len(rows),
            classifications=classification_names,
            details={
                "eligible_count": len(eligible_rows),
                "required_count": 2,
                "shared_w1_manifest_sha": shared_w1_manifest_sha,
                "shared_evidence_manifest_sha": shared_evidence_manifest_sha,
            },
        )

    correlation_candidates: list[dict[str, Any]] = []
    for row in eligible_rows:
        strategy_id = row["strategy_id"]
        ledger = _mapping(
            row["package"]["groups"]["correlation_ledger"],
            f"{strategy_id}.correlation_ledger",
        )
        if ledger.get("strategy_id") != strategy_id:
            _fail("CORRELATION_LEDGER_STRATEGY_MISMATCH", strategy_id)
        correlation_candidates.append({
            "strategy_id": strategy_id,
            "candidate_sha": proposals[strategy_id]["candidate_sha"],
            "proposal_sha": proposals[strategy_id]["proposal_sha"],
            "classification_sha": classifications[strategy_id]["classification_sha"],
            "classification": classifications[strategy_id]["classification"],
            "trades": copy.deepcopy(ledger.get("trades")),
        })
    correlation = analyze_candidates(correlation_candidates, correlation_policy)
    combinations = correlation.get("shadow_only_candidate_combinations")
    if not isinstance(combinations, list) or not combinations:
        return _hold(
            "HOLD_MULTICANDIDATE_NO_COMPATIBLE_COMBINATION",
            candidate_count=len(rows),
            classifications=classification_names,
            details={
                "blocked_pair_count": correlation.get("blocked_pair_count"),
                "correlation_analysis_sha": correlation.get("analysis_sha"),
            },
        )
    selected = combinations[0]
    selected_ids = list(selected["members"])
    selected_rows = [row for row in eligible_rows if row["strategy_id"] in selected_ids]
    if len(selected_rows) != len(selected_ids):
        _fail("SELECTED_COMBINATION_ROW_MISMATCH")

    materials = [
        _material(row, proposals[row["strategy_id"]], classifications[row["strategy_id"]])
        for row in selected_rows
    ]
    governor = govern({
        "candidate_set_sha": selected["combination_sha"],
        "correlation_artifact_sha": correlation["analysis_sha"],
        "materials": materials,
        "policy": governor_policy,
        **SAFETY,
    })
    if governor.get("status") != "PASS_PORTFOLIO_GOVERNOR_SHADOW_TARGETS":
        return _hold(
            "HOLD_MULTICANDIDATE_GOVERNOR",
            candidate_count=len(rows),
            classifications=classification_names,
            details={"governor": governor},
        )

    source_rows: list[dict[str, Any]] = []
    for row in selected_rows:
        strategy_id = row["strategy_id"]
        source_ledger = _mapping(
            row["package"]["groups"]["source_ledger"],
            f"{strategy_id}.source_ledger",
        )
        trades = source_ledger.get("trades")
        if not isinstance(trades, list) or not trades:
            _fail("SOURCE_LEDGER_TRADES_REQUIRED", strategy_id)
        for trade in trades:
            if not isinstance(trade, Mapping):
                _fail("SOURCE_LEDGER_TRADE_OBJECT_REQUIRED", strategy_id)
            if trade.get("strategy_id") != strategy_id:
                _fail("SOURCE_LEDGER_STRATEGY_MISMATCH", strategy_id)
            if trade.get("candidate_sha") != proposals[strategy_id]["candidate_sha"]:
                _fail("SOURCE_LEDGER_CANDIDATE_SHA_MISMATCH", strategy_id)
            source_rows.append(copy.deepcopy(dict(trade)))
    attribution = build_projection({
        "projection_only": True,
        "source_ledger_mutated": False,
        "runtime_append_enabled": False,
        "trades": source_rows,
        **SAFETY,
    })
    if attribution.get("status") != "PASS_STRATEGY_ATTRIBUTION_LEDGER":
        _fail("ATTRIBUTION_PROJECTION_NOT_PASS")

    try:
        history_source = validate_source("portfolio_source_history", payload.get("portfolio_source_history"))
        if history_source["source_kind"] != "SOURCE_LEDGER_HISTORY":
            _fail("PORTFOLIO_HISTORY_SOURCE_KIND_INVALID")
        history = validate_source_history(history_source["document"])
        attribution_history = attribution_history_envelope(attribution, history)
    except SourceBindingError as exc:
        raise MulticandidateOrchestratorError(str(exc)) from exc

    validated_messages: list[dict[str, Any]] = []
    for row in selected_rows:
        strategy_id = row["strategy_id"]
        role_lineage = _mapping(
            row["package"]["groups"]["role_lineage"],
            f"{strategy_id}.role_lineage",
        )
        if role_lineage.get("strategy_id") != strategy_id:
            _fail("ROLE_LINEAGE_STRATEGY_MISMATCH", strategy_id)
        if role_lineage.get("sbot_veto_active") is not False:
            return _hold(
                "HOLD_MULTICANDIDATE_SBOT_VETO",
                candidate_count=len(rows),
                classifications=classification_names,
                details={"strategy_id": strategy_id},
            )
        bundle = _mapping(
            row["package"]["groups"]["role_messages"],
            f"{strategy_id}.role_messages",
        )
        messages = bundle.get("messages")
        if not isinstance(messages, list) or not messages:
            _fail("ROLE_MESSAGES_REQUIRED", strategy_id)
        for message in messages:
            normalized = validate_message(message)
            if normalized["lineage"]["strategy_id"] != strategy_id:
                _fail("ROLE_MESSAGE_STRATEGY_MISMATCH", strategy_id)
            validated_messages.append(normalized)
    role_boundary_sha = canonical_sha({
        "manifest": role_manifest(),
        "messages": validated_messages,
    })

    governor_sha = canonical_sha(governor)
    model_risk_rows: list[dict[str, Any]] = []
    for row in selected_rows:
        strategy_id = row["strategy_id"]
        baseline = _mapping(
            row["package"]["groups"]["model_risk_baseline"],
            f"{strategy_id}.model_risk_baseline",
        )
        snapshot = {
            "candidate_id": row["candidate_id"],
            "candidate_sha": proposals[strategy_id]["candidate_sha"],
            "proposal_sha": proposals[strategy_id]["proposal_sha"],
            "classification_sha": classifications[strategy_id]["classification_sha"],
            "correlation_analysis_sha": correlation["analysis_sha"],
            "portfolio_governor_sha": governor_sha,
            "attribution_projection_sha": attribution_history["history_envelope_sha"],
            "role_boundary_sha": role_boundary_sha,
            "source_manifest_sha": shared_w1_manifest_sha,
            "lineage_match": True,
            "stale": False,
            "private_field_violation": False,
            **baseline,
            "authority": {**SAFETY, "runtime_bound": False},
        }
        risk = evaluate_model_risk(snapshot, model_risk_policy)
        model_risk_rows.append(risk)
    non_pass = [row for row in model_risk_rows if row.get("state") != "PASS_MODEL_RISK_GOVERNANCE"]
    if non_pass:
        return _hold(
            "HOLD_MULTICANDIDATE_MODEL_RISK",
            candidate_count=len(rows),
            classifications=classification_names,
            details={
                "model_risk_states": [row.get("state") for row in model_risk_rows],
                "requested_actions": [row.get("requested_action") for row in model_risk_rows],
            },
        )

    result = {
        "schema_version": OUTPUT_SCHEMA,
        "state": "PASS_SOURCE_BOUND_MULTICANDIDATE_PREFLIGHT",
        "candidate_count": len(rows),
        "eligible_candidate_count": len(eligible_rows),
        "classifications": classification_names,
        "selected_combination": selected_ids,
        "selected_combination_sha": selected["combination_sha"],
        "target_risk_weights": governor["target_risk_weights"],
        "shared_lineage": {
            "source_w1_run_id": shared_w1_run_id,
            "source_w1_manifest_sha": shared_w1_manifest_sha,
            "data_sha": shared_data_sha,
            "window_sha": shared_window_sha,
            "evidence_manifest_sha": shared_evidence_manifest_sha,
        },
        "stage_shas": {
            "proposal": {
                strategy_id: proposals[strategy_id]["proposal_sha"]
                for strategy_id in selected_ids
            },
            "classification": {
                strategy_id: classifications[strategy_id]["classification_sha"]
                for strategy_id in selected_ids
            },
            "correlation": correlation["analysis_sha"],
            "governor": governor_sha,
            "attribution_history": attribution_history["history_envelope_sha"],
            "role_boundary": role_boundary_sha,
            "model_risk": {
                row["candidate_id"]: row["governance_sha"]
                for row in model_risk_rows
            },
        },
        "source_history_verified": attribution_history["source_history_verified"],
        "append_only_evidence": attribution_history["append_only_evidence"],
        "validated_role_message_count": len(validated_messages),
        "model_risk_states": [row["state"] for row in model_risk_rows],
        "shadow_20c_ready": True,
        "shadow_canary_scope": "READ_ONLY_ORCHESTRATOR_PREFLIGHT_ONLY",
        "automatic_shadow_start": False,
        "runtime_bound": False,
        "next": "SHADOW_20C_READ_ONLY_CANARY_ORCHESTRATOR",
        **SAFETY,
    }
    result["orchestrator_sha"] = canonical_sha(result)
    return result
