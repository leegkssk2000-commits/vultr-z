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
from typing import Any

REPAIR_DIR = Path("runtime/r7a4d2_short_all_lane_architecture_repair_execution")
REPAIR_LOCK = REPAIR_DIR / "repair_lock_v1.json"
CELL_RESULTS = REPAIR_DIR / "repair_arm_cell_results_v1.jsonl"
TRADE_RESULTS = REPAIR_DIR / "repair_trade_results_v1.jsonl"
OUTPUT_PATH = Path("runtime/r7a4d2_short_second_order_repair_causal_audit/causal_audit_v1.json")
EXPECTED_LANES = 25
EXPECTED_ARMS = 75
EXPECTED_CELLS = 450
EXPECTED_STRESS_CELLS = 6
MIN_TRADES = 8
MIN_POSITIVE_CELLS = 4
SEVERE_CELL = ("cost_profile_2", "perturbation_1")
LOW_COST_NO_DELAY = ("cost_profile_0", "perturbation_0")
SEVERE_NO_DELAY = ("cost_profile_2", "perturbation_0")
LOW_COST_DELAY = ("cost_profile_0", "perturbation_1")


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
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def finite(value: Any, default: float = 0.0) -> float:
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    if value == float("inf"):
        return 1e100
    return default


def economic_pass(row: dict[str, Any]) -> bool:
    return bool(
        int(row.get("trade_count") or 0) >= MIN_TRADES
        and finite(row.get("profit_factor"), -1e100) > 1.0
        and finite(row.get("expectancy_r"), -1e100) > 0.0
        and finite(row.get("net_pnl_sum_pct"), -1e100) > 0.0
    )


def gate_status(row: dict[str, Any], positive_cells: int) -> dict[str, bool]:
    return {
        "trade_gate": int(row.get("trade_count") or 0) >= MIN_TRADES,
        "profit_factor_gate": finite(row.get("profit_factor"), -1e100) > 1.0,
        "expectancy_gate": finite(row.get("expectancy_r"), -1e100) > 0.0,
        "net_pnl_gate": finite(row.get("net_pnl_sum_pct"), -1e100) > 0.0,
        "stress_stability_gate": positive_cells >= MIN_POSITIVE_CELLS,
    }


def failure_reasons(gates: dict[str, bool]) -> list[str]:
    mapping = {
        "trade_gate": "SEVERE_TRADE_COUNT_LT_8",
        "profit_factor_gate": "SEVERE_PROFIT_FACTOR_LE_1",
        "expectancy_gate": "SEVERE_EXPECTANCY_R_LE_0",
        "net_pnl_gate": "SEVERE_NET_PNL_LE_0",
        "stress_stability_gate": "POSITIVE_STRESS_CELL_COUNT_LT_4",
    }
    return [mapping[key] for key, passed in gates.items() if not passed]


def root_cause(
    severe: dict[str, Any],
    low: dict[str, Any],
    severe_no_delay: dict[str, Any],
    low_delay: dict[str, Any],
    cells: list[dict[str, Any]],
    positive_cells: int,
) -> str:
    severe_trades = int(severe.get("trade_count") or 0)
    max_trades = max((int(row.get("trade_count") or 0) for row in cells), default=0)
    if severe_trades < MIN_TRADES:
        if max_trades < MIN_TRADES:
            return "SIGNAL_OR_ENTRY_SAMPLE_DEFICIT"
        return "SEVERE_COST_TIMING_SAMPLE_COLLAPSE"
    if economic_pass(severe) and positive_cells < MIN_POSITIVE_CELLS:
        return "CROSS_STRESS_INSTABILITY"
    if economic_pass(low) and not economic_pass(severe_no_delay):
        return "COST_FRICTION_SENSITIVITY"
    if economic_pass(severe_no_delay) and not economic_pass(severe):
        return "TIMING_LATENCY_SENSITIVITY"
    if economic_pass(low_delay) and not economic_pass(severe):
        return "COST_FRICTION_SENSITIVITY"
    pf = finite(severe.get("profit_factor"), 0.0)
    expectancy = finite(severe.get("expectancy_r"), 0.0)
    pnl = finite(severe.get("net_pnl_sum_pct"), 0.0)
    win_rate = finite(severe.get("win_rate_pct"), 0.0)
    payoff = finite(severe.get("payoff_ratio"), 0.0)
    if pf <= 1.0 and expectancy <= 0.0 and pnl <= 0.0:
        if win_rate >= 50.0 and payoff < 1.0:
            return "PAYOFF_COMPRESSION_EXIT_GEOMETRY"
        return "NEGATIVE_EDGE_ENTRY_OR_REGIME"
    if expectancy <= 0.0 or pnl <= 0.0:
        return "EXPECTANCY_PNL_COMPRESSION"
    if pf <= 1.0:
        return "PAYOFF_DISTRIBUTION_FAILURE"
    return "MULTI_AXIS_STRESS_FAILURE"


def recommendation(cause: str) -> str:
    return {
        "SIGNAL_OR_ENTRY_SAMPLE_DEFICIT": "REBUILD_SEMANTIC_ENTRY_OR_NATIVE_TIMEFRAME",
        "SEVERE_COST_TIMING_SAMPLE_COLLAPSE": "INCREASE_ENTRY_SPACING_AND_LATENCY_ROBUSTNESS",
        "CROSS_STRESS_INSTABILITY": "ADD_REGIME_GATING_AND_STABILITY_CONSTRAINT",
        "COST_FRICTION_SENSITIVITY": "INCREASE_GROSS_EXCURSION_OR_REDUCE_TURNOVER",
        "TIMING_LATENCY_SENSITIVITY": "REBUILD_CONFIRMATION_AND_DELAY_ROBUST_ENTRY",
        "PAYOFF_COMPRESSION_EXIT_GEOMETRY": "REDESIGN_STOP_TP_ASYMMETRY_AND_MFE_CAPTURE",
        "NEGATIVE_EDGE_ENTRY_OR_REGIME": "REBUILD_ENTRY_AND_REGIME_HYPOTHESIS",
        "EXPECTANCY_PNL_COMPRESSION": "REDESIGN_TIMEOUT_PARTIAL_AND_RUNNER_CAPTURE",
        "PAYOFF_DISTRIBUTION_FAILURE": "REBALANCE_WIN_RATE_PAYOFF_DISTRIBUTION",
        "MULTI_AXIS_STRESS_FAILURE": "TARGETED_MULTI_AXIS_CAUSAL_REPAIR",
    }.get(cause, "DIAGNOSTIC_HOLD")


def ranking_key(row: dict[str, Any]) -> tuple[Any, ...]:
    severe = row["severe_metrics"]
    return (
        int(row["gate_pass_count"]),
        int(row["positive_stress_cell_count"]),
        int(severe.get("trade_count") or 0),
        finite(severe.get("expectancy_r"), -1e100),
        finite(severe.get("profit_factor"), -1e100),
        finite(severe.get("net_pnl_sum_pct"), -1e100),
        -finite(severe.get("max_drawdown_pct"), 1e100),
    )


def self_test() -> int:
    base = {
        "trade_count": 20,
        "profit_factor": 1.3,
        "expectancy_r": 0.1,
        "net_pnl_sum_pct": 1.0,
        "win_rate_pct": 52.0,
        "payoff_ratio": 1.1,
    }
    weak = dict(base, profit_factor=0.8, expectancy_r=-0.1, net_pnl_sum_pct=-1.0)
    cause = root_cause(weak, base, weak, base, [base, weak], 2)
    assert cause == "COST_FRICTION_SENSITIVITY"
    gates = gate_status(weak, 2)
    assert len(failure_reasons(gates)) == 4
    print("STATE=PASS_SHORT_SECOND_ORDER_REPAIR_CAUSAL_AUDIT_SELF_TEST")
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
    required = [root / REPAIR_LOCK, root / CELL_RESULTS, root / TRADE_RESULTS]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        print("STATE=HOLD_SHORT_SECOND_ORDER_REPAIR_CAUSAL_AUDIT_INPUT")
        print("BLOCKER_COUNT=1")
        print("BLOCKERS=" + json.dumps(["REQUIRED_EVIDENCE_MISSING:" + ",".join(missing)]))
        print("RC=2")
        return 2

    before = {str(path): sha256_file(path) for path in required}
    lock = load_json(root / REPAIR_LOCK)
    cells = load_jsonl(root / CELL_RESULTS)
    blockers: list[str] = []
    if lock.get("state") != "PASS_SHORT_ALL_LANE_ARCHITECTURE_REPAIR_EXECUTION":
        blockers.append("REPAIR_EXECUTION_NOT_PASS")
    if int(lock.get("strategy_lane_count", -1)) != EXPECTED_LANES:
        blockers.append("STRATEGY_LANE_COUNT_INVALID")
    if int(lock.get("candidate_arm_count", -1)) != EXPECTED_ARMS:
        blockers.append("CANDIDATE_ARM_COUNT_INVALID")
    if int(lock.get("repair_arm_cell_result_count", -1)) != EXPECTED_CELLS or len(cells) != EXPECTED_CELLS:
        blockers.append(f"CELL_COUNT_INVALID:{len(cells)}")
    if int(lock.get("economic_repair_survivor_count", -1)) != 0:
        blockers.append("ZERO_SURVIVOR_PRECONDITION_NOT_MET")
    if str(lock.get("repair_arm_cell_results_sha256") or "") != sha256_file(root / CELL_RESULTS):
        blockers.append("CELL_RESULTS_SHA_MISMATCH")
    if str(lock.get("repair_trade_results_sha256") or "") != sha256_file(root / TRADE_RESULTS):
        blockers.append("TRADE_RESULTS_SHA_MISMATCH")

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in cells:
        grouped[(str(row.get("lane_id") or ""), str(row.get("arm_id") or ""))].append(row)
    if len(grouped) != EXPECTED_ARMS:
        blockers.append(f"ARM_GROUP_COUNT_INVALID:{len(grouped)}")
    if any(len(rows) != EXPECTED_STRESS_CELLS for rows in grouped.values()):
        blockers.append("STRESS_CELL_PER_ARM_INVALID")
    if blockers:
        print("STATE=HOLD_SHORT_SECOND_ORDER_REPAIR_CAUSAL_AUDIT_INPUT")
        print("BLOCKER_COUNT=" + str(len(blockers)))
        print("BLOCKERS=" + json.dumps(blockers, ensure_ascii=False))
        print("RC=2")
        return 2

    arm_rows: list[dict[str, Any]] = []
    for (lane_id, arm_id), rows in sorted(grouped.items()):
        by_cell = {
            (str(row.get("cost_profile_id")), str(row.get("perturbation_id"))): row
            for row in rows
        }
        severe = by_cell[SEVERE_CELL]
        low = by_cell[LOW_COST_NO_DELAY]
        severe_no_delay = by_cell[SEVERE_NO_DELAY]
        low_delay = by_cell[LOW_COST_DELAY]
        positive_cells = sum(1 for row in rows if economic_pass(row))
        gates = gate_status(severe, positive_cells)
        cause = root_cause(severe, low, severe_no_delay, low_delay, rows, positive_cells)
        arm_rows.append({
            "lane_id": lane_id,
            "strategy_id": str(severe.get("strategy_id") or ""),
            "family": str(severe.get("family") or ""),
            "timeframe": str(severe.get("timeframe") or ""),
            "arm_id": arm_id,
            "arm_axis": severe.get("arm_axis"),
            "severe_metrics": severe,
            "low_cost_no_delay_metrics": low,
            "severe_no_delay_metrics": severe_no_delay,
            "low_cost_delay_metrics": low_delay,
            "positive_stress_cell_count": positive_cells,
            "gate_status": gates,
            "gate_pass_count": sum(1 for value in gates.values() if value),
            "failure_reasons": failure_reasons(gates),
            "primary_root_cause": cause,
            "recommended_repair": recommendation(cause),
        })

    by_strategy: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in arm_rows:
        by_strategy[str(row["strategy_id"])].append(row)
    strategy_rows: list[dict[str, Any]] = []
    for strategy_id, rows in sorted(by_strategy.items()):
        ranked = sorted(rows, key=ranking_key, reverse=True)
        best = ranked[0]
        strategy_rows.append({
            "strategy_id": strategy_id,
            "lane_count": len({str(row["lane_id"]) for row in rows}),
            "arm_count": len(rows),
            "best_near_miss_lane_id": best["lane_id"],
            "best_near_miss_arm_id": best["arm_id"],
            "best_near_miss_arm_axis": best["arm_axis"],
            "best_gate_pass_count": best["gate_pass_count"],
            "best_positive_stress_cell_count": best["positive_stress_cell_count"],
            "primary_root_cause": best["primary_root_cause"],
            "recommended_repair": best["recommended_repair"],
            "top_near_misses": ranked[:3],
        })

    cause_histogram = dict(sorted(Counter(row["primary_root_cause"] for row in arm_rows).items()))
    strategy_cause_histogram = dict(sorted(Counter(row["primary_root_cause"] for row in strategy_rows).items()))
    gate_failure_histogram = Counter()
    for row in arm_rows:
        gate_failure_histogram.update(row["failure_reasons"])
    high_near_miss = [row for row in strategy_rows if int(row["best_gate_pass_count"]) >= 3]

    after = {str(path): sha256_file(path) for path in required}
    mutations = sorted(path for path in before if before[path] != after[path])
    if mutations:
        blockers.append("INPUT_MUTATION_DETECTED:" + json.dumps(mutations))

    state = "PASS_SHORT_SECOND_ORDER_REPAIR_CAUSAL_AUDIT" if not blockers else "HOLD_SHORT_SECOND_ORDER_REPAIR_CAUSAL_AUDIT"
    next_stage = (
        "R7.A4D2_SHORT_SECOND_ORDER_TARGETED_REPAIR_PLAN"
        if not blockers and high_near_miss
        else "R7.A4D2_SHORT_STRATEGY_FAMILY_HYPOTHESIS_REBUILD_PLAN"
    )
    report = {
        "schema": "r7a4d2_short_second_order_repair_causal_audit_v1",
        "official_stage": "R7.A4D2_SHORT_SECOND_ORDER_REPAIR_CAUSAL_AUDIT",
        "state": state,
        "target_commit": args.target_sha,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "strategy_count": len(strategy_rows),
        "strategy_lane_count": EXPECTED_LANES,
        "candidate_arm_count": len(arm_rows),
        "stress_cell_count": len(cells),
        "economic_repair_survivor_count": 0,
        "arm_root_cause_histogram": cause_histogram,
        "strategy_root_cause_histogram": strategy_cause_histogram,
        "gate_failure_histogram": dict(sorted(gate_failure_histogram.items())),
        "high_near_miss_strategy_count": len(high_near_miss),
        "high_near_miss_strategy_ids": [row["strategy_id"] for row in high_near_miss],
        "strategy_causal_rows": strategy_rows,
        "arm_causal_rows": arm_rows,
        "input_mutation_paths": mutations,
        "selection_policy": "NO_ARBITRARY_SCORE_GATE_COUNT_THEN_SEVERE_ECONOMICS_STABILITY_AND_DRAWDOWN",
        "next_stage": next_stage,
    }
    atomic_json(root / OUTPUT_PATH, report)
    print("STATE=" + state)
    print("BLOCKER_COUNT=" + str(len(blockers)))
    print("STRATEGY_COUNT=" + str(len(strategy_rows)))
    print("CANDIDATE_ARM_COUNT=" + str(len(arm_rows)))
    print("STRESS_CELL_COUNT=" + str(len(cells)))
    print("ARM_ROOT_CAUSE_HISTOGRAM=" + json.dumps(cause_histogram, sort_keys=True))
    print("STRATEGY_ROOT_CAUSE_HISTOGRAM=" + json.dumps(strategy_cause_histogram, sort_keys=True))
    print("GATE_FAILURE_HISTOGRAM=" + json.dumps(dict(sorted(gate_failure_histogram.items())), sort_keys=True))
    print("HIGH_NEAR_MISS_STRATEGY_COUNT=" + str(len(high_near_miss)))
    print("HIGH_NEAR_MISS_STRATEGY_IDS=" + json.dumps([row["strategy_id"] for row in high_near_miss]))
    print("STRATEGY_CAUSAL_ROWS=" + json.dumps(strategy_rows, ensure_ascii=False, sort_keys=True))
    print("AUDIT_JSON=" + str(root / OUTPUT_PATH))
    print("NEXT_STAGE=" + next_stage)
    print("BLOCKERS=" + json.dumps(blockers, ensure_ascii=False))
    print("RC=" + ("0" if not blockers else "2"))
    return 0 if not blockers else 2


if __name__ == "__main__":
    raise SystemExit(main())
