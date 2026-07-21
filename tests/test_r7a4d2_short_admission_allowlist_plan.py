from __future__ import annotations

import importlib.util
import os
from pathlib import Path


def load_module():
    path = Path(os.environ["R7A4D2_ALLOWLIST_PLAN"])
    spec = importlib.util.spec_from_file_location("allowlist_plan", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def observation(strategy: str, regime: str, index: int) -> dict:
    return {
        "scenario_id": f"scenario.{strategy}.{index}",
        "strategy_id": strategy,
        "segment_id": f"segment.{index}",
        "regime": regime,
        "bar_index": 100 + index,
    }


def evidence():
    observations = [observation("grid_rebalance", "range", i) for i in range(8)]
    observations += [observation("scalp_snap", "trend_up", 20)]
    observations += [observation("vol_spike_fade", "shock_recovery", 21)]
    closure = {
        "state": "PASS_SHORT_SIGNAL_FREQUENCY_AND_ADMISSION_CLOSURE",
        "blocker_count": 0,
        "observer_candidate_count": 158,
        "closed_trade_count": 158,
        "negative_pair_count": 14,
        "allowlist_candidates": [
            {"strategy_id": "scalp_snap", "regime": "trend_up"},
            {"strategy_id": "vol_spike_fade", "regime": "shock_recovery"},
        ],
        "candidate_observations": observations,
        "negative_pairs": [
            {"strategy_id": f"negative_{i}", "regime": "trend_up"}
            for i in range(14)
        ],
    }
    coverage = {
        "state": "PASS_NO_TRIGGER_MARKET_COVERAGE_DIAGNOSE",
        "allowed_flat_enter_count": 1,
        "candidate_trace": [
            {
                **observation("baseline_strategy", "trend_down", 30),
                "admitted": True,
                "candidate_state": "FLAT_ENTER",
                "legacy_action": "enter",
            }
        ],
    }
    return closure, coverage


def test_plan_has_11_candidates_and_66_stress_cells() -> None:
    module = load_module()
    closure, coverage = evidence()
    plan, blockers = module.build_plan(closure, coverage)
    assert blockers == []
    assert plan["stress_candidate_count"] == 11
    assert plan["stress_execution_target_count"] == 66
    assert plan["stress_candidate_bucket_counts"]["grid_rebalance_range"] == 8


def test_negative_pairs_remain_blocked() -> None:
    module = load_module()
    closure, coverage = evidence()
    plan, blockers = module.build_plan(closure, coverage)
    assert blockers == []
    assert len(plan["negative_pair_blocks"]) == 14
    assert all(row["action"] == "block" for row in plan["negative_pair_blocks"])


def test_single_trade_axis_repeats_cannot_promote() -> None:
    module = load_module()
    closure, coverage = evidence()
    plan, blockers = module.build_plan(closure, coverage)
    assert blockers == []
    gate = plan["promotion_gates"]["single_trade_watchlist"]
    assert gate["promotion_allowed_from_axis_repeats_only"] is False
    assert gate["minimum_unique_segment_count_before_promotion"] == 3
    assert gate["minimum_independent_closed_trade_count_before_promotion"] == 12


def test_unexpected_positive_pair_fails_closed() -> None:
    module = load_module()
    closure, coverage = evidence()
    closure["allowlist_candidates"].append({"strategy_id": "grid_rebalance", "regime": "range"})
    _, blockers = module.build_plan(closure, coverage)
    assert any(value.startswith("POSITIVE_PAIR_SET_INVALID") for value in blockers)
