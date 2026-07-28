from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import subprocess
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "ZEL_RUNTIME_WRITER_OBSERVATION_V1"
OBSERVE_SEC = max(15, min(180, int(os.getenv("OBSERVE_SEC", "75"))))
POLL_SEC = max(0.5, min(5.0, float(os.getenv("POLL_SEC", "1"))))
MATCH = re.compile(r"(?:zel|z-os|alimi|telegram|strategy11|shadow|paper|q4r3|exact25)", re.I)
PATH_RE = re.compile(r"/(?:home/z/z|opt/zel|var/www)/[A-Za-z0-9_./@\-]+")
DATA_RE = re.compile(r"\.(?:json|jsonl|csv|db|sqlite|log)$", re.I)
SECRET_RE = re.compile(r"(?i)(token|secret|password|passwd|api[_-]?key|private[_-]?key)=([^\s]+)")
UNIT_ROOTS = (Path("/etc/systemd/system"), Path("/lib/systemd/system"), Path("/usr/lib/systemd/system"))


def clean(value: str, limit: int = 30000) -> str:
    return SECRET_RE.sub(lambda match: f"{match.group(1)}=[REDACTED]", value)[:limit]


def run(command: list[str], timeout: int = 20) -> tuple[int, str, str]:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
        return result.returncode, result.stdout, result.stderr
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, "", str(exc)


def sha256_small(path: Path, limit: int = 8 * 1024 * 1024) -> str | None:
    try:
        if not path.is_file() or path.stat().st_size > limit:
            return None
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def metadata(path: Path) -> dict[str, Any]:
    row: dict[str, Any] = {"path": str(path), "exists": path.exists()}
    try:
        stat = path.stat()
        row.update({"size_bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": sha256_small(path)})
    except OSError as exc:
        row["error"] = clean(str(exc))
    return row


def command_paths(command: str) -> set[str]:
    values: set[str] = set()
    for match in PATH_RE.findall(command):
        candidate = match.rstrip(";,}])\"")
        if DATA_RE.search(candidate):
            values.add(candidate)
    return values


def unit_commands() -> dict[str, str]:
    names: set[str] = set()
    for root in UNIT_ROOTS:
        if not root.is_dir():
            continue
        try:
            entries = list(root.iterdir())
        except OSError:
            continue
        for path in entries:
            if MATCH.search(path.name) and path.suffix in {".service", ".timer", ".path"}:
                names.add(path.name)
    commands: dict[str, str] = {}
    for name in sorted(names):
        rc, stdout, _ = run(["systemctl", "show", name, "--property=ExecStart", "--no-pager"])
        if rc != 0:
            continue
        _, _, value = stdout.strip().partition("=")
        if value:
            commands[name] = clean(value)
    return commands


def process_command(pid: int) -> str | None:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
        command = raw.replace(b"\0", b" ").decode("utf-8", errors="replace").strip()
        return clean(command) if command else None
    except OSError:
        return None


def matching_pids() -> dict[int, str]:
    rows: dict[int, str] = {}
    for path in Path("/proc").iterdir():
        if not path.name.isdigit():
            continue
        pid = int(path.name)
        command = process_command(pid)
        if command and MATCH.search(command):
            rows[pid] = command
    return rows


def writable_fds(pid: int) -> list[dict[str, Any]]:
    base = Path(f"/proc/{pid}/fd")
    rows: list[dict[str, Any]] = []
    try:
        fds = list(base.iterdir())
    except OSError:
        return rows
    for fd in fds:
        try:
            target = os.readlink(fd)
            if target.endswith(" (deleted)"):
                target = target[:-10]
            if not target.startswith(("/home/z/z/", "/opt/zel/", "/var/www/")):
                continue
            flags_text = Path(f"/proc/{pid}/fdinfo/{fd.name}").read_text(encoding="utf-8", errors="replace")
            match = re.search(r"^flags:\s*([0-7]+)$", flags_text, re.M)
            if not match:
                continue
            flags = int(match.group(1), 8)
            access_mode = flags & os.O_ACCMODE
            if access_mode not in {os.O_WRONLY, os.O_RDWR}:
                continue
            rows.append({"fd": int(fd.name), "target": target, "flags_octal": match.group(1), "access_mode": "WRONLY" if access_mode == os.O_WRONLY else "RDWR"})
        except (OSError, ValueError):
            continue
    return rows


def main() -> int:
    units = unit_commands()
    references: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    candidate_paths: set[str] = set()
    for unit, command in units.items():
        for path in command_paths(command):
            candidate_paths.add(path)
            references[path].append({"kind": "unit", "unit": unit, "command": command})

    first_processes = matching_pids()
    for pid, command in first_processes.items():
        for path in command_paths(command):
            candidate_paths.add(path)
            references[path].append({"kind": "process", "pid": pid, "command": command})

    before = {path: metadata(Path(path)) for path in sorted(candidate_paths)}
    observed_processes: dict[int, str] = dict(first_processes)
    fd_writers: defaultdict[str, dict[int, dict[str, Any]]] = defaultdict(dict)
    process_seen_count: defaultdict[int, int] = defaultdict(int)
    started = time.monotonic()
    samples = 0

    while time.monotonic() - started < OBSERVE_SEC:
        current = matching_pids()
        samples += 1
        for pid, command in current.items():
            observed_processes[pid] = command
            process_seen_count[pid] += 1
            for path in command_paths(command):
                candidate_paths.add(path)
                references[path].append({"kind": "process", "pid": pid, "command": command})
            for fd in writable_fds(pid):
                target = fd["target"]
                candidate_paths.add(target)
                fd_writers[target][pid] = {"pid": pid, "command": command, **fd}
        time.sleep(POLL_SEC)

    after = {path: metadata(Path(path)) for path in sorted(candidate_paths)}
    changed: list[dict[str, Any]] = []
    for path in sorted(candidate_paths):
        left = before.get(path, {"path": path, "exists": False})
        right = after.get(path, {"path": path, "exists": False})
        keys = ("exists", "size_bytes", "mtime_ns", "sha256")
        if any(left.get(key) != right.get(key) for key in keys):
            unique_refs: dict[tuple[str, str], dict[str, Any]] = {}
            for ref in references.get(path, []):
                identity = (str(ref.get("kind")), str(ref.get("pid") or ref.get("unit")))
                unique_refs[identity] = ref
            changed.append({"path": path, "before": left, "after": right, "referencers": list(unique_refs.values()), "direct_fd_writers": list(fd_writers.get(path, {}).values())})

    direct_conflicts = [
        {"path": path, "writer_count": len(rows), "writers": list(rows.values()), "severity": "CRITICAL"}
        for path, rows in sorted(fd_writers.items()) if len(rows) > 1
    ]
    changed_ambiguous = [
        {"path": row["path"], "referencer_count": len(row["referencers"]), "direct_fd_writer_count": len(row["direct_fd_writers"]), "severity": "REVIEW"}
        for row in changed if len(row["referencers"]) > 1 and not row["direct_fd_writers"]
    ]

    payload = {
        "schema_version": "1.0",
        "version": VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "observe_sec": OBSERVE_SEC,
        "poll_sec": POLL_SEC,
        "sample_count": samples,
        "unit_command_count": len(units),
        "observed_process_count": len(observed_processes),
        "candidate_path_count": len(candidate_paths),
        "changed_path_count": len(changed),
        "direct_writer_path_count": len(fd_writers),
        "changed_paths": changed,
        "direct_fd_writers": {path: list(rows.values()) for path, rows in sorted(fd_writers.items())},
        "direct_conflicts": direct_conflicts,
        "changed_ambiguous": changed_ambiguous,
        "observed_processes": [{"pid": pid, "command": command, "seen_samples": process_seen_count.get(pid, 0)} for pid, command in sorted(observed_processes.items())],
        "state": "HOLD_DIRECT_MULTI_WRITER_CONFLICT" if direct_conflicts else "PASS_DYNAMIC_WRITER_OBSERVATION_WITH_REVIEW_ITEMS",
        "safety": {
            "read_only": True,
            "remote_file_created": False,
            "service_changed": False,
            "process_changed": False,
            "database_changed": False,
            "deployment_changed": False,
            "execution_allowed": False,
            "order_authority": "BLOCKED",
        },
        "next": "USE_DIRECT_FD_EVIDENCE_FIRST_THEN_RESOLVE_CHANGED_AMBIGUOUS_PATHS",
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
