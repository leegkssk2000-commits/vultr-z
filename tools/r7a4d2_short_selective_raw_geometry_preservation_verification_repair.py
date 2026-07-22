#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

RAW_DIR = Path("runtime/r7a4d2_short_raw_geometry_and_simple_benchmark_execution")
REBASELINE_DIR = Path("runtime/r7a4d2_short_selective_raw_geometry_rebaseline_execution")
PLAN_DIR = Path("runtime/r7a4d2_short_selective_canonical_source_snapshot_and_rebaseline_plan")
OUTPUT_DIR = Path("runtime/r7a4d2_short_selective_raw_geometry_preservation_verification_repair")

EXPECTED_AFFECTED_IDS = {
    "strategy:vwap_revert:1m",
    "strategy:vwap_revert:5m",
    "strategy:vwap_revert:15m",
}
EXPECTED_REPLACEMENT_SCANS = 72
EXPECTED_PRESERVED_SCANS = 792
EXPECTED_MERGED_SCANS = 864
EXPECTED_HOLD_BLOCKER = "PRESERVED_GEOMETRY_CONTENT_CHANGED"


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


def canonical_line(row: dict[str, Any]) -> str:
    return json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_multiset(rows: Iterable[dict[str, Any]]) -> Counter[str]:
    return Counter(canonical_line(row) for row in rows)


def canonical_multiset_sha(rows: Iterable[dict[str, Any]]) -> str:
    counts = canonical_multiset(rows)
    digest = hashlib.sha256()
    for line, count in sorted(counts.items()):
        digest.update(str(count).encode("ascii"))
        digest.update(b"\t")
        digest.update(line.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def unique_scan_keys(rows: list[dict[str, Any]]) -> bool:
    keys = [(str(row.get("lane_id") or ""), str(row.get("segment_id") or "")) for row in rows]
    return len(keys) == len(set(keys))


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def self_test() -> int:
    first = [{"a": 1}, {"a": 2}, {"a": 2}]
    second = [{"a": 2}, {"a": 1}, {"a": 2}]
    changed = [{"a": 2}, {"a": 1}]
    assert canonical_multiset(first) == canonical_multiset(second)
    assert canonical_multiset_sha(first) == canonical_multiset_sha(second)
    assert canonical_multiset(first) != canonical_multiset(changed)
    print("STATE=PASS_SHORT_SELECTIVE_RAW_GEOMETRY_PRESERVATION_VERIFICATION_REPAIR_SELF_TEST")
    print("ORDER_INDEPENDENT_MULTISET_CHECK=true")
    print("DUPLICATE_MULTIPLICITY_PRESERVED=true")
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
    required = {
        "old_scans": root / RAW_DIR / "scan_results_v1.jsonl",
        "old_geometry": root / RAW_DIR / "signal_geometry_v1.jsonl",
        "old_aggregate": root / RAW_DIR / "aggregate_v1.json",
        "old_proof": root / RAW_DIR / "proof_v1.json",
        "replacement_scans": root / REBASELINE_DIR / "replacement_scan_results_v2.jsonl",
        "replacement_geometry": root / REBASELINE_DIR / "replacement_signal_geometry_v2.jsonl",
        "merged_scans": root / REBASELINE_DIR / "merged_scan_results_v2.jsonl",
        "merged_geometry": root / REBASELINE_DIR / "merged_signal_geometry_v2.jsonl",
        "hold_aggregate": root / REBASELINE_DIR / "merged_aggregate_v2.json",
        "hold_proof": root / REBASELINE_DIR / "proof_v2.json",
        "effective_plan": root / REBASELINE_DIR / "effective_execution_plan_v2.json",
        "rebaseline_plan": root / PLAN_DIR / "rebaseline_plan_v1.json",
        "snapshot_manifest": root / PLAN_DIR / "snapshot_manifest_v1.json",
    }
    blockers: list[str] = []
    for label, path in required.items():
        if not path.is_file():
            blockers.append(f"REQUIRED_EVIDENCE_MISSING:{label}:{path}")
    if blockers:
        print("STATE=HOLD_SHORT_SELECTIVE_RAW_GEOMETRY_PRESERVATION_VERIFICATION_REPAIR_INPUT")
        print("BLOCKER_COUNT=" + str(len(blockers)))
        print("BLOCKERS=" + json.dumps(blockers, ensure_ascii=False))
        print("RC=2")
        return 2

    old_aggregate = load_json(required["old_aggregate"])
    old_proof = load_json(required["old_proof"])
    hold_aggregate = load_json(required["hold_aggregate"])
    hold_proof = load_json(required["hold_proof"])
    effective_plan = load_json(required["effective_plan"])
    rebaseline_plan = load_json(required["rebaseline_plan"])
    snapshot_manifest = load_json(required["snapshot_manifest"])

    old_scans = read_jsonl(required["old_scans"])
    old_geometry = read_jsonl(required["old_geometry"])
    replacement_scans = read_jsonl(required["replacement_scans"])
    replacement_geometry = read_jsonl(required["replacement_geometry"])
    merged_scans = read_jsonl(required["merged_scans"])
    merged_geometry = read_jsonl(required["merged_geometry"])

    affected = {str(value) for value in rebaseline_plan.get("affected_strategy_lane_ids", [])}
    if affected != EXPECTED_AFFECTED_IDS:
        blockers.append(f"AFFECTED_LANE_SET_INVALID:{sorted(affected)}")

    if hold_aggregate.get("state") != "HOLD_SHORT_SELECTIVE_RAW_GEOMETRY_REBASELINE_EXECUTION":
        blockers.append("PRIOR_HOLD_STATE_INVALID")
    prior_blockers = [str(value) for value in hold_aggregate.get("blockers", [])]
    if prior_blockers != [EXPECTED_HOLD_BLOCKER]:
        blockers.append(f"PRIOR_BLOCKER_SET_INVALID:{prior_blockers}")
    if [str(value) for value in hold_proof.get("blockers", [])] != [EXPECTED_HOLD_BLOCKER]:
        blockers.append("PRIOR_PROOF_BLOCKER_SET_INVALID")

    file_sha_checks = {
        "OLD_SCAN_SHA": (required["old_scans"], old_aggregate.get("scan_results_sha256")),
        "OLD_GEOMETRY_SHA": (required["old_geometry"], old_aggregate.get("signal_geometry_sha256")),
        "REPLACEMENT_SCAN_SHA": (
            required["replacement_scans"], hold_aggregate.get("replacement_scan_results_sha256")
        ),
        "REPLACEMENT_GEOMETRY_SHA": (
            required["replacement_geometry"], hold_aggregate.get("replacement_signal_geometry_sha256")
        ),
        "MERGED_SCAN_SHA": (required["merged_scans"], hold_aggregate.get("merged_scan_results_sha256")),
        "MERGED_GEOMETRY_SHA": (
            required["merged_geometry"], hold_aggregate.get("merged_signal_geometry_sha256")
        ),
    }
    for label, (path, expected) in file_sha_checks.items():
        if sha256_file(path) != str(expected or ""):
            blockers.append(f"{label}_MISMATCH")

    if str(old_proof.get("scan_results_sha256") or "") != str(old_aggregate.get("scan_results_sha256") or ""):
        blockers.append("OLD_PROOF_SCAN_SHA_MISMATCH")
    if str(old_proof.get("signal_geometry_sha256") or "") != str(old_aggregate.get("signal_geometry_sha256") or ""):
        blockers.append("OLD_PROOF_GEOMETRY_SHA_MISMATCH")

    if len(replacement_scans) != EXPECTED_REPLACEMENT_SCANS:
        blockers.append(f"REPLACEMENT_SCAN_COUNT_INVALID:{len(replacement_scans)}")
    if len(merged_scans) != EXPECTED_MERGED_SCANS:
        blockers.append(f"MERGED_SCAN_COUNT_INVALID:{len(merged_scans)}")
    if not unique_scan_keys(replacement_scans):
        blockers.append("REPLACEMENT_SCAN_PRIMARY_KEY_DUPLICATE")
    if not unique_scan_keys(merged_scans):
        blockers.append("MERGED_SCAN_PRIMARY_KEY_DUPLICATE")
    if any(str(row.get("lane_id") or "") not in affected for row in replacement_scans):
        blockers.append("REPLACEMENT_SCAN_CONTAINS_UNAFFECTED_LANE")
    if any(row.get("completed") is not True or row.get("error") not in (None, "") for row in replacement_scans):
        blockers.append("REPLACEMENT_SCAN_FAILURE_PRESENT")

    old_preserved_scans = [row for row in old_scans if str(row.get("lane_id") or "") not in affected]
    merged_preserved_scans = [row for row in merged_scans if str(row.get("lane_id") or "") not in affected]
    merged_affected_scans = [row for row in merged_scans if str(row.get("lane_id") or "") in affected]
    if len(old_preserved_scans) != EXPECTED_PRESERVED_SCANS:
        blockers.append(f"OLD_PRESERVED_SCAN_COUNT_INVALID:{len(old_preserved_scans)}")
    if canonical_multiset(old_preserved_scans) != canonical_multiset(merged_preserved_scans):
        blockers.append("PRESERVED_SCAN_MULTISET_CHANGED")
    if canonical_multiset(replacement_scans) != canonical_multiset(merged_affected_scans):
        blockers.append("REPLACEMENT_SCAN_MULTISET_NOT_MERGED")

    old_preserved_geometry = [row for row in old_geometry if str(row.get("lane_id") or "") not in affected]
    merged_preserved_geometry = [row for row in merged_geometry if str(row.get("lane_id") or "") not in affected]
    merged_affected_geometry = [row for row in merged_geometry if str(row.get("lane_id") or "") in affected]
    preserved_geometry_equal = canonical_multiset(old_preserved_geometry) == canonical_multiset(merged_preserved_geometry)
    replacement_geometry_equal = canonical_multiset(replacement_geometry) == canonical_multiset(merged_affected_geometry)
    if not preserved_geometry_equal:
        blockers.append("PRESERVED_GEOMETRY_MULTISET_CHANGED")
    if not replacement_geometry_equal:
        blockers.append("REPLACEMENT_GEOMETRY_MULTISET_NOT_MERGED")

    snapshots = [row for row in snapshot_manifest.get("snapshots", []) if isinstance(row, dict)]
    snapshot_sha = str(snapshots[0].get("snapshot_sha256") or "") if len(snapshots) == 1 else ""
    snapshot_path = str(snapshots[0].get("snapshot_path") or "") if len(snapshots) == 1 else ""
    if not snapshot_sha or not snapshot_path:
        blockers.append("SNAPSHOT_MANIFEST_INVALID")
    for row in replacement_geometry:
        if (
            str(row.get("source_sha256") or "") != snapshot_sha
            or str(row.get("source_snapshot_path") or "") != snapshot_path
            or int(row.get("rebaseline_generation") or -1) != 2
        ):
            blockers.append("REPLACEMENT_GEOMETRY_LINEAGE_INVALID")
            break

    if int(hold_aggregate.get("replacement_scan_count", -1)) != EXPECTED_REPLACEMENT_SCANS:
        blockers.append("AGGREGATE_REPLACEMENT_SCAN_COUNT_INVALID")
    if int(hold_aggregate.get("preserved_scan_count", -1)) != EXPECTED_PRESERVED_SCANS:
        blockers.append("AGGREGATE_PRESERVED_SCAN_COUNT_INVALID")
    if int(hold_aggregate.get("merged_scan_count", -1)) != EXPECTED_MERGED_SCANS:
        blockers.append("AGGREGATE_MERGED_SCAN_COUNT_INVALID")
    if int(hold_aggregate.get("completed_scan_count", -1)) != EXPECTED_MERGED_SCANS:
        blockers.append("AGGREGATE_COMPLETED_SCAN_COUNT_INVALID")
    if int(hold_aggregate.get("failed_scan_count", -1)) != 0:
        blockers.append("AGGREGATE_FAILED_SCAN_COUNT_NONZERO")
    if int(hold_aggregate.get("failure_count", -1)) != 0:
        blockers.append("AGGREGATE_FAILURE_COUNT_NONZERO")
    if int(hold_aggregate.get("side_effect_attempt_count", -1)) != 0:
        blockers.append("SIDE_EFFECT_ATTEMPT_PRESENT")

    mutation_rows = hold_aggregate.get("mutation_rows", [])
    if not isinstance(mutation_rows, list):
        blockers.append("MUTATION_ROWS_INVALID")
    else:
        forbidden = [
            row for row in mutation_rows
            if not isinstance(row, dict)
            or str(row.get("classification") or "") not in {"EXTERNAL_OPERATIONAL_VOLATILE_MUTATION"}
        ]
        if forbidden:
            blockers.append(f"FORBIDDEN_MUTATION_PRESENT:{len(forbidden)}")

    raw_evidence = effective_plan.get("raw_geometry_evidence") if isinstance(effective_plan.get("raw_geometry_evidence"), dict) else {}
    if str(raw_evidence.get("scan_results_sha256") or "") != sha256_file(required["merged_scans"]):
        blockers.append("EFFECTIVE_PLAN_MERGED_SCAN_SHA_MISMATCH")
    if str(raw_evidence.get("signal_geometry_sha256") or "") != sha256_file(required["merged_geometry"]):
        blockers.append("EFFECTIVE_PLAN_MERGED_GEOMETRY_SHA_MISMATCH")

    unique = list(dict.fromkeys(blockers))
    state = (
        "PASS_SHORT_SELECTIVE_RAW_GEOMETRY_PRESERVATION_VERIFICATION_REPAIR"
        if not unique
        else "HOLD_SHORT_SELECTIVE_RAW_GEOMETRY_PRESERVATION_VERIFICATION_REPAIR"
    )
    output = root / OUTPUT_DIR

    verified_aggregate = dict(hold_aggregate)
    verified_aggregate.update({
        "schema": "r7a4d2_short_selective_raw_geometry_rebaseline_verified_aggregate_v3",
        "official_stage": "R7.A4D2_SHORT_SELECTIVE_RAW_GEOMETRY_PRESERVATION_VERIFICATION_REPAIR",
        "state": state,
        "target_commit": args.target_sha,
        "verification_mode": "ORDER_INDEPENDENT_CANONICAL_JSON_MULTISET",
        "preserved_scan_multiset_sha256": canonical_multiset_sha(old_preserved_scans),
        "merged_preserved_scan_multiset_sha256": canonical_multiset_sha(merged_preserved_scans),
        "preserved_geometry_multiset_sha256": canonical_multiset_sha(old_preserved_geometry),
        "merged_preserved_geometry_multiset_sha256": canonical_multiset_sha(merged_preserved_geometry),
        "replacement_geometry_multiset_sha256": canonical_multiset_sha(replacement_geometry),
        "merged_affected_geometry_multiset_sha256": canonical_multiset_sha(merged_affected_geometry),
        "preserved_geometry_content_equal": preserved_geometry_equal,
        "replacement_geometry_merge_equal": replacement_geometry_equal,
        "prior_false_positive_blocker": EXPECTED_HOLD_BLOCKER,
        "prior_evidence_reexecuted": False,
        "blocker_count": len(unique),
        "blockers": unique,
        "next_stage": (
            "R7.A4D2_SHORT_SELECTIVE_VWAP_ECONOMIC_DIAGNOSE_AND_REPAIR_PLAN_REBUILD"
            if not unique
            else "R7.A4D2_SHORT_SELECTIVE_RAW_GEOMETRY_PRESERVATION_VERIFICATION_DIAGNOSE"
        ),
    })
    atomic_json(output / "verified_aggregate_v3.json", verified_aggregate)

    verified_effective_plan = dict(effective_plan)
    verified_effective_plan.update({
        "schema": "r7a4d2_short_effective_execution_plan_rebaseline_generation_2_verified_v3",
        "preservation_verification_evidence": str(OUTPUT_DIR / "verified_aggregate_v3.json"),
        "preservation_verification_state": state,
        "preservation_verification_mode": "ORDER_INDEPENDENT_CANONICAL_JSON_MULTISET",
    })
    atomic_json(output / "verified_effective_execution_plan_v3.json", verified_effective_plan)

    proof = {
        "schema": "r7a4d2_short_selective_raw_geometry_preservation_verification_proof_v3",
        "official_stage": "R7.A4D2_SHORT_SELECTIVE_RAW_GEOMETRY_PRESERVATION_VERIFICATION_REPAIR",
        "state": state,
        "target_commit": args.target_sha,
        "affected_lane_ids": sorted(affected),
        "old_preserved_scan_count": len(old_preserved_scans),
        "merged_preserved_scan_count": len(merged_preserved_scans),
        "old_preserved_geometry_count": len(old_preserved_geometry),
        "merged_preserved_geometry_count": len(merged_preserved_geometry),
        "replacement_geometry_count": len(replacement_geometry),
        "merged_affected_geometry_count": len(merged_affected_geometry),
        "preserved_scan_multiset_equal": canonical_multiset(old_preserved_scans) == canonical_multiset(merged_preserved_scans),
        "preserved_geometry_multiset_equal": preserved_geometry_equal,
        "replacement_scan_multiset_equal": canonical_multiset(replacement_scans) == canonical_multiset(merged_affected_scans),
        "replacement_geometry_multiset_equal": replacement_geometry_equal,
        "prior_evidence_reexecuted": False,
        "blockers": unique,
    }
    atomic_json(output / "proof_v3.json", proof)

    print("STATE=" + state)
    print("BLOCKER_COUNT=" + str(len(unique)))
    print("VERIFICATION_MODE=ORDER_INDEPENDENT_CANONICAL_JSON_MULTISET")
    print("PRIOR_EVIDENCE_REEXECUTED=false")
    print("OLD_PRESERVED_SCAN_COUNT=" + str(len(old_preserved_scans)))
    print("MERGED_PRESERVED_SCAN_COUNT=" + str(len(merged_preserved_scans)))
    print("PRESERVED_SCAN_MULTISET_EQUAL=" + str(canonical_multiset(old_preserved_scans) == canonical_multiset(merged_preserved_scans)).lower())
    print("OLD_PRESERVED_GEOMETRY_COUNT=" + str(len(old_preserved_geometry)))
    print("MERGED_PRESERVED_GEOMETRY_COUNT=" + str(len(merged_preserved_geometry)))
    print("PRESERVED_GEOMETRY_MULTISET_EQUAL=" + str(preserved_geometry_equal).lower())
    print("REPLACEMENT_GEOMETRY_COUNT=" + str(len(replacement_geometry)))
    print("MERGED_AFFECTED_GEOMETRY_COUNT=" + str(len(merged_affected_geometry)))
    print("REPLACEMENT_GEOMETRY_MULTISET_EQUAL=" + str(replacement_geometry_equal).lower())
    print("VERIFIED_AGGREGATE_JSON=" + str(output / "verified_aggregate_v3.json"))
    print("VERIFIED_EFFECTIVE_EXECUTION_PLAN_JSON=" + str(output / "verified_effective_execution_plan_v3.json"))
    print("PROOF_JSON=" + str(output / "proof_v3.json"))
    print("NEXT_STAGE=" + str(verified_aggregate["next_stage"]))
    print("BLOCKERS=" + json.dumps(unique, ensure_ascii=False))
    print("RC=" + ("0" if not unique else "2"))
    return 0 if not unique else 2


if __name__ == "__main__":
    raise SystemExit(main())
