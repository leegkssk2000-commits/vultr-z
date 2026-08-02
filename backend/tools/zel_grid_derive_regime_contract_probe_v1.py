from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "ZEL_GRID_DERIVE_REGIME_CONTRACT_PROBE_V1"
SCHEMA = "zel.grid.derive_regime_contract_probe.receipt.v1"
SECRET_KEY = re.compile(r"(?i)(secret|token|password|api[_-]?key|private[_-]?key|credential)")
MAX_STRING_LEN = 120


def stable_sha(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


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


def safe_string(value: str) -> str:
    if SECRET_KEY.search(value):
        return "<redacted>"
    return value if len(value) <= MAX_STRING_LEN else value[:MAX_STRING_LEN] + "…"


def string_constants(node: ast.AST | None) -> list[str]:
    if node is None:
        return []
    values = {
        safe_string(child.value.strip())
        for child in ast.walk(node)
        if isinstance(child, ast.Constant)
        and isinstance(child.value, str)
        and child.value.strip()
    }
    return sorted(values)


def numeric_constants(node: ast.AST | None) -> list[float | int]:
    if node is None:
        return []
    values: set[float | int] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Constant):
            continue
        value = child.value
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        if -1_000_000 <= float(value) <= 1_000_000:
            values.add(value)
    return sorted(values, key=float)


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
        key: str | None = None
        if child.args and isinstance(child.args[0], ast.Constant) and isinstance(child.args[0].value, str):
            key = safe_string(child.args[0].value)
        rows.append(
            {
                "line": int(getattr(child, "lineno", 0) or 0),
                "base": name.removesuffix(".get"),
                "key": key,
                "default_node_type": type(child.args[1]).__name__ if len(child.args) > 1 else None,
                "default_strings": string_constants(child.args[1]) if len(child.args) > 1 else [],
                "default_numbers": numeric_constants(child.args[1]) if len(child.args) > 1 else [],
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
        "loaded_names": loaded_names(node),
        "calls": calls(node),
        "get_calls": get_calls(node),
        "strings": string_constants(node),
        "numbers": numeric_constants(node),
        "operators": sorted(operators),
        "compare_operators": sorted(compare_operators),
        "has_if_expression": any(isinstance(child, ast.IfExp) for child in ast.walk(node)),
    }


def target_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return dotted_name(node) or node.attr
    if isinstance(node, ast.Subscript):
        return (dotted_name(node.value) or type(node.value).__name__) + "[<key>]"
    if isinstance(node, (ast.Tuple, ast.List)):
        return ",".join(target_name(child) for child in node.elts)
    return type(node).__name__


def assignments(function: ast.AST) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for child in ast.walk(function):
        targets: list[ast.AST]
        value: ast.AST | None
        if isinstance(child, ast.Assign):
            targets = list(child.targets)
            value = child.value
        elif isinstance(child, ast.AnnAssign):
            targets = [child.target]
            value = child.value
        elif isinstance(child, ast.NamedExpr):
            targets = [child.target]
            value = child.value
        else:
            continue
        rows.append(
            {
                "line": int(getattr(child, "lineno", 0) or 0),
                "targets": [target_name(target) for target in targets],
                "value": expression(value),
            }
        )
    return sorted(rows, key=lambda row: (row["line"], row["targets"]))


def branches(function: ast.AST) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for child in ast.walk(function):
        if not isinstance(child, ast.If):
            continue
        returns: list[dict[str, Any]] = []
        for statement in [*child.body, *child.orelse]:
            for descendant in ast.walk(statement):
                if isinstance(descendant, ast.Return):
                    returns.append(
                        {
                            "line": int(getattr(descendant, "lineno", 0) or 0),
                            "value": expression(descendant.value),
                        }
                    )
        rows.append(
            {
                "line": int(child.lineno),
                "condition": expression(child.test),
                "returns": returns,
            }
        )
    return sorted(rows, key=lambda row: row["line"])


def returns(function: ast.AST) -> list[dict[str, Any]]:
    return sorted(
        [
            {
                "line": int(getattr(child, "lineno", 0) or 0),
                "value": expression(child.value),
            }
            for child in ast.walk(function)
            if isinstance(child, ast.Return)
        ],
        key=lambda row: row["line"],
    )


def function_record(function: ast.AST) -> dict[str, Any]:
    arguments = getattr(function, "args")
    return {
        "function": str(getattr(function, "name")),
        "line": int(getattr(function, "lineno", 0) or 0),
        "arguments": [
            argument.arg
            for argument in [
                *arguments.posonlyargs,
                *arguments.args,
                *arguments.kwonlyargs,
            ]
        ],
        "assignments": assignments(function),
        "get_calls": get_calls(function),
        "branches": branches(function),
        "returns": returns(function),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("/home/z/z/tools/q4r3_exact25_preentry_method_context_capture.py"),
    )
    parser.add_argument("--out", type=Path)
    parser.add_argument("--stdout", action="store_true")
    args = parser.parse_args()

    if not args.source.is_file():
        raise RuntimeError(f"SOURCE_MISSING:{args.source}")
    tree = ast.parse(args.source.read_text(encoding="utf-8", errors="replace"))
    functions = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in {"derive_regime", "build_capture"}
    }
    blockers: list[str] = []
    for name in ("derive_regime", "build_capture"):
        if name not in functions:
            blockers.append(f"{name.upper()}_MISSING")

    derive = function_record(functions["derive_regime"]) if "derive_regime" in functions else None
    capture = function_record(functions["build_capture"]) if "build_capture" in functions else None
    required_context_keys = sorted(
        {
            row["key"]
            for row in (derive or {}).get("get_calls", [])
            if row.get("base") == "context" and row.get("key") and row["key"] != "<redacted>"
        }
    )
    assigned_targets = {
        target
        for row in (derive or {}).get("assignments", [])
        for target in row.get("targets", [])
    }
    if "strength" not in assigned_targets:
        blockers.append("STRENGTH_ASSIGNMENT_MISSING")
    if "direction" not in assigned_targets:
        blockers.append("DIRECTION_ASSIGNMENT_MISSING")
    if not required_context_keys:
        blockers.append("DERIVE_CONTEXT_KEYS_MISSING")

    receipt = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": "PASS_GRID_DERIVE_REGIME_CONTRACT_EXTRACTED" if not blockers else "HOLD_GRID_DERIVE_REGIME_CONTRACT_INCOMPLETE",
        "source_path": str(args.source.resolve()),
        "source_sha256": sha256_file(args.source),
        "derive_regime": derive,
        "build_capture": capture,
        "required_context_keys": required_context_keys,
        "assigned_targets": sorted(assigned_targets),
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
        "next": "MAP_DERIVE_CONTEXT_KEYS_TO_FROZEN_PREFIX_FEATURES" if not blockers else "RESOLVE_DERIVE_REGIME_CONTRACT_BLOCKERS",
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
