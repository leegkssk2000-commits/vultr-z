from __future__ import annotations

import copy
from datetime import datetime
from typing import Any, Mapping

from backend.contracts.strategy11_source_binding_contract_v1 import SAFETY, canonical_sha

INPUT_SCHEMA = "strategy11.observer_only_gate.input.v1"
OUTPUT_SCHEMA = "strategy11.observer_only_gate.output.v1"
REQUIRED_TYPES = {"ML_LIGHT", "FAILURE_LEARNING"}
FORBIDDEN_CAPABILITIES = {
    "WRITE_STRATEGY", "WRITE_THRESHOLD", "WRITE_WEIGHT", "WRITE_LEDGER",
    "OPEN_ORDER", "CLOSE_ORDER", "AMEND_ORDER", "ENABLE_PAPER", "ENABLE_LIVE",
    "PROMOTE_CANDIDATE", "OVERRIDE_SBOT_VETO",
}


class ObserverOnlyGateError(ValueError):
    pass


def _fail(code: str, detail: str = "") -> None:
    raise ObserverOnlyGateError(f"{code}:{detail}" if detail else code)


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
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        _fail("SHA256_REQUIRED", name)
    return result


def _integer(value: Any, name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        _fail("INT_REQUIRED", name)
    return value


def _timestamp(value: Any, name: str) -> datetime:
    text = _string(value, name)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ObserverOnlyGateError(f"TIMESTAMP_INVALID:{name}") from exc
    if parsed.tzinfo is None:
        _fail("TIMESTAMP_TIMEZONE_REQUIRED", name)
    return parsed


def _authority(value: Any) -> dict[str, Any]:
    authority = _mapping(value, "authority")
    for key, expected in SAFETY.items():
        if authority.get(key) != expected:
            _fail("AUTHORITY_MISMATCH", key)
    if authority.get("runtime_bound") is not False:
        _fail("RUNTIME_BOUND_FORBIDDEN")
    return {**SAFETY, "runtime_bound": False}


def validate_shadow300(value: Any) -> dict[str, Any]:
    result = _mapping(value, "shadow300")
    if result.get("state") != "PASS_SHADOW300_READ_ONLY_COMPLETION":
        _fail("SHADOW300_NOT_PASS", str(result.get("state")))
    for key, expected in SAFETY.items():
        if result.get(key) != expected:
            _fail("SHADOW300_SAFETY_MISMATCH", key)
    if result.get("runtime_bound") is not False or result.get("real_shadow_started") is not False:
        _fail("SHADOW300_RUNTIME_FORBIDDEN")
    if result.get("ml_light_observer_gate_allowed") is not True:
        _fail("ML_LIGHT_OBSERVER_GATE_NOT_ALLOWED")
    if result.get("failure_learning_observer_gate_allowed") is not True:
        _fail("FAILURE_LEARNING_OBSERVER_GATE_NOT_ALLOWED")
    if result.get("paper_30d_allowed") is not False:
        _fail("PAPER_PREMATURELY_ALLOWED")
    supplied = _sha(result.get("completion_sha"), "shadow300.completion_sha")
    computed = canonical_sha({key: child for key, child in result.items() if key != "completion_sha"})
    if supplied != computed:
        _fail("SHADOW300_SHA_MISMATCH")
    return {
        "completion_sha": supplied,
        "selected_combination_sha": _sha(result.get("selected_combination_sha"), "shadow300.selected_combination_sha"),
        "target_weights_sha": _sha(result.get("target_weights_sha"), "shadow300.target_weights_sha"),
        "shared_lineage": copy.deepcopy(_mapping(result.get("shared_lineage"), "shadow300.shared_lineage")),
    }


def validate_observer(value: Any, index: int, min_calibration_samples: int) -> dict[str, Any]:
    observer = _mapping(value, f"observers[{index}]")
    required = {
        "observer_id", "observer_type", "source_sha", "model_sha", "config_sha",
        "training_data_sha", "feature_lineage_sha", "output_schema_sha",
        "training_cutoff_ts", "evaluation_start_ts", "calibration_sample_count",
        "leakage_check_pass", "drift_baseline_pass", "calibration_baseline_pass",
        "attribution_plan_pass", "rollback_plan_pass", "offline_fixture_pass",
        "reads_existing_sealed", "advisory_enabled", "runtime_bound",
        "capabilities", "authority",
    }
    missing = sorted(required - set(observer))
    extra = sorted(set(observer) - required)
    if missing:
        _fail("OBSERVER_FIELDS_MISSING", f"{index}:{','.join(missing)}")
    if extra:
        _fail("OBSERVER_EXTRA_FIELDS", f"{index}:{','.join(extra)}")
    observer_type = _string(observer["observer_type"], f"observers[{index}].observer_type").upper()
    if observer_type not in REQUIRED_TYPES:
        _fail("OBSERVER_TYPE_INVALID", observer_type)
    authority = _mapping(observer["authority"], f"observers[{index}].authority")
    for key, expected in SAFETY.items():
        if authority.get(key) != expected:
            _fail("OBSERVER_AUTHORITY_MISMATCH", f"{observer_type}:{key}")
    if observer["runtime_bound"] is not False:
        _fail("OBSERVER_RUNTIME_BOUND", observer_type)
    if observer["advisory_enabled"] is not False:
        _fail("OBSERVER_ADVISORY_PREMATURE", observer_type)
    if observer["reads_existing_sealed"] is not False:
        _fail("EXISTING_SEALED_READ_FORBIDDEN", observer_type)
    capabilities = observer["capabilities"]
    if not isinstance(capabilities, list):
        _fail("CAPABILITIES_ARRAY_REQUIRED", observer_type)
    normalized_capabilities = sorted({_string(item, "capabilities[]").upper() for item in capabilities})
    forbidden = sorted(set(normalized_capabilities) & FORBIDDEN_CAPABILITIES)
    if forbidden:
        _fail("OBSERVER_FORBIDDEN_CAPABILITY", f"{observer_type}:{','.join(forbidden)}")
    if set(normalized_capabilities) - {"READ_EVIDENCE", "EMIT_OBSERVATION", "EMIT_CALIBRATION", "REQUEST_HOLD"}:
        _fail("OBSERVER_UNKNOWN_CAPABILITY", observer_type)
    for field in (
        "leakage_check_pass", "drift_baseline_pass", "calibration_baseline_pass",
        "attribution_plan_pass", "rollback_plan_pass", "offline_fixture_pass",
    ):
        if observer[field] is not True:
            _fail("OBSERVER_CHECK_NOT_PASS", f"{observer_type}:{field}")
    calibration_samples = _integer(observer["calibration_sample_count"], f"observers[{index}].calibration_sample_count", 0)
    if calibration_samples < min_calibration_samples:
        _fail("CALIBRATION_SAMPLE_COUNT_LOW", observer_type)
    training_cutoff = _timestamp(observer["training_cutoff_ts"], f"observers[{index}].training_cutoff_ts")
    evaluation_start = _timestamp(observer["evaluation_start_ts"], f"observers[{index}].evaluation_start_ts")
    if training_cutoff >= evaluation_start:
        _fail("TRAINING_EVALUATION_LEAKAGE", observer_type)
    normalized = {
        "observer_id": _string(observer["observer_id"], f"observers[{index}].observer_id"),
        "observer_type": observer_type,
        "source_sha": _sha(observer["source_sha"], f"observers[{index}].source_sha"),
        "model_sha": _sha(observer["model_sha"], f"observers[{index}].model_sha"),
        "config_sha": _sha(observer["config_sha"], f"observers[{index}].config_sha"),
        "training_data_sha": _sha(observer["training_data_sha"], f"observers[{index}].training_data_sha"),
        "feature_lineage_sha": _sha(observer["feature_lineage_sha"], f"observers[{index}].feature_lineage_sha"),
        "output_schema_sha": _sha(observer["output_schema_sha"], f"observers[{index}].output_schema_sha"),
        "training_cutoff_ts": observer["training_cutoff_ts"],
        "evaluation_start_ts": observer["evaluation_start_ts"],
        "calibration_sample_count": calibration_samples,
        "capabilities": normalized_capabilities,
        "advisory_enabled": False,
        "runtime_bound": False,
        "reads_existing_sealed": False,
        **{field: True for field in (
            "leakage_check_pass", "drift_baseline_pass", "calibration_baseline_pass",
            "attribution_plan_pass", "rollback_plan_pass", "offline_fixture_pass",
        )},
        "authority": {**SAFETY, "runtime_bound": False},
    }
    normalized["observer_manifest_sha"] = canonical_sha(normalized)
    return normalized


def evaluate(value: Mapping[str, Any]) -> dict[str, Any]:
    payload = _mapping(value, "input")
    if payload.get("schema_version") != INPUT_SCHEMA:
        _fail("INPUT_SCHEMA_MISMATCH")
    authority = _authority(payload.get("authority"))
    shadow = validate_shadow300(payload.get("shadow300"))
    policy = _mapping(payload.get("policy"), "policy")
    policy_id = _string(policy.get("policy_id"), "policy.policy_id")
    min_samples = _integer(policy.get("min_calibration_samples"), "policy.min_calibration_samples", 1)
    required_burnin_cycles = _integer(policy.get("required_observer_burnin_cycles"), "policy.required_observer_burnin_cycles", 1)
    if required_burnin_cycles < 20:
        _fail("OBSERVER_BURNIN_BELOW_20")
    raw = payload.get("observers")
    if not isinstance(raw, list):
        _fail("OBSERVERS_ARRAY_REQUIRED")
    if len(raw) != 2:
        return _result("HOLD_OBSERVER_ONLY_GATE_INCOMPLETE", shadow, [], policy_id, min_samples, required_burnin_cycles, authority, ["TWO_OBSERVERS_REQUIRED"])
    observers = [validate_observer(row, index, min_samples) for index, row in enumerate(raw)]
    types = {row["observer_type"] for row in observers}
    if types != REQUIRED_TYPES:
        _fail("REQUIRED_OBSERVER_TYPES_MISSING")
    if len({row["observer_id"] for row in observers}) != 2:
        _fail("DUPLICATE_OBSERVER_ID")
    if len({row["training_data_sha"] for row in observers}) != 2:
        _fail("OBSERVER_TRAINING_DATA_NOT_INDEPENDENT")
    if len({row["model_sha"] for row in observers}) != 2:
        _fail("OBSERVER_MODEL_NOT_INDEPENDENT")
    return _result("PASS_OBSERVER_ONLY_GATE", shadow, observers, policy_id, min_samples, required_burnin_cycles, authority, [])


def _result(state: str, shadow: dict[str, Any], observers: list[dict[str, Any]], policy_id: str,
            min_samples: int, burnin_cycles: int, authority: dict[str, Any], blockers: list[str]) -> dict[str, Any]:
    result = {
        "schema_version": OUTPUT_SCHEMA,
        "state": state,
        "shadow300_completion_sha": shadow["completion_sha"],
        "selected_combination_sha": shadow["selected_combination_sha"],
        "target_weights_sha": shadow["target_weights_sha"],
        "shared_lineage": copy.deepcopy(shadow["shared_lineage"]),
        "observer_count": len(observers),
        "observer_manifests": observers,
        "observer_bundle_sha": canonical_sha(observers),
        "policy": {
            "policy_id": policy_id,
            "min_calibration_samples": min_samples,
            "required_observer_burnin_cycles": burnin_cycles,
        },
        "blocker_codes": sorted(set(blockers)),
        "observer_burnin_allowed": state == "PASS_OBSERVER_ONLY_GATE",
        "observer_advisory_allowed": False,
        "strategy_input_allowed": False,
        "portfolio_weight_input_allowed": False,
        "paper_30d_allowed": False,
        "runtime_bound": False,
        "automatic_activation": False,
        "requested_action": "hold",
        "production_threshold_authority": False,
        **authority,
    }
    result["gate_sha"] = canonical_sha(result)
    return result
