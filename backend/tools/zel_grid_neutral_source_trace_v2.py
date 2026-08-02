from __future__ import annotations

import argparse
import ast
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

VERSION = "ZEL_GRID_NEUTRAL_SOURCE_TRACE_V2"
SCHEMA = "zel.grid_neutral.source_trace.receipt.v2"
TOKENS = ("regime", "entry", "trade", "signal", "strategy", "window", "event", "timestamp", "captured", "bar")


def stable_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def sha256_file(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def call_name(node: ast.Call) -> str:
    value: ast.AST = node.func
    parts: list[str] = []
    while isinstance(value, ast.Attribute):
        parts.append(value.attr)
        value = value.value
    if isinstance(value, ast.Name):
        parts.append(value.id)
    return ".".join(reversed(parts)) if parts else type(node.func).__name__


def target_names(node: ast.AST) -> list[str]:
    rows: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
            rows.add(child.id)
        elif isinstance(child, ast.Attribute) and isinstance(child.ctx, ast.Store):
            rows.add(child.attr)
    return sorted(rows)


def load_names(node: ast.AST | None) -> list[str]:
    if node is None:
        return []
    rows: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
            rows.add(child.id)
        elif isinstance(child, ast.Attribute) and isinstance(child.ctx, ast.Load):
            rows.add(child.attr)
    return sorted(rows)


def safe_strings(node: ast.AST) -> list[str]:
    rows: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            value = child.value.strip()
            lower = value.lower()
            if len(value) <= 120 and any(token in lower for token in TOKENS):
                rows.add(value)
    return sorted(rows)


def slices(node: ast.AST) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for child in ast.walk(node):
        if not isinstance(child, ast.Subscript):
            continue
        base = child.value.attr if isinstance(child.value, ast.Attribute) else child.value.id if isinstance(child.value, ast.Name) else type(child.value).__name__
        values = list(child.slice.elts) if isinstance(child.slice, ast.Tuple) else [child.slice]
        for value in values:
            if isinstance(value, ast.Slice):
                rows.append({
                    "base": base,
                    "lower_names": load_names(value.lower),
                    "upper_names": load_names(value.upper),
                    "upper_plus_one": isinstance(value.upper, ast.BinOp) and isinstance(value.upper.op, ast.Add),
                })
    return rows


def statement_fact(node: ast.stmt) -> dict[str, Any] | None:
    assigned = target_names(node)
    loaded = load_names(node)
    strings = safe_strings(node)
    calls = sorted({call_name(child) for child in ast.walk(node) if isinstance(child, ast.Call)})
    slice_rows = slices(node)
    values = [*assigned, *loaded, *strings, *calls]
    relevant = any(any(token in value.lower() for token in TOKENS) for value in values) or bool(slice_rows)
    if not relevant:
        return None
    return {
        "line": int(getattr(node, "lineno", 0) or 0),
        "node_type": type(node).__name__,
        "assigned": assigned,
        "loaded": loaded,
        "safe_strings": strings,
        "calls": calls,
        "slices": slice_rows,
    }


def statements(function: ast.AST) -> Iterable[ast.stmt]:
    return sorted(
        [node for node in ast.walk(function) if isinstance(node, ast.stmt) and node is not function],
        key=lambda node: (int(getattr(node, "lineno", 0) or 0), int(getattr(node, "col_offset", 0) or 0)),
    )


def trace_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"path": str(path), "exists": False, "functions": []}
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    functions: list[dict[str, Any]] = []
    module_facts = [fact for node in tree.body if isinstance(node, ast.stmt) and (fact := statement_fact(node)) is not None]
    for function in [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        facts = [fact for node in statements(function) if (fact := statement_fact(node)) is not None]
        name_relevant = any(token in function.name.lower() for token in TOKENS)
        content_relevant = any(any("regime" in value.lower() for value in fact["assigned"] + fact["loaded"] + fact["safe_strings"] + fact["calls"]) for fact in facts)
        if not name_relevant and not content_relevant:
            continue
        functions.append({
            "function_name": function.name,
            "function_name_sha256": hashlib.sha256(function.name.encode()).hexdigest(),
            "first_line": int(function.lineno),
            "facts": facts[:500],
        })
    return {
        "path": str(path.resolve()),
        "exists": True,
        "sha256": sha256_file(path),
        "module_facts": module_facts[:300],
        "functions": functions,
        "raw_code_published": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", type=Path, default=Path("/home/z/z"))
    parser.add_argument("--terminal-root", type=Path, default=Path("/var/lib/zel-research/data-b-1m-v2"))
    parser.add_argument("--out", type=Path)
    parser.add_argument("--stdout", action="store_true")
    args = parser.parse_args()
    runtime_root = args.runtime_root.resolve()
    terminal_root = args.terminal_root.resolve()
    report_path = terminal_root / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.is_file() else {}
    source_root = None
    if isinstance(report, dict) and isinstance(report.get("source"), dict) and isinstance(report["source"].get("root"), str):
        source_root = Path(report["source"]["root"])
    paths = [
        Path("/opt/zel/research-runtime/data-b-v2/zel_historical_oos_exact25_replay_v1.py"),
        Path("/opt/zel/research-runtime/data-b-v2/zel_historical_oos_exact25_replay_v2.py"),
        runtime_root / "backend/strategies/grid_rebalance.py",
    ]
    if source_root:
        paths.append(source_root / "backend/strategies/grid_rebalance.py")
    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        if str(path) not in seen:
            seen.add(str(path)); unique.append(path)
    files = [trace_file(path) for path in unique]
    relevant = sum(len(row.get("functions", [])) for row in files)
    receipt = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": "PASS_GRID_SOURCE_TRACE_V2_EXTRACTED" if relevant else "HOLD_GRID_SOURCE_TRACE_V2_EMPTY",
        "file_count": len(files),
        "relevant_function_count": relevant,
        "files": files,
        "canonical_mutated": False,
        "runtime_mutated": False,
        "formal_ledger_mutated": False,
        "raw_code_published": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    encoded = json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True); args.out.write_text(encoded, encoding="utf-8")
    if args.stdout or not args.out:
        print(encoded, end="")
    return 0 if relevant else 1


if __name__ == "__main__":
    raise SystemExit(main())
