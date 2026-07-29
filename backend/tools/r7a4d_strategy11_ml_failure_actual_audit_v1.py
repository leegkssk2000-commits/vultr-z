from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
from pathlib import Path
from typing import Any

VERSION = "R7A4D_STRATEGY11_ML_FAILURE_ACTUAL_AUDIT_V1"
TEXT_SUFFIXES = {".py", ".json", ".yaml", ".yml", ".toml", ".ini", ".md", ".txt"}
SKIP_PARTS = {".git", ".venv", "venv", "node_modules", "artifacts", "dist", "build", "__pycache__"}
NAME_PATTERNS = {
    "ML_LIGHT": re.compile(r"(?:^|[_\-.])(ml[_\-.]?light|light[_\-.]?ml)(?:$|[_\-.])", re.I),
    "FAILURE_LEARNING": re.compile(r"(?:^|[_\-.])(failure[_\-.]?learning|fail[_\-.]?learning|failure[_\-.]?learner)(?:$|[_\-.])", re.I),
}
CONTENT_PATTERNS = {
    "ML_LIGHT": re.compile(r"\bML[_ -]?LIGHT\b|\bml_light\b", re.I),
    "FAILURE_LEARNING": re.compile(r"\bFAILURE[_ -]?LEARNING\b|\bfailure_learning\b", re.I),
}
CONTROL_TOKENS = {"gate", "fixture", "test", "workflow", "docs", "readme", "schema", "contract", "audit"}
FORBIDDEN_TOKENS = {
    "place_order", "open_order", "close_order", "amend_order", "cancel_order",
    "enable_live", "enable_paper", "write_strategy", "write_threshold", "write_weight",
    "registry_mutated", "ledger.append", "write_ledger", "promotion_authority=true",
    "execution_allowed=true", "order_authority=enabled", "override_sbot_veto",
}
COMMON_REQUIREMENTS = {
    "source_sha", "model_sha", "config_sha", "training_data_sha", "feature_lineage",
    "output_schema", "training_cutoff", "evaluation_start", "leakage", "calibration",
    "drift", "rollback", "deterministic", "observer", "research_only",
}
TYPE_REQUIREMENTS = {
    "ML_LIGHT": {
        "fit", "predict", "score", "regularization", "max_iter", "seed", "brier",
        "ece", "class_balance", "feature_order", "standardization",
    },
    "FAILURE_LEARNING": {
        "reason_code", "taxonomy", "severity", "confidence", "sample_count",
        "strategy_id", "symbol", "regime", "side", "hypothesis",
    },
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def classify_role(path: Path) -> str:
    lowered = {part.lower() for part in path.parts}
    stem_tokens = set(re.split(r"[_\-.]+", path.stem.lower()))
    tokens = lowered | stem_tokens
    if "fixture" in tokens:
        return "FIXTURE"
    if "test" in tokens or "tests" in tokens:
        return "TEST"
    if ".github" in lowered or "workflows" in lowered:
        return "WORKFLOW"
    if tokens & CONTROL_TOKENS:
        return "CONTROL_PLANE"
    if path.suffix == ".py":
        return "IMPLEMENTATION"
    return "CONFIG_OR_DOC"


def python_inventory(text: str) -> dict[str, Any]:
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return {"syntax_ok": False, "syntax_error": str(exc), "functions": [], "classes": [], "imports": [], "calls": []}
    functions: list[str] = []
    classes: list[str] = []
    imports: list[str] = []
    calls: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(node.name)
        elif isinstance(node, ast.ClassDef):
            classes.append(node.name)
        elif isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
        elif isinstance(node, ast.Call):
            target = node.func
            if isinstance(target, ast.Name):
                calls.append(target.id)
            elif isinstance(target, ast.Attribute):
                parts: list[str] = []
                current: Any = target
                while isinstance(current, ast.Attribute):
                    parts.append(current.attr)
                    current = current.value
                if isinstance(current, ast.Name):
                    parts.append(current.id)
                calls.append(".".join(reversed(parts)))
    return {
        "syntax_ok": True,
        "functions": sorted(set(functions)),
        "classes": sorted(set(classes)),
        "imports": sorted(set(imports)),
        "calls": sorted(set(calls)),
    }


def coverage(text: str, required: set[str]) -> dict[str, Any]:
    lowered = text.lower()
    present = sorted(token for token in required if token.lower() in lowered)
    missing = sorted(required - set(present))
    return {"present": present, "missing": missing, "ratio": len(present) / max(1, len(required))}


def scan(root: Path) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        rel = path.relative_to(root)
        if any(part in SKIP_PARTS for part in rel.parts):
            continue
        try:
            data = path.read_bytes()
            text = data.decode("utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        matched_types = sorted(
            kind for kind in NAME_PATTERNS
            if NAME_PATTERNS[kind].search(rel.as_posix()) or CONTENT_PATTERNS[kind].search(text)
        )
        if not matched_types:
            continue
        role = classify_role(rel)
        forbidden = sorted(token for token in FORBIDDEN_TOKENS if token in text.lower())
        py = python_inventory(text) if path.suffix == ".py" else None
        for kind in matched_types:
            common = coverage(text, COMMON_REQUIREMENTS)
            specific = coverage(text, TYPE_REQUIREMENTS[kind])
            rows.append({
                "observer_type": kind,
                "path": rel.as_posix(),
                "role": role,
                "sha256": sha256_bytes(data),
                "size_bytes": len(data),
                "forbidden_tokens": forbidden,
                "common_coverage": common,
                "type_coverage": specific,
                "python": py,
            })
    return evaluate(rows)


def evaluate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    types: dict[str, Any] = {}
    blockers: list[str] = []
    for kind in sorted(TYPE_REQUIREMENTS):
        candidates = [row for row in rows if row["observer_type"] == kind]
        implementations = [row for row in candidates if row["role"] == "IMPLEMENTATION"]
        qualified = [
            row for row in implementations
            if not row["forbidden_tokens"]
            and row["common_coverage"]["ratio"] >= 0.80
            and row["type_coverage"]["ratio"] >= 0.75
            and (row["python"] or {}).get("syntax_ok") is True
        ]
        if not implementations:
            blockers.append(f"{kind}_ACTUAL_IMPLEMENTATION_MISSING")
        elif not qualified:
            blockers.append(f"{kind}_IMPLEMENTATION_NOT_PRODUCTION_READY")
        types[kind] = {
            "candidate_file_count": len(candidates),
            "implementation_file_count": len(implementations),
            "qualified_implementation_count": len(qualified),
            "implementation_paths": [row["path"] for row in implementations],
            "qualified_paths": [row["path"] for row in qualified],
        }
    state = "PASS_ACTUAL_ML_FAILURE_IMPLEMENTATIONS" if not blockers else "HOLD_ACTUAL_ML_FAILURE_IMPLEMENTATIONS"
    result = {
        "schema_version": "strategy11.ml_failure_actual_audit.v1",
        "version": VERSION,
        "state": state,
        "types": types,
        "blocker_codes": blockers,
        "rows": rows,
        "control_plane_only_is_not_implementation": True,
        "fixture_evidence_is_not_production_evidence": True,
        "runtime_bound": False,
        "automatic_activation": False,
        "observer_only": True,
        "research_only": True,
        "promotion_authority": False,
        "protected_mutations": 0,
        "execution_allowed": False,
        "order_authority": "BLOCKED",
        "requested_action": "hold" if blockers else "observer_burnin_only",
    }
    result["audit_sha"] = hashlib.sha256(
        json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = scan(args.root.resolve())
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "audit.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (args.out / "summary.json").write_text(json.dumps({
        "state": result["state"],
        "blocker_codes": result["blocker_codes"],
        "types": result["types"],
        "audit_sha": result["audit_sha"],
        "research_only": True,
        "promotion_authority": False,
        "protected_mutations": 0,
        "execution_allowed": False,
        "order_authority": "BLOCKED",
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(result["state"], ",".join(result["blocker_codes"]) or "NO_BLOCKERS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
