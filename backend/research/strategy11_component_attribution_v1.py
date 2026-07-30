from __future__ import annotations

import copy
import math
from typing import Any, Mapping

from backend.research.strategy11_synthesis_factorial_replay_v1 import (
    SAFETY,
    evaluate_factorial,
)
from backend.research.strategy11_synthesis_material_registry_v1 import canonical_sha
from backend.contracts.strategy11_validation_primitives_v1 import ValidationPrimitives

INPUT_SCHEMA = "strategy11.component_attribution.input.v1"
OUTPUT_SCHEMA = "strategy11.component_attribution.output.v1"


class ComponentAttributionError(ValueError):
    pass


def _fail(code: str, detail: str = "") -> None:
    raise ComponentAttributionError(f"{code}:{detail}" if detail else code)

_validation = ValidationPrimitives(_fail)
_mapping = _validation.mapping
_string = _validation.string
_number = _validation.number
_bool = _validation.boolean







def validate_policy(value: Mapping[str, Any]) -> dict[str, Any]:
    policy = _mapping(value, "policy")
    required = {
        "policy_id", "min_leave_one_out_net_r", "min_shapley_net_r",
        "max_leave_one_out_drawdown_penalty_r", "min_joint_uplift_net_r",
        "max_component_share_pct", "require_both_positive",
    }
    missing = sorted(required - set(policy))
    extra = sorted(set(policy) - required)
    if missing:
        _fail("POLICY_FIELDS_MISSING", ",".join(missing))
    if extra:
        _fail("POLICY_EXTRA_FIELDS", ",".join(extra))
    return {
        "policy_id": _string(policy["policy_id"], "policy.policy_id"),
        "min_leave_one_out_net_r": _number(policy["min_leave_one_out_net_r"], "policy.min_leave_one_out_net_r"),
        "min_shapley_net_r": _number(policy["min_shapley_net_r"], "policy.min_shapley_net_r"),
        "max_leave_one_out_drawdown_penalty_r": _number(
            policy["max_leave_one_out_drawdown_penalty_r"],
            "policy.max_leave_one_out_drawdown_penalty_r",
        ),
        "min_joint_uplift_net_r": _number(policy["min_joint_uplift_net_r"], "policy.min_joint_uplift_net_r"),
        "max_component_share_pct": _number(
            policy["max_component_share_pct"],
            "policy.max_component_share_pct",
            minimum=50.0,
            maximum=100.0,
        ),
        "require_both_positive": _bool(policy["require_both_positive"], "policy.require_both_positive"),
    }


def _factorial_result(value: Mapping[str, Any], factorial_input: Mapping[str, Any]) -> dict[str, Any]:
    supplied = _mapping(value, "factorial_result")
    reproduced = evaluate_factorial(factorial_input)
    if supplied.get("factorial_sha") != reproduced.get("factorial_sha"):
        _fail("FACTORIAL_RESULT_SHA_MISMATCH")
    if supplied != reproduced:
        _fail("FACTORIAL_RESULT_RECONCILIATION_MISMATCH")
    if reproduced["state"] != "PASS_SYNTHESIS_FACTORIAL_W2_CANDIDATE":
        _fail("PASS_FACTORIAL_RESULT_REQUIRED")
    return reproduced


def _cell_metrics(factorial_input: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    rows = factorial_input.get("cells")
    if not isinstance(rows, list):
        _fail("FACTORIAL_CELLS_REQUIRED")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            _fail("CELL_OBJECT_REQUIRED")
        cell_id = _string(row.get("cell_id"), "cell.cell_id").upper()
        metrics = row.get("metrics")
        if not isinstance(metrics, Mapping):
            _fail("CELL_METRICS_REQUIRED", cell_id)
        result[cell_id] = dict(metrics)
    if set(result) != {"BASE", "BASE_A", "BASE_B", "BASE_AB"}:
        _fail("CELL_COVERAGE_MISMATCH")
    return result


def attribute_components(value: Mapping[str, Any]) -> dict[str, Any]:
    payload = _mapping(value, "attribution_input")
    allowed = {"schema_version", "factorial_input", "factorial_result", "policy", "authority"}
    missing = sorted(allowed - set(payload))
    extra = sorted(set(payload) - allowed)
    if missing:
        _fail("INPUT_FIELDS_MISSING", ",".join(missing))
    if extra:
        _fail("INPUT_EXTRA_FIELDS", ",".join(extra))
    if payload.get("schema_version") != INPUT_SCHEMA:
        _fail("INPUT_SCHEMA_MISMATCH")
    if payload.get("authority") != SAFETY:
        _fail("INPUT_AUTHORITY_MISMATCH")

    factorial_input = _mapping(payload["factorial_input"], "factorial_input")
    factorial_result = _factorial_result(payload["factorial_result"], factorial_input)
    policy = validate_policy(payload["policy"])
    candidate = _mapping(factorial_input.get("candidate"), "factorial_input.candidate")
    components = candidate.get("components")
    if not isinstance(components, list) or len(components) != 2:
        _fail("TWO_COMPONENT_CANDIDATE_REQUIRED")
    component_rows = sorted(
        [dict(row) for row in components if isinstance(row, Mapping)],
        key=lambda row: row.get("material_id", ""),
    )
    if len(component_rows) != 2:
        _fail("TWO_COMPONENT_OBJECTS_REQUIRED")
    a, b = component_rows
    a_id = _string(a.get("material_id"), "component_a.material_id")
    b_id = _string(b.get("material_id"), "component_b.material_id")

    metrics = _cell_metrics(factorial_input)
    net = {cell: _number(row.get("net_after_cost_r"), f"{cell}.net_after_cost_r") for cell, row in metrics.items()}
    dd = {cell: _number(row.get("max_drawdown_r"), f"{cell}.max_drawdown_r", minimum=0.0) for cell, row in metrics.items()}

    contribution_a = net["BASE_AB"] - net["BASE_B"]
    contribution_b = net["BASE_AB"] - net["BASE_A"]
    shapley_a = 0.5 * ((net["BASE_A"] - net["BASE"]) + (net["BASE_AB"] - net["BASE_B"]))
    shapley_b = 0.5 * ((net["BASE_B"] - net["BASE"]) + (net["BASE_AB"] - net["BASE_A"]))
    dd_penalty_a = dd["BASE_AB"] - dd["BASE_B"]
    dd_penalty_b = dd["BASE_AB"] - dd["BASE_A"]
    joint_uplift = net["BASE_AB"] - net["BASE"]
    shapley_sum = shapley_a + shapley_b
    if abs(shapley_sum - joint_uplift) > 1e-9:
        _fail("SHAPLEY_RECONCILIATION_MISMATCH")
    absolute_total = abs(shapley_a) + abs(shapley_b)
    shares = {
        a_id: abs(shapley_a) / absolute_total * 100.0 if absolute_total else 0.0,
        b_id: abs(shapley_b) / absolute_total * 100.0 if absolute_total else 0.0,
    }

    raw_components = (
        (a, contribution_a, shapley_a, dd_penalty_a),
        (b, contribution_b, shapley_b, dd_penalty_b),
    )
    attributed: list[dict[str, Any]] = []
    blockers: list[str] = []
    for component, leave_one_out_net, shapley_net, dd_penalty in raw_components:
        material_id = component["material_id"]
        row_blockers: list[str] = []
        if leave_one_out_net < policy["min_leave_one_out_net_r"]:
            row_blockers.append("LEAVE_ONE_OUT_NET_LOW")
        if shapley_net < policy["min_shapley_net_r"]:
            row_blockers.append("SHAPLEY_NET_LOW")
        if dd_penalty > policy["max_leave_one_out_drawdown_penalty_r"]:
            row_blockers.append("DRAWDOWN_PENALTY_HIGH")
        if shares[material_id] > policy["max_component_share_pct"]:
            row_blockers.append("COMPONENT_DOMINANCE_HIGH")
        if policy["require_both_positive"] and (leave_one_out_net <= 0.0 or shapley_net <= 0.0):
            row_blockers.append("NON_POSITIVE_COMPONENT")
        blockers.extend(f"{material_id}:{code}" for code in row_blockers)
        attributed.append(
            {
                "material_id": material_id,
                "material_sha": component["material_sha"],
                "component_type": component["component_type"],
                "semantic_axis": component["semantic_axis"],
                "leave_one_out_net_r": leave_one_out_net,
                "shapley_net_r": shapley_net,
                "leave_one_out_drawdown_penalty_r": dd_penalty,
                "absolute_shapley_share_pct": shares[material_id],
                "blockers": row_blockers,
                "contribution_pass": not row_blockers,
            }
        )
    if joint_uplift < policy["min_joint_uplift_net_r"]:
        blockers.append("JOINT_UPLIFT_LOW")

    state = "PASS_COMPONENT_ATTRIBUTION" if not blockers else "HOLD_COMPONENT_ATTRIBUTION"
    result = {
        "schema_version": OUTPUT_SCHEMA,
        "state": state,
        "candidate_id": candidate["candidate_id"],
        "candidate_sha": candidate["candidate_sha"],
        "factorial_sha": factorial_result["factorial_sha"],
        "evaluation_stage": factorial_result["evaluation_stage"],
        "components": attributed,
        "joint_uplift_net_r": joint_uplift,
        "shapley_sum_net_r": shapley_sum,
        "attribution_blockers": blockers,
        "policy_sha": canonical_sha(policy),
        "next": "SYNTHESIS_SEALER" if not blockers else "DROP_OR_REDESIGN_COMPONENTS",
        **SAFETY,
    }
    result["attribution_sha"] = canonical_sha(result)
    return result
