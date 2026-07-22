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

EXECUTION_PLAN = Path("runtime/r7a4d2_short_raw_geometry_and_simple_benchmark_execution_plan/execution_plan_v1.json")
REPAIR_PLAN = Path("runtime/r7a4d2_short_all_lane_architecture_repair_plan/repair_plan_v1.json")
REPAIR_DIR = Path("runtime/r7a4d2_short_all_lane_architecture_repair_execution")
REPAIR_LOCK = REPAIR_DIR / "repair_lock_v1.json"
CELL_RESULTS = REPAIR_DIR / "repair_arm_cell_results_v1.jsonl"
TRADE_RESULTS = REPAIR_DIR / "repair_trade_results_v1.jsonl"
RAW_DIR = Path("runtime/r7a4d2_short_raw_geometry_and_simple_benchmark_execution")
RAW_GEOMETRY = RAW_DIR / "signal_geometry_v1.jsonl"
RAW_AGGREGATE = RAW_DIR / "aggregate_v1.json"
OUTPUT_PATH = Path("runtime/r7a4d2_short_strategy_identity_lineage_audit/identity_lineage_audit_v1.json")

EXPECTED_STRATEGIES = 11
EXPECTED_LANES = 25
EXPECTED_ARMS = 75
EXPECTED_CELLS = 450
REBUILD_POLICIES = {
    "RECONSTRUCT_SHORT_SEMANTICS_FROM_FAMILY_CANDLES",
    "REBUILD_FROM_FAMILY_CANDLE_HYPOTHESIS",
}


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


def sha256_value(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def safe_repo_path(value: str) -> Path:
    candidate = Path(value)
    if not value or candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"UNSAFE_REPO_PATH:{value}")
    return candidate


def finite(value: Any, default: float = 0.0) -> float:
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    return default


def rounded(value: Any) -> float:
    return round(finite(value), 12)


def event_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        str(row.get("segment_id") or ""),
        int(row.get("fold") or 0),
        int(row.get("signal_bar_index") or -1),
        int(row.get("entry_bar_index") or -1),
        str(row.get("parameter_id") or "canonical"),
    )


def event_fingerprint(rows: list[dict[str, Any]]) -> tuple[str | None, set[tuple[Any, ...]]]:
    events = {event_key(row) for row in rows if int(row.get("fold", 99)) < 3}
    if not events:
        return None, set()
    ordered = sorted(events)
    return sha256_value(ordered), events


def histogram_tuple(value: Any) -> tuple[tuple[str, int], ...]:
    if not isinstance(value, dict):
        return tuple()
    return tuple(sorted((str(key), int(count or 0)) for key, count in value.items()))


def normalized_cell(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        str(row.get("timeframe") or ""),
        str(row.get("arm_id") or ""),
        str(row.get("arm_axis") or ""),
        str(row.get("cost_profile_id") or ""),
        str(row.get("perturbation_id") or ""),
        int(row.get("trade_count") or 0),
        int(row.get("win_count") or 0),
        rounded(row.get("win_rate_pct")),
        rounded(row.get("profit_factor")),
        rounded(row.get("expectancy_r")),
        rounded(row.get("net_pnl_sum_pct")),
        rounded(row.get("max_drawdown_pct")),
        rounded(row.get("payoff_ratio")),
        rounded(row.get("median_risk_pct")),
        rounded(row.get("median_holding_bars")),
        histogram_tuple(row.get("exit_histogram")),
        histogram_tuple(row.get("regime_histogram")),
        histogram_tuple(row.get("symbol_histogram")),
    )


def duplicate_groups(mapping: dict[str, str | None]) -> list[dict[str, Any]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for key, fingerprint in mapping.items():
        if fingerprint:
            grouped[fingerprint].append(key)
    return [
        {"fingerprint": fingerprint, "members": sorted(members)}
        for fingerprint, members in sorted(grouped.items())
        if len(members) > 1
    ]


def self_test() -> int:
    rows_a = [{"segment_id": "s1", "fold": 0, "signal_bar_index": 10, "entry_bar_index": 11}]
    rows_b = [{"segment_id": "s1", "fold": 0, "signal_bar_index": 10, "entry_bar_index": 11}]
    fp_a, events_a = event_fingerprint(rows_a)
    fp_b, events_b = event_fingerprint(rows_b)
    assert fp_a == fp_b and events_a == events_b
    groups = duplicate_groups({"a": fp_a, "b": fp_b, "empty": None})
    assert len(groups) == 1 and groups[0]["members"] == ["a", "b"]
    assert normalized_cell({"timeframe": "1m", "trade_count": 1}) == normalized_cell({"timeframe": "1m", "trade_count": 1})
    print("STATE=PASS_SHORT_STRATEGY_IDENTITY_LINEAGE_AUDIT_SELF_TEST")
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
        root / EXECUTION_PLAN,
        root / REPAIR_PLAN,
        root / REPAIR_LOCK,
        root / CELL_RESULTS,
        root / TRADE_RESULTS,
        root / RAW_GEOMETRY,
        root / RAW_AGGREGATE,
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        print("STATE=HOLD_SHORT_STRATEGY_IDENTITY_LINEAGE_AUDIT_INPUT")
        print("BLOCKER_COUNT=1")
        print("BLOCKERS=" + json.dumps(["REQUIRED_EVIDENCE_MISSING:" + ",".join(missing)]))
        print("RC=2")
        return 2

    plan = load_json(root / EXECUTION_PLAN)
    repair = load_json(root / REPAIR_PLAN)
    lock = load_json(root / REPAIR_LOCK)
    aggregate = load_json(root / RAW_AGGREGATE)
    cells = load_jsonl(root / CELL_RESULTS)
    trades = load_jsonl(root / TRADE_RESULTS)
    geometry = load_jsonl(root / RAW_GEOMETRY)
    blockers: list[str] = []

    strategy_lanes = [row for row in plan.get("strategy_lanes", []) if isinstance(row, dict)]
    repair_rows = [row for row in repair.get("repair_rows", []) if isinstance(row, dict)]
    repair_by_lane = {str(row.get("lane_id") or ""): row for row in repair_rows}
    lane_by_id = {str(row.get("lane_id") or ""): row for row in strategy_lanes}
    strategy_ids = sorted({str(row.get("strategy_id") or "") for row in strategy_lanes if row.get("strategy_id")})

    if plan.get("state") != "PASS_SHORT_RAW_GEOMETRY_AND_SIMPLE_BENCHMARK_EXECUTION_PLAN":
        blockers.append("EXECUTION_PLAN_NOT_PASS")
    if repair.get("state") != "PASS_SHORT_ALL_LANE_ARCHITECTURE_REPAIR_PLAN":
        blockers.append("REPAIR_PLAN_NOT_PASS")
    if lock.get("state") != "PASS_SHORT_ALL_LANE_ARCHITECTURE_REPAIR_EXECUTION":
        blockers.append("REPAIR_EXECUTION_NOT_PASS")
    if len(strategy_ids) != EXPECTED_STRATEGIES:
        blockers.append(f"STRATEGY_COUNT_INVALID:{len(strategy_ids)}")
    if len(strategy_lanes) != EXPECTED_LANES or len(lane_by_id) != EXPECTED_LANES:
        blockers.append(f"STRATEGY_LANE_COUNT_INVALID:{len(strategy_lanes)}:{len(lane_by_id)}")
    if len(repair_rows) != EXPECTED_LANES:
        blockers.append(f"REPAIR_ROW_COUNT_INVALID:{len(repair_rows)}")
    if len(cells) != EXPECTED_CELLS or int(lock.get("repair_arm_cell_result_count", -1)) != EXPECTED_CELLS:
        blockers.append(f"CELL_COUNT_INVALID:{len(cells)}")
    if int(lock.get("candidate_arm_count", -1)) != EXPECTED_ARMS:
        blockers.append("ARM_COUNT_INVALID")
    if str(aggregate.get("signal_geometry_sha256") or "") != sha256_file(root / RAW_GEOMETRY):
        blockers.append("RAW_GEOMETRY_SHA_MISMATCH")
    if str(lock.get("repair_arm_cell_results_sha256") or "") != sha256_file(root / CELL_RESULTS):
        blockers.append("CELL_RESULTS_SHA_MISMATCH")
    if str(lock.get("repair_trade_results_sha256") or "") != sha256_file(root / TRADE_RESULTS):
        blockers.append("TRADE_RESULTS_SHA_MISMATCH")
    if set(repair_by_lane) != set(lane_by_id):
        blockers.append("REPAIR_AND_EXECUTION_LANE_SET_MISMATCH")

    implementation_paths: list[Path] = []
    binding_by_strategy: dict[str, dict[str, Any]] = {}
    for strategy_id in strategy_ids:
        lanes = [row for row in strategy_lanes if str(row.get("strategy_id")) == strategy_id]
        bindings = {
            (
                str(row.get("implementation_path") or ""),
                str(row.get("callable") or ""),
                str(row.get("source_sha256") or ""),
            )
            for row in lanes
        }
        if len(bindings) != 1:
            blockers.append(f"INTRA_STRATEGY_BINDING_DIVERGENCE:{strategy_id}:{len(bindings)}")
            continue
        implementation_path, callable_name, declared_sha = next(iter(bindings))
        try:
            full_path = root / safe_repo_path(implementation_path)
        except Exception as exc:
            blockers.append(f"IMPLEMENTATION_PATH_INVALID:{strategy_id}:{type(exc).__name__}:{exc}")
            continue
        if not full_path.is_file():
            blockers.append(f"IMPLEMENTATION_FILE_MISSING:{strategy_id}:{implementation_path}")
            continue
        actual_sha = sha256_file(full_path)
        implementation_paths.append(full_path)
        binding_by_strategy[strategy_id] = {
            "implementation_path": implementation_path,
            "callable": callable_name,
            "declared_source_sha256": declared_sha,
            "actual_source_sha256": actual_sha,
            "source_sha_match": not declared_sha or declared_sha == actual_sha,
            "binding_fingerprint": sha256_value([implementation_path, callable_name, actual_sha]),
        }
        if declared_sha and declared_sha != actual_sha:
            blockers.append(f"STRATEGY_SOURCE_SHA_MISMATCH:{strategy_id}")

    before_paths = required + implementation_paths
    before = {str(path): sha256_file(path) for path in before_paths}
    if blockers:
        unique = list(dict.fromkeys(blockers))
        print("STATE=HOLD_SHORT_STRATEGY_IDENTITY_LINEAGE_AUDIT_INPUT")
        print("BLOCKER_COUNT=" + str(len(unique)))
        print("BLOCKERS=" + json.dumps(unique, ensure_ascii=False))
        print("RC=2")
        return 2

    geometry_by_lane: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in geometry:
        lane_id = str(row.get("lane_id") or "")
        if lane_id in lane_by_id and int(row.get("fold", 99)) < 3:
            geometry_by_lane[lane_id].append(row)

    cells_by_lane: dict[str, list[dict[str, Any]]] = defaultdict(list)
    cells_by_strategy: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in cells:
        lane_id = str(row.get("lane_id") or "")
        strategy_id = str(row.get("strategy_id") or "")
        cells_by_lane[lane_id].append(row)
        cells_by_strategy[strategy_id].append(row)

    trades_by_lane: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in trades:
        trades_by_lane[str(row.get("lane_id") or "")].append(row)

    signal_fingerprints: dict[str, str | None] = {}
    signal_sets: dict[str, set[tuple[Any, ...]]] = {}
    lane_rows: list[dict[str, Any]] = []
    for lane_id in sorted(lane_by_id):
        lane = lane_by_id[lane_id]
        repair_row = repair_by_lane[lane_id]
        native_fp, native_events = event_fingerprint(geometry_by_lane.get(lane_id, []))
        signal_fingerprints[lane_id] = native_fp
        signal_sets[lane_id] = native_events
        execution_lane_ids = sorted({str(row.get("execution_lane_id") or "") for row in cells_by_lane.get(lane_id, [])})
        execution_lane_ids = [value for value in execution_lane_ids if value]
        entry_policy = str(repair_row.get("entry_policy") or "")
        sibling_id = str(repair_row.get("sibling_native_timeframe_candidate") or "")
        benchmark_reconstruction = entry_policy in REBUILD_POLICIES or not native_events
        sibling_execution = any(value != lane_id for value in execution_lane_ids)
        geometry_profile = repair_row.get("geometry_profile") if isinstance(repair_row.get("geometry_profile"), dict) else {}
        sibling_geometry = bool(sibling_id and int(geometry_profile.get("discovery_geometry_row_count") or 0) == 0)
        lineage_flags: list[str] = []
        if native_events:
            lineage_flags.append("NATIVE_SIGNAL_PRESENT")
        else:
            lineage_flags.append("NO_NATIVE_SIGNAL")
        if benchmark_reconstruction:
            lineage_flags.append("BENCHMARK_RECONSTRUCTION_USED")
        if sibling_execution:
            lineage_flags.append("SIBLING_EXECUTION_LANE_USED")
        if sibling_geometry:
            lineage_flags.append("SIBLING_GEOMETRY_PROFILE_USED")
        if not benchmark_reconstruction and not sibling_execution and not sibling_geometry and native_events:
            lineage_flags.append("NATIVE_LINEAGE_CLEAN")
        lane_rows.append({
            "lane_id": lane_id,
            "strategy_id": str(lane.get("strategy_id") or ""),
            "family": str(lane.get("family") or ""),
            "declared_timeframe": str(lane.get("timeframe") or ""),
            "implementation_path": str(lane.get("implementation_path") or ""),
            "callable": str(lane.get("callable") or ""),
            "native_signal_count": len(native_events),
            "native_signal_fingerprint": native_fp,
            "entry_policy": entry_policy,
            "sibling_native_timeframe_candidate": sibling_id or None,
            "execution_lane_ids": execution_lane_ids,
            "benchmark_reconstruction_used": benchmark_reconstruction,
            "sibling_execution_used": sibling_execution,
            "sibling_geometry_profile_used": sibling_geometry,
            "repair_trade_count": len(trades_by_lane.get(lane_id, [])),
            "lineage_flags": lineage_flags,
        })

    binding_groups = duplicate_groups({key: value.get("binding_fingerprint") for key, value in binding_by_strategy.items()})
    exact_signal_groups_all = duplicate_groups(signal_fingerprints)
    exact_signal_groups: list[dict[str, Any]] = []
    for group in exact_signal_groups_all:
        members = group["members"]
        strategies = {str(lane_by_id[member].get("strategy_id") or "") for member in members}
        if len(strategies) > 1:
            exact_signal_groups.append({**group, "strategy_ids": sorted(strategies)})

    near_pairs: list[dict[str, Any]] = []
    lane_ids = sorted(lane_by_id)
    for index, left in enumerate(lane_ids):
        left_lane = lane_by_id[left]
        left_events = signal_sets[left]
        if not left_events:
            continue
        for right in lane_ids[index + 1:]:
            right_lane = lane_by_id[right]
            right_events = signal_sets[right]
            if not right_events:
                continue
            if str(left_lane.get("strategy_id")) == str(right_lane.get("strategy_id")):
                continue
            if str(left_lane.get("timeframe")) != str(right_lane.get("timeframe")):
                continue
            union = left_events | right_events
            similarity = len(left_events & right_events) / len(union) if union else 0.0
            if similarity >= 0.95:
                near_pairs.append({
                    "left_lane_id": left,
                    "right_lane_id": right,
                    "timeframe": str(left_lane.get("timeframe") or ""),
                    "jaccard_similarity": round(similarity, 6),
                    "left_signal_count": len(left_events),
                    "right_signal_count": len(right_events),
                })

    outcome_fingerprint_by_strategy: dict[str, str | None] = {}
    for strategy_id in strategy_ids:
        normalized = sorted(normalized_cell(row) for row in cells_by_strategy.get(strategy_id, []))
        outcome_fingerprint_by_strategy[strategy_id] = sha256_value(normalized) if normalized else None
    outcome_alias_groups = duplicate_groups(outcome_fingerprint_by_strategy)

    binding_alias_members = {member for group in binding_groups for member in group["members"]}
    signal_alias_members = {
        str(lane_by_id[member].get("strategy_id") or "")
        for group in exact_signal_groups for member in group["members"]
    }
    signal_alias_members.update(
        str(lane_by_id[row[side]].get("strategy_id") or "")
        for row in near_pairs for side in ("left_lane_id", "right_lane_id")
    )
    outcome_alias_members = {member for group in outcome_alias_groups for member in group["members"]}

    strategy_rows: list[dict[str, Any]] = []
    for strategy_id in strategy_ids:
        rows = [row for row in lane_rows if row["strategy_id"] == strategy_id]
        issue_flags: list[str] = []
        if strategy_id in binding_alias_members:
            issue_flags.append("CANONICAL_BINDING_ALIAS")
        if strategy_id in signal_alias_members:
            issue_flags.append("CROSS_STRATEGY_SIGNAL_ALIAS")
        if strategy_id in outcome_alias_members:
            issue_flags.append("REPAIR_OUTCOME_ALIAS")
        if any(row["benchmark_reconstruction_used"] for row in rows):
            issue_flags.append("BENCHMARK_RECONSTRUCTION_DEPENDENCY")
        if any(row["sibling_execution_used"] for row in rows):
            issue_flags.append("SIBLING_EXECUTION_DEPENDENCY")
        if any(row["sibling_geometry_profile_used"] for row in rows):
            issue_flags.append("SIBLING_GEOMETRY_DEPENDENCY")
        if all(int(row["native_signal_count"]) == 0 for row in rows):
            issue_flags.append("NO_NATIVE_SIGNAL_ACROSS_LANES")
        strategy_rows.append({
            "strategy_id": strategy_id,
            "lane_count": len(rows),
            "native_signal_count": sum(int(row["native_signal_count"]) for row in rows),
            "benchmark_reconstruction_lane_count": sum(1 for row in rows if row["benchmark_reconstruction_used"]),
            "sibling_execution_lane_count": sum(1 for row in rows if row["sibling_execution_used"]),
            "sibling_geometry_lane_count": sum(1 for row in rows if row["sibling_geometry_profile_used"]),
            "canonical_binding": binding_by_strategy[strategy_id],
            "issue_flags": issue_flags,
            "identity_status": "IDENTITY_CLEAN" if not issue_flags else "IDENTITY_REBUILD_REQUIRED",
            "required_action": (
                "PRESERVE_NATIVE_CONTRACT_AND_BUILD_CANDLE_REGIME_TABLE"
                if not issue_flags
                else "REBUILD_NATIVE_CALLABLE_SIGNAL_TIMEFRAME_CONTRACT"
            ),
        })

    issue_histogram = dict(sorted(Counter(flag for row in strategy_rows for flag in row["issue_flags"]).items()))
    clean_count = sum(1 for row in strategy_rows if row["identity_status"] == "IDENTITY_CLEAN")
    identity_pass = clean_count == EXPECTED_STRATEGIES

    after = {str(path): sha256_file(path) for path in before_paths}
    mutation_paths = sorted(path for path in before if before[path] != after[path])
    if mutation_paths:
        blockers.append("INPUT_MUTATION_DETECTED:" + json.dumps(mutation_paths))

    state = "PASS_SHORT_STRATEGY_IDENTITY_LINEAGE_AUDIT" if not blockers else "HOLD_SHORT_STRATEGY_IDENTITY_LINEAGE_AUDIT"
    next_stage = (
        "R7.A4D2_SHORT_STRATEGY_CANDLE_REGIME_PERFORMANCE_TABLE"
        if not blockers and identity_pass
        else "R7.A4D2_SHORT_NATIVE_SIGNAL_CONTRACT_REBUILD_PLAN"
    )
    report = {
        "schema": "r7a4d2_short_strategy_identity_lineage_audit_v1",
        "official_stage": "R7.A4D2_SHORT_STRATEGY_IDENTITY_LINEAGE_AUDIT",
        "state": state,
        "target_commit": args.target_sha,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "audit_completed": not blockers,
        "identity_integrity_pass": identity_pass if not blockers else False,
        "strategy_count": len(strategy_ids),
        "strategy_lane_count": len(strategy_lanes),
        "identity_clean_strategy_count": clean_count,
        "identity_rebuild_strategy_count": len(strategy_rows) - clean_count,
        "native_signal_lane_count": sum(1 for row in lane_rows if int(row["native_signal_count"]) > 0),
        "zero_native_signal_lane_count": sum(1 for row in lane_rows if int(row["native_signal_count"]) == 0),
        "benchmark_reconstruction_lane_count": sum(1 for row in lane_rows if row["benchmark_reconstruction_used"]),
        "sibling_execution_lane_count": sum(1 for row in lane_rows if row["sibling_execution_used"]),
        "sibling_geometry_lane_count": sum(1 for row in lane_rows if row["sibling_geometry_profile_used"]),
        "canonical_binding_alias_group_count": len(binding_groups),
        "exact_signal_alias_group_count": len(exact_signal_groups),
        "near_signal_alias_pair_count": len(near_pairs),
        "repair_outcome_alias_group_count": len(outcome_alias_groups),
        "issue_histogram": issue_histogram,
        "canonical_binding_alias_groups": binding_groups,
        "exact_signal_alias_groups": exact_signal_groups,
        "near_signal_alias_pairs": near_pairs,
        "repair_outcome_alias_groups": outcome_alias_groups,
        "strategy_identity_rows": strategy_rows,
        "lane_lineage_rows": lane_rows,
        "input_mutation_paths": mutation_paths,
        "next_stage": next_stage,
    }
    atomic_json(root / OUTPUT_PATH, report)

    print("STATE=" + state)
    print("BLOCKER_COUNT=" + str(len(blockers)))
    print("AUDIT_COMPLETED=" + str(not blockers).lower())
    print("IDENTITY_INTEGRITY_PASS=" + str(identity_pass if not blockers else False).lower())
    print("STRATEGY_COUNT=" + str(len(strategy_ids)))
    print("STRATEGY_LANE_COUNT=" + str(len(strategy_lanes)))
    print("IDENTITY_CLEAN_STRATEGY_COUNT=" + str(clean_count))
    print("IDENTITY_REBUILD_STRATEGY_COUNT=" + str(len(strategy_rows) - clean_count))
    print("NATIVE_SIGNAL_LANE_COUNT=" + str(report["native_signal_lane_count"]))
    print("ZERO_NATIVE_SIGNAL_LANE_COUNT=" + str(report["zero_native_signal_lane_count"]))
    print("BENCHMARK_RECONSTRUCTION_LANE_COUNT=" + str(report["benchmark_reconstruction_lane_count"]))
    print("SIBLING_EXECUTION_LANE_COUNT=" + str(report["sibling_execution_lane_count"]))
    print("SIBLING_GEOMETRY_LANE_COUNT=" + str(report["sibling_geometry_lane_count"]))
    print("CANONICAL_BINDING_ALIAS_GROUP_COUNT=" + str(len(binding_groups)))
    print("EXACT_SIGNAL_ALIAS_GROUP_COUNT=" + str(len(exact_signal_groups)))
    print("NEAR_SIGNAL_ALIAS_PAIR_COUNT=" + str(len(near_pairs)))
    print("REPAIR_OUTCOME_ALIAS_GROUP_COUNT=" + str(len(outcome_alias_groups)))
    print("ISSUE_HISTOGRAM=" + json.dumps(issue_histogram, sort_keys=True))
    print("CANONICAL_BINDING_ALIAS_GROUPS=" + json.dumps(binding_groups, ensure_ascii=False, sort_keys=True))
    print("EXACT_SIGNAL_ALIAS_GROUPS=" + json.dumps(exact_signal_groups, ensure_ascii=False, sort_keys=True))
    print("NEAR_SIGNAL_ALIAS_PAIRS=" + json.dumps(near_pairs, ensure_ascii=False, sort_keys=True))
    print("REPAIR_OUTCOME_ALIAS_GROUPS=" + json.dumps(outcome_alias_groups, ensure_ascii=False, sort_keys=True))
    print("STRATEGY_IDENTITY_ROWS=" + json.dumps(strategy_rows, ensure_ascii=False, sort_keys=True))
    print("AUDIT_JSON=" + str(root / OUTPUT_PATH))
    print("NEXT_STAGE=" + next_stage)
    print("BLOCKERS=" + json.dumps(blockers, ensure_ascii=False))
    print("RC=" + ("0" if not blockers else "2"))
    return 0 if not blockers else 2


if __name__ == "__main__":
    raise SystemExit(main())
