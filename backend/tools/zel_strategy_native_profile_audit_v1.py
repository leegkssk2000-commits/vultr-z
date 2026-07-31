from __future__ import annotations

import argparse
import ast
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from backend.research.zel_strategy_lifecycle_registry_v1 import REGISTRY

VERSION = "ZEL_STRATEGY_NATIVE_PROFILE_AUDIT_V1_1"
ACTION_LITERALS = {
    "enter", "entry", "open", "buy", "sell", "hold", "none", "flat",
    "exit", "close", "stop", "add", "reduce", "partial", "partial30",
}
INDICATOR_TOKENS = {
    "ema", "sma", "macd", "rsi", "mfi", "obv", "vwap", "atr", "supertrend",
    "keltner", "bollinger", "bb", "pivot", "fvg", "volume", "squeeze", "turtle",
    "donchian", "support", "resistance", "liquidity", "trend", "range", "session",
}
RISK_KEYS = {"sl", "tp", "stop", "stop_loss", "take_profit", "risk", "size", "qty", "leverage"}
STATE_KEYS = {"state", "position_side", "position_qty", "avg_entry", "add_count", "last_add_price"}


class NativeProfileError(ValueError):
    pass


def _fail(code: str, detail: str = "") -> None:
    raise NativeProfileError(f"{code}:{detail}" if detail else code)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def string_constants(node: ast.AST) -> set[str]:
    return {
        child.value.strip().lower()
        for child in ast.walk(node)
        if isinstance(child, ast.Constant) and isinstance(child.value, str) and child.value.strip()
    }


def identifiers(node: ast.AST) -> set[str]:
    values: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            values.add(child.id.lower())
        elif isinstance(child, ast.Attribute):
            values.add(child.attr.lower())
        elif isinstance(child, ast.arg):
            values.add(child.arg.lower())
    return values


def dict_keys(node: ast.AST) -> set[str]:
    output: set[str] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Dict):
            continue
        for key in child.keys:
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                output.add(key.value.strip().lower())
    return output


def callable_nodes(tree: ast.Module, callable_name: str) -> tuple[ast.ClassDef, ast.AST]:
    parts = callable_name.split(".")
    if len(parts) != 2:
        _fail("CALLABLE_FORMAT_INVALID", callable_name)
    class_name, method_name = parts
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == method_name:
                    return node, child
    _fail("CALLABLE_NOT_FOUND", callable_name)
    raise AssertionError


def profile_entry(source_root: Path, entry: dict[str, Any]) -> dict[str, Any]:
    source = entry["canonical_source"]
    path = source_root / source["implementation_path"]
    if not path.is_file():
        _fail("STRATEGY_SOURCE_MISSING", entry["strategy_id"])
    actual_sha = sha256(path)
    if actual_sha != source["source_sha256"]:
        _fail("STRATEGY_SOURCE_SHA_MISMATCH", entry["strategy_id"])
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(path))
    class_node, method = callable_nodes(tree, source["callable"])
    constants = string_constants(class_node)
    names = identifiers(class_node)
    keys = dict_keys(class_node)
    combined = constants | names | keys
    actions = sorted(ACTION_LITERALS & constants)
    indicators = sorted({token for token in INDICATOR_TOKENS if any(token in item for item in combined)})
    risk = sorted(RISK_KEYS & combined)
    state = sorted(STATE_KEYS & combined)
    sides = sorted({side for side in ("long", "short") if side in constants})
    comparisons = sum(isinstance(node, ast.Compare) for node in ast.walk(class_node))
    boolean_branches = sum(isinstance(node, (ast.If, ast.IfExp, ast.BoolOp)) for node in ast.walk(class_node))
    method_arguments = [argument.arg for argument in method.args.args]
    return {
        "strategy_id": entry["strategy_id"],
        "declared_family": entry["family"],
        "family_status": "DECLARED_LIFECYCLE_CLASSIFICATION_NOT_PROMOTION_AUTHORITY",
        "source_path": source["implementation_path"],
        "source_sha256": actual_sha,
        "callable": source["callable"],
        "callable_found": True,
        "callable_arguments": method_arguments,
        "source_parse_pass": True,
        "semantic_scope": "COMPLETE_STRATEGY_CLASS_AST",
        "action_literals": actions,
        "side_literals": sides,
        "indicator_semantic_tokens": indicators,
        "risk_output_keys": risk,
        "state_semantic_keys": state,
        "comparison_count": comparisons,
        "boolean_branch_count": boolean_branches,
        "supports_explicit_hold": "hold" in actions,
        "supports_explicit_entry": bool({"enter", "entry", "open", "buy", "sell"} & set(actions)),
        "supports_explicit_exit": bool({"exit", "close", "stop"} & set(actions)),
        "supports_position_management": bool({"add", "reduce", "partial", "partial30"} & set(actions)),
        "native_profile_complete": bool(actions) and bool(indicators or comparisons),
        "profile_authority": "SOURCE_DERIVED_STATIC_EVIDENCE_ONLY",
        "runtime_binding_allowed": False,
        "promotion_authority": False,
    }


def audit(source_root: Path) -> dict[str, Any]:
    rows = [profile_entry(source_root, entry) for entry in REGISTRY["entries"]]
    if len(rows) != 25 or len({row["strategy_id"] for row in rows}) != 25:
        _fail("EXACT25_PROFILE_COUNT_MISMATCH")
    incomplete = [row["strategy_id"] for row in rows if not row["native_profile_complete"]]
    indicator_counts = Counter(token for row in rows for token in row["indicator_semantic_tokens"])
    action_counts = Counter(action for row in rows for action in row["action_literals"])
    result = {
        "schema_version": "zel.strategy_native_profile.audit.v1",
        "version": VERSION,
        "state": "PASS_EXACT25_NATIVE_PROFILE_SOURCE_AUDIT" if not incomplete else "HOLD_EXACT25_NATIVE_PROFILE_GAPS",
        "strategy_count": 25,
        "source_sha_verified_count": 25,
        "callable_verified_count": 25,
        "native_profile_complete_count": 25 - len(incomplete),
        "incomplete_strategy_ids": incomplete,
        "indicator_token_counts": dict(sorted(indicator_counts.items())),
        "action_literal_counts": dict(sorted(action_counts.items())),
        "profiles": sorted(rows, key=lambda row: row["strategy_id"]),
        "parent_strategy_mutation_count": 0,
        "runtime_binding_allowed": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
    }
    result["result_sha256"] = canonical_sha(result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.source_root.resolve())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(result["state"])
    print(f"EVIDENCE={args.out}")
    return 0 if result["state"].startswith("PASS_") else 1


if __name__ == "__main__":
    raise SystemExit(main())
