#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

DISCOVERY_DIR = Path("runtime/r7a4d2_short_native_family_architecture_discovery_execution_132")
DISCOVERY_LOCK = DISCOVERY_DIR / "architecture_discovery_lock_v1.json"
DISCOVERY_CELLS = DISCOVERY_DIR / "architecture_cell_results_v1.jsonl"
DISCOVERY_TRADES = DISCOVERY_DIR / "architecture_trade_results_v1.jsonl"
REBUILD_PLAN = Path("runtime/r7a4d2_short_vwap_native_hypothesis_and_remaining_family_rebuild_plan/rebuild_plan_v1.json")
MANIFEST = Path("runtime/r7a4c_historical_simulation_input_lineage/selected_input_manifest_v1.json")
OUTPUT_DIR = Path("runtime/r7a4d2_short_native_architecture_disjoint_validation_and_near_miss_rescue_plan")

EXPECTED_STRATEGIES = 11
EXPECTED_BUNDLES = 22
EXPECTED_DISCOVERY_CELLS = 132
EXPECTED_VALIDATION_SEGMENTS = 12
EXPECTED_STRESS_PER_BUNDLE = 6
SEVERE_CELL = ("cost_profile_2", "perturbation_1")
MIN_TRADES = 8
MAX_RESCUE_STRATEGIES = 6
SECOND_GEN_VARIANTS_PER_STRATEGY = 2


def import_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"MODULE_SPEC_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"JSONL_OBJECT_REQUIRED:{path}:{line_no}")
            rows.append(value)
    return rows


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def finite(value: Any, default: float = 0.0) -> float:
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    if value == float("inf"):
        return 1e100
    return default


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def strict_pass(helper: Any, row: dict[str, Any]) -> bool:
    return bool(
        int(row.get("trade_count") or 0) >= MIN_TRADES
        and helper.finite_metric(row.get("profit_factor")) > 1.25
        and helper.finite_metric(row.get("expectancy_r")) > 0.15
        and helper.finite_metric(row.get("net_pnl_sum_pct")) > 0.0
    )


def economic_pass(helper: Any, row: dict[str, Any]) -> bool:
    return bool(
        int(row.get("trade_count") or 0) >= MIN_TRADES
        and helper.finite_metric(row.get("profit_factor")) > 1.0
        and helper.finite_metric(row.get("expectancy_r")) > 0.0
        and helper.finite_metric(row.get("net_pnl_sum_pct")) > 0.0
    )


def rescue_axis(metrics: dict[str, Any], signal_count: int, positive_cells: int) -> tuple[str, str]:
    trades = int(metrics.get("trade_count") or 0)
    pf = finite(metrics.get("profit_factor"), 0.0)
    expectancy = finite(metrics.get("expectancy_r"), -9.0)
    if positive_cells >= 3:
        return "COST_TIMING_ROBUSTNESS_REDESIGN", "retain native trigger; reduce churn and late fills without widening stops"
    if signal_count >= 12 and trades >= MIN_TRADES and pf < 1.0:
        return "ENTRY_REGIME_HYPOTHESIS_REBUILD", "signal density exists but edge is negative; rebuild context and invalidation logic"
    if signal_count >= 12 and trades >= MIN_TRADES and pf >= 1.0 and expectancy <= 0.15:
        return "PAYOFF_EXIT_STRUCTURE_REBUILD", "edge exists but payoff is too weak; rebuild target, partial and timeout geometry"
    if signal_count >= 8 and trades < MIN_TRADES:
        return "TIMEFRAME_ROUTE_EVENT_AGGREGATION", "preserve threshold; aggregate events or route to native higher timeframe"
    if 4 <= signal_count < 8:
        return "SEMANTIC_RECONSTRUCTION", "rebuild family-native event semantics; no threshold relaxation"
    return "RETIRE_OR_REPLACE", "insufficient native evidence after complete architecture rebuild"


def rescue_score(metrics: dict[str, Any], signal_count: int, positive_cells: int, strict_positive_cells: int) -> float:
    trades = int(metrics.get("trade_count") or 0)
    pf = max(0.0, finite(metrics.get("profit_factor"), 0.0))
    expectancy = finite(metrics.get("expectancy_r"), -2.0)
    pnl = finite(metrics.get("net_pnl_sum_pct"), -100.0)
    dd_ok = bool(metrics.get("drawdown_nonworsening_vs_reference", True))
    score = 0.0
    score += 30.0 * clamp(positive_cells / 4.0, 0.0, 1.0)
    score += 10.0 * clamp(strict_positive_cells / 4.0, 0.0, 1.0)
    score += 20.0 * clamp(pf / 1.25, 0.0, 1.0)
    score += 15.0 * clamp((expectancy + 0.40) / 0.55, 0.0, 1.0)
    score += 10.0 * clamp(trades / MIN_TRADES, 0.0, 1.0)
    score += 10.0 * clamp(signal_count / 12.0, 0.0, 1.0)
    score += 5.0 if dd_ok else 0.0
    if pnl > 0:
        score += 5.0
    return round(score, 6)


def build_rescue_rows(discovery: dict[str, Any], strict_strategy_ids: set[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    signal_counts = {str(key): int(value) for key, value in discovery.get("signal_count_by_bundle", {}).items()}
    audited: list[dict[str, Any]] = []
    for row in discovery.get("candidate_rows", []):
        if not isinstance(row, dict):
            continue
        strategy_id = str(row.get("strategy_id") or "")
        if strategy_id in strict_strategy_ids:
            continue
        metrics = row.get("severe_metrics") if isinstance(row.get("severe_metrics"), dict) else {}
        bundle_id = str(row.get("bundle_id") or "")
        positive = int(row.get("positive_stress_cell_count") or 0)
        strict_positive = int(row.get("strict_positive_stress_cell_count") or 0)
        signal_count = signal_counts.get(bundle_id, 0)
        axis, reason = rescue_axis(metrics, signal_count, positive)
        score_metrics = dict(metrics)
        score_metrics["drawdown_nonworsening_vs_reference"] = bool(row.get("drawdown_nonworsening_vs_reference", True))
        score = rescue_score(score_metrics, signal_count, positive, strict_positive)
        audited.append({
            "strategy_id": strategy_id,
            "family": row.get("family"),
            "bundle_id": bundle_id,
            "batch": row.get("batch"),
            "role": row.get("role"),
            "signal_count": signal_count,
            "severe_trade_count": int(metrics.get("trade_count") or 0),
            "severe_profit_factor": metrics.get("profit_factor"),
            "severe_expectancy_r": metrics.get("expectancy_r"),
            "severe_net_pnl_sum_pct": metrics.get("net_pnl_sum_pct"),
            "severe_max_drawdown_pct": metrics.get("max_drawdown_pct"),
            "positive_stress_cell_count": positive,
            "strict_positive_stress_cell_count": strict_positive,
            "drawdown_nonworsening_vs_reference": bool(row.get("drawdown_nonworsening_vs_reference", True)),
            "rescue_axis": axis,
            "rescue_reason": reason,
            "rescue_score": score,
        })
    by_strategy: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in audited:
        by_strategy[str(row["strategy_id"])].append(row)
    selected: list[dict[str, Any]] = []
    for strategy_id, rows in sorted(by_strategy.items()):
        eligible = [row for row in rows if row["rescue_axis"] != "RETIRE_OR_REPLACE"]
        eligible.sort(key=lambda row: (float(row["rescue_score"]), int(row["positive_stress_cell_count"]), int(row["signal_count"])), reverse=True)
        if eligible:
            selected.append(eligible[0])
    selected.sort(key=lambda row: (float(row["rescue_score"]), int(row["positive_stress_cell_count"]), int(row["signal_count"])), reverse=True)
    selected = selected[:MAX_RESCUE_STRATEGIES]
    for rank, row in enumerate(selected, 1):
        row["rescue_rank"] = rank
        row["second_generation_variant_count"] = SECOND_GEN_VARIANTS_PER_STRATEGY
        row["stop_widening_allowed"] = False
        row["entry_threshold_relaxation_allowed"] = False
        row["future_validation_selection_allowed"] = False
    return audited, selected


def validate_strict_bundles(
    root: Path,
    engine: Any,
    raw: Any,
    helper: Any,
    contract: dict[str, Any],
    manifest: dict[str, Any],
    plan: dict[str, Any],
    discovery: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    bundles = {str(row["bundle_id"]): row for row in plan.get("architecture_bundles", []) if isinstance(row, dict)}
    strict_locks = [row for row in discovery.get("strategy_lock_rows", []) if isinstance(row, dict) and row.get("disjoint_validation_allowed") is True]
    validation_segments = {
        str(row["segment_id"]): row
        for row in manifest.get("selected_segments", [])
        if isinstance(row, dict) and int(row.get("fold", -1)) >= 3
    }
    if len(validation_segments) != EXPECTED_VALIDATION_SEGMENTS:
        raise ValueError(f"VALIDATION_SEGMENT_COUNT_INVALID:{len(validation_segments)}")
    costs = [row for row in contract.get("cost_profiles", []) if isinstance(row, dict)]
    perturbations = [row for row in contract.get("perturbations", []) if isinstance(row, dict)]
    source_sha = {str(row.get("source_path")): str(row.get("source_sha256") or "") for row in manifest.get("selected_segments", []) if isinstance(row, dict)}
    source_cache: dict[str, pd.DataFrame] = {}
    frame_cache: dict[tuple[str, str], pd.DataFrame] = {}
    mask_cache: dict[tuple[str, str], pd.Series] = {}
    feature_cache: dict[tuple[str, str], dict[str, pd.Series]] = {}
    trade_rows: list[dict[str, Any]] = []
    cell_rows: list[dict[str, Any]] = []
    validation_rows: list[dict[str, Any]] = []
    for lock in strict_locks:
        bundle_id = str(lock.get("selected_bundle_id") or "")
        bundle = bundles.get(bundle_id)
        if bundle is None:
            raise ValueError(f"LOCKED_BUNDLE_MISSING:{bundle_id}")
        trigger_tf = str(bundle["trigger_timeframe"])
        bundle_signals: dict[str, list[dict[str, Any]]] = {}
        for segment_id, segment in sorted(validation_segments.items()):
            source_path = str(segment["source_path"])
            if source_path not in source_cache:
                source_cache[source_path] = raw.fixed_ohlcv_frame(root / helper.safe_repo_path(source_path), source_sha[source_path])
            frames: dict[str, pd.DataFrame] = {}
            feats: dict[str, dict[str, pd.Series]] = {}
            masks: dict[str, pd.Series] = {}
            for timeframe in {str(bundle["context_timeframe"]), str(bundle["setup_timeframe"]), trigger_tf}:
                key = (segment_id, timeframe)
                if key not in frame_cache:
                    frame_cache[key] = raw.resample_for_segment(source_cache[source_path], int(segment["start_row"]), int(segment["end_row_exclusive"]), timeframe)
                    mask_cache[key] = raw.measurement_mask(frame_cache[key], int(segment["start_row"]), int(segment["end_row_exclusive"]))
                    feature_cache[key] = engine.features(frame_cache[key])
                frames[timeframe] = frame_cache[key]
                masks[timeframe] = mask_cache[key]
                feats[timeframe] = feature_cache[key]
            bundle_signals[segment_id] = engine.build_signal(bundle, frames, feats, masks, segment)
        for cost in costs:
            for perturbation in perturbations:
                cell_trades: list[dict[str, Any]] = []
                for segment_id, segment in sorted(validation_segments.items()):
                    frame = frame_cache[(segment_id, trigger_tf)]
                    measurement = mask_cache[(segment_id, trigger_tf)]
                    last_exit = -1
                    for signal in bundle_signals[segment_id]:
                        if int(signal["entry_bar_index"]) <= last_exit:
                            continue
                        trade = engine.simulate_trade(frame, measurement, signal, cost, perturbation, trigger_tf)
                        if trade is None:
                            continue
                        last_exit = int(trade["exit_index"])
                        trade.update({
                            "bundle_id": bundle_id,
                            "strategy_id": bundle["strategy_id"],
                            "family": bundle["family"],
                            "cost_profile_id": cost["id"],
                            "perturbation_id": perturbation["id"],
                            "segment_id": segment_id,
                            "regime": segment["regime"],
                            "fold": int(segment["fold"]),
                            "symbol": str(frame.iloc[int(signal["signal_bar_index"])].get("symbol") or ""),
                            "signal_bar_index": int(signal["signal_bar_index"]),
                        })
                        trade_rows.append(trade)
                        cell_trades.append(trade)
                cell_rows.append({
                    "bundle_id": bundle_id,
                    "strategy_id": bundle["strategy_id"],
                    "cost_profile_id": cost["id"],
                    "perturbation_id": perturbation["id"],
                    **helper.aggregate_trades(cell_trades),
                })
        cells = [row for row in cell_rows if row["bundle_id"] == bundle_id]
        severe = next(row for row in cells if (str(row["cost_profile_id"]), str(row["perturbation_id"])) == SEVERE_CELL)
        strict_positive = sum(1 for row in cells if strict_pass(helper, row))
        positive = sum(1 for row in cells if economic_pass(helper, row))
        passed = strict_pass(helper, severe) and strict_positive >= 4
        validation_rows.append({
            "strategy_id": bundle["strategy_id"],
            "bundle_id": bundle_id,
            "validation_segment_count": len(validation_segments),
            "validation_signal_count": sum(len(value) for value in bundle_signals.values()),
            "severe_metrics": severe,
            "positive_stress_cell_count": positive,
            "strict_positive_stress_cell_count": strict_positive,
            "strict_disjoint_validation_pass": passed,
            "validation_status": "STRICT_DISJOINT_VALIDATED" if passed else "DISCOVERY_SURVIVOR_NOT_REPRODUCED",
        })
    return validation_rows, trade_rows, cell_rows


def self_test() -> int:
    metrics = {"trade_count": 8, "profit_factor": 0.95, "expectancy_r": -0.05, "net_pnl_sum_pct": -0.1}
    axis, _ = rescue_axis(metrics, 20, 3)
    assert axis == "COST_TIMING_ROBUSTNESS_REDESIGN"
    score = rescue_score(metrics, 20, 3, 1)
    assert score > 0
    print("STATE=PASS_SHORT_NATIVE_ARCHITECTURE_DISJOINT_VALIDATION_AND_NEAR_MISS_RESCUE_PLAN_SELF_TEST")
    print("RC=0")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--target-sha", default="UNKNOWN")
    parser.add_argument("--engine-module")
    parser.add_argument("--raw-module")
    parser.add_argument("--helper-module")
    parser.add_argument("--a4d-contract")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not all([args.engine_module, args.raw_module, args.helper_module, args.a4d_contract]):
        raise SystemExit("--engine-module --raw-module --helper-module --a4d-contract required")
    root = Path(args.root).resolve()
    engine = import_module(Path(args.engine_module).resolve(), "r7a4d2_disjoint_engine")
    raw = import_module(Path(args.raw_module).resolve(), "r7a4d2_disjoint_raw")
    helper = import_module(Path(args.helper_module).resolve(), "r7a4d2_disjoint_helper")
    required = [root / DISCOVERY_LOCK, root / DISCOVERY_CELLS, root / DISCOVERY_TRADES, root / REBUILD_PLAN, root / MANIFEST]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        print("STATE=HOLD_SHORT_NATIVE_ARCHITECTURE_DISJOINT_VALIDATION_AND_NEAR_MISS_RESCUE_PLAN_INPUT")
        print("BLOCKER_COUNT=1")
        print("BLOCKERS=" + json.dumps(["REQUIRED_EVIDENCE_MISSING:" + ",".join(missing)]))
        print("RC=2")
        return 2
    discovery = load_json(root / DISCOVERY_LOCK)
    discovery_cells = load_jsonl(root / DISCOVERY_CELLS)
    plan = load_json(root / REBUILD_PLAN)
    manifest = load_json(root / MANIFEST)
    contract = load_json(Path(args.a4d_contract).resolve())
    blockers: list[str] = []
    if discovery.get("state") != "PASS_SHORT_NATIVE_FAMILY_ARCHITECTURE_DISCOVERY_EXECUTION_132":
        blockers.append("DISCOVERY_NOT_PASS")
    if int(discovery.get("strategy_count") or 0) != EXPECTED_STRATEGIES:
        blockers.append("STRATEGY_COUNT_INVALID")
    if int(discovery.get("architecture_bundle_count") or 0) != EXPECTED_BUNDLES:
        blockers.append("BUNDLE_COUNT_INVALID")
    if len(discovery_cells) != EXPECTED_DISCOVERY_CELLS:
        blockers.append(f"DISCOVERY_CELL_COUNT_INVALID:{len(discovery_cells)}")
    strict_locks = [row for row in discovery.get("strategy_lock_rows", []) if isinstance(row, dict) and row.get("disjoint_validation_allowed") is True]
    if not strict_locks:
        blockers.append("STRICT_DISCOVERY_SURVIVOR_MISSING")
    if blockers:
        print("STATE=HOLD_SHORT_NATIVE_ARCHITECTURE_DISJOINT_VALIDATION_AND_NEAR_MISS_RESCUE_PLAN_INPUT")
        print("BLOCKER_COUNT=" + str(len(blockers)))
        print("BLOCKERS=" + json.dumps(blockers))
        print("RC=2")
        return 2
    canonical_paths = required.copy()
    for row in manifest.get("selected_segments", []):
        if isinstance(row, dict) and row.get("source_path"):
            canonical_paths.append(root / helper.safe_repo_path(str(row["source_path"])))
    protected = [Path(str(value)) for value in contract.get("protected_paths", [])]
    before = helper.snapshot(canonical_paths + protected)
    validation_rows, validation_trades, validation_cells = validate_strict_bundles(root, engine, raw, helper, contract, manifest, plan, discovery)
    strict_strategy_ids = {str(row["strategy_id"]) for row in validation_rows}
    audited_rows, rescue_rows = build_rescue_rows(discovery, strict_strategy_ids)
    after = helper.snapshot(canonical_paths + protected)
    mutation_paths = sorted(path for path in before if before[path] != after[path])
    mutation_rows = [{"path": path, "classification": helper.classify_mutation(path, root)} for path in mutation_paths]
    critical_mutations = [row for row in mutation_rows if row["classification"] != "EXTERNAL_OPERATIONAL_VOLATILE_MUTATION"]
    if critical_mutations:
        blockers.append(f"CRITICAL_MUTATIONS:{len(critical_mutations)}")
    validated = [row for row in validation_rows if row["strict_disjoint_validation_pass"]]
    retire_rows = [row for row in audited_rows if row["rescue_axis"] == "RETIRE_OR_REPLACE"]
    output = root / OUTPUT_DIR
    atomic_json(output / "strict_validation_and_rescue_plan_v1.json", {
        "schema": "r7a4d2_short_native_architecture_disjoint_validation_and_near_miss_rescue_plan_v1",
        "official_stage": "R7.A4D2_SHORT_NATIVE_ARCHITECTURE_DISJOINT_VALIDATION_AND_NEAR_MISS_RESCUE_PLAN",
        "state": "PASS_SHORT_NATIVE_ARCHITECTURE_DISJOINT_VALIDATION_AND_NEAR_MISS_RESCUE_PLAN" if not blockers else "HOLD_SHORT_NATIVE_ARCHITECTURE_DISJOINT_VALIDATION_AND_NEAR_MISS_RESCUE_PLAN",
        "target_commit": args.target_sha,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "strict_discovery_lock_count": len(strict_locks),
        "strict_validation_rows": validation_rows,
        "validated_strict_survivor_count": len(validated),
        "near_miss_audited_bundle_count": len(audited_rows),
        "near_miss_audit_rows": audited_rows,
        "rescue_candidate_count": len(rescue_rows),
        "rescue_strategy_count": len({str(row["strategy_id"]) for row in rescue_rows}),
        "rescue_priority_rows": rescue_rows,
        "second_generation_bundle_target": len(rescue_rows) * SECOND_GEN_VARIANTS_PER_STRATEGY,
        "second_generation_cell_target": len(rescue_rows) * SECOND_GEN_VARIANTS_PER_STRATEGY * EXPECTED_STRESS_PER_BUNDLE,
        "retire_or_replace_bundle_count": len(retire_rows),
        "stop_widening_allowed": False,
        "entry_threshold_relaxation_allowed": False,
        "future_validation_selection_allowed": False,
        "mutation_rows": mutation_rows,
        "next_stage": "R7.A4D2_SHORT_VALIDATED_SURVIVOR_LOCK_AND_SECOND_GENERATION_RESCUE_EXECUTION" if validated and rescue_rows else "R7.A4D2_SHORT_SECOND_GENERATION_RESCUE_EXECUTION" if rescue_rows else "R7.A4D2_SHORT_FAMILY_HYPOTHESIS_RETIRE_OR_REPLACE_AUDIT",
    })
    atomic_json(output / "validation_cells_v1.json", {"rows": validation_cells})
    atomic_json(output / "validation_trades_v1.json", {"rows": validation_trades})
    state = "PASS_SHORT_NATIVE_ARCHITECTURE_DISJOINT_VALIDATION_AND_NEAR_MISS_RESCUE_PLAN" if not blockers else "HOLD_SHORT_NATIVE_ARCHITECTURE_DISJOINT_VALIDATION_AND_NEAR_MISS_RESCUE_PLAN"
    next_stage = "R7.A4D2_SHORT_VALIDATED_SURVIVOR_LOCK_AND_SECOND_GENERATION_RESCUE_EXECUTION" if validated and rescue_rows else "R7.A4D2_SHORT_SECOND_GENERATION_RESCUE_EXECUTION" if rescue_rows else "R7.A4D2_SHORT_FAMILY_HYPOTHESIS_RETIRE_OR_REPLACE_AUDIT"
    print("STATE=" + state)
    print("BLOCKER_COUNT=" + str(len(blockers)))
    print("STRICT_DISCOVERY_LOCK_COUNT=" + str(len(strict_locks)))
    print("STRICT_VALIDATION_CELL_COUNT=" + str(len(validation_cells)))
    print("STRICT_VALIDATION_TRADE_COUNT=" + str(len(validation_trades)))
    print("VALIDATED_STRICT_SURVIVOR_COUNT=" + str(len(validated)))
    print("STRICT_VALIDATION_ROWS=" + json.dumps(validation_rows, ensure_ascii=False, sort_keys=True))
    print("NEAR_MISS_AUDITED_BUNDLE_COUNT=" + str(len(audited_rows)))
    print("RESCUE_CANDIDATE_COUNT=" + str(len(rescue_rows)))
    print("RESCUE_STRATEGY_COUNT=" + str(len({str(row['strategy_id']) for row in rescue_rows})))
    print("RESCUE_PRIORITY_ROWS=" + json.dumps(rescue_rows, ensure_ascii=False, sort_keys=True))
    print("SECOND_GENERATION_BUNDLE_TARGET=" + str(len(rescue_rows) * SECOND_GEN_VARIANTS_PER_STRATEGY))
    print("SECOND_GENERATION_CELL_TARGET=" + str(len(rescue_rows) * SECOND_GEN_VARIANTS_PER_STRATEGY * EXPECTED_STRESS_PER_BUNDLE))
    print("RETIRE_OR_REPLACE_BUNDLE_COUNT=" + str(len(retire_rows)))
    print("MUTATION_ROWS=" + json.dumps(mutation_rows, ensure_ascii=False, sort_keys=True))
    print("PLAN_JSON=" + str(output / "strict_validation_and_rescue_plan_v1.json"))
    print("NEXT_STAGE=" + next_stage)
    print("BLOCKERS=" + json.dumps(blockers))
    print("RC=" + ("0" if not blockers else "2"))
    return 0 if not blockers else 2


if __name__ == "__main__":
    raise SystemExit(main())
