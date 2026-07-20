#!/usr/bin/env python3
from __future__ import annotations

import ast
import hashlib
from pathlib import Path
from typing import Any

DIAGNOSTIC_TOKENS = (
    "audit", "smoke", "bootstrap", "probe", "diagnose", "report",
    "readiness", "display", "contract", "fixture", "example", "demo",
)


def path_kind(path: str) -> str:
    low = path.lower()
    parts = set(Path(low).parts)
    if parts & {"tests", "test", "docs", "examples", "notebooks"}:
        return "DIAGNOSTIC"
    if low.startswith("tools/") or any(token in low for token in DIAGNOSTIC_TOKENS):
        return "DIAGNOSTIC"
    if low.startswith(("config/", "configs/", "manifests/", "runtime/")):
        return "CONFIG"
    return "SOURCE"


def full_hash(node: ast.AST) -> str:
    payload = ast.dump(node, annotate_fields=True, include_attributes=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def semantic_hash(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    payload = {
        "async": isinstance(node, ast.AsyncFunctionDef),
        "positional": len(node.args.posonlyargs) + len(node.args.args),
        "kwonly": len(node.args.kwonlyargs),
        "vararg": node.args.vararg is not None,
        "kwarg": node.args.kwarg is not None,
        "body": ast.dump(ast.Module(body=node.body, type_ignores=[]), annotate_fields=True, include_attributes=False),
    }
    raw = repr(sorted(payload.items()))
    return hashlib.sha256(raw.encode()).hexdigest()


def function_rows(source: str, path: str) -> list[dict[str, Any]]:
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError:
        return []
    rows: list[dict[str, Any]] = []

    def visit(body: list[ast.stmt], owner: str | None = None) -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qname = f"{owner}.{node.name}" if owner else node.name
                rows.append({
                    "path": path,
                    "callable": qname,
                    "callable_leaf": node.name,
                    "path_kind": path_kind(path),
                    "full_hash": full_hash(node),
                    "semantic_hash": semantic_hash(node),
                })
            elif isinstance(node, ast.ClassDef):
                visit(node.body, node.name)
    visit(tree.body)
    return rows


def classify_strategy(
    strategy_id: str,
    reference_rows: list[dict[str, Any]],
    all_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    reference_semantics = {str(row.get("semantic_hash")) for row in reference_rows if row.get("semantic_hash")}
    expected_names = {str(row.get("callable_leaf")) for row in reference_rows if row.get("callable_leaf")}
    matches = [row for row in all_rows if row.get("semantic_hash") in reference_semantics]
    source_matches = [row for row in matches if row.get("path_kind") == "SOURCE"]
    diagnostic_matches = [row for row in matches if row.get("path_kind") == "DIAGNOSTIC"]
    config_matches = [row for row in matches if row.get("path_kind") == "CONFIG"]

    if len(source_matches) == 1:
        chosen = source_matches[0]
        classification = (
            "UNIQUE_PRODUCTION_ENGINE"
            if chosen.get("callable_leaf") in expected_names
            else "UNIQUE_PRODUCTION_ENGINE_CALLABLE_RENAME"
        )
        resolvable = True
    elif len(source_matches) > 1:
        chosen = None
        classification = "MULTIPLE_PRODUCTION_MATCHES"
        resolvable = False
    elif diagnostic_matches:
        chosen = None
        classification = "DIAGNOSTIC_ONLY_REFERENCE"
        resolvable = False
    elif config_matches:
        chosen = None
        classification = "CONFIG_ONLY_REFERENCE"
        resolvable = False
    else:
        chosen = None
        classification = "NO_IMPLEMENTATION_BODY_MATCH"
        resolvable = False

    return {
        "strategy_id": strategy_id,
        "classification": classification,
        "resolvable": resolvable,
        "canonical_candidate": chosen,
        "reference_count": len(reference_rows),
        "source_match_count": len(source_matches),
        "diagnostic_match_count": len(diagnostic_matches),
        "config_match_count": len(config_matches),
        "source_matches": source_matches[:20],
        "diagnostic_matches": diagnostic_matches[:20],
    }
