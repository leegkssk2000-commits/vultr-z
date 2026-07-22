#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

DIAG_PATH = Path("runtime/r7a4d2_short_raw_geometry_mutation_and_lane_economic_diagnose/diagnose_v1.json")
PLAN_PATH = Path("runtime/r7a4d2_short_raw_geometry_and_simple_benchmark_execution_plan/execution_plan_v1.json")
GEOMETRY_PATH = Path("runtime/r7a4d2_short_raw_geometry_and_simple_benchmark_execution/signal_geometry_v1.jsonl")
DISCOVERY_LOCK_PATH = Path("runtime/r7a4d2_short_survivor_controlled_upgrade_discovery/discovery_lock_v1.json")
OUTPUT_PATH = Path("runtime/r7a4d2_short_all_lane_architecture_repair_plan/repair_plan_v1.json")
EXPECTED_LANES = 25
EXPECTED_CLASSES = {
    "PARETO_DOMINATES_BENCHMARK",
    "MIXED_TRADEOFF",
    "PARETO_DOMINATED_BY_BENCHMARK",
    "NO_ELIGIBLE_STRATEGY_SIGNAL",
}


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            text = line.strip()
            if not text:
                continue
            value = json.loads(text)
            if not isinstance(value, dict):
                raise ValueError(f"JSONL_OBJECT_REQUIRED:{path}:{line_number}")
            rows.append(value)
    return rows


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def finite(value: Any) -> float | None:
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    return None


def quantile(values: list[float], q: float) -> float | None:
    clean = sorted(value for value in values if math.isfinite(value))
    if not clean:
        return None
    if len(clean) == 1:
        return clean[0]
    index = (len(clean) - 1) * q
    low = int(math.floor(index))
    high = int(math.ceil(index))
    if low == high:
        return clean[low]
    weight = index - low
    return clean[low] * (1.0 - weight) + clean[high] * weight


def geometry_profile(rows: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = [row for row in rows if bool(row.get("semantic_eligible", True)) and int(row.get("fold", 99)) < 3]
    def values(key: str) -> list[float]:
        result: list[float] = []
        for row in eligible:
            value = finite(row.get(key))
            if value is not None:
                result.append(value)
        return result

    stop = values("structural_stop_distance_pct")
    mfe = values("full_forward_mfe_pct")
    mae = values("full_forward_mae_pct")
    ttmfe = values("time_to_mfe_bars")
    ttmae = values("time_to_mae_bars")
    return {
        "discovery_geometry_row_count": len(eligible),
        "stop_distance_pct": {"q25": quantile(stop, .25), "q50": quantile(stop, .50), "q75": quantile(stop, .75)},
        "mfe_pct": {"q25": quantile(mfe, .25), "q50": quantile(mfe, .50), "q75": quantile(mfe, .75)},
        "mae_pct": {"q25": quantile(mae, .25), "q50": quantile(mae, .50), "q75": quantile(mae, .75)},
        "time_to_mfe_bars": {"q25": quantile(ttmfe, .25), "q50": quantile(ttmfe, .50), "q75": quantile(ttmfe, .75)},
        "time_to_mae_bars": {"q25": quantile(ttmae, .25), "q50": quantile(ttmae, .50), "q75": quantile(ttmae, .75)},
        "symbol_histogram": dict(sorted(Counter(str(row.get("symbol") or "") for row in eligible).items())),
        "regime_histogram": dict(sorted(Counter(str(row.get("regime") or "") for row in eligible).items())),
    }


def family_candle_contract(family: str) -> dict[str, Any]:
    contracts = {
        "trend": {
            "entry_features": ["ema_fast_below_slow", "negative_slow_slope", "bearish_pullback_rejection", "upper_wick_ratio"],
            "stop_candidates": ["latest_confirmed_swing_high", "atr_envelope_high", "pullback_high_plus_atr_buffer"],
            "exit_candidates": ["mfe_q50", "ema_recross", "time_to_mfe_q75_timeout", "mfe_runner_after_partial"],
        },
        "mean_reversion": {
            "entry_features": ["rolling_vwap_zscore", "rsi_exhaustion", "bearish_close_location", "momentum_stall"],
            "stop_candidates": ["recent_excursion_high", "signal_high_plus_atr_buffer", "mae_q75_guard"],
            "exit_candidates": ["rolling_vwap", "fair_value_midpoint", "mfe_q50", "time_to_mfe_q75_timeout"],
        },
        "scalp": {
            "entry_features": ["fast_ema_impulse", "range_expansion", "volume_impulse", "friction_multiple_floor", "close_near_low"],
            "stop_candidates": ["micro_swing_high", "signal_high_plus_small_atr", "mae_q75_guard"],
            "exit_candidates": ["short_horizon_mfe_q50", "micro_structure_break", "time_to_mfe_q50_timeout"],
        },
        "grid_range": {
            "entry_features": ["range_slope_low", "upper_range_quartile", "bearish_rejection", "spacing_to_cost_multiple"],
            "stop_candidates": ["range_upper_boundary", "grid_step_buffer", "mae_q75_guard"],
            "exit_candidates": ["next_grid_level", "range_midpoint", "time_to_mfe_q75_timeout"],
        },
        "event_reversal": {
            "entry_features": ["extreme_up_bar_quantile", "volume_shock", "upper_wick_ratio", "failed_continuation"],
            "stop_candidates": ["event_extreme_high", "failed_continuation_high", "mae_q75_guard"],
            "exit_candidates": ["event_midpoint", "mfe_q50", "time_to_mfe_q75_timeout", "runner_after_event_reversion"],
        },
    }
    return contracts.get(family, {
        "entry_features": ["component_consensus"],
        "stop_candidates": ["component_specific"],
        "exit_candidates": ["component_specific"],
    })


def repair_mode(classification: str) -> str:
    return {
        "PARETO_DOMINATES_BENCHMARK": "ECONOMIC_EXIT_AND_COST_REPAIR",
        "MIXED_TRADEOFF": "NEGATIVE_AXIS_ONLY_PARETO_REPAIR",
        "PARETO_DOMINATED_BY_BENCHMARK": "FAMILY_HYPOTHESIS_REDESIGN",
        "NO_ELIGIBLE_STRATEGY_SIGNAL": "TIMEFRAME_ROUTE_OR_SEMANTIC_RECONSTRUCTION",
    }.get(classification, "DIAGNOSTIC_HOLD")


def best_sibling(strategy_id: str, current_lane: str, comparisons: list[dict[str, Any]]) -> str | None:
    candidates: list[tuple[float, str]] = []
    for row in comparisons:
        if str(row.get("strategy_id")) != strategy_id or str(row.get("strategy_lane_id")) == current_lane:
            continue
        metrics = row.get("strategy_metrics") if isinstance(row.get("strategy_metrics"), dict) else {}
        if int(metrics.get("semantic_eligible_signal_count") or 0) <= 0:
            continue
        delta = row.get("deltas") if isinstance(row.get("deltas"), dict) else {}
        score = finite(delta.get("severe_net_available_r_positive_rate_pct")) or -1e9
        candidates.append((score, str(row.get("strategy_lane_id"))))
    candidates.sort(reverse=True)
    return candidates[0][1] if candidates else None


def build_repair_row(
    comparison: dict[str, Any],
    profile: dict[str, Any],
    comparisons: list[dict[str, Any]],
) -> dict[str, Any]:
    lane_id = str(comparison["strategy_lane_id"])
    strategy_id = str(comparison.get("strategy_id") or "")
    family = str(comparison.get("family") or "")
    classification = str(comparison.get("classification") or "")
    metric_comparisons = comparison.get("metric_comparisons") if isinstance(comparison.get("metric_comparisons"), dict) else {}
    losing_axes = sorted(key for key, value in metric_comparisons.items() if value == -1)
    winning_axes = sorted(key for key, value in metric_comparisons.items() if value == 1)
    sibling = best_sibling(strategy_id, lane_id, comparisons) if classification == "NO_ELIGIBLE_STRATEGY_SIGNAL" else None
    candle_contract = family_candle_contract(family)

    if classification == "PARETO_DOMINATES_BENCHMARK":
        entry_policy = "PRESERVE_CANONICAL_ENTRY"
        redesign_scope = ["stop", "exit", "timeout", "cost_floor"]
    elif classification == "MIXED_TRADEOFF":
        entry_policy = "PRESERVE_WINNING_AXES_REPAIR_LOSING_AXES"
        redesign_scope = losing_axes or ["entry", "stop", "exit"]
    elif classification == "PARETO_DOMINATED_BY_BENCHMARK":
        entry_policy = "REBUILD_FROM_FAMILY_CANDLE_HYPOTHESIS"
        redesign_scope = ["entry", "stop", "exit", "regime"]
    else:
        entry_policy = "ROUTE_TO_SIBLING_NATIVE_TIMEFRAME" if sibling else "RECONSTRUCT_SHORT_SEMANTICS_FROM_FAMILY_CANDLES"
        redesign_scope = ["timeframe", "semantic_entry", "regime"]

    arms = [
        {
            "arm_id": "entry_candle_quality",
            "axis": "entry",
            "features": candle_contract["entry_features"],
            "future_pnl_selection_allowed": False,
        },
        {
            "arm_id": "stop_geometry_quantile",
            "axis": "stop",
            "candidates": candle_contract["stop_candidates"],
            "quantile_source": profile["stop_distance_pct"],
            "mae_guard_source": profile["mae_pct"],
        },
        {
            "arm_id": "exit_mfe_timeout",
            "axis": "exit",
            "candidates": candle_contract["exit_candidates"],
            "mfe_source": profile["mfe_pct"],
            "timeout_source": profile["time_to_mfe_bars"],
        },
    ]

    return {
        "lane_id": lane_id,
        "strategy_id": strategy_id,
        "family": family,
        "timeframe": comparison.get("timeframe"),
        "current_classification": classification,
        "repair_mode": repair_mode(classification),
        "entry_policy": entry_policy,
        "winning_axes_locked": winning_axes,
        "losing_axes_to_repair": losing_axes,
        "redesign_scope": redesign_scope,
        "sibling_native_timeframe_candidate": sibling,
        "geometry_profile": profile,
        "candidate_arms": arms,
        "maximum_discovery_arms": 3,
        "validation_selection_allowed": False,
        "retirement_allowed_before_repair_execution": False,
    }


def self_test() -> int:
    sample = [
        {"structural_stop_distance_pct": .4, "full_forward_mfe_pct": .6, "full_forward_mae_pct": .2, "time_to_mfe_bars": 3, "time_to_mae_bars": 1, "fold": 0, "semantic_eligible": True, "symbol": "BTCUSDT", "regime": "range"},
        {"structural_stop_distance_pct": .6, "full_forward_mfe_pct": 1.0, "full_forward_mae_pct": .4, "time_to_mfe_bars": 5, "time_to_mae_bars": 2, "fold": 1, "semantic_eligible": True, "symbol": "ETHUSDT", "regime": "range"},
    ]
    profile = geometry_profile(sample)
    assert profile["discovery_geometry_row_count"] == 2
    assert abs(float(profile["stop_distance_pct"]["q50"]) - .5) < 1e-9
    assert repair_mode("MIXED_TRADEOFF") == "NEGATIVE_AXIS_ONLY_PARETO_REPAIR"
    print("STATE=PASS_SHORT_ALL_LANE_ARCHITECTURE_REPAIR_PLAN_SELF_TEST")
    print("RC=0")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--target-sha", default="UNKNOWN")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()

    root = Path(args.root).resolve()
    required = [root / DIAG_PATH, root / PLAN_PATH, root / GEOMETRY_PATH, root / DISCOVERY_LOCK_PATH]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        print("STATE=HOLD_SHORT_ALL_LANE_ARCHITECTURE_REPAIR_PLAN_INPUT")
        print("BLOCKER_COUNT=1")
        print("BLOCKERS=" + json.dumps(["REQUIRED_EVIDENCE_MISSING:" + ",".join(missing)]))
        print("RC=2")
        return 2

    diagnose = load_json(root / DIAG_PATH)
    plan = load_json(root / PLAN_PATH)
    lock = load_json(root / DISCOVERY_LOCK_PATH)
    blockers: list[str] = []
    if diagnose.get("state") != "PASS_SHORT_RAW_GEOMETRY_MUTATION_AND_LANE_ECONOMIC_DIAGNOSE" or diagnose.get("result_reusable") is not True:
        blockers.append("DIAGNOSE_NOT_REUSABLE")
    comparisons = [row for row in diagnose.get("lane_comparisons", []) if isinstance(row, dict)]
    if len(comparisons) != EXPECTED_LANES:
        blockers.append(f"LANE_COMPARISON_COUNT_INVALID:{len(comparisons)}")
    strategy_lanes = [row for row in plan.get("strategy_lanes", []) if isinstance(row, dict)]
    if len(strategy_lanes) != EXPECTED_LANES:
        blockers.append(f"STRATEGY_LANE_COUNT_INVALID:{len(strategy_lanes)}")
    classes = {str(row.get("classification")) for row in comparisons}
    if not classes.issubset(EXPECTED_CLASSES):
        blockers.append("UNEXPECTED_COMPARISON_CLASS:" + json.dumps(sorted(classes - EXPECTED_CLASSES)))
    if lock.get("state") != "PASS_SHORT_SURVIVOR_CONTROLLED_UPGRADE_DISCOVERY":
        blockers.append("SURVIVOR_DISCOVERY_NOT_PASS")
    if int(lock.get("economic_survivor_count", -1)) != 0:
        blockers.append("ZERO_SURVIVOR_FAILURE_NOT_REPRODUCED")
    if blockers:
        print("STATE=HOLD_SHORT_ALL_LANE_ARCHITECTURE_REPAIR_PLAN_INPUT")
        print("BLOCKER_COUNT=" + str(len(blockers)))
        print("BLOCKERS=" + json.dumps(blockers, ensure_ascii=False))
        print("RC=2")
        return 2

    geometry_by_lane: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in load_jsonl(root / GEOMETRY_PATH):
        lane_id = str(row.get("lane_id") or "")
        if lane_id.startswith("strategy:"):
            geometry_by_lane[lane_id].append(row)

    repair_rows = [
        build_repair_row(row, geometry_profile(geometry_by_lane.get(str(row["strategy_lane_id"]), [])), comparisons)
        for row in comparisons
    ]
    mode_histogram = dict(sorted(Counter(row["repair_mode"] for row in repair_rows).items()))
    class_histogram = dict(sorted(Counter(row["current_classification"] for row in repair_rows).items()))
    sibling_route_count = sum(1 for row in repair_rows if row.get("sibling_native_timeframe_candidate"))
    semantic_rebuild_count = sum(1 for row in repair_rows if row["entry_policy"] == "RECONSTRUCT_SHORT_SEMANTICS_FROM_FAMILY_CANDLES")

    report = {
        "schema": "r7a4d2_short_all_lane_architecture_repair_plan_v1",
        "official_stage": "R7.A4D2_SHORT_ALL_LANE_ARCHITECTURE_REPAIR_PLAN",
        "state": "PASS_SHORT_ALL_LANE_ARCHITECTURE_REPAIR_PLAN",
        "target_commit": args.target_sha,
        "blocker_count": 0,
        "blockers": [],
        "strategy_lane_count": len(repair_rows),
        "current_class_histogram": class_histogram,
        "repair_mode_histogram": mode_histogram,
        "sibling_timeframe_route_count": sibling_route_count,
        "semantic_reconstruction_count": semantic_rebuild_count,
        "retirement_before_repair_execution_allowed": False,
        "universal_rr_allowed": False,
        "future_pnl_parameter_selection_allowed": False,
        "maximum_candidate_arms_per_lane": 3,
        "maximum_total_candidate_arms": len(repair_rows) * 3,
        "discovery_only_parameter_derivation": True,
        "disjoint_validation_required": True,
        "repair_rows": repair_rows,
        "execution_order": [
            "route no-signal lanes to proven sibling timeframes where available",
            "repair raw-dominant lanes at exit/stop/cost without changing entry",
            "repair only negative axes for mixed lanes",
            "rebuild benchmark-dominated and remaining no-signal lanes from family candle hypotheses",
            "run discovery under same cost/timing/collision policy",
            "lock at most one arm per unique strategy",
            "run disjoint validation before any canonical or registry mutation",
        ],
        "next_stage": "R7.A4D2_SHORT_ALL_LANE_ARCHITECTURE_REPAIR_EXECUTION",
    }
    atomic_json(root / OUTPUT_PATH, report)
    print("STATE=PASS_SHORT_ALL_LANE_ARCHITECTURE_REPAIR_PLAN")
    print("BLOCKER_COUNT=0")
    print("STRATEGY_LANE_COUNT=" + str(len(repair_rows)))
    print("CURRENT_CLASS_HISTOGRAM=" + json.dumps(class_histogram, sort_keys=True))
    print("REPAIR_MODE_HISTOGRAM=" + json.dumps(mode_histogram, sort_keys=True))
    print("SIBLING_TIMEFRAME_ROUTE_COUNT=" + str(sibling_route_count))
    print("SEMANTIC_RECONSTRUCTION_COUNT=" + str(semantic_rebuild_count))
    print("MAXIMUM_TOTAL_CANDIDATE_ARMS=" + str(len(repair_rows) * 3))
    print("RETIREMENT_BEFORE_REPAIR_EXECUTION_ALLOWED=false")
    print("PLAN_JSON=" + str(root / OUTPUT_PATH))
    print("NEXT_STAGE=R7.A4D2_SHORT_ALL_LANE_ARCHITECTURE_REPAIR_EXECUTION")
    print("BLOCKERS=[]")
    print("RC=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
