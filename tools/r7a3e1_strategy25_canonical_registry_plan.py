#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


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


def file_sha(path: str) -> str | None:
    target = Path(path)
    if not target.is_file():
        return None
    return hashlib.sha256(target.read_bytes()).hexdigest()


def cluster_id(body_sha: str) -> str:
    return f"engine.{body_sha[:16]}"


def direct_entry(row: dict[str, Any]) -> dict[str, Any]:
    mapping = row.get("canonical_mapping") if isinstance(row.get("canonical_mapping"), dict) else {}
    return {
        "strategy_id": str(row.get("strategy_id") or ""),
        "binding_mode": "DIRECT_PROVEN",
        "binding_state": "STATIC_PROVEN_NOT_ACTIVATED",
        "implementation_path": mapping.get("implementation_path"),
        "callable": mapping.get("callable"),
        "source_blob_sha": mapping.get("source_blob_sha"),
        "engine_cluster_id": None,
        "config_ref": None,
        "active_allowed": False,
        "fail_closed": True,
        "binding_source": mapping.get("binding_source") or "A3D3C2_PRIOR_PROVEN",
    }


def shared_entry(row: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    candidates = [item for item in row.get("candidate_proofs", []) if isinstance(item, dict)]
    complete = [
        item for item in candidates
        if item.get("source_exists") is True
        and item.get("callable_exists") is True
        and item.get("actual_blob_sha")
        and item.get("callable_body_sha256")
    ]
    body_hashes = sorted({str(item.get("callable_body_sha256")) for item in complete})
    errors: list[str] = []
    if len(body_hashes) != 1:
        errors.append(f"SHARED_BODY_HASH_NOT_UNIQUE:{row.get('strategy_id')}:{len(body_hashes)}")
    body_sha = body_hashes[0] if len(body_hashes) == 1 else ""
    paths = sorted({str(item.get("implementation_path")) for item in complete if item.get("implementation_path")})
    callables = sorted({str(item.get("callable")) for item in complete if item.get("callable")})
    blobs = sorted({str(item.get("actual_blob_sha")) for item in complete if item.get("actual_blob_sha")})
    return {
        "strategy_id": str(row.get("strategy_id") or ""),
        "binding_mode": "SHARED_ENGINE",
        "binding_state": "EXPLICIT_CONFIG_BINDING_REQUIRED",
        "implementation_path": None,
        "callable": None,
        "source_blob_sha": None,
        "engine_cluster_id": cluster_id(body_sha) if body_sha else None,
        "engine_body_sha256": body_sha or None,
        "candidate_paths": paths,
        "candidate_callables": callables,
        "candidate_source_blob_shas": blobs,
        "config_ref": None,
        "active_allowed": False,
        "fail_closed": True,
        "binding_source": "A3D3C2_SHARED_ENGINE_CLASSIFICATION",
    }, errors


def build_plan(proof: dict[str, Any], expected: int) -> tuple[dict[str, Any], list[str]]:
    rows = [row for row in proof.get("mappings", []) if isinstance(row, dict)]
    errors: list[str] = []
    if len(rows) != expected:
        errors.append(f"PROOF_MAPPING_COUNT_NOT_{expected}")

    entries: list[dict[str, Any]] = []
    for row in rows:
        classification = str(row.get("classification") or "")
        if row.get("proven") is True and row.get("canonical_mapping"):
            entries.append(direct_entry(row))
        elif classification == "SHARED_ENGINE_REQUIRES_EXPLICIT_BINDING":
            entry, row_errors = shared_entry(row)
            entries.append(entry)
            errors.extend(row_errors)
        else:
            errors.append(f"UNSUPPORTED_IMPLEMENTATION_CLASS:{row.get('strategy_id')}:{classification}")

    ids = [entry.get("strategy_id") for entry in entries]
    if len(set(ids)) != len(ids):
        errors.append("DUPLICATE_STRATEGY_ID")
    if any(not value for value in ids):
        errors.append("EMPTY_STRATEGY_ID")

    direct_count = sum(entry.get("binding_mode") == "DIRECT_PROVEN" for entry in entries)
    shared_count = sum(entry.get("binding_mode") == "SHARED_ENGINE" for entry in entries)
    cluster_members: dict[str, list[str]] = defaultdict(list)
    cluster_paths: dict[str, set[str]] = defaultdict(set)
    cluster_callables: dict[str, set[str]] = defaultdict(set)
    for entry in entries:
        cid = entry.get("engine_cluster_id")
        if cid:
            cluster_members[str(cid)].append(str(entry.get("strategy_id")))
            cluster_paths[str(cid)].update(entry.get("candidate_paths") or [])
            cluster_callables[str(cid)].update(entry.get("candidate_callables") or [])

    clusters = [
        {
            "engine_cluster_id": cid,
            "strategy_count": len(strategy_ids),
            "strategy_ids": sorted(strategy_ids),
            "candidate_paths": sorted(cluster_paths[cid]),
            "candidate_callables": sorted(cluster_callables[cid]),
            "canonical_engine_path": None,
            "canonical_callable": None,
            "binding_state": "ENGINE_AND_CONFIG_SELECTION_REQUIRED",
            "active_allowed": False,
        }
        for cid, strategy_ids in sorted(cluster_members.items())
    ]

    plan = {
        "schema": "canonical_strategy_registry_plan_v1",
        "official_stage": "R7.A3E1",
        "read_only_plan": True,
        "future_registry_path": "backend/strategy25/canonical_strategy_registry_v1.json",
        "strategy_count": len(entries),
        "direct_proven_count": direct_count,
        "shared_binding_required_count": shared_count,
        "engine_cluster_count": len(clusters),
        "active_entry_count": 0,
        "fail_closed_entry_count": sum(bool(entry.get("fail_closed")) for entry in entries),
        "required_entry_fields": [
            "strategy_id", "binding_mode", "implementation_path", "callable",
            "source_blob_sha", "engine_cluster_id", "config_ref", "binding_source"
        ],
        "engine_clusters": clusters,
        "entries": sorted(entries, key=lambda item: str(item.get("strategy_id"))),
    }
    return plan, errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--contract", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    contract = load(Path(args.contract))
    prior_status = load(root / contract["prior_status_path"])
    proof = load(root / contract["prior_proof_path"])
    expected = int(contract.get("expected_strategy_count", 25))
    blockers: list[str] = []

    if not (prior_status.get("state") == "PASS" and prior_status.get("blocker_count") == 0):
        blockers.append("PRIOR_A3D3C2_INVALID")
    if prior_status.get("proven_mapping_count") != int(contract.get("expected_direct_count", 2)):
        blockers.append("PRIOR_DIRECT_COUNT_MISMATCH")
    if prior_status.get("implementation_gap_count") != int(contract.get("expected_shared_binding_count", 23)):
        blockers.append("PRIOR_SHARED_GAP_COUNT_MISMATCH")

    before = {path: file_sha(path) for path in contract.get("protected_paths", [])}
    plan, plan_errors = build_plan(proof, expected)
    blockers.extend(plan_errors)

    if plan.get("direct_proven_count") != int(contract.get("expected_direct_count", 2)):
        blockers.append("PLAN_DIRECT_COUNT_MISMATCH")
    if plan.get("shared_binding_required_count") != int(contract.get("expected_shared_binding_count", 23)):
        blockers.append("PLAN_SHARED_COUNT_MISMATCH")
    if plan.get("active_entry_count") != 0:
        blockers.append("PLAN_ACTIVE_ENTRY_NOT_ZERO")

    atomic(root / contract["plan_path"], plan)
    after = {path: file_sha(path) for path in contract.get("protected_paths", [])}
    changed = [path for path in before if before[path] != after[path]]
    if changed:
        blockers.append("PROTECTED_PATH_CHANGED")
    blockers = list(dict.fromkeys(blockers))

    state = "PASS" if not blockers else "HOLD"
    status = {
        "official_stage": "R7.A3E1",
        "state": state,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "strategy_count": plan.get("strategy_count", 0),
        "direct_proven_count": plan.get("direct_proven_count", 0),
        "shared_binding_required_count": plan.get("shared_binding_required_count", 0),
        "engine_cluster_count": plan.get("engine_cluster_count", 0),
        "active_entry_count": plan.get("active_entry_count", 0),
        "canonical_registry_mutation_count": 0,
        "strategy_logic_mutation_count": 0,
        "service_mutation_count": 0,
        "protected_change_count": len(changed),
        "runtime_mutation_count": 0,
        "performance_s_promoted_count": 0,
        "plan_path": str(root / contract["plan_path"]),
        "next_stage": contract["next_stage_pass"] if state == "PASS" else contract["next_stage_fail"],
    }
    atomic(root / contract["status_path"], status)
    for key in (
        "state", "blocker_count", "strategy_count", "direct_proven_count",
        "shared_binding_required_count", "engine_cluster_count", "active_entry_count",
        "canonical_registry_mutation_count", "protected_change_count", "next_stage",
    ):
        print(f"{key.upper()}={status[key]}")
    print("CLUSTER_COUNTS=" + json.dumps(
        {row["engine_cluster_id"]: row["strategy_count"] for row in plan.get("engine_clusters", [])},
        ensure_ascii=False, sort_keys=True,
    ))
    print("PLAN_JSON=" + status["plan_path"])
    print("RC=" + str(0 if state == "PASS" else 2))
    return 0 if state == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
