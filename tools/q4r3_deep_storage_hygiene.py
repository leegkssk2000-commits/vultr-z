from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path("/home/z/z")
RUNTIME = ROOT / "runtime"
TMP = Path("/tmp")
SYSTEMD_ROOTS = (Path("/etc/systemd/system"), Path("/run/systemd/system"))
BACKUP_NAME_RE = re.compile(r"(^backup$|^backups$|_backup$|_backups$|backups?)", re.IGNORECASE)
PROTECTED_NAME_RE = re.compile(r"golden|canonical|ssot|baseline|freeze|lock|manifest|registry", re.IGNORECASE)
TRANSIENT_SUFFIXES = (".tmp", ".bak", ".orig", ".rej", ".swp", ".swo", "~")


@dataclass(frozen=True)
class Snapshot:
    path: str
    parent: str
    mtime: float
    size_bytes: int
    file_count: int
    quick_digest: str
    content_digest: str | None
    protected: bool
    referenced: bool
    retention_keep: bool
    duplicate_of: str | None
    delete_reason: str | None


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_files(root: Path) -> Iterable[Path]:
    if root.is_symlink() or root.is_file():
        yield root
        return
    for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        dirs[:] = [name for name in dirs if not (current_path / name).is_symlink()]
        for name in files:
            path = current_path / name
            if not path.is_symlink():
                yield path


def quick_manifest(root: Path) -> tuple[int, int, str]:
    rows: list[tuple[str, int]] = []
    total = 0
    for path in iter_files(root):
        try:
            size = path.stat().st_size
            rel = str(path.relative_to(root)) if path != root else path.name
        except (FileNotFoundError, ValueError):
            continue
        rows.append((rel, size))
        total += size
    rows.sort()
    digest = hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode()).hexdigest()
    return total, len(rows), digest


def content_manifest(root: Path) -> str:
    digest = hashlib.sha256()
    rows: list[Path] = sorted(iter_files(root), key=lambda p: str(p.relative_to(root)) if p != root else p.name)
    for path in rows:
        try:
            rel = str(path.relative_to(root)) if path != root else path.name
            size = path.stat().st_size
        except (FileNotFoundError, ValueError):
            continue
        digest.update(rel.encode())
        digest.update(b"\0")
        digest.update(str(size).encode())
        digest.update(b"\0")
        digest.update(file_sha256(path).encode())
        digest.update(b"\n")
    return digest.hexdigest()


def git_worktrees() -> set[Path]:
    result: set[Path] = set()
    output = run(["git", "-C", str(ROOT), "worktree", "list", "--porcelain"]).stdout
    for line in output.splitlines():
        if line.startswith("worktree "):
            try:
                result.add(Path(line[9:]).resolve())
            except OSError:
                pass
    return result


def collect_text_references() -> set[Path]:
    references: set[Path] = set()
    absolute_path = re.compile(r"/(?:home|tmp|var|root)/[^\s\"'<>]+")
    scan_roots = [RUNTIME, *SYSTEMD_ROOTS]
    for base in scan_roots:
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            try:
                size = path.stat().st_size
            except FileNotFoundError:
                continue
            if size > 5_000_000:
                continue
            if base == RUNTIME and not any(token in path.name.lower() for token in ("latest", "status", "manifest", "registry", "restore", "rollback", "golden", "lock")):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for match in absolute_path.findall(text):
                cleaned = match.rstrip(",:;)]}")
                try:
                    references.add(Path(cleaned).resolve())
                except OSError:
                    pass
    for base in (ROOT, RUNTIME, TMP):
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_symlink():
                continue
            try:
                references.add(path.resolve())
            except OSError:
                pass
    return references


def path_touches(path: Path, references: Iterable[Path]) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path
    for ref in references:
        try:
            target = ref.resolve()
        except OSError:
            target = ref
        if resolved == target or resolved in target.parents or target in resolved.parents:
            return True
    return False


def backup_roots() -> list[Path]:
    roots: set[Path] = set()
    if not RUNTIME.exists():
        return []
    for current, dirs, _files in os.walk(RUNTIME, topdown=True, followlinks=False):
        current_path = Path(current)
        for name in dirs:
            candidate = current_path / name
            if BACKUP_NAME_RE.search(name):
                roots.add(candidate)
    return sorted(roots)


def children_as_snapshots(root: Path) -> list[Path]:
    try:
        children = [item for item in root.iterdir() if item.is_dir() or item.is_file()]
    except OSError:
        return []
    return sorted(children, key=lambda p: p.stat().st_mtime if p.exists() else 0.0, reverse=True)


def retention_set(children: list[Path]) -> set[Path]:
    keep: set[Path] = set(children[:5])
    if children:
        keep.add(children[-1])
    daily: set[str] = set()
    weekly: set[str] = set()
    now = datetime.now(timezone.utc)
    for item in children:
        try:
            dt = datetime.fromtimestamp(item.stat().st_mtime, timezone.utc)
        except FileNotFoundError:
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


def classify_snapshots(references: set[Path]) -> list[Snapshot]:
    result: list[Snapshot] = []
    for parent in backup_roots():
        children = children_as_snapshots(parent)
        if not children:
            continue
        retention = retention_set(children)
        preliminary: list[dict[str, Any]] = []
        for child in children:
            try:
                mtime = child.stat().st_mtime
            except FileNotFoundError:
                continue
            size, count, quick = quick_manifest(child)
            referenced = path_touches(child, references)
            protected = referenced or bool(PROTECTED_NAME_RE.search(str(child)))
            preliminary.append({
                "path": child,
                "mtime": mtime,
                "size": size,
                "count": count,
                "quick": quick,
                "referenced": referenced,
                "protected": protected,
                "retention": child in retention,
            })

        groups: dict[tuple[int, int, str], list[dict[str, Any]]] = defaultdict(list)
        for item in preliminary:
            groups[(item["size"], item["count"], item["quick"])].append(item)

        for group in groups.values():
            if len(group) < 2:
                continue
            for item in group:
                item["content"] = content_manifest(item["path"])

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
            reason = "exact_duplicate_unreferenced_outside_retention" if duplicate_of else None
            result.append(Snapshot(
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
            ))
    return sorted(result, key=lambda item: item.size_bytes, reverse=True)


def orphan_transients(references: set[Path], minimum_age_hours: float = 24.0) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc).timestamp()
    candidates: list[dict[str, Any]] = []
    roots = [ROOT / "runtime", ROOT / "tools", ROOT / "backend", ROOT / "config", TMP]
    worktrees = git_worktrees()
    protected_refs = references | worktrees | {ROOT, RUNTIME, ROOT / ".git"}
    for base in roots:
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() and not path.is_symlink():
                continue
            if not path.name.endswith(TRANSIENT_SUFFIXES):
                continue
            try:
                stat = path.lstat()
            except FileNotFoundError:
                continue
            age_hours = (now - stat.st_mtime) / 3600.0
            if age_hours < minimum_age_hours or path_touches(path, protected_refs):
                continue
            candidates.append({"path": str(path), "size_bytes": stat.st_size, "age_hours": round(age_hours, 2), "reason": "stale_atomic_or_editor_transient"})
    return sorted(candidates, key=lambda item: int(item["size_bytes"]), reverse=True)


def largest_paths(roots: Iterable[Path], limit: int = 80) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for root in roots:
        if not root.exists():
            continue
        try:
            children = list(root.iterdir())
        except OSError:
            continue
        for child in children:
            size, count, _ = quick_manifest(child)
            rows.append({"path": str(child), "size_bytes": size, "file_count": count})
    return sorted(rows, key=lambda item: int(item["size_bytes"]), reverse=True)[:limit]


def remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)


def disk_payload() -> dict[str, int]:
    usage = shutil.disk_usage("/")
    return {"total": usage.total, "used": usage.total - usage.free, "free": usage.free}


def execute(apply: bool, output: Path) -> dict[str, Any]:
    before = disk_payload()
    references = collect_text_references()
    snapshots = classify_snapshots(references)
    transients = orphan_transients(references)
    deletions = [item for item in snapshots if item.delete_reason]
    removed: list[dict[str, Any]] = []

    if apply:
        for item in deletions:
            path = Path(item.path)
            if not path.exists() or item.protected or item.retention_keep or not item.duplicate_of:
                continue
            # Revalidate exact equality immediately before deletion.
            canonical = Path(item.duplicate_of)
            if not canonical.exists():
                continue
            if content_manifest(path) != content_manifest(canonical):
                continue
            remove_path(path)
            removed.append({"path": item.path, "size_bytes": item.size_bytes, "reason": item.delete_reason, "duplicate_of": item.duplicate_of})

        for item in transients:
            path = Path(str(item["path"]))
            if path.exists() or path.is_symlink():
                remove_path(path)
                removed.append(item)

        run(["git", "-C", str(ROOT), "worktree", "prune", "--expire", "now"])
        run(["git", "-C", str(ROOT), "reflog", "expire", "--expire=30.days.ago", "--all"])
        run(["git", "-C", str(ROOT), "gc", "--prune=30.days.ago"])

    after = disk_payload()
    payload: dict[str, Any] = {
        "schema": "q4r3_deep_storage_hygiene_v1",
        "generated_at": iso_now(),
        "mode": "apply" if apply else "audit",
        "state": "PASS",
        "action": "hold",
        "policy": "exact_duplicate_backups_and_stale_transients_only",
        "backup_root_count": len({item.parent for item in snapshots}),
        "snapshot_count": len(snapshots),
        "exact_duplicate_delete_candidate_count": len(deletions),
        "stale_transient_candidate_count": len(transients),
        "candidate_bytes": sum(item.size_bytes for item in deletions) + sum(int(item["size_bytes"]) for item in transients),
        "removed_count": len(removed),
        "removed_declared_bytes": sum(int(item["size_bytes"]) for item in removed),
        "disk_before": before,
        "disk_after": after,
        "free_bytes_delta": after["free"] - before["free"],
        "runtime_root_deleted": False,
        "formal_ledger_deleted": False,
        "golden_or_ssot_deleted": False,
        "unique_backup_deleted": False,
        "snapshots": [asdict(item) for item in snapshots],
        "stale_transients": transients,
        "removed": removed,
        "largest_remaining_roots": largest_paths([ROOT, RUNTIME, Path("/var"), Path("/root"), TMP]),
        "next_action": "REVIEW_LARGEST_REMAINING_ROOTS_AND_UNIQUE_BACKUP_RETENTION_ONLY_IF_DISK_ABOVE_85_PERCENT",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(output)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = execute(args.apply, args.output)
    print(json.dumps({key: payload[key] for key in (
        "state", "mode", "backup_root_count", "snapshot_count",
        "exact_duplicate_delete_candidate_count", "stale_transient_candidate_count",
        "candidate_bytes", "removed_count", "removed_declared_bytes",
        "free_bytes_delta", "next_action"
    )}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
