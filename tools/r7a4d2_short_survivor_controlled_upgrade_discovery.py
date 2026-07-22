#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import statistics
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

DIAG_PATH = Path("runtime/r7a4d2_short_raw_geometry_mutation_and_lane_economic_diagnose/diagnose_v1.json")
PLAN_PATH = Path("runtime/r7a4d2_short_raw_geometry_and_simple_benchmark_execution_plan/execution_plan_v1.json")
EXEC_DIR = Path("runtime/r7a4d2_short_raw_geometry_and_simple_benchmark_execution")
OUTPUT_DIR = Path("runtime/r7a4d2_short_survivor_controlled_upgrade_discovery")
EXPECTED_SURVIVORS = {
    "strategy:vwap_revert:5m": {"strategy_id": "vwap_revert", "family": "mean_reversion", "timeframe": "5m"},
    "strategy:grid_rebalance:1m": {"strategy_id": "grid_rebalance", "family": "grid_range", "timeframe": "1m"},
}
SEVERE_CELL = ("cost_profile_2", "perturbation_1")
MIN_DISCOVERY_TRADES = 8


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
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)
    return len(rows), sha256_file(path)


def import_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"MODULE_SPEC_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def safe_repo_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"UNSAFE_REPO_PATH:{value}")
    return path


def snapshot(paths: list[Path]) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in paths:
        key = str(path.resolve())
        result[key] = sha256_file(path) if path.is_file() else "__MISSING__"
    return result


def classify_mutation(path_value: str, root: Path) -> str:
    path = Path(path_value).resolve()
    try:
        path.relative_to((root / "runtime/exact25_edge_v1").resolve())
        return "EXTERNAL_OPERATIONAL_VOLATILE_MUTATION"
    except ValueError:
        pass
    if path == Path("/etc/caddy/Caddyfile"):
        return "EXTERNAL_INFRA_MUTATION"
    return "CRITICAL_INPUT_MUTATION"


def rsi(series: pd.Series, length: int = 14) -> pd.Series:
    delta = series.astype(float).diff()
    up = delta.clip(lower=0.0)
    down = -delta.clip(upper=0.0)
    avg_up = up.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
    avg_down = down.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
    rs = avg_up / (avg_down + 1e-9)
    return 100.0 - (100.0 / (1.0 + rs))


def cumulative_vwap(frame: pd.DataFrame) -> pd.Series:
    typical = (frame["high"].astype(float) + frame["low"].astype(float) + frame["close"].astype(float)) / 3.0
    volume = frame["volume"].astype(float)
    return (typical * volume).cumsum() / (volume.cumsum() + 1e-9)


def arm_definitions(lane_id: str) -> list[dict[str, Any]]:
    if lane_id == "strategy:vwap_revert:5m":
        return [
            {"arm_id": "baseline_canonical", "axis": "baseline"},
            {"arm_id": "entry_short_beam_only", "axis": "entry"},
            {"arm_id": "stop_atr_075", "axis": "stop"},
            {"arm_id": "exit_full_vwap", "axis": "exit"},
        ]
    if lane_id == "strategy:grid_rebalance:1m":
        return [
            {"arm_id": "baseline_canonical", "axis": "baseline"},
            {"arm_id": "entry_short_beam_only", "axis": "entry"},
            {"arm_id": "stop_grid_075", "axis": "stop"},
            {"arm_id": "exit_anchor_mean", "axis": "exit"},
        ]
    raise ValueError(f"UNSUPPORTED_SURVIVOR:{lane_id}")


def indicator_bundle(lane_id: str, frame: pd.DataFrame) -> dict[str, pd.Series]:
    close = frame["close"].astype(float)
    atr = pd.concat(
        [
            frame["high"].astype(float) - frame["low"].astype(float),
            (frame["high"].astype(float) - close.shift(1)).abs(),
            (frame["low"].astype(float) - close.shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1).rolling(14, min_periods=14).mean()
    if lane_id == "strategy:vwap_revert:5m":
        return {
            "atr": atr,
            "rsi": rsi(close, 14),
            "vwap": cumulative_vwap(frame),
        }
    return {
        "atr": atr,
        "ema_fast": close.ewm(span=21, adjust=False, min_periods=21).mean(),
        "ema_slow": close.ewm(span=55, adjust=False, min_periods=55).mean(),
        "anchor": close.rolling(96, min_periods=96).mean(),
    }


def entry_filter_pass(lane_id: str, arm_id: str, signal: dict[str, Any], frame: pd.DataFrame, indicators: dict[str, pd.Series]) -> bool:
    if arm_id != "entry_short_beam_only":
        return True
    index = int(signal["signal_bar_index"])
    if index < 1 or index >= len(frame):
        return False
    row = frame.iloc[index]
    previous = frame.iloc[index - 1]
    price = float(row["close"])
    if lane_id == "strategy:vwap_revert:5m":
        atr = float(indicators["atr"].iloc[index])
        vwap = float(indicators["vwap"].iloc[index])
        rsi_now = float(indicators["rsi"].iloc[index])
        if not all(math.isfinite(value) and value > 0 for value in (price, atr, vwap)) or not math.isfinite(rsi_now):
            return False
        width = max(float(row["high"]) - float(row["low"]), 1e-9)
        body_ratio = abs(price - float(row["open"])) / width
        reclaim_atr = abs(price - float(row["open"])) / max(atr, 1e-9)
        close_location = (price - float(row["low"])) / width
        extension_atr = (price - vwap) / max(atr, 1e-9)
        return bool(
            price > vwap + 2.0 * atr
            and extension_atr >= 1.65
            and rsi_now > 66.0
            and body_ratio >= 0.45
            and reclaim_atr >= 0.25
            and (1.0 - close_location) >= 0.55
        )
    atr = float(indicators["atr"].iloc[index])
    anchor = float(indicators["anchor"].iloc[index])
    ema_fast = float(indicators["ema_fast"].iloc[index])
    ema_slow = float(indicators["ema_slow"].iloc[index])
    if not all(math.isfinite(value) and value > 0 for value in (price, atr, anchor, ema_fast, ema_slow)):
        return False
    grid_step = max(price * 0.003, atr * 0.55)
    k = (price - anchor) / max(grid_step, 1e-9)
    short_reclaim = price < float(previous["close"]) - atr * 0.10
    trend_long = price > ema_fast > ema_slow
    return bool(k >= 1.80 and short_reclaim and not trend_long)


def resolve_levels(
    lane_id: str,
    arm_id: str,
    signal: dict[str, Any],
    frame: pd.DataFrame,
    indicators: dict[str, pd.Series],
    entry_index: int,
) -> tuple[float, float] | None:
    signal_index = int(signal["signal_bar_index"])
    entry = float(frame.iloc[entry_index]["open"])
    declared_sl = signal.get("declared_sl")
    declared_tp = signal.get("declared_tp")
    sl = float(declared_sl) if isinstance(declared_sl, (int, float)) else float("nan")
    tp = float(declared_tp) if isinstance(declared_tp, (int, float)) else float("nan")
    if arm_id == "stop_atr_075":
        atr = float(indicators["atr"].iloc[signal_index])
        sl = max(float(frame.iloc[signal_index]["high"]), entry + 0.75 * atr)
    elif arm_id == "exit_full_vwap":
        tp = float(indicators["vwap"].iloc[signal_index])
    elif arm_id == "stop_grid_075":
        atr = float(indicators["atr"].iloc[signal_index])
        signal_price = float(frame.iloc[signal_index]["close"])
        grid_step = max(signal_price * 0.003, atr * 0.55)
        sl = entry + 0.75 * grid_step
    elif arm_id == "exit_anchor_mean":
        tp = float(indicators["anchor"].iloc[signal_index])
    if not (math.isfinite(sl) and math.isfinite(tp) and sl > entry > tp > 0):
        return None
    return sl, tp


def simulate_trade(
    frame: pd.DataFrame,
    measurement: pd.Series,
    signal: dict[str, Any],
    lane_id: str,
    arm_id: str,
    indicators: dict[str, pd.Series],
    cost: dict[str, Any],
    perturbation: dict[str, Any],
) -> dict[str, Any] | None:
    signal_index = int(signal["signal_bar_index"])
    if not entry_filter_pass(lane_id, arm_id, signal, frame, indicators):
        return None
    entry_delay = int(cost.get("latency_bars") or 0) + int(perturbation.get("additional_entry_delay_bars") or 0)
    exit_delay = int(cost.get("latency_bars") or 0) + int(perturbation.get("additional_exit_delay_bars") or 0)
    entry_index = int(signal["entry_bar_index"]) + entry_delay
    measured_indices = [int(value) for value in measurement[measurement].index]
    if not measured_indices:
        return None
    last_index = measured_indices[-1]
    if entry_index > last_index or entry_index >= len(frame) or not bool(measurement.iloc[entry_index]):
        return None
    levels = resolve_levels(lane_id, arm_id, signal, frame, indicators, entry_index)
    if levels is None:
        return None
    sl, tp = levels
    entry = float(frame.iloc[entry_index]["open"])
    risk_pct = (sl - entry) / entry * 100.0
    if risk_pct <= 0:
        return None
    trigger = "segment_end"
    trigger_index = last_index
    reference_exit = float(frame.iloc[last_index]["close"])
    for index in range(entry_index, last_index + 1):
        high = float(frame.iloc[index]["high"])
        low = float(frame.iloc[index]["low"])
        stop_hit = high >= sl
        tp_hit = low <= tp
        if stop_hit:
            trigger = "stop"
            trigger_index = index
            reference_exit = sl
            break
        if tp_hit:
            trigger = "take_profit"
            trigger_index = index
            reference_exit = tp
            break
    execution_index = min(trigger_index + exit_delay, last_index)
    exit_price = reference_exit if exit_delay == 0 and trigger != "segment_end" else (
        float(frame.iloc[execution_index]["open"]) if trigger != "segment_end" else float(frame.iloc[execution_index]["close"])
    )
    gross_pct = (entry - exit_price) / entry * 100.0
    round_trip_pct = 2.0 * (float(cost.get("fee_bps_per_side") or 0.0) + float(cost.get("slippage_bps_per_side") or 0.0)) / 100.0
    bar_minutes = 1 if lane_id.endswith(":1m") else 5
    holding_hours = max(execution_index - entry_index, 0) * bar_minutes / 60.0
    funding_pct = float(cost.get("funding_bps_per_8h") or 0.0) / 100.0 * holding_hours / 8.0
    net_pct = gross_pct - round_trip_pct - funding_pct
    net_r = net_pct / risk_pct
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
        "net_r": net_r,
        "exit_reason": trigger,
        "holding_bars": max(execution_index - entry_index, 0),
    }


def aggregate_trades(trades: list[dict[str, Any]]) -> dict[str, Any]:
    net_r = [float(row["net_r"]) for row in trades]
    net_pct = [float(row["net_return_pct"]) for row in trades]
    wins = [value for value in net_r if value > 0]
    losses = [value for value in net_r if value < 0]
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for value in net_pct:
        cumulative += value
        peak = max(peak, cumulative)
        max_dd = max(max_dd, peak - cumulative)
    profit_factor = sum(wins) / abs(sum(losses)) if losses else (float("inf") if wins else 0.0)
    payoff = statistics.mean(wins) / abs(statistics.mean(losses)) if wins and losses else (float("inf") if wins else 0.0)
    return {
        "trade_count": len(trades),
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate_pct": len(wins) / len(trades) * 100.0 if trades else 0.0,
        "profit_factor": profit_factor,
        "expectancy_r": statistics.mean(net_r) if net_r else 0.0,
        "net_r_sum": sum(net_r),
        "net_pnl_sum_pct": sum(net_pct),
        "max_drawdown_pct": max_dd,
        "payoff_ratio": payoff,
        "median_risk_pct": statistics.median(float(row["risk_pct"]) for row in trades) if trades else None,
        "median_holding_bars": statistics.median(int(row["holding_bars"]) for row in trades) if trades else None,
        "exit_histogram": dict(sorted(Counter(str(row["exit_reason"]) for row in trades).items())),
        "symbol_histogram": dict(sorted(Counter(str(row["symbol"]) for row in trades).items())),
        "regime_histogram": dict(sorted(Counter(str(row["regime"]) for row in trades).items())),
    }


def finite_metric(value: Any, default: float = -1e100) -> float:
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    if value == float("inf"):
        return 1e100
    return default


def economic_pass(metrics: dict[str, Any]) -> bool:
    return bool(
        int(metrics.get("trade_count") or 0) >= MIN_DISCOVERY_TRADES
        and finite_metric(metrics.get("expectancy_r")) > 0
        and finite_metric(metrics.get("net_pnl_sum_pct")) > 0
        and finite_metric(metrics.get("profit_factor")) > 1.0
    )


def pareto_improves(candidate: dict[str, Any], baseline: dict[str, Any]) -> bool:
    comparisons = [
        finite_metric(candidate.get("expectancy_r")) >= finite_metric(baseline.get("expectancy_r")),
        finite_metric(candidate.get("net_pnl_sum_pct")) >= finite_metric(baseline.get("net_pnl_sum_pct")),
        finite_metric(candidate.get("profit_factor")) >= finite_metric(baseline.get("profit_factor")),
        finite_metric(candidate.get("max_drawdown_pct"), 1e100) <= finite_metric(baseline.get("max_drawdown_pct"), 1e100),
    ]
    strict = [
        finite_metric(candidate.get("expectancy_r")) > finite_metric(baseline.get("expectancy_r")),
        finite_metric(candidate.get("net_pnl_sum_pct")) > finite_metric(baseline.get("net_pnl_sum_pct")),
        finite_metric(candidate.get("profit_factor")) > finite_metric(baseline.get("profit_factor")),
        finite_metric(candidate.get("max_drawdown_pct"), 1e100) < finite_metric(baseline.get("max_drawdown_pct"), 1e100),
    ]
    return all(comparisons) and any(strict)


def self_test() -> int:
    metrics = aggregate_trades([
        {"net_r": 1.0, "net_return_pct": 0.5, "risk_pct": 0.5, "holding_bars": 2, "exit_reason": "take_profit", "symbol": "A", "regime": "range"},
        {"net_r": -0.5, "net_return_pct": -0.25, "risk_pct": 0.5, "holding_bars": 1, "exit_reason": "stop", "symbol": "A", "regime": "range"},
    ])
    assert metrics["trade_count"] == 2
    assert abs(float(metrics["profit_factor"]) - 2.0) < 1e-9
    assert abs(float(metrics["expectancy_r"]) - 0.25) < 1e-9
    print("STATE=PASS_SHORT_SURVIVOR_CONTROLLED_UPGRADE_DISCOVERY_SELF_TEST")
    print("RC=0")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--target-sha", default="UNKNOWN")
    parser.add_argument("--raw-module", required=False)
    parser.add_argument("--a4d-contract", required=False)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.raw_module or not args.a4d_contract:
        raise SystemExit("--raw-module and --a4d-contract required")

    root = Path(args.root).resolve()
    raw = import_module(Path(args.raw_module).resolve(), "r7a4d2_raw_geometry_dependency")
    required = [
        root / DIAG_PATH,
        root / PLAN_PATH,
        root / EXEC_DIR / "aggregate_v1.json",
        root / EXEC_DIR / "proof_v1.json",
        root / EXEC_DIR / "scan_results_v1.jsonl",
        root / EXEC_DIR / "signal_geometry_v1.jsonl",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        print("STATE=HOLD_SHORT_SURVIVOR_CONTROLLED_UPGRADE_DISCOVERY_INPUT")
        print("BLOCKER_COUNT=1")
        print("BLOCKERS=" + json.dumps(["REQUIRED_EVIDENCE_MISSING:" + ",".join(missing)]))
        print("RC=2")
        return 2

    diagnose = load_json(root / DIAG_PATH)
    plan = load_json(root / PLAN_PATH)
    aggregate = load_json(root / EXEC_DIR / "aggregate_v1.json")
    proof = load_json(root / EXEC_DIR / "proof_v1.json")
    contract = load_json(Path(args.a4d_contract).resolve())
    geometry_path = root / EXEC_DIR / "signal_geometry_v1.jsonl"
    scans_path = root / EXEC_DIR / "scan_results_v1.jsonl"
    blockers: list[str] = []
    if diagnose.get("state") != "PASS_SHORT_RAW_GEOMETRY_MUTATION_AND_LANE_ECONOMIC_DIAGNOSE" or diagnose.get("result_reusable") is not True:
        blockers.append("DIAGNOSE_NOT_REUSABLE")
    if sha256_file(geometry_path) != str(aggregate.get("signal_geometry_sha256") or ""):
        blockers.append("GEOMETRY_SHA_MISMATCH")
    if sha256_file(scans_path) != str(aggregate.get("scan_results_sha256") or ""):
        blockers.append("SCAN_SHA_MISMATCH")
    if str(proof.get("signal_geometry_sha256") or "") != str(aggregate.get("signal_geometry_sha256") or ""):
        blockers.append("PROOF_GEOMETRY_SHA_MISMATCH")
    dominant = {
        str(row.get("strategy_lane_id"))
        for row in diagnose.get("lane_comparisons", [])
        if isinstance(row, dict) and row.get("classification") == "PARETO_DOMINATES_BENCHMARK"
    }
    if dominant != set(EXPECTED_SURVIVORS):
        blockers.append("SURVIVOR_SET_INVALID:" + json.dumps(sorted(dominant)))
    if len(contract.get("cost_profiles", [])) != 3 or len(contract.get("perturbations", [])) != 2:
        blockers.append("STRESS_CONTRACT_INVALID")
    data_contract = plan.get("data_contract") if isinstance(plan.get("data_contract"), dict) else {}
    manifest_path = root / safe_repo_path(str(data_contract.get("selected_manifest_path") or ""))
    if not manifest_path.is_file():
        blockers.append("SELECTED_MANIFEST_MISSING")
    if blockers:
        print("STATE=HOLD_SHORT_SURVIVOR_CONTROLLED_UPGRADE_DISCOVERY_INPUT")
        print("BLOCKER_COUNT=" + str(len(blockers)))
        print("BLOCKERS=" + json.dumps(blockers, ensure_ascii=False))
        print("RC=2")
        return 2

    manifest = load_json(manifest_path)
    segments = {
        str(row["segment_id"]): row
        for row in manifest.get("selected_segments", [])
        if isinstance(row, dict) and int(row.get("fold", 99)) < 3
    }
    if len(segments) != 12:
        blockers.append(f"DISCOVERY_SEGMENT_COUNT_INVALID:{len(segments)}")
    strategy_lanes = {
        str(row["lane_id"]): row
        for row in plan.get("strategy_lanes", [])
        if isinstance(row, dict)
    }
    for lane_id, expected in EXPECTED_SURVIVORS.items():
        lane = strategy_lanes.get(lane_id)
        if lane is None or any(str(lane.get(key)) != value for key, value in expected.items()):
            blockers.append(f"SURVIVOR_LANE_CONTRACT_INVALID:{lane_id}")

    geometry_rows = [
        row for row in load_jsonl(geometry_path)
        if str(row.get("lane_id")) in EXPECTED_SURVIVORS and str(row.get("segment_id")) in segments
    ]
    unique_signals: dict[tuple[str, str, int, str], dict[str, Any]] = {}
    for row in geometry_rows:
        key = (
            str(row["lane_id"]),
            str(row["segment_id"]),
            int(row["signal_bar_index"]),
            str(row.get("parameter_id") or "canonical"),
        )
        unique_signals.setdefault(key, row)
    signals_by_lane_segment: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in unique_signals.values():
        signals_by_lane_segment[(str(row["lane_id"]), str(row["segment_id"]))].append(row)
    if any(not any(key[0] == lane_id for key in signals_by_lane_segment) for lane_id in EXPECTED_SURVIVORS):
        blockers.append("SURVIVOR_SIGNAL_EVIDENCE_MISSING")
    if blockers:
        print("STATE=HOLD_SHORT_SURVIVOR_CONTROLLED_UPGRADE_DISCOVERY_INPUT")
        print("BLOCKER_COUNT=" + str(len(blockers)))
        print("BLOCKERS=" + json.dumps(blockers, ensure_ascii=False))
        print("RC=2")
        return 2

    canonical_paths = [manifest_path, geometry_path, scans_path, root / DIAG_PATH, root / PLAN_PATH]
    for lane_id in EXPECTED_SURVIVORS:
        implementation = root / safe_repo_path(str(strategy_lanes[lane_id]["implementation_path"]))
        canonical_paths.append(implementation)
    protected_paths = [Path(str(value)) for value in contract.get("protected_paths", [])]
    before = snapshot(canonical_paths + protected_paths)

    source_sha_by_path = {
        str(row.get("source_path")): str(row.get("source_sha256") or "")
        for row in manifest.get("selected_segments", []) if isinstance(row, dict)
    }
    source_cache: dict[str, pd.DataFrame] = {}
    frame_cache: dict[tuple[str, str], pd.DataFrame] = {}
    indicator_cache: dict[tuple[str, str], dict[str, pd.Series]] = {}
    cost_profiles = [row for row in contract.get("cost_profiles", []) if isinstance(row, dict)]
    perturbations = [row for row in contract.get("perturbations", []) if isinstance(row, dict)]
    trade_rows: list[dict[str, Any]] = []
    cell_rows: list[dict[str, Any]] = []

    for lane_id in sorted(EXPECTED_SURVIVORS):
        lane = strategy_lanes[lane_id]
        for segment_id, segment in sorted(segments.items()):
            source_path = str(segment["source_path"])
            if source_path not in source_cache:
                source_cache[source_path] = raw.fixed_ohlcv_frame(
                    root / safe_repo_path(source_path), source_sha_by_path[source_path]
                )
            frame_key = (lane_id, segment_id)
            frame = raw.resample_for_segment(
                source_cache[source_path], int(segment["start_row"]), int(segment["end_row_exclusive"]), str(lane["timeframe"])
            )
            frame_cache[frame_key] = frame
            indicator_cache[frame_key] = indicator_bundle(lane_id, frame)

        for arm in arm_definitions(lane_id):
            for cost in cost_profiles:
                for perturbation in perturbations:
                    cell_trades: list[dict[str, Any]] = []
                    for segment_id, segment in sorted(segments.items()):
                        frame = frame_cache[(lane_id, segment_id)]
                        indicators = indicator_cache[(lane_id, segment_id)]
                        measurement = raw.measurement_mask(frame, int(segment["start_row"]), int(segment["end_row_exclusive"]))
                        last_exit_index = -1
                        for signal in sorted(signals_by_lane_segment.get((lane_id, segment_id), []), key=lambda row: int(row["entry_bar_index"])):
                            if int(signal["entry_bar_index"]) <= last_exit_index:
                                continue
                            trade = simulate_trade(frame, measurement, signal, lane_id, str(arm["arm_id"]), indicators, cost, perturbation)
                            if trade is None:
                                continue
                            last_exit_index = int(trade["exit_index"])
                            trade.update({
                                "lane_id": lane_id,
                                "strategy_id": lane["strategy_id"],
                                "family": lane["family"],
                                "timeframe": lane["timeframe"],
                                "arm_id": arm["arm_id"],
                                "arm_axis": arm["axis"],
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
                    metrics = aggregate_trades(cell_trades)
                    cell_rows.append({
                        "lane_id": lane_id,
                        "strategy_id": lane["strategy_id"],
                        "family": lane["family"],
                        "timeframe": lane["timeframe"],
                        "arm_id": arm["arm_id"],
                        "arm_axis": arm["axis"],
                        "cost_profile_id": cost["id"],
                        "perturbation_id": perturbation["id"],
                        **metrics,
                    })

    cell_map = {
        (str(row["lane_id"]), str(row["arm_id"]), str(row["cost_profile_id"]), str(row["perturbation_id"])): row
        for row in cell_rows
    }
    lock_rows: list[dict[str, Any]] = []
    for lane_id in sorted(EXPECTED_SURVIVORS):
        baseline = cell_map[(lane_id, "baseline_canonical", *SEVERE_CELL)]
        candidates = [
            cell_map[(lane_id, str(arm["arm_id"]), *SEVERE_CELL)]
            for arm in arm_definitions(lane_id) if arm["arm_id"] != "baseline_canonical"
        ]
        eligible = [row for row in candidates if economic_pass(row) and pareto_improves(row, baseline)]
        eligible.sort(
            key=lambda row: (
                finite_metric(row.get("expectancy_r")),
                finite_metric(row.get("profit_factor")),
                finite_metric(row.get("net_pnl_sum_pct")),
                -finite_metric(row.get("max_drawdown_pct"), 1e100),
            ),
            reverse=True,
        )
        if eligible:
            selected = eligible[0]
            status = "UPGRADE_ARM_LOCKED"
        elif economic_pass(baseline):
            selected = baseline
            status = "BASELINE_RETAINS_POSITIVE"
        else:
            selected = None
            status = "NO_ECONOMIC_SURVIVOR"
        lock_rows.append({
            "lane_id": lane_id,
            "strategy_id": EXPECTED_SURVIVORS[lane_id]["strategy_id"],
            "baseline_severe_timing_metrics": baseline,
            "eligible_upgrade_arm_count": len(eligible),
            "selected_arm_id": selected.get("arm_id") if selected else None,
            "selected_arm_axis": selected.get("arm_axis") if selected else None,
            "selected_metrics": selected,
            "lock_status": status,
            "validation_allowed": selected is not None,
        })

    after = snapshot(canonical_paths + protected_paths)
    mutation_paths = sorted(path for path in before if before[path] != after[path])
    mutation_rows = [{"path": path, "classification": classify_mutation(path, root)} for path in mutation_paths]
    critical_mutations = [row for row in mutation_rows if row["classification"] != "EXTERNAL_OPERATIONAL_VOLATILE_MUTATION"]
    output = root / OUTPUT_DIR
    trade_count, trade_sha = atomic_jsonl(output / "trade_results_v1.jsonl", trade_rows)
    cell_count, cell_sha = atomic_jsonl(output / "arm_cell_results_v1.jsonl", cell_rows)
    economic_survivors = [row for row in lock_rows if row["validation_allowed"]]
    technical_blockers = []
    if critical_mutations:
        technical_blockers.append(f"CRITICAL_MUTATIONS:{len(critical_mutations)}")
    state = "PASS_SHORT_SURVIVOR_CONTROLLED_UPGRADE_DISCOVERY" if not technical_blockers else "HOLD_SHORT_SURVIVOR_CONTROLLED_UPGRADE_DISCOVERY"
    next_stage = (
        "R7.A4D2_SHORT_SURVIVOR_LOCKED_VALIDATION_EXECUTION"
        if not technical_blockers and economic_survivors
        else "R7.A4D2_SHORT_SURVIVOR_ARCHITECTURE_REPAIR_OR_RETIRE"
    )
    report = {
        "schema": "r7a4d2_short_survivor_controlled_upgrade_discovery_v1",
        "official_stage": "R7.A4D2_SHORT_SURVIVOR_CONTROLLED_UPGRADE_DISCOVERY",
        "state": state,
        "target_commit": args.target_sha,
        "blockers": technical_blockers,
        "survivor_lane_count": len(EXPECTED_SURVIVORS),
        "arm_count_per_lane": 4,
        "discovery_segment_count": len(segments),
        "stress_cell_count": len(cost_profiles) * len(perturbations),
        "trade_result_count": trade_count,
        "arm_cell_result_count": cell_count,
        "trade_results_sha256": trade_sha,
        "arm_cell_results_sha256": cell_sha,
        "minimum_discovery_trade_count": MIN_DISCOVERY_TRADES,
        "selection_policy": "SEVERE_COST_PLUS_TIMING_POSITIVE_ECONOMICS_AND_PARETO_IMPROVEMENT_OVER_FROZEN_BASELINE",
        "lock_rows": lock_rows,
        "economic_survivor_count": len(economic_survivors),
        "mutation_rows": mutation_rows,
        "next_stage": next_stage,
    }
    atomic_json(output / "discovery_lock_v1.json", report)
    print("STATE=" + state)
    print("BLOCKER_COUNT=" + str(len(technical_blockers)))
    print("SURVIVOR_LANE_COUNT=" + str(len(EXPECTED_SURVIVORS)))
    print("ARM_COUNT_PER_LANE=4")
    print("DISCOVERY_SEGMENT_COUNT=" + str(len(segments)))
    print("STRESS_CELL_COUNT=" + str(len(cost_profiles) * len(perturbations)))
    print("TRADE_RESULT_COUNT=" + str(trade_count))
    print("ARM_CELL_RESULT_COUNT=" + str(cell_count))
    print("ECONOMIC_SURVIVOR_COUNT=" + str(len(economic_survivors)))
    print("LOCK_ROWS=" + json.dumps(lock_rows, ensure_ascii=False, sort_keys=True))
    print("MUTATION_ROWS=" + json.dumps(mutation_rows, ensure_ascii=False, sort_keys=True))
    print("DISCOVERY_LOCK_JSON=" + str(output / "discovery_lock_v1.json"))
    print("NEXT_STAGE=" + next_stage)
    print("BLOCKERS=" + json.dumps(technical_blockers, ensure_ascii=False))
    print("RC=" + ("0" if not technical_blockers else "2"))
    return 0 if not technical_blockers else 2


if __name__ == "__main__":
    raise SystemExit(main())
