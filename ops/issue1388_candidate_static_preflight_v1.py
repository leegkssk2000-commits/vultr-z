"""Fail-fast, read-only candidate DSL admission for already saved A5 proposals.

No rewriting AI proposals, no strategy replay, no market API, no economic
claim. A strict record-complete breakout comparison against a max containing
its OWN close is unsatisfiable; roc(close,n) is invalid in the actual engine
whose roc signature accepts only a single lookback argument.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

CLOSED_BAR_SERIES = {"open", "high", "low", "close"}
ISSUE1388_TFS = {"15m", "30m", "1h"}  # do not silently change research scope
SOURCE = Path("backend/research/architecture_factory/a1_top5_evolutionary_synthesis_latest.json")

def _series(arg: ast.AST) -> str | None:
    if isinstance(arg, ast.Name):
        return arg.id
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return arg.value
    return None

def _impossible_pair(left: ast.AST, op: ast.cmpop, right: ast.AST) -> bool:
    """Only structural impossibilities, no tuned or guessed alpha rule."""
    def max_including_bar(a: ast.AST, b: ast.AST) -> bool:
        if not isinstance(b, ast.Call) or not isinstance(b.func, ast.Name):
            return False
        if b.func.id != "highest" or len(b.args) != 2:
            return False
        n = b.args[1]
        if not isinstance(n, ast.Constant) or type(n.value) is not int or n.value < 1:
            return False
        source, top = _series(b.args[0]), _series(a)
        # high_t >= {open_t,close_t,low_t}; close_t >= low_t.
        if source == "high" and top in CLOSED_BAR_SERIES:
            return True
        if source == "close" and top == "close":
            return True
        if source == "open" and top == "open":
            return True
        return False
    def min_including_bar(a: ast.AST, b: ast.AST) -> bool:
        if not isinstance(b, ast.Call) or not isinstance(b.func, ast.Name):
            return False
        if b.func.id != "lowest" or len(b.args) != 2:
            return False
        n = b.args[1]
        if not isinstance(n, ast.Constant) or type(n.value) is not int or n.value < 1:
            return False
        source, low = _series(b.args[0]), _series(a)
        if source == "low" and low in CLOSED_BAR_SERIES:
            return True
        if source == "close" and low == "close":
            return True
        if source == "open" and low == "open":
            return True
        return False
    if isinstance(op, ast.Gt):
        return max_including_bar(left, right)
    if isinstance(op, ast.Lt):
        return max_including_bar(right, left) or min_including_bar(left, right)
    # highest(source,n)>close is NOT impossible; lowest(source,n)>close
    # isn't universally false. Avoid all guessed simplifications.
    return False

def _guaranteed_false(node: ast.AST) -> bool:
    if isinstance(node, ast.Expression):
        return _guaranteed_false(node.body)
    if isinstance(node, ast.BoolOp):
        xs = [_guaranteed_false(v) for v in node.values]
        return any(xs) if isinstance(node.op, ast.And) else all(xs) if isinstance(node.op, ast.Or) else False
    if isinstance(node, ast.Compare) and len(node.ops) == 1:
        return _impossible_pair(node.left, node.ops[0], node.comparators[0])
    return False

def inspect_spec(spec: Mapping[str, Any], *, issue1388_scope: bool = True) -> dict[str, Any]:
    entry = str(spec.get("entry_rule") or "")
    issues: list[str] = []
    parsed = None
    try:
        parsed = ast.parse(entry, mode="eval")
    except SyntaxError:
        issues.append("UNPARSEABLE_ENTRY_EXPRESSION")
    if parsed is not None:
        for node in ast.walk(parsed):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in {"roc", "ret"} and len(node.args) > 1:
                    issues.append("EXECUTOR_FUNCTION_ARITY_MISMATCH:" + node.func.id)
                if node.keywords:
                    issues.append("EXECUTOR_UNSUPPORTED_KEYWORD_CALL")
        if _guaranteed_false(parsed):
            issues.append("UNREACHABLE_CURRENT_BAR_EXTREME")
    tf = str(spec.get("bar_interval") or "")
    if issue1388_scope and tf not in ISSUE1388_TFS:
        issues.append("OUTSIDE_CURRENT_ISSUE1388_TIMEFRAME:" + tf)
    issues = sorted(set(issues))
    return {
        "state": "BLOCKED_STATIC_RULE_OR_SCOPE" if issues else "STATIC_ONLY_PASS_NEEDS_NATIVE_RUNTIME_AND_DENSITY",
        "hard_issues": issues,
        "formal_economic_credit": 0,
        "new_economic_run": False,
        "executable_proved": False,
    }

def audit_saved(path: Path = SOURCE) -> dict[str, Any]:
    raw = path.read_bytes()
    z = json.loads(raw)
    rows = z.get("initial_candidates") or []
    if not isinstance(rows, list):
        raise RuntimeError("MALFORMED_SAVED_CANDIDATE_LIST")
    observations = []
    for item in rows:
        if not isinstance(item, dict):
            raise RuntimeError("CANDIDATE_SCHEMA_BROKEN")
        candidate_id = item.get("candidate_id")
        spec = item.get("executable_spec")
        if not candidate_id or not isinstance(spec, dict):
            raise RuntimeError("CANDIDATE_SPEC_MISSING")
        observations.append({
            "candidate_id": candidate_id,
            "strategy_id": item.get("strategy_id"),
            "entry_rule": spec.get("entry_rule"),
            "bar_interval": spec.get("bar_interval"),
            "static": inspect_spec(spec),
        })
    return {
        "schema": "zel.issue1388.candidate_static_admission.v1",
        "source": str(path),
        "source_bytes_sha256": hashlib.sha256(raw).hexdigest(),
        "model_created_economic_results_recomputed": False,
        "source_economic_attempt_replayed": False,
        "new_candidate_or_identity": False,
        "stale_result_reset": False,
        "formal_survivor_credit": 0,
        "candidates": observations,
        "blocked": sum(v["static"]["state"].startswith("BLOCKED") for v in observations),
        "not_static_blocked": sum(not v["static"]["state"].startswith("BLOCKED") for v in observations),
        "limitations": [
            "Static preflight proves impossibility/arity only, not profitability.",
            "Current A5 source is historical frozen output; no retrofit or retry.",
            "DSL and original/cost/fill/market-data causal admission are separate.",
        ],
    }

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=SOURCE)
    parser.add_argument("--output", type=Path, required=True)
    opts = parser.parse_args()
    output = audit_saved(opts.input)
    opts.output.parent.mkdir(parents=True, exist_ok=True)
    opts.output.write_text(json.dumps(output, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print("STATIC_CANDIDATE_ADMISSION",json.dumps({
        "source_sha256": output["source_bytes_sha256"],
        "blocked": output["blocked"],
        "not_static_blocked": output["not_static_blocked"],
        "findings": [{
            "id": v["candidate_id"], "issues":v["static"]["hard_issues"],
        } for v in output["candidates"]],
        "economic_credit":0,
    },sort_keys=True),flush=True)

if __name__ == "__main__":
    main()
