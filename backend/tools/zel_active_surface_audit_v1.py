from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "ZEL_ACTIVE_SURFACE_AUDIT_V1"
PORTS = {80, 443, 8000, 8787}
SECRET_RE = re.compile(r"(?i)(token|secret|password|passwd|api[_-]?key|private[_-]?key)(\s*[=:]\s*)([^\s,}]+)")
PID_RE = re.compile(r"pid=(\d+)")
PORT_RE = re.compile(r":(\d+)\b")
UNIT_RE = re.compile(r"/system\.slice/([^/]+\.service)")
MODULE_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_.]*):([A-Za-z_][A-Za-z0-9_]*)$")
ALLOWED_ENV = {"Z_HOME", "PYTHONPATH", "PORT", "APP_MODULE", "UVICORN_APP", "GUNICORN_CMD_ARGS", "ENVIRONMENT", "FLASK_ENV"}


def clean(value: str, limit: int = 50000) -> str:
    return SECRET_RE.sub(lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]", value)[:limit]


def run(command: list[str], timeout: int = 20) -> tuple[int, str, str]:
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


def proc_text(pid: int, name: str, binary: bool = False) -> str:
    path = Path(f"/proc/{pid}/{name}")
    try:
        if binary:
            return path.read_bytes().replace(b"\0", b" ").decode("utf-8", errors="replace").strip()
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def process_row(pid: int) -> dict[str, Any]:
    command = clean(proc_text(pid, "cmdline", binary=True))
    cgroup = proc_text(pid, "cgroup")
    unit_match = UNIT_RE.search(cgroup)
    env: dict[str, str] = {}
    try:
        for item in Path(f"/proc/{pid}/environ").read_bytes().split(b"\0"):
            if b"=" not in item:
                continue
            key, value = item.split(b"=", 1)
            key_text = key.decode("utf-8", errors="replace")
            if key_text in ALLOWED_ENV:
                env[key_text] = clean(value.decode("utf-8", errors="replace"), 2000)
    except OSError:
        pass
    try:
        cwd = os.readlink(f"/proc/{pid}/cwd")
    except OSError:
        cwd = None
    try:
        executable = os.readlink(f"/proc/{pid}/exe")
    except OSError:
        executable = None
    status = proc_text(pid, "status")
    ppid_match = re.search(r"^PPid:\s*(\d+)$", status, re.M)
    return {
        "pid": pid,
        "ppid": int(ppid_match.group(1)) if ppid_match else None,
        "command": command,
        "cwd": cwd,
        "executable": executable,
        "systemd_unit": unit_match.group(1) if unit_match else None,
        "cgroup": clean(cgroup, 10000),
        "allowed_env": env,
    }


def ancestry(pid: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[int] = set()
    current = pid
    while current > 0 and current not in seen and len(rows) < 12:
        seen.add(current)
        row = process_row(current)
        rows.append(row)
        parent = row.get("ppid")
        if not isinstance(parent, int) or parent <= 0 or parent == current:
            break
        current = parent
    return rows


def listener_rows() -> list[dict[str, Any]]:
    rc, stdout, stderr = run(["ss", "-ltnp"])
    if rc != 0:
        return [{"error": clean(stderr)}]
    rows: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        ports = [int(value) for value in PORT_RE.findall(line)]
        selected = sorted(set(ports) & PORTS)
        if not selected:
            continue
        pids = sorted({int(value) for value in PID_RE.findall(line)})
        rows.append({"ports": selected, "raw": clean(line), "pids": pids, "processes": [process_row(pid) for pid in pids]})
    return rows


def module_sources(process: dict[str, Any]) -> list[dict[str, Any]]:
    command = str(process.get("command") or "")
    cwd = Path(process.get("cwd") or "/")
    candidates: set[Path] = set()
    tokens = command.split()
    for token in tokens:
        module = MODULE_RE.match(token)
        if module:
            relative = Path(*module.group(1).split(".")).with_suffix(".py")
            candidates.add(cwd / relative)
            candidates.add(Path("/home/z/z") / relative)
        if token.startswith("/") and token.endswith(".py"):
            candidates.add(Path(token))
    rows: list[dict[str, Any]] = []
    for path in sorted(candidates):
        if not path.is_file():
            continue
        try:
            stat = path.stat()
            rows.append({
                "path": str(path),
                "realpath": str(path.resolve()),
                "size_bytes": stat.st_size,
                "mtime_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat().replace("+00:00", "Z"),
                "sha256": sha256(path),
            })
        except OSError:
            continue
    return rows


def http_probe(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "zel-active-surface-audit/1.0", "Accept": "application/json,text/plain,*/*"})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            body = response.read(4096)
            return {
                "url": url,
                "status": response.status,
                "headers": {key.lower(): clean(value, 2000) for key, value in response.headers.items() if key.lower() in {"server", "content-type", "x-zel-root", "cache-control"}},
                "body_prefix": clean(body.decode("utf-8", errors="replace"), 4096),
            }
    except urllib.error.HTTPError as exc:
        return {"url": url, "status": exc.code, "error": clean(str(exc))}
    except (urllib.error.URLError, OSError) as exc:
        return {"url": url, "status": None, "error": clean(str(exc))}


def caddy_config() -> dict[str, Any]:
    path = Path("/etc/caddy/Caddyfile")
    row: dict[str, Any] = {"path": str(path), "exists": path.is_file()}
    if not path.is_file():
        return row
    try:
        text = clean(path.read_text(encoding="utf-8", errors="replace"), 100000)
        row["sha256"] = sha256(path)
        row["content_redacted"] = text
        row["reverse_proxy_targets"] = sorted(set(re.findall(r"\breverse_proxy\s+([^\s{]+)", text)))
        row["root_targets"] = sorted(set(re.findall(r"\broot\s+\*?\s*([^\s{]+)", text)))
        row["site_labels"] = sorted(set(re.findall(r"(?m)^\s*([A-Za-z0-9.*_-]+(?:\.[A-Za-z0-9.*_-]+)+)\s*\{", text)))
    except OSError as exc:
        row["error"] = clean(str(exc))
    return row


def main() -> int:
    listeners = listener_rows()
    processes: dict[int, dict[str, Any]] = {}
    for listener in listeners:
        for process in listener.get("processes", []):
            if process.get("pid") is not None:
                processes[int(process["pid"])] = process
    process_details: list[dict[str, Any]] = []
    for pid, process in sorted(processes.items()):
        process_details.append({**process, "ancestry": ancestry(pid), "module_sources": module_sources(process)})

    probes = []
    for port in (8000, 8787):
        for path in ("/health", "/healthz", "/"):
            probes.append(http_probe(f"http://127.0.0.1:{port}{path}"))

    caddy = caddy_config()
    findings: list[dict[str, Any]] = []
    port8000 = [row for row in listeners if 8000 in row.get("ports", [])]
    if not port8000:
        findings.append({"severity": "HIGH", "code": "PORT_8000_NO_LISTENER"})
    for process in process_details:
        if any(8000 in row.get("ports", []) and process.get("pid") in row.get("pids", []) for row in listeners):
            if not process.get("systemd_unit"):
                findings.append({"severity": "HIGH", "code": "PORT_8000_PROCESS_WITHOUT_SYSTEMD_OWNER", "pid": process.get("pid"), "command": process.get("command")})
            if not process.get("module_sources"):
                findings.append({"severity": "HIGH", "code": "PORT_8000_SOURCE_NOT_RESOLVED", "pid": process.get("pid"), "command": process.get("command")})
    roots = caddy.get("root_targets", []) if isinstance(caddy.get("root_targets"), list) else []
    if len(roots) > 1:
        findings.append({"severity": "REVIEW", "code": "CADDY_MULTIPLE_ROOT_TARGETS", "targets": roots})

    payload = {
        "schema_version": "1.0",
        "version": VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "listeners": listeners,
        "process_details": process_details,
        "http_probes": probes,
        "caddy": caddy,
        "findings": findings,
        "state": "HOLD_ACTIVE_SURFACE_REVIEW_REQUIRED" if any(row.get("severity") == "HIGH" for row in findings) else "PASS_ACTIVE_SURFACE_CENSUS_WITH_REVIEW_ITEMS",
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
        "next": "COMPARE_ACTIVE_SOURCE_HASHES_WITH_GIT_AND_BIND_CADDY_ROOTS_TO_SINGLE_DEPLOY_AUTHORITY",
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
