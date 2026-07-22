#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

REBASELINE_PLAN = Path("runtime/r7a4d2_short_selective_canonical_source_snapshot_and_rebaseline_plan/rebaseline_plan_v1.json")
SNAPSHOT_MANIFEST = Path("runtime/r7a4d2_short_selective_canonical_source_snapshot_and_rebaseline_plan/snapshot_manifest_v1.json")
BASE_EXECUTION_PLAN = Path("runtime/r7a4d2_short_raw_geometry_and_simple_benchmark_execution_plan/execution_plan_v1.json")
ADAPTER = Path("runtime/r7a4d2_short_scalp_required_ohlcv_schema_adapter_bind/adapter_bind_v1.json")
DIAGNOSE = Path("runtime/r7a4d2_short_raw_geometry_mutation_and_lane_economic_diagnose/diagnose_v1.json")
RAW_DIR = Path("runtime/r7a4d2_short_raw_geometry_and_simple_benchmark_execution")
OUTPUT_DIR = Path("runtime/r7a4d2_short_selective_raw_geometry_rebaseline_execution")
REGISTRY = Path("backend/strategy25/canonical_strategy_registry_v1.json")
CONFIG = Path("backend/strategy25/canonical_strategy25_config_v1.json")

EXPECTED_AFFECTED_LANES = 3
EXPECTED_SEGMENTS = 24
EXPECTED_REPLACEMENT_SCANS = 72
EXPECTED_PRESERVED_SCANS = 792
EXPECTED_MERGED_SCANS = 864
EXPECTED_STRATEGY_LANES = 25
EXPECTED_BENCHMARK_LANES = 11
EXPECTED_AFFECTED_IDS = {
    "strategy:vwap_revert:1m",
    "strategy:vwap_revert:5m",
    "strategy:vwap_revert:15m",
}


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            value = json.loads(line)
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


def canonical_rows_sha(rows: Iterable[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for row in rows:
        digest.update(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def atomic_jsonl(path: Path, rows: list[dict[str, Any]]) -> tuple[int, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        for row in rows:
            line = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            handle.write(line)
            digest.update(line.encode("utf-8"))
        temporary = Path(handle.name)
    os.replace(temporary, path)
    return len(rows), digest.hexdigest()


def import_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"MODULE_SPEC_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def unique_scan_keys(rows: list[dict[str, Any]]) -> bool:
    keys = [(str(row.get("lane_id") or ""), str(row.get("segment_id") or "")) for row in rows]
    return len(keys) == len(set(keys))


def merge_scans(
    old_rows: list[dict[str, Any]], replacement_rows: list[dict[str, Any]], affected: set[str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    preserved = [row for row in old_rows if str(row.get("lane_id") or "") not in affected]
    merged = preserved + replacement_rows
    merged.sort(key=lambda row: (str(row.get("lane_id") or ""), str(row.get("segment_id") or "")))
    return preserved, merged


def geometry_sort_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        str(row.get("lane_id") or ""),
        str(row.get("segment_id") or ""),
        int(row.get("signal_bar_index") or -1),
        str(row.get("parameter_id") or ""),
        str(row.get("structural_stop_name") or ""),
        float(row.get("entry_timestamp") or 0.0),
    )


def self_test() -> int:
    affected = {"strategy:vwap_revert:1m"}
    old = [
        {"lane_id": "strategy:vwap_revert:1m", "segment_id": "a", "completed": True},
        {"lane_id": "strategy:other:1m", "segment_id": "a", "completed": True},
    ]
    replacement = [{"lane_id": "strategy:vwap_revert:1m", "segment_id": "a", "completed": True, "generation": 2}]
    preserved, merged = merge_scans(old, replacement, affected)
    assert len(preserved) == 1
    assert len(merged) == 2
    assert unique_scan_keys(merged)
    assert EXPECTED_AFFECTED_LANES * EXPECTED_SEGMENTS == EXPECTED_REPLACEMENT_SCANS
    assert EXPECTED_PRESERVED_SCANS + EXPECTED_REPLACEMENT_SCANS == EXPECTED_MERGED_SCANS
    print("STATE=PASS_SHORT_SELECTIVE_RAW_GEOMETRY_REBASELINE_EXECUTION_SELF_TEST")
    print("RC=0")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--target-sha", default="SELF_TEST")
    parser.add_argument("--raw-module")
    parser.add_argument("--runner")
    parser.add_argument("--diagnose-module")
    parser.add_argument("--a4d-contract")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not all((args.raw_module, args.runner, args.diagnose_module, args.a4d_contract)):
        raise SystemExit("--raw-module --runner --diagnose-module --a4d-contract required")

    root = Path(args.root).resolve()
    required = [
        REBASELINE_PLAN,
        SNAPSHOT_MANIFEST,
        BASE_EXECUTION_PLAN,
        ADAPTER,
        DIAGNOSE,
        REGISTRY,
        CONFIG,
        RAW_DIR / "scan_results_v1.jsonl",
        RAW_DIR / "signal_geometry_v1.jsonl",
        RAW_DIR / "aggregate_v1.json",
        RAW_DIR / "proof_v1.json",
    ]
    blockers: list[str] = []
    for rel in required:
        if not (root / rel).is_file():
            blockers.append(f"REQUIRED_EVIDENCE_MISSING:{rel}")
    if blockers:
        print("STATE=HOLD_SHORT_SELECTIVE_RAW_GEOMETRY_REBASELINE_EXECUTION_INPUT")
        print("BLOCKER_COUNT=" + str(len(blockers)))
        print("BLOCKERS=" + json.dumps(blockers, ensure_ascii=False))
        print("RC=2")
        return 2

    raw = import_module(Path(args.raw_module).resolve(), "r7a4d2_selective_raw_helper")
    runner = import_module(Path(args.runner).resolve(), "r7a4d2_selective_runner")
    mutation_helper = import_module(Path(args.diagnose_module).resolve(), "r7a4d2_selective_mutation_helper")

    plan = load_json(root / REBASELINE_PLAN)
    snapshot_manifest = load_json(root / SNAPSHOT_MANIFEST)
    base_plan = load_json(root / BASE_EXECUTION_PLAN)
    adapter = load_json(root / ADAPTER)
    diagnose = load_json(root / DIAGNOSE)
    old_aggregate = load_json(root / RAW_DIR / "aggregate_v1.json")
    old_proof = load_json(root / RAW_DIR / "proof_v1.json")
    registry = load_json(root / REGISTRY)
    a4d_contract = load_json(Path(args.a4d_contract).resolve())

    if plan.get("state") != "PASS_SHORT_SELECTIVE_CANONICAL_SOURCE_SNAPSHOT_AND_REBASELINE_PLAN":
        blockers.append("REBASELINE_PLAN_NOT_PASS")
    if int(plan.get("blocker_count", -1)) != 0:
        blockers.append("REBASELINE_PLAN_BLOCKED")
    if plan.get("full_864_reexecution_allowed") is not False:
        blockers.append("FULL_864_REEXECUTION_NOT_DISABLED")
    if snapshot_manifest.get("state") != "PASS_SHORT_SELECTIVE_CANONICAL_SOURCE_SNAPSHOT":
        blockers.append("SNAPSHOT_MANIFEST_NOT_PASS")
    if diagnose.get("result_reusable") is not True or diagnose.get("evidence_integrity_pass") is not True:
        blockers.append("PRIOR_RAW_EVIDENCE_NOT_REUSABLE")
    if base_plan.get("state") != "PASS_SHORT_RAW_GEOMETRY_AND_SIMPLE_BENCHMARK_EXECUTION_PLAN":
        blockers.append("BASE_EXECUTION_PLAN_NOT_PASS")

    affected = {str(value) for value in plan.get("affected_strategy_lane_ids", [])}
    if affected != EXPECTED_AFFECTED_IDS:
        blockers.append(f"AFFECTED_LANE_SET_INVALID:{sorted(affected)}")
    overrides = {
        str(row.get("lane_id")): row
        for row in plan.get("strategy_lane_overrides", [])
        if isinstance(row, dict) and row.get("lane_id")
    }
    if set(overrides) != affected:
        blockers.append("LANE_OVERRIDE_SET_INVALID")
    snapshots = [row for row in snapshot_manifest.get("snapshots", []) if isinstance(row, dict)]
    if len(snapshots) != 1 or str(snapshots[0].get("strategy_id")) != "vwap_revert":
        blockers.append("VWAP_SNAPSHOT_COUNT_INVALID")
    snapshot_row = snapshots[0] if snapshots else {}
    snapshot_rel = str(snapshot_row.get("snapshot_path") or "")
    snapshot_path = root / raw.safe_repo_path(snapshot_rel) if snapshot_rel else root / "__missing_snapshot__"
    snapshot_sha = str(snapshot_row.get("snapshot_sha256") or "")
    if not snapshot_path.is_file() or sha256_file(snapshot_path) != snapshot_sha:
        blockers.append("VWAP_SNAPSHOT_SHA_INVALID")
    if any(str(row.get("source_sha256") or "") != snapshot_sha for row in overrides.values()):
        blockers.append("LANE_OVERRIDE_SNAPSHOT_SHA_MISMATCH")

    scans_path = root / RAW_DIR / "scan_results_v1.jsonl"
    geometry_path = root / RAW_DIR / "signal_geometry_v1.jsonl"
    if sha256_file(scans_path) != str(old_aggregate.get("scan_results_sha256") or ""):
        blockers.append("PRIOR_SCAN_SHA_MISMATCH")
    if sha256_file(geometry_path) != str(old_aggregate.get("signal_geometry_sha256") or ""):
        blockers.append("PRIOR_GEOMETRY_SHA_MISMATCH")
    if str(old_proof.get("scan_results_sha256") or "") != str(old_aggregate.get("scan_results_sha256") or ""):
        blockers.append("PRIOR_PROOF_SCAN_SHA_MISMATCH")
    if str(old_proof.get("signal_geometry_sha256") or "") != str(old_aggregate.get("signal_geometry_sha256") or ""):
        blockers.append("PRIOR_PROOF_GEOMETRY_SHA_MISMATCH")
    if int(old_aggregate.get("scan_count", -1)) != EXPECTED_MERGED_SCANS:
        blockers.append("PRIOR_SCAN_COUNT_INVALID")
    if int(old_aggregate.get("completed_scan_count", -1)) != EXPECTED_MERGED_SCANS:
        blockers.append("PRIOR_COMPLETED_SCAN_COUNT_INVALID")
    if int(old_aggregate.get("failed_scan_count", -1)) != 0 or int(old_aggregate.get("failure_count", -1)) != 0:
        blockers.append("PRIOR_SCAN_FAILURE_PRESENT")

    data_contract = base_plan.get("data_contract") if isinstance(base_plan.get("data_contract"), dict) else {}
    manifest_rel = str(data_contract.get("selected_manifest_path") or "")
    manifest_path = root / raw.safe_repo_path(manifest_rel) if manifest_rel else root / "__missing_manifest__"
    if not manifest_path.is_file():
        blockers.append("SELECTED_MANIFEST_MISSING")
        manifest: dict[str, Any] = {}
    else:
        manifest = load_json(manifest_path)
    segments = [row for row in manifest.get("selected_segments", []) if isinstance(row, dict)]
    if len(segments) != EXPECTED_SEGMENTS or len({str(row.get("segment_id")) for row in segments}) != EXPECTED_SEGMENTS:
        blockers.append(f"SEGMENT_SET_INVALID:{len(segments)}")
    allowlist = {
        str(row.get("source_path") or "")
        for row in adapter.get("source_allowlist", [])
        if isinstance(row, dict)
    }
    required_sources = {str(row.get("source_path") or "") for row in segments}
    if not required_sources.issubset(allowlist):
        blockers.append("SELECTED_SOURCE_NOT_IN_ADAPTER_ALLOWLIST")

    old_scans = read_jsonl(scans_path)
    old_geometry = read_jsonl(geometry_path)
    old_affected_scans = [row for row in old_scans if str(row.get("lane_id") or "") in affected]
    if len(old_scans) != EXPECTED_MERGED_SCANS or len(old_affected_scans) != EXPECTED_REPLACEMENT_SCANS:
        blockers.append(f"PRIOR_SCAN_PARTITION_INVALID:{len(old_scans)}:{len(old_affected_scans)}")
    if not unique_scan_keys(old_scans):
        blockers.append("PRIOR_SCAN_PRIMARY_KEY_DUPLICATE")

    cost_profiles = [row for row in a4d_contract.get("cost_profiles", []) if isinstance(row, dict)]
    if len(cost_profiles) != 3:
        blockers.append("COST_PROFILE_COUNT_INVALID")
    base_cost = next((row for row in cost_profiles if str(row.get("id")) == "cost_profile_0"), None)
    if base_cost is None:
        blockers.append("BASE_COST_PROFILE_MISSING")

    if blockers:
        unique = list(dict.fromkeys(blockers))
        print("STATE=HOLD_SHORT_SELECTIVE_RAW_GEOMETRY_REBASELINE_EXECUTION_INPUT")
        print("BLOCKER_COUNT=" + str(len(unique)))
        print("BLOCKERS=" + json.dumps(unique, ensure_ascii=False))
        print("RC=2")
        return 2

    source_sha = {
        str(row.get("source_path") or ""): str(row.get("source_sha256") or "")
        for row in segments
    }
    source_cache: dict[str, Any] = {}
    for source_rel in sorted(required_sources):
        source_cache[source_rel] = raw.fixed_ohlcv_frame(root / raw.safe_repo_path(source_rel), source_sha[source_rel])

    protected_paths: list[Path] = [
        root / REBASELINE_PLAN,
        root / SNAPSHOT_MANIFEST,
        root / BASE_EXECUTION_PLAN,
        root / ADAPTER,
        root / DIAGNOSE,
        root / REGISTRY,
        root / CONFIG,
        manifest_path,
        snapshot_path,
    ]
    protected_paths.extend(root / raw.safe_repo_path(path) for path in sorted(required_sources))
    for value in a4d_contract.get("protected_paths", []):
        path = Path(str(value))
        resolved = path if path.is_absolute() else root / path
        if resolved.exists():
            protected_paths.append(resolved)
    protected_paths = list(dict.fromkeys(protected_paths))
    before = raw.snapshot(protected_paths)

    sys.path.insert(0, str(root))
    sys.dont_write_bytecode = True
    try:
        strategy_module = runner.load_module(root, raw.safe_repo_path(snapshot_rel), "vwap_revert_rebaseline_g2")
        owner, method_name = runner.resolve_callable(strategy_module, str(snapshot_row.get("callable") or ""))
    finally:
        try:
            sys.path.remove(str(root))
        except ValueError:
            pass

    costs_pct = raw.friction_profiles(cost_profiles)
    replacement_scans: list[dict[str, Any]] = []
    replacement_geometry: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    side_effect_attempts: list[str] = []
    completed = 0

    for lane_id in sorted(affected):
        lane = dict(overrides[lane_id])
        lane["lane_type"] = "strategy"
        lane["strategy_id"] = "vwap_revert"
        lane["source_binding_mode"] = "IMMUTABLE_RUNTIME_SNAPSHOT"
        for segment in sorted(segments, key=lambda row: str(row.get("segment_id") or "")):
            completed += 1
            scan: dict[str, Any] = {
                "lane_id": lane_id,
                "lane_type": "strategy",
                "family": lane.get("family"),
                "strategy_id": "vwap_revert",
                "benchmark_id": None,
                "timeframe": lane.get("timeframe"),
                "segment_id": segment.get("segment_id"),
                "regime": segment.get("regime"),
                "fold": segment.get("fold"),
                "source_path": segment.get("source_path"),
                "source_snapshot_path": snapshot_rel,
                "source_sha256": snapshot_sha,
                "rebaseline_generation": 2,
                "completed": False,
                "error": None,
            }
            try:
                source_rel = str(segment["source_path"])
                frame = raw.resample_for_segment(
                    source_cache[source_rel],
                    int(segment["start_row"]),
                    int(segment["end_row_exclusive"]),
                    str(lane["timeframe"]),
                )
                measured = raw.measurement_mask(frame, int(segment["start_row"]), int(segment["end_row_exclusive"]))
                if int(measured.sum()) < 2:
                    raise ValueError(f"MEASUREMENT_BAR_COUNT_INSUFFICIENT:{int(measured.sum())}")
                raw_signals, semantic_counts = raw.strategy_signals(
                    lane,
                    frame,
                    str(segment["regime"]),
                    owner,
                    method_name,
                    runner,
                    base_cost,
                    side_effect_attempts,
                )
                measured_signals = [
                    signal for signal in raw_signals
                    if int(signal["bar_index"]) < len(measured) and bool(measured.iloc[int(signal["bar_index"])])
                ]
                eligible_signals = [signal for signal in measured_signals if bool(signal.get("semantic_eligible", True))]
                generated: list[dict[str, Any]] = []
                for signal in eligible_signals:
                    rows = raw.geometry_rows_for_signal(lane, segment, frame, signal, measured, costs_pct)
                    for row in rows:
                        row["source_snapshot_path"] = snapshot_rel
                        row["source_sha256"] = snapshot_sha
                        row["rebaseline_generation"] = 2
                    generated.extend(rows)
                replacement_geometry.extend(generated)
                scan.update({
                    "completed": True,
                    "resampled_bar_count": len(frame),
                    "measurement_bar_count": int(measured.sum()),
                    "warmup_bar_count": int((~measured & (frame["__last_source_index"] < int(segment["start_row"]))).sum()),
                    "minimum_strategy_call_bars": raw.MINIMUM_STRATEGY_CALL_BARS,
                    "raw_signal_count": len(raw_signals),
                    "measurement_signal_count": len(measured_signals),
                    "semantic_eligible_signal_count": len(eligible_signals),
                    "semantic_mismatch_count": int(semantic_counts.get("semantic_mismatch", 0)),
                    "geometry_row_count": len(generated),
                    "semantic_counts": semantic_counts,
                    "insufficient_warmup": len(frame) < raw.MINIMUM_STRATEGY_CALL_BARS,
                })
            except Exception as exc:
                scan["error"] = f"{type(exc).__name__}:{exc}"
                failures.append({"lane_id": lane_id, "segment_id": segment.get("segment_id"), "error": scan["error"]})
            replacement_scans.append(scan)
            if completed % 12 == 0 or completed == EXPECTED_REPLACEMENT_SCANS:
                print(
                    f"A4D2_SELECTIVE_VWAP_RAW_PROGRESS={completed}/{EXPECTED_REPLACEMENT_SCANS} "
                    f"FAILED={len(failures)} GEOMETRY_ROWS={len(replacement_geometry)}",
                    flush=True,
                )

    after = raw.snapshot(protected_paths)
    mutation_paths = sorted(path for path in before if before[path] != after[path])
    mutation_rows = [
        {"path": path, "classification": mutation_helper.classify_mutation(path, root)}
        for path in mutation_paths
    ]
    critical_mutations = [
        row for row in mutation_rows
        if row["classification"] not in {"EXTERNAL_OPERATIONAL_VOLATILE_MUTATION"}
    ]

    preserved_scans, merged_scans = merge_scans(old_scans, replacement_scans, affected)
    preserved_geometry = [row for row in old_geometry if str(row.get("lane_id") or "") not in affected]
    old_affected_geometry = [row for row in old_geometry if str(row.get("lane_id") or "") in affected]
    replacement_geometry.sort(key=geometry_sort_key)
    merged_geometry = preserved_geometry + replacement_geometry
    merged_geometry.sort(key=geometry_sort_key)

    execution_blockers: list[str] = []
    if len(replacement_scans) != EXPECTED_REPLACEMENT_SCANS:
        execution_blockers.append(f"REPLACEMENT_SCAN_COUNT_INVALID:{len(replacement_scans)}")
    if failures:
        execution_blockers.append(f"REPLACEMENT_SCAN_FAILURES:{len(failures)}")
    if side_effect_attempts:
        execution_blockers.append(f"SIDE_EFFECT_ATTEMPTS:{len(side_effect_attempts)}")
    if critical_mutations:
        execution_blockers.append(f"CRITICAL_MUTATIONS:{len(critical_mutations)}")
    if len(preserved_scans) != EXPECTED_PRESERVED_SCANS:
        execution_blockers.append(f"PRESERVED_SCAN_COUNT_INVALID:{len(preserved_scans)}")
    if len(merged_scans) != EXPECTED_MERGED_SCANS:
        execution_blockers.append(f"MERGED_SCAN_COUNT_INVALID:{len(merged_scans)}")
    if not unique_scan_keys(replacement_scans):
        execution_blockers.append("REPLACEMENT_SCAN_PRIMARY_KEY_DUPLICATE")
    if not unique_scan_keys(merged_scans):
        execution_blockers.append("MERGED_SCAN_PRIMARY_KEY_DUPLICATE")
    if canonical_rows_sha(preserved_scans) != canonical_rows_sha(
        [row for row in merged_scans if str(row.get("lane_id") or "") not in affected]
    ):
        execution_blockers.append("PRESERVED_SCAN_CONTENT_CHANGED")
    if canonical_rows_sha(preserved_geometry) != canonical_rows_sha(
        [row for row in merged_geometry if str(row.get("lane_id") or "") not in affected]
    ):
        execution_blockers.append("PRESERVED_GEOMETRY_CONTENT_CHANGED")

    output = root / OUTPUT_DIR
    replacement_scan_count, replacement_scan_sha = atomic_jsonl(output / "replacement_scan_results_v2.jsonl", replacement_scans)
    replacement_geometry_count, replacement_geometry_sha = atomic_jsonl(output / "replacement_signal_geometry_v2.jsonl", replacement_geometry)
    merged_scan_count, merged_scan_sha = atomic_jsonl(output / "merged_scan_results_v2.jsonl", merged_scans)
    merged_geometry_count, merged_geometry_sha = atomic_jsonl(output / "merged_signal_geometry_v2.jsonl", merged_geometry)

    aggregate = raw.aggregate_results(merged_scans, merged_geometry)
    aggregate.update({
        "schema": "r7a4d2_short_selective_raw_geometry_rebaseline_aggregate_v2",
        "official_stage": "R7.A4D2_SHORT_SELECTIVE_RAW_GEOMETRY_REBASELINE_EXECUTION",
        "state": "PASS_SHORT_SELECTIVE_RAW_GEOMETRY_REBASELINE_EXECUTION" if not execution_blockers else "HOLD_SHORT_SELECTIVE_RAW_GEOMETRY_REBASELINE_EXECUTION",
        "target_commit": args.target_sha,
        "rebaseline_generation": 2,
        "rebaseline_strategy_ids": ["vwap_revert"],
        "affected_lane_ids": sorted(affected),
        "replacement_scan_count": replacement_scan_count,
        "preserved_scan_count": len(preserved_scans),
        "merged_scan_count": merged_scan_count,
        "completed_scan_count": sum(1 for row in merged_scans if row.get("completed") is True),
        "failed_scan_count": sum(1 for row in merged_scans if row.get("completed") is not True),
        "old_affected_geometry_row_count": len(old_affected_geometry),
        "replacement_geometry_row_count": replacement_geometry_count,
        "preserved_geometry_row_count": len(preserved_geometry),
        "merged_geometry_row_count": merged_geometry_count,
        "strategy_lane_count": EXPECTED_STRATEGY_LANES,
        "benchmark_lane_count": EXPECTED_BENCHMARK_LANES,
        "replacement_scan_results_sha256": replacement_scan_sha,
        "replacement_signal_geometry_sha256": replacement_geometry_sha,
        "merged_scan_results_sha256": merged_scan_sha,
        "merged_signal_geometry_sha256": merged_geometry_sha,
        "preserved_scan_rows_sha256": canonical_rows_sha(preserved_scans),
        "preserved_geometry_rows_sha256": canonical_rows_sha(preserved_geometry),
        "snapshot_path": snapshot_rel,
        "snapshot_sha256": snapshot_sha,
        "side_effect_attempt_count": len(side_effect_attempts),
        "mutation_rows": mutation_rows,
        "failure_count": len(failures),
        "failure_histogram": dict(sorted(Counter(str(row["error"]).split(":", 1)[0] for row in failures).items())),
        "blocker_count": len(execution_blockers),
        "blockers": execution_blockers,
        "next_stage": (
            "R7.A4D2_SHORT_SELECTIVE_VWAP_ECONOMIC_DIAGNOSE_AND_REPAIR_PLAN_REBUILD"
            if not execution_blockers
            else "R7.A4D2_SHORT_SELECTIVE_RAW_GEOMETRY_REBASELINE_DIAGNOSE"
        ),
    })
    atomic_json(output / "merged_aggregate_v2.json", aggregate)

    effective_plan = dict(base_plan)
    effective_strategy_lanes: list[dict[str, Any]] = []
    for lane in base_plan.get("strategy_lanes", []):
        lane_id = str(lane.get("lane_id") or "")
        effective_strategy_lanes.append(dict(overrides[lane_id]) if lane_id in overrides else lane)
    effective_plan.update({
        "schema": "r7a4d2_short_effective_execution_plan_rebaseline_generation_2",
        "rebaseline_generation": 2,
        "strategy_lanes": effective_strategy_lanes,
        "selective_source_snapshot_manifest": str(SNAPSHOT_MANIFEST),
        "selective_rebaseline_plan": str(REBASELINE_PLAN),
        "raw_geometry_evidence": {
            "scan_results_path": str(OUTPUT_DIR / "merged_scan_results_v2.jsonl"),
            "scan_results_sha256": merged_scan_sha,
            "signal_geometry_path": str(OUTPUT_DIR / "merged_signal_geometry_v2.jsonl"),
            "signal_geometry_sha256": merged_geometry_sha,
        },
    })
    atomic_json(output / "effective_execution_plan_v2.json", effective_plan)

    proof = {
        "schema": "r7a4d2_short_selective_raw_geometry_rebaseline_proof_v2",
        "state": aggregate["state"],
        "target_commit": args.target_sha,
        "snapshot_path": snapshot_rel,
        "snapshot_sha256": snapshot_sha,
        "affected_lane_ids": sorted(affected),
        "replacement_scan_count": replacement_scan_count,
        "preserved_scan_count": len(preserved_scans),
        "merged_scan_count": merged_scan_count,
        "replacement_scan_results_sha256": replacement_scan_sha,
        "replacement_signal_geometry_sha256": replacement_geometry_sha,
        "merged_scan_results_sha256": merged_scan_sha,
        "merged_signal_geometry_sha256": merged_geometry_sha,
        "mutation_rows": mutation_rows,
        "side_effect_attempts": side_effect_attempts,
        "failures": failures,
        "blockers": execution_blockers,
    }
    atomic_json(output / "proof_v2.json", proof)

    vwap_summary = {
        lane_id: aggregate.get("by_lane", {}).get(lane_id, {})
        for lane_id in sorted(affected)
    }
    print("STATE=" + aggregate["state"])
    print("BLOCKER_COUNT=" + str(len(execution_blockers)))
    print("AFFECTED_STRATEGY_LANE_COUNT=" + str(len(affected)))
    print("REPLACEMENT_SCAN_COUNT=" + str(replacement_scan_count))
    print("PRESERVED_SCAN_COUNT=" + str(len(preserved_scans)))
    print("MERGED_SCAN_COUNT=" + str(merged_scan_count))
    print("MERGED_COMPLETED_SCAN_COUNT=" + str(aggregate["completed_scan_count"]))
    print("MERGED_FAILED_SCAN_COUNT=" + str(aggregate["failed_scan_count"]))
    print("OLD_AFFECTED_GEOMETRY_ROW_COUNT=" + str(len(old_affected_geometry)))
    print("REPLACEMENT_GEOMETRY_ROW_COUNT=" + str(replacement_geometry_count))
    print("PRESERVED_GEOMETRY_ROW_COUNT=" + str(len(preserved_geometry)))
    print("MERGED_GEOMETRY_ROW_COUNT=" + str(merged_geometry_count))
    print("SIDE_EFFECT_ATTEMPT_COUNT=" + str(len(side_effect_attempts)))
    print("MUTATION_ROWS=" + json.dumps(mutation_rows, ensure_ascii=False, sort_keys=True))
    print("VWAP_LANE_SUMMARY=" + json.dumps(vwap_summary, ensure_ascii=False, sort_keys=True))
    print("MERGED_AGGREGATE_JSON=" + str(output / "merged_aggregate_v2.json"))
    print("EFFECTIVE_EXECUTION_PLAN_JSON=" + str(output / "effective_execution_plan_v2.json"))
    print("PROOF_JSON=" + str(output / "proof_v2.json"))
    print("NEXT_STAGE=" + str(aggregate["next_stage"]))
    print("BLOCKERS=" + json.dumps(execution_blockers, ensure_ascii=False))
    print("RC=" + ("0" if not execution_blockers else "2"))
    return 0 if not execution_blockers else 2


if __name__ == "__main__":
    raise SystemExit(main())
