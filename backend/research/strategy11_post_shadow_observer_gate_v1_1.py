from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any, Mapping

from backend.contracts.strategy11_source_binding_contract_v1 import canonical_sha

INPUT_SCHEMA = "strategy11.post_shadow_observer_gate.input.v1"
OUTPUT_SCHEMA = "strategy11.post_shadow_observer_gate.output.v1.1"
CYCLE_SCHEMA = "strategy11.post_shadow_observer_cycle.v1.1"
POLICY_PATH = Path(__file__).with_name("strategy11_post_shadow_observer_gate_policy_v1.json")
OBSERVER_CAPABILITIES = {"READ_EVIDENCE", "EMIT_OBSERVATION", "EMIT_CALIBRATION", "REQUEST_HOLD"}
OBSERVER_SAFETY = {
    "observer_only": True,
    "research_only": True,
    "promotion_authority": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "order_authority": "BLOCKED",
    "runtime_bound": False,
    "advisory_enabled": False,
}
CORE_SAFETY = {
    "research_only": True,
    "promotion_authority": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "order_authority": "BLOCKED",
    "runtime_bound": False,
}


class PostShadowObserverGateError(ValueError):
    pass


def _fail(code: str, detail: str = "") -> None:
    raise PostShadowObserverGateError(f"{code}:{detail}" if detail else code)


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail("OBJECT_REQUIRED", name)
    return dict(value)


def _string(value: Any, name: str, maximum: int = 180) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail("STRING_REQUIRED", name)
    result = value.strip()
    if len(result) > maximum:
        _fail("STRING_TOO_LONG", name)
    return result


def _sha(value: Any, name: str) -> str:
    result = _string(value, name, 64).lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        _fail("SHA256_REQUIRED", name)
    return result


def _integer(value: Any, name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        _fail("INT_REQUIRED", name)
    if value < minimum:
        _fail("INT_BELOW_MIN", name)
    return value


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail("NUMBER_REQUIRED", name)
    result = float(value)
    if not math.isfinite(result):
        _fail("NUMBER_NOT_FINITE", name)
    return result


def _boolean(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        _fail("BOOL_REQUIRED", name)
    return value


def load_trusted_policy() -> dict[str, Any]:
    if not POLICY_PATH.is_file():
        _fail("TRUSTED_POLICY_FILE_MISSING", str(POLICY_PATH))
    value = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        _fail("TRUSTED_POLICY_OBJECT_REQUIRED")
    policy = dict(value)
    if policy.get("schema_version") != "strategy11.post_shadow_observer_gate_policy.v1":
        _fail("TRUSTED_POLICY_SCHEMA_MISMATCH")
    if policy.get("required_burnin_cycles") != 100 or policy.get("first_burnin_cycle") != 301:
        _fail("TRUSTED_POLICY_BURNIN_MISMATCH")
    if set(policy.get("observer_outputs_allowed", [])) != OBSERVER_CAPABILITIES:
        _fail("TRUSTED_POLICY_CAPABILITY_MISMATCH")
    for key in ("automatic_paper_start", "strategy_write_allowed", "weight_write_allowed", "ledger_write_allowed", "live_order_allowed"):
        if policy.get(key) is not False:
            _fail("TRUSTED_POLICY_WRITE_BOUNDARY_MISMATCH", key)
    return policy


def trusted_policy_sha() -> str:
    return canonical_sha(load_trusted_policy())


def validate_shadow300(value: Mapping[str, Any]) -> dict[str, Any]:
    shadow = _mapping(value, "shadow300")
    supplied_sha = _sha(shadow.get("completion_sha"), "shadow300.completion_sha")
    if canonical_sha({key: child for key, child in shadow.items() if key != "completion_sha"}) != supplied_sha:
        _fail("SHADOW300_SHA_MISMATCH")
    if shadow.get("state") != "PASS_SHADOW300_READ_ONLY_COMPLETION" or shadow.get("cycle_count") != 300:
        _fail("PASS_SHADOW300_REQUIRED")
    if shadow.get("ml_light_observer_gate_allowed") is not True or shadow.get("failure_learning_observer_gate_allowed") is not True:
        _fail("SHADOW300_OBSERVER_GATE_NOT_ALLOWED")
    if shadow.get("paper_30d_allowed") is not False:
        _fail("PAPER_PREMATURELY_ALLOWED")
    if shadow.get("real_shadow_started") is not False:
        _fail("REAL_SHADOW_STATE_UNEXPECTED")
    for key, expected in CORE_SAFETY.items():
        if shadow.get(key) != expected:
            _fail("SHADOW300_AUTHORITY_MISMATCH", key)
    review = _mapping(shadow.get("final_review"), "shadow300.final_review")
    if review.get("ml_light_disconnected") is not True or review.get("failure_learning_disconnected") is not True:
        _fail("OBSERVER_PREMATURE_CONNECTION")
    return shadow


def validate_observer(value: Mapping[str, Any], observer_type: str) -> dict[str, Any]:
    observer = _mapping(value, observer_type.lower())
    manifest_sha = _sha(observer.get("observer_manifest_sha"), f"{observer_type}.observer_manifest_sha")
    if canonical_sha({key: child for key, child in observer.items() if key != "observer_manifest_sha"}) != manifest_sha:
        _fail("OBSERVER_MANIFEST_SHA_MISMATCH", observer_type)
    expected_states = {
        "ML_LIGHT": {"PASS_ML_LIGHT_OBSERVATION", "HOLD_ML_LIGHT_OBSERVATION"},
        "FAILURE_LEARNING": {"PASS_FAILURE_LEARNING_OBSERVATION", "HOLD_FAILURE_LEARNING_OBSERVATION"},
    }
    if observer.get("observer_type") != observer_type or observer.get("state") not in expected_states[observer_type]:
        _fail("OBSERVER_TYPE_OR_STATE_MISMATCH", observer_type)
    if set(observer.get("capabilities", [])) != OBSERVER_CAPABILITIES:
        _fail("OBSERVER_CAPABILITY_MISMATCH", observer_type)
    if observer.get("leakage_check_pass") is not True:
        _fail("OBSERVER_LEAKAGE_CHECK_NOT_PASS", observer_type)
    for key, expected in OBSERVER_SAFETY.items():
        if observer.get(key) != expected:
            _fail("OBSERVER_AUTHORITY_MISMATCH", f"{observer_type}:{key}")
    return observer


def ledger_genesis(shadow300_completion_sha: str) -> str:
    return canonical_sha({"kind": "POST_SHADOW_OBSERVER_LEDGER_GENESIS", "shadow300_completion_sha": shadow300_completion_sha})


def expected_ledger_head(previous_head: str, cycle: int, observer_input_sha: str) -> str:
    return canonical_sha(
        {
            "previous_source_ledger_head_sha": previous_head,
            "cycle": cycle,
            "observer_input_sha": observer_input_sha,
        }
    )


def validate_cycle(
    value: Mapping[str, Any],
    shadow: Mapping[str, Any],
    ml: Mapping[str, Any],
    failure: Mapping[str, Any],
    observer_bundle_sha: str,
    expected_previous_head: str,
) -> dict[str, Any]:
    receipt = _mapping(value, "burnin_cycle")
    receipt_sha = _sha(receipt.get("receipt_sha"), "burnin.receipt_sha")
    if canonical_sha({key: child for key, child in receipt.items() if key != "receipt_sha"}) != receipt_sha:
        _fail("BURNIN_RECEIPT_SHA_MISMATCH", str(receipt.get("cycle")))
    if receipt.get("schema_version") != CYCLE_SCHEMA:
        _fail("BURNIN_RECEIPT_SCHEMA_MISMATCH")
    cycle = _integer(receipt.get("cycle"), "burnin.cycle", 1)
    previous_head = _sha(receipt.get("previous_source_ledger_head_sha"), "burnin.previous_source_ledger_head_sha")
    observer_input_sha = _sha(receipt.get("observer_input_sha"), "burnin.observer_input_sha")
    source_head = _sha(receipt.get("source_ledger_head_sha"), "burnin.source_ledger_head_sha")
    if previous_head != expected_previous_head:
        _fail("BURNIN_PREVIOUS_LEDGER_HEAD_MISMATCH", str(cycle))
    if source_head != expected_ledger_head(previous_head, cycle, observer_input_sha):
        _fail("BURNIN_LEDGER_HEAD_CHAIN_MISMATCH", str(cycle))
    normalized = {
        "schema_version": CYCLE_SCHEMA,
        "cycle": cycle,
        "previous_source_ledger_head_sha": previous_head,
        "source_ledger_head_sha": source_head,
        "observer_input_sha": observer_input_sha,
        "shadow300_completion_sha": _sha(receipt.get("shadow300_completion_sha"), "burnin.shadow300_completion_sha"),
        "selected_combination_sha": _sha(receipt.get("selected_combination_sha"), "burnin.selected_combination_sha"),
        "target_weights_sha": _sha(receipt.get("target_weights_sha"), "burnin.target_weights_sha"),
        "observer_bundle_sha": _sha(receipt.get("observer_bundle_sha"), "burnin.observer_bundle_sha"),
        "ml_manifest_sha": _sha(receipt.get("ml_manifest_sha"), "burnin.ml_manifest_sha"),
        "failure_manifest_sha": _sha(receipt.get("failure_manifest_sha"), "burnin.failure_manifest_sha"),
        "state_mutation_count": _integer(receipt.get("state_mutation_count"), "burnin.state_mutation_count"),
        "strategy_mutation_count": _integer(receipt.get("strategy_mutation_count"), "burnin.strategy_mutation_count"),
        "weight_mutation_count": _integer(receipt.get("weight_mutation_count"), "burnin.weight_mutation_count"),
        "ledger_mutation_count": _integer(receipt.get("ledger_mutation_count"), "burnin.ledger_mutation_count"),
        "paper_live_mutation_count": _integer(receipt.get("paper_live_mutation_count"), "burnin.paper_live_mutation_count"),
        "order_attempt_count": _integer(receipt.get("order_attempt_count"), "burnin.order_attempt_count"),
        "hold_requested": _boolean(receipt.get("hold_requested"), "burnin.hold_requested"),
        "error_budget_used": _integer(receipt.get("error_budget_used"), "burnin.error_budget_used"),
        "authority": copy.deepcopy(receipt.get("authority")),
    }
    if normalized["authority"] != OBSERVER_SAFETY:
        _fail("BURNIN_AUTHORITY_MISMATCH", str(cycle))
    if normalized["shadow300_completion_sha"] != shadow["completion_sha"]:
        _fail("BURNIN_SHADOW300_BINDING_MISMATCH", str(cycle))
    if normalized["selected_combination_sha"] != shadow["selected_combination_sha"] or normalized["target_weights_sha"] != shadow["target_weights_sha"]:
        _fail("BURNIN_PORTFOLIO_BINDING_MISMATCH", str(cycle))
    if normalized["observer_bundle_sha"] != observer_bundle_sha:
        _fail("BURNIN_OBSERVER_BUNDLE_MISMATCH", str(cycle))
    if normalized["ml_manifest_sha"] != ml["observer_manifest_sha"] or normalized["failure_manifest_sha"] != failure["observer_manifest_sha"]:
        _fail("BURNIN_OBSERVER_MANIFEST_MISMATCH", str(cycle))
    normalized["receipt_sha"] = canonical_sha(normalized)
    if normalized["receipt_sha"] != receipt_sha:
        _fail("BURNIN_NORMALIZED_SHA_MISMATCH", str(cycle))
    return normalized


def metric_blockers(ml: Mapping[str, Any], failure: Mapping[str, Any], policy: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    if ml.get("state") != "PASS_ML_LIGHT_OBSERVATION":
        blockers.append("ML_OBSERVER_HOLD")
    if failure.get("state") != "PASS_FAILURE_LEARNING_OBSERVATION":
        blockers.append("FAILURE_OBSERVER_HOLD")
    if _integer(ml.get("evaluation_sample_count"), "ml.evaluation_sample_count") < policy["min_ml_evaluation_samples"]:
        blockers.append("ML_EVALUATION_SAMPLE_LOW")
    if _integer(failure.get("evaluation_sample_count"), "failure.evaluation_sample_count") < policy["min_failure_evaluation_samples"]:
        blockers.append("FAILURE_EVALUATION_SAMPLE_LOW")
    calibration = _mapping(ml.get("calibration"), "ml.calibration")
    discrimination = _mapping(ml.get("discrimination"), "ml.discrimination")
    drift = _mapping(ml.get("drift"), "ml.drift")
    if _number(calibration.get("brier_score"), "ml.brier") > policy["max_ml_brier"]:
        blockers.append("ML_BRIER_BREACH")
    if _number(calibration.get("ece_score"), "ml.ece") > policy["max_ml_ece"]:
        blockers.append("ML_ECE_BREACH")
    if _number(discrimination.get("auc_score"), "ml.auc") < policy["min_ml_auc"]:
        blockers.append("ML_AUC_LOW")
    if _number(drift.get("max_feature_psi"), "ml.psi") > policy["max_ml_feature_psi"]:
        blockers.append("ML_FEATURE_DRIFT_BREACH")
    failure_calibration = _mapping(failure.get("calibration"), "failure.calibration")
    failure_drift = _mapping(failure.get("drift"), "failure.drift")
    if _number(failure_calibration.get("unknown_rate"), "failure.unknown_rate") > policy["max_failure_unknown_rate"]:
        blockers.append("FAILURE_UNKNOWN_RATE_BREACH")
    if _number(failure_drift.get("max_recurrence_delta_abs"), "failure.recurrence") > policy["max_failure_recurrence_drift"]:
        blockers.append("FAILURE_RECURRENCE_DRIFT_BREACH")
    return blockers


def evaluate_gate(value: Mapping[str, Any]) -> dict[str, Any]:
    payload = _mapping(value, "post_shadow_observer_input")
    allowed = {"schema_version", "shadow300", "ml_observation", "failure_observation", "burnin_cycles", "policy", "policy_sha", "authority"}
    if set(payload) != allowed:
        _fail("INPUT_FIELD_SET_MISMATCH")
    if payload.get("schema_version") != INPUT_SCHEMA or payload.get("authority") != OBSERVER_SAFETY:
        _fail("INPUT_SCHEMA_OR_AUTHORITY_MISMATCH")
    policy = load_trusted_policy()
    policy_sha = trusted_policy_sha()
    if payload.get("policy") != policy or payload.get("policy_sha") != policy_sha:
        _fail("TRUSTED_POLICY_BINDING_MISMATCH")

    shadow = validate_shadow300(payload["shadow300"])
    ml = validate_observer(payload["ml_observation"], "ML_LIGHT")
    failure = validate_observer(payload["failure_observation"], "FAILURE_LEARNING")
    bundle_sha = canonical_sha(
        {
            "shadow300_completion_sha": shadow["completion_sha"],
            "ml_manifest_sha": ml["observer_manifest_sha"],
            "failure_manifest_sha": failure["observer_manifest_sha"],
            "policy_sha": policy_sha,
        }
    )
    raw_cycles = payload.get("burnin_cycles")
    if not isinstance(raw_cycles, list):
        _fail("BURNIN_CYCLES_ARRAY_REQUIRED")
    cycles: list[dict[str, Any]] = []
    previous_head = ledger_genesis(shadow["completion_sha"])
    for raw in raw_cycles:
        cycle = validate_cycle(raw, shadow, ml, failure, bundle_sha, previous_head)
        cycles.append(cycle)
        previous_head = cycle["source_ledger_head_sha"]
    cycle_numbers = [row["cycle"] for row in cycles]
    if len(cycle_numbers) != len(set(cycle_numbers)):
        _fail("DUPLICATE_BURNIN_CYCLE")
    if cycle_numbers:
        expected = list(range(policy["first_burnin_cycle"], policy["first_burnin_cycle"] + len(cycles)))
        if cycle_numbers != expected:
            _fail("BURNIN_CYCLE_GAP_OR_REORDER")
    if len({row["observer_input_sha"] for row in cycles}) != len(cycles):
        _fail("BURNIN_INPUT_SHA_DUPLICATE")

    blockers = metric_blockers(ml, failure, policy)
    hold_count = sum(row["hold_requested"] for row in cycles)
    error_budget_used = sum(row["error_budget_used"] for row in cycles)
    error_budget_ratio = error_budget_used / policy["error_budget_limit"]
    if len(cycles) != policy["required_burnin_cycles"]:
        blockers.append("BURNIN_CYCLE_COUNT_NOT_100")
    if hold_count > policy["max_hold_requested_cycles"]:
        blockers.append("HOLD_REQUEST_LIMIT")
    if error_budget_ratio > policy["max_error_budget_ratio"]:
        blockers.append("OBSERVER_ERROR_BUDGET_BREACH")
    mutation_fields = (
        "state_mutation_count", "strategy_mutation_count", "weight_mutation_count",
        "ledger_mutation_count", "paper_live_mutation_count", "order_attempt_count",
    )
    mutation_totals = {field: sum(row[field] for row in cycles) for field in mutation_fields}
    mutation_blockers = [field.upper() for field, total in mutation_totals.items() if total != 0]
    structural_pass = not blockers and not mutation_blockers
    production_policy = policy.get("production_threshold_authority") is True
    if mutation_blockers:
        state = "BLOCK_POST_SHADOW_OBSERVER_MUTATION"
    elif blockers:
        state = "HOLD_POST_SHADOW_OBSERVER_100C"
    elif production_policy:
        state = "PASS_POST_SHADOW_OBSERVER_100C_GATE"
    else:
        state = "PASS_POST_SHADOW_OBSERVER_100C_STRUCTURAL_GATE"
    paper_allowed = structural_pass and production_policy
    result = {
        "schema_version": OUTPUT_SCHEMA,
        "state": state,
        "trusted_policy_id": policy["policy_id"],
        "trusted_policy_sha": policy_sha,
        "policy_class": policy["policy_class"],
        "production_threshold_authority": production_policy,
        "shadow300_completion_sha": shadow["completion_sha"],
        "selected_combination_sha": shadow["selected_combination_sha"],
        "target_weights_sha": shadow["target_weights_sha"],
        "observer_bundle_sha": bundle_sha,
        "ml_manifest_sha": ml["observer_manifest_sha"],
        "failure_manifest_sha": failure["observer_manifest_sha"],
        "ledger_genesis_sha": ledger_genesis(shadow["completion_sha"]),
        "ledger_final_head_sha": cycles[-1]["source_ledger_head_sha"] if cycles else ledger_genesis(shadow["completion_sha"]),
        "ledger_chain_verified": bool(cycles),
        "burnin_cycle_count": len(cycles),
        "burnin_start_cycle": cycles[0]["cycle"] if cycles else None,
        "burnin_end_cycle": cycles[-1]["cycle"] if cycles else None,
        "burnin_receipt_shas": [row["receipt_sha"] for row in cycles],
        "hold_requested_cycles": hold_count,
        "error_budget_used": error_budget_used,
        "error_budget_limit": policy["error_budget_limit"],
        "error_budget_ratio": error_budget_ratio,
        "mutation_totals": mutation_totals,
        "blocker_codes": sorted(set(mutation_blockers + blockers)),
        "ml_failure_readonly_bridge_allowed": structural_pass,
        "paper_30d_structural_gate_pass": structural_pass,
        "paper_30d_allowed": paper_allowed,
        "automatic_paper_start": False,
        "strategy_write_allowed": False,
        "weight_write_allowed": False,
        "ledger_write_allowed": False,
        "live_order_allowed": False,
        "requested_action": "block" if mutation_blockers else "hold",
        "next": "30D_PAPER_CANARY_MANUAL_START" if paper_allowed else "WAIT_PRODUCTION_POLICY_AND_REAL_100C" if structural_pass else "HOLD_OR_ROLLBACK_OBSERVER_ARTIFACTS",
        **OBSERVER_SAFETY,
    }
    result["gate_sha"] = canonical_sha(result)
    return result
