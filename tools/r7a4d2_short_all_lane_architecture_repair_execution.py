#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPAIR_PLAN = Path("runtime/r7a4d2_short_all_lane_architecture_repair_plan/repair_plan_v1.json")
EXECUTION_PLAN = Path("runtime/r7a4d2_short_raw_geometry_and_simple_benchmark_execution_plan/execution_plan_v1.json")
DIAGNOSE = Path("runtime/r7a4d2_short_raw_geometry_mutation_and_lane_economic_diagnose/diagnose_v1.json")
RAW_DIR = Path("runtime/r7a4d2_short_raw_geometry_and_simple_benchmark_execution")
MANIFEST = Path("runtime/r7a4c_historical_simulation_input_lineage/selected_input_manifest_v1.json")
OUTPUT_DIR = Path("runtime/r7a4d2_short_all_lane_architecture_repair_execution")
EXPECTED_LANES = 25
EXPECTED_ARMS = 75
EXPECTED_SEGMENTS = 12
EXPECTED_STRESS_CELLS = 6
SEVERE_CELL = ("cost_profile_2", "perturbation_1")
MIN_TRADES = 8


def import_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"MODULE_SPEC_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def atomic_jsonl(path: Path, rows: list[dict[str, Any]]) -> tuple[int, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        for row in rows:
            line = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            handle.write(line)
            digest.update(line.encode("utf-8"))
        temporary = Path(handle.name)
    os.replace(temporary, path)
    return len(rows), digest.hexdigest()


def finite(value: Any) -> float | None:
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    return None


def qvalue(profile: dict[str, Any], section: str, key: str, default: float) -> float:
    values = profile.get(section) if isinstance(profile.get(section), dict) else {}
    value = finite(values.get(key))
    return value if value is not None and value > 0 else default


def benchmark_by_family_timeframe(plan: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (str(row.get("family")), str(row.get("timeframe"))): row
        for row in plan.get("benchmark_lanes", [])
        if isinstance(row, dict)
    }


def unique_geometry_signals(rows: list[dict[str, Any]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    result: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    seen: set[tuple[str, str, int, str]] = set()
    for row in rows:
        lane_id = str(row.get("lane_id") or "")
        if not lane_id.startswith("strategy:") or int(row.get("fold", 99)) >= 3:
            continue
        key = (
            lane_id,
            str(row.get("segment_id") or ""),
            int(row.get("signal_bar_index") or -1),
            str(row.get("parameter_id") or "canonical"),
        )
        if key in seen:
            continue
        seen.add(key)
        result[(key[0], key[1])].append(row)
    return result


def reconstruct_signals(raw: Any, benchmark_lane: dict[str, Any], frame: pd.DataFrame, measurement: pd.Series) -> list[dict[str, Any]]:
    rows = raw.benchmark_signals(benchmark_lane, frame)
    by_index: dict[int, dict[str, Any]] = {}
    for row in rows:
        signal_index = int(row.get("bar_index", -1))
        entry_index = signal_index + 1
        if signal_index < 0 or entry_index >= len(frame):
            continue
        if not bool(measurement.iloc[signal_index]) or not bool(measurement.iloc[entry_index]):
            continue
        by_index.setdefault(signal_index, {
            "signal_bar_index": signal_index,
            "entry_bar_index": entry_index,
            "declared_sl": None,
            "declared_tp": None,
            "parameter_id": "family_benchmark_reconstruction",
            "semantic_eligible": True,
        })
    return [by_index[index] for index in sorted(by_index)]


def quality_indices(raw: Any, benchmark_lane: dict[str, Any], frame: pd.DataFrame) -> set[int]:
    return {int(row.get("bar_index", -999)) for row in raw.benchmark_signals(benchmark_lane, frame)}


def resolve_levels(
    arm_id: str,
    signal: dict[str, Any],
    frame: pd.DataFrame,
    entry_index: int,
    profile: dict[str, Any],
) -> tuple[float, float, int] | None:
    signal_index = int(signal["signal_bar_index"])
    entry = float(frame.iloc[entry_index]["open"])
    signal_high = float(frame.iloc[signal_index]["high"])
    if entry <= 0:
        return None
    stop_q50 = qvalue(profile, "stop_distance_pct", "q50", 0.45)
    mae_q75 = qvalue(profile, "mae_pct", "q75", stop_q50)
    mfe_q50 = qvalue(profile, "mfe_pct", "q50", max(0.20, stop_q50 * 0.8))
    timeout_q75 = max(1, int(round(qvalue(profile, "time_to_mfe_bars", "q75", 8.0))))
    declared_sl = finite(signal.get("declared_sl"))
    declared_tp = finite(signal.get("declared_tp"))
    base_sl = declared_sl if declared_sl is not None and declared_sl > entry else max(signal_high, entry * (1 + stop_q50 / 100))
    base_tp = declared_tp if declared_tp is not None and 0 < declared_tp < entry else entry * (1 - max(mfe_q50, 0.12) / 100)
    if arm_id == "entry_candle_quality":
        sl, tp, timeout = base_sl, base_tp, timeout_q75
    elif arm_id == "stop_geometry_quantile":
        distance = max(0.10, stop_q50, min(mae_q75, stop_q50 * 1.5))
        sl, tp, timeout = max(signal_high, entry * (1 + distance / 100)), base_tp, timeout_q75
    elif arm_id == "exit_mfe_timeout":
        sl, tp, timeout = base_sl, entry * (1 - max(mfe_q50, 0.12) / 100), timeout_q75
    else:
        return None
    if not (math.isfinite(sl) and math.isfinite(tp) and sl > entry > tp > 0):
        return None
    return sl, tp, timeout


def simulate_trade(
    frame: pd.DataFrame,
    measurement: pd.Series,
    signal: dict[str, Any],
    arm_id: str,
    quality: set[int],
    profile: dict[str, Any],
    cost: dict[str, Any],
    perturbation: dict[str, Any],
    timeframe: str,
) -> dict[str, Any] | None:
    signal_index = int(signal["signal_bar_index"])
    if arm_id == "entry_candle_quality" and not any(abs(signal_index - value) <= 1 for value in quality):
        return None
    entry_delay = int(cost.get("latency_bars") or 0) + int(perturbation.get("additional_entry_delay_bars") or 0)
    exit_delay = int(cost.get("latency_bars") or 0) + int(perturbation.get("additional_exit_delay_bars") or 0)
    entry_index = int(signal["entry_bar_index"]) + entry_delay
    measured = [int(value) for value in measurement[measurement].index]
    if not measured:
        return None
    last_index = measured[-1]
    if entry_index > last_index or entry_index >= len(frame) or not bool(measurement.iloc[entry_index]):
        return None
    levels = resolve_levels(arm_id, signal, frame, entry_index, profile)
    if levels is None:
        return None
    sl, tp, timeout = levels
    entry = float(frame.iloc[entry_index]["open"])
    risk_pct = (sl - entry) / entry * 100
    if risk_pct <= 0:
        return None
    reason, trigger_index, reference_exit = "segment_end", last_index, float(frame.iloc[last_index]["close"])
    timeout_index = min(entry_index + timeout, last_index)
    for index in range(entry_index, last_index + 1):
        high = float(frame.iloc[index]["high"])
        low = float(frame.iloc[index]["low"])
        if high >= sl:
            reason, trigger_index, reference_exit = "stop", index, sl
            break
        if low <= tp:
            reason, trigger_index, reference_exit = "take_profit", index, tp
            break
        if arm_id == "exit_mfe_timeout" and index >= timeout_index:
            reason, trigger_index, reference_exit = "timeout", index, float(frame.iloc[index]["close"])
            break
    execution_index = min(trigger_index + exit_delay, last_index)
    if exit_delay == 0 and reason in {"stop", "take_profit"}:
        exit_price = reference_exit
    elif reason == "segment_end":
        exit_price = float(frame.iloc[execution_index]["close"])
    else:
        exit_price = float(frame.iloc[execution_index]["open"])
    gross_pct = (entry - exit_price) / entry * 100
    round_trip_pct = 2 * (float(cost.get("fee_bps_per_side") or 0) + float(cost.get("slippage_bps_per_side") or 0)) / 100
    minutes = {"1m": 1, "5m": 5, "15m": 15}.get(timeframe, 1)
    holding_hours = max(execution_index - entry_index, 0) * minutes / 60
    funding_pct = float(cost.get("funding_bps_per_8h") or 0) / 100 * holding_hours / 8
    net_pct = gross_pct - round_trip_pct - funding_pct
    return {
        "entry_index": entry_index,
        "exit_index": execution_index,
        "entry_price": entry,
        "exit_price": exit_price,
        "stop_price": sl,
        "take_profit_price": tp,
        "risk_pct": risk_pct,
        "gross_return_pct": gross_pct,
        "round_trip_cost_pct": round_trip_pct,
        "funding_cost_pct": funding_pct,
        "net_return_pct": net_pct,
        "net_r": net_pct / risk_pct,
        "exit_reason": reason,
        "holding_bars": max(execution_index - entry_index, 0),
    }


def economic_pass(helper: Any, row: dict[str, Any]) -> bool:
    return bool(
        int(row.get("trade_count") or 0) >= MIN_TRADES
        and helper.finite_metric(row.get("expectancy_r")) > 0
        and helper.finite_metric(row.get("net_pnl_sum_pct")) > 0
        and helper.finite_metric(row.get("profit_factor")) > 1
    )


def self_test() -> int:
    frame = pd.DataFrame({
        "open": np.linspace(100, 99, 40),
        "high": np.linspace(100.2, 99.2, 40),
        "low": np.linspace(99.8, 98.8, 40),
        "close": np.linspace(100, 99, 40),
        "volume": np.ones(40),
    })
    profile = {
        "stop_distance_pct": {"q50": 0.5},
        "mae_pct": {"q75": 0.6},
        "mfe_pct": {"q50": 0.4},
        "time_to_mfe_bars": {"q75": 4},
    }
    signal = {"signal_bar_index": 10, "entry_bar_index": 11, "declared_sl": None, "declared_tp": None}
    levels = resolve_levels("exit_mfe_timeout", signal, frame, 11, profile)
    assert levels is not None and levels[0] > float(frame.iloc[11]["open"]) > levels[1]
    print("STATE=PASS_SHORT_ALL_LANE_ARCHITECTURE_REPAIR_EXECUTION_SELF_TEST")
    print("RC=0")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--target-sha", default="UNKNOWN")
    parser.add_argument("--raw-module")
    parser.add_argument("--helper-module")
    parser.add_argument("--a4d-contract")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.raw_module or not args.helper_module or not args.a4d_contract:
        raise SystemExit("--raw-module --helper-module --a4d-contract required")

    root = Path(args.root).resolve()
    raw = import_module(Path(args.raw_module).resolve(), "r7a4d2_raw_geometry_all_lane")
    helper = import_module(Path(args.helper_module).resolve(), "r7a4d2_survivor_helper_all_lane")
    required = [
        root / REPAIR_PLAN,
        root / EXECUTION_PLAN,
        root / DIAGNOSE,
        root / RAW_DIR / "aggregate_v1.json",
        root / RAW_DIR / "proof_v1.json",
        root / RAW_DIR / "scan_results_v1.jsonl",
        root / RAW_DIR / "signal_geometry_v1.jsonl",
        root / MANIFEST,
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        print("STATE=HOLD_SHORT_ALL_LANE_ARCHITECTURE_REPAIR_EXECUTION_INPUT")
        print("BLOCKER_COUNT=1")
        print("BLOCKERS=" + json.dumps(["REQUIRED_EVIDENCE_MISSING:" + ",".join(missing)]))
        print("RC=2")
        return 2

    repair = helper.load_json(root / REPAIR_PLAN)
    plan = helper.load_json(root / EXECUTION_PLAN)
    diagnose = helper.load_json(root / DIAGNOSE)
    aggregate = helper.load_json(root / RAW_DIR / "aggregate_v1.json")
    proof = helper.load_json(root / RAW_DIR / "proof_v1.json")
    manifest = helper.load_json(root / MANIFEST)
    contract = helper.load_json(Path(args.a4d_contract).resolve())
    geometry_path = root / RAW_DIR / "signal_geometry_v1.jsonl"
    scans_path = root / RAW_DIR / "scan_results_v1.jsonl"
    blockers: list[str] = []
    repair_rows = [row for row in repair.get("repair_rows", []) if isinstance(row, dict)]
    strategy_lanes = {str(row["lane_id"]): row for row in plan.get("strategy_lanes", []) if isinstance(row, dict)}
    benchmark_map = benchmark_by_family_timeframe(plan)
    if repair.get("state") != "PASS_SHORT_ALL_LANE_ARCHITECTURE_REPAIR_PLAN":
        blockers.append("REPAIR_PLAN_NOT_PASS")
    if len(repair_rows) != EXPECTED_LANES or len(strategy_lanes) != EXPECTED_LANES:
        blockers.append(f"LANE_COUNT_INVALID:{len(repair_rows)}:{len(strategy_lanes)}")
    if int(repair.get("maximum_total_candidate_arms", -1)) != EXPECTED_ARMS:
        blockers.append("CANDIDATE_ARM_TARGET_INVALID")
    if diagnose.get("result_reusable") is not True:
        blockers.append("DIAGNOSE_NOT_REUSABLE")
    if helper.sha256_file(geometry_path) != str(aggregate.get("signal_geometry_sha256") or ""):
        blockers.append("GEOMETRY_SHA_MISMATCH")
    if helper.sha256_file(scans_path) != str(aggregate.get("scan_results_sha256") or ""):
        blockers.append("SCAN_SHA_MISMATCH")
    if str(proof.get("signal_geometry_sha256") or "") != str(aggregate.get("signal_geometry_sha256") or ""):
        blockers.append("PROOF_GEOMETRY_SHA_MISMATCH")
    costs = [row for row in contract.get("cost_profiles", []) if isinstance(row, dict)]
    perturbations = [row for row in contract.get("perturbations", []) if isinstance(row, dict)]
    if len(costs) * len(perturbations) != EXPECTED_STRESS_CELLS:
        blockers.append("STRESS_CELL_COUNT_INVALID")
    segments = {
        str(row["segment_id"]): row
        for row in manifest.get("selected_segments", [])
        if isinstance(row, dict) and int(row.get("fold", 99)) < 3
    }
    if len(segments) != EXPECTED_SEGMENTS:
        blockers.append(f"DISCOVERY_SEGMENT_COUNT_INVALID:{len(segments)}")
    if blockers:
        print("STATE=HOLD_SHORT_ALL_LANE_ARCHITECTURE_REPAIR_EXECUTION_INPUT")
        print("BLOCKER_COUNT=" + str(len(blockers)))
        print("BLOCKERS=" + json.dumps(blockers, ensure_ascii=False))
        print("RC=2")
        return 2

    geometry = unique_geometry_signals(helper.load_jsonl(geometry_path))
    repair_by_lane = {str(row["lane_id"]): row for row in repair_rows}
    source_sha = {
        str(row.get("source_path")): str(row.get("source_sha256") or "")
        for row in manifest.get("selected_segments", []) if isinstance(row, dict)
    }
    canonical_paths = [root / REPAIR_PLAN, root / EXECUTION_PLAN, root / DIAGNOSE, root / MANIFEST, geometry_path, scans_path]
    for lane in strategy_lanes.values():
        canonical_paths.append(root / helper.safe_repo_path(str(lane["implementation_path"])))
    for path in sorted({str(row["source_path"]) for row in segments.values()}):
        canonical_paths.append(root / helper.safe_repo_path(path))
    protected = [Path(str(value)) for value in contract.get("protected_paths", [])]
    before = helper.snapshot(canonical_paths + protected)

    source_cache: dict[str, pd.DataFrame] = {}
    frame_cache: dict[tuple[str, str], pd.DataFrame] = {}
    measurement_cache: dict[tuple[str, str], pd.Series] = {}
    signal_cache: dict[tuple[str, str], list[dict[str, Any]]] = {}
    quality_cache: dict[tuple[str, str], set[int]] = {}
    trade_rows: list[dict[str, Any]] = []
    cell_rows: list[dict[str, Any]] = []
    arm_count = 0

    for completed, lane_id in enumerate(sorted(repair_by_lane), 1):
        repair_row = repair_by_lane[lane_id]
        lane = strategy_lanes[lane_id]
        family = str(lane["family"])
        sibling_id = str(repair_row.get("sibling_native_timeframe_candidate") or "")
        execution_lane = strategy_lanes.get(sibling_id) if sibling_id else lane
        execution_lane_id = str(execution_lane["lane_id"])
        profile = repair_row.get("geometry_profile") if isinstance(repair_row.get("geometry_profile"), dict) else {}
        if sibling_id and int(profile.get("discovery_geometry_row_count") or 0) == 0:
            sibling_repair = repair_by_lane.get(sibling_id)
            if isinstance(sibling_repair, dict) and isinstance(sibling_repair.get("geometry_profile"), dict):
                profile = sibling_repair["geometry_profile"]
        benchmark_lane = benchmark_map.get((family, str(execution_lane["timeframe"])))
        if benchmark_lane is None:
            blockers.append(f"BENCHMARK_LANE_MISSING:{lane_id}")
            continue
        arms = [row for row in repair_row.get("candidate_arms", []) if isinstance(row, dict)]
        if len(arms) != 3:
            blockers.append(f"ARM_COUNT_INVALID:{lane_id}:{len(arms)}")
            continue
        arm_count += len(arms)

        for segment_id, segment in sorted(segments.items()):
            key = (execution_lane_id, segment_id)
            if key not in frame_cache:
                source_path = str(segment["source_path"])
                if source_path not in source_cache:
                    source_cache[source_path] = raw.fixed_ohlcv_frame(root / helper.safe_repo_path(source_path), source_sha[source_path])
                frame_cache[key] = raw.resample_for_segment(
                    source_cache[source_path], int(segment["start_row"]), int(segment["end_row_exclusive"]), str(execution_lane["timeframe"])
                )
                measurement_cache[key] = raw.measurement_mask(
                    frame_cache[key], int(segment["start_row"]), int(segment["end_row_exclusive"])
                )
            frame = frame_cache[key]
            measurement = measurement_cache[key]
            quality_cache[key] = quality_indices(raw, benchmark_lane, frame)
            source_signals = geometry.get((execution_lane_id, segment_id), [])
            rebuild = repair_row.get("entry_policy") in {
                "RECONSTRUCT_SHORT_SEMANTICS_FROM_FAMILY_CANDLES",
                "REBUILD_FROM_FAMILY_CANDLE_HYPOTHESIS",
            }
            signal_cache[(lane_id, segment_id)] = (
                reconstruct_signals(raw, benchmark_lane, frame, measurement)
                if rebuild or not source_signals else source_signals
            )

        for arm in arms:
            arm_id = str(arm["arm_id"])
            for cost in costs:
                for perturbation in perturbations:
                    cell_trades: list[dict[str, Any]] = []
                    for segment_id, segment in sorted(segments.items()):
                        key = (execution_lane_id, segment_id)
                        frame = frame_cache[key]
                        measurement = measurement_cache[key]
                        last_exit = -1
                        for signal in sorted(signal_cache[(lane_id, segment_id)], key=lambda row: int(row["entry_bar_index"])):
                            if int(signal["entry_bar_index"]) <= last_exit:
                                continue
                            trade = simulate_trade(
                                frame, measurement, signal, arm_id, quality_cache[key], profile,
                                cost, perturbation, str(execution_lane["timeframe"]),
                            )
                            if trade is None:
                                continue
                            last_exit = int(trade["exit_index"])
                            trade.update({
                                "lane_id": lane_id,
                                "execution_lane_id": execution_lane_id,
                                "strategy_id": lane["strategy_id"],
                                "family": family,
                                "timeframe": lane["timeframe"],
                                "execution_timeframe": execution_lane["timeframe"],
                                "arm_id": arm_id,
                                "arm_axis": arm.get("axis"),
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
                        "lane_id": lane_id,
                        "execution_lane_id": execution_lane_id,
                        "strategy_id": lane["strategy_id"],
                        "family": family,
                        "timeframe": lane["timeframe"],
                        "arm_id": arm_id,
                        "arm_axis": arm.get("axis"),
                        "cost_profile_id": cost["id"],
                        "perturbation_id": perturbation["id"],
                        **helper.aggregate_trades(cell_trades),
                    })
        print(
            f"A4D2_ALL_LANE_REPAIR_PROGRESS={completed}/{EXPECTED_LANES} "
            f"CELLS={len(cell_rows)}/{EXPECTED_ARMS * EXPECTED_STRESS_CELLS} TRADES={len(trade_rows)}"
        )

    if arm_count != EXPECTED_ARMS:
        blockers.append(f"CANDIDATE_ARM_COUNT_INVALID:{arm_count}")
    expected_cells = EXPECTED_ARMS * EXPECTED_STRESS_CELLS
    if len(cell_rows) != expected_cells:
        blockers.append(f"ARM_CELL_COUNT_INVALID:{len(cell_rows)}:{expected_cells}")
    cell_map = {
        (str(row["lane_id"]), str(row["arm_id"]), str(row["cost_profile_id"]), str(row["perturbation_id"])): row
        for row in cell_rows
    }
    lane_candidates: list[dict[str, Any]] = []
    for lane_id in sorted(repair_by_lane):
        for arm in repair_by_lane[lane_id]["candidate_arms"]:
            arm_id = str(arm["arm_id"])
            severe = cell_map[(lane_id, arm_id, *SEVERE_CELL)]
            cells = [row for row in cell_rows if row["lane_id"] == lane_id and row["arm_id"] == arm_id]
            positive_cells = sum(1 for row in cells if economic_pass(helper, row))
            lane_candidates.append({
                "lane_id": lane_id,
                "strategy_id": repair_by_lane[lane_id]["strategy_id"],
                "family": repair_by_lane[lane_id]["family"],
                "timeframe": repair_by_lane[lane_id]["timeframe"],
                "arm_id": arm_id,
                "arm_axis": arm.get("axis"),
                "severe_metrics": severe,
                "positive_stress_cell_count": positive_cells,
                "eligible_for_strategy_lock": economic_pass(helper, severe) and positive_cells >= 4,
            })

    by_strategy: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in lane_candidates:
        by_strategy[str(row["strategy_id"])].append(row)
    lock_rows: list[dict[str, Any]] = []
    for strategy_id, rows in sorted(by_strategy.items()):
        eligible = [row for row in rows if row["eligible_for_strategy_lock"]]
        eligible.sort(key=lambda row: (
            helper.finite_metric(row["severe_metrics"].get("expectancy_r")),
            helper.finite_metric(row["severe_metrics"].get("profit_factor")),
            helper.finite_metric(row["severe_metrics"].get("net_pnl_sum_pct")),
            -helper.finite_metric(row["severe_metrics"].get("max_drawdown_pct"), 1e100),
            int(row["positive_stress_cell_count"]),
        ), reverse=True)
        selected = eligible[0] if eligible else None
        lock_rows.append({
            "strategy_id": strategy_id,
            "eligible_candidate_count": len(eligible),
            "selected_lane_id": selected.get("lane_id") if selected else None,
            "selected_arm_id": selected.get("arm_id") if selected else None,
            "selected_arm_axis": selected.get("arm_axis") if selected else None,
            "selected_metrics": selected.get("severe_metrics") if selected else None,
            "positive_stress_cell_count": selected.get("positive_stress_cell_count") if selected else 0,
            "lock_status": "REPAIR_ARM_LOCKED" if selected else "NO_ECONOMIC_REPAIR_SURVIVOR",
            "validation_allowed": selected is not None,
        })

    after = helper.snapshot(canonical_paths + protected)
    mutation_paths = sorted(path for path in before if before[path] != after[path])
    mutation_rows = [{"path": path, "classification": helper.classify_mutation(path, root)} for path in mutation_paths]
    critical = [row for row in mutation_rows if row["classification"] != "EXTERNAL_OPERATIONAL_VOLATILE_MUTATION"]
    if critical:
        blockers.append(f"CRITICAL_MUTATIONS:{len(critical)}")

    output = root / OUTPUT_DIR
    trade_count, trade_sha = atomic_jsonl(output / "repair_trade_results_v1.jsonl", trade_rows)
    cell_count, cell_sha = atomic_jsonl(output / "repair_arm_cell_results_v1.jsonl", cell_rows)
    locked = [row for row in lock_rows if row["validation_allowed"]]
    state = "PASS_SHORT_ALL_LANE_ARCHITECTURE_REPAIR_EXECUTION" if not blockers else "HOLD_SHORT_ALL_LANE_ARCHITECTURE_REPAIR_EXECUTION"
    next_stage = "R7.A4D2_SHORT_LOCKED_REPAIR_DISJOINT_VALIDATION" if not blockers and locked else "R7.A4D2_SHORT_SECOND_ORDER_REPAIR_CAUSAL_AUDIT"
    report = {
        "schema": "r7a4d2_short_all_lane_architecture_repair_execution_v1",
        "official_stage": "R7.A4D2_SHORT_ALL_LANE_ARCHITECTURE_REPAIR_EXECUTION",
        "state": state,
        "target_commit": args.target_sha,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "strategy_lane_count": len(repair_rows),
        "candidate_arm_count": arm_count,
        "discovery_segment_count": len(segments),
        "stress_cell_count": EXPECTED_STRESS_CELLS,
        "repair_trade_result_count": trade_count,
        "repair_arm_cell_result_count": cell_count,
        "repair_trade_results_sha256": trade_sha,
        "repair_arm_cell_results_sha256": cell_sha,
        "minimum_discovery_trade_count": MIN_TRADES,
        "selection_policy": "SEVERE_POSITIVE_ECONOMICS_AND_AT_LEAST_FOUR_OF_SIX_POSITIVE_STRESS_CELLS_ONE_LOCK_PER_STRATEGY",
        "lane_candidates": lane_candidates,
        "strategy_lock_rows": lock_rows,
        "economic_repair_survivor_count": len(locked),
        "mutation_rows": mutation_rows,
        "next_stage": next_stage,
    }
    atomic_json(output / "repair_lock_v1.json", report)
    print("STATE=" + state)
    print("BLOCKER_COUNT=" + str(len(blockers)))
    print("STRATEGY_LANE_COUNT=" + str(len(repair_rows)))
    print("CANDIDATE_ARM_COUNT=" + str(arm_count))
    print("DISCOVERY_SEGMENT_COUNT=" + str(len(segments)))
    print("STRESS_CELL_COUNT=" + str(EXPECTED_STRESS_CELLS))
    print("REPAIR_TRADE_RESULT_COUNT=" + str(trade_count))
    print("REPAIR_ARM_CELL_RESULT_COUNT=" + str(cell_count))
    print("ECONOMIC_REPAIR_SURVIVOR_COUNT=" + str(len(locked)))
    print("STRATEGY_LOCK_ROWS=" + json.dumps(lock_rows, ensure_ascii=False, sort_keys=True))
    print("MUTATION_ROWS=" + json.dumps(mutation_rows, ensure_ascii=False, sort_keys=True))
    print("REPAIR_LOCK_JSON=" + str(output / "repair_lock_v1.json"))
    print("NEXT_STAGE=" + next_stage)
    print("BLOCKERS=" + json.dumps(blockers, ensure_ascii=False))
    print("RC=" + ("0" if not blockers else "2"))
    return 0 if not blockers else 2


if __name__ == "__main__":
    raise SystemExit(main())
