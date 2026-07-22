#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

EXECUTION_DIR = Path("runtime/r7a4d2_short_raw_geometry_and_simple_benchmark_execution")
PLAN_PATH = Path("runtime/r7a4d2_short_raw_geometry_and_simple_benchmark_execution_plan/execution_plan_v1.json")
OUTPUT_DIR = Path("runtime/r7a4d2_short_raw_geometry_mutation_and_lane_economic_diagnose")
EXPECTED_SCANS = 864
EXPECTED_STRATEGY_LANES = 25
EXPECTED_BENCHMARK_LANES = 11


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


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


def resolved(path: str, root: Path) -> Path:
    candidate = Path(path)
    return candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()


def inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def classify_mutation(path_value: str, root: Path) -> str:
    path = resolved(path_value, root)
    critical_inputs = (
        (root / "backend/strategy25").resolve(),
        (root / "data/historical_ohlcv").resolve(),
        (root / "runtime/r7a4c_historical_simulation_input_lineage").resolve(),
        (root / "runtime/r7a4d2_short_scalp_required_ohlcv_schema_adapter_bind").resolve(),
        (root / "runtime/r7a4d2_short_raw_geometry_and_simple_benchmark_execution_plan").resolve(),
    )
    if any(inside(path, parent) for parent in critical_inputs):
        return "CRITICAL_INPUT_MUTATION"
    if inside(path, (root / "runtime/exact25_edge_v1").resolve()):
        return "EXTERNAL_OPERATIONAL_VOLATILE_MUTATION"
    if path == Path("/etc/caddy/Caddyfile"):
        return "EXTERNAL_INFRA_MUTATION"
    if inside(path, (root / EXECUTION_DIR).resolve()):
        return "SELF_OUTPUT_MUTATION"
    return "OTHER_PROTECTED_MUTATION"


def number(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def lane_metrics(summary: dict[str, Any]) -> dict[str, float | int | None]:
    return {
        "measurement_signal_count": int(summary.get("measurement_signal_count") or 0),
        "semantic_eligible_signal_count": int(summary.get("semantic_eligible_signal_count") or 0),
        "severe_net_available_r_positive_rate_pct": number(
            summary.get("severe_net_available_r_positive_rate_pct")
        ),
        "median_full_forward_mfe_pct": number(summary.get("median_full_forward_mfe_pct")),
        "median_full_forward_mae_pct": number(summary.get("median_full_forward_mae_pct")),
        "median_severe_friction_r": number(summary.get("median_severe_friction_r")),
        "median_structural_stop_distance_pct": number(
            summary.get("median_structural_stop_distance_pct")
        ),
    }


def compare_metric(strategy: float | None, benchmark: float | None, higher_is_better: bool) -> int | None:
    if strategy is None or benchmark is None:
        return None
    if strategy == benchmark:
        return 0
    if higher_is_better:
        return 1 if strategy > benchmark else -1
    return 1 if strategy < benchmark else -1


def compare_lanes(
    strategy_lane: dict[str, Any], benchmark_lane: dict[str, Any], by_lane: dict[str, Any]
) -> dict[str, Any]:
    strategy_id = str(strategy_lane["lane_id"])
    benchmark_id = str(benchmark_lane["lane_id"])
    strategy = lane_metrics(by_lane.get(strategy_id, {}))
    benchmark = lane_metrics(by_lane.get(benchmark_id, {}))
    comparisons = {
        "severe_positive_rate": compare_metric(
            number(strategy["severe_net_available_r_positive_rate_pct"]),
            number(benchmark["severe_net_available_r_positive_rate_pct"]),
            True,
        ),
        "mfe": compare_metric(
            number(strategy["median_full_forward_mfe_pct"]),
            number(benchmark["median_full_forward_mfe_pct"]),
            True,
        ),
        "mae": compare_metric(
            number(strategy["median_full_forward_mae_pct"]),
            number(benchmark["median_full_forward_mae_pct"]),
            False,
        ),
        "friction_r": compare_metric(
            number(strategy["median_severe_friction_r"]),
            number(benchmark["median_severe_friction_r"]),
            False,
        ),
    }
    known = [value for value in comparisons.values() if value is not None]
    if int(strategy["semantic_eligible_signal_count"] or 0) == 0:
        classification = "NO_ELIGIBLE_STRATEGY_SIGNAL"
    elif not known:
        classification = "INSUFFICIENT_COMPARABLE_METRICS"
    elif all(value >= 0 for value in known) and any(value > 0 for value in known):
        classification = "PARETO_DOMINATES_BENCHMARK"
    elif all(value <= 0 for value in known) and any(value < 0 for value in known):
        classification = "PARETO_DOMINATED_BY_BENCHMARK"
    elif all(value == 0 for value in known):
        classification = "PARETO_EQUAL"
    else:
        classification = "MIXED_TRADEOFF"

    def delta(key: str) -> float | None:
        left = number(strategy[key])
        right = number(benchmark[key])
        return left - right if left is not None and right is not None else None

    return {
        "strategy_lane_id": strategy_id,
        "benchmark_lane_id": benchmark_id,
        "strategy_id": strategy_lane.get("strategy_id"),
        "family": strategy_lane.get("family"),
        "timeframe": strategy_lane.get("timeframe"),
        "classification": classification,
        "metric_comparisons": comparisons,
        "strategy_metrics": strategy,
        "benchmark_metrics": benchmark,
        "deltas": {
            "severe_net_available_r_positive_rate_pct": delta(
                "severe_net_available_r_positive_rate_pct"
            ),
            "median_full_forward_mfe_pct": delta("median_full_forward_mfe_pct"),
            "median_full_forward_mae_pct": delta("median_full_forward_mae_pct"),
            "median_severe_friction_r": delta("median_severe_friction_r"),
            "median_structural_stop_distance_pct": delta(
                "median_structural_stop_distance_pct"
            ),
        },
    }


def self_test() -> int:
    root = Path("/home/z/z")
    assert classify_mutation(
        "/home/z/z/runtime/exact25_edge_v1/display_adapter/telegram_status_latest.json", root
    ) == "EXTERNAL_OPERATIONAL_VOLATILE_MUTATION"
    assert classify_mutation(
        "/home/z/z/backend/strategy25/canonical_strategy_registry_v1.json", root
    ) == "CRITICAL_INPUT_MUTATION"
    strategy_lane = {
        "lane_id": "strategy:s:5m",
        "strategy_id": "s",
        "family": "trend",
        "timeframe": "5m",
    }
    benchmark_lane = {
        "lane_id": "benchmark:b:5m",
        "benchmark_id": "b",
        "family": "trend",
        "timeframe": "5m",
    }
    by_lane = {
        "strategy:s:5m": {
            "measurement_signal_count": 10,
            "semantic_eligible_signal_count": 10,
            "severe_net_available_r_positive_rate_pct": 60.0,
            "median_full_forward_mfe_pct": 0.8,
            "median_full_forward_mae_pct": 0.4,
            "median_severe_friction_r": 0.5,
        },
        "benchmark:b:5m": {
            "measurement_signal_count": 10,
            "semantic_eligible_signal_count": 10,
            "severe_net_available_r_positive_rate_pct": 50.0,
            "median_full_forward_mfe_pct": 0.7,
            "median_full_forward_mae_pct": 0.5,
            "median_severe_friction_r": 0.6,
        },
    }
    assert compare_lanes(strategy_lane, benchmark_lane, by_lane)["classification"] == "PARETO_DOMINATES_BENCHMARK"
    print("STATE=PASS_SHORT_RAW_GEOMETRY_MUTATION_LANE_DIAGNOSE_SELF_TEST")
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
    aggregate_path = root / EXECUTION_DIR / "aggregate_v1.json"
    proof_path = root / EXECUTION_DIR / "proof_v1.json"
    scans_path = root / EXECUTION_DIR / "scan_results_v1.jsonl"
    geometry_path = root / EXECUTION_DIR / "signal_geometry_v1.jsonl"
    plan_path = root / PLAN_PATH
    required = [aggregate_path, proof_path, scans_path, geometry_path, plan_path]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        print("STATE=HOLD_SHORT_RAW_GEOMETRY_MUTATION_AND_LANE_ECONOMIC_DIAGNOSE_INPUT")
        print("BLOCKER_COUNT=1")
        print("BLOCKERS=" + json.dumps(["REQUIRED_EVIDENCE_MISSING:" + ",".join(missing)]))
        print("RC=2")
        return 2

    aggregate = load_json(aggregate_path)
    proof = load_json(proof_path)
    plan = load_json(plan_path)
    blockers: list[str] = []
    if int(aggregate.get("scan_count", -1)) != EXPECTED_SCANS:
        blockers.append("SCAN_COUNT_INVALID")
    if int(aggregate.get("completed_scan_count", -1)) != EXPECTED_SCANS:
        blockers.append("COMPLETED_SCAN_COUNT_INVALID")
    if int(aggregate.get("failed_scan_count", -1)) != 0:
        blockers.append("FAILED_SCAN_COUNT_NONZERO")
    if int(aggregate.get("failure_count", -1)) != 0:
        blockers.append("FAILURE_COUNT_NONZERO")
    if int(aggregate.get("side_effect_attempt_count", -1)) != 0:
        blockers.append("SIDE_EFFECT_ATTEMPT_NONZERO")
    if sha256_file(scans_path) != str(aggregate.get("scan_results_sha256") or ""):
        blockers.append("SCAN_RESULTS_SHA_MISMATCH")
    if sha256_file(geometry_path) != str(aggregate.get("signal_geometry_sha256") or ""):
        blockers.append("SIGNAL_GEOMETRY_SHA_MISMATCH")
    if str(proof.get("scan_results_sha256") or "") != str(aggregate.get("scan_results_sha256") or ""):
        blockers.append("PROOF_SCAN_SHA_MISMATCH")
    if str(proof.get("signal_geometry_sha256") or "") != str(aggregate.get("signal_geometry_sha256") or ""):
        blockers.append("PROOF_GEOMETRY_SHA_MISMATCH")

    mutation_paths = [str(value) for value in proof.get("mutation_paths", [])]
    mutation_rows = [
        {"path": path, "classification": classify_mutation(path, root)} for path in mutation_paths
    ]
    mutation_histogram = dict(sorted(Counter(row["classification"] for row in mutation_rows).items()))
    critical_mutations = [
        row for row in mutation_rows
        if row["classification"] in {
            "CRITICAL_INPUT_MUTATION", "SELF_OUTPUT_MUTATION", "OTHER_PROTECTED_MUTATION"
        }
    ]
    result_reusable = not blockers and not critical_mutations

    strategy_lanes = [
        row for row in plan.get("strategy_lanes", []) if isinstance(row, dict)
    ]
    benchmark_lanes = [
        row for row in plan.get("benchmark_lanes", []) if isinstance(row, dict)
    ]
    if len(strategy_lanes) != EXPECTED_STRATEGY_LANES:
        blockers.append(f"STRATEGY_LANE_COUNT_INVALID:{len(strategy_lanes)}")
    if len(benchmark_lanes) != EXPECTED_BENCHMARK_LANES:
        blockers.append(f"BENCHMARK_LANE_COUNT_INVALID:{len(benchmark_lanes)}")
    benchmark_by_family_timeframe = {
        (str(row.get("family")), str(row.get("timeframe"))): row for row in benchmark_lanes
    }
    by_lane = aggregate.get("by_lane") if isinstance(aggregate.get("by_lane"), dict) else {}
    comparisons: list[dict[str, Any]] = []
    for lane in strategy_lanes:
        benchmark = benchmark_by_family_timeframe.get(
            (str(lane.get("family")), str(lane.get("timeframe")))
        )
        if benchmark is None:
            blockers.append(f"BENCHMARK_PAIR_MISSING:{lane.get('lane_id')}")
            continue
        comparisons.append(compare_lanes(lane, benchmark, by_lane))

    class_histogram = dict(sorted(Counter(row["classification"] for row in comparisons).items()))
    top_positive_rate_delta = sorted(
        comparisons,
        key=lambda row: (
            row["deltas"].get("severe_net_available_r_positive_rate_pct") is not None,
            row["deltas"].get("severe_net_available_r_positive_rate_pct") or float("-inf"),
        ),
        reverse=True,
    )[:10]
    result_reusable = result_reusable and not blockers
    decision = (
        "REUSE_864_RESULTS_AND_PROCEED_TO_DISCOVERY_EXIT_PARAMETER_LOCK"
        if result_reusable
        else "INVALIDATE_OR_HOLD_864_RESULTS_AND_REEXECUTE_AFTER_CAUSE_CLOSURE"
    )
    next_stage = (
        "R7.A4D2_SHORT_DISCOVERY_EXIT_AND_PARAMETER_LOCK"
        if result_reusable
        else "R7.A4D2_SHORT_RAW_GEOMETRY_AND_SIMPLE_BENCHMARK_EXECUTION_REPAIR"
    )
    report = {
        "schema": "r7a4d2_short_raw_geometry_mutation_and_lane_economic_diagnose_v1",
        "official_stage": "R7.A4D2_SHORT_RAW_GEOMETRY_MUTATION_AND_LANE_ECONOMIC_DIAGNOSE",
        "state": "PASS_SHORT_RAW_GEOMETRY_MUTATION_AND_LANE_ECONOMIC_DIAGNOSE" if not blockers else "HOLD_SHORT_RAW_GEOMETRY_MUTATION_AND_LANE_ECONOMIC_DIAGNOSE",
        "target_commit": args.target_sha,
        "diagnose_blockers": blockers,
        "evidence_integrity_pass": not blockers,
        "result_reusable": result_reusable,
        "decision": decision,
        "mutation_path_count": len(mutation_rows),
        "mutation_rows": mutation_rows,
        "mutation_class_histogram": mutation_histogram,
        "comparison_count": len(comparisons),
        "comparison_class_histogram": class_histogram,
        "lane_comparisons": comparisons,
        "top_severe_positive_rate_delta": top_positive_rate_delta,
        "next_stage": next_stage,
    }
    atomic_json(root / OUTPUT_DIR / "diagnose_v1.json", report)
    print("STATE=" + report["state"])
    print("BLOCKER_COUNT=" + str(len(blockers)))
    print("EVIDENCE_INTEGRITY_PASS=" + str(not blockers).lower())
    print("RESULT_REUSABLE=" + str(result_reusable).lower())
    print("DECISION=" + decision)
    print("MUTATION_PATH_COUNT=" + str(len(mutation_rows)))
    print("MUTATION_ROWS=" + json.dumps(mutation_rows, ensure_ascii=False, sort_keys=True))
    print("MUTATION_CLASS_HISTOGRAM=" + json.dumps(mutation_histogram, sort_keys=True))
    print("STRATEGY_LANE_COUNT=" + str(len(strategy_lanes)))
    print("BENCHMARK_LANE_COUNT=" + str(len(benchmark_lanes)))
    print("COMPARISON_COUNT=" + str(len(comparisons)))
    print("COMPARISON_CLASS_HISTOGRAM=" + json.dumps(class_histogram, sort_keys=True))
    print("TOP_SEVERE_POSITIVE_RATE_DELTA=" + json.dumps(top_positive_rate_delta, ensure_ascii=False, sort_keys=True))
    print("DIAGNOSE_JSON=" + str(root / OUTPUT_DIR / "diagnose_v1.json"))
    print("NEXT_STAGE=" + next_stage)
    print("BLOCKERS=" + json.dumps(blockers, ensure_ascii=False))
    print("RC=" + ("0" if not blockers else "2"))
    return 0 if not blockers else 2


if __name__ == "__main__":
    raise SystemExit(main())
