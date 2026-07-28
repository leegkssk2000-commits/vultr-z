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

VERSION = "ZEL_ACTIVE_BACKEND_DYNAMIC_CENSUS_V2"
ROOT = Path(os.getenv("Z_HOME", "/home/z/z")).resolve()
ENTRY = Path(os.getenv("ACTIVE_BACKEND_ENTRY", str(ROOT / "backend/main.py"))).resolve()
LOCAL_PREFIXES = ("backend", "engine", "config", "ensemble", "strategies", "telegram", "routers", "api", "state")
MAX_FILES = 800
MAX_SOURCE_TOTAL = 12 * 1024 * 1024
MAX_SOURCE_FILE = 400 * 1024
MODULE_LITERAL_RE = re.compile(r"^(?:backend|engine|config|ensemble|strategies|telegram|routers|api|state)(?:\.[A-Za-z_][A-Za-z0-9_]*)+$")
ASSIGN_SECRET_RE = re.compile(r"(?im)^(\s*[A-Za-z_][A-Za-z0-9_]*(?:token|secret|password|passwd|api[_-]?key|private[_-]?key)[A-Za-z0-9_]*\s*=\s*)(.+)$")
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


def canonical_module(module: str) -> str:
    if module.startswith("routers."):
        return "backend." + module
    if module.startswith("api."):
        return "backend." + module
    if module.startswith("state."):
        return "backend." + module
    return module


def module_path(module: str) -> Path | None:
    module = canonical_module(module)
    if not module.startswith(LOCAL_PREFIXES):
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


def literal_modules(tree: ast.AST) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and MODULE_LITERAL_RE.match(node.value):
            modules.add(node.value)
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
            local_path = None
            if decorator.args and isinstance(decorator.args[0], ast.Constant) and isinstance(decorator.args[0].value, str):
                local_path = decorator.args[0].value
            owner = decorator.func.value.id if isinstance(decorator.func.value, ast.Name) else ast.unparse(decorator.func.value)
            rows.append({"method": method.upper(), "local_path": local_path, "function": node.name, "owner": owner, "line": node.lineno})
    return rows


def router_prefixes(tree: ast.Module) -> dict[str, str]:
    rows: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        value = node.value
        if not isinstance(value, ast.Call):
            continue
        name = None
        if isinstance(value.func, ast.Name):
            name = value.func.id
        elif isinstance(value.func, ast.Attribute):
            name = value.func.attr
        if name != "APIRouter":
            continue
        prefix = ""
        for keyword in value.keywords:
            if keyword.arg == "prefix" and isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
                prefix = keyword.value.value
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if isinstance(target, ast.Name):
                rows[target.id] = prefix
    return rows


def include_rows(tree: ast.AST) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute) or node.func.attr != "include_router" or not node.args:
            continue
        parent = node.func.value.id if isinstance(node.func.value, ast.Name) else ast.unparse(node.func.value)
        child = node.args[0].id if isinstance(node.args[0], ast.Name) else ast.unparse(node.args[0])
        prefix = ""
        for keyword in node.keywords:
            if keyword.arg == "prefix" and isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
                prefix = keyword.value.value
        rows.append({"parent": parent, "child": child, "include_prefix": prefix, "line": node.lineno})
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
    redacted_sources: dict[str, str] = {}
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

        discovered = sorted(literal_modules(tree))
        resolved_paths: list[str] = []
        for module in discovered:
            candidate = module_path(module)
            if candidate is not None:
                resolved = candidate.relative_to(ROOT).as_posix()
                if resolved not in resolved_paths:
                    resolved_paths.append(resolved)
                if candidate not in seen:
                    queue.append(candidate)
            elif module.startswith(LOCAL_PREFIXES):
                unresolved.append({"source": relative, "module": module})

        stat = path.stat()
        inventory.append({
            "path": relative,
            "sha256": sha256(path),
            "size_bytes": stat.st_size,
            "mtime_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat().replace("+00:00", "Z"),
            "tracked": relative in tracked,
            "git_status": git_status(relative),
            "imports_local": resolved_paths,
            "router_prefixes": router_prefixes(tree),
            "routes": route_rows(tree),
            "includes": include_rows(tree),
            "top_level_calls": [
                {"call": (node.value.func.id if isinstance(node.value.func, ast.Name) else node.value.func.attr if isinstance(node.value.func, ast.Attribute) else type(node.value.func).__name__), "line": node.lineno}
                for node in tree.body if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
            ],
        })
        encoded = text.encode("utf-8", errors="replace")
        if len(encoded) <= MAX_SOURCE_FILE and source_total + len(encoded) <= MAX_SOURCE_TOTAL:
            redacted_sources[relative] = redact(text)
            source_total += len(encoded)

    untracked = sorted(row["path"] for row in inventory if row.get("tracked") is False)
    dirty = sorted(row["path"] for row in inventory if row.get("git_status"))
    parse_errors = [row for row in inventory if row.get("parse_error")]
    findings: list[dict[str, Any]] = []
    if not ENTRY.is_file():
        findings.append({"severity": "CRITICAL", "code": "ACTIVE_ENTRY_MISSING", "path": str(ENTRY)})
    if untracked:
        findings.append({"severity": "CRITICAL", "code": "ACTIVE_DYNAMIC_CLOSURE_UNTRACKED", "count": len(untracked), "paths": untracked})
    if dirty:
        findings.append({"severity": "HIGH", "code": "ACTIVE_DYNAMIC_CLOSURE_DIRTY", "count": len(dirty), "paths": dirty})
    if parse_errors:
        findings.append({"severity": "CRITICAL", "code": "ACTIVE_SOURCE_PARSE_ERRORS", "count": len(parse_errors)})
    if len(seen) >= MAX_FILES:
        findings.append({"severity": "HIGH", "code": "CLOSURE_FILE_CAP_REACHED", "cap": MAX_FILES})

    payload = {
        "schema_version": "2.0",
        "version": VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "root": str(ROOT),
        "entry": str(ENTRY),
        "closure_file_count": len(inventory),
        "source_text_file_count": len(redacted_sources),
        "source_text_total_bytes": source_total,
        "inventory": sorted(inventory, key=lambda row: row["path"]),
        "unresolved_local_imports": unresolved,
        "redacted_sources": redacted_sources,
        "findings": findings,
        "state": "HOLD_ACTIVE_DYNAMIC_SOURCE_NOT_IN_GIT" if findings else "PASS_ACTIVE_DYNAMIC_SOURCE_CENSUS",
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
        "next": "RUN_OPENAPI_ROUTE_OWNERSHIP_AND_SECRET_GUARDED_EXPORT",
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
