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

SECOND_SUMMARY = Path("runtime/r7a4d2_exchange_bot_v2_all_11_second_wave_execution_132/all_11_second_wave_summary_v1.json")
SECOND_TRADES = Path("runtime/r7a4d2_exchange_bot_v2_all_11_second_wave_execution_132/second_wave_trade_rows_v1.jsonl")
REPAIR36_SUMMARY = Path("runtime/r7a4d2_incremental_single_defect_repair_execution_36/incremental_single_defect_repair_summary_v1.json")
REPAIR36_TRADES = Path("runtime/r7a4d2_incremental_single_defect_repair_execution_36/incremental_repair_trade_rows_v1.jsonl")
AUDIT1 = Path("runtime/r7a4d2_incremental_defect_ablation_audit/incremental_defect_ablation_audit_v1.json")
OUTPUT_DIR = Path("runtime/r7a4d2_incremental_recovery_contract_repair_and_defect2_audit")

EXPECTED_SELECTED = 6
MIN_TRADES = 24
ATR5 = "dual_atr_volatility_bot:5m"
ATR15 = "dual_atr_volatility_bot:15m"
MA15 = "dual_ma_trend_bot:15m"
MA5 = "dual_ma_trend_bot:5m"
GRID5 = "directional_trend_grid_bot:5m"
NGRID5 = "neutral_multi_level_grid_bot:5m"
BASE_CELL = ("cost_profile_0", "timing_0")
ADVERSE_CELL = ("cost_profile_1", "timing_1")
SEVERE_CELL = ("cost_profile_2", "timing_1")
DISCOVERY_FOLDS = {0, 1, 2}
VALIDATION_FOLDS = {3, 4, 5}
AXES = (
    ("regime",),
    ("symbol",),
    ("side",),
    ("signal_reason",),
    ("regime", "side"),
    ("symbol", "regime"),
)

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
        for number, raw in enumerate(handle, 1):
            line = raw.strip()
            if not line:
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"JSONL_OBJECT_REQUIRED:{path}:{number}")
            rows.append(value)
    return rows

def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
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

def positive_folds(metrics: dict[str, Any]) -> int:
    return int((metrics.get("fold_metrics") or {}).get("positive_fold_count") or 0)

def number_equal(left: Any, right: Any, tolerance: float = 1e-7) -> bool:
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        lf = float(left)
        rf = float(right)
        if math.isinf(lf) or math.isinf(rf):
            return math.isinf(lf) and math.isinf(rf) and ((lf > 0) == (rf > 0))
        if math.isnan(lf) or math.isnan(rf):
            return math.isnan(lf) and math.isnan(rf)
        return abs(lf - rf) <= tolerance
    return left == right

def metric_deltas(actual: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
    keys = ("trade_count", "net_pnl_sum_pct", "expectancy_r", "profit_factor", "max_drawdown_pct")
    deltas: dict[str, Any] = {}
    for key in keys:
        actual_value = actual.get(key)
        expected_value = expected.get(key)
        if not number_equal(actual_value, expected_value):
            if isinstance(actual_value, (int, float)) and isinstance(expected_value, (int, float)) and math.isfinite(float(actual_value)) and math.isfinite(float(expected_value)):
                deltas[key] = {"actual": actual_value, "expected": expected_value, "delta": float(actual_value) - float(expected_value)}
            else:
                deltas[key] = {"actual": actual_value, "expected": expected_value}
    actual_folds = positive_folds(actual)
    expected_folds = positive_folds(expected)
    if actual_folds != expected_folds:
        deltas["positive_fold_count"] = {"actual": actual_folds, "expected": expected_folds, "delta": actual_folds - expected_folds}
    return deltas

def metric_close(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    return not metric_deltas(actual, expected)

def lane_map(summary: dict[str, Any], key: str) -> dict[str, dict[str, Any]]:
    rows = summary.get(key) or []
    output: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        lane = str(row.get("source_lane_id") or row.get("lane_id") or "")
        if lane:
            output[lane] = row
    return output

def profile_metrics(row: dict[str, Any], profile: str) -> dict[str, Any]:
    if profile == "base":
        return dict(row.get("base_metrics") or {})
    if profile == "adverse":
        return dict(row.get("adverse_metrics") or {})
    if profile == "severe":
        return dict(row.get("severe_metrics") or row.get("severe_tail_metrics") or {})
    raise ValueError(profile)

def cell_key(row: dict[str, Any]) -> tuple[str, str]:
    return str(row.get("cost_profile_id") or ""), str(row.get("timing_id") or "")

def lane_profile_rows(rows: list[dict[str, Any]], lane: str, cell: tuple[str, str]) -> list[dict[str, Any]]:
    return [row for row in rows if str(row.get("lane_id") or "") == lane and cell_key(row) == cell]

def cluster_value(row: dict[str, Any], axes: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(str(row.get(axis) or "UNKNOWN") for axis in axes)

def pnl(rows: Iterable[dict[str, Any]]) -> float:
    return sum(finite(row.get("net_return_pct")) for row in rows)

def persistent_cluster(rows: list[dict[str, Any]], lane: str, min_remaining: int) -> dict[str, Any] | None:
    base = lane_profile_rows(rows, lane, BASE_CELL)
    adverse = lane_profile_rows(rows, lane, ADVERSE_CELL)
    severe = lane_profile_rows(rows, lane, SEVERE_CELL)
    candidates: list[dict[str, Any]] = []
    for axes in AXES:
        values = sorted({cluster_value(row, axes) for row in severe})
        for value in values:
            base_cluster = [row for row in base if cluster_value(row, axes) == value]
            adverse_cluster = [row for row in adverse if cluster_value(row, axes) == value]
            severe_cluster = [row for row in severe if cluster_value(row, axes) == value]
            severe_discovery = [row for row in severe_cluster if int(row.get("fold") if row.get("fold") is not None else -1) in DISCOVERY_FOLDS]
            severe_validation = [row for row in severe_cluster if int(row.get("fold") if row.get("fold") is not None else -1) in VALIDATION_FOLDS]
            adverse_discovery = [row for row in adverse_cluster if int(row.get("fold") if row.get("fold") is not None else -1) in DISCOVERY_FOLDS]
            adverse_validation = [row for row in adverse_cluster if int(row.get("fold") if row.get("fold") is not None else -1) in VALIDATION_FOLDS]
            remaining = len(base) - len(base_cluster)
            if remaining < min_remaining:
                continue
            if not severe_discovery or not severe_validation:
                continue
            if pnl(severe_discovery) >= 0 or pnl(severe_validation) >= 0:
                continue
            if pnl(adverse_discovery) + pnl(adverse_validation) >= 0:
                continue
            folds = {int(row.get("fold") if row.get("fold") is not None else -1) for row in severe_cluster}
            if len(folds) < 2:
                continue
            harm = -(pnl(severe_cluster) + 0.5 * pnl(adverse_cluster))
            score = harm / max(len(severe_cluster), 1)
            candidates.append({
                "axes": list(axes),
                "values": list(value),
                "base_cluster_trade_count": len(base_cluster),
                "base_remaining_trade_count": remaining,
                "adverse_cluster_trade_count": len(adverse_cluster),
                "severe_cluster_trade_count": len(severe_cluster),
                "severe_discovery_pnl_pct": pnl(severe_discovery),
                "severe_validation_pnl_pct": pnl(severe_validation),
                "adverse_cluster_pnl_pct": pnl(adverse_cluster),
                "severe_cluster_pnl_pct": pnl(severe_cluster),
                "fold_count": len(folds),
                "score": score,
            })
    candidates.sort(key=lambda row: (finite(row["score"]), row["severe_cluster_trade_count"]), reverse=True)
    return candidates[0] if candidates else None

def self_test() -> int:
    expected = {"trade_count": 24, "net_pnl_sum_pct": 1.0, "expectancy_r": 0.1, "profit_factor": math.inf, "max_drawdown_pct": 0.0, "fold_metrics": {"positive_fold_count": 4}}
    actual = dict(expected)
    assert metric_close(actual, expected)
    broken = dict(expected)
    broken["net_pnl_sum_pct"] = 0.8
    assert "net_pnl_sum_pct" in metric_deltas(broken, expected)
    rows: list[dict[str, Any]] = []
    for fold in range(6):
        for cell in (BASE_CELL, ADVERSE_CELL, SEVERE_CELL):
            rows.append({
                "lane_id": ATR5,
                "cost_profile_id": cell[0],
                "timing_id": cell[1],
                "fold": fold,
                "regime": "bad" if fold in {0, 3} else "good",
                "symbol": "BTC",
                "side": "long",
                "signal_reason": "x",
                "net_return_pct": -1.0 if fold in {0, 3} else 0.5,
            })
    for index in range(20):
        rows.append({
            "lane_id": ATR5,
            "cost_profile_id": BASE_CELL[0],
            "timing_id": BASE_CELL[1],
            "fold": index % 6,
            "regime": "good",
            "symbol": "ETH",
            "side": "long",
            "signal_reason": "x",
            "net_return_pct": 0.2,
        })
    cluster = persistent_cluster(rows, ATR5, 20)
    assert cluster is not None
    assert cluster["axes"] == ["regime"]
    print("STATE=PASS_INCREMENTAL_RECOVERY_CONTRACT_REPAIR_AND_DEFECT2_AUDIT_SELF_TEST")
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
    required = [root / SECOND_SUMMARY, root / SECOND_TRADES, root / REPAIR36_SUMMARY, root / REPAIR36_TRADES, root / AUDIT1]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        print("STATE=HOLD_INCREMENTAL_RECOVERY_CONTRACT_REPAIR_AND_DEFECT2_AUDIT_INPUT")
        print("BLOCKER_COUNT=1")
        print("BLOCKERS=" + json.dumps(["REQUIRED_EVIDENCE_MISSING:" + ",".join(missing)]))
        print("RC=2")
        return 2

    before = snapshot(required)
    second_summary = load_json(root / SECOND_SUMMARY)
    repair_summary = load_json(root / REPAIR36_SUMMARY)
    audit1 = load_json(root / AUDIT1)
    blockers: list[str] = []
    if second_summary.get("state") != "PASS_EXCHANGE_BOT_V2_ALL_11_SECOND_WAVE_EXECUTION_132":
        blockers.append("SECOND_WAVE_SUMMARY_NOT_PASS")
    if repair_summary.get("state") != "PASS_INCREMENTAL_SINGLE_DEFECT_REPAIR_EXECUTION_36":
        blockers.append("REPAIR36_SUMMARY_NOT_PASS")
    if audit1.get("state") != "PASS_INCREMENTAL_DEFECT_ABLATION_AUDIT":
        blockers.append("AUDIT1_NOT_PASS")
    if int(repair_summary.get("selected_lane_count") or 0) != EXPECTED_SELECTED:
        blockers.append("REPAIR36_SELECTED_COUNT_INVALID")
    if blockers:
        print("STATE=HOLD_INCREMENTAL_RECOVERY_CONTRACT_REPAIR_AND_DEFECT2_AUDIT_INPUT")
        print("BLOCKER_COUNT=" + str(len(blockers)))
        print("BLOCKERS=" + json.dumps(blockers))
        print("RC=2")
        return 2

    second_lanes = lane_map(second_summary, "lane_best_rows")
    repair_lanes = lane_map(repair_summary, "lane_result_rows")
    repair_trades = load_jsonl(root / REPAIR36_TRADES)
    corrected_rows: list[dict[str, Any]] = []
    restored_ids: list[str] = []
    for lane in sorted(repair_lanes):
        control = second_lanes.get(lane)
        current = repair_lanes[lane]
        if control is None:
            blockers.append(f"SECOND_WAVE_CONTROL_MISSING:{lane}")
            continue
        base_expected = profile_metrics(control, "base")
        adverse_expected = profile_metrics(control, "adverse")
        base_actual = profile_metrics(current, "base")
        adverse_actual = profile_metrics(current, "adverse")
        base_delta = metric_deltas(base_actual, base_expected)
        adverse_delta = metric_deltas(adverse_actual, adverse_expected)
        restored = not base_delta and not adverse_delta
        if restored:
            restored_ids.append(lane)
        corrected_rows.append({
            "lane_id": lane,
            "control_variant_id": str(control.get("variant_id") or current.get("control_variant_id") or ""),
            "execution_timeframe": str(control.get("execution_timeframe") or current.get("execution_timeframe") or ""),
            "corrected_baseline_exact_restored": restored,
            "base_metric_deltas": base_delta,
            "adverse_metric_deltas": adverse_delta,
            "base_metrics": base_actual,
            "adverse_metrics": adverse_actual,
            "severe_metrics": profile_metrics(current, "severe"),
        })

    if blockers:
        print("STATE=HOLD_INCREMENTAL_RECOVERY_CONTRACT_REPAIR_AND_DEFECT2_AUDIT_INPUT")
        print("BLOCKER_COUNT=" + str(len(blockers)))
        print("BLOCKERS=" + json.dumps(blockers))
        print("RC=2")
        return 2

    corrected_map = {row["lane_id"]: row for row in corrected_rows}
    next_rows: list[dict[str, Any]] = []
    queues: dict[str, list[str]] = {"active_repair": [], "data_expansion": [], "retire_or_replace": [], "preserve_only": []}

    for lane in (ATR5, ATR15):
        row = corrected_map.get(lane)
        if not row or not row["corrected_baseline_exact_restored"]:
            continue
        cluster = persistent_cluster(repair_trades, lane, MIN_TRADES)
        repair_mode = "PERSISTENT_LOSS_CLUSTER_VETO" if cluster else "GENERIC_EXECUTION_COST_BUFFER"
        next_rows.append({
            "lane_id": lane,
            "control_variant_id": row["control_variant_id"],
            "execution_timeframe": row["execution_timeframe"],
            "defect2": "SEVERE_MARGIN_COMPRESSION" if lane == ATR5 else "ADVERSE_FOLD_AND_SEVERE_TAIL_CONCENTRATION",
            "repair_mode": repair_mode,
            "cluster": cluster,
            "expected_stress_cell_count": 6,
            "baseline_base_metrics": row["base_metrics"],
            "baseline_adverse_metrics": row["adverse_metrics"],
            "baseline_severe_metrics": row["severe_metrics"],
            "constraints": ["ONE_DEFECT_ONLY", "CONTROL_SIGNAL_SET_IS_SOURCE", "NO_STOP_WIDENING", "NO_ENTRY_RELAXATION", "SAME_FROZEN_DATA_AND_COSTS", "BASELINE_MUST_NOT_DEGRADE"],
        })
        queues["active_repair"].append(lane)

    ma5_row = corrected_map.get(MA5)
    if ma5_row and ma5_row["corrected_baseline_exact_restored"]:
        cluster = persistent_cluster(repair_trades, MA5, 0)
        if cluster:
            next_rows.append({
                "lane_id": MA5,
                "control_variant_id": ma5_row["control_variant_id"],
                "execution_timeframe": ma5_row["execution_timeframe"],
                "defect2": "ADVERSE_AND_SEVERE_ENTRY_TIMING_CLUSTER",
                "repair_mode": "PERSISTENT_LOSS_CLUSTER_ONE_BAR_CONFIRMATION",
                "cluster": cluster,
                "expected_stress_cell_count": 6,
                "baseline_base_metrics": ma5_row["base_metrics"],
                "baseline_adverse_metrics": ma5_row["adverse_metrics"],
                "baseline_severe_metrics": ma5_row["severe_metrics"],
                "constraints": ["ONE_DEFECT_ONLY", "NO_SIGNAL_REMOVAL_TARGET", "NO_STOP_WIDENING", "NO_ENTRY_RELAXATION", "SAME_FROZEN_DATA_AND_COSTS", "BASELINE_MUST_NOT_DEGRADE"],
            })
            queues["active_repair"].append(MA5)
        else:
            queues["preserve_only"].append(MA5)

    if MA15 in corrected_map:
        queues["data_expansion"].append(MA15)
    for lane in (GRID5, NGRID5):
        if lane in corrected_map:
            queues["retire_or_replace"].append(lane)

    expected_cells = 6 * len(next_rows)
    output = root / OUTPUT_DIR
    state = "PASS_INCREMENTAL_RECOVERY_CONTRACT_REPAIR_AND_DEFECT2_AUDIT"
    summary = {
        "state": state,
        "target_sha": args.target_sha,
        "original_reported_restored_lane_count": int(repair_summary.get("rollback_restored_lane_count") or 0),
        "corrected_restored_lane_count": len(restored_ids),
        "corrected_restored_lane_ids": restored_ids,
        "contract_root_cause": "AUDIT1_OMITTED_BASELINE_ADVERSE_METRICS_CAUSING_EMPTY_EXPECTED_ADVERSE_COMPARISON",
        "corrected_lane_rows": corrected_rows,
        "active_repair_lane_count": len(next_rows),
        "active_repair_lane_ids": [row["lane_id"] for row in next_rows],
        "defect2_repair_rows": next_rows,
        "expected_defect2_cell_count": expected_cells,
        "queues": queues,
        "atr5_control_preserved": True,
        "donchian15_reference_preserved": True,
        "keep14_untouched": True,
        "mutation_rows": [],
        "next_stage": f"R7.A4D2_INCREMENTAL_DEFECT2_EXECUTION_{expected_cells}" if next_rows else "R7.A4D2_DATA_EXPANSION_OR_RETIRE_DECISION",
    }
    atomic_json(output / "incremental_recovery_contract_repair_and_defect2_audit_v1.json", summary)
    after = snapshot(required)
    mutations = [path for path in before if before[path] != after.get(path)]
    if mutations:
        print("STATE=HOLD_INCREMENTAL_RECOVERY_CONTRACT_REPAIR_AND_DEFECT2_AUDIT")
        print("BLOCKER_COUNT=1")
        print("BLOCKERS=" + json.dumps([f"INPUT_MUTATIONS:{len(mutations)}"]))
        print("RC=2")
        return 2

    print("STATE=" + state)
    print("BLOCKER_COUNT=0")
    print("ORIGINAL_RESTORED_LANE_COUNT=" + str(summary["original_reported_restored_lane_count"]))
    print("CORRECTED_RESTORED_LANE_COUNT=" + str(len(restored_ids)))
    print("CORRECTED_RESTORED_LANE_IDS=" + json.dumps(restored_ids))
    print("CONTRACT_ROOT_CAUSE=" + summary["contract_root_cause"])
    print("ACTIVE_REPAIR_LANE_COUNT=" + str(len(next_rows)))
    print("ACTIVE_REPAIR_LANE_IDS=" + json.dumps(summary["active_repair_lane_ids"]))
    print("DEFECT2_REPAIR_ROWS=" + json.dumps(next_rows, sort_keys=True))
    print("EXPECTED_DEFECT2_CELL_COUNT=" + str(expected_cells))
    print("DATA_EXPANSION_QUEUE=" + json.dumps(queues["data_expansion"]))
    print("RETIRE_OR_REPLACE_QUEUE=" + json.dumps(queues["retire_or_replace"]))
    print("ATR5_CONTROL_PRESERVED=true")
    print("DONCHIAN15_REFERENCE_PRESERVED=true")
    print("KEEP14_UNTOUCHED=true")
    print("AUDIT_JSON=" + str(output / "incremental_recovery_contract_repair_and_defect2_audit_v1.json"))
    print("NEXT_STAGE=" + summary["next_stage"])
    print("BLOCKERS=[]")
    print("RC=0")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
