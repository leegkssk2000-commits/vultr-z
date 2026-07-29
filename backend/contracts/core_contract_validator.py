from __future__ import annotations

from typing import Any, Dict, List, Optional


RULE_DECISION_ID = "decision_id_required"
RULE_FRESHNESS = "freshness_required"
RULE_CHANGE_DIGEST = "change_digest_required"
RULE_ACK = "ack_contract_required"


def _violation(rule_id: str, severity: str, reason: str, details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        "rule_id": rule_id,
        "severity": severity,
        "reason": reason,
        "details": details or {},
    }


def validate_core_contract(payload: Dict[str, Any]) -> Dict[str, Any]:
    decision_id = payload.get("decision_id")
    change_digest = payload.get("change_digest")
    freshness = payload.get("freshness") if isinstance(payload.get("freshness"), dict) else {}
    ack = payload.get("ack") if isinstance(payload.get("ack"), dict) else {}

    violations: List[Dict[str, Any]] = []

    if not decision_id:
        violations.append(
            _violation(
                RULE_DECISION_ID,
                "high",
                "decision_id is required",
            )
        )

    freshness_ok = bool(
        freshness.get("source_ts")
        or "stale" in freshness
        or freshness.get("verification_status")
    )
    if not freshness_ok:
        violations.append(
            _violation(
                RULE_FRESHNESS,
                "medium",
                "freshness payload requires source_ts or stale/verification fields",
            )
        )

    if not change_digest:
        violations.append(
            _violation(
                RULE_CHANGE_DIGEST,
                "medium",
                "change_digest is required",
            )
        )

    ack_ok = bool(ack.get("scope")) and ack.get("ttl_s") is not None
    if not ack_ok:
        violations.append(
            _violation(
                RULE_ACK,
                "low",
                "ack requires scope and ttl_s",
            )
        )

    return {
        "ok": len(violations) == 0,
        "count": len(violations),
        "violations": violations,
        "rules": [RULE_DECISION_ID, RULE_FRESHNESS, RULE_CHANGE_DIGEST, RULE_ACK],
    }
