#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

INPUT_PLAN_PATH = Path(
    "runtime/r7a4d2_short_strategy_family_contract_and_simple_benchmark_plan/plan_v1.json"
)
OUTPUT_PATH = Path(
    "runtime/r7a4d2_short_raw_geometry_and_simple_benchmark_execution_plan/execution_plan_v1.json"
)

ACTIVE_FAMILIES = ("trend", "mean_reversion", "scalp", "grid_range", "event_reversal")
DEFERRED_FAMILIES = ("composite",)
SUPPORTED_TIMEFRAMES = {"1m", "5m", "15m"}

BENCHMARK_PARAMETER_GRIDS: dict[str, dict[str, Any]] = {
    "trend": {
        "ema_pairs": [[5, 20], [8, 34], [12, 48]],
        "slow_slope_lookback_bars": [2, 3, 5],
        "entry_confirmation": "close_below_slow_and_fast_below_slow_and_negative_slow_slope",
        "exit_candidates": ["fast_slow_recross", "latest_confirmed_swing_high", "atr_envelope"],
    },
    "mean_reversion": {
        "fair_value_lookback_bars": [32, 64, 96],
        "entry_zscore": [1.5, 2.0, 2.5],
        "momentum_stall_bars": [1, 2, 3],
        "exit_candidates": ["fair_value", "signal_excursion_high", "timeout_from_time_to_mfe"],
    },
    "scalp": {
        "ema_pairs": [[3, 8], [5, 13]],
        "impulse_horizon_bars": [3, 5, 8],
        "minimum_excursion_to_friction_multiple": [1.0, 1.25, 1.5],
        "exit_candidates": ["micro_swing_high", "horizon_timeout", "mfe_quantile"],
    },
    "grid_range": {
        "range_lookback_bars": [32, 64, 96],
        "equal_spacing_level_count": [3, 4, 5],
        "diagnostic_max_inventory_units": 1,
        "exit_candidates": ["next_grid_level", "range_midpoint", "range_boundary_stop"],
    },
    "event_reversal": {
        "event_lookback_bars": [32, 64, 96],
        "event_quantile": [0.9, 0.95, 0.975],
        "failed_continuation_confirmation_bars": [1, 2],
        "exit_candidates": ["event_midpoint", "event_extreme_high", "timeout_from_time_to_mfe"],
    },
}

RAW_GEOMETRY_CONTRACTS: dict[str, dict[str, Any]] = {
    "trend": {
        "stop_geometry_candidates": ["latest_confirmed_swing_high", "atr_envelope_high"],
        "favorable_path_anchor": "entry_to_low_path",
    },
    "mean_reversion": {
        "stop_geometry_candidates": ["signal_bar_high", "recent_excursion_high"],
        "favorable_path_anchor": "entry_to_fair_value_and_low_path",
    },
    "scalp": {
        "stop_geometry_candidates": ["signal_bar_high", "micro_swing_high"],
        "favorable_path_anchor": "entry_to_short_horizon_low_path",
    },
    "grid_range": {
        "stop_geometry_candidates": ["range_upper_boundary", "inventory_risk_boundary"],
        "favorable_path_anchor": "entry_to_next_grid_and_range_midpoint",
    },
    "event_reversal": {
        "stop_geometry_candidates": ["event_extreme_high", "post_event_failed_continuation_high"],
        "favorable_path_anchor": "entry_to_event_midpoint_and_low_path",
    },
}


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def registry_map(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    entries = registry.get("entries")
    if not isinstance(entries, list):
        raise ValueError("REGISTRY_ENTRIES_LIST_REQUIRED")
    result: dict[str, dict[str, Any]] = {}
    for row in entries:
        if not isinstance(row, dict):
            continue
        strategy_id = str(row.get("strategy_id") or "")
        if strategy_id:
            result[strategy_id] = row
    return result


def validate_inputs(plan: dict[str, Any], contract: dict[str, Any], registry: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    if plan.get("state") != "PASS_SHORT_STRATEGY_FAMILY_CONTRACT_AND_SIMPLE_BENCHMARK_PLAN":
        blockers.append("FAMILY_BENCHMARK_PLAN_NOT_PASS")
    if int(plan.get("blocker_count", -1)) != 0:
        blockers.append("FAMILY_BENCHMARK_PLAN_BLOCKED")
    if int(plan.get("redesign_scope_count", -1)) != 5:
        blockers.append("REDESIGN_SCOPE_COUNT_INVALID")
    if int(plan.get("strategy_family_count", -1)) != 6:
        blockers.append("STRATEGY_FAMILY_COUNT_INVALID")
    if int(plan.get("benchmark_count", -1)) != 6:
        blockers.append("BENCHMARK_COUNT_INVALID")
    frozen_actions = plan.get("frozen_actions")
    if not isinstance(frozen_actions, dict) or any(
        frozen_actions.get(key) != "block"
        for key in (
            "current_36_candidate_branch",
            "current_216_cell_branch",
            "full_3600_reexecution",
            "event_replay_2880",
            "ensemble_or_s_grade_promotion",
            "shadow_start",
            "paper_live_order",
        )
    ):
        blockers.append("FROZEN_ACTIONS_NOT_BLOCKED")

    if int(contract.get("expected_strategy_count", -1)) != 25:
        blockers.append("R7A4C_STRATEGY_COUNT_INVALID")
    if int(contract.get("folds_per_regime", -1)) != 6:
        blockers.append("R7A4C_FOLDS_PER_REGIME_INVALID")
    if int(contract.get("expected_historical_segment_count", -1)) != 24:
        blockers.append("R7A4C_SEGMENT_COUNT_INVALID")
    if int(contract.get("cost_profile_count", -1)) != 3:
        blockers.append("R7A4C_COST_PROFILE_COUNT_INVALID")
    if int(contract.get("perturbation_count", -1)) != 2:
        blockers.append("R7A4C_PERTURBATION_COUNT_INVALID")
    regimes = contract.get("required_regimes")
    if not isinstance(regimes, list) or len(regimes) != 4:
        blockers.append("R7A4C_REGIME_COUNT_INVALID")

    family_contracts = plan.get("strategy_family_contracts")
    if not isinstance(family_contracts, dict):
        blockers.append("FAMILY_CONTRACTS_OBJECT_REQUIRED")
        return blockers
    if set(family_contracts) != set(ACTIVE_FAMILIES + DEFERRED_FAMILIES):
        blockers.append("FAMILY_SET_INVALID")

    registry_by_id = registry_map(registry)
    target_ids: set[str] = set()
    for family, family_contract in family_contracts.items():
        if not isinstance(family_contract, dict):
            blockers.append(f"FAMILY_CONTRACT_INVALID:{family}")
            continue
        strategy_ids = family_contract.get("strategy_ids")
        timeframes = family_contract.get("provisional_timeframe_candidates")
        if not isinstance(strategy_ids, list) or not strategy_ids:
            blockers.append(f"FAMILY_STRATEGY_IDS_INVALID:{family}")
            continue
        if not isinstance(timeframes, list) or not timeframes:
            blockers.append(f"FAMILY_TIMEFRAMES_INVALID:{family}")
            continue
        if family in ACTIVE_FAMILIES and any(str(value) not in SUPPORTED_TIMEFRAMES for value in timeframes):
            blockers.append(f"ACTIVE_FAMILY_TIMEFRAME_UNSUPPORTED:{family}")
        if family in DEFERRED_FAMILIES and timeframes != ["component_native_only"]:
            blockers.append(f"DEFERRED_FAMILY_TIMEFRAME_INVALID:{family}")
        if family_contract.get("universal_rr_allowed") is not False:
            blockers.append(f"UNIVERSAL_RR_NOT_DISABLED:{family}")
        if family_contract.get("fixed_rr_before_raw_geometry_allowed") is not False:
            blockers.append(f"FIXED_RR_BEFORE_GEOMETRY_NOT_DISABLED:{family}")
        if family_contract.get("benchmark_required") is not True:
            blockers.append(f"BENCHMARK_NOT_REQUIRED:{family}")
        for strategy_id_value in strategy_ids:
            strategy_id = str(strategy_id_value)
            target_ids.add(strategy_id)
            entry = registry_by_id.get(strategy_id)
            if entry is None:
                blockers.append(f"REGISTRY_STRATEGY_MISSING:{strategy_id}")
                continue
            if entry.get("active_allowed") is not False:
                blockers.append(f"REGISTRY_STRATEGY_ACTIVE:{strategy_id}")
            canonical = entry.get("canonical_engine")
            if not isinstance(canonical, dict):
                blockers.append(f"CANONICAL_ENGINE_MISSING:{strategy_id}")
            elif not canonical.get("implementation_path") or not canonical.get("callable"):
                blockers.append(f"CANONICAL_BINDING_INCOMPLETE:{strategy_id}")
    if len(target_ids) != 12:
        blockers.append(f"TARGET_STRATEGY_COUNT_INVALID:{len(target_ids)}")
    return list(dict.fromkeys(blockers))


def build_lanes(plan: dict[str, Any], registry: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    family_contracts = plan["strategy_family_contracts"]
    registry_by_id = registry_map(registry)
    strategy_lanes: list[dict[str, Any]] = []
    benchmark_lanes: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []

    for family in ACTIVE_FAMILIES:
        contract = family_contracts[family]
        timeframes = [str(value) for value in contract["provisional_timeframe_candidates"]]
        benchmark_id = str(contract["benchmark_id"])
        for strategy_id_value in contract["strategy_ids"]:
            strategy_id = str(strategy_id_value)
            registry_entry = registry_by_id[strategy_id]
            canonical = registry_entry["canonical_engine"]
            for timeframe in timeframes:
                strategy_lanes.append({
                    "lane_id": f"strategy:{strategy_id}:{timeframe}",
                    "lane_type": "strategy",
                    "family": family,
                    "strategy_id": strategy_id,
                    "timeframe": timeframe,
                    "implementation_path": canonical["implementation_path"],
                    "callable": canonical["callable"],
                    "source_sha256": canonical.get("source_sha256"),
                    "raw_geometry_contract": RAW_GEOMETRY_CONTRACTS[family],
                    "universal_rr_allowed": False,
                })
        for timeframe in timeframes:
            benchmark_lanes.append({
                "lane_id": f"benchmark:{benchmark_id}:{timeframe}",
                "lane_type": "benchmark",
                "family": family,
                "benchmark_id": benchmark_id,
                "timeframe": timeframe,
                "parameter_grid": BENCHMARK_PARAMETER_GRIDS[family],
                "parameter_selection_scope": "discovery_only",
                "raw_geometry_contract": RAW_GEOMETRY_CONTRACTS[family],
                "universal_rr_allowed": False,
            })

    for family in DEFERRED_FAMILIES:
        contract = family_contracts[family]
        for strategy_id_value in contract["strategy_ids"]:
            deferred.append({
                "strategy_id": str(strategy_id_value),
                "family": family,
                "reason": "COMPONENT_FAMILY_SURVIVORS_REQUIRED_BEFORE_COMPOSITION",
                "execution_allowed_now": False,
                "benchmark_id": contract["benchmark_id"],
            })
    strategy_lanes.sort(key=lambda row: row["lane_id"])
    benchmark_lanes.sort(key=lambda row: row["lane_id"])
    deferred.sort(key=lambda row: row["strategy_id"])
    return strategy_lanes, benchmark_lanes, deferred


def build_execution_plan(plan: dict[str, Any], contract: dict[str, Any], registry: dict[str, Any], lineage: dict[str, str]) -> dict[str, Any]:
    strategy_lanes, benchmark_lanes, deferred = build_lanes(plan, registry)
    all_lanes = strategy_lanes + benchmark_lanes
    regime_count = len(contract["required_regimes"])
    folds_per_regime = int(contract["folds_per_regime"])
    discovery_folds_per_regime = folds_per_regime // 2
    validation_folds_per_regime = folds_per_regime - discovery_folds_per_regime
    cost_profiles = int(contract["cost_profile_count"])
    perturbations = int(contract["perturbation_count"])
    historical_segments = int(contract["expected_historical_segment_count"])
    raw_geometry_scans = len(all_lanes) * historical_segments
    discovery_stress_runs = (
        len(all_lanes)
        * regime_count
        * discovery_folds_per_regime
        * cost_profiles
        * perturbations
    )
    maximum_validation_stress_runs = (
        len(all_lanes)
        * regime_count
        * validation_folds_per_regime
        * cost_profiles
        * perturbations
    )

    return {
        "schema": "r7a4d2_short_raw_geometry_and_simple_benchmark_execution_plan_v1",
        "official_stage": "R7.A4D2_SHORT_RAW_GEOMETRY_AND_SIMPLE_BENCHMARK_EXECUTION_PLAN",
        "state": "PASS_SHORT_RAW_GEOMETRY_AND_SIMPLE_BENCHMARK_EXECUTION_PLAN",
        "blocker_count": 0,
        "blockers": [],
        "input_lineage": lineage,
        "strategy_pool_count": 12,
        "active_strategy_count": 11,
        "deferred_strategy_count": len(deferred),
        "deferred_strategies": deferred,
        "active_family_count": len(ACTIVE_FAMILIES),
        "deferred_family_count": len(DEFERRED_FAMILIES),
        "strategy_timeframe_lane_count": len(strategy_lanes),
        "benchmark_timeframe_lane_count": len(benchmark_lanes),
        "total_execution_lane_count": len(all_lanes),
        "strategy_lanes": strategy_lanes,
        "benchmark_lanes": benchmark_lanes,
        "data_contract": {
            "selected_manifest_path": contract["selected_manifest_path"],
            "scenario_plan_path": contract["scenario_plan_path"],
            "required_regimes": contract["required_regimes"],
            "segment_bars": contract["segment_bars"],
            "historical_segment_count": historical_segments,
            "folds_per_regime": folds_per_regime,
            "fold_partition": {
                "mode": "chronological_rank_within_each_regime",
                "discovery_fold_count_per_regime": discovery_folds_per_regime,
                "validation_fold_count_per_regime": validation_folds_per_regime,
                "discovery_role": "parameter_timeframe_and_exit_candidate_selection_only",
                "validation_role": "locked_disjoint_economic_comparison",
                "future_pnl_selection_allowed": False,
            },
            "cost_profile_count": cost_profiles,
            "timing_perturbation_count": perturbations,
            "same_segments_for_strategy_and_benchmark": True,
            "same_costs_for_strategy_and_benchmark": True,
            "same_timing_for_strategy_and_benchmark": True,
            "same_collision_policy_for_strategy_and_benchmark": True,
            "collision_policy": "conservative_stop_first",
            "fill_policy": "next_bar_or_later",
        },
        "phase_plan": [
            {
                "phase": "A_RAW_SIGNAL_AND_GEOMETRY",
                "target_scan_count": raw_geometry_scans,
                "scope": "all_strategy_and_benchmark_lanes_x_all_24_frozen_segments",
                "universal_rr_applied": False,
                "required_measurements": [
                    "raw_signal_count",
                    "entry_price_and_timestamp",
                    "structural_stop_distance_pct_by_candidate",
                    "round_trip_friction_pct_by_cost_profile",
                    "friction_r_by_stop_candidate",
                    "full_forward_mfe_pct_until_segment_end",
                    "full_forward_mae_pct_until_segment_end",
                    "time_to_mfe_bars",
                    "time_to_mae_bars",
                    "available_gross_payoff_ratio",
                    "symbol_regime_and_timeframe_concentration",
                ],
            },
            {
                "phase": "B_DISCOVERY_EXIT_AND_PARAMETER_LOCK",
                "scope": "discovery_folds_only",
                "benchmark_grid_selection_allowed": True,
                "strategy_source_mutation_allowed": False,
                "exit_candidate_source": "raw_geometry_mfe_mae_friction_and_time_to_mfe_quantiles",
                "mfe_quantiles": [0.5, 0.7, 0.85],
                "mae_quantiles": [0.5, 0.7, 0.85],
                "timeout_quantiles": [0.5, 0.75, 0.9],
                "universal_rr_allowed": False,
                "locked_before_validation": True,
            },
            {
                "phase": "C_DISCOVERY_ECONOMIC_STRESS",
                "target_run_count": discovery_stress_runs,
                "scope": "all_36_lanes_x_12_discovery_segments_x_3_costs_x_2_timing_perturbations",
                "required_metrics": plan["economic_comparison_metrics"],
            },
            {
                "phase": "D_DISJOINT_VALIDATION",
                "maximum_run_count": maximum_validation_stress_runs,
                "scope": "discovery_positive_and_benchmark_comparable_lanes_only",
                "locked_parameters_required": True,
                "reselection_on_validation_allowed": False,
            },
            {
                "phase": "E_SURVIVOR_AND_RESIDUAL_AUDIT",
                "survival_rule": "positive_net_expectancy_and_beat_family_benchmark_in_at_least_two_of_net_pnl_profit_factor_max_drawdown_on_discovery_and_validation",
                "minimum_independent_trade_evidence": "SSOT_REQUIRED_BEFORE_PROMOTION",
                "insufficient_evidence_action": "hold",
                "candidate_shortfall_is_error": False,
                "residual_issue_backlog_required": True,
            },
        ],
        "raw_geometry_scan_target": raw_geometry_scans,
        "discovery_stress_run_target": discovery_stress_runs,
        "maximum_validation_stress_run_target": maximum_validation_stress_runs,
        "maximum_total_stress_run_target": discovery_stress_runs + maximum_validation_stress_runs,
        "fixed_candidate_quota_allowed": False,
        "universal_rr_allowed": False,
        "legacy_loss_cap_r_reference_only": 0.75,
        "legacy_full_tp_r_reference_only": 2.5,
        "strategy_source_mutation_allowed": False,
        "registry_mutation_allowed": False,
        "config_mutation_allowed": False,
        "router_mutation_allowed": False,
        "service_mutation_allowed": False,
        "shadow_start_allowed": False,
        "paper_live_order_allowed": False,
        "full_3600_reexecution_allowed": False,
        "event_replay_2880_allowed": False,
        "current_36_candidate_branch_allowed": False,
        "current_216_cell_branch_allowed": False,
        "next_stage": "R7.A4D2_SHORT_RAW_GEOMETRY_AND_SIMPLE_BENCHMARK_EXECUTION",
    }


def self_test() -> int:
    fake_plan = {
        "state": "PASS_SHORT_STRATEGY_FAMILY_CONTRACT_AND_SIMPLE_BENCHMARK_PLAN",
        "blocker_count": 0,
        "redesign_scope_count": 5,
        "strategy_family_count": 6,
        "benchmark_count": 6,
        "frozen_actions": {
            "current_36_candidate_branch": "block",
            "current_216_cell_branch": "block",
            "full_3600_reexecution": "block",
            "event_replay_2880": "block",
            "ensemble_or_s_grade_promotion": "block",
            "shadow_start": "block",
            "paper_live_order": "block",
        },
        "strategy_family_contracts": {
            "trend": {"strategy_ids": ["a", "b", "c"], "provisional_timeframe_candidates": ["5m", "15m"], "benchmark_id": "bt", "universal_rr_allowed": False, "fixed_rr_before_raw_geometry_allowed": False, "benchmark_required": True},
            "mean_reversion": {"strategy_ids": ["d", "e", "f"], "provisional_timeframe_candidates": ["1m", "5m", "15m"], "benchmark_id": "bm", "universal_rr_allowed": False, "fixed_rr_before_raw_geometry_allowed": False, "benchmark_required": True},
            "scalp": {"strategy_ids": ["g", "h"], "provisional_timeframe_candidates": ["1m", "5m"], "benchmark_id": "bs", "universal_rr_allowed": False, "fixed_rr_before_raw_geometry_allowed": False, "benchmark_required": True},
            "grid_range": {"strategy_ids": ["i"], "provisional_timeframe_candidates": ["1m", "5m"], "benchmark_id": "bg", "universal_rr_allowed": False, "fixed_rr_before_raw_geometry_allowed": False, "benchmark_required": True},
            "event_reversal": {"strategy_ids": ["j", "k"], "provisional_timeframe_candidates": ["1m", "5m"], "benchmark_id": "be", "universal_rr_allowed": False, "fixed_rr_before_raw_geometry_allowed": False, "benchmark_required": True},
            "composite": {"strategy_ids": ["l"], "provisional_timeframe_candidates": ["component_native_only"], "benchmark_id": "bc", "universal_rr_allowed": False, "fixed_rr_before_raw_geometry_allowed": False, "benchmark_required": True},
        },
        "economic_comparison_metrics": ["net_pnl_after_cost_pct", "profit_factor", "expectancy_r", "max_drawdown_pct"],
    }
    fake_contract = {
        "expected_strategy_count": 25,
        "folds_per_regime": 6,
        "expected_historical_segment_count": 24,
        "cost_profile_count": 3,
        "perturbation_count": 2,
        "required_regimes": ["trend_up", "range", "trend_down", "shock_recovery"],
        "selected_manifest_path": "selected.json",
        "scenario_plan_path": "scenario.json",
        "segment_bars": 320,
    }
    entries = []
    for strategy_id in "abcdefghijkl":
        entries.append({
            "strategy_id": strategy_id,
            "active_allowed": False,
            "canonical_engine": {
                "implementation_path": f"backend/strategies/{strategy_id}.py",
                "callable": f"{strategy_id}.decide",
                "source_sha256": strategy_id * 64,
            },
        })
    fake_registry = {"entries": entries}
    assert validate_inputs(fake_plan, fake_contract, fake_registry) == []
    execution = build_execution_plan(fake_plan, fake_contract, fake_registry, {})
    assert execution["strategy_timeframe_lane_count"] == 25
    assert execution["benchmark_timeframe_lane_count"] == 11
    assert execution["total_execution_lane_count"] == 36
    assert execution["raw_geometry_scan_target"] == 864
    assert execution["discovery_stress_run_target"] == 2592
    assert execution["maximum_validation_stress_run_target"] == 2592
    assert execution["deferred_strategy_count"] == 1
    print("STATE=PASS_SHORT_RAW_GEOMETRY_BENCHMARK_EXECUTION_PLAN_SELF_TEST")
    print("RC=0")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--contract", required=False)
    parser.add_argument("--registry", required=False)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.contract or not args.registry:
        print("STATE=HOLD_SHORT_RAW_GEOMETRY_AND_SIMPLE_BENCHMARK_EXECUTION_PLAN_INPUT")
        print("BLOCKER_COUNT=1")
        print('BLOCKERS=["CONTRACT_AND_REGISTRY_REQUIRED"]')
        print("RC=2")
        return 2

    root = Path(args.root).resolve()
    input_plan_path = root / INPUT_PLAN_PATH
    contract_path = Path(args.contract).resolve()
    registry_path = Path(args.registry).resolve()
    required_runtime_paths = [
        input_plan_path,
        root / "runtime/r7a4c_historical_simulation_input_lineage/selected_input_manifest_v1.json",
        root / "runtime/r7a4c_historical_simulation_input_lineage/scenario_plan_3600_v1.json",
        root / "runtime/r7a4_simulation_replay_input_freeze/frozen_input_manifest_v1.json",
    ]
    missing = [str(path) for path in required_runtime_paths if not path.is_file()]
    if missing:
        print("STATE=HOLD_SHORT_RAW_GEOMETRY_AND_SIMPLE_BENCHMARK_EXECUTION_PLAN_INPUT")
        print("BLOCKER_COUNT=" + str(len(missing)))
        print("BLOCKERS=" + json.dumps([f"REQUIRED_EVIDENCE_MISSING:{path}" for path in missing], ensure_ascii=False))
        print("RC=2")
        return 2

    plan = load_json(input_plan_path)
    contract = load_json(contract_path)
    registry = load_json(registry_path)
    blockers = validate_inputs(plan, contract, registry)
    if blockers:
        print("STATE=HOLD_SHORT_RAW_GEOMETRY_AND_SIMPLE_BENCHMARK_EXECUTION_PLAN_INPUT")
        print("BLOCKER_COUNT=" + str(len(blockers)))
        print("BLOCKERS=" + json.dumps(blockers, ensure_ascii=False))
        print("NEXT_STAGE=R7.A4D2_SHORT_RAW_GEOMETRY_AND_SIMPLE_BENCHMARK_EXECUTION_PLAN")
        print("RC=2")
        return 2

    lineage = {
        "family_benchmark_plan_path": str(INPUT_PLAN_PATH),
        "family_benchmark_plan_sha256": file_sha256(input_plan_path),
        "r7a4c_contract_sha256": file_sha256(contract_path),
        "canonical_registry_sha256": file_sha256(registry_path),
        "selected_manifest_sha256": file_sha256(required_runtime_paths[1]),
        "scenario_plan_sha256": file_sha256(required_runtime_paths[2]),
        "frozen_manifest_sha256": file_sha256(required_runtime_paths[3]),
    }
    execution = build_execution_plan(plan, contract, registry, lineage)
    output = root / OUTPUT_PATH
    atomic_json(output, execution)

    print("STATE=" + execution["state"])
    print("BLOCKER_COUNT=0")
    print("STRATEGY_POOL_COUNT=" + str(execution["strategy_pool_count"]))
    print("ACTIVE_STRATEGY_COUNT=" + str(execution["active_strategy_count"]))
    print("DEFERRED_STRATEGY_COUNT=" + str(execution["deferred_strategy_count"]))
    print("STRATEGY_TIMEFRAME_LANE_COUNT=" + str(execution["strategy_timeframe_lane_count"]))
    print("BENCHMARK_TIMEFRAME_LANE_COUNT=" + str(execution["benchmark_timeframe_lane_count"]))
    print("TOTAL_EXECUTION_LANE_COUNT=" + str(execution["total_execution_lane_count"]))
    print("RAW_GEOMETRY_SCAN_TARGET=" + str(execution["raw_geometry_scan_target"]))
    print("DISCOVERY_STRESS_RUN_TARGET=" + str(execution["discovery_stress_run_target"]))
    print("MAXIMUM_VALIDATION_STRESS_RUN_TARGET=" + str(execution["maximum_validation_stress_run_target"]))
    print("MAXIMUM_TOTAL_STRESS_RUN_TARGET=" + str(execution["maximum_total_stress_run_target"]))
    print("FIXED_CANDIDATE_QUOTA_ALLOWED=false")
    print("UNIVERSAL_RR_ALLOWED=false")
    print("COMPOSITE_EXECUTION_ALLOWED_NOW=false")
    print("STRATEGY_SOURCE_MUTATION_ALLOWED=false")
    print("SHADOW_START_ALLOWED=false")
    print("PAPER_LIVE_ORDER_ALLOWED=false")
    print("PLAN_JSON=" + str(output))
    print("NEXT_STAGE=" + execution["next_stage"])
    print("RC=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
