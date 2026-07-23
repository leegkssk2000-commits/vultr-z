#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any

MA5_OOS_SUMMARY = Path("runtime/r7a4d2_ma5_independent_oos_expansion/ma5_independent_oos_summary_v1.json")
MA5_SIDE_SUMMARY = Path("runtime/r7a4d2_incremental_defect4_ma5_side_specialization_6/ma5_side_specialization_summary_v1.json")
SECOND_WAVE_SUMMARY = Path("runtime/r7a4d2_exchange_bot_v2_all_11_second_wave_execution_132/all_11_second_wave_summary_v1.json")
OOS_OVERLAY_MANIFEST = Path("runtime/r7a4d2_ma5_oos_market_source_coverage_expansion/oos_overlay_frozen_input_manifest_v1.json")
OOS_COVERAGE_SUMMARY = Path("runtime/r7a4d2_ma5_oos_market_source_coverage_expansion/market_source_coverage_expansion_summary_v1.json")
OUTPUT_DIR = Path("runtime/r7a4d2_ma5_observer_material_reclassify")
RECLASS_PATH = OUTPUT_DIR / "ma5_observer_material_reclassification_v1.json"
BATCH_PLAN_PATH = OUTPUT_DIR / "remaining_survivor_independent_oos_batch_plan_v1.json"

MA5_LANE_ID = "dual_ma_trend_bot:5m"
MA5_VARIANTS = {"ma5_accel_15m_alignment", "ma5_confluence_first_pullback"}
EXPECTED_LANE_BEST = 11
EXPECTED_REMAINING = 10
EXPECTED_SEGMENTS = 240
EXPECTED_STRESS_CELLS = 6
EXPECTED_FOLDS = 6
MIN_EVENTS = 24
MIN_SYMBOLS = 3


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def sha256_file(path: Path) -> str | None:
    if not path.is_file() or path.is_symlink():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def finite(value: Any, default: float = math.nan) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--target-sha", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    required = [
        root / MA5_OOS_SUMMARY,
        root / MA5_SIDE_SUMMARY,
        root / SECOND_WAVE_SUMMARY,
        root / OOS_OVERLAY_MANIFEST,
        root / OOS_COVERAGE_SUMMARY,
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        print("STATE=HOLD_MA5_OBSERVER_MATERIAL_RECLASSIFY_INPUT")
        print("BLOCKERS=" + json.dumps(["REQUIRED_EVIDENCE_MISSING:" + ",".join(missing)]))
        print("RC=2")
        return 2

    before = {str(path): sha256_file(path) for path in required}
    oos = load_json(root / MA5_OOS_SUMMARY)
    side = load_json(root / MA5_SIDE_SUMMARY)
    second = load_json(root / SECOND_WAVE_SUMMARY)
    overlay = load_json(root / OOS_OVERLAY_MANIFEST)
    coverage = load_json(root / OOS_COVERAGE_SUMMARY)

    blockers: list[str] = []
    if oos.get("state") != "PASS_MA5_INDEPENDENT_OOS_EXPANSION":
        blockers.append("MA5_OOS_STATE_NOT_PASS")
    if oos.get("classification") != "MA5_OOS_FAIL":
        blockers.append("MA5_OOS_CLASSIFICATION_NOT_FAIL")
    if bool(oos.get("robust_survivor")) or bool(oos.get("conditional_survivor")):
        blockers.append("MA5_OOS_SURVIVOR_FLAG_TRUE")
    if not bool(oos.get("coverage_ready")):
        blockers.append("MA5_OOS_COVERAGE_NOT_READY")
    if int(oos.get("strict_forward_oos_segment_count", -1)) != EXPECTED_SEGMENTS:
        blockers.append("MA5_OOS_SEGMENT_COUNT_CHANGED")
    if int(oos.get("signal_fold_count", -1)) != EXPECTED_FOLDS:
        blockers.append("MA5_OOS_FOLD_COUNT_CHANGED")
    if int(oos.get("stress_cell_count", -1)) != EXPECTED_STRESS_CELLS:
        blockers.append("MA5_OOS_STRESS_CELL_COUNT_CHANGED")
    if int(oos.get("unique_long_signal_count", -1)) < MIN_EVENTS:
        blockers.append("MA5_OOS_EVENT_COUNT_BELOW_GATE")
    if int(oos.get("signal_symbol_count", -1)) < MIN_SYMBOLS:
        blockers.append("MA5_OOS_SYMBOL_COUNT_BELOW_GATE")
    if int(oos.get("mutation_path_count", -1)) != 0:
        blockers.append("MA5_OOS_INPUT_MUTATION_DETECTED")

    profile_metrics = oos.get("profile_metrics") if isinstance(oos.get("profile_metrics"), dict) else {}
    for profile in ("base", "adverse", "severe"):
        metrics = profile_metrics.get(profile) if isinstance(profile_metrics.get(profile), dict) else {}
        if finite(metrics.get("net_r_sum"), math.inf) >= 0:
            blockers.append(f"MA5_{profile.upper()}_NET_NOT_NEGATIVE")
        if finite(metrics.get("profit_factor"), math.inf) >= 1.0:
            blockers.append(f"MA5_{profile.upper()}_PF_NOT_BELOW_ONE")
        if int(metrics.get("positive_fold_count", -1)) != 0:
            blockers.append(f"MA5_{profile.upper()}_POSITIVE_FOLDS_NOT_ZERO")

    if side.get("state") != "PASS_INCREMENTAL_DEFECT4_MA5_SIDE_SPECIALIZATION_6":
        blockers.append("MA5_SIDE_REPAIR_STATE_CHANGED")
    if not bool((side.get("pass_checks") or {}).get("repair_pass")):
        blockers.append("MA5_SIDE_REPAIR_NOT_PASS")
    if bool(side.get("robust_survivor")):
        blockers.append("MA5_SIDE_ROBUST_FLAG_CHANGED")

    if second.get("state") != "PASS_EXCHANGE_BOT_V2_ALL_11_SECOND_WAVE_EXECUTION_132":
        blockers.append("SECOND_WAVE_STATE_NOT_PASS")
    lane_best = [row for row in second.get("lane_best_rows", []) if isinstance(row, dict)]
    if len(lane_best) != EXPECTED_LANE_BEST:
        blockers.append(f"LANE_BEST_COUNT_INVALID:{len(lane_best)}")

    if overlay.get("state") != "PASS" or int(overlay.get("oos_generated_market_source_count", -1)) < MIN_SYMBOLS:
        blockers.append("OOS_OVERLAY_INVALID")
    if coverage.get("state") != "PASS_MA5_OOS_MARKET_SOURCE_COVERAGE_EXPANSION":
        blockers.append("OOS_COVERAGE_STATE_NOT_PASS")
    if int(coverage.get("mutation_path_count", -1)) != 0:
        blockers.append("OOS_COVERAGE_MUTATION_DETECTED")

    remaining: list[dict[str, Any]] = []
    ma5_rows: list[dict[str, Any]] = []
    for row in lane_best:
        lane_id = str(row.get("source_lane_id") or "")
        variant_id = str(row.get("variant_id") or "")
        if lane_id == MA5_LANE_ID or variant_id in MA5_VARIANTS:
            ma5_rows.append(row)
            continue
        remaining.append({
            "source_lane_id": lane_id,
            "variant_id": variant_id,
            "execution_timeframe": str(row.get("execution_timeframe") or lane_id.rsplit(":", 1)[-1]),
            "family": row.get("family"),
            "repair_class": row.get("repair_class"),
            "prior_uplift_discovery_pass": bool(row.get("uplift_discovery_pass")),
            "prior_reference_beating_discovery_pass": bool(row.get("reference_beating_discovery_pass")),
            "prior_candidate_risk_score": finite(row.get("candidate_risk_score"), 0.0),
            "prior_baseline_risk_score": finite(row.get("baseline_risk_score"), 0.0),
            "prior_base_metrics": row.get("base_metrics") if isinstance(row.get("base_metrics"), dict) else {},
            "prior_adverse_metrics": row.get("adverse_metrics") if isinstance(row.get("adverse_metrics"), dict) else {},
            "prior_severe_tail_metrics": row.get("severe_tail_metrics") if isinstance(row.get("severe_tail_metrics"), dict) else {},
        })

    remaining.sort(key=lambda row: (row["source_lane_id"], row["variant_id"]))
    if len(ma5_rows) != 1:
        blockers.append(f"MA5_LANE_BEST_MATCH_COUNT_INVALID:{len(ma5_rows)}")
    if len(remaining) != EXPECTED_REMAINING:
        blockers.append(f"REMAINING_CANDIDATE_COUNT_INVALID:{len(remaining)}")
    if len({row["source_lane_id"] for row in remaining}) != EXPECTED_REMAINING:
        blockers.append("REMAINING_LANE_DUPLICATE")
    if any(not row["source_lane_id"] or not row["variant_id"] for row in remaining):
        blockers.append("REMAINING_CANDIDATE_ID_MISSING")

    after = {str(path): sha256_file(path) for path in required}
    input_mutations = sorted(path for path in before if before[path] != after[path])
    if input_mutations:
        blockers.append(f"READ_ONLY_INPUT_MUTATION:{len(input_mutations)}")

    blockers = list(dict.fromkeys(blockers))
    if blockers:
        print("STATE=HOLD_MA5_OBSERVER_MATERIAL_RECLASSIFY")
        print("BLOCKER_COUNT=" + str(len(blockers)))
        print("BLOCKERS=" + json.dumps(blockers))
        print("RC=2")
        return 2

    oos_profiles = {
        profile: {
            "net_r": finite((profile_metrics.get(profile) or {}).get("net_r_sum"), 0.0),
            "profit_factor": finite((profile_metrics.get(profile) or {}).get("profit_factor"), 0.0),
            "max_drawdown_r": finite((profile_metrics.get(profile) or {}).get("max_drawdown_r"), 0.0),
            "positive_folds": int((profile_metrics.get(profile) or {}).get("positive_fold_count", 0)),
            "unique_events": int((profile_metrics.get(profile) or {}).get("unique_event_count", 0)),
            "symbols": int((profile_metrics.get(profile) or {}).get("symbol_count", 0)),
        }
        for profile in ("base", "adverse", "severe")
    }

    reclassification = {
        "schema": "r7a4d2_ma5_observer_material_reclassification_v1",
        "official_stage": "R7.A4D2_MA5_OBSERVER_MATERIAL_RECLASSIFY",
        "state": "PASS_MA5_OBSERVER_MATERIAL_RECLASSIFY",
        "target_commit": args.target_sha,
        "source_lane_id": MA5_LANE_ID,
        "source_variant_id": str(ma5_rows[0].get("variant_id") or ""),
        "previous_candidate_variant_id": "ma5_long_only_side_specialization",
        "classification": "OBSERVER_MATERIAL",
        "standalone_candidate_allowed": False,
        "portfolio_weight_allowed": False,
        "shadow_active_allowed": False,
        "paper_live_order_allowed": False,
        "strategy_mutation_allowed": False,
        "exit_repair_allowed": False,
        "parameter_optimization_allowed": False,
        "permitted_uses": [
            "loss_taxonomy_reference",
            "regime_failure_observer",
            "feature_attribution_material",
            "ensemble_negative_control",
        ],
        "reclassification_reason": "FULL_STRICT_FORWARD_OOS_FAILURE_ACROSS_BASE_ADVERSE_SEVERE_AND_ALL_6_FOLDS",
        "oos_segment_count": int(oos.get("strict_forward_oos_segment_count", 0)),
        "oos_unique_long_signal_count": int(oos.get("unique_long_signal_count", 0)),
        "oos_symbol_count": int(oos.get("signal_symbol_count", 0)),
        "oos_fold_count": int(oos.get("signal_fold_count", 0)),
        "oos_stress_cell_count": int(oos.get("stress_cell_count", 0)),
        "oos_profiles": oos_profiles,
        "worst_severe_cell_metrics": oos.get("worst_severe_cell_metrics") if isinstance(oos.get("worst_severe_cell_metrics"), dict) else {},
        "input_mutation_count": 0,
        "next_stage": "R7.A4D2_REMAINING_SURVIVOR_INDEPENDENT_OOS_BATCH",
    }

    batch_plan = {
        "schema": "r7a4d2_remaining_survivor_independent_oos_batch_plan_v1",
        "official_stage": "R7.A4D2_REMAINING_SURVIVOR_INDEPENDENT_OOS_BATCH_PLAN",
        "state": "PASS_REMAINING_SURVIVOR_INDEPENDENT_OOS_BATCH_PLAN",
        "target_commit": args.target_sha,
        "selection_policy": "PRIOR_FIXED_LANE_BEST_EXCLUDING_MA5_NO_OOS_PERFORMANCE_RESELECTION",
        "candidate_count": len(remaining),
        "candidates": remaining,
        "market_overlay_manifest_path": str(OOS_OVERLAY_MANIFEST),
        "selected_discovery_manifest_path": "runtime/r7a4c_historical_simulation_input_lineage/selected_input_manifest_v1.json",
        "execution_calibration_path": "runtime/r7a4d2_short_economic_calibration_and_exchange_bot_benchmark_v2_plan/economic_calibration_and_exchange_bot_benchmark_v2_plan_v1.json",
        "expected_strict_forward_segment_count": EXPECTED_SEGMENTS,
        "expected_stress_cell_count_per_candidate": EXPECTED_STRESS_CELLS,
        "expected_fold_count": EXPECTED_FOLDS,
        "minimum_unique_events": MIN_EVENTS,
        "minimum_symbols": MIN_SYMBOLS,
        "parameter_optimization_allowed": False,
        "candidate_reselection_allowed": False,
        "strategy_mutation_allowed": False,
        "registry_mutation_allowed": False,
        "config_mutation_allowed": False,
        "router_mutation_allowed": False,
        "service_mutation_allowed": False,
        "shadow_start_allowed": False,
        "paper_live_order_allowed": False,
        "next_stage": "R7.A4D2_REMAINING_SURVIVOR_INDEPENDENT_OOS_BATCH_EXECUTION",
    }

    output = root / OUTPUT_DIR
    atomic_json(output / RECLASS_PATH.name, reclassification)
    atomic_json(output / BATCH_PLAN_PATH.name, batch_plan)

    print("STATE=PASS_MA5_OBSERVER_MATERIAL_RECLASSIFY")
    print("BLOCKER_COUNT=0")
    print("MA5_CLASSIFICATION=OBSERVER_MATERIAL")
    print("MA5_STANDALONE_ALLOWED=false")
    print("MA5_EXIT_REPAIR_ALLOWED=false")
    print("MA5_OOS_BASE_NET_R=" + f"{oos_profiles['base']['net_r']:.12f}")
    print("MA5_OOS_ADVERSE_NET_R=" + f"{oos_profiles['adverse']['net_r']:.12f}")
    print("MA5_OOS_SEVERE_NET_R=" + f"{oos_profiles['severe']['net_r']:.12f}")
    print("REMAINING_OOS_CANDIDATE_COUNT=" + str(len(remaining)))
    for row in remaining:
        print("OOS_CANDIDATE=" + row["source_lane_id"] + "|" + row["variant_id"] + "|" + row["execution_timeframe"])
    print("RECLASS_JSON=" + str(output / RECLASS_PATH.name))
    print("BATCH_PLAN_JSON=" + str(output / BATCH_PLAN_PATH.name))
    print("INPUT_MUTATION_COUNT=0")
    print("NEXT_STAGE=R7.A4D2_REMAINING_SURVIVOR_INDEPENDENT_OOS_BATCH_EXECUTION")
    print("BLOCKERS=[]")
    print("RC=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
