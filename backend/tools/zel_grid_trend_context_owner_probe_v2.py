from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

VERSION = "ZEL_GRID_TREND_CONTEXT_OWNER_PROBE_V2"
SCHEMA = "zel.grid.trend_context_owner_probe.receipt.v2"
TARGET_KEYS = {"trend_strength", "trend_direction"}
SECRET_KEY = re.compile(r"(?i)(secret|token|password|api[_-]?key|private[_-]?key|credential)")
MAX_FILE_BYTES = 2_000_000


def stable_sha(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def dotted_name(node: ast.AST | None) -> str | None:
    if node is None:
        return None
    parts: list[str] = []
    value = node
    while isinstance(value, ast.Attribute):
        parts.append(value.attr)
        value = value.value
    if isinstance(value, ast.Name):
        parts.append(value.id)
    return ".".join(reversed(parts)) if parts else None


def call_name(node: ast.Call) -> str:
    return dotted_name(node.func) or type(node.func).__name__


def scalar_constants(node: ast.AST | None) -> dict[str, list[Any]]:
    strings: set[str] = set()
    numbers: set[float | int] = set()
    if node is not None:
        for child in ast.walk(node):
            if not isinstance(child, ast.Constant):
                continue
            value = child.value
            if isinstance(value, str) and value.strip():
                text = value.strip()
                strings.add("<redacted>" if SECRET_KEY.search(text) else text[:120])
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                if -1_000_000 <= float(value) <= 1_000_000:
                    numbers.add(value)
    return {"strings": sorted(strings), "numbers": sorted(numbers, key=float)}


def loaded_names(node: ast.AST | None) -> list[str]:
    values: set[str] = set()
    if node is not None:
        for child in ast.walk(node):
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                values.add(child.id)
            elif isinstance(child, ast.Attribute) and isinstance(child.ctx, ast.Load):
                values.add(child.attr)
    return sorted(values)


def get_calls(node: ast.AST | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if node is None:
        return rows
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        name = call_name(child)
        if not (name.endswith(".get") or name == "get"):
            continue
        key = None
        if child.args and isinstance(child.args[0], ast.Constant) and isinstance(child.args[0].value, str):
            key = child.args[0].value
            if SECRET_KEY.search(key):
                key = "<redacted>"
        default = scalar_constants(child.args[1]) if len(child.args) > 1 else {"strings": [], "numbers": []}
        rows.append(
            {
                "line": int(getattr(child, "lineno", 0) or 0),
                "base": name.removesuffix(".get"),
                "key": key,
                "default_strings": default["strings"],
                "default_numbers": default["numbers"],
            }
        )
    return sorted(rows, key=lambda row: (row["line"], row["base"], row["key"] or ""))


def fingerprint(node: ast.AST | None) -> dict[str, Any] | None:
    if node is None:
        return None
    constants = scalar_constants(node)
    return {
        "node_type": type(node).__name__,
        "loaded_names": loaded_names(node)[:120],
        "calls": sorted({call_name(child) for child in ast.walk(node) if isinstance(child, ast.Call)})[:120],
        "get_calls": get_calls(node)[:120],
        "strings": constants["strings"][:120],
        "numbers": constants["numbers"],
    }


def subscript_key(node: ast.Subscript) -> str | None:
    if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
        return node.slice.value
    return None


def target_key(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name) and node.id in TARGET_KEYS:
        return node.id
    if isinstance(node, ast.Attribute) and node.attr in TARGET_KEYS:
        return node.attr
    if isinstance(node, ast.Subscript):
        key = subscript_key(node)
        return key if key in TARGET_KEYS else None
    return None


def function_facts(function: ast.AST) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    writers: list[dict[str, Any]] = []
    readers: list[dict[str, Any]] = []
    for child in ast.walk(function):
        if isinstance(child, ast.Assign):
            for target in child.targets:
                key = target_key(target)
                if key:
                    writers.append({"key": key, "line": int(child.lineno), "kind": "assign", "value": fingerprint(child.value)})
        elif isinstance(child, ast.AnnAssign):
            key = target_key(child.target)
            if key:
                writers.append({"key": key, "line": int(child.lineno), "kind": "ann_assign", "value": fingerprint(child.value)})
        elif isinstance(child, ast.Dict):
            for key_node, value_node in zip(child.keys, child.values):
                if isinstance(key_node, ast.Constant) and key_node.value in TARGET_KEYS:
                    writers.append(
                        {
                            "key": key_node.value,
                            "line": int(getattr(key_node, "lineno", child.lineno)),
                            "kind": "dict",
                            "value": fingerprint(value_node),
                        }
                    )
        elif isinstance(child, ast.Call):
            name = call_name(child)
            if (name.endswith(".get") or name == "get") and child.args and isinstance(child.args[0], ast.Constant):
                key = child.args[0].value
                if key in TARGET_KEYS:
                    readers.append(
                        {
                            "key": key,
                            "line": int(child.lineno),
                            "kind": "get",
                            "base": name.removesuffix(".get"),
                        }
                    )
        elif isinstance(child, ast.Subscript):
            key = subscript_key(child)
            if key in TARGET_KEYS and isinstance(child.ctx, ast.Load):
                readers.append(
                    {
                        "key": key,
                        "line": int(getattr(child, "lineno", 0) or 0),
                        "kind": "subscript",
                        "base": dotted_name(child.value),
                    }
                )
    writers.sort(key=lambda row: (row["line"], row["key"], row["kind"]))
    readers.sort(key=lambda row: (row["line"], row["key"], row["kind"]))
    return writers, readers


def candidate_paths(root: Path) -> Iterable[Path]:
    if root.is_file() and root.suffix == ".py":
        yield root
        return
    if not root.is_dir():
        return
    skip = {".git", ".venv", "venv", "node_modules", "__pycache__", "archive", "archives", "backup", "backups"}
    for base, dirs, files in os.walk(root):
        dirs[:] = [name for name in dirs if name not in skip]
        for name in files:
            if not name.endswith(".py"):
                continue
            path = Path(base) / name
            try:
                stat = path.stat()
                if stat.st_size <= 0 or stat.st_size > MAX_FILE_BYTES:
                    continue
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if any(key in text for key in TARGET_KEYS):
                yield path


def frozen_root(terminal_root: Path) -> Path | None:
    report_path = terminal_root / "report.json"
    if not report_path.is_file():
        return None
    value = json.loads(report_path.read_text(encoding="utf-8"))
    source = value.get("source") if isinstance(value, Mapping) else None
    root = source.get("root") if isinstance(source, Mapping) else None
    if not isinstance(root, str):
        return None
    path = Path(root)
    return path.resolve() if path.is_absolute() else None


def scan_roots(runtime_root: Path, terminal_root: Path) -> list[tuple[str, Path]]:
    roots: list[tuple[str, Path]] = [
        ("runtime_tools", runtime_root / "tools"),
        ("runtime_backend", runtime_root / "backend"),
        ("runtime_engine", runtime_root / "engine"),
        ("research_runtime", Path("/opt/zel/research-runtime/data-b-v2")),
    ]
    frozen = frozen_root(terminal_root)
    if frozen is not None:
        roots.extend(
            [
                ("frozen_tools", frozen / "tools"),
                ("frozen_backend", frozen / "backend"),
                ("frozen_engine", frozen / "engine"),
            ]
        )
    output: list[tuple[str, Path]] = []
    seen: set[str] = set()
    for label, path in roots:
        key = str(path.resolve()) if path.exists() else str(path)
        if key in seen:
            continue
        seen.add(key)
        output.append((label, path))
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", type=Path, default=Path("/home/z/z"))
    parser.add_argument("--terminal-root", type=Path, default=Path("/var/lib/zel-research/data-b-1m-v2"))
    parser.add_argument("--out", type=Path)
    parser.add_argument("--stdout", action="store_true")
    args = parser.parse_args()

    files: list[dict[str, Any]] = []
    writers: list[dict[str, Any]] = []
    readers: list[dict[str, Any]] = []
    candidate_counts: dict[str, int] = {}
    seen_paths: set[str] = set()

    for label, root in scan_roots(args.runtime_root.resolve(), args.terminal_root.resolve()):
        count = 0
        for path in candidate_paths(root):
            resolved = str(path.resolve())
            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)
            count += 1
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:
                continue
            parent_class: dict[int, str] = {}
            for class_node in [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]:
                for child in ast.walk(class_node):
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        parent_class[id(child)] = class_node.name
            function_rows: list[dict[str, Any]] = []
            source_sha = sha256_file(path)
            for function in [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]:
                function_writers, function_readers = function_facts(function)
                if not function_writers and not function_readers:
                    continue
                function_meta = {
                    "class_name": parent_class.get(id(function)),
                    "function_name": function.name,
                    "function_line": int(function.lineno),
                }
                function_rows.append({**function_meta, "writers": function_writers, "readers": function_readers})
                base = {
                    "root_label": label,
                    "path": resolved,
                    "sha256": source_sha,
                    **function_meta,
                }
                writers.extend({**base, **row} for row in function_writers)
                readers.extend({**base, **row} for row in function_readers)
            files.append(
                {
                    "root_label": label,
                    "path": resolved,
                    "sha256": source_sha,
                    "functions": function_rows,
                    "raw_code_published": False,
                }
            )
        candidate_counts[label] = count

    writers.sort(key=lambda row: (row["key"], row["path"], row["line"]))
    readers.sort(key=lambda row: (row["key"], row["path"], row["line"]))
    writer_counts = {key: sum(row["key"] == key for row in writers) for key in sorted(TARGET_KEYS)}
    reader_counts = {key: sum(row["key"] == key for row in readers) for key in sorted(TARGET_KEYS)}
    blockers = [f"{key.upper()}_WRITER_NOT_FOUND" for key, count in writer_counts.items() if count == 0]

    receipt = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": "PASS_GRID_TREND_CONTEXT_OWNERS_FOUND" if not blockers else "HOLD_GRID_TREND_CONTEXT_OWNER_INCOMPLETE",
        "candidate_counts": candidate_counts,
        "candidate_file_count": len(files),
        "writer_counts": writer_counts,
        "reader_counts": reader_counts,
        "writers": writers[:300],
        "readers": readers[:300],
        "files": files[:300],
        "blockers": blockers,
        "raw_code_published": False,
        "raw_trade_rows_published": False,
        "canonical_mutated": False,
        "runtime_mutated": False,
        "formal_ledger_mutated": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
        "next": "MAP_TREND_CONTEXT_WRITERS_TO_FROZEN_PREFIX_FRAME" if not blockers else "RESOLVE_TREND_CONTEXT_OWNER_BLOCKERS",
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    encoded = json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(encoded, encoding="utf-8")
    if args.stdout or not args.out:
        print(encoded, end="")
    return 0 if not blockers else 1


if __name__ == "__main__":
    raise SystemExit(main())
