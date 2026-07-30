from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Mapping

SCHEMA_VERSION = "strategy11.source_binding_contract.v1"
SAFETY = {
    "research_only": True,
    "promotion_authority": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "order_authority": "BLOCKED",
    "runtime_bound": False,
}

REQUIRED_GROUPS = {
    "proposal_core": {"W1_REPLAY", "DETERMINISTIC_PROPOSAL_ADAPTER"},
    "classifier_evidence": {"OOS_EVIDENCE_MANIFEST", "DETERMINISTIC_EVIDENCE_ADAPTER"},
    "correlation_ledger": {"TIMESTAMPED_TRADE_LEDGER"},
    "portfolio_policy": {"PORTFOLIO_POLICY_SSOT", "FIXTURE_POLICY"},
    "source_ledger": {"SOURCE_LEDGER"},
    "source_history": {"SOURCE_LEDGER_HISTORY"},
    "role_lineage": {"ROLE_LINEAGE_SSOT"},
    "role_messages": {"ROLE_MESSAGE_BUNDLE"},
    "model_risk_baseline": {"SHADOW_MODEL_RISK_BASELINE"},
    "model_risk_policy": {"MODEL_RISK_POLICY_SSOT", "FIXTURE_POLICY"},
}

SOURCE_KEYS = {
    "source_kind",
    "artifact",
    "run_id",
    "artifact_sha",
    "document",
    "transform",
    "inference_used",
    "private_fields_present",
    "stale",
}
BINDING_KEYS = {"source_id", "field_path"}
ALLOWED_TRANSFORMS = {"DIRECT_ARTIFACT", "DETERMINISTIC_ADAPTER", "FIXTURE_ONLY"}
PRIVATE_TOKENS = {
    "api_key", "apikey", "secret", "credential", "password", "private_key",
    "account_id", "order_id", "position_id", "exchange_key", "wallet",
}


class SourceBindingError(ValueError):
    pass


def _fail(code: str, detail: str = "") -> None:
    raise SourceBindingError(f"{code}:{detail}" if detail else code)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def canonical_sha(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _string(value: Any, name: str, *, max_len: int = 300) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail("STRING_REQUIRED", name)
    result = value.strip()
    if len(result) > max_len:
        _fail("STRING_TOO_LONG", name)
    return result


def _sha(value: Any, name: str) -> str:
    result = _string(value, name, max_len=64).lower()
    if len(result) != 64 or any(char not in "0123456789abcdef" for char in result):
        _fail("SHA256_REQUIRED", name)
    return result


def _bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        _fail("BOOL_REQUIRED", name)
    return value


def _reject_private_fields(value: Any, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            lowered = str(key).lower()
            if any(token in lowered for token in PRIVATE_TOKENS):
                _fail("PRIVATE_FIELD_FORBIDDEN", f"{path}.{key}")
            _reject_private_fields(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_private_fields(child, f"{path}[{index}]")


def _resolve_path(document: Any, field_path: str) -> Any:
    if field_path in {"$", ""}:
        return copy.deepcopy(document)
    current = document
    for token in field_path.split("."):
        if isinstance(current, Mapping):
            if token not in current:
                _fail("SOURCE_FIELD_PATH_MISSING", field_path)
            current = current[token]
        elif isinstance(current, list) and token.isdigit():
            index = int(token)
            if index >= len(current):
                _fail("SOURCE_FIELD_INDEX_MISSING", field_path)
            current = current[index]
        else:
            _fail("SOURCE_FIELD_PATH_INVALID", field_path)
    return copy.deepcopy(current)


def _leaf_rows(value: Any, target_path: str, source_path: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if isinstance(value, Mapping):
        if not value:
            rows.append({"target_path": target_path, "source_field_path": source_path, "value_sha": canonical_sha(value)})
        for key in sorted(value):
            child_target = f"{target_path}.{key}"
            child_source = f"{source_path}.{key}" if source_path not in {"", "$"} else str(key)
            rows.extend(_leaf_rows(value[key], child_target, child_source))
    elif isinstance(value, list):
        if not value:
            rows.append({"target_path": target_path, "source_field_path": source_path, "value_sha": canonical_sha(value)})
        for index, child in enumerate(value):
            child_target = f"{target_path}[{index}]"
            child_source = f"{source_path}.{index}" if source_path not in {"", "$"} else str(index)
            rows.extend(_leaf_rows(child, child_target, child_source))
    else:
        rows.append({"target_path": target_path, "source_field_path": source_path, "value_sha": canonical_sha(value)})
    return rows


def validate_authority(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail("AUTHORITY_OBJECT_REQUIRED")
    authority = dict(value)
    for key, expected in SAFETY.items():
        if authority.get(key) != expected:
            _fail("AUTHORITY_MISMATCH", key)
    if authority.get("runtime_bound") is not False:
        _fail("RUNTIME_BINDING_FORBIDDEN")
    return {**SAFETY, "runtime_bound": False}


def validate_source(source_id: str, value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail("SOURCE_OBJECT_REQUIRED", source_id)
    source = dict(value)
    missing = sorted(SOURCE_KEYS - set(source))
    extra = sorted(set(source) - SOURCE_KEYS)
    if missing:
        _fail("SOURCE_FIELDS_MISSING", f"{source_id}:{','.join(missing)}")
    if extra:
        _fail("SOURCE_EXTRA_FIELDS", f"{source_id}:{','.join(extra)}")
    document = copy.deepcopy(source["document"])
    _reject_private_fields(document, f"$.sources.{source_id}.document")
    artifact_sha = _sha(source["artifact_sha"], f"sources.{source_id}.artifact_sha")
    computed = canonical_sha(document)
    if artifact_sha != computed:
        _fail("SOURCE_ARTIFACT_SHA_MISMATCH", source_id)
    transform = _string(source["transform"], f"sources.{source_id}.transform").upper()
    if transform not in ALLOWED_TRANSFORMS:
        _fail("SOURCE_TRANSFORM_INVALID", f"{source_id}:{transform}")
    if _bool(source["inference_used"], f"sources.{source_id}.inference_used"):
        _fail("INFERENCE_FORBIDDEN", source_id)
    if _bool(source["private_fields_present"], f"sources.{source_id}.private_fields_present"):
        _fail("PRIVATE_FIELDS_PRESENT", source_id)
    if _bool(source["stale"], f"sources.{source_id}.stale"):
        _fail("STALE_SOURCE_FORBIDDEN", source_id)
    return {
        "source_id": source_id,
        "source_kind": _string(source["source_kind"], f"sources.{source_id}.source_kind").upper(),
        "artifact": _string(source["artifact"], f"sources.{source_id}.artifact"),
        "run_id": _string(source["run_id"], f"sources.{source_id}.run_id", max_len=80),
        "artifact_sha": artifact_sha,
        "document": document,
        "transform": transform,
        "inference_used": False,
        "private_fields_present": False,
        "stale": False,
    }


def validate_source_history(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail("SOURCE_HISTORY_OBJECT_REQUIRED")
    history = dict(value)
    required = {"previous_head_sha", "rows_sha", "sequence", "current_head_sha", "append_only_verified"}
    missing = sorted(required - set(history))
    if missing:
        _fail("SOURCE_HISTORY_FIELDS_MISSING", ",".join(missing))
    previous = _sha(history["previous_head_sha"], "source_history.previous_head_sha")
    rows_sha = _sha(history["rows_sha"], "source_history.rows_sha")
    sequence = history["sequence"]
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
        _fail("SOURCE_HISTORY_SEQUENCE_INVALID")
    current = _sha(history["current_head_sha"], "source_history.current_head_sha")
    computed = canonical_sha({"previous_head_sha": previous, "rows_sha": rows_sha, "sequence": sequence})
    if current != computed:
        _fail("SOURCE_HISTORY_HEAD_MISMATCH")
    if history["append_only_verified"] is not True:
        _fail("APPEND_ONLY_VERIFICATION_REQUIRED")
    return {
        "previous_head_sha": previous,
        "rows_sha": rows_sha,
        "sequence": sequence,
        "current_head_sha": current,
        "append_only_verified": True,
        "history_contract_sha": canonical_sha({
            "previous_head_sha": previous,
            "rows_sha": rows_sha,
            "sequence": sequence,
            "current_head_sha": current,
        }),
    }


def bind_package(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail("PACKAGE_OBJECT_REQUIRED")
    package = dict(value)
    allowed = {"schema_version", "package_id", "sources", "group_bindings", "authority"}
    extra = sorted(set(package) - allowed)
    missing = sorted(allowed - set(package))
    if missing:
        _fail("PACKAGE_FIELDS_MISSING", ",".join(missing))
    if extra:
        _fail("PACKAGE_EXTRA_FIELDS", ",".join(extra))
    if package.get("schema_version") != SCHEMA_VERSION:
        _fail("SCHEMA_VERSION_MISMATCH")
    package_id = _string(package.get("package_id"), "package_id")
    authority = validate_authority(package.get("authority"))

    raw_sources = package.get("sources")
    if not isinstance(raw_sources, Mapping) or not raw_sources:
        _fail("SOURCES_REQUIRED")
    sources = {str(source_id): validate_source(str(source_id), source) for source_id, source in raw_sources.items()}

    raw_bindings = package.get("group_bindings")
    if not isinstance(raw_bindings, Mapping):
        _fail("GROUP_BINDINGS_REQUIRED")
    missing_groups = sorted(set(REQUIRED_GROUPS) - set(raw_bindings))
    extra_groups = sorted(set(raw_bindings) - set(REQUIRED_GROUPS))
    if missing_groups:
        _fail("REQUIRED_BINDING_GROUP_MISSING", ",".join(missing_groups))
    if extra_groups:
        _fail("UNKNOWN_BINDING_GROUP", ",".join(extra_groups))

    groups: dict[str, Any] = {}
    manifest_rows: list[dict[str, Any]] = []
    group_rows: list[dict[str, Any]] = []
    for group_name in sorted(REQUIRED_GROUPS):
        binding_value = raw_bindings[group_name]
        if not isinstance(binding_value, Mapping):
            _fail("BINDING_OBJECT_REQUIRED", group_name)
        binding = dict(binding_value)
        missing_binding = sorted(BINDING_KEYS - set(binding))
        extra_binding = sorted(set(binding) - BINDING_KEYS)
        if missing_binding:
            _fail("BINDING_FIELDS_MISSING", f"{group_name}:{','.join(missing_binding)}")
        if extra_binding:
            _fail("BINDING_EXTRA_FIELDS", f"{group_name}:{','.join(extra_binding)}")
        source_id = _string(binding["source_id"], f"group_bindings.{group_name}.source_id")
        if source_id not in sources:
            _fail("BINDING_SOURCE_UNKNOWN", f"{group_name}:{source_id}")
        source = sources[source_id]
        if source["source_kind"] not in REQUIRED_GROUPS[group_name]:
            _fail("SOURCE_KIND_NOT_ALLOWED_FOR_GROUP", f"{group_name}:{source['source_kind']}")
        field_path = _string(binding["field_path"], f"group_bindings.{group_name}.field_path")
        resolved = _resolve_path(source["document"], field_path)
        _reject_private_fields(resolved, f"$.groups.{group_name}")
        groups[group_name] = resolved
        leaves = _leaf_rows(resolved, group_name, field_path)
        for leaf in leaves:
            manifest_rows.append({
                **leaf,
                "source_id": source_id,
                "source_kind": source["source_kind"],
                "source_artifact": source["artifact"],
                "source_run_id": source["run_id"],
                "source_artifact_sha": source["artifact_sha"],
                "transform": source["transform"],
                "inference_used": False,
            })
        group_rows.append({
            "group": group_name,
            "source_id": source_id,
            "source_kind": source["source_kind"],
            "source_artifact": source["artifact"],
            "source_run_id": source["run_id"],
            "source_artifact_sha": source["artifact_sha"],
            "field_path": field_path,
            "resolved_group_sha": canonical_sha(resolved),
            "leaf_binding_count": len(leaves),
        })

    history = validate_source_history(groups["source_history"])
    source_inventory = [
        {
            "source_id": source["source_id"],
            "source_kind": source["source_kind"],
            "artifact": source["artifact"],
            "run_id": source["run_id"],
            "artifact_sha": source["artifact_sha"],
            "transform": source["transform"],
        }
        for source in sorted(sources.values(), key=lambda item: item["source_id"])
    ]
    result = {
        "schema_version": "strategy11.source_bound_package.v1",
        "status": "PASS_STRICT_SOURCE_BINDING",
        "package_id": package_id,
        "groups": groups,
        "source_inventory": source_inventory,
        "group_bindings": group_rows,
        "field_bindings": sorted(manifest_rows, key=lambda row: row["target_path"]),
        "bound_group_count": len(group_rows),
        "bound_field_count": len(manifest_rows),
        "source_history": history,
        "inference_used": False,
        "all_values_source_bound": True,
        "runtime_bound": False,
        **SAFETY,
    }
    result["binding_manifest_sha"] = canonical_sha({
        "package_id": package_id,
        "sources": source_inventory,
        "groups": group_rows,
        "fields": result["field_bindings"],
        "source_history": history,
    })
    result["package_sha"] = canonical_sha({
        "groups": groups,
        "binding_manifest_sha": result["binding_manifest_sha"],
        "authority": authority,
    })
    return result


def attribution_history_envelope(projection: Mapping[str, Any], history: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(projection, Mapping) or projection.get("status") != "PASS_STRATEGY_ATTRIBUTION_LEDGER":
        _fail("ATTRIBUTION_PROJECTION_NOT_PASS")
    verified = validate_source_history(history)
    rows = projection.get("rows")
    if not isinstance(rows, list) or not rows:
        _fail("ATTRIBUTION_ROWS_REQUIRED")
    rows_sha = canonical_sha([
        (row.get("source_ledger_id"), row.get("source_row_id"), row.get("source_row_sha"))
        for row in rows
    ])
    if rows_sha != verified["rows_sha"]:
        _fail("ATTRIBUTION_HISTORY_ROWS_SHA_MISMATCH")
    result = {
        "schema_version": "strategy11.attribution_history_envelope.v1",
        "status": "PASS_ATTRIBUTION_SOURCE_HISTORY",
        "projection_sha": _sha(projection.get("projection_sha"), "projection.projection_sha"),
        "previous_source_ledger_head_sha": verified["previous_head_sha"],
        "current_source_ledger_head_sha": verified["current_head_sha"],
        "source_rows_sha": verified["rows_sha"],
        "source_sequence": verified["sequence"],
        "append_only_evidence": True,
        "source_history_verified": True,
        "runtime_bound": False,
        **SAFETY,
    }
    result["history_envelope_sha"] = canonical_sha(result)
    return result
