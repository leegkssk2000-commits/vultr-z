from __future__ import annotations

import copy
import math
from typing import Any, Mapping

from backend.contracts.strategy11_source_binding_contract_v1 import canonical_sha

INPUT_SCHEMA = "strategy11.post_shadow_observer_gate.input.v1"
OUTPUT_SCHEMA = "strategy11.post_shadow_observer_gate.output.v1"
CYCLE_SCHEMA = "strategy11.post_shadow_observer_cycle.v1"
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


def _string(value: Any, name: str, *, maximum: int = 180) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail("STRING_REQUIRED", name)
    result = value.strip()
    if len(result) > maximum:
        _fail("STRING_TOO_LONG", name)
    return result


def _sha(value: Any, name: str) -> str:
    result = _string(value, name, maximum=64).lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        _fail("SHA256_REQUIRED", name)
    return result


def _bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        _fail("BOOL_REQUIRED", name)
    return value


def _integer(value: Any, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        _fail("INT_REQUIRED", name)
    if value < minimum:
        _fail("INT_BELOW_MIN", name)
    return value


def _number(value: Any, name: str, *, minimum: float | None = None, maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail("NUMBER_REQUIRED", name)
    result = float(value)
    if not math.isfinite(result):
        _fail("NUMBER_NOT_FINITE", name)
    if minimum is not None and result < minimum:
        _fail("NUMBER_BELOW_MIN", name)
    if maximum is not None and result > maximum:
        _fail("NUMBER_ABOVE_MAX", name)
    return result


def validate_policy(value: Mapping[str, Any]) -> dict[str, Any]:
    policy = _mapping(value, "policy")
    required = {
        "policy_id", "required_burnin_cycles", "first_burnin_cycle", "min_ml_evaluation_samples",
        "min_failure_evaluation_samples", "max_ml_brier", "max_ml_ece", "min_ml_auc",
        "max_ml_feature_psi", "max_failure_unknown_rate", "max_failure_recurrence_drift",
        "max_hold_requested_cycles", "error_budget_limit", "max_error_budget_ratio",
    }
    missing = sorted(required - set(policy))
    extra = sorted(set(policy) - required)
    if missing:
        _fail("POLICY_FIELDS_MISSING", ",".join(missing))
    if extra:
        _fail("POLICY_EXTRA_FIELDS", ",".join(extra))
    result = {
        "policy_id": _string(policy["policy_id"], "policy.policy_id"),
        "required_burnin_cycles": _integer(policy["required_burnin_cycles"], "policy.required_burnin_cycles", minimum=1),
        "first_burnin_cycle": _integer(policy["first_burnin_cycle"], "policy.first_burnin_cycle", minimum=1),
        "min_ml_evaluation_samples": _integer(policy["min_ml_evaluation_samples"], "policy.min_ml_evaluation_samples", minimum=1),
        "min_failure_evaluation_samples": _integer(policy["min_failure_evaluation_samples"], "policy.min_failure_evaluation_samples", minimum=1),
        "max_ml_brier": _number(policy["max_ml_brier"], "policy.max_ml_brier", minimum=0.0, maximum=1.0),
        "max_ml_ece": _number(policy["max_ml_ece"], "policy.max_ml_ece", minimum=0.0, maximum=1.0),
        "min_ml_auc": _number(policy["min_ml_auc"], "policy.min_ml_auc", minimum=0.0, maximum=1.0),
        "max_ml_feature_psi": _number(policy["max_ml_feature_psi"], "policy.max_ml_feature_psi", minimum=0.0),
        "max_failure_unknown_rate": _number(policy["max_failure_unknown_rate"], "policy.max_failure_unknown_rate", minimum=0.0, maximum=1.0),
        "max_failure_recurrence_drift": _number(
            policy["max_failure_recurrence_drift"],
            "policy.max_failure_recurrence_drift",
            minimum=0.0,
            maximum=1.0,
        ),
        "max_hold_requested_cycles": _integer(policy["max_hold_requested_cycles"], "policy.max_hold_requested_cycles"),
        "error_budget_limit": _integer(policy["error_budget_limit"], "policy.error_budget_limit", minimum=1),
        "max_error_budget_ratio": _number(policy["max_error_budget_ratio"], "policy.max_error_budget_ratio", minimum=0.0, maximum=1.0),
    }
    if result["required_burnin_cycles"] != 100 or result["first_burnin_cycle"] != 301:
        _fail("BURNIN_POLICY_MUST_BE_301_TO_400")
    return result


def validate_shadow300(value: Mapping[str, Any]) -> dict[str, Any]:
    shadow = _mapping(value, "shadow300")
    supplied_sha = _sha(shadow.get("completion_sha"), "shadow300.completion_sha")
    computed = canonical_sha({key: child for key, child in shadow.items() if key != "completion_sha"})
    if supplied_sha != computed:
        _fail("SHADOW300_SHA_MISMATCH")
    if shadow.get("state") != "PASS_SHADOW300_READ_ONLY_COMPLETION":
        _fail("PASS_SHADOW300_REQUIRED", str(shadow.get("state")))
    if shadow.get("cycle_count") != 300:
        _fail("SHADOW300_CYCLE_COUNT_MISMATCH")
    if shadow.get("ml_light_observer_gate_allowed") is not True:
        _fail("ML_GATE_NOT_ALLOWED")
    if shadow.get("failure_learning_observer_gate_allowed") is not True:
        _fail("FAILURE_GATE_NOT_ALLOWED")
    if shadow.get("paper_30d_allowed") is not False:
        _fail("PAPER_PREMATURELY_ALLOWED")
    if shadow.get("real_shadow_started") is not False or shadow.get("runtime_bound") is not False:
        _fail("SHADOW_RUNTIME_AUTHORITY_FORBIDDEN")
    for key, expected in CORE_SAFETY.items():
        if shadow.get(key) != expected:
            _fail("SHADOW300_AUTHORITY_MISMATCH", key)
    final_review = _mapping(shadow.get("final_review"), "shadow300.final_review")
    if final_review.get("ml_light_disconnected") is not True or final_review.get("failure_learning_disconnected") is not True:
        _fail("SHADOW300_OBSERVERS_NOT_DISCONNECTED_DURING_300C")
    return shadow


def validate_observer(value: Mapping[str, Any], observer_type: str) -> dict[str, Any]:
    observer = _mapping(value, observer_type.lower())
    supplied_sha = _sha(observer.get("observer_manifest_sha"), f"{observer_type}.observer_manifest_sha")
    computed = canonical_sha({key: child for key, child in observer.items() if key != "observer_manifest_sha"})
    if supplied_sha != computed:
        _fail("OBSERVER_MANIFEST_SHA_MISMATCH", observer_type)
    if observer.get("observer_type") != observer_type:
        _fail("OBSERVER_TYPE_MISMATCH", observer_type)
    allowed_states = {
        "ML_LIGHT": {"PASS_ML_LIGHT_OBSERVATION", "HOLD_ML_LIGHT_OBSERVATION"},
        "FAILURE_LEARNING": {"PASS_FAILURE_LEARNING_OBSERVATION", "HOLD_FAILURE_LEARNING_OBSERVATION"},
    }
    if observer.get("state") not in allowed_states[observer_type]:
        _fail("OBSERVER_STATE_INVALID", f"{observer_type}:{observer.get('state')}")
    if set(observer.get("capabilities", [])) != OBSERVER_CAPABILITIES:
        _fail("OBSERVER_CAPABILITY_MISMATCH", observer_type)
    if observer.get("leakage_check_pass") is not True:
        _fail("OBSERVER_LEAKAGE_CHECK_NOT_PASS", observer_type)
    for key, expected in OBSERVER_SAFETY.items():
        if observer.get(key) != expected:
            _fail("OBSERVER_AUTHORITY_MISMATCH", f"{observer_type}:{key}")
    return observer


def validate_cycle(
    value: Mapping[str, Any],
    shadow: Mapping[str, Any],
    ml: Mapping[str, Any],
    failure: Mapping[str, Any],
    expected_bundle_sha: str,
) -> dict[str, Any]:
    receipt = _mapping(value, "burnin_cycle")
    supplied_sha = _sha(receipt.get("receipt_sha"), "burnin_cycle.receipt_sha")
    raw = copy.deepcopy(receipt)
    raw.pop("receipt_sha", None)
    if canonical_sha(raw) != supplied_sha:
        _fail("BURNIN_RECEIPT_SHA_MISMATCH", str(receipt.get("cycle")))
    if receipt.get("schema_version") != CYCLE_SCHEMA:
        _fail("BURNIN_RECEIPT_SCHEMA_MISMATCH")
    cycle = _integer(receipt.get("cycle"), "burnin_cycle.cycle", minimum=1)
    normalized = {
        "schema_version": CYCLE_SCHEMA,
        "cycle": cycle,
        "shadow300_completion_sha": _sha(receipt.get("shadow300_completion_sha"), "burnin.shadow300_completion_sha"),
        "selected_combination_sha": _sha(receipt.get("selected_combination_sha"), "burnin.selected_combination_sha"),
        "target_weights_sha": _sha(receipt.get("target_weights_sha"), "burnin.target_weights_sha"),
        "source_ledger_head_sha": _sha(receipt.get("source_ledger_head_sha"), "burnin.source_ledger_head_sha"),
        "observer_input_sha": _sha(receipt.get("observer_input_sha"), "burnin.observer_input_sha"),
        "observer_bundle_sha": _sha(receipt.get("observer_bundle_sha"), "burnin.observer_bundle_sha"),
        "ml_manifest_sha": _sha(receipt.get("ml_manifest_sha"), "burnin.ml_manifest_sha"),
        "failure_manifest_sha": _sha(receipt.get("failure_manifest_sha"), "burnin.failure_manifest_sha"),
        "state_mutation_count": _integer(receipt.get("state_mutation_count"), "burnin.state_mutation_count"),
        "strategy_mutation_count": _integer(receipt.get("strategy_mutation_count"), "burnin.strategy_mutation_count"),
        "weight_mutation_count": _integer(receipt.get("weight_mutation_count"), "burnin.weight_mutation_count"),
        "ledger_mutation_count": _integer(receipt.get("ledger_mutation_count"), "burnin.ledger_mutation_count"),
        "paper_live_mutation_count": _integer(receipt.get("paper_live_mutation_count"), "burnin.paper_live_mutation_count"),
        "order_attempt_count": _integer(receipt.get("order_attempt_count"), "burnin.order_attempt_count"),
        "hold_requested": _bool(receipt.get("hold_requested"), "burnin.hold_requested"),
        "error_budget_used": _integer(receipt.get("error_budget_used"), "burnin.error_budget_used"),
        "authority": copy.deepcopy(receipt.get("authority")),
    }
    if normalized["authority"] != OBSERVER_SAFETY:
        _fail("BURNIN_AUTHORITY_MISMATCH", str(cycle))
    if normalized["shadow300_completion_sha"] != shadow["completion_sha"]:
        _fail("BURNIN_SHADOW300_BINDING_MISMATCH", str(cycle))
    if normalized["selected_combination_sha"] != shadow["selected_combination_sha"]:
        _fail("BURNIN_COMBINATION_BINDING_MISMATCH", str(cycle))
    if normalized["target_weights_sha"] != shadow["target_weights_sha"]:
        _fail("BURNIN_WEIGHT_BINDING_MISMATCH", str(cycle))
    if normalized["ml_manifest_sha"] != ml["observer_manifest_sha"]:
        _fail("BURNIN_ML_MANIFEST_MISMATCH", str(cycle))
    if normalized["failure_manifest_sha"] != failure["observer_manifest_sha"]:
        _fail("BURNIN_FAILURE_MANIFEST_MISMATCH", str(cycle))
    if normalized["observer_bundle_sha"] != expected_bundle_sha:
        _fail("BURNIN_OBSERVER_BUNDLE_MISMATCH", str(cycle))
    normalized["receipt_sha"] = canonical_sha(normalized)
    if normalized["receipt_sha"] != supplied_sha:
        _fail("BURNIN_NORMALIZED_SHA_MISMATCH", str(cycle))
    return normalized


def _metric_blockers(ml: Mapping[str, Any], failure: Mapping[str, Any], policy: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    if ml.get("state") != "PASS_ML_LIGHT_OBSERVATION":
        blockers.append("ML_OBSERVER_HOLD")
    if failure.get("state") != "PASS_FAILURE_LEARNING_OBSERVATION":
        blockers.append("FAILURE_OBSERVER_HOLD")
    if ml.get("evaluation_sample_count", 0) < policy["min_ml_evaluation_samples"]:
        blockers.append("ML_EVALUATION_SAMPLE_LOW")
    if failure.get("evaluation_sample_count", 0) < policy["min_failure_evaluation_samples"]:
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
    if _number(failure_drift.get("max_recurrence_delta_abs"), "failure.recurrence_drift") > policy["max_failure_recurrence_drift"]:
        blockers.append("FAILURE_RECURRENCE_DRIFT_BREACH")
    return blockers


def evaluate_gate(value: Mapping[str, Any]) -> dict[str, Any]:
    payload = _mapping(value, "post_shadow_observer_input")
    allowed = {"schema_version", "shadow300", "ml_observation", "failure_observation", "burnin_cycles", "policy", "authority"}
    missing = sorted(allowed - set(payload))
    extra = sorted(set(payload) - allowed)
    if missing:
        _fail("INPUT_FIELDS_MISSING", ",".join(missing))
    if extra:
        _fail("INPUT_EXTRA_FIELDS", ",".join(extra))
    if payload.get("schema_version") != INPUT_SCHEMA:
        _fail("INPUT_SCHEMA_MISMATCH")
    if payload.get("authority") != OBSERVER_SAFETY:
        _fail("INPUT_AUTHORITY_MISMATCH")

    shadow = validate_shadow300(payload["shadow300"])
    ml = validate_observer(payload["ml_observation"], "ML_LIGHT")
    failure = validate_observer(payload["failure_observation"], "FAILURE_LEARNING")
    policy = validate_policy(payload["policy"])
    bundle_sha = canonical_sha(
        {
            "shadow300_completion_sha": shadow["completion_sha"],
            "ml_manifest_sha": ml["observer_manifest_sha"],
            "failure_manifest_sha": failure["observer_manifest_sha"],
        }
    )
    raw_cycles = payload.get("burnin_cycles")
    if not isinstance(raw_cycles, list):
        _fail("BURNIN_CYCLES_ARRAY_REQUIRED")
    cycles = [validate_cycle(row, shadow, ml, failure, bundle_sha) for row in raw_cycles]
    cycles.sort(key=lambda row: row["cycle"])
    cycle_numbers = [row["cycle"] for row in cycles]
    if len(cycle_numbers) != len(set(cycle_numbers)):
        _fail("DUPLICATE_BURNIN_CYCLE")
    if cycle_numbers:
        expected = list(range(policy["first_burnin_cycle"], policy["first_burnin_cycle"] + len(cycle_numbers)))
        if cycle_numbers != expected:
            _fail("BURNIN_CYCLE_GAP_OR_REORDER")
    ledger_heads = [row["source_ledger_head_sha"] for row in cycles]
    observer_inputs = [row["observer_input_sha"] for row in cycles]
    if len(ledger_heads) != len(set(ledger_heads)):
        _fail("BURNIN_LEDGER_HEAD_NOT_APPEND_ONLY")
    if len(observer_inputs) != len(set(observer_inputs)):
        _fail("BURNIN_INPUT_SHA_DUPLICATE")

    metric_blockers = _metric_blockers(ml, failure, policy)
    hold_count = sum(row["hold_requested"] for row in cycles)
    error_budget_used = sum(row["error_budget_used"] for row in cycles)
    error_budget_ratio = error_budget_used / policy["error_budget_limit"]
    if len(cycles) != policy["required_burnin_cycles"]:
        metric_blockers.append("BURNIN_CYCLE_COUNT_NOT_100")
    if hold_count > policy["max_hold_requested_cycles"]:
        metric_blockers.append("HOLD_REQUEST_LIMIT")
    if error_budget_ratio > policy["max_error_budget_ratio"]:
        metric_blockers.append("OBSERVER_ERROR_BUDGET_BREACH")

    mutation_fields = (
        "state_mutation_count", "strategy_mutation_count", "weight_mutation_count",
        "ledger_mutation_count", "paper_live_mutation_count", "order_attempt_count",
    )
    mutation_totals = {field: sum(row[field] for row in cycles) for field in mutation_fields}
    mutation_blockers = [field.upper() for field, total in mutation_totals.items() if total != 0]

    if mutation_blockers:
        state = "BLOCK_POST_SHADOW_OBSERVER_MUTATION"
        blockers = mutation_blockers + metric_blockers
    elif metric_blockers:
        state = "HOLD_POST_SHADOW_OBSERVER_100C"
        blockers = metric_blockers
    else:
        state = "PASS_POST_SHADOW_OBSERVER_100C_GATE"
        blockers = []

    result = {
        "schema_version": OUTPUT_SCHEMA,
        "state": state,
        "shadow300_completion_sha": shadow["completion_sha"],
        "selected_combination_sha": shadow["selected_combination_sha"],
        "target_weights_sha": shadow["target_weights_sha"],
        "observer_bundle_sha": bundle_sha,
        "ml_manifest_sha": ml["observer_manifest_sha"],
        "failure_manifest_sha": failure["observer_manifest_sha"],
        "burnin_cycle_count": len(cycles),
        "burnin_start_cycle": cycles[0]["cycle"] if cycles else None,
        "burnin_end_cycle": cycles[-1]["cycle"] if cycles else None,
        "burnin_receipt_shas": [row["receipt_sha"] for row in cycles],
        "hold_requested_cycles": hold_count,
        "error_budget_used": error_budget_used,
        "error_budget_limit": policy["error_budget_limit"],
        "error_budget_ratio": error_budget_ratio,
        "mutation_totals": mutation_totals,
        "blocker_codes": sorted(set(blockers)),
        "ml_failure_readonly_bridge_allowed": state == "PASS_POST_SHADOW_OBSERVER_100C_GATE",
        "paper_30d_allowed": state == "PASS_POST_SHADOW_OBSERVER_100C_GATE",
        "automatic_paper_start": False,
        "strategy_write_allowed": False,
        "weight_write_allowed": False,
        "ledger_write_allowed": False,
        "live_order_allowed": False,
        "requested_action": "hold" if not state.startswith("BLOCK_") else "block",
        "production_threshold_authority": False,
        "next": "30D_PAPER_CANARY_MANUAL_START" if state == "PASS_POST_SHADOW_OBSERVER_100C_GATE" else "HOLD_OR_ROLLBACK_OBSERVER_ARTIFACTS",
        **OBSERVER_SAFETY,
    }
    result["gate_sha"] = canonical_sha(result)
    return result
