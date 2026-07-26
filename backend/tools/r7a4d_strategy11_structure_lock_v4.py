from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
V3_PATH = ROOT / "backend/tools/r7a4d_strategy11_structure_lock_v3.py"


def _load_v3() -> Any:
    name = "r7a4d_strategy11_structure_lock_v3_base"
    spec = importlib.util.spec_from_file_location(name, V3_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("STRUCTURE_LOCK_V3_IMPORT_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


base = _load_v3()
base.STRUCTURE_VERSION = "4.0"


def _positive_constant(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and node.value > 0


def _negative_constant(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.UnaryOp)
        and isinstance(node.op, ast.USub)
        and isinstance(node.operand, ast.Constant)
        and isinstance(node.operand.value, (int, float))
        and node.operand.value > 0
    )


def _future_relative_index(node: ast.AST) -> bool:
    """Detect direct iloc[i + N] future indexing without flagging causal negative slices."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return (isinstance(node.left, ast.Name) and _positive_constant(node.right)) or (
            isinstance(node.right, ast.Name) and _positive_constant(node.left)
        )
    return False


class CausalityVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.findings: list[dict[str, Any]] = []

    def _record(self, node: ast.AST, code: str) -> None:
        self.findings.append({"code": code, "line": getattr(node, "lineno", None), "column": getattr(node, "col_offset", None)})

    def visit_Name(self, node: ast.Name) -> None:
        if node.id in {"future_open", "future_high", "future_low", "future_close", "future_volume"}:
            self._record(node, f"FUTURE_NAME:{node.id}")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Attribute):
            name = node.func.attr
            if name in {"shift", "diff", "pct_change"} and node.args and _negative_constant(node.args[0]):
                self._record(node, f"NEGATIVE_{name.upper()}")
            if name == "rolling":
                for keyword in node.keywords:
                    if keyword.arg == "center" and isinstance(keyword.value, ast.Constant) and keyword.value.value is True:
                        self._record(node, "CENTERED_ROLLING")
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        if isinstance(node.value, ast.Attribute) and node.value.attr == "iloc":
            target = node.slice
            if _future_relative_index(target):
                self._record(node, "ILOC_FUTURE_RELATIVE_INDEX")
            elif isinstance(target, ast.Tuple):
                for element in target.elts:
                    if _future_relative_index(element):
                        self._record(node, "ILOC_FUTURE_RELATIVE_INDEX")
            elif isinstance(target, ast.Slice):
                for element in (target.lower, target.upper):
                    if element is not None and _future_relative_index(element):
                        self._record(node, "ILOC_FUTURE_RELATIVE_SLICE")
        self.generic_visit(node)


def validate_static_causality(root: Path, registry: Mapping[str, Any], blockers: list[str]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    for row in registry.get("entries", []):
        path = root / str(row["path"])
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            blockers.append(f"STATIC_PARSE:{row['strategy_id']}:{exc.lineno}:{exc.msg}")
            findings.append({"strategy_id": row["strategy_id"], "path": str(row["path"]), "code": "SYNTAX_ERROR", "line": exc.lineno})
            continue
        visitor = CausalityVisitor()
        visitor.visit(tree)
        for finding in visitor.findings:
            enriched = {"strategy_id": row["strategy_id"], "path": str(row["path"]), **finding}
            findings.append(enriched)
            blockers.append(f"STATIC_LOOKAHEAD:{row['strategy_id']}:{finding['code']}:{finding['line']}")
    return {"method": "AST_V4", "findings": findings}


base.validate_static_causality = validate_static_causality


if __name__ == "__main__":
    raise SystemExit(base.main())
