#!/usr/bin/env python3
"""Read-only semantic discovery for Route A A2 EMA Ribbon/Beam candidates.

Runs against the checked-out ZEL tree on the server. It does not import strategy
modules, write production files, or touch registry/paper/live/order paths.
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path("/home/z/z")
STRATEGY_DIR = ROOT / "backend" / "strategies"
OUT = ROOT / "runtime" / "q4r3_route_a_a2_semantic_audit_latest.json"

EMA_PATTERNS = {
    "ema_fast_slow": re.compile(r"ema\w*.*ema\w*|fast_ema|slow_ema", re.I | re.S),
    "ema_stack": re.compile(r"ema\w*\s*[<>]\s*ema\w*|ema\d+\s*[<>]\s*ema\d+", re.I),
    "ribbon_width": re.compile(r"ribbon|ema_spread|ema_gap|band_width|width", re.I),
    "slope": re.compile(r"slope|diff\(|pct_change|gradient", re.I),
    "compression_expansion": re.compile(r"compress|expand|squeeze|release", re.I),
    "pullback_reclaim": re.compile(r"pullback|reclaim|retest", re.I),
    "trend_alignment": re.compile(r"trend.*align|align.*trend|higher.*timeframe|htf", re.I | re.S),
    "beam_semantic": re.compile(r"long_beam|short_beam|beam_entry|beam_signal", re.I),
}

NEGATIVE_PATTERNS = {
    "mean_reversion": re.compile(r"revert|mean_reversion|zscore|deviation_from_vwap", re.I),
    "pure_breakout": re.compile(r"donchian|turtle|breakout_high|breakout_low", re.I),
    "pivot_reversal": re.compile(r"pivot|swing_fail|reversal", re.I),
}


def parse(path: Path) -> dict[str, Any]:
    src = path.read_text(errors="ignore")
    try:
        tree = ast.parse(src)
        syntax_error = None
    except Exception as exc:  # pragma: no cover - diagnostic only
        tree = None
        syntax_error = repr(exc)

    funcs: list[str] = []
    classes: list[str] = []
    strings: list[str] = []
    if tree is not None:
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                funcs.append(node.name)
            elif isinstance(node, ast.ClassDef):
                classes.append(node.name)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                strings.append(node.value[:240])

    positive = {name: bool(rx.search(src)) for name, rx in EMA_PATTERNS.items()}
    negative = {name: bool(rx.search(src)) for name, rx in NEGATIVE_PATTERNS.items()}

    score = (
        3 * positive["ema_fast_slow"]
        + 4 * positive["ema_stack"]
        + 4 * positive["ribbon_width"]
        + 2 * positive["slope"]
        + 3 * positive["compression_expansion"]
        + 2 * positive["pullback_reclaim"]
        + 2 * positive["trend_alignment"]
        + 1 * positive["beam_semantic"]
        - 4 * negative["mean_reversion"]
        - 2 * negative["pure_breakout"]
        - 2 * negative["pivot_reversal"]
    )

    has_strategy = "strategy" in funcs
    if not has_strategy:
        score -= 8

    return {
        "path": str(path),
        "module": f"backend.strategies.{path.stem}",
        "sha256": hashlib.sha256(src.encode()).hexdigest(),
        "syntax_error": syntax_error,
        "has_strategy": has_strategy,
        "functions": sorted(set(funcs)),
        "classes": sorted(set(classes)),
        "positive_features": positive,
        "negative_features": negative,
        "semantic_score": score,
        "evidence_strings": [s for s in strings if re.search(r"ema|ribbon|beam|reclaim|pullback|slope", s, re.I)][:20],
    }


def main() -> int:
    if not STRATEGY_DIR.exists():
        raise SystemExit(f"STRATEGY_DIR_MISSING:{STRATEGY_DIR}")

    reports = [parse(p) for p in sorted(STRATEGY_DIR.glob("*.py")) if not p.name.startswith("_")]
    ranked = sorted(reports, key=lambda r: (r["semantic_score"], r["has_strategy"]), reverse=True)
    eligible = [r for r in ranked if r["has_strategy"] and r["syntax_error"] is None and r["semantic_score"] >= 7]

    if not eligible:
        status = "HOLD_A2_SEMANTIC_CANDIDATE_NOT_FOUND"
        best = None
    elif len(eligible) == 1 or eligible[0]["semantic_score"] >= eligible[1]["semantic_score"] + 3:
        status = "PASS_A2_SEMANTIC_CANDIDATE_UNAMBIGUOUS"
        best = eligible[0]
    else:
        status = "HOLD_A2_SEMANTIC_CANDIDATE_AMBIGUOUS"
        best = eligible[0]

    payload = {
        "status": status,
        "scope": "Route A A2 semantic source audit only",
        "best_candidate": best,
        "eligible_candidates": eligible,
        "ranked_candidates": ranked,
        "guard": {
            "read_only": True,
            "order_authority": "blocked",
            "execution_authority": "none",
            "real_order_enabled": False,
            "paper_request_written": False,
            "live_execution_allowed": False,
        },
        "next": "Only an unambiguous semantic candidate may proceed to 5-symbol OOS replay.",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({
        "status": status,
        "best_candidate": None if best is None else {
            "module": best["module"],
            "path": best["path"],
            "semantic_score": best["semantic_score"],
            "positive_features": best["positive_features"],
            "negative_features": best["negative_features"],
        },
        "eligible_count": len(eligible),
        "top5": [
            {"module": r["module"], "score": r["semantic_score"], "positive": r["positive_features"], "negative": r["negative_features"]}
            for r in ranked[:5]
        ],
        "out": str(OUT),
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
