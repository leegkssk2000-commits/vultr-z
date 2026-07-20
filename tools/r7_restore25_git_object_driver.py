#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

MODULE_PATH = Path(__file__).with_name("r7_restore25_canonical_source_recovery.py")
spec = importlib.util.spec_from_file_location("restore25_core", MODULE_PATH)
if not spec or not spec.loader:
    raise RuntimeError("RESTORE25_CORE_IMPORT_SPEC_INVALID")
restore25 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(restore25)


def _target_sha(argv: list[str]) -> str:
    try:
        index = argv.index("--target-sha")
        value = argv[index + 1].strip()
    except (ValueError, IndexError):
        return ""
    return value


TARGET_SHA = _target_sha(sys.argv)


def safe_repo_path(value: str) -> str | None:
    raw = value.strip().replace("\\", "/")
    if not raw or "\x00" in raw or raw.startswith("/"):
        return None
    # Reject traversal before stripping an optional leading './'. Using
    # lstrip('./') would incorrectly turn '../../etc/passwd' into 'etc/passwd'.
    if any(segment == ".." for segment in raw.split("/")):
        return None
    while raw.startswith("./"):
        raw = raw[2:]
    if not raw or raw.startswith("/"):
        return None
    parts = Path(raw).parts
    if any(part in {"", ".", ".."} for part in parts):
        return None
    return Path(*parts).as_posix()


def git_output(root: Path, args: list[str], timeout: int = 60) -> str:
    try:
        result = subprocess.run(
            args,
            cwd=root,
            capture_output=True,
            timeout=timeout,
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.decode("utf-8", errors="replace")


def git_blob_source(root: Path, revision: str, repo_path: str) -> str:
    path = safe_repo_path(repo_path)
    revision = revision.strip()
    if not path or not revision:
        return ""
    return git_output(root, ["git", "show", f"{revision}:{path}"], 45)


def path_revisions(root: Path, repo_path: str, target_sha: str) -> list[str]:
    path = safe_repo_path(repo_path)
    if not path:
        return []
    revisions: list[str] = []
    if target_sha:
        revisions.append(target_sha)
    history = git_output(root, ["git", "log", "--all", "--format=%H", "--", path], 120)
    revisions.extend(line.strip() for line in history.splitlines() if line.strip())
    return list(dict.fromkeys(revisions))[:200]


def artifact_rows_from_git(
    root: Path,
    entry: dict[str, Any],
    target_sha: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    reasons: list[str] = []
    for evidence in entry.get("artifact_matches", []):
        if not isinstance(evidence, dict) or not evidence.get("path"):
            continue
        repo_path = safe_repo_path(str(evidence["path"]))
        if not repo_path:
            reasons.append("ARTIFACT_PATH_INVALID")
            continue

        working = root / repo_path
        candidates: list[tuple[str, str, str]] = []
        if working.is_file():
            candidates.append(("WORKTREE", "", working.read_text(encoding="utf-8", errors="replace")))
        for revision in path_revisions(root, repo_path, target_sha):
            source = git_blob_source(root, revision, repo_path)
            if source:
                candidates.append(("GIT_OBJECT", revision, source))

        if not candidates:
            reasons.append(f"ARTIFACT_GIT_OBJECT_NOT_FOUND:{repo_path}")
            continue
        for origin, revision, source in candidates:
            ast_sha = restore25.module_ast_sha(source, f"{revision}:{repo_path}" if revision else repo_path)
            if not ast_sha:
                reasons.append(f"ARTIFACT_SYNTAX_INVALID:{repo_path}:{revision or origin}")
                continue
            rows.append({
                **evidence,
                "path": repo_path,
                "source": source,
                "source_sha256": restore25.sha256_bytes(source.encode()),
                "module_ast_sha256": ast_sha,
                "materialized_from": origin,
                "materialized_revision": revision or None,
            })

    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (str(row["source_sha256"]), str(row["module_ast_sha256"]))
        current = unique.get(key)
        if current is None or row.get("materialized_from") == "GIT_OBJECT":
            unique[key] = row
    return list(unique.values()), reasons


def corrected_select_source(
    root: Path,
    strategy_id: str,
    entry: dict[str, Any],
    allowed: list[str],
    baseline_roots: list[str],
    default_prefix: str,
) -> tuple[dict[str, Any] | None, list[str]]:
    reasons: list[str] = []

    # Canonical production history is collected first. Artifact files are then
    # materialized from the requested target SHA or earlier Git objects; the
    # live worktree is only an optional fallback.
    history = restore25.historical_rows(root, strategy_id, allowed)
    artifacts, artifact_reasons = artifact_rows_from_git(root, entry, TARGET_SHA)
    reasons.extend(artifact_reasons)

    selected: dict[str, Any] | None = None
    decision = ""
    history_asts = {str(row.get("module_ast_sha256")) for row in history if row.get("module_ast_sha256")}
    artifact_asts = {str(row.get("module_ast_sha256")) for row in artifacts if row.get("module_ast_sha256")}
    matching_history = [row for row in history if row.get("module_ast_sha256") in artifact_asts]
    matching_history_asts = {str(row.get("module_ast_sha256")) for row in matching_history}

    if len(matching_history_asts) == 1:
        selected = matching_history[0]
        decision = "HISTORICAL_GIT_BLOB_MATCHES_ARTIFACT_AST"
    elif len(artifact_asts) == 1 and artifacts:
        selected = {
            **artifacts[0],
            "path": f"{default_prefix.rstrip('/')}/{strategy_id}.py",
            "blob_sha": None,
        }
        decision = "TARGET_SHA_GIT_OBJECT_ARTIFACT_AST_IDENTICAL"
    elif not artifacts and len(history_asts) == 1 and history:
        selected = history[0]
        decision = "UNIQUE_HISTORICAL_GIT_AST_WITHOUT_ARTIFACT_FILE"
    elif artifacts:
        counts = restore25.baseline_hits(
            root,
            baseline_roots,
            [str(row["source_sha256"]) for row in artifacts],
        )
        winners = [row for row in artifacts if counts.get(str(row["source_sha256"]), 0) > 0]
        winner_hashes = {str(row["source_sha256"]) for row in winners}
        if len(winner_hashes) == 1 and winners:
            selected = {
                **winners[0],
                "path": f"{default_prefix.rstrip('/')}/{strategy_id}.py",
                "blob_sha": None,
            }
            decision = "UNIQUE_BASELINE_SHA_MATCH"
        else:
            reasons.append("ARTIFACTS_DIVERGE_WITHOUT_UNIQUE_BASELINE_MATCH")
    elif len(history_asts) > 1:
        reasons.append("HISTORICAL_VARIANTS_WITHOUT_ARTIFACT_DISCRIMINATOR")
    else:
        reasons.append("NO_GIT_HISTORY_OR_ARTIFACT_OBJECT")

    if not selected:
        return None, list(dict.fromkeys(reasons))

    source = str(selected.get("source") or "")
    if not source:
        return None, list(dict.fromkeys(reasons + ["SELECTED_SOURCE_EMPTY"]))
    callable_evidence = artifacts if artifacts else [
        row for row in entry.get("artifact_matches", []) if isinstance(row, dict)
    ]
    callable_name = restore25.choose_callable(source, str(selected.get("path") or strategy_id), callable_evidence)
    if not callable_name:
        return None, list(dict.fromkeys(reasons + ["CALLABLE_NOT_UNIQUE"]))

    destination = str(selected.get("path") or "")
    if not restore25.is_true_source(destination, allowed):
        destination = f"{default_prefix.rstrip('/')}/{strategy_id}.py"
    return {
        "strategy_id": strategy_id,
        "destination_path": destination,
        "callable": callable_name,
        "source": source,
        "source_sha256": restore25.sha256_bytes(source.encode()),
        "module_ast_sha256": restore25.module_ast_sha(source, destination),
        "origin_commit": selected.get("commit") or selected.get("materialized_revision"),
        "origin_path": selected.get("path"),
        "origin_blob_sha": selected.get("blob_sha"),
        "decision_reason": decision,
        "artifact_paths": sorted({str(row.get("path")) for row in artifacts if row.get("path")}),
        "artifact_source_sha256": sorted({str(row["source_sha256"]) for row in artifacts}),
        "artifact_materialization": sorted({
            f"{row.get('materialized_from')}:{row.get('materialized_revision') or 'WORKTREE'}"
            for row in artifacts
        }),
    }, list(dict.fromkeys(reasons))


def main() -> int:
    if not TARGET_SHA:
        print('BLOCKERS=["MISSING_TARGET_SHA_FOR_GIT_OBJECT_RESOLVER"]')
        return 2
    restore25.select_source = corrected_select_source
    return int(restore25.main())


if __name__ == "__main__":
    raise SystemExit(main())
