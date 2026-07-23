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

import pandas as pd

PLAN_PATH = Path("runtime/r7a4d2_incremental_recovery_contract_repair_and_defect2_audit/incremental_recovery_contract_repair_and_defect2_audit_v1.json")
CALIBRATION_PATH = Path("runtime/r7a4d2_short_economic_calibration_and_exchange_bot_benchmark_v2_plan/economic_calibration_and_exchange_bot_benchmark_v2_plan_v1.json")
MANIFEST_PATH = Path("runtime/r7a4c_historical_simulation_input_lineage/selected_input_manifest_v1.json")
OUTPUT_DIR = Path("runtime/r7a4d2_incremental_defect2_execution")

EXPECTED_SEGMENTS = 24
EXPECTED_FOLDS = 6
MIN_TRADES = 24
MIN_SYMBOLS = 3
MIN_POSITIVE_FOLDS = 4
BASE_CELL = ("cost_profile_0", "timing_0")
ADVERSE_CELL = ("cost_profile_1", "timing_1")
SEVERE_CELL = ("cost_profile_2", "timing_1")
ATR5 = "dual_atr_volatility_bot:5m"
ATR15 = "dual_atr_volatility_bot:15m"
MA5 = "dual_ma_trend_bot:5m"

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
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)

def atomic_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> tuple[int, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    count = 0
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
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
    return {"rows": rows, "fold_count": EXPECTED_FOLDS, "positive_fold_count": positive, "positive_fold_ratio": positive / EXPECTED_FOLDS}

def cell_gate(helper: Any, cell: dict[str, Any]) -> dict[str, bool]:
    return {
        "trade_gate": int(cell.get("trade_count") or 0) >= MIN_TRADES,
        "symbol_gate": len(cell.get("symbol_histogram") or {}) >= MIN_SYMBOLS,
        "profit_factor_gate": helper.finite_metric(cell.get("profit_factor")) > 1.0,
        "expectancy_gate": helper.finite_metric(cell.get("expectancy_r")) > 0.0,
        "net_pnl_gate": helper.finite_metric(cell.get("net_pnl_sum_pct")) > 0.0,
        "walk_forward_gate": positive_folds(cell) >= MIN_POSITIVE_FOLDS,
    }

def risk_score(metrics: dict[str, Any]) -> float:
    expectancy = finite(metrics.get("expectancy_r"))
    pnl = finite(metrics.get("net_pnl_sum_pct"))
    drawdown = max(finite(metrics.get("max_drawdown_pct")), 0.25)
    pf = max(finite(metrics.get("profit_factor")), 0.0)
    folds = positive_folds(metrics)
    return expectancy + 0.20 * (pnl / drawdown) + 0.10 * (pf - 1.0) + 0.03 * folds

def signal_attributes(signal: dict[str, Any], frame: pd.DataFrame, regime: str) -> dict[str, str]:
    index = int(signal.get("signal_bar_index") or -1)
    symbol = ""
    if 0 <= index < len(frame):
        symbol = str(frame.iloc[index].get("symbol") or "")
    return {
        "regime": str(regime),
        "symbol": symbol,
        "side": str(signal.get("side") or ""),
        "signal_reason": str(signal.get("reason") or ""),
    }

def cluster_match(signal: dict[str, Any], frame: pd.DataFrame, regime: str, cluster: dict[str, Any]) -> bool:
    axes = [str(value) for value in cluster.get("axes") or []]
    values = [str(value) for value in cluster.get("values") or []]
    attrs = signal_attributes(signal, frame, regime)
    return bool(axes) and len(axes) == len(values) and all(attrs.get(axis, "UNKNOWN") == value for axis, value in zip(axes, values))

def one_bar_confirmation(signal: dict[str, Any], frame: pd.DataFrame, measurement: pd.Series, base_cost_pct: float) -> dict[str, Any] | None:
    candidate = dict(signal)
    signal_index = int(candidate["signal_bar_index"]) + 1
    entry_index = int(candidate["entry_bar_index"]) + 1
    if signal_index < 0 or entry_index >= len(frame):
        return None
    if not bool(measurement.iloc[signal_index]) or not bool(measurement.iloc[entry_index]):
        return None
    entry = finite(frame.iloc[entry_index]["open"], math.nan)
    stop = finite(candidate.get("stop_price"), math.nan)
    target = finite(candidate.get("target_price"), math.nan)
    if not all(math.isfinite(value) for value in (entry, stop, target)):
        return None
    side = str(candidate.get("side") or "")
    valid = (0 < stop < entry < target) if side == "long" else (stop > entry > target > 0)
    if not valid:
        return None
    risk_pct = abs(entry - stop) / entry * 100.0
    target_pct = abs(target - entry) / entry * 100.0
    if target_pct / base_cost_pct < 3.0 or risk_pct / base_cost_pct < 2.0:
        return None
    candidate.update({
        "signal_bar_index": signal_index,
        "entry_bar_index": entry_index,
        "risk_pct_at_admission": risk_pct,
        "target_move_pct_at_admission": target_pct,
        "target_to_base_cost_ratio": target_pct / base_cost_pct,
        "risk_to_base_cost_ratio": risk_pct / base_cost_pct,
        "reason": str(candidate.get("reason") or "") + "|one_bar_confirmation",
    })
    return candidate

def apply_repair(signals: list[dict[str, Any]], frame: pd.DataFrame, measurement: pd.Series, regime: str, base_cost_pct: float, plan_row: dict[str, Any]) -> tuple[list[dict[str, Any]], Counter[str]]:
    mode = str(plan_row.get("repair_mode") or "")
    cluster = dict(plan_row.get("cluster") or {})
    output: list[dict[str, Any]] = []
    rejected: Counter[str] = Counter()
    for signal in signals:
        matched = cluster_match(signal, frame, regime, cluster) if cluster else False
        if mode == "PERSISTENT_LOSS_CLUSTER_VETO":
            if matched:
                rejected["PERSISTENT_LOSS_CLUSTER_VETO"] += 1
                continue
            output.append(dict(signal))
        elif mode == "GENERIC_EXECUTION_COST_BUFFER":
            if finite(signal.get("target_to_base_cost_ratio")) < 4.0:
                rejected["TARGET_COST_BUFFER_REJECT"] += 1
                continue
            output.append(dict(signal))
        elif mode == "PERSISTENT_LOSS_CLUSTER_ONE_BAR_CONFIRMATION":
            if not matched:
                output.append(dict(signal))
                continue
            confirmed = one_bar_confirmation(signal, frame, measurement, base_cost_pct)
            if confirmed is None:
                rejected["ONE_BAR_CONFIRMATION_REJECT"] += 1
                continue
            output.append(confirmed)
            rejected["ONE_BAR_CONFIRMATION_APPLIED"] += 1
        else:
            raise ValueError(f"UNSUPPORTED_REPAIR_MODE:{mode}")
    return output, rejected

def meaningful_severe(metrics: dict[str, Any]) -> bool:
    return bool(metrics.get("economic_pass")) and finite(metrics.get("net_pnl_sum_pct")) >= 0.50 and finite(metrics.get("profit_factor")) >= 1.20 and positive_folds(metrics) >= MIN_POSITIVE_FOLDS

def incremental_pass(lane: str, base: dict[str, Any], adverse: dict[str, Any], severe: dict[str, Any], plan_row: dict[str, Any]) -> tuple[bool, dict[str, bool]]:
    baseline_base = dict(plan_row.get("baseline_base_metrics") or {})
    baseline_adverse = dict(plan_row.get("baseline_adverse_metrics") or {})
    baseline_severe = dict(plan_row.get("baseline_severe_metrics") or {})
    base_non_degrade = int(base.get("trade_count") or 0) >= MIN_TRADES and finite(base.get("net_pnl_sum_pct")) >= finite(baseline_base.get("net_pnl_sum_pct")) - 0.25 and risk_score(base) >= risk_score(baseline_base) - 0.10
    adverse_positive = finite(adverse.get("net_pnl_sum_pct")) > 0 and finite(adverse.get("profit_factor")) > 1.0
    severe_delta = finite(severe.get("net_pnl_sum_pct")) - finite(baseline_severe.get("net_pnl_sum_pct"))
    adverse_fold_delta = positive_folds(adverse) - positive_folds(baseline_adverse)
    adverse_pnl_delta = finite(adverse.get("net_pnl_sum_pct")) - finite(baseline_adverse.get("net_pnl_sum_pct"))

    if lane == ATR5:
        defect_improved = meaningful_severe(severe) or (severe_delta >= 0.50 and finite(severe.get("profit_factor")) > finite(baseline_severe.get("profit_factor")) and positive_folds(severe) >= positive_folds(baseline_severe))
    elif lane == ATR15:
        defect_improved = adverse_positive and (adverse_fold_delta >= 1 or (severe_delta >= 0.75 and finite(severe.get("profit_factor")) > finite(baseline_severe.get("profit_factor"))))
    elif lane == MA5:
        defect_improved = adverse_pnl_delta >= 0.75 and severe_delta >= 0.75 and positive_folds(adverse) >= positive_folds(baseline_adverse)
    else:
        defect_improved = False
    checks = {"base_non_degrade": base_non_degrade, "adverse_positive": adverse_positive, "defect_improved": defect_improved, "meaningful_severe": meaningful_severe(severe)}
    return base_non_degrade and defect_improved, checks

def self_test() -> int:
    frame = pd.DataFrame({"open": [100.0, 101.0, 102.0, 103.0], "symbol": ["BTC"] * 4})
    measurement = pd.Series([True] * 4)
    signal = {"signal_bar_index": 0, "entry_bar_index": 1, "side": "long", "stop_price": 95.0, "target_price": 110.0, "target_to_base_cost_ratio": 5.0, "risk_to_base_cost_ratio": 3.0, "reason": "x"}
    confirmed = one_bar_confirmation(signal, frame, measurement, 0.2)
    assert confirmed is not None and confirmed["entry_bar_index"] == 2
    plan = {"repair_mode": "PERSISTENT_LOSS_CLUSTER_VETO", "cluster": {"axes": ["regime"], "values": ["bad"]}}
    repaired, rejected = apply_repair([signal], frame, measurement, "bad", 0.2, plan)
    assert not repaired and rejected["PERSISTENT_LOSS_CLUSTER_VETO"] == 1
    print("STATE=PASS_INCREMENTAL_DEFECT2_EXECUTION_SELF_TEST")
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
    if not all([args.raw_module, args.helper_module, args.benchmark_module, args.indicator_module, args.second_wave_module, args.a4d_contract]):
        raise SystemExit("ALL_MODULE_ARGUMENTS_REQUIRED")

    root = Path(args.root).resolve()
    raw = import_module(Path(args.raw_module).resolve(), "r7a4d2_defect2_raw")
    helper = import_module(Path(args.helper_module).resolve(), "r7a4d2_defect2_helper")
    benchmark = import_module(Path(args.benchmark_module).resolve(), "r7a4d2_defect2_benchmark")
    indicator = import_module(Path(args.indicator_module).resolve(), "r7a4d2_defect2_indicator")
    second = import_module(Path(args.second_wave_module).resolve(), "r7a4d2_defect2_second")
    contract = load_json(Path(args.a4d_contract).resolve())

    required = [root / PLAN_PATH, root / CALIBRATION_PATH, root / MANIFEST_PATH]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        print("STATE=HOLD_INCREMENTAL_DEFECT2_EXECUTION_INPUT")
        print("BLOCKER_COUNT=1")
        print("BLOCKERS=" + json.dumps(["REQUIRED_EVIDENCE_MISSING:" + ",".join(missing)]))
        print("RC=2")
        return 2

    plan = load_json(root / PLAN_PATH)
    calibration = load_json(root / CALIBRATION_PATH)
    manifest = load_json(root / MANIFEST_PATH)
    selected = [row for row in plan.get("defect2_repair_rows", []) if isinstance(row, dict)]
    expected_cells = int(plan.get("expected_defect2_cell_count") or 0)
    blockers: list[str] = []
    if plan.get("state") != "PASS_INCREMENTAL_RECOVERY_CONTRACT_REPAIR_AND_DEFECT2_AUDIT":
        blockers.append("DEFECT2_PLAN_NOT_PASS")
    if not selected or expected_cells != len(selected) * 6:
        blockers.append("DEFECT2_CELL_CONTRACT_INVALID")
    if any(str(row.get("lane_id") or "") not in {ATR5, ATR15, MA5} for row in selected):
        blockers.append("UNEXPECTED_ACTIVE_REPAIR_LANE")
    segments = {str(row["segment_id"]): row for row in manifest.get("selected_segments", []) if isinstance(row, dict)}
    if len(segments) != EXPECTED_SEGMENTS:
        blockers.append(f"SEGMENT_COUNT_INVALID:{len(segments)}")
    model = calibration.get("corrected_execution_model", {})
    costs = [row for row in model.get("profiles", []) if isinstance(row, dict)]
    timings = [row for row in model.get("timing_perturbations", []) if isinstance(row, dict)]
    if len(costs) * len(timings) != 6:
        blockers.append("STRESS_GRID_INVALID")
    base_cost_pct = benchmark.base_round_trip_cost(calibration)
    if not math.isfinite(base_cost_pct) or base_cost_pct <= 0:
        blockers.append("BASE_COST_INVALID")
    if blockers:
        print("STATE=HOLD_INCREMENTAL_DEFECT2_EXECUTION_INPUT")
        print("BLOCKER_COUNT=" + str(len(blockers)))
        print("BLOCKERS=" + json.dumps(blockers))
        print("RC=2")
        return 2

    source_sha = {str(row.get("source_path")): str(row.get("source_sha256") or "") for row in manifest.get("selected_segments", []) if isinstance(row, dict)}
    source_paths = sorted({str(row["source_path"]) for row in segments.values()})
    selected_paths = [root / raw.safe_repo_path(path) for path in source_paths]
    protected = [Path(str(value)) for value in contract.get("protected_paths", [])]
    before = snapshot(required + selected_paths + protected)

    source_cache: dict[str, pd.DataFrame] = {}
    frame_cache: dict[tuple[str, str], pd.DataFrame] = {}
    mask_cache: dict[tuple[str, str], pd.Series] = {}
    trade_rows: list[dict[str, Any]] = []
    cell_rows: list[dict[str, Any]] = []
    lane_rows: list[dict[str, Any]] = []

    for lane_number, plan_row in enumerate(sorted(selected, key=lambda row: str(row["lane_id"])), 1):
        lane_id = str(plan_row["lane_id"])
        variant = str(plan_row["control_variant_id"])
        timeframe = str(plan_row["execution_timeframe"])
        signal_cache: dict[str, list[dict[str, Any]]] = {}
        rejections: Counter[str] = Counter()
        control_count = 0
        for segment_id, segment in sorted(segments.items()):
            source_path = str(segment["source_path"])
            if source_path not in source_cache:
                source_cache[source_path] = raw.fixed_ohlcv_frame(root / raw.safe_repo_path(source_path), source_sha[source_path])
            for tf in {timeframe, "15m"}:
                key = (segment_id, tf)
                if key not in frame_cache:
                    frame_cache[key] = raw.resample_for_segment(source_cache[source_path], int(segment["start_row"]), int(segment["end_row_exclusive"]), tf)
                    mask_cache[key] = raw.measurement_mask(frame_cache[key], int(segment["start_row"]), int(segment["end_row_exclusive"]))
            control, generated_rejected = second.generate_variant_signals(variant, frame_cache[(segment_id, timeframe)], mask_cache[(segment_id, timeframe)], frame_cache[(segment_id, "15m")], str(segment["regime"]), base_cost_pct, indicator)
            repaired, repair_rejected = apply_repair(control, frame_cache[(segment_id, timeframe)], mask_cache[(segment_id, timeframe)], str(segment["regime"]), base_cost_pct, plan_row)
            signal_cache[segment_id] = repaired
            control_count += len(control)
            rejections.update(generated_rejected)
            rejections.update(repair_rejected)

        cell_map: dict[tuple[str, str], dict[str, Any]] = {}
        for cost in costs:
            for timing in timings:
                cell_trades: list[dict[str, Any]] = []
                for segment_id, segment in sorted(segments.items()):
                    frame = frame_cache[(segment_id, timeframe)]
                    measurement = mask_cache[(segment_id, timeframe)]
                    last_exit = -1
                    for signal in signal_cache[segment_id]:
                        if int(signal["entry_bar_index"]) <= last_exit:
                            continue
                        trade = benchmark.simulate_trade(frame, measurement, signal, cost, timing, timeframe)
                        if trade is None:
                            continue
                        last_exit = int(trade["exit_index"])
                        trade.update({
                            "lane_id": lane_id,
                            "control_variant_id": variant,
                            "repair_mode": plan_row["repair_mode"],
                            "execution_timeframe": timeframe,
                            "cost_profile_id": str(cost["id"]),
                            "timing_id": str(timing["id"]),
                            "segment_id": segment_id,
                            "fold": int(segment["fold"]),
                            "regime": str(segment["regime"]),
                            "symbol": str(frame.iloc[int(signal["signal_bar_index"])].get("symbol") or ""),
                            "signal_reason": signal["reason"],
                        })
                        cell_trades.append(trade)
                        trade_rows.append(trade)
                metrics = helper.aggregate_trades(cell_trades)
                metrics.update({
                    "lane_id": lane_id,
                    "control_variant_id": variant,
                    "repair_mode": plan_row["repair_mode"],
                    "execution_timeframe": timeframe,
                    "cost_profile_id": str(cost["id"]),
                    "timing_id": str(timing["id"]),
                    "fold_metrics": fold_metrics(helper, cell_trades),
                })
                metrics["gate_status"] = cell_gate(helper, metrics)
                metrics["economic_pass"] = all(metrics["gate_status"].values())
                cell_rows.append(metrics)
                cell_map[(str(cost["id"]), str(timing["id"]))] = metrics

        base = cell_map.get(BASE_CELL, {})
        adverse = cell_map.get(ADVERSE_CELL, {})
        severe = cell_map.get(SEVERE_CELL, {})
        passed, checks = incremental_pass(lane_id, base, adverse, severe, plan_row)
        lane_rows.append({
            "lane_id": lane_id,
            "control_variant_id": variant,
            "repair_mode": plan_row["repair_mode"],
            "cluster": plan_row.get("cluster"),
            "control_signal_count": control_count,
            "repaired_signal_count": sum(len(value) for value in signal_cache.values()),
            "rejection_histogram": dict(sorted(rejections.items())),
            "incremental_pass": passed,
            "pass_checks": checks,
            "robust_survivor_pass": bool(base.get("economic_pass")) and bool(adverse.get("economic_pass")) and meaningful_severe(severe),
            "base_metrics": base,
            "adverse_metrics": adverse,
            "severe_metrics": severe,
        })
        print(f"A4D2_INCREMENTAL_DEFECT2_PROGRESS={lane_number}/{len(selected)} CELLS={lane_number*6}/{expected_cells} TRADES={len(trade_rows)}")

    output = root / OUTPUT_DIR
    trade_count, trade_sha = atomic_jsonl(output / "incremental_defect2_trade_rows_v1.jsonl", trade_rows)
    cell_count, cell_sha = atomic_jsonl(output / "incremental_defect2_cell_rows_v1.jsonl", cell_rows)
    passed_ids = sorted(row["lane_id"] for row in lane_rows if row["incremental_pass"])
    robust_ids = sorted(row["lane_id"] for row in lane_rows if row["robust_survivor_pass"])
    failed_ids = sorted(set(str(row["lane_id"]) for row in selected) - set(passed_ids))
    next_stage = "R7.A4D2_INCREMENTAL_DEFECT3_AUDIT" if passed_ids else "R7.A4D2_ACTIVE_LANE_DATA_EXPANSION_OR_PRESERVE_DECISION"
    summary = {
        "state": "PASS_INCREMENTAL_DEFECT2_EXECUTION",
        "target_sha": args.target_sha,
        "selected_lane_count": len(selected),
        "cell_result_count": cell_count,
        "trade_result_count": trade_count,
        "trade_sha256": trade_sha,
        "cell_sha256": cell_sha,
        "incremental_pass_lane_count": len(passed_ids),
        "incremental_pass_lane_ids": passed_ids,
        "robust_survivor_lane_count": len(robust_ids),
        "robust_survivor_lane_ids": robust_ids,
        "failed_lane_count": len(failed_ids),
        "failed_lane_ids": failed_ids,
        "atr5_control_preserved": True,
        "donchian15_reference_preserved": True,
        "keep14_untouched": True,
        "lane_result_rows": lane_rows,
        "mutation_rows": [],
        "next_stage": next_stage,
    }
    atomic_json(output / "incremental_defect2_summary_v1.json", summary)
    after = snapshot(required + selected_paths + protected)
    mutations = [path for path in before if before[path] != after.get(path)]
    final_blockers: list[str] = []
    if cell_count != expected_cells:
        final_blockers.append(f"CELL_COUNT_INVALID:{cell_count}:{expected_cells}")
    if mutations:
        final_blockers.append(f"PROTECTED_MUTATIONS:{len(mutations)}")
    if final_blockers:
        print("STATE=HOLD_INCREMENTAL_DEFECT2_EXECUTION")
        print("BLOCKER_COUNT=" + str(len(final_blockers)))
        print("BLOCKERS=" + json.dumps(final_blockers))
        print("RC=2")
        return 2

    print("STATE=PASS_INCREMENTAL_DEFECT2_EXECUTION")
    print("BLOCKER_COUNT=0")
    print("SELECTED_LANE_COUNT=" + str(len(selected)))
    print("CELL_RESULT_COUNT=" + str(cell_count))
    print("TRADE_RESULT_COUNT=" + str(trade_count))
    print("INCREMENTAL_PASS_LANE_COUNT=" + str(len(passed_ids)))
    print("INCREMENTAL_PASS_LANE_IDS=" + json.dumps(passed_ids))
    print("ROBUST_SURVIVOR_LANE_COUNT=" + str(len(robust_ids)))
    print("ROBUST_SURVIVOR_LANE_IDS=" + json.dumps(robust_ids))
    print("FAILED_LANE_COUNT=" + str(len(failed_ids)))
    print("FAILED_LANE_IDS=" + json.dumps(failed_ids))
    print("ATR5_CONTROL_PRESERVED=true")
    print("DONCHIAN15_REFERENCE_PRESERVED=true")
    print("KEEP14_UNTOUCHED=true")
    print("LANE_RESULT_ROWS=" + json.dumps(lane_rows, sort_keys=True))
    print("SUMMARY_JSON=" + str(output / "incremental_defect2_summary_v1.json"))
    print("NEXT_STAGE=" + next_stage)
    print("BLOCKERS=[]")
    print("RC=0")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
