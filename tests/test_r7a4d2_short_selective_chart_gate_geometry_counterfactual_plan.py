from __future__ import annotations

import importlib.util
import os
from pathlib import Path


def load_module():
    path = Path(os.environ["R7A4D2_SELECTIVE_PLAN"])
    spec = importlib.util.spec_from_file_location("selective_plan", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixtures():
    diagnose = {
        "state": "PASS_SHORT_CHART_CAUSAL_CLUSTER_DIAGNOSE",
        "blocker_count": 0,
        "next_stage": "R7.A4D2_SHORT_SELECTIVE_CHART_GATE_AND_GEOMETRY_COUNTERFACTUAL_PLAN",
        "gate_uses_pre_entry_chart_only": True,
        "future_outcome_used_to_fit_clusters": False,
        "protected_mutation_path_count": 0,
        "strategy_mutation_allowed": False,
        "baseline_cluster_gate_ready": False,
        "baseline_s_core_clusters": [],
        "baseline_failure_clusters": [{"cluster_id": 0}],
        "scalp_geometry_diagnosis": {
            "rebase_counterfactual_ready": True,
            "failure_count": 0,
            "geometry_parity_failure_count": 0,
            "rebase_counterfactual_candidate_ids": ["rebase-1", "rebase-2", "rebase-3"],
            "raw_geometry_stable_salvage_ids": ["stable-1"],
        },
        "vol_component_decomposition": {
            "permanent_strategy_regime_block": True,
            "automatic_repair_or_promotion_allowed": False,
            "failure_learning_connection_allowed": False,
            "reusable_observer_only_components": ["volume_spike_detector"],
            "blocked_entry_components": ["shock_recovery_short_fade_entry"],
            "s_grade_material_status": "RAW_COMPONENTS_ONLY_REQUIRES_INDEPENDENT_OBSERVER_VALIDATION",
        },
    }
    stress = {
        "state": "PASS_SHORT_EXPANDED_CANDIDATE_STRESS_168",
        "completed_cell_count": 168,
        "failed_cell_count": 0,
        "baseline_target_parity_failure_count": 0,
    }
    expanded_plan = {
        "state": "PASS_SHORT_CANDIDATE_REPAIR_AND_EXPANDED_STRESS_PLAN",
        "expanded_candidate_count": 28,
        "expanded_stress_execution_target_count": 168,
        "policy": {"grid_rebalance_strategy_quarantined": True},
    }
    return diagnose, stress, expanded_plan


def test_builds_24_cell_scalp_and_36_segment_baseline_plan() -> None:
    module = load_module()
    plan, blockers = module.build_plan(*fixtures())
    assert blockers == []
    assert plan["state"] == "PASS_SHORT_SELECTIVE_CHART_GATE_AND_GEOMETRY_COUNTERFACTUAL_PLAN"
    assert plan["scalp_counterfactual"]["candidate_count"] == 4
    assert plan["scalp_counterfactual"]["execution_cell_count"] == 24
    assert plan["baseline_cluster_expansion"]["target_segment_count"] == 36
    assert plan["next_stage"] == "R7.A4D2_SHORT_SCALP_GEOMETRY_COUNTERFACTUAL_24_AND_BASELINE_CLUSTER_EXPANSION_36"


def test_universe_state_distinguishes_strategies_from_candidates() -> None:
    module = load_module()
    plan, blockers = module.build_plan(*fixtures())
    assert blockers == []
    universe = plan["universe_state"]
    assert universe["canonical_strategy_universe_count"] == 25
    assert universe["short_target_strategy_universe_count"] == 12
    assert universe["active_repair_strategy_count"] == 3
    assert universe["active_repair_candidate_count"] == 28
    assert universe["current_stage_is_not_eleven_strategy_simulation"] is True
    assert universe["post_repair_short_600_revalidation_required"] is True
    assert universe["post_short_revalidation_full_3600_required"] is True


def test_realized_payoff_ratio_is_mandatory_and_nominal_rr_is_preserved() -> None:
    module = load_module()
    plan, blockers = module.build_plan(*fixtures())
    assert blockers == []
    metrics = plan["scalp_counterfactual"]["realized_rr_metrics"]
    assert metrics["nominal_loss_cap_r"] == 0.75
    assert metrics["nominal_full_tp_r"] == 2.5
    assert round(metrics["nominal_gross_payoff_ratio"], 6) == round(2.5 / 0.75, 6)
    assert "net_realized_payoff_ratio" in metrics["required_metrics"]
    assert "mfe_capture_ratio" in metrics["required_metrics"]
    assert metrics["economic_gate"]["invalid_geometry_count"] == 0


def test_missing_scalp_watchlist_fails_closed() -> None:
    module = load_module()
    diagnose, stress, expanded_plan = fixtures()
    diagnose["scalp_geometry_diagnosis"]["rebase_counterfactual_candidate_ids"] = ["rebase-1", "rebase-2"]
    plan, blockers = module.build_plan(diagnose, stress, expanded_plan)
    assert plan["state"].startswith("HOLD_")
    assert any(item.startswith("SCALP_REBASE_CANDIDATE_COUNT_INVALID") for item in blockers)


def test_vol_block_and_grid_quarantine_are_not_relaxed() -> None:
    module = load_module()
    plan, blockers = module.build_plan(*fixtures())
    assert blockers == []
    assert plan["baseline_cluster_expansion"]["grid_strategy_quarantine_retained"] is True
    assert plan["vol_spike_fade_shock_recovery"]["permanent_strategy_regime_block"] is True
    assert plan["vol_spike_fade_shock_recovery"]["automatic_repair_or_promotion_allowed"] is False
    assert plan["policy"]["entry_threshold_relaxation_allowed"] is False
