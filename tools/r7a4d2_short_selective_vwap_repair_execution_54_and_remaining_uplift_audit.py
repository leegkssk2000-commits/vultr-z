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
from typing import Any

import numpy as np
import pandas as pd

VWAP_PLAN = Path("runtime/r7a4d2_short_selective_vwap_economic_diagnose_and_repair_plan_rebuild/repair_plan_v1.json")
VERIFIED_PLAN = Path("runtime/r7a4d2_short_selective_raw_geometry_preservation_verification_repair/verified_effective_execution_plan_v3.json")
MERGED_GEOMETRY = Path("runtime/r7a4d2_short_selective_raw_geometry_rebaseline_execution/merged_signal_geometry_v2.jsonl")
MERGED_SCANS = Path("runtime/r7a4d2_short_selective_raw_geometry_rebaseline_execution/merged_scan_results_v2.jsonl")
MANIFEST = Path("runtime/r7a4c_historical_simulation_input_lineage/selected_input_manifest_v1.json")
CAUSAL_AUDIT = Path("runtime/r7a4d2_short_second_order_repair_causal_audit/causal_audit_v1.json")
ALL_LANE_CELLS = Path("runtime/r7a4d2_short_all_lane_architecture_repair_execution/repair_arm_cell_results_v1.jsonl")
OUTPUT_DIR = Path("runtime/r7a4d2_short_selective_vwap_repair_execution_54_and_remaining_uplift_audit")

EXPECTED_LANES = 3
EXPECTED_ARMS = 9
EXPECTED_REPAIR_CELLS = 54
EXPECTED_REFERENCE_CELLS = 18
EXPECTED_DISCOVERY_SEGMENTS = 12
EXPECTED_REMAINING_STRATEGIES = 10
SEVERE_CELL = ("cost_profile_2", "perturbation_1")
MIN_TRADES = 8
MIN_POSITIVE_CELLS = 4
PARTIAL_FRACTION = 0.30


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
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"JSONL_OBJECT_REQUIRED:{path}:{line_number}")
            rows.append(value)
    return rows


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def finite(value: Any, default: float | None = None) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def rolling_vwap(frame: pd.DataFrame, window: int = 20) -> pd.Series:
    typical = (frame["high"].astype(float) + frame["low"].astype(float) + frame["close"].astype(float)) / 3.0
    volume = frame["volume"].astype(float).clip(lower=0.0)
    numerator = (typical * volume).rolling(window, min_periods=max(5, window // 4)).sum()
    denominator = volume.rolling(window, min_periods=max(5, window // 4)).sum().replace(0.0, np.nan)
    return (numerator / denominator).ffill().bfill()


def unique_vwap_signals(rows: list[dict[str, Any]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    seen: set[tuple[str, str, int, str]] = set()
    for row in rows:
        lane_id = str(row.get("lane_id") or "")
        if not lane_id.startswith("strategy:vwap_revert:") or int(row.get("fold", 99)) >= 3:
            continue
        signal_index = int(row.get("signal_bar_index") or -1)
        parameter_id = str(row.get("parameter_id") or "canonical")
        key = (lane_id, str(row.get("segment_id") or ""), signal_index, parameter_id)
        if signal_index < 0 or key in seen:
            continue
        seen.add(key)
        signal = dict(row)
        signal["signal_bar_index"] = signal_index
        signal["entry_bar_index"] = int(row.get("entry_bar_index") or signal_index + 1)
        grouped[(key[0], key[1])].append(signal)
    for key in grouped:
        grouped[key].sort(key=lambda row: (int(row["entry_bar_index"]), int(row["signal_bar_index"])))
    return grouped


def economic_pass(row: dict[str, Any]) -> bool:
    return bool(
        int(row.get("trade_count") or 0) >= MIN_TRADES
        and float(finite(row.get("profit_factor"), -1e100)) > 1.0
        and float(finite(row.get("expectancy_r"), -1e100)) > 0.0
        and float(finite(row.get("net_pnl_sum_pct"), -1e100)) > 0.0
    )


def entry_filter(frame: pd.DataFrame, vwap: pd.Series, signal_index: int, design: dict[str, Any]) -> bool:
    if signal_index < 5 or signal_index >= len(frame):
        return False
    current = frame.iloc[signal_index]
    previous = frame.iloc[signal_index - 1]
    current_vwap = finite(vwap.iloc[signal_index])
    if current_vwap is None or current_vwap <= 0:
        return False
    minimum = float(finite(design.get("minimum_entry_deviation_pct"), 0.0) or 0.0)
    excursion_price = max(float(current["high"]), float(previous["close"]), float(previous["high"]))
    excursion_pct = (excursion_price - current_vwap) / current_vwap * 100.0
    bearish = float(current["close"]) < float(current["open"]) and float(current["close"]) < float(previous["close"])
    moved_toward = abs(float(current["close"]) - current_vwap) < abs(excursion_price - current_vwap)
    above_or_touch = excursion_price >= current_vwap
    return bool(excursion_pct >= minimum and bearish and moved_toward and above_or_touch)


def resolve_levels(
    signal: dict[str, Any], frame: pd.DataFrame, vwap: pd.Series, entry_index: int,
    lane_parameters: dict[str, Any], axis: str,
) -> tuple[float, float, float, int] | None:
    entry = float(frame.iloc[entry_index]["open"])
    if entry <= 0:
        return None
    stop_pct = float(finite(lane_parameters.get("structural_stop_distance_pct"), 0.45) or 0.45)
    partial_pct = float(finite(lane_parameters.get("partial_trigger_mfe_pct"), 0.15) or 0.15)
    timeout = max(1, int(lane_parameters.get("timeout_bars") or 6))
    declared_sl = finite(signal.get("declared_sl"))
    declared_tp = finite(signal.get("declared_tp"))
    structural_sl = entry * (1.0 + max(stop_pct, 0.10) / 100.0)
    sl = float(declared_sl) if declared_sl is not None and declared_sl > entry else structural_sl
    vwap_target = finite(vwap.iloc[entry_index])
    fallback_tp = entry * (1.0 - max(partial_pct, 0.10) / 100.0)
    tp = float(declared_tp) if declared_tp is not None and 0 < declared_tp < entry else (
        float(vwap_target) if vwap_target is not None and 0 < vwap_target < entry else fallback_tp
    )
    if axis == "EXIT":
        sl = structural_sl
    if not (math.isfinite(sl) and math.isfinite(tp) and sl > entry > tp > 0):
        return None
    return sl, tp, partial_pct, timeout


def simulate_trade(
    frame: pd.DataFrame,
    measurement: pd.Series,
    vwap: pd.Series,
    signal: dict[str, Any],
    arm: dict[str, Any] | None,
    lane_parameters: dict[str, Any],
    cost: dict[str, Any],
    perturbation: dict[str, Any],
    timeframe: str,
    regime: str,
) -> dict[str, Any] | None:
    axis = str(arm.get("axis") or "REFERENCE") if arm else "REFERENCE"
    design = arm.get("design") if arm and isinstance(arm.get("design"), dict) else {}
    signal_index = int(signal["signal_bar_index"])
    if axis == "ENTRY" and not entry_filter(frame, vwap, signal_index, design):
        return None
    if axis == "REGIME":
        allowed = {str(value) for value in design.get("allowed_regimes", [])}
        if allowed and regime not in allowed:
            return None
        if design.get("trend_up_chase_veto") is True and regime == "trend_up":
            return None
        if signal_index < int(design.get("post_shock_cooldown_bars") or 0):
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
    levels = resolve_levels(signal, frame, vwap, entry_index, lane_parameters, axis)
    if levels is None:
        return None
    sl, tp, partial_trigger_pct, timeout = levels
    entry = float(frame.iloc[entry_index]["open"])
    risk_pct = (sl - entry) / entry * 100.0
    if risk_pct <= 0:
        return None

    partial_done = False
    partial_price: float | None = None
    reason = "segment_end"
    trigger_index = last_index
    reference_exit = float(frame.iloc[last_index]["close"])
    timeout_index = min(entry_index + timeout, last_index)
    partial_level = entry * (1.0 - max(partial_trigger_pct, 0.05) / 100.0)

    for index in range(entry_index, last_index + 1):
        high = float(frame.iloc[index]["high"])
        low = float(frame.iloc[index]["low"])
        close = float(frame.iloc[index]["close"])
        current_vwap = finite(vwap.iloc[index])
        if high >= sl:
            reason, trigger_index, reference_exit = "stop", index, sl
            break
        if axis == "EXIT":
            if not partial_done and low <= partial_level:
                partial_done, partial_price = True, partial_level
            if current_vwap is not None and current_vwap < entry and (low <= current_vwap or close <= current_vwap):
                reason, trigger_index, reference_exit = "vwap_touch_or_close_cross", index, float(current_vwap)
                break
            if index >= timeout_index:
                reason, trigger_index, reference_exit = "timeout", index, close
                break
        else:
            if low <= tp:
                reason, trigger_index, reference_exit = "take_profit", index, tp
                break
            if index >= timeout_index:
                reason, trigger_index, reference_exit = "timeout", index, close
                break

    execution_index = min(trigger_index + exit_delay, last_index)
    if exit_delay == 0 and reason in {"stop", "take_profit", "vwap_touch_or_close_cross"}:
        final_exit = reference_exit
    elif reason == "segment_end":
        final_exit = float(frame.iloc[execution_index]["close"])
    else:
        final_exit = float(frame.iloc[execution_index]["open"])

    final_gross = (entry - final_exit) / entry * 100.0
    if axis == "EXIT" and partial_done and partial_price is not None:
        partial_gross = (entry - partial_price) / entry * 100.0
        gross_pct = PARTIAL_FRACTION * partial_gross + (1.0 - PARTIAL_FRACTION) * final_gross
        reason = "partial30+" + reason
    else:
        gross_pct = final_gross
    round_trip_pct = 2.0 * (
        float(cost.get("fee_bps_per_side") or 0.0) + float(cost.get("slippage_bps_per_side") or 0.0)
    ) / 100.0
    minutes = {"1m": 1, "5m": 5, "15m": 15}.get(timeframe, 1)
    holding_hours = max(execution_index - entry_index, 0) * minutes / 60.0
    funding_pct = float(cost.get("funding_bps_per_8h") or 0.0) / 100.0 * holding_hours / 8.0
    net_pct = gross_pct - round_trip_pct - funding_pct
    return {
        "entry_index": entry_index,
        "exit_index": execution_index,
        "entry_price": entry,
        "exit_price": final_exit,
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
        "partial30_executed": partial_done,
    }


def remaining_uplift_rows(causal: dict[str, Any]) -> list[dict[str, Any]]:
    route_map = {
        "SIGNAL_OR_ENTRY_SAMPLE_DEFICIT": "NATIVE_SIGNAL_AND_TIMEFRAME_REBUILD",
        "SEVERE_COST_TIMING_SAMPLE_COLLAPSE": "ENTRY_SPACING_AND_DELAY_ROBUSTNESS",
        "CROSS_STRESS_INSTABILITY": "REGIME_GATE_AND_STABILITY_REBUILD",
        "COST_FRICTION_SENSITIVITY": "TIMEFRAME_UPSHIFT_OR_TURNOVER_REDUCTION",
        "TIMING_LATENCY_SENSITIVITY": "CONFIRMATION_AND_DELAY_ROBUST_ENTRY",
        "PAYOFF_COMPRESSION_EXIT_GEOMETRY": "STOP_TP_ASYMMETRY_PARTIAL_RUNNER",
        "NEGATIVE_EDGE_ENTRY_OR_REGIME": "ENTRY_AND_REGIME_HYPOTHESIS_REBUILD",
        "EXPECTANCY_PNL_COMPRESSION": "TIMEOUT_PARTIAL_AND_MFE_CAPTURE",
        "PAYOFF_DISTRIBUTION_FAILURE": "WIN_RATE_PAYOFF_DISTRIBUTION_REBALANCE",
        "MULTI_AXIS_STRESS_FAILURE": "STRATEGY_SPECIFIC_MULTI_AXIS_REDESIGN",
    }
    rows: list[dict[str, Any]] = []
    for strategy in causal.get("strategy_causal_rows", []):
        if not isinstance(strategy, dict) or str(strategy.get("strategy_id")) == "vwap_revert":
            continue
        top = strategy.get("top_near_misses") if isinstance(strategy.get("top_near_misses"), list) else []
        best = top[0] if top and isinstance(top[0], dict) else {}
        severe = best.get("severe_metrics") if isinstance(best.get("severe_metrics"), dict) else {}
        low = best.get("low_cost_no_delay_metrics") if isinstance(best.get("low_cost_no_delay_metrics"), dict) else {}
        gate_count = int(strategy.get("best_gate_pass_count") or 0)
        low_pass = economic_pass(low)
        severe_trades = int(severe.get("trade_count") or 0)
        pf = float(finite(severe.get("profit_factor"), 0.0) or 0.0)
        expectancy = float(finite(severe.get("expectancy_r"), -1e100) or -1e100)
        if gate_count >= 3 or low_pass:
            tier = "A"
        elif gate_count >= 2 or (severe_trades >= MIN_TRADES and (pf >= 0.80 or expectancy > -0.15)):
            tier = "B"
        else:
            tier = "C"
        cause = str(strategy.get("primary_root_cause") or "UNKNOWN")
        rows.append({
            "strategy_id": str(strategy.get("strategy_id") or ""),
            "family": str(best.get("family") or ""),
            "priority_tier": tier,
            "best_lane_id": strategy.get("best_near_miss_lane_id"),
            "best_arm_id": strategy.get("best_near_miss_arm_id"),
            "best_arm_axis": strategy.get("best_near_miss_arm_axis"),
            "best_gate_pass_count": gate_count,
            "best_positive_stress_cell_count": int(strategy.get("best_positive_stress_cell_count") or 0),
            "primary_root_cause": cause,
            "next_rebuild_axis": route_map.get(cause, "FULL_NATIVE_HYPOTHESIS_REBUILD"),
            "low_cost_economic_pass": low_pass,
            "severe_trade_count": severe_trades,
            "severe_profit_factor": finite(severe.get("profit_factor")),
            "severe_expectancy_r": finite(severe.get("expectancy_r")),
            "severe_net_pnl_pct": finite(severe.get("net_pnl_sum_pct")),
            "retirement_allowed_now": False,
        })
    tier_rank = {"A": 3, "B": 2, "C": 1}
    rows.sort(key=lambda row: (
        tier_rank[row["priority_tier"]], int(row["best_gate_pass_count"]),
        int(row["best_positive_stress_cell_count"]), float(row["severe_expectancy_r"] or -1e100),
    ), reverse=True)
    return rows


def self_test() -> int:
    frame = pd.DataFrame({
        "open": np.linspace(101.0, 99.0, 40),
        "high": np.linspace(101.3, 99.3, 40),
        "low": np.linspace(100.7, 98.7, 40),
        "close": np.linspace(100.9, 98.9, 40),
        "volume": np.ones(40),
    })
    vwap = rolling_vwap(frame)
    signal = {"signal_bar_index": 10, "entry_bar_index": 11, "declared_sl": None, "declared_tp": None}
    measurement = pd.Series([True] * 40)
    trade = simulate_trade(
        frame, measurement, vwap, signal,
        {"axis": "EXIT", "design": {}},
        {"structural_stop_distance_pct": 0.5, "partial_trigger_mfe_pct": 0.1, "timeout_bars": 5},
        {"fee_bps_per_side": 1.0, "slippage_bps_per_side": 1.0, "latency_bars": 0, "funding_bps_per_8h": 0.0},
        {"additional_entry_delay_bars": 0, "additional_exit_delay_bars": 0}, "5m", "range",
    )
    assert trade is not None and math.isfinite(float(trade["net_r"]))
    print("STATE=PASS_SHORT_SELECTIVE_VWAP_REPAIR_EXECUTION_54_AND_REMAINING_UPLIFT_AUDIT_SELF_TEST")
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
    if not all((args.raw_module, args.helper_module, args.a4d_contract)):
        raise SystemExit("--raw-module --helper-module --a4d-contract required")

    root = Path(args.root).resolve()
    required = [
        root / VWAP_PLAN, root / VERIFIED_PLAN, root / MERGED_GEOMETRY, root / MERGED_SCANS,
        root / MANIFEST, root / CAUSAL_AUDIT, root / ALL_LANE_CELLS,
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        print("STATE=HOLD_SHORT_SELECTIVE_VWAP_REPAIR_EXECUTION_54_AND_REMAINING_UPLIFT_AUDIT_INPUT")
        print("BLOCKER_COUNT=1")
        print("BLOCKERS=" + json.dumps(["REQUIRED_EVIDENCE_MISSING:" + ",".join(missing)]))
        print("RC=2")
        return 2

    raw = import_module(Path(args.raw_module).resolve(), "r7a4d2_vwap_raw")
    helper = import_module(Path(args.helper_module).resolve(), "r7a4d2_vwap_helper")
    plan = load_json(root / VWAP_PLAN)
    effective = load_json(root / VERIFIED_PLAN)
    manifest = load_json(root / MANIFEST)
    causal = load_json(root / CAUSAL_AUDIT)
    contract = load_json(Path(args.a4d_contract).resolve())
    geometry_path = root / MERGED_GEOMETRY
    scans_path = root / MERGED_SCANS
    blockers: list[str] = []

    if plan.get("state") != "PASS_SHORT_SELECTIVE_VWAP_ECONOMIC_DIAGNOSE_AND_REPAIR_PLAN_REBUILD":
        blockers.append("VWAP_REPAIR_PLAN_NOT_PASS")
    arms = [row for row in plan.get("repair_arms", []) if isinstance(row, dict)]
    diagnoses = [row for row in plan.get("diagnosis_rows", []) if isinstance(row, dict)]
    if len(arms) != EXPECTED_ARMS or len(diagnoses) != EXPECTED_LANES:
        blockers.append(f"VWAP_PLAN_CARDINALITY_INVALID:{len(arms)}:{len(diagnoses)}")
    raw_evidence = effective.get("raw_geometry_evidence") if isinstance(effective.get("raw_geometry_evidence"), dict) else {}
    if str(raw_evidence.get("signal_geometry_sha256") or "") != sha256_file(geometry_path):
        blockers.append("MERGED_GEOMETRY_SHA_MISMATCH")
    if str(raw_evidence.get("scan_results_sha256") or "") != sha256_file(scans_path):
        blockers.append("MERGED_SCAN_SHA_MISMATCH")
    if causal.get("state") != "PASS_SHORT_SECOND_ORDER_REPAIR_CAUSAL_AUDIT":
        blockers.append("CAUSAL_AUDIT_NOT_PASS")
    costs = [row for row in contract.get("cost_profiles", []) if isinstance(row, dict)]
    perturbations = [row for row in contract.get("perturbations", []) if isinstance(row, dict)]
    if len(costs) * len(perturbations) != 6:
        blockers.append("STRESS_CELL_CONTRACT_INVALID")
    segments = {
        str(row["segment_id"]): row for row in manifest.get("selected_segments", [])
        if isinstance(row, dict) and int(row.get("fold", 99)) < 3
    }
    if len(segments) != EXPECTED_DISCOVERY_SEGMENTS:
        blockers.append(f"DISCOVERY_SEGMENT_COUNT_INVALID:{len(segments)}")
    lane_map = {
        str(row.get("lane_id")): row for row in effective.get("strategy_lanes", [])
        if isinstance(row, dict) and str(row.get("strategy_id")) == "vwap_revert"
    }
    if len(lane_map) != EXPECTED_LANES:
        blockers.append(f"VWAP_EFFECTIVE_LANE_COUNT_INVALID:{len(lane_map)}")
    diagnosis_map = {str(row.get("lane_id")): row for row in diagnoses}
    arms_by_lane: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for arm in arms:
        arms_by_lane[str(arm.get("lane_id"))].append(arm)
    if set(arms_by_lane) != set(lane_map) or any(len(rows) != 3 for rows in arms_by_lane.values()):
        blockers.append("VWAP_ARM_LANE_BINDING_INVALID")
    if blockers:
        print("STATE=HOLD_SHORT_SELECTIVE_VWAP_REPAIR_EXECUTION_54_AND_REMAINING_UPLIFT_AUDIT_INPUT")
        print("BLOCKER_COUNT=" + str(len(blockers)))
        print("BLOCKERS=" + json.dumps(blockers, ensure_ascii=False))
        print("RC=2")
        return 2

    source_sha = {
        str(row.get("source_path")): str(row.get("source_sha256") or "")
        for row in manifest.get("selected_segments", []) if isinstance(row, dict)
    }
    canonical_paths = required[:]
    for lane in lane_map.values():
        path = str(lane.get("implementation_path") or "")
        if path:
            canonical_paths.append(root / helper.safe_repo_path(path))
    for segment in segments.values():
        canonical_paths.append(root / helper.safe_repo_path(str(segment["source_path"])))
    protected = [Path(str(value)) for value in contract.get("protected_paths", [])]
    before = helper.snapshot(canonical_paths + protected)

    signals = unique_vwap_signals(load_jsonl(geometry_path))
    source_cache: dict[str, pd.DataFrame] = {}
    frame_cache: dict[tuple[str, str], pd.DataFrame] = {}
    measurement_cache: dict[tuple[str, str], pd.Series] = {}
    vwap_cache: dict[tuple[str, str], pd.Series] = {}

    for lane_id, lane in lane_map.items():
        for segment_id, segment in segments.items():
            key = (lane_id, segment_id)
            source_path = str(segment["source_path"])
            if source_path not in source_cache:
                source_cache[source_path] = raw.fixed_ohlcv_frame(
                    root / helper.safe_repo_path(source_path), source_sha[source_path]
                )
            frame_cache[key] = raw.resample_for_segment(
                source_cache[source_path], int(segment["start_row"]), int(segment["end_row_exclusive"]), str(lane["timeframe"])
            )
            measurement_cache[key] = raw.measurement_mask(
                frame_cache[key], int(segment["start_row"]), int(segment["end_row_exclusive"])
            )
            vwap_cache[key] = rolling_vwap(frame_cache[key])

    trade_rows: list[dict[str, Any]] = []
    repair_cells: list[dict[str, Any]] = []
    reference_cells: list[dict[str, Any]] = []

    def execute_cell(lane_id: str, arm: dict[str, Any] | None, cost: dict[str, Any], perturbation: dict[str, Any]) -> list[dict[str, Any]]:
        lane = lane_map[lane_id]
        params = diagnosis_map[lane_id].get("derived_parameters") if isinstance(diagnosis_map[lane_id].get("derived_parameters"), dict) else {}
        cell_trades: list[dict[str, Any]] = []
        for segment_id, segment in sorted(segments.items()):
            key = (lane_id, segment_id)
            frame = frame_cache[key]
            measurement = measurement_cache[key]
            vwap_series = vwap_cache[key]
            last_exit = -1
            for signal in signals.get(key, []):
                if int(signal["entry_bar_index"]) <= last_exit:
                    continue
                trade = simulate_trade(
                    frame, measurement, vwap_series, signal, arm, params, cost, perturbation,
                    str(lane["timeframe"]), str(segment.get("regime") or "unknown"),
                )
                if trade is None:
                    continue
                last_exit = int(trade["exit_index"])
                trade.update({
                    "lane_id": lane_id,
                    "strategy_id": "vwap_revert",
                    "timeframe": lane["timeframe"],
                    "arm_id": str(arm.get("arm_id")) if arm else "native_reference",
                    "arm_axis": str(arm.get("axis")) if arm else "REFERENCE",
                    "cost_profile_id": cost["id"],
                    "perturbation_id": perturbation["id"],
                    "segment_id": segment_id,
                    "regime": segment.get("regime"),
                    "fold": int(segment.get("fold") or 0),
                    "signal_bar_index": int(signal["signal_bar_index"]),
                })
                trade_rows.append(trade)
                cell_trades.append(trade)
        return cell_trades

    completed = 0
    for lane_id in sorted(lane_map):
        for cost in costs:
            for perturbation in perturbations:
                trades = execute_cell(lane_id, None, cost, perturbation)
                reference_cells.append({
                    "lane_id": lane_id, "strategy_id": "vwap_revert", "timeframe": lane_map[lane_id]["timeframe"],
                    "arm_id": "native_reference", "arm_axis": "REFERENCE",
                    "cost_profile_id": cost["id"], "perturbation_id": perturbation["id"],
                    **helper.aggregate_trades(trades),
                })
        for arm in arms_by_lane[lane_id]:
            for cost in costs:
                for perturbation in perturbations:
                    trades = execute_cell(lane_id, arm, cost, perturbation)
                    repair_cells.append({
                        "lane_id": lane_id, "strategy_id": "vwap_revert", "timeframe": lane_map[lane_id]["timeframe"],
                        "arm_id": arm["arm_id"], "arm_axis": arm["axis"],
                        "standalone_promotion_allowed": bool(arm.get("standalone_promotion_allowed")),
                        "cost_profile_id": cost["id"], "perturbation_id": perturbation["id"],
                        **helper.aggregate_trades(trades),
                    })
            completed += 1
            print(f"A4D2_SELECTIVE_VWAP_REPAIR_PROGRESS={completed}/{EXPECTED_ARMS} CELLS={len(repair_cells)}/{EXPECTED_REPAIR_CELLS} TRADES={len(trade_rows)}")

    if len(reference_cells) != EXPECTED_REFERENCE_CELLS:
        blockers.append(f"REFERENCE_CELL_COUNT_INVALID:{len(reference_cells)}")
    if len(repair_cells) != EXPECTED_REPAIR_CELLS:
        blockers.append(f"REPAIR_CELL_COUNT_INVALID:{len(repair_cells)}")

    reference_map = {
        (str(row["lane_id"]), str(row["cost_profile_id"]), str(row["perturbation_id"])): row for row in reference_cells
    }
    cell_map = {
        (str(row["lane_id"]), str(row["arm_id"]), str(row["cost_profile_id"]), str(row["perturbation_id"])): row for row in repair_cells
    }
    candidate_rows: list[dict[str, Any]] = []
    for arm in arms:
        lane_id = str(arm["lane_id"])
        arm_id = str(arm["arm_id"])
        severe = cell_map[(lane_id, arm_id, *SEVERE_CELL)]
        native_severe = reference_map[(lane_id, *SEVERE_CELL)]
        cells = [row for row in repair_cells if row["lane_id"] == lane_id and row["arm_id"] == arm_id]
        positive_cells = sum(1 for row in cells if economic_pass(row))
        candidate_dd = float(finite(severe.get("max_drawdown_pct"), 1e100) or 1e100)
        native_dd = float(finite(native_severe.get("max_drawdown_pct"), 1e100) or 1e100)
        dd_nonworsening = candidate_dd <= native_dd + 1e-12
        eligible = economic_pass(severe) and positive_cells >= MIN_POSITIVE_CELLS and dd_nonworsening
        candidate_rows.append({
            "lane_id": lane_id,
            "timeframe": lane_map[lane_id]["timeframe"],
            "arm_id": arm_id,
            "arm_axis": arm["axis"],
            "standalone_promotion_allowed": bool(arm.get("standalone_promotion_allowed")),
            "severe_metrics": severe,
            "native_reference_severe_metrics": native_severe,
            "positive_stress_cell_count": positive_cells,
            "drawdown_nonworsening_vs_native": dd_nonworsening,
            "eligible_economic_survivor": eligible,
        })

    eligible = [row for row in candidate_rows if row["eligible_economic_survivor"]]
    eligible.sort(key=lambda row: (
        int(bool(row["standalone_promotion_allowed"])),
        float(finite(row["severe_metrics"].get("expectancy_r"), -1e100) or -1e100),
        float(finite(row["severe_metrics"].get("profit_factor"), -1e100) or -1e100),
        float(finite(row["severe_metrics"].get("net_pnl_sum_pct"), -1e100) or -1e100),
        int(row["positive_stress_cell_count"]),
        -float(finite(row["severe_metrics"].get("max_drawdown_pct"), 1e100) or 1e100),
    ), reverse=True)
    selected = eligible[0] if eligible else None
    standalone = [row for row in eligible if row["standalone_promotion_allowed"]]
    context_only = [row for row in eligible if not row["standalone_promotion_allowed"]]

    uplift_rows = remaining_uplift_rows(causal)
    if len(uplift_rows) != EXPECTED_REMAINING_STRATEGIES:
        blockers.append(f"REMAINING_STRATEGY_COUNT_INVALID:{len(uplift_rows)}")
    priority_hist = dict(sorted(Counter(str(row["priority_tier"]) for row in uplift_rows).items()))
    axis_hist = dict(sorted(Counter(str(row["next_rebuild_axis"]) for row in uplift_rows).items()))

    after = helper.snapshot(canonical_paths + protected)
    mutations = sorted(path for path in before if before[path] != after.get(path))
    if mutations:
        blockers.append("PROTECTED_INPUT_MUTATION:" + json.dumps(mutations))
    unique_blockers = list(dict.fromkeys(blockers))
    state = (
        "PASS_SHORT_SELECTIVE_VWAP_REPAIR_EXECUTION_54_AND_REMAINING_UPLIFT_AUDIT"
        if not unique_blockers else
        "HOLD_SHORT_SELECTIVE_VWAP_REPAIR_EXECUTION_54_AND_REMAINING_UPLIFT_AUDIT"
    )
    if not unique_blockers and selected is not None:
        next_stage = "R7.A4D2_SHORT_SELECTIVE_VWAP_DISCOVERY_LOCK_AND_INDEPENDENT_VALIDATION_PLAN"
    elif not unique_blockers:
        next_stage = "R7.A4D2_SHORT_VWAP_NATIVE_HYPOTHESIS_REBUILD_AND_REMAINING_10_STRATEGY_FAMILY_REBUILD_PLAN"
    else:
        next_stage = "R7.A4D2_SHORT_SELECTIVE_VWAP_REPAIR_EXECUTION_DIAGNOSE"

    output = root / OUTPUT_DIR
    trade_count, trade_sha = atomic_jsonl(output / "vwap_trade_results_v1.jsonl", trade_rows)
    repair_count, repair_sha = atomic_jsonl(output / "vwap_repair_cell_results_v1.jsonl", repair_cells)
    reference_count, reference_sha = atomic_jsonl(output / "vwap_native_reference_cell_results_v1.jsonl", reference_cells)
    report = {
        "schema": "r7a4d2_short_selective_vwap_repair_execution_54_and_remaining_uplift_audit_v1",
        "official_stage": "R7.A4D2_SHORT_SELECTIVE_VWAP_REPAIR_EXECUTION_54_AND_REMAINING_UPLIFT_AUDIT",
        "state": state,
        "target_commit": args.target_sha,
        "blocker_count": len(unique_blockers),
        "blockers": unique_blockers,
        "vwap_lane_count": len(lane_map),
        "vwap_repair_arm_count": len(arms),
        "vwap_repair_cell_count": repair_count,
        "vwap_native_reference_cell_count": reference_count,
        "vwap_trade_count": trade_count,
        "vwap_trade_results_sha256": trade_sha,
        "vwap_repair_cell_results_sha256": repair_sha,
        "vwap_native_reference_cell_results_sha256": reference_sha,
        "economic_survivor_count": len(eligible),
        "standalone_survivor_count": len(standalone),
        "context_only_survivor_count": len(context_only),
        "selected_candidate": selected,
        "candidate_rows": candidate_rows,
        "remaining_strategy_count": len(uplift_rows),
        "remaining_uplift_priority_histogram": priority_hist,
        "remaining_uplift_axis_histogram": axis_hist,
        "remaining_uplift_rows": uplift_rows,
        "remaining_family_rebuild_pending": True,
        "strategy_mutation_allowed": False,
        "registry_mutation_allowed": False,
        "shadow_start_allowed": False,
        "paper_live_order_allowed": False,
        "input_mutation_paths": mutations,
        "next_stage": next_stage,
    }
    atomic_json(output / "economic_execution_and_uplift_audit_v1.json", report)

    print("STATE=" + state)
    print("BLOCKER_COUNT=" + str(len(unique_blockers)))
    print("VWAP_REPAIR_ARM_COUNT=" + str(len(arms)))
    print("VWAP_REPAIR_CELL_COUNT=" + str(repair_count))
    print("VWAP_NATIVE_REFERENCE_CELL_COUNT=" + str(reference_count))
    print("VWAP_TRADE_COUNT=" + str(trade_count))
    print("VWAP_ECONOMIC_SURVIVOR_COUNT=" + str(len(eligible)))
    print("VWAP_STANDALONE_SURVIVOR_COUNT=" + str(len(standalone)))
    print("VWAP_CONTEXT_ONLY_SURVIVOR_COUNT=" + str(len(context_only)))
    print("VWAP_SELECTED_CANDIDATE=" + json.dumps(selected, ensure_ascii=False, sort_keys=True))
    print("VWAP_CANDIDATE_ROWS=" + json.dumps(candidate_rows, ensure_ascii=False, sort_keys=True))
    print("REMAINING_STRATEGY_COUNT=" + str(len(uplift_rows)))
    print("REMAINING_UPLIFT_PRIORITY_HISTOGRAM=" + json.dumps(priority_hist, sort_keys=True))
    print("REMAINING_UPLIFT_AXIS_HISTOGRAM=" + json.dumps(axis_hist, sort_keys=True))
    print("REMAINING_UPLIFT_ROWS=" + json.dumps(uplift_rows, ensure_ascii=False, sort_keys=True))
    print("REMAINING_FAMILY_REBUILD_PENDING=true")
    print("REPORT_JSON=" + str(output / "economic_execution_and_uplift_audit_v1.json"))
    print("NEXT_STAGE=" + next_stage)
    print("BLOCKERS=" + json.dumps(unique_blockers, ensure_ascii=False))
    print("RC=" + ("0" if not unique_blockers else "2"))
    return 0 if not unique_blockers else 2


if __name__ == "__main__":
    raise SystemExit(main())
