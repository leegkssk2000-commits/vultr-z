#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


SHORT_STRATEGY_UNIVERSE = [
    "alpha_combo",
    "anchor_vwap_trend",
    "bb_revert",
    "ema_ribbon_scalp",
    "grid_rebalance",
    "keltner_trend",
    "liquidity_sweep",
    "obv_trend",
    "range_fade",
    "scalp_snap",
    "vol_spike_fade",
    "vwap_revert",
]
ACTIVE_REPAIR_STRATEGIES = ["grid_rebalance", "scalp_snap", "vol_spike_fade"]
LOSS_CAP_R = 0.75
FULL_TP_R = 2.5
NOMINAL_GROSS_PAYOFF_RATIO = FULL_TP_R / LOSS_CAP_R
COST_AXIS_COUNT = 3
PERTURBATION_AXIS_COUNT = 2
AXIS_MULTIPLIER = COST_AXIS_COUNT * PERTURBATION_AXIS_COUNT
SCALP_REBASE_EXPECTED = 3
SCALP_RAW_STABLE_EXPECTED = 1
SCALP_COUNTERFACTUAL_CANDIDATE_COUNT = SCALP_REBASE_EXPECTED + SCALP_RAW_STABLE_EXPECTED
SCALP_COUNTERFACTUAL_CELL_COUNT = SCALP_COUNTERFACTUAL_CANDIDATE_COUNT * AXIS_MULTIPLIER
BASELINE_EXPANSION_TARGETS = {
    "ETHUSDT": 12,
    "SOLUSDT": 12,
    "CONTROL_BTC_LINK_XRP": 12,
}
BASELINE_EXPANSION_SEGMENT_TARGET_COUNT = sum(BASELINE_EXPANSION_TARGETS.values())


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_plan(
    diagnose: dict[str, Any],
    stress: dict[str, Any],
    expanded_plan: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    blockers: list[str] = []
    if diagnose.get("state") != "PASS_SHORT_CHART_CAUSAL_CLUSTER_DIAGNOSE":
        blockers.append("CAUSAL_CLUSTER_DIAGNOSE_NOT_PASS")
    if int(diagnose.get("blocker_count", -1)) != 0:
        blockers.append("CAUSAL_CLUSTER_DIAGNOSE_BLOCKED")
    if diagnose.get("next_stage") != "R7.A4D2_SHORT_SELECTIVE_CHART_GATE_AND_GEOMETRY_COUNTERFACTUAL_PLAN":
        blockers.append("CAUSAL_CLUSTER_NEXT_STAGE_MISMATCH")
    if diagnose.get("gate_uses_pre_entry_chart_only") is not True:
        blockers.append("PRE_ENTRY_CHART_ONLY_GUARD_FAILED")
    if diagnose.get("future_outcome_used_to_fit_clusters") is not False:
        blockers.append("CLUSTER_OUTCOME_LEAKAGE_DETECTED")
    if int(diagnose.get("protected_mutation_path_count", -1)) != 0:
        blockers.append("DIAGNOSE_PROTECTED_MUTATION_DETECTED")
    if diagnose.get("strategy_mutation_allowed") is not False:
        blockers.append("DIAGNOSE_STRATEGY_MUTATION_POLICY_INVALID")

    if stress.get("state") != "PASS_SHORT_EXPANDED_CANDIDATE_STRESS_168":
        blockers.append("STRESS168_NOT_PASS")
    if int(stress.get("completed_cell_count", -1)) != 168 or int(stress.get("failed_cell_count", -1)) != 0:
        blockers.append("STRESS168_COMPLETION_INVALID")
    if int(stress.get("baseline_target_parity_failure_count", -1)) != 0:
        blockers.append("STRESS168_BASELINE_PARITY_FAILED")

    if expanded_plan.get("state") != "PASS_SHORT_CANDIDATE_REPAIR_AND_EXPANDED_STRESS_PLAN":
        blockers.append("EXPANDED_STRESS_PLAN_NOT_PASS")
    if int(expanded_plan.get("expanded_candidate_count", -1)) != 28:
        blockers.append("EXPANDED_CANDIDATE_COUNT_INVALID")
    if int(expanded_plan.get("expanded_stress_execution_target_count", -1)) != 168:
        blockers.append("EXPANDED_CELL_COUNT_INVALID")
    if expanded_plan.get("policy", {}).get("grid_rebalance_strategy_quarantined") is not True:
        blockers.append("GRID_QUARANTINE_NOT_LOCKED")

    baseline_gate_ready = diagnose.get("baseline_cluster_gate_ready") is True
    baseline_s_core = [
        row for row in diagnose.get("baseline_s_core_clusters", []) if isinstance(row, dict)
    ]
    baseline_failure = [
        row for row in diagnose.get("baseline_failure_clusters", []) if isinstance(row, dict)
    ]
    if baseline_gate_ready or baseline_s_core:
        blockers.append("BASELINE_GATE_PREMATURELY_READY")
    if len(baseline_failure) != 1:
        blockers.append(f"BASELINE_FAILURE_CLUSTER_COUNT_INVALID:{len(baseline_failure)}")

    scalp = diagnose.get("scalp_geometry_diagnosis")
    if not isinstance(scalp, dict):
        blockers.append("SCALP_GEOMETRY_DIAGNOSIS_MISSING")
        scalp = {}
    if scalp.get("rebase_counterfactual_ready") is not True:
        blockers.append("SCALP_REBASE_COUNTERFACTUAL_NOT_READY")
    if int(scalp.get("failure_count", -1)) != 0:
        blockers.append("SCALP_GEOMETRY_FAILURE_PRESENT")
    if int(scalp.get("geometry_parity_failure_count", -1)) != 0:
        blockers.append("SCALP_GEOMETRY_PARITY_FAILED")

    rebase_ids = sorted({str(value) for value in scalp.get("rebase_counterfactual_candidate_ids", []) if str(value)})
    stable_ids = sorted({str(value) for value in scalp.get("raw_geometry_stable_salvage_ids", []) if str(value)})
    if len(rebase_ids) != SCALP_REBASE_EXPECTED:
        blockers.append(f"SCALP_REBASE_CANDIDATE_COUNT_INVALID:{len(rebase_ids)}")
    if len(stable_ids) != SCALP_RAW_STABLE_EXPECTED:
        blockers.append(f"SCALP_RAW_STABLE_CANDIDATE_COUNT_INVALID:{len(stable_ids)}")
    if set(rebase_ids) & set(stable_ids):
        blockers.append("SCALP_WATCHLIST_OVERLAP")

    vol = diagnose.get("vol_component_decomposition")
    if not isinstance(vol, dict):
        blockers.append("VOL_COMPONENT_DECOMPOSITION_MISSING")
        vol = {}
    if vol.get("permanent_strategy_regime_block") is not True:
        blockers.append("VOL_PERMANENT_BLOCK_NOT_LOCKED")
    if vol.get("automatic_repair_or_promotion_allowed") is not False:
        blockers.append("VOL_AUTOMATIC_REPAIR_POLICY_INVALID")
    if vol.get("failure_learning_connection_allowed") is not False:
        blockers.append("VOL_FAILURE_LEARNING_POLICY_INVALID")

    watchlist = [
        *[
            {
                "candidate_id": candidate_id,
                "arm": "FILL_REBASED_GEOMETRY",
                "axis_count": AXIS_MULTIPLIER,
                "new_execution_cell_count": AXIS_MULTIPLIER,
                "prior_raw_arm_source": "stress168_proof_v1.json",
            }
            for candidate_id in rebase_ids
        ],
        *[
            {
                "candidate_id": candidate_id,
                "arm": "RAW_GEOMETRY_STABILITY_CONTROL",
                "axis_count": AXIS_MULTIPLIER,
                "new_execution_cell_count": AXIS_MULTIPLIER,
                "prior_raw_arm_source": "stress168_proof_v1.json",
            }
            for candidate_id in stable_ids
        ],
    ]

    realized_rr_metrics = {
        "nominal_loss_cap_r": LOSS_CAP_R,
        "nominal_full_tp_r": FULL_TP_R,
        "nominal_gross_payoff_ratio": round(NOMINAL_GROSS_PAYOFF_RATIO, 10),
        "required_metrics": [
            "gross_average_win_r",
            "gross_average_loss_r_abs",
            "gross_realized_payoff_ratio",
            "net_average_win_r",
            "net_average_loss_r_abs",
            "net_realized_payoff_ratio",
            "expectancy_r",
            "profit_factor",
            "win_rate_pct",
            "take_profit_rate_pct",
            "stop_rate_pct",
            "segment_end_rate_pct",
            "mfe_capture_ratio",
            "mean_mfe_r",
            "mean_mae_r",
            "worst_cost_axis_net_return_pct",
            "worst_perturbation_axis_net_return_pct",
        ],
        "economic_gate": {
            "profit_factor_min_exclusive": 1.25,
            "expectancy_r_min_exclusive": 0.15,
            "net_realized_payoff_ratio_min_exclusive": 1.5,
            "max_realized_loss_r": 0.75,
            "worst_cost_axis_net_return_positive": True,
            "worst_perturbation_axis_net_return_positive": True,
            "invalid_geometry_count": 0,
        },
        "s_grade_observer_gate": {
            "profit_factor_min_exclusive": 1.75,
            "expectancy_r_min_exclusive": 0.5,
            "net_realized_payoff_ratio_min_exclusive": 2.0,
            "minimum_independent_closed_trade_count": 12,
            "minimum_unique_segment_count": 10,
            "source_leave_one_out_required": True,
            "automatic_production_promotion_allowed": False,
        },
    }

    baseline_expansion = {
        "mode": "PRE_ENTRY_CLUSTER_CAUSAL_EXPANSION_TRACE_ONLY",
        "target_segment_count": BASELINE_EXPANSION_SEGMENT_TARGET_COUNT,
        "target_segment_counts": BASELINE_EXPANSION_TARGETS,
        "segment_length_bars": 320,
        "indicator_preroll_bars": 320,
        "non_overlapping_with_prior_24_segments": True,
        "performance_based_segment_selection_allowed": False,
        "future_outcome_used_for_selection": False,
        "required_symbols": ["ETHUSDT", "SOLUSDT", "BTCUSDT", "LINKUSDT", "XRPUSDT"],
        "purpose": [
            "confirm_or_reject_eth_failure_structure",
            "confirm_or_reject_sol_failure_structure",
            "measure_btc_link_xrp_control_stability",
            "derive_symbol_independent_pre_entry_cluster_boundary",
        ],
        "grid_strategy_quarantine_retained": True,
        "automatic_gate_activation_allowed": False,
    }

    universe_state = {
        "canonical_strategy_universe_count": 25,
        "short_target_strategy_universe_count": len(SHORT_STRATEGY_UNIVERSE),
        "short_target_strategy_ids": SHORT_STRATEGY_UNIVERSE,
        "active_repair_strategy_count": len(ACTIVE_REPAIR_STRATEGIES),
        "active_repair_strategy_ids": ACTIVE_REPAIR_STRATEGIES,
        "active_repair_candidate_count": 28,
        "current_stage_is_not_eleven_strategy_simulation": True,
        "post_repair_short_600_revalidation_required": True,
        "post_short_revalidation_full_3600_required": True,
        "post_3600_survivor_event_replay_2880_required": True,
    }

    state = (
        "PASS_SHORT_SELECTIVE_CHART_GATE_AND_GEOMETRY_COUNTERFACTUAL_PLAN"
        if not blockers
        else "HOLD_SHORT_SELECTIVE_CHART_GATE_AND_GEOMETRY_COUNTERFACTUAL_PLAN_INPUT"
    )
    next_stage = (
        "R7.A4D2_SHORT_SCALP_GEOMETRY_COUNTERFACTUAL_24_AND_BASELINE_CLUSTER_EXPANSION_36"
        if not blockers
        else "R7.A4D2_SHORT_SELECTIVE_CHART_GATE_AND_GEOMETRY_COUNTERFACTUAL_PLAN"
    )
    plan = {
        "schema": "r7a4d2_short_selective_chart_gate_geometry_counterfactual_plan_v1",
        "official_stage": "R7.A4D2_SHORT_SELECTIVE_CHART_GATE_AND_GEOMETRY_COUNTERFACTUAL_PLAN",
        "state": state,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "universe_state": universe_state,
        "policy": {
            "loss_cap_r": LOSS_CAP_R,
            "full_tp_r": FULL_TP_R,
            "nominal_gross_payoff_ratio": round(NOMINAL_GROSS_PAYOFF_RATIO, 10),
            "entry_threshold_relaxation_allowed": False,
            "raw_strategy_source_mutation_allowed": False,
            "registry_mutation_allowed": False,
            "admission_expansion_allowed": False,
            "shadow_start_allowed": False,
            "paper_live_order_allowed": False,
            "failure_learning_connection_allowed": False,
        },
        "scalp_counterfactual": {
            "candidate_count": len(watchlist),
            "rebase_candidate_count": len(rebase_ids),
            "raw_stability_control_count": len(stable_ids),
            "cost_axis_count": COST_AXIS_COUNT,
            "perturbation_axis_count": PERTURBATION_AXIS_COUNT,
            "execution_cell_count": len(watchlist) * AXIS_MULTIPLIER,
            "watchlist": watchlist,
            "non_watchlist_scalp_candidates_blocked": True,
            "raw_signal_predicates_preserved": True,
            "fill_rebase_changes_geometry_only": True,
            "prior_raw_arm_reused_for_comparison": True,
            "realized_rr_metrics": realized_rr_metrics,
        },
        "baseline_cluster_expansion": baseline_expansion,
        "vol_spike_fade_shock_recovery": {
            "permanent_strategy_regime_block": True,
            "reusable_observer_only_components": vol.get("reusable_observer_only_components", []),
            "blocked_entry_components": vol.get("blocked_entry_components", []),
            "s_grade_material_status": vol.get("s_grade_material_status"),
            "automatic_repair_or_promotion_allowed": False,
        },
        "plan_manifest_sha256": "",
        "next_stage": next_stage,
    }
    manifest_payload = {
        "universe_state": universe_state,
        "scalp_counterfactual": plan["scalp_counterfactual"],
        "baseline_cluster_expansion": baseline_expansion,
        "vol_spike_fade_shock_recovery": plan["vol_spike_fade_shock_recovery"],
    }
    plan["plan_manifest_sha256"] = canonical_hash(manifest_payload)
    return plan, blockers


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    diagnose = load_json(root / "runtime/r7a4d2_short_chart_causal_cluster_diagnose/causal_cluster_diagnose_v1.json")
    stress = load_json(root / "runtime/r7a4d2_short_expanded_candidate_stress_168/stress168_proof_v1.json")
    expanded_plan = load_json(root / "runtime/r7a4d2_short_candidate_repair_expanded_stress_plan/expanded_stress_plan_v1.json")
    plan, blockers = build_plan(diagnose, stress, expanded_plan)
    output = root / "runtime/r7a4d2_short_selective_chart_gate_geometry_counterfactual_plan/counterfactual_plan_v1.json"
    atomic_json(output, plan)

    universe = plan["universe_state"]
    scalp = plan["scalp_counterfactual"]
    baseline = plan["baseline_cluster_expansion"]
    print("STATE=" + str(plan["state"]))
    print("BLOCKER_COUNT=" + str(len(blockers)))
    print("CANONICAL_STRATEGY_UNIVERSE_COUNT=" + str(universe["canonical_strategy_universe_count"]))
    print("SHORT_TARGET_STRATEGY_UNIVERSE_COUNT=" + str(universe["short_target_strategy_universe_count"]))
    print("ACTIVE_REPAIR_STRATEGY_COUNT=" + str(universe["active_repair_strategy_count"]))
    print("ACTIVE_REPAIR_CANDIDATE_COUNT=" + str(universe["active_repair_candidate_count"]))
    print("CURRENT_STAGE_IS_NOT_ELEVEN_STRATEGY_SIMULATION=true")
    print("NOMINAL_GROSS_PAYOFF_RATIO=" + str(plan["policy"]["nominal_gross_payoff_ratio"]))
    print("REALIZED_PAYOFF_RATIO_AUDIT_REQUIRED=true")
    print("SCALP_COUNTERFACTUAL_CANDIDATE_COUNT=" + str(scalp["candidate_count"]))
    print("SCALP_REBASE_CANDIDATE_COUNT=" + str(scalp["rebase_candidate_count"]))
    print("SCALP_RAW_STABILITY_CONTROL_COUNT=" + str(scalp["raw_stability_control_count"]))
    print("SCALP_COUNTERFACTUAL_EXECUTION_CELL_COUNT=" + str(scalp["execution_cell_count"]))
    print("BASELINE_CLUSTER_EXPANSION_SEGMENT_TARGET_COUNT=" + str(baseline["target_segment_count"]))
    print("BASELINE_CLUSTER_EXPANSION_TARGETS=" + json.dumps(baseline["target_segment_counts"], sort_keys=True))
    print("VOL_PERMANENT_BLOCK=true")
    print("POST_REPAIR_SHORT_600_REVALIDATION_REQUIRED=true")
    print("POST_SHORT_REVALIDATION_FULL_3600_REQUIRED=true")
    print("POST_3600_EVENT_REPLAY_2880_REQUIRED=true")
    print("PLAN_MANIFEST_SHA256=" + str(plan["plan_manifest_sha256"]))
    print("PLAN_JSON=" + str(output))
    print("NEXT_STAGE=" + str(plan["next_stage"]))
    print("BLOCKERS=" + json.dumps(blockers, ensure_ascii=False))
    print("RC=" + ("0" if not blockers else "2"))
    return 0 if not blockers else 2


if __name__ == "__main__":
    raise SystemExit(main())
