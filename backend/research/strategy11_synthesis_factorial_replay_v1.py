from __future__ import annotations

import copy
import json
import math
from typing import Any, Mapping, Sequence

from backend.research.strategy11_synthesis_material_registry_v1 import SAFETY, canonical_sha

INPUT_SCHEMA = "strategy11.synthesis_factorial_replay.input.v1"
OUTPUT_SCHEMA = "strategy11.synthesis_factorial_replay.output.v1"
CELL_SCHEMA = "strategy11.synthesis_factorial_cell.v1"
REQUIRED_CELLS = ("BASE", "BASE_A", "BASE_B", "BASE_AB")
ALLOWED_STAGES = {"W2", "W3", "NEW_SEALED"}


class SynthesisFactorialError(ValueError):
    pass


def _fail(code: str, detail: str = "") -> None:
    raise SynthesisFactorialError(f"{code}:{detail}" if detail else code)


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
        "policy_id", "min_retention_pct", "min_profit_factor", "min_payoff",
        "min_net_after_cost_r", "max_drawdown_r", "min_avg_loss_r", "min_worst_loss_r",
        "min_stress_worst_loss_r", "min_positive_windows", "min_interaction_net_r",
        "max_interaction_drawdown_r", "min_marginal_net_r", "require_ab_parity",
        "require_duplicate_zero",
    }
    missing = sorted(required - set(policy))
    extra = sorted(set(policy) - required)
    if missing:
        _fail("POLICY_FIELDS_MISSING", ",".join(missing))
    if extra:
        _fail("POLICY_EXTRA_FIELDS", ",".join(extra))
    return {
        "policy_id": _string(policy["policy_id"], "policy.policy_id"),
        "min_retention_pct": _number(policy["min_retention_pct"], "policy.min_retention_pct", minimum=0.0, maximum=100.0),
        "min_profit_factor": _number(policy["min_profit_factor"], "policy.min_profit_factor", minimum=0.0),
        "min_payoff": _number(policy["min_payoff"], "policy.min_payoff", minimum=0.0),
        "min_net_after_cost_r": _number(policy["min_net_after_cost_r"], "policy.min_net_after_cost_r"),
        "max_drawdown_r": _number(policy["max_drawdown_r"], "policy.max_drawdown_r", minimum=0.0),
        "min_avg_loss_r": _number(policy["min_avg_loss_r"], "policy.min_avg_loss_r", maximum=0.0),
        "min_worst_loss_r": _number(policy["min_worst_loss_r"], "policy.min_worst_loss_r", maximum=0.0),
        "min_stress_worst_loss_r": _number(policy["min_stress_worst_loss_r"], "policy.min_stress_worst_loss_r", maximum=0.0),
        "min_positive_windows": _integer(policy["min_positive_windows"], "policy.min_positive_windows", minimum=1),
        "min_interaction_net_r": _number(policy["min_interaction_net_r"], "policy.min_interaction_net_r"),
        "max_interaction_drawdown_r": _number(policy["max_interaction_drawdown_r"], "policy.max_interaction_drawdown_r"),
        "min_marginal_net_r": _number(policy["min_marginal_net_r"], "policy.min_marginal_net_r"),
        "require_ab_parity": _bool(policy["require_ab_parity"], "policy.require_ab_parity"),
        "require_duplicate_zero": _bool(policy["require_duplicate_zero"], "policy.require_duplicate_zero"),
    }


def validate_candidate(value: Mapping[str, Any]) -> dict[str, Any]:
    candidate = _mapping(value, "candidate")
    supplied_sha = _sha(candidate.get("candidate_sha"), "candidate.candidate_sha")
    payload = copy.deepcopy(candidate)
    payload.pop("candidate_sha", None)
    if canonical_sha(payload) != supplied_sha:
        _fail("CANDIDATE_SHA_MISMATCH")
    if candidate.get("schema_version") != "strategy11.bounded_synthesis_candidate.v1":
        _fail("CANDIDATE_SCHEMA_MISMATCH")
    if candidate.get("selection_data_role") != "DESIGN_SELECTION_ONLY":
        _fail("CANDIDATE_SELECTION_ROLE_MISMATCH")
    if candidate.get("first_oos_required") != "W2":
        _fail("FIRST_OOS_W2_REQUIRED")
    components = candidate.get("components")
    if not isinstance(components, list) or len(components) != 2:
        _fail("TWO_COMPONENT_CANDIDATE_REQUIRED")
    ids = [_string(row.get("material_id"), "candidate.components[].material_id") for row in components if isinstance(row, Mapping)]
    if len(ids) != 2 or len(set(ids)) != 2:
        _fail("TWO_UNIQUE_COMPONENT_IDS_REQUIRED")
    for key, expected in SAFETY.items():
        if candidate.get(key) != expected:
            _fail("CANDIDATE_AUTHORITY_MISMATCH", key)
    return candidate


def _metrics(value: Any, cell_id: str) -> dict[str, Any]:
    metrics = _mapping(value, f"cells.{cell_id}.metrics")
    required = {
        "trades", "net_after_cost_r", "profit_factor", "payoff", "max_drawdown_r",
        "avg_loss_r", "worst_loss_r", "stress_worst_loss_r", "positive_windows", "total_windows",
    }
    missing = sorted(required - set(metrics))
    extra = sorted(set(metrics) - required)
    if missing:
        _fail("METRIC_FIELDS_MISSING", f"{cell_id}:{','.join(missing)}")
    if extra:
        _fail("METRIC_EXTRA_FIELDS", f"{cell_id}:{','.join(extra)}")
    result = {
        "trades": _integer(metrics["trades"], f"{cell_id}.trades", minimum=1),
        "net_after_cost_r": _number(metrics["net_after_cost_r"], f"{cell_id}.net_after_cost_r"),
        "profit_factor": _number(metrics["profit_factor"], f"{cell_id}.profit_factor", minimum=0.0),
        "payoff": _number(metrics["payoff"], f"{cell_id}.payoff", minimum=0.0),
        "max_drawdown_r": _number(metrics["max_drawdown_r"], f"{cell_id}.max_drawdown_r", minimum=0.0),
        "avg_loss_r": _number(metrics["avg_loss_r"], f"{cell_id}.avg_loss_r", maximum=0.0),
        "worst_loss_r": _number(metrics["worst_loss_r"], f"{cell_id}.worst_loss_r", maximum=0.0),
        "stress_worst_loss_r": _number(metrics["stress_worst_loss_r"], f"{cell_id}.stress_worst_loss_r", maximum=0.0),
        "positive_windows": _integer(metrics["positive_windows"], f"{cell_id}.positive_windows"),
        "total_windows": _integer(metrics["total_windows"], f"{cell_id}.total_windows", minimum=1),
    }
    if result["positive_windows"] > result["total_windows"]:
        _fail("POSITIVE_WINDOWS_EXCEED_TOTAL", cell_id)
    return result


def validate_cell(value: Mapping[str, Any], expected_components: Sequence[str]) -> dict[str, Any]:
    cell = _mapping(value, "cell")
    supplied_sha = _sha(cell.get("summary_sha"), "cell.summary_sha")
    payload = copy.deepcopy(cell)
    payload.pop("summary_sha", None)
    if canonical_sha(payload) != supplied_sha:
        _fail("CELL_SUMMARY_SHA_MISMATCH", str(cell.get("cell_id")))
    if cell.get("schema_version") != CELL_SCHEMA:
        _fail("CELL_SCHEMA_MISMATCH")
    cell_id = _string(cell.get("cell_id"), "cell.cell_id").upper()
    component_ids = cell.get("component_ids")
    if not isinstance(component_ids, list):
        _fail("COMPONENT_IDS_LIST_REQUIRED", cell_id)
    normalized_ids = sorted(_string(item, f"{cell_id}.component_ids[]") for item in component_ids)
    if normalized_ids != sorted(expected_components):
        _fail("CELL_COMPONENT_MAPPING_MISMATCH", cell_id)
    stage = _string(cell.get("evaluation_stage"), f"{cell_id}.evaluation_stage").upper()
    if stage not in ALLOWED_STAGES:
        _fail("EVALUATION_STAGE_INVALID", stage)
    lineage = _mapping(cell.get("lineage"), f"{cell_id}.lineage")
    normalized_lineage = {
        "data_sha": _sha(lineage.get("data_sha"), f"{cell_id}.lineage.data_sha"),
        "window_sha": _sha(lineage.get("window_sha"), f"{cell_id}.lineage.window_sha"),
        "source_manifest_sha": _sha(lineage.get("source_manifest_sha"), f"{cell_id}.lineage.source_manifest_sha"),
        "replay_run_id": _string(lineage.get("replay_run_id"), f"{cell_id}.lineage.replay_run_id"),
    }
    result = {
        "schema_version": CELL_SCHEMA,
        "cell_id": cell_id,
        "component_ids": normalized_ids,
        "evaluation_stage": stage,
        "lineage": normalized_lineage,
        "ab_parity_pass": _bool(cell.get("ab_parity_pass"), f"{cell_id}.ab_parity_pass"),
        "duplicate_count": _integer(cell.get("duplicate_count"), f"{cell_id}.duplicate_count"),
        "metrics": _metrics(cell.get("metrics"), cell_id),
    }
    result["summary_sha"] = canonical_sha(result)
    if result["summary_sha"] != supplied_sha:
        _fail("CELL_NORMALIZED_SHA_MISMATCH", cell_id)
    return result


def _hard_pass(metrics: Mapping[str, Any], retention_pct: float, policy: Mapping[str, Any]) -> tuple[bool, list[str]]:
    blockers: list[str] = []
    if retention_pct < policy["min_retention_pct"]:
        blockers.append("RETENTION_LOW")
    if metrics["profit_factor"] < policy["min_profit_factor"]:
        blockers.append("PF_LOW")
    if metrics["payoff"] < policy["min_payoff"]:
        blockers.append("PAYOFF_LOW")
    if metrics["net_after_cost_r"] < policy["min_net_after_cost_r"]:
        blockers.append("NET_LOW")
    if metrics["max_drawdown_r"] > policy["max_drawdown_r"]:
        blockers.append("DD_HIGH")
    if metrics["avg_loss_r"] < policy["min_avg_loss_r"]:
        blockers.append("AVG_LOSS_BREACH")
    if metrics["worst_loss_r"] < policy["min_worst_loss_r"]:
        blockers.append("WORST_LOSS_BREACH")
    if metrics["stress_worst_loss_r"] < policy["min_stress_worst_loss_r"]:
        blockers.append("STRESS_LOSS_BREACH")
    if metrics["positive_windows"] < policy["min_positive_windows"]:
        blockers.append("WINDOW_BREADTH_LOW")
    return not blockers, blockers


def evaluate_factorial(value: Mapping[str, Any]) -> dict[str, Any]:
    payload = _mapping(value, "factorial_input")
    allowed = {"schema_version", "candidate", "cells", "policy", "authority"}
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

    candidate = validate_candidate(payload["candidate"])
    policy = validate_policy(payload["policy"])
    components = sorted(row["material_id"] for row in candidate["components"])
    a_id, b_id = components
    expected = {
        "BASE": [],
        "BASE_A": [a_id],
        "BASE_B": [b_id],
        "BASE_AB": [a_id, b_id],
    }
    raw_cells = payload.get("cells")
    if not isinstance(raw_cells, list) or len(raw_cells) != 4:
        _fail("EXACT_FOUR_CELLS_REQUIRED")
    cells: dict[str, dict[str, Any]] = {}
    for raw in raw_cells:
        if not isinstance(raw, Mapping):
            _fail("CELL_OBJECT_REQUIRED")
        cell_id = _string(raw.get("cell_id"), "cell.cell_id").upper()
        if cell_id not in expected:
            _fail("CELL_ID_INVALID", cell_id)
        if cell_id in cells:
            _fail("DUPLICATE_CELL_ID", cell_id)
        cells[cell_id] = validate_cell(raw, expected[cell_id])
    if set(cells) != set(REQUIRED_CELLS):
        _fail("CELL_COVERAGE_MISMATCH")

    stages = {cell["evaluation_stage"] for cell in cells.values()}
    if len(stages) != 1:
        _fail("EVALUATION_STAGE_MISMATCH")
    stage = next(iter(stages))
    if stage != "W2":
        _fail("FIRST_FACTORIAL_STAGE_MUST_BE_W2")
    for field in ("data_sha", "window_sha", "source_manifest_sha", "replay_run_id"):
        values = {cell["lineage"][field] for cell in cells.values()}
        if len(values) != 1:
            _fail("CELL_LINEAGE_MISMATCH", field)
    evaluation_lineage = copy.deepcopy(cells["BASE"]["lineage"])
    selection_lineage = candidate.get("selection_lineage")
    if not isinstance(selection_lineage, Mapping):
        _fail("CANDIDATE_SELECTION_LINEAGE_REQUIRED")
    if evaluation_lineage["data_sha"] == selection_lineage.get("data_sha"):
        _fail("SELECTION_DATA_REUSE_FORBIDDEN")
    if evaluation_lineage["window_sha"] == selection_lineage.get("window_sha"):
        _fail("SELECTION_WINDOW_REUSE_FORBIDDEN")

    if policy["require_ab_parity"] and not all(cell["ab_parity_pass"] for cell in cells.values()):
        _fail("AB_PARITY_REQUIRED")
    if policy["require_duplicate_zero"] and any(cell["duplicate_count"] != 0 for cell in cells.values()):
        _fail("DUPLICATE_ZERO_REQUIRED")

    base_trades = cells["BASE"]["metrics"]["trades"]
    retention = {
        cell_id: cell["metrics"]["trades"] / base_trades * 100.0
        for cell_id, cell in cells.items()
    }
    gate_rows: dict[str, dict[str, Any]] = {}
    for cell_id in REQUIRED_CELLS:
        passed, blockers = _hard_pass(cells[cell_id]["metrics"], retention[cell_id], policy)
        gate_rows[cell_id] = {
            "hard_pass": passed,
            "blockers": blockers,
            "retention_pct": retention[cell_id],
        }

    metrics = {cell_id: cells[cell_id]["metrics"] for cell_id in REQUIRED_CELLS}
    interaction_net = (
        metrics["BASE_AB"]["net_after_cost_r"]
        - metrics["BASE_A"]["net_after_cost_r"]
        - metrics["BASE_B"]["net_after_cost_r"]
        + metrics["BASE"]["net_after_cost_r"]
    )
    interaction_dd = (
        metrics["BASE_AB"]["max_drawdown_r"]
        - metrics["BASE_A"]["max_drawdown_r"]
        - metrics["BASE_B"]["max_drawdown_r"]
        + metrics["BASE"]["max_drawdown_r"]
    )
    marginal_net = metrics["BASE_AB"]["net_after_cost_r"] - max(
        metrics["BASE_A"]["net_after_cost_r"],
        metrics["BASE_B"]["net_after_cost_r"],
    )
    synergy_blockers: list[str] = []
    if interaction_net < policy["min_interaction_net_r"]:
        synergy_blockers.append("INTERACTION_NET_LOW")
    if interaction_dd > policy["max_interaction_drawdown_r"]:
        synergy_blockers.append("INTERACTION_DD_HIGH")
    if marginal_net < policy["min_marginal_net_r"]:
        synergy_blockers.append("MARGINAL_NET_LOW")
    if not all(gate_rows[cell_id]["hard_pass"] for cell_id in REQUIRED_CELLS):
        synergy_blockers.append("CELL_HARD_GATE_FAILED")

    state = "PASS_SYNTHESIS_FACTORIAL_W2_CANDIDATE" if not synergy_blockers else "HOLD_SYNTHESIS_FACTORIAL"
    result = {
        "schema_version": OUTPUT_SCHEMA,
        "state": state,
        "candidate_id": candidate["candidate_id"],
        "candidate_sha": candidate["candidate_sha"],
        "evaluation_stage": stage,
        "evaluation_lineage": evaluation_lineage,
        "cell_summary_shas": {cell_id: cells[cell_id]["summary_sha"] for cell_id in REQUIRED_CELLS},
        "cell_gates": gate_rows,
        "interaction": {
            "net_after_cost_r": interaction_net,
            "max_drawdown_r": interaction_dd,
            "marginal_net_r_vs_best_single": marginal_net,
        },
        "synergy_blockers": synergy_blockers,
        "selection_data_reused": False,
        "next": "COMPONENT_ATTRIBUTION" if not synergy_blockers else "HOLD_OR_REDESIGN",
        **SAFETY,
    }
    result["factorial_sha"] = canonical_sha(result)
    return result
