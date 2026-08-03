from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "ZEL_VWAP_SOURCE_PROVENANCE_V1"
SCHEMA = "zel.vwap_source_provenance.v1"
TARGET_NAME = "vwap_revert.py"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_sha(value: Any) -> str:
    return sha256_bytes(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())


def classify(path: Path) -> str:
    lowered = str(path).lower()
    if any(token in lowered for token in ("backup", ".bak", "quarantine", "archive", "snapshot", "rollback", "golden")):
        return "BACKUP_OR_SNAPSHOT"
    if any(token in lowered for token in ("imported_zips", "runtime_pkg", "/tmp/", "runtime_results")):
        return "IMPORTED_OR_RESULT_COPY"
    if str(path) == "/home/z/z/backend/strategies/vwap_revert.py":
        return "ACTIVE_CANONICAL_PATH"
    return "OTHER_COPY"


def inventory(root: Path) -> list[dict[str, Any]]:
    skip = {".git", ".venv", "venv", "node_modules", "__pycache__", "proc", "sys", "dev"}
    rows: list[dict[str, Any]] = []
    for current, dirs, files in os.walk(root):
        dirs[:] = [name for name in dirs if name not in skip]
        if TARGET_NAME not in files:
            continue
        path = (Path(current) / TARGET_NAME).resolve()
        try:
            stat = path.stat()
            rows.append({
                "path": str(path),
                "class": classify(path),
                "sha256": sha256_path(path),
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
            })
        except OSError as exc:
            rows.append({"path": str(path), "class": classify(path), "error": type(exc).__name__})
    return sorted(rows, key=lambda row: (row.get("class", ""), row.get("path", "")))


def command(args: list[str], cwd: Path) -> dict[str, Any]:
    completed = subprocess.run(args, cwd=cwd, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return {
        "returncode": completed.returncode,
        "stdout": completed.stdout.decode(errors="replace").strip(),
        "stderr": completed.stderr.decode(errors="replace").strip(),
    }


def git_provenance(root: Path, relative: str) -> dict[str, Any]:
    repo = command(["git", "rev-parse", "--show-toplevel"], root)
    if repo["returncode"] != 0:
        return {"repository_present": False, "rev_parse": repo}
    top = Path(repo["stdout"])
    head = command(["git", "rev-parse", "HEAD"], top)
    tracked = command(["git", "ls-files", "--error-unmatch", relative], top)
    status = command(["git", "status", "--porcelain=v1", "--", relative], top)
    log = command(["git", "log", "-n", "20", "--format=%H%x09%aI%x09%s", "--follow", "--", relative], top)
    show = command(["git", "show", f"HEAD:{relative}"], top)
    head_content_sha = sha256_bytes(show["stdout"].encode()) if show["returncode"] == 0 else None
    return {
        "repository_present": True,
        "repo_root": str(top),
        "head": head["stdout"] if head["returncode"] == 0 else None,
        "tracked": tracked["returncode"] == 0,
        "worktree_status": status["stdout"],
        "head_content_sha256": head_content_sha,
        "recent_history": log["stdout"].splitlines() if log["returncode"] == 0 else [],
        "head_show_error": show["stderr"] if show["returncode"] != 0 else None,
    }


def run(root: Path, expected_sha: str, active_sha: str) -> dict[str, Any]:
    copies = inventory(root)
    expected_matches = [row for row in copies if row.get("sha256") == expected_sha]
    active_matches = [row for row in copies if row.get("sha256") == active_sha]
    git = git_provenance(root, "backend/strategies/vwap_revert.py")
    checks = {
        "active_path_present": any(row.get("class") == "ACTIVE_CANONICAL_PATH" for row in copies),
        "expected_sha_copy_found": bool(expected_matches),
        "git_repo_present": git.get("repository_present") is True,
        "canonical_not_mutated_by_audit": True,
        "runtime_not_mutated_by_audit": True,
    }
    if expected_matches:
        cause = "EXPECTED_TERMINAL_SOURCE_COPY_FOUND"
        next_step = "VERIFY_EXPECTED_COPY_LINEAGE_THEN_ATOMIC_RESTORE_OR_NEW_EPOCH"
    elif git.get("head_content_sha256") == expected_sha:
        cause = "WORKTREE_DRIFT_FROM_GIT_HEAD_EXPECTED_SOURCE"
        next_step = "RESTORE_TRACKED_FILE_FROM_HEAD_AFTER_ROLLBACK_REHEARSAL"
    elif git.get("head_content_sha256") == active_sha:
        cause = "GIT_HEAD_CONTAINS_NEW_SOURCE_TERMINAL_MANIFEST_IS_OLD_EPOCH"
        next_step = "KEEP_SOURCE_AND_CREATE_NEW_IMMUTABLE_EPOCH_MANIFEST"
    else:
        cause = "EXPECTED_SOURCE_NOT_FOUND_AND_GIT_PROVENANCE_AMBIGUOUS"
        next_step = "QUARANTINE_AND_REQUIRE_MANUAL_PROVENANCE_RESOLUTION"
    receipt = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": "PASS_VWAP_SOURCE_PROVENANCE_INVENTORY",
        "expected_terminal_sha256": expected_sha,
        "active_observed_sha256": active_sha,
        "copy_count": len(copies),
        "expected_match_count": len(expected_matches),
        "active_match_count": len(active_matches),
        "expected_matches": expected_matches,
        "active_matches": active_matches,
        "copies": copies,
        "git": git,
        "checks": checks,
        "cause": cause,
        "next": next_step,
        "raw_source_published": False,
        "canonical_mutated": False,
        "registry_mutated": False,
        "runtime_mutated": False,
        "formal_ledger_mutated": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--active-sha", required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--stdout", action="store_true")
    args = parser.parse_args()
    receipt = run(args.root.resolve(), args.expected_sha, args.active_sha)
    encoded = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(encoded, encoding="utf-8")
    if args.stdout or not args.out:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
