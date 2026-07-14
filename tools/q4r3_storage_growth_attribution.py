from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


DEFAULT_ROOTS = (
    Path("/home/z/z/runtime"),
    Path("/home/z/z/.worktrees"),
    Path("/tmp"),
    Path("/var/log"),
    Path("/var/lib/systemd"),
    Path("/root"),
)
PATH_ERRORS = (OSError, RuntimeError, ValueError)


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def allocated_bytes(path: Path) -> int:
    try:
        stat = path.lstat()
    except PATH_ERRORS:
        return 0
    return int(stat.st_blocks) * 512


def safe_walk(root: Path) -> Iterable[tuple[Path, list[str], list[str]]]:
    try:
        if not root.exists() or root.is_symlink():
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
        kept: list[str] = []
        for name in dirs:
            candidate = current_path / name
            try:
                if candidate.is_symlink():
                    continue
            except PATH_ERRORS:
                continue
            kept.append(name)
        dirs[:] = kept
        yield current_path, dirs, files


def direct_child_usage(root: Path) -> dict[str, int]:
    usage: dict[str, int] = {}
    try:
        children = list(root.iterdir())
    except PATH_ERRORS:
        return usage

    for child in children:
        total = allocated_bytes(child)
        try:
            is_dir = child.is_dir() and not child.is_symlink()
        except PATH_ERRORS:
            is_dir = False
        if is_dir:
            for current, _dirs, files in safe_walk(child):
                total += allocated_bytes(current)
                for name in files:
                    total += allocated_bytes(current / name)
        usage[str(child)] = total
    return usage


def large_file_snapshot(roots: Iterable[Path], minimum_bytes: int = 1_000_000) -> dict[str, int]:
    rows: dict[str, int] = {}
    for root in roots:
        for current, _dirs, files in safe_walk(root):
            for name in files:
                path = current / name
                size = allocated_bytes(path)
                if size >= minimum_bytes:
                    rows[str(path)] = size
    return rows


def snapshot(roots: Iterable[Path]) -> dict[str, Any]:
    root_rows: dict[str, int] = {}
    for root in roots:
        root_rows.update(direct_child_usage(root))
    return {
        "captured_at": iso_now(),
        "paths": root_rows,
        "large_files": large_file_snapshot(roots),
    }


def delta_rows(before: dict[str, int], after: dict[str, int]) -> list[dict[str, Any]]:
    keys = set(before) | set(after)
    rows = [
        {
            "path": path,
            "before_bytes": int(before.get(path, 0)),
            "after_bytes": int(after.get(path, 0)),
            "delta_bytes": int(after.get(path, 0)) - int(before.get(path, 0)),
        }
        for path in keys
    ]
    return sorted(rows, key=lambda row: int(row["delta_bytes"]), reverse=True)


def open_deleted_files() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    proc = Path("/proc")
    try:
        processes = list(proc.iterdir())
    except PATH_ERRORS:
        return rows

    for process in processes:
        if not process.name.isdigit():
            continue
        try:
            command = (process / "comm").read_text(encoding="utf-8", errors="ignore").strip()
            fds = list((process / "fd").iterdir())
        except PATH_ERRORS:
            continue
        for fd in fds:
            try:
                target = os.readlink(fd)
            except PATH_ERRORS:
                continue
            if not target.endswith(" (deleted)"):
                continue
            size = allocated_bytes(fd)
            rows.append(
                {
                    "pid": int(process.name),
                    "command": command,
                    "fd": fd.name,
                    "target": target,
                    "allocated_bytes": size,
                }
            )
    return sorted(rows, key=lambda row: int(row["allocated_bytes"]), reverse=True)


def command_output(command: list[str]) -> str:
    completed = subprocess.run(
        command,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return completed.stdout.strip()


def classify(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    suspects: list[dict[str, Any]] = []
    for row in rows:
        delta = int(row["delta_bytes"])
        if delta <= 0:
            continue
        path = str(row["path"])
        if "/.worktrees/" in path or path.startswith("/tmp/q4r3-"):
            category = "worktree_or_job_workspace_growth"
        elif "/runtime/" in path and (path.endswith(".log") or "backup" in path.lower()):
            category = "runtime_log_or_backup_growth"
        elif path.startswith("/var/log") or "journal" in path.lower():
            category = "system_log_growth"
        else:
            category = "other_growth"
        suspects.append({**row, "category": category})
    return suspects


def run(interval_sec: int, output: Path) -> dict[str, Any]:
    roots = [root for root in DEFAULT_ROOTS if root.exists()]
    first = snapshot(roots)
    time.sleep(max(interval_sec, 1))
    second = snapshot(roots)
    path_deltas = delta_rows(first["paths"], second["paths"])
    file_deltas = delta_rows(first["large_files"], second["large_files"])
    deleted = open_deleted_files()
    payload = {
        "schema": "q4r3_storage_growth_attribution_v1",
        "generated_at": iso_now(),
        "state": "PASS",
        "observer_only": True,
        "interval_sec": interval_sec,
        "growth_detected": any(int(row["delta_bytes"]) > 0 for row in path_deltas),
        "top_path_growth": path_deltas[:50],
        "top_file_growth": file_deltas[:100],
        "suspected_growth_sources": classify(file_deltas + path_deltas)[:100],
        "open_deleted_files": deleted[:100],
        "open_deleted_allocated_bytes": sum(int(row["allocated_bytes"]) for row in deleted),
        "journal_disk_usage": command_output(["journalctl", "--disk-usage", "--no-pager"]),
        "git_worktrees": command_output(["git", "-C", "/home/z/z", "worktree", "list", "--porcelain"]),
        "next_action": "REMOVE_ONLY_CONFIRMED_REGENERABLE_GROWTH_SOURCE_OR_INSTALL_RETENTION_CAP",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(output)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval-sec", type=int, default=30)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = run(args.interval_sec, args.output)
    print(
        json.dumps(
            {
                "state": payload["state"],
                "growth_detected": payload["growth_detected"],
                "open_deleted_allocated_bytes": payload["open_deleted_allocated_bytes"],
                "top_suspects": payload["suspected_growth_sources"][:10],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
