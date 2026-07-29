from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

SCHEMA_VERSION = "strategy11.role_boundary.zbot_zico_lico_zlice.v1"
SAFETY = {
    "research_only": True,
    "promotion_authority": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "order_authority": "BLOCKED",
}
REQUIRED_LINEAGE = {
    "strategy_id", "method_id", "skill_id", "team_id", "event_ts",
    "source_ids", "contract_version", "source_manifest_sha",
}
PRIVATE_ACTIONS = {
    "OPEN_ORDER", "CLOSE_ORDER", "AMEND_ORDER", "CANCEL_ORDER", "SET_LEVERAGE",
    "SET_POSITION_SIZE", "ENABLE_LIVE", "ENABLE_PAPER", "MUTATE_STRATEGY",
    "GENERATE_STRATEGY", "SET_PORTFOLIO_WEIGHT", "PROMOTE_CANDIDATE",
    "OVERRIDE_SBOT_VETO", "FINAL_TRADE_DECISION", "WRITE_FORMAL_LEDGER",
}
ROLE_SPECS = {
    "ZBOT": {
        "role": "advisor_decision_trace_only_not_team_bot",
        "allowed_actions": {
            "ADVISE", "COUNTERARGUE", "PROPOSE_ALTERNATIVES",
            "EMIT_COUNTERFACTUAL", "ABSTAIN",
        },
        "required_payload": {"advice", "alternatives", "counterfactual"},
        "can_veto": False,
        "can_request_hold": True,
        "can_request_rollback": False,
    },
    "ZICO": {
        "role": "intent_and_lifecycle_context_control_without_trade_authority",
        "allowed_actions": {
            "EMIT_INTENT_CONTEXT", "EMIT_LIFECYCLE_CONTEXT", "REQUEST_HOLD",
            "REQUEST_COOLDOWN", "REQUEST_ROLLBACK", "ABSTAIN",
        },
        "required_payload": {"intent_state", "lifecycle_state", "control_context"},
        "can_veto": False,
        "can_request_hold": True,
        "can_request_rollback": True,
    },
    "LICO": {
        "role": "liquidity_macro_fx_context_without_trade_authority",
        "allowed_actions": {
            "EMIT_CONTEXT_ENVELOPE", "EMIT_LIQUIDITY_CONTEXT",
            "EMIT_COST_CAPACITY_CONTEXT", "REQUEST_HOLD", "ABSTAIN",
        },
        "required_payload": {"liquidity", "macro", "fx", "freshness", "cost_capacity"},
        "can_veto": False,
        "can_request_hold": True,
        "can_request_rollback": False,
    },
    "ZLICE": {
        "role": "evidence_and_lifecycle_trace_without_trade_authority",
        "allowed_actions": {
            "PROJECT_EVIDENCE", "EMIT_LINEAGE_TRACE", "EMIT_LIFECYCLE_TRACE",
            "EMIT_ATTRIBUTION", "REQUEST_HOLD", "ABSTAIN",
        },
        "required_payload": {"evidence_lineage", "lifecycle_trace", "source_ids"},
        "can_veto": False,
        "can_request_hold": True,
        "can_request_rollback": False,
    },
}


class RoleBoundaryError(ValueError):
    pass


def _fail(code: str, detail: str = "") -> None:
    raise RoleBoundaryError(f"{code}:{detail}" if detail else code)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def require_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail("STRING_REQUIRED", name)
    return value.strip()


def require_bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        _fail("BOOL_REQUIRED", name)
    return value


def require_sha(value: Any, name: str) -> str:
    result = require_string(value, name).lower()
    if len(result) != 64 or any(char not in "0123456789abcdef" for char in result):
        _fail("SHA256_REQUIRED", name)
    return result


def validate_authority(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail("OBJECT_REQUIRED", "authority")
    authority = dict(value)
    for key, expected in SAFETY.items():
        if authority.get(key) != expected:
            _fail("AUTHORITY_MISMATCH", key)
    if authority.get("runtime_bound") is not False:
        _fail("RUNTIME_BINDING_FORBIDDEN")
    return {**SAFETY, "runtime_bound": False}


def validate_lineage(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail("OBJECT_REQUIRED", "lineage")
    lineage = dict(value)
    missing = sorted(REQUIRED_LINEAGE - set(lineage))
    if missing:
        _fail("LINEAGE_FIELDS_MISSING", ",".join(missing))
    source_ids = lineage.get("source_ids")
    if not isinstance(source_ids, list) or not source_ids:
        _fail("SOURCE_IDS_REQUIRED")
    return {
        "strategy_id": require_string(lineage["strategy_id"], "lineage.strategy_id"),
        "method_id": require_string(lineage["method_id"], "lineage.method_id"),
        "skill_id": require_string(lineage["skill_id"], "lineage.skill_id"),
        "team_id": require_string(lineage["team_id"], "lineage.team_id"),
        "event_ts": require_string(lineage["event_ts"], "lineage.event_ts"),
        "source_ids": sorted({require_string(item, "lineage.source_ids[]") for item in source_ids}),
        "contract_version": require_string(lineage["contract_version"], "lineage.contract_version"),
        "source_manifest_sha": require_sha(lineage["source_manifest_sha"], "lineage.source_manifest_sha"),
    }


def validate_message(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail("OBJECT_REQUIRED", "message")
    message = dict(value)
    role = require_string(message.get("role"), "role").upper()
    if role not in ROLE_SPECS:
        _fail("ROLE_INVALID", role)
    action = require_string(message.get("action"), "action").upper()
    if action in PRIVATE_ACTIONS:
        _fail("PRIVATE_AUTHORITY_ACTION_FORBIDDEN", action)
    spec = ROLE_SPECS[role]
    if action not in spec["allowed_actions"]:
        _fail("ACTION_OUTSIDE_ROLE", f"{role}:{action}")

    stale = require_bool(message.get("stale"), "stale")
    abstain = require_bool(message.get("abstain"), "abstain")
    if stale and action != "ABSTAIN":
        _fail("STALE_INPUT_MUST_ABSTAIN")
    if abstain != (action == "ABSTAIN"):
        _fail("ABSTAIN_ACTION_MISMATCH")
    if message.get("sbot_veto_active") is True and action not in {"ABSTAIN", "REQUEST_HOLD"}:
        _fail("SBOT_VETO_PRECEDENCE")

    confidence = message.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        _fail("CONFIDENCE_NUMBER_REQUIRED")
    confidence = float(confidence)
    if not 0.0 <= confidence <= 1.0:
        _fail("CONFIDENCE_OUT_OF_RANGE")
    reasons = message.get("reason_codes")
    if not isinstance(reasons, list) or not reasons:
        _fail("REASON_CODES_REQUIRED")
    reason_codes = sorted({require_string(item, "reason_codes[]").upper() for item in reasons})

    payload = message.get("payload")
    if not isinstance(payload, Mapping):
        _fail("OBJECT_REQUIRED", "payload")
    payload = dict(payload)
    if action != "ABSTAIN":
        missing_payload = sorted(spec["required_payload"] - set(payload))
        if missing_payload:
            _fail("ROLE_PAYLOAD_FIELDS_MISSING", ",".join(missing_payload))

    normalized = {
        "schema_version": SCHEMA_VERSION,
        "role": role,
        "role_contract": spec["role"],
        "action": action,
        "payload": payload,
        "confidence": confidence,
        "abstain": abstain,
        "stale": stale,
        "latency_ms": float(message.get("latency_ms", 0.0)),
        "reason_codes": reason_codes,
        "sbot_veto_active": bool(message.get("sbot_veto_active", False)),
        "lineage": validate_lineage(message.get("lineage")),
        "authority": validate_authority(message.get("authority")),
        "capabilities": {
            "can_veto": spec["can_veto"],
            "can_request_hold": spec["can_request_hold"],
            "can_request_rollback": spec["can_request_rollback"],
            "can_generate_strategy": False,
            "can_set_weight": False,
            "can_write_formal_ledger": False,
            "can_execute_order": False,
        },
    }
    normalized["message_sha"] = sha256(normalized)
    return normalized


def role_manifest() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "source_authority_reference": {
            "pr": 77,
            "head_sha": "be2586bdc5350eb15e10a6ca8fbdecb3b542e209",
            "status": "EVIDENCE_HISTORY_NOT_RUNTIME_BOUND",
        },
        "roles": {
            role: {
                "role": spec["role"],
                "allowed_actions": sorted(spec["allowed_actions"]),
                "forbidden_actions": sorted(PRIVATE_ACTIONS),
                "required_payload": sorted(spec["required_payload"]),
                "can_veto": spec["can_veto"],
                "can_request_hold": spec["can_request_hold"],
                "can_request_rollback": spec["can_request_rollback"],
            }
            for role, spec in ROLE_SPECS.items()
        },
        "flow": [
            "INDEPENDENT_TEAM_PROPOSALS",
            "LICO_CONTEXT_AND_COST_CAPACITY_ENVELOPE",
            "ZBOT_ADVISORY_COUNTERARGUMENT",
            "GLOBAL_CLASSIFIER_AND_MATERIAL_SEAL",
            "ENSEMBLE_CORRELATION_ANALYSIS",
            "PORTFOLIO_GOVERNOR_SHADOW_TARGETS",
            "ZICO_INTENT_AND_LIFECYCLE_CONTEXT",
            "ZLICE_EVIDENCE_LINEAGE_ATTRIBUTION",
        ],
        "sbot_hard_veto_precedence": True,
        "cross_role_substitution_forbidden": True,
        "runtime_bound": False,
        **SAFETY,
    }
