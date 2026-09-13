from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
from typing import Any

VERSION = "ZEL_EMA_EXCURSION_STATE_LINEAGE_V1"
SCHEMA = "zel.ema.excursion_state_lineage.receipt.v1"
EXPECTED_PRODUCER_SHA256 = "f01d4bd7ca63648170a2cb2e238b8155b01c3fb3ada88c24486278643ad87bc9"
TARGETS = {"max_favorable_usdt", "max_adverse_usdt"}


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def call_name(node: ast.Call) -> str:
    value = node.func
    parts: list[str] = []
    while isinstance(value, ast.Attribute):
        parts.append(value.attr)
        value = value.value
    if isinstance(value, ast.Name):
        parts.append(value.id)
    return ".".join(reversed(parts))


def operator_name(node: ast.AST) -> str:
    return type(node).__name__


def string_constants(node: ast.AST) -> list[str]:
    return sorted(
        {
            value.value
            for value in ast.walk(node)
            if isinstance(value, ast.Constant) and isinstance(value.value, str)
        }
    )


def numeric_constants(node: ast.AST) -> list[float]:
    values: set[float] = set()
    for value in ast.walk(node):
        if isinstance(value, ast.Constant) and isinstance(value.value, (int, float)) and not isinstance(value.value, bool):
            values.add(float(value.value))
    return sorted(values)


def statement_summary(
    statement: ast.stmt,
    *,
    function_name: str | None,
    function_line: int | None,
    class_name: str | None,
) -> dict[str, Any]:
    names = sorted({value.id for value in ast.walk(statement) if isinstance(value, ast.Name)})
    calls = sorted({call_name(value) for value in ast.walk(statement) if isinstance(value, ast.Call)})
    strings = string_constants(statement)
    operators = sorted(
        {
            operator_name(value)
            for value in ast.walk(statement)
            if isinstance(
                value,
                (
                    ast.operator,
                    ast.unaryop,
                    ast.boolop,
                    ast.cmpop,
                ),
            )
        }
    )
    target_keys = sorted(TARGETS.intersection(strings))
    lowered = {value.lower() for value in names + strings + calls}
    return {
        "line": int(getattr(statement, "lineno", 0) or 0),
        "end_line": int(getattr(statement, "end_lineno", 0) or 0),
        "node_type": type(statement).__name__,
        "class_name": class_name,
        "function_name": function_name,
        "function_line": function_line,
        "target_keys": target_keys,
        "names": names,
        "calls": calls,
        "strings": strings,
        "numbers": numeric_constants(statement),
        "operators": operators,
        "uses_high": any("high" in value for value in lowered),
        "uses_low": any("low" in value for value in lowered),
        "uses_close": any("close" in value for value in lowered),
        "uses_open": any("open" in value for value in lowered),
        "uses_entry": any("entry" in value for value in lowered),
        "uses_side": any("side" in value for value in lowered),
        "uses_qty": any(value in {"qty", "quantity", "size"} or "qty" in value for value in lowered),
        "uses_initial_risk": any("initial_risk" in value or "risk_usdt" in value for value in lowered),
        "uses_unrealized": any("unrealized" in value or "pnl" in value for value in lowered),
        "uses_max": any(value.endswith("max") or value == "max" or ".max" in value for value in lowered),
        "uses_min": any(value.endswith("min") or value == "min" or ".min" in value for value in lowered),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--producer",
        type=Path,
        default=Path("/home/z/z/tools/q4r3_exact25_dedicated_shadow_producer.py"),
    )
    parser.add_argument("--out", type=Path)
    parser.add_argument("--stdout", action="store_true")
    args = parser.parse_args()

    producer_sha = sha256_file(args.producer)
    if producer_sha != EXPECTED_PRODUCER_SHA256:
        raise RuntimeError(
            f"PRODUCER_SHA_MISMATCH:{producer_sha}:{EXPECTED_PRODUCER_SHA256}"
        )
    source = args.producer.read_text(encoding="utf-8", errors="strict")
    tree = ast.parse(source)

    contexts: list[dict[str, Any]] = []
    seen: set[tuple[int, str, str | None]] = set()

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.class_stack: list[tuple[str, int]] = []
            self.function_stack: list[tuple[str, int]] = []

        def visit_ClassDef(self, node: ast.ClassDef) -> Any:
            self.class_stack.append((node.name, node.lineno))
            self.generic_visit(node)
            self.class_stack.pop()

        def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
            self.function_stack.append((node.name, node.lineno))
            for statement in node.body:
                self.visit(statement)
            self.function_stack.pop()

        visit_AsyncFunctionDef = visit_FunctionDef

        def generic_visit(self, node: ast.AST) -> Any:
            if isinstance(node, ast.stmt):
                strings = set(string_constants(node))
                if TARGETS.intersection(strings):
                    function_name, function_line = self.function_stack[-1] if self.function_stack else (None, None)
                    class_name = self.class_stack[-1][0] if self.class_stack else None
                    key = (int(getattr(node, "lineno", 0) or 0), type(node).__name__, function_name)
                    if key not in seen:
                        seen.add(key)
                        contexts.append(
                            statement_summary(
                                node,
                                function_name=function_name,
                                function_line=function_line,
                                class_name=class_name,
                            )
                        )
                    return
            super().generic_visit(node)

    Visitor().visit(tree)
    contexts.sort(key=lambda row: (row["line"], row["node_type"], row["function_name"] or ""))

    target_counts = {
        target: sum(target in row["target_keys"] for row in contexts)
        for target in sorted(TARGETS)
    }
    update_contexts = [
        row
        for row in contexts
        if row["function_name"] != "close_position"
        or row["uses_high"]
        or row["uses_low"]
        or row["uses_close"]
        or row["uses_open"]
        or row["uses_unrealized"]
        or row["uses_max"]
        or row["uses_min"]
    ]
    semantic_modes: dict[str, int] = {}
    for row in update_contexts:
        if row["uses_high"] or row["uses_low"]:
            mode = "bar_high_low"
        elif row["uses_close"]:
            mode = "close_price"
        elif row["uses_unrealized"]:
            mode = "unrealized_pnl"
        else:
            mode = "state_passthrough_or_unknown"
        semantic_modes[mode] = semantic_modes.get(mode, 0) + 1

    blockers: list[str] = []
    if not contexts:
        blockers.append("EXCURSION_STATE_REFERENCES_NOT_FOUND")
    for target, count in target_counts.items():
        if count == 0:
            blockers.append(f"TARGET_REFERENCE_MISSING:{target}")
    if not update_contexts:
        blockers.append("EXCURSION_UPDATE_CONTEXT_NOT_FOUND")

    receipt = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "state": (
            "PASS_EMA_EXCURSION_STATE_LINEAGE_FOUND"
            if not blockers
            else "HOLD_EMA_EXCURSION_STATE_LINEAGE_INCOMPLETE"
        ),
        "producer_path": str(args.producer),
        "producer_sha256": producer_sha,
        "expected_producer_sha256": EXPECTED_PRODUCER_SHA256,
        "producer_sha_match": producer_sha == EXPECTED_PRODUCER_SHA256,
        "target_reference_counts": target_counts,
        "context_count": len(contexts),
        "update_context_count": len(update_contexts),
        "semantic_mode_counts": dict(sorted(semantic_modes.items())),
        "contexts": contexts,
        "blockers": blockers,
        "raw_code_published": False,
        "raw_trade_rows_published": False,
        "raw_prices_published": False,
        "canonical_mutated": False,
        "runtime_mutated": False,
        "formal_ledger_mutated": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
        "next": (
            "RECONSTRUCT_EXCURSION_FROM_PINNED_STATE_SEMANTICS"
            if not blockers
            else "RESOLVE_SINGLE_EXCURSION_LINEAGE_BLOCKER"
        ),
    }
    encoded = json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(encoded, encoding="utf-8")
    if args.stdout or not args.out:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
