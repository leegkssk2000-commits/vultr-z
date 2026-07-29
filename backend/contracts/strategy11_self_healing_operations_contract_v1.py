from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

VERSION = "STRATEGY11_SELF_HEALING_OPERATIONS_CONTRACT_V1"
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
SAFETY = {
    "research_only": True,
    "promotion_authority": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "order_authority": "BLOCKED",
    "runtime_bound": False,
    "automatic_recovery_execute_allowed": False,
    "service_mutation_allowed": False,
    "ledger_mutation_allowed": False,
    "writer_reassignment_allowed": False,
}


class SelfHealingContractError(ValueError):
    pass


@dataclass(frozen=True)
class Decision:
    state: str
    action: str
    blockers: tuple[str, ...]
    recovery_requests: tuple[Mapping[str, Any], ...]
    metrics: Mapping[str, Any]
    lineage: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "strategy11.self_healing_operations_decision.v1",
            "version": VERSION,
            "state": self.state,
            "action": self.action,
            "blockers": list(self.blockers),
            "recovery_requests": [dict(item) for item in self.recovery_requests],
            "metrics": dict(self.metrics),
            "lineage": dict(self.lineage),
            **SAFETY,
        }


def stable_sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def finite(value: Any, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise SelfHealingContractError(f"INVALID_NUMBER:{name}") from exc
    if not math.isfinite(number):
        raise SelfHealingContractError(f"NONFINITE_NUMBER:{name}")
    return number


def require_sha(value: Any, name: str) -> str:
    text = str(value or "").lower()
    if not SHA_RE.fullmatch(text):
        raise SelfHealingContractError(f"INVALID_SHA:{name}")
    return text


def require_nonempty(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise SelfHealingContractError(f"EMPTY_FIELD:{name}")
    return text


def verify_policy(policy_input: Mapping[str, Any]) -> dict[str, Any]:
    policy = dict(policy_input)
    for key in (
        "fixture_only", "runtime_activation_allowed", "automatic_recovery_execute_allowed",
        "service_mutation_allowed", "ledger_mutation_allowed", "writer_reassignment_allowed",
        "threshold_authority",
    ):
        expected = key == "fixture_only"
        if policy.get(key) is not expected:
            raise SelfHealingContractError(f"POLICY_FAIL_CLOSED_MISMATCH:{key}")
    material = {key: value for key, value in policy.items() if key != "policy_sha"}
    actual = stable_sha(material)
    if policy.get("policy_sha") != actual:
        raise SelfHealingContractError(f"POLICY_SHA_MISMATCH:{actual}:{policy.get('policy_sha')}")
    domains = [str(value) for value in policy.get("required_writer_domains") or []]
    if not domains or len(domains) != len(set(domains)):
        raise SelfHealingContractError("INVALID_REQUIRED_WRITER_DOMAINS")
    return policy


def verify_binding(binding_input: Mapping[str, Any], policy_sha: str) -> dict[str, str]:
    binding = {
        "source_sha": require_sha(binding_input.get("source_sha"), "source_sha"),
        "data_sha": require_sha(binding_input.get("data_sha"), "data_sha"),
        "policy_sha": require_sha(binding_input.get("policy_sha"), "policy_sha"),
        "run_id": require_nonempty(binding_input.get("run_id"), "run_id"),
        "artifact_id": require_nonempty(binding_input.get("artifact_id"), "artifact_id"),
    }
    if binding["policy_sha"] != policy_sha:
        raise SelfHealingContractError("REQUEST_POLICY_SHA_MISMATCH")
    return binding


def active_writer_map(writers: Sequence[Mapping[str, Any]]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for index, row in enumerate(writers):
        domain = require_nonempty(row.get("domain"), f"writers[{index}].domain")
        writer_id = require_nonempty(row.get("writer_id"), f"writers[{index}].writer_id")
        if row.get("active") is True:
            result.setdefault(domain, []).append(writer_id)
    return {key: sorted(value) for key, value in sorted(result.items())}


def deduplicate_incidents(incidents: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    unique: dict[str, dict[str, Any]] = {}
    duplicates = 0
    for index, row in enumerate(incidents):
        fingerprint = require_nonempty(row.get("fingerprint"), f"incidents[{index}].fingerprint")
        normalized = {
            "fingerprint": fingerprint,
            "severity": require_nonempty(row.get("severity"), f"incidents[{index}].severity"),
            "required_action": require_nonempty(row.get("required_action"), f"incidents[{index}].required_action"),
        }
        if fingerprint in unique:
            duplicates += 1
            continue
        unique[fingerprint] = normalized
    return {
        "unique": [unique[key] for key in sorted(unique)],
        "input_count": len(incidents),
        "unique_count": len(unique),
        "duplicate_count": duplicates,
    }


def evaluate_operations(snapshot: Mapping[str, Any], policy_input: Mapping[str, Any]) -> dict[str, Any]:
    policy = verify_policy(policy_input)
    binding = verify_binding(snapshot.get("source_binding") or {}, str(policy["policy_sha"]))
    now_ms = int(finite(snapshot.get("now_ms"), "now_ms"))
    writers = active_writer_map(snapshot.get("writers") or [])
    incidents = deduplicate_incidents(snapshot.get("incidents") or [])

    blockers: list[str] = []
    recovery_requests: list[dict[str, Any]] = []
    stale_components: list[str] = []
    failed_components: list[str] = []
    source_mismatches: list[str] = []

    required_domains = [str(value) for value in policy["required_writer_domains"]]
    for domain in required_domains:
        count = len(writers.get(domain, []))
        if count == 0:
            blockers.append(f"MISSING_ACTIVE_WRITER:{domain}")
        elif count > 1:
            blockers.append(f"MULTIPLE_ACTIVE_WRITERS:{domain}")

    components = snapshot.get("components") or []
    if not isinstance(components, Sequence) or isinstance(components, (str, bytes)) or not components:
        raise SelfHealingContractError("EMPTY_COMPONENTS")
    for index, row in enumerate(components):
        component_id = require_nonempty(row.get("component_id"), f"components[{index}].component_id")
        heartbeat_age = max(0, now_ms - int(finite(row.get("heartbeat_ts_ms"), f"components[{index}].heartbeat_ts_ms")))
        data_age = max(0, now_ms - int(finite(row.get("data_ts_ms"), f"components[{index}].data_ts_ms")))
        service_state = require_nonempty(row.get("service_state"), f"components[{index}].service_state").upper()
        timer_active = row.get("timer_active") is True
        expected_source_sha = require_sha(row.get("expected_source_sha"), f"components[{index}].expected_source_sha")
        observed_source_sha = require_sha(row.get("observed_source_sha"), f"components[{index}].observed_source_sha")
        if heartbeat_age > int(policy["max_heartbeat_age_ms"]) or data_age > int(policy["max_data_age_ms"]):
            stale_components.append(component_id)
        if service_state != "ACTIVE" or not timer_active:
            failed_components.append(component_id)
        if expected_source_sha != observed_source_sha:
            source_mismatches.append(component_id)

    parity_rows = snapshot.get("parity_checks") or []
    parity_mismatches: list[str] = []
    for index, row in enumerate(parity_rows):
        name = require_nonempty(row.get("name"), f"parity_checks[{index}].name")
        expected = require_sha(row.get("expected_sha"), f"parity_checks[{index}].expected_sha")
        observed = require_sha(row.get("observed_sha"), f"parity_checks[{index}].observed_sha")
        if expected != observed:
            parity_mismatches.append(name)

    authority = snapshot.get("authority") or {}
    if int(authority.get("protected_mutations") or 0) != 0:
        blockers.append("PROTECTED_MUTATION_DETECTED")
    if authority.get("execution_allowed") is not False:
        blockers.append("EXECUTION_AUTHORITY_ANOMALY")
    if str(authority.get("order_authority") or "") != "BLOCKED":
        blockers.append("ORDER_AUTHORITY_ANOMALY")

    if source_mismatches:
        blockers.extend(f"SOURCE_SHA_MISMATCH:{value}" for value in source_mismatches)
    if parity_mismatches:
        blockers.extend(f"PARITY_MISMATCH:{value}" for value in parity_mismatches)
    if stale_components:
        blockers.extend(f"STALE_COMPONENT:{value}" for value in stale_components)

    last_good = snapshot.get("last_good_snapshot") or {}
    if failed_components:
        snapshot_sha = require_sha(last_good.get("snapshot_sha"), "last_good_snapshot.snapshot_sha")
        if last_good.get("compile_ok") is not True or last_good.get("verified") is not True:
            blockers.append("NO_VERIFIED_ROLLBACK_SNAPSHOT")
        else:
            recovery_requests.append({
                "request_type": "ROLLBACK_TO_LAST_VERIFIED_SNAPSHOT",
                "snapshot_sha": snapshot_sha,
                "failed_components": sorted(failed_components),
                "execute_allowed": False,
            })

    blockers = sorted(set(blockers))
    writer_block = any(value.startswith(("MISSING_ACTIVE_WRITER:", "MULTIPLE_ACTIVE_WRITERS:")) for value in blockers)
    authority_block = any(value.endswith("AUTHORITY_ANOMALY") or value == "PROTECTED_MUTATION_DETECTED" for value in blockers)
    parity_block = any(value.startswith(("SOURCE_SHA_MISMATCH:", "PARITY_MISMATCH:")) for value in blockers)

    if writer_block or authority_block:
        state = "BLOCK_SELF_HEALING_AUTHORITY"
        action = "block"
    elif recovery_requests:
        state = "ROLLBACK_REQUEST_SELF_HEALING"
        action = "rollback"
    elif parity_block or blockers:
        state = "HOLD_SELF_HEALING_OPERATIONS"
        action = "hold"
    else:
        state = "PASS_SELF_HEALING_OBSERVER"
        action = "hold"

    metrics = {
        "required_writer_domain_count": len(required_domains),
        "active_writer_map": writers,
        "component_count": len(components),
        "stale_components": sorted(stale_components),
        "failed_components": sorted(failed_components),
        "source_mismatches": sorted(source_mismatches),
        "parity_mismatches": sorted(parity_mismatches),
        "incident_input_count": incidents["input_count"],
        "incident_unique_count": incidents["unique_count"],
        "incident_duplicate_count": incidents["duplicate_count"],
        "incident_fingerprints": [row["fingerprint"] for row in incidents["unique"]],
    }
    lineage = {
        **binding,
        "component_snapshot_sha": stable_sha(components),
        "writer_snapshot_sha": stable_sha(snapshot.get("writers") or []),
        "parity_snapshot_sha": stable_sha(parity_rows),
        "incident_snapshot_sha": stable_sha(snapshot.get("incidents") or []),
        "request_sha": stable_sha(snapshot),
    }
    result = Decision(state, action, tuple(blockers), tuple(recovery_requests), metrics, lineage).as_dict()
    result["decision_sha"] = stable_sha(result)
    return result
