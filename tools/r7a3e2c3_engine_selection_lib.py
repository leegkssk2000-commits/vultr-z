#!/usr/bin/env python3
from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

DIAGNOSTIC_PARTS = {"tests", "test", "docs", "examples", "notebooks", "tools"}
CONFIG_PARTS = {"config", "configs", "manifests", "runtime"}


def path_kind(path: str) -> str:
    parts = set(Path(path.lower()).parts)
    if parts & DIAGNOSTIC_PARTS:
        return "DIAGNOSTIC"
    if parts & CONFIG_PARTS or Path(path).suffix.lower() in {".json", ".yaml", ".yml", ".toml"}:
        return "CONFIG"
    return "SOURCE"


def module_variants(path: str) -> set[str]:
    value = path[:-3] if path.endswith(".py") else path
    value = value.replace("/", ".")
    if value.endswith(".__init__"):
        value = value[: -len(".__init__")]
    parts = value.split(".")
    variants = {value}
    for index in range(1, min(4, len(parts))):
        variants.add(".".join(parts[index:]))
    variants.add(Path(path).stem)
    return {item for item in variants if item}


def import_hits(source: str, candidate_path: str) -> int:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return 0
    variants = module_variants(candidate_path)
    hits = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if any(alias.name == item or alias.name.endswith("." + item) for item in variants):
                    hits += 1
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if any(module == item or module.endswith("." + item) or item.endswith("." + module) for item in variants):
                hits += 1
    return hits


def literal_hits(source: str, candidate_path: str, strategy_id: str) -> tuple[int, int]:
    modules = module_variants(candidate_path)
    normalized = candidate_path.replace("/", ".").removesuffix(".py")
    candidate_hits = source.count(candidate_path) + source.count(normalized)
    candidate_hits += sum(source.count(module) for module in modules if len(module) >= 6)
    strategy_hits = source.count(strategy_id)
    return candidate_hits, strategy_hits


def score_candidate(candidate: dict[str, Any], evidence: dict[str, int], strategy_id: str) -> dict[str, Any]:
    path = str(candidate.get("path") or candidate.get("implementation_path") or "")
    callable_name = str(candidate.get("callable") or "")
    normalized = strategy_id.lower().replace("-", "_")
    identity = 0
    if normalized in Path(path).stem.lower().replace("-", "_"):
        identity += 80
    if normalized in callable_name.lower().replace("-", "_"):
        identity += 80
    score = (
        min(evidence.get("runtime_hits", 0), 2) * 500
        + min(evidence.get("production_import_hits", 0), 3) * 120
        + min(evidence.get("production_literal_hits", 0), 3) * 60
        + min(evidence.get("config_hits", 0), 3) * 50
        + min(evidence.get("test_hits", 0), 3) * 10
        + min(evidence.get("candidate_strategy_literal_hits", 0), 1) * 100
        + identity
    )
    strong = bool(
        evidence.get("runtime_hits", 0)
        or evidence.get("production_import_hits", 0)
        or evidence.get("production_literal_hits", 0)
        or (
            evidence.get("candidate_strategy_literal_hits", 0)
            and evidence.get("config_hits", 0)
        )
    )
    return {
        **candidate,
        "selection_score": score,
        "strong_authority": strong,
        "identity_score": identity,
        "evidence": evidence,
    }


def select_candidate(rows: list[dict[str, Any]], minimum_margin: int) -> tuple[dict[str, Any] | None, list[dict[str, Any]], str | None]:
    ranked = sorted(
        rows,
        key=lambda row: (
            int(row.get("selection_score", 0)),
            str(row.get("path") or row.get("implementation_path") or ""),
            str(row.get("callable") or ""),
        ),
        reverse=True,
    )
    if len(ranked) != 2:
        return None, ranked, "CANDIDATE_COUNT_NOT_2"
    margin = int(ranked[0].get("selection_score", 0)) - int(ranked[1].get("selection_score", 0))
    if not ranked[0].get("strong_authority"):
        return None, ranked, "TOP_CANDIDATE_HAS_NO_STRONG_AUTHORITY"
    if margin < minimum_margin:
        return None, ranked, f"SELECTION_MARGIN_TOO_SMALL:{margin}"
    selected = {**ranked[0], "selection_margin": margin}
    return selected, ranked, None
