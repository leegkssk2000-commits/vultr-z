#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any

CAUSALITY_PATH = Path("runtime/r7a4d2_exchange_bot_v2_second_wave_failure_causality_decomposition/causality_and_repair_plan_v1.json")
SECOND_WAVE_SUMMARY_PATH = Path("runtime/r7a4d2_exchange_bot_v2_all_11_second_wave_execution_132/all_11_second_wave_summary_v1.json")
SECOND_WAVE_PLAN_PATH = Path("runtime/r7a4d2_exchange_bot_v2_all_11_second_wave_execution_plan/all_11_second_wave_plan_v1.json")
OUTPUT_DIR = Path("runtime/r7a4d2_exchange_bot_v2_third_wave_targeted_repair_plan")
OUTPUT_NAME = "third_wave_targeted_repair_plan_v1.json"

EXPECTED_LANES = 11
EXPECTED_VARIANTS = 22
EXPECTED_CELLS = 132
ATR5_CONTROL = "dual_atr_volatility_bot:5m"
REFERENCE_LANE = "dual_donchian_trend_bot:15m"

SPECS: list[dict[str, Any]] = [
    {"lane_id":"directional_trend_grid_bot:15m","repair_axis":"CONTEXT_TO_EXECUTION_ROUTE_REBIND","variant_id":"trend_grid15_context_pullback_rebind","family":"grid_trend","execution_timeframe":"5m","design_class":"FULL_ROUTE_REBUILD"},
    {"lane_id":"directional_trend_grid_bot:15m","repair_axis":"ZERO_SIGNAL_COVERAGE_GUARD","variant_id":"trend_grid15_breakout_coverage_guard","family":"grid_trend","execution_timeframe":"5m","design_class":"FULL_ROUTE_REBUILD"},
    {"lane_id":"directional_trend_grid_bot:5m","repair_axis":"FAMILY_HYPOTHESIS_REBUILD","variant_id":"trend_grid5_regime_switch_rebuild","family":"grid_trend","execution_timeframe":"5m","design_class":"FULL_FAMILY_REBUILD"},
    {"lane_id":"directional_trend_grid_bot:5m","repair_axis":"REPLACE_WITH_ORTHOGONAL_SIBLING_FACTOR","variant_id":"trend_grid5_donchian_inventory_sibling","family":"grid_trend","execution_timeframe":"5m","design_class":"ORTHOGONAL_SIBLING_REPLACEMENT"},
    {"lane_id":"dual_atr_volatility_bot:15m","repair_axis":"NEGATIVE_FOLD_REGIME_SYMBOL_VETO","variant_id":"atr15_negative_fold_context_veto","family":"breakout","execution_timeframe":"5m","design_class":"TARGETED_STABILITY_REPAIR"},
    {"lane_id":"dual_atr_volatility_bot:15m","repair_axis":"FOLD_BALANCED_REENTRY_OR_COOLDOWN","variant_id":"atr15_balanced_cooldown_reentry","family":"breakout","execution_timeframe":"5m","design_class":"TARGETED_STABILITY_REPAIR"},
    {"lane_id":"dual_atr_volatility_bot:5m","repair_axis":"TIMEOUT_MFE_CAPTURE_DEFENSE","variant_id":"atr5_mfe_timeout_capture","family":"breakout","execution_timeframe":"5m","design_class":"CONTROL_MARGIN_UPLIFT"},
    {"lane_id":"dual_atr_volatility_bot:5m","repair_axis":"MAKER_FIRST_COST_FLOOR","variant_id":"atr5_retest_cost_floor","family":"breakout","execution_timeframe":"5m","design_class":"CONTROL_MARGIN_UPLIFT"},
    {"lane_id":"dual_donchian_trend_bot:5m","repair_axis":"MAKER_FIRST_COST_ADMISSION","variant_id":"donchian5_retest_limit_cost","family":"trend","execution_timeframe":"5m","design_class":"TARGETED_COST_REPAIR"},
    {"lane_id":"dual_donchian_trend_bot:5m","repair_axis":"TARGET_TO_COST_FLOOR_AND_TIMEOUT_REPRICE","variant_id":"donchian5_cost_floor_mfe_exit","family":"trend","execution_timeframe":"5m","design_class":"TARGETED_COST_REPAIR"},
    {"lane_id":"dual_ma_trend_bot:15m","repair_axis":"CONTEXT_TO_EXECUTION_ROUTE_REBIND","variant_id":"ma15_context_5m_pullback_rebind","family":"trend","execution_timeframe":"5m","design_class":"FULL_ROUTE_REBUILD"},
    {"lane_id":"dual_ma_trend_bot:15m","repair_axis":"ZERO_SIGNAL_COVERAGE_GUARD","variant_id":"ma15_persistent_state_coverage","family":"trend","execution_timeframe":"5m","design_class":"FULL_ROUTE_REBUILD"},
    {"lane_id":"dual_ma_trend_bot:5m","repair_axis":"MAKER_FIRST_COST_ADMISSION","variant_id":"ma5_retest_limit_cost","family":"trend","execution_timeframe":"5m","design_class":"TARGETED_COST_REPAIR"},
    {"lane_id":"dual_ma_trend_bot:5m","repair_axis":"TARGET_TO_COST_FLOOR_AND_TIMEOUT_REPRICE","variant_id":"ma5_side_specific_timeout_cost","family":"trend","execution_timeframe":"5m","design_class":"TARGETED_COST_REPAIR"},
    {"lane_id":"dual_vwap_mean_reversion_bot:15m","repair_axis":"CONTEXT_TO_EXECUTION_ROUTE_REBIND","variant_id":"vwap15_context_outer_reclaim_rebind","family":"mean_reversion","execution_timeframe":"5m","design_class":"FULL_ROUTE_REBUILD"},
    {"lane_id":"dual_vwap_mean_reversion_bot:15m","repair_axis":"ZERO_SIGNAL_COVERAGE_GUARD","variant_id":"vwap15_dual_anchor_coverage","family":"mean_reversion","execution_timeframe":"5m","design_class":"FULL_ROUTE_REBUILD"},
    {"lane_id":"dual_vwap_mean_reversion_bot:5m","repair_axis":"CONTEXT_TO_EXECUTION_ROUTE_REBIND","variant_id":"vwap5_context_side_rebind","family":"mean_reversion","execution_timeframe":"5m","design_class":"FULL_ROUTE_REBUILD"},
    {"lane_id":"dual_vwap_mean_reversion_bot:5m","repair_axis":"ZERO_SIGNAL_COVERAGE_GUARD","variant_id":"vwap5_exhaustion_sibling_coverage","family":"mean_reversion","execution_timeframe":"5m","design_class":"ORTHOGONAL_SIBLING_REPLACEMENT"},
    {"lane_id":"neutral_multi_level_grid_bot:15m","repair_axis":"CONTEXT_TO_EXECUTION_ROUTE_REBIND","variant_id":"neutral_grid15_efficiency_inventory_rebind","family":"grid_range","execution_timeframe":"5m","design_class":"FULL_INVENTORY_REBUILD"},
    {"lane_id":"neutral_multi_level_grid_bot:15m","repair_axis":"ZERO_SIGNAL_COVERAGE_GUARD","variant_id":"neutral_grid15_adaptive_center_coverage","family":"grid_range","execution_timeframe":"5m","design_class":"FULL_INVENTORY_REBUILD"},
    {"lane_id":"neutral_multi_level_grid_bot:5m","repair_axis":"CONTEXT_TO_EXECUTION_ROUTE_REBIND","variant_id":"neutral_grid5_efficiency_inventory_rebind","family":"grid_range","execution_timeframe":"5m","design_class":"FULL_INVENTORY_REBUILD"},
    {"lane_id":"neutral_multi_level_grid_bot:5m","repair_axis":"ZERO_SIGNAL_COVERAGE_GUARD","variant_id":"neutral_grid5_volatility_band_coverage","family":"grid_range","execution_timeframe":"5m","design_class":"FULL_INVENTORY_REBUILD"},
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
        tmp = Path(handle.name)
    os.replace(tmp, path)

def self_test() -> int:
    assert len(SPECS) == EXPECTED_VARIANTS
    assert len({row["variant_id"] for row in SPECS}) == EXPECTED_VARIANTS
    lanes = {row["lane_id"] for row in SPECS}
    assert len(lanes) == EXPECTED_LANES
    assert all(sum(1 for row in SPECS if row["lane_id"] == lane) == 2 for lane in lanes)
    assert sum(row["lane_id"] == ATR5_CONTROL for row in SPECS) == 2
    print("STATE=PASS_EXCHANGE_BOT_V2_THIRD_WAVE_TARGETED_REPAIR_PLAN_SELF_TEST")
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
    required = [root / CAUSALITY_PATH, root / SECOND_WAVE_SUMMARY_PATH, root / SECOND_WAVE_PLAN_PATH]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        print("STATE=HOLD_EXCHANGE_BOT_V2_THIRD_WAVE_TARGETED_REPAIR_PLAN_INPUT")
        print("BLOCKER_COUNT=1")
        print("BLOCKERS=" + json.dumps(["REQUIRED_EVIDENCE_MISSING:" + ",".join(missing)]))
        print("RC=2")
        return 2

    causality = load_json(root / CAUSALITY_PATH)
    previous_summary = load_json(root / SECOND_WAVE_SUMMARY_PATH)
    previous_plan = load_json(root / SECOND_WAVE_PLAN_PATH)
    blockers: list[str] = []

    if causality.get("state") != "PASS_SECOND_WAVE_FAILURE_CAUSALITY_DECOMPOSITION":
        blockers.append("CAUSALITY_NOT_PASS")
    lane_rows = [row for row in causality.get("lane_causality_rows", []) if isinstance(row, dict)]
    repair_rows = [row for row in causality.get("target_repair_rows", []) if isinstance(row, dict)]
    if len(lane_rows) != EXPECTED_LANES:
        blockers.append(f"LANE_COUNT_INVALID:{len(lane_rows)}")
    if len(repair_rows) != EXPECTED_VARIANTS:
        blockers.append(f"REPAIR_ROW_COUNT_INVALID:{len(repair_rows)}")
    expected_pairs = {(str(row.get("lane_id")), str(row.get("repair_axis"))) for row in repair_rows}
    spec_pairs = {(row["lane_id"], row["repair_axis"]) for row in SPECS}
    if expected_pairs != spec_pairs:
        blockers.append("REPAIR_AXIS_SPEC_MISMATCH")
    previous_lane_rows = [row for row in previous_summary.get("lane_best_rows", []) if isinstance(row, dict)]
    previous_lane_map = {str(row.get("source_lane_id")): row for row in previous_lane_rows}
    if len(previous_lane_map) != EXPECTED_LANES:
        blockers.append(f"PREVIOUS_LANE_MAP_INVALID:{len(previous_lane_map)}")
    reference_metrics = previous_plan.get("reference_metrics")
    if not isinstance(reference_metrics, dict):
        blockers.append("REFERENCE_METRICS_MISSING")
    if blockers:
        print("STATE=HOLD_EXCHANGE_BOT_V2_THIRD_WAVE_TARGETED_REPAIR_PLAN_INPUT")
        print("BLOCKER_COUNT=" + str(len(blockers)))
        print("BLOCKERS=" + json.dumps(blockers))
        print("RC=2")
        return 2

    cause_map = {str(row["lane_id"]): row for row in lane_rows}
    rows: list[dict[str, Any]] = []
    for spec in SPECS:
        source = cause_map[spec["lane_id"]]
        rows.append({
            **spec,
            "primary_cause": source["primary_cause"],
            "source_variant_id": source["selected_variant_id"],
            "source_metrics": previous_lane_map[spec["lane_id"]],
            "control_preserved": spec["lane_id"] == ATR5_CONTROL,
            "parameter_optimization_allowed": False,
            "blind_stop_widening_allowed": False,
            "entry_threshold_relaxation_allowed": False,
            "future_validation_selection_allowed": False,
            "discovery_s_grade_allowed": False,
        })

    plan = {
        "state": "PASS_EXCHANGE_BOT_V2_THIRD_WAVE_TARGETED_REPAIR_PLAN",
        "target_sha": args.target_sha,
        "lane_count": EXPECTED_LANES,
        "bundle_count": EXPECTED_VARIANTS,
        "stress_cell_per_bundle": 6,
        "cell_target": EXPECTED_CELLS,
        "atr5_control_lane": ATR5_CONTROL,
        "atr5_control_preserved": True,
        "reference_lane_id": REFERENCE_LANE,
        "reference_metrics": reference_metrics,
        "third_wave_rows": rows,
        "mutation_rows": [],
        "next_stage": "R7.A4D2_EXCHANGE_BOT_V2_THIRD_WAVE_TARGETED_REPAIR_EXECUTION_132",
    }
    output = root / OUTPUT_DIR / OUTPUT_NAME
    atomic_json(output, plan)
    print("STATE=PASS_EXCHANGE_BOT_V2_THIRD_WAVE_TARGETED_REPAIR_PLAN")
    print("BLOCKER_COUNT=0")
    print("THIRD_WAVE_LANE_COUNT=11")
    print("THIRD_WAVE_BUNDLE_COUNT=22")
    print("THIRD_WAVE_CELL_TARGET=132")
    print("ATR5_CONTROL_PRESERVED=true")
    print("PLAN_JSON=" + str(output))
    print("NEXT_STAGE=" + plan["next_stage"])
    print("BLOCKERS=[]")
    print("RC=0")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
