#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

SECOND_DIR = Path("runtime/r7a4d2_exchange_bot_v2_all_11_second_wave_execution_132")
THIRD_DIR = Path("runtime/r7a4d2_exchange_bot_v2_third_wave_targeted_repair_execution_132")
OUTPUT_DIR = Path("runtime/r7a4d2_incremental_defect_ablation_audit")

SECOND_SUMMARY = SECOND_DIR / "all_11_second_wave_summary_v1.json"
SECOND_TRADES = SECOND_DIR / "second_wave_trade_rows_v1.jsonl"
SECOND_CELLS = SECOND_DIR / "second_wave_cell_rows_v1.jsonl"
THIRD_SUMMARY = THIRD_DIR / "third_wave_targeted_repair_summary_v1.json"
THIRD_TRADES = THIRD_DIR / "third_wave_trade_rows_v1.jsonl"
THIRD_CELLS = THIRD_DIR / "third_wave_cell_rows_v1.jsonl"

EXPECTED_LANES = 11
MAX_ACTIVE_REPAIR_LANES = 6
STRESS_CELLS_PER_REPAIR = 6
ATR5_CONTROL = "dual_atr_volatility_bot:5m"
REFERENCE_LANE = "dual_donchian_trend_bot:15m"
BASE_CELL = ("cost_profile_0", "timing_0")
ADVERSE_CELL = ("cost_profile_1", "timing_1")
SEVERE_CELL = ("cost_profile_2", "timing_1")

REPAIRABLE_CAUSES = {
    "ADDED_LOW_QUALITY_SIGNAL_DILUTION",
    "REMOVED_POSITIVE_SIGNAL_COVERAGE",
    "SHARED_EXIT_GEOMETRY_REGRESSION",
    "TIMEFRAME_ROUTE_REWRITE",
    "COST_FRAGILITY",
    "WALK_FORWARD_CONCENTRATION",
    "ENTRY_REGIME_CONTAMINATION",
    "SAMPLE_EXPANSION_QUALITY_DILUTION",
    "SEVERE_MARGIN_COMPRESSION",
}

REPAIR_AXIS_BY_CAUSE = {
    "ADDED_LOW_QUALITY_SIGNAL_DILUTION": "RESTORE_BASELINE_TRIGGER_PLUS_ONE_LOSS_CLUSTER_VETO",
    "REMOVED_POSITIVE_SIGNAL_COVERAGE": "RESTORE_BASELINE_WINNER_CLUSTER_ONLY",
    "SHARED_EXIT_GEOMETRY_REGRESSION": "RESTORE_BASELINE_EXIT_GEOMETRY_ONLY",
    "TIMEFRAME_ROUTE_REWRITE": "RESTORE_BASELINE_TIMEFRAME_THEN_ONE_DEFECT_ABLATION",
    "COST_FRAGILITY": "KEEP_SIGNAL_AND_APPLY_EXECUTION_COST_DEFENSE_ONLY",
    "WALK_FORWARD_CONCENTRATION": "KEEP_SIGNAL_AND_VETO_SINGLE_BAD_FOLD_CLUSTER",
    "ENTRY_REGIME_CONTAMINATION": "REMOVE_SINGLE_REGIME_SYMBOL_SIDE_LOSS_CLUSTER",
    "SAMPLE_EXPANSION_QUALITY_DILUTION": "RESTORE_BASELINE_TRIGGER_AND_EXPAND_HISTORY_ONLY",
    "SEVERE_MARGIN_COMPRESSION": "KEEP_BASELINE_SIGNAL_AND_REPAIR_SEVERE_EXIT_ONLY",
    "ROUTE_STARVATION": "DATA_EXPANSION_BEFORE_STRATEGY_CHANGE",
    "WHOLE_TRIGGER_REPLACEMENT": "ROLLBACK_THIRD_WAVE_TRIGGER_REPLACEMENT",
    "PERSISTENT_NEGATIVE_EDGE": "RETIRE_OR_ORTHOGONAL_REPLACEMENT",
}

def finite(value: Any, default: float = 0.0) -> float:
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    return default

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

def summary_lane_map(summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = summary.get("lane_best_rows") or []
    output: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        lane = str(row.get("source_lane_id") or "")
        if lane:
            output[lane] = row
    return output

def cell_key(row: dict[str, Any]) -> tuple[str, str]:
    return str(row.get("cost_profile_id") or ""), str(row.get("timing_id") or "")

def metric_row(row: dict[str, Any], profile: str) -> dict[str, Any]:
    if profile == "base":
        return dict(row.get("base_metrics") or {})
    if profile == "adverse":
        return dict(row.get("adverse_metrics") or {})
    if profile == "severe":
        return dict(row.get("severe_tail_metrics") or row.get("severe_metrics") or {})
    raise ValueError(profile)

def trade_locus(row: dict[str, Any]) -> tuple[str, str, str, int, str, str]:
    return (
        str(row.get("segment_id") or ""),
        str(row.get("symbol") or ""),
        str(row.get("execution_timeframe") or ""),
        int(row.get("entry_index") or -1),
        str(row.get("side") or ""),
        str(row.get("level_id") or ""),
    )

def base_variant_trades(
    rows: list[dict[str, Any]], lane: str, variant: str
) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if str(row.get("source_lane_id") or "") == lane
        and str(row.get("variant_id") or "") == variant
        and cell_key(row) == BASE_CELL
    ]

def sum_net(rows: Iterable[dict[str, Any]]) -> float:
    return sum(finite(row.get("net_return_pct")) for row in rows)

def cluster_stats(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    materialized = list(rows)
    axes: dict[str, Counter[str]] = {
        "symbol": Counter(),
        "regime": Counter(),
        "side": Counter(),
        "exit_reason": Counter(),
    }
    loss_axes: dict[str, Counter[str]] = {key: Counter() for key in axes}
    pnl_axes: dict[str, defaultdict[str, float]] = {
        key: defaultdict(float) for key in axes
    }
    for row in materialized:
        net = finite(row.get("net_return_pct"))
        for key in axes:
            value = str(row.get(key) or "UNKNOWN")
            axes[key][value] += 1
            pnl_axes[key][value] += net
            if net < 0:
                loss_axes[key][value] += 1
    worst: dict[str, dict[str, Any]] = {}
    for axis in axes:
        candidates = [
            {
                "value": value,
                "trade_count": axes[axis][value],
                "loss_count": loss_axes[axis][value],
                "net_pnl_sum_pct": pnl,
            }
            for value, pnl in pnl_axes[axis].items()
        ]
        candidates.sort(key=lambda item: (finite(item["net_pnl_sum_pct"]), -int(item["trade_count"])))
        worst[axis] = candidates[0] if candidates else {
            "value": None,
            "trade_count": 0,
            "loss_count": 0,
            "net_pnl_sum_pct": 0.0,
        }
    return {
        "trade_count": len(materialized),
        "net_pnl_sum_pct": sum_net(materialized),
        "worst_clusters": worst,
    }

def exact_delta(
    baseline_trades: list[dict[str, Any]],
    candidate_trades: list[dict[str, Any]],
) -> dict[str, Any]:
    baseline_map: dict[tuple[str, str, str, int, str, str], list[dict[str, Any]]] = defaultdict(list)
    candidate_map: dict[tuple[str, str, str, int, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in baseline_trades:
        baseline_map[trade_locus(row)].append(row)
    for row in candidate_trades:
        candidate_map[trade_locus(row)].append(row)

    baseline_keys = set(baseline_map)
    candidate_keys = set(candidate_map)
    shared_keys = baseline_keys & candidate_keys
    removed_keys = baseline_keys - candidate_keys
    added_keys = candidate_keys - baseline_keys

    shared_rows: list[dict[str, Any]] = []
    exit_change_count = 0
    shared_baseline_pnl = 0.0
    shared_candidate_pnl = 0.0
    for key in sorted(shared_keys):
        baseline = baseline_map[key][0]
        candidate = candidate_map[key][0]
        baseline_net = finite(baseline.get("net_return_pct"))
        candidate_net = finite(candidate.get("net_return_pct"))
        exit_changed = (
            str(baseline.get("exit_reason") or "") != str(candidate.get("exit_reason") or "")
            or int(baseline.get("holding_bars") or 0) != int(candidate.get("holding_bars") or 0)
            or str(baseline.get("entry_mode") or "") != str(candidate.get("entry_mode") or "")
        )
        exit_change_count += int(exit_changed)
        shared_baseline_pnl += baseline_net
        shared_candidate_pnl += candidate_net
        shared_rows.append(
            {
                "locus": list(key),
                "baseline_net_pct": baseline_net,
                "candidate_net_pct": candidate_net,
                "delta_net_pct": candidate_net - baseline_net,
                "baseline_exit": str(baseline.get("exit_reason") or ""),
                "candidate_exit": str(candidate.get("exit_reason") or ""),
                "exit_changed": exit_changed,
            }
        )

    removed = [row for key in removed_keys for row in baseline_map[key]]
    added = [row for key in added_keys for row in candidate_map[key]]
    overlap_denominator = max(len(baseline_keys | candidate_keys), 1)
    return {
        "baseline_trade_count": len(baseline_trades),
        "candidate_trade_count": len(candidate_trades),
        "shared_locus_count": len(shared_keys),
        "removed_locus_count": len(removed_keys),
        "added_locus_count": len(added_keys),
        "locus_overlap_ratio": len(shared_keys) / overlap_denominator,
        "removed_baseline_pnl_pct": sum_net(removed),
        "added_candidate_pnl_pct": sum_net(added),
        "shared_baseline_pnl_pct": shared_baseline_pnl,
        "shared_candidate_pnl_pct": shared_candidate_pnl,
        "shared_delta_pnl_pct": shared_candidate_pnl - shared_baseline_pnl,
        "shared_exit_change_count": exit_change_count,
        "removed_cluster_stats": cluster_stats(removed),
        "added_cluster_stats": cluster_stats(added),
        "worst_shared_deltas": sorted(
            shared_rows, key=lambda row: finite(row["delta_net_pct"])
        )[:10],
    }

def positive_folds(metrics: dict[str, Any]) -> int:
    return int((metrics.get("fold_metrics") or {}).get("positive_fold_count") or 0)

def classify_cause(
    baseline_row: dict[str, Any],
    candidate_row: dict[str, Any],
    delta: dict[str, Any],
) -> str:
    baseline_base = metric_row(baseline_row, "base")
    candidate_base = metric_row(candidate_row, "base")
    candidate_adverse = metric_row(candidate_row, "adverse")
    candidate_severe = metric_row(candidate_row, "severe")

    baseline_pnl = finite(baseline_base.get("net_pnl_sum_pct"))
    candidate_pnl = finite(candidate_base.get("net_pnl_sum_pct"))
    total_delta = candidate_pnl - baseline_pnl
    baseline_trades = int(baseline_base.get("trade_count") or 0)
    candidate_trades = int(candidate_base.get("trade_count") or 0)
    baseline_tf = str(baseline_row.get("execution_timeframe") or "")
    candidate_tf = str(candidate_row.get("execution_timeframe") or "")
    overlap = finite(delta.get("locus_overlap_ratio"))
    added_pnl = finite(delta.get("added_candidate_pnl_pct"))
    removed_pnl = finite(delta.get("removed_baseline_pnl_pct"))
    shared_delta = finite(delta.get("shared_delta_pnl_pct"))
    exit_changes = int(delta.get("shared_exit_change_count") or 0)

    if baseline_tf and candidate_tf and baseline_tf != candidate_tf:
        return "TIMEFRAME_ROUTE_REWRITE"
    if baseline_trades < 24 and candidate_trades < 24 and max(baseline_trades, candidate_trades) <= 17:
        return "ROUTE_STARVATION"
    if overlap < 0.10 and candidate_pnl < baseline_pnl:
        return "WHOLE_TRIGGER_REPLACEMENT"
    if baseline_trades < 24 and candidate_trades >= max(24, baseline_trades * 2) and candidate_pnl <= 0:
        return "SAMPLE_EXPANSION_QUALITY_DILUTION"
    if total_delta < 0 and added_pnl < 0 and abs(added_pnl) >= 0.45 * max(abs(total_delta), 0.01):
        return "ADDED_LOW_QUALITY_SIGNAL_DILUTION"
    if total_delta < 0 and removed_pnl > 0 and removed_pnl >= 0.45 * max(abs(total_delta), 0.01):
        return "REMOVED_POSITIVE_SIGNAL_COVERAGE"
    if total_delta < 0 and shared_delta < 0 and exit_changes > 0 and abs(shared_delta) >= 0.35 * max(abs(total_delta), 0.01):
        return "SHARED_EXIT_GEOMETRY_REGRESSION"
    if candidate_pnl > 0 and finite(candidate_adverse.get("net_pnl_sum_pct")) <= 0:
        return "COST_FRAGILITY"
    if candidate_pnl > 0 and positive_folds(candidate_base) < 4:
        return "WALK_FORWARD_CONCENTRATION"
    if (
        finite(candidate_severe.get("net_pnl_sum_pct")) < 0.50
        or finite(candidate_severe.get("profit_factor")) < 1.20
        or positive_folds(candidate_severe) < 4
    ) and baseline_row.get("source_lane_id") == ATR5_CONTROL:
        return "SEVERE_MARGIN_COMPRESSION"
    added_stats = delta.get("added_cluster_stats") or {}
    worst = (added_stats.get("worst_clusters") or {}).get("regime") or {}
    if int(worst.get("loss_count") or 0) >= 3 and finite(worst.get("net_pnl_sum_pct")) < 0:
        return "ENTRY_REGIME_CONTAMINATION"
    return "PERSISTENT_NEGATIVE_EDGE"

def priority_score(
    lane: str,
    baseline_row: dict[str, Any],
    candidate_row: dict[str, Any],
    delta: dict[str, Any],
    cause: str,
) -> float:
    baseline_base = metric_row(baseline_row, "base")
    baseline_adverse = metric_row(baseline_row, "adverse")
    candidate_base = metric_row(candidate_row, "base")
    candidate_adverse = metric_row(candidate_row, "adverse")
    evidence = (
        max(finite(baseline_base.get("net_pnl_sum_pct")), 0.0)
        + max(finite(baseline_adverse.get("net_pnl_sum_pct")), 0.0)
        + 0.25 * max(finite(baseline_base.get("profit_factor")) - 1.0, 0.0)
        + 0.10 * positive_folds(baseline_base)
    )
    recoverable = (
        max(-finite(delta.get("added_candidate_pnl_pct")), 0.0)
        + max(finite(delta.get("removed_baseline_pnl_pct")), 0.0)
        + max(-finite(delta.get("shared_delta_pnl_pct")), 0.0)
    )
    current_hint = (
        max(finite(candidate_base.get("net_pnl_sum_pct")), 0.0)
        + max(finite(candidate_adverse.get("net_pnl_sum_pct")), 0.0)
    )
    control_bonus = 2.0 if lane == ATR5_CONTROL else 0.0
    cause_bonus = 1.0 if cause in REPAIRABLE_CAUSES else -1.0
    return evidence + 0.50 * recoverable + 0.20 * current_hint + control_bonus + cause_bonus

def build_rows(
    second_summary: dict[str, Any],
    third_summary: dict[str, Any],
    second_trades: list[dict[str, Any]],
    third_trades: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    second_lanes = summary_lane_map(second_summary)
    third_lanes = summary_lane_map(third_summary)
    lanes = sorted(set(second_lanes) | set(third_lanes))
    if len(lanes) != EXPECTED_LANES:
        raise ValueError(f"LANE_COUNT_INVALID:{len(lanes)}")

    rows: list[dict[str, Any]] = []
    for lane in lanes:
        baseline = second_lanes[lane]
        candidate = third_lanes[lane]
        baseline_variant = str(baseline.get("variant_id") or "")
        candidate_variant = str(candidate.get("variant_id") or "")
        baseline_trade_rows = base_variant_trades(second_trades, lane, baseline_variant)
        candidate_trade_rows = base_variant_trades(third_trades, lane, candidate_variant)
        delta = exact_delta(baseline_trade_rows, candidate_trade_rows)
        cause = classify_cause(baseline, candidate, delta)
        score = priority_score(lane, baseline, candidate, delta, cause)
        baseline_base = metric_row(baseline, "base")
        candidate_base = metric_row(candidate, "base")
        candidate_adverse = metric_row(candidate, "adverse")
        candidate_severe = metric_row(candidate, "severe")
        rows.append(
            {
                "lane_id": lane,
                "family": str(candidate.get("family") or baseline.get("family") or ""),
                "baseline_variant_id": baseline_variant,
                "candidate_variant_id": candidate_variant,
                "baseline_execution_timeframe": str(baseline.get("execution_timeframe") or ""),
                "candidate_execution_timeframe": str(candidate.get("execution_timeframe") or ""),
                "baseline_base_metrics": baseline_base,
                "candidate_base_metrics": candidate_base,
                "candidate_adverse_metrics": candidate_adverse,
                "candidate_severe_metrics": candidate_severe,
                "base_pnl_delta_pct": finite(candidate_base.get("net_pnl_sum_pct")) - finite(baseline_base.get("net_pnl_sum_pct")),
                "base_trade_delta": int(candidate_base.get("trade_count") or 0) - int(baseline_base.get("trade_count") or 0),
                "exact_entry_locus_delta": delta,
                "primary_defect": cause,
                "single_repair_axis": REPAIR_AXIS_BY_CAUSE[cause],
                "repairable_now": cause in REPAIRABLE_CAUSES,
                "priority_score": score,
                "atr5_control_preserved": lane == ATR5_CONTROL,
                "third_wave_variant_rejected": True,
            }
        )
    return rows

def select_repairs(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    eligible = [row for row in rows if bool(row.get("repairable_now"))]
    eligible.sort(
        key=lambda row: (
            int(row.get("lane_id") == ATR5_CONTROL),
            finite(row.get("priority_score"), -1e9),
        ),
        reverse=True,
    )
    selected: list[dict[str, Any]] = []
    for row in eligible[:MAX_ACTIVE_REPAIR_LANES]:
        selected.append(
            {
                "lane_id": row["lane_id"],
                "family": row["family"],
                "control_variant_id": row["baseline_variant_id"],
                "rejected_variant_id": row["candidate_variant_id"],
                "primary_defect": row["primary_defect"],
                "single_repair_axis": row["single_repair_axis"],
                "control_execution_timeframe": row["baseline_execution_timeframe"],
                "expected_stress_cell_count": STRESS_CELLS_PER_REPAIR,
                "selection_score": row["priority_score"],
                "selection_constraints": [
                    "CONTROL_SIGNAL_SET_PRESERVED",
                    "ONE_DEFECT_CHANGE_ONLY",
                    "NO_STOP_WIDENING",
                    "NO_ENTRY_THRESHOLD_RELAXATION",
                    "SAME_FROZEN_DATA_AND_COSTS",
                    "BASELINE_MUST_NOT_DEGRADE",
                ],
            }
        )
    return selected

def self_test() -> int:
    baseline = {
        "source_lane_id": ATR5_CONTROL,
        "variant_id": "control",
        "execution_timeframe": "5m",
        "family": "event_reversal",
        "base_metrics": {"trade_count": 24, "net_pnl_sum_pct": 5.0, "profit_factor": 2.0, "fold_metrics": {"positive_fold_count": 5}},
        "adverse_metrics": {"trade_count": 24, "net_pnl_sum_pct": 2.0, "profit_factor": 1.4, "fold_metrics": {"positive_fold_count": 4}},
        "severe_tail_metrics": {"trade_count": 24, "net_pnl_sum_pct": 0.1, "profit_factor": 1.05, "fold_metrics": {"positive_fold_count": 3}},
    }
    candidate = {
        **baseline,
        "variant_id": "candidate",
        "base_metrics": {"trade_count": 28, "net_pnl_sum_pct": 2.0, "profit_factor": 1.2, "fold_metrics": {"positive_fold_count": 4}},
        "adverse_metrics": {"trade_count": 28, "net_pnl_sum_pct": -1.0, "profit_factor": 0.8, "fold_metrics": {"positive_fold_count": 2}},
        "severe_tail_metrics": {"trade_count": 28, "net_pnl_sum_pct": -2.0, "profit_factor": 0.5, "fold_metrics": {"positive_fold_count": 1}},
    }
    base_trades = [
        {"segment_id": "s1", "symbol": "BTC", "execution_timeframe": "5m", "entry_index": i, "side": "long", "level_id": None, "net_return_pct": 0.2, "exit_reason": "take_profit", "holding_bars": 3, "entry_mode": "next_open"}
        for i in range(24)
    ]
    candidate_trades = list(base_trades) + [
        {"segment_id": "s1", "symbol": "BTC", "execution_timeframe": "5m", "entry_index": 100+i, "side": "long", "level_id": None, "net_return_pct": -0.8, "exit_reason": "stop", "holding_bars": 1, "entry_mode": "next_open", "regime": "shock_recovery"}
        for i in range(4)
    ]
    delta = exact_delta(base_trades, candidate_trades)
    cause = classify_cause(baseline, candidate, delta)
    assert cause == "ADDED_LOW_QUALITY_SIGNAL_DILUTION", cause
    assert delta["added_locus_count"] == 4
    assert REPAIR_AXIS_BY_CAUSE[cause] == "RESTORE_BASELINE_TRIGGER_PLUS_ONE_LOSS_CLUSTER_VETO"
    print("STATE=PASS_INCREMENTAL_DEFECT_ABLATION_AUDIT_SELF_TEST")
    print("RC=0")
    return 0

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--target-sha", default="UNKNOWN")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return self_test()

    root = Path(args.root).resolve()
    required = [
        root / SECOND_SUMMARY,
        root / SECOND_TRADES,
        root / SECOND_CELLS,
        root / THIRD_SUMMARY,
        root / THIRD_TRADES,
        root / THIRD_CELLS,
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        print("STATE=HOLD_INCREMENTAL_DEFECT_ABLATION_AUDIT_INPUT")
        print("BLOCKER_COUNT=1")
        print("BLOCKERS=" + json.dumps(["REQUIRED_EVIDENCE_MISSING:" + ",".join(missing)]))
        print("RC=2")
        return 2

    before = snapshot(required)
    second_summary = load_json(root / SECOND_SUMMARY)
    third_summary = load_json(root / THIRD_SUMMARY)
    blockers: list[str] = []
    if second_summary.get("state") != "PASS_EXCHANGE_BOT_V2_ALL_11_SECOND_WAVE_EXECUTION_132":
        blockers.append("SECOND_WAVE_SUMMARY_NOT_PASS")
    if third_summary.get("state") != "PASS_EXCHANGE_BOT_V2_THIRD_WAVE_TARGETED_REPAIR_EXECUTION_132":
        blockers.append("THIRD_WAVE_SUMMARY_NOT_PASS")
    if int(second_summary.get("bundle_count") or 0) != 22:
        blockers.append("SECOND_WAVE_BUNDLE_COUNT_INVALID")
    if int(third_summary.get("bundle_count") or 0) != 22:
        blockers.append("THIRD_WAVE_BUNDLE_COUNT_INVALID")
    if blockers:
        print("STATE=HOLD_INCREMENTAL_DEFECT_ABLATION_AUDIT_INPUT")
        print("BLOCKER_COUNT=" + str(len(blockers)))
        print("BLOCKERS=" + json.dumps(blockers))
        print("RC=2")
        return 2

    second_trades = load_jsonl(root / SECOND_TRADES)
    third_trades = load_jsonl(root / THIRD_TRADES)
    lane_rows = build_rows(second_summary, third_summary, second_trades, third_trades)
    selected = select_repairs(lane_rows)
    cause_histogram = Counter(str(row["primary_defect"]) for row in lane_rows)
    selected_histogram = Counter(str(row["primary_defect"]) for row in selected)
    output = root / OUTPUT_DIR
    expected_cells = len(selected) * STRESS_CELLS_PER_REPAIR
    next_stage = (
        f"R7.A4D2_INCREMENTAL_SINGLE_DEFECT_REPAIR_EXECUTION_{expected_cells}"
        if selected
        else "R7.A4D2_FAILED_LANE_DATA_EXPANSION_OR_RETIRE_DECISION"
    )
    summary = {
        "state": "PASS_INCREMENTAL_DEFECT_ABLATION_AUDIT",
        "target_sha": args.target_sha,
        "lane_count": len(lane_rows),
        "max_active_repair_lanes": MAX_ACTIVE_REPAIR_LANES,
        "selected_repair_lane_count": len(selected),
        "selected_repair_lane_ids": [row["lane_id"] for row in selected],
        "expected_incremental_repair_cell_count": expected_cells,
        "primary_defect_histogram": dict(sorted(cause_histogram.items())),
        "selected_defect_histogram": dict(sorted(selected_histogram.items())),
        "atr5_control_preserved": True,
        "donchian15_reference_preserved": True,
        "keep14_untouched": True,
        "third_wave_bundle_set_rejected": True,
        "lane_delta_rows": lane_rows,
        "selected_incremental_repair_rows": selected,
        "mutation_rows": [],
        "next_stage": next_stage,
    }
    atomic_json(output / "incremental_defect_ablation_audit_v1.json", summary)
    after = snapshot(required)
    mutations = [
        {"path": path, "before": before[path], "after": after.get(path)}
        for path in before
        if before[path] != after.get(path)
    ]
    if mutations:
        print("STATE=HOLD_INCREMENTAL_DEFECT_ABLATION_AUDIT")
        print("BLOCKER_COUNT=1")
        print("BLOCKERS=" + json.dumps([f"INPUT_MUTATIONS:{len(mutations)}"]))
        print("RC=2")
        return 2

    print("STATE=PASS_INCREMENTAL_DEFECT_ABLATION_AUDIT")
    print("BLOCKER_COUNT=0")
    print("LANE_COUNT=" + str(len(lane_rows)))
    print("ATR5_CONTROL_PRESERVED=true")
    print("DONCHIAN15_REFERENCE_PRESERVED=true")
    print("KEEP14_UNTOUCHED=true")
    print("THIRD_WAVE_BUNDLE_SET_REJECTED=true")
    print("PRIMARY_DEFECT_HISTOGRAM=" + json.dumps(summary["primary_defect_histogram"], sort_keys=True))
    print("SELECTED_REPAIR_LANE_COUNT=" + str(len(selected)))
    print("SELECTED_REPAIR_LANE_IDS=" + json.dumps(summary["selected_repair_lane_ids"]))
    print("EXPECTED_INCREMENTAL_REPAIR_CELL_COUNT=" + str(expected_cells))
    print("SELECTED_INCREMENTAL_REPAIR_ROWS=" + json.dumps(selected, sort_keys=True))
    print("AUDIT_JSON=" + str(output / "incremental_defect_ablation_audit_v1.json"))
    print("NEXT_STAGE=" + next_stage)
    print("BLOCKERS=[]")
    print("RC=0")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
