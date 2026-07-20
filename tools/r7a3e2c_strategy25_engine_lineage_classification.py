#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from r7a3e2c_engine_lineage_lib import classify_strategy, function_rows


def load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


def sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_tree(path: Path) -> dict[str, str]:
    blobs: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            meta, repo_path = line.split("\t", 1)
            mode, kind, blob = meta.split()
        except ValueError:
            continue
        if kind == "blob":
            blobs[repo_path] = blob
    return blobs


def scan_snapshot(snapshot: Path, blobs: dict[str, str]) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    all_rows: list[dict[str, Any]] = []
    by_path: dict[str, list[dict[str, Any]]] = {}
    for source_path in snapshot.rglob("*.py"):
        if not source_path.is_file() or source_path.stat().st_size > 2_000_000:
            continue
        repo_path = source_path.relative_to(snapshot).as_posix()
        source = source_path.read_text(encoding="utf-8", errors="replace")
        rows = function_rows(source, repo_path)
        file_hash = sha256(source_path)
        for row in rows:
            row["source_blob_sha"] = blobs.get(repo_path)
            row["source_sha256"] = file_hash
        all_rows.extend(rows)
        by_path[repo_path] = rows
    return all_rows, by_path


def reference_rows(entry: dict[str, Any], by_path: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    target_hash = str(entry.get("engine_body_sha256") or "")
    candidate_paths = [str(value) for value in entry.get("candidate_paths", []) if value]
    candidate_names = {str(value).split(".")[-1] for value in entry.get("candidate_callables", []) if value}
    rows = [
        row for path in candidate_paths for row in by_path.get(path, [])
        if target_hash and row.get("full_hash") == target_hash
    ]
    if rows:
        return rows
    return [
        row for path in candidate_paths for row in by_path.get(path, [])
        if row.get("callable_leaf") in candidate_names
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--tree", required=True)
    parser.add_argument("--target-sha", required=True)
    parser.add_argument("--contract", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    snapshot = Path(args.snapshot).resolve()
    contract = load(Path(args.contract))
    prior_status = load(root / contract["prior_status_path"])
    prior_matrix = load(root / contract["prior_matrix_path"])
    prior_plan = load(root / contract["prior_plan_path"])
    blockers: list[str] = []

    if not (prior_status.get("state") == "PASS" and prior_status.get("blocker_count") == 0):
        blockers.append("PRIOR_A3E2_INVALID")
    expected = int(contract.get("expected_strategy_count", 25))
    if prior_status.get("strategy_count") != expected:
        blockers.append("PRIOR_STRATEGY_COUNT_MISMATCH")
    if prior_status.get("engine_bound_count") != int(contract.get("expected_engine_bound_count", 2)):
        blockers.append("PRIOR_ENGINE_BOUND_COUNT_MISMATCH")
    if prior_status.get("config_bound_count") != int(contract.get("expected_config_bound_count", 25)):
        blockers.append("PRIOR_CONFIG_BOUND_COUNT_MISMATCH")
    if prior_status.get("unresolved_count") != int(contract.get("expected_unresolved_count", 23)):
        blockers.append("PRIOR_UNRESOLVED_COUNT_MISMATCH")
    if not snapshot.is_dir():
        blockers.append("TARGET_SNAPSHOT_INVALID")

    matrix_entries = [row for row in prior_matrix.get("entries", []) if isinstance(row, dict)]
    plan_entries = [row for row in prior_plan.get("entries", []) if isinstance(row, dict)]
    if len(matrix_entries) != expected or len(plan_entries) != expected:
        blockers.append("PRIOR_ENTRY_COUNT_NOT_25")
    unresolved_ids = {
        str(row.get("strategy_id")) for row in matrix_entries
        if not row.get("binding_complete")
    }
    if len(unresolved_ids) != int(contract.get("expected_unresolved_count", 23)):
        blockers.append("UNRESOLVED_ID_COUNT_NOT_23")

    blobs = read_tree(Path(args.tree)) if Path(args.tree).is_file() else {}
    if not blobs:
        blockers.append("TARGET_TREE_INVALID")
    before = {path: sha256(Path(path)) for path in contract.get("protected_paths", [])}

    all_rows, by_path = scan_snapshot(snapshot, blobs) if not blockers else ([], {})
    plan_by_id = {str(row.get("strategy_id")): row for row in plan_entries}
    results: list[dict[str, Any]] = []
    for strategy_id in sorted(unresolved_ids):
        entry = plan_by_id.get(strategy_id, {})
        refs = reference_rows(entry, by_path)
        result = classify_strategy(strategy_id, refs, all_rows)
        result["engine_cluster_id"] = entry.get("engine_cluster_id")
        result["reference_paths"] = sorted({str(row.get("path")) for row in refs})
        result["reference_callables"] = sorted({str(row.get("callable")) for row in refs})
        results.append(result)

    counts: dict[str, int] = {}
    for row in results:
        key = str(row.get("classification"))
        counts[key] = counts.get(key, 0) + 1
    resolvable_count = sum(bool(row.get("resolvable")) for row in results)
    ambiguous_count = counts.get("MULTIPLE_PRODUCTION_MATCHES", 0)
    implementation_gap_count = sum(
        counts.get(key, 0) for key in (
            "DIAGNOSTIC_ONLY_REFERENCE", "CONFIG_ONLY_REFERENCE", "NO_IMPLEMENTATION_BODY_MATCH"
        )
    )

    after = {path: sha256(Path(path)) for path in contract.get("protected_paths", [])}
    changed = [path for path in before if before[path] != after[path]]
    if changed:
        blockers.append("PROTECTED_PATH_CHANGED")
    blockers = list(dict.fromkeys(blockers))
    state = "PASS" if not blockers else "HOLD"
    if blockers:
        next_stage = contract["next_stage_fail"]
    elif implementation_gap_count:
        next_stage = contract["next_stage_implementation_gap"]
    elif ambiguous_count:
        next_stage = contract["next_stage_ambiguous"]
    else:
        next_stage = contract["next_stage_all_resolvable"]

    proof = {
        "schema": "strategy25_engine_lineage_classification_v1",
        "official_stage": "R7.A3E2C",
        "read_only": True,
        "target_commit": args.target_sha,
        "strategy_count": expected,
        "unresolved_input_count": len(unresolved_ids),
        "resolvable_engine_count": resolvable_count,
        "ambiguous_engine_count": ambiguous_count,
        "implementation_gap_count": implementation_gap_count,
        "classification_counts": counts,
        "entries": results,
    }
    atomic(root / contract["proof_path"], proof)
    status = {
        "official_stage": "R7.A3E2C",
        "state": state,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "strategy_count": expected,
        "prior_engine_bound_count": 2,
        "config_bound_count": 25,
        "unresolved_input_count": len(unresolved_ids),
        "resolvable_engine_count": resolvable_count,
        "ambiguous_engine_count": ambiguous_count,
        "implementation_gap_count": implementation_gap_count,
        "canonical_registry_mutation_count": 0,
        "strategy_logic_mutation_count": 0,
        "active_entry_count": 0,
        "protected_change_count": len(changed),
        "runtime_mutation_count": 0,
        "proof_path": str(root / contract["proof_path"]),
        "next_stage": next_stage,
    }
    atomic(root / contract["status_path"], status)
    for key in (
        "state", "blocker_count", "strategy_count", "prior_engine_bound_count",
        "config_bound_count", "unresolved_input_count", "resolvable_engine_count",
        "ambiguous_engine_count", "implementation_gap_count", "active_entry_count",
        "protected_change_count", "next_stage",
    ):
        print(f"{key.upper()}={status[key]}")
    print("CLASSIFICATION_COUNTS=" + json.dumps(counts, ensure_ascii=False, sort_keys=True))
    print("ENGINE_GAPS=" + json.dumps([
        {"strategy_id": row["strategy_id"], "classification": row["classification"],
         "source_match_count": row["source_match_count"], "diagnostic_match_count": row["diagnostic_match_count"]}
        for row in results if not row.get("resolvable")
    ], ensure_ascii=False))
    print("PROOF_JSON=" + status["proof_path"])
    print("RC=" + str(0 if state == "PASS" else 2))
    return 0 if state == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
