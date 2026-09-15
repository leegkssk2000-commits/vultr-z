"""Check the immutable evaluator bytes and its separate static type contract.

The saved TrendRider manifests pin this exact source. This guard replaces
formatting/lint/direct-source typing for that one file, without executing it.
The .pyi remains subject to Black, Ruff and Mypy.
"""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "backend/research/rebuild/a1_exact25_generic_evaluator_v1.py"
ARCHIVE = (
    "research/campaigns/economic7_20260915/recovered_originals/"
    "a1_exact25_generic_evaluator_v1.py.txt"
)
ORIGINAL_SHA256 = "074ccb2a0bec3454e7900d86deb365b47c652dc5f024884124692496a4ffcf5d"
CONSTANT_TYPES = {
    "ROOT": "Path",
    "LEDGER_PATH": "Path",
    "INVENTORY_PATH": "Path",
    "COST_PATH": "Path",
    "KLINE_API": "str",
    "DEPTH_API": "str",
    "FUNDING_API": "str",
}


class FreezeError(ValueError):
    """The immutable source or its type contract changed."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise FreezeError(message)


def _signature(node: ast.FunctionDef) -> str:
    signature = ast.FunctionDef(
        name=node.name,
        args=node.args,
        body=[ast.Pass()],
        decorator_list=node.decorator_list,
        returns=node.returns,
        type_comment=node.type_comment,
    )
    return ast.dump(signature, include_attributes=False)


def _exports(tree: ast.Module) -> dict[str, tuple[str, str, int]]:
    result: dict[str, tuple[str, str, int]] = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                binding = alias.asname or alias.name.split(".")[0]
                imported = alias.name if alias.asname else alias.name.split(".")[0]
                result[binding] = ("module", imported, 0)
        elif isinstance(node, ast.ImportFrom) and node.module != "__future__":
            for alias in node.names:
                result[alias.asname or alias.name] = (
                    "from " + str(node.module),
                    alias.name,
                    node.level,
                )
    return result


def verify(root: Path = ROOT) -> dict[str, str]:
    try:
        source = (root / SOURCE).read_bytes()
        archive = (root / ARCHIVE).read_bytes()
        stub = (root / SOURCE).with_suffix(".pyi").read_bytes()
    except OSError as exc:
        raise FreezeError("FROZEN_EXACT25_REQUIRED_FILE_MISSING") from exc
    for label, content in (("SOURCE", source), ("ARCHIVE", archive)):
        _require(
            hashlib.sha256(content).hexdigest() == ORIGINAL_SHA256,
            "FROZEN_EXACT25_" + label + "_SHA_MISMATCH",
        )
    try:
        source_tree = ast.parse(source)
        stub_tree = ast.parse(stub)
    except SyntaxError as exc:
        raise FreezeError("FROZEN_EXACT25_INVALID_PYTHON") from exc
    original_functions = {
        node.name: _signature(node)
        for node in source_tree.body
        if isinstance(node, ast.FunctionDef)
    }
    stub_functions = {
        node.name: _signature(node)
        for node in stub_tree.body
        if isinstance(node, ast.FunctionDef)
    }
    _require(
        len(stub_functions)
        == sum(isinstance(node, ast.FunctionDef) for node in stub_tree.body),
        "FROZEN_EXACT25_STUB_DUPLICATE_FUNCTION",
    )
    _require(
        original_functions == stub_functions,
        "FROZEN_EXACT25_STUB_SIGNATURE_MISMATCH",
    )
    allowed_nodes = (
        ast.Import,
        ast.ImportFrom,
        ast.FunctionDef,
        ast.AnnAssign,
        ast.Expr,
    )
    _require(
        all(isinstance(node, allowed_nodes) for node in stub_tree.body),
        "FROZEN_EXACT25_STUB_UNEXPECTED_DECLARATION",
    )
    for node in stub_tree.body:
        if isinstance(node, ast.FunctionDef):
            _require(
                len(node.body) == 1
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and node.body[0].value.value is Ellipsis,
                "FROZEN_EXACT25_STUB_FUNCTION_BODY",
            )
        elif isinstance(node, ast.AnnAssign):
            _require(
                node.value is None and isinstance(node.target, ast.Name),
                "FROZEN_EXACT25_STUB_CONSTANT_VALUE",
            )
        elif isinstance(node, ast.Expr):
            _require(
                isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str),
                "FROZEN_EXACT25_STUB_EXPRESSION",
            )
    constants = {
        node.target.id: ast.unparse(node.annotation)
        for node in stub_tree.body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }
    _require(constants == CONSTANT_TYPES, "FROZEN_EXACT25_STUB_CONSTANT_MISMATCH")
    _require(
        _exports(source_tree) == _exports(stub_tree),
        "FROZEN_EXACT25_STUB_IMPORT_EXPORT_MISMATCH",
    )
    return {"state": "PASS_FROZEN_EXACT25_SOURCE_AND_STUB", "sha256": ORIGINAL_SHA256}


if __name__ == "__main__":
    print(verify())
