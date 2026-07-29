from __future__ import annotations

import copy
import math
from typing import Any, Mapping

from backend.contracts.strategy11_source_binding_contract_v1 import SAFETY, canonical_sha
from backend.research.strategy11_shadow200_readonly_accumulator_v1 import validate_segment

INPUT_SCHEMA = "strategy11.shadow300_readonly_completion.input.v1"
OUTPUT_SCHEMA = "strategy11.shadow300_readonly_completion.output.v1"
REQUIRED_CONTINUATION_SEGMENTS = 5
REQUIRED_TOTAL_CYCLES = 300
FINAL_CHECKS = (
    "source_parity_pass",
    "strategy_config_unchanged",
    "portfolio_policy_unchanged",
    "material_seals_unchanged",
    "role_boundaries_pass",
    "attribution_complete",
    "model_risk_pass",
    "display_integrity_pass",
    "chaos_e2e_pass",
    "rollback_drill_pass",
    "failure_learning_disconnected",
    "ml_light_disconnected",
    "paper_live_order_blocked",
)


class Shadow300CompletionError(ValueError):
    pass


def _fail(code: str, detail: str = "") -> None:
    raise Shadow300CompletionError(f"{code}:{detail}" if detail else code)


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


def _number(value: Any, name: str, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail("NUMBER_REQUIRED", name)
    result = float(value)
    if not math.isfinite(result):
        _fail("NUMBER_NOT_FINITE", name)
    if minimum is not None and result < minimum:
        _fail("NUMBER_BELOW_MIN", name)
    return result


def _integer(value: Any, name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        _fail("INT_REQUIRED", name)
    if value < minimum:
        _fail("INT_BELOW_MIN", name)
    return value


def _authority(value: Any) -> dict[str, Any]:
    authority = _mapping(value, "authority")
    for key, expected in SAFETY.items():
        if authority.get(key) != expected:
            _fail("AUTHORITY_MISMATCH", key)
    if authority.get("runtime_bound") is not False:
        _fail("RUNTIME_BOUND_FORBIDDEN")
    return {**SAFETY, "runtime_bound": False}


def validate_base_200(value: Any) -> dict[str, Any]:
    base = _mapping(value, "base_200")
    if base.get("state") != "PASS_SHADOW200_READ_ONLY_ACCUMULATION":
        _fail("BASE_200_NOT_PASS", str(base.get("state")))
    for key, expected in SAFETY.items():
        if base.get(key) != expected:
            _fail("BASE_200_SAFETY_MISMATCH", key)
    if base.get("runtime_bound") is not False or base.get("real_shadow_started") is not False:
        _fail("BASE_200_RUNTIME_FORBIDDEN")
    if base.get("shadow_300c_allowed") is not True:
        _fail("BASE_200_300C_NOT_ALLOWED")
    if base.get("cycle_count") != 200 or base.get("segment_count") != 10:
        _fail("BASE_200_COUNT_MISMATCH")
    supplied = _sha(base.get("accumulator_sha"), "base_200.accumulator_sha")
    computed = canonical_sha({key: child for key, child in base.items() if key != "accumulator_sha"})
    if supplied != computed:
        _fail("BASE_200_SHA_MISMATCH")
    metrics = _mapping(base.get("metrics"), "base_200.metrics")
    lineage = _mapping(base.get("shared_lineage"), "base_200.shared_lineage")
    return {
        "accumulator_sha": supplied,
        "selected_combination_sha": _sha(base.get("selected_combination_sha"), "base_200.selected_combination_sha"),
        "target_weights_sha": _sha(base.get("target_weights_sha"), "base_200.target_weights_sha"),
        "shared_lineage": {
            "source_w1_manifest_sha": _sha(lineage.get("source_w1_manifest_sha"), "base_200.source_w1_manifest_sha"),
            "data_sha": _sha(lineage.get("data_sha"), "base_200.data_sha"),
            "window_sha": _sha(lineage.get("window_sha"), "base_200.window_sha"),
            "evidence_manifest_sha": _sha(lineage.get("evidence_manifest_sha"), "base_200.evidence_manifest_sha"),
        },
        "metrics": {
            "total_net_r": _number(metrics.get("total_net_r"), "base_200.metrics.total_net_r"),
            "total_cost_r": _number(metrics.get("total_cost_r"), "base_200.metrics.total_cost_r", 0.0),
            "max_shadow_dd_pct": _number(metrics.get("max_shadow_dd_pct"), "base_200.metrics.max_shadow_dd_pct", 0.0),
            "max_cost_overrun_pct": _number(metrics.get("max_cost_overrun_pct"), "base_200.metrics.max_cost_overrun_pct", 0.0),
            "max_abs_weight_drift": _number(metrics.get("max_abs_weight_drift"), "base_200.metrics.max_abs_weight_drift", 0.0),
            "max_abs_rolling_correlation": _number(metrics.get("max_abs_rolling_correlation"), "base_200.metrics.max_abs_rolling_correlation", 0.0),
            "max_attribution_error_r": _number(metrics.get("max_attribution_error_r"), "base_200.metrics.max_attribution_error_r", 0.0),
            "stale_cycles": _integer(metrics.get("stale_cycles"), "base_200.metrics.stale_cycles", 0),
            "source_parity_failures": _integer(metrics.get("source_parity_failures"), "base_200.metrics.source_parity_failures", 0),
            "display_integrity_failures": _integer(metrics.get("display_integrity_failures"), "base_200.metrics.display_integrity_failures", 0),
            "lineage_failures": _integer(metrics.get("lineage_failures"), "base_200.metrics.lineage_failures", 0),
            "chaos_e2e_failures": _integer(metrics.get("chaos_e2e_failures"), "base_200.metrics.chaos_e2e_failures", 0),
        },
    }


def validate_policy(value: Any) -> dict[str, Any]:
    policy = _mapping(value, "policy")
    required = {
        "policy_id", "required_total_cycles", "max_shadow_dd_pct", "max_cost_overrun_pct",
        "max_abs_weight_drift", "max_abs_rolling_correlation", "max_attribution_error_r",
        "min_total_net_r", "max_stale_cycles", "max_source_parity_failures",
        "max_display_integrity_failures", "max_lineage_failures", "max_chaos_e2e_failures",
        "max_error_budget_ratio",
    }
    missing = sorted(required - set(policy))
    if missing:
        _fail("POLICY_FIELDS_MISSING", ",".join(missing))
    normalized = {
        "policy_id": _string(policy["policy_id"], "policy.policy_id"),
        "required_total_cycles": _integer(policy["required_total_cycles"], "policy.required_total_cycles", 1),
        "max_shadow_dd_pct": _number(policy["max_shadow_dd_pct"], "policy.max_shadow_dd_pct", 0.0),
        "max_cost_overrun_pct": _number(policy["max_cost_overrun_pct"], "policy.max_cost_overrun_pct", 0.0),
        "max_abs_weight_drift": _number(policy["max_abs_weight_drift"], "policy.max_abs_weight_drift", 0.0),
        "max_abs_rolling_correlation": _number(policy["max_abs_rolling_correlation"], "policy.max_abs_rolling_correlation", 0.0),
        "max_attribution_error_r": _number(policy["max_attribution_error_r"], "policy.max_attribution_error_r", 0.0),
        "min_total_net_r": _number(policy["min_total_net_r"], "policy.min_total_net_r"),
        "max_stale_cycles": _integer(policy["max_stale_cycles"], "policy.max_stale_cycles", 0),
        "max_source_parity_failures": _integer(policy["max_source_parity_failures"], "policy.max_source_parity_failures", 0),
        "max_display_integrity_failures": _integer(policy["max_display_integrity_failures"], "policy.max_display_integrity_failures", 0),
        "max_lineage_failures": _integer(policy["max_lineage_failures"], "policy.max_lineage_failures", 0),
        "max_chaos_e2e_failures": _integer(policy["max_chaos_e2e_failures"], "policy.max_chaos_e2e_failures", 0),
        "max_error_budget_ratio": _number(policy["max_error_budget_ratio"], "policy.max_error_budget_ratio", 0.0),
    }
    if normalized["required_total_cycles"] != REQUIRED_TOTAL_CYCLES:
        _fail("TOTAL_CYCLE_POLICY_MUST_EQUAL_300")
    return normalized


def validate_final_review(value: Any) -> dict[str, Any]:
    review = _mapping(value, "final_review")
    for key in FINAL_CHECKS:
        if review.get(key) is not True:
            _fail("FINAL_CHECK_NOT_PASS", key)
    evidence = _mapping(review.get("evidence_stages"), "final_review.evidence_stages")
    if set(evidence) != {"W1", "W2", "W3", "NEW_SEALED"} or any(state != "PASS" for state in evidence.values()):
        _fail("FINAL_EVIDENCE_STAGES_INVALID")
    error_budget_used = _integer(review.get("error_budget_used"), "final_review.error_budget_used", 0)
    error_budget_limit = _integer(review.get("error_budget_limit"), "final_review.error_budget_limit", 1)
    return {
        **{key: True for key in FINAL_CHECKS},
        "evidence_stages": copy.deepcopy(evidence),
        "error_budget_used": error_budget_used,
        "error_budget_limit": error_budget_limit,
        "error_budget_ratio": error_budget_used / error_budget_limit,
    }


def complete(value: Mapping[str, Any]) -> dict[str, Any]:
    payload = _mapping(value, "input")
    if payload.get("schema_version") != INPUT_SCHEMA:
        _fail("INPUT_SCHEMA_MISMATCH")
    authority = _authority(payload.get("authority"))
    base = validate_base_200(payload.get("base_200"))
    policy = validate_policy(payload.get("policy"))
    raw_segments = payload.get("continuation_segments")
    if not isinstance(raw_segments, list):
        _fail("CONTINUATION_SEGMENTS_ARRAY_REQUIRED")
    if len(raw_segments) != REQUIRED_CONTINUATION_SEGMENTS:
        return _result("HOLD_SHADOW300_INCOMPLETE", base, [], None, policy, authority, ["CONTINUATION_SEGMENT_COUNT_NOT_5"])
    segments = [validate_segment(row, index) for index, row in enumerate(raw_segments)]
    segments.sort(key=lambda row: row["start_cycle"])
    expected = 201
    for row in segments:
        if row["start_cycle"] != expected:
            _fail("CONTINUATION_GAP_OR_OVERLAP", f"expected={expected},actual={row['start_cycle']}")
        expected = row["end_cycle"] + 1
    if expected != 301:
        _fail("CONTINUATION_RANGE_NOT_201_TO_300")
    for row in segments:
        if row["head_sha"] != segments[0]["head_sha"]:
            _fail("CONTINUATION_HEAD_SHA_MISMATCH")
        if row["selected_combination_sha"] != base["selected_combination_sha"]:
            _fail("CONTINUATION_COMBINATION_SHA_MISMATCH")
        if row["target_weights_sha"] != base["target_weights_sha"]:
            _fail("CONTINUATION_TARGET_WEIGHTS_SHA_MISMATCH")
        if row["shared_lineage"] != base["shared_lineage"]:
            _fail("CONTINUATION_LINEAGE_MISMATCH")
    review = validate_final_review(payload.get("final_review"))
    metrics = {
        "cycle_count": 200 + sum(row["cycle_count"] for row in segments),
        "total_net_r": round(base["metrics"]["total_net_r"] + sum(row["metrics"]["total_net_r"] for row in segments), 10),
        "total_cost_r": round(base["metrics"]["total_cost_r"] + sum(row["metrics"]["total_cost_r"] for row in segments), 10),
        "max_shadow_dd_pct": max([base["metrics"]["max_shadow_dd_pct"]] + [row["metrics"]["max_shadow_dd_pct"] for row in segments]),
        "max_cost_overrun_pct": max([base["metrics"]["max_cost_overrun_pct"]] + [row["metrics"]["max_cost_overrun_pct"] for row in segments]),
        "max_abs_weight_drift": max([base["metrics"]["max_abs_weight_drift"]] + [row["metrics"]["max_abs_weight_drift"] for row in segments]),
        "max_abs_rolling_correlation": max([base["metrics"]["max_abs_rolling_correlation"]] + [row["metrics"]["max_abs_rolling_correlation"] for row in segments]),
        "max_attribution_error_r": max([base["metrics"]["max_attribution_error_r"]] + [row["metrics"]["max_attribution_error_r"] for row in segments]),
        "stale_cycles": base["metrics"]["stale_cycles"] + sum(row["metrics"]["stale_cycles"] for row in segments),
        "source_parity_failures": base["metrics"]["source_parity_failures"] + sum(row["metrics"]["source_parity_failures"] for row in segments),
        "display_integrity_failures": base["metrics"]["display_integrity_failures"] + sum(row["metrics"]["display_integrity_failures"] for row in segments),
        "lineage_failures": base["metrics"]["lineage_failures"] + sum(row["metrics"]["lineage_failures"] for row in segments),
        "chaos_e2e_failures": base["metrics"]["chaos_e2e_failures"] + sum(row["metrics"]["chaos_e2e_failures"] for row in segments),
        "error_budget_ratio": review["error_budget_ratio"],
    }
    rollback = []
    hold = []
    if metrics["max_shadow_dd_pct"] > policy["max_shadow_dd_pct"]:
        rollback.append("SHADOW_DD_BREACH")
    if metrics["max_cost_overrun_pct"] > policy["max_cost_overrun_pct"]:
        rollback.append("COST_OVERRUN_BREACH")
    if metrics["max_abs_rolling_correlation"] > policy["max_abs_rolling_correlation"]:
        rollback.append("CORRELATION_BREACH")
    if metrics["error_budget_ratio"] > policy["max_error_budget_ratio"]:
        rollback.append("ERROR_BUDGET_BREACH")
    if metrics["total_net_r"] < policy["min_total_net_r"]:
        hold.append("TOTAL_NET_BELOW_FLOOR")
    for metric, limit, code in (
        ("max_abs_weight_drift", "max_abs_weight_drift", "WEIGHT_DRIFT_BREACH"),
        ("max_attribution_error_r", "max_attribution_error_r", "ATTRIBUTION_BREACH"),
        ("stale_cycles", "max_stale_cycles", "STALE_CYCLE_LIMIT"),
        ("source_parity_failures", "max_source_parity_failures", "SOURCE_PARITY_FAILURE_LIMIT"),
        ("display_integrity_failures", "max_display_integrity_failures", "DISPLAY_INTEGRITY_FAILURE_LIMIT"),
        ("lineage_failures", "max_lineage_failures", "LINEAGE_FAILURE_LIMIT"),
        ("chaos_e2e_failures", "max_chaos_e2e_failures", "CHAOS_E2E_FAILURE_LIMIT"),
    ):
        if metrics[metric] > policy[limit]:
            hold.append(code)
    state = "ROLLBACK_SHADOW300_READ_ONLY" if rollback else "HOLD_SHADOW300_READ_ONLY" if hold else "PASS_SHADOW300_READ_ONLY_COMPLETION"
    return _result(state, base, segments, review, policy, authority, rollback + hold, metrics)


def _result(state: str, base: dict[str, Any], segments: list[dict[str, Any]], review: dict[str, Any] | None,
            policy: dict[str, Any], authority: dict[str, Any], blockers: list[str], metrics: dict[str, Any] | None = None) -> dict[str, Any]:
    result = {
        "schema_version": OUTPUT_SCHEMA,
        "state": state,
        "base_200_accumulator_sha": base["accumulator_sha"],
        "continuation_segment_count": len(segments),
        "cycle_count": 200 + sum(row.get("cycle_count", 0) for row in segments),
        "continuation_lineage": [
            {key: row[key] for key in ("segment_id", "run_id", "head_sha", "artifact_sha", "payload_sha", "start_cycle", "end_cycle")}
            for row in segments
        ],
        "shared_lineage": copy.deepcopy(base["shared_lineage"]),
        "selected_combination_sha": base["selected_combination_sha"],
        "target_weights_sha": base["target_weights_sha"],
        "metrics": metrics or {},
        "final_review": review,
        "policy": policy,
        "policy_sha": canonical_sha(policy),
        "blocker_codes": sorted(set(blockers)),
        "ml_light_observer_gate_allowed": state == "PASS_SHADOW300_READ_ONLY_COMPLETION",
        "failure_learning_observer_gate_allowed": state == "PASS_SHADOW300_READ_ONLY_COMPLETION",
        "paper_30d_allowed": False,
        "automatic_shadow_start": False,
        "real_shadow_started": False,
        "runtime_bound": False,
        "requested_action": "rollback" if state.startswith("ROLLBACK_") else "hold",
        "rollback_target": "VERIFIED_SHADOW200_BASE" if state.startswith("ROLLBACK_") else None,
        "production_threshold_authority": False,
        **authority,
    }
    result["completion_sha"] = canonical_sha(result)
    return result
