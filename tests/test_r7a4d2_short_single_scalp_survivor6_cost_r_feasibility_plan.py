from __future__ import annotations

import importlib.util
import os
from pathlib import Path


def load_module():
    path = Path(os.environ["R7A4D2_SURVIVOR_FEASIBILITY"])
    spec = importlib.util.spec_from_file_location("survivor_feasibility", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def contract() -> dict:
    return {
        "cost_profiles": [
            {"id": "cost_profile_0", "fee_bps_per_side": 5.0, "slippage_bps_per_side": 1.0},
            {"id": "cost_profile_1", "fee_bps_per_side": 7.5, "slippage_bps_per_side": 3.0},
            {"id": "cost_profile_2", "fee_bps_per_side": 10.0, "slippage_bps_per_side": 6.0},
        ],
        "perturbations": [
            {"id": "perturbation_0"},
            {"id": "perturbation_1"},
        ],
    }


def prior_plan() -> dict:
    return {
        "state": "PASS_SHORT_SELECTIVE_CHART_GATE_AND_GEOMETRY_COUNTERFACTUAL_PLAN",
        "blocker_count": 0,
        "scalp_counterfactual_candidate_count": 4,
        "scalp_counterfactual_execution_cell_count": 24,
    }


def prior_proof() -> dict:
    return {
        "state": "PASS_SHORT_SCALP_GEOMETRY_COUNTERFACTUAL_24_AND_BASELINE_CLUSTER_EXPANSION_36",
        "blocker_count": 0,
        "failure_count": 0,
        "scalp_counterfactual_completed_cell_count": 24,
        "scalp_invalid_geometry_count": 0,
    }


def selected_cells(raw_distance: float, friction_by_cost: dict[str, float], net_by_cost: dict[str, float]) -> list[dict]:
    rows: list[dict] = []
    for cost_id in ("cost_profile_0", "cost_profile_1", "cost_profile_2"):
        for perturbation in ("perturbation_0", "perturbation_1"):
            rows.append({
                "candidate_id": "survivor:scalp_snap:606",
                "arm": "FILL_REBASED_GEOMETRY",
                "cost_profile": cost_id,
                "perturbation": perturbation,
                "exit_reason": "take_profit",
                "raw_r_distance_pct": raw_distance,
                "contractual_friction_floor_r": friction_by_cost[cost_id],
                "gross_r": net_by_cost[cost_id] + 0.1,
                "net_r": net_by_cost[cost_id],
                "stop_overshoot_r": 0.0,
            })
    return rows


def audit(*, raw_distance: float, friction_by_cost: dict[str, float], net_by_cost: dict[str, float]) -> dict:
    selected = {
        "candidate_id": "survivor:scalp_snap:606",
        "arm": "FILL_REBASED_GEOMETRY",
        "classification": "SINGLE_SURVIVOR_RETEST_CANDIDATE",
        "closed_trade_cell_count": 6,
        "invalid_geometry_count": 0,
        "net_r_sum": sum(net_by_cost.values()) * 2.0,
        "expectancy_r": 0.8,
        "net_r_sum_delta": 5.7,
        "expectancy_r_delta": 0.85,
        "worst_cost_axis_net_r_sum": min(value * 2.0 for value in net_by_cost.values()),
    }
    cells = selected_cells(raw_distance, friction_by_cost, net_by_cost)
    for index in range(18):
        cells.append({
            "candidate_id": f"other:{index // 6}",
            "arm": "FILL_REBASED_GEOMETRY" if index < 12 else "RAW_GEOMETRY_STABILITY_CONTROL",
            "cost_profile": f"cost_profile_{(index // 2) % 3}",
            "perturbation": f"perturbation_{index % 2}",
            "exit_reason": "segment_end",
            "raw_r_distance_pct": raw_distance,
            "contractual_friction_floor_r": 0.2,
            "gross_r": -0.1,
            "net_r": -0.2,
            "stop_overshoot_r": 0.0,
        })
    return {
        "state": "PASS_SHORT_STOP_OVERSHOOT_AND_COST_R_CAUSAL_AUDIT",
        "blocker_count": 0,
        "failure_count": 0,
        "next_stage": "R7.A4D2_SHORT_SINGLE_SCALP_SURVIVOR_6_AND_COST_R_FEASIBILITY_PLAN",
        "cell_count": 24,
        "policy_geometry_parity_failure_count": 0,
        "protected_mutation_path_count": 0,
        "candidate_resolution": {
            "survivor_candidate_count": 1,
            "selected_survivor": selected,
            "rebase_reject_candidate_ids": ["reject:1", "reject:2"],
            "raw_control_candidate_ids": ["control:1"],
        },
        "cell_audits": cells,
    }


def test_required_raw_distance_matches_cost_math() -> None:
    module = load_module()
    assert round(module.required_raw_distance_pct(5.0, 1.0, 0.33), 6) == round(0.12 / 0.33, 6)
    assert round(module.required_raw_distance_pct(10.0, 6.0, 0.25), 6) == 1.28


def test_infeasible_current_geometry_redirects_to_redesign() -> None:
    module = load_module()
    evidence = audit(
        raw_distance=0.15,
        friction_by_cost={"cost_profile_0": 0.8, "cost_profile_1": 1.4, "cost_profile_2": 2.1},
        net_by_cost={"cost_profile_0": 2.0, "cost_profile_1": 1.0, "cost_profile_2": 0.2},
    )
    plan, blockers = module.build_plan(evidence, prior_plan(), prior_proof(), contract())
    assert blockers == []
    assert plan["state"] == "PASS_SHORT_SINGLE_SCALP_SURVIVOR_6_AND_COST_R_FEASIBILITY_PLAN"
    assert plan["single_survivor_retest_allowed"] is False
    assert plan["feasibility_classification"] == "CURRENT_GEOMETRY_COST_R_INFEASIBLE"
    assert plan["next_stage"] == "R7.A4D2_SHORT_SCALP_R_DISTANCE_AND_TIMEFRAME_REDESIGN_PLAN"


def test_feasible_survivor_allows_six_cell_retest() -> None:
    module = load_module()
    evidence = audit(
        raw_distance=1.4,
        friction_by_cost={"cost_profile_0": 0.09, "cost_profile_1": 0.15, "cost_profile_2": 0.23},
        net_by_cost={"cost_profile_0": 2.0, "cost_profile_1": 1.5, "cost_profile_2": 0.7},
    )
    plan, blockers = module.build_plan(evidence, prior_plan(), prior_proof(), contract())
    assert blockers == []
    assert plan["single_survivor_retest_allowed"] is True
    assert plan["robust_geometry_feasible"] is True
    assert plan["next_stage"] == "R7.A4D2_SHORT_SINGLE_SCALP_SURVIVOR_6"


def test_negative_severe_axis_blocks_retest_even_with_low_friction() -> None:
    module = load_module()
    evidence = audit(
        raw_distance=1.4,
        friction_by_cost={"cost_profile_0": 0.09, "cost_profile_1": 0.15, "cost_profile_2": 0.23},
        net_by_cost={"cost_profile_0": 2.0, "cost_profile_1": 1.0, "cost_profile_2": -0.2},
    )
    plan, blockers = module.build_plan(evidence, prior_plan(), prior_proof(), contract())
    assert blockers == []
    assert plan["single_survivor_retest_allowed"] is False
    assert plan["feasibility_checks"]["worst_cost_axis_net_r_positive"] is False


def test_candidate_set_mismatch_fail_closes() -> None:
    module = load_module()
    evidence = audit(
        raw_distance=1.4,
        friction_by_cost={"cost_profile_0": 0.09, "cost_profile_1": 0.15, "cost_profile_2": 0.23},
        net_by_cost={"cost_profile_0": 2.0, "cost_profile_1": 1.5, "cost_profile_2": 0.7},
    )
    evidence["candidate_resolution"]["rebase_reject_candidate_ids"] = ["reject:1"]
    _, blockers = module.build_plan(evidence, prior_plan(), prior_proof(), contract())
    assert "REBASE_REJECT_SET_INVALID:1" in blockers
