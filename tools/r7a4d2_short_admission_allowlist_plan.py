#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


COST_AXIS_COUNT = 3
PERTURBATION_AXIS_COUNT = 2
AXIS_MULTIPLIER = COST_AXIS_COUNT * PERTURBATION_AXIS_COUNT


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


def candidate_key(row: dict[str, Any]) -> tuple[str, str, int]:
    return (
        str(row.get("scenario_id") or ""),
        str(row.get("strategy_id") or ""),
        int(row.get("bar_index", -1)),
    )


def positive_pairs(closure: dict[str, Any]) -> list[tuple[str, str]]:
    pairs = []
    for row in closure.get("allowlist_candidates", []):
        if not isinstance(row, dict):
            continue
        pairs.append((str(row.get("strategy_id") or ""), str(row.get("regime") or "")))
    return sorted(set(pairs))


def build_plan(closure: dict[str, Any], coverage: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    blockers: list[str] = []
    if closure.get("state") != "PASS_SHORT_SIGNAL_FREQUENCY_AND_ADMISSION_CLOSURE":
        blockers.append("ADMISSION_CLOSURE_NOT_PASS")
    if int(closure.get("blocker_count", -1)) != 0:
        blockers.append("ADMISSION_CLOSURE_BLOCKED")
    if int(closure.get("observer_candidate_count", -1)) != 158:
        blockers.append("OBSERVER_CANDIDATE_COUNT_INVALID")
    if int(closure.get("closed_trade_count", -1)) != 158:
        blockers.append("OBSERVER_CLOSED_TRADE_COUNT_INVALID")
    if int(closure.get("negative_pair_count", -1)) != 14:
        blockers.append("NEGATIVE_PAIR_COUNT_INVALID")
    if coverage.get("state") != "PASS_NO_TRIGGER_MARKET_COVERAGE_DIAGNOSE":
        blockers.append("COVERAGE_DIAGNOSE_NOT_PASS")
    if int(coverage.get("allowed_flat_enter_count", -1)) != 1:
        blockers.append("BASELINE_ALLOWED_FLAT_ENTER_COUNT_INVALID")

    pairs = positive_pairs(closure)
    expected_pairs = {
        ("scalp_snap", "trend_up"),
        ("vol_spike_fade", "shock_recovery"),
    }
    if set(pairs) != expected_pairs:
        blockers.append(f"POSITIVE_PAIR_SET_INVALID:{pairs}")

    observations = [row for row in closure.get("candidate_observations", []) if isinstance(row, dict)]
    grid_range = [
        row for row in observations
        if row.get("strategy_id") == "grid_rebalance" and row.get("regime") == "range"
    ]
    scalp_trend_up = [
        row for row in observations
        if row.get("strategy_id") == "scalp_snap" and row.get("regime") == "trend_up"
    ]
    vol_shock = [
        row for row in observations
        if row.get("strategy_id") == "vol_spike_fade" and row.get("regime") == "shock_recovery"
    ]
    admitted_trace = [
        row for row in coverage.get("candidate_trace", [])
        if isinstance(row, dict)
        and bool(row.get("admitted"))
        and row.get("candidate_state") == "FLAT_ENTER"
        and row.get("legacy_action") == "enter"
    ]

    if len(grid_range) != 8:
        blockers.append(f"GRID_RANGE_CANDIDATE_COUNT_INVALID:{len(grid_range)}")
    if len(scalp_trend_up) != 1:
        blockers.append(f"SCALP_TREND_UP_CANDIDATE_COUNT_INVALID:{len(scalp_trend_up)}")
    if len(vol_shock) != 1:
        blockers.append(f"VOL_SHOCK_CANDIDATE_COUNT_INVALID:{len(vol_shock)}")
    if len(admitted_trace) != 1:
        blockers.append(f"BASELINE_TREND_DOWN_CANDIDATE_COUNT_INVALID:{len(admitted_trace)}")

    stress_candidates: list[dict[str, Any]] = []
    for bucket, rows, status in (
        ("grid_rebalance_range", grid_range, "QUARANTINED_STRESS_CANDIDATE"),
        ("scalp_snap_trend_up", scalp_trend_up, "SINGLE_TRADE_WATCHLIST"),
        ("vol_spike_fade_shock_recovery", vol_shock, "SINGLE_TRADE_WATCHLIST"),
        ("baseline_trend_down", admitted_trace, "SINGLE_TRADE_WATCHLIST"),
    ):
        for row in rows:
            item = {
                "candidate_id": ":".join(map(str, candidate_key(row))),
                "bucket": bucket,
                "status": status,
                "scenario_id": str(row.get("scenario_id") or ""),
                "strategy_id": str(row.get("strategy_id") or ""),
                "segment_id": str(row.get("segment_id") or ""),
                "regime": str(row.get("regime") or ""),
                "bar_index": int(row.get("bar_index", -1)),
                "source": "closure_observer" if bucket != "baseline_trend_down" else "coverage_admitted_trace",
            }
            stress_candidates.append(item)

    keys = [
        (row["scenario_id"], row["strategy_id"], row["bar_index"])
        for row in stress_candidates
    ]
    if len(stress_candidates) != 11 or len(set(keys)) != 11:
        blockers.append(f"STRESS_CANDIDATE_SET_INVALID:{len(stress_candidates)}:{len(set(keys))}")

    negative_pairs = []
    for row in closure.get("negative_pairs", []):
        if not isinstance(row, dict):
            continue
        negative_pairs.append({
            "strategy_id": str(row.get("strategy_id") or ""),
            "regime": str(row.get("regime") or ""),
            "action": "block",
            "reason": "NEGATIVE_OBSERVER_RESULT",
        })
    if len(negative_pairs) != 14:
        blockers.append(f"NEGATIVE_BLOCK_SET_INVALID:{len(negative_pairs)}")

    bucket_counts = dict(sorted(Counter(row["bucket"] for row in stress_candidates).items()))
    plan = {
        "schema": "r7a4d2_short_admission_allowlist_plan_v1",
        "official_stage": "R7.A4D2_SHORT_ADMISSION_ALLOWLIST_PLAN",
        "state": "PASS_SHORT_ADMISSION_ALLOWLIST_PLAN" if not blockers else "HOLD_SHORT_ADMISSION_ALLOWLIST_PLAN_INPUT",
        "blocker_count": len(blockers),
        "blockers": blockers,
        "policy": {
            "loss_cap_r": 0.75,
            "full_tp_r": 2.5,
            "raw_strategy_sl_tp_preserved": True,
            "grid_rebalance_quarantined": True,
            "production_admission_expansion_allowed": False,
            "entry_threshold_relaxation_allowed": False,
        },
        "negative_pair_blocks": negative_pairs,
        "stress_candidate_count": len(stress_candidates),
        "stress_candidate_bucket_counts": bucket_counts,
        "cost_axis_count": COST_AXIS_COUNT,
        "perturbation_axis_count": PERTURBATION_AXIS_COUNT,
        "stress_execution_target_count": len(stress_candidates) * AXIS_MULTIPLIER,
        "stress_candidates": stress_candidates,
        "promotion_gates": {
            "common": {
                "all_stress_cells_completed": True,
                "failed_cell_count": 0,
                "invalid_geometry_count": 0,
                "source_registry_parity": True,
                "mutation_path_count": 0,
                "side_effect_attempt_count": 0,
                "profit_factor_min_exclusive": 1.25,
                "expectancy_r_min_exclusive": 0.15,
                "worst_cost_profile_net_return_must_be_positive": True,
                "worst_perturbation_net_return_must_be_positive": True,
            },
            "grid_rebalance_range": {
                "minimum_independent_candidate_count": 8,
                "minimum_stress_execution_count": 48,
                "quarantine_release_requires_separate_approval": True,
            },
            "single_trade_watchlist": {
                "promotion_allowed_from_axis_repeats_only": False,
                "minimum_unique_segment_count_before_promotion": 3,
                "minimum_independent_closed_trade_count_before_promotion": 12,
                "next_if_axis_robust_but_under_sampled": "R7.A4D2_MARKET_SEGMENT_EXPANSION_FOR_SHORT_CANDIDATES",
            },
        },
        "optimization_ladder": [
            "candidate_axis_stress_66",
            "market_segment_expansion_for_under_sampled_pairs",
            "strategy_regime_allowlist_counterfactual_600",
            "cost_and_latency_penalty_recheck",
            "partial_trailing_mfe_observer_compare",
            "combined_long_short_3600_reexecution",
            "event_replay_2880",
            "holdout_720",
            "fourth_shadow_start_gate",
        ],
        "next_stage": "R7.A4D2_SHORT_ADMISSION_CANDIDATE_STRESS_66" if not blockers else "R7.A4D2_SHORT_ADMISSION_ALLOWLIST_PLAN",
    }
    return plan, blockers


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    closure = load_json(root / "runtime/r7a4d2_short_signal_frequency_admission_closure/admission_closure_v1.json")
    coverage = load_json(root / "runtime/r7a4d2_no_trigger_market_coverage_diagnose/coverage_diagnose_v1.json")
    plan, blockers = build_plan(closure, coverage)
    output = root / "runtime/r7a4d2_short_admission_allowlist_plan/allowlist_plan_v1.json"
    atomic_json(output, plan)

    print("STATE=" + str(plan["state"]))
    print("BLOCKER_COUNT=" + str(len(blockers)))
    print("NEGATIVE_PAIR_BLOCK_COUNT=" + str(len(plan["negative_pair_blocks"])))
    print("STRESS_CANDIDATE_COUNT=" + str(plan["stress_candidate_count"]))
    print("STRESS_CANDIDATE_BUCKET_COUNTS=" + json.dumps(plan["stress_candidate_bucket_counts"], sort_keys=True))
    print("COST_AXIS_COUNT=" + str(COST_AXIS_COUNT))
    print("PERTURBATION_AXIS_COUNT=" + str(PERTURBATION_AXIS_COUNT))
    print("STRESS_EXECUTION_TARGET_COUNT=" + str(plan["stress_execution_target_count"]))
    print("GRID_REBALANCE_QUARANTINED=true")
    print("PRODUCTION_ADMISSION_EXPANSION_ALLOWED=false")
    print("PLAN_JSON=" + str(output))
    print("NEXT_STAGE=" + str(plan["next_stage"]))
    print("BLOCKERS=" + json.dumps(blockers, ensure_ascii=False))
    print("RC=" + ("0" if not blockers else "2"))
    return 0 if not blockers else 2


if __name__ == "__main__":
    raise SystemExit(main())
