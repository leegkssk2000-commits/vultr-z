from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


SNAPSHOT_ROOT = Path(
    "runtime_results/q4r3/strategy_source_snapshot/source"
)
REGISTRY_REL = Path("backend/contracts/ZOS_SKILL_REGISTRY_v1.json")
RESOLVER_REL = Path("backend/engine/skill_resolver.py")
STRATEGY_MAP_REL = Path(
    "runtime_results/q4r3/strategy_source_snapshot/strategy_map.json"
)

CANONICAL_CATEGORIES = {
    "전략 스킬",
    "포지션 관리 스킬",
    "봇 런타임 스킬",
    "실행 스킬",
    "포트폴리오/멀티봇 스킬",
    "운영/안전 스킬",
    "AI Advisor 스킬",
    "학습/적응 스킬",
}

REQUIRED_SKILL_IDS = {
    "SK_ENTRY_LONG_BEAM",
    "SK_ENTRY_SHORT_BEAM",
    "SK_ADD_AVG_DOWN",
    "SK_ADD_DCA",
    "SK_ADD_WATER_ADD",
    "SK_ADD_PYRAMIDING",
    "SK_ADD_PROFITABLE_SCALE_IN",
    "SK_EXIT_PARTIAL_30",
    "SK_EXIT_TRAILING_STOP",
    "SK_EXIT_MFE_RUNNER",
    "SK_EXIT_RUNNER_HOLD",
    "SK_EXIT_BREAK_EVEN_SHIFT",
    "SK_EXIT_TIME_STOP",
    "SK_RISK_REDUCE_25",
    "SK_RISK_LOSS_CAP",
    "SK_RISK_COOLDOWN",
    "SK_RISK_EXPOSURE_LIMITER",
    "SK_RISK_LIQUIDATION_BUFFER_GUARD",
}

LEGACY_SKILL_IDS = {
    "SK_POS_SCALE_IN",
    "SK_POS_SCALE_OUT",
    "SK_POS_TIME_STOP",
    "SK_POS_TRAILING_STOP",
    "SK_POS_BREAK_EVEN_SHIFT",
    "SK_BOT_COOLDOWN",
}

REQUIRED_REGISTRY_FIELDS = {
    "skill_id",
    "skill_version",
    "skill_sha256",
    "skill_category",
    "owner",
    "implementation_path",
    "runtime_allowed",
    "observer_allowed",
    "writes_to",
    "reads_from",
    "trigger_contract",
    "effect_contract",
    "risk_contract",
    "lineage_contract",
    "outcome_metrics",
    "family_scope",
    "method_scope",
    "regime_scope",
    "side_scope",
    "conflicts_with",
    "requires",
    "gate_level",
    "fallback_action",
}

SKILL_TERMS = {
    "long_beam": ("longbeam", "long_beam", "long beam", "롱빔"),
    "short_beam": ("shortbeam", "short_beam", "short beam", "숏빔"),
    "avg_down": ("avg_down", "average_down", "averaging_down", "물타기"),
    "dca": ("dca",),
    "water_add": ("water_add",),
    "pyramiding": ("pyramiding", "pyramid", "불타기"),
    "profitable_scale_in": ("profitable_scale_in", "profit_scale_in"),
    "partial": ("partial30", "partial_30", "partial_reduce", "scale_out"),
    "trailing": ("trailing_stop", "trailing"),
    "mfe_runner": ("mfe_runner", "mfe runner"),
    "runner_hold": ("runner_hold", "runner hold"),
    "time_stop": ("time_stop", "time exit"),
    "loss_cap": ("loss_cap", "loss cap"),
    "reduce25": ("reduce25", "reduce_25"),
    "exposure_limiter": ("exposure_limiter", "exposure limit"),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)


def iter_strategy_paths(repo_root: Path) -> list[Path]:
    strategy_map_path = repo_root / STRATEGY_MAP_REL
    paths: set[Path] = set()

    if strategy_map_path.is_file():
        data = load_json(strategy_map_path)
        for value in walk(data):
            if not isinstance(value, str):
                continue
            normalized = value.replace("\\", "/")
            if not normalized.endswith(".py"):
                continue
            if "/strategies/" not in f"/{normalized}":
                continue
            candidate = repo_root / SNAPSHOT_ROOT / normalized
            if candidate.is_file():
                paths.add(candidate)

    fallback_root = repo_root / SNAPSHOT_ROOT / "backend/strategies"
    if fallback_root.is_dir():
        for path in fallback_root.glob("*.py"):
            if path.name not in {"__init__.py", "common_utils.py", "registry.py"}:
                paths.add(path)

    return sorted(paths)


def walk(value: Any) -> Iterable[Any]:
    yield value
    if isinstance(value, dict):
        for item in value.values():
            yield from walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk(item)


def resolver_ast_findings(source: str) -> dict[str, Any]:
    tree = ast.parse(source)
    function_args: dict[str, list[str]] = {}
    used_names: Counter[str] = Counter()
    string_literals: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            function_args[node.name] = [arg.arg for arg in node.args.args]
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            used_names[node.id] += 1
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            string_literals.add(node.value)

    resolve_args = function_args.get("resolve_effective_skills", [])
    context_args = [name for name in ("regime", "deploy_stage", "market") if name in resolve_args]
    dead_context = [name for name in context_args if used_names[name] <= 1]

    prefixed_categories = sorted(
        value
        for value in string_literals
        if re.match(r"^[1-8]\s", value)
    )

    return {
        "silent_registry_read_fallback": "except Exception:" in source and "return {}" in source,
        "unknown_family_defaults_to_l": 'else "L"' in source,
        "validator_called_by_resolver": "validate_strategy_skill_refs(" in source.split("def resolve_effective_skills", 1)[1],
        "schema_lock_used_for_decision": "schema_lock" in source.split("def resolve_effective_skills", 1)[1].split("return {", 1)[0],
        "context_parameters": context_args,
        "dead_context_parameters": dead_context,
        "prefixed_category_literals": prefixed_categories,
        "set_to_list_without_sort": "list(active_os_guards)" in source,
        "generic_scale_in_uses_allow_dca": '"SK_POS_SCALE_IN": bool(behavior.get("allow_dca"))' in source,
        "runtime_disallowed_can_enter_active_guards": (
            "active_os_guards.add(sid)" in source
            and "if _is_learning_only(row):" in source
        ),
        "mandatory_guard_existence_validated": "MANDATORY_OS_GUARDS" in source and "missing_in_registry" in source.split("MANDATORY_OS_GUARDS", 1)[1].split("def resolve_effective_skills", 1)[0],
    }


def audit(repo_root: Path) -> dict[str, Any]:
    registry_path = repo_root / SNAPSHOT_ROOT / REGISTRY_REL
    resolver_path = repo_root / SNAPSHOT_ROOT / RESOLVER_REL

    if not registry_path.is_file():
        raise FileNotFoundError(f"REGISTRY_MISSING:{registry_path}")
    if not resolver_path.is_file():
        raise FileNotFoundError(f"RESOLVER_MISSING:{resolver_path}")

    registry = load_json(registry_path)
    skills = registry.get("skills") if isinstance(registry, dict) else None
    if not isinstance(skills, list):
        raise ValueError("REGISTRY_SKILLS_LIST_REQUIRED")

    ids: list[str] = []
    duplicate_ids: list[str] = []
    seen: set[str] = set()
    category_counts: Counter[str] = Counter()
    missing_fields_by_skill: dict[str, list[str]] = {}
    malformed_rows: list[int] = []

    for index, row in enumerate(skills):
        if not isinstance(row, dict):
            malformed_rows.append(index)
            continue
        skill_id = str(row.get("skill_id") or "").strip()
        if not skill_id:
            malformed_rows.append(index)
            continue
        if skill_id in seen:
            duplicate_ids.append(skill_id)
        seen.add(skill_id)
        ids.append(skill_id)
        category = str(row.get("skill_category") or "").strip()
        category_counts[category] += 1
        missing = sorted(REQUIRED_REGISTRY_FIELDS - set(row))
        if missing:
            missing_fields_by_skill[skill_id] = missing

    resolver_source = resolver_path.read_text(encoding="utf-8")
    resolver = resolver_ast_findings(resolver_source)

    registry_categories = set(category_counts)
    resolver_categories = set(resolver["prefixed_category_literals"])
    normalized_resolver_categories = {re.sub(r"^[1-8]\s+", "", value) for value in resolver_categories}

    strategy_paths = iter_strategy_paths(repo_root)
    strategies_with_skill_refs: list[str] = []
    term_hits: dict[str, list[str]] = defaultdict(list)

    for path in strategy_paths:
        text = path.read_text(encoding="utf-8", errors="replace")
        lowered = text.lower()
        relative = str(path.relative_to(repo_root))
        if "skill_refs" in text:
            strategies_with_skill_refs.append(relative)
        for group, terms in SKILL_TERMS.items():
            if any(term.lower() in lowered for term in terms):
                term_hits[group].append(relative)

    missing_required_ids = sorted(REQUIRED_SKILL_IDS - set(ids))
    present_legacy_ids = sorted(LEGACY_SKILL_IDS & set(ids))

    critical_findings: list[str] = []
    major_findings: list[str] = []

    if registry_categories != normalized_resolver_categories:
        critical_findings.append("REGISTRY_RESOLVER_CATEGORY_ENUM_MISMATCH")
    if resolver["silent_registry_read_fallback"]:
        critical_findings.append("REGISTRY_READ_FAILURE_SILENTLY_BECOMES_EMPTY_REGISTRY")
    if resolver["unknown_family_defaults_to_l"]:
        critical_findings.append("UNKNOWN_BOT_FAMILY_DEFAULTS_TO_L_INSTEAD_OF_BLOCK")
    if resolver["runtime_disallowed_can_enter_active_guards"]:
        critical_findings.append("RUNTIME_DISALLOWED_SKILL_CAN_ENTER_ACTIVE_OS_GUARDS")
    if missing_required_ids:
        major_findings.append("REQUIRED_DIRECTION_ADD_EXIT_RISK_SKILLS_MISSING")
    if resolver["generic_scale_in_uses_allow_dca"]:
        major_findings.append("LOSS_DIRECTION_AND_PROFIT_DIRECTION_ADD_CONFLATED")
    if not resolver["validator_called_by_resolver"]:
        major_findings.append("RESOLVER_DOES_NOT_ENFORCE_REFERENCE_VALIDATOR")
    if resolver["dead_context_parameters"]:
        major_findings.append("REGIME_DEPLOY_STAGE_MARKET_ARE_METADATA_ONLY")
    if resolver["set_to_list_without_sort"]:
        major_findings.append("EFFECTIVE_GUARD_ORDER_NOT_CANONICAL")
    if not resolver["mandatory_guard_existence_validated"]:
        major_findings.append("MANDATORY_GUARD_EXISTENCE_NOT_FAIL_CLOSED")
    if missing_fields_by_skill:
        major_findings.append("PER_SKILL_VERSION_IMPLEMENTATION_TRIGGER_LINEAGE_CONTRACTS_MISSING")
    if len(strategies_with_skill_refs) < len(strategy_paths):
        major_findings.append("CANONICAL_STRATEGY_TO_SKILL_MAPPING_INCOMPLETE")

    state = "VIOLATION" if critical_findings or major_findings else "PASS"
    severity = "C" if critical_findings else ("M" if major_findings else "none")

    return {
        "schema": "q4r3_exact25_skill_registry_static_audit_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": state,
        "severity": severity,
        "action": "hold",
        "observer_only": True,
        "registry": {
            "path": str(registry_path.relative_to(repo_root)),
            "sha256": sha256(registry_path),
            "meta": registry.get("meta", {}),
            "skill_count": len(ids),
            "duplicate_skill_ids": sorted(set(duplicate_ids)),
            "malformed_row_indexes": malformed_rows,
            "category_counts": dict(sorted(category_counts.items())),
            "category_values": sorted(registry_categories),
            "required_skill_count": len(REQUIRED_SKILL_IDS),
            "missing_required_skill_ids": missing_required_ids,
            "present_legacy_skill_ids": present_legacy_ids,
            "skills_missing_v2_contract_fields_count": len(missing_fields_by_skill),
            "skills_missing_v2_contract_fields": missing_fields_by_skill,
        },
        "resolver": {
            "path": str(resolver_path.relative_to(repo_root)),
            "sha256": sha256(resolver_path),
            **resolver,
            "normalized_resolver_category_values": sorted(normalized_resolver_categories),
            "registry_resolver_category_match": registry_categories == normalized_resolver_categories,
        },
        "strategy_binding": {
            "strategy_file_count": len(strategy_paths),
            "strategy_files_with_skill_refs_count": len(strategies_with_skill_refs),
            "strategy_files_with_skill_refs": strategies_with_skill_refs,
            "term_hits": {key: sorted(value) for key, value in sorted(term_hits.items())},
        },
        "critical_findings": critical_findings,
        "major_findings": major_findings,
        "verdict": (
            "SKILL_REGISTRY_AND_RESOLVER_NOT_BINDING_READY"
            if state == "VIOLATION"
            else "SKILL_REGISTRY_STATIC_CONTRACT_READY"
        ),
        "next_action": (
            "BUILD_ISOLATED_SKILL_REGISTRY_V2_AND_ACTIVE_BINDING_AUDIT"
            if state == "VIOLATION"
            else "RUN_ACTIVE_BINDING_AUDIT"
        ),
        "safety": {
            "paper_enabled": False,
            "live_enabled": False,
            "order_enabled": False,
            "order_authority": "blocked",
            "execution_authority": "none",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = audit(args.repo_root.resolve())
    atomic_json(args.output, payload)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
