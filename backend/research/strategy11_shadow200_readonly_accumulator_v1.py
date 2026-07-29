from __future__ import annotations

import copy
import math
from typing import Any, Mapping

from backend.contracts.strategy11_source_binding_contract_v1 import SAFETY, canonical_sha

INPUT_SCHEMA = "strategy11.shadow200_readonly_accumulator.input.v1"
OUTPUT_SCHEMA = "strategy11.shadow200_readonly_accumulator.output.v1"
REQUIRED_SEGMENTS = 10
REQUIRED_CYCLES = 200
MIDCHECKS = (
    "source_parity_pass",
    "a_c_mirroring_pass",
    "policy_abcd_shadow_pass",
    "bad_context_filter_pass",
    "cooldown_pass",
    "pre_entry_lineage_pass",
    "mfe_mae_complete",
    "fee_slippage_latency_complete",
    "dd_exposure_pass",
    "symbol_regime_side_complete",
    "display_integrity_pass",
    "chaos_e2e_pass",
)


class Shadow200AccumulatorError(ValueError):
    pass


def _fail(code: str, detail: str = "") -> None:
    raise Shadow200AccumulatorError(f"{code}:{detail}" if detail else code)


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


def validate_policy(value: Any) -> dict[str, Any]:
    policy = _mapping(value, "policy")
    required = {
        "policy_id", "required_segment_count", "required_cycle_count",
        "max_shadow_dd_pct", "max_cost_overrun_pct", "max_abs_weight_drift",
        "max_abs_rolling_correlation", "max_attribution_error_r",
        "min_total_net_r", "max_stale_cycles", "max_source_parity_failures",
        "max_display_integrity_failures", "max_lineage_failures",
        "max_chaos_e2e_failures",
    }
    missing = sorted(required - set(policy))
    if missing:
        _fail("POLICY_FIELDS_MISSING", ",".join(missing))
    normalized = {
        "policy_id": _string(policy["policy_id"], "policy.policy_id"),
        "required_segment_count": _integer(policy["required_segment_count"], "policy.required_segment_count", 1),
        "required_cycle_count": _integer(policy["required_cycle_count"], "policy.required_cycle_count", 1),
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
    }
    if normalized["required_segment_count"] != REQUIRED_SEGMENTS:
        _fail("SEGMENT_COUNT_POLICY_MUST_EQUAL_10")
    if normalized["required_cycle_count"] != REQUIRED_CYCLES:
        _fail("CYCLE_COUNT_POLICY_MUST_EQUAL_200")
    return normalized


def validate_segment(value: Any, index: int) -> dict[str, Any]:
    segment = _mapping(value, f"segments[{index}]")
    required = {
        "segment_id", "start_cycle", "end_cycle", "cycle_count", "run_id",
        "head_sha", "artifact_sha", "payload", "payload_sha",
    }
    missing = sorted(required - set(segment))
    extra = sorted(set(segment) - required)
    if missing:
        _fail("SEGMENT_FIELDS_MISSING", f"{index}:{','.join(missing)}")
    if extra:
        _fail("SEGMENT_EXTRA_FIELDS", f"{index}:{','.join(extra)}")
    payload = _mapping(segment["payload"], f"segments[{index}].payload")
    supplied_payload_sha = _sha(segment["payload_sha"], f"segments[{index}].payload_sha")
    if supplied_payload_sha != canonical_sha(payload):
        _fail("SEGMENT_PAYLOAD_SHA_MISMATCH", str(index))
    if payload.get("state") != "PASS_SHADOW20_READ_ONLY_CANARY":
        _fail("SEGMENT_NOT_SHADOW20_PASS", str(index))
    for key, expected in SAFETY.items():
        if payload.get(key) != expected:
            _fail("SEGMENT_SAFETY_MISMATCH", f"{index}:{key}")
    if payload.get("runtime_bound") is not False or payload.get("real_shadow_started") is not False:
        _fail("SEGMENT_RUNTIME_OR_REAL_SHADOW_FORBIDDEN", str(index))
    if payload.get("shadow_200c_allowed") is not True:
        _fail("SEGMENT_200C_NOT_ALLOWED", str(index))
    start_cycle = _integer(segment["start_cycle"], f"segments[{index}].start_cycle", 1)
    end_cycle = _integer(segment["end_cycle"], f"segments[{index}].end_cycle", start_cycle)
    cycle_count = _integer(segment["cycle_count"], f"segments[{index}].cycle_count", 1)
    if cycle_count != 20 or end_cycle - start_cycle + 1 != cycle_count:
        _fail("SEGMENT_RANGE_COUNT_MISMATCH", str(index))
    metrics = _mapping(payload.get("metrics"), f"segments[{index}].payload.metrics")
    lineage = _mapping(payload.get("shared_lineage"), f"segments[{index}].payload.shared_lineage")
    return {
        "segment_id": _string(segment["segment_id"], f"segments[{index}].segment_id"),
        "start_cycle": start_cycle,
        "end_cycle": end_cycle,
        "cycle_count": cycle_count,
        "run_id": _string(segment["run_id"], f"segments[{index}].run_id"),
        "head_sha": _sha(segment["head_sha"], f"segments[{index}].head_sha"),
        "artifact_sha": _sha(segment["artifact_sha"], f"segments[{index}].artifact_sha"),
        "payload_sha": supplied_payload_sha,
        "selected_combination_sha": _sha(payload.get("selected_combination_sha"), f"segments[{index}].selected_combination_sha"),
        "target_weights_sha": _sha(payload.get("target_weights_sha"), f"segments[{index}].target_weights_sha"),
        "shared_lineage": {
            "source_w1_manifest_sha": _sha(lineage.get("source_w1_manifest_sha"), f"segments[{index}].source_w1_manifest_sha"),
            "data_sha": _sha(lineage.get("data_sha"), f"segments[{index}].data_sha"),
            "window_sha": _sha(lineage.get("window_sha"), f"segments[{index}].window_sha"),
            "evidence_manifest_sha": _sha(lineage.get("evidence_manifest_sha"), f"segments[{index}].evidence_manifest_sha"),
        },
        "metrics": {
            "total_net_r": _number(metrics.get("total_net_r"), f"segments[{index}].metrics.total_net_r"),
            "total_cost_r": _number(metrics.get("total_cost_r"), f"segments[{index}].metrics.total_cost_r"),
            "max_shadow_dd_pct": _number(metrics.get("max_shadow_dd_pct"), f"segments[{index}].metrics.max_shadow_dd_pct", 0.0),
            "max_cost_overrun_pct": _number(metrics.get("max_cost_overrun_pct"), f"segments[{index}].metrics.max_cost_overrun_pct", 0.0),
            "max_abs_weight_drift": _number(metrics.get("max_abs_weight_drift"), f"segments[{index}].metrics.max_abs_weight_drift", 0.0),
            "max_abs_rolling_correlation": _number(metrics.get("max_abs_rolling_correlation"), f"segments[{index}].metrics.max_abs_rolling_correlation", 0.0),
            "max_attribution_error_r": _number(metrics.get("max_attribution_error_r"), f"segments[{index}].metrics.max_attribution_error_r", 0.0),
            "stale_cycles": _integer(metrics.get("stale_cycles"), f"segments[{index}].metrics.stale_cycles", 0),
            "source_parity_failures": _integer(metrics.get("source_parity_failures"), f"segments[{index}].metrics.source_parity_failures", 0),
            "display_integrity_failures": _integer(metrics.get("display_integrity_failures"), f"segments[{index}].metrics.display_integrity_failures", 0),
            "lineage_failures": _integer(metrics.get("lineage_failures"), f"segments[{index}].metrics.lineage_failures", 0),
            "chaos_e2e_failures": _integer(metrics.get("chaos_e2e_failures"), f"segments[{index}].metrics.chaos_e2e_failures", 0),
        },
    }


def validate_midcheck(value: Any) -> dict[str, Any]:
    midcheck = _mapping(value, "midcheck")
    for key in MIDCHECKS:
        if midcheck.get(key) is not True:
            _fail("MIDCHECK_NOT_PASS", key)
    policies = _mapping(midcheck.get("policy_abcd_results"), "midcheck.policy_abcd_results")
    if set(policies) != {"A", "B", "C", "D"} or any(value != "PASS" for value in policies.values()):
        _fail("POLICY_ABCD_RESULTS_INVALID")
    required_metrics = {
        "mfe_sample_count", "mae_sample_count", "fee_sample_count", "slippage_sample_count",
        "latency_sample_count", "symbol_count", "regime_count", "side_count",
    }
    metrics = _mapping(midcheck.get("coverage_metrics"), "midcheck.coverage_metrics")
    missing = sorted(required_metrics - set(metrics))
    if missing:
        _fail("MIDCHECK_COVERAGE_FIELDS_MISSING", ",".join(missing))
    normalized_metrics = {key: _integer(metrics[key], f"midcheck.coverage_metrics.{key}", 1) for key in required_metrics}
    return {
        **{key: True for key in MIDCHECKS},
        "policy_abcd_results": copy.deepcopy(policies),
        "coverage_metrics": normalized_metrics,
        "midcheck_sha": canonical_sha({
            **{key: True for key in MIDCHECKS},
            "policy_abcd_results": policies,
            "coverage_metrics": normalized_metrics,
        }),
    }


def accumulate(value: Mapping[str, Any]) -> dict[str, Any]:
    payload = _mapping(value, "input")
    if payload.get("schema_version") != INPUT_SCHEMA:
        _fail("INPUT_SCHEMA_MISMATCH")
    authority = _authority(payload.get("authority"))
    policy = validate_policy(payload.get("policy"))
    segments_raw = payload.get("segments")
    if not isinstance(segments_raw, list):
        _fail("SEGMENTS_ARRAY_REQUIRED")
    if len(segments_raw) != REQUIRED_SEGMENTS:
        return _result("HOLD_SHADOW200_INCOMPLETE", [], policy, None, authority, ["SEGMENT_COUNT_NOT_10"])
    segments = [validate_segment(row, index) for index, row in enumerate(segments_raw)]
    segments.sort(key=lambda row: row["start_cycle"])
    if len({row["segment_id"] for row in segments}) != len(segments):
        _fail("DUPLICATE_SEGMENT_ID")
    expected_start = 1
    for row in segments:
        if row["start_cycle"] != expected_start:
            _fail("SEGMENT_GAP_OR_OVERLAP", f"expected={expected_start},actual={row['start_cycle']}")
        expected_start = row["end_cycle"] + 1
    if expected_start != REQUIRED_CYCLES + 1:
        _fail("CYCLE_RANGE_NOT_1_TO_200")
    for field in ("head_sha", "selected_combination_sha", "target_weights_sha"):
        if len({row[field] for row in segments}) != 1:
            _fail("SEGMENT_SHARED_FIELD_MISMATCH", field)
    for field in ("source_w1_manifest_sha", "data_sha", "window_sha", "evidence_manifest_sha"):
        if len({row["shared_lineage"][field] for row in segments}) != 1:
            _fail("SEGMENT_LINEAGE_MISMATCH", field)
    midcheck = validate_midcheck(payload.get("midcheck"))
    metrics = {
        "segment_count": len(segments),
        "cycle_count": sum(row["cycle_count"] for row in segments),
        "total_net_r": round(sum(row["metrics"]["total_net_r"] for row in segments), 10),
        "total_cost_r": round(sum(row["metrics"]["total_cost_r"] for row in segments), 10),
        "max_shadow_dd_pct": max(row["metrics"]["max_shadow_dd_pct"] for row in segments),
        "max_cost_overrun_pct": max(row["metrics"]["max_cost_overrun_pct"] for row in segments),
        "max_abs_weight_drift": max(row["metrics"]["max_abs_weight_drift"] for row in segments),
        "max_abs_rolling_correlation": max(row["metrics"]["max_abs_rolling_correlation"] for row in segments),
        "max_attribution_error_r": max(row["metrics"]["max_attribution_error_r"] for row in segments),
        "stale_cycles": sum(row["metrics"]["stale_cycles"] for row in segments),
        "source_parity_failures": sum(row["metrics"]["source_parity_failures"] for row in segments),
        "display_integrity_failures": sum(row["metrics"]["display_integrity_failures"] for row in segments),
        "lineage_failures": sum(row["metrics"]["lineage_failures"] for row in segments),
        "chaos_e2e_failures": sum(row["metrics"]["chaos_e2e_failures"] for row in segments),
    }
    rollback = []
    hold = []
    if metrics["max_shadow_dd_pct"] > policy["max_shadow_dd_pct"]:
        rollback.append("SHADOW_DD_BREACH")
    if metrics["max_cost_overrun_pct"] > policy["max_cost_overrun_pct"]:
        rollback.append("COST_OVERRUN_BREACH")
    if metrics["max_abs_rolling_correlation"] > policy["max_abs_rolling_correlation"]:
        rollback.append("CORRELATION_BREACH")
    if metrics["total_net_r"] < policy["min_total_net_r"]:
        hold.append("TOTAL_NET_BELOW_FLOOR")
    limits = {
        "max_abs_weight_drift": "WEIGHT_DRIFT_BREACH",
        "max_attribution_error_r": "ATTRIBUTION_RECONCILIATION_BREACH",
        "stale_cycles": "STALE_CYCLE_LIMIT",
        "source_parity_failures": "SOURCE_PARITY_FAILURE_LIMIT",
        "display_integrity_failures": "DISPLAY_INTEGRITY_FAILURE_LIMIT",
        "lineage_failures": "LINEAGE_FAILURE_LIMIT",
        "chaos_e2e_failures": "CHAOS_E2E_FAILURE_LIMIT",
    }
    policy_key = {
        "max_abs_weight_drift": "max_abs_weight_drift",
        "max_attribution_error_r": "max_attribution_error_r",
        "stale_cycles": "max_stale_cycles",
        "source_parity_failures": "max_source_parity_failures",
        "display_integrity_failures": "max_display_integrity_failures",
        "lineage_failures": "max_lineage_failures",
        "chaos_e2e_failures": "max_chaos_e2e_failures",
    }
    for metric, code in limits.items():
        if metrics[metric] > policy[policy_key[metric]]:
            hold.append(code)
    state = "ROLLBACK_SHADOW200_READ_ONLY" if rollback else "HOLD_SHADOW200_READ_ONLY" if hold else "PASS_SHADOW200_READ_ONLY_ACCUMULATION"
    return _result(state, segments, policy, midcheck, authority, rollback + hold, metrics)


def _result(
    state: str,
    segments: list[dict[str, Any]],
    policy: dict[str, Any],
    midcheck: dict[str, Any] | None,
    authority: dict[str, Any],
    blockers: list[str],
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = {
        "schema_version": OUTPUT_SCHEMA,
        "state": state,
        "segment_count": len(segments),
        "cycle_count": sum(row.get("cycle_count", 0) for row in segments),
        "segment_lineage": [
            {key: row[key] for key in ("segment_id", "run_id", "head_sha", "artifact_sha", "payload_sha", "start_cycle", "end_cycle")}
            for row in segments
        ],
        "shared_lineage": copy.deepcopy(segments[0]["shared_lineage"]) if segments else None,
        "selected_combination_sha": segments[0]["selected_combination_sha"] if segments else None,
        "target_weights_sha": segments[0]["target_weights_sha"] if segments else None,
        "metrics": metrics or {},
        "midcheck": midcheck,
        "policy": policy,
        "policy_sha": canonical_sha(policy),
        "blocker_codes": sorted(set(blockers)),
        "shadow_300c_allowed": state == "PASS_SHADOW200_READ_ONLY_ACCUMULATION",
        "automatic_shadow_start": False,
        "real_shadow_started": False,
        "fixture_only": bool(policy.get("policy_id", "").startswith("FIXTURE_")),
        "production_threshold_authority": False,
        "runtime_bound": False,
        "requested_action": "rollback" if state.startswith("ROLLBACK_") else "hold",
        "rollback_target": "PREVIOUS_VERIFIED_SHADOW20_CHAIN" if state.startswith("ROLLBACK_") else None,
        **authority,
    }
    result["accumulator_sha"] = canonical_sha(result)
    return result
