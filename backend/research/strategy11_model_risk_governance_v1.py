from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Mapping

ACTIONS = {"hold", "rollback", "block"}
SAFETY = {
    "research_only": True,
    "promotion_authority": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "order_authority": "BLOCKED",
}


class ModelRiskError(ValueError):
    pass


def _fail(code: str, detail: str = "") -> None:
    raise ModelRiskError(f"{code}:{detail}" if detail else code)


def canonical_sha(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def require_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail("STRING_REQUIRED", name)
    return value.strip()


def require_bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        _fail("BOOL_REQUIRED", name)
    return value


def require_number(value: Any, name: str, minimum: float | None = None, maximum: float | None = None) -> float:
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


def require_int(value: Any, name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        _fail("INT_REQUIRED", name)
    if value < minimum:
        _fail("INT_BELOW_MIN", name)
    return value


def require_sha(value: Any, name: str) -> str:
    result = require_string(value, name).lower()
    if len(result) != 64 or any(char not in "0123456789abcdef" for char in result):
        _fail("SHA256_REQUIRED", name)
    return result


def validate_policy(value: Mapping[str, Any]) -> dict[str, Any]:
    policy = dict(value)
    normalized = {
        "policy_id": require_string(policy.get("policy_id"), "policy.policy_id"),
        "drift_psi_warn": require_number(policy.get("drift_psi_warn"), "policy.drift_psi_warn", 0.0),
        "drift_psi_rollback": require_number(policy.get("drift_psi_rollback"), "policy.drift_psi_rollback", 0.0),
        "calibration_error_warn": require_number(policy.get("calibration_error_warn"), "policy.calibration_error_warn", 0.0, 1.0),
        "calibration_error_rollback": require_number(policy.get("calibration_error_rollback"), "policy.calibration_error_rollback", 0.0, 1.0),
        "error_budget_warn_ratio": require_number(policy.get("error_budget_warn_ratio"), "policy.error_budget_warn_ratio", 0.0, 1.0),
        "error_budget_block_ratio": require_number(policy.get("error_budget_block_ratio"), "policy.error_budget_block_ratio", 0.0),
        "max_shadow_dd_pct": require_number(policy.get("max_shadow_dd_pct"), "policy.max_shadow_dd_pct", 0.0),
        "max_cost_overrun_pct": require_number(policy.get("max_cost_overrun_pct"), "policy.max_cost_overrun_pct", 0.0),
        "max_correlation_breach_count": require_int(policy.get("max_correlation_breach_count"), "policy.max_correlation_breach_count", 0),
        "max_consecutive_failures": require_int(policy.get("max_consecutive_failures"), "policy.max_consecutive_failures", 1),
    }
    if normalized["drift_psi_warn"] >= normalized["drift_psi_rollback"]:
        _fail("DRIFT_THRESHOLD_ORDER_INVALID")
    if normalized["calibration_error_warn"] >= normalized["calibration_error_rollback"]:
        _fail("CALIBRATION_THRESHOLD_ORDER_INVALID")
    if normalized["error_budget_warn_ratio"] >= normalized["error_budget_block_ratio"]:
        _fail("ERROR_BUDGET_THRESHOLD_ORDER_INVALID")
    return normalized


def validate_snapshot(value: Mapping[str, Any]) -> dict[str, Any]:
    snapshot = dict(value)
    authority = snapshot.get("authority")
    if not isinstance(authority, Mapping):
        _fail("AUTHORITY_OBJECT_REQUIRED")
    authority = dict(authority)
    for key, expected in SAFETY.items():
        if authority.get(key) != expected:
            _fail("AUTHORITY_MISMATCH", key)
    if authority.get("runtime_bound") is not False:
        _fail("RUNTIME_BINDING_FORBIDDEN")
    return {
        "candidate_id": require_string(snapshot.get("candidate_id"), "snapshot.candidate_id"),
        "candidate_sha": require_sha(snapshot.get("candidate_sha"), "snapshot.candidate_sha"),
        "proposal_sha": require_sha(snapshot.get("proposal_sha"), "snapshot.proposal_sha"),
        "classification_sha": require_sha(snapshot.get("classification_sha"), "snapshot.classification_sha"),
        "correlation_analysis_sha": require_sha(snapshot.get("correlation_analysis_sha"), "snapshot.correlation_analysis_sha"),
        "portfolio_governor_sha": require_sha(snapshot.get("portfolio_governor_sha"), "snapshot.portfolio_governor_sha"),
        "attribution_projection_sha": require_sha(snapshot.get("attribution_projection_sha"), "snapshot.attribution_projection_sha"),
        "role_boundary_sha": require_sha(snapshot.get("role_boundary_sha"), "snapshot.role_boundary_sha"),
        "source_manifest_sha": require_sha(snapshot.get("source_manifest_sha"), "snapshot.source_manifest_sha"),
        "lineage_match": require_bool(snapshot.get("lineage_match"), "snapshot.lineage_match"),
        "stale": require_bool(snapshot.get("stale"), "snapshot.stale"),
        "private_field_violation": require_bool(snapshot.get("private_field_violation"), "snapshot.private_field_violation"),
        "drift_psi": require_number(snapshot.get("drift_psi"), "snapshot.drift_psi", 0.0),
        "calibration_error": require_number(snapshot.get("calibration_error"), "snapshot.calibration_error", 0.0, 1.0),
        "calibration_sample_count": require_int(snapshot.get("calibration_sample_count"), "snapshot.calibration_sample_count", 0),
        "error_budget_used": require_int(snapshot.get("error_budget_used"), "snapshot.error_budget_used", 0),
        "error_budget_limit": require_int(snapshot.get("error_budget_limit"), "snapshot.error_budget_limit", 1),
        "shadow_dd_pct": require_number(snapshot.get("shadow_dd_pct"), "snapshot.shadow_dd_pct", 0.0),
        "cost_overrun_pct": require_number(snapshot.get("cost_overrun_pct"), "snapshot.cost_overrun_pct", 0.0),
        "correlation_breach_count": require_int(snapshot.get("correlation_breach_count"), "snapshot.correlation_breach_count", 0),
        "consecutive_failures": require_int(snapshot.get("consecutive_failures"), "snapshot.consecutive_failures", 0),
        "incumbent_available": require_bool(snapshot.get("incumbent_available"), "snapshot.incumbent_available"),
        "shadow_only": require_bool(snapshot.get("shadow_only"), "snapshot.shadow_only"),
        "authority": {**SAFETY, "runtime_bound": False},
    }


def evaluate_model_risk(snapshot_value: Mapping[str, Any], policy_value: Mapping[str, Any]) -> dict[str, Any]:
    snapshot = validate_snapshot(snapshot_value)
    policy = validate_policy(policy_value)
    if snapshot["shadow_only"] is not True:
        _fail("SHADOW_ONLY_REQUIRED")

    budget_ratio = snapshot["error_budget_used"] / snapshot["error_budget_limit"]
    checks = {
        "lineage": snapshot["lineage_match"],
        "freshness": not snapshot["stale"],
        "private_fields": not snapshot["private_field_violation"],
        "drift_warn": snapshot["drift_psi"] < policy["drift_psi_warn"],
        "drift_rollback": snapshot["drift_psi"] < policy["drift_psi_rollback"],
        "calibration_warn": snapshot["calibration_error"] < policy["calibration_error_warn"],
        "calibration_rollback": snapshot["calibration_error"] < policy["calibration_error_rollback"],
        "error_budget_warn": budget_ratio < policy["error_budget_warn_ratio"],
        "error_budget_block": budget_ratio < policy["error_budget_block_ratio"],
        "shadow_dd": snapshot["shadow_dd_pct"] <= policy["max_shadow_dd_pct"],
        "cost_overrun": snapshot["cost_overrun_pct"] <= policy["max_cost_overrun_pct"],
        "correlation": snapshot["correlation_breach_count"] <= policy["max_correlation_breach_count"],
        "failure_streak": snapshot["consecutive_failures"] < policy["max_consecutive_failures"],
    }

    block_reasons: list[str] = []
    rollback_reasons: list[str] = []
    hold_reasons: list[str] = []
    if not checks["lineage"]:
        block_reasons.append("LINEAGE_MISMATCH")
    if not checks["private_fields"]:
        block_reasons.append("PRIVATE_FIELD_VIOLATION")
    if not checks["error_budget_block"]:
        block_reasons.append("ERROR_BUDGET_EXHAUSTED")
    if not checks["freshness"]:
        hold_reasons.append("STALE_EVIDENCE")
    if not checks["drift_rollback"]:
        rollback_reasons.append("DRIFT_ROLLBACK_THRESHOLD")
    elif not checks["drift_warn"]:
        hold_reasons.append("DRIFT_WARNING")
    if not checks["calibration_rollback"]:
        rollback_reasons.append("CALIBRATION_ROLLBACK_THRESHOLD")
    elif not checks["calibration_warn"]:
        hold_reasons.append("CALIBRATION_WARNING")
    if not checks["error_budget_warn"] and checks["error_budget_block"]:
        hold_reasons.append("ERROR_BUDGET_WARNING")
    if not checks["shadow_dd"]:
        rollback_reasons.append("SHADOW_DD_BREACH")
    if not checks["cost_overrun"]:
        rollback_reasons.append("COST_OVERRUN")
    if not checks["correlation"]:
        rollback_reasons.append("CORRELATION_BREACH")
    if not checks["failure_streak"]:
        rollback_reasons.append("CONSECUTIVE_FAILURE_LIMIT")

    if block_reasons:
        state = "BLOCK_MODEL_RISK"
        requested_action = "block"
        reason_codes = block_reasons + rollback_reasons + hold_reasons
    elif rollback_reasons:
        if snapshot["incumbent_available"]:
            state = "ROLLBACK_MODEL_RISK"
            requested_action = "rollback"
        else:
            state = "HOLD_MODEL_RISK_REVIEW"
            requested_action = "hold"
            rollback_reasons.append("INCUMBENT_UNAVAILABLE")
        reason_codes = rollback_reasons + hold_reasons
    elif hold_reasons:
        state = "HOLD_MODEL_RISK_REVIEW"
        requested_action = "hold"
        reason_codes = hold_reasons
    else:
        state = "PASS_MODEL_RISK_GOVERNANCE"
        requested_action = "hold"
        reason_codes = ["ALL_MODEL_RISK_GATES_PASS"]

    if requested_action not in ACTIONS:
        _fail("ACTION_INVALID")
    result = {
        "schema_version": "strategy11.model_risk_governance.v1",
        "state": state,
        "candidate_id": snapshot["candidate_id"],
        "requested_action": requested_action,
        "reason_codes": sorted(set(reason_codes)),
        "checks": checks,
        "metrics": {
            "drift_psi": snapshot["drift_psi"],
            "calibration_error": snapshot["calibration_error"],
            "calibration_sample_count": snapshot["calibration_sample_count"],
            "error_budget_used": snapshot["error_budget_used"],
            "error_budget_limit": snapshot["error_budget_limit"],
            "error_budget_ratio": budget_ratio,
            "shadow_dd_pct": snapshot["shadow_dd_pct"],
            "cost_overrun_pct": snapshot["cost_overrun_pct"],
            "correlation_breach_count": snapshot["correlation_breach_count"],
            "consecutive_failures": snapshot["consecutive_failures"],
        },
        "lineage": {
            key: snapshot[key]
            for key in (
                "candidate_sha", "proposal_sha", "classification_sha", "correlation_analysis_sha",
                "portfolio_governor_sha", "attribution_projection_sha", "role_boundary_sha", "source_manifest_sha",
            )
        },
        "policy": policy,
        "policy_sha": canonical_sha(policy),
        "rollback_target": "PREVIOUS_VERIFIED_INCUMBENT" if requested_action == "rollback" else None,
        "automatic_order_action": False,
        "runtime_mutation_allowed": False,
        "shadow_only": True,
        "runtime_bound": False,
        **SAFETY,
    }
    result["governance_sha"] = canonical_sha(result)
    return result
