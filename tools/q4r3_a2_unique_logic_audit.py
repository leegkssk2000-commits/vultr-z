#!/usr/bin/env python3
"""Read-only Route A/A2 unique-logic audit.

Purpose:
- inspect the actual server-side strategy sources;
- compare only Config + strategy() decision logic;
- remove shared/common scaffolding across candidate files;
- determine whether an existing module is truly an EMA Ribbon/Beam entry core,
  merely adjacent, or whether A2 is not implemented/bound.

No production files are modified.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

STRATEGY_DIR = Path("/home/z/z/backend/strategies")
PREV = Path("/home/z/z/runtime/q4r3_route_a_a2_semantic_audit_latest.json")
OUT = Path("/home/z/z/runtime/q4r3_route_a_a2_unique_logic_audit_latest.json")

TOP_N = 8
COMMON_RATIO = 0.60

EMA_PATTERNS = (
    r"ema[_\s-]?(?:fast|short|[0-9]+)",
    r"ema[_\s-]?(?:slow|long|[0-9]+)",
    r"ewm\(",
)
RIBBON_PATTERNS = (
    r"ribbon",
    r"ema[_\s-]?width",
    r"spread[_\s-]?pct",
    r"band[_\s-]?width",
    r"compression",
    r"expansion",
    r"squeeze",
)
SLOPE_PATTERNS = (
    r"slope",
    r"diff\(",
    r"pct_change\(",
    r"rising",
    r"falling",
)
STACK_PATTERNS = (
    r"ema\w*\s*>\s*ema\w*",
    r"ema\w*\s*<\s*ema\w*",
    r"fast\w*\s*>\s*slow\w*",
    r"fast\w*\s*<\s*slow\w*",
)
RECLAIM_PATTERNS = (
    r"reclaim",
    r"pullback",
    r"retest",
    r"cross(?:ed)?[_\s-]?(?:above|below)",
)
BEAM_PATTERNS = (
    r"long_beam",
    r"short_beam",
    r"beam",
)

NEGATIVE_FAMILY_PATTERNS = {
    "mean_reversion": (r"mean[_\s-]?revert", r"vwap_revert", r"reversion"),
    "liquidity_sweep": (r"liquidity[_\s-]?sweep", r"sweep", r"stop[_\s-]?hunt"),
    "pivot_reversal": (r"pivot", r"reversal", r"swing[_\s-]?fail"),
    "pure_breakout": (r"donchian", r"turtle", r"breakout"),
    "divergence": (r"divergence", r"mfi", r"rsi_div"),
}


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def source_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def find_strategy_node(tree: ast.AST) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "strategy":
            return node
    return None


def extract_config_nodes(tree: ast.AST) -> list[ast.ClassDef]:
    out: list[ast.ClassDef] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and (
            node.name.lower().endswith("config")
            or any(
                isinstance(d, ast.Name) and d.id == "dataclass"
                for d in node.decorator_list
            )
        ):
            out.append(node)
    return out


def node_source(text: str, node: ast.AST | None) -> str:
    if node is None or not hasattr(node, "lineno"):
        return ""
    lines = text.splitlines()
    start = max(int(getattr(node, "lineno", 1)) - 1, 0)
    end = int(getattr(node, "end_lineno", start + 1))
    return "\n".join(lines[start:end])


def normalize_expr(expr: str) -> str:
    expr = re.sub(r"\s+", " ", expr.strip().lower())
    expr = re.sub(r"['\"][^'\"]+['\"]", "<str>", expr)
    expr = re.sub(r"\b\d+(?:\.\d+)?\b", "<num>", expr)
    expr = re.sub(r"\b(?:cfg|config)\.", "cfg.", expr)
    return expr


def extract_conditions(node: ast.AST | None) -> list[str]:
    if node is None:
        return []
    out: list[str] = []
    for child in ast.walk(node):
        if isinstance(child, (ast.If, ast.IfExp, ast.While, ast.Assert)):
            test = getattr(child, "test", None)
            if test is None:
                continue
            try:
                out.append(normalize_expr(ast.unparse(test)))
            except Exception:
                continue
    return list(dict.fromkeys(out))


def extract_returns(node: ast.AST | None) -> list[str]:
    if node is None:
        return []
    out: list[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Return) and child.value is not None:
            try:
                out.append(normalize_expr(ast.unparse(child.value)))
            except Exception:
                continue
    return list(dict.fromkeys(out))


def extract_reason_strings(node: ast.AST | None) -> list[str]:
    if node is None:
        return []
    out: list[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            value = child.value.strip()
            low = value.lower()
            if any(token in low for token in ("entry", "setup", "reclaim", "break", "beam", "ribbon", "squeeze", "trend", "sweep", "revert", "pivot")):
                out.append(value)
    return list(dict.fromkeys(out))


def extract_names(node: ast.AST | None) -> list[str]:
    if node is None:
        return []
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            names.add(child.id)
        elif isinstance(child, ast.Attribute):
            try:
                names.add(ast.unparse(child))
            except Exception:
                pass
    return sorted(names)


def config_fields(classes: Iterable[ast.ClassDef], text: str) -> list[str]:
    fields: list[str] = []
    for cls in classes:
        for child in cls.body:
            if isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
                value = ""
                if child.value is not None:
                    try:
                        value = ast.unparse(child.value)
                    except Exception:
                        value = ""
                fields.append(f"{child.target.id}={value}" if value else child.target.id)
            elif isinstance(child, ast.Assign):
                for target in child.targets:
                    if isinstance(target, ast.Name):
                        try:
                            value = ast.unparse(child.value)
                        except Exception:
                            value = ""
                        fields.append(f"{target.id}={value}" if value else target.id)
    return list(dict.fromkeys(fields))


def has_any(text: str, patterns: Iterable[str]) -> bool:
    low = text.lower()
    return any(re.search(pattern, low) for pattern in patterns)


def classify_family(text: str) -> dict[str, bool]:
    return {
        name: has_any(text, patterns)
        for name, patterns in NEGATIVE_FAMILY_PATTERNS.items()
    }


def load_candidates() -> list[str]:
    if PREV.exists():
        try:
            obj = json.loads(read_text(PREV))
            top = obj.get("top5") or []
            names = [str(row.get("module", "")).split(".")[-1] for row in top]
            names = [name for name in names if name]
            if names:
                return names[:TOP_N]
        except Exception:
            pass

    return [
        "squeeze_break",
        "liquidity_sweep",
        "mfi_rsi_div",
        "obv_trend",
        "anchor_vwap_trend",
        "vwap_revert",
        "turtle_trend",
        "trend_ma_macd",
    ][:TOP_N]


def inspect_module(name: str) -> dict[str, Any]:
    path = STRATEGY_DIR / f"{name}.py"
    if not path.exists():
        return {"module": f"backend.strategies.{name}", "path": str(path), "exists": False}

    text = read_text(path)
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return {
            "module": f"backend.strategies.{name}",
            "path": str(path),
            "exists": True,
            "syntax_error": repr(exc),
        }

    strategy = find_strategy_node(tree)
    configs = extract_config_nodes(tree)
    strategy_src = node_source(text, strategy)
    config_src = "\n".join(node_source(text, node) for node in configs)
    decision_text = "\n".join((strategy_src, config_src))

    conditions = extract_conditions(strategy)
    returns = extract_returns(strategy)
    reasons = extract_reason_strings(strategy)
    names = extract_names(strategy)
    fields = config_fields(configs, text)

    return {
        "module": f"backend.strategies.{name}",
        "path": str(path),
        "exists": True,
        "sha256": source_hash(text),
        "strategy_found": strategy is not None,
        "strategy_lines": [
            int(getattr(strategy, "lineno", 0)) if strategy is not None else None,
            int(getattr(strategy, "end_lineno", 0)) if strategy is not None else None,
        ],
        "config_classes": [node.name for node in configs],
        "config_fields": fields,
        "conditions": conditions,
        "returns": returns,
        "reason_strings": reasons,
        "referenced_names": names,
        "features": {
            "ema": has_any(decision_text, EMA_PATTERNS),
            "ema_stack": has_any(decision_text, STACK_PATTERNS),
            "ribbon_width": has_any(decision_text, RIBBON_PATTERNS),
            "slope": has_any(decision_text, SLOPE_PATTERNS),
            "pullback_reclaim": has_any(decision_text, RECLAIM_PATTERNS),
            "beam_semantic": has_any(decision_text, BEAM_PATTERNS),
        },
        "negative_family": classify_family(decision_text + "\n" + name),
        "strategy_source_excerpt": strategy_src[:12000],
    }


def common_conditions(reports: list[dict[str, Any]]) -> set[str]:
    valid = [row for row in reports if row.get("strategy_found")]
    threshold = max(2, int(len(valid) * COMMON_RATIO + 0.9999))
    counts: Counter[str] = Counter()
    for row in valid:
        counts.update(set(row.get("conditions", [])))
    return {condition for condition, count in counts.items() if count >= threshold}


def unique_score(row: dict[str, Any], shared: set[str]) -> dict[str, Any]:
    if not row.get("strategy_found"):
        return {"score": -999, "classification": "invalid"}

    unique_conditions = [c for c in row.get("conditions", []) if c not in shared]
    unique_text = "\n".join(
        unique_conditions
        + row.get("reason_strings", [])
        + row.get("config_fields", [])
        + row.get("referenced_names", [])
    )

    features = {
        "ema": has_any(unique_text, EMA_PATTERNS),
        "ema_stack": has_any(unique_text, STACK_PATTERNS),
        "ribbon_width": has_any(unique_text, RIBBON_PATTERNS),
        "slope": has_any(unique_text, SLOPE_PATTERNS),
        "pullback_reclaim": has_any(unique_text, RECLAIM_PATTERNS),
        "beam_semantic": has_any(unique_text, BEAM_PATTERNS),
    }

    score = 0
    score += 2 if features["ema"] else 0
    score += 5 if features["ema_stack"] else 0
    score += 5 if features["ribbon_width"] else 0
    score += 3 if features["slope"] else 0
    score += 3 if features["pullback_reclaim"] else 0
    score += 2 if features["beam_semantic"] else 0

    negative = row.get("negative_family", {})
    score -= 5 if negative.get("mean_reversion") else 0
    score -= 5 if negative.get("liquidity_sweep") else 0
    score -= 4 if negative.get("pivot_reversal") else 0
    score -= 4 if negative.get("pure_breakout") else 0
    score -= 3 if negative.get("divergence") else 0

    identity_count = sum(
        bool(features[key])
        for key in ("ema_stack", "ribbon_width", "slope", "pullback_reclaim")
    )

    if score >= 13 and identity_count >= 3 and not any(negative.values()):
        classification = "EMA_RIBBON_CORE_CANDIDATE"
    elif score >= 8 and identity_count >= 2:
        classification = "EMA_RIBBON_ADJACENT"
    else:
        classification = "NOT_A2_CORE"

    return {
        "score": score,
        "classification": classification,
        "unique_features": features,
        "unique_conditions": unique_conditions,
        "shared_conditions_removed": len(row.get("conditions", [])) - len(unique_conditions),
        "negative_family": negative,
    }


def main() -> None:
    candidates = load_candidates()
    reports = [inspect_module(name) for name in candidates]
    shared = common_conditions(reports)

    ranked: list[dict[str, Any]] = []
    for row in reports:
        evaluation = unique_score(row, shared)
        ranked.append({
            "module": row.get("module"),
            "path": row.get("path"),
            **evaluation,
            "config_fields": row.get("config_fields", []),
            "reason_strings": row.get("reason_strings", []),
            "strategy_lines": row.get("strategy_lines"),
            "sha256": row.get("sha256"),
        })

    ranked.sort(key=lambda row: (row.get("score", -999), row.get("module", "")), reverse=True)
    core = [row for row in ranked if row.get("classification") == "EMA_RIBBON_CORE_CANDIDATE"]

    if len(core) == 1:
        status = "PASS_A2_UNIQUE_CORE_IDENTIFIED"
        verdict = "EXISTING_A2_CORE_FOUND"
        best = core[0]
    elif len(core) > 1:
        status = "HOLD_A2_MULTIPLE_UNIQUE_CORES"
        verdict = "MULTIPLE_A2_LIKE_MODULES_REQUIRE_ENTRY_REPLAY"
        best = core[0]
    else:
        status = "HOLD_A2_CORE_NOT_IMPLEMENTED_OR_NOT_BOUND"
        verdict = "NO_EXISTING_MODULE_HAS_UNIQUE_EMA_RIBBON_CORE_IDENTITY"
        best = ranked[0] if ranked else None

    payload = {
        "status": status,
        "verdict": verdict,
        "candidate_source": str(PREV),
        "candidates": candidates,
        "common_ratio": COMMON_RATIO,
        "shared_conditions_removed": sorted(shared),
        "best_candidate": best,
        "ranked": ranked,
        "raw_reports": reports,
        "interpretation": {
            "core_found": "Only a unique EMA-stack/ribbon-width/slope/reclaim decision core counts as A2.",
            "adjacent": "Shared helpers, tags, exits, and generic EMA references are insufficient.",
            "not_found": "If no core is found, A2 is missing/unbound and must not be substituted with vwap_revert, squeeze_break, or another family.",
        },
        "order_authority": "blocked",
        "execution_authority": "none",
        "real_order_enabled": False,
        "paper_request_written": False,
        "live_execution_allowed": False,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    print(json.dumps({
        "status": status,
        "verdict": verdict,
        "best_candidate": best,
        "top5": ranked[:5],
        "shared_conditions_removed_count": len(shared),
        "out": str(OUT),
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
