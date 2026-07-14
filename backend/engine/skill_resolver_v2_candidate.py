from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


CONTRACTS_DIR = Path("/home/z/z/backend/contracts")
REGISTRY_PATH = CONTRACTS_DIR / "ZOS_SKILL_REGISTRY_v2_candidate.json"

ALLOWED_FAMILIES = {"L", "M", "O", "S"}
ALLOWED_STATES = {
    "declared",
    "observer_only",
    "counterfactual_ready",
    "candidate_shadow",
    "paper_candidate",
    "live_eligible",
    "quarantined",
    "archived",
}
ALLOWED_CATEGORIES = {
    "entry_direction",
    "loss_direction_add",
    "profit_direction_add",
    "exit_management",
    "risk_control",
}


class SkillResolutionError(RuntimeError):
    """Raised only for invalid registry structure, never for normal HOLD routes."""


@dataclass(frozen=True)
class SkillContext:
    strategy_id: str
    method_id: str
    bot_family: str
    regime: str
    deploy_stage: str
    market: str
    position_id: str | None = None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "SkillContext":
        return cls(
            strategy_id=_required_text(raw, "strategy_id"),
            method_id=_required_text(raw, "method_id"),
            bot_family=_required_family(raw.get("bot_family")),
            regime=_required_text(raw, "regime"),
            deploy_stage=_required_text(raw, "deploy_stage"),
            market=_required_text(raw, "market"),
            position_id=_optional_text(raw.get("position_id")),
        )


def _required_text(raw: Mapping[str, Any], key: str) -> str:
    value = _optional_text(raw.get(key))
    if value is None:
        raise SkillResolutionError(f"CONTEXT_FIELD_MISSING:{key}")
    return value


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _required_family(value: Any) -> str:
    text = _optional_text(value)
    if text is None:
        raise SkillResolutionError("CONTEXT_FIELD_MISSING:bot_family")
    family = text.upper()
    if family not in ALLOWED_FAMILIES:
        raise SkillResolutionError(f"UNKNOWN_BOT_FAMILY:{text}")
    return family


def load_registry(path: Path = REGISTRY_PATH) -> dict[str, Any]:
    if not path.is_file():
        raise SkillResolutionError(f"REGISTRY_MISSING:{path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SkillResolutionError(f"REGISTRY_READ_FAILED:{path}:{type(exc).__name__}") from exc
    if not isinstance(data, dict):
        raise SkillResolutionError("REGISTRY_ROOT_NOT_OBJECT")
    validate_registry(data)
    return data


def validate_registry(registry: Mapping[str, Any]) -> None:
    if registry.get("schema") != "zos_skill_registry_v2_candidate":
        raise SkillResolutionError("REGISTRY_SCHEMA_MISMATCH")
    if registry.get("activation_allowed") is not False:
        raise SkillResolutionError("CANDIDATE_REGISTRY_ACTIVATION_MUST_BE_FALSE")
    rows = registry.get("skills")
    if not isinstance(rows, list) or not rows:
        raise SkillResolutionError("REGISTRY_SKILLS_EMPTY")

    ids: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise SkillResolutionError(f"SKILL_ROW_NOT_OBJECT:{index}")
        skill_id = _optional_text(row.get("skill_id"))
        if skill_id is None:
            raise SkillResolutionError(f"SKILL_ID_MISSING:{index}")
        if skill_id in ids:
            raise SkillResolutionError(f"SKILL_ID_DUPLICATE:{skill_id}")
        ids.add(skill_id)
        if row.get("category") not in ALLOWED_CATEGORIES:
            raise SkillResolutionError(f"SKILL_CATEGORY_INVALID:{skill_id}:{row.get('category')}")
        if row.get("state") not in ALLOWED_STATES:
            raise SkillResolutionError(f"SKILL_STATE_INVALID:{skill_id}:{row.get('state')}")
        if not isinstance(row.get("required_inputs"), list):
            raise SkillResolutionError(f"SKILL_REQUIRED_INPUTS_INVALID:{skill_id}")
        if not isinstance(row.get("trigger_contract"), list):
            raise SkillResolutionError(f"SKILL_TRIGGER_CONTRACT_INVALID:{skill_id}")
        if not isinstance(row.get("evidence_required"), list):
            raise SkillResolutionError(f"SKILL_EVIDENCE_INVALID:{skill_id}")
        if not isinstance(row.get("performance_metrics"), list):
            raise SkillResolutionError(f"SKILL_METRICS_INVALID:{skill_id}")

    for row in rows:
        skill_id = str(row["skill_id"])
        for relation in ("dependencies", "conflicts"):
            values = row.get(relation, [])
            if not isinstance(values, list):
                raise SkillResolutionError(f"SKILL_RELATION_INVALID:{skill_id}:{relation}")
            unknown = sorted({str(value) for value in values} - ids)
            if unknown:
                raise SkillResolutionError(
                    f"SKILL_RELATION_UNKNOWN:{skill_id}:{relation}:{','.join(unknown)}"
                )


def _index(registry: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(row["skill_id"]): dict(row) for row in registry["skills"]}


def migrate_requested_ids(
    requested_ids: Iterable[str], registry: Mapping[str, Any]
) -> tuple[list[str], dict[str, str]]:
    migrations = registry.get("legacy_migration", {})
    if not isinstance(migrations, dict):
        raise SkillResolutionError("LEGACY_MIGRATION_NOT_OBJECT")

    resolved: list[str] = []
    blocked: dict[str, str] = {}
    for raw in requested_ids:
        skill_id = str(raw).strip()
        if not skill_id:
            continue
        migration = migrations.get(skill_id)
        if not isinstance(migration, dict):
            resolved.append(skill_id)
            continue
        if migration.get("auto_map") is True and _optional_text(migration.get("target")):
            resolved.append(str(migration["target"]))
        else:
            blocked[skill_id] = "ambiguous_legacy_skill_requires_explicit_migration"
    return _dedupe(resolved), blocked


def _family_allowed(row: Mapping[str, Any], family: str) -> bool:
    scope = row.get("family_scope")
    if not isinstance(scope, list) or not scope:
        return False
    normalized = {str(value).upper() for value in scope}
    return "ALL" in normalized or family in normalized


def _dedupe(values: Iterable[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value and value not in seen:
            output.append(value)
            seen.add(value)
    return output


def resolve_skills(
    requested_ids: Sequence[str],
    context: Mapping[str, Any],
    *,
    registry: Mapping[str, Any] | None = None,
    permit_candidate_shadow: bool = False,
) -> dict[str, Any]:
    source = dict(registry) if registry is not None else load_registry()
    validate_registry(source)
    ctx = SkillContext.from_mapping(context)
    skills = _index(source)
    requested, blocked = migrate_requested_ids(requested_ids, source)

    observer_ids: list[str] = []
    candidate_shadow_ids: list[str] = []
    relation_blocked: dict[str, str] = {}

    for skill_id in requested:
        row = skills.get(skill_id)
        if row is None:
            blocked[skill_id] = "missing_in_registry"
            continue
        if not _family_allowed(row, ctx.bot_family):
            blocked[skill_id] = "family_scope_mismatch"
            continue
        state = str(row["state"])
        if state in {"quarantined", "archived"}:
            blocked[skill_id] = f"state_{state}"
            continue
        if state in {"declared", "observer_only", "counterfactual_ready"}:
            observer_ids.append(skill_id)
            continue
        if state == "candidate_shadow" and permit_candidate_shadow:
            candidate_shadow_ids.append(skill_id)
            continue
        blocked[skill_id] = f"state_not_permitted:{state}"

    accepted = set(observer_ids) | set(candidate_shadow_ids)
    for skill_id in sorted(accepted):
        row = skills[skill_id]
        missing_dependencies = sorted(set(row.get("dependencies", [])) - accepted)
        if missing_dependencies:
            relation_blocked[skill_id] = (
                "missing_dependencies:" + ",".join(missing_dependencies)
            )
        active_conflicts = sorted(set(row.get("conflicts", [])) & accepted)
        if active_conflicts:
            relation_blocked[skill_id] = "active_conflicts:" + ",".join(active_conflicts)

    if relation_blocked:
        for skill_id, reason in relation_blocked.items():
            blocked[skill_id] = reason
        observer_ids = [skill_id for skill_id in observer_ids if skill_id not in relation_blocked]
        candidate_shadow_ids = [
            skill_id for skill_id in candidate_shadow_ids if skill_id not in relation_blocked
        ]

    state = "PASS" if not blocked else "HOLD"
    return {
        "schema": "zos_skill_resolution_v2_candidate",
        "state": state,
        "action": "hold",
        "registry_version": source.get("version"),
        "context": {
            "strategy_id": ctx.strategy_id,
            "method_id": ctx.method_id,
            "bot_family": ctx.bot_family,
            "regime": ctx.regime,
            "deploy_stage": ctx.deploy_stage,
            "market": ctx.market,
            "position_id": ctx.position_id,
        },
        "requested_skill_ids": list(requested_ids),
        "normalized_skill_ids": requested,
        "observer_skill_ids": _dedupe(observer_ids),
        "candidate_shadow_skill_ids": _dedupe(candidate_shadow_ids),
        "blocked_skill_ids": sorted(blocked),
        "blocked_reason": {key: blocked[key] for key in sorted(blocked)},
        "runtime_mutation_allowed": False,
        "paper_enabled": False,
        "live_enabled": False,
        "order_enabled": False,
        "order_authority": "blocked",
        "execution_authority": "none",
    }


__all__ = [
    "REGISTRY_PATH",
    "SkillContext",
    "SkillResolutionError",
    "load_registry",
    "validate_registry",
    "migrate_requested_ids",
    "resolve_skills",
]
