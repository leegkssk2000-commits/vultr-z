#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

ARTIFACT_PARTS = {
    "runtime_results", "artifacts", "artifact", "snapshots", "snapshot",
    "strategy_source_snapshot", "exact25_candidate_package", "candidate_package",
    "archives", "archive", "backups", "backup", "generated", "build", "dist",
    "reports", "report", "tmp", "temp", "logs",
}
DIAGNOSTIC_PARTS = {"tools", "tests", "test", "docs", "examples", "notebooks"}
CONFIG_PARTS = {"config", "configs", "manifests", "runtime"}
PRODUCTION_PREFIXES = (
    "backend/", "services/", "src/", "app/", "core/", "strategies/", "workers/",
)


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


def path_kind(path: str) -> str:
    low = path.lower().lstrip("./")
    parts = set(Path(low).parts)
    if parts & ARTIFACT_PARTS or low.startswith("runtime_results/"):
        return "ARTIFACT"
    if parts & DIAGNOSTIC_PARTS:
        return "DIAGNOSTIC"
    if parts & CONFIG_PARTS or Path(low).suffix in {".json", ".yaml", ".yml", ".toml"}:
        return "CONFIG"
    if low.startswith(PRODUCTION_PREFIXES):
        return "SOURCE"
    return "OTHER"


def full_hash(node: ast.AST) -> str:
    payload = ast.dump(node, annotate_fields=True, include_attributes=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def semantic_hash(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    payload = {
        "async": isinstance(node, ast.AsyncFunctionDef),
        "positional": len(node.args.posonlyargs) + len(node.args.args),
        "kwonly": len(node.args.kwonlyargs),
        "vararg": node.args.vararg is not None,
        "kwarg": node.args.kwarg is not None,
        "body": ast.dump(ast.Module(body=node.body, type_ignores=[]), annotate_fields=True, include_attributes=False),
    }
    return hashlib.sha256(repr(sorted(payload.items())).encode()).hexdigest()


def function_rows(source: str, path: str) -> list[dict[str, Any]]:
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError:
        return []
    rows: list[dict[str, Any]] = []

    def visit(body: list[ast.stmt], owner: str | None = None) -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qname = f"{owner}.{node.name}" if owner else node.name
                rows.append({
                    "path": path,
                    "callable": qname,
                    "callable_leaf": node.name,
                    "path_kind": path_kind(path),
                    "full_hash": full_hash(node),
                    "semantic_hash": semantic_hash(node),
                })
            elif isinstance(node, ast.ClassDef):
                visit(node.body, node.name)
    visit(tree.body)
    return rows


def scan(snapshot: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in snapshot.rglob("*.py"):
        if not path.is_file() or path.stat().st_size > 2_000_000:
            continue
        repo_path = path.relative_to(snapshot).as_posix()
        source = path.read_text(encoding="utf-8", errors="replace")
        rows.extend(function_rows(source, repo_path))
    return rows


def identity_keys(entry: dict[str, Any]) -> tuple[set[str], set[str], set[str]]:
    semantic: set[str] = set()
    full: set[str] = set()
    names: set[str] = set()
    for candidate in entry.get("ranked_candidates", []):
        if not isinstance(candidate, dict):
            continue
        if candidate.get("semantic_hash"):
            semantic.add(str(candidate["semantic_hash"]))
        if candidate.get("full_hash"):
            full.add(str(candidate["full_hash"]))
        if candidate.get("callable_leaf"):
            names.add(str(candidate["callable_leaf"]))
        elif candidate.get("callable"):
            names.add(str(candidate["callable"]).split(".")[-1])
    return semantic, full, names


def classify(entry: dict[str, Any], all_rows: list[dict[str, Any]]) -> dict[str, Any]:
    strategy_id = str(entry.get("strategy_id") or "")
    semantic, full, names = identity_keys(entry)
    matches = [
        row for row in all_rows
        if (semantic and row.get("semantic_hash") in semantic)
        or (full and row.get("full_hash") in full)
    ]
    if not matches and names:
        matches = [row for row in all_rows if row.get("callable_leaf") in names and strategy_id in Path(str(row.get("path"))).stem]
    by_kind: dict[str, list[dict[str, Any]]] = {}
    for row in matches:
        by_kind.setdefault(str(row.get("path_kind")), []).append(row)
    true_source = by_kind.get("SOURCE", [])
    artifacts = by_kind.get("ARTIFACT", [])
    if len(true_source) == 1:
        classification = "UNIQUE_TRUE_PRODUCTION_ENGINE"
        canonical = true_source[0]
    elif len(true_source) > 1:
        classification = "MULTIPLE_TRUE_PRODUCTION_ENGINES"
        canonical = None
    elif artifacts:
        classification = "ARTIFACT_SNAPSHOT_ONLY_NO_TRUE_ENGINE"
        canonical = None
    else:
        classification = "NO_TRUE_PRODUCTION_ENGINE"
        canonical = None
    return {
        "strategy_id": strategy_id,
        "classification": classification,
        "canonical_candidate": canonical,
        "true_source_count": len(true_source),
        "artifact_match_count": len(artifacts),
        "diagnostic_match_count": len(by_kind.get("DIAGNOSTIC", [])),
        "config_match_count": len(by_kind.get("CONFIG", [])),
        "other_match_count": len(by_kind.get("OTHER", [])),
        "true_source_matches": true_source[:10],
        "artifact_matches": artifacts[:10],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--target-sha", required=True)
    parser.add_argument("--contract", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    snapshot = Path(args.snapshot).resolve()
    contract = load(Path(args.contract))
    prior_status = load(root / contract["prior_status_path"])
    prior_selection = load(root / contract["prior_selection_path"])
    blockers: list[str] = []

    if not (prior_status.get("state") == "PASS" and prior_status.get("blocker_count") == 0):
        blockers.append("PRIOR_A3E2C3_INVALID")
    if prior_status.get("canonical_selected_count") != int(contract.get("expected_selected_count", 0)):
        blockers.append("PRIOR_SELECTED_COUNT_MISMATCH")
    if prior_status.get("owner_record_required_count") != int(contract.get("expected_owner_required_count", 23)):
        blockers.append("PRIOR_OWNER_REQUIRED_COUNT_MISMATCH")
    entries = [row for row in prior_selection.get("entries", []) if isinstance(row, dict)]
    unresolved = [row for row in entries if row.get("selection_state") == "EXPLICIT_OWNER_RECORD_REQUIRED"]
    if len(unresolved) != int(contract.get("expected_owner_required_count", 23)):
        blockers.append("OWNER_REQUIRED_ENTRY_COUNT_NOT_23")
    if not snapshot.is_dir():
        blockers.append("TARGET_SNAPSHOT_INVALID")

    before = {path: sha256(Path(path)) for path in contract.get("protected_paths", [])}
    all_rows = scan(snapshot) if not blockers else []
    results = [classify(entry, all_rows) for entry in sorted(unresolved, key=lambda row: str(row.get("strategy_id")))]

    unique_count = sum(row["classification"] == "UNIQUE_TRUE_PRODUCTION_ENGINE" for row in results)
    ambiguous_count = sum(row["classification"] == "MULTIPLE_TRUE_PRODUCTION_ENGINES" for row in results)
    gap_count = sum(row["classification"] in {"ARTIFACT_SNAPSHOT_ONLY_NO_TRUE_ENGINE", "NO_TRUE_PRODUCTION_ENGINE"} for row in results)
    artifact_only_count = sum(row["classification"] == "ARTIFACT_SNAPSHOT_ONLY_NO_TRUE_ENGINE" for row in results)
    false_positive_candidate_count = sum(int(row.get("artifact_match_count", 0)) for row in results)

    after = {path: sha256(Path(path)) for path in contract.get("protected_paths", [])}
    changed = [path for path in before if before[path] != after[path]]
    if changed:
        blockers.append("PROTECTED_PATH_CHANGED")
    blockers = list(dict.fromkeys(blockers))
    state = "PASS" if not blockers else "HOLD"
    if blockers:
        next_stage = contract["next_stage_fail"]
    elif gap_count:
        next_stage = contract["next_stage_true_gap"]
    elif ambiguous_count:
        next_stage = contract["next_stage_true_ambiguous"]
    else:
        next_stage = contract["next_stage_all_unique"]

    proof = {
        "schema": "strategy25_snapshot_false_positive_correction_v1",
        "official_stage": "R7.A3E2C3F",
        "read_only": True,
        "target_commit": args.target_sha,
        "strategy_count": int(contract.get("expected_strategy_count", 25)),
        "corrected_input_count": len(results),
        "unique_true_engine_count": unique_count,
        "ambiguous_true_engine_count": ambiguous_count,
        "true_implementation_gap_count": gap_count,
        "artifact_snapshot_only_count": artifact_only_count,
        "false_positive_candidate_count": false_positive_candidate_count,
        "entries": results,
    }
    atomic(root / contract["proof_path"], proof)
    status = {
        "official_stage": "R7.A3E2C3F",
        "state": state,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "strategy_count": int(contract.get("expected_strategy_count", 25)),
        "prior_owner_record_required_count": len(unresolved),
        "unique_true_engine_count": unique_count,
        "ambiguous_true_engine_count": ambiguous_count,
        "true_implementation_gap_count": gap_count,
        "artifact_snapshot_only_count": artifact_only_count,
        "false_positive_candidate_count": false_positive_candidate_count,
        "active_entry_count": 0,
        "canonical_registry_mutation_count": 0,
        "strategy_logic_mutation_count": 0,
        "protected_change_count": len(changed),
        "runtime_mutation_count": 0,
        "proof_path": str(root / contract["proof_path"]),
        "next_stage": next_stage,
    }
    atomic(root / contract["status_path"], status)
    for key in (
        "state", "blocker_count", "strategy_count", "prior_owner_record_required_count",
        "unique_true_engine_count", "ambiguous_true_engine_count", "true_implementation_gap_count",
        "artifact_snapshot_only_count", "false_positive_candidate_count", "active_entry_count",
        "protected_change_count", "next_stage",
    ):
        print(f"{key.upper()}={status[key]}")
    print("CORRECTED_GAPS=" + json.dumps([
        {"strategy_id": row["strategy_id"], "classification": row["classification"],
         "true_source_count": row["true_source_count"], "artifact_match_count": row["artifact_match_count"]}
        for row in results if row["classification"] != "UNIQUE_TRUE_PRODUCTION_ENGINE"
    ], ensure_ascii=False))
    print("PROOF_JSON=" + status["proof_path"])
    print("RC=" + str(0 if state == "PASS" else 2))
    return 0 if state == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
