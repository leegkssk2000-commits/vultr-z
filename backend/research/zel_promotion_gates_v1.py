from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

SCHEMA_VERSION = "zel.completion.promotion_gates.v1"
PHASES = ("P1", "P2", "P3", "P4", "P5", "P6", "CLEANUP")
PHASE_WEIGHTS = {"P1": 15.0, "P2": 15.0, "P3": 15.0, "P4": 20.0, "P5": 15.0, "P6": 10.0, "CLEANUP": 10.0}


class PromotionGateError(ValueError):
    pass


def _fail(code: str, detail: str = "") -> None:
    raise PromotionGateError(f"{code}:{detail}" if detail else code)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def canonical_sha(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail("OBJECT_REQUIRED", name)
    return dict(value)


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail("NUMBER_REQUIRED", name)
    result = float(value)
    if result != result or result in (float("inf"), float("-inf")):
        _fail("NUMBER_NOT_FINITE", name)
    return result


def _eq(evidence: dict[str, Any], key: str, expected: Any, blockers: list[str]) -> None:
    if evidence.get(key) != expected:
        blockers.append(f"{key}!={expected}")


def _range(evidence: dict[str, Any], key: str, low: float, high: float, blockers: list[str]) -> None:
    try:
        value = _number(evidence.get(key), key)
    except PromotionGateError:
        blockers.append(f"{key}:INVALID")
        return
    if not low <= value <= high:
        blockers.append(f"{key}:{value}_OUTSIDE_{low}_{high}")


def evaluate_p1(e: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    for key, expected in {
        "lifecycle_strategy_count": 25, "observer_allowed_count": 25,
        "capital_allowed_count": 0, "event_lineage_coverage_pct": 100.0,
        "duplicate_event_count": 0, "missing_close_count": 0,
        "missing_ledger_join_count": 0, "cross_lane_leak_count": 0,
        "polling_is_proof_authority": False, "parent_strategy_mutation_count": 0,
    }.items():
        _eq(e, key, expected, blockers)
    return blockers


def evaluate_p2(e: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    _eq(e, "liveness_evaluated_count", 25, blockers)
    _eq(e, "failure_fingerprint_coverage_pct", 100.0, blockers)
    _range(e, "shadow_survivor_count", 10, 15, blockers)
    for key in ("single_axis_violation_count", "same_sample_tune_promote_count", "parent_strategy_mutation_count", "cost_stress_missing_count", "regime_symbol_side_split_missing_count"):
        _eq(e, key, 0, blockers)
    return blockers


def evaluate_p3(e: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    _range(e, "s_material_count", 6, 10, blockers)
    _range(e, "standalone_strategy_count", 4, 7, blockers)
    _range(e, "family_ensemble_count", 3, 5, blockers)
    _range(e, "active_ensemble_count", 2, 3, blockers)
    for key in ("joint_dd_breach_count", "correlation_limit_breach_count", "turnover_limit_breach_count", "family_exposure_breach_count", "sbot_veto_override_count", "attribution_residual_count"):
        _eq(e, key, 0, blockers)
    return blockers


def evaluate_p4(e: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    for key in ("persistent_idempotency_pass", "partial_fill_recovery_pass", "sent_ack_timeout_recovery_pass", "crash_recovery_pass", "manual_desync_recovery_pass"):
        _eq(e, key, True, blockers)
    for key in ("duplicate_order_count", "orphan_order_count", "unreconciled_position_count"):
        _eq(e, key, 0, blockers)
    _eq(e, "private_exchange_call_enabled", False, blockers)
    _eq(e, "live_order_authority", "BLOCKED", blockers)
    return blockers


def evaluate_p5(e: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    _range(e, "paper_days", 30, 100000, blockers)
    _range(e, "paper_closed_positions", 1, 1000000000, blockers)
    for key in ("ssot_thresholds_bound", "paper_restart_recovery_pass", "paper_rollback_drill_pass", "paper_private_api_receipt_bound"):
        _eq(e, key, True, blockers)
    for key in ("paper_threshold_breach_count", "paper_lifecycle_mismatch_count", "paper_ledger_mismatch_count", "paper_display_mismatch_count"):
        _eq(e, key, 0, blockers)
    return blockers


def evaluate_p6(e: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    for key in ("human_approval", "micro_live_canary_completed", "capital_risk_ssot_bound", "emergency_stop_drill_pass", "live_rollback_drill_pass", "activation_receipt_sha_bound"):
        _eq(e, key, True, blockers)
    for key in ("live_threshold_breach_count", "live_incident_count", "live_unreconciled_position_count", "live_duplicate_order_count"):
        _eq(e, key, 0, blockers)
    return blockers


def evaluate_cleanup(e: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    for key in ("pipeline_bottleneck_count", "duplicate_owner_count", "broken_import_count", "syntax_error_count", "stale_module_count", "orphan_artifact_count", "unsafe_execution_token_count"):
        _eq(e, key, 0, blockers)
    _eq(e, "full_regression_pass", True, blockers)
    _eq(e, "rollback_manifest_complete", True, blockers)
    return blockers


EVALUATORS = {"P1": evaluate_p1, "P2": evaluate_p2, "P3": evaluate_p3, "P4": evaluate_p4, "P5": evaluate_p5, "P6": evaluate_p6, "CLEANUP": evaluate_cleanup}


def evaluate_completion(value: Mapping[str, Any]) -> dict[str, Any]:
    payload = _mapping(value, "evidence")
    if payload.get("schema_version") != "zel.completion.evidence.v1":
        _fail("EVIDENCE_SCHEMA_MISMATCH")
    if payload.get("source_authority_verified") is not True:
        _fail("SOURCE_AUTHORITY_NOT_VERIFIED")
    if payload.get("fixture_only") is not False:
        _fail("REAL_EVIDENCE_REQUIRED")
    phases = _mapping(payload.get("phases"), "phases")
    results: dict[str, Any] = {}
    blocked_upstream = False
    completed_weight = 0.0
    highest_completed = "NONE"
    for phase in PHASES:
        phase_evidence = _mapping(phases.get(phase, {}), f"phases.{phase}")
        blockers = EVALUATORS[phase](phase_evidence)
        if blocked_upstream:
            blockers = ["UPSTREAM_PHASE_NOT_PASS"] + blockers
        passed = not blockers
        results[phase] = {"pass": passed, "blockers": blockers, "evidence_sha256": canonical_sha(phase_evidence)}
        if passed:
            completed_weight += PHASE_WEIGHTS[phase]
            highest_completed = phase
        else:
            blocked_upstream = True
    all_pass = all(results[phase]["pass"] for phase in PHASES)
    return {
        "schema_version": SCHEMA_VERSION,
        "state": "PASS_ZEL_COMPLETION_100" if all_pass else "HOLD_ZEL_COMPLETION_INCOMPLETE",
        "completion_pct": round(completed_weight, 10), "highest_completed_phase": highest_completed,
        "phase_results": results, "claim_100_allowed": all_pass, "activation_allowed": False,
        "activation_requires_separate_human_approved_receipt": True,
        "execution_authority": "NONE", "order_authority": "BLOCKED", "input_sha256": canonical_sha(payload),
    }


def fixture_evidence() -> dict[str, Any]:
    return {
        "schema_version": "zel.completion.evidence.v1", "source_authority_verified": True, "fixture_only": True,
        "phases": {
            "P1": {"lifecycle_strategy_count": 25, "observer_allowed_count": 25, "capital_allowed_count": 0, "event_lineage_coverage_pct": 100.0, "duplicate_event_count": 0, "missing_close_count": 0, "missing_ledger_join_count": 0, "cross_lane_leak_count": 0, "polling_is_proof_authority": False, "parent_strategy_mutation_count": 0},
            "P2": {"liveness_evaluated_count": 25, "failure_fingerprint_coverage_pct": 100.0, "shadow_survivor_count": 12, "single_axis_violation_count": 0, "same_sample_tune_promote_count": 0, "parent_strategy_mutation_count": 0, "cost_stress_missing_count": 0, "regime_symbol_side_split_missing_count": 0},
            "P3": {"s_material_count": 8, "standalone_strategy_count": 5, "family_ensemble_count": 4, "active_ensemble_count": 3, "joint_dd_breach_count": 0, "correlation_limit_breach_count": 0, "turnover_limit_breach_count": 0, "family_exposure_breach_count": 0, "sbot_veto_override_count": 0, "attribution_residual_count": 0},
            "P4": {"persistent_idempotency_pass": True, "duplicate_order_count": 0, "orphan_order_count": 0, "unreconciled_position_count": 0, "partial_fill_recovery_pass": True, "sent_ack_timeout_recovery_pass": True, "crash_recovery_pass": True, "manual_desync_recovery_pass": True, "private_exchange_call_enabled": False, "live_order_authority": "BLOCKED"},
            "P5": {"paper_days": 30, "paper_closed_positions": 100, "ssot_thresholds_bound": True, "paper_threshold_breach_count": 0, "paper_lifecycle_mismatch_count": 0, "paper_ledger_mismatch_count": 0, "paper_display_mismatch_count": 0, "paper_restart_recovery_pass": True, "paper_rollback_drill_pass": True, "paper_private_api_receipt_bound": True},
            "P6": {"human_approval": True, "micro_live_canary_completed": True, "capital_risk_ssot_bound": True, "live_threshold_breach_count": 0, "live_incident_count": 0, "live_unreconciled_position_count": 0, "live_duplicate_order_count": 0, "emergency_stop_drill_pass": True, "live_rollback_drill_pass": True, "activation_receipt_sha_bound": True},
            "CLEANUP": {"pipeline_bottleneck_count": 0, "duplicate_owner_count": 0, "broken_import_count": 0, "syntax_error_count": 0, "stale_module_count": 0, "orphan_artifact_count": 0, "unsafe_execution_token_count": 0, "full_regression_pass": True, "rollback_manifest_complete": True},
        },
    }
