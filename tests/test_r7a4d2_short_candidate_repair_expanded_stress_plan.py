from __future__ import annotations

import importlib.util
import os
from pathlib import Path


def load_module():
    path = Path(os.environ["R7A4D2_EXPANDED_PLAN"])
    spec = importlib.util.spec_from_file_location("expanded_plan", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def candidate(bucket: str, strategy: str, regime: str, index: int, segment: int | None = None) -> dict:
    segment_no = index if segment is None else segment
    bar_index = 320 + (index % 300)
    return {
        "candidate_id": f"scenario{index}:{strategy}:{bar_index}",
        "bucket": bucket,
        "strategy_id": strategy,
        "regime": regime,
        "scenario_id": f"scenario{index}",
        "segment_id": f"segment{segment_no}",
        "source_path": f"data/source{index % 5}.json",
        "source_sha256": "a" * 64,
        "start_row": index * 320,
        "end_row_exclusive": index * 320 + 320,
        "bar_index": bar_index,
        "evaluation_index": bar_index - 320,
        "discovery_only": True,
    }


def fixtures():
    baseline = [candidate("baseline_trend_down", "grid_rebalance", "trend_down", i) for i in range(12)]
    scalp = [candidate("scalp_snap_trend_up", "scalp_snap", "trend_up", 100 + i, 100 + min(i, 9)) for i in range(12)]
    vol = [candidate("vol_spike_fade_shock_recovery", "vol_spike_fade", "shock_recovery", 200 + i) for i in range(4)]
    rows = [
        {
            "bucket": "baseline_trend_down",
            "strategy_id": "grid_rebalance",
            "regime": "trend_down",
            "selected_candidate_count": 12,
            "selected_unique_segment_count": 12,
            "selected_unique_source_count": 5,
            "selected_candidates": baseline,
        },
        {
            "bucket": "grid_rebalance_range",
            "strategy_id": "grid_rebalance",
            "regime": "range",
            "selected_candidate_count": 0,
            "selected_unique_segment_count": 0,
            "selected_unique_source_count": 0,
            "selected_candidates": [],
        },
        {
            "bucket": "scalp_snap_trend_up",
            "strategy_id": "scalp_snap",
            "regime": "trend_up",
            "selected_candidate_count": 12,
            "selected_unique_segment_count": 10,
            "selected_unique_source_count": 5,
            "selected_candidates": scalp,
        },
        {
            "bucket": "vol_spike_fade_shock_recovery",
            "strategy_id": "vol_spike_fade",
            "regime": "shock_recovery",
            "selected_candidate_count": 4,
            "selected_unique_segment_count": 4,
            "selected_unique_source_count": 4,
            "selected_candidates": vol,
        },
    ]
    expansion = {
        "state": "PASS_MARKET_SEGMENT_EXPANSION_FOR_SHORT_CANDIDATES",
        "blocker_count": 0,
        "baseline_expansion_ready": True,
        "mutation_path_count": 0,
        "side_effect_attempt_count": 0,
        "source_registry_parity": True,
        "bucket_expansion_results": rows,
    }
    stress = {
        "state": "PASS_SHORT_ADMISSION_CANDIDATE_STRESS_66",
        "baseline_parity_failure_count": 0,
    }
    allowlist = {
        "state": "PASS_SHORT_ADMISSION_ALLOWLIST_PLAN",
        "negative_pair_blocks": [{} for _ in range(14)],
    }
    return expansion, stress, allowlist


def test_builds_28_candidate_168_cell_plan() -> None:
    module = load_module()
    plan, blockers = module.build_plan(*fixtures())
    assert blockers == []
    assert plan["expanded_candidate_count"] == 28
    assert plan["expanded_stress_execution_target_count"] == 168
    assert plan["next_stage"] == "R7.A4D2_SHORT_EXPANDED_CANDIDATE_STRESS_168"


def test_grid_strategy_remains_quarantined() -> None:
    module = load_module()
    plan, blockers = module.build_plan(*fixtures())
    assert blockers == []
    assert plan["policy"]["grid_rebalance_strategy_quarantined"] is True
    baseline_gate = plan["promotion_gates"]["baseline_trend_down"]
    assert baseline_gate["automatic_production_promotion_allowed"] is False


def test_duplicate_candidate_is_blocked() -> None:
    module = load_module()
    expansion, stress, allowlist = fixtures()
    rows = expansion["bucket_expansion_results"]
    rows[0]["selected_candidates"][1] = dict(rows[0]["selected_candidates"][0])
    plan, blockers = module.build_plan(expansion, stress, allowlist)
    assert plan["state"].startswith("HOLD_")
    assert any(item.startswith("EXPANDED_CANDIDATE_SET_INVALID") for item in blockers)


def test_bad_preroll_lineage_is_blocked() -> None:
    module = load_module()
    expansion, stress, allowlist = fixtures()
    expansion["bucket_expansion_results"][0]["selected_candidates"][0]["evaluation_index"] = 999
    _, blockers = module.build_plan(expansion, stress, allowlist)
    assert any(item.startswith("CANDIDATE_LINEAGE_INVALID") for item in blockers)
