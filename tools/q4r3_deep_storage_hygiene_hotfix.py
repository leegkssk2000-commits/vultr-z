from __future__ import annotations

import importlib.util
import os
import re
import sys
from pathlib import Path
from typing import Any, Iterable


MODULE_PATH = Path(__file__).with_name("q4r3_deep_storage_hygiene.py")
SPEC = importlib.util.spec_from_file_location("q4r3_deep_storage_hygiene_base", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise SystemExit("DEEP_STORAGE_BASE_IMPORT_SPEC_FAILED")
BASE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BASE
SPEC.loader.exec_module(BASE)


def safe_walk(root: Path) -> Iterable[tuple[Path, list[str], list[str]]]:
    if not root.exists():
        return
    def onerror(_error: OSError) -> None:
        return
    for current, dirs, files in os.walk(root, topdown=True, followlinks=False, onerror=onerror):
        current_path = Path(current)
        kept_dirs: list[str] = []
        for name in dirs:
            candidate = current_path / name
            try:
                if candidate.is_symlink():
                    continue
            except OSError:
                continue
            kept_dirs.append(name)
        dirs[:] = kept_dirs
        yield current_path, dirs, files


def safe_iter_files(root: Path) -> Iterable[Path]:
    try:
        if root.is_symlink() or root.is_file():
            yield root
            return
    except OSError:
        return
    for current, _dirs, files in safe_walk(root):
        for name in files:
            path = current / name
            try:
                if path.is_symlink():
                    continue
            except OSError:
                continue
            yield path


def safe_collect_text_references() -> set[Path]:
    references: set[Path] = set()
    absolute_path = re.compile(r"/(?:home|tmp|var|root)/[^\s\"'<>]+")
    runtime_tokens = ("latest", "status", "manifest", "registry", "restore", "rollback", "golden", "lock")

    for base in [BASE.RUNTIME, *BASE.SYSTEMD_ROOTS]:
        for current, _dirs, files in safe_walk(base):
            for name in files:
                path = current / name
                try:
                    if path.is_symlink() or not path.is_file():
                        continue
                    size = path.stat().st_size
                except OSError:
                    continue
                if size > 5_000_000:
                    continue
                if base == BASE.RUNTIME and not any(token in name.lower() for token in runtime_tokens):
                    continue
                try:
                    text = path.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                for match in absolute_path.findall(text):
                    cleaned = match.rstrip(",:;)]}")
                    try:
                        references.add(Path(cleaned).resolve(strict=False))
                    except OSError:
                        continue

    for base in (BASE.ROOT, BASE.RUNTIME, BASE.TMP):
        for current, dirs, files in safe_walk(base):
            for name in [*dirs, *files]:
                path = current / name
                try:
                    if not path.is_symlink():
                        continue
                    references.add(path.resolve(strict=False))
                except OSError:
                    continue

    return references


def safe_orphan_transients(references: set[Path], minimum_age_hours: float = 24.0) -> list[dict[str, Any]]:
    now = BASE.datetime.now(BASE.timezone.utc).timestamp()
    candidates: list[dict[str, Any]] = []
    roots = [BASE.ROOT / "runtime", BASE.ROOT / "tools", BASE.ROOT / "backend", BASE.ROOT / "config", BASE.TMP]
    worktrees = BASE.git_worktrees()
    protected_refs = references | worktrees | {BASE.ROOT, BASE.RUNTIME, BASE.ROOT / ".git"}

    for root in roots:
        for current, dirs, files in safe_walk(root):
            for name in [*dirs, *files]:
                path = current / name
                if not name.endswith(BASE.TRANSIENT_SUFFIXES):
                    continue
                try:
                    stat = path.lstat()
                except OSError:
                    continue
                age_hours = (now - stat.st_mtime) / 3600.0
                if age_hours < minimum_age_hours or BASE.path_touches(path, protected_refs):
                    continue
                candidates.append({
                    "path": str(path),
                    "size_bytes": stat.st_size,
                    "age_hours": round(age_hours, 2),
                    "reason": "stale_atomic_or_editor_transient",
                })

    return sorted(candidates, key=lambda item: int(item["size_bytes"]), reverse=True)


BASE.iter_files = safe_iter_files
BASE.collect_text_references = safe_collect_text_references
BASE.orphan_transients = safe_orphan_transients


if __name__ == "__main__":
    raise SystemExit(BASE.main())
