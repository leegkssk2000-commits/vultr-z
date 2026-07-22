#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

AUDIT = Path("runtime/r7a4d2_short_four_way_lineage_selective_rebaseline_audit/audit_v1.json")
REGISTRY = Path("backend/strategy25/canonical_strategy_registry_v1.json")
EXECUTION_PLAN = Path("runtime/r7a4d2_short_raw_geometry_and_simple_benchmark_execution_plan/execution_plan_v1.json")
DIAGNOSE = Path("runtime/r7a4d2_short_raw_geometry_mutation_and_lane_economic_diagnose/diagnose_v1.json")
RAW_DIR = Path("runtime/r7a4d2_short_raw_geometry_and_simple_benchmark_execution")
REPAIR_DIR = Path("runtime/r7a4d2_short_all_lane_architecture_repair_execution")
OUTPUT_DIR = Path("runtime/r7a4d2_short_selective_canonical_source_snapshot_and_rebaseline_plan")
OUTPUT_PLAN = OUTPUT_DIR / "rebaseline_plan_v1.json"
SNAPSHOT_MANIFEST = OUTPUT_DIR / "snapshot_manifest_v1.json"

EXPECTED_STRATEGIES = 11
EXPECTED_STRATEGY_LANES = 25
EXPECTED_BENCHMARK_LANES = 11
EXPECTED_SEGMENTS = 24
EXPECTED_TOTAL_SCANS = 864
EXPECTED_REPAIR_CELLS = 450
ARMS_PER_LANE = 3
STRESS_CELLS_PER_ARM = 6


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"JSONL_OBJECT_REQUIRED:{path}:{line_number}")
            yield value


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_repo_path(value: str) -> str:
    if not value or "\x00" in value or "\\" in value:
        raise ValueError(f"UNSAFE_REPO_PATH:{value!r}")
    candidate = value[2:] if value.startswith("./") else value
    pure = PurePosixPath(candidate)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise ValueError(f"UNSAFE_REPO_PATH:{value!r}")
    return pure.as_posix()


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def atomic_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.is_symlink() or path.read_bytes() != value:
            raise ValueError(f"IMMUTABLE_SNAPSHOT_COLLISION:{path}")
        return
    with tempfile.NamedTemporaryFile("wb", dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        handle.write(value)
        temporary = Path(handle.name)
    os.replace(temporary, path)
    path.chmod(0o444)


def registry_map(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("strategy_id")): row
        for row in registry.get("entries", [])
        if isinstance(row, dict) and row.get("strategy_id")
    }


def count_by_lane(path: Path, affected: set[str]) -> tuple[int, int, int]:
    total = affected_count = preserved_count = 0
    for row in iter_jsonl(path):
        total += 1
        if str(row.get("lane_id") or "") in affected:
            affected_count += 1
        else:
            preserved_count += 1
    return total, affected_count, preserved_count


def lineage_manifest(root: Path, paths: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for rel in paths:
        path = root / rel
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"REQUIRED_EVIDENCE_MISSING:{path}")
        rows.append({"path": str(rel), "sha256": sha256_file(path), "size_bytes": path.stat().st_size})
    return rows


def self_test() -> int:
    affected = {"strategy:vwap_revert:1m", "strategy:vwap_revert:5m", "strategy:vwap_revert:15m"}
    assert len(affected) * EXPECTED_SEGMENTS == 72
    assert EXPECTED_TOTAL_SCANS - 72 == 792
    assert len(affected) * ARMS_PER_LANE * STRESS_CELLS_PER_ARM == 54
    assert EXPECTED_REPAIR_CELLS - 54 == 396
    assert safe_repo_path("backend/strategies/vwap_revert.py") == "backend/strategies/vwap_revert.py"
    print("STATE=PASS_SHORT_SELECTIVE_CANONICAL_SOURCE_SNAPSHOT_REBASELINE_PLAN_SELF_TEST")
    print("RC=0")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--target-sha", default="SELF_TEST")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()

    root = Path(args.root).resolve()
    required = [
        AUDIT, REGISTRY, EXECUTION_PLAN, DIAGNOSE,
        RAW_DIR / "scan_results_v1.jsonl",
        RAW_DIR / "signal_geometry_v1.jsonl",
        RAW_DIR / "aggregate_v1.json",
        RAW_DIR / "proof_v1.json",
        REPAIR_DIR / "repair_arm_cell_results_v1.jsonl",
        REPAIR_DIR / "repair_trade_results_v1.jsonl",
        REPAIR_DIR / "repair_lock_v1.json",
    ]
    blockers: list[str] = []
    for rel in required:
        if not (root / rel).is_file():
            blockers.append(f"REQUIRED_EVIDENCE_MISSING:{rel}")
    if blockers:
        print("STATE=HOLD_SHORT_SELECTIVE_CANONICAL_SOURCE_SNAPSHOT_REBASELINE_PLAN_INPUT")
        print("BLOCKER_COUNT=" + str(len(blockers)))
        print("BLOCKERS=" + json.dumps(blockers, ensure_ascii=False))
        print("RC=2")
        return 2

    audit = load_json(root / AUDIT)
    registry = load_json(root / REGISTRY)
    execution_plan = load_json(root / EXECUTION_PLAN)
    diagnose = load_json(root / DIAGNOSE)

    if audit.get("state") != "PASS_SHORT_FOUR_WAY_LINEAGE_SELECTIVE_REBASELINE_AUDIT":
        blockers.append("FOUR_WAY_AUDIT_NOT_PASS")
    if int(audit.get("blocker_count", -1)) != 0:
        blockers.append("FOUR_WAY_AUDIT_BLOCKED")
    if audit.get("selective_rebaseline_allowed") is not True:
        blockers.append("SELECTIVE_REBASELINE_NOT_ALLOWED")
    if audit.get("full_864_reexecution_required") is not False:
        blockers.append("FULL_864_REEXECUTION_NOT_DISABLED")
    if int(audit.get("strategy_count", -1)) != EXPECTED_STRATEGIES:
        blockers.append("AUDIT_STRATEGY_COUNT_INVALID")
    if int(audit.get("strategy_lane_count", -1)) != EXPECTED_STRATEGY_LANES:
        blockers.append("AUDIT_STRATEGY_LANE_COUNT_INVALID")
    if int(audit.get("authority_conflict_strategy_count", -1)) != 0:
        blockers.append("AUTHORITY_CONFLICT_PRESENT")
    if diagnose.get("result_reusable") is not True or diagnose.get("evidence_integrity_pass") is not True:
        blockers.append("PRIOR_RAW_RESULT_NOT_REUSABLE")

    rebaseline_ids = [str(value) for value in audit.get("rebaseline_strategy_ids", [])]
    affected_lane_ids = sorted(str(value) for value in audit.get("affected_lane_ids", []))
    preserved_lane_ids = sorted(str(value) for value in audit.get("preserved_lane_ids", []))
    affected = set(affected_lane_ids)
    if len(rebaseline_ids) != 1 or rebaseline_ids != ["vwap_revert"]:
        blockers.append(f"EXPECTED_SINGLE_VWAP_REBASELINE:{rebaseline_ids}")
    if len(affected_lane_ids) != 3:
        blockers.append(f"AFFECTED_LANE_COUNT_INVALID:{len(affected_lane_ids)}")
    if len(preserved_lane_ids) != 22:
        blockers.append(f"PRESERVED_LANE_COUNT_INVALID:{len(preserved_lane_ids)}")

    strategy_rows = {
        str(row.get("strategy_id")): row
        for row in audit.get("strategy_rows", [])
        if isinstance(row, dict) and row.get("strategy_id")
    }
    registry_by_id = registry_map(registry)
    strategy_lanes = [row for row in execution_plan.get("strategy_lanes", []) if isinstance(row, dict)]
    benchmark_lanes = [row for row in execution_plan.get("benchmark_lanes", []) if isinstance(row, dict)]
    if len(strategy_lanes) != EXPECTED_STRATEGY_LANES:
        blockers.append("EXECUTION_STRATEGY_LANE_COUNT_INVALID")
    if len(benchmark_lanes) != EXPECTED_BENCHMARK_LANES:
        blockers.append("EXECUTION_BENCHMARK_LANE_COUNT_INVALID")

    snapshot_rows: list[dict[str, Any]] = []
    lane_overrides: list[dict[str, Any]] = []
    for strategy_id in rebaseline_ids:
        audit_row = strategy_rows.get(strategy_id)
        entry = registry_by_id.get(strategy_id)
        if not isinstance(audit_row, dict) or not isinstance(entry, dict):
            blockers.append(f"STRATEGY_AUTHORITY_ROW_MISSING:{strategy_id}")
            continue
        if audit_row.get("classification") != "ACTUAL_REGISTRY_AHEAD_OF_TARGET_AND_PLAN":
            blockers.append(f"UNEXPECTED_REBASELINE_CLASS:{strategy_id}:{audit_row.get('classification')}")
            continue
        engine = entry.get("canonical_engine") if isinstance(entry.get("canonical_engine"), dict) else {}
        rel = safe_repo_path(str(engine.get("implementation_path") or ""))
        callable_name = str(engine.get("callable") or "")
        source = root / rel
        if not source.is_file() or source.is_symlink():
            blockers.append(f"CANONICAL_SOURCE_INVALID:{strategy_id}:{rel}")
            continue
        value = source.read_bytes()
        actual_sha = sha256_bytes(value)
        registry_sha = str(engine.get("source_sha256") or "")
        if actual_sha != registry_sha or actual_sha != str(audit_row.get("actual_sha256") or ""):
            blockers.append(f"CANONICAL_AUTHORITY_SHA_MISMATCH:{strategy_id}")
            continue
        snapshot_rel = OUTPUT_DIR / "snapshots" / strategy_id / actual_sha / Path(rel).name
        atomic_bytes(root / snapshot_rel, value)
        snapshot_rows.append({
            "strategy_id": strategy_id,
            "implementation_path": rel,
            "callable": callable_name,
            "source_sha256": actual_sha,
            "snapshot_path": str(snapshot_rel),
            "snapshot_sha256": sha256_file(root / snapshot_rel),
            "snapshot_size_bytes": len(value),
            "source_authority": "ACTUAL_EQUALS_REGISTRY",
            "old_target_commit_sha256": audit_row.get("target_commit_sha256"),
            "old_execution_plan_sha256_values": audit_row.get("execution_plan_sha256_values"),
        })
        for lane in strategy_lanes:
            if str(lane.get("strategy_id")) != strategy_id:
                continue
            lane_id = str(lane.get("lane_id") or "")
            if lane_id not in affected:
                blockers.append(f"AUDIT_PLAN_AFFECTED_LANE_MISMATCH:{lane_id}")
                continue
            override = dict(lane)
            override.update({
                "source_sha256": actual_sha,
                "source_snapshot_path": str(snapshot_rel),
                "source_binding_mode": "IMMUTABLE_RUNTIME_SNAPSHOT",
                "rebaseline_generation": 2,
            })
            lane_overrides.append(override)

    scan_total, affected_scan_count, preserved_scan_count = count_by_lane(root / RAW_DIR / "scan_results_v1.jsonl", affected)
    cell_total, affected_cell_count, preserved_cell_count = count_by_lane(root / REPAIR_DIR / "repair_arm_cell_results_v1.jsonl", affected)
    expected_selective_scans = len(affected) * EXPECTED_SEGMENTS
    expected_selective_arms = len(affected) * ARMS_PER_LANE
    expected_selective_cells = expected_selective_arms * STRESS_CELLS_PER_ARM
    if scan_total != EXPECTED_TOTAL_SCANS or affected_scan_count != expected_selective_scans or preserved_scan_count != EXPECTED_TOTAL_SCANS - expected_selective_scans:
        blockers.append(f"RAW_SCAN_PARTITION_INVALID:{scan_total}:{affected_scan_count}:{preserved_scan_count}")
    if cell_total != EXPECTED_REPAIR_CELLS or affected_cell_count != expected_selective_cells or preserved_cell_count != EXPECTED_REPAIR_CELLS - expected_selective_cells:
        blockers.append(f"REPAIR_CELL_PARTITION_INVALID:{cell_total}:{affected_cell_count}:{preserved_cell_count}")
    if len(lane_overrides) != len(affected):
        blockers.append(f"LANE_OVERRIDE_COUNT_INVALID:{len(lane_overrides)}")
    if len(snapshot_rows) != len(rebaseline_ids):
        blockers.append(f"SNAPSHOT_ROW_COUNT_INVALID:{len(snapshot_rows)}")

    if blockers:
        print("STATE=HOLD_SHORT_SELECTIVE_CANONICAL_SOURCE_SNAPSHOT_REBASELINE_PLAN_INPUT")
        print("BLOCKER_COUNT=" + str(len(blockers)))
        print("BLOCKERS=" + json.dumps(list(dict.fromkeys(blockers)), ensure_ascii=False))
        print("RC=2")
        return 2

    evidence_paths = [
        AUDIT, EXECUTION_PLAN, DIAGNOSE,
        RAW_DIR / "scan_results_v1.jsonl", RAW_DIR / "signal_geometry_v1.jsonl",
        RAW_DIR / "aggregate_v1.json", RAW_DIR / "proof_v1.json",
        REPAIR_DIR / "repair_arm_cell_results_v1.jsonl", REPAIR_DIR / "repair_trade_results_v1.jsonl",
        REPAIR_DIR / "repair_lock_v1.json",
    ]
    evidence_manifest = lineage_manifest(root, evidence_paths)
    benchmark_lane_ids = sorted(str(row.get("lane_id")) for row in benchmark_lanes)
    all_preserved_execution_lane_ids = sorted(preserved_lane_ids + benchmark_lane_ids)

    snapshot_manifest = {
        "schema": "r7a4d2_short_selective_canonical_source_snapshot_manifest_v1",
        "state": "PASS_SHORT_SELECTIVE_CANONICAL_SOURCE_SNAPSHOT",
        "target_sha": args.target_sha,
        "snapshot_count": len(snapshot_rows),
        "snapshots": snapshot_rows,
        "canonical_source_mutation_allowed": False,
        "snapshot_immutability_required": True,
        "blocker_count": 0,
        "blockers": [],
    }
    atomic_json(root / SNAPSHOT_MANIFEST, snapshot_manifest)

    plan = {
        "schema": "r7a4d2_short_selective_canonical_source_snapshot_and_rebaseline_plan_v1",
        "official_stage": "R7.A4D2_SHORT_SELECTIVE_CANONICAL_SOURCE_SNAPSHOT_AND_REBASELINE_PLAN",
        "state": "PASS_SHORT_SELECTIVE_CANONICAL_SOURCE_SNAPSHOT_AND_REBASELINE_PLAN",
        "target_sha": args.target_sha,
        "blocker_count": 0,
        "blockers": [],
        "rebaseline_generation": 2,
        "rebaseline_strategy_count": len(rebaseline_ids),
        "rebaseline_strategy_ids": rebaseline_ids,
        "affected_strategy_lane_count": len(affected_lane_ids),
        "affected_strategy_lane_ids": affected_lane_ids,
        "preserved_strategy_lane_count": len(preserved_lane_ids),
        "preserved_strategy_lane_ids": preserved_lane_ids,
        "preserved_benchmark_lane_count": len(benchmark_lane_ids),
        "preserved_benchmark_lane_ids": benchmark_lane_ids,
        "preserved_execution_lane_count": len(all_preserved_execution_lane_ids),
        "preserved_execution_lane_ids": all_preserved_execution_lane_ids,
        "source_snapshots": snapshot_rows,
        "strategy_lane_overrides": sorted(lane_overrides, key=lambda row: str(row.get("lane_id"))),
        "selective_raw_geometry_contract": {
            "historical_segment_count": EXPECTED_SEGMENTS,
            "replacement_scan_target": expected_selective_scans,
            "preserved_scan_count": preserved_scan_count,
            "merged_scan_target": EXPECTED_TOTAL_SCANS,
            "preserve_benchmark_results": True,
            "source_binding_mode": "IMMUTABLE_RUNTIME_SNAPSHOT",
            "future_pnl_selection_allowed": False,
        },
        "selective_repair_contract": {
            "candidate_arm_target": expected_selective_arms,
            "replacement_stress_cell_target": expected_selective_cells,
            "preserved_stress_cell_count": preserved_cell_count,
            "merged_stress_cell_target": EXPECTED_REPAIR_CELLS,
            "repair_plan_regeneration_required_for_affected_lanes": True,
            "preserve_unaffected_repair_results": True,
        },
        "merge_contract": {
            "replace_by_primary_key": {
                "raw_scan_results": ["lane_id", "segment_id"],
                "raw_signal_geometry": ["lane_id", "segment_id", "signal_bar_index", "parameter_id"],
                "repair_cell_results": ["lane_id", "arm_id", "cost_profile_id", "perturbation_id"],
                "repair_trade_results": ["lane_id", "arm_id", "cost_profile_id", "perturbation_id", "segment_id", "signal_bar_index"],
            },
            "affected_rows_must_be_removed_before_merge": True,
            "duplicate_primary_keys_allowed": False,
            "post_merge_total_scan_count": EXPECTED_TOTAL_SCANS,
            "post_merge_total_repair_cell_count": EXPECTED_REPAIR_CELLS,
        },
        "phase_plan": [
            "A_IMMUTABLE_CANONICAL_SOURCE_SNAPSHOT",
            "B_AFFECTED_LANE_EXECUTION_CONTRACT_REBUILD",
            "C_SELECTIVE_RAW_GEOMETRY_72_SCAN_EXECUTION",
            "D_PRESERVED_792_PLUS_REPLACEMENT_72_EVIDENCE_MERGE",
            "E_AFFECTED_LANE_ECONOMIC_DIAGNOSE_AND_REPAIR_PLAN_REBUILD",
            "F_SELECTIVE_REPAIR_54_CELL_EXECUTION",
            "G_PRESERVED_396_PLUS_REPLACEMENT_54_REPAIR_MERGE",
            "H_STRATEGY_IDENTITY_LINEAGE_AUDIT_RETRY",
        ],
        "prior_evidence_manifest": evidence_manifest,
        "snapshot_manifest_path": str(SNAPSHOT_MANIFEST),
        "full_864_reexecution_allowed": False,
        "unchanged_evidence_preservation_required": True,
        "affected_lane_only_rebaseline_required": True,
        "strategy_mutation_allowed": False,
        "registry_mutation_allowed": False,
        "config_mutation_allowed": False,
        "router_mutation_allowed": False,
        "service_mutation_allowed": False,
        "shadow_start_allowed": False,
        "paper_live_order_allowed": False,
        "next_stage": "R7.A4D2_SHORT_SELECTIVE_RAW_GEOMETRY_REBASELINE_EXECUTION",
    }
    atomic_json(root / OUTPUT_PLAN, plan)

    print("STATE=PASS_SHORT_SELECTIVE_CANONICAL_SOURCE_SNAPSHOT_AND_REBASELINE_PLAN")
    print("BLOCKER_COUNT=0")
    print("REBASELINE_STRATEGY_COUNT=" + str(len(rebaseline_ids)))
    print("REBASELINE_STRATEGY_IDS=" + json.dumps(rebaseline_ids))
    print("AFFECTED_STRATEGY_LANE_COUNT=" + str(len(affected_lane_ids)))
    print("AFFECTED_STRATEGY_LANE_IDS=" + json.dumps(affected_lane_ids))
    print("PRESERVED_STRATEGY_LANE_COUNT=" + str(len(preserved_lane_ids)))
    print("PRESERVED_BENCHMARK_LANE_COUNT=" + str(len(benchmark_lane_ids)))
    print("SELECTIVE_RAW_GEOMETRY_SCAN_TARGET=" + str(expected_selective_scans))
    print("PRESERVED_RAW_GEOMETRY_SCAN_COUNT=" + str(preserved_scan_count))
    print("MERGED_RAW_GEOMETRY_SCAN_TARGET=" + str(EXPECTED_TOTAL_SCANS))
    print("SELECTIVE_REPAIR_ARM_TARGET=" + str(expected_selective_arms))
    print("SELECTIVE_REPAIR_CELL_TARGET=" + str(expected_selective_cells))
    print("PRESERVED_REPAIR_CELL_COUNT=" + str(preserved_cell_count))
    print("MERGED_REPAIR_CELL_TARGET=" + str(EXPECTED_REPAIR_CELLS))
    print("FULL_864_REEXECUTION_ALLOWED=false")
    print("SNAPSHOT_MANIFEST_JSON=" + str(root / SNAPSHOT_MANIFEST))
    print("REBASELINE_PLAN_JSON=" + str(root / OUTPUT_PLAN))
    print("NEXT_STAGE=R7.A4D2_SHORT_SELECTIVE_RAW_GEOMETRY_REBASELINE_EXECUTION")
    print("RC=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
