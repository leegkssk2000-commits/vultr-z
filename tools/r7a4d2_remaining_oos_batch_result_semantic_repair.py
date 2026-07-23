#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

INPUT = Path("runtime/r7a4d2_remaining_survivor_independent_oos_batch_execution/remaining_survivor_independent_oos_batch_summary_v1.json")
OUTPUT_DIR = Path("runtime/r7a4d2_remaining_oos_batch_result_semantic_repair")
OUTPUT = OUTPUT_DIR / "remaining_oos_batch_semantic_repair_summary_v1.json"
EXPECTED_CANDIDATES = 10
EXPECTED_SEGMENTS = 240
EXPECTED_STRESS_CELLS = 6


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def classify(row: dict[str, Any]) -> tuple[str, str]:
    checks = row.get("coverage_checks") if isinstance(row.get("coverage_checks"), dict) else {}
    failures = row.get("execution_failures") if isinstance(row.get("execution_failures"), list) else []
    profiles = row.get("profile_metrics") if isinstance(row.get("profile_metrics"), dict) else {}
    stress_cells = int(row.get("stress_cell_count") or 0)
    coverage_ready = bool(row.get("coverage_ready"))

    non_execution_coverage = all(bool(checks.get(key)) for key in (
        "strict_forward_segment_gate", "unique_event_gate", "symbol_gate", "fold_coverage_gate"
    ))
    source_replay_ok = bool(checks.get("source_replay_gate"))

    if bool(row.get("robust_survivor")):
        return "ROBUST_SURVIVOR", "ALL_ROBUST_GATES_PASS"
    if bool(row.get("conditional_survivor")):
        return "CONDITIONAL_SURVIVOR", "BASE_AND_ADVERSE_PASS_SEVERE_NOT_FULL_PASS"
    if failures or (non_execution_coverage and not source_replay_ok):
        return "EXECUTION_HOLD", "EXECUTION_FAILURE_OR_SOURCE_REPLAY_FAILURE"
    if not coverage_ready:
        return "DATA_COVERAGE_HOLD", "EVENT_SYMBOL_OR_FOLD_COVERAGE_INSUFFICIENT"
    if stress_cells != EXPECTED_STRESS_CELLS:
        return "EXECUTION_HOLD", f"STRESS_CELL_COUNT_{stress_cells}_EXPECTED_{EXPECTED_STRESS_CELLS}"

    trade_counts = [int((profiles.get(profile) or {}).get("trade_count") or 0) for profile in ("base", "adverse", "severe")]
    if max(trade_counts, default=0) == 0:
        return "EXECUTION_HOLD", "SIGNALS_PRESENT_BUT_ZERO_EXECUTABLE_TRADES"

    return "ECONOMIC_FAIL", "FULL_COVERAGE_EXECUTED_BUT_SURVIVOR_GATES_FAILED"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--target-sha", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    source_path = root / INPUT
    if not source_path.is_file():
        print("STATE=HOLD_REMAINING_OOS_BATCH_SEMANTIC_REPAIR_INPUT")
        print("BLOCKERS=[\"SOURCE_SUMMARY_MISSING\"]")
        print("RC=2")
        return 2

    source = load_json(source_path)
    blockers: list[str] = []
    if source.get("state") != "PASS_REMAINING_SURVIVOR_INDEPENDENT_OOS_BATCH":
        blockers.append("SOURCE_BATCH_STATE_NOT_PASS")
    if int(source.get("blocker_count") or 0) != 0:
        blockers.append("SOURCE_BATCH_BLOCKED")
    if int(source.get("candidate_count") or -1) != EXPECTED_CANDIDATES:
        blockers.append("SOURCE_CANDIDATE_COUNT_INVALID")
    if int(source.get("strict_forward_oos_segment_count") or -1) != EXPECTED_SEGMENTS:
        blockers.append("SOURCE_SEGMENT_COUNT_INVALID")
    if int(source.get("mutation_path_count") or 0) != 0:
        blockers.append("SOURCE_INPUT_MUTATION_DETECTED")

    candidates = [row for row in source.get("candidate_results", []) if isinstance(row, dict)]
    if len(candidates) != EXPECTED_CANDIDATES:
        blockers.append("SOURCE_RESULT_COUNT_INVALID")

    if blockers:
        print("STATE=HOLD_REMAINING_OOS_BATCH_SEMANTIC_REPAIR_INPUT")
        print("BLOCKER_COUNT=" + str(len(blockers)))
        print("BLOCKERS=" + json.dumps(blockers))
        print("RC=2")
        return 2

    repaired: list[dict[str, Any]] = []
    for row in candidates:
        semantic_class, reason = classify(row)
        profiles = row.get("profile_metrics") if isinstance(row.get("profile_metrics"), dict) else {}
        repaired.append({
            "lane_id": row.get("lane_id"),
            "variant_id": row.get("variant_id"),
            "execution_timeframe": row.get("execution_timeframe"),
            "source_classification": row.get("classification"),
            "semantic_classification": semantic_class,
            "semantic_reason": reason,
            "coverage_ready": bool(row.get("coverage_ready")),
            "coverage_checks": row.get("coverage_checks"),
            "unique_signal_count": int(row.get("unique_signal_count") or 0),
            "signal_symbol_count": int(row.get("signal_symbol_count") or 0),
            "signal_fold_count": int(row.get("signal_fold_count") or 0),
            "stress_cell_count": int(row.get("stress_cell_count") or 0),
            "execution_failure_count": len(row.get("execution_failures") or []),
            "base_net_r": finite((profiles.get("base") or {}).get("net_r_sum")),
            "base_pf": finite((profiles.get("base") or {}).get("profit_factor")),
            "adverse_net_r": finite((profiles.get("adverse") or {}).get("net_r_sum")),
            "adverse_pf": finite((profiles.get("adverse") or {}).get("profit_factor")),
            "severe_net_r": finite((profiles.get("severe") or {}).get("net_r_sum")),
            "severe_pf": finite((profiles.get("severe") or {}).get("profit_factor")),
            "next_stage": {
                "ROBUST_SURVIVOR": "R7.A4D2_SURVIVOR_PORTFOLIO_QUEUE",
                "CONDITIONAL_SURVIVOR": "R7.A4D2_CONDITIONAL_RESIDUAL_LOSS_AUDIT",
                "ECONOMIC_FAIL": "R7.A4D2_ECONOMIC_FAIL_ALL_LOSS_MECHANISM_AUDIT",
                "DATA_COVERAGE_HOLD": "R7.A4D2_STRICT_FORWARD_DATA_COVERAGE_EXTENSION",
                "EXECUTION_HOLD": "R7.A4D2_EXECUTION_ADAPTER_ZERO_TRADE_AUDIT",
            }[semantic_class],
        })

    counts = dict(sorted(Counter(row["semantic_classification"] for row in repaired).items()))
    output = {
        "schema": "r7a4d2_remaining_oos_batch_result_semantic_repair_v1",
        "official_stage": "R7.A4D2_REMAINING_OOS_BATCH_RESULT_SEMANTIC_REPAIR",
        "state": "PASS_REMAINING_OOS_BATCH_RESULT_SEMANTIC_REPAIR",
        "target_commit": args.target_sha,
        "source_summary_path": str(INPUT),
        "candidate_count": len(repaired),
        "semantic_classification_counts": counts,
        "candidate_results": repaired,
        "blind_redesign_allowed": False,
        "parameter_optimization_allowed": False,
        "threshold_relaxation_allowed": False,
        "strategy_mutation_allowed": False,
        "registry_mutation_allowed": False,
        "shadow_start_allowed": False,
        "paper_live_order_allowed": False,
        "next_stage": "R7.A4D2_SPLIT_EXECUTION_HOLD_COVERAGE_HOLD_AND_ECONOMIC_FAIL",
        "blockers": [],
    }
    atomic_json(root / OUTPUT, output)

    print("STATE=PASS_REMAINING_OOS_BATCH_RESULT_SEMANTIC_REPAIR")
    print("BLOCKER_COUNT=0")
    for key in ("ROBUST_SURVIVOR", "CONDITIONAL_SURVIVOR", "ECONOMIC_FAIL", "DATA_COVERAGE_HOLD", "EXECUTION_HOLD"):
        print(f"{key}_COUNT={counts.get(key, 0)}")
    for row in repaired:
        print(
            "SEMANTIC_RESULT="
            f"{row['lane_id']}|{row['variant_id']}|CLASS={row['semantic_classification']}|"
            f"REASON={row['semantic_reason']}|EVENTS={row['unique_signal_count']}|"
            f"SYMBOLS={row['signal_symbol_count']}|FOLDS={row['signal_fold_count']}|CELLS={row['stress_cell_count']}|"
            f"BASE_R={row['base_net_r']:.6f}|ADVERSE_R={row['adverse_net_r']:.6f}|SEVERE_R={row['severe_net_r']:.6f}"
        )
    print("BLIND_REDESIGN_ALLOWED=false")
    print("SUMMARY_JSON=" + str(root / OUTPUT))
    print("NEXT_STAGE=R7.A4D2_SPLIT_EXECUTION_HOLD_COVERAGE_HOLD_AND_ECONOMIC_FAIL")
    print("BLOCKERS=[]")
    print("RC=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
