#!/usr/bin/env python3
from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

DIAGNOSTIC = (
    "audit", "smoke", "bootstrap", "display", "probe", "readiness",
    "diagnose", "report", "test", "docs", "contract",
)


def diagnostic_path(path: str) -> bool:
    low = path.lower()
    return low.startswith(("tools/", "tests/", "test/", "docs/")) or any(
        token in low for token in DIAGNOSTIC
    )


def callable_exists(source: str, callable_name: str, filename: str) -> bool:
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError:
        return False
    target = callable_name.split(".")[-1]
    matches = [
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == target
    ]
    return len(matches) == 1


def engine_score(
    path: str,
    callable_name: str,
    strategy_id: str,
    prefixes: list[str],
) -> int:
    if diagnostic_path(path):
        return -10000
    prefix_score = None
    for index, prefix in enumerate(prefixes):
        if path.startswith(prefix):
            prefix_score = 300 - index * 20
            break
    if prefix_score is None:
        return -10000
    score = prefix_score + max(0, 20 - path.count("/"))
    normalized = strategy_id.lower().replace("-", "_")
    if normalized in Path(path).stem.lower().replace("-", "_"):
        score += 80
    if normalized in callable_name.lower().replace("-", "_"):
        score += 80
    return score


def select_unique_engine(candidates: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, str | None]:
    valid = [row for row in candidates if int(row.get("selection_score", -10000)) > -10000]
    valid.sort(
        key=lambda row: (
            int(row.get("selection_score", -10000)),
            str(row.get("implementation_path", "")),
            str(row.get("callable", "")),
        ),
        reverse=True,
    )
    if not valid:
        return None, "NO_PRODUCTION_ENGINE_CANDIDATE"
    top_score = int(valid[0]["selection_score"])
    top = [row for row in valid if int(row["selection_score"]) == top_score]
    if len(top) != 1:
        return None, "ENGINE_SELECTION_NOT_UNIQUE"
    return top[0], None


def escape_pointer(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def find_pointers(value: Any, target: str, path: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            found.extend(find_pointers(child, target, f"{path}/{escape_pointer(str(key))}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(find_pointers(child, target, f"{path}/{index}"))
    elif isinstance(value, str) and value == target:
        found.append(path or "/")
    return found


def manifest_score(path: str, hints: list[str]) -> int:
    low = path.lower()
    if diagnostic_path(path) or low.startswith("runtime/"):
        return -10000
    score = sum(30 for token in hints if token.lower() in low)
    if low.startswith((
        "config/", "configs/", "backend/config/",
        "backend/strategy25/", "manifests/",
    )):
        score += 100
    return score + max(0, 20 - path.count("/"))


def select_unique_manifest(candidates: list[dict[str, Any]], strategy_ids: list[str]) -> tuple[dict[str, Any] | None, str | None]:
    valid = [row for row in candidates if int(row.get("selection_score", -10000)) > -10000]
    valid.sort(key=lambda row: (int(row["selection_score"]), str(row["manifest_path"])), reverse=True)
    if not valid:
        return None, "NO_EXACT25_JSON_MANIFEST"
    top_score = int(valid[0]["selection_score"])
    top = [row for row in valid if int(row["selection_score"]) == top_score]
    if len(top) != 1:
        return None, "MANIFEST_SELECTION_NOT_UNIQUE"
    selected = top[0]
    if any(len(selected["strategy_pointers"].get(strategy_id, [])) != 1 for strategy_id in strategy_ids):
        return None, "MANIFEST_POINTER_NOT_UNIQUE"
    return selected, None
