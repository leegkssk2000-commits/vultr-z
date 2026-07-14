from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

ROOT = Path("/home/z/z")
RUNTIME = ROOT / "runtime"
FORMAL_LEDGER = RUNTIME / "exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl"
ACTIVE_METHOD_ROOT = ROOT / "backend/trade_methods"
ACTIVE_PRODUCER = ROOT / "tools/q4r3_exact25_dedicated_shadow_producer.py"

PRODUCER_UNIT = "q4r3-exact25-shadow-producer.service"
WRITER_UNIT = "q4r3-exact25-persistent-single-event-writer.service"
CAPTURE_TIMER = "q4r3-exact25-preentry-method-context-capture.timer"

REPORT_ROOT = RUNTIME / "q4r3_patch_debris_cleanup_v8"
REPORT_PATH = REPORT_ROOT / "report_latest.json"
STATUS_PATH = RUNTIME / "q4r3_patch_debris_cleanup_v8_job_latest.json"
GENERATOR_REPORT = REPORT_ROOT / "generator_references_latest.txt"

BACKUP_ROOTS = (
    RUNTIME / "r4d58q4i_open_canonical_guard_backups",
    RUNTIME / "r4d58q4l_candidate_identity_rebind_backups",
    RUNTIME / "r4d58q4l2_d38_identity_post_guard_backups",
    RUNTIME / "r4d58q4m6_q4l2_fallback_identity_backups",
    RUNTIME / "r4d58q4m5_q4l2_atomic_backups",
    RUNTIME / "r4d58q4m12_postwrite_identity_stabilizer_backups",
    ROOT / "_zui_patch_backups",
    ROOT / "_patches/_zui_patch_backups",
)

EXACT_STALE_PATHS = (
    ROOT / ".worktrees/q4r3-deep-storage-hygiene-hotfix-v3",
    ROOT / ".worktrees/q4r3-deep-storage-hygiene-v4",
    ROOT / ".worktrees/q4r3-deep-storage-hygiene-v5",
    ROOT / ".worktrees/q4r3-deep-storage-hygiene-v6",
    Path("/tmp/q4r3-deep-storage-hygiene"),
    Path("/tmp/q4r3-deep-storage-hygiene-hotfix"),
    Path("/tmp/q4r3-deep-storage-hygiene-hotfix-v3"),
    Path("/tmp/q4r3-safe-disk-hygiene"),
)

PROTECTED_NAME_RE = re.compile(
    r"(?:golden|ssot|baseline|verified|owner|lock|active|current|latest|production|canonical_restore)",
    re.IGNORECASE,
)
PATH_ERRORS = (OSError, RuntimeError, ValueError)


@dataclass(frozen=True)
class Snapshot:
    path: Path
    mtime: float
    size_bytes: int


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run(command: list[str]) -> str:
    completed = subprocess.run(
        command,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return completed.stdout.strip()


def unit_pid(unit: str) -> str:
    return run(["systemctl", "show", unit, "-p", "MainPID", "--value"])


def unit_active(unit: str) -> bool:
    return run(["systemctl", "is-active", unit]) == "active"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def method_hash() -> str:
    digest = hashlib.sha256()
    for path in sorted(ACTIVE_METHOD_ROOT.glob("*.py")):
        digest.update(path.name.encode())
        digest.update(b"\0")
        digest.update(file_sha256(path).encode())
        digest.update(b"\n")
    return digest.hexdigest()


def disk_state() -> dict[str, int | str]:
    stat = shutil.disk_usage("/")
    pct = round((stat.used / stat.total) * 100, 2) if stat.total else 0.0
    return {
        "total_bytes": stat.total,
        "used_bytes": stat.used,
        "free_bytes": stat.free,
        "use_pct": pct,
    }


def allocated_size(path: Path) -> int:
    if path.is_symlink():
        try:
            return int(path.lstat().st_blocks) * 512
        except PATH_ERRORS:
            return 0
    total = 0
    try:
        if path.is_file():
            return int(path.stat().st_blocks) * 512
    except PATH_ERRORS:
        return 0
    for current, dirs, files in os.walk(path, topdown=True, followlinks=False):
        current_path = Path(current)
        kept_dirs: list[str] = []
        for name in dirs:
            candidate = current_path / name
            try:
                if candidate.is_symlink():
                    total += int(candidate.lstat().st_blocks) * 512
                    continue
            except PATH_ERRORS:
                continue
            kept_dirs.append(name)
        dirs[:] = kept_dirs
        try:
            total += int(current_path.stat().st_blocks) * 512
        except PATH_ERRORS:
            pass
        for name in files:
            candidate = current_path / name
            try:
                total += int(candidate.lstat().st_blocks) * 512
            except PATH_ERRORS:
                continue
    return total


def collect_process_references() -> set[Path]:
    references: set[Path] = set()
    proc = Path("/proc")
    try:
        processes = list(proc.iterdir())
    except PATH_ERRORS:
        return references
    for process in processes:
        if not process.name.isdigit():
            continue
        for entry in (process / "cwd", process / "root", process / "exe"):
            try:
                references.add(Path(os.readlink(entry)).resolve(strict=False))
            except PATH_ERRORS:
                pass
        try:
            cmdline = (process / "cmdline").read_bytes().replace(b"\x00", b" ").decode(errors="ignore")
        except PATH_ERRORS:
            cmdline = ""
        for token in cmdline.split():
            if token.startswith("/") and "\x00" not in token:
                try:
                    references.add(Path(token).resolve(strict=False))
                except PATH_ERRORS:
                    pass
        try:
            fds = list((process / "fd").iterdir())
        except PATH_ERRORS:
            fds = []
        for fd in fds:
            try:
                target = os.readlink(fd)
                if target.endswith(" (deleted)"):
                    target = target[:-10]
                if target.startswith("/"):
                    references.add(Path(target).resolve(strict=False))
            except PATH_ERRORS:
                continue
    return references


def touches_reference(path: Path, references: Iterable[Path]) -> bool:
    try:
        resolved = path.resolve(strict=False)
    except PATH_ERRORS:
        return True
    for ref in references:
        try:
            if resolved == ref or resolved in ref.parents or ref in resolved.parents:
                return True
        except PATH_ERRORS:
            continue
    return False


def direct_snapshots(root: Path) -> list[Snapshot]:
    rows: list[Snapshot] = []
    try:
        children = list(root.iterdir())
    except PATH_ERRORS:
        return rows
    for child in children:
        try:
            stat = child.lstat()
        except PATH_ERRORS:
            continue
        rows.append(Snapshot(child, stat.st_mtime, allocated_size(child)))
    return sorted(rows, key=lambda item: item.mtime, reverse=True)


def retention_keep(rows: list[Snapshot], references: set[Path]) -> dict[Path, str]:
    keep: dict[Path, str] = {}
    if not rows:
        return keep
    for row in rows[:5]:
        keep[row.path] = "newest_5"
    keep[rows[-1].path] = "oldest_anchor"

    now = time.time()
    daily: set[str] = set()
    weekly: set[str] = set()
    for row in rows:
        age_days = max(0.0, (now - row.mtime) / 86400.0)
        dt = datetime.fromtimestamp(row.mtime, timezone.utc)
        day_key = dt.strftime("%Y-%m-%d")
        week_key = dt.strftime("%G-W%V")
        if age_days <= 7 and day_key not in daily:
            keep.setdefault(row.path, "daily_7d")
            daily.add(day_key)
        if age_days <= 56 and week_key not in weekly:
            keep.setdefault(row.path, "weekly_8w")
            weekly.add(week_key)
        if PROTECTED_NAME_RE.search(row.path.name):
            keep[row.path] = "protected_name"
        if touches_reference(row.path, references):
            keep[row.path] = "active_reference"
    return keep


def safe_delete(path: Path, allowed_parent: Path) -> None:
    if path.parent != allowed_parent:
        raise RuntimeError(f"PARENT_SCOPE_MISMATCH:{path}")
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    else:
        shutil.rmtree(path)


def source_generator_matches(names: list[str]) -> list[str]:
    matches: list[str] = []
    roots = [ROOT / "tools", ROOT / "backend", ROOT / "frontend", Path("/etc/systemd/system")]
    excluded = {".git", ".venv", "node_modules", "runtime", "static", "data"}
    for root in roots:
        if not root.exists():
            continue
        for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
            dirs[:] = [name for name in dirs if name not in excluded]
            for name in files:
                path = Path(current) / name
                try:
                    if path.stat().st_size > 2_000_000:
                        continue
                    text = path.read_text(encoding="utf-8", errors="ignore")
                except PATH_ERRORS:
                    continue
                hit_names = [token for token in names if token in text]
                if hit_names:
                    matches.append(f"{path}: {','.join(hit_names)}")
    return sorted(set(matches))


def write_status(state: str, stage: str, reason: str) -> None:
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    payload = {
        "job": "q4r3_patch_debris_retention_cleanup_v8",
        "state": state,
        "current_stage": stage,
        "reason": reason,
        "updated_at": now_iso(),
        "action": "hold",
        "runtime_root_deleted": False,
        "formal_ledger_deleted": False,
        "unique_golden_or_ssot_deleted": False,
        "paper_enabled": False,
        "live_enabled": False,
        "order_enabled": False,
        "order_authority": "blocked",
        "execution_authority": "none",
    }
    STATUS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--minimum-age-hours", type=float, default=24.0)
    args = parser.parse_args()

    for required in (FORMAL_LEDGER, ACTIVE_METHOD_ROOT, ACTIVE_PRODUCER):
        if not required.exists():
            raise SystemExit(f"REQUIRED_INPUT_MISSING:{required}")
    for unit in (PRODUCER_UNIT, WRITER_UNIT, CAPTURE_TIMER):
        if not unit_active(unit):
            raise SystemExit(f"REQUIRED_UNIT_NOT_ACTIVE:{unit}")

    write_status("RUNNING", "preflight", "capture_immutability_baseline")
    producer_pid_before = unit_pid(PRODUCER_UNIT)
    writer_pid_before = unit_pid(WRITER_UNIT)
    ledger_before = FORMAL_LEDGER.read_bytes()
    methods_before = method_hash()
    producer_before = file_sha256(ACTIVE_PRODUCER)
    disk_before = disk_state()

    references = collect_process_references()
    deleted: list[dict[str, object]] = []
    kept: list[dict[str, object]] = []
    root_reports: list[dict[str, object]] = []
    minimum_age_sec = args.minimum_age_hours * 3600.0
    now = time.time()

    write_status("RUNNING", "backup_retention", "protected_gfs_retention")
    for root in BACKUP_ROOTS:
        if not root.exists():
            continue
        rows = direct_snapshots(root)
        keep_map = retention_keep(rows, references)
        before_bytes = sum(item.size_bytes for item in rows)
        candidate_bytes = 0
        candidate_count = 0
        for row in rows:
            age_sec = now - row.mtime
            reason = keep_map.get(row.path)
            if reason is not None:
                kept.append({"path": str(row.path), "size_bytes": row.size_bytes, "reason": reason})
                continue
            if age_sec < minimum_age_sec:
                kept.append({"path": str(row.path), "size_bytes": row.size_bytes, "reason": "minimum_age"})
                continue
            candidate_count += 1
            candidate_bytes += row.size_bytes
            if args.apply:
                safe_delete(row.path, root)
            deleted.append({
                "path": str(row.path),
                "size_bytes": row.size_bytes,
                "reason": "outside_newest_daily_weekly_retention",
                "applied": args.apply,
            })
        root_reports.append({
            "root": str(root),
            "snapshot_count": len(rows),
            "before_bytes": before_bytes,
            "candidate_count": candidate_count,
            "candidate_bytes": candidate_bytes,
        })

    write_status("RUNNING", "trash_cleanup", "explicit_trash_and_failed_worktrees_only")
    trash_paths = list(ROOT.glob("_TRASH_*"))
    exact_paths = [*EXACT_STALE_PATHS, *trash_paths]
    for path in exact_paths:
        if not path.exists() and not path.is_symlink():
            continue
        try:
            mtime = path.lstat().st_mtime
        except PATH_ERRORS:
            continue
        age_sec = now - mtime
        if age_sec < minimum_age_sec:
            kept.append({"path": str(path), "size_bytes": allocated_size(path), "reason": "minimum_age"})
            continue
        if touches_reference(path, references):
            kept.append({"path": str(path), "size_bytes": allocated_size(path), "reason": "active_reference"})
            continue
        size = allocated_size(path)
        if args.apply:
            if path.is_symlink() or path.is_file():
                path.unlink(missing_ok=True)
            else:
                shutil.rmtree(path)
        deleted.append({
            "path": str(path),
            "size_bytes": size,
            "reason": "explicit_trash_or_failed_cleanup_worktree",
            "applied": args.apply,
        })

    write_status("RUNNING", "generator_discovery", "find_future_growth_sources")
    generator_names = [root.name for root in BACKUP_ROOTS]
    generator_matches = source_generator_matches(generator_names)
    GENERATOR_REPORT.write_text("\n".join(generator_matches) + ("\n" if generator_matches else ""), encoding="utf-8")

    write_status("RUNNING", "postcheck", "verify_immutability")
    producer_pid_after = unit_pid(PRODUCER_UNIT)
    writer_pid_after = unit_pid(WRITER_UNIT)
    ledger_after = FORMAL_LEDGER.read_bytes()
    methods_after = method_hash()
    producer_after = file_sha256(ACTIVE_PRODUCER)

    if producer_pid_before != producer_pid_after:
        raise SystemExit("PRODUCER_PID_CHANGED")
    if writer_pid_before != writer_pid_after:
        raise SystemExit("WRITER_PID_CHANGED")
    if methods_before != methods_after:
        raise SystemExit("ACTIVE_TRADE_METHOD_CHANGED")
    if producer_before != producer_after:
        raise SystemExit("ACTIVE_PRODUCER_CHANGED")
    if not ledger_after.startswith(ledger_before):
        raise SystemExit("FORMAL_LEDGER_NOT_APPEND_ONLY")
    for unit in (PRODUCER_UNIT, WRITER_UNIT, CAPTURE_TIMER):
        if not unit_active(unit):
            raise SystemExit(f"POSTCHECK_UNIT_NOT_ACTIVE:{unit}")

    disk_after = disk_state()
    deleted_bytes = sum(int(row["size_bytes"]) for row in deleted if row["applied"])
    payload = {
        "job": "q4r3_patch_debris_retention_cleanup_v8",
        "state": "PASS",
        "current_stage": "complete",
        "status": "PASS_Q4R3_PATCH_DEBRIS_RETENTION_CLEANUP_V8",
        "verdict": "PATCH_BACKUP_RETENTION_AND_EXPLICIT_TRASH_CLEANUP_COMPLETE" if args.apply else "AUDIT_ONLY_COMPLETE",
        "updated_at": now_iso(),
        "action": "hold",
        "apply": args.apply,
        "minimum_age_hours": args.minimum_age_hours,
        "disk_before": disk_before,
        "disk_after": disk_after,
        "free_bytes_delta": int(disk_after["free_bytes"]) - int(disk_before["free_bytes"]),
        "declared_deleted_bytes": deleted_bytes,
        "deleted_count": sum(1 for row in deleted if row["applied"]),
        "candidate_count": len(deleted),
        "kept_count": len(kept),
        "backup_roots": root_reports,
        "deleted": deleted[:500],
        "kept": kept[:500],
        "generator_reference_count": len(generator_matches),
        "generator_report_path": str(GENERATOR_REPORT),
        "runtime_root_deleted": False,
        "formal_ledger_deleted": False,
        "unique_golden_or_ssot_deleted": False,
        "producer_pid_unchanged": True,
        "writer_pid_unchanged": True,
        "active_trade_method_hash_unchanged": True,
        "active_producer_hash_unchanged": True,
        "formal_ledger_append_only": True,
        "paper_enabled": False,
        "live_enabled": False,
        "order_enabled": False,
        "order_authority": "blocked",
        "execution_authority": "none",
        "next_action": "PATCH_IDENTIFIED_BACKUP_GENERATORS_WITH_RETENTION_CAP_THEN_RUN_SKILL_ACTIVE_LINEAGE_AUDIT",
    }
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    STATUS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "state": payload["state"],
        "status": payload["status"],
        "deleted_count": payload["deleted_count"],
        "declared_deleted_bytes": payload["declared_deleted_bytes"],
        "free_bytes_delta": payload["free_bytes_delta"],
        "generator_reference_count": payload["generator_reference_count"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
