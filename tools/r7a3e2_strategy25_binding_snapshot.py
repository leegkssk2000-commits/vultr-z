#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from r7a3e2_binding_lib import (
    callable_exists,
    engine_score,
    find_pointers,
    manifest_score,
    select_unique_engine,
    select_unique_manifest,
)


def load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def sha256(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def read_tree(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "\t" not in line:
            continue
        meta, repo_path = line.split("\t", 1)
        parts = meta.split()
        if len(parts) >= 3:
            result[repo_path] = parts[2]
    return result


def engine_rows(
    snapshot: Path,
    blobs: dict[str, str],
    strategy_id: str,
    paths: list[str],
    callables: list[str],
    prefixes: list[str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for repo_path in sorted(set(paths)):
        source_path = snapshot / repo_path
        if not source_path.is_file() or not repo_path.endswith(".py"):
            continue
        source = source_path.read_text(encoding="utf-8", errors="replace")
        for callable_name in sorted(set(callables)):
            if not callable_exists(source, callable_name, repo_path):
                continue
            rows.append({
                "implementation_path": repo_path,
                "callable": callable_name,
                "source_blob_sha": blobs.get(repo_path),
                "source_sha256": sha256(source_path),
                "selection_score": engine_score(repo_path, callable_name, strategy_id, prefixes),
            })
    return rows


def manifest_rows(
    snapshot: Path,
    blobs: dict[str, str],
    strategy_ids: list[str],
    hints: list[str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source_path in snapshot.rglob("*.json"):
        repo_path = source_path.relative_to(snapshot).as_posix()
        if source_path.stat().st_size > 4_000_000:
            continue
        try:
            value = json.loads(source_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        pointers = {strategy_id: find_pointers(value, strategy_id) for strategy_id in strategy_ids}
        if not all(pointers[strategy_id] for strategy_id in strategy_ids):
            continue
        rows.append({
            "manifest_path": repo_path,
            "manifest_blob_sha": blobs.get(repo_path),
            "manifest_sha256": sha256(source_path),
            "selection_score": manifest_score(repo_path, hints),
            "strategy_pointers": pointers,
        })
    return rows


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
    prior_plan = load(root / contract["prior_plan_path"])
    blobs = read_tree(Path(args.tree))
    blockers: list[str] = []

    if not (prior_status.get("state") == "PASS" and prior_status.get("blocker_count") == 0):
        blockers.append("PRIOR_A3E1_INVALID")
    if prior_status.get("strategy_count") != int(contract.get("expected_strategy_count", 25)):
        blockers.append("PRIOR_STRATEGY_COUNT_MISMATCH")
    if prior_status.get("engine_cluster_count") != int(contract.get("expected_engine_cluster_count", 23)):
        blockers.append("PRIOR_CLUSTER_COUNT_MISMATCH")
    if not snapshot.is_dir() or not blobs:
        blockers.append("TARGET_SNAPSHOT_INVALID")

    entries = [row for row in prior_plan.get("entries", []) if isinstance(row, dict)]
    clusters = [row for row in prior_plan.get("engine_clusters", []) if isinstance(row, dict)]
    if len(entries) != 25:
        blockers.append("PRIOR_ENTRY_COUNT_NOT_25")
    if len(clusters) != 23:
        blockers.append("PRIOR_CLUSTER_COUNT_NOT_23")
    strategy_ids = sorted(str(row.get("strategy_id") or "") for row in entries)
    if len(set(strategy_ids)) != 25 or any(not value for value in strategy_ids):
        blockers.append("STRATEGY_IDS_INVALID")

    manifests = manifest_rows(
        snapshot,
        blobs,
        strategy_ids,
        list(contract.get("manifest_path_hints", [])),
    ) if strategy_ids else []
    manifest, manifest_error = select_unique_manifest(manifests, strategy_ids)
    cluster_by_id = {str(row.get("engine_cluster_id")): row for row in clusters}

    matrix_entries: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    engine_bound = config_bound = complete_count = 0

    for entry in sorted(entries, key=lambda row: str(row.get("strategy_id"))):
        strategy_id = str(entry.get("strategy_id") or "")
        config_ref = None
        if manifest:
            pointer = manifest["strategy_pointers"][strategy_id][0]
            config_ref = f"{manifest['manifest_path']}#{pointer}"
            config_bound += 1

        selected_engine = None
        candidates: list[dict[str, Any]] = []
        engine_error = None
        if entry.get("binding_mode") == "DIRECT_PROVEN":
            if entry.get("implementation_path") and entry.get("callable") and entry.get("source_blob_sha"):
                selected_engine = {
                    "implementation_path": entry["implementation_path"],
                    "callable": entry["callable"],
                    "source_blob_sha": entry["source_blob_sha"],
                    "binding_source": entry.get("binding_source") or "A3E1_DIRECT_PROVEN",
                }
            else:
                engine_error = "DIRECT_ENGINE_INCOMPLETE"
        else:
            cluster = cluster_by_id.get(str(entry.get("engine_cluster_id")))
            if not cluster:
                engine_error = "ENGINE_CLUSTER_MISSING"
            else:
                candidates = engine_rows(
                    snapshot,
                    blobs,
                    strategy_id,
                    list(cluster.get("candidate_paths") or []),
                    list(cluster.get("candidate_callables") or []),
                    list(contract.get("allowed_engine_prefixes", [])),
                )
                selected_engine, engine_error = select_unique_engine(candidates)
                if selected_engine:
                    selected_engine = {
                        **selected_engine,
                        "binding_source": "A3E2_DETERMINISTIC_PRODUCTION_SELECTION",
                    }

        if selected_engine:
            engine_bound += 1
        complete = bool(selected_engine and config_ref)
        complete_count += int(complete)
        reasons = [reason for reason in (engine_error, manifest_error) if reason]
        if not complete:
            unresolved.append({"strategy_id": strategy_id, "reasons": reasons})
        matrix_entries.append({
            "strategy_id": strategy_id,
            "binding_mode": entry.get("binding_mode"),
            "engine_cluster_id": entry.get("engine_cluster_id"),
            "canonical_engine": selected_engine,
            "config_ref": config_ref,
            "binding_complete": complete,
            "active_allowed": False,
            "fail_closed": True,
            "engine_error": engine_error,
            "engine_candidates": candidates[:12],
        })

    before = {path: sha256(Path(path)) for path in contract.get("protected_paths", [])}
    matrix = {
        "schema": "strategy25_per_strategy_engine_binding_matrix_v1",
        "official_stage": "R7.A3E2",
        "read_only_plan": True,
        "target_commit": args.target_sha,
        "future_registry_path": contract["future_registry_path"],
        "strategy_count": len(matrix_entries),
        "engine_cluster_count": len(clusters),
        "engine_bound_count": engine_bound,
        "config_bound_count": config_bound,
        "binding_complete_count": complete_count,
        "unresolved_count": 25 - complete_count,
        "active_entry_count": 0,
        "fail_closed_entry_count": sum(bool(row["fail_closed"]) for row in matrix_entries),
        "manifest_selection": manifest,
        "manifest_candidates": manifests[:20],
        "manifest_error": manifest_error,
        "entries": matrix_entries,
    }
    atomic(root / contract["matrix_path"], matrix)
    after = {path: sha256(Path(path)) for path in contract.get("protected_paths", [])}
    changed = [path for path in before if before[path] != after[path]]
    if changed:
        blockers.append("PROTECTED_PATH_CHANGED")

    blockers = list(dict.fromkeys(blockers))
    state = "PASS" if not blockers else "HOLD"
    if blockers:
        next_stage = contract["next_stage_fail"]
    elif matrix["unresolved_count"] == 0:
        next_stage = contract["next_stage_all_bound"]
    else:
        next_stage = contract["next_stage_gap"]

    status = {
        "official_stage": "R7.A3E2",
        "state": state,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "strategy_count": len(matrix_entries),
        "engine_cluster_count": len(clusters),
        "engine_bound_count": engine_bound,
        "config_bound_count": config_bound,
        "binding_complete_count": complete_count,
        "unresolved_count": matrix["unresolved_count"],
        "active_entry_count": 0,
        "canonical_registry_mutation_count": 0,
        "strategy_logic_mutation_count": 0,
        "router_mutation_count": 0,
        "service_mutation_count": 0,
        "protected_change_count": len(changed),
        "runtime_mutation_count": 0,
        "matrix_path": str(root / contract["matrix_path"]),
        "next_stage": next_stage,
    }
    atomic(root / contract["status_path"], status)
    for key in (
        "state", "blocker_count", "strategy_count", "engine_cluster_count",
        "engine_bound_count", "config_bound_count", "binding_complete_count",
        "unresolved_count", "active_entry_count", "canonical_registry_mutation_count",
        "protected_change_count", "next_stage",
    ):
        print(f"{key.upper()}={status[key]}")
    print("MANIFEST_ERROR=" + str(manifest_error))
    print("UNRESOLVED=" + json.dumps(unresolved, ensure_ascii=False))
    print("MATRIX_JSON=" + status["matrix_path"])
    print("RC=" + str(0 if state == "PASS" else 2))
    return 0 if state == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
