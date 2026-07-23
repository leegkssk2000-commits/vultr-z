#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any

PREVIOUS_PLAN_PATH = Path("runtime/r7a4d2_exchange_bot_v2_remaining_11_lane_uplift_plan/remaining_11_lane_uplift_plan_v1.json")
PREVIOUS_SUMMARY_PATH = Path("runtime/r7a4d2_exchange_bot_v2_remaining_11_lane_uplift_execution_132/remaining_11_lane_uplift_summary_v1.json")
OUTPUT_DIR = Path("runtime/r7a4d2_exchange_bot_v2_all_11_second_wave_execution_plan")
OUTPUT_NAME = "all_11_second_wave_plan_v1.json"
EXPECTED_LANES = 11
EXPECTED_VARIANTS_PER_LANE = 2
EXPECTED_BUNDLES = 22
EXPECTED_CELLS = 132
PASSED_LANE = "dual_atr_volatility_bot:5m"

SPECS = [
    ("dual_atr_volatility_bot:5m", "breakout", "SURVIVOR_SEVERE_ROBUSTNESS_UPLIFT", "atr5_impulse_15m_alignment", "REGIME", "Preserve the proven impulse geometry; veto only directly opposing 15m structure and increase reward-to-cost."),
    ("dual_atr_volatility_bot:5m", "breakout", "SURVIVOR_SEVERE_ROBUSTNESS_UPLIFT", "atr5_impulse_retest_cost_defense", "ENTRY_EXIT", "Require a shallow post-impulse retest for maker-like entry and shorter exposure; preserve the original control if this loses sample quality."),
    ("dual_ma_trend_bot:15m", "trend", "HIGH_EDGE_SAMPLE_EXPANSION", "ma15_accel_first_pullback", "ENTRY", "Convert the strong acceleration state into first-pullback entries without lowering the acceleration requirement."),
    ("dual_ma_trend_bot:15m", "trend", "HIGH_EDGE_SAMPLE_EXPANSION", "ma15_accel_continuation_reentry", "ROUTE", "Allow one continuation re-entry after renewed acceleration while preserving trend-regime and cost admission."),
    ("dual_ma_trend_bot:5m", "trend", "HIGH_EDGE_SAMPLE_EXPANSION", "ma5_confluence_first_pullback", "ENTRY", "Expand the profitable MA/Donchian confluence through first-pullback execution."),
    ("dual_ma_trend_bot:5m", "trend", "HIGH_EDGE_SAMPLE_EXPANSION", "ma5_accel_15m_alignment", "REGIME", "Use 15m directional structure with 5m spread acceleration to increase valid occurrences without accepting opposing context."),
    ("dual_donchian_trend_bot:5m", "trend", "COST_ROBUST_BREAKOUT_REPAIR", "donchian5_break_retest_volume", "ENTRY", "Replace direct break entries with volume-confirmed close and first retest."),
    ("dual_donchian_trend_bot:5m", "trend", "COST_ROBUST_BREAKOUT_REPAIR", "donchian5_15m_alignment_continuation", "REGIME", "Use 15m direction and 5m continuation/reclaim to improve adverse-cost survival."),
    ("dual_atr_volatility_bot:15m", "breakout", "TIMEFRAME_EXECUTION_REPAIR", "atr15_context_5m_retest", "TIMEFRAME", "Keep 15m volatility context but execute the first 5m reclaim to expand sample and reduce entry friction."),
    ("dual_atr_volatility_bot:15m", "breakout", "TIMEFRAME_EXECUTION_REPAIR", "atr15_persistence_5m_trigger", "TIMEFRAME", "Require persistent 15m expansion and use a 5m continuation trigger."),
    ("dual_vwap_mean_reversion_bot:15m", "mean_reversion", "TIMEFRAME_EXECUTION_REPAIR", "vwap15_context_5m_outer_reclaim", "TIMEFRAME", "Use 15m range context with 5m outer-band reclaim and VWAP target."),
    ("dual_vwap_mean_reversion_bot:15m", "mean_reversion", "COST_ROBUST_REVERSION_REPAIR", "vwap15_session_failed_auction", "ENTRY", "Detect failed auction wicks around session VWAP and require close-back confirmation."),
    ("dual_vwap_mean_reversion_bot:5m", "mean_reversion", "ZERO_SIGNAL_ROUTE_REBUILD", "vwap5_anchor_rotation", "ROUTE", "Rebuild from anchored VWAP rotation with range stability and cost-admissible distance."),
    ("dual_vwap_mean_reversion_bot:5m", "mean_reversion", "ZERO_SIGNAL_ROUTE_REBUILD", "vwap5_outer_reclaim_maker", "ENTRY", "Use rolling VWAP outer reclaim followed by a one-bar confirmation instead of direct touch."),
    ("neutral_multi_level_grid_bot:15m", "grid_range", "REAL_INVENTORY_GRID_REBUILD", "neutral_grid15_inventory_cycle", "SYSTEM", "Run repeatable level-to-level inventory cycles on 5m execution under a stable 15m range."),
    ("neutral_multi_level_grid_bot:15m", "grid_range", "REAL_INVENTORY_GRID_REBUILD", "neutral_grid15_session_reset_cycle", "SYSTEM", "Reset the inventory ladder when the 15m range center materially migrates."),
    ("neutral_multi_level_grid_bot:5m", "grid_range", "REAL_INVENTORY_GRID_REBUILD", "neutral_grid5_inventory_cycle", "SYSTEM", "Run repeatable wide-spacing maker-like grid cycles with per-level inventory isolation."),
    ("neutral_multi_level_grid_bot:5m", "grid_range", "REAL_INVENTORY_GRID_REBUILD", "neutral_grid5_volatility_cycle", "SYSTEM", "Scale grid width with ATR and suspend cycles when range slope exits the neutral envelope."),
    ("directional_trend_grid_bot:15m", "grid_trend", "REAL_INVENTORY_GRID_REBUILD", "trend_grid15_inventory_pullback", "SYSTEM", "Use 15m trend state and repeated 5m pullback inventory levels."),
    ("directional_trend_grid_bot:15m", "grid_trend", "REAL_INVENTORY_GRID_REBUILD", "trend_grid15_breakout_ladder", "SYSTEM", "Activate the ladder after a 15m breakout and recycle only in the breakout direction."),
    ("directional_trend_grid_bot:5m", "grid_trend", "REAL_INVENTORY_GRID_REBUILD", "trend_grid5_inventory_pullback", "SYSTEM", "Use 15m direction with two independent 5m pullback inventory levels."),
    ("directional_trend_grid_bot:5m", "grid_trend", "REAL_INVENTORY_GRID_REBUILD", "trend_grid5_impulse_ladder", "SYSTEM", "Arm a short-lived directional ladder after a 5m impulse aligned with 15m structure."),
]

def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value

def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)

def self_test() -> int:
    assert len(SPECS) == EXPECTED_BUNDLES
    lanes = [row[0] for row in SPECS]
    assert len(set(lanes)) == EXPECTED_LANES
    assert all(lanes.count(lane) == EXPECTED_VARIANTS_PER_LANE for lane in set(lanes))
    assert lanes.count(PASSED_LANE) == 2
    assert len({row[3] for row in SPECS}) == EXPECTED_BUNDLES
    print("STATE=PASS_EXCHANGE_BOT_V2_ALL_11_SECOND_WAVE_PLAN_SELF_TEST")
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
    previous_plan_path = root / PREVIOUS_PLAN_PATH
    previous_summary_path = root / PREVIOUS_SUMMARY_PATH
    missing = [str(path) for path in (previous_plan_path, previous_summary_path) if not path.is_file()]
    if missing:
        print("STATE=HOLD_EXCHANGE_BOT_V2_ALL_11_SECOND_WAVE_PLAN_INPUT")
        print("BLOCKER_COUNT=1")
        print("BLOCKERS=" + json.dumps(["REQUIRED_EVIDENCE_MISSING:" + ",".join(missing)]))
        print("RC=2")
        return 2
    previous_plan = load_json(previous_plan_path)
    previous_summary = load_json(previous_summary_path)
    blockers: list[str] = []
    if previous_summary.get("state") != "PASS_EXCHANGE_BOT_V2_REMAINING_11_LANE_UPLIFT_EXECUTION_132":
        blockers.append("PREVIOUS_UPLIFT_SUMMARY_NOT_PASS")
    lane_rows = [row for row in previous_summary.get("lane_best_rows", []) if isinstance(row, dict)]
    lane_map = {str(row.get("source_lane_id")): row for row in lane_rows}
    if len(lane_map) != EXPECTED_LANES:
        blockers.append(f"PREVIOUS_LANE_COUNT_INVALID:{len(lane_map)}")
    if previous_summary.get("uplifted_lane_ids") != [PASSED_LANE]:
        blockers.append("EXPECTED_SINGLE_ATR5_SURVIVOR_NOT_FOUND")
    spec_lanes = {row[0] for row in SPECS}
    if spec_lanes != set(lane_map):
        blockers.append("SECOND_WAVE_LANE_SET_MISMATCH")
    reference_metrics = previous_plan.get("reference_metrics")
    if not isinstance(reference_metrics, dict):
        blockers.append("REFERENCE_METRICS_MISSING")
    if blockers:
        print("STATE=HOLD_EXCHANGE_BOT_V2_ALL_11_SECOND_WAVE_PLAN_INPUT")
        print("BLOCKER_COUNT=" + str(len(blockers)))
        print("BLOCKERS=" + json.dumps(blockers))
        print("RC=2")
        return 2
    rows: list[dict[str, Any]] = []
    for lane_id, family, repair_class, variant_id, axis, design in SPECS:
        baseline = lane_map[lane_id]
        rows.append({
            "lane_id": lane_id,
            "family": family,
            "repair_class": repair_class,
            "variant_id": variant_id,
            "repair_axis": axis,
            "design": design,
            "source_best_variant_id": baseline.get("variant_id"),
            "source_uplift_discovery_pass": bool(baseline.get("uplift_discovery_pass")),
            "baseline_metrics": {
                "base": baseline.get("base_metrics") or {},
                "adverse": baseline.get("adverse_metrics") or {},
                "severe": baseline.get("severe_tail_metrics") or {},
            },
            "control_policy": "PRESERVE_PREVIOUS_BEST_IF_SECOND_WAVE_FAILS",
            "parameter_optimization_allowed": False,
            "entry_threshold_relaxation_allowed": False,
            "blind_stop_widening_allowed": False,
            "discovery_s_grade_allowed": False,
        })
    plan = {
        "state": "PASS_EXCHANGE_BOT_V2_ALL_11_SECOND_WAVE_PLAN",
        "target_sha": args.target_sha,
        "lane_count": EXPECTED_LANES,
        "passed_lane_further_uplift_count": 1,
        "failed_lane_repair_count": 10,
        "variant_per_lane": EXPECTED_VARIANTS_PER_LANE,
        "bundle_count": EXPECTED_BUNDLES,
        "stress_cell_per_bundle": 6,
        "discovery_cell_target": EXPECTED_CELLS,
        "passed_lane_id": PASSED_LANE,
        "reference_lane_id": previous_plan.get("reference_lane_id"),
        "reference_metrics": reference_metrics,
        "second_wave_rows": rows,
        "mutation_rows": [],
        "next_stage": "R7.A4D2_EXCHANGE_BOT_V2_ALL_11_SECOND_WAVE_EXECUTION_132",
    }
    output = root / OUTPUT_DIR / OUTPUT_NAME
    atomic_json(output, plan)
    print("STATE=PASS_EXCHANGE_BOT_V2_ALL_11_SECOND_WAVE_PLAN")
    print("BLOCKER_COUNT=0")
    print("SECOND_WAVE_LANE_COUNT=11")
    print("FAILED_LANE_REPAIR_COUNT=10")
    print("PASSED_LANE_FURTHER_UPLIFT_COUNT=1")
    print("SECOND_WAVE_BUNDLE_COUNT=22")
    print("SECOND_WAVE_CELL_TARGET=132")
    print("PLAN_JSON=" + str(output))
    print("NEXT_STAGE=" + plan["next_stage"])
    print("BLOCKERS=[]")
    print("RC=0")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
