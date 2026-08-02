from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import inspect
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

VERSION = "ZEL_GRID_REGIME_SEMANTICS_PROBE_V1"
SCHEMA = "zel.grid_regime.semantics_probe.receipt.v1"
FUNCTIONS = {"feature_snapshot", "make_position", "close_position", "grouped_metrics", "replay_lane"}
KEYS = {"regime", "market_regime", "entry_features", "features", "entry_ts", "entry_time", "captured_at", "event_id", "trade_id"}
CALLS = {"producer.feature_snapshot", "owner.strategy", "producer.make_position", "producer.close_position", "row.update", "closed.append"}


def stable_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def sha256_file(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def call_name(node: ast.Call) -> str:
    value: ast.AST = node.func
    parts: list[str] = []
    while isinstance(value, ast.Attribute):
        parts.append(value.attr); value = value.value
    if isinstance(value, ast.Name):
        parts.append(value.id)
    return ".".join(reversed(parts)) if parts else type(node.func).__name__


def loaded_names(node: ast.AST | None) -> list[str]:
    if node is None:
        return []
    rows: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
            rows.add(child.id)
        elif isinstance(child, ast.Attribute) and isinstance(child.ctx, ast.Load):
            rows.add(child.attr)
    return sorted(rows)


def assigned_names(node: ast.AST) -> list[str]:
    rows: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
            rows.add(child.id)
        elif isinstance(child, ast.Attribute) and isinstance(child.ctx, ast.Store):
            rows.add(child.attr)
    return sorted(rows)


def dict_bindings(node: ast.AST) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for child in ast.walk(node):
        if not isinstance(child, ast.Dict):
            continue
        for key, value in zip(child.keys, child.values):
            if isinstance(key, ast.Constant) and isinstance(key.value, str) and key.value in KEYS:
                rows.append({
                    "key": key.value,
                    "value_loaded_names": loaded_names(value),
                    "value_node_type": type(value).__name__,
                    "line": int(getattr(value, "lineno", getattr(child, "lineno", 0)) or 0),
                })
    return rows


def call_rows(node: ast.AST) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        name = call_name(child)
        if name not in CALLS:
            continue
        rows.append({
            "line": int(child.lineno),
            "call": name,
            "positional_argument_names": [loaded_names(value) for value in child.args],
            "keyword_arguments": {
                str(keyword.arg): loaded_names(keyword.value)
                for keyword in child.keywords if keyword.arg
            },
        })
    return rows


def function_contract(path: Path, wanted: set[str]) -> dict[str, Any]:
    if not path.is_file():
        return {"path": str(path), "exists": False, "functions": []}
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    rows: list[dict[str, Any]] = []
    for function in [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in wanted]:
        args = [argument.arg for argument in [*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs]]
        statements: list[dict[str, Any]] = []
        for node in sorted([item for item in ast.walk(function) if isinstance(item, ast.stmt) and item is not function], key=lambda item: (item.lineno, item.col_offset)):
            bindings = dict_bindings(node)
            calls = call_rows(node)
            relevant_names = [value for value in [*assigned_names(node), *loaded_names(node)] if value in KEYS or "regime" in value.lower() or "feature" in value.lower()]
            if not bindings and not calls and not relevant_names:
                continue
            statements.append({
                "line": int(node.lineno),
                "node_type": type(node).__name__,
                "assigned": assigned_names(node),
                "loaded": loaded_names(node),
                "relevant_names": sorted(set(relevant_names)),
                "dict_bindings": bindings,
                "calls": calls,
            })
        rows.append({
            "function": function.name,
            "function_sha256": hashlib.sha256(function.name.encode()).hexdigest(),
            "line": int(function.lineno),
            "arguments": args,
            "statements": statements[:400],
        })
    return {
        "path": str(path.resolve()),
        "exists": True,
        "sha256": sha256_file(path),
        "functions": rows,
        "raw_code_published": False,
    }


def module_from_file(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"IMPORT_SPEC_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def signature_text(value: Any) -> str | None:
    try:
        return str(inspect.signature(value))
    except Exception:
        return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", type=Path, default=Path("/opt/zel/research-runtime/data-b-v2/zel_historical_oos_exact25_replay_v1.py"))
    parser.add_argument("--terminal-root", type=Path, default=Path("/var/lib/zel-research/data-b-1m-v2"))
    parser.add_argument("--out", type=Path)
    parser.add_argument("--stdout", action="store_true")
    args = parser.parse_args()

    report = load_object(args.terminal_root / "report.json")
    source = report.get("source") if isinstance(report.get("source"), Mapping) else {}
    source_root_raw = source.get("root") if isinstance(source, Mapping) else None
    if not isinstance(source_root_raw, str) or not source_root_raw:
        raise RuntimeError("SOURCE_ROOT_MISSING")
    source_root = Path(source_root_raw)
    engine = module_from_file(args.engine, "zel_semantics_engine")
    producer = engine.import_producer(source_root)
    producer_path = Path(inspect.getsourcefile(producer) or getattr(producer, "__file__", ""))
    runtime_contract = {
        "producer_path": str(producer_path.resolve()),
        "producer_sha256": sha256_file(producer_path),
        "feature_snapshot_signature": signature_text(getattr(producer, "feature_snapshot", None)),
        "make_position_signature": signature_text(getattr(producer, "make_position", None)),
        "close_position_signature": signature_text(getattr(producer, "close_position", None)),
        "grouped_metrics_signature": signature_text(getattr(producer, "grouped_metrics", None)),
    }
    producer_contract = function_contract(producer_path, FUNCTIONS - {"replay_lane"})
    replay_contract = function_contract(args.engine, {"replay_lane"})

    producer_functions = {row["function"]: row for row in producer_contract.get("functions", [])}
    replay_functions = {row["function"]: row for row in replay_contract.get("functions", [])}
    blockers: list[str] = []
    for name in ("feature_snapshot", "make_position", "close_position"):
        if name not in producer_functions:
            blockers.append(f"PRODUCER_{name.upper()}_MISSING")
    if "replay_lane" not in replay_functions:
        blockers.append("REPLAY_LANE_MISSING")

    receipt = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": "PASS_GRID_REGIME_SEMANTICS_EXTRACTED" if not blockers else "HOLD_GRID_REGIME_SEMANTICS_INCOMPLETE",
        "runtime_contract": runtime_contract,
        "producer_contract": producer_contract,
        "replay_contract": replay_contract,
        "blockers": blockers,
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
    return 0 if not blockers else 1


if __name__ == "__main__":
    raise SystemExit(main())
