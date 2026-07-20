#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import py_compile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent


def import_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if not spec or not spec.loader:
        raise RuntimeError(f"IMPORT_SPEC_INVALID:{name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


driver = import_module("restore25_git_driver", HERE / "r7_restore25_git_object_driver.py")
core = driver.restore25


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def exact_path_source(root: Path, repo_path: str, callable_name: str, expected_blob: str | None, target_sha: str) -> tuple[str | None, str | None]:
    path = driver.safe_repo_path(repo_path)
    if not path or not core.is_true_source(path, [
        "backend/strategies/", "backend/strategy/", "backend/strategy25/",
        "services/strategies/", "services/strategy/", "services/strategy25/",
    ]):
        return None, "DIRECT_PATH_INVALID"

    candidates: list[tuple[str, str, str | None]] = []
    for revision in driver.path_revisions(root, path, target_sha):
        source = driver.git_blob_source(root, revision, path)
        if not source:
            continue
        blob = driver.git_output(root, ["git", "rev-parse", f"{revision}:{path}"], 30).strip() or None
        names = core.callable_names(source, f"{revision}:{path}")
        if callable_name not in names:
            continue
        candidates.append((source, revision, blob))

    if expected_blob:
        matches = [row for row in candidates if row[2] == expected_blob]
        if len(matches) == 1:
            return matches[0][0], None
        if len(matches) > 1:
            unique = {core.sha256_bytes(row[0].encode()) for row in matches}
            if len(unique) == 1:
                return matches[0][0], None

    unique_by_ast: dict[str, str] = {}
    for source, _revision, _blob in candidates:
        ast_sha = core.module_ast_sha(source, path)
        if ast_sha:
            unique_by_ast.setdefault(ast_sha, source)
    if len(unique_by_ast) == 1:
        return next(iter(unique_by_ast.values())), None
    if not candidates:
        return None, "DIRECT_GIT_OBJECT_NOT_FOUND"
    return None, "DIRECT_HISTORY_AMBIGUOUS"


def preflight_direct_engines(root: Path, contract: dict[str, Any], target_sha: str) -> tuple[list[Path], list[str]]:
    matrix = load_json(root / str(contract["prior_matrix_path"]))
    entries = [row for row in matrix.get("entries", []) if isinstance(row, dict)]
    direct = [row for row in entries if row.get("binding_mode") == "DIRECT_PROVEN"]
    errors: list[str] = []
    created: list[Path] = []
    if len(direct) != 2:
        return created, [f"DIRECT_ENTRY_COUNT_NOT_2:{len(direct)}"]

    for row in direct:
        strategy_id = str(row.get("strategy_id") or "")
        engine = row.get("canonical_engine") if isinstance(row.get("canonical_engine"), dict) else {}
        repo_path = str(engine.get("implementation_path") or "")
        callable_name = str(engine.get("callable") or "")
        expected_blob = str(engine.get("source_blob_sha") or "") or None
        safe_path = driver.safe_repo_path(repo_path)
        if not strategy_id or not safe_path or not callable_name:
            errors.append(f"DIRECT_ENGINE_METADATA_INVALID:{strategy_id or 'UNKNOWN'}")
            continue
        destination = root / safe_path
        if destination.is_file():
            source = destination.read_text(encoding="utf-8", errors="replace")
            if callable_name in core.callable_names(source, safe_path):
                continue
            errors.append(f"DIRECT_WORKTREE_CALLABLE_MISMATCH:{strategy_id}:{safe_path}")
            continue
        source, error = exact_path_source(root, safe_path, callable_name, expected_blob, target_sha)
        if not source:
            errors.append(f"{error}:{strategy_id}:{safe_path}")
            continue
        core.atomic_text(destination, source)
        created.append(destination)
        try:
            py_compile.compile(str(destination), doraise=True)
        except Exception as exc:
            errors.append(f"DIRECT_COMPILE_FAILED:{strategy_id}:{type(exc).__name__}:{exc}")
            break

    if errors:
        for path in reversed(created):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        created = []
    return created, errors


def print_status(root: Path, contract: dict[str, Any]) -> None:
    status = load_json(root / str(contract["status_path"]))
    verification = load_json(root / str(contract["verification_path"]))
    print("BLOCKERS=" + json.dumps(status.get("blockers", []), ensure_ascii=False))
    print("VERIFICATION_ERRORS=" + json.dumps(verification.get("errors", []), ensure_ascii=False))


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--contract", required=True)
    parser.add_argument("--target-sha", required=True)
    parser.add_argument("--apply", action="store_true")
    args, _ = parser.parse_known_args()

    root = Path(args.root).resolve()
    contract = load_json(Path(args.contract))
    created, errors = preflight_direct_engines(root, contract, args.target_sha)
    if errors:
        print("DIRECT_PREFLIGHT_ERRORS=" + json.dumps(errors, ensure_ascii=False))
        return 2

    rc = int(driver.main())
    print_status(root, contract)
    if rc != 0:
        for path in reversed(created):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
