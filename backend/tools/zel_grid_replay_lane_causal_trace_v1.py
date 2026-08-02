from __future__ import annotations

import argparse
import ast
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "ZEL_GRID_REPLAY_LANE_CAUSAL_TRACE_V1"
SCHEMA = "zel.grid_replay_lane.causal_trace.receipt.v1"
TARGET_FUNCTION = "replay_lane"
CALL_TARGETS = (
    "feature_snapshot", "owner.strategy", "valid_entry", "make_position",
    "closed.append", "close_position", "bar_exit", "mark_excursions",
)
SAFE_STRINGS = {
    "regime", "market_regime", "entry_ts", "entry_time", "entry_features",
    "captured_at", "strategy_id", "event_id", "trade_id", "window_id", "timestamp",
}


def stable_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def call_name(node: ast.Call) -> str:
    value: ast.AST = node.func
    parts: list[str] = []
    while isinstance(value, ast.Attribute):
        parts.append(value.attr); value = value.value
    if isinstance(value, ast.Name):
        parts.append(value.id)
    return ".".join(reversed(parts)) if parts else type(node.func).__name__


def names(node: ast.AST | None, store: bool) -> list[str]:
    if node is None:
        return []
    rows: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store if store else ast.Load):
            rows.add(child.id)
        elif isinstance(child, ast.Attribute) and isinstance(child.ctx, ast.Store if store else ast.Load):
            rows.add(child.attr)
    return sorted(rows)


def safe_strings(node: ast.AST) -> list[str]:
    rows: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str) and child.value in SAFE_STRINGS:
            rows.add(child.value)
    return sorted(rows)


def slice_rows(node: ast.AST) -> list[dict[str, Any]]:
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
                    "lower_names": names(value.lower, False),
                    "upper_names": names(value.upper, False),
                    "upper_plus_one": isinstance(value.upper, ast.BinOp) and isinstance(value.upper.op, ast.Add),
                })
    return rows


def trace(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"state": "HOLD_REPLAY_ENGINE_MISSING", "path": str(path)}
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    functions = [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == TARGET_FUNCTION]
    if len(functions) != 1:
        return {"state": "HOLD_REPLAY_LANE_NOT_UNIQUE", "path": str(path.resolve()), "count": len(functions)}
    function = functions[0]
    facts: list[dict[str, Any]] = []
    for node in sorted([item for item in ast.walk(function) if isinstance(item, ast.stmt) and item is not function], key=lambda item: (item.lineno, item.col_offset)):
        calls = sorted({call_name(child) for child in ast.walk(node) if isinstance(child, ast.Call)})
        slices = slice_rows(node)
        relevant_calls = [call for call in calls if any(target in call for target in CALL_TARGETS)]
        strings = safe_strings(node)
        assigned = names(node, True)
        loaded = names(node, False)
        if not relevant_calls and not slices and not strings:
            continue
        facts.append({
            "line": int(node.lineno),
            "node_type": type(node).__name__,
            "assigned": assigned,
            "loaded": loaded,
            "safe_strings": strings,
            "relevant_calls": relevant_calls,
            "slices": slices,
        })

    def first_line_for_call(token: str) -> int | None:
        lines = [row["line"] for row in facts if any(token in call for call in row["relevant_calls"])]
        return min(lines) if lines else None

    prefix_lines = [
        row["line"] for row in facts
        if any(slice_row.get("upper_plus_one") and "index" in slice_row.get("upper_names", []) for slice_row in row["slices"])
    ]
    prefix_line = min(prefix_lines) if prefix_lines else None
    feature_line = first_line_for_call("feature_snapshot")
    strategy_line = first_line_for_call("owner.strategy")
    valid_line = first_line_for_call("valid_entry")
    make_line = first_line_for_call("make_position")
    append_line = first_line_for_call("closed.append")
    required = [prefix_line, feature_line, strategy_line, valid_line, make_line, append_line]
    ordered = all(value is not None for value in required) and required == sorted(required)
    checks = {
        "current_frame_prefix_through_index": prefix_line is not None,
        "feature_snapshot_after_prefix": bool(prefix_line and feature_line and prefix_line <= feature_line),
        "strategy_after_feature_snapshot": bool(feature_line and strategy_line and feature_line <= strategy_line),
        "valid_entry_after_strategy": bool(strategy_line and valid_line and strategy_line <= valid_line),
        "position_after_valid_entry": bool(valid_line and make_line and valid_line <= make_line),
        "closed_trade_after_position": bool(make_line and append_line and make_line <= append_line),
        "full_order": ordered,
    }
    return {
        "state": "PASS_REPLAY_LANE_CAUSAL_ORDER" if all(checks.values()) else "HOLD_REPLAY_LANE_CAUSAL_ORDER_INCOMPLETE",
        "path": str(path.resolve()),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "function_name_sha256": hashlib.sha256(TARGET_FUNCTION.encode()).hexdigest(),
        "function_first_line": int(function.lineno),
        "lineage_lines": {
            "prefix_frame": prefix_line,
            "feature_snapshot": feature_line,
            "strategy_call": strategy_line,
            "valid_entry": valid_line,
            "make_position": make_line,
            "closed_append": append_line,
        },
        "checks": checks,
        "facts": facts,
        "raw_code_published": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", type=Path, default=Path("/opt/zel/research-runtime/data-b-v2/zel_historical_oos_exact25_replay_v1.py"))
    parser.add_argument("--out", type=Path)
    parser.add_argument("--stdout", action="store_true")
    args = parser.parse_args()
    evidence = trace(args.engine)
    passed = evidence.get("state") == "PASS_REPLAY_LANE_CAUSAL_ORDER"
    receipt = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": "PASS_GRID_REPLAY_SOURCE_CAUSAL_ORDER" if passed else "HOLD_GRID_REPLAY_SOURCE_CAUSAL_ORDER",
        "evidence": evidence,
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
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
