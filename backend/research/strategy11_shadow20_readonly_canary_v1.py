from __future__ import annotations

import copy
import math
from datetime import datetime
from typing import Any, Mapping

from backend.contracts.strategy11_source_binding_contract_v1 import (
    SAFETY,
    SourceBindingError,
    canonical_sha,
    validate_authority,
    validate_source,
)

INPUT_SCHEMA = "strategy11.shadow20_readonly_canary.input.v1"
OUTPUT_SCHEMA = "strategy11.shadow20_readonly_canary.output.v1"
CYCLE_SOURCE_KIND = "SHADOW_READ_ONLY_CYCLE_LEDGER"
POLICY_SOURCE_KINDS = {"SHADOW_CANARY_POLICY_SSOT", "FIXTURE_POLICY"}


class Shadow20CanaryError(ValueError):
    pass


def _fail(code: str, detail: str = "") -> None:
    raise Shadow20CanaryError(f"{code}:{detail}" if detail else code)


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


def _bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        _fail("BOOL_REQUIRED", name)
    return value


def _number(value: Any, name: str, minimum: float | None = None, maximum: float | None = None) -> float:
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


def _integer(value: Any, name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        _fail("INT_REQUIRED", name)
    if value < minimum:
        _fail("INT_BELOW_MIN", name)
    return value


def _timestamp(value: Any, name: str) -> datetime:
    text = _string(value, name)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise Shadow20CanaryError(f"TIMESTAMP_INVALID:{name}") from exc
    if parsed.tzinfo is None:
        _fail("TIMESTAMP_TIMEZONE_REQUIRED", name)
    return parsed


def _authority(value: Any) -> dict[str, Any]:
    try:
        return validate_authority(value)
    except SourceBindingError as exc:
        raise Shadow20CanaryError(str(exc)) from exc


def _source(source_id: str, value: Any) -> dict[str, Any]:
    try:
        return validate_source(source_id, value)
    except SourceBindingError as exc:
        raise Shadow20CanaryError(str(exc)) from exc


def validate_policy(value: Mapping[str, Any]) -> dict[str, Any]:
    policy = _mapping(value, "policy")
    required = {
        "policy_id",
        "required_cycle_count",
        "max_cycle_gap_minutes",
        "max_shadow_dd_pct",
        "max_cost_overrun_pct",
        "max_abs_weight_drift",
        "max_abs_rolling_correlation",
        "max_attribution_error_r",
        "min_worst_cycle_net_r",
        "max_consecutive_negative_cycles",
        "max_stale_cycles",
        "max_source_parity_failures",
        "max_display_integrity_failures",
        "max_duplicate_cycle_ids",
    }
    missing = sorted(required - set(policy))
    if missing:
        _fail("POLICY_FIELDS_MISSING", ",".join(missing))
    normalized = {
        "policy_id": _string(policy["policy_id"], "policy.policy_id"),
        "required_cycle_count": _integer(policy["required_cycle_count"], "policy.required_cycle_count", 1),
        "max_cycle_gap_minutes": _number(policy["max_cycle_gap_minutes"], "policy.max_cycle_gap_minutes", 0.0),
        "max_shadow_dd_pct": _number(policy["max_shadow_dd_pct"], "policy.max_shadow_dd_pct", 0.0),
        "max_cost_overrun_pct": _number(policy["max_cost_overrun_pct"], "policy.max_cost_overrun_pct", 0.0),
        "max_abs_weight_drift": _number(policy["max_abs_weight_drift"], "policy.max_abs_weight_drift", 0.0, 1.0),
        "max_abs_rolling_correlation": _number(policy["max_abs_rolling_correlation"], "policy.max_abs_rolling_correlation", 0.0, 1.0),
        "max_attribution_error_r": _number(policy["max_attribution_error_r"], "policy.max_attribution_error_r", 0.0),
        "min_worst_cycle_net_r": _number(policy["min_worst_cycle_net_r"], "policy.min_worst_cycle_net_r", maximum=0.0),
        "max_consecutive_negative_cycles": _integer(policy["max_consecutive_negative_cycles"], "policy.max_consecutive_negative_cycles", 1),
        "max_stale_cycles": _integer(policy["max_stale_cycles"], "policy.max_stale_cycles", 0),
        "max_source_parity_failures": _integer(policy["max_source_parity_failures"], "policy.max_source_parity_failures", 0),
        "max_display_integrity_failures": _integer(policy["max_display_integrity_failures"], "policy.max_display_integrity_failures", 0),
        "max_duplicate_cycle_ids": _integer(policy["max_duplicate_cycle_ids"], "policy.max_duplicate_cycle_ids", 0),
    }
    if normalized["required_cycle_count"] != 20:
        _fail("SHADOW20_POLICY_COUNT_MUST_EQUAL_20")
    return normalized


def validate_preflight(value: Mapping[str, Any]) -> dict[str, Any]:
    preflight = _mapping(value, "preflight")
    for key, expected in SAFETY.items():
        if preflight.get(key) != expected:
            _fail("PREFLIGHT_SAFETY_MISMATCH", key)
    if preflight.get("runtime_bound") is not False:
        _fail("PREFLIGHT_RUNTIME_BOUND")
    if preflight.get("state") != "PASS_SOURCE_BOUND_MULTICANDIDATE_PREFLIGHT":
        _fail("PREFLIGHT_NOT_PASS", str(preflight.get("state")))
    if preflight.get("shadow_20c_ready") is not True:
        _fail("PREFLIGHT_SHADOW20_NOT_READY")
    if preflight.get("automatic_shadow_start") is not False:
        _fail("AUTOMATIC_SHADOW_START_FORBIDDEN")
    supplied_sha = _sha(preflight.get("orchestrator_sha"), "preflight.orchestrator_sha")
    computed_sha = canonical_sha({key: child for key, child in preflight.items() if key != "orchestrator_sha"})
    if supplied_sha != computed_sha:
        _fail("PREFLIGHT_SHA_MISMATCH")
    selected = preflight.get("selected_combination")
    if not isinstance(selected, list) or not 2 <= len(selected) <= 3:
        _fail("PREFLIGHT_COMBINATION_COUNT_INVALID")
    selected_ids = [_string(item, "preflight.selected_combination[]") for item in selected]
    if len(set(selected_ids)) != len(selected_ids):
        _fail("PREFLIGHT_DUPLICATE_STRATEGY")
    weights = preflight.get("target_risk_weights")
    if not isinstance(weights, Mapping) or len(weights) != len(selected_ids):
        _fail("PREFLIGHT_TARGET_WEIGHTS_INVALID")
    normalized_weights = {
        _string(key, "preflight.target_risk_weights.key"): _number(value, f"preflight.target_risk_weights.{key}", 0.0, 1.0)
        for key, value in weights.items()
    }
    if abs(sum(normalized_weights.values()) - 1.0) > 1e-9:
        _fail("PREFLIGHT_TARGET_WEIGHTS_NOT_ONE")
    lineage = _mapping(preflight.get("shared_lineage"), "preflight.shared_lineage")
    normalized_lineage = {
        "source_w1_run_id": _string(lineage.get("source_w1_run_id"), "preflight.shared_lineage.source_w1_run_id"),
        "source_w1_manifest_sha": _sha(lineage.get("source_w1_manifest_sha"), "preflight.shared_lineage.source_w1_manifest_sha"),
        "data_sha": _sha(lineage.get("data_sha"), "preflight.shared_lineage.data_sha"),
        "window_sha": _sha(lineage.get("window_sha"), "preflight.shared_lineage.window_sha"),
        "evidence_manifest_sha": _sha(lineage.get("evidence_manifest_sha"), "preflight.shared_lineage.evidence_manifest_sha"),
    }
    return {
        "orchestrator_sha": supplied_sha,
        "selected_combination": selected_ids,
        "selected_combination_sha": _sha(preflight.get("selected_combination_sha"), "preflight.selected_combination_sha"),
        "target_risk_weights": normalized_weights,
        "shared_lineage": normalized_lineage,
        "stage_shas": copy.deepcopy(_mapping(preflight.get("stage_shas"), "preflight.stage_shas")),
    }


def validate_cycle(
    value: Mapping[str, Any],
    index: int,
    preflight: Mapping[str, Any],
) -> dict[str, Any]:
    cycle = _mapping(value, f"cycles[{index}]")
    required = {
        "cycle_id",
        "event_ts",
        "source_w1_manifest_sha",
        "data_sha",
        "window_sha",
        "evidence_manifest_sha",
        "selected_combination_sha",
        "target_weights",
        "observed_weights",
        "material_net_pnl_r",
        "gross_pnl_r",
        "fee_r",
        "slippage_r",
        "funding_r",
        "net_pnl_r",
        "cumulative_dd_pct",
        "cost_overrun_pct",
        "rolling_correlation",
        "source_parity_pass",
        "display_integrity_pass",
        "stale",
        "protected_mutations",
        "execution_allowed",
        "order_authority",
        "cycle_sha",
    }
    missing = sorted(required - set(cycle))
    extra = sorted(set(cycle) - required)
    if missing:
        _fail("CYCLE_FIELDS_MISSING", f"{index}:{','.join(missing)}")
    if extra:
        _fail("CYCLE_EXTRA_FIELDS", f"{index}:{','.join(extra)}")
    supplied_cycle_sha = _sha(cycle["cycle_sha"], f"cycles[{index}].cycle_sha")
    computed_cycle_sha = canonical_sha({key: child for key, child in cycle.items() if key != "cycle_sha"})
    if supplied_cycle_sha != computed_cycle_sha:
        _fail("CYCLE_SHA_MISMATCH", str(index))
    if _sha(cycle["source_w1_manifest_sha"], f"cycles[{index}].source_w1_manifest_sha") != preflight["shared_lineage"]["source_w1_manifest_sha"]:
        _fail("CYCLE_W1_MANIFEST_SHA_MISMATCH", str(index))
    if _sha(cycle["data_sha"], f"cycles[{index}].data_sha") != preflight["shared_lineage"]["data_sha"]:
        _fail("CYCLE_DATA_SHA_MISMATCH", str(index))
    if _sha(cycle["window_sha"], f"cycles[{index}].window_sha") != preflight["shared_lineage"]["window_sha"]:
        _fail("CYCLE_WINDOW_SHA_MISMATCH", str(index))
    if _sha(cycle["evidence_manifest_sha"], f"cycles[{index}].evidence_manifest_sha") != preflight["shared_lineage"]["evidence_manifest_sha"]:
        _fail("CYCLE_EVIDENCE_MANIFEST_SHA_MISMATCH", str(index))
    if _sha(cycle["selected_combination_sha"], f"cycles[{index}].selected_combination_sha") != preflight["selected_combination_sha"]:
        _fail("CYCLE_COMBINATION_SHA_MISMATCH", str(index))
    if cycle["protected_mutations"] != 0:
        _fail("CYCLE_PROTECTED_MUTATION", str(index))
    if cycle["execution_allowed"] is not False:
        _fail("CYCLE_EXECUTION_FORBIDDEN", str(index))
    if cycle["order_authority"] != "BLOCKED":
        _fail("CYCLE_ORDER_AUTHORITY_NOT_BLOCKED", str(index))

    target = cycle["target_weights"]
    observed = cycle["observed_weights"]
    material_pnl = cycle["material_net_pnl_r"]
    if not isinstance(target, Mapping) or not isinstance(observed, Mapping) or not isinstance(material_pnl, Mapping):
        _fail("CYCLE_WEIGHT_OR_ATTRIBUTION_OBJECT_REQUIRED", str(index))
    target_weights = {str(key): _number(value, f"cycles[{index}].target_weights.{key}", 0.0, 1.0) for key, value in target.items()}
    observed_weights = {str(key): _number(value, f"cycles[{index}].observed_weights.{key}", 0.0, 1.0) for key, value in observed.items()}
    material_values = {str(key): _number(value, f"cycles[{index}].material_net_pnl_r.{key}") for key, value in material_pnl.items()}
    expected_keys = set(preflight["target_risk_weights"])
    if set(target_weights) != expected_keys or set(observed_weights) != expected_keys or set(material_values) != expected_keys:
        _fail("CYCLE_MATERIAL_KEY_MISMATCH", str(index))
    for key, expected in preflight["target_risk_weights"].items():
        if abs(target_weights[key] - expected) > 1e-9:
            _fail("CYCLE_TARGET_WEIGHT_MISMATCH", f"{index}:{key}")
    if abs(sum(observed_weights.values()) - 1.0) > 1e-9:
        _fail("CYCLE_OBSERVED_WEIGHTS_NOT_ONE", str(index))

    gross = _number(cycle["gross_pnl_r"], f"cycles[{index}].gross_pnl_r")
    fee = _number(cycle["fee_r"], f"cycles[{index}].fee_r", 0.0)
    slippage = _number(cycle["slippage_r"], f"cycles[{index}].slippage_r", 0.0)
    funding = _number(cycle["funding_r"], f"cycles[{index}].funding_r")
    net = _number(cycle["net_pnl_r"], f"cycles[{index}].net_pnl_r")
    expected_net = gross - fee - slippage - funding
    if abs(net - expected_net) > 1e-9:
        _fail("CYCLE_NET_PNL_RECONCILIATION_FAIL", str(index))
    attribution_error = abs(sum(material_values.values()) - net)

    return {
        "cycle_id": _string(cycle["cycle_id"], f"cycles[{index}].cycle_id"),
        "event_ts": _timestamp(cycle["event_ts"], f"cycles[{index}].event_ts"),
        "event_ts_text": cycle["event_ts"],
        "target_weights": target_weights,
        "observed_weights": observed_weights,
        "material_net_pnl_r": material_values,
        "gross_pnl_r": gross,
        "fee_r": fee,
        "slippage_r": slippage,
        "funding_r": funding,
        "net_pnl_r": net,
        "cumulative_dd_pct": _number(cycle["cumulative_dd_pct"], f"cycles[{index}].cumulative_dd_pct", 0.0),
        "cost_overrun_pct": _number(cycle["cost_overrun_pct"], f"cycles[{index}].cost_overrun_pct", 0.0),
        "rolling_correlation": _number(cycle["rolling_correlation"], f"cycles[{index}].rolling_correlation", -1.0, 1.0),
        "source_parity_pass": _bool(cycle["source_parity_pass"], f"cycles[{index}].source_parity_pass"),
        "display_integrity_pass": _bool(cycle["display_integrity_pass"], f"cycles[{index}].display_integrity_pass"),
        "stale": _bool(cycle["stale"], f"cycles[{index}].stale"),
        "weight_drift": max(abs(observed_weights[key] - target_weights[key]) for key in expected_keys),
        "attribution_error_r": attribution_error,
        "cycle_sha": supplied_cycle_sha,
    }


def evaluate(value: Mapping[str, Any]) -> dict[str, Any]:
    payload = _mapping(value, "shadow20_input")
    allowed = {"schema_version", "preflight", "cycle_source", "policy_source", "authority"}
    missing = sorted(allowed - set(payload))
    extra = sorted(set(payload) - allowed)
    if missing:
        _fail("INPUT_FIELDS_MISSING", ",".join(missing))
    if extra:
        _fail("INPUT_EXTRA_FIELDS", ",".join(extra))
    if payload.get("schema_version") != INPUT_SCHEMA:
        _fail("INPUT_SCHEMA_MISMATCH")
    _authority(payload.get("authority"))
    preflight = validate_preflight(payload.get("preflight"))
    cycle_source = _source("cycle_source", payload.get("cycle_source"))
    if cycle_source["source_kind"] != CYCLE_SOURCE_KIND:
        _fail("CYCLE_SOURCE_KIND_INVALID")
    policy_source = _source("policy_source", payload.get("policy_source"))
    if policy_source["source_kind"] not in POLICY_SOURCE_KINDS:
        _fail("POLICY_SOURCE_KIND_INVALID")
    policy = validate_policy(_mapping(policy_source["document"], "policy_source.document"))
    cycle_document = _mapping(cycle_source["document"], "cycle_source.document")
    cycles_value = cycle_document.get("cycles")
    if not isinstance(cycles_value, list):
        _fail("CYCLES_REQUIRED")
    cycles = [validate_cycle(cycle, index, preflight) for index, cycle in enumerate(cycles_value)]

    cycle_ids = [cycle["cycle_id"] for cycle in cycles]
    duplicate_count = len(cycle_ids) - len(set(cycle_ids))
    ordered = sorted(cycles, key=lambda row: row["event_ts"])
    if ordered != cycles:
        _fail("CYCLE_TIMESTAMP_ORDER_INVALID")
    gaps = [
        (cycles[index]["event_ts"] - cycles[index - 1]["event_ts"]).total_seconds() / 60.0
        for index in range(1, len(cycles))
    ]
    max_gap = max(gaps, default=0.0)

    stale_count = sum(cycle["stale"] for cycle in cycles)
    source_parity_failures = sum(not cycle["source_parity_pass"] for cycle in cycles)
    display_integrity_failures = sum(not cycle["display_integrity_pass"] for cycle in cycles)
    max_dd = max((cycle["cumulative_dd_pct"] for cycle in cycles), default=0.0)
    max_cost_overrun = max((cycle["cost_overrun_pct"] for cycle in cycles), default=0.0)
    max_correlation = max((abs(cycle["rolling_correlation"]) for cycle in cycles), default=0.0)
    max_weight_drift = max((cycle["weight_drift"] for cycle in cycles), default=0.0)
    max_attribution_error = max((cycle["attribution_error_r"] for cycle in cycles), default=0.0)
    worst_cycle = min((cycle["net_pnl_r"] for cycle in cycles), default=0.0)
    total_net = sum(cycle["net_pnl_r"] for cycle in cycles)
    total_cost = sum(cycle["fee_r"] + cycle["slippage_r"] + cycle["funding_r"] for cycle in cycles)
    consecutive_negative = 0
    max_consecutive_negative = 0
    for cycle in cycles:
        if cycle["net_pnl_r"] < 0.0:
            consecutive_negative += 1
            max_consecutive_negative = max(max_consecutive_negative, consecutive_negative)
        else:
            consecutive_negative = 0

    hold_reasons: list[str] = []
    rollback_reasons: list[str] = []
    if len(cycles) != policy["required_cycle_count"]:
        hold_reasons.append("CYCLE_COUNT_INCOMPLETE")
    if duplicate_count > policy["max_duplicate_cycle_ids"]:
        hold_reasons.append("DUPLICATE_CYCLE_ID")
    if max_gap > policy["max_cycle_gap_minutes"]:
        hold_reasons.append("CYCLE_GAP_EXCEEDED")
    if stale_count > policy["max_stale_cycles"]:
        hold_reasons.append("STALE_CYCLE")
    if source_parity_failures > policy["max_source_parity_failures"]:
        hold_reasons.append("SOURCE_PARITY_FAILURE")
    if display_integrity_failures > policy["max_display_integrity_failures"]:
        hold_reasons.append("DISPLAY_INTEGRITY_FAILURE")
    if max_weight_drift > policy["max_abs_weight_drift"]:
        hold_reasons.append("WEIGHT_DRIFT")
    if max_attribution_error > policy["max_attribution_error_r"]:
        hold_reasons.append("ATTRIBUTION_RECONCILIATION")
    if max_dd > policy["max_shadow_dd_pct"]:
        rollback_reasons.append("SHADOW_DD_BREACH")
    if max_cost_overrun > policy["max_cost_overrun_pct"]:
        rollback_reasons.append("COST_OVERRUN")
    if max_correlation > policy["max_abs_rolling_correlation"]:
        rollback_reasons.append("CORRELATION_BREACH")
    if worst_cycle < policy["min_worst_cycle_net_r"]:
        rollback_reasons.append("WORST_CYCLE_LOSS_BREACH")
    if max_consecutive_negative > policy["max_consecutive_negative_cycles"]:
        rollback_reasons.append("CONSECUTIVE_NEGATIVE_CYCLES")

    if rollback_reasons:
        state = "ROLLBACK_SHADOW20_READ_ONLY_CANARY"
        requested_action = "rollback"
        shadow_200c_allowed = False
    elif hold_reasons:
        state = "HOLD_SHADOW20_READ_ONLY_CANARY"
        requested_action = "hold"
        shadow_200c_allowed = False
    else:
        state = "PASS_SHADOW20_READ_ONLY_CANARY"
        requested_action = "hold"
        shadow_200c_allowed = True

    result = {
        "schema_version": OUTPUT_SCHEMA,
        "state": state,
        "requested_action": requested_action,
        "reason_codes": sorted(set(rollback_reasons + hold_reasons)) or ["ALL_SHADOW20_GATES_PASS"],
        "preflight_orchestrator_sha": preflight["orchestrator_sha"],
        "cycle_source_artifact": cycle_source["artifact"],
        "cycle_source_sha": cycle_source["artifact_sha"],
        "policy_source_artifact": policy_source["artifact"],
        "policy_source_sha": policy_source["artifact_sha"],
        "policy": policy,
        "policy_sha": canonical_sha(policy),
        "cycle_count": len(cycles),
        "cycle_ledger_sha": canonical_sha([cycle["cycle_sha"] for cycle in cycles]),
        "metrics": {
            "duplicate_cycle_count": duplicate_count,
            "max_cycle_gap_minutes": max_gap,
            "stale_cycle_count": stale_count,
            "source_parity_failure_count": source_parity_failures,
            "display_integrity_failure_count": display_integrity_failures,
            "max_shadow_dd_pct": max_dd,
            "max_cost_overrun_pct": max_cost_overrun,
            "max_abs_rolling_correlation": max_correlation,
            "max_abs_weight_drift": max_weight_drift,
            "max_attribution_error_r": max_attribution_error,
            "worst_cycle_net_r": worst_cycle,
            "max_consecutive_negative_cycles": max_consecutive_negative,
            "total_net_pnl_r": total_net,
            "total_cost_r": total_cost,
        },
        "selected_combination": preflight["selected_combination"],
        "selected_combination_sha": preflight["selected_combination_sha"],
        "target_risk_weights": preflight["target_risk_weights"],
        "shared_lineage": preflight["shared_lineage"],
        "stage_shas": preflight["stage_shas"],
        "shadow_20c_complete": len(cycles) == 20,
        "shadow_200c_allowed": shadow_200c_allowed,
        "promotion_authority": False,
        "automatic_shadow_start": False,
        "real_shadow_started": False,
        "runtime_bound": False,
        "next": "SHADOW_200C_READ_ONLY_ACCUMULATION" if shadow_200c_allowed else "RETAIN_INCUMBENT_AND_REMEDIATE_SHADOW20",
        **{key: child for key, child in SAFETY.items() if key != "promotion_authority"},
    }
    result["canary_sha"] = canonical_sha(result)
    return result
