from __future__ import annotations

from typing import Any, Dict, List


_REASON_BY_RULE = {
    "decision_id_required": ("critical", "missing_decision_id"),
    "freshness_required": ("high", "missing_freshness"),
    "change_digest_required": ("high", "missing_change_digest"),
    "ack_contract_required": ("medium", "missing_ack_contract"),
}


def _safe_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}



def _rule_meta(rule_id: str) -> tuple[str, str]:
    return _REASON_BY_RULE.get(rule_id, ("medium", "contract_violation"))



def build_violation_events(payload: Dict[str, Any], validator: Dict[str, Any]) -> List[Dict[str, Any]]:
    decision_id = str(payload.get("decision_id") or "missing")
    backend_ver = str(payload.get("backend_ver") or "unknown")
    path = "/api/rail-status"
    events: List[Dict[str, Any]] = []

    for item in validator.get("violations", []) or []:
        details = _safe_dict(item.get("details"))
        rule_id = str(item.get("rule_id") or "unknown")
        default_severity, reason_code = _rule_meta(rule_id)
        severity = str(item.get("severity") or default_severity)
        events.append(
            {
                "decision_id": decision_id,
                "backend_ver": backend_ver,
                "rule_id": rule_id,
                "severity": severity,
                "reason_code": reason_code,
                "path": path,
                "details": details,
            }
        )
    return events
