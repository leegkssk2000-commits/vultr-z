from __future__ import annotations

import argparse
import ast
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

VERSION = "ZEL_GRID_REGIME_SEMANTICS_PROBE_V1"
SCHEMA = "zel.grid_regime.semantics_probe.receipt.v1"
PRODUCER_FUNCTIONS = {"feature_snapshot", "make_position", "close_position"}
REPLAY_FUNCTIONS = {"replay_lane"}
PREENTRY_FUNCTIONS = {"derive_regime", "build_capture"}
INTEREST_KEYS = {
    "regime",
    "market_regime",
    "entry_features",
    "exit_features",
    "features",
    "entry_ts",
    "entry_time",
    "captured_at",
    "event_id",
    "trade_id",
    "htf_bias",
    "premium_discount_side",
    "swing_sequence",
    "session_window",
    "dealing_range_position",
    "ltf_reversal_confirm",
}
ORDER_CALLS = {
    "producer.feature_snapshot",
    "owner.strategy",
    "producer.valid_entry",
    "producer.make_position",
    "producer.close_position",
    "closed.append",
}
SAFE_STRINGS = {
    "regime",
    "market_regime",
    "neutral",
    "long",
    "short",
    "trend",
    "range",
    "unknown",
    "bull",
    "bear",
    "bullish",
    "bearish",
    "up",
    "down",
}


def stable_sha(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def sha256_file(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def dotted_name(node: ast.AST | None) -> str | None:
    if node is None:
        return None
    value = node
    parts: list[str] = []
    while isinstance(value, ast.Attribute):
        parts.append(value.attr)
        value = value.value
    if isinstance(value, ast.Name):
        parts.append(value.id)
    return ".".join(reversed(parts)) if parts else None


def call_name(node: ast.Call) -> str:
    return dotted_name(node.func) or type(node.func).__name__


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


def calls(node: ast.AST | None) -> list[str]:
    if node is None:
        return []
    return sorted({call_name(child) for child in ast.walk(node) if isinstance(child, ast.Call)})


def safe_strings(node: ast.AST | None) -> list[str]:
    if node is None:
        return []
    return sorted(
        {
            child.value
            for child in ast.walk(node)
            if isinstance(child, ast.Constant)
            and isinstance(child.value, str)
            and child.value.strip().lower() in SAFE_STRINGS
        }
    )


def safe_numbers(node: ast.AST | None) -> list[float | int]:
    if node is None:
        return []
    values: set[float | int] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, (int, float)) and not isinstance(child.value, bool):
            value = child.value
            if -10000 <= float(value) <= 10000:
                values.add(value)
    return sorted(values, key=float)


def fingerprint(node: ast.AST | None) -> dict[str, Any] | None:
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
        "loaded_names": loaded_names(node)[:120],
        "calls": calls(node)[:120],
        "safe_strings": safe_strings(node),
        "safe_numbers": safe_numbers(node),
        "operators": sorted(operators),
        "compare_operators": sorted(compare_operators),
        "has_slice": any(isinstance(child, ast.Slice) for child in ast.walk(node)),
        "has_if_expression": any(isinstance(child, ast.IfExp) for child in ast.walk(node)),
    }


def dict_bindings(node: ast.AST) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for child in ast.walk(node):
        if not isinstance(child, ast.Dict):
            continue
        for key, value in zip(child.keys, child.values):
            if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                continue
            if key.value not in INTEREST_KEYS:
                continue
            rows.append(
                {
                    "key": key.value,
                    "line": int(getattr(key, "lineno", getattr(child, "lineno", 0)) or 0),
                    "value": fingerprint(value),
                }
            )
    return rows


def get_calls(node: ast.AST) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        name = call_name(child)
        if not (name.endswith(".get") or name == "get"):
            continue
        if not child.args or not isinstance(child.args[0], ast.Constant) or not isinstance(child.args[0].value, str):
            continue
        key = child.args[0].value
        if key not in INTEREST_KEYS:
            continue
        rows.append(
            {
                "base": name.removesuffix(".get"),
                "key": key,
                "line": int(getattr(child, "lineno", 0) or 0),
                "default": fingerprint(child.args[1]) if len(child.args) > 1 else None,
            }
        )
    return rows


def branch_rows(function: ast.AST) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for child in ast.walk(function):
        if not isinstance(child, ast.If):
            continue
        returns: list[dict[str, Any]] = []
        for branch_node in [*child.body, *child.orelse]:
            for descendant in ast.walk(branch_node):
                if isinstance(descendant, ast.Return):
                    returns.append(
                        {
                            "line": int(getattr(descendant, "lineno", 0) or 0),
                            "value": fingerprint(descendant.value),
                        }
                    )
        rows.append(
            {
                "line": int(child.lineno),
                "condition": fingerprint(child.test),
                "returns": returns[:20],
            }
        )
    return rows


def return_rows(function: ast.AST) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for child in ast.walk(function):
        if not isinstance(child, ast.Return):
            continue
        keys: list[str] = []
        if isinstance(child.value, ast.Dict):
            for key in child.value.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    keys.append(key.value)
        rows.append(
            {
                "line": int(getattr(child, "lineno", 0) or 0),
                "dict_keys": sorted(keys),
                "value": fingerprint(child.value),
            }
        )
    return rows


def order_calls(function: ast.AST) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for child in ast.walk(function):
        if not isinstance(child, ast.Call):
            continue
        name = call_name(child)
        if name not in ORDER_CALLS:
            continue
        rows.append(
            {
                "line": int(child.lineno),
                "call": name,
                "arguments": [fingerprint(value) for value in child.args],
                "keywords": {
                    str(keyword.arg): fingerprint(keyword.value)
                    for keyword in child.keywords
                    if keyword.arg
                },
            }
        )
    return sorted(rows, key=lambda row: (row["line"], row["call"]))


def slice_rows(function: ast.AST) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for child in ast.walk(function):
        if not isinstance(child, ast.Subscript):
            continue
        slices = list(child.slice.elts) if isinstance(child.slice, ast.Tuple) else [child.slice]
        for value in slices:
            if not isinstance(value, ast.Slice):
                continue
            rows.append(
                {
                    "line": int(getattr(child, "lineno", 0) or 0),
                    "base": dotted_name(child.value) or type(child.value).__name__,
                    "lower": fingerprint(value.lower),
                    "upper": fingerprint(value.upper),
                    "upper_plus_one": isinstance(value.upper, ast.BinOp) and isinstance(value.upper.op, ast.Add),
                }
            )
    return rows


def function_contract(path: Path, wanted: set[str]) -> dict[str, Any]:
    if not path.is_file():
        return {"path": str(path), "exists": False, "functions": [], "raw_code_published": False}
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    rows: list[dict[str, Any]] = []
    for function in [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in wanted
    ]:
        rows.append(
            {
                "function": function.name,
                "line": int(function.lineno),
                "arguments": [
                    argument.arg
                    for argument in [
                        *function.args.posonlyargs,
                        *function.args.args,
                        *function.args.kwonlyargs,
                    ]
                ],
                "dict_bindings": dict_bindings(function),
                "get_calls": get_calls(function),
                "branches": branch_rows(function),
                "returns": return_rows(function),
                "order_calls": order_calls(function),
                "slices": slice_rows(function),
            }
        )
    rows.sort(key=lambda row: row["line"])
    return {
        "path": str(path.resolve()),
        "exists": True,
        "sha256": sha256_file(path),
        "functions": rows,
        "raw_code_published": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--engine",
        type=Path,
        default=Path("/opt/zel/research-runtime/data-b-v2/zel_historical_oos_exact25_replay_v1.py"),
    )
    parser.add_argument(
        "--preentry",
        type=Path,
        default=Path("/home/z/z/tools/q4r3_exact25_preentry_method_context_capture.py"),
    )
    parser.add_argument(
        "--terminal-root",
        type=Path,
        default=Path("/var/lib/zel-research/data-b-1m-v2"),
    )
    parser.add_argument("--out", type=Path)
    parser.add_argument("--stdout", action="store_true")
    args = parser.parse_args()

    report = load_object(args.terminal_root / "report.json")
    source = report.get("source") if isinstance(report.get("source"), Mapping) else {}
    source_root_raw = source.get("root") if isinstance(source, Mapping) else None
    if not isinstance(source_root_raw, str) or not source_root_raw:
        raise RuntimeError("SOURCE_ROOT_MISSING")
    source_root = Path(source_root_raw).resolve()
    producer_path = source_root / "tools/q4r3_exact25_dedicated_shadow_producer.py"

    producer_contract = function_contract(producer_path, PRODUCER_FUNCTIONS)
    replay_contract = function_contract(args.engine, REPLAY_FUNCTIONS)
    preentry_contract = function_contract(args.preentry, PREENTRY_FUNCTIONS)

    producer_names = {row["function"] for row in producer_contract["functions"]}
    replay_names = {row["function"] for row in replay_contract["functions"]}
    preentry_names = {row["function"] for row in preentry_contract["functions"]}
    blockers: list[str] = []
    for name in sorted(PRODUCER_FUNCTIONS - producer_names):
        blockers.append(f"PRODUCER_{name.upper()}_MISSING")
    for name in sorted(REPLAY_FUNCTIONS - replay_names):
        blockers.append(f"REPLAY_{name.upper()}_MISSING")
    for name in sorted(PREENTRY_FUNCTIONS - preentry_names):
        blockers.append(f"PREENTRY_{name.upper()}_MISSING")

    close_position = next(
        (row for row in producer_contract["functions"] if row["function"] == "close_position"),
        {},
    )
    derive_regime = next(
        (row for row in preentry_contract["functions"] if row["function"] == "derive_regime"),
        {},
    )
    replay_lane = next(
        (row for row in replay_contract["functions"] if row["function"] == "replay_lane"),
        {},
    )
    exit_regime_writer = any(
        binding.get("key") == "regime"
        and "exit_features" in (binding.get("value") or {}).get("loaded_names", [])
        for binding in close_position.get("dict_bindings", [])
    )
    preentry_deriver_present = bool(derive_regime.get("branches") or derive_regime.get("returns"))
    causal_prefix_present = any(row.get("upper_plus_one") for row in replay_lane.get("slices", []))

    receipt = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": "PASS_GRID_REGIME_SEMANTICS_EXTRACTED" if not blockers else "HOLD_GRID_REGIME_SEMANTICS_INCOMPLETE",
        "runtime_contract": {
            "terminal_source_root": str(source_root),
            "producer_path": str(producer_path),
            "producer_sha256": sha256_file(producer_path),
            "engine_path": str(args.engine.resolve()),
            "engine_sha256": sha256_file(args.engine),
            "preentry_path": str(args.preentry.resolve()),
            "preentry_sha256": sha256_file(args.preentry),
        },
        "producer_contract": producer_contract,
        "replay_contract": replay_contract,
        "preentry_contract": preentry_contract,
        "semantic_facts": {
            "legacy_trade_regime_written_from_exit_features": exit_regime_writer,
            "preentry_derive_regime_contract_present": preentry_deriver_present,
            "replay_prefix_frame_includes_current_index_only": causal_prefix_present,
            "legacy_regime_valid_for_entry_filter": False if exit_regime_writer else None,
        },
        "blockers": blockers,
        "canonical_mutated": False,
        "runtime_mutated": False,
        "formal_ledger_mutated": False,
        "raw_code_published": False,
        "raw_trade_rows_published": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
        "next": "RECOMPUTE_ENTRY_REGIME_FROM_FROZEN_PREFIX_FRAMES" if not blockers else "RESOLVE_REGIME_SEMANTICS_BLOCKERS",
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
