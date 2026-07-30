from __future__ import annotations

import copy
import hashlib
import json
import math
from typing import Any, Iterable, Mapping
from backend.contracts.strategy11_validation_primitives_v1 import ValidationPrimitives

SCHEMA_VERSION = "strategy11.synthesis_material.v1"
REGISTRY_SCHEMA = "strategy11.synthesis_material_registry.v1"
COMPONENT_ROLE = {
    "BASE_ENGINE": "SIGNAL",
    "CONTEXT_GATE": "FILTER",
    "ENTRY_CONFIRM": "CONFIRM",
    "EXIT_SKILL": "EXIT",
    "POSITION_MANAGEMENT": "MANAGEMENT",
    "RISK_CONSTRAINT": "CONSTRAINT",
    "ADVISOR": "ADVISORY",
}
MATERIAL_STATES = {"PASS_LEAF", "HOLD", "REJECT"}
PRIVATE_TOKENS = {
    "api_key", "apikey", "secret", "credential", "password", "private_key",
    "account_id", "order_id", "position_id", "exchange_key", "wallet",
}
SAFETY = {
    "research_only": True,
    "promotion_authority": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "order_authority": "BLOCKED",
    "runtime_bound": False,
}
TOP_LEVEL = {
    "schema_version", "material_id", "material_sha", "base_strategy_id",
    "component_type", "component_role", "semantic_axis", "parameters",
    "source_lineage", "evidence", "compatibility", "state", "authority", "metadata",
}
LINEAGE_SHA_FIELDS = {
    "source_candidate_sha", "source_proposal_sha", "strategy_source_sha",
    "data_sha", "window_sha", "source_manifest_sha", "evidence_sha",
}


class SynthesisMaterialError(ValueError):
    pass


def _fail(code: str, detail: str = "") -> None:
    raise SynthesisMaterialError(f"{code}:{detail}" if detail else code)

_validation = ValidationPrimitives(_fail)
_mapping = _validation.mapping
_string = _validation.string
_sha = _validation.sha256
_bool = _validation.boolean
_integer = _validation.integer
_number = _validation.number



def canonical_sha(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()








def _reject_private(value: Any, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key).lower()
            if any(token in key_text for token in PRIVATE_TOKENS):
                _fail("PRIVATE_FIELD_FORBIDDEN", f"{path}.{key}")
            _reject_private(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_private(child, f"{path}[{index}]")


def _json_parameter(value: Any, path: str = "parameters", depth: int = 0) -> Any:
    if depth > 4:
        _fail("PARAMETER_DEPTH_EXCEEDED", path)
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(float(value)):
            _fail("PARAMETER_NOT_FINITE", path)
        return value
    if isinstance(value, list):
        if len(value) > 20:
            _fail("PARAMETER_LIST_TOO_LONG", path)
        return [_json_parameter(child, f"{path}[{index}]", depth + 1) for index, child in enumerate(value)]
    if isinstance(value, Mapping):
        if len(value) > 30:
            _fail("PARAMETER_OBJECT_TOO_LARGE", path)
        result: dict[str, Any] = {}
        for key, child in sorted(value.items(), key=lambda item: str(item[0])):
            normalized_key = _string(str(key), f"{path}.key", maximum=80)
            result[normalized_key] = _json_parameter(child, f"{path}.{normalized_key}", depth + 1)
        return result
    _fail("PARAMETER_TYPE_INVALID", path)


def _string_list(value: Any, name: str, *, maximum: int = 30, upper: bool = False) -> list[str]:
    if not isinstance(value, list) or len(value) > maximum:
        _fail("LIST_INVALID", name)
    rows = [_string(item, f"{name}[]", maximum=100) for item in value]
    if upper:
        rows = [item.upper() for item in rows]
    if len(rows) != len(set(rows)):
        _fail("LIST_DUPLICATE", name)
    return sorted(rows)


def _authority(value: Any) -> dict[str, Any]:
    authority = _mapping(value, "authority")
    result = {
        "research_only": _bool(authority.get("research_only"), "authority.research_only"),
        "promotion_authority": _bool(authority.get("promotion_authority"), "authority.promotion_authority"),
        "protected_mutations": _integer(authority.get("protected_mutations"), "authority.protected_mutations"),
        "execution_allowed": _bool(authority.get("execution_allowed"), "authority.execution_allowed"),
        "order_authority": _string(authority.get("order_authority"), "authority.order_authority").upper(),
        "runtime_bound": _bool(authority.get("runtime_bound"), "authority.runtime_bound"),
    }
    if result != SAFETY:
        _fail("AUTHORITY_MISMATCH")
    return result


def _evidence(value: Any, state: str) -> dict[str, Any]:
    evidence = _mapping(value, "evidence")
    required = {
        "ab_replay_pass", "duplicate_count", "baseline_trades", "candidate_trades",
        "retention_pct", "normal_loss_cap_pass", "stress_loss_cap_pass",
        "economic_gate_pass", "window_gate_pass", "pareto_non_dominated",
        "net_after_cost_delta", "max_drawdown_delta", "worst_loss_r_delta",
        "positive_windows_delta", "stress_worst_loss_r_delta",
    }
    missing = sorted(required - set(evidence))
    extra = sorted(set(evidence) - required)
    if missing:
        _fail("EVIDENCE_FIELDS_MISSING", ",".join(missing))
    if extra:
        _fail("EVIDENCE_EXTRA_FIELDS", ",".join(extra))
    result = {
        "ab_replay_pass": _bool(evidence["ab_replay_pass"], "evidence.ab_replay_pass"),
        "duplicate_count": _integer(evidence["duplicate_count"], "evidence.duplicate_count"),
        "baseline_trades": _integer(evidence["baseline_trades"], "evidence.baseline_trades", minimum=1),
        "candidate_trades": _integer(evidence["candidate_trades"], "evidence.candidate_trades"),
        "retention_pct": _number(evidence["retention_pct"], "evidence.retention_pct", minimum=0.0, maximum=100.0),
        "normal_loss_cap_pass": _bool(evidence["normal_loss_cap_pass"], "evidence.normal_loss_cap_pass"),
        "stress_loss_cap_pass": _bool(evidence["stress_loss_cap_pass"], "evidence.stress_loss_cap_pass"),
        "economic_gate_pass": _bool(evidence["economic_gate_pass"], "evidence.economic_gate_pass"),
        "window_gate_pass": _bool(evidence["window_gate_pass"], "evidence.window_gate_pass"),
        "pareto_non_dominated": _bool(evidence["pareto_non_dominated"], "evidence.pareto_non_dominated"),
        "net_after_cost_delta": _number(evidence["net_after_cost_delta"], "evidence.net_after_cost_delta"),
        "max_drawdown_delta": _number(evidence["max_drawdown_delta"], "evidence.max_drawdown_delta"),
        "worst_loss_r_delta": _number(evidence["worst_loss_r_delta"], "evidence.worst_loss_r_delta"),
        "positive_windows_delta": _integer(evidence["positive_windows_delta"], "evidence.positive_windows_delta"),
        "stress_worst_loss_r_delta": _number(evidence["stress_worst_loss_r_delta"], "evidence.stress_worst_loss_r_delta"),
    }
    expected_retention = result["candidate_trades"] / result["baseline_trades"] * 100.0
    if abs(result["retention_pct"] - expected_retention) > 1e-6:
        _fail("RETENTION_RECONCILIATION_MISMATCH")
    pass_leaf = (
        result["ab_replay_pass"]
        and result["duplicate_count"] == 0
        and result["candidate_trades"] > 0
        and result["normal_loss_cap_pass"]
        and result["stress_loss_cap_pass"]
        and result["economic_gate_pass"]
        and result["window_gate_pass"]
        and result["pareto_non_dominated"]
    )
    if state == "PASS_LEAF" and not pass_leaf:
        _fail("PASS_LEAF_EVIDENCE_NOT_PASS")
    return result


def _lineage(value: Any) -> dict[str, Any]:
    lineage = _mapping(value, "source_lineage")
    missing = sorted(LINEAGE_SHA_FIELDS - set(lineage))
    extra = sorted(set(lineage) - LINEAGE_SHA_FIELDS)
    if missing:
        _fail("LINEAGE_FIELDS_MISSING", ",".join(missing))
    if extra:
        _fail("LINEAGE_EXTRA_FIELDS", ",".join(extra))
    return {key: _sha(lineage[key], f"source_lineage.{key}") for key in sorted(LINEAGE_SHA_FIELDS)}


def _compatibility(value: Any) -> dict[str, Any]:
    compatibility = _mapping(value, "compatibility")
    required = {
        "allowed_base_families", "incompatible_component_types", "incompatible_axes",
        "same_axis_allowed", "maximum_generation_per_axis_data",
    }
    missing = sorted(required - set(compatibility))
    extra = sorted(set(compatibility) - required)
    if missing:
        _fail("COMPATIBILITY_FIELDS_MISSING", ",".join(missing))
    if extra:
        _fail("COMPATIBILITY_EXTRA_FIELDS", ",".join(extra))
    incompatible_types = _string_list(
        compatibility["incompatible_component_types"],
        "compatibility.incompatible_component_types",
        upper=True,
    )
    unknown = sorted(set(incompatible_types) - set(COMPONENT_ROLE))
    if unknown:
        _fail("INCOMPATIBLE_COMPONENT_TYPE_UNKNOWN", ",".join(unknown))
    return {
        "allowed_base_families": _string_list(
            compatibility["allowed_base_families"],
            "compatibility.allowed_base_families",
            upper=True,
        ),
        "incompatible_component_types": incompatible_types,
        "incompatible_axes": _string_list(
            compatibility["incompatible_axes"],
            "compatibility.incompatible_axes",
            upper=True,
        ),
        "same_axis_allowed": _bool(compatibility["same_axis_allowed"], "compatibility.same_axis_allowed"),
        "maximum_generation_per_axis_data": _integer(
            compatibility["maximum_generation_per_axis_data"],
            "compatibility.maximum_generation_per_axis_data",
            minimum=1,
        ),
    }


def material_fingerprint(value: Mapping[str, Any]) -> str:
    return canonical_sha(
        {
            "base_strategy_id": value["base_strategy_id"],
            "component_type": value["component_type"],
            "semantic_axis": value["semantic_axis"],
            "parameters": value["parameters"],
            "data_sha": value["source_lineage"]["data_sha"],
            "window_sha": value["source_lineage"]["window_sha"],
        }
    )


def validate_material(value: Mapping[str, Any], *, require_material_sha: bool = True) -> dict[str, Any]:
    raw = _mapping(value, "material")
    _reject_private(raw)
    missing = sorted((TOP_LEVEL - {"material_sha", "metadata"}) - set(raw))
    extra = sorted(set(raw) - TOP_LEVEL)
    if missing:
        _fail("TOP_LEVEL_FIELDS_MISSING", ",".join(missing))
    if extra:
        _fail("TOP_LEVEL_EXTRA_FIELDS", ",".join(extra))
    if raw.get("schema_version") != SCHEMA_VERSION:
        _fail("SCHEMA_VERSION_MISMATCH")

    component_type = _string(raw.get("component_type"), "component_type").upper()
    if component_type not in COMPONENT_ROLE:
        _fail("COMPONENT_TYPE_INVALID", component_type)
    component_role = _string(raw.get("component_role"), "component_role").upper()
    if component_role != COMPONENT_ROLE[component_type]:
        _fail("COMPONENT_ROLE_MISMATCH", f"{component_type}:{component_role}")
    state = _string(raw.get("state"), "state").upper()
    if state not in MATERIAL_STATES:
        _fail("MATERIAL_STATE_INVALID", state)

    normalized_evidence = _evidence(raw.get("evidence"), state)
    normalized_lineage = _lineage(raw.get("source_lineage"))
    if normalized_lineage["evidence_sha"] != canonical_sha(normalized_evidence):
        _fail("EVIDENCE_SHA_MISMATCH")

    normalized: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "material_id": _string(raw.get("material_id"), "material_id"),
        "base_strategy_id": _string(raw.get("base_strategy_id"), "base_strategy_id"),
        "component_type": component_type,
        "component_role": component_role,
        "semantic_axis": _string(raw.get("semantic_axis"), "semantic_axis").upper(),
        "parameters": _json_parameter(raw.get("parameters")),
        "source_lineage": normalized_lineage,
        "evidence": normalized_evidence,
        "compatibility": _compatibility(raw.get("compatibility")),
        "state": state,
        "authority": _authority(raw.get("authority")),
        "metadata": copy.deepcopy(dict(raw.get("metadata", {}))),
    }
    _reject_private(normalized["metadata"], "$.metadata")
    normalized["metadata"]["material_fingerprint"] = material_fingerprint(normalized)
    computed_sha = canonical_sha(normalized)
    if require_material_sha:
        supplied = _sha(raw.get("material_sha"), "material_sha")
        if supplied != computed_sha:
            _fail("MATERIAL_SHA_MISMATCH")
    normalized["material_sha"] = computed_sha
    return normalized


def seal_material(value: Mapping[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(dict(value))
    payload.pop("material_sha", None)
    first = validate_material(payload, require_material_sha=False)
    return validate_material(first, require_material_sha=True)


def build_registry(material_values: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    materials = [validate_material(value) for value in material_values]
    if not materials:
        _fail("MATERIALS_REQUIRED")
    ids = [row["material_id"] for row in materials]
    if len(ids) != len(set(ids)):
        _fail("DUPLICATE_MATERIAL_ID")
    shas = [row["material_sha"] for row in materials]
    if len(shas) != len(set(shas)):
        _fail("DUPLICATE_MATERIAL_SHA")
    fingerprints = [row["metadata"]["material_fingerprint"] for row in materials]
    if len(fingerprints) != len(set(fingerprints)):
        _fail("DUPLICATE_MATERIAL_FINGERPRINT")

    pass_rows = [row for row in materials if row["state"] == "PASS_LEAF"]
    result = {
        "schema_version": REGISTRY_SCHEMA,
        "material_count": len(materials),
        "pass_leaf_count": len(pass_rows),
        "hold_count": sum(row["state"] == "HOLD" for row in materials),
        "reject_count": sum(row["state"] == "REJECT" for row in materials),
        "materials": sorted(materials, key=lambda row: row["material_id"]),
        "eligible_material_ids": sorted(row["material_id"] for row in pass_rows),
        "next": "BOUNDED_SYNTHESIS_CONSTRUCTOR" if pass_rows else "WAIT_NEW_CAUSAL_EVIDENCE",
        **SAFETY,
    }
    result["registry_sha"] = canonical_sha(result)
    return result
