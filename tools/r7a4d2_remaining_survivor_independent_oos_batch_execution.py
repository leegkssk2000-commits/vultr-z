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

import pandas as pd

PLAN_PATH = Path("runtime/r7a4d2_ma5_observer_material_reclassify/remaining_survivor_independent_oos_batch_plan_v1.json")
RECLASS_PATH = Path("runtime/r7a4d2_ma5_observer_material_reclassify/ma5_observer_material_reclassification_v1.json")
SELECTED_MANIFEST = Path("runtime/r7a4c_historical_simulation_input_lineage/selected_input_manifest_v1.json")
CALIBRATION = Path("runtime/r7a4d2_short_economic_calibration_and_exchange_bot_benchmark_v2_plan/economic_calibration_and_exchange_bot_benchmark_v2_plan_v1.json")
OUTPUT_DIR = Path("runtime/r7a4d2_remaining_survivor_independent_oos_batch_execution")

EXPECTED_CANDIDATES = 10
EXPECTED_SEGMENTS = 240
EXPECTED_STRESS_CELLS = 6
EXPECTED_FOLDS = 6
MIN_UNIQUE_EVENTS = 24
MIN_SYMBOLS = 3
MIN_POSITIVE_FOLDS = 4
SEVERE_MIN_PF = 1.20
EPS = 1e-12
MA5_LANE = "dual_ma_trend_bot:5m"
MA5_VARIANTS = {"ma5_accel_15m_alignment", "ma5_confluence_first_pullback"}


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
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
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


def max_drawdown(values: list[float]) -> float:
    equity = peak = drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return drawdown


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
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
        "side_histogram": dict(sorted(Counter(str(row.get("side") or "") for row in rows).items())),
        "exit_histogram": dict(sorted(Counter(str(row.get("exit_reason") or "") for row in rows).items())),
    }


def profile_name(cost_profile_id: str) -> str:
    return {
        "cost_profile_0": "base",
        "cost_profile_1": "adverse",
        "cost_profile_2": "severe",
    }.get(cost_profile_id, cost_profile_id)


def self_test(second: Any, old: Any, benchmark: Any) -> int:
    size = 900
    x = pd.Series(range(size), dtype=float)
    close = 100.0 + 0.015 * x + 1.7 * (x / 9.0).map(math.sin)
    open_v = close.shift(1).fillna(close.iloc[0])
    frame5 = pd.DataFrame({
        "__timestamp": x * 300000,
        "open": open_v,
        "high": pd.concat([close, open_v], axis=1).max(axis=1) + 0.4,
        "low": pd.concat([close, open_v], axis=1).min(axis=1) - 0.4,
        "close": close,
        "volume": 100.0 + (x % 29) * 3.0,
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
    signals, rejected = second.generate_variant_signals(
        "atr5_impulse_15m_alignment", frame5, mask, frame15, "trend_up", 0.12, old
    )
    assert isinstance(signals, list) and isinstance(rejected, Counter)
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
    assert trade is not None
    print("STATE=PASS_REMAINING_SURVIVOR_INDEPENDENT_OOS_BATCH_SELF_TEST")
    print("RC=0")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--target-sha", required=True)
    parser.add_argument("--raw-module", required=True)
    parser.add_argument("--benchmark-module", required=True)
    parser.add_argument("--old-uplift-module", required=True)
    parser.add_argument("--second-wave-module", required=True)
    parser.add_argument("--oos-module", required=True)
    parser.add_argument("--a4d-contract", required=True)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    raw = import_module(Path(args.raw_module).resolve(), "remaining_oos_raw")
    benchmark = import_module(Path(args.benchmark_module).resolve(), "remaining_oos_benchmark")
    old = import_module(Path(args.old_uplift_module).resolve(), "remaining_oos_old")
    second = import_module(Path(args.second_wave_module).resolve(), "remaining_oos_second")
    oos = import_module(Path(args.oos_module).resolve(), "remaining_oos_segmenter")

    if args.self_test:
        return self_test(second, old, benchmark)

    root = Path(args.root).resolve()
    contract = load_json(Path(args.a4d_contract).resolve())
    required = [root / PLAN_PATH, root / RECLASS_PATH, root / SELECTED_MANIFEST, root / CALIBRATION]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        print("STATE=HOLD_REMAINING_SURVIVOR_INDEPENDENT_OOS_BATCH_INPUT")
        print("BLOCKER_COUNT=1")
        print("BLOCKERS=" + json.dumps(["REQUIRED_EVIDENCE_MISSING:" + ",".join(missing)]))
        print("RC=2")
        return 2

    plan = load_json(root / PLAN_PATH)
    reclass = load_json(root / RECLASS_PATH)
    selected_manifest = load_json(root / SELECTED_MANIFEST)
    calibration = load_json(root / CALIBRATION)
    overlay_path = root / str(plan.get("market_overlay_manifest_path") or "")
    if not overlay_path.is_file():
        print("STATE=HOLD_REMAINING_SURVIVOR_INDEPENDENT_OOS_BATCH_INPUT")
        print("BLOCKER_COUNT=1")
        print("BLOCKERS=[\"OOS_OVERLAY_MANIFEST_MISSING\"]")
        print("RC=2")
        return 2
    overlay = load_json(overlay_path)

    blockers: list[str] = []
    if plan.get("state") != "PASS_REMAINING_SURVIVOR_INDEPENDENT_OOS_BATCH_PLAN":
        blockers.append("BATCH_PLAN_NOT_PASS")
    if reclass.get("state") != "PASS_MA5_OBSERVER_MATERIAL_RECLASSIFY":
        blockers.append("MA5_RECLASS_NOT_PASS")
    if reclass.get("classification") != "OBSERVER_MATERIAL":
        blockers.append("MA5_RECLASS_CHANGED")
    if bool(reclass.get("standalone_candidate_allowed")) or bool(reclass.get("exit_repair_allowed")):
        blockers.append("MA5_AUTHORITY_NOT_BLOCKED")
    if selected_manifest.get("state") != "PASS" or len(selected_manifest.get("selected_segments") or []) != 24:
        blockers.append("SELECTED_MANIFEST_INVALID")
    if overlay.get("state") != "PASS" or int(overlay.get("oos_generated_market_source_count", -1)) < MIN_SYMBOLS:
        blockers.append("OOS_OVERLAY_INVALID")
    if contract.get("official_stage") != "R7.A4D":
        blockers.append("A4D_CONTRACT_INVALID")

    candidates = [row for row in plan.get("candidates", []) if isinstance(row, dict)]
    if len(candidates) != EXPECTED_CANDIDATES:
        blockers.append(f"CANDIDATE_COUNT_INVALID:{len(candidates)}")
    lane_ids = [str(row.get("source_lane_id") or "") for row in candidates]
    variant_ids = [str(row.get("variant_id") or "") for row in candidates]
    if len(set(lane_ids)) != EXPECTED_CANDIDATES:
        blockers.append("CANDIDATE_LANE_DUPLICATE")
    if MA5_LANE in lane_ids or any(variant in MA5_VARIANTS for variant in variant_ids):
        blockers.append("MA5_PRESENT_IN_REMAINING_BATCH")
    if any(variant not in second.VARIANT_IDS for variant in variant_ids):
        blockers.append("CANDIDATE_VARIANT_UNKNOWN")
    if any(str(row.get("execution_timeframe") or "") not in {"5m", "15m"} for row in candidates):
        blockers.append("CANDIDATE_TIMEFRAME_INVALID")

    model = calibration.get("corrected_execution_model") if isinstance(calibration.get("corrected_execution_model"), dict) else {}
    costs = [row for row in model.get("profiles", []) if isinstance(row, dict)]
    timings = [row for row in model.get("timing_perturbations", []) if isinstance(row, dict)]
    base_cost_pct = finite(old.base_round_trip_cost(calibration), math.nan)
    if len(costs) * len(timings) != EXPECTED_STRESS_CELLS:
        blockers.append("STRESS_GRID_INVALID")
    if not math.isfinite(base_cost_pct) or base_cost_pct <= 0:
        blockers.append("BASE_COST_INVALID")

    category_inputs = overlay.get("category_inputs") if isinstance(overlay.get("category_inputs"), dict) else {}
    market_entries = [row for row in category_inputs.get("market_data", []) if isinstance(row, dict)]
    if not market_entries:
        blockers.append("OOS_MARKET_ENTRY_ZERO")

    if blockers:
        print("STATE=HOLD_REMAINING_SURVIVOR_INDEPENDENT_OOS_BATCH_INPUT")
        print("BLOCKER_COUNT=" + str(len(blockers)))
        print("BLOCKERS=" + json.dumps(blockers))
        print("RC=2")
        return 2

    selected_rows = [row for row in selected_manifest.get("selected_segments", []) if isinstance(row, dict)]
    market_paths = [root / raw.safe_repo_path(str(row.get("path") or "")) for row in market_entries]
    protected = [Path(str(value)) for value in contract.get("protected_paths", [])]
    input_paths = required + [overlay_path] + market_paths + protected
    before = snapshot(input_paths)

    segments, source_cache, rejected_sources, overlap_reject_count = oos.build_strict_forward_segments(
        root, raw, overlay, selected_rows
    )
    segment_gate = len(segments) == EXPECTED_SEGMENTS

    needed_timeframes = {str(row["execution_timeframe"]) for row in candidates} | {"15m"}
    frame_cache: dict[tuple[str, str], pd.DataFrame] = {}
    mask_cache: dict[tuple[str, str], pd.Series] = {}
    frame_failures: list[dict[str, Any]] = []
    for segment in segments:
        segment_id = str(segment["segment_id"])
        source = source_cache[str(segment["source_path"])]
        for timeframe in sorted(needed_timeframes):
            try:
                frame = raw.resample_for_segment(
                    source, int(segment["start_row"]), int(segment["end_row_exclusive"]), timeframe
                )
                mask = raw.measurement_mask(
                    frame, int(segment["start_row"]), int(segment["end_row_exclusive"])
                )
                frame_cache[(segment_id, timeframe)] = frame
                mask_cache[(segment_id, timeframe)] = mask
            except Exception as exc:
                frame_failures.append({
                    "segment_id": segment_id,
                    "timeframe": timeframe,
                    "error": f"{type(exc).__name__}:{exc}",
                })

    all_trade_rows: list[dict[str, Any]] = []
    all_cell_rows: list[dict[str, Any]] = []
    candidate_results: list[dict[str, Any]] = []
    global_failures: list[dict[str, Any]] = list(frame_failures)

    for candidate_index, candidate in enumerate(candidates, 1):
        lane_id = str(candidate["source_lane_id"])
        variant_id = str(candidate["variant_id"])
        execution_timeframe = str(candidate["execution_timeframe"])
        signal_cache: dict[str, list[dict[str, Any]]] = {}
        rejection_histogram: Counter[str] = Counter()
        failures: list[dict[str, Any]] = []

        for segment in segments:
            segment_id = str(segment["segment_id"])
            frame = frame_cache.get((segment_id, execution_timeframe))
            frame15 = frame_cache.get((segment_id, "15m"))
            mask = mask_cache.get((segment_id, execution_timeframe))
            if frame is None or frame15 is None or mask is None:
                failures.append({"phase": "FRAME_MISSING", "segment_id": segment_id})
                continue
            try:
                signals, rejected = second.generate_variant_signals(
                    variant_id,
                    frame,
                    mask,
                    frame15,
                    str(segment["regime"]),
                    base_cost_pct,
                    old,
                )
                signal_cache[segment_id] = signals
                rejection_histogram.update(rejected)
            except Exception as exc:
                failures.append({
                    "phase": "SIGNAL_GENERATION",
                    "segment_id": segment_id,
                    "error": f"{type(exc).__name__}:{exc}",
                })

        unique_signal_keys = {
            (
                segment_id,
                int(signal.get("signal_bar_index", -1)),
                str(signal.get("side") or ""),
                str(signal.get("reason") or ""),
                str(signal.get("level_id") or ""),
            )
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
            "strict_forward_segment_gate": segment_gate,
            "unique_event_gate": len(unique_signal_keys) >= MIN_UNIQUE_EVENTS,
            "symbol_gate": len(signal_symbols) >= MIN_SYMBOLS,
            "fold_coverage_gate": len(signal_folds) == EXPECTED_FOLDS,
            "source_replay_gate": not failures and not frame_failures,
        }
        coverage_ready = all(coverage_checks.values())
        candidate_trade_rows: list[dict[str, Any]] = []
        candidate_cell_rows: list[dict[str, Any]] = []

        if coverage_ready:
            for cost in costs:
                for timing in timings:
                    cell_trades: list[dict[str, Any]] = []
                    for segment in segments:
                        segment_id = str(segment["segment_id"])
                        frame = frame_cache[(segment_id, execution_timeframe)]
                        mask = mask_cache[(segment_id, execution_timeframe)]
                        last_exit = -1
                        last_exit_by_level: dict[str, int] = {}
                        for signal in signal_cache.get(segment_id, []):
                            entry_bar = int(signal["entry_bar_index"])
                            if variant_id in second.GRID_VARIANTS:
                                level_key = f"{signal.get('side')}:{signal.get('level_id') or 'NA'}"
                                if entry_bar <= last_exit_by_level.get(level_key, -1):
                                    continue
                            elif entry_bar <= last_exit:
                                continue
                            try:
                                trade = benchmark.simulate_trade(
                                    frame, mask, signal, cost, timing, execution_timeframe
                                )
                                if trade is None:
                                    continue
                                if variant_id in second.GRID_VARIANTS:
                                    last_exit_by_level[level_key] = int(trade["exit_index"])
                                else:
                                    last_exit = int(trade["exit_index"])
                                entry_index = int(trade["entry_index"])
                                exit_index = int(trade["exit_index"])
                                event_id = oos.digest_id(
                                    "remaining-oos",
                                    variant_id,
                                    segment_id,
                                    int(signal.get("signal_bar_index", -1)),
                                    str(signal.get("side") or ""),
                                    str(signal.get("reason") or ""),
                                    str(signal.get("level_id") or ""),
                                )
                                trade.update({
                                    "event_id": event_id,
                                    "variant_id": variant_id,
                                    "lane_id": lane_id,
                                    "execution_timeframe": execution_timeframe,
                                    "family": candidate.get("family"),
                                    "repair_class": candidate.get("repair_class"),
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
                                    "signal_reason": str(signal.get("reason") or ""),
                                    "level_id": signal.get("level_id"),
                                    "target_to_base_cost_ratio": finite(signal.get("target_to_base_cost_ratio")),
                                    "risk_to_base_cost_ratio": finite(signal.get("risk_to_base_cost_ratio")),
                                    "oos_selection_policy": segment["selection_policy"],
                                })
                                cell_trades.append(trade)
                                candidate_trade_rows.append(trade)
                                all_trade_rows.append(trade)
                            except Exception as exc:
                                failure = {
                                    "phase": "TRADE_SIMULATION",
                                    "variant_id": variant_id,
                                    "segment_id": segment_id,
                                    "cost_profile_id": str(cost.get("id")),
                                    "timing_id": str(timing.get("id")),
                                    "error": f"{type(exc).__name__}:{exc}",
                                }
                                failures.append(failure)
                                global_failures.append(failure)
                    cell_metrics = aggregate(cell_trades)
                    cell_row = {
                        "variant_id": variant_id,
                        "lane_id": lane_id,
                        "execution_timeframe": execution_timeframe,
                        "cost_profile_id": str(cost["id"]),
                        "timing_id": str(timing["id"]),
                        "profile": profile_name(str(cost["id"])),
                        **cell_metrics,
                    }
                    candidate_cell_rows.append(cell_row)
                    all_cell_rows.append(cell_row)

        profiles = {
            profile: aggregate([
                row for row in candidate_trade_rows
                if profile_name(str(row.get("cost_profile_id") or "")) == profile
            ])
            for profile in ("base", "adverse", "severe")
        }
        severe_cells = [row for row in candidate_cell_rows if row.get("profile") == "severe"]
        worst_severe_cell = min(
            severe_cells, key=lambda row: finite(row.get("net_r_sum"), math.inf)
        ) if severe_cells else {}
        checks = {
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
        robust = coverage_ready and not failures and all(checks.values())
        conditional = (
            coverage_ready
            and not failures
            and all(checks[key] for key in (
                "base_net_positive", "base_pf_positive", "base_positive_folds",
                "adverse_net_positive", "adverse_pf_positive", "adverse_positive_folds",
            ))
            and not robust
        )
        classification = (
            "ROBUST_SURVIVOR" if robust else
            "CONDITIONAL_SURVIVOR" if conditional else
            "OBSERVER_RETIRE"
        )
        result = {
            "candidate_index": candidate_index,
            "lane_id": lane_id,
            "variant_id": variant_id,
            "execution_timeframe": execution_timeframe,
            "family": candidate.get("family"),
            "repair_class": candidate.get("repair_class"),
            "classification": classification,
            "coverage_ready": coverage_ready,
            "coverage_checks": coverage_checks,
            "unique_signal_count": len(unique_signal_keys),
            "signal_symbol_count": len(signal_symbols),
            "signal_fold_count": len(signal_folds),
            "stress_cell_count": len(candidate_cell_rows),
            "profile_metrics": profiles,
            "worst_severe_cell_metrics": worst_severe_cell,
            "profile_checks": checks,
            "robust_survivor": robust,
            "conditional_survivor": conditional,
            "signal_rejection_histogram": dict(sorted(rejection_histogram.items())),
            "execution_failures": failures[:50],
            "prior_uplift_discovery_pass": bool(candidate.get("prior_uplift_discovery_pass")),
            "prior_reference_beating_discovery_pass": bool(candidate.get("prior_reference_beating_discovery_pass")),
        }
        candidate_results.append(result)
        print(
            f"OOS_BATCH_PROGRESS={candidate_index}/{EXPECTED_CANDIDATES}|"
            f"LANE={lane_id}|VARIANT={variant_id}|CLASS={classification}|"
            f"EVENTS={len(unique_signal_keys)}|CELLS={len(candidate_cell_rows)}|"
            f"BASE_R={profiles['base']['net_r_sum']:.6f}|"
            f"ADVERSE_R={profiles['adverse']['net_r_sum']:.6f}|"
            f"SEVERE_R={profiles['severe']['net_r_sum']:.6f}"
        )

    after = snapshot(input_paths)
    mutation_paths = sorted(path for path in before if before[path] != after[path])
    integrity_blockers: list[str] = []
    if not segment_gate:
        integrity_blockers.append(f"STRICT_FORWARD_SEGMENT_COUNT_INVALID:{len(segments)}")
    if frame_failures:
        integrity_blockers.append(f"FRAME_FAILURES:{len(frame_failures)}")
    if len(candidate_results) != EXPECTED_CANDIDATES:
        integrity_blockers.append(f"RESULT_COUNT_INVALID:{len(candidate_results)}")
    if any(row["coverage_ready"] and row["stress_cell_count"] != EXPECTED_STRESS_CELLS for row in candidate_results):
        integrity_blockers.append("CANDIDATE_CELL_COUNT_INVALID")
    if global_failures:
        integrity_blockers.append(f"EXECUTION_FAILURES:{len(global_failures)}")
    if mutation_paths:
        integrity_blockers.append(f"INPUT_MUTATION:{len(mutation_paths)}")

    classification_counts = dict(sorted(Counter(row["classification"] for row in candidate_results).items()))
    robust_rows = [row for row in candidate_results if row["classification"] == "ROBUST_SURVIVOR"]
    conditional_rows = [row for row in candidate_results if row["classification"] == "CONDITIONAL_SURVIVOR"]
    observer_rows = [row for row in candidate_results if row["classification"] == "OBSERVER_RETIRE"]

    state = "PASS_REMAINING_SURVIVOR_INDEPENDENT_OOS_BATCH" if not integrity_blockers else "HOLD_REMAINING_SURVIVOR_INDEPENDENT_OOS_BATCH_INTEGRITY"
    next_stage = "R7.A4D2_CANONICAL25_ROLE_AND_REPLAY_COVERAGE_AUDIT" if not integrity_blockers else "R7.A4D2_REMAINING_SURVIVOR_INDEPENDENT_OOS_BATCH_REPAIR"
    output = root / OUTPUT_DIR
    trade_count, trade_sha = atomic_jsonl(output / "remaining_oos_trade_rows_v1.jsonl", all_trade_rows)
    cell_count, cell_sha = atomic_jsonl(output / "remaining_oos_cell_rows_v1.jsonl", all_cell_rows)
    atomic_json(output / "remaining_oos_selected_segments_v1.json", {
        "state": "PASS_REMAINING_OOS_SEGMENT_SELECTION" if segment_gate else "HOLD_REMAINING_OOS_SEGMENT_SELECTION",
        "selection_policy": "DISJOINT_SOURCE_OR_STRICT_FORWARD_CHRONOLOGICAL_NO_PERFORMANCE_SELECTION",
        "segment_count": len(segments),
        "segments": segments,
        "rejected_sources": rejected_sources,
        "overlap_reject_count": overlap_reject_count,
    })
    summary = {
        "schema": "r7a4d2_remaining_survivor_independent_oos_batch_execution_v1",
        "official_stage": "R7.A4D2_REMAINING_SURVIVOR_INDEPENDENT_OOS_BATCH_EXECUTION",
        "state": state,
        "target_commit": args.target_sha,
        "blocker_count": len(integrity_blockers),
        "blockers": integrity_blockers,
        "selection_policy": "PRIOR_FIXED_LANE_BEST_EXCLUDING_MA5_NO_OOS_PERFORMANCE_RESELECTION",
        "candidate_count": len(candidate_results),
        "strict_forward_oos_segment_count": len(segments),
        "expected_stress_cells_per_candidate": EXPECTED_STRESS_CELLS,
        "classification_counts": classification_counts,
        "robust_survivor_count": len(robust_rows),
        "conditional_survivor_count": len(conditional_rows),
        "observer_retire_count": len(observer_rows),
        "robust_survivors": [{"lane_id": row["lane_id"], "variant_id": row["variant_id"]} for row in robust_rows],
        "conditional_survivors": [{"lane_id": row["lane_id"], "variant_id": row["variant_id"]} for row in conditional_rows],
        "observer_retire": [{"lane_id": row["lane_id"], "variant_id": row["variant_id"]} for row in observer_rows],
        "candidate_results": candidate_results,
        "trade_row_count": trade_count,
        "trade_sha256": trade_sha,
        "cell_row_count": cell_count,
        "cell_sha256": cell_sha,
        "rejected_market_sources": rejected_sources,
        "overlap_reject_count": overlap_reject_count,
        "execution_failures": global_failures[:100],
        "mutation_path_count": len(mutation_paths),
        "mutation_paths": mutation_paths,
        "parameter_optimization_allowed": False,
        "candidate_reselection_allowed": False,
        "strategy_mutation_allowed": False,
        "registry_mutation_allowed": False,
        "config_mutation_allowed": False,
        "router_mutation_allowed": False,
        "service_mutation_allowed": False,
        "shadow_start_allowed": False,
        "paper_live_order_allowed": False,
        "next_stage": next_stage,
    }
    atomic_json(output / "remaining_survivor_independent_oos_batch_summary_v1.json", summary)

    print("STATE=" + state)
    print("BLOCKER_COUNT=" + str(len(integrity_blockers)))
    print("STRICT_FORWARD_OOS_SEGMENT_COUNT=" + str(len(segments)))
    print("OOS_CANDIDATE_COUNT=" + str(len(candidate_results)))
    print("EXPECTED_TOTAL_STRESS_CELLS=" + str(EXPECTED_CANDIDATES * EXPECTED_STRESS_CELLS))
    print("ACTUAL_CELL_ROW_COUNT=" + str(cell_count))
    print("ROBUST_SURVIVOR_COUNT=" + str(len(robust_rows)))
    print("CONDITIONAL_SURVIVOR_COUNT=" + str(len(conditional_rows)))
    print("OBSERVER_RETIRE_COUNT=" + str(len(observer_rows)))
    for row in candidate_results:
        base = row["profile_metrics"]["base"]
        adverse = row["profile_metrics"]["adverse"]
        severe = row["profile_metrics"]["severe"]
        print(
            "OOS_RESULT="
            f"{row['lane_id']}|{row['variant_id']}|CLASS={row['classification']}|"
            f"EVENTS={row['unique_signal_count']}|SYMBOLS={row['signal_symbol_count']}|FOLDS={row['signal_fold_count']}|"
            f"BASE_R={base['net_r_sum']:.12f}|BASE_PF={base['profit_factor']:.12f}|BASE_POS={base['positive_fold_count']}/{EXPECTED_FOLDS}|"
            f"ADVERSE_R={adverse['net_r_sum']:.12f}|ADVERSE_PF={adverse['profit_factor']:.12f}|ADVERSE_POS={adverse['positive_fold_count']}/{EXPECTED_FOLDS}|"
            f"SEVERE_R={severe['net_r_sum']:.12f}|SEVERE_PF={severe['profit_factor']:.12f}|SEVERE_POS={severe['positive_fold_count']}/{EXPECTED_FOLDS}"
        )
    print("MUTATION_PATH_COUNT=" + str(len(mutation_paths)))
    print("SUMMARY_JSON=" + str(output / "remaining_survivor_independent_oos_batch_summary_v1.json"))
    print("NEXT_STAGE=" + next_stage)
    print("BLOCKERS=" + json.dumps(integrity_blockers))
    print("RC=" + ("0" if not integrity_blockers else "2"))
    return 0 if not integrity_blockers else 2


if __name__ == "__main__":
    raise SystemExit(main())
