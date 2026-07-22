from __future__ import annotations

import importlib.util
import os
from pathlib import Path


def load_module():
    path = Path(os.environ["R7A4D2_SCALP_TIMEFRAME_REDESIGN"])
    spec = importlib.util.spec_from_file_location("scalp_timeframe_redesign", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def feasibility() -> dict:
    return {
        "state": "PASS_SHORT_SINGLE_SCALP_SURVIVOR_6_AND_COST_R_FEASIBILITY_PLAN",
        "blocker_count": 0,
        "next_stage": "R7.A4D2_SHORT_SCALP_R_DISTANCE_AND_TIMEFRAME_REDESIGN_PLAN",
        "single_survivor_retest_allowed": False,
        "current_geometry_feasible": False,
        "feasibility_classification": "CURRENT_GEOMETRY_COST_R_INFEASIBLE",
        "protected_mutation_path_count": 0,
        "single_survivor_candidate_id": "diagnostic:scalp_snap:606",
    }


def frozen_manifest() -> dict:
    return {
        "state": "PASS",
        "category_inputs": {
            "market_data": [
                {"path": "data/BTCUSDT_1m.json", "sha256": "a" * 64},
                {"path": "data/ETHUSDT_1m.json", "sha256": "b" * 64},
                {"path": "data/SOLUSDT_1m.json", "sha256": "c" * 64},
            ]
        },
    }


def a4c_contract() -> dict:
    return {"expected_strategy_count": 25}


def a4d_contract() -> dict:
    return {
        "expected_strategy_count": 25,
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


def inventory(*, include_15m: bool = True) -> list[dict]:
    rows = [
        {
            "source_path": "data/BTCUSDT_1m.json",
            "source_sha256": "a" * 64,
            "row_count": 10000,
            "symbol": "BTCUSDT",
            "native_timeframe": "1m",
            "timestamp_ready": True,
            "derivable_timeframes": ["5m", "15m"] if include_15m else ["5m"],
        },
        {
            "source_path": "data/ETHUSDT_1m.json",
            "source_sha256": "b" * 64,
            "row_count": 10000,
            "symbol": "ETHUSDT",
            "native_timeframe": "1m",
            "timestamp_ready": True,
            "derivable_timeframes": ["5m", "15m"] if include_15m else ["5m"],
        },
        {
            "source_path": "data/SOLUSDT_1m.json",
            "source_sha256": "c" * 64,
            "row_count": 10000,
            "symbol": "SOLUSDT",
            "native_timeframe": "1m",
            "timestamp_ready": True,
            "derivable_timeframes": ["5m", "15m"] if include_15m else ["5m"],
        },
    ]
    return rows


def test_required_distance_is_derived_from_cost_contract() -> None:
    module = load_module()
    assert round(module.required_raw_distance_pct(10.0, 6.0, 0.33), 6) == round(0.32 / 0.33, 6)
    assert round(module.required_raw_distance_pct(10.0, 6.0, 0.25), 6) == 1.28


def test_ready_plan_builds_three_architectures_and_216_cells() -> None:
    module = load_module()
    plan, blockers = module.build_plan(
        feasibility(),
        frozen_manifest(),
        a4c_contract(),
        a4d_contract(),
        inventory(),
        [],
    )
    assert blockers == []
    assert plan["state"] == "PASS_SHORT_SCALP_R_DISTANCE_AND_TIMEFRAME_REDESIGN_PLAN"
    assert plan["plan_ready"] is True
    assert plan["current_1m_scalp_execution_allowed"] is False
    assert plan["architecture_count"] == 3
    assert plan["target_candidate_count"] == 36
    assert plan["target_execution_cell_count"] == 216
    assert plan["next_stage"] == "R7.A4D2_SHORT_SCALP_TIMEFRAME_CANDIDATE_DISCOVERY_36"
    assert all(row["future_outcome_selection_allowed"] is False for row in plan["architectures"])


def test_missing_15m_lineage_routes_to_coverage_closure_without_input_failure() -> None:
    module = load_module()
    plan, blockers = module.build_plan(
        feasibility(),
        frozen_manifest(),
        a4c_contract(),
        a4d_contract(),
        inventory(include_15m=False),
        [],
    )
    assert blockers == []
    assert plan["state"] == "PASS_SHORT_SCALP_R_DISTANCE_AND_TIMEFRAME_REDESIGN_PLAN"
    assert plan["plan_ready"] is False
    assert "TF15_MARKET_LINEAGE_UNAVAILABLE" in plan["coverage_flags"]
    assert plan["next_stage"] == "R7.A4D2_SHORT_SCALP_TIMEFRAME_MARKET_COVERAGE_CLOSURE"


def test_prior_geometry_must_be_infeasible_before_redesign() -> None:
    module = load_module()
    prior = feasibility()
    prior["current_geometry_feasible"] = True
    _, blockers = module.build_plan(
        prior,
        frozen_manifest(),
        a4c_contract(),
        a4d_contract(),
        inventory(),
        [],
    )
    assert "CURRENT_GEOMETRY_UNEXPECTEDLY_FEASIBLE" in blockers


def test_rejected_frozen_source_fail_closes() -> None:
    module = load_module()
    _, blockers = module.build_plan(
        feasibility(),
        frozen_manifest(),
        a4c_contract(),
        a4d_contract(),
        inventory(),
        [{"path": "data/bad.json", "reason": "FROZEN_SHA_MISMATCH"}],
    )
    assert "FROZEN_MARKET_SOURCE_REJECTED:1" in blockers
