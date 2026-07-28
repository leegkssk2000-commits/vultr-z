from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import subprocess
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "ZEL_ACTIVE_BACKEND_SOURCE_CENSUS_V1"
ROOT = Path(os.getenv("Z_HOME", "/home/z/z")).resolve()
ENTRY = Path(os.getenv("ACTIVE_BACKEND_ENTRY", str(ROOT / "backend/main.py"))).resolve()
LOCAL_PREFIXES = ("backend", "engine", "config", "ensemble", "strategies", "telegram")
MAX_FILES = 300
MAX_SOURCE_TOTAL = 3 * 1024 * 1024
MAX_SOURCE_FILE = 220 * 1024
SECRET_NAME_RE = re.compile(r"(?i)(token|secret|password|passwd|api[_-]?key|private[_-]?key|client[_-]?secret)")
ASSIGN_SECRET_RE = re.compile(r"(?im)^(\s*[A-Za-z_][A-Za-z0-9_]*(?:token|secret|password|passwd|key)[A-Za-z0-9_]*\s*=\s*)(.+)$")
DICT_SECRET_RE = re.compile(r"(?i)([\"'][^\"']*(?:token|secret|password|passwd|api[_-]?key|private[_-]?key)[^\"']*[\"']\s*:\s*)([\"'][^\"']*[\"']|[^,}\n]+)")
BEARER_RE = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{12,}")
URL_CRED_RE = re.compile(r"(https?://)([^/@:\s]+):([^/@\s]+)@")


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


def redact(text: str) -> str:
    text = ASSIGN_SECRET_RE.sub(lambda match: match.group(1) + "'[REDACTED]'", text)
    text = DICT_SECRET_RE.sub(lambda match: match.group(1) + "'[REDACTED]'", text)
    text = BEARER_RE.sub(lambda match: match.group(1) + "[REDACTED]", text)
    text = URL_CRED_RE.sub(lambda match: match.group(1) + "[REDACTED]@", text)
    return text


def module_path(module: str) -> Path | None:
    if not module or not module.startswith(LOCAL_PREFIXES):
        return None
    relative = Path(*module.split("."))
    for candidate in (ROOT / relative.with_suffix(".py"), ROOT / relative / "__init__.py"):
        if candidate.is_file():
            try:
                candidate.resolve().relative_to(ROOT)
            except ValueError:
                continue
            return candidate.resolve()
    return None


def imported_modules(tree: ast.AST) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                modules.add(node.module)
                for alias in node.names:
                    modules.add(f"{node.module}.{alias.name}")
    return modules


def route_rows(tree: ast.AST) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
                continue
            method = decorator.func.attr.lower()
            if method not in {"get", "post", "put", "patch", "delete", "route", "websocket"}:
                continue
            path = None
            if decorator.args and isinstance(decorator.args[0], ast.Constant) and isinstance(decorator.args[0].value, str):
                path = decorator.args[0].value
            rows.append({"method": method.upper(), "path": path, "function": node.name, "line": node.lineno})
    return rows


def top_level_calls(tree: ast.Module) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for node in tree.body:
        call = node.value if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) else None
        if call is None:
            continue
        if isinstance(call.func, ast.Name):
            name = call.func.id
        elif isinstance(call.func, ast.Attribute):
            name = call.func.attr
        else:
            name = type(call.func).__name__
        rows.append({"call": name, "line": node.lineno})
    return rows


def git_tracked() -> set[str]:
    rc, stdout, _ = run(["git", "-C", str(ROOT), "ls-files"])
    return set(stdout.splitlines()) if rc == 0 else set()


def git_status(relative: str) -> str:
    rc, stdout, _ = run(["git", "-C", str(ROOT), "status", "--porcelain=v1", "--", relative])
    return stdout.strip() if rc == 0 else ""


def main() -> int:
    tracked = git_tracked()
    queue: deque[Path] = deque([ENTRY])
    seen: set[Path] = set()
    inventory: list[dict[str, Any]] = []
    sources: dict[str, str] = {}
    unresolved: list[dict[str, Any]] = []
    source_total = 0

    while queue and len(seen) < MAX_FILES:
        path = queue.popleft().resolve()
        if path in seen or not path.is_file():
            continue
        try:
            relative = path.relative_to(ROOT).as_posix()
        except ValueError:
            continue
        seen.add(path)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(text, filename=relative)
        except (OSError, SyntaxError) as exc:
            inventory.append({"path": relative, "parse_error": str(exc), "tracked": relative in tracked})
            continue

        modules = sorted(imported_modules(tree))
        resolved: list[str] = []
        for module in modules:
            candidate = module_path(module)
            if candidate is not None:
                resolved_relative = candidate.relative_to(ROOT).as_posix()
                if resolved_relative not in resolved:
                    resolved.append(resolved_relative)
                if candidate not in seen:
                    queue.append(candidate)
            elif module.startswith(LOCAL_PREFIXES):
                unresolved.append({"source": relative, "module": module})

        definitions = [
            {"kind": type(node).__name__, "name": node.name, "line": node.lineno}
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        ]
        stat = path.stat()
        status = git_status(relative)
        row = {
            "path": relative,
            "absolute_path": str(path),
            "sha256": sha256(path),
            "size_bytes": stat.st_size,
            "mtime_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat().replace("+00:00", "Z"),
            "tracked": relative in tracked,
            "git_status": status,
            "imports_local": resolved,
            "definitions": definitions,
            "routes": route_rows(tree),
            "top_level_calls": top_level_calls(tree),
        }
        inventory.append(row)

        encoded = text.encode("utf-8", errors="replace")
        if len(encoded) <= MAX_SOURCE_FILE and source_total + len(encoded) <= MAX_SOURCE_TOTAL:
            sources[relative] = redact(text)
            source_total += len(encoded)

    untracked = [row["path"] for row in inventory if row.get("tracked") is False]
    dirty = [row["path"] for row in inventory if row.get("git_status")]
    route_index: dict[str, list[dict[str, Any]]] = {}
    for row in inventory:
        for route in row.get("routes", []):
            key = f"{route.get('method')} {route.get('path')}"
            route_index.setdefault(key, []).append({"path": row["path"], **route})
    duplicate_routes = {key: rows for key, rows in route_index.items() if len(rows) > 1 and not key.endswith(" None")}

    findings: list[dict[str, Any]] = []
    entry_relative = ENTRY.relative_to(ROOT).as_posix() if ENTRY.is_relative_to(ROOT) else str(ENTRY)
    if entry_relative not in tracked:
        findings.append({"severity": "CRITICAL", "code": "ACTIVE_ENTRY_UNTRACKED", "path": entry_relative})
    if untracked:
        findings.append({"severity": "HIGH", "code": "ACTIVE_IMPORT_CLOSURE_UNTRACKED", "count": len(untracked), "paths": untracked})
    if dirty:
        findings.append({"severity": "HIGH", "code": "ACTIVE_IMPORT_CLOSURE_DIRTY", "count": len(dirty), "paths": dirty})
    if unresolved:
        findings.append({"severity": "REVIEW", "code": "LOCAL_IMPORTS_UNRESOLVED", "count": len(unresolved)})
    if duplicate_routes:
        findings.append({"severity": "HIGH", "code": "DUPLICATE_ACTIVE_ROUTES", "count": len(duplicate_routes), "routes": duplicate_routes})

    payload = {
        "schema_version": "1.0",
        "version": VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "root": str(ROOT),
        "entry": str(ENTRY),
        "entry_exists": ENTRY.is_file(),
        "closure_file_count": len(inventory),
        "source_text_file_count": len(sources),
        "source_text_total_bytes": source_total,
        "inventory": sorted(inventory, key=lambda row: row["path"]),
        "unresolved_local_imports": unresolved,
        "duplicate_routes": duplicate_routes,
        "redacted_sources": sources,
        "findings": findings,
        "state": "HOLD_ACTIVE_SOURCE_NOT_IN_GIT" if any(row.get("severity") in {"CRITICAL", "HIGH"} for row in findings) else "PASS_ACTIVE_SOURCE_CENSUS",
        "safety": {
            "read_only": True,
            "remote_file_created": False,
            "service_changed": False,
            "process_changed": False,
            "database_changed": False,
            "deployment_changed": False,
            "execution_allowed": False,
            "order_authority": "BLOCKED",
            "secret_values_redacted": True,
        },
        "next": "IMPORT_VERIFIED_ACTIVE_CLOSURE_TO_GIT_WITHOUT_DEPLOYING_OR_RESTARTING",
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
