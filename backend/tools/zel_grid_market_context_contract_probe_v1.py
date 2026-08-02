from __future__ import annotations

import argparse
import ast
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

VERSION = "ZEL_GRID_MARKET_CONTEXT_CONTRACT_PROBE_V1"
SCHEMA = "zel.grid.market_context_contract_probe.receipt.v1"
TARGET_FUNCTION = "compute_context"
TARGET_ASSIGNMENTS = {
    "ema_fast",
    "ema_slow",
    "atr",
    "trend_strength",
    "trend_direction",
}
TARGET_RETURN_KEYS = {
    "trend_strength",
    "trend_direction",
    "atr_pct",
    "realized_volatility_pct",
    "funding_8h_pct",
    "spread_bps",
    "session_bucket",
    "snapshot_id",
    "bar_epoch",
}


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


def constants(node: ast.AST | None) -> dict[str, list[Any]]:
    strings: set[str] = set()
    numbers: set[float | int] = set()
    if node is not None:
        for child in ast.walk(node):
            if not isinstance(child, ast.Constant):
                continue
            value = child.value
            if isinstance(value, str) and value.strip() and len(value.strip()) <= 160:
                strings.add(value.strip())
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


def calls(node: ast.AST | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if node is None:
        return rows
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        rows.append(
            {
                "line": int(getattr(child, "lineno", 0) or 0),
                "call": call_name(child),
                "argument_facts": [expression(value) for value in child.args],
                "keyword_facts": {
                    str(keyword.arg): expression(keyword.value)
                    for keyword in child.keywords
                    if keyword.arg
                },
            }
        )
    return sorted(rows, key=lambda row: (row["line"], row["call"]))


def expression(node: ast.AST | None) -> dict[str, Any] | None:
    if node is None:
        return None
    values = constants(node)
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
        "loaded_names": loaded_names(node)[:120],
        "calls": sorted({call_name(child) for child in ast.walk(node) if isinstance(child, ast.Call)})[:120],
        "strings": values["strings"][:120],
        "numbers": values["numbers"],
        "operators": sorted(operators),
        "compare_operators": sorted(compare_operators),
        "has_negative_shift": any(
            isinstance(child, ast.Call)
            and call_name(child).endswith(".shift")
            and child.args
            and isinstance(child.args[0], ast.UnaryOp)
            and isinstance(child.args[0].op, ast.USub)
            for child in ast.walk(node)
        ),
        "has_center_true": any(
            isinstance(child, ast.keyword)
            and child.arg == "center"
            and isinstance(child.value, ast.Constant)
            and child.value.value is True
            for child in ast.walk(node)
        ),
    }


def assignment_target(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    return None


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
        else:
            continue
        names = [assignment_target(target) for target in targets]
        names = [name for name in names if name in TARGET_ASSIGNMENTS]
        if not names:
            continue
        rows.append(
            {
                "line": int(getattr(child, "lineno", 0) or 0),
                "targets": names,
                "value": expression(value),
                "nested_calls": calls(value),
            }
        )
    return sorted(rows, key=lambda row: (row["line"], row["targets"]))


def returns(function: ast.AST) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for child in ast.walk(function):
        if not isinstance(child, ast.Return):
            continue
        bindings: list[dict[str, Any]] = []
        if isinstance(child.value, ast.Dict):
            for key_node, value_node in zip(child.value.keys, child.value.values):
                if not isinstance(key_node, ast.Constant) or not isinstance(key_node.value, str):
                    continue
                if key_node.value not in TARGET_RETURN_KEYS:
                    continue
                bindings.append(
                    {
                        "key": key_node.value,
                        "line": int(getattr(key_node, "lineno", getattr(child, "lineno", 0)) or 0),
                        "value": expression(value_node),
                    }
                )
        rows.append(
            {
                "line": int(getattr(child, "lineno", 0) or 0),
                "bindings": bindings,
                "value": expression(child.value),
            }
        )
    return sorted(rows, key=lambda row: row["line"])


def imports(tree: ast.AST) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                rows.append({"line": int(node.lineno), "module": alias.name, "name": None, "alias": alias.asname})
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                rows.append({"line": int(node.lineno), "module": node.module, "name": alias.name, "alias": alias.asname})
    return sorted(rows, key=lambda row: (row["line"], row["module"] or "", row["name"] or ""))


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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--runtime-source",
        type=Path,
        default=Path("/home/z/z/tools/q4r3_exact25_market_context_collector.py"),
    )
    parser.add_argument(
        "--terminal-root",
        type=Path,
        default=Path("/var/lib/zel-research/data-b-1m-v2"),
    )
    parser.add_argument("--out", type=Path)
    parser.add_argument("--stdout", action="store_true")
    args = parser.parse_args()

    if not args.runtime_source.is_file():
        raise RuntimeError(f"RUNTIME_SOURCE_MISSING:{args.runtime_source}")
    tree = ast.parse(args.runtime_source.read_text(encoding="utf-8", errors="replace"))
    function = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == TARGET_FUNCTION
        ),
        None,
    )
    blockers: list[str] = []
    if function is None:
        blockers.append("COMPUTE_CONTEXT_MISSING")

    function_assignments = assignments(function) if function is not None else []
    assignment_names = {
        name
        for row in function_assignments
        for name in row.get("targets", [])
    }
    for name in sorted(TARGET_ASSIGNMENTS - assignment_names):
        blockers.append(f"{name.upper()}_ASSIGNMENT_MISSING")

    function_returns = returns(function) if function is not None else []
    return_keys = {
        binding["key"]
        for row in function_returns
        for binding in row.get("bindings", [])
    }
    for key in ("trend_strength", "trend_direction"):
        if key not in return_keys:
            blockers.append(f"{key.upper()}_RETURN_MISSING")

    lookahead_flags = {
        "negative_shift": any(
            row["value"] and row["value"].get("has_negative_shift")
            for row in function_assignments
        ),
        "center_true": any(
            row["value"] and row["value"].get("has_center_true")
            for row in function_assignments
        ),
    }
    if any(lookahead_flags.values()):
        blockers.append("LOOKAHEAD_PATTERN_DETECTED")

    frozen = source_root(args.terminal_root.resolve())
    frozen_candidate = frozen / "tools/q4r3_exact25_market_context_collector.py" if frozen is not None else None
    frozen_exists = bool(frozen_candidate and frozen_candidate.is_file())
    frozen_sha = sha256_file(frozen_candidate) if frozen_candidate is not None else None
    runtime_sha = sha256_file(args.runtime_source)

    receipt = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": "PASS_GRID_MARKET_CONTEXT_CONTRACT_EXTRACTED" if not blockers else "HOLD_GRID_MARKET_CONTEXT_CONTRACT_INCOMPLETE",
        "runtime_source_path": str(args.runtime_source.resolve()),
        "runtime_source_sha256": runtime_sha,
        "frozen_source_root": str(frozen) if frozen else None,
        "frozen_candidate_path": str(frozen_candidate) if frozen_candidate else None,
        "frozen_candidate_exists": frozen_exists,
        "frozen_candidate_sha256": frozen_sha,
        "runtime_frozen_sha_parity": bool(runtime_sha and frozen_sha and runtime_sha == frozen_sha),
        "imports": imports(tree),
        "compute_context": {
            "line": int(getattr(function, "lineno", 0) or 0) if function else None,
            "arguments": [
                argument.arg
                for argument in [
                    *getattr(getattr(function, "args", None), "posonlyargs", []),
                    *getattr(getattr(function, "args", None), "args", []),
                    *getattr(getattr(function, "args", None), "kwonlyargs", []),
                ]
            ] if function else [],
            "assignments": function_assignments,
            "returns": function_returns,
            "all_calls": calls(function) if function is not None else [],
        },
        "assignment_names": sorted(assignment_names),
        "return_keys": sorted(return_keys),
        "lookahead_flags": lookahead_flags,
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
        "next": "BUILD_FROZEN_PREFIX_ENTRY_REGIME_REPLAY" if not blockers else "RESOLVE_MARKET_CONTEXT_CONTRACT_BLOCKERS",
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
