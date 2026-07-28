from __future__ import annotations

import ast
import base64
import hashlib
import json
import math
import os
import re
import subprocess
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "ZEL_ACTIVE_SOURCE_EXPORT_GUARD_V1"
ROOT = Path(os.getenv("Z_HOME", "/home/z/z")).resolve()
ENTRY = Path(os.getenv("ACTIVE_BACKEND_ENTRY", str(ROOT / "backend/main.py"))).resolve()
LOCAL_PREFIXES = ("backend", "engine", "config", "ensemble", "strategies", "telegram", "routers", "api", "state")
MODULE_LITERAL_RE = re.compile(r"^(?:backend|engine|config|ensemble|strategies|telegram|routers|api|state)(?:\.[A-Za-z_][A-Za-z0-9_]*)+$")
SECRET_NAME_RE = re.compile(r"(?i)(token|secret|password|passwd|api[_-]?key|private[_-]?key|client[_-]?secret|access[_-]?key)")
HIGH_RISK_PATTERNS = {
    "PRIVATE_KEY_BLOCK": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "OPENAI_KEY": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "GITHUB_TOKEN": re.compile(r"\bgh[opusr]_[A-Za-z0-9]{30,}\b"),
    "AWS_ACCESS_KEY": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "TELEGRAM_BOT_TOKEN": re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{30,}\b"),
    "BEARER_LITERAL": re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{24,}"),
    "URL_CREDENTIALS": re.compile(r"https?://[^/@:\s]{3,}:[^/@\s]{3,}@"),
}
MAX_FILES = 800
MAX_TOTAL_BYTES = 20 * 1024 * 1024


def run(command: list[str], timeout: int = 20) -> tuple[int, str, str]:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
        return result.returncode, result.stdout, result.stderr
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, "", str(exc)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_module(module: str) -> str:
    if module.startswith(("routers.", "api.", "state.")):
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


def modules(tree: ast.AST) -> set[str]:
    rows: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            rows.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            rows.add(node.module)
            rows.update(f"{node.module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and MODULE_LITERAL_RE.match(node.value):
            rows.add(node.value)
    return rows


def shannon_entropy(value: str) -> float:
    if not value:
        return 0.0
    counts = {char: value.count(char) for char in set(value)}
    return -sum((count / len(value)) * math.log2(count / len(value)) for count in counts.values())


def safe_secret_literal(value: str) -> bool:
    low = value.casefold().strip()
    if not low or low in {"none", "null", "changeme", "replace_me", "[redacted]", "disabled"}:
        return True
    if value.startswith(("/", "./", "../")) or any(value.endswith(suffix) for suffix in (".json", ".txt", ".key", ".pem", ".env", ".secret")):
        return True
    if re.fullmatch(r"[A-Z][A-Z0-9_]{3,}", value):
        return True
    return False


def assignment_name(target: ast.AST) -> str | None:
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    if isinstance(target, ast.Subscript) and isinstance(target.slice, ast.Constant):
        return str(target.slice.value)
    return None


def scan_file(relative: str, text: str, tree: ast.AST) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    for code, pattern in HIGH_RISK_PATTERNS.items():
        for match in pattern.finditer(text):
            blockers.append({"path": relative, "code": code, "line": text.count("\n", 0, match.start()) + 1})
    for node in ast.walk(tree):
        targets: list[ast.AST] = []
        value: ast.AST | None = None
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value = node.value
        if not targets or value is None:
            continue
        names = [name for target in targets if (name := assignment_name(target))]
        if not any(SECRET_NAME_RE.search(name) for name in names):
            continue
        literal = value.value if isinstance(value, ast.Constant) and isinstance(value.value, str) else None
        if literal is None or safe_secret_literal(literal):
            continue
        if len(literal) >= 12 and (shannon_entropy(literal) >= 3.2 or re.search(r"[A-Za-z].*\d|\d.*[A-Za-z]", literal)):
            blockers.append({
                "path": relative,
                "code": "SECRET_NAMED_HIGH_ENTROPY_LITERAL",
                "line": getattr(node, "lineno", None),
                "names": names,
                "length": len(literal),
                "entropy": round(shannon_entropy(literal), 3),
            })
    return blockers


def git_status(relative: str) -> str:
    rc, stdout, _ = run(["git", "-C", str(ROOT), "status", "--porcelain=v1", "--", relative])
    return stdout.strip() if rc == 0 else ""


def main() -> int:
    queue: deque[Path] = deque([ENTRY])
    seen: set[Path] = set()
    files: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    total_bytes = 0

    while queue and len(seen) < MAX_FILES:
        path = queue.popleft().resolve()
        if path in seen or not path.is_file():
            continue
        try:
            relative = path.relative_to(ROOT).as_posix()
        except ValueError:
            continue
        seen.add(path)
        data = path.read_bytes()
        total_bytes += len(data)
        try:
            text = data.decode("utf-8")
            tree = ast.parse(text, filename=relative)
        except (UnicodeDecodeError, SyntaxError) as exc:
            blockers.append({"path": relative, "code": "SOURCE_PARSE_OR_ENCODING_FAIL", "error": str(exc)})
            continue
        blockers.extend(scan_file(relative, text, tree))
        for module in modules(tree):
            candidate = module_path(module)
            if candidate is not None and candidate not in seen:
                queue.append(candidate)
        files.append({
            "path": relative,
            "sha256": sha256_bytes(data),
            "size_bytes": len(data),
            "git_status": git_status(relative),
            "content_b64": base64.b64encode(data).decode("ascii"),
        })

    if total_bytes > MAX_TOTAL_BYTES:
        blockers.append({"code": "EXPORT_TOTAL_SIZE_CAP_EXCEEDED", "total_bytes": total_bytes, "cap": MAX_TOTAL_BYTES})
    if len(seen) >= MAX_FILES:
        blockers.append({"code": "EXPORT_FILE_CAP_REACHED", "count": len(seen), "cap": MAX_FILES})

    export_allowed = not blockers
    if not export_allowed:
        for row in files:
            row.pop("content_b64", None)

    payload = {
        "schema_version": "1.0",
        "version": VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "root": str(ROOT),
        "entry": str(ENTRY),
        "file_count": len(files),
        "total_bytes": total_bytes,
        "export_allowed": export_allowed,
        "blockers": blockers,
        "files": sorted(files, key=lambda row: row["path"]),
        "state": "PASS_SECRET_GUARD_EXPORT_READY" if export_allowed else "HOLD_SECRET_GUARD_BLOCKED",
        "safety": {
            "read_only": True,
            "remote_file_created": False,
            "service_changed": False,
            "process_changed": False,
            "database_changed": False,
            "deployment_changed": False,
            "execution_allowed": False,
            "order_authority": "BLOCKED",
            "source_content_emitted_only_when_guard_passes": True,
        },
        "next": "CREATE_NONDEPLOYING_GIT_RECOVERY_BRANCH_FROM_VERIFIED_HASHED_SOURCES" if export_allowed else "REMOVE_OR_EXTERNALIZE_BLOCKED_SECRET_LITERALS_FIRST",
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
