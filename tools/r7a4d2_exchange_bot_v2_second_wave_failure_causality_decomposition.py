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
from typing import Any, Iterable

import numpy as np
import pandas as pd

SUMMARY_PATH = Path("runtime/r7a4d2_exchange_bot_v2_all_11_second_wave_execution_132/all_11_second_wave_summary_v1.json")
TRADE_PATH = Path("runtime/r7a4d2_exchange_bot_v2_all_11_second_wave_execution_132/second_wave_trade_rows_v1.jsonl")
CELL_PATH = Path("runtime/r7a4d2_exchange_bot_v2_all_11_second_wave_execution_132/second_wave_cell_rows_v1.jsonl")
PLAN_PATH = Path("runtime/r7a4d2_exchange_bot_v2_all_11_second_wave_execution_plan/all_11_second_wave_plan_v1.json")
MANIFEST_PATH = Path("runtime/r7a4c_historical_simulation_input_lineage/selected_input_manifest_v1.json")
OUTPUT_DIR = Path("runtime/r7a4d2_exchange_bot_v2_second_wave_failure_causality_decomposition")

EXPECTED_LANES = 11
EXPECTED_BUNDLES = 22
EXPECTED_CELLS = 132
EXPECTED_SEGMENTS = 24
EXPECTED_FOLDS = 6
MINIMUM_TRADES = 24
MINIMUM_POSITIVE_FOLDS = 4
ATR5_CONTROL_LANE = "dual_atr_volatility_bot:5m"
REFERENCE_LANE = "dual_donchian_trend_bot:15m"

BASE_CELL = ("cost_profile_0", "timing_0")
ADVERSE_CELL = ("cost_profile_1", "timing_1")
SEVERE_CELL = ("cost_profile_2", "timing_1")

REPAIR_AXES: dict[str, list[str]] = {
    "SEVERE_MARGIN_THIN": [
        "TIMEOUT_MFE_CAPTURE_DEFENSE",
        "MAKER_FIRST_COST_FLOOR",
    ],
    "SAMPLE_STARVATION": [
        "HISTORICAL_SEGMENT_EXPANSION_NO_THRESHOLD_RELAXATION",
        "NATIVE_TIMEFRAME_REENTRY_COVERAGE",
    ],
    "ROUTE_DISCONNECTION": [
        "CONTEXT_TO_EXECUTION_ROUTE_REBIND",
        "ZERO_SIGNAL_COVERAGE_GUARD",
    ],
    "COST_FRAGILITY": [
        "MAKER_FIRST_COST_ADMISSION",
        "TARGET_TO_COST_FLOOR_AND_TIMEOUT_REPRICE",
    ],
    "WALK_FORWARD_INSTABILITY": [
        "NEGATIVE_FOLD_REGIME_SYMBOL_VETO",
        "FOLD_BALANCED_REENTRY_OR_COOLDOWN",
    ],
    "REGIME_MISPLACEMENT": [
        "FAMILY_REGIME_HARD_ADMISSION",
        "CONTEXT_TIMEFRAME_ROUTE_SPLIT",
    ],
    "EXIT_GEOMETRY_FAILURE": [
        "MFE_CAPTURE_PARTIAL_OR_RULE_EXIT",
        "MAE_EARLY_FAILURE_ABORT",
    ],
    "SIDE_ASYMMETRY": [
        "SIDE_SPECIFIC_ADMISSION",
        "SIDE_SPECIFIC_EXIT_GEOMETRY",
    ],
    "NEGATIVE_EDGE": [
        "FAMILY_HYPOTHESIS_REBUILD",
        "REPLACE_WITH_ORTHOGONAL_SIBLING_FACTOR",
    ],
    "NO_INCREMENTAL_EDGE": [
        "ORTHOGONAL_FEATURE_ADDITION",
        "RETIRE_IF_REFERENCE_DELTA_NOT_POSITIVE",
    ],
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


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, 1):
            line = raw_line.strip()
            if not line:
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"JSONL_OBJECT_REQUIRED:{path}:{line_number}")
            rows.append(value)
    return rows


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


def finite(value: Any, default: float = 0.0) -> float:
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    return default


def median(values: Iterable[Any]) -> float | None:
    clean = [float(value) for value in values if isinstance(value, (int, float)) and math.isfinite(float(value))]
    return statistics.median(clean) if clean else None


def safe_ratio(numerator: float, denominator: float, default: float = 0.0) -> float:
    return numerator / denominator if math.isfinite(numerator) and math.isfinite(denominator) and abs(denominator) > 1e-12 else default


def summarize_partition(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get(key) or "UNKNOWN")].append(row)
    output: list[dict[str, Any]] = []
    for value, group in sorted(grouped.items()):
        pnl = sum(finite(row.get("net_return_pct")) for row in group)
        gross = sum(finite(row.get("gross_return_pct")) for row in group)
        wins = sum(finite(row.get("net_return_pct")) > 0 for row in group)
        output.append(
            {
                key: value,
                "trade_count": len(group),
                "win_count": wins,
                "win_rate_pct": 100.0 * wins / len(group) if group else 0.0,
                "net_pnl_sum_pct": pnl,
                "gross_pnl_sum_pct": gross,
                "net_r_sum": sum(finite(row.get("net_r")) for row in group),
                "median_mfe_r": median(row.get("mfe_r") for row in group),
                "median_mae_r": median(row.get("mae_r") for row in group),
            }
        )
    return output


def cell_key(row: dict[str, Any]) -> tuple[str, str]:
    return str(row.get("cost_profile_id") or ""), str(row.get("timing_id") or "")


def gate_failures(metrics: dict[str, Any]) -> list[str]:
    status = metrics.get("gate_status") or {}
    return sorted(str(key) for key, passed in status.items() if not bool(passed))


def add_excursions(
    root: Path,
    trades: list[dict[str, Any]],
    manifest: dict[str, Any],
    raw: Any,
) -> list[dict[str, Any]]:
    segments = {
        str(row["segment_id"]): row
        for row in manifest.get("selected_segments", [])
        if isinstance(row, dict) and row.get("segment_id")
    }
    source_sha = {
        str(row.get("source_path")): str(row.get("source_sha256") or "")
        for row in manifest.get("selected_segments", [])
        if isinstance(row, dict)
    }
    source_cache: dict[str, pd.DataFrame] = {}
    frame_cache: dict[tuple[str, str], pd.DataFrame] = {}
    output: list[dict[str, Any]] = []
    for trade in trades:
        row = dict(trade)
        segment_id = str(row.get("segment_id") or "")
        timeframe = str(row.get("execution_timeframe") or "")
        segment = segments.get(segment_id)
        if segment is None or timeframe not in {"5m", "15m"}:
            row.update({"mfe_pct": None, "mae_pct": None, "mfe_r": None, "mae_r": None, "mfe_capture_ratio": None})
            output.append(row)
            continue
        source_path = str(segment["source_path"])
        if source_path not in source_cache:
            safe_path = root / raw.safe_repo_path(source_path)
            source_cache[source_path] = raw.fixed_ohlcv_frame(safe_path, source_sha.get(source_path, ""))
        cache_key = (segment_id, timeframe)
        if cache_key not in frame_cache:
            frame_cache[cache_key] = raw.resample_for_segment(
                source_cache[source_path],
                int(segment["start_row"]),
                int(segment["end_row_exclusive"]),
                timeframe,
            )
        frame = frame_cache[cache_key]
        entry_index = int(row.get("entry_index") or 0)
        exit_index = int(row.get("exit_index") or entry_index)
        entry = finite(row.get("entry_price"), math.nan)
        risk_pct = finite(row.get("risk_pct"), math.nan)
        side = str(row.get("side") or "")
        if (
            not math.isfinite(entry)
            or entry <= 0
            or entry_index < 0
            or exit_index < entry_index
            or exit_index >= len(frame)
        ):
            row.update({"mfe_pct": None, "mae_pct": None, "mfe_r": None, "mae_r": None, "mfe_capture_ratio": None})
            output.append(row)
            continue
        window = frame.iloc[entry_index : exit_index + 1]
        high = finite(window["high"].astype(float).max(), entry)
        low = finite(window["low"].astype(float).min(), entry)
        if side == "long":
            mfe_pct = max(0.0, (high - entry) / entry * 100.0)
            mae_pct = max(0.0, (entry - low) / entry * 100.0)
        elif side == "short":
            mfe_pct = max(0.0, (entry - low) / entry * 100.0)
            mae_pct = max(0.0, (high - entry) / entry * 100.0)
        else:
            mfe_pct = mae_pct = math.nan
        mfe_r = mfe_pct / risk_pct if math.isfinite(risk_pct) and risk_pct > 0 and math.isfinite(mfe_pct) else math.nan
        mae_r = mae_pct / risk_pct if math.isfinite(risk_pct) and risk_pct > 0 and math.isfinite(mae_pct) else math.nan
        gross = finite(row.get("gross_return_pct"), math.nan)
        capture = gross / mfe_pct if math.isfinite(gross) and math.isfinite(mfe_pct) and mfe_pct > 1e-12 else math.nan
        row.update(
            {
                "mfe_pct": mfe_pct if math.isfinite(mfe_pct) else None,
                "mae_pct": mae_pct if math.isfinite(mae_pct) else None,
                "mfe_r": mfe_r if math.isfinite(mfe_r) else None,
                "mae_r": mae_r if math.isfinite(mae_r) else None,
                "mfe_capture_ratio": capture if math.isfinite(capture) else None,
            }
        )
        output.append(row)
    return output


def intended_regimes(lane_id: str) -> set[str]:
    if "grid" in lane_id or "vwap" in lane_id:
        return {"range", "shock_recovery"} if "vwap" in lane_id else {"range"}
    return {"trend_up", "trend_down", "shock_recovery"}


def negative_share_outside_intended(rows: list[dict[str, Any]], lane_id: str) -> float:
    intended = intended_regimes(lane_id)
    losses = [row for row in rows if finite(row.get("net_return_pct")) < 0]
    total_loss = sum(abs(finite(row.get("net_return_pct"))) for row in losses)
    outside_loss = sum(
        abs(finite(row.get("net_return_pct")))
        for row in losses
        if str(row.get("regime") or "") not in intended
    )
    return safe_ratio(outside_loss, total_loss)


def side_asymmetry(rows: list[dict[str, Any]]) -> tuple[float, dict[str, float]]:
    pnl = {
        side: sum(finite(row.get("net_return_pct")) for row in rows if str(row.get("side")) == side)
        for side in ("long", "short")
    }
    absolute = abs(pnl["long"]) + abs(pnl["short"])
    asymmetry = abs(pnl["long"] - pnl["short"]) / absolute if absolute > 1e-12 else 0.0
    return asymmetry, pnl


def diagnose_lane(
    lane_row: dict[str, Any],
    variant_rows: list[dict[str, Any]],
    selected_trades: list[dict[str, Any]],
    selected_cells: list[dict[str, Any]],
) -> dict[str, Any]:
    lane_id = str(lane_row["source_lane_id"])
    variant_id = str(lane_row["variant_id"])
    cells = {cell_key(row): row for row in selected_cells}
    base = cells.get(BASE_CELL, lane_row.get("base_metrics") or {})
    adverse = cells.get(ADVERSE_CELL, lane_row.get("adverse_metrics") or {})
    severe = cells.get(SEVERE_CELL, lane_row.get("severe_tail_metrics") or {})
    base_trades = [row for row in selected_trades if cell_key(row) == BASE_CELL]

    signal_count = int(lane_row.get("signal_count") or 0)
    base_count = int(base.get("trade_count") or len(base_trades))
    adverse_folds = int((adverse.get("fold_metrics") or {}).get("positive_fold_count") or 0)
    base_pnl = finite(base.get("net_pnl_sum_pct"))
    adverse_pnl = finite(adverse.get("net_pnl_sum_pct"))
    severe_pnl = finite(severe.get("net_pnl_sum_pct"))
    base_pf = finite(base.get("profit_factor"))
    adverse_pf = finite(adverse.get("profit_factor"))
    severe_pf = finite(severe.get("profit_factor"))
    outside_share = negative_share_outside_intended(base_trades, lane_id)
    asymmetry, side_pnl = side_asymmetry(base_trades)
    exit_hist = Counter(str(row.get("exit_reason") or "UNKNOWN") for row in base_trades)
    timeout_stop_rate = safe_ratio(
        exit_hist.get("rule_exit_or_timeout", 0) + exit_hist.get("stop", 0),
        max(len(base_trades), 1),
    )
    median_mfe_r = median(row.get("mfe_r") for row in base_trades)
    median_mae_r = median(row.get("mae_r") for row in base_trades)
    median_capture = median(row.get("mfe_capture_ratio") for row in base_trades)
    uplift_pass = bool(lane_row.get("uplift_discovery_pass"))

    secondary: list[str] = []
    if base_count < MINIMUM_TRADES:
        secondary.append("SAMPLE_DEFICIT")
    if adverse_folds < MINIMUM_POSITIVE_FOLDS:
        secondary.append("ADVERSE_FOLD_DEFICIT")
    if severe_pnl <= 0 or severe_pf <= 1.0:
        secondary.append("SEVERE_NEGATIVE")
    elif severe_pnl < 0.50 or severe_pf < 1.20:
        secondary.append("SEVERE_MARGIN_THIN")
    if outside_share >= 0.50:
        secondary.append("REGIME_LOSS_CONCENTRATION")
    if asymmetry >= 0.70 and side_pnl["long"] * side_pnl["short"] <= 0:
        secondary.append("SIDE_ASYMMETRY")
    if timeout_stop_rate >= 0.65:
        secondary.append("EXIT_FAILURE_CONCENTRATION")
    if median_mfe_r is not None and median_mfe_r >= 0.80 and (median_capture is None or median_capture < 0.35):
        secondary.append("MFE_CAPTURE_FAILURE")

    if lane_id == ATR5_CONTROL_LANE and uplift_pass:
        primary = "SEVERE_MARGIN_THIN"
    elif base_count < MINIMUM_TRADES:
        primary = "ROUTE_DISCONNECTION" if signal_count < max(12, MINIMUM_TRADES // 2) else "SAMPLE_STARVATION"
    elif bool(base.get("economic_pass")) and not bool(adverse.get("economic_pass")):
        if adverse_pnl > 0 and adverse_pf > 1.0 and adverse_folds < MINIMUM_POSITIVE_FOLDS:
            primary = "WALK_FORWARD_INSTABILITY"
        else:
            primary = "COST_FRAGILITY"
    elif base_pnl <= 0 or base_pf <= 1.0:
        if outside_share >= 0.50:
            primary = "REGIME_MISPLACEMENT"
        elif timeout_stop_rate >= 0.65 and median_mfe_r is not None and median_mfe_r >= 0.60:
            primary = "EXIT_GEOMETRY_FAILURE"
        elif asymmetry >= 0.70 and side_pnl["long"] * side_pnl["short"] <= 0:
            primary = "SIDE_ASYMMETRY"
        else:
            primary = "NEGATIVE_EDGE"
    elif adverse_folds < MINIMUM_POSITIVE_FOLDS:
        primary = "WALK_FORWARD_INSTABILITY"
    elif not uplift_pass:
        primary = "NO_INCREMENTAL_EDGE"
    else:
        primary = "SEVERE_MARGIN_THIN"

    axes = REPAIR_AXES[primary][:2]
    variant_comparison = [
        {
            "variant_id": str(row.get("variant_id")),
            "uplift_discovery_pass": bool(row.get("uplift_discovery_pass")),
            "candidate_risk_score": finite(row.get("candidate_risk_score")),
            "base_trade_count": int((row.get("base_metrics") or {}).get("trade_count") or 0),
            "base_net_pnl_sum_pct": finite((row.get("base_metrics") or {}).get("net_pnl_sum_pct")),
            "adverse_net_pnl_sum_pct": finite((row.get("adverse_metrics") or {}).get("net_pnl_sum_pct")),
            "severe_net_pnl_sum_pct": finite((row.get("severe_tail_metrics") or {}).get("net_pnl_sum_pct")),
        }
        for row in sorted(variant_rows, key=lambda item: str(item.get("variant_id")))
    ]
    return {
        "lane_id": lane_id,
        "selected_variant_id": variant_id,
        "control_preserved": lane_id == ATR5_CONTROL_LANE,
        "uplift_discovery_pass": uplift_pass,
        "primary_cause": primary,
        "secondary_causes": sorted(set(secondary)),
        "target_repair_axes": axes,
        "signal_count": signal_count,
        "base_trade_count": base_count,
        "base_gate_failures": gate_failures(base),
        "adverse_gate_failures": gate_failures(adverse),
        "severe_gate_failures": gate_failures(severe),
        "base_net_pnl_sum_pct": base_pnl,
        "adverse_net_pnl_sum_pct": adverse_pnl,
        "severe_net_pnl_sum_pct": severe_pnl,
        "base_profit_factor": base_pf,
        "adverse_profit_factor": adverse_pf,
        "severe_profit_factor": severe_pf,
        "adverse_positive_fold_count": adverse_folds,
        "outside_intended_regime_loss_share": outside_share,
        "side_net_pnl_sum_pct": side_pnl,
        "side_asymmetry_score": asymmetry,
        "exit_histogram": dict(sorted(exit_hist.items())),
        "timeout_stop_rate": timeout_stop_rate,
        "median_mfe_r": median_mfe_r,
        "median_mae_r": median_mae_r,
        "median_mfe_capture_ratio": median_capture,
        "regime_breakdown": summarize_partition(base_trades, "regime"),
        "symbol_breakdown": summarize_partition(base_trades, "symbol"),
        "side_breakdown": summarize_partition(base_trades, "side"),
        "exit_breakdown": summarize_partition(base_trades, "exit_reason"),
        "fold_breakdown": summarize_partition(base_trades, "fold"),
        "variant_comparison": variant_comparison,
    }


def self_test() -> int:
    pass_row = {
        "source_lane_id": ATR5_CONTROL_LANE,
        "variant_id": "atr5_impulse_15m_alignment",
        "signal_count": 28,
        "uplift_discovery_pass": True,
        "base_metrics": {"economic_pass": True, "trade_count": 27, "net_pnl_sum_pct": 8.2, "profit_factor": 6.0, "gate_status": {}},
        "adverse_metrics": {"economic_pass": True, "trade_count": 27, "net_pnl_sum_pct": 3.0, "profit_factor": 2.1, "fold_metrics": {"positive_fold_count": 5}, "gate_status": {}},
        "severe_tail_metrics": {"economic_pass": True, "trade_count": 27, "net_pnl_sum_pct": 0.03, "profit_factor": 1.14, "gate_status": {}},
    }
    trades = [
        {
            "cost_profile_id": "cost_profile_0",
            "timing_id": "timing_0",
            "net_return_pct": 0.2,
            "gross_return_pct": 0.3,
            "net_r": 0.4,
            "regime": "trend_up",
            "symbol": "BTCUSDT",
            "side": "long",
            "exit_reason": "rule_exit_or_timeout",
            "mfe_r": 1.0,
            "mae_r": 0.2,
            "mfe_capture_ratio": 0.2,
        }
    ] * 27
    result = diagnose_lane(pass_row, [pass_row], trades, [])
    assert result["primary_cause"] == "SEVERE_MARGIN_THIN"
    assert len(result["target_repair_axes"]) == 2

    starved = dict(pass_row)
    starved.update({
        "source_lane_id": "dual_ma_trend_bot:15m",
        "variant_id": "ma15",
        "signal_count": 5,
        "uplift_discovery_pass": False,
        "base_metrics": {"economic_pass": False, "trade_count": 5, "net_pnl_sum_pct": 3.0, "profit_factor": 2.0, "gate_status": {"trade_gate": False}},
    })
    starved_result = diagnose_lane(starved, [starved], [], [])
    assert starved_result["primary_cause"] == "ROUTE_DISCONNECTION"
    print("STATE=PASS_SECOND_WAVE_FAILURE_CAUSALITY_DECOMPOSITION_SELF_TEST")
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
    raw = import_module(Path(args.raw_module).resolve(), "r7a4d2_causality_raw")
    helper = import_module(Path(args.helper_module).resolve(), "r7a4d2_causality_helper")
    contract = load_json(Path(args.a4d_contract).resolve())

    required = [
        root / SUMMARY_PATH,
        root / TRADE_PATH,
        root / CELL_PATH,
        root / PLAN_PATH,
        root / MANIFEST_PATH,
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        print("STATE=HOLD_SECOND_WAVE_FAILURE_CAUSALITY_DECOMPOSITION_INPUT")
        print("BLOCKER_COUNT=1")
        print("BLOCKERS=" + json.dumps(["REQUIRED_EVIDENCE_MISSING:" + ",".join(missing)]))
        print("RC=2")
        return 2

    summary = load_json(root / SUMMARY_PATH)
    plan = load_json(root / PLAN_PATH)
    manifest = load_json(root / MANIFEST_PATH)
    trades = load_jsonl(root / TRADE_PATH)
    cells = load_jsonl(root / CELL_PATH)
    blockers: list[str] = []

    if summary.get("state") != "PASS_EXCHANGE_BOT_V2_ALL_11_SECOND_WAVE_EXECUTION_132":
        blockers.append("SECOND_WAVE_SUMMARY_NOT_PASS")
    if int(summary.get("bundle_count") or 0) != EXPECTED_BUNDLES:
        blockers.append(f"BUNDLE_COUNT_INVALID:{summary.get('bundle_count')}")
    if int(summary.get("cell_result_count") or 0) != EXPECTED_CELLS or len(cells) != EXPECTED_CELLS:
        blockers.append(f"CELL_COUNT_INVALID:{len(cells)}")
    lane_best_rows = [row for row in summary.get("lane_best_rows", []) if isinstance(row, dict)]
    if len(lane_best_rows) != EXPECTED_LANES:
        blockers.append(f"LANE_COUNT_INVALID:{len(lane_best_rows)}")
    if len(manifest.get("selected_segments", [])) != EXPECTED_SEGMENTS:
        blockers.append(f"SEGMENT_COUNT_INVALID:{len(manifest.get('selected_segments', []))}")
    if ATR5_CONTROL_LANE not in {str(row.get("source_lane_id")) for row in lane_best_rows}:
        blockers.append("ATR5_CONTROL_LANE_MISSING")
    if int(summary.get("uplifted_lane_count") or 0) != 1 or summary.get("uplifted_lane_ids") != [ATR5_CONTROL_LANE]:
        blockers.append("UPLIFTED_LANE_SET_INVALID")

    if blockers:
        print("STATE=HOLD_SECOND_WAVE_FAILURE_CAUSALITY_DECOMPOSITION_INPUT")
        print("BLOCKER_COUNT=" + str(len(blockers)))
        print("BLOCKERS=" + json.dumps(blockers))
        print("RC=2")
        return 2

    source_paths = sorted({
        str(row.get("source_path"))
        for row in manifest.get("selected_segments", [])
        if isinstance(row, dict) and row.get("source_path")
    })
    selected = [root / raw.safe_repo_path(path) for path in source_paths]
    protected = [Path(str(value)) for value in contract.get("protected_paths", [])]
    before = helper.snapshot(required + selected + protected)

    enriched_trades = add_excursions(root, trades, manifest, raw)
    bundle_rows = [row for row in plan.get("second_wave_rows", []) if isinstance(row, dict)]
    lane_variants: dict[str, list[dict[str, Any]]] = defaultdict(list)
    summary_bundle_rows = [row for row in summary.get("lane_best_rows", []) if isinstance(row, dict)]
    cell_by_variant: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in cells:
        cell_by_variant[str(row.get("variant_id") or "")].append(row)
    plan_by_variant = {str(row.get("variant_id")): row for row in bundle_rows}
    selected_by_lane = {str(row["source_lane_id"]): row for row in summary_bundle_rows}
    for variant_id, variant_cells in cell_by_variant.items():
        if not variant_id or variant_id not in plan_by_variant:
            continue
        bundle = plan_by_variant[variant_id]
        lane_id = str(bundle.get("lane_id") or "")
        mapping = {cell_key(row): row for row in variant_cells}
        base = mapping.get(BASE_CELL, {})
        adverse = mapping.get(ADVERSE_CELL, {})
        severe = mapping.get(SEVERE_CELL, {})
        lane_variants[lane_id].append(
            {
                "variant_id": variant_id,
                "uplift_discovery_pass": bool(
                    lane_id == str(selected_by_lane.get(lane_id, {}).get("source_lane_id"))
                    and variant_id == str(selected_by_lane.get(lane_id, {}).get("variant_id"))
                    and selected_by_lane.get(lane_id, {}).get("uplift_discovery_pass")
                ),
                "candidate_risk_score": finite(
                    selected_by_lane.get(lane_id, {}).get("candidate_risk_score")
                    if variant_id == str(selected_by_lane.get(lane_id, {}).get("variant_id"))
                    else 0.0
                ),
                "base_metrics": base,
                "adverse_metrics": adverse,
                "severe_tail_metrics": severe,
            }
        )

    lane_rows: list[dict[str, Any]] = []
    for lane_row in sorted(lane_best_rows, key=lambda row: str(row.get("source_lane_id"))):
        lane_id = str(lane_row["source_lane_id"])
        variant_id = str(lane_row["variant_id"])
        selected_trades = [
            row for row in enriched_trades
            if str(row.get("source_lane_id")) == lane_id and str(row.get("variant_id")) == variant_id
        ]
        selected_cells = [
            row for row in cells
            if str(row.get("source_lane_id")) == lane_id and str(row.get("variant_id")) == variant_id
        ]
        lane_rows.append(
            diagnose_lane(
                lane_row,
                lane_variants.get(lane_id, [lane_row]),
                selected_trades,
                selected_cells,
            )
        )

    primary_hist = Counter(str(row["primary_cause"]) for row in lane_rows)
    repair_rows: list[dict[str, Any]] = []
    for row in lane_rows:
        for ordinal, axis in enumerate(row["target_repair_axes"], 1):
            repair_rows.append(
                {
                    "lane_id": row["lane_id"],
                    "source_variant_id": row["selected_variant_id"],
                    "repair_number": ordinal,
                    "repair_axis": axis,
                    "primary_cause": row["primary_cause"],
                    "control_preserved": row["control_preserved"],
                    "parameter_optimization_allowed": False,
                    "blind_stop_widening_allowed": False,
                    "entry_threshold_relaxation_allowed": False,
                    "future_validation_selection_allowed": False,
                }
            )

    output = root / OUTPUT_DIR
    lane_count, lane_sha = atomic_jsonl(output / "lane_causality_rows_v1.jsonl", lane_rows)
    repair_count, repair_sha = atomic_jsonl(output / "target_repair_rows_v1.jsonl", repair_rows)
    result = {
        "state": "PASS_SECOND_WAVE_FAILURE_CAUSALITY_DECOMPOSITION",
        "target_sha": args.target_sha,
        "source_summary_path": str(root / SUMMARY_PATH),
        "lane_count": lane_count,
        "repair_row_count": repair_count,
        "expected_third_wave_bundle_count": repair_count,
        "expected_third_wave_cell_count": repair_count * 6,
        "atr5_control_lane": ATR5_CONTROL_LANE,
        "atr5_control_preserved": True,
        "reference_lane_id": REFERENCE_LANE,
        "primary_cause_histogram": dict(sorted(primary_hist.items())),
        "lane_causality_sha256": lane_sha,
        "target_repair_sha256": repair_sha,
        "lane_causality_rows": lane_rows,
        "target_repair_rows": repair_rows,
        "parameter_optimization_allowed": False,
        "blind_stop_widening_allowed": False,
        "entry_threshold_relaxation_allowed": False,
        "discovery_s_grade_label_allowed": False,
        "strategy_mutation_allowed": False,
        "market_source_mutation_allowed": False,
        "registry_mutation_allowed": False,
        "config_mutation_allowed": False,
        "router_mutation_allowed": False,
        "service_mutation_allowed": False,
        "shadow_start_allowed": False,
        "paper_live_order_allowed": False,
        "next_stage": "R7.A4D2_EXCHANGE_BOT_V2_THIRD_WAVE_TARGETED_REPAIR_EXECUTION_132",
    }
    atomic_json(output / "causality_and_repair_plan_v1.json", result)

    after = helper.snapshot(required + selected + protected)
    mutations = helper.diff_snapshot(before, after)
    final_blockers: list[str] = []
    if lane_count != EXPECTED_LANES:
        final_blockers.append(f"LANE_COUNT_INVALID:{lane_count}")
    if repair_count != EXPECTED_LANES * 2:
        final_blockers.append(f"REPAIR_ROW_COUNT_INVALID:{repair_count}")
    if mutations:
        final_blockers.append(f"PROTECTED_MUTATIONS:{len(mutations)}")
    if final_blockers:
        print("STATE=HOLD_SECOND_WAVE_FAILURE_CAUSALITY_DECOMPOSITION")
        print("BLOCKER_COUNT=" + str(len(final_blockers)))
        print("BLOCKERS=" + json.dumps(final_blockers))
        print("RC=2")
        return 2

    print("STATE=PASS_SECOND_WAVE_FAILURE_CAUSALITY_DECOMPOSITION")
    print("BLOCKER_COUNT=0")
    print("LANE_COUNT=" + str(lane_count))
    print("ATR5_CONTROL_PRESERVED=true")
    print("PRIMARY_CAUSE_HISTOGRAM=" + json.dumps(result["primary_cause_histogram"], sort_keys=True))
    print("TARGET_REPAIR_ROW_COUNT=" + str(repair_count))
    print("EXPECTED_THIRD_WAVE_BUNDLE_COUNT=" + str(repair_count))
    print("EXPECTED_THIRD_WAVE_CELL_COUNT=" + str(repair_count * 6))
    print("LANE_CAUSALITY_ROWS=" + json.dumps(lane_rows, sort_keys=True))
    print("PLAN_JSON=" + str(output / "causality_and_repair_plan_v1.json"))
    print("NEXT_STAGE=" + result["next_stage"])
    print("BLOCKERS=[]")
    print("RC=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
