from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

VERSION = "ZEL_GRID_TREND_CONTEXT_OWNER_PROBE_V1"
SCHEMA = "zel.grid.trend_context_owner_probe.receipt.v1"
TARGET_KEYS = {"trend_strength", "trend_direction"}
SECRET_KEY = re.compile(r"(?i)(secret|token|password|api[_-]?key|private[_-]?key|credential)")
MAX_FILE_BYTES = 2_000_000
MAX_FILES_PER_ROOT = 10000


def stable_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


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


def strings(node: ast.AST | None) -> list[str]:
    if node is None:
        return []
    output: set[str] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Constant) or not isinstance(child.value, str):
            continue
        value = child.value.strip()
        if not value:
            continue
        if SECRET_KEY.search(value):
            value = "<redacted>"
        elif len(value) > 120:
            value = value[:120] + "…"
        output.add(value)
    return sorted(output)


def numbers(node: ast.AST | None) -> list[float | int]:
    if node is None:
        return []
    output: set[float | int] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Constant):
            continue
        value = child.value
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        if -1_000_000 <= float(value) <= 1_000_000:
            output.add(value)
    return sorted(output, key=float)


def loaded_names(node: ast.AST | None) -> list[str]:
    if node is None:
        return []
    values: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
            values.add(child.id)
        elif isinstance(child, ast.Attribute) and isinstance(child.ctx, ast.Load):
            values.add(child.attr)
    return sorted(values)


def calls(node: ast.AST | None) -> list[str]:
    if node is None:
        return []
    return sorted({call_name(child) for child in ast.walk(node) if isinstance(child, ast.Call)})


def get_calls(node: ast.AST | None) -> list[dict[str, Any]]:
    if node is None:
        return []
    rows: list[dict[str, Any]] = []
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
        rows.append(
            {
                "line": int(getattr(child, "lineno", 0) or 0),
                "base": name.removesuffix(".get"),
                "key": key,
                "default_strings": strings(child.args[1]) if len(child.args) > 1 else [],
                "default_numbers": numbers(child.args[1]) if len(child.args) > 1 else [],
                "default_loaded_names": loaded_names(child.args[1]) if len(child.args) > 1 else [],
            }
        )
    return sorted(rows, key=lambda row: (row["line"], row["base"], row["key"] or ""))


def expression(node: ast.AST | None) -> dict[str, Any] | None:
    if node is None:
        return None
    operators: set[str] = set()
    compare_operators: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.BinOp):
            operators.add(type(child.op).__name__)
        elif isinstance(child, ast.BoolOp):
            operators.add(type(child.op).__name__)
        elif isinstance(child, ast.UnaryOp):
            operators.add(type(child.op).__name__)
        elif isinstance(child, ast.Compare):
            compare_operators.update(type(value).__name__ for value in child.ops)
    return {
        "node_type": type(node).__name__,
        "loaded_names": loaded_names(node)[:160],
        "calls": calls(node)[:160],
        "get_calls": get_calls(node)[:160],
        "strings": strings(node)[:160],
        "numbers": numbers(node),
        "operators": sorted(operators),
        "compare_operators": sorted(compare_operators),
    }


def subscript_key(node: ast.Subscript) -> str | None:
    value = node.slice
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return value.value
    return None


def target_key(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name) and node.id in TARGET_KEYS:
        return node.id
    if isinstance(node, ast.Attribute) and node.attr in TARGET_KEYS:
        return node.attr
    if isinstance(node, ast.Subscript):
        key = subscript_key(node)
        if key in TARGET_KEYS:
            return key
    return None


def writer_rows(function: ast.AST) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for child in ast.walk(function):
        if isinstance(child, ast.Assign):
            for target in child.targets:
                key = target_key(target)
                if key:
                    rows.append({"key": key, "line": int(child.lineno), "kind": "assign", "value": expression(child.value)})
        elif isinstance(child, ast.AnnAssign):
            key = target_key(child.target)
            if key:
                rows.append({"key": key, "line": int(child.lineno), "kind": "ann_assign", "value": expression(child.value)})
        elif isinstance(child, ast.Dict):
            for key_node, value_node in zip(child.keys, child.values):
                if isinstance(key_node, ast.Constant) and key_node.value in TARGET_KEYS:
                    rows.append({"key": key_node.value, "line": int(getattr(key_node, "lineno", child.lineno)), "kind": "dict", "value": expression(value_node)})
        elif isinstance(child, ast.Call):
            name = call_name(child)
            if name.endswith(".update") and child.args and isinstance(child.args[0], ast.Dict):
                for key_node, value_node in zip(child.args[0].keys, child.args[0].values):
                    if isinstance(key_node, ast.Constant) and key_node.value in TARGET_KEYS:
                        rows.append({"key": key_node.value, "line": int(child.lineno), "kind": "update", "value": expression(value_node)})
            for keyword in child.keywords:
                if keyword.arg in TARGET_KEYS:
                    rows.append({"key": keyword.arg, "line": int(child.lineno), "kind": "keyword", "value": expression(keyword.value)})
    return sorted(rows, key=lambda row: (row["line"], row["key"], row["kind"]))


def reader_rows(function: ast.AST) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for child in ast.walk(function):
        if isinstance(child, ast.Call):
            name = call_name(child)
            if (name.endswith(".get") or name == "get") and child.args and isinstance(child.args[0], ast.Constant):
                key = child.args[0].value
                if key in TARGET_KEYS:
                    rows.append({"key": key, "line": int(child.lineno), "kind": "get", "base": name.removesuffix(".get")})
        elif isinstance(child, ast.Subscript):
            key = subscript_key(child)
            if key in TARGET_KEYS and isinstance(child.ctx, ast.Load):
                rows.append({"key": key, "line": int(getattr(child, "lineno", 0) or 0), "kind": "subscript", "base": dotted_name(child.value)})
    return sorted(rows, key=lambda row: (row["line"], row["key"], row["kind"]))


def file_record(path: Path, root_label: str) -> dict[str, Any] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    if stat.st_size <= 0 or stat.st_size > MAX_FILE_BYTES:
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    if not any(key in text for key in TARGET_KEYS):
        return None
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return {
            "root_label": root_label,
            "path": str(path.resolve()),
            "sha256": sha256_file(path),
            "size_bytes": stat.st_size,
            "parse_error": f"{type(exc).__name__}:{exc.lineno}",
            "functions": [],
            "raw_code_published": False,
        }
    parent_class: dict[int, str] = {}
    for class_node in [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]:
        for child in ast.walk(class_node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                parent_class[id(child)] = class_node.name
    functions: list[dict[str, Any]] = []
    module_writers = writer_rows(tree)
    module_readers = reader_rows(tree)
    for function in [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        writers = writer_rows(function)
        readers = reader_rows(function)
        if not writers and not readers:
            continue
        functions.append(
            {
                "class_name": parent_class.get(id(function)),
                "function_name": function.name,
                "line": int(function.lineno),
                "arguments": [
                    argument.arg
                    for argument in [
                        *function.args.posonlyargs,
                        *function.args.args,
                        *function.args.kwonlyargs,
                    ]
                ],
                "writers": writers,
                "readers": readers,
                "calls": calls(function)[:200],
            }
        )
    functions.sort(key=lambda row: (row["line"], row["class_name"] or "", row["function_name"]))
    return {
        "root_label": root_label,
        "path": str(path.resolve()),
        "sha256": sha256_file(path),
        "size_bytes": stat.st_size,
        "module_writers": module_writers,
        "module_readers": module_readers,
        "functions": functions,
        "raw_code_published": False,
    }


def iter_python(root: Path) -> Iterable[Path]:
    if root.is_file() and root.suffix == ".py":
        yield root
        return
    if not root.is_dir():
        return
    count = 0
    for path in root.rglob("*.py"):
        if {part.lower() for part in path.parts}.intersection({".git", ".venv", "venv", "node_modules", "__pycache__"}):
            continue
        yield path
        count += 1
        if count >= MAX_FILES_PER_ROOT:
            break


def source_root(terminal_root: Path) -> Path | None:
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


def roots(runtime_root: Path, terminal_root: Path) -> list[tuple[str, Path]]:
    frozen = source_root(terminal_root)
    rows: list[tuple[str, Path]] = [
        ("runtime", runtime_root),
        ("research_runtime", Path("/opt/zel/research-runtime/data-b-v2")),
    ]
    if frozen is not None:
        rows.append(("frozen_source", frozen))
    output: list[tuple[str, Path]] = []
    seen: set[str] = set()
    for label, path in rows:
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
    scanned_counts: dict[str, int] = {}
    seen_paths: set[str] = set()
    for label, root in roots(args.runtime_root.resolve(), args.terminal_root.resolve()):
        count = 0
        for path in iter_python(root):
            count += 1
            key = str(path.resolve())
            if key in seen_paths:
                continue
            seen_paths.add(key)
            row = file_record(path, label)
            if row is not None:
                files.append(row)
        scanned_counts[label] = count

    writers: list[dict[str, Any]] = []
    readers: list[dict[str, Any]] = []
    for file_row in files:
        for function in file_row.get("functions", []):
            for writer in function.get("writers", []):
                writers.append(
                    {
                        "root_label": file_row["root_label"],
                        "path": file_row["path"],
                        "sha256": file_row["sha256"],
                        "class_name": function["class_name"],
                        "function_name": function["function_name"],
                        "function_line": function["line"],
                        **writer,
                    }
                )
            for reader in function.get("readers", []):
                readers.append(
                    {
                        "root_label": file_row["root_label"],
                        "path": file_row["path"],
                        "sha256": file_row["sha256"],
                        "class_name": function["class_name"],
                        "function_name": function["function_name"],
                        "function_line": function["line"],
                        **reader,
                    }
                )
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
        "scanned_python_counts": scanned_counts,
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
