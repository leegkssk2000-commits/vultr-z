from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


MODULE_PATH = Path(__file__).with_name("q4r3_deep_storage_hygiene.py")
SPEC = importlib.util.spec_from_file_location("q4r3_deep_storage_hygiene_base", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise SystemExit("DEEP_STORAGE_BASE_IMPORT_SPEC_FAILED")
BASE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BASE
SPEC.loader.exec_module(BASE)

PATH_ERRORS = (OSError, RuntimeError, ValueError)


def safe_resolve(value: object) -> Path | None:
    text = str(value)
    if not text or "\x00" in text:
        return None
    if any(ord(char) < 32 for char in text):
        return None
    try:
        return Path(text).resolve(strict=False)
    except PATH_ERRORS:
        return None


def safe_walk(root: Path) -> Iterable[tuple[Path, list[str], list[str]]]:
    try:
        if not root.exists():
            return
    except PATH_ERRORS:
        return

    def onerror(_error: OSError) -> None:
        return

    for current, dirs, files in os.walk(
        root,
        topdown=True,
        followlinks=False,
        onerror=onerror,
    ):
        current_path = Path(current)
        kept_dirs: list[str] = []
        for name in dirs:
            candidate = current_path / name
            try:
                if candidate.is_symlink():
                    continue
            except PATH_ERRORS:
                continue
            kept_dirs.append(name)
        dirs[:] = kept_dirs
        yield current_path, dirs, files


def safe_iter_files(root: Path) -> Iterable[Path]:
    try:
        if root.is_symlink() or root.is_file():
            yield root
            return
    except PATH_ERRORS:
        return

    for current, _dirs, files in safe_walk(root):
        for name in files:
            path = current / name
            try:
                if path.is_symlink():
                    continue
            except PATH_ERRORS:
                continue
            yield path


def safe_file_sha256(path: Path) -> str | None:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
                digest.update(chunk)
    except PATH_ERRORS:
        return None
    return digest.hexdigest()


def safe_quick_manifest(root: Path) -> tuple[int, int, str]:
    rows: list[tuple[str, int]] = []
    total = 0
    for path in safe_iter_files(root):
        try:
            size = path.stat().st_size
            rel = str(path.relative_to(root)) if path != root else path.name
        except PATH_ERRORS:
            continue
        rows.append((rel, size))
        total += size
    rows.sort()
    digest = hashlib.sha256(
        json.dumps(rows, separators=(",", ":")).encode()
    ).hexdigest()
    return total, len(rows), digest


def safe_content_manifest(root: Path) -> str:
    digest = hashlib.sha256()
    rows: list[tuple[str, Path]] = []
    for path in safe_iter_files(root):
        try:
            rel = str(path.relative_to(root)) if path != root else path.name
        except PATH_ERRORS:
            continue
        rows.append((rel, path))
    rows.sort(key=lambda item: item[0])

    for rel, path in rows:
        try:
            size = path.stat().st_size
        except PATH_ERRORS:
            continue
        file_hash = safe_file_sha256(path)
        if file_hash is None:
            continue
        digest.update(rel.encode(errors="surrogateescape"))
        digest.update(b"\0")
        digest.update(str(size).encode())
        digest.update(b"\0")
        digest.update(file_hash.encode())
        digest.update(b"\n")
    return digest.hexdigest()


def safe_git_worktrees() -> set[Path]:
    result: set[Path] = set()
    output = BASE.run(
        ["git", "-C", str(BASE.ROOT), "worktree", "list", "--porcelain"]
    ).stdout
    for line in output.splitlines():
        if not line.startswith("worktree "):
            continue
        resolved = safe_resolve(line[9:])
        if resolved is not None:
            result.add(resolved)
    return result


def safe_path_touches(path: Path, references: Iterable[Path]) -> bool:
    resolved = safe_resolve(path)
    if resolved is None:
        return True
    for ref in references:
        target = safe_resolve(ref)
        if target is None:
            continue
        if (
            resolved == target
            or resolved in target.parents
            or target in resolved.parents
        ):
            return True
    return False


def safe_collect_text_references() -> set[Path]:
    references: set[Path] = set()
    absolute_path = re.compile(r"/(?:home|tmp|var|root)/[^\s\"'<>]+")
    runtime_tokens = (
        "latest",
        "status",
        "manifest",
        "registry",
        "restore",
        "rollback",
        "golden",
        "lock",
    )

    for base in [BASE.RUNTIME, *BASE.SYSTEMD_ROOTS]:
        for current, _dirs, files in safe_walk(base):
            for name in files:
                path = current / name
                try:
                    if path.is_symlink() or not path.is_file():
                        continue
                    size = path.stat().st_size
                except PATH_ERRORS:
                    continue
                if size > 5_000_000:
                    continue
                if base == BASE.RUNTIME and not any(
                    token in name.lower() for token in runtime_tokens
                ):
                    continue
                try:
                    text = path.read_text(encoding="utf-8", errors="ignore")
                except PATH_ERRORS:
                    continue
                for match in absolute_path.findall(text):
                    cleaned = match.rstrip(" ,:;)]}\r\n\t")
                    resolved = safe_resolve(cleaned)
                    if resolved is not None:
                        references.add(resolved)

    for base in (BASE.ROOT, BASE.RUNTIME, BASE.TMP):
        for current, dirs, files in safe_walk(base):
            for name in [*dirs, *files]:
                path = current / name
                try:
                    if not path.is_symlink():
                        continue
                except PATH_ERRORS:
                    continue
                resolved = safe_resolve(path)
                if resolved is not None:
                    references.add(resolved)

    return references


def safe_children_as_snapshots(root: Path) -> list[Path]:
    children: list[Path] = []
    try:
        for item in root.iterdir():
            try:
                if item.is_dir() or item.is_file():
                    item.stat()
                    children.append(item)
            except PATH_ERRORS:
                continue
    except PATH_ERRORS:
        return []

    def mtime(item: Path) -> float:
        try:
            return item.stat().st_mtime
        except PATH_ERRORS:
            return 0.0

    return sorted(children, key=mtime, reverse=True)


def safe_retention_set(children: list[Path]) -> set[Path]:
    keep: set[Path] = set(children[:5])
    if children:
        keep.add(children[-1])
    daily: set[str] = set()
    weekly: set[str] = set()
    now = datetime.now(timezone.utc)
    for item in children:
        try:
            dt = datetime.fromtimestamp(item.stat().st_mtime, timezone.utc)
        except PATH_ERRORS:
            keep.add(item)
            continue
        age_days = (now - dt).total_seconds() / 86400.0
        day_key = dt.strftime("%Y-%m-%d")
        week_key = dt.strftime("%G-W%V")
        if age_days <= 14 and day_key not in daily:
            keep.add(item)
            daily.add(day_key)
        if age_days <= 84 and week_key not in weekly:
            keep.add(item)
            weekly.add(week_key)
    return keep


def safe_classify_snapshots(references: set[Path]) -> list[Any]:
    result: list[Any] = []
    for parent in BASE.backup_roots():
        children = safe_children_as_snapshots(parent)
        if not children:
            continue
        retention = safe_retention_set(children)
        preliminary: list[dict[str, Any]] = []
        for child in children:
            try:
                mtime = child.stat().st_mtime
            except PATH_ERRORS:
                continue
            size, count, quick = safe_quick_manifest(child)
            referenced = safe_path_touches(child, references)
            protected = referenced or bool(BASE.PROTECTED_NAME_RE.search(str(child)))
            preliminary.append(
                {
                    "path": child,
                    "mtime": mtime,
                    "size": size,
                    "count": count,
                    "quick": quick,
                    "referenced": referenced,
                    "protected": protected,
                    "retention": child in retention,
                }
            )

        groups: dict[tuple[int, int, str], list[dict[str, Any]]] = defaultdict(list)
        for item in preliminary:
            groups[(item["size"], item["count"], item["quick"])].append(item)
        for group in groups.values():
            if len(group) < 2:
                continue
            for item in group:
                item["content"] = safe_content_manifest(item["path"])

        content_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in preliminary:
            if item.get("content"):
                content_groups[item["content"]].append(item)

        duplicate_map: dict[Path, Path] = {}
        for group in content_groups.values():
            if len(group) < 2:
                continue
            ordered = sorted(group, key=lambda item: item["mtime"], reverse=True)
            canonical = ordered[0]["path"]
            for item in ordered[1:]:
                if not item["protected"] and not item["retention"]:
                    duplicate_map[item["path"]] = canonical

        for item in preliminary:
            duplicate_of = duplicate_map.get(item["path"])
            reason = (
                "exact_duplicate_unreferenced_outside_retention"
                if duplicate_of
                else None
            )
            result.append(
                BASE.Snapshot(
                    path=str(item["path"]),
                    parent=str(parent),
                    mtime=float(item["mtime"]),
                    size_bytes=int(item["size"]),
                    file_count=int(item["count"]),
                    quick_digest=str(item["quick"]),
                    content_digest=item.get("content"),
                    protected=bool(item["protected"]),
                    referenced=bool(item["referenced"]),
                    retention_keep=bool(item["retention"]),
                    duplicate_of=str(duplicate_of) if duplicate_of else None,
                    delete_reason=reason,
                )
            )
    return sorted(result, key=lambda item: item.size_bytes, reverse=True)


def safe_orphan_transients(
    references: set[Path],
    minimum_age_hours: float = 24.0,
) -> list[dict[str, Any]]:
    now = BASE.datetime.now(BASE.timezone.utc).timestamp()
    candidates: list[dict[str, Any]] = []
    roots = [
        BASE.ROOT / "runtime",
        BASE.ROOT / "tools",
        BASE.ROOT / "backend",
        BASE.ROOT / "config",
        BASE.TMP,
    ]
    worktrees = safe_git_worktrees()
    protected_refs = references | worktrees | {
        BASE.ROOT,
        BASE.RUNTIME,
        BASE.ROOT / ".git",
    }

    for root in roots:
        for current, dirs, files in safe_walk(root):
            for name in [*dirs, *files]:
                path = current / name
                if not name.endswith(BASE.TRANSIENT_SUFFIXES):
                    continue
                try:
                    stat = path.lstat()
                except PATH_ERRORS:
                    continue
                age_hours = (now - stat.st_mtime) / 3600.0
                if age_hours < minimum_age_hours:
                    continue
                if safe_path_touches(path, protected_refs):
                    continue
                candidates.append(
                    {
                        "path": str(path),
                        "size_bytes": stat.st_size,
                        "age_hours": round(age_hours, 2),
                        "reason": "stale_atomic_or_editor_transient",
                    }
                )

    return sorted(
        candidates,
        key=lambda item: int(item["size_bytes"]),
        reverse=True,
    )


BASE.iter_files = safe_iter_files
BASE.file_sha256 = safe_file_sha256
BASE.quick_manifest = safe_quick_manifest
BASE.content_manifest = safe_content_manifest
BASE.git_worktrees = safe_git_worktrees
BASE.path_touches = safe_path_touches
BASE.collect_text_references = safe_collect_text_references
BASE.children_as_snapshots = safe_children_as_snapshots
BASE.retention_set = safe_retention_set
BASE.classify_snapshots = safe_classify_snapshots
BASE.orphan_transients = safe_orphan_transients


if __name__ == "__main__":
    raise SystemExit(BASE.main())
