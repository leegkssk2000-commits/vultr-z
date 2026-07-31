from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping
from typing import Any

SCHEMA_VERSION = "zel.strategy_lifecycle.registry.v1"
STRATEGY_COUNT = 25
FAMILIES = {"TREND", "MEAN_REVERSION", "BREAKOUT", "HYBRID"}
STATES = {
    "IMMUTABLE_CONTROL", "LIVENESS_TEST", "RESEARCH_ACTIVE", "SHADOW_CANDIDATE",
    "SHADOW_ACTIVE", "PAPER_CANARY", "PAPER_ACTIVE", "LIVE_MICRO", "LIVE_ACTIVE",
    "DORMANT", "QUARANTINED", "RETIRED",
}
CAPITAL_STATES = {"PAPER_CANARY", "PAPER_ACTIVE", "LIVE_MICRO", "LIVE_ACTIVE"}
ALLOWED_TRANSITIONS = {
    "IMMUTABLE_CONTROL": {"LIVENESS_TEST", "RESEARCH_ACTIVE", "DORMANT", "QUARANTINED"},
    "LIVENESS_TEST": {"RESEARCH_ACTIVE", "DORMANT", "QUARANTINED"},
    "RESEARCH_ACTIVE": {"SHADOW_CANDIDATE", "DORMANT", "QUARANTINED"},
    "SHADOW_CANDIDATE": {"SHADOW_ACTIVE", "RESEARCH_ACTIVE", "DORMANT", "QUARANTINED"},
    "SHADOW_ACTIVE": {"PAPER_CANARY", "RESEARCH_ACTIVE", "DORMANT", "QUARANTINED"},
    "PAPER_CANARY": {"PAPER_ACTIVE", "SHADOW_ACTIVE", "QUARANTINED"},
    "PAPER_ACTIVE": {"LIVE_MICRO", "SHADOW_ACTIVE", "QUARANTINED"},
    "LIVE_MICRO": {"LIVE_ACTIVE", "PAPER_ACTIVE", "QUARANTINED"},
    "LIVE_ACTIVE": {"PAPER_ACTIVE", "QUARANTINED"},
    "DORMANT": {"LIVENESS_TEST", "RESEARCH_ACTIVE", "RETIRED", "QUARANTINED"},
    "QUARANTINED": {"LIVENESS_TEST", "DORMANT", "RETIRED"},
    "RETIRED": set(),
}
REQUIRED_EVIDENCE = {
    "LIVENESS_TEST": {"source_sha_verified", "indicator_liveness_checked"},
    "RESEARCH_ACTIVE": {"source_sha_verified", "behavioral_fidelity_pass"},
    "SHADOW_CANDIDATE": {"failure_fingerprint", "single_axis_change", "parent_immutable"},
    "SHADOW_ACTIVE": {"lineage_coverage_pct", "duplicate_event_count", "cross_lane_leak_count"},
    "PAPER_CANARY": {"shadow_gate_receipt_sha", "paper_authority_receipt_sha", "human_approval"},
    "PAPER_ACTIVE": {"paper_days", "paper_gate_receipt_sha", "rollback_drill_pass"},
    "LIVE_MICRO": {"micro_live_authority_receipt_sha", "human_approval", "emergency_stop_drill_pass"},
    "LIVE_ACTIVE": {"micro_live_gate_receipt_sha", "human_approval", "capital_risk_ssot_bound"},
    "DORMANT": {"failure_fingerprint"},
    "QUARANTINED": {"quarantine_reason"},
    "RETIRED": {"retirement_reason", "human_approval"},
}


class StrategyLifecycleError(ValueError):
    pass


def _fail(code: str, detail: str = "") -> None:
    raise StrategyLifecycleError(f"{code}:{detail}" if detail else code)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def canonical_sha(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail("OBJECT_REQUIRED", name)
    return dict(value)


def _string(value: Any, name: str, *, maximum: int = 240) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail("STRING_REQUIRED", name)
    result = value.strip()
    if len(result) > maximum:
        _fail("STRING_TOO_LONG", name)
    return result


def _sha(value: Any, name: str) -> str:
    result = _string(value, name, maximum=64).lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        _fail("SHA256_REQUIRED", name)
    return result


def _boolean(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        _fail("BOOL_REQUIRED", name)
    return value


def _integer(value: Any, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        _fail("INT_REQUIRED", name)
    return value


def _enum(value: Any, name: str, allowed: set[str]) -> str:
    result = _string(value, name).upper()
    if result not in allowed:
        _fail("ENUM_INVALID", f"{name}={result}")
    return result


def validate_registry(value: Mapping[str, Any], *, require_sealed_sha: bool = True) -> dict[str, Any]:
    registry = _mapping(value, "registry")
    if registry.get("schema_version") != SCHEMA_VERSION:
        _fail("SCHEMA_VERSION_MISMATCH")
    entries = registry.get("entries")
    if not isinstance(entries, list) or len(entries) != STRATEGY_COUNT:
        _fail("STRATEGY_COUNT_MISMATCH", str(len(entries) if isinstance(entries, list) else -1))

    normalized_entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(entries):
        row = _mapping(raw, f"entries[{index}]")
        strategy_id = _string(row.get("strategy_id"), f"entries[{index}].strategy_id", maximum=120)
        if strategy_id in seen:
            _fail("DUPLICATE_STRATEGY_ID", strategy_id)
        seen.add(strategy_id)
        state = _enum(row.get("state"), f"entries[{index}].state", STATES)
        family = _enum(row.get("family"), f"entries[{index}].family", FAMILIES)
        observer_allowed = _boolean(row.get("observer_allowed"), f"entries[{index}].observer_allowed")
        capital_allowed = _boolean(row.get("capital_allowed"), f"entries[{index}].capital_allowed")
        if capital_allowed and state not in CAPITAL_STATES:
            _fail("CAPITAL_ALLOWED_OUTSIDE_CAPITAL_STATE", strategy_id)
        if state in CAPITAL_STATES and not capital_allowed:
            _fail("CAPITAL_STATE_REQUIRES_CAPITAL_ALLOWED", strategy_id)
        source = _mapping(row.get("canonical_source"), f"entries[{index}].canonical_source")
        source_sha = _sha(source.get("source_sha256"), f"entries[{index}].canonical_source.source_sha256")
        normalized_entries.append({
            "strategy_id": strategy_id,
            "family": family,
            "state": state,
            "observer_allowed": observer_allowed,
            "capital_allowed": capital_allowed,
            "canonical_source": {
                "implementation_path": _string(source.get("implementation_path"), f"entries[{index}].canonical_source.implementation_path"),
                "callable": _string(source.get("callable"), f"entries[{index}].canonical_source.callable"),
                "source_sha256": source_sha,
                "source_ref": _string(source.get("source_ref"), f"entries[{index}].canonical_source.source_ref"),
            },
            "parent_sha256": _sha(row.get("parent_sha256"), f"entries[{index}].parent_sha256"),
            "current_child_sha256": (
                _sha(row.get("current_child_sha256"), f"entries[{index}].current_child_sha256")
                if row.get("current_child_sha256") not in (None, "") else None
            ),
            "failure_fingerprint": _string(row.get("failure_fingerprint"), f"entries[{index}].failure_fingerprint"),
            "native_profile_status": _string(row.get("native_profile_status"), f"entries[{index}].native_profile_status"),
            "reopen_conditions": sorted({_string(item, f"entries[{index}].reopen_conditions[]", maximum=120) for item in (row.get("reopen_conditions") or [])}),
            "evidence_refs": sorted({_string(item, f"entries[{index}].evidence_refs[]", maximum=300) for item in (row.get("evidence_refs") or [])}),
        })
        if normalized_entries[-1]["parent_sha256"] != source_sha:
            _fail("PARENT_SOURCE_SHA_MISMATCH", strategy_id)

    normalized = {
        "schema_version": SCHEMA_VERSION,
        "registry_revision": _integer(registry.get("registry_revision"), "registry_revision", minimum=1),
        "source_registry_ref": _string(registry.get("source_registry_ref"), "source_registry_ref"),
        "source_registry_blob_sha": _string(registry.get("source_registry_blob_sha"), "source_registry_blob_sha", maximum=40).lower(),
        "source_registry_semantic_sha256": _sha(registry.get("source_registry_semantic_sha256"), "source_registry_semantic_sha256"),
        "strategy_count": STRATEGY_COUNT,
        "entries": sorted(normalized_entries, key=lambda row: row["strategy_id"]),
        "authority": {
            "research_only": True,
            "runtime_bound": False,
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "paper_allowed": False,
            "live_allowed": False,
        },
    }
    blob_sha = normalized["source_registry_blob_sha"]
    if len(blob_sha) != 40 or any(ch not in "0123456789abcdef" for ch in blob_sha):
        _fail("GIT_BLOB_SHA_REQUIRED", "source_registry_blob_sha")
    supplied_authority = _mapping(registry.get("authority"), "authority")
    for key, expected in normalized["authority"].items():
        if supplied_authority.get(key) != expected:
            _fail("AUTHORITY_MISMATCH", key)
    computed = canonical_sha(normalized)
    if require_sealed_sha:
        supplied = _sha(registry.get("registry_sha256"), "registry_sha256")
        if supplied != computed:
            _fail("REGISTRY_SHA_MISMATCH")
    normalized["registry_sha256"] = computed
    return normalized


def seal_registry(value: Mapping[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(dict(value))
    payload.pop("registry_sha256", None)
    normalized = validate_registry(payload, require_sealed_sha=False)
    normalized["registry_sha256"] = canonical_sha({k: v for k, v in normalized.items() if k != "registry_sha256"})
    return validate_registry(normalized, require_sealed_sha=True)


def transition(registry: Mapping[str, Any], strategy_id: str, target_state: str, evidence: Mapping[str, Any]) -> dict[str, Any]:
    current = validate_registry(registry)
    target = _enum(target_state, "target_state", STATES)
    evidence_map = _mapping(evidence, "evidence")
    rows = {row["strategy_id"]: row for row in current["entries"]}
    if strategy_id not in rows:
        _fail("STRATEGY_NOT_FOUND", strategy_id)
    row = rows[strategy_id]
    if target not in ALLOWED_TRANSITIONS[row["state"]]:
        _fail("TRANSITION_FORBIDDEN", f"{row['state']}->{target}")
    missing = sorted(
        key for key in REQUIRED_EVIDENCE.get(target, set())
        if evidence_map.get(key) is None or evidence_map.get(key) == "" or evidence_map.get(key) is False
    )
    if missing:
        _fail("TRANSITION_EVIDENCE_MISSING", ",".join(missing))
    if target == "SHADOW_ACTIVE":
        if float(evidence_map["lineage_coverage_pct"]) != 100.0:
            _fail("LINEAGE_NOT_COMPLETE")
        if int(evidence_map["duplicate_event_count"]) != 0:
            _fail("DUPLICATE_EVENT_PRESENT")
        if int(evidence_map["cross_lane_leak_count"]) != 0:
            _fail("CROSS_LANE_LEAK_PRESENT")
    capital_allowed = target in CAPITAL_STATES
    if capital_allowed and evidence_map.get("human_approval") is not True:
        _fail("HUMAN_APPROVAL_REQUIRED")
    updated = copy.deepcopy(current)
    updated.pop("registry_sha256", None)
    updated["registry_revision"] += 1
    for candidate in updated["entries"]:
        if candidate["strategy_id"] != strategy_id:
            continue
        candidate["state"] = target
        candidate["capital_allowed"] = capital_allowed
        if "failure_fingerprint" in evidence_map:
            candidate["failure_fingerprint"] = _string(evidence_map["failure_fingerprint"], "failure_fingerprint")
        if evidence_map.get("current_child_sha256"):
            candidate["current_child_sha256"] = _sha(evidence_map["current_child_sha256"], "current_child_sha256")
        refs = evidence_map.get("evidence_refs") or []
        candidate["evidence_refs"] = sorted(set(candidate["evidence_refs"]) | {_string(item, "evidence_refs[]", maximum=300) for item in refs})
        break
    return seal_registry(updated)
