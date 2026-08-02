from __future__ import annotations

import argparse
import ast
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

VERSION = "ZEL_GRID_NEUTRAL_SOURCE_TRACE_V1"
SCHEMA = "zel.grid_neutral.source_trace.receipt.v1"
SAFE_KEYS = {
    "regime", "market_regime", "entry_ts", "entry_time", "entry_features",
    "captured_at", "strategy_id", "strategy", "window_id", "event_id",
    "trade_id", "signal_ts", "bar_ts", "timestamp", "ts",
}


def stable_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    names: list[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
            names.append(child.id)
        elif isinstance(child, ast.Attribute) and isinstance(child.ctx, ast.Store):
            names.append(child.attr)
    return sorted(set(names))


def load_names(node: ast.AST) -> list[str]:
    names: list[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
            names.append(child.id)
        elif isinstance(child, ast.Attribute) and isinstance(child.ctx, ast.Load):
            names.append(child.attr)
    return sorted(set(names))


def dict_keys(node: ast.AST) -> list[str]:
    keys: list[str] = []
    for child in ast.walk(node):
        if not isinstance(child, ast.Dict):
            continue
        for key in child.keys:
            if isinstance(key, ast.Constant) and isinstance(key.value, str) and key.value in SAFE_KEYS:
                keys.append(key.value)
    return sorted(set(keys))


def slice_facts(node: ast.AST) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for child in ast.walk(node):
        if not isinstance(child, ast.Subscript):
            continue
        base = None
        if isinstance(child.value, ast.Attribute):
            base = child.value.attr
        elif isinstance(child.value, ast.Name):
            base = child.value.id
        value = child.slice
        if isinstance(value, ast.Slice):
            rows.append({
                "base": base,
                "lower_names": load_names(value.lower) if value.lower else [],
                "upper_names": load_names(value.upper) if value.upper else [],
                "upper_has_plus_one": isinstance(value.upper, ast.BinOp) and isinstance(value.upper.op, ast.Add),
            })
        elif isinstance(value, ast.Tuple):
            for element in value.elts:
                if isinstance(element, ast.Slice):
                    rows.append({
                        "base": base,
                        "lower_names": load_names(element.lower) if element.lower else [],
                        "upper_names": load_names(element.upper) if element.upper else [],
                        "upper_has_plus_one": isinstance(element.upper, ast.BinOp) and isinstance(element.upper.op, ast.Add),
                    })
    return rows


def statement_fact(node: ast.AST) -> dict[str, Any] | None:
    line = int(getattr(node, "lineno", 0) or 0)
    if not line:
        return None
    assigned = target_names(node)
    loaded = load_names(node)
    keys = dict_keys(node)
    calls = sorted({call_name(child) for child in ast.walk(node) if isinstance(child, ast.Call)})
    slices = slice_facts(node)
    relevant = (
        any("regime" in value.lower() for value in assigned + loaded + keys + calls)
        or any(value in SAFE_KEYS for value in assigned + loaded + keys)
        or any(token in value.lower() for value in calls for token in ("append", "decide", "strategy", "signal", "open", "close", "execute"))
        or bool(slices)
    )
    if not relevant:
        return None
    return {
        "line": line,
        "node_type": type(node).__name__,
        "assigned": assigned,
        "loaded": loaded,
        "safe_dict_keys": keys,
        "calls": calls,
        "slices": slices,
    }


def lexical_statements(function: ast.AST) -> Iterable[ast.AST]:
    nodes = [node for node in ast.walk(function) if isinstance(node, ast.stmt)]
    return sorted(nodes, key=lambda node: (int(getattr(node, "lineno", 0) or 0), int(getattr(node, "col_offset", 0) or 0)))


def trace_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"path": str(path), "exists": False, "functions": []}
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError as exc:
        return {"path": str(path.resolve()), "exists": True, "sha256": sha256_file(path), "parse_error": str(exc), "functions": []}
    functions: list[dict[str, Any]] = []
    for function in [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        facts = [fact for node in lexical_statements(function) if (fact := statement_fact(node)) is not None]
        if not any(any("regime" in value.lower() for value in fact["assigned"] + fact["loaded"] + fact["safe_dict_keys"] + fact["calls"]) for fact in facts):
            continue
        functions.append({
            "function_name_sha256": hashlib.sha256(function.name.encode()).hexdigest(),
            "first_line": int(function.lineno),
            "facts": facts[:300],
        })
    return {
        "path": str(path.resolve()),
        "exists": True,
        "sha256": sha256_file(path),
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
    source = report.get("source") if isinstance(report, dict) else None
    if isinstance(source, dict) and isinstance(source.get("root"), str):
        source_root = Path(source["root"])
    paths = [
        Path("/opt/zel/research-runtime/data-b-v2/zel_historical_oos_exact25_replay_v1.py"),
        Path("/opt/zel/research-runtime/data-b-v2/zel_historical_oos_exact25_replay_v2.py"),
        runtime_root / "backend/tools/zel_historical_oos_exact25_replay_v1.py",
        runtime_root / "backend/tools/zel_historical_oos_exact25_replay_v2.py",
        runtime_root / "backend/strategies/grid_rebalance.py",
    ]
    if source_root:
        paths.extend([
            source_root / "backend/strategies/grid_rebalance.py",
            source_root / "backend/tools/zel_historical_oos_exact25_replay_v1.py",
            source_root / "backend/tools/zel_historical_oos_exact25_replay_v2.py",
        ])
    seen: set[str] = set()
    unique_paths: list[Path] = []
    for path in paths:
        key = str(path)
        if key not in seen:
            seen.add(key)
            unique_paths.append(path)
    files = [trace_file(path) for path in unique_paths]
    relevant_functions = sum(len(row.get("functions", [])) for row in files)
    receipt = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": "PASS_GRID_SOURCE_TRACE_EXTRACTED" if relevant_functions else "HOLD_GRID_SOURCE_TRACE_EMPTY",
        "file_count": len(files),
        "relevant_function_count": relevant_functions,
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
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(encoded, encoding="utf-8")
    if args.stdout or not args.out:
        print(encoded, end="")
    return 0 if relevant_functions else 1


if __name__ == "__main__":
    raise SystemExit(main())
