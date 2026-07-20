#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import py_compile
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ARTIFACT_PARTS = {
    "runtime_results", "artifacts", "artifact", "snapshots", "snapshot",
    "strategy_source_snapshot", "exact25_candidate_package", "candidate_package",
    "archives", "archive", "backups", "backup", "generated", "build", "dist",
}


def load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def atomic_json(path: Path, value: dict[str, Any]) -> None:
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


def atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str | None:
    return sha256_bytes(path.read_bytes()) if path.is_file() else None


def module_ast_sha(source: str, filename: str = "<source>") -> str | None:
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError:
        return None
    payload = ast.dump(tree, annotate_fields=True, include_attributes=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def callable_names(source: str, filename: str) -> set[str]:
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError:
        return set()
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    names.add(f"{node.name}.{child.name}")
    return names


def command(root: Path, args: list[str], timeout: int = 60) -> str:
    result = subprocess.run(
        args, cwd=root, text=True, capture_output=True, timeout=timeout,
        env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
    )
    return result.stdout if result.returncode == 0 else ""


def is_true_source(path: str, allowed: list[str]) -> bool:
    low = path.lower().lstrip("./")
    parts = set(Path(low).parts)
    return low.startswith(tuple(allowed)) and not bool(parts & ARTIFACT_PARTS)


def historical_rows(root: Path, strategy_id: str, allowed: list[str]) -> list[dict[str, Any]]:
    spec = f":(glob)**/{strategy_id}.py"
    text = command(root, ["git", "log", "--all", "--format=@@%H", "--name-only", "--", spec], 120)
    rows: list[dict[str, Any]] = []
    commit = ""
    seen: set[tuple[str, str]] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("@@"):
            commit = line[2:]
            continue
        if not line or not commit or not is_true_source(line, allowed):
            continue
        key = (commit, line)
        if key in seen:
            continue
        seen.add(key)
        source = command(root, ["git", "show", f"{commit}:{line}"], 30)
        ast_sha = module_ast_sha(source, f"{commit}:{line}") if source else None
        if not ast_sha:
            continue
        blob = command(root, ["git", "rev-parse", f"{commit}:{line}"], 15).strip() or None
        rows.append({
            "commit": commit,
            "path": line,
            "blob_sha": blob,
            "source": source,
            "source_sha256": sha256_bytes(source.encode()),
            "module_ast_sha256": ast_sha,
        })
    return rows


def baseline_hits(root: Path, roots: list[str], hashes: list[str]) -> dict[str, int]:
    counts = {value: 0 for value in hashes}
    for relative in roots:
        base = root / relative
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in {".json", ".jsonl", ".txt"}:
                continue
            try:
                if path.stat().st_size > 5_000_000:
                    continue
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for value in hashes:
                counts[value] += text.count(value)
    return counts


def choose_callable(source: str, path: str, artifact_matches: list[dict[str, Any]]) -> str | None:
    available = callable_names(source, path)
    expected = {
        str(row.get("callable")) for row in artifact_matches
        if row.get("callable")
    }
    intersection = sorted(available & expected)
    if len(intersection) == 1:
        return intersection[0]
    expected_leaf = {value.split(".")[-1] for value in expected}
    leaf_matches = sorted(value for value in available if value.split(".")[-1] in expected_leaf)
    if len(leaf_matches) == 1:
        return leaf_matches[0]
    if len(available) == 1:
        return next(iter(available))
    return None


def select_source(
    root: Path,
    strategy_id: str,
    entry: dict[str, Any],
    allowed: list[str],
    baseline_roots: list[str],
    default_prefix: str,
) -> tuple[dict[str, Any] | None, list[str]]:
    reasons: list[str] = []
    artifacts: list[dict[str, Any]] = []
    for row in entry.get("artifact_matches", []):
        if not isinstance(row, dict) or not row.get("path"):
            continue
        repo_path = str(row["path"])
        path = root / repo_path
        if not path.is_file():
            reasons.append(f"ARTIFACT_MISSING:{repo_path}")
            continue
        source = path.read_text(encoding="utf-8", errors="replace")
        ast_sha = module_ast_sha(source, repo_path)
        if not ast_sha:
            reasons.append(f"ARTIFACT_SYNTAX_INVALID:{repo_path}")
            continue
        artifacts.append({
            **row,
            "source": source,
            "source_sha256": sha256_bytes(source.encode()),
            "module_ast_sha256": ast_sha,
        })
    unique_artifacts: dict[tuple[str, str], dict[str, Any]] = {}
    for row in artifacts:
        unique_artifacts[(row["source_sha256"], row["module_ast_sha256"])] = row
    artifacts = list(unique_artifacts.values())
    if not artifacts:
        return None, reasons + ["NO_VALID_ARTIFACT"]

    history = historical_rows(root, strategy_id, allowed)
    artifact_ast = {row["module_ast_sha256"] for row in artifacts}
    matching_history = [row for row in history if row["module_ast_sha256"] in artifact_ast]
    matching_history_asts = {row["module_ast_sha256"] for row in matching_history}
    selected: dict[str, Any] | None = None
    decision = ""
    if len(matching_history_asts) == 1:
        selected = matching_history[0]
        decision = "HISTORICAL_GIT_BLOB_MATCHES_ARTIFACT_AST"
    elif len({row["module_ast_sha256"] for row in artifacts}) == 1:
        selected = artifacts[0]
        selected = {
            **selected,
            "path": f"{default_prefix.rstrip('/')}/{strategy_id}.py",
            "blob_sha": None,
        }
        decision = "ARTIFACT_PAIR_NORMALIZED_AST_IDENTICAL"
    else:
        counts = baseline_hits(root, baseline_roots, [row["source_sha256"] for row in artifacts])
        winners = [row for row in artifacts if counts.get(row["source_sha256"], 0) > 0]
        if len(winners) == 1:
            selected = {
                **winners[0],
                "path": f"{default_prefix.rstrip('/')}/{strategy_id}.py",
                "blob_sha": None,
            }
            decision = "UNIQUE_BASELINE_SHA_MATCH"
        else:
            reasons.append("ARTIFACTS_DIVERGE_WITHOUT_UNIQUE_BASELINE_MATCH")

    if not selected:
        return None, reasons
    source = str(selected["source"])
    callable_name = choose_callable(source, str(selected["path"]), artifacts)
    if not callable_name:
        return None, reasons + ["CALLABLE_NOT_UNIQUE"]
    destination = str(selected["path"])
    if not is_true_source(destination, allowed):
        destination = f"{default_prefix.rstrip('/')}/{strategy_id}.py"
    return {
        "strategy_id": strategy_id,
        "destination_path": destination,
        "callable": callable_name,
        "source": source,
        "source_sha256": sha256_bytes(source.encode()),
        "module_ast_sha256": module_ast_sha(source, destination),
        "origin_commit": selected.get("commit"),
        "origin_path": selected.get("path"),
        "origin_blob_sha": selected.get("blob_sha"),
        "decision_reason": decision,
        "artifact_paths": sorted(str(row.get("path")) for row in artifacts),
        "artifact_source_sha256": sorted(row["source_sha256"] for row in artifacts),
    }, reasons


def rollback(created: list[Path], overwritten: dict[Path, Path]) -> None:
    for path in reversed(created):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    for destination, backup in overwritten.items():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup, destination)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--contract", required=True)
    parser.add_argument("--target-sha", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    contract = load(Path(args.contract))
    prior_status = load(root / contract["prior_status_path"])
    proof = load(root / contract["prior_proof_path"])
    matrix = load(root / contract["prior_matrix_path"])
    blockers: list[str] = []

    if not (prior_status.get("state") == "PASS" and prior_status.get("blocker_count") == 0):
        blockers.append("PRIOR_CORRECTION_INVALID")
    if prior_status.get("true_implementation_gap_count") != int(contract.get("expected_restore_count", 23)):
        blockers.append("PRIOR_GAP_COUNT_NOT_23")
    proof_entries = [row for row in proof.get("entries", []) if isinstance(row, dict)]
    gap_entries = [row for row in proof_entries if row.get("classification") == "ARTIFACT_SNAPSHOT_ONLY_NO_TRUE_ENGINE"]
    matrix_entries = [row for row in matrix.get("entries", []) if isinstance(row, dict)]
    if len(gap_entries) != 23 or len(matrix_entries) != 25:
        blockers.append("INPUT_ENTRY_COUNT_INVALID")
    matrix_by_id = {str(row.get("strategy_id")): row for row in matrix_entries}
    if len(matrix_by_id) != 25 or any(not row.get("config_ref") for row in matrix_entries):
        blockers.append("CONFIG_BINDING_NOT_25")

    protected_before = {path: sha256_file(Path(path)) for path in contract.get("protected_paths", [])}
    allowed = list(contract.get("allowed_restore_prefixes", []))
    selected_rows: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    if not blockers:
        for entry in sorted(gap_entries, key=lambda row: str(row.get("strategy_id"))):
            strategy_id = str(entry.get("strategy_id") or "")
            selected, reasons = select_source(
                root, strategy_id, entry, allowed,
                list(contract.get("baseline_search_roots", [])),
                str(contract["default_restore_prefix"]),
            )
            if selected:
                destination = root / selected["destination_path"]
                if destination.exists() and sha256_file(destination) != selected["source_sha256"]:
                    unresolved.append({"strategy_id": strategy_id, "reasons": ["DESTINATION_CONFLICT"], "path": str(destination)})
                else:
                    selected["config_ref"] = matrix_by_id[strategy_id]["config_ref"]
                    selected_rows.append(selected)
            else:
                unresolved.append({"strategy_id": strategy_id, "reasons": reasons})

    restore_matrix = {
        "schema": "restore25_matrix_v1",
        "official_stage": "R7.RESTORE25",
        "target_commit": args.target_sha,
        "strategy_count": 25,
        "restore_input_count": len(gap_entries),
        "resolved_count": len(selected_rows),
        "unresolved_count": len(unresolved),
        "entries": [{key: value for key, value in row.items() if key != "source"} for row in selected_rows],
        "unresolved": unresolved,
    }
    atomic_json(root / contract["restore_matrix_path"], restore_matrix)

    applied = False
    restored_count = 0
    registry_entries: list[dict[str, Any]] = []
    verification_errors: list[str] = []
    created: list[Path] = []
    overwritten: dict[Path, Path] = {}
    backup_root = root / contract["rollback_root"] / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    if args.apply and not blockers and not unresolved and len(selected_rows) == 23:
        try:
            for row in matrix_entries:
                strategy_id = str(row["strategy_id"])
                if strategy_id in {item["strategy_id"] for item in selected_rows}:
                    selected = next(item for item in selected_rows if item["strategy_id"] == strategy_id)
                    engine = {
                        "implementation_path": selected["destination_path"],
                        "callable": selected["callable"],
                        "source_sha256": selected["source_sha256"],
                        "source_blob_sha": selected.get("origin_blob_sha"),
                        "binding_source": "RESTORE25_CANONICAL_RECOVERY",
                        "decision_reason": selected["decision_reason"],
                    }
                else:
                    engine = row.get("canonical_engine")
                    if not isinstance(engine, dict) or not engine.get("implementation_path") or not engine.get("callable"):
                        raise RuntimeError(f"DIRECT_ENGINE_INVALID:{strategy_id}")
                registry_entries.append({
                    "strategy_id": strategy_id,
                    "canonical_engine": engine,
                    "config_ref": row["config_ref"],
                    "active_allowed": False,
                    "fail_closed": True,
                })

            for selected in selected_rows:
                destination = root / selected["destination_path"]
                if destination.exists():
                    continue
                atomic_text(destination, selected["source"])
                created.append(destination)
                py_compile.compile(str(destination), doraise=True)
                restored_count += 1

            registry_path = root / contract["canonical_registry_path"]
            if registry_path.exists():
                backup = backup_root / contract["canonical_registry_path"]
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(registry_path, backup)
                overwritten[registry_path] = backup
            else:
                created.append(registry_path)
            registry = {
                "schema": "canonical_strategy25_registry_v1",
                "official_stage": "R7.RESTORE25",
                "active_entry_count": 0,
                "fail_closed": True,
                "strategy_count": 25,
                "entries": sorted(registry_entries, key=lambda row: row["strategy_id"]),
            }
            atomic_json(registry_path, registry)

            if len({row["strategy_id"] for row in registry_entries}) != 25:
                raise RuntimeError("REGISTRY_ID_COUNT_NOT_25")
            if any(row["active_allowed"] or not row["fail_closed"] or not row["config_ref"] for row in registry_entries):
                raise RuntimeError("REGISTRY_FAIL_CLOSED_CONTRACT_INVALID")
            for row in registry_entries:
                path = root / str(row["canonical_engine"]["implementation_path"])
                if not path.is_file():
                    raise RuntimeError(f"ENGINE_FILE_MISSING:{row['strategy_id']}")
                py_compile.compile(str(path), doraise=True)
            applied = True
        except Exception as exc:
            verification_errors.append(f"APPLY_FAILED:{type(exc).__name__}:{exc}")
            rollback(created, overwritten)
            restored_count = 0
            registry_entries = []

    protected_after = {path: sha256_file(Path(path)) for path in contract.get("protected_paths", [])}
    protected_changed = [path for path in protected_before if protected_before[path] != protected_after[path]]
    if protected_changed:
        blockers.append("PROTECTED_PATH_CHANGED")
        if applied:
            rollback(created, overwritten)
            applied = False
            restored_count = 0

    total_source_count = 0
    callable_valid_count = 0
    config_bound_count = 0
    if applied:
        for row in registry_entries:
            path = root / str(row["canonical_engine"]["implementation_path"])
            total_source_count += int(path.is_file())
            config_bound_count += int(bool(row.get("config_ref")))
            names = callable_names(path.read_text(encoding="utf-8", errors="replace"), str(path)) if path.is_file() else set()
            callable_valid_count += int(str(row["canonical_engine"]["callable"]) in names)

    verification = {
        "schema": "restore25_verification_v1",
        "official_stage": "R7.RESTORE25",
        "apply_requested": args.apply,
        "applied": applied,
        "restored_count": restored_count,
        "total_source_count": total_source_count,
        "callable_valid_count": callable_valid_count,
        "config_bound_count": config_bound_count,
        "canonical_unique_count": len({row["strategy_id"] for row in registry_entries}),
        "unresolved_count": len(unresolved),
        "active_entry_count": 0,
        "protected_change_count": len(protected_changed),
        "errors": verification_errors,
        "rollback_path": str(backup_root),
    }
    atomic_json(root / contract["verification_path"], verification)

    pass_gate = bool(
        applied and restored_count == 23 and total_source_count == 25
        and callable_valid_count == 25 and config_bound_count == 25
        and len({row["strategy_id"] for row in registry_entries}) == 25
        and not unresolved and not blockers and not verification_errors and not protected_changed
    )
    if blockers or verification_errors:
        state = "HOLD"
        next_stage = contract["next_stage_fail"]
    elif unresolved:
        state = "HOLD"
        next_stage = contract["next_stage_unresolved"]
    elif pass_gate:
        state = "PASS"
        next_stage = contract["next_stage_pass"]
    else:
        state = "HOLD"
        next_stage = contract["next_stage_fail"]

    status = {
        "official_stage": "R7.RESTORE25",
        "state": state,
        "blocker_count": len(blockers) + len(verification_errors) + len(unresolved),
        "blockers": blockers + verification_errors,
        "strategy_count": 25,
        "restore_input_count": len(gap_entries),
        "resolved_plan_count": len(selected_rows),
        "restored_count": restored_count,
        "total_source_count": total_source_count,
        "callable_valid_count": callable_valid_count,
        "config_bound_count": config_bound_count,
        "canonical_unique_count": len({row["strategy_id"] for row in registry_entries}),
        "unresolved_count": len(unresolved),
        "active_entry_count": 0,
        "protected_change_count": len(protected_changed),
        "runtime_mutation_count": 0,
        "registry_path": str(root / contract["canonical_registry_path"]),
        "restore_matrix_path": str(root / contract["restore_matrix_path"]),
        "verification_path": str(root / contract["verification_path"]),
        "next_stage": next_stage,
    }
    atomic_json(root / contract["status_path"], status)
    for key in (
        "state", "blocker_count", "strategy_count", "restore_input_count",
        "resolved_plan_count", "restored_count", "total_source_count",
        "callable_valid_count", "config_bound_count", "canonical_unique_count",
        "unresolved_count", "active_entry_count", "protected_change_count", "next_stage",
    ):
        print(f"{key.upper()}={status[key]}")
    print("UNRESOLVED=" + json.dumps(unresolved, ensure_ascii=False))
    print("RESTORE_MATRIX=" + status["restore_matrix_path"])
    print("VERIFICATION=" + status["verification_path"])
    print("RC=" + str(0 if state == "PASS" else 2))
    return 0 if state == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
