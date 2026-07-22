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
from typing import Any, Iterable

import numpy as np
import pandas as pd

PLAN_PATH = Path("runtime/r7a4d2_short_macro_alpha_reset_plan/macro_alpha_reset_plan_v1.json")
MANIFEST_PATH = Path("runtime/r7a4c_historical_simulation_input_lineage/selected_input_manifest_v1.json")
OUTPUT_DIR = Path("runtime/r7a4d2_short_simple_benchmark_baseline_execution_60_and_data_coverage_audit")
EXPECTED_BENCHMARKS = 5
EXPECTED_LANES = 10
EXPECTED_SEGMENTS = 24
EXPECTED_STRESS_PER_LANE = 6
EXPECTED_CELLS = 60
SEVERE_CELL = ("cost_profile_2", "perturbation_1")

BENCHMARK_PARAMETERS = {
    "benchmark_ma_cross_short": {
        "fast_ema": 12, "slow_ema": 26, "atr_period": 14,
        "stop_atr": 1.50, "target_atr": 2.00, "max_hold_bars": 48,
    },
    "benchmark_donchian_breakout_short": {
        "lookback": 20, "atr_period": 14,
        "stop_atr": 1.25, "target_atr": 2.00, "max_hold_bars": 36,
    },
    "benchmark_atr_volatility_breakout_short": {
        "atr_period": 14, "range_atr_min": 1.25, "volume_z_min": 0.50,
        "stop_atr": 1.25, "target_atr": 2.50, "max_hold_bars": 30,
    },
    "benchmark_vwap_mean_reversion_short": {
        "lookback": 20, "entry_std": 1.25,
        "stop_atr": 0.75, "max_hold_bars": 18,
    },
    "benchmark_single_cycle_grid_short": {
        "lookback": 30, "upper_quantile": 0.75,
        "stop_atr": 0.50, "max_hold_bars": 30,
    },
}

FEATURE_ALIASES = {
    "funding": ("funding", "funding_rate", "fundingrate"),
    "open_interest": ("open_interest", "openinterest", "oi_history"),
    "basis": ("basis", "premium_index", "premiumindex", "mark_index_spread"),
    "trade_flow": ("trade_flow", "aggtrade", "agg_trade", "taker_buy", "buy_sell_volume"),
    "order_book_imbalance": ("order_book", "orderbook", "depth", "book_imbalance", "bid_ask_imbalance"),
    "liquidation_flow": ("liquidation", "force_order", "forced_order", "liq_flow"),
    "btc_lead_lag": ("lead_lag", "btc_lead", "cross_asset", "market_breadth"),
}


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


def finite(value: Any, default: float = 0.0) -> float:
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    if value == float("inf"):
        return 1e100
    return default


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.astype(float).ewm(span=span, adjust=False, min_periods=span).mean()


def atr(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    close = frame["close"].astype(float)
    previous = close.shift(1)
    true_range = pd.concat([(high - low), (high - previous).abs(), (low - previous).abs()], axis=1).max(axis=1)
    return true_range.rolling(period, min_periods=period).mean()


def rolling_vwap(frame: pd.DataFrame, lookback: int = 20) -> pd.Series:
    volume = frame["volume"].astype(float)
    typical = (frame["high"].astype(float) + frame["low"].astype(float) + frame["close"].astype(float)) / 3.0
    weighted = (typical * volume).rolling(lookback, min_periods=lookback).sum()
    volume_sum = volume.rolling(lookback, min_periods=lookback).sum()
    fallback = typical.rolling(lookback, min_periods=lookback).mean()
    return weighted.div(volume_sum.where(volume_sum > 0)).fillna(fallback)


def edge_trigger(condition: pd.Series) -> pd.Series:
    clean = condition.fillna(False).astype(bool)
    return clean & ~clean.shift(1, fill_value=False)


def next_true_distance(condition: pd.Series, start: int, maximum: int) -> int:
    upper = min(len(condition), start + maximum + 1)
    for index in range(start + 1, upper):
        if bool(condition.iloc[index]):
            return max(2, index - start)
    return maximum


def generate_signals(benchmark_id: str, frame: pd.DataFrame, measurement: pd.Series) -> list[dict[str, Any]]:
    params = BENCHMARK_PARAMETERS[benchmark_id]
    close = frame["close"].astype(float)
    open_v = frame["open"].astype(float)
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    volume = frame["volume"].astype(float)
    atr14 = atr(frame, int(params.get("atr_period", 14)))
    signals: list[dict[str, Any]] = []

    def append(index: int, stop: float, target: float, timeout: int, reason: str) -> None:
        if index + 1 >= len(frame):
            return
        if not bool(measurement.iloc[index]) or not bool(measurement.iloc[index + 1]):
            return
        reference_entry = float(frame.iloc[index + 1]["open"])
        if not all(math.isfinite(value) for value in (reference_entry, stop, target)):
            return
        if not stop > reference_entry > target > 0:
            return
        signals.append({
            "signal_bar_index": int(index), "entry_bar_index": int(index + 1),
            "stop_price": float(stop), "target_price": float(target),
            "partial_price": None, "timeout_bars": int(max(2, timeout)), "reason": reason,
        })

    if benchmark_id == "benchmark_ma_cross_short":
        fast = ema(close, int(params["fast_ema"]))
        slow = ema(close, int(params["slow_ema"]))
        down_cross = (fast < slow) & (fast.shift(1) >= slow.shift(1)) & (close < slow)
        up_cross = (fast > slow) & (fast.shift(1) <= slow.shift(1))
        for index in np.flatnonzero(edge_trigger(down_cross).to_numpy(dtype=bool)):
            i = int(index); a = finite(atr14.iloc[i], math.nan)
            append(i, max(float(high.iloc[i]), float(close.iloc[i]) + float(params["stop_atr"]) * a),
                   float(close.iloc[i]) - float(params["target_atr"]) * a,
                   next_true_distance(up_cross, i, int(params["max_hold_bars"])), "ema_12_26_down_cross")

    elif benchmark_id == "benchmark_donchian_breakout_short":
        lookback = int(params["lookback"])
        prior_low = low.shift(1).rolling(lookback, min_periods=lookback).min()
        prior_high = high.shift(1).rolling(lookback, min_periods=lookback).max()
        midpoint = (prior_high + prior_low) / 2.0
        breakdown = close < prior_low
        reclaim = close > midpoint
        for index in np.flatnonzero(edge_trigger(breakdown).to_numpy(dtype=bool)):
            i = int(index); a = finite(atr14.iloc[i], math.nan)
            append(i, float(close.iloc[i]) + float(params["stop_atr"]) * a,
                   float(close.iloc[i]) - float(params["target_atr"]) * a,
                   next_true_distance(reclaim, i, int(params["max_hold_bars"])), "donchian_20_down_break")

    elif benchmark_id == "benchmark_atr_volatility_breakout_short":
        bar_range = high - low
        vol_mean = volume.rolling(20, min_periods=20).mean()
        vol_std = volume.rolling(20, min_periods=20).std(ddof=0).replace(0, np.nan)
        volume_z = (volume - vol_mean).div(vol_std)
        breakdown = ((close < open_v) & (bar_range >= float(params["range_atr_min"]) * atr14)
                     & (volume_z >= float(params["volume_z_min"]))
                     & (close <= low.shift(1).rolling(10, min_periods=10).min()))
        for index in np.flatnonzero(edge_trigger(breakdown).to_numpy(dtype=bool)):
            i = int(index); a = finite(atr14.iloc[i], math.nan)
            append(i, max(float(high.iloc[i]), float(close.iloc[i]) + float(params["stop_atr"]) * a),
                   float(close.iloc[i]) - float(params["target_atr"]) * a,
                   int(params["max_hold_bars"]), "atr_volume_down_break")

    elif benchmark_id == "benchmark_vwap_mean_reversion_short":
        lookback = int(params["lookback"])
        vwap = rolling_vwap(frame, lookback)
        deviation = close - vwap
        std = deviation.rolling(lookback, min_periods=lookback).std(ddof=0)
        upper = vwap + float(params["entry_std"]) * std
        reclaim = (high > upper) & (close < upper) & (close < open_v)
        for index in np.flatnonzero(edge_trigger(reclaim).to_numpy(dtype=bool)):
            i = int(index); a = finite(atr14.iloc[i], math.nan)
            append(i, max(float(high.iloc[i]), float(close.iloc[i]) + float(params["stop_atr"]) * a),
                   finite(vwap.iloc[i], math.nan), int(params["max_hold_bars"]),
                   "vwap_upper_excursion_close_inside")

    elif benchmark_id == "benchmark_single_cycle_grid_short":
        lookback = int(params["lookback"])
        range_high = high.shift(1).rolling(lookback, min_periods=lookback).max()
        range_low = low.shift(1).rolling(lookback, min_periods=lookback).min()
        width = range_high - range_low
        upper_quartile = range_low + float(params["upper_quantile"]) * width
        midpoint = (range_high + range_low) / 2.0
        stable = width.between(2.0 * atr14, 8.0 * atr14)
        entry = stable & (high >= upper_quartile) & (close < open_v) & (close < upper_quartile)
        for index in np.flatnonzero(edge_trigger(entry).to_numpy(dtype=bool)):
            i = int(index); a = finite(atr14.iloc[i], math.nan)
            append(i, max(float(range_high.iloc[i]) + float(params["stop_atr"]) * a,
                          float(high.iloc[i]) + 0.1 * a),
                   finite(midpoint.iloc[i], math.nan), int(params["max_hold_bars"]),
                   "single_cycle_upper_quartile_grid")
    else:
        raise ValueError(f"BENCHMARK_UNSUPPORTED:{benchmark_id}")
    return signals


def simulate_trade(frame: pd.DataFrame, measurement: pd.Series, signal: dict[str, Any],
                   cost: dict[str, Any], perturbation: dict[str, Any], timeframe: str) -> dict[str, Any] | None:
    entry_delay = int(cost.get("latency_bars") or 0) + int(perturbation.get("additional_entry_delay_bars") or 0)
    exit_delay = int(cost.get("latency_bars") or 0) + int(perturbation.get("additional_exit_delay_bars") or 0)
    entry_index = int(signal["entry_bar_index"]) + entry_delay
    measured_indices = np.flatnonzero(measurement.to_numpy(dtype=bool))
    if measured_indices.size == 0:
        return None
    last_index = int(measured_indices[-1])
    if entry_index >= len(frame) or entry_index > last_index or not bool(measurement.iloc[entry_index]):
        return None
    entry = float(frame.iloc[entry_index]["open"])
    stop = float(signal["stop_price"]); target = float(signal["target_price"])
    if not stop > entry > target > 0:
        return None
    risk_pct = (stop - entry) / entry * 100.0
    if risk_pct <= 0:
        return None
    timeout_index = min(entry_index + int(signal["timeout_bars"]), last_index)
    trigger = "segment_end"; trigger_index = last_index
    reference_exit = float(frame.iloc[last_index]["close"])
    for index in range(entry_index, last_index + 1):
        high = float(frame.iloc[index]["high"]); low = float(frame.iloc[index]["low"])
        if high >= stop:
            trigger = "stop"; trigger_index = index; reference_exit = stop; break
        if low <= target:
            trigger = "take_profit"; trigger_index = index; reference_exit = target; break
        if index >= timeout_index:
            trigger = "rule_exit_or_timeout"; trigger_index = index
            reference_exit = float(frame.iloc[index]["close"]); break
    execution_index = min(trigger_index + exit_delay, last_index)
    if exit_delay == 0 and trigger in {"stop", "take_profit"}:
        exit_price = reference_exit
    elif trigger == "segment_end":
        exit_price = float(frame.iloc[execution_index]["close"])
    else:
        exit_price = float(frame.iloc[execution_index]["open"])
    gross_pct = (entry - exit_price) / entry * 100.0
    round_trip_pct = 2.0 * (float(cost.get("fee_bps_per_side") or 0.0)
                            + float(cost.get("slippage_bps_per_side") or 0.0)) / 100.0
    minutes = {"5m": 5, "15m": 15}[timeframe]
    holding_hours = max(execution_index - entry_index, 0) * minutes / 60.0
    funding_pct = float(cost.get("funding_bps_per_8h") or 0.0) / 100.0 * holding_hours / 8.0
    net_pct = gross_pct - round_trip_pct - funding_pct
    return {
        "entry_index": entry_index, "exit_index": execution_index,
        "entry_price": entry, "exit_price": exit_price,
        "stop_price": stop, "target_price": target, "risk_pct": risk_pct,
        "gross_return_pct": gross_pct, "round_trip_cost_pct": round_trip_pct,
        "funding_cost_pct": funding_pct, "net_return_pct": net_pct,
        "net_r": net_pct / risk_pct, "exit_reason": trigger,
        "holding_bars": max(execution_index - entry_index, 0),
    }


def economic_pass(helper: Any, metrics: dict[str, Any]) -> bool:
    return bool(int(metrics.get("trade_count") or 0) >= 20
                and helper.finite_metric(metrics.get("profit_factor")) > 1.0
                and helper.finite_metric(metrics.get("expectancy_r")) > 0.0
                and helper.finite_metric(metrics.get("net_pnl_sum_pct")) > 0.0)


def fold_metrics(helper: Any, trades: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in trades:
        grouped[str(row["fold"])].append(row)
    rows = {fold: helper.aggregate_trades(values) for fold, values in sorted(grouped.items())}
    positive = sum(1 for metrics in rows.values()
                   if helper.finite_metric(metrics.get("net_pnl_sum_pct")) > 0.0)
    return {"rows": rows, "fold_count": len(rows), "positive_fold_count": positive,
            "positive_fold_ratio": positive / len(rows) if rows else 0.0}


def audit_external_features(root: Path, selected_source_paths: list[Path]) -> dict[str, Any]:
    selected_key_hits: dict[str, list[str]] = defaultdict(list)
    selected_rows_widths: dict[str, int] = {}
    selected_timestamp_monotonic = True
    for path in selected_source_paths:
        payload = load_json(path)
        flattened_keys = {str(key).lower() for key in payload.keys()}
        rows = payload.get("rows")
        if isinstance(rows, list) and rows:
            widths = {len(row) for row in rows[:100] if isinstance(row, list)}
            selected_rows_widths[str(path.relative_to(root))] = max(widths) if widths else 0
            if widths and max(widths) > 6:
                flattened_keys.add("extended_rows")
            timestamps = [row[0] for row in rows[:1000] if isinstance(row, list) and row]
            if len(timestamps) > 1:
                selected_timestamp_monotonic &= all(float(timestamps[i]) < float(timestamps[i + 1])
                                                    for i in range(len(timestamps) - 1))
        lower_text = " ".join(sorted(flattened_keys))
        for feature, aliases in FEATURE_ALIASES.items():
            if any(alias in lower_text for alias in aliases):
                selected_key_hits[feature].append(str(path.relative_to(root)))

    candidate_paths: dict[str, list[str]] = defaultdict(list)
    scanned = 0
    skipped_dirs = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache",
                    "dist", "build", "tmp", "logs", "log"}
    scan_roots = [root / name for name in ("data", "runtime", "backend", "replay", "static")
                  if (root / name).exists()]
    for base in scan_roots:
        for directory, dirs, files in os.walk(base):
            dirs[:] = [item for item in dirs if item not in skipped_dirs]
            for name in files:
                scanned += 1
                if scanned > 20000:
                    break
                relative = str((Path(directory) / name).relative_to(root))
                lower = relative.lower()
                for feature, aliases in FEATURE_ALIASES.items():
                    if any(alias in lower for alias in aliases) and len(candidate_paths[feature]) < 20:
                        candidate_paths[feature].append(relative)
            if scanned > 20000:
                break
        if scanned > 20000:
            break

    statuses: dict[str, dict[str, Any]] = {}
    for feature in FEATURE_ALIASES:
        bound = sorted(set(selected_key_hits.get(feature, [])))
        candidates = sorted(set(candidate_paths.get(feature, [])))
        status = "BOUND_TO_SELECTED_SEGMENTS" if bound else (
            "CANDIDATE_FILES_FOUND_UNBOUND" if candidates else "NOT_FOUND")
        statuses[feature] = {"status": status, "selected_source_hits": bound,
                             "candidate_file_count": len(candidates),
                             "candidate_file_samples": candidates[:10]}
    statuses["session_time"] = {
        "status": "DERIVABLE_FROM_OHLCV_TIMESTAMP" if selected_timestamp_monotonic else "TIMESTAMP_AUDIT_FAILED",
        "timezone_policy": "UTC_REQUIRED_BEFORE_BERLIN_DERIVATION",
        "selected_timestamp_monotonic": selected_timestamp_monotonic,
    }
    microstructure_ready = all(statuses[feature]["status"] == "BOUND_TO_SELECTED_SEGMENTS"
                               for feature in ("trade_flow", "order_book_imbalance", "liquidation_flow"))
    return {"filesystem_files_scanned": scanned, "selected_source_row_widths": selected_rows_widths,
            "feature_status": statuses, "microstructure_engine_ready": microstructure_ready,
            "microstructure_engine_status": "READY_FOR_LINEAGED_REBUILD" if microstructure_ready else "DATA_GATED"}


def self_test() -> int:
    size = 300
    close = pd.Series(100.0 - np.arange(size) * 0.02 + np.sin(np.arange(size) / 7.0) * 0.2)
    frame = pd.DataFrame({
        "__timestamp": np.arange(size, dtype=float),
        "open": close.shift(1).fillna(close.iloc[0]),
        "high": pd.concat([close, close.shift(1).fillna(close.iloc[0])], axis=1).max(axis=1) + 0.10,
        "low": pd.concat([close, close.shift(1).fillna(close.iloc[0])], axis=1).min(axis=1) - 0.10,
        "close": close, "volume": 100.0 + np.arange(size) % 17, "symbol": "TEST",
        "__source_index": np.arange(size, dtype=int), "__first_source_index": np.arange(size, dtype=int),
        "__last_source_index": np.arange(size, dtype=int), "__complete_bucket": True, "timeframe": "5m",
    })
    measurement = pd.Series([True] * size)
    for benchmark_id in BENCHMARK_PARAMETERS:
        assert isinstance(generate_signals(benchmark_id, frame, measurement), list)
    synthetic = {"signal_bar_index": 50, "entry_bar_index": 51,
                 "stop_price": float(frame.iloc[51]["open"]) + 1.0,
                 "target_price": float(frame.iloc[51]["open"]) - 1.0,
                 "partial_price": None, "timeout_bars": 10, "reason": "self_test"}
    trade = simulate_trade(frame, measurement, synthetic,
                           {"fee_bps_per_side": 1.0, "slippage_bps_per_side": 1.0,
                            "latency_bars": 0, "funding_bps_per_8h": 0.0},
                           {"additional_entry_delay_bars": 0, "additional_exit_delay_bars": 0}, "5m")
    assert trade is not None and math.isfinite(float(trade["net_r"]))
    print("STATE=PASS_SHORT_SIMPLE_BENCHMARK_BASELINE_EXECUTION_60_AND_DATA_COVERAGE_AUDIT_SELF_TEST")
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
    if not all([args.raw_module, args.helper_module, args.a4d_contract]):
        raise SystemExit("--raw-module --helper-module --a4d-contract required")

    root = Path(args.root).resolve()
    raw = import_module(Path(args.raw_module).resolve(), "r7a4d2_benchmark_raw")
    helper = import_module(Path(args.helper_module).resolve(), "r7a4d2_benchmark_helper")
    contract = load_json(Path(args.a4d_contract).resolve())
    required = [root / PLAN_PATH, root / MANIFEST_PATH]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        print("STATE=HOLD_SHORT_SIMPLE_BENCHMARK_BASELINE_EXECUTION_60_AND_DATA_COVERAGE_AUDIT_INPUT")
        print("BLOCKER_COUNT=1")
        print("BLOCKERS=" + json.dumps(["REQUIRED_EVIDENCE_MISSING:" + ",".join(missing)]))
        print("RC=2")
        return 2

    plan = load_json(root / PLAN_PATH); manifest = load_json(root / MANIFEST_PATH)
    blockers: list[str] = []
    if plan.get("state") != "PASS_SHORT_MACRO_ALPHA_RESET_PLAN":
        blockers.append("MACRO_ALPHA_RESET_PLAN_NOT_PASS")
    benchmarks = [row for row in plan.get("benchmarks", []) if isinstance(row, dict)]
    if len(benchmarks) != EXPECTED_BENCHMARKS:
        blockers.append(f"BENCHMARK_COUNT_INVALID:{len(benchmarks)}")
    lanes = [{"benchmark_id": str(row["benchmark_id"]), "family": str(row["family"]),
              "timeframe": str(timeframe), "lane_id": f"{row['benchmark_id']}:{timeframe}"}
             for row in benchmarks for timeframe in row.get("timeframes", [])]
    if len(lanes) != EXPECTED_LANES:
        blockers.append(f"BENCHMARK_LANE_COUNT_INVALID:{len(lanes)}")
    if {row["benchmark_id"] for row in lanes} != set(BENCHMARK_PARAMETERS):
        blockers.append("BENCHMARK_ID_SET_INVALID")
    segments = {str(row["segment_id"]): row for row in manifest.get("selected_segments", [])
                if isinstance(row, dict)}
    if len(segments) != EXPECTED_SEGMENTS:
        blockers.append(f"SEGMENT_COUNT_INVALID:{len(segments)}")
    costs = [row for row in contract.get("cost_profiles", []) if isinstance(row, dict)]
    perturbations = [row for row in contract.get("perturbations", []) if isinstance(row, dict)]
    if len(costs) * len(perturbations) != EXPECTED_STRESS_PER_LANE:
        blockers.append("STRESS_CELL_COUNT_INVALID")
    if blockers:
        print("STATE=HOLD_SHORT_SIMPLE_BENCHMARK_BASELINE_EXECUTION_60_AND_DATA_COVERAGE_AUDIT_INPUT")
        print("BLOCKER_COUNT=" + str(len(blockers)))
        print("BLOCKERS=" + json.dumps(blockers)); print("RC=2"); return 2

    source_sha = {str(row.get("source_path")): str(row.get("source_sha256") or "")
                  for row in manifest.get("selected_segments", []) if isinstance(row, dict)}
    source_paths = sorted({str(row["source_path"]) for row in segments.values()})
    selected_source_paths = [root / raw.safe_repo_path(path) for path in source_paths]
    canonical_paths = required + selected_source_paths
    protected = [Path(str(value)) for value in contract.get("protected_paths", [])]
    before = helper.snapshot(canonical_paths + protected)

    source_cache: dict[str, pd.DataFrame] = {}
    frame_cache: dict[tuple[str, str], pd.DataFrame] = {}
    mask_cache: dict[tuple[str, str], pd.Series] = {}
    signal_cache: dict[tuple[str, str], list[dict[str, Any]]] = {}
    trade_rows: list[dict[str, Any]] = []
    cell_rows: list[dict[str, Any]] = []

    for lane_number, lane in enumerate(sorted(lanes, key=lambda row: row["lane_id"]), 1):
        benchmark_id = lane["benchmark_id"]; timeframe = lane["timeframe"]
        for segment_id, segment in sorted(segments.items()):
            source_path = str(segment["source_path"])
            if source_path not in source_cache:
                source_cache[source_path] = raw.fixed_ohlcv_frame(
                    root / raw.safe_repo_path(source_path), source_sha[source_path])
            key = (segment_id, timeframe)
            if key not in frame_cache:
                frame_cache[key] = raw.resample_for_segment(source_cache[source_path],
                    int(segment["start_row"]), int(segment["end_row_exclusive"]), timeframe)
                mask_cache[key] = raw.measurement_mask(frame_cache[key],
                    int(segment["start_row"]), int(segment["end_row_exclusive"]))
            signal_cache[(lane["lane_id"], segment_id)] = generate_signals(
                benchmark_id, frame_cache[key], mask_cache[key])

        for cost in costs:
            for perturbation in perturbations:
                cell_trades: list[dict[str, Any]] = []
                for segment_id, segment in sorted(segments.items()):
                    frame = frame_cache[(segment_id, timeframe)]
                    measurement = mask_cache[(segment_id, timeframe)]
                    last_exit = -1
                    for signal in signal_cache[(lane["lane_id"], segment_id)]:
                        if int(signal["entry_bar_index"]) <= last_exit:
                            continue
                        trade = simulate_trade(frame, measurement, signal, cost, perturbation, timeframe)
                        if trade is None:
                            continue
                        last_exit = int(trade["exit_index"])
                        trade.update({"lane_id": lane["lane_id"], "benchmark_id": benchmark_id,
                                      "family": lane["family"], "timeframe": timeframe,
                                      "cost_profile_id": cost["id"], "perturbation_id": perturbation["id"],
                                      "segment_id": segment_id, "fold": int(segment["fold"]),
                                      "regime": str(segment["regime"]),
                                      "symbol": str(frame.iloc[int(signal["signal_bar_index"])].get("symbol") or ""),
                                      "signal_bar_index": int(signal["signal_bar_index"]),
                                      "signal_reason": signal["reason"]})
                        trade_rows.append(trade); cell_trades.append(trade)
                metrics = helper.aggregate_trades(cell_trades)
                cell_rows.append({"lane_id": lane["lane_id"], "benchmark_id": benchmark_id,
                                  "family": lane["family"], "timeframe": timeframe,
                                  "cost_profile_id": cost["id"], "perturbation_id": perturbation["id"],
                                  **metrics, "fold_metrics": fold_metrics(helper, cell_trades)})
        print(f"A4D2_SIMPLE_BENCHMARK_PROGRESS={lane_number}/{EXPECTED_LANES} "
              f"CELLS={len(cell_rows)}/{EXPECTED_CELLS} TRADES={len(trade_rows)}")

    if len(cell_rows) != EXPECTED_CELLS:
        blockers.append(f"BENCHMARK_CELL_COUNT_INVALID:{len(cell_rows)}")
    lane_rows: list[dict[str, Any]] = []
    for lane in sorted(lanes, key=lambda row: row["lane_id"]):
        cells = [row for row in cell_rows if row["lane_id"] == lane["lane_id"]]
        severe = next(row for row in cells
                      if (str(row["cost_profile_id"]), str(row["perturbation_id"])) == SEVERE_CELL)
        positive_cells = sum(1 for row in cells if economic_pass(helper, row))
        lane_rows.append({**lane, "signal_count": sum(len(signal_cache[(lane["lane_id"], segment_id)])
                                                       for segment_id in segments),
                          "positive_stress_cell_count": positive_cells, "severe_metrics": severe,
                          "baseline_economic_pass": economic_pass(helper, severe) and positive_cells >= 4})

    family_best_rows: list[dict[str, Any]] = []
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in lane_rows:
        grouped[str(row["family"])].append(row)
    for family, rows in sorted(grouped.items()):
        rows.sort(key=lambda row: (int(row["baseline_economic_pass"]),
                   helper.finite_metric(row["severe_metrics"].get("expectancy_r")),
                   helper.finite_metric(row["severe_metrics"].get("profit_factor")),
                   helper.finite_metric(row["severe_metrics"].get("net_pnl_sum_pct")),
                   -helper.finite_metric(row["severe_metrics"].get("max_drawdown_pct"), 1e100)), reverse=True)
        family_best_rows.append({"family": family, "selected_lane_id": rows[0]["lane_id"],
                                 "selected_metrics": rows[0]["severe_metrics"],
                                 "selected_baseline_economic_pass": rows[0]["baseline_economic_pass"]})

    coverage = audit_external_features(root, selected_source_paths)
    after = helper.snapshot(canonical_paths + protected)
    mutation_paths = sorted(path for path in before if before[path] != after[path])
    mutation_rows = [{"path": path, "classification": helper.classify_mutation(path, root)}
                     for path in mutation_paths]
    critical_mutations = [row for row in mutation_rows
                          if row["classification"] != "EXTERNAL_OPERATIONAL_VOLATILE_MUTATION"]
    if critical_mutations:
        blockers.append(f"CRITICAL_MUTATIONS:{len(critical_mutations)}")

    output = root / OUTPUT_DIR
    trade_count, trade_sha = atomic_jsonl(output / "benchmark_trade_results_v1.jsonl", trade_rows)
    cell_count, cell_sha = atomic_jsonl(output / "benchmark_cell_results_v1.jsonl", cell_rows)
    pass_lanes = [row for row in lane_rows if row["baseline_economic_pass"]]
    state = ("PASS_SHORT_SIMPLE_BENCHMARK_BASELINE_EXECUTION_60_AND_DATA_COVERAGE_AUDIT"
             if not blockers else "HOLD_SHORT_SIMPLE_BENCHMARK_BASELINE_EXECUTION_60_AND_DATA_COVERAGE_AUDIT")
    next_stage = ("R7.A4D2_SHORT_FACTOR_ENGINE_REBUILD_AGAINST_SIMPLE_BENCHMARKS"
                  if not blockers else "R7.A4D2_SHORT_SIMPLE_BENCHMARK_BASELINE_DIAGNOSE")
    summary = {
        "schema": "r7a4d2_short_simple_benchmark_baseline_execution_60_and_data_coverage_audit_v1",
        "official_stage": "R7.A4D2_SHORT_SIMPLE_BENCHMARK_BASELINE_EXECUTION_60_AND_DATA_COVERAGE_AUDIT",
        "state": state, "target_commit": args.target_sha,
        "blocker_count": len(blockers), "blockers": blockers,
        "benchmark_count": EXPECTED_BENCHMARKS, "benchmark_lane_count": len(lanes),
        "selected_segment_count": len(segments), "benchmark_cell_result_count": cell_count,
        "benchmark_trade_result_count": trade_count, "benchmark_cell_results_sha256": cell_sha,
        "benchmark_trade_results_sha256": trade_sha,
        "baseline_economic_pass_lane_count": len(pass_lanes),
        "baseline_economic_pass_lane_ids": [row["lane_id"] for row in pass_lanes],
        "lane_rows": lane_rows, "family_best_rows": family_best_rows,
        "data_coverage_audit": coverage,
        "factor_engine_readiness": {
            "regime_trend_engine": "OHLCV_BASELINE_READY",
            "range_mean_reversion_engine": "OHLCV_BASELINE_READY",
            "event_reversal_engine": "OHLCV_BASELINE_READY",
            "microstructure_scalp_engine": "READY_FOR_LINEAGED_REBUILD" if coverage["microstructure_engine_ready"] else "DATA_GATED",
        },
        "strategy_mutation_allowed": False, "registry_mutation_allowed": False,
        "config_mutation_allowed": False, "router_mutation_allowed": False,
        "service_mutation_allowed": False, "shadow_start_allowed": False,
        "paper_live_order_allowed": False, "mutation_rows": mutation_rows,
        "next_stage": next_stage,
    }
    atomic_json(output / "benchmark_baseline_and_data_coverage_v1.json", summary)
    print("STATE=" + state)
    print("BLOCKER_COUNT=" + str(len(blockers)))
    print("BENCHMARK_COUNT=" + str(EXPECTED_BENCHMARKS))
    print("BENCHMARK_LANE_COUNT=" + str(len(lanes)))
    print("SELECTED_SEGMENT_COUNT=" + str(len(segments)))
    print("BENCHMARK_CELL_RESULT_COUNT=" + str(cell_count))
    print("BENCHMARK_TRADE_RESULT_COUNT=" + str(trade_count))
    print("BASELINE_ECONOMIC_PASS_LANE_COUNT=" + str(len(pass_lanes)))
    print("BASELINE_ECONOMIC_PASS_LANE_IDS=" + json.dumps([row["lane_id"] for row in pass_lanes]))
    print("BENCHMARK_LANE_ROWS=" + json.dumps(lane_rows, ensure_ascii=False, sort_keys=True))
    print("FAMILY_BEST_ROWS=" + json.dumps(family_best_rows, ensure_ascii=False, sort_keys=True))
    print("DATA_COVERAGE_AUDIT=" + json.dumps(coverage, ensure_ascii=False, sort_keys=True))
    print("MICROSTRUCTURE_ENGINE_READY=" + str(coverage["microstructure_engine_ready"]).lower())
    print("MUTATION_ROWS=" + json.dumps(mutation_rows, ensure_ascii=False, sort_keys=True))
    print("SUMMARY_JSON=" + str(output / "benchmark_baseline_and_data_coverage_v1.json"))
    print("NEXT_STAGE=" + next_stage)
    print("BLOCKERS=" + json.dumps(blockers))
    print("RC=" + ("0" if not blockers else "2"))
    return 0 if not blockers else 2


if __name__ == "__main__":
    raise SystemExit(main())
