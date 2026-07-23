#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

AUDIT_PATH = Path("runtime/r7a4d2_incremental_defect_ablation_audit/incremental_defect_ablation_audit_v1.json")
CALIBRATION_PATH = Path("runtime/r7a4d2_short_economic_calibration_and_exchange_bot_benchmark_v2_plan/economic_calibration_and_exchange_bot_benchmark_v2_plan_v1.json")
MANIFEST_PATH = Path("runtime/r7a4c_historical_simulation_input_lineage/selected_input_manifest_v1.json")
OUTPUT_DIR = Path("runtime/r7a4d2_incremental_single_defect_repair_execution_36")

EXPECTED_SELECTED_LANES = 6
EXPECTED_STRESS_PER_LANE = 6
EXPECTED_CELLS = 36
EXPECTED_SEGMENTS = 24
EXPECTED_FOLDS = 6
MINIMUM_TRADES = 24
MINIMUM_SYMBOLS = 3
MINIMUM_POSITIVE_FOLDS = 4
MINIMUM_POSITIVE_PRIMARY_CELLS = 3
ATR5_CONTROL = "dual_atr_volatility_bot:5m"
REFERENCE_LANE = "dual_donchian_trend_bot:15m"

BASE_CELL = ("cost_profile_0", "timing_0")
ADVERSE_CELL = ("cost_profile_1", "timing_1")
SEVERE_CELL = ("cost_profile_2", "timing_1")

ROLLBACK_CAUSES = {
    "REMOVED_POSITIVE_SIGNAL_COVERAGE",
    "TIMEFRAME_ROUTE_REWRITE",
}
COST_CAUSE = "COST_FRAGILITY"


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


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def atomic_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> tuple[int, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    count = 0
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as handle:
        for row in rows:
            line = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            handle.write(line)
            digest.update(line.encode("utf-8"))
            count += 1
        temporary = Path(handle.name)
    os.replace(temporary, path)
    return count, digest.hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot(paths: Iterable[Path]) -> dict[str, str]:
    return {str(path): sha256_file(path) for path in paths}


def finite(value: Any, default: float = 0.0) -> float:
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    return default


def positive_folds(metrics: dict[str, Any]) -> int:
    return int((metrics.get("fold_metrics") or {}).get("positive_fold_count") or 0)


def fold_metrics(helper: Any, trades: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in trades:
        grouped[int(row["fold"])].append(row)
    rows: dict[str, dict[str, Any]] = {}
    positive = 0
    for fold in range(EXPECTED_FOLDS):
        metrics = helper.aggregate_trades(grouped.get(fold, []))
        rows[str(fold)] = metrics
        if helper.finite_metric(metrics.get("net_pnl_sum_pct")) > 0:
            positive += 1
    return {
        "rows": rows,
        "fold_count": EXPECTED_FOLDS,
        "positive_fold_count": positive,
        "positive_fold_ratio": positive / EXPECTED_FOLDS,
    }


def cell_gate(helper: Any, cell: dict[str, Any]) -> dict[str, bool]:
    return {
        "trade_gate": int(cell.get("trade_count") or 0) >= MINIMUM_TRADES,
        "symbol_gate": len(cell.get("symbol_histogram") or {}) >= MINIMUM_SYMBOLS,
        "profit_factor_gate": helper.finite_metric(cell.get("profit_factor")) > 1.0,
        "expectancy_gate": helper.finite_metric(cell.get("expectancy_r")) > 0.0,
        "net_pnl_gate": helper.finite_metric(cell.get("net_pnl_sum_pct")) > 0.0,
        "walk_forward_gate": positive_folds(cell) >= MINIMUM_POSITIVE_FOLDS,
    }


def risk_score(metrics: dict[str, Any]) -> float:
    expectancy = finite(metrics.get("expectancy_r"))
    pnl = finite(metrics.get("net_pnl_sum_pct"))
    drawdown = max(finite(metrics.get("max_drawdown_pct")), 0.25)
    profit_factor = max(finite(metrics.get("profit_factor")), 0.0)
    folds = positive_folds(metrics)
    return expectancy + 0.20 * (pnl / drawdown) + 0.10 * (profit_factor - 1.0) + 0.03 * folds


def metric_close(actual: dict[str, Any], expected: dict[str, Any], tolerance: float = 1e-7) -> bool:
    keys = ("trade_count", "net_pnl_sum_pct", "expectancy_r", "profit_factor", "max_drawdown_pct")
    for key in keys:
        if key == "trade_count":
            if int(actual.get(key) or 0) != int(expected.get(key) or 0):
                return False
        elif abs(finite(actual.get(key)) - finite(expected.get(key))) > tolerance:
            return False
    return positive_folds(actual) == positive_folds(expected)


def meaningful_severe(metrics: dict[str, Any]) -> bool:
    return (
        bool(metrics.get("economic_pass"))
        and finite(metrics.get("net_pnl_sum_pct")) >= 0.50
        and finite(metrics.get("profit_factor")) >= 1.20
        and positive_folds(metrics) >= MINIMUM_POSITIVE_FOLDS
    )


def repair_signals(
    signals: list[dict[str, Any]],
    cause: str,
) -> tuple[list[dict[str, Any]], Counter[str]]:
    if cause in ROLLBACK_CAUSES:
        return [dict(row) for row in signals], Counter({"CONTROL_SIGNAL_SET_RESTORED": len(signals)})

    if cause == COST_CAUSE:
        kept: list[dict[str, Any]] = []
        rejected: Counter[str] = Counter()
        for row in signals:
            target_ratio = finite(row.get("target_to_base_cost_ratio"))
            risk_ratio = finite(row.get("risk_to_base_cost_ratio"))
            if target_ratio < 4.0:
                rejected["TARGET_COST_FLOOR_REJECT"] += 1
                continue
            if risk_ratio < 2.0:
                rejected["RISK_COST_FLOOR_REJECT"] += 1
                continue
            kept.append(dict(row))
        return kept, rejected

    raise ValueError(f"UNSUPPORTED_SELECTED_CAUSE:{cause}")


def self_test() -> int:
    signals = [
        {"target_to_base_cost_ratio": 4.5, "risk_to_base_cost_ratio": 2.2},
        {"target_to_base_cost_ratio": 3.5, "risk_to_base_cost_ratio": 2.2},
        {"target_to_base_cost_ratio": 4.5, "risk_to_base_cost_ratio": 1.8},
    ]
    rollback, rollback_rejected = repair_signals(signals, "REMOVED_POSITIVE_SIGNAL_COVERAGE")
    assert len(rollback) == 3
    assert rollback_rejected["CONTROL_SIGNAL_SET_RESTORED"] == 3
    cost, cost_rejected = repair_signals(signals, COST_CAUSE)
    assert len(cost) == 1
    assert cost_rejected["TARGET_COST_FLOOR_REJECT"] == 1
    assert cost_rejected["RISK_COST_FLOOR_REJECT"] == 1

    baseline = {
        "trade_count": 24,
        "net_pnl_sum_pct": 2.0,
        "expectancy_r": 0.2,
        "profit_factor": 1.5,
        "max_drawdown_pct": 1.0,
        "fold_metrics": {"positive_fold_count": 4},
    }
    assert metric_close(dict(baseline), dict(baseline))
    assert meaningful_severe({**baseline, "net_pnl_sum_pct": 0.6, "profit_factor": 1.3, "economic_pass": True})
    print("STATE=PASS_INCREMENTAL_SINGLE_DEFECT_REPAIR_EXECUTION_36_SELF_TEST")
    print("RC=0")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--target-sha", default="UNKNOWN")
    parser.add_argument("--raw-module")
    parser.add_argument("--helper-module")
    parser.add_argument("--benchmark-module")
    parser.add_argument("--indicator-module")
    parser.add_argument("--second-wave-module")
    parser.add_argument("--a4d-contract")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return self_test()

    required_args = [
        args.raw_module,
        args.helper_module,
        args.benchmark_module,
        args.indicator_module,
        args.second_wave_module,
        args.a4d_contract,
    ]
    if not all(required_args):
        raise SystemExit("ALL_MODULE_ARGUMENTS_REQUIRED")

    root = Path(args.root).resolve()
    raw = import_module(Path(args.raw_module).resolve(), "r7a4d2_incremental_raw")
    helper = import_module(Path(args.helper_module).resolve(), "r7a4d2_incremental_helper")
    benchmark = import_module(Path(args.benchmark_module).resolve(), "r7a4d2_incremental_benchmark")
    indicator = import_module(Path(args.indicator_module).resolve(), "r7a4d2_incremental_indicator")
    second = import_module(Path(args.second_wave_module).resolve(), "r7a4d2_incremental_second")
    contract = load_json(Path(args.a4d_contract).resolve())

    required = [root / AUDIT_PATH, root / CALIBRATION_PATH, root / MANIFEST_PATH]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        print("STATE=HOLD_INCREMENTAL_SINGLE_DEFECT_REPAIR_EXECUTION_36_INPUT")
        print("BLOCKER_COUNT=1")
        print("BLOCKERS=" + json.dumps(["REQUIRED_EVIDENCE_MISSING:" + ",".join(missing)]))
        print("RC=2")
        return 2

    audit = load_json(root / AUDIT_PATH)
    calibration = load_json(root / CALIBRATION_PATH)
    manifest = load_json(root / MANIFEST_PATH)
    selected = [
        row for row in audit.get("selected_incremental_repair_rows", [])
        if isinstance(row, dict)
    ]
    blockers: list[str] = []
    if audit.get("state") != "PASS_INCREMENTAL_DEFECT_ABLATION_AUDIT":
        blockers.append("AUDIT_NOT_PASS")
    if len(selected) != EXPECTED_SELECTED_LANES:
        blockers.append(f"SELECTED_LANE_COUNT_INVALID:{len(selected)}")
    expected_ids = set(audit.get("selected_repair_lane_ids") or [])
    actual_ids = {str(row.get("lane_id") or "") for row in selected}
    if expected_ids != actual_ids:
        blockers.append("SELECTED_LANE_ID_MISMATCH")
    if int(audit.get("expected_incremental_repair_cell_count") or 0) != EXPECTED_CELLS:
        blockers.append("EXPECTED_CELL_COUNT_INVALID")
    if any(str(row.get("primary_defect") or "") not in ROLLBACK_CAUSES | {COST_CAUSE} for row in selected):
        blockers.append("UNSUPPORTED_SELECTED_DEFECT")
    if not bool(audit.get("atr5_control_preserved")):
        blockers.append("ATR5_CONTROL_NOT_PRESERVED")
    if not bool(audit.get("donchian15_reference_preserved")):
        blockers.append("REFERENCE_NOT_PRESERVED")
    if not bool(audit.get("keep14_untouched")):
        blockers.append("KEEP14_NOT_PRESERVED")

    segments = {
        str(row["segment_id"]): row
        for row in manifest.get("selected_segments", [])
        if isinstance(row, dict)
    }
    if len(segments) != EXPECTED_SEGMENTS:
        blockers.append(f"SEGMENT_COUNT_INVALID:{len(segments)}")

    model = calibration.get("corrected_execution_model", {})
    costs = [row for row in model.get("profiles", []) if isinstance(row, dict)]
    timings = [row for row in model.get("timing_perturbations", []) if isinstance(row, dict)]
    if len(costs) * len(timings) != EXPECTED_STRESS_PER_LANE:
        blockers.append("STRESS_GRID_INVALID")
    base_cost_pct = benchmark.base_round_trip_cost(calibration)
    if not math.isfinite(base_cost_pct) or base_cost_pct <= 0:
        blockers.append("BASE_COST_INVALID")

    if blockers:
        print("STATE=HOLD_INCREMENTAL_SINGLE_DEFECT_REPAIR_EXECUTION_36_INPUT")
        print("BLOCKER_COUNT=" + str(len(blockers)))
        print("BLOCKERS=" + json.dumps(blockers))
        print("RC=2")
        return 2

    source_sha = {
        str(row.get("source_path")): str(row.get("source_sha256") or "")
        for row in manifest.get("selected_segments", [])
        if isinstance(row, dict)
    }
    source_paths = sorted({str(row["source_path"]) for row in segments.values()})
    selected_paths = [root / raw.safe_repo_path(path) for path in source_paths]
    protected = [Path(str(value)) for value in contract.get("protected_paths", [])]
    before = snapshot(required + selected_paths + protected)

    lane_delta_map = {
        str(row.get("lane_id") or ""): row
        for row in audit.get("lane_delta_rows", [])
        if isinstance(row, dict)
    }
    source_cache: dict[str, pd.DataFrame] = {}
    frame_cache: dict[tuple[str, str], pd.DataFrame] = {}
    mask_cache: dict[tuple[str, str], pd.Series] = {}
    trade_rows: list[dict[str, Any]] = []
    cell_rows: list[dict[str, Any]] = []
    lane_rows: list[dict[str, Any]] = []

    for lane_number, selected_row in enumerate(
        sorted(selected, key=lambda row: str(row["lane_id"])), 1
    ):
        lane_id = str(selected_row["lane_id"])
        control_variant = str(selected_row["control_variant_id"])
        execution_timeframe = str(selected_row["control_execution_timeframe"])
        primary_defect = str(selected_row["primary_defect"])
        audit_row = lane_delta_map[lane_id]
        signal_cache: dict[str, list[dict[str, Any]]] = {}
        rejection_total: Counter[str] = Counter()
        control_signal_count = 0

        for segment_id, segment in sorted(segments.items()):
            source_path = str(segment["source_path"])
            if source_path not in source_cache:
                source_cache[source_path] = raw.fixed_ohlcv_frame(
                    root / raw.safe_repo_path(source_path), source_sha[source_path]
                )
            for timeframe in {execution_timeframe, "15m"}:
                key = (segment_id, timeframe)
                if key not in frame_cache:
                    frame_cache[key] = raw.resample_for_segment(
                        source_cache[source_path],
                        int(segment["start_row"]),
                        int(segment["end_row_exclusive"]),
                        timeframe,
                    )
                    mask_cache[key] = raw.measurement_mask(
                        frame_cache[key],
                        int(segment["start_row"]),
                        int(segment["end_row_exclusive"]),
                    )

            control_signals, generator_rejected = second.generate_variant_signals(
                control_variant,
                frame_cache[(segment_id, execution_timeframe)],
                mask_cache[(segment_id, execution_timeframe)],
                frame_cache[(segment_id, "15m")],
                str(segment["regime"]),
                base_cost_pct,
                indicator,
            )
            repaired_signals, repair_rejected = repair_signals(control_signals, primary_defect)
            signal_cache[segment_id] = repaired_signals
            control_signal_count += len(control_signals)
            rejection_total.update(generator_rejected)
            rejection_total.update(repair_rejected)

        cell_map: dict[tuple[str, str], dict[str, Any]] = {}
        for cost in costs:
            for timing in timings:
                cell_trades: list[dict[str, Any]] = []
                for segment_id, segment in sorted(segments.items()):
                    frame = frame_cache[(segment_id, execution_timeframe)]
                    measurement = mask_cache[(segment_id, execution_timeframe)]
                    last_exit = -1
                    last_exit_by_level: dict[str, int] = {}
                    for signal in signal_cache[segment_id]:
                        is_grid = "grid" in str(audit_row.get("family") or "")
                        if is_grid:
                            key = f"{signal.get('side')}:{signal.get('level_id') or 'NA'}"
                            if int(signal["entry_bar_index"]) <= last_exit_by_level.get(key, -1):
                                continue
                        elif int(signal["entry_bar_index"]) <= last_exit:
                            continue

                        trade = benchmark.simulate_trade(
                            frame,
                            measurement,
                            signal,
                            cost,
                            timing,
                            execution_timeframe,
                        )
                        if trade is None:
                            continue
                        if is_grid:
                            last_exit_by_level[key] = int(trade["exit_index"])
                        else:
                            last_exit = int(trade["exit_index"])
                        trade.update(
                            {
                                "lane_id": lane_id,
                                "control_variant_id": control_variant,
                                "primary_defect": primary_defect,
                                "single_repair_axis": selected_row["single_repair_axis"],
                                "execution_timeframe": execution_timeframe,
                                "cost_profile_id": str(cost["id"]),
                                "timing_id": str(timing["id"]),
                                "segment_id": segment_id,
                                "fold": int(segment["fold"]),
                                "regime": str(segment["regime"]),
                                "symbol": str(
                                    frame.iloc[int(signal["signal_bar_index"])].get("symbol") or ""
                                ),
                                "signal_reason": signal["reason"],
                                "level_id": signal.get("level_id"),
                            }
                        )
                        cell_trades.append(trade)
                        trade_rows.append(trade)

                metrics = helper.aggregate_trades(cell_trades)
                metrics.update(
                    {
                        "lane_id": lane_id,
                        "control_variant_id": control_variant,
                        "primary_defect": primary_defect,
                        "single_repair_axis": selected_row["single_repair_axis"],
                        "execution_timeframe": execution_timeframe,
                        "cost_profile_id": str(cost["id"]),
                        "timing_id": str(timing["id"]),
                        "fold_metrics": fold_metrics(helper, cell_trades),
                    }
                )
                metrics["gate_status"] = cell_gate(helper, metrics)
                metrics["economic_pass"] = all(metrics["gate_status"].values())
                cell_rows.append(metrics)
                cell_map[(str(cost["id"]), str(timing["id"]))] = metrics

        base = cell_map.get(BASE_CELL, {})
        adverse = cell_map.get(ADVERSE_CELL, {})
        severe = cell_map.get(SEVERE_CELL, {})
        primary_cells = [
            metrics
            for (cost_id, _), metrics in cell_map.items()
            if cost_id in {"cost_profile_0", "cost_profile_1"}
        ]
        positive_primary = sum(bool(metrics.get("economic_pass")) for metrics in primary_cells)
        base_adverse_pass = bool(base.get("economic_pass")) and bool(adverse.get("economic_pass"))
        baseline_base = dict(audit_row.get("baseline_base_metrics") or {})
        baseline_adverse = dict(audit_row.get("baseline_adverse_metrics") or {})
        rejected_base = dict(audit_row.get("candidate_base_metrics") or {})
        rejected_adverse = dict(audit_row.get("candidate_adverse_metrics") or {})

        baseline_score = (risk_score(baseline_base) + risk_score(baseline_adverse)) / 2.0
        candidate_score = (risk_score(base) + risk_score(adverse)) / 2.0
        rejected_score = (risk_score(rejected_base) + risk_score(rejected_adverse)) / 2.0
        baseline_exact_restored = (
            metric_close(base, baseline_base)
            and metric_close(adverse, baseline_adverse)
        )
        rejected_variant_beaten = candidate_score > rejected_score + 1e-9
        rollback_recovery = (
            primary_defect in ROLLBACK_CAUSES
            and baseline_exact_restored
            and rejected_variant_beaten
        )
        cost_defense_uplift = (
            primary_defect == COST_CAUSE
            and base_adverse_pass
            and positive_primary >= MINIMUM_POSITIVE_PRIMARY_CELLS
            and candidate_score > baseline_score + 1e-9
            and finite(adverse.get("net_pnl_sum_pct")) > finite(baseline_adverse.get("net_pnl_sum_pct"))
            and finite(base.get("net_pnl_sum_pct")) >= finite(baseline_base.get("net_pnl_sum_pct")) - 0.25
        )
        repair_pass = rollback_recovery or cost_defense_uplift

        lane_rows.append(
            {
                "lane_id": lane_id,
                "family": str(audit_row.get("family") or ""),
                "control_variant_id": control_variant,
                "rejected_variant_id": str(selected_row.get("rejected_variant_id") or ""),
                "primary_defect": primary_defect,
                "single_repair_axis": selected_row["single_repair_axis"],
                "execution_timeframe": execution_timeframe,
                "control_signal_count": control_signal_count,
                "repaired_signal_count": sum(len(rows) for rows in signal_cache.values()),
                "rejection_histogram": dict(sorted(rejection_total.items())),
                "positive_primary_cell_count": positive_primary,
                "base_and_adverse_economic_pass": base_adverse_pass,
                "baseline_risk_score": baseline_score,
                "rejected_variant_risk_score": rejected_score,
                "candidate_risk_score": candidate_score,
                "baseline_exact_restored": baseline_exact_restored,
                "rejected_variant_beaten": rejected_variant_beaten,
                "rollback_recovery_pass": rollback_recovery,
                "cost_defense_uplift_pass": cost_defense_uplift,
                "single_defect_repair_pass": repair_pass,
                "meaningful_severe_margin_pass": meaningful_severe(severe),
                "base_metrics": base,
                "adverse_metrics": adverse,
                "severe_metrics": severe,
            }
        )
        print(
            f"A4D2_INCREMENTAL_SINGLE_DEFECT_PROGRESS={lane_number}/{EXPECTED_SELECTED_LANES} "
            f"CELLS={lane_number * EXPECTED_STRESS_PER_LANE}/{EXPECTED_CELLS} "
            f"TRADES={len(trade_rows)}"
        )

    output = root / OUTPUT_DIR
    trade_count, trade_sha = atomic_jsonl(output / "incremental_repair_trade_rows_v1.jsonl", trade_rows)
    cell_count, cell_sha = atomic_jsonl(output / "incremental_repair_cell_rows_v1.jsonl", cell_rows)

    restored = sorted(row["lane_id"] for row in lane_rows if row["rollback_recovery_pass"])
    uplifted = sorted(row["lane_id"] for row in lane_rows if row["cost_defense_uplift_pass"])
    passed = sorted(row["lane_id"] for row in lane_rows if row["single_defect_repair_pass"])
    severe = sorted(row["lane_id"] for row in lane_rows if row["meaningful_severe_margin_pass"])
    failed = sorted(set(actual_ids) - set(passed))
    next_stage = (
        "R7.A4D2_INCREMENTAL_DEFECT_2_AUDIT"
        if passed
        else "R7.A4D2_SELECTED_LANE_DATA_EXPANSION_OR_RETIRE_DECISION"
    )
    summary = {
        "state": "PASS_INCREMENTAL_SINGLE_DEFECT_REPAIR_EXECUTION_36",
        "target_sha": args.target_sha,
        "selected_lane_count": len(lane_rows),
        "cell_result_count": cell_count,
        "trade_result_count": trade_count,
        "trade_sha256": trade_sha,
        "cell_sha256": cell_sha,
        "rollback_restored_lane_count": len(restored),
        "rollback_restored_lane_ids": restored,
        "incremental_uplift_lane_count": len(uplifted),
        "incremental_uplift_lane_ids": uplifted,
        "single_defect_repair_pass_lane_count": len(passed),
        "single_defect_repair_pass_lane_ids": passed,
        "meaningful_severe_margin_lane_count": len(severe),
        "meaningful_severe_margin_lane_ids": severe,
        "failed_selected_lane_count": len(failed),
        "failed_selected_lane_ids": failed,
        "atr5_control_preserved": True,
        "donchian15_reference_preserved": True,
        "keep14_untouched": True,
        "lane_result_rows": lane_rows,
        "mutation_rows": [],
        "next_stage": next_stage,
    }
    atomic_json(output / "incremental_single_defect_repair_summary_v1.json", summary)

    after = snapshot(required + selected_paths + protected)
    mutations = [
        path for path in before
        if before[path] != after.get(path)
    ]
    final_blockers: list[str] = []
    if cell_count != EXPECTED_CELLS:
        final_blockers.append(f"CELL_COUNT_INVALID:{cell_count}")
    if mutations:
        final_blockers.append(f"PROTECTED_MUTATIONS:{len(mutations)}")
    if final_blockers:
        print("STATE=HOLD_INCREMENTAL_SINGLE_DEFECT_REPAIR_EXECUTION_36")
        print("BLOCKER_COUNT=" + str(len(final_blockers)))
        print("BLOCKERS=" + json.dumps(final_blockers))
        print("RC=2")
        return 2

    print("STATE=PASS_INCREMENTAL_SINGLE_DEFECT_REPAIR_EXECUTION_36")
    print("BLOCKER_COUNT=0")
    print("SELECTED_LANE_COUNT=" + str(len(lane_rows)))
    print("CELL_RESULT_COUNT=" + str(cell_count))
    print("TRADE_RESULT_COUNT=" + str(trade_count))
    print("ROLLBACK_RESTORED_LANE_COUNT=" + str(len(restored)))
    print("ROLLBACK_RESTORED_LANE_IDS=" + json.dumps(restored))
    print("INCREMENTAL_UPLIFT_LANE_COUNT=" + str(len(uplifted)))
    print("INCREMENTAL_UPLIFT_LANE_IDS=" + json.dumps(uplifted))
    print("SINGLE_DEFECT_REPAIR_PASS_LANE_COUNT=" + str(len(passed)))
    print("SINGLE_DEFECT_REPAIR_PASS_LANE_IDS=" + json.dumps(passed))
    print("MEANINGFUL_SEVERE_MARGIN_LANE_COUNT=" + str(len(severe)))
    print("MEANINGFUL_SEVERE_MARGIN_LANE_IDS=" + json.dumps(severe))
    print("FAILED_SELECTED_LANE_COUNT=" + str(len(failed)))
    print("FAILED_SELECTED_LANE_IDS=" + json.dumps(failed))
    print("ATR5_CONTROL_PRESERVED=true")
    print("DONCHIAN15_REFERENCE_PRESERVED=true")
    print("KEEP14_UNTOUCHED=true")
    print("LANE_RESULT_ROWS=" + json.dumps(lane_rows, sort_keys=True))
    print("SUMMARY_JSON=" + str(output / "incremental_single_defect_repair_summary_v1.json"))
    print("NEXT_STAGE=" + next_stage)
    print("BLOCKERS=[]")
    print("RC=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
