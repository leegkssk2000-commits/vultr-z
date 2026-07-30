from __future__ import annotations

import copy
import itertools
import json
import math
from typing import Any, Iterable, Mapping, Sequence

from backend.research.strategy11_synthesis_material_registry_v1 import (
    SAFETY,
    build_registry,
    canonical_sha,
    validate_material,
)

INPUT_SCHEMA = "strategy11.bounded_synthesis_constructor.input.v1"
OUTPUT_SCHEMA = "strategy11.bounded_synthesis_constructor.output.v1"
CANDIDATE_SCHEMA = "strategy11.bounded_synthesis_candidate.v1"
ALPHA_COMPONENT_TYPES = {"CONTEXT_GATE", "ENTRY_CONFIRM", "EXIT_SKILL", "POSITION_MANAGEMENT"}
FORBIDDEN_ALPHA_TYPES = {"RISK_CONSTRAINT", "ADVISOR"}
TEMPLATE_BY_TYPES = {
    ("CONTEXT_GATE",): "BASE_PLUS_CONTEXT",
    ("ENTRY_CONFIRM",): "BASE_PLUS_CONFIRM",
    ("EXIT_SKILL",): "BASE_PLUS_EXIT",
    ("CONTEXT_GATE", "EXIT_SKILL"): "BASE_PLUS_CONTEXT_EXIT",
    ("ENTRY_CONFIRM", "EXIT_SKILL"): "BASE_PLUS_CONFIRM_EXIT",
}


class BoundedSynthesisError(ValueError):
    pass


def _fail(code: str, detail: str = "") -> None:
    raise BoundedSynthesisError(f"{code}:{detail}" if detail else code)


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail("OBJECT_REQUIRED", name)
    return dict(value)


def _string(value: Any, name: str, *, maximum: int = 180) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail("STRING_REQUIRED", name)
    result = value.strip()
    if len(result) > maximum:
        _fail("STRING_TOO_LONG", name)
    return result


def _integer(value: Any, name: str, *, minimum: int = 0, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        _fail("INT_REQUIRED", name)
    if value < minimum:
        _fail("INT_BELOW_MIN", name)
    if maximum is not None and value > maximum:
        _fail("INT_ABOVE_MAX", name)
    return value


def _bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        _fail("BOOL_REQUIRED", name)
    return value


def _sha(value: Any, name: str) -> str:
    result = _string(value, name, maximum=64).lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        _fail("SHA256_REQUIRED", name)
    return result


def _string_list(value: Any, name: str, *, allowed: set[str] | None = None) -> list[str]:
    if not isinstance(value, list) or not value:
        _fail("NONEMPTY_LIST_REQUIRED", name)
    rows = sorted({_string(item, f"{name}[]").upper() for item in value})
    if len(rows) != len(value):
        _fail("LIST_DUPLICATE", name)
    if allowed is not None:
        unknown = sorted(set(rows) - allowed)
        if unknown:
            _fail("LIST_VALUE_INVALID", f"{name}:{','.join(unknown)}")
    return rows


def validate_policy(value: Mapping[str, Any]) -> dict[str, Any]:
    policy = _mapping(value, "policy")
    required = {
        "policy_id", "allowed_templates", "max_non_base_components", "max_candidates",
        "allow_position_management_pre_shadow", "require_shared_selection_lineage",
        "generic_base_strategy_id",
    }
    missing = sorted(required - set(policy))
    extra = sorted(set(policy) - required)
    if missing:
        _fail("POLICY_FIELDS_MISSING", ",".join(missing))
    if extra:
        _fail("POLICY_EXTRA_FIELDS", ",".join(extra))
    allowed_templates = _string_list(
        policy["allowed_templates"],
        "policy.allowed_templates",
        allowed=set(TEMPLATE_BY_TYPES.values()),
    )
    return {
        "policy_id": _string(policy["policy_id"], "policy.policy_id"),
        "allowed_templates": allowed_templates,
        "max_non_base_components": _integer(
            policy["max_non_base_components"],
            "policy.max_non_base_components",
            minimum=1,
            maximum=2,
        ),
        "max_candidates": _integer(policy["max_candidates"], "policy.max_candidates", minimum=1, maximum=100),
        "allow_position_management_pre_shadow": _bool(
            policy["allow_position_management_pre_shadow"],
            "policy.allow_position_management_pre_shadow",
        ),
        "require_shared_selection_lineage": _bool(
            policy["require_shared_selection_lineage"],
            "policy.require_shared_selection_lineage",
        ),
        "generic_base_strategy_id": _string(
            policy["generic_base_strategy_id"],
            "policy.generic_base_strategy_id",
        ),
    }


def validate_registry(value: Mapping[str, Any]) -> dict[str, Any]:
    registry = _mapping(value, "registry")
    supplied_sha = _sha(registry.get("registry_sha"), "registry.registry_sha")
    materials = registry.get("materials")
    if not isinstance(materials, list) or not materials:
        _fail("REGISTRY_MATERIALS_REQUIRED")
    rebuilt = build_registry(materials)
    if rebuilt["registry_sha"] != supplied_sha:
        _fail("REGISTRY_SHA_MISMATCH")
    for key, expected in SAFETY.items():
        if registry.get(key) != expected:
            _fail("REGISTRY_AUTHORITY_MISMATCH", key)
    for key in (
        "schema_version", "material_count", "pass_leaf_count", "hold_count", "reject_count",
        "eligible_material_ids", "next",
    ):
        if registry.get(key) != rebuilt.get(key):
            _fail("REGISTRY_RECONCILIATION_MISMATCH", key)
    return rebuilt


def _family(material: Mapping[str, Any]) -> str:
    metadata = material.get("metadata")
    if not isinstance(metadata, Mapping):
        _fail("MATERIAL_METADATA_REQUIRED", material.get("material_id", "unknown"))
    value = metadata.get("strategy_family")
    return _string(value, f"{material.get('material_id')}.metadata.strategy_family").upper()


def _shared_lineage(materials: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    fields = ("data_sha", "window_sha", "source_manifest_sha")
    result: dict[str, str] = {}
    for field in fields:
        values = {material["source_lineage"][field] for material in materials}
        if len(values) != 1:
            _fail("SELECTION_LINEAGE_MISMATCH", field)
        result[field] = next(iter(values))
    result["selection_lineage_sha"] = canonical_sha(result)
    return result


def _pair_compatible(left: Mapping[str, Any], right: Mapping[str, Any]) -> None:
    left_id = left["material_id"]
    right_id = right["material_id"]
    if right["component_type"] in left["compatibility"]["incompatible_component_types"]:
        _fail("COMPONENT_TYPE_INCOMPATIBLE", f"{left_id}:{right_id}")
    if left["component_type"] in right["compatibility"]["incompatible_component_types"]:
        _fail("COMPONENT_TYPE_INCOMPATIBLE", f"{right_id}:{left_id}")
    if right["semantic_axis"] in left["compatibility"]["incompatible_axes"]:
        _fail("SEMANTIC_AXIS_INCOMPATIBLE", f"{left_id}:{right_id}")
    if left["semantic_axis"] in right["compatibility"]["incompatible_axes"]:
        _fail("SEMANTIC_AXIS_INCOMPATIBLE", f"{right_id}:{left_id}")
    if left["semantic_axis"] == right["semantic_axis"]:
        _fail("DUPLICATE_SEMANTIC_AXIS", left["semantic_axis"])


def _component_allowed_for_base(
    base: Mapping[str, Any],
    component: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> None:
    if component["component_type"] in FORBIDDEN_ALPHA_TYPES:
        _fail("NON_ALPHA_COMPONENT_FORBIDDEN", component["component_type"])
    if component["component_type"] not in ALPHA_COMPONENT_TYPES:
        _fail("COMPONENT_TYPE_NOT_CONSTRUCTIBLE", component["component_type"])
    if component["component_type"] == "POSITION_MANAGEMENT" and not policy["allow_position_management_pre_shadow"]:
        _fail("POSITION_MANAGEMENT_PRE_SHADOW_FORBIDDEN")
    if component["base_strategy_id"] not in {base["base_strategy_id"], policy["generic_base_strategy_id"]}:
        _fail("BASE_STRATEGY_BINDING_MISMATCH", component["material_id"])
    base_family = _family(base)
    allowed_families = component["compatibility"]["allowed_base_families"]
    if allowed_families and base_family not in allowed_families:
        _fail("BASE_FAMILY_NOT_ALLOWED", f"{component['material_id']}:{base_family}")


def _template(components: Sequence[Mapping[str, Any]], policy: Mapping[str, Any]) -> str:
    types = tuple(sorted(component["component_type"] for component in components))
    template = TEMPLATE_BY_TYPES.get(types)
    if template is None:
        _fail("COMPONENT_TEMPLATE_NOT_SUPPORTED", ",".join(types))
    if template not in policy["allowed_templates"]:
        _fail("TEMPLATE_NOT_ALLOWED", template)
    return template


def construct_candidate(
    base_value: Mapping[str, Any],
    component_values: Sequence[Mapping[str, Any]],
    policy_value: Mapping[str, Any],
) -> dict[str, Any]:
    policy = validate_policy(policy_value)
    base = validate_material(base_value)
    components = [validate_material(value) for value in component_values]
    if base["state"] != "PASS_LEAF" or base["component_type"] != "BASE_ENGINE":
        _fail("PASS_BASE_ENGINE_REQUIRED")
    if not 1 <= len(components) <= policy["max_non_base_components"]:
        _fail("NON_BASE_COMPONENT_COUNT_INVALID")
    if any(component["state"] != "PASS_LEAF" for component in components):
        _fail("PASS_LEAF_COMPONENT_REQUIRED")
    if len({component["material_id"] for component in components}) != len(components):
        _fail("DUPLICATE_COMPONENT_ID")
    if len({component["material_sha"] for component in components}) != len(components):
        _fail("DUPLICATE_COMPONENT_SHA")

    for component in components:
        _component_allowed_for_base(base, component, policy)
        _pair_compatible(base, component)
    for left, right in itertools.combinations(components, 2):
        _pair_compatible(left, right)

    template = _template(components, policy)
    all_materials = [base, *components]
    lineage = _shared_lineage(all_materials) if policy["require_shared_selection_lineage"] else {
        "selection_lineage_sha": canonical_sha(
            sorted(material["source_lineage"]["evidence_sha"] for material in all_materials)
        )
    }
    component_rows = [
        {
            "material_id": component["material_id"],
            "material_sha": component["material_sha"],
            "component_type": component["component_type"],
            "semantic_axis": component["semantic_axis"],
            "parameters": copy.deepcopy(component["parameters"]),
        }
        for component in sorted(components, key=lambda row: (row["component_type"], row["material_id"]))
    ]
    candidate_core = {
        "schema_version": CANDIDATE_SCHEMA,
        "template": template,
        "base_strategy_id": base["base_strategy_id"],
        "base_family": _family(base),
        "base_material": {
            "material_id": base["material_id"],
            "material_sha": base["material_sha"],
            "parameters": copy.deepcopy(base["parameters"]),
        },
        "components": component_rows,
        "component_count": 1 + len(component_rows),
        "semantic_axes": sorted(component["semantic_axis"] for component in components),
        "selection_lineage": lineage,
        "selection_data_role": "DESIGN_SELECTION_ONLY",
        "first_oos_required": "W2",
        "confirmation_required": ["W2", "W3", "NEW_SEALED"],
        "policy_id": policy["policy_id"],
        **SAFETY,
    }
    candidate_core["candidate_id"] = (
        f"synthesis::{base['base_strategy_id']}::{template}::"
        + "+".join(row["material_id"] for row in component_rows)
    )
    candidate_core["candidate_sha"] = canonical_sha(candidate_core)
    return candidate_core


def construct_plan(value: Mapping[str, Any]) -> dict[str, Any]:
    payload = _mapping(value, "constructor_input")
    allowed = {"schema_version", "registry", "policy", "authority"}
    missing = sorted(allowed - set(payload))
    extra = sorted(set(payload) - allowed)
    if missing:
        _fail("INPUT_FIELDS_MISSING", ",".join(missing))
    if extra:
        _fail("INPUT_EXTRA_FIELDS", ",".join(extra))
    if payload.get("schema_version") != INPUT_SCHEMA:
        _fail("INPUT_SCHEMA_MISMATCH")
    if payload.get("authority") != SAFETY:
        _fail("INPUT_AUTHORITY_MISMATCH")

    registry = validate_registry(payload["registry"])
    policy = validate_policy(payload["policy"])
    eligible = [validate_material(row) for row in registry["materials"] if row["state"] == "PASS_LEAF"]
    bases = [row for row in eligible if row["component_type"] == "BASE_ENGINE"]
    non_bases = [row for row in eligible if row["component_type"] != "BASE_ENGINE"]
    candidates: list[dict[str, Any]] = []
    rejection_counts: dict[str, int] = {}

    for base in bases:
        max_size = min(policy["max_non_base_components"], len(non_bases))
        for size in range(1, max_size + 1):
            for combo in itertools.combinations(non_bases, size):
                try:
                    candidate = construct_candidate(base, list(combo), policy)
                except BoundedSynthesisError as exc:
                    code = str(exc).split(":", 1)[0]
                    rejection_counts[code] = rejection_counts.get(code, 0) + 1
                    continue
                candidates.append(candidate)

    unique: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        unique[candidate["candidate_sha"]] = candidate
    candidates = sorted(
        unique.values(),
        key=lambda row: (row["component_count"], row["template"], row["candidate_id"]),
    )[: policy["max_candidates"]]
    state = "PASS_BOUNDED_SYNTHESIS_PLAN" if candidates else "HOLD_NO_COMPATIBLE_SYNTHESIS"
    result = {
        "schema_version": OUTPUT_SCHEMA,
        "state": state,
        "registry_sha": registry["registry_sha"],
        "policy_sha": canonical_sha(policy),
        "base_count": len(bases),
        "eligible_non_base_count": len(non_bases),
        "candidate_count": len(candidates),
        "candidates": candidates,
        "rejection_counts": dict(sorted(rejection_counts.items())),
        "selection_only": True,
        "next": "SYNTHESIS_FACTORIAL_REPLAY" if candidates else "WAIT_NEW_CAUSAL_MATERIAL",
        **SAFETY,
    }
    result["plan_sha"] = canonical_sha(result)
    return result
