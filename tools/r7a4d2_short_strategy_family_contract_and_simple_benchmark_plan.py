#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any


AUDIT_PATH = Path(
    "runtime/r7a4d2_short_architecture_economic_alignment_audit/alignment_audit_v1.json"
)
OUTPUT_PATH = Path(
    "runtime/r7a4d2_short_strategy_family_contract_and_simple_benchmark_plan/plan_v1.json"
)

EXPECTED_ROOT_CAUSES = {
    "TARGET_SELECTION_SEMANTIC_NOT_ECONOMIC",
    "UNIVERSAL_RR_ACROSS_HETEROGENEOUS_FAMILIES",
    "NATIVE_TIMEFRAME_CONTRACT_MISSING",
    "SIMPLE_BENCHMARK_ABSENT",
    "CANDIDATE_COUNT_OBJECTIVE_MISALIGNED",
}

FAMILY_CONTRACTS: dict[str, dict[str, Any]] = {
    "composite": {
        "strategy_ids": ["alpha_combo"],
        "economic_hypothesis": "component strategies add value only when their independently proven family edges agree",
        "provisional_timeframe_candidates": ["component_native_only"],
        "benchmark_id": "benchmark_best_component_or_flat",
        "raw_geometry_source": "component_specific_structure_before_composition",
        "exit_design_mode": "component_weighted_after_independent_family_validation",
        "diagnostic_regimes": ["component_defined"],
    },
    "trend": {
        "strategy_ids": ["anchor_vwap_trend", "keltner_trend", "obv_trend"],
        "economic_hypothesis": "persistent downside direction continues after a simple trend confirmation",
        "provisional_timeframe_candidates": ["5m", "15m"],
        "benchmark_id": "benchmark_ema_trend_short",
        "raw_geometry_source": "latest_confirmed_swing_high_or_atr_envelope",
        "exit_design_mode": "mfe_mae_and_time_to_mfe_quantile_candidates",
        "diagnostic_regimes": ["trend_down"],
    },
    "mean_reversion": {
        "strategy_ids": ["bb_revert", "range_fade", "vwap_revert"],
        "economic_hypothesis": "upward displacement from a local fair-value anchor mean-reverts after exhaustion",
        "provisional_timeframe_candidates": ["1m", "5m", "15m"],
        "benchmark_id": "benchmark_vwap_zscore_revert_short",
        "raw_geometry_source": "recent_excursion_high_and_fair_value_distance",
        "exit_design_mode": "fair_value_target_plus_tail_loss_distribution",
        "diagnostic_regimes": ["range", "shock_recovery_observer"],
    },
    "scalp": {
        "strategy_ids": ["ema_ribbon_scalp", "scalp_snap"],
        "economic_hypothesis": "short-horizon downside impulse exceeds round-trip friction before mean reversion",
        "provisional_timeframe_candidates": ["1m", "5m"],
        "benchmark_id": "benchmark_fast_ema_impulse_short",
        "raw_geometry_source": "micro_swing_high_and_realized_short_horizon_excursion",
        "exit_design_mode": "friction_first_horizon_specific_mfe_mae_candidates",
        "diagnostic_regimes": ["trend_down", "high_momentum"],
    },
    "grid_range": {
        "strategy_ids": ["grid_rebalance"],
        "economic_hypothesis": "repeated range excursions can be harvested after fees without directional trend exposure",
        "provisional_timeframe_candidates": ["1m", "5m"],
        "benchmark_id": "benchmark_equal_spacing_range_grid_short",
        "raw_geometry_source": "range_boundary_and_grid_spacing_distribution",
        "exit_design_mode": "spacing_cost_inventory_risk_candidates",
        "diagnostic_regimes": ["range"],
    },
    "event_reversal": {
        "strategy_ids": ["liquidity_sweep", "vol_spike_fade"],
        "economic_hypothesis": "a discrete upside liquidity or volume shock reverses after failed continuation",
        "provisional_timeframe_candidates": ["1m", "5m"],
        "benchmark_id": "benchmark_extreme_bar_fade_short",
        "raw_geometry_source": "event_extreme_high_and_post_event_reversion_path",
        "exit_design_mode": "event_conditioned_mfe_mae_and_timeout_candidates",
        "diagnostic_regimes": ["range", "shock_recovery"],
    },
}

BENCHMARKS: dict[str, dict[str, Any]] = {
    "benchmark_ema_trend_short": {
        "family": "trend",
        "rule": "short when close is below a slow EMA and fast EMA is below slow EMA with negative slow-EMA slope; exit on fast/slow recross or structural stop",
        "complexity": "simple",
    },
    "benchmark_vwap_zscore_revert_short": {
        "family": "mean_reversion",
        "rule": "short an upper fair-value deviation only after momentum stalls; exit at fair value or structural event high stop",
        "complexity": "simple",
    },
    "benchmark_fast_ema_impulse_short": {
        "family": "scalp",
        "rule": "short a fast downside EMA impulse only when projected excursion exceeds measured round-trip friction; exit by horizon timeout or micro structure",
        "complexity": "simple",
    },
    "benchmark_equal_spacing_range_grid_short": {
        "family": "grid_range",
        "rule": "one-direction diagnostic grid at equal range spacing with bounded inventory and fee-aware spacing",
        "complexity": "simple",
    },
    "benchmark_extreme_bar_fade_short": {
        "family": "event_reversal",
        "rule": "short a statistically extreme upside bar only after the next bar fails to continue; exit at event midpoint or event high stop",
        "complexity": "simple",
    },
    "benchmark_best_component_or_flat": {
        "family": "composite",
        "rule": "use the best independently validated component-family benchmark; remain flat when no component qualifies",
        "complexity": "simple",
    },
}


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temp = Path(handle.name)
    os.replace(temp, path)


def validate_audit(audit: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if audit.get("state") != "PASS_SHORT_ARCHITECTURE_ECONOMIC_ALIGNMENT_AUDIT":
        errors.append("ALIGNMENT_AUDIT_NOT_PASS")
    if int(audit.get("blocker_count", -1)) != 0:
        errors.append("ALIGNMENT_AUDIT_BLOCKED")
    if audit.get("audit_completed") is not True:
        errors.append("ALIGNMENT_AUDIT_NOT_COMPLETED")
    if audit.get("architecture_alignment_pass") is not False:
        errors.append("ALIGNMENT_FAILURE_NOT_REPRODUCED")
    if audit.get("architecture_decision") != "BLOCK_REBUILD_REQUIRED":
        errors.append("ARCHITECTURE_DECISION_INVALID")
    causes = {
        str(row.get("id") or "")
        for row in audit.get("primary_root_causes", [])
        if isinstance(row, dict)
    }
    if causes != EXPECTED_ROOT_CAUSES:
        errors.append("ROOT_CAUSE_SET_MISMATCH")
    if int(audit.get("short_target_strategy_count", -1)) != 12:
        errors.append("SHORT_TARGET_COUNT_INVALID")
    if int(audit.get("diagnostic_family_count", -1)) != 6:
        errors.append("FAMILY_COUNT_INVALID")
    return errors


def build_plan(audit: dict[str, Any]) -> dict[str, Any]:
    target_ids = sorted(str(value) for value in audit.get("short_target_strategy_ids", []))
    family_ids = sorted(
        strategy_id
        for contract in FAMILY_CONTRACTS.values()
        for strategy_id in contract["strategy_ids"]
    )
    if target_ids != family_ids:
        raise ValueError("FAMILY_STRATEGY_SET_MISMATCH")

    family_contracts: dict[str, Any] = {}
    for family, contract in FAMILY_CONTRACTS.items():
        item = dict(contract)
        item.update({
            "contract_status": "PROVISIONAL_DIAGNOSTIC_NOT_PROMOTION_SSOT",
            "native_timeframe_selection_method": "same_data_same_cost_discovery_then_disjoint_validation",
            "universal_rr_allowed": False,
            "fixed_rr_before_raw_geometry_allowed": False,
            "benchmark_required": True,
            "strategy_source_mutation_allowed": False,
        })
        family_contracts[family] = item

    plan = {
        "schema": "r7a4d2_short_strategy_family_contract_and_simple_benchmark_plan_v1",
        "official_stage": "R7.A4D2_SHORT_STRATEGY_FAMILY_CONTRACT_AND_SIMPLE_BENCHMARK_PLAN",
        "state": "PASS_SHORT_STRATEGY_FAMILY_CONTRACT_AND_SIMPLE_BENCHMARK_PLAN",
        "blocker_count": 0,
        "blockers": [],
        "redesign_scope_count": 5,
        "redesign_scope": [
            {
                "root_cause_id": "TARGET_SELECTION_SEMANTIC_NOT_ECONOMIC",
                "replacement": "UNPROVEN_POOL_TO_ECONOMIC_SURVIVOR",
                "contract": {
                    "initial_pool_strategy_count": 12,
                    "initial_pool_strategy_ids": target_ids,
                    "fixed_target_count_allowed": False,
                    "selection_basis": "same_data_same_cost_family_benchmark_dominance",
                    "survival_rule": "positive net expectancy and beat the relevant simple benchmark in at least two of net_pnl, profit_factor, and max_drawdown on discovery and disjoint validation",
                    "insufficient_trade_evidence_action": "hold",
                    "promotion_before_independent_validation_allowed": False,
                },
            },
            {
                "root_cause_id": "UNIVERSAL_RR_ACROSS_HETEROGENEOUS_FAMILIES",
                "replacement": "RAW_GEOMETRY_THEN_FAMILY_EXIT_CANDIDATES",
                "contract": {
                    "legacy_reference_loss_cap_r": 0.75,
                    "legacy_reference_full_tp_r": 2.5,
                    "legacy_reference_is_universal_gate": False,
                    "measurement_order": [
                        "raw structural stop distance",
                        "round-trip friction in R",
                        "MFE and MAE distributions",
                        "time to MFE and timeout distribution",
                        "family-specific exit candidate generation",
                        "disjoint validation",
                    ],
                    "absolute_exit_threshold_source": "SSOT_REQUIRED_FOR_PROMOTION",
                },
            },
            {
                "root_cause_id": "NATIVE_TIMEFRAME_CONTRACT_MISSING",
                "replacement": "EXPLICIT_FAMILY_AND_STRATEGY_TIMEFRAME_CONTRACT",
                "contract": {
                    "family_contracts": family_contracts,
                    "registry_mutation_allowed_now": False,
                    "registry_binding_gate": "timeframe winner passes discovery and disjoint validation against family benchmark",
                    "same_strategy_code_on_different_timeframes_treated_as_same_strategy": False,
                },
            },
            {
                "root_cause_id": "SIMPLE_BENCHMARK_ABSENT",
                "replacement": "SAME_DATA_SAME_COST_SIMPLE_BENCHMARK_FLOOR",
                "contract": {
                    "benchmarks": BENCHMARKS,
                    "flat_baseline_retained": True,
                    "same_segments_required": True,
                    "same_cost_profiles_required": True,
                    "same_timing_perturbations_required": True,
                    "same_collision_policy_required": True,
                    "broker_bot_direct_comparison_status": "UNSUPPORTED_UNTIL_USER_EXPORTS_COMPARABLE_BOT_LOGS",
                    "complex_strategy_must_add_value": True,
                },
            },
            {
                "root_cause_id": "CANDIDATE_COUNT_OBJECTIVE_MISALIGNED",
                "replacement": "EDGE_FIRST_SEQUENTIAL_EVIDENCE_POLICY",
                "contract": {
                    "fixed_candidate_quota_allowed": False,
                    "candidate_collection_order": "chronological_source_symbol_round_robin",
                    "future_pnl_selection_allowed": False,
                    "collection_stop_conditions": [
                        "SSOT minimum independent trade evidence reached",
                        "available frozen data exhausted",
                        "family benchmark dominance becomes impossible under remaining evidence",
                    ],
                    "candidate_shortfall_is_error": False,
                    "candidate_shortfall_classification": "INSUFFICIENT_EDGE_OR_DATA",
                    "selected_candidate_count_is_objective": False,
                },
            },
        ],
        "strategy_family_count": len(FAMILY_CONTRACTS),
        "strategy_family_contracts": family_contracts,
        "benchmark_count": len(BENCHMARKS),
        "benchmark_suite": BENCHMARKS,
        "economic_comparison_metrics": [
            "net_pnl_after_cost_pct",
            "profit_factor",
            "expectancy_r",
            "max_drawdown_pct",
            "realized_payoff_ratio",
            "friction_r",
            "trade_count",
            "symbol_and_regime_concentration",
        ],
        "execution_sequence": [
            "freeze current 12 strategies as an unproven pool",
            "run raw signal and raw geometry measurement without universal RR",
            "run family simple benchmarks on identical data and costs",
            "select native timeframe per strategy by discovery only",
            "derive family exit candidates from raw MFE MAE friction and time exposure",
            "run disjoint validation for strategy and benchmark",
            "retain only benchmark-dominant strategies",
            "then audit residual architecture and runner problems before any ensemble",
        ],
        "residual_issue_backlog": [
            {
                "id": "ADMISSION_AND_REGIME_ATTRITION",
                "evidence": "11 of 12 strategies produced no closed short trade evidence; many candidates were blocked before execution",
                "sequence": "after raw family benchmark measurement",
            },
            {
                "id": "SAMPLE_SIZE_AND_CONCENTRATION",
                "evidence": "the only current positive result is one grid_rebalance trade and scalp survivors were XRP-only",
                "sequence": "during discovery and disjoint validation",
            },
            {
                "id": "SHORT_SIGNAL_SEMANTIC_QUALITY",
                "evidence": "short targets originated from long-only adapter downgrade evidence rather than native short alpha proof",
                "sequence": "strategy-level raw signal audit",
            },
            {
                "id": "RUNNER_AND_SIDECAR_COMPLEXITY",
                "evidence": "temporary adapter, RR, trace and contract patches can pass technically while obscuring economic failure",
                "sequence": "after benchmark runner is minimal and deterministic",
            },
            {
                "id": "BROKER_BOT_COMPARISON_GAP",
                "evidence": "no comparable broker-bot trade export exists in current evidence",
                "sequence": "optional external comparison after same-data simple benchmarks",
            },
        ],
        "frozen_actions": {
            "current_36_candidate_branch": "block",
            "current_216_cell_branch": "block",
            "full_3600_reexecution": "block",
            "event_replay_2880": "block",
            "ensemble_or_s_grade_promotion": "block",
            "shadow_start": "block",
            "paper_live_order": "block",
        },
        "strategy_source_mutation_allowed": False,
        "registry_mutation_allowed": False,
        "config_mutation_allowed": False,
        "router_mutation_allowed": False,
        "service_mutation_allowed": False,
        "next_stage": "R7.A4D2_SHORT_RAW_GEOMETRY_AND_SIMPLE_BENCHMARK_EXECUTION_PLAN",
    }
    return plan


def self_test() -> int:
    fake = {
        "state": "PASS_SHORT_ARCHITECTURE_ECONOMIC_ALIGNMENT_AUDIT",
        "blocker_count": 0,
        "audit_completed": True,
        "architecture_alignment_pass": False,
        "architecture_decision": "BLOCK_REBUILD_REQUIRED",
        "primary_root_causes": [{"id": value} for value in sorted(EXPECTED_ROOT_CAUSES)],
        "short_target_strategy_count": 12,
        "diagnostic_family_count": 6,
        "short_target_strategy_ids": sorted(
            strategy_id
            for contract in FAMILY_CONTRACTS.values()
            for strategy_id in contract["strategy_ids"]
        ),
    }
    assert validate_audit(fake) == []
    plan = build_plan(fake)
    assert plan["redesign_scope_count"] == 5
    assert plan["strategy_family_count"] == 6
    assert plan["benchmark_count"] == 6
    assert plan["frozen_actions"]["full_3600_reexecution"] == "block"
    assert all(
        contract["universal_rr_allowed"] is False
        for contract in plan["strategy_family_contracts"].values()
    )
    print("STATE=PASS_SHORT_FAMILY_CONTRACT_BENCHMARK_PLAN_SELF_TEST")
    print("RC=0")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()

    root = Path(args.root).resolve()
    audit = load_json(root / AUDIT_PATH)
    blockers = validate_audit(audit)
    if blockers:
        print("STATE=HOLD_SHORT_STRATEGY_FAMILY_CONTRACT_AND_SIMPLE_BENCHMARK_PLAN_INPUT")
        print("BLOCKER_COUNT=" + str(len(blockers)))
        print("BLOCKERS=" + json.dumps(blockers, ensure_ascii=False))
        print("NEXT_STAGE=R7.A4D2_SHORT_STRATEGY_FAMILY_CONTRACT_AND_SIMPLE_BENCHMARK_PLAN")
        print("RC=2")
        return 2

    try:
        plan = build_plan(audit)
    except Exception as exc:
        print("STATE=HOLD_SHORT_STRATEGY_FAMILY_CONTRACT_AND_SIMPLE_BENCHMARK_PLAN_INPUT")
        print("BLOCKER_COUNT=1")
        print("BLOCKERS=" + json.dumps([f"PLAN_BUILD_FAILED:{type(exc).__name__}:{exc}"], ensure_ascii=False))
        print("NEXT_STAGE=R7.A4D2_SHORT_STRATEGY_FAMILY_CONTRACT_AND_SIMPLE_BENCHMARK_PLAN")
        print("RC=2")
        return 2

    output = root / OUTPUT_PATH
    atomic_json(output, plan)
    print("STATE=" + str(plan["state"]))
    print("BLOCKER_COUNT=0")
    print("REDESIGN_SCOPE_COUNT=" + str(plan["redesign_scope_count"]))
    print("STRATEGY_FAMILY_COUNT=" + str(plan["strategy_family_count"]))
    print("BENCHMARK_COUNT=" + str(plan["benchmark_count"]))
    print("FIXED_TARGET_COUNT_ALLOWED=false")
    print("UNIVERSAL_RR_ALLOWED=false")
    print("NATIVE_TIMEFRAME_CONTRACT_REQUIRED=true")
    print("SIMPLE_BENCHMARK_REQUIRED=true")
    print("FIXED_CANDIDATE_QUOTA_ALLOWED=false")
    print("RESIDUAL_ISSUE_BACKLOG_COUNT=" + str(len(plan["residual_issue_backlog"])))
    print("PLAN_JSON=" + str(output))
    print("NEXT_STAGE=" + str(plan["next_stage"]))
    print("RC=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
