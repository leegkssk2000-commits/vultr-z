#!/usr/bin/env python3
from __future__ import annotations

import ast
import base64
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

ROOT = Path(os.environ.get("G0_ROOT", "/home/z/z")).resolve()
MAX_SCAN_BYTES = 2_000_000
SENSITIVE_NAME_RE = re.compile(r"(?:secret|password|passwd|api[_-]?key|token|private[_-]?key|access[_-]?key)", re.I)
TEXT_SECRET_PATTERNS = {
    "PRIVATE_KEY_BLOCK": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "OPENAI_STYLE_KEY": re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "GOOGLE_API_KEY": re.compile(rb"\bAIza[A-Za-z0-9_-]{30,}\b"),
    "GITHUB_TOKEN": re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    "SLACK_TOKEN": re.compile(rb"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    "AWS_ACCESS_KEY": re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
}


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def stable_sha(value: Any) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())


def decode_env_json(name: str) -> Any:
    return json.loads(base64.b64decode(os.environ[name].encode("ascii")).decode("utf-8"))


def source_paths(pin: dict[str, Any], inv: dict[str, Any]) -> list[str]:
    paths: set[str] = set()
    for module in pin.get("modules", []):
        for raw in module.get("source_paths", []):
            rel = str(raw)
            if not rel.startswith("external:"):
                paths.add(rel)
    for name in inv.get("historical_implementation_inventory_25", []):
        paths.add(f"backend/strategies/{name}.py")
    return sorted(paths)


def python_literal_secret_names(text: str) -> list[str]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    found: set[str] = set()
    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value = node.value
        if value is None or not isinstance(value, ast.Constant) or not isinstance(value.value, str) or not value.value:
            continue
        names: list[str] = []
        for target in targets:
            if isinstance(target, ast.Name):
                names.append(target.id)
            elif isinstance(target, ast.Attribute):
                names.append(target.attr)
        for name in names:
            if SENSITIVE_NAME_RE.search(name):
                found.add(name)
    return sorted(found)


def scan(rel: str) -> dict[str, Any]:
    path = ROOT / rel
    if not path.is_file():
        return {"path": rel, "state": "MISSING_RUNTIME", "size_bytes": None, "sha256": None, "secret_pattern_categories": [], "sensitive_literal_names": [], "syntax_state": "NOT_SCANNED"}
    raw = path.read_bytes()
    if len(raw) > MAX_SCAN_BYTES:
        return {"path": rel, "state": "BLOCK_TOO_LARGE", "size_bytes": len(raw), "sha256": sha256(raw), "secret_pattern_categories": [], "sensitive_literal_names": [], "syntax_state": "NOT_SCANNED"}
    categories = [name for name, rx in TEXT_SECRET_PATTERNS.items() if rx.search(raw)]
    syntax_state = "NOT_APPLICABLE"
    sensitive_literal_names: list[str] = []
    if path.suffix == ".py":
        try:
            text = raw.decode("utf-8")
            ast.parse(text)
            syntax_state = "PASS_PYTHON_AST"
            sensitive_literal_names = python_literal_secret_names(text)
        except (UnicodeDecodeError, SyntaxError):
            syntax_state = "FAIL_PYTHON_AST"
    elif path.suffix == ".json":
        try:
            json.loads(raw.decode("utf-8"))
            syntax_state = "PASS_JSON"
        except Exception:
            syntax_state = "FAIL_JSON"
    blockers = []
    if categories:
        blockers.append("SECRET_PATTERN")
    if sensitive_literal_names:
        blockers.append("SENSITIVE_LITERAL_ASSIGNMENT")
    if syntax_state.startswith("FAIL_"):
        blockers.append("SYNTAX_OR_PARSE")
    return {
        "path": rel,
        "state": "SAFE_TO_STAGE_FOR_PRIVATE_REVIEW" if not blockers else "BLOCK_REVIEW_REQUIRED",
        "size_bytes": len(raw),
        "sha256": sha256(raw),
        "secret_pattern_categories": categories,
        "sensitive_literal_names": sensitive_literal_names,
        "syntax_state": syntax_state,
        "blockers": blockers,
    }


def main() -> int:
    pin = decode_env_json("EXPECTED_PIN_B64")
    inv = decode_env_json("LEGACY25_B64")
    rows = [scan(rel) for rel in source_paths(pin, inv)]
    safe = [r for r in rows if r["state"] == "SAFE_TO_STAGE_FOR_PRIVATE_REVIEW"]
    review = [r for r in rows if r["state"] == "BLOCK_REVIEW_REQUIRED"]
    missing = [r for r in rows if r["state"] == "MISSING_RUNTIME"]
    result: dict[str, Any] = {
        "schema_version": "zel.g0.runtime_source_safety_scan.v1",
        "state": "PASS_SOURCE_SAFETY_SCAN" if not review else "HOLD_SOURCE_SAFETY_REVIEW",
        "source_count": len(rows),
        "safe_to_stage_private_review_count": len(safe),
        "review_required_count": len(review),
        "missing_runtime_count": len(missing),
        "rows": rows,
        "public_repository_publish_authority": False,
        "runtime_mutated": False,
        "destructive_cleanup_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    result["receipt_sha256"] = stable_sha(result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
