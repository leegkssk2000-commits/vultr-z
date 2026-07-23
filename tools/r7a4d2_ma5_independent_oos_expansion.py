#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import statistics
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

SEGMENT_BARS = 320
PREROLL_BARS = 320
MAX_OOS_SEGMENTS = 240
EXPECTED_STRESS_CELLS = 6
EXPECTED_FOLDS = 6
MIN_UNIQUE_EVENTS = 24
MIN_SYMBOLS = 3
MIN_POSITIVE_FOLDS = 4
SEVERE_MIN_PF = 1.20
EPS = 1e-12

VARIANT_ID = "ma5_accel_15m_alignment"
PARENT_VARIANT_ID = "ma5_long_only_side_specialization"
LANE_ID = "dual_ma_trend_bot:5m"

SELECTED_MANIFEST = Path("runtime/r7a4c_historical_simulation_input_lineage/selected_input_manifest_v1.json")
FROZEN_MANIFEST = Path("runtime/r7a4_simulation_replay_input_freeze/frozen_input_manifest_v1.json")
SIDE_SUMMARY = Path("runtime/r7a4d2_incremental_defect4_ma5_side_specialization_6/ma5_side_specialization_summary_v1.json")
SIDE_TRADES = Path("runtime/r7a4d2_incremental_defect4_ma5_side_specialization_6/ma5_long_only_child_trade_rows_v1.jsonl")
KILL_SUMMARY = Path("runtime/r7a4d2_simplebot_benchmark_kill_test_6cell/simplebot_benchmark_kill_test_summary_v1.json")
CALIBRATION = Path("runtime/r7a4d2_short_economic_calibration_and_exchange_bot_benchmark_v2_plan/economic_calibration_and_exchange_bot_benchmark_v2_plan_v1.json")
OUTPUT_DIR = Path("runtime/r7a4d2_ma5_independent_oos_expansion")


def import_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_LOAD_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"JSONL_OBJECT_REQUIRED:{path}:{line_number}")
        rows.append(value)
    return rows


def sha256_file(path: Path) -> str | None:
    if not path.is_file() or path.is_symlink():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot(paths: list[Path]) -> dict[str, str | None]:
    return {str(path): sha256_file(path) for path in paths}


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def atomic_jsonl(path: Path, rows: list[dict[str, Any]]) -> tuple[int, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    count = 0
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        for row in rows:
            line = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            handle.write(line)
            digest.update(line.encode("utf-8"))
            count += 1
        temporary = Path(handle.name)
    os.replace(temporary, path)
    return count, digest.hexdigest()


def finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def digest_id(*parts: Any) -> str:
    text = ":".join(str(part) for part in parts)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]


def segment_metrics(frame: pd.DataFrame) -> dict[str, float]:
    close = frame["close"].astype(float).to_numpy()
    log_returns = np.diff(np.log(np.maximum(close, 1e-12)))
    total_return = float(close[-1] / close[0] - 1.0)
    volatility = float(np.std(log_returns)) if log_returns.size else 0.0
    scaled_volatility = volatility * math.sqrt(max(len(close), 1))
    trend_score = total_return / max(scaled_volatility, 1e-9)
    peaks = np.maximum.accumulate(close)
    drawdowns = close / np.maximum(peaks, 1e-12) - 1.0
    trough_index = int(np.argmin(drawdowns))
    max_drawdown = float(drawdowns[trough_index])
    recovery = float(close[-1] / max(float(close[trough_index]), 1e-12) - 1.0)
    return {
        "return": total_return,
        "volatility": volatility,
        "trend_score": trend_score,
        "max_drawdown": max_drawdown,
        "recovery": recovery,
        "shock_score": abs(max_drawdown) + max(recovery, 0.0),
    }


def overlaps(candidate: dict[str, Any], selected: list[dict[str, Any]]) -> bool:
    for prior in selected:
        if str(prior.get("source_path") or "") != str(candidate.get("source_path") or ""):
            continue
        if max(int(candidate["start_row"]), int(prior.get("start_row", -1))) < min(
            int(candidate["end_row_exclusive"]), int(prior.get("end_row_exclusive", -1))
        ):
            return True
    return False


def build_regime_classifier(selected: list[dict[str, Any]]):
    feature_names = ("return", "trend_score", "max_drawdown", "recovery", "shock_score")
    usable: list[tuple[str, np.ndarray]] = []
    for row in selected:
        metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
        regime = str(row.get("regime") or "")
        values = np.asarray([finite(metrics.get(name), math.nan) for name in feature_names], dtype=float)
        if regime and np.isfinite(values).all():
            usable.append((regime, values))
    if not usable:
        return lambda metrics: "oos_unclassified"
    matrix = np.vstack([values for _, values in usable])
    mean = matrix.mean(axis=0)
    scale = matrix.std(axis=0)
    scale[scale <= 1e-12] = 1.0
    by_regime: dict[str, list[np.ndarray]] = defaultdict(list)
    for regime, values in usable:
        by_regime[regime].append((values - mean) / scale)
    centroids = {regime: np.vstack(rows).mean(axis=0) for regime, rows in by_regime.items()}

    def classify(metrics: dict[str, Any]) -> str:
        values = np.asarray([finite(metrics.get(name), math.nan) for name in feature_names], dtype=float)
        if not np.isfinite(values).all():
            return "oos_unclassified"
        point = (values - mean) / scale
        return min(centroids, key=lambda regime: (float(np.linalg.norm(point - centroids[regime])), regime))

    return classify


def build_strict_forward_segments(
    root: Path,
    raw: Any,
    frozen: dict[str, Any],
    selected: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, pd.DataFrame], list[dict[str, Any]], int]:
    category_inputs = frozen.get("category_inputs") if isinstance(frozen.get("category_inputs"), dict) else {}
    entries = [row for row in category_inputs.get("market_data", []) if isinstance(row, dict)]
    frame_cache: dict[str, pd.DataFrame] = {}
    rejected: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    overlap_reject_count = 0
    classifier = build_regime_classifier(selected)

    selected_by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in selected:
        selected_by_source[str(row.get("source_path") or "")].append(row)

    for entry in entries:
        repo_path = str(entry.get("path") or "")
        try:
            repo_path = raw.safe_repo_path(repo_path)
            expected_sha = str(entry.get("sha256") or "")
            frame = raw.fixed_ohlcv_frame(root / repo_path, expected_sha)
            frame_cache[repo_path] = frame
            prior_rows = selected_by_source.get(repo_path, [])
            selected_end = max((int(row.get("end_row_exclusive", 0)) for row in prior_rows), default=0)
            start_floor = max(PREROLL_BARS, selected_end)
            first_start = ((start_floor + SEGMENT_BARS - 1) // SEGMENT_BARS) * SEGMENT_BARS
            for start in range(first_start, len(frame) - SEGMENT_BARS + 1, SEGMENT_BARS):
                stop = start + SEGMENT_BARS
                sample = frame.iloc[start:stop]
                metrics = segment_metrics(sample)
                candidate = {
                    "segment_id": digest_id("ma5-independent-oos", repo_path, expected_sha, start, stop),
                    "source_path": repo_path,
                    "source_sha256": expected_sha,
                    "start_row": start,
                    "end_row_exclusive": stop,
                    "bars": SEGMENT_BARS,
                    "start_timestamp": finite(sample["__timestamp"].iloc[0]),
                    "end_timestamp": finite(sample["__timestamp"].iloc[-1]),
                    "symbol": str(sample["symbol"].iloc[-1]),
                    "source_timeframe": str(sample["timeframe"].iloc[-1]),
                    "metrics": metrics,
                    "regime": classifier(metrics),
                    "strict_forward_from_selected_end_row": selected_end,
                    "source_used_in_discovery": bool(prior_rows),
                }
                if overlaps(candidate, selected):
                    overlap_reject_count += 1
                    continue
                candidates.append(candidate)
        except Exception as exc:
            rejected.append({"path": repo_path, "reason": f"{type(exc).__name__}:{exc}"})

    candidates.sort(
        key=lambda row: (
            finite(row.get("start_timestamp")),
            str(row.get("source_path") or ""),
            int(row.get("start_row", -1)),
            str(row.get("segment_id") or ""),
        )
    )
    selected_candidates = candidates[:MAX_OOS_SEGMENTS]
    count = len(selected_candidates)
    for index, row in enumerate(selected_candidates):
        row["fold"] = min(EXPECTED_FOLDS - 1, int(index * EXPECTED_FOLDS / max(count, 1)))
        row["selection_policy"] = "DISJOINT_SOURCE_OR_STRICT_FORWARD_CHRONOLOGICAL_NO_PERFORMANCE_SELECTION"
    return selected_candidates, frame_cache, rejected, overlap_reject_count


def max_drawdown(values: list[float]) -> float:
    equity = peak = drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return drawdown


def metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(
        rows,
        key=lambda row: (
            int(row.get("fold", -1)),
            finite(row.get("entry_timestamp")),
            str(row.get("symbol") or ""),
            str(row.get("event_id") or ""),
            str(row.get("timing_id") or ""),
        ),
    )
    values = [finite(row.get("net_r")) for row in ordered]
    pnl = [finite(row.get("net_return_pct")) for row in ordered]
    wins = [value for value in values if value > 0]
    losses = [-value for value in values if value < 0]
    folds: dict[int, float] = defaultdict(float)
    for row, value in zip(ordered, values):
        folds[int(row.get("fold", -1))] += value
    gross_win = sum(wins)
    gross_loss = sum(losses)
    event_ids = {str(row.get("event_id") or "") for row in rows if row.get("event_id")}
    return {
        "trade_count": len(rows),
        "unique_event_count": len(event_ids),
        "symbol_count": len({str(row.get("symbol") or "") for row in rows}),
        "source_count": len({str(row.get("source_path") or "") for row in rows}),
        "fold_count": len(folds),
        "positive_fold_count": sum(value > 0 for value in folds.values()),
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate_pct": len(wins) / len(rows) * 100.0 if rows else 0.0,
        "net_r_sum": sum(values),
        "net_pnl_sum_pct": sum(pnl),
        "expectancy_r": statistics.mean(values) if values else 0.0,
        "profit_factor": gross_win / gross_loss if gross_loss > EPS else (math.inf if gross_win > 0 else 0.0),
        "max_drawdown_r": max_drawdown(values),
        "max_drawdown_pct": max_drawdown(pnl),
        "fold_net_r": {str(key): value for key, value in sorted(folds.items())},
        "symbol_histogram": dict(sorted(Counter(str(row.get("symbol") or "") for row in rows).items())),
        "regime_histogram": dict(sorted(Counter(str(row.get("regime") or "") for row in rows).items())),
        "exit_histogram": dict(sorted(Counter(str(row.get("exit_reason") or "") for row in rows).items())),
    }


def profile_name(cost_profile_id: str) -> str:
    return {
        "cost_profile_0": "base",
        "cost_profile_1": "adverse",
        "cost_profile_2": "severe",
    }.get(cost_profile_id, cost_profile_id)


def prior_gate(
    side_summary: dict[str, Any],
    side_trades: list[dict[str, Any]],
    kill_summary: dict[str, Any],
) -> list[str]:
    blockers: list[str] = []
    checks = [
        (side_summary.get("state") == "PASS_INCREMENTAL_DEFECT4_MA5_SIDE_SPECIALIZATION_6", "SIDE_STATE_NOT_PASS"),
        (bool((side_summary.get("pass_checks") or {}).get("repair_pass")), "SIDE_REPAIR_NOT_PASS"),
        (side_summary.get("child_variant_id") == PARENT_VARIANT_ID, "SIDE_VARIANT_CHANGED"),
        (int(side_summary.get("stress_cell_count") or -1) == 6, "SIDE_CELL_COUNT_CHANGED"),
        (int(side_summary.get("child_trade_count") or -1) == 78, "SIDE_TRADE_COUNT_CHANGED"),
        (len(side_trades) == 78, "SIDE_TRADE_ROWS_CHANGED"),
        ({str(row.get("side") or "") for row in side_trades} == {"long"}, "SIDE_ROWS_NOT_LONG_ONLY"),
        (kill_summary.get("state") == "PASS_SIMPLEBOT_BENCHMARK_KILL_TEST_6CELL", "KILL_TEST_NOT_PASS"),
        (int(kill_summary.get("blocker_count") or -1) == 0, "KILL_TEST_BLOCKED"),
        (kill_summary.get("ma5_classification") == "MA5_CONTINUE_INDEPENDENT_OOS", "KILL_TEST_NEXT_CLASS_CHANGED"),
    ]
    for ok, label in checks:
        if not ok:
            blockers.append(label)
    return blockers


def self_test(second: Any, old: Any, benchmark: Any) -> int:
    size = 800
    x = np.arange(size, dtype=float)
    close = pd.Series(100.0 + 0.02 * x + 1.8 * np.sin(x / 8.0))
    open_v = close.shift(1).fillna(close.iloc[0])
    frame5 = pd.DataFrame({
        "__timestamp": x * 300000,
        "open": open_v,
        "high": pd.concat([close, open_v], axis=1).max(axis=1) + 0.35,
        "low": pd.concat([close, open_v], axis=1).min(axis=1) - 0.35,
        "close": close,
        "volume": 100.0 + (x % 31) * 4.0,
        "symbol": "TESTUSDT",
        "timeframe": "5m",
        "__source_index": x.astype(int) * 5,
        "__first_source_index": x.astype(int) * 5,
        "__last_source_index": x.astype(int) * 5 + 4,
        "__complete_bucket": True,
    })
    frame15 = frame5.iloc[::3].reset_index(drop=True).copy()
    frame15["timeframe"] = "15m"
    mask = pd.Series([True] * size)
    signals, _ = second.generate_variant_signals(
        VARIANT_ID, frame5, mask, frame15, "trend_up", 0.12, old
    )
    assert isinstance(signals, list)
    assert all(str(row.get("reason")) == VARIANT_ID for row in signals)
    synthetic = {
        "entry_bar_index": 100,
        "side": "long",
        "stop_price": float(frame5.iloc[100]["open"]) - 1.0,
        "target_price": float(frame5.iloc[100]["open"]) + 2.0,
        "timeout_bars": 12,
    }
    trade = benchmark.simulate_trade(
        frame5,
        mask,
        synthetic,
        {"fee_bps_per_side": 5.0, "slippage_bps_per_side": 1.0, "funding_bps_per_8h": 1.0},
        {"additional_entry_delay_bars": 0, "additional_exit_delay_bars": 0, "additional_slippage_bps_per_side": 0.0},
        "5m",
    )
    assert trade is not None and str(trade.get("side")) == "long"
    print("STATE=PASS_MA5_INDEPENDENT_OOS_EXPANSION_SELF_TEST")
    print("RC=0")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--target-sha", default="UNKNOWN")
    parser.add_argument("--raw-module", required=True)
    parser.add_argument("--helper-module", required=True)
    parser.add_argument("--benchmark-module", required=True)
    parser.add_argument("--old-uplift-module", required=True)
    parser.add_argument("--second-wave-module", required=True)
    parser.add_argument("--a4c-contract", required=True)
    parser.add_argument("--a4d-contract", required=True)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    raw = import_module(Path(args.raw_module).resolve(), "ma5_oos_raw")
    helper = import_module(Path(args.helper_module).resolve(), "ma5_oos_helper")
    benchmark = import_module(Path(args.benchmark_module).resolve(), "ma5_oos_benchmark")
    old = import_module(Path(args.old_uplift_module).resolve(), "ma5_oos_old")
    second = import_module(Path(args.second_wave_module).resolve(), "ma5_oos_second")

    if args.self_test:
        return self_test(second, old, benchmark)

    root = Path(args.root).resolve()
    a4c_contract = load_json(Path(args.a4c_contract).resolve())
    a4d_contract = load_json(Path(args.a4d_contract).resolve())
    required = [
        root / SELECTED_MANIFEST,
        root / FROZEN_MANIFEST,
        root / SIDE_SUMMARY,
        root / SIDE_TRADES,
        root / KILL_SUMMARY,
        root / CALIBRATION,
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        print("STATE=HOLD_MA5_INDEPENDENT_OOS_EXPANSION_INPUT")
        print("BLOCKER_COUNT=1")
        print("BLOCKERS=" + json.dumps(["REQUIRED_EVIDENCE_MISSING:" + ",".join(missing)]))
        print("RC=2")
        return 2

    selected_manifest = load_json(root / SELECTED_MANIFEST)
    frozen_manifest = load_json(root / FROZEN_MANIFEST)
    side_summary = load_json(root / SIDE_SUMMARY)
    side_trades = load_jsonl(root / SIDE_TRADES)
    kill_summary = load_json(root / KILL_SUMMARY)
    calibration = load_json(root / CALIBRATION)

    blockers = prior_gate(side_summary, side_trades, kill_summary)
    if selected_manifest.get("state") != "PASS" or len(selected_manifest.get("selected_segments") or []) != 24:
        blockers.append("SELECTED_MANIFEST_INVALID")
    if frozen_manifest.get("state") != "PASS":
        blockers.append("FROZEN_MANIFEST_INVALID")
    if a4c_contract.get("official_stage") != "R7.A4C" or int(a4c_contract.get("segment_bars") or -1) != SEGMENT_BARS:
        blockers.append("A4C_CONTRACT_INVALID")
    if a4d_contract.get("official_stage") != "R7.A4D":
        blockers.append("A4D_CONTRACT_INVALID")

    model = calibration.get("corrected_execution_model") if isinstance(calibration.get("corrected_execution_model"), dict) else {}
    costs = [row for row in model.get("profiles", []) if isinstance(row, dict)]
    timings = [row for row in model.get("timing_perturbations", []) if isinstance(row, dict)]
    base_cost_pct = finite(old.base_round_trip_cost(calibration), math.nan)
    if len(costs) * len(timings) != EXPECTED_STRESS_CELLS:
        blockers.append("STRESS_GRID_INVALID")
    if not math.isfinite(base_cost_pct) or base_cost_pct <= 0:
        blockers.append("BASE_COST_INVALID")

    category_inputs = frozen_manifest.get("category_inputs") if isinstance(frozen_manifest.get("category_inputs"), dict) else {}
    market_entries = [row for row in category_inputs.get("market_data", []) if isinstance(row, dict)]
    if not market_entries:
        blockers.append("FROZEN_MARKET_ENTRY_ZERO")

    if blockers:
        print("STATE=HOLD_MA5_INDEPENDENT_OOS_EXPANSION_INPUT")
        print("BLOCKER_COUNT=" + str(len(blockers)))
        print("BLOCKERS=" + json.dumps(blockers))
        print("RC=2")
        return 2

    selected_rows = [row for row in selected_manifest.get("selected_segments", []) if isinstance(row, dict)]
    market_paths = [root / raw.safe_repo_path(str(row.get("path") or "")) for row in market_entries]
    protected = [Path(str(value)) for value in a4d_contract.get("protected_paths", [])]
    input_paths = required + market_paths + protected
    before = snapshot(input_paths)

    segments, source_cache, rejected_sources, overlap_reject_count = build_strict_forward_segments(
        root, raw, frozen_manifest, selected_rows
    )

    frame_cache: dict[tuple[str, str], pd.DataFrame] = {}
    mask_cache: dict[str, pd.Series] = {}
    signal_cache: dict[str, list[dict[str, Any]]] = {}
    rejection_histogram: Counter[str] = Counter()
    execution_failures: list[dict[str, Any]] = []

    for segment in segments:
        segment_id = str(segment["segment_id"])
        source = source_cache[str(segment["source_path"])]
        try:
            frame5 = raw.resample_for_segment(
                source, int(segment["start_row"]), int(segment["end_row_exclusive"]), "5m"
            )
            frame15 = raw.resample_for_segment(
                source, int(segment["start_row"]), int(segment["end_row_exclusive"]), "15m"
            )
            mask5 = raw.measurement_mask(
                frame5, int(segment["start_row"]), int(segment["end_row_exclusive"])
            )
            signals, rejected = second.generate_variant_signals(
                VARIANT_ID,
                frame5,
                mask5,
                frame15,
                str(segment["regime"]),
                base_cost_pct,
                old,
            )
            long_signals = [row for row in signals if str(row.get("side") or "") == "long"]
            frame_cache[(segment_id, "5m")] = frame5
            frame_cache[(segment_id, "15m")] = frame15
            mask_cache[segment_id] = mask5
            signal_cache[segment_id] = long_signals
            rejection_histogram.update(rejected)
        except Exception as exc:
            execution_failures.append({
                "phase": "SIGNAL_GENERATION",
                "segment_id": segment_id,
                "error": f"{type(exc).__name__}:{exc}",
            })

    unique_signal_keys = {
        (segment_id, int(signal.get("signal_bar_index", -1)), str(signal.get("reason") or ""))
        for segment_id, signals in signal_cache.items()
        for signal in signals
    }
    signal_symbols = {
        str(segment["symbol"])
        for segment in segments
        if signal_cache.get(str(segment["segment_id"]))
    }
    signal_folds = {
        int(segment["fold"])
        for segment in segments
        if signal_cache.get(str(segment["segment_id"]))
    }

    coverage_checks = {
        "strict_forward_segment_gate": len(segments) >= EXPECTED_FOLDS,
        "unique_event_gate": len(unique_signal_keys) >= MIN_UNIQUE_EVENTS,
        "symbol_gate": len(signal_symbols) >= MIN_SYMBOLS,
        "fold_coverage_gate": len(signal_folds) == EXPECTED_FOLDS,
        "source_replay_gate": not execution_failures,
    }
    coverage_ready = all(coverage_checks.values())

    trade_rows: list[dict[str, Any]] = []
    cell_rows: list[dict[str, Any]] = []

    if coverage_ready:
        for cost in costs:
            for timing in timings:
                cell_trades: list[dict[str, Any]] = []
                for segment in segments:
                    segment_id = str(segment["segment_id"])
                    frame = frame_cache.get((segment_id, "5m"))
                    mask = mask_cache.get(segment_id)
                    if frame is None or mask is None:
                        continue
                    last_exit = -1
                    for signal in signal_cache.get(segment_id, []):
                        if int(signal["entry_bar_index"]) <= last_exit:
                            continue
                        try:
                            trade = benchmark.simulate_trade(frame, mask, signal, cost, timing, "5m")
                            if trade is None:
                                continue
                            last_exit = int(trade["exit_index"])
                            event_id = digest_id(segment_id, int(signal["signal_bar_index"]), signal["reason"])
                            entry_index = int(trade["entry_index"])
                            exit_index = int(trade["exit_index"])
                            trade.update({
                                "event_id": event_id,
                                "variant_id": PARENT_VARIANT_ID,
                                "source_variant_id": VARIANT_ID,
                                "lane_id": LANE_ID,
                                "side": "long",
                                "cost_profile_id": str(cost["id"]),
                                "timing_id": str(timing["id"]),
                                "segment_id": segment_id,
                                "fold": int(segment["fold"]),
                                "regime": str(segment["regime"]),
                                "symbol": str(segment["symbol"]),
                                "source_path": str(segment["source_path"]),
                                "source_sha256": str(segment["source_sha256"]),
                                "segment_start_row": int(segment["start_row"]),
                                "segment_end_row_exclusive": int(segment["end_row_exclusive"]),
                                "entry_source_index": int(frame.iloc[entry_index]["__first_source_index"]),
                                "exit_source_index": int(frame.iloc[exit_index]["__last_source_index"]),
                                "entry_timestamp": finite(frame.iloc[entry_index]["__timestamp"]),
                                "exit_timestamp": finite(frame.iloc[exit_index]["__timestamp"]),
                                "signal_reason": str(signal["reason"]),
                                "target_to_base_cost_ratio": finite(signal.get("target_to_base_cost_ratio")),
                                "risk_to_base_cost_ratio": finite(signal.get("risk_to_base_cost_ratio")),
                                "oos_selection_policy": segment["selection_policy"],
                            })
                            cell_trades.append(trade)
                            trade_rows.append(trade)
                        except Exception as exc:
                            execution_failures.append({
                                "phase": "TRADE_SIMULATION",
                                "segment_id": segment_id,
                                "cost_profile_id": str(cost.get("id")),
                                "timing_id": str(timing.get("id")),
                                "error": f"{type(exc).__name__}:{exc}",
                            })
                cell_metrics = metrics(cell_trades)
                cell_rows.append({
                    "cost_profile_id": str(cost["id"]),
                    "timing_id": str(timing["id"]),
                    "profile": profile_name(str(cost["id"])),
                    **cell_metrics,
                })

    profiles = {
        profile: metrics([
            row for row in trade_rows if profile_name(str(row.get("cost_profile_id") or "")) == profile
        ])
        for profile in ("base", "adverse", "severe")
    }
    severe_cells = [row for row in cell_rows if row.get("profile") == "severe"]
    worst_severe_cell = min(severe_cells, key=lambda row: finite(row.get("net_r_sum"), math.inf)) if severe_cells else {}

    profile_checks = {
        "base_net_positive": profiles["base"]["net_r_sum"] > 0,
        "base_pf_positive": profiles["base"]["profit_factor"] > 1.0,
        "base_positive_folds": profiles["base"]["positive_fold_count"] >= MIN_POSITIVE_FOLDS,
        "adverse_net_positive": profiles["adverse"]["net_r_sum"] > 0,
        "adverse_pf_positive": profiles["adverse"]["profit_factor"] > 1.0,
        "adverse_positive_folds": profiles["adverse"]["positive_fold_count"] >= MIN_POSITIVE_FOLDS,
        "severe_net_positive": profiles["severe"]["net_r_sum"] > 0,
        "severe_pf_gate": profiles["severe"]["profit_factor"] >= SEVERE_MIN_PF,
        "severe_positive_folds": profiles["severe"]["positive_fold_count"] >= MIN_POSITIVE_FOLDS,
        "severe_unique_events": profiles["severe"]["unique_event_count"] >= MIN_UNIQUE_EVENTS,
        "severe_symbol_gate": profiles["severe"]["symbol_count"] >= MIN_SYMBOLS,
        "worst_severe_cell_net_positive": finite(worst_severe_cell.get("net_r_sum"), -math.inf) > 0,
        "worst_severe_cell_pf_positive": finite(worst_severe_cell.get("profit_factor"), 0.0) > 1.0,
    }

    robust_pass = coverage_ready and not execution_failures and all(profile_checks.values())
    conditional_pass = (
        coverage_ready
        and not execution_failures
        and all(profile_checks[key] for key in (
            "base_net_positive", "base_pf_positive", "base_positive_folds",
            "adverse_net_positive", "adverse_pf_positive", "adverse_positive_folds",
        ))
        and not robust_pass
    )
    if not coverage_ready:
        classification = "MA5_OOS_DATA_COVERAGE_HOLD"
        next_stage = "R7.A4D2_MA5_OOS_MARKET_SOURCE_COVERAGE_EXPANSION"
    elif robust_pass:
        classification = "MA5_OOS_ROBUST_PASS"
        next_stage = "R7.A4D2_MA5_OOS_EXIT_CAPTURE_AUDIT"
    elif conditional_pass:
        classification = "MA5_OOS_CONDITIONAL_PASS"
        next_stage = "R7.A4D2_MA5_OOS_RESIDUAL_LOSS_DECOMPOSITION"
    else:
        classification = "MA5_OOS_FAIL"
        next_stage = "R7.A4D2_MA5_OBSERVER_MATERIAL_RECLASSIFY"

    after = snapshot(input_paths)
    mutation_paths = sorted(path for path in before if before[path] != after[path])
    integrity_blockers: list[str] = []
    if len(cell_rows) not in {0, EXPECTED_STRESS_CELLS}:
        integrity_blockers.append(f"CELL_COUNT_INVALID:{len(cell_rows)}")
    if mutation_paths:
        integrity_blockers.append(f"INPUT_MUTATION:{len(mutation_paths)}")
    if execution_failures and coverage_ready:
        integrity_blockers.append(f"EXECUTION_FAILURE:{len(execution_failures)}")

    state = (
        "PASS_MA5_INDEPENDENT_OOS_EXPANSION"
        if not integrity_blockers and coverage_ready
        else (
            "HOLD_MA5_INDEPENDENT_OOS_DATA_COVERAGE"
            if not integrity_blockers
            else "HOLD_MA5_INDEPENDENT_OOS_EXPANSION_INTEGRITY"
        )
    )
    rc = 0 if state == "PASS_MA5_INDEPENDENT_OOS_EXPANSION" else 2

    output = root / OUTPUT_DIR
    trade_count, trade_sha = atomic_jsonl(output / "ma5_oos_trade_rows_v1.jsonl", trade_rows)
    cell_count, cell_sha = atomic_jsonl(output / "ma5_oos_cell_rows_v1.jsonl", cell_rows)
    atomic_json(output / "ma5_oos_selected_segments_v1.json", {
        "state": "PASS_MA5_OOS_SEGMENT_SELECTION" if segments else "HOLD_MA5_OOS_SEGMENT_SELECTION_EMPTY",
        "selection_policy": "DISJOINT_SOURCE_OR_STRICT_FORWARD_CHRONOLOGICAL_NO_PERFORMANCE_SELECTION",
        "segment_count": len(segments),
        "segments": segments,
    })
    summary = {
        "schema": "r7a4d2_ma5_independent_oos_expansion_v1",
        "official_stage": "R7.A4D2_MA5_INDEPENDENT_OOS_EXPANSION",
        "state": state,
        "target_commit": args.target_sha,
        "blocker_count": len(integrity_blockers),
        "blockers": integrity_blockers,
        "classification": classification,
        "selection_policy": "DISJOINT_SOURCE_OR_STRICT_FORWARD_CHRONOLOGICAL_NO_PERFORMANCE_SELECTION",
        "selected_discovery_segment_count": len(selected_rows),
        "strict_forward_oos_segment_count": len(segments),
        "max_oos_segments": MAX_OOS_SEGMENTS,
        "rejected_market_source_count": len(rejected_sources),
        "rejected_market_sources": rejected_sources,
        "overlap_reject_count": overlap_reject_count,
        "unique_long_signal_count": len(unique_signal_keys),
        "signal_symbol_count": len(signal_symbols),
        "signal_fold_count": len(signal_folds),
        "coverage_checks": coverage_checks,
        "coverage_ready": coverage_ready,
        "stress_cell_count": cell_count,
        "trade_row_count": trade_count,
        "trade_sha256": trade_sha,
        "cell_sha256": cell_sha,
        "profile_metrics": profiles,
        "worst_severe_cell_metrics": worst_severe_cell,
        "profile_checks": profile_checks,
        "robust_survivor": robust_pass,
        "conditional_survivor": conditional_pass,
        "signal_rejection_histogram": dict(sorted(rejection_histogram.items())),
        "execution_failures": execution_failures[:50],
        "mutation_path_count": len(mutation_paths),
        "mutation_paths": mutation_paths,
        "strategy_mutation_allowed": False,
        "registry_mutation_allowed": False,
        "config_mutation_allowed": False,
        "router_mutation_allowed": False,
        "service_mutation_allowed": False,
        "shadow_start_allowed": False,
        "paper_live_order_allowed": False,
        "next_stage": next_stage,
    }
    atomic_json(output / "ma5_independent_oos_summary_v1.json", summary)

    print("STATE=" + state)
    print("BLOCKER_COUNT=" + str(len(integrity_blockers)))
    print("OOS_CLASSIFICATION=" + classification)
    print("STRICT_FORWARD_OOS_SEGMENT_COUNT=" + str(len(segments)))
    print("UNIQUE_LONG_SIGNAL_COUNT=" + str(len(unique_signal_keys)))
    print("SIGNAL_SYMBOL_COUNT=" + str(len(signal_symbols)))
    print("SIGNAL_FOLD_COUNT=" + str(len(signal_folds)))
    print("COVERAGE_CHECKS=" + json.dumps(coverage_checks, sort_keys=True))
    print("STRESS_CELL_COUNT=" + str(cell_count))
    for profile in ("base", "adverse", "severe"):
        row = profiles[profile]
        print(
            f"{profile.upper()}_NET_R={row['net_r_sum']:.12f}|"
            f"PF={row['profit_factor']:.12f}|DD_R={row['max_drawdown_r']:.12f}|"
            f"POS_FOLDS={row['positive_fold_count']}/{EXPECTED_FOLDS}|"
            f"UNIQUE_EVENTS={row['unique_event_count']}|SYMBOLS={row['symbol_count']}"
        )
    if worst_severe_cell:
        print(
            f"WORST_SEVERE_CELL={worst_severe_cell['cost_profile_id']}:{worst_severe_cell['timing_id']}|"
            f"NET_R={worst_severe_cell['net_r_sum']:.12f}|"
            f"PF={worst_severe_cell['profit_factor']:.12f}|"
            f"DD_R={worst_severe_cell['max_drawdown_r']:.12f}"
        )
    print("PROFILE_CHECKS=" + json.dumps(profile_checks, sort_keys=True))
    print("ROBUST_SURVIVOR=" + str(robust_pass).lower())
    print("CONDITIONAL_SURVIVOR=" + str(conditional_pass).lower())
    print("MUTATION_PATH_COUNT=" + str(len(mutation_paths)))
    print("SUMMARY_JSON=" + str(output / "ma5_independent_oos_summary_v1.json"))
    print("NEXT_STAGE=" + next_stage)
    print("BLOCKERS=" + json.dumps(integrity_blockers))
    print("RC=" + str(rc))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
