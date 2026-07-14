from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from backend.engine.skill_resolver_v2_candidate import (
    SkillResolutionError,
    validate_registry,
)


ROOT = Path("/home/z/z")
ACTIVE_V1 = ROOT / "backend/contracts/ZOS_SKILL_REGISTRY_v1.json"
CANDIDATE_V2 = ROOT / "backend/contracts/ZOS_SKILL_REGISTRY_v2_candidate.json"
ACTIVE_RESOLVER = ROOT / "backend/engine/skill_resolver.py"
CANDIDATE_RESOLVER = ROOT / "backend/engine/skill_resolver_v2_candidate.py"

EXPECTED_METHOD_PROFILES = (
    "scalp_first/revert",
    "scalp_first/continuation",
    "scalp_first/liquidity_reclaim",
    "intraday/breakout_probe",
    "intraday/rescue",
    "tactical_swing/continuation",
)
EXPECTED_SKILLS = {
    "SK_ENTRY_LONG_BEAM",
    "SK_ENTRY_SHORT_BEAM",
    "SK_ADD_DCA",
    "SK_ADD_AVG_DOWN",
    "SK_ADD_WATER_ADD",
    "SK_ADD_PYRAMIDING",
    "SK_ADD_PROFITABLE_SCALE_IN",
    "SK_EXIT_PARTIAL_30",
    "SK_EXIT_TRAILING_STOP",
    "SK_EXIT_MFE_RUNNER",
    "SK_EXIT_RUNNER_HOLD",
    "SK_EXIT_TIME_STOP",
    "SK_EXIT_BREAK_EVEN_SHIFT",
    "SK_RISK_REDUCE_25",
    "SK_RISK_LOSS_CAP",
    "SK_RISK_COOLDOWN",
    "SK_RISK_EXPOSURE_LIMITER",
    "SK_RISK_LIQUIDATION_BUFFER_GUARD",
}
SKILL_ID_RE = re.compile(r"\bSK_[A-Z0-9_]+\b")
EXCLUDED_PARTS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "runtime",
    "runtime_results",
    "_TRASH",
    "backups",
    "archive",
    "dist",
    "build",
    "__pycache__",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def safe_files(roots: Iterable[Path]) -> Iterable[Path]:
    for root in roots:
        if not root.exists():
            continue
        if root.is_file():
            yield root
            continue
        for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
            current_path = Path(current)
            dirs[:] = [name for name in dirs if name not in EXCLUDED_PARTS]
            for name in files:
                path = current_path / name
                if any(part in EXCLUDED_PARTS for part in path.parts):
                    continue
                yield path


def text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def registry_summary(path: Path, candidate: bool) -> dict[str, Any]:
    data = load_json(path)
    rows = data.get("skills") if isinstance(data.get("skills"), list) else []
    ids = [str(row.get("skill_id")) for row in rows if isinstance(row, dict) and row.get("skill_id")]
    categories = Counter(
        str(row.get("category") or row.get("skill_category") or "")
        for row in rows
        if isinstance(row, dict)
    )
    errors: list[str] = []
    if not data:
        errors.append("registry_missing_or_invalid")
    if len(ids) != len(set(ids)):
        errors.append("duplicate_skill_ids")
    if candidate and data:
        try:
            validate_registry(data)
        except SkillResolutionError as exc:
            errors.append(str(exc))
    return {
        "path": str(path),
        "exists": path.is_file(),
        "sha256": sha256(path),
        "skill_count": len(ids),
        "unique_skill_count": len(set(ids)),
        "categories": dict(categories),
        "missing_expected_skills": sorted(EXPECTED_SKILLS - set(ids)) if candidate else [],
        "unexpected_candidate_skills": sorted(set(ids) - EXPECTED_SKILLS) if candidate else [],
        "errors": errors,
    }


def active_resolver_findings(path: Path) -> list[dict[str, str]]:
    source = text(path)
    checks = [
        (
            "registry_error_hidden",
            "except Exception" in source and "return {}" in source,
            "registry read failures collapse to an empty object",
        ),
        (
            "unknown_family_defaults_to_L",
            'else "L"' in source,
            "unknown bot families are silently coerced to L",
        ),
        (
            "legacy_scale_in_ambiguous",
            '"SK_POS_SCALE_IN": bool(behavior.get("allow_dca"))' in source,
            "loss averaging and profitable pyramiding share one capability",
        ),
        (
            "context_metadata_only",
            all(token in source for token in ("regime", "deploy_stage", "market"))
            and "context_gate" not in source,
            "regime/deploy_stage/market are returned but not used as gates",
        ),
        (
            "category_number_mismatch_risk",
            '"1 전략 스킬"' in source,
            "resolver expects numbered category labels while v1 rows use unnumbered labels",
        ),
    ]
    return [
        {"code": code, "severity": "C" if code != "context_metadata_only" else "M", "detail": detail}
        for code, present, detail in checks
        if present
    ]


def python_contract(path: Path) -> dict[str, Any]:
    source = text(path)
    if not source:
        return {"path": str(path), "exists": False, "ast_valid": False, "functions": []}
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return {
            "path": str(path),
            "exists": True,
            "ast_valid": False,
            "syntax_error": f"{exc.lineno}:{exc.msg}",
            "functions": [],
        }
    functions = sorted(
        node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    )
    return {
        "path": str(path),
        "exists": True,
        "sha256": sha256(path),
        "ast_valid": True,
        "functions": functions,
    }


def extract_strategy_names(data: Any) -> set[str]:
    result: set[str] = set()
    if isinstance(data, dict):
        for key, value in data.items():
            key_text = str(key).strip()
            if key_text in {"strategy", "strategy_id", "strategy_name", "name", "id"}:
                if isinstance(value, str) and value.strip():
                    result.add(value.strip())
            result.update(extract_strategy_names(value))
    elif isinstance(data, list):
        for value in data:
            result.update(extract_strategy_names(value))
    return result


def discover_exact25() -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    roots = [ROOT / "backend", ROOT / "config", ROOT / "data"]
    for path in safe_files(roots):
        if path.suffix.lower() != ".json":
            continue
        lower = path.name.lower()
        if not any(token in lower for token in ("manifest", "registry", "strategy")):
            continue
        data = load_json(path)
        names = extract_strategy_names(data)
        if len(names) >= 20:
            candidates.append(
                {
                    "path": str(path),
                    "strategy_count": len(names),
                    "names": sorted(names),
                    "sha256": sha256(path),
                }
            )
    exact = [row for row in candidates if row["strategy_count"] == 25]
    selected = exact[0] if len(exact) == 1 else None
    return {
        "candidate_count": len(candidates),
        "exact25_candidate_count": len(exact),
        "selected": selected,
        "candidates": sorted(candidates, key=lambda row: (-int(row["strategy_count"]), row["path"]))[:20],
        "state": "PASS" if selected else "HOLD",
        "reason": "unique_exact25_manifest" if selected else "unique_exact25_manifest_not_proven",
    }


def scan_skill_references() -> dict[str, Any]:
    roots = [
        ROOT / "backend/strategies",
        ROOT / "backend/strategies_v4",
        ROOT / "backend/legendary_rebuild/strategies",
        ROOT / "backend/engine",
        ROOT / "backend/bots",
        ROOT / "backend/trade_methods",
        ROOT / "skills",
    ]
    by_id: dict[str, list[str]] = defaultdict(list)
    files_scanned = 0
    for path in safe_files(roots):
        if path.suffix.lower() not in {".py", ".json", ".yaml", ".yml", ".md"}:
            continue
        source = text(path)
        if not source:
            continue
        files_scanned += 1
        for skill_id in sorted(set(SKILL_ID_RE.findall(source))):
            by_id[skill_id].append(str(path))
    return {
        "files_scanned": files_scanned,
        "referenced_skill_count": len(by_id),
        "references": {key: sorted(set(value)) for key, value in sorted(by_id.items())},
        "candidate_v2_unreferenced": sorted(EXPECTED_SKILLS - set(by_id)),
    }


def strategy_hook_matrix(strategy_names: Iterable[str]) -> list[dict[str, Any]]:
    roots = [ROOT / "backend/strategies", ROOT / "backend/strategies_v4", ROOT / "backend/legendary_rebuild/strategies"]
    sources = list(safe_files(roots))
    rows: list[dict[str, Any]] = []
    for strategy in sorted(set(strategy_names)):
        matched = [path for path in sources if strategy in path.stem]
        skill_ids: set[str] = set()
        hook_tokens: set[str] = set()
        for path in matched:
            source = text(path)
            skill_ids.update(SKILL_ID_RE.findall(source))
            for token in (
                "allow_dca",
                "scale_in",
                "avg_down",
                "water_add",
                "pyramid",
                "partial",
                "trailing",
                "runner",
                "mfe",
                "beam",
            ):
                if token in source.lower():
                    hook_tokens.add(token)
        rows.append(
            {
                "strategy_id": strategy,
                "source_count": len(matched),
                "explicit_skill_ids": sorted(skill_ids),
                "implicit_hook_tokens": sorted(hook_tokens),
                "explicit_binding_ready": bool(skill_ids),
            }
        )
    return rows


def compatibility_rows(
    strategy_names: Iterable[str], registry: Mapping[str, Any]
) -> list[dict[str, Any]]:
    skill_rows = registry.get("skills") if isinstance(registry.get("skills"), list) else []
    result: list[dict[str, Any]] = []
    for strategy_id in sorted(set(strategy_names)):
        for method_id in EXPECTED_METHOD_PROFILES:
            for skill in skill_rows:
                if not isinstance(skill, dict):
                    continue
                result.append(
                    {
                        "strategy_id": strategy_id,
                        "method_id": method_id,
                        "skill_id": skill.get("skill_id"),
                        "skill_category": skill.get("category"),
                        "risk_tier": skill.get("risk_tier"),
                        "registry_state": skill.get("state"),
                        "static_verdict": "UNKNOWN_REQUIRES_RUNTIME_TRIGGER_AND_OUTCOME_EVIDENCE",
                        "binding_allowed": False,
                    }
                )
    return result


def grade(summary: Mapping[str, Any]) -> tuple[str, list[str]]:
    failures: list[str] = []
    candidate = summary["registry_v2"]
    if candidate["errors"]:
        failures.append("v2_registry_invalid")
    if candidate["skill_count"] != 18:
        failures.append("v2_skill_count_not_18")
    if candidate["missing_expected_skills"]:
        failures.append("required_skills_missing")
    if summary["exact25"]["state"] != "PASS":
        failures.append("unique_exact25_manifest_unproven")
    if summary["candidate_resolver"]["ast_valid"] is not True:
        failures.append("candidate_resolver_invalid")
    if summary["strategy_binding_coverage_pct"] < 100.0:
        failures.append("strategy_skill_binding_incomplete")
    if summary["active_resolver_findings"]:
        failures.append("active_resolver_critical_gaps")
    return ("S_STATIC_CONTRACT_READY" if not failures else "HOLD_GAPS_REMAIN", failures)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0].keys()) if rows else ["strategy_id", "method_id", "skill_id"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def run(output: Path, matrix_output: Path) -> dict[str, Any]:
    registry_v2_data = load_json(CANDIDATE_V2)
    exact25 = discover_exact25()
    selected_names = exact25.get("selected", {}).get("names", []) if exact25.get("selected") else []
    hooks = strategy_hook_matrix(selected_names)
    explicit_count = sum(1 for row in hooks if row["explicit_binding_ready"])
    coverage_pct = round(explicit_count / len(hooks) * 100.0, 3) if hooks else 0.0

    summary: dict[str, Any] = {
        "schema": "q4r3_exact25_skill_registry_v2_audit_v1",
        "generated_at": now_iso(),
        "mode": "read_only_static_audit",
        "registry_v1": registry_summary(ACTIVE_V1, candidate=False),
        "registry_v2": registry_summary(CANDIDATE_V2, candidate=True),
        "active_resolver": python_contract(ACTIVE_RESOLVER),
        "candidate_resolver": python_contract(CANDIDATE_RESOLVER),
        "active_resolver_findings": active_resolver_findings(ACTIVE_RESOLVER),
        "exact25": exact25,
        "skill_references": scan_skill_references(),
        "strategy_hooks": hooks,
        "strategy_binding_coverage_pct": coverage_pct,
        "expected_method_profile_count": len(EXPECTED_METHOD_PROFILES),
        "expected_skill_count": len(EXPECTED_SKILLS),
        "runtime_mutation_allowed": False,
        "strategy_modified": False,
        "trade_method_modified": False,
        "producer_modified": False,
        "writer_modified": False,
        "formal_ledger_modified": False,
        "paper_enabled": False,
        "live_enabled": False,
        "order_enabled": False,
        "order_authority": "blocked",
        "execution_authority": "none",
        "action": "hold",
    }
    verdict, failures = grade(summary)
    summary["state"] = "PASS" if not summary["registry_v2"]["errors"] else "FAILED"
    summary["verdict"] = verdict
    summary["grade_blockers"] = failures
    summary["next_action"] = (
        "INSTALL_READONLY_ACTIVE_BINDING_AUDIT_AFTER_STORAGE_HYGIENE_PASS"
        if failures
        else "BUILD_COUNTERFACTUAL_SKILL_PROJECTION_OBSERVER"
    )

    matrix = compatibility_rows(selected_names, registry_v2_data)
    summary["compatibility_matrix_rows"] = len(matrix)
    summary["compatibility_expected_rows"] = len(selected_names) * len(EXPECTED_METHOD_PROFILES) * 18
    summary["compatibility_complete"] = bool(selected_names) and len(matrix) == summary["compatibility_expected_rows"]

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(output)
    write_csv(matrix_output, matrix)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--matrix-output", type=Path, required=True)
    args = parser.parse_args()
    summary = run(args.output, args.matrix_output)
    print(
        json.dumps(
            {
                "state": summary["state"],
                "verdict": summary["verdict"],
                "grade_blockers": summary["grade_blockers"],
                "strategy_binding_coverage_pct": summary["strategy_binding_coverage_pct"],
                "compatibility_matrix_rows": summary["compatibility_matrix_rows"],
                "next_action": summary["next_action"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if summary["state"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
