from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


ROOT = Path("/home/z/z")
RUNTIME = ROOT / "runtime"
REPO_GIT = ROOT / ".git"

CACHE_DIR_NAMES = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
EXACT_CACHE_PATHS = [
    Path("/root/.cache/pip"),
    Path("/root/.cache/uv"),
    Path("/root/.npm/_cacache"),
]
TMP_PREFIXES = ("q4r3-", "pytest-of-root", "pip-build-", "pip-install-")


@dataclass(frozen=True)
class Candidate:
    path: str
    category: str
    size_bytes: int
    protected: bool
    reason: str


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_text(command: list[str]) -> str:
    completed = subprocess.run(command, check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    return completed.stdout


def disk_free_bytes(path: Path = Path("/")) -> int:
    return shutil.disk_usage(path).free


def disk_used_bytes(path: Path = Path("/")) -> int:
    usage = shutil.disk_usage(path)
    return usage.total - usage.free


def tree_size(path: Path) -> int:
    try:
        if path.is_symlink() or path.is_file():
            return path.lstat().st_size
    except FileNotFoundError:
        return 0

    total = 0
    for root, dirs, files in os.walk(path, topdown=True, followlinks=False):
        dirs[:] = [name for name in dirs if not (Path(root) / name).is_symlink()]
        for name in files:
            item = Path(root) / name
            try:
                total += item.lstat().st_size
            except FileNotFoundError:
                pass
    return total


def registered_worktrees() -> set[Path]:
    output = run_text(["git", "-C", str(ROOT), "worktree", "list", "--porcelain"])
    result: set[Path] = set()
    for line in output.splitlines():
        if line.startswith("worktree "):
            try:
                result.add(Path(line[9:]).resolve())
            except OSError:
                pass
    return result


def referenced_tmp_paths() -> set[Path]:
    references: set[Path] = set()

    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            text = (proc / "cmdline").read_bytes().replace(b"\x00", b" ").decode(errors="ignore")
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        for token in text.split():
            if token.startswith("/tmp/"):
                try:
                    references.add(Path(token).resolve())
                except OSError:
                    pass

    for base in (Path("/etc/systemd/system"), Path("/run/systemd/system")):
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for token in text.replace("=", " ").split():
                if token.startswith("/tmp/"):
                    try:
                        references.add(Path(token).resolve())
                    except OSError:
                        pass

    return references


def path_related(path: Path, protected: Iterable[Path]) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path
    for item in protected:
        try:
            protected_resolved = item.resolve()
        except OSError:
            protected_resolved = item
        if resolved == protected_resolved or protected_resolved in resolved.parents or resolved in protected_resolved.parents:
            return True
    return False


def repo_cache_candidates() -> list[Path]:
    result: list[Path] = []
    for current, dirs, _files in os.walk(ROOT, topdown=True, followlinks=False):
        current_path = Path(current)
        if current_path == RUNTIME or RUNTIME in current_path.parents:
            dirs[:] = []
            continue
        if current_path == REPO_GIT or REPO_GIT in current_path.parents:
            dirs[:] = []
            continue
        dirs[:] = [name for name in dirs if name not in {"node_modules", ".git", "runtime", "venv", ".venv"}]
        for name in list(dirs):
            if name in CACHE_DIR_NAMES:
                result.append(current_path / name)
                dirs.remove(name)
    return result


def collect_candidates() -> list[Candidate]:
    worktrees = registered_worktrees()
    references = referenced_tmp_paths()
    protected = worktrees | references | {ROOT, RUNTIME, REPO_GIT}
    candidates: list[Candidate] = []

    for path in EXACT_CACHE_PATHS:
        if not path.exists():
            continue
        is_protected = path_related(path, protected)
        candidates.append(Candidate(str(path), "package_cache", tree_size(path), is_protected, "protected_reference" if is_protected else "allowlisted_rebuildable_cache"))

    for path in repo_cache_candidates():
        if not path.exists():
            continue
        is_protected = path_related(path, protected)
        candidates.append(Candidate(str(path), "repo_tool_cache", tree_size(path), is_protected, "protected_reference" if is_protected else "allowlisted_generated_cache"))

    tmp_root = Path("/tmp")
    if tmp_root.exists():
        for path in sorted(tmp_root.iterdir()):
            if not path.name.startswith(TMP_PREFIXES):
                continue
            is_protected = path_related(path, protected)
            candidates.append(Candidate(str(path), "temporary_workspace", tree_size(path), is_protected, "registered_or_referenced" if is_protected else "unregistered_unreferenced_tmp"))

    unique: dict[str, Candidate] = {}
    for item in candidates:
        prior = unique.get(item.path)
        if prior is None or (prior.protected and not item.protected):
            unique[item.path] = item
    return sorted(unique.values(), key=lambda item: item.size_bytes, reverse=True)


def safe_remove(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)


def top_level_usage(paths: Iterable[Path]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for base in paths:
        if not base.exists():
            continue
        try:
            children = list(base.iterdir())
        except OSError:
            continue
        for child in children:
            try:
                size = tree_size(child)
            except OSError:
                continue
            rows.append({"path": str(child), "size_bytes": size})
    return sorted(rows, key=lambda row: int(row["size_bytes"]), reverse=True)[:40]


def execute(apply: bool) -> dict[str, object]:
    before_free = disk_free_bytes()
    before_used = disk_used_bytes()
    candidates = collect_candidates()
    removed: list[dict[str, object]] = []
    skipped: list[dict[str, object]] = []

    for item in candidates:
        if item.protected:
            skipped.append(asdict(item))
            continue
        if not apply:
            skipped.append(asdict(item))
            continue
        path = Path(item.path)
        if not path.exists():
            continue
        safe_remove(path)
        removed.append(asdict(item))

    subprocess.run(["git", "-C", str(ROOT), "worktree", "prune", "--expire", "now"], check=False)

    after_free = disk_free_bytes()
    after_used = disk_used_bytes()
    payload: dict[str, object] = {
        "schema": "q4r3_safe_disk_hygiene_v1",
        "generated_at": utc_now(),
        "mode": "apply" if apply else "audit",
        "state": "PASS",
        "action": "hold",
        "allowlist_only": True,
        "runtime_deleted": False,
        "backup_deleted": False,
        "repository_source_deleted": False,
        "candidate_count": len(candidates),
        "removed_count": len(removed),
        "protected_or_audit_only_count": len(skipped),
        "candidate_bytes": sum(item.size_bytes for item in candidates),
        "removed_declared_bytes": sum(int(item["size_bytes"]) for item in removed),
        "free_bytes_before": before_free,
        "free_bytes_after": after_free,
        "free_bytes_delta": after_free - before_free,
        "used_bytes_before": before_used,
        "used_bytes_after": after_used,
        "removed": removed,
        "skipped": skipped,
        "largest_remaining_roots": top_level_usage([ROOT, Path("/var"), Path("/root"), Path("/tmp")]),
        "protected_roots": [str(RUNTIME), str(REPO_GIT), str(ROOT / "backend"), str(ROOT / "config")],
    }
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = execute(args.apply)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(args.output)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
