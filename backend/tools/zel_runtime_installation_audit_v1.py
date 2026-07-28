from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "ZEL_RUNTIME_INSTALLATION_AUDIT_V1"
EXPECTED_MASTER_SHA = os.getenv("EXPECTED_MASTER_SHA", "").strip()
MATCH = re.compile(r"(?:zel|z-os|alimi|telegram|gunicorn|strategy11|shadow|paper|portfolio)", re.I)
SECRET_RE = re.compile(r"(?i)(token|secret|password|passwd|api[_-]?key|private[_-]?key)=([^\s]+)")


def clean(value: str) -> str:
    return SECRET_RE.sub(lambda match: f"{match.group(1)}=[REDACTED]", value)[:20000]


def run(command: list[str], timeout: int = 20) -> dict[str, Any]:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
        return {
            "rc": result.returncode,
            "stdout": clean(result.stdout.strip()),
            "stderr": clean(result.stderr.strip()),
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"rc": 127, "stdout": "", "stderr": clean(str(exc))}


def stat_row(path: Path) -> dict[str, Any]:
    row: dict[str, Any] = {"path": str(path), "exists": path.exists(), "is_file": path.is_file(), "is_dir": path.is_dir()}
    try:
        stat = path.stat()
        row.update({
            "size_bytes": stat.st_size,
            "mtime_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat().replace("+00:00", "Z"),
            "uid": stat.st_uid,
            "gid": stat.st_gid,
            "mode": oct(stat.st_mode & 0o777),
            "realpath": str(path.resolve()),
        })
        if path.is_file() and stat.st_size <= 50 * 1024 * 1024:
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            row["sha256"] = digest.hexdigest()
    except OSError as exc:
        row["error"] = clean(str(exc))
    return row


def git_probe(path: Path) -> dict[str, Any]:
    row: dict[str, Any] = {"path": str(path), "exists": path.exists(), "git": (path / ".git").exists()}
    if not row["git"]:
        return row
    for key, args in {
        "head_sha": ["git", "-C", str(path), "rev-parse", "HEAD"],
        "branch": ["git", "-C", str(path), "branch", "--show-current"],
        "status_porcelain": ["git", "-C", str(path), "status", "--porcelain=v1", "--untracked-files=no"],
    }.items():
        result = run(args)
        row[key] = result["stdout"] if result["rc"] == 0 else None
        if result["rc"] != 0:
            row[f"{key}_error"] = result["stderr"]
    row["expected_master_sha"] = EXPECTED_MASTER_SHA or None
    row["master_parity"] = bool(EXPECTED_MASTER_SHA and row.get("head_sha") == EXPECTED_MASTER_SHA)
    row["tracked_dirty"] = bool(row.get("status_porcelain"))
    return row


def sqlite_probe(path: Path) -> dict[str, Any]:
    row = stat_row(path)
    row.update({"read_only_open": False, "tables": [], "wal": stat_row(Path(str(path) + "-wal")), "shm": stat_row(Path(str(path) + "-shm"))})
    if not path.is_file():
        return row
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=3)
        row["read_only_open"] = True
        tables = [name for (name,) in connection.execute("select name from sqlite_master where type='table' order by name")]
        row["tables"] = tables
        row["columns"] = {
            table: [dict(zip(("cid", "name", "type", "notnull", "default", "pk"), values)) for values in connection.execute(f"pragma table_info({json.dumps(table)})")]
            for table in tables[:50]
        }
        connection.close()
    except (sqlite3.Error, OSError) as exc:
        row["sqlite_error"] = clean(str(exc))
    return row


def service_inventory() -> dict[str, Any]:
    unit_files = run(["systemctl", "list-unit-files", "--no-legend", "--no-pager"])
    units: list[str] = []
    if unit_files["rc"] == 0:
        for line in unit_files["stdout"].splitlines():
            name = line.split(maxsplit=1)[0] if line.split() else ""
            if name and MATCH.search(name):
                units.append(name)
    rows: list[dict[str, Any]] = []
    properties = "Id,Names,LoadState,ActiveState,SubState,UnitFileState,FragmentPath,User,Group,WorkingDirectory,ExecStart,ExecMainPID,MainPID,Result,Restart,NRestarts"
    for unit in sorted(set(units)):
        result = run(["systemctl", "show", unit, f"--property={properties}", "--no-pager"])
        values: dict[str, Any] = {"unit": unit, "show_rc": result["rc"]}
        for line in result["stdout"].splitlines():
            key, separator, value = line.partition("=")
            if separator:
                values[key] = clean(value)
        if result["stderr"]:
            values["error"] = result["stderr"]
        rows.append(values)
    timers = run(["systemctl", "list-timers", "--all", "--no-legend", "--no-pager"])
    timer_lines = [clean(line) for line in timers["stdout"].splitlines() if MATCH.search(line)] if timers["rc"] == 0 else []
    return {"unit_file_probe": unit_files, "units": rows, "timers": timer_lines, "timer_probe_error": timers["stderr"]}


def process_inventory() -> list[dict[str, Any]]:
    result = run(["ps", "-eo", "pid=,ppid=,user=,comm=,args="])
    rows: list[dict[str, Any]] = []
    if result["rc"] != 0:
        return [{"error": result["stderr"]}]
    for line in result["stdout"].splitlines():
        if not MATCH.search(line):
            continue
        parts = line.strip().split(maxsplit=4)
        if len(parts) < 4:
            continue
        rows.append({
            "pid": int(parts[0]),
            "ppid": int(parts[1]),
            "user": parts[2],
            "comm": parts[3],
            "args": clean(parts[4] if len(parts) > 4 else ""),
        })
    return rows


def file_owners(paths: list[Path]) -> dict[str, Any]:
    lsof = run(["bash", "-lc", "command -v lsof >/dev/null 2>&1 && lsof -Fpcu -- " + " ".join(repr(str(path)) for path in paths) + " || true"])
    return {"available": lsof["rc"] == 0, "raw": lsof["stdout"], "error": lsof["stderr"]}


def frontend_lock() -> dict[str, Any]:
    path = Path("/home/z/z/frontend/.z_app_source_root.env")
    row = stat_row(path)
    allowed = {"APP_SOURCE_ROOT", "APP_DEPLOY_ROOT_1", "APP_DIST_DIR"}
    values: dict[str, str] = {}
    if path.is_file():
        try:
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                key, separator, value = line.partition("=")
                key = key.strip()
                if separator and key in allowed:
                    values[key] = value.strip().strip("'\"")
        except OSError as exc:
            row["read_error"] = clean(str(exc))
    row["allowed_values"] = values
    return row


def main() -> int:
    repos = [Path("/home/z/z"), Path("/home/z/z/frontend/z-os-app-source")]
    critical_paths = [
        Path("/home/z/z/app.py"),
        Path("/home/z/z/wsgi.py"),
        Path("/home/z/z/gunicorn_conf.py"),
        Path("/home/z/z/engine/core_loop.py"),
        Path("/home/z/z/engine/signal_hub.py"),
        Path("/home/z/z/engine/runner.py"),
        Path("/home/z/z/frontend/z-os-app-source/deploy_apply.sh"),
        Path("/home/z/z/frontend/z-os-app-source/scripts/deploy_locked.sh"),
        Path("/var/www/z-os-app/index.html"),
        Path("/var/www/z-os-pwa/index.html"),
        Path("/var/www/z-os/index.html"),
        Path("/var/www/html/index.html"),
    ]
    databases = [Path("/home/z/z/db/z.sqlite"), Path("/home/z/z/db/logs.db")]
    services = service_inventory()
    processes = process_inventory()
    repo_rows = [git_probe(path) for path in repos]
    db_rows = [sqlite_probe(path) for path in databases]
    port_probe = run(["ss", "-ltnp"])
    ports = [clean(line) for line in port_probe["stdout"].splitlines() if re.search(r":(?:80|443|8000|8080|3000)\b", line)] if port_probe["rc"] == 0 else []

    findings: list[dict[str, Any]] = []
    main_repo = repo_rows[0]
    if EXPECTED_MASTER_SHA and main_repo.get("head_sha") and not main_repo.get("master_parity"):
        findings.append({"severity": "HIGH", "code": "VPS_GIT_HEAD_DIFFERS_FROM_MASTER", "evidence": {"actual": main_repo.get("head_sha"), "expected": EXPECTED_MASTER_SHA}})
    if main_repo.get("tracked_dirty"):
        findings.append({"severity": "HIGH", "code": "VPS_TRACKED_WORKTREE_DIRTY", "evidence": main_repo.get("status_porcelain")})

    active_gunicorn = [row for row in processes if row.get("comm") and "gunicorn" in str(row.get("comm")).casefold()]
    if len(active_gunicorn) > 1:
        findings.append({"severity": "REVIEW", "code": "MULTIPLE_GUNICORN_PROCESSES", "count": len(active_gunicorn), "note": "May be normal worker topology; compare unit owner and scheduler import behavior."})
    active_units = [row for row in services["units"] if row.get("ActiveState") == "active"]
    if not active_units:
        findings.append({"severity": "HIGH", "code": "NO_MATCHING_ACTIVE_SYSTEMD_UNIT", "evidence": "No active ZEL/Z-OS/ALIMI/Telegram/Gunicorn unit found by name."})

    frontend = frontend_lock()
    lock_values = frontend.get("allowed_values", {})
    if lock_values.get("APP_SOURCE_ROOT") and lock_values.get("APP_SOURCE_ROOT") != "/home/z/z/frontend/z-os-app-source":
        findings.append({"severity": "HIGH", "code": "FRONTEND_SOURCE_ROOT_LOCK_MISMATCH", "evidence": lock_values})
    if lock_values.get("APP_DEPLOY_ROOT_1") and lock_values.get("APP_DEPLOY_ROOT_1") != "/var/www/z-os-app":
        findings.append({"severity": "HIGH", "code": "FRONTEND_DEPLOY_ROOT_LOCK_MISMATCH", "evidence": lock_values})

    existing_web_roots = [row for row in map(stat_row, critical_paths[-4:]) if row.get("exists")]
    if len(existing_web_roots) > 1:
        findings.append({"severity": "HIGH", "code": "MULTIPLE_DEPLOYED_WEB_ROOTS_EXIST", "evidence": [row["path"] for row in existing_web_roots]})

    payload = {
        "schema_version": "1.0",
        "version": VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "host": socket.gethostname(),
        "expected_master_sha": EXPECTED_MASTER_SHA or None,
        "repositories": repo_rows,
        "services": services,
        "processes": processes,
        "ports": ports,
        "port_probe_error": port_probe["stderr"],
        "critical_paths": [stat_row(path) for path in critical_paths],
        "frontend_source_lock": frontend,
        "databases": db_rows,
        "database_file_owners": file_owners(databases),
        "findings": findings,
        "state": "HOLD_RUNTIME_REVIEW_REQUIRED" if any(row.get("severity") == "HIGH" for row in findings) else "PASS_RUNTIME_CENSUS_WITH_REVIEW_ITEMS",
        "safety": {
            "read_only": True,
            "remote_file_created": False,
            "service_changed": False,
            "process_changed": False,
            "database_changed": False,
            "deployment_changed": False,
            "canonical_mutated": False,
            "registry_mutated": False,
            "execution_allowed": False,
            "order_authority": "BLOCKED",
        },
        "next": "BIND_GIT_FILES_TO_ACTIVE_UNITS_AND_SINGLE_WRITERS_BEFORE_DELETE_OR_MERGE",
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
