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

DEFECT2_SUMMARY = Path("runtime/r7a4d2_incremental_defect2_execution/incremental_defect2_summary_v1.json")
DEFECT2_TRADES = Path("runtime/r7a4d2_incremental_defect2_execution/incremental_defect2_trade_rows_v1.jsonl")
DEFECT2_CELLS = Path("runtime/r7a4d2_incremental_defect2_execution/incremental_defect2_cell_rows_v1.jsonl")
SECOND_SUMMARY = Path("runtime/r7a4d2_exchange_bot_v2_all_11_second_wave_execution_132/all_11_second_wave_summary_v1.json")
SECOND_TRADES = Path("runtime/r7a4d2_exchange_bot_v2_all_11_second_wave_execution_132/second_wave_trade_rows_v1.jsonl")
MANIFEST_PATH = Path("runtime/r7a4c_historical_simulation_input_lineage/selected_input_manifest_v1.json")
DEFECT3_AUDIT = Path("runtime/r7a4d2_incremental_defect3_consecutive_loss_causality_audit/incremental_defect3_consecutive_loss_causality_audit_v1.json")
OUTPUT_DIR = Path("runtime/r7a4d2_incremental_defect3b_payoff_geometry_all_loss_audit")

ATR5 = "dual_atr_volatility_bot:5m"
ATR15 = "dual_atr_volatility_bot:15m"
MA5 = "dual_ma_trend_bot:5m"
ACTIVE_LANES = (ATR5, ATR15, MA5)
DISCOVERY_FOLDS = {0, 1, 2}
VALIDATION_FOLDS = {3, 4, 5}
PROFILE_ORDER = ("base", "adverse", "severe")
MIN_CLUSTER_SPLIT_TRADES = 2
MIN_CLUSTER_TOTAL_TRADES = 4
MIN_REMAINING_TRADES = 24
MIN_REMAINING_SYMBOLS = 3
MAX_ACTIVE_REPAIR_LANES = 3

MECHANISM_TO_AXIS = {
    "COST_EROSION": "EXECUTION_COST_ADMISSION",
    "EXIT_CAPTURE_FAILURE": "MFE_CAPTURE_EXIT_GEOMETRY",
    "TIMEOUT_DRIFT": "TIME_DECAY_EXIT_STATE",
    "NO_FAVORABLE_EXCURSION": "ENTRY_REGIME_SPECIALIZATION",
    "FAST_STOP_VOLATILITY": "POST_SHOCK_COOLDOWN",
    "REENTRY_CHURN": "STATE_RESET_COOLDOWN",
    "WINNER_CAPTURE_COMPRESSION": "WINNER_CAPTURE_GEOMETRY",
    "MIXED_LOSS_MECHANISM": "READ_ONLY_SUBCLUSTER_REQUIRED",
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
        for line_number, raw in enumerate(handle, 1):
            line = raw.strip()
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

def safe_mean(values: list[float]) -> float:
    return statistics.fmean(values) if values else 0.0

def safe_median(values: list[float]) -> float:
    return statistics.median(values) if values else 0.0

def net_r(row: dict[str, Any]) -> float:
    value = finite(row.get("net_r"), math.nan)
    if math.isfinite(value):
        return value
    risk = finite(row.get("risk_pct"), 0.0)
    return finite(row.get("net_return_pct"), 0.0) / risk if risk > 0 else 0.0

def gross_r(row: dict[str, Any]) -> float:
    value = finite(row.get("gross_r"), math.nan)
    if math.isfinite(value):
        return value
    risk = finite(row.get("risk_pct"), 0.0)
    return finite(row.get("gross_return_pct"), 0.0) / risk if risk > 0 else net_r(row)

def profile_rows(base: Any, rows: list[dict[str, Any]], lane: str, profile: str) -> list[dict[str, Any]]:
    return [
        row for row in rows
        if str(row.get("lane_id") or "") == lane and base.profile_name(row) == profile
    ]

def split_name(row: dict[str, Any]) -> str:
    fold = int(row.get("fold") if row.get("fold") is not None else -1)
    return "discovery" if fold in DISCOVERY_FOLDS else "validation"

def positive_fold_count(rows: list[dict[str, Any]]) -> int:
    pnl: dict[int, float] = defaultdict(float)
    for row in rows:
        fold = int(row.get("fold") if row.get("fold") is not None else -1)
        pnl[fold] += net_r(row)
    return sum(value > 0 for value in pnl.values())

def payoff_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    r_values = [net_r(row) for row in rows]
    wins = [value for value in r_values if value > 0]
    losses = [-value for value in r_values if value < 0]
    win_sum = sum(wins)
    loss_sum = sum(losses)
    pf = win_sum / loss_sum if loss_sum > 0 else (math.inf if win_sum > 0 else 0.0)
    avg_win = safe_mean(wins)
    avg_loss = safe_mean(losses)
    payoff = avg_win / avg_loss if avg_loss > 0 else (math.inf if avg_win > 0 else 0.0)

    mfe_values = [finite(row.get("mfe_r")) for row in rows]
    mae_values = [finite(row.get("mae_r")) for row in rows]
    winner_capture = [
        max(net_r(row), 0.0) / max(finite(row.get("mfe_r")), 1e-9)
        for row in rows
        if net_r(row) > 0 and finite(row.get("mfe_r")) > 0
    ]
    loss_rows = [row for row in rows if net_r(row) < 0]
    loss_abs_total = sum(-net_r(row) for row in loss_rows)
    mechanism_loss_r: dict[str, float] = defaultdict(float)
    for row in loss_rows:
        mechanism_loss_r[str(row.get("loss_mechanism") or "UNKNOWN")] += -net_r(row)

    cost_pct = sum(finite(row.get("total_cost_pct")) for row in rows)
    gross_pct = sum(max(finite(row.get("gross_return_pct")), 0.0) for row in rows)
    cost_to_positive_gross_ratio = cost_pct / gross_pct if gross_pct > 0 else math.inf

    return {
        "trade_count": len(rows),
        "symbol_count": len({str(row.get("symbol") or "") for row in rows}),
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate_pct": len(wins) / len(rows) * 100.0 if rows else 0.0,
        "net_r_sum": sum(r_values),
        "expectancy_r": safe_mean(r_values),
        "profit_factor": pf,
        "average_win_r": avg_win,
        "average_loss_r": avg_loss,
        "payoff_ratio": payoff,
        "median_winner_r": safe_median(wins),
        "median_loser_r": safe_median(losses),
        "median_mfe_r": safe_median(mfe_values),
        "median_mae_r": safe_median(mae_values),
        "median_winner_capture_ratio": safe_median(winner_capture),
        "positive_fold_count": positive_fold_count(rows),
        "cost_to_positive_gross_ratio": cost_to_positive_gross_ratio,
        "loss_mechanism_r_contribution": dict(sorted(mechanism_loss_r.items())),
        "loss_mechanism_pct_contribution": {
            key: value / loss_abs_total * 100.0 if loss_abs_total > 0 else 0.0
            for key, value in sorted(mechanism_loss_r.items())
        },
    }

def mechanism_events(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    ordered = sorted(
        rows,
        key=lambda row: (
            str(row.get("lane_id") or ""),
            str(row.get("symbol") or ""),
            int(row.get("fold") if row.get("fold") is not None else -1),
            finite(row.get("entry_timestamp")),
        ),
    )
    previous_by_key: dict[tuple[str, str, int], dict[str, Any]] = {}
    for row in ordered:
        lane = str(row.get("lane_id") or "")
        fold = int(row.get("fold") if row.get("fold") is not None else -1)
        symbol = str(row.get("symbol") or "")
        key = (lane, symbol, fold)
        nr = net_r(row)
        mechanism = str(row.get("loss_mechanism") or "UNKNOWN")
        if nr < 0:
            events.append({**row, "_mechanism": mechanism, "_leakage_r": -nr})
        elif nr > 0 and finite(row.get("mfe_r")) >= 1.0:
            capture = nr / max(finite(row.get("mfe_r")), 1e-9)
            if capture < 0.40:
                events.append({
                    **row,
                    "_mechanism": "WINNER_CAPTURE_COMPRESSION",
                    "_leakage_r": max(finite(row.get("mfe_r")) - nr, 0.0),
                })
        previous = previous_by_key.get(key)
        if previous is not None and net_r(previous) < 0:
            gap = int(row.get("entry_source_index") or 0) - int(previous.get("exit_source_index") or 0)
            factor = {"5m": 5, "15m": 15}.get(str(row.get("timeframe") or ""), 1)
            if gap / max(factor, 1) <= 2.0 and nr < 0:
                events.append({
                    **row,
                    "_mechanism": "REENTRY_CHURN",
                    "_leakage_r": -nr,
                })
        previous_by_key[key] = row
    return events

def cluster_rows(events: list[dict[str, Any]], all_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, str, str, str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in events:
        key = (
            str(row.get("lane_id") or ""),
            str(row.get("_profile") or ""),
            str(row.get("_mechanism") or ""),
            str(row.get("regime") or "UNKNOWN"),
            str(row.get("side") or "UNKNOWN"),
            str(row.get("signal_reason") or "UNKNOWN"),
            str(row.get("exit_reason") or "UNKNOWN"),
        )
        buckets[key].append(row)

    output: list[dict[str, Any]] = []
    for key, bucket in buckets.items():
        lane, profile, mechanism, regime, side, signal_reason, exit_reason = key
        discovery = [row for row in bucket if split_name(row) == "discovery"]
        validation = [row for row in bucket if split_name(row) == "validation"]
        discovery_leak = sum(finite(row.get("_leakage_r")) for row in discovery)
        validation_leak = sum(finite(row.get("_leakage_r")) for row in validation)
        cluster_ids = {
            (
                str(row.get("segment_id") or ""),
                int(row.get("entry_index") if row.get("entry_index") is not None else -1),
                int(row.get("fold") if row.get("fold") is not None else -1),
            )
            for row in bucket
        }
        lane_profile_rows = [
            row for row in all_rows
            if str(row.get("lane_id") or "") == lane and str(row.get("_profile") or "") == profile
        ]
        remaining = [
            row for row in lane_profile_rows
            if (
                str(row.get("segment_id") or ""),
                int(row.get("entry_index") if row.get("entry_index") is not None else -1),
                int(row.get("fold") if row.get("fold") is not None else -1),
            ) not in cluster_ids
        ]
        remaining_symbols = {str(row.get("symbol") or "") for row in remaining}
        persistent = (
            len(discovery) >= MIN_CLUSTER_SPLIT_TRADES
            and len(validation) >= MIN_CLUSTER_SPLIT_TRADES
            and len(bucket) >= MIN_CLUSTER_TOTAL_TRADES
            and discovery_leak > 0
            and validation_leak > 0
        )
        repair_executable = (
            persistent
            and len(remaining) >= MIN_REMAINING_TRADES
            and len(remaining_symbols) >= MIN_REMAINING_SYMBOLS
            and mechanism != "MIXED_LOSS_MECHANISM"
        )
        output.append({
            "lane_id": lane,
            "profile": profile,
            "mechanism": mechanism,
            "repair_axis": MECHANISM_TO_AXIS.get(mechanism, "READ_ONLY_SUBCLUSTER_REQUIRED"),
            "cluster": {
                "axes": ["regime", "side", "signal_reason", "exit_reason"],
                "values": [regime, side, signal_reason, exit_reason],
            },
            "cluster_trade_count": len(bucket),
            "discovery_trade_count": len(discovery),
            "validation_trade_count": len(validation),
            "discovery_leakage_r": discovery_leak,
            "validation_leakage_r": validation_leak,
            "total_leakage_r": discovery_leak + validation_leak,
            "remaining_trade_count": len(remaining),
            "remaining_symbol_count": len(remaining_symbols),
            "persistent_across_split": persistent,
            "repair_executable": repair_executable,
        })
    output.sort(
        key=lambda row: (
            bool(row["repair_executable"]),
            bool(row["persistent_across_split"]),
            finite(row["validation_leakage_r"]),
            finite(row["total_leakage_r"]),
        ),
        reverse=True,
    )
    return output

def selected_repairs(clusters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    used: set[str] = set()
    for row in clusters:
        lane = str(row["lane_id"])
        profile = str(row["profile"])
        if not bool(row["repair_executable"]) or lane in used:
            continue
        if lane == ATR5 and profile != "severe":
            continue
        if lane == ATR15 and profile not in {"adverse", "severe"}:
            continue
        selected.append({
            **row,
            "single_axis_only": True,
            "parent_immutable": True,
            "child_only": True,
            "baseline_non_degrade_required": True,
            "same_frozen_data_and_costs_required": True,
            "no_stop_widening": True,
            "no_entry_threshold_relaxation": True,
            "no_parameter_optimization": True,
        })
        used.add(lane)
        if len(selected) >= MAX_ACTIVE_REPAIR_LANES:
            break
    return selected

def self_test() -> int:
    rows: list[dict[str, Any]] = []
    for fold in range(6):
        group = "discovery" if fold in DISCOVERY_FOLDS else "validation"
        for i in range(6):
            loss = i < 2
            rows.append({
                "lane_id": ATR15,
                "_profile": "severe",
                "symbol": ["BTC", "ETH", "SOL"][i % 3],
                "fold": fold,
                "segment_id": f"{group}-{fold}-{i}",
                "entry_index": i,
                "exit_index": i + 1,
                "entry_source_index": i * 5,
                "exit_source_index": i * 5 + 1,
                "entry_timestamp": fold * 100 + i,
                "timeframe": "5m",
                "regime": "trend_down" if loss else "trend_up",
                "side": "short" if loss else "long",
                "signal_reason": "atr15_persistence_5m_trigger",
                "exit_reason": "rule_exit_or_timeout" if loss else "take_profit",
                "loss_mechanism": "TIMEOUT_DRIFT" if loss else "NON_LOSS",
                "net_r": -0.7 if loss else 0.8,
                "mfe_r": 0.5 if loss else 1.1,
                "mae_r": 0.8 if loss else 0.2,
                "gross_return_pct": 0.2,
                "total_cost_pct": 0.03,
            })
    events = mechanism_events(rows)
    clusters = cluster_rows(events, rows)
    selected = selected_repairs(clusters)
    assert selected and selected[0]["lane_id"] == ATR15
    metrics = payoff_metrics(rows)
    assert metrics["trade_count"] == 36
    assert metrics["positive_fold_count"] == 6
    print("STATE=PASS_INCREMENTAL_DEFECT3B_PAYOFF_GEOMETRY_ALL_LOSS_AUDIT_SELF_TEST")
    print("RC=0")
    return 0

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--target-sha", default="UNKNOWN")
    parser.add_argument("--defect3-module")
    parser.add_argument("--raw-module")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.defect3_module or not args.raw_module:
        raise SystemExit("DEFECT3_AND_RAW_MODULE_REQUIRED")

    root = Path(args.root).resolve()
    base = import_module(Path(args.defect3_module).resolve(), "r7a4d2_defect3_base")
    raw = import_module(Path(args.raw_module).resolve(), "r7a4d2_defect3b_raw")
    required = [
        root / DEFECT2_SUMMARY,
        root / DEFECT2_TRADES,
        root / DEFECT2_CELLS,
        root / SECOND_SUMMARY,
        root / SECOND_TRADES,
        root / MANIFEST_PATH,
        root / DEFECT3_AUDIT,
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        print("STATE=HOLD_INCREMENTAL_DEFECT3B_PAYOFF_GEOMETRY_ALL_LOSS_AUDIT_INPUT")
        print("BLOCKER_COUNT=1")
        print("BLOCKERS=" + json.dumps(["REQUIRED_EVIDENCE_MISSING:" + ",".join(missing)]))
        print("RC=2")
        return 2

    defect2_summary = load_json(root / DEFECT2_SUMMARY)
    second_summary = load_json(root / SECOND_SUMMARY)
    defect3_summary = load_json(root / DEFECT3_AUDIT)
    manifest = load_json(root / MANIFEST_PATH)
    blockers: list[str] = []
    if defect2_summary.get("state") != "PASS_INCREMENTAL_DEFECT2_EXECUTION":
        blockers.append("DEFECT2_SUMMARY_NOT_PASS")
    if set(defect2_summary.get("incremental_pass_lane_ids") or []) != {ATR5, ATR15}:
        blockers.append("DEFECT2_PASS_LANES_CHANGED")
    if set(defect2_summary.get("robust_survivor_lane_ids") or []) != {ATR5}:
        blockers.append("ROBUST_PARENT_CHANGED")
    if set(defect2_summary.get("failed_lane_ids") or []) != {MA5}:
        blockers.append("FAILED_LANE_CHANGED")
    if defect3_summary.get("state") != "PASS_INCREMENTAL_DEFECT3_CONSECUTIVE_LOSS_CAUSALITY_AUDIT":
        blockers.append("DEFECT3_AUDIT_NOT_PASS")
    if int(defect3_summary.get("selected_repair_lane_count") or 0) != 0:
        blockers.append("DEFECT3_REPAIR_SELECTION_CHANGED")
    if second_summary.get("state") != "PASS_EXCHANGE_BOT_V2_ALL_11_SECOND_WAVE_EXECUTION_132":
        blockers.append("SECOND_WAVE_SUMMARY_NOT_PASS")
    if not bool(defect2_summary.get("atr5_control_preserved")):
        blockers.append("ATR5_CONTROL_NOT_PRESERVED")
    if not bool(defect2_summary.get("donchian15_reference_preserved")):
        blockers.append("DONCHIAN15_REFERENCE_NOT_PRESERVED")
    if not bool(defect2_summary.get("keep14_untouched")):
        blockers.append("KEEP14_NOT_PRESERVED")
    if blockers:
        print("STATE=HOLD_INCREMENTAL_DEFECT3B_PAYOFF_GEOMETRY_ALL_LOSS_AUDIT_INPUT")
        print("BLOCKER_COUNT=" + str(len(blockers)))
        print("BLOCKERS=" + json.dumps(blockers))
        print("RC=2")
        return 2

    before = snapshot(required)
    defect2_trades = load_jsonl(root / DEFECT2_TRADES)
    second_trades = load_jsonl(root / SECOND_TRADES)
    metadata, trades_by_lane = base.current_lane_sources(
        defect2_summary, defect2_trades, second_summary, second_trades
    )
    enriched, source_paths = base.build_enriched_rows(
        root, raw, manifest, metadata, trades_by_lane
    )
    source_before = snapshot(source_paths)
    for row in enriched:
        row["_profile"] = base.profile_name(row) or "other"

    profile_audits: list[dict[str, Any]] = []
    all_events = mechanism_events(enriched)
    clusters = cluster_rows(all_events, enriched)
    selected = selected_repairs(clusters)

    for lane in ACTIVE_LANES:
        profiles: dict[str, Any] = {}
        for profile in PROFILE_ORDER:
            rows = profile_rows(base, enriched, lane, profile)
            profiles[profile] = {
                "all": payoff_metrics(rows),
                "discovery": payoff_metrics([row for row in rows if split_name(row) == "discovery"]),
                "validation": payoff_metrics([row for row in rows if split_name(row) == "validation"]),
            }
        profile_audits.append({
            **metadata[lane],
            "profiles": profiles,
            "dominant_structural_clusters": [
                row for row in clusters if row["lane_id"] == lane
            ][:12],
            "confidence_claim_allowed": False,
            "confidence_blocker": "INDEPENDENT_OOS_AND_FORWARD_SHADOW_NOT_COMPLETED",
        })

    next_stage = (
        f"R7.A4D2_INCREMENTAL_DEFECT3B_SINGLE_AXIS_PAYOFF_EXECUTION_{len(selected) * 6}"
        if selected
        else "R7.A4D2_PARENT_PRESERVE_AND_INDEPENDENT_DATA_EXPANSION"
    )
    summary = {
        "state": "PASS_INCREMENTAL_DEFECT3B_PAYOFF_GEOMETRY_ALL_LOSS_AUDIT",
        "target_sha": args.target_sha,
        "active_lane_count": len(ACTIVE_LANES),
        "active_lane_ids": list(ACTIVE_LANES),
        "trade_row_count": len(enriched),
        "payoff_profile_rows": profile_audits,
        "structural_cluster_count": len(clusters),
        "persistent_structural_cluster_count": sum(bool(row["persistent_across_split"]) for row in clusters),
        "repair_executable_cluster_count": sum(bool(row["repair_executable"]) for row in clusters),
        "selected_repair_lane_count": len(selected),
        "selected_repair_lane_ids": [row["lane_id"] for row in selected],
        "selected_payoff_repair_rows": selected,
        "atr5_robust_parent_preserved": True,
        "atr15_incremental_parent_preserved": True,
        "ma5_second_wave_control_preserved": True,
        "donchian15_reference_preserved": True,
        "keep14_untouched": True,
        "confidence_claim_allowed": False,
        "confidence_claim_blocker": "INDEPENDENT_OOS_AND_FORWARD_SHADOW_NOT_COMPLETED",
        "mutation_rows": [],
        "next_stage": next_stage,
    }
    output = root / OUTPUT_DIR
    atomic_json(output / "incremental_defect3b_payoff_geometry_all_loss_audit_v1.json", summary)

    after = snapshot(required)
    source_after = snapshot(source_paths)
    mutations = [
        path for path in before if before[path] != after.get(path)
    ] + [
        path for path in source_before if source_before[path] != source_after.get(path)
    ]
    if mutations:
        print("STATE=HOLD_INCREMENTAL_DEFECT3B_PAYOFF_GEOMETRY_ALL_LOSS_AUDIT")
        print("BLOCKER_COUNT=1")
        print("BLOCKERS=" + json.dumps([f"INPUT_MUTATIONS:{len(mutations)}"]))
        print("RC=2")
        return 2

    print("STATE=PASS_INCREMENTAL_DEFECT3B_PAYOFF_GEOMETRY_ALL_LOSS_AUDIT")
    print("BLOCKER_COUNT=0")
    print("ACTIVE_LANE_COUNT=" + str(len(ACTIVE_LANES)))
    print("ACTIVE_LANE_IDS=" + json.dumps(list(ACTIVE_LANES)))
    print("TRADE_ROW_COUNT=" + str(len(enriched)))
    print("STRUCTURAL_CLUSTER_COUNT=" + str(len(clusters)))
    print("PERSISTENT_STRUCTURAL_CLUSTER_COUNT=" + str(summary["persistent_structural_cluster_count"]))
    print("REPAIR_EXECUTABLE_CLUSTER_COUNT=" + str(summary["repair_executable_cluster_count"]))
    print("SELECTED_REPAIR_LANE_COUNT=" + str(len(selected)))
    print("SELECTED_REPAIR_LANE_IDS=" + json.dumps(summary["selected_repair_lane_ids"]))
    print("CONFIDENCE_CLAIM_ALLOWED=false")
    print("PAYOFF_PROFILE_ROWS=" + json.dumps(profile_audits, sort_keys=True))
    print("SELECTED_PAYOFF_REPAIR_ROWS=" + json.dumps(selected, sort_keys=True))
    print("AUDIT_JSON=" + str(output / "incremental_defect3b_payoff_geometry_all_loss_audit_v1.json"))
    print("NEXT_STAGE=" + next_stage)
    print("BLOCKERS=[]")
    print("RC=0")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
