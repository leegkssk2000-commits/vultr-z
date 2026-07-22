#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any


EXPECTED_SCALP_CELL_COUNT = 24
EXPECTED_SCALP_CANDIDATE_COUNT = 4
EXPECTED_SURVIVOR_COUNT = 1
EXPECTED_SURVIVOR_CELL_COUNT = 6
ROBUST_FRICTION_CAP_R = 0.25
CONDITIONAL_FRICTION_CAP_R = 0.33
ABSOLUTE_FRICTION_CAP_R = 0.75


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except Exception:
        return default


def rounded(value: Any, digits: int = 10) -> float:
    return round(finite(value), digits)


def sha256_file(path: Path) -> str | None:
    if not path.is_file() or path.is_symlink():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def required_raw_distance_pct(fee_bps_per_side: float, slippage_bps_per_side: float, friction_cap_r: float) -> float:
    if friction_cap_r <= 0:
        raise ValueError("FRICTION_CAP_R_INVALID")
    roundtrip_friction_pct = 2.0 * (fee_bps_per_side + slippage_bps_per_side) / 100.0
    return roundtrip_friction_pct / friction_cap_r


def summarize_selected_cells(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "cell_count": 0,
            "median_raw_r_distance_pct": 0.0,
            "minimum_raw_r_distance_pct": 0.0,
            "maximum_raw_r_distance_pct": 0.0,
            "median_contractual_friction_floor_r": 0.0,
            "maximum_contractual_friction_floor_r": 0.0,
            "stop_trade_count": 0,
            "stop_overshoot_count": 0,
            "cost_axis": {},
            "perturbation_axis": {},
        }
    raw_distances = [finite(row.get("raw_r_distance_pct")) for row in rows]
    frictions = [finite(row.get("contractual_friction_floor_r")) for row in rows]
    by_cost: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_perturbation: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_cost[str(row.get("cost_profile") or "")].append(row)
        by_perturbation[str(row.get("perturbation") or "")].append(row)

    def axis_summary(grouped: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, float]]:
        output: dict[str, dict[str, float]] = {}
        for key, members in sorted(grouped.items()):
            output[key] = {
                "cell_count": float(len(members)),
                "gross_r_sum": rounded(sum(finite(row.get("gross_r")) for row in members)),
                "net_r_sum": rounded(sum(finite(row.get("net_r")) for row in members)),
                "median_contractual_friction_floor_r": rounded(
                    statistics.median(finite(row.get("contractual_friction_floor_r")) for row in members)
                ),
                "maximum_contractual_friction_floor_r": rounded(
                    max(finite(row.get("contractual_friction_floor_r")) for row in members)
                ),
            }
        return output

    stop_rows = [row for row in rows if str(row.get("exit_reason") or "") in {"stop", "stop_collision"}]
    return {
        "cell_count": len(rows),
        "median_raw_r_distance_pct": rounded(statistics.median(raw_distances)),
        "minimum_raw_r_distance_pct": rounded(min(raw_distances)),
        "maximum_raw_r_distance_pct": rounded(max(raw_distances)),
        "median_contractual_friction_floor_r": rounded(statistics.median(frictions)),
        "maximum_contractual_friction_floor_r": rounded(max(frictions)),
        "stop_trade_count": len(stop_rows),
        "stop_overshoot_count": sum(1 for row in stop_rows if finite(row.get("stop_overshoot_r")) > 1e-7),
        "cost_axis": axis_summary(by_cost),
        "perturbation_axis": axis_summary(by_perturbation),
    }


def build_plan(
    audit: dict[str, Any],
    prior_plan: dict[str, Any],
    prior_proof: dict[str, Any],
    contract: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    blockers: list[str] = []
    if audit.get("state") != "PASS_SHORT_STOP_OVERSHOOT_AND_COST_R_CAUSAL_AUDIT":
        blockers.append("CAUSAL_AUDIT_NOT_PASS")
    if int(audit.get("blocker_count", -1)) != 0 or int(audit.get("failure_count", -1)) != 0:
        blockers.append("CAUSAL_AUDIT_INTEGRITY_FAILED")
    if audit.get("next_stage") != "R7.A4D2_SHORT_SINGLE_SCALP_SURVIVOR_6_AND_COST_R_FEASIBILITY_PLAN":
        blockers.append("CAUSAL_AUDIT_NEXT_STAGE_MISMATCH")
    if int(audit.get("cell_count", -1)) != EXPECTED_SCALP_CELL_COUNT:
        blockers.append("CAUSAL_AUDIT_CELL_COUNT_INVALID")
    if int(audit.get("policy_geometry_parity_failure_count", -1)) != 0:
        blockers.append("POLICY_GEOMETRY_PARITY_FAILED")
    if int(audit.get("protected_mutation_path_count", -1)) != 0:
        blockers.append("CAUSAL_AUDIT_MUTATION_DETECTED")

    if prior_plan.get("state") != "PASS_SHORT_SELECTIVE_CHART_GATE_AND_GEOMETRY_COUNTERFACTUAL_PLAN":
        blockers.append("PRIOR_COUNTERFACTUAL_PLAN_NOT_PASS")
    if int(prior_plan.get("blocker_count", -1)) != 0:
        blockers.append("PRIOR_COUNTERFACTUAL_PLAN_BLOCKED")
    if int(prior_plan.get("scalp_counterfactual_candidate_count", -1)) != EXPECTED_SCALP_CANDIDATE_COUNT:
        blockers.append("PRIOR_COUNTERFACTUAL_CANDIDATE_COUNT_INVALID")
    if int(prior_plan.get("scalp_counterfactual_execution_cell_count", -1)) != EXPECTED_SCALP_CELL_COUNT:
        blockers.append("PRIOR_COUNTERFACTUAL_CELL_COUNT_INVALID")

    if prior_proof.get("state") != "PASS_SHORT_SCALP_GEOMETRY_COUNTERFACTUAL_24_AND_BASELINE_CLUSTER_EXPANSION_36":
        blockers.append("PRIOR_COUNTERFACTUAL_PROOF_NOT_PASS")
    if int(prior_proof.get("blocker_count", -1)) != 0 or int(prior_proof.get("failure_count", -1)) != 0:
        blockers.append("PRIOR_COUNTERFACTUAL_PROOF_INTEGRITY_FAILED")
    if int(prior_proof.get("scalp_counterfactual_completed_cell_count", -1)) != EXPECTED_SCALP_CELL_COUNT:
        blockers.append("PRIOR_COUNTERFACTUAL_COMPLETION_INVALID")
    if int(prior_proof.get("scalp_invalid_geometry_count", -1)) != 0:
        blockers.append("PRIOR_COUNTERFACTUAL_GEOMETRY_INVALID")

    decisions = audit.get("candidate_resolution") if isinstance(audit.get("candidate_resolution"), dict) else {}
    selected = decisions.get("selected_survivor") if isinstance(decisions.get("selected_survivor"), dict) else None
    survivor_count = int(decisions.get("survivor_candidate_count", -1))
    if survivor_count != EXPECTED_SURVIVOR_COUNT or selected is None:
        blockers.append(f"SINGLE_SURVIVOR_COUNT_INVALID:{survivor_count}")
    selected_id = str((selected or {}).get("candidate_id") or "")
    if not selected_id:
        blockers.append("SINGLE_SURVIVOR_ID_MISSING")

    cell_audits = [row for row in audit.get("cell_audits", []) if isinstance(row, dict)]
    selected_cells = [row for row in cell_audits if str(row.get("candidate_id") or "") == selected_id]
    if len(cell_audits) != EXPECTED_SCALP_CELL_COUNT:
        blockers.append(f"CELL_AUDIT_COUNT_INVALID:{len(cell_audits)}")
    if len(selected_cells) != EXPECTED_SURVIVOR_CELL_COUNT:
        blockers.append(f"SURVIVOR_CELL_COUNT_INVALID:{len(selected_cells)}")

    cost_profiles = {
        str(row.get("id") or ""): row
        for row in contract.get("cost_profiles", [])
        if isinstance(row, dict) and row.get("id")
    }
    perturbations = {
        str(row.get("id") or ""): row
        for row in contract.get("perturbations", [])
        if isinstance(row, dict) and row.get("id")
    }
    if sorted(cost_profiles) != ["cost_profile_0", "cost_profile_1", "cost_profile_2"]:
        blockers.append("COST_PROFILE_CONTRACT_INVALID")
    if sorted(perturbations) != ["perturbation_0", "perturbation_1"]:
        blockers.append("PERTURBATION_CONTRACT_INVALID")

    requirements: dict[str, dict[str, float]] = {}
    for cost_id, row in sorted(cost_profiles.items()):
        fee = finite(row.get("fee_bps_per_side"))
        slip = finite(row.get("slippage_bps_per_side"))
        requirements[cost_id] = {
            "fee_bps_per_side": rounded(fee),
            "slippage_bps_per_side": rounded(slip),
            "required_raw_distance_pct_for_0_25r": rounded(required_raw_distance_pct(fee, slip, ROBUST_FRICTION_CAP_R)),
            "required_raw_distance_pct_for_0_33r": rounded(required_raw_distance_pct(fee, slip, CONDITIONAL_FRICTION_CAP_R)),
        }

    selected_summary = summarize_selected_cells(selected_cells)
    selected_net = finite((selected or {}).get("net_r_sum"))
    selected_delta = finite((selected or {}).get("net_r_sum_delta"))
    selected_expectancy = finite((selected or {}).get("expectancy_r"))
    selected_expectancy_delta = finite((selected or {}).get("expectancy_r_delta"))
    selected_worst_cost = finite((selected or {}).get("worst_cost_axis_net_r_sum"))
    perturbation_1_net = finite(
        selected_summary.get("perturbation_axis", {}).get("perturbation_1", {}).get("net_r_sum")
    )
    median_friction = finite(selected_summary.get("median_contractual_friction_floor_r"))
    maximum_friction = finite(selected_summary.get("maximum_contractual_friction_floor_r"))

    feasibility_checks = {
        "selected_survivor_exactly_one": survivor_count == EXPECTED_SURVIVOR_COUNT,
        "six_cells_present": len(selected_cells) == EXPECTED_SURVIVOR_CELL_COUNT,
        "current_net_r_positive": selected_net > 0,
        "net_r_delta_positive": selected_delta > 0,
        "current_expectancy_r_positive": selected_expectancy > 0,
        "expectancy_r_delta_positive": selected_expectancy_delta > 0,
        "worst_cost_axis_net_r_positive": selected_worst_cost > 0,
        "timing_stress_net_r_positive": perturbation_1_net > 0,
        "median_friction_floor_le_0_33r": median_friction <= CONDITIONAL_FRICTION_CAP_R,
        "maximum_friction_floor_le_0_75r": maximum_friction <= ABSOLUTE_FRICTION_CAP_R,
        "policy_geometry_parity": int(audit.get("policy_geometry_parity_failure_count", -1)) == 0,
    }
    current_geometry_feasible = all(feasibility_checks.values())
    robust_geometry_feasible = current_geometry_feasible and median_friction <= ROBUST_FRICTION_CAP_R

    if median_friction <= ROBUST_FRICTION_CAP_R:
        feasibility_classification = "ROBUST_COST_R_FEASIBLE"
    elif median_friction <= CONDITIONAL_FRICTION_CAP_R and maximum_friction <= ABSOLUTE_FRICTION_CAP_R:
        feasibility_classification = "CONDITIONAL_COST_R_FEASIBLE"
    else:
        feasibility_classification = "CURRENT_GEOMETRY_COST_R_INFEASIBLE"

    raw_distance = finite(selected_summary.get("median_raw_r_distance_pct"))
    distance_shortfall: dict[str, dict[str, float]] = {}
    for cost_id, row in requirements.items():
        robust_required = finite(row.get("required_raw_distance_pct_for_0_25r"))
        conditional_required = finite(row.get("required_raw_distance_pct_for_0_33r"))
        distance_shortfall[cost_id] = {
            "current_median_raw_distance_pct": rounded(raw_distance),
            "robust_required_multiple": rounded(robust_required / raw_distance) if raw_distance > 0 else 0.0,
            "conditional_required_multiple": rounded(conditional_required / raw_distance) if raw_distance > 0 else 0.0,
            "robust_distance_shortfall_pct": rounded(max(robust_required - raw_distance, 0.0)),
            "conditional_distance_shortfall_pct": rounded(max(conditional_required - raw_distance, 0.0)),
        }

    rebase_rejects = sorted(str(value) for value in decisions.get("rebase_reject_candidate_ids", []))
    raw_controls = sorted(str(value) for value in decisions.get("raw_control_candidate_ids", []))
    if len(rebase_rejects) != 2:
        blockers.append(f"REBASE_REJECT_SET_INVALID:{len(rebase_rejects)}")
    if len(raw_controls) != 1:
        blockers.append(f"RAW_CONTROL_SET_INVALID:{len(raw_controls)}")

    if blockers:
        next_stage = "R7.A4D2_SHORT_SINGLE_SCALP_SURVIVOR_6_AND_COST_R_FEASIBILITY_PLAN"
    elif current_geometry_feasible:
        next_stage = "R7.A4D2_SHORT_SINGLE_SCALP_SURVIVOR_6"
    else:
        next_stage = "R7.A4D2_SHORT_SCALP_R_DISTANCE_AND_TIMEFRAME_REDESIGN_PLAN"

    plan = {
        "schema": "r7a4d2_short_single_scalp_survivor6_cost_r_feasibility_plan_v1",
        "official_stage": "R7.A4D2_SHORT_SINGLE_SCALP_SURVIVOR_6_AND_COST_R_FEASIBILITY_PLAN",
        "state": "PASS_SHORT_SINGLE_SCALP_SURVIVOR_6_AND_COST_R_FEASIBILITY_PLAN" if not blockers else "HOLD_SHORT_SINGLE_SCALP_SURVIVOR_6_AND_COST_R_FEASIBILITY_PLAN_INPUT",
        "blocker_count": len(blockers),
        "blockers": blockers,
        "single_survivor_candidate_id": selected_id,
        "single_survivor_retest_cell_target": EXPECTED_SURVIVOR_CELL_COUNT,
        "single_survivor_retest_allowed": bool(not blockers and current_geometry_feasible),
        "current_geometry_feasible": current_geometry_feasible,
        "robust_geometry_feasible": robust_geometry_feasible,
        "feasibility_classification": feasibility_classification,
        "diagnostic_cost_r_policy": {
            "robust_friction_cap_r": ROBUST_FRICTION_CAP_R,
            "conditional_friction_cap_r": CONDITIONAL_FRICTION_CAP_R,
            "absolute_friction_cap_r": ABSOLUTE_FRICTION_CAP_R,
            "operational_ssot_change": False,
            "stop_widening_to_pass_gate_allowed": False,
            "entry_threshold_relaxation_allowed": False,
        },
        "selected_survivor_from_audit": selected,
        "selected_survivor_cell_summary": selected_summary,
        "feasibility_checks": feasibility_checks,
        "required_raw_distance_pct_by_cost_profile": requirements,
        "raw_distance_shortfall_by_cost_profile": distance_shortfall,
        "rebase_reject_candidate_ids": rebase_rejects,
        "raw_geometry_control_candidate_ids": raw_controls,
        "rejected_candidates_locked": True,
        "raw_control_execution_allowed": False,
        "redesign_constraints": {
            "allowed_diagnostic_axes": [
                "larger_pre_entry_chart_structure_distance",
                "higher_timeframe_candidate_discovery",
                "lower_friction_execution_profile_feasibility",
            ],
            "forbidden_shortcuts": [
                "blind_stop_widening",
                "entry_threshold_relaxation",
                "future_pnl_selected_segments",
                "symbol_only_overfit",
                "production_admission_expansion",
            ],
            "baseline_market_coverage_expansion_still_required": True,
        },
        "strategy_mutation_allowed": False,
        "registry_mutation_allowed": False,
        "config_mutation_allowed": False,
        "production_admission_expansion_allowed": False,
        "shadow_start_allowed": False,
        "full_3600_reexecution_allowed": False,
        "event_replay_2880_allowed": False,
        "next_stage": next_stage,
    }
    return plan, blockers


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--contract", required=True)
    args = parser.parse_args()
    root = Path(args.root).resolve()
    contract_path = Path(args.contract).resolve()
    audit_path = root / "runtime/r7a4d2_short_stop_overshoot_cost_r_causal_audit/causal_audit_v1.json"
    prior_plan_path = root / "runtime/r7a4d2_short_selective_counterfactual_plan/counterfactual_plan_v1.json"
    prior_proof_path = root / "runtime/r7a4d2_short_scalp_counterfactual24_baseline_expansion36/counterfactual_expansion_proof_v1.json"

    before = {
        str(audit_path): sha256_file(audit_path),
        str(prior_plan_path): sha256_file(prior_plan_path),
        str(prior_proof_path): sha256_file(prior_proof_path),
        str(contract_path): sha256_file(contract_path),
    }
    audit = load_json(audit_path)
    prior_plan = load_json(prior_plan_path)
    prior_proof = load_json(prior_proof_path)
    contract = load_json(contract_path)
    plan, blockers = build_plan(audit, prior_plan, prior_proof, contract)
    after = {
        str(audit_path): sha256_file(audit_path),
        str(prior_plan_path): sha256_file(prior_plan_path),
        str(prior_proof_path): sha256_file(prior_proof_path),
        str(contract_path): sha256_file(contract_path),
    }
    mutation_paths = sorted(path for path in before if before[path] != after[path])
    if mutation_paths:
        blockers.append("PROTECTED_INPUT_MUTATION_DETECTED")
        plan["blockers"] = list(dict.fromkeys(blockers))
        plan["blocker_count"] = len(plan["blockers"])
        plan["state"] = "HOLD_SHORT_SINGLE_SCALP_SURVIVOR_6_AND_COST_R_FEASIBILITY_PLAN_INPUT"
        plan["single_survivor_retest_allowed"] = False
        plan["next_stage"] = "R7.A4D2_SHORT_SINGLE_SCALP_SURVIVOR_6_AND_COST_R_FEASIBILITY_PLAN"
    plan["protected_mutation_path_count"] = len(mutation_paths)
    plan["protected_mutation_paths"] = mutation_paths

    output = root / "runtime/r7a4d2_short_single_scalp_survivor6_cost_r_feasibility_plan/feasibility_plan_v1.json"
    atomic_json(output, plan)
    summary = plan.get("selected_survivor_cell_summary", {})
    print("STATE=" + str(plan["state"]))
    print("BLOCKER_COUNT=" + str(plan["blocker_count"]))
    print("SINGLE_SURVIVOR_CANDIDATE_ID=" + str(plan["single_survivor_candidate_id"]))
    print("SINGLE_SURVIVOR_RETEST_CELL_TARGET=" + str(plan["single_survivor_retest_cell_target"]))
    print("SINGLE_SURVIVOR_RETEST_ALLOWED=" + str(plan["single_survivor_retest_allowed"]).lower())
    print("CURRENT_GEOMETRY_FEASIBLE=" + str(plan["current_geometry_feasible"]).lower())
    print("ROBUST_GEOMETRY_FEASIBLE=" + str(plan["robust_geometry_feasible"]).lower())
    print("FEASIBILITY_CLASSIFICATION=" + str(plan["feasibility_classification"]))
    print("SURVIVOR_MEDIAN_RAW_R_DISTANCE_PCT=" + str(summary.get("median_raw_r_distance_pct", 0.0)))
    print("SURVIVOR_MEDIAN_FRICTION_FLOOR_R=" + str(summary.get("median_contractual_friction_floor_r", 0.0)))
    print("SURVIVOR_MAX_FRICTION_FLOOR_R=" + str(summary.get("maximum_contractual_friction_floor_r", 0.0)))
    print("FEASIBILITY_CHECKS=" + json.dumps(plan["feasibility_checks"], sort_keys=True))
    print("REQUIRED_RAW_DISTANCE_PCT_BY_COST_PROFILE=" + json.dumps(plan["required_raw_distance_pct_by_cost_profile"], sort_keys=True))
    print("RAW_DISTANCE_SHORTFALL_BY_COST_PROFILE=" + json.dumps(plan["raw_distance_shortfall_by_cost_profile"], sort_keys=True))
    print("REBASE_REJECT_CANDIDATE_IDS=" + json.dumps(plan["rebase_reject_candidate_ids"]))
    print("RAW_GEOMETRY_CONTROL_CANDIDATE_IDS=" + json.dumps(plan["raw_geometry_control_candidate_ids"]))
    print("PROTECTED_MUTATION_PATH_COUNT=" + str(len(mutation_paths)))
    print("PLAN_JSON=" + str(output))
    print("NEXT_STAGE=" + str(plan["next_stage"]))
    print("BLOCKERS=" + json.dumps(plan["blockers"], ensure_ascii=False))
    print("RC=" + ("0" if int(plan["blocker_count"]) == 0 else "2"))
    return 0 if int(plan["blocker_count"]) == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
