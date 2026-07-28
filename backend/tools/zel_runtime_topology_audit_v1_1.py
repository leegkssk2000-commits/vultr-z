from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "ZEL_RUNTIME_TOPOLOGY_AUDIT_V1_1"
MATCH = re.compile(r"(?:zel|z-os|alimi|telegram|gunicorn|uvicorn|strategy11|shadow|paper|q4r3|exact25)", re.I)
SECRET_RE = re.compile(r"(?i)(token|secret|password|passwd|api[_-]?key|private[_-]?key)=([^\s]+)")
OUTPUT_FLAG_RE = re.compile(r"^(?:--(?:state|status|ledger|output|out|gate|current|latest|artifact|manifest|open-latest|close-latest))$")
OUTPUT_NAME_RE = re.compile(r"(?:state|status|ledger|current|latest|gate|manifest|artifact).*(?:\.json|\.jsonl|\.csv)$", re.I)
UNIT_ROOTS = (Path("/etc/systemd/system"), Path("/lib/systemd/system"), Path("/usr/lib/systemd/system"))


def clean(value: str, limit: int = 50000) -> str:
    return SECRET_RE.sub(lambda match: f"{match.group(1)}=[REDACTED]", value)[:limit]


def run(command: list[str], timeout: int = 30) -> tuple[int, str, str]:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
        return result.returncode, result.stdout, result.stderr
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, "", str(exc)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return ""


def unit_names() -> tuple[set[str], dict[str, str]]:
    names: set[str] = set()
    paths: dict[str, str] = {}
    for root in UNIT_ROOTS:
        if not root.is_dir():
            continue
        try:
            entries = list(root.iterdir())
        except OSError:
            continue
        for path in entries:
            if MATCH.search(path.name):
                names.add(path.name)
                paths.setdefault(path.name, str(path))
    return names, paths


def service_topology() -> dict[str, Any]:
    names, discovered = unit_names()
    timer_rc, timer_stdout, timer_stderr = run(["systemctl", "list-timers", "--all", "--no-legend", "--no-pager"])
    timer_lines: list[str] = []
    if timer_rc == 0:
        for line in timer_stdout.splitlines():
            if not MATCH.search(line):
                continue
            timer_lines.append(clean(line))
            names.update(re.findall(r"([A-Za-z0-9_.@\-]+\.(?:timer|service|path))", line))

    properties = (
        "Id,Names,LoadState,ActiveState,SubState,UnitFileState,FragmentPath,SourcePath,"
        "User,Group,WorkingDirectory,ExecStart,ExecMainPID,MainPID,Result,Restart,NRestarts,"
        "Triggers,TriggeredBy,Description"
    )
    rows: list[dict[str, Any]] = []
    for name in sorted(names):
        rc, stdout, stderr = run(["systemctl", "show", name, f"--property={properties}", "--no-pager"])
        row: dict[str, Any] = {"unit": name, "show_rc": rc, "discovered_path": discovered.get(name)}
        for line in stdout.splitlines():
            key, separator, value = line.partition("=")
            if separator:
                row[key] = clean(value)
        if stderr.strip():
            row["error"] = clean(stderr.strip())
        rows.append(row)
    return {
        "units": rows,
        "unit_count": len(rows),
        "timer_lines": timer_lines,
        "timer_count": len(timer_lines),
        "timer_probe_rc": timer_rc,
        "timer_probe_error": clean(timer_stderr.strip()),
    }


def process_topology() -> list[dict[str, Any]]:
    rc, stdout, stderr = run(["ps", "-eo", "pid=,ppid=,user=,etimes=,comm=,args="])
    if rc != 0:
        return [{"error": clean(stderr)}]
    rows: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        if not MATCH.search(line):
            continue
        parts = line.strip().split(maxsplit=5)
        if len(parts) < 5:
            continue
        rows.append(
            {
                "pid": int(parts[0]),
                "ppid": int(parts[1]),
                "user": parts[2],
                "age_sec": int(parts[3]),
                "comm": parts[4],
                "args": clean(parts[5] if len(parts) > 5 else ""),
            }
        )
    return rows


def command_targets(command: str) -> list[str]:
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()
    targets: set[str] = set()
    for index, token in enumerate(tokens[:-1]):
        if OUTPUT_FLAG_RE.match(token):
            candidate = tokens[index + 1]
            if candidate.startswith("/"):
                targets.add(candidate)
    for token in tokens:
        if token.startswith("/") and OUTPUT_NAME_RE.search(token):
            targets.add(token.rstrip(";,}"))
    return sorted(targets)


def writer_topology(processes: list[dict[str, Any]], units: list[dict[str, Any]]) -> dict[str, Any]:
    owners: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in processes:
        command = str(row.get("args") or "")
        for target in command_targets(command):
            owners[target].append({"kind": "process", "pid": row.get("pid"), "command": command})
    for row in units:
        command = str(row.get("ExecStart") or "")
        for target in command_targets(command):
            owners[target].append({"kind": "unit", "unit": row.get("unit"), "command": command})

    conflicts: list[dict[str, Any]] = []
    for target, rows in sorted(owners.items()):
        identities = {
            (str(row.get("kind")), str(row.get("pid") or row.get("unit")))
            for row in rows
        }
        if len(identities) > 1:
            conflicts.append(
                {
                    "target": target,
                    "owner_count": len(identities),
                    "owners": rows,
                    "severity": "CRITICAL" if len(identities) >= 3 else "HIGH",
                }
            )
    return {"target_count": len(owners), "targets": dict(owners), "conflicts": conflicts}


def executable_inventory(processes: list[dict[str, Any]], units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    paths: set[Path] = set()
    commands = [str(row.get("args") or "") for row in processes]
    commands.extend(str(row.get("ExecStart") or "") for row in units)
    for command in commands:
        for value in re.findall(r"/(?:usr/local/bin|home/z/z|opt/zel)/[A-Za-z0-9_./@\-]+", command):
            candidate = Path(value.rstrip(";,}"))
            if candidate.is_file():
                paths.add(candidate)
    rows: list[dict[str, Any]] = []
    for path in sorted(paths):
        try:
            stat = path.stat()
            rows.append(
                {
                    "path": str(path),
                    "realpath": str(path.resolve()),
                    "size_bytes": stat.st_size,
                    "mtime_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat().replace("+00:00", "Z"),
                    "sha256": sha256(path) if stat.st_size <= 20 * 1024 * 1024 else "",
                    "versioned_release": str(path.resolve()).startswith("/opt/zel/releases/"),
                    "usr_local_unversioned": str(path).startswith("/usr/local/bin/"),
                }
            )
        except OSError as exc:
            rows.append({"path": str(path), "error": clean(str(exc))})
    return rows


def release_topology() -> dict[str, Any]:
    current = Path("/opt/zel/current")
    releases = Path("/opt/zel/releases")
    recent: list[dict[str, Any]] = []
    if releases.is_dir():
        try:
            candidates = sorted(releases.iterdir(), key=lambda item: item.stat().st_mtime, reverse=True)[:25]
        except OSError:
            candidates = []
        for path in candidates:
            try:
                recent.append(
                    {
                        "path": str(path),
                        "mtime_utc": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat().replace("+00:00", "Z"),
                    }
                )
            except OSError:
                continue
    return {
        "current_exists": current.exists(),
        "current_is_symlink": current.is_symlink(),
        "current_realpath": str(current.resolve()) if current.exists() else None,
        "releases_exists": releases.is_dir(),
        "recent_releases": recent,
    }


def main() -> int:
    services = service_topology()
    processes = process_topology()
    writers = writer_topology(processes, services["units"])
    executables = executable_inventory(processes, services["units"])
    releases = release_topology()

    active_units = [row for row in services["units"] if row.get("ActiveState") == "active"]
    restart_hot = [row for row in services["units"] if int(str(row.get("NRestarts") or "0") or 0) >= 10]
    usr_local = [row for row in executables if row.get("usr_local_unversioned")]
    findings: list[dict[str, Any]] = []
    if len(processes) >= 25:
        findings.append({"severity": "HIGH", "code": "RUNTIME_PROCESS_SPRAWL", "count": len(processes)})
    if services["timer_count"] >= 25:
        findings.append({"severity": "HIGH", "code": "RUNTIME_TIMER_SPRAWL", "count": services["timer_count"]})
    if len(usr_local) >= 10:
        findings.append({"severity": "HIGH", "code": "UNVERSIONED_USR_LOCAL_RUNTIME_OWNERS", "count": len(usr_local)})
    if restart_hot:
        findings.append(
            {
                "severity": "HIGH",
                "code": "SERVICE_RESTART_STORM",
                "units": [{"unit": row.get("unit"), "NRestarts": row.get("NRestarts")} for row in restart_hot],
            }
        )
    if writers["conflicts"]:
        findings.append({"severity": "CRITICAL", "code": "MULTI_WRITER_TARGET_CONFLICTS", "count": len(writers["conflicts"])})
    if releases["releases_exists"] and not releases["current_exists"]:
        findings.append({"severity": "HIGH", "code": "RELEASES_EXIST_WITHOUT_CURRENT_POINTER"})

    payload = {
        "schema_version": "1.1",
        "version": VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "services": services,
        "active_unit_count": len(active_units),
        "processes": processes,
        "process_count": len(processes),
        "writer_topology": writers,
        "executables": executables,
        "release_topology": releases,
        "findings": findings,
        "state": "HOLD_RUNTIME_TOPOLOGY_REVIEW_REQUIRED" if findings else "PASS_RUNTIME_TOPOLOGY_CENSUS",
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
        "next": "CLASSIFY_ACTIVE_OWNER_GRAPH_THEN_DISABLE_ONLY_PROVEN_SUPERSEDED_TIMERS",
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
