# ZOPS_ORDER_GATE_ALIAS_HARD_MOUNT_V2
# Advisory/read-only API alias for Harness Control Plane.
# Contract: /api/order-gate/* must return JSON and never mutate orders.
from __future__ import annotations

import time
from typing import Any, Dict
from fastapi import APIRouter, Body

router = APIRouter()

ALLOWED_ACTIONS = [
    "reduce25", "partial30", "hold", "stop", "route_change", "rollback", "block"
]


def _ts_ms() -> int:
    return int(time.time() * 1000)


def _base() -> Dict[str, Any]:
    return {
        "ok": True,
        "component": "order_risk_gate_contract_v1",
        "alias_component": "order_gate_alias_hard_mount_v2",
        "phase": "v3.1_hardening_layer",
        "policy_id": "zops_gate_policy_v1",
        "mode": "advisory_only",
        "execution_enabled": False,
        "order_mutation": "blocked",
        "os_final_approval_required": True,
        "zbot_authority": "recommend_only",
        "allowed_actions": ALLOWED_ACTIONS,
        "ts_ms": _ts_ms(),
    }


@router.get("/health")
def health() -> Dict[str, Any]:
    payload = _base()
    payload.update({
        "status": "ok",
        "route": "/api/order-gate/health",
        "contract": "json_not_404",
    })
    return payload


@router.get("/status")
def status() -> Dict[str, Any]:
    payload = _base()
    payload.update({
        "status": "sealed",
        "route": "/api/order-gate/status",
        "paper_allowed": True,
        "shadow_allowed": True,
        "live_allowed_without_os_approve": False,
        "checks": {
            "synchronous_pre_trade_validation": True,
            "async_risk_monitoring": True,
            "structured_reject_reason": True,
            "rate_limit_required": True,
            "position_sizing_required": True,
            "correlation_check_required": True,
        },
    })
    return payload


@router.get("/sample")
def sample() -> Dict[str, Any]:
    payload = _base()
    payload.update({
        "status": "sample_ok",
        "route": "/api/order-gate/sample",
        "sample_decision": {
            "decision_id": "order_gate_alias_sample_001",
            "symbol": "BTCUSDT",
            "strategy": "alpha1",
            "requested_action": "hold",
            "allowed_action": "hold",
            "reject": False,
            "reason_enum": "ADVISORY_ONLY_SAMPLE",
            "human_message": "advisory-only sample; no order mutation path exposed",
        },
    })
    return payload


@router.post("/validate")
def validate(payload_in: Dict[str, Any] = Body(default_factory=dict)) -> Dict[str, Any]:
    payload = _base()
    requested = payload_in.get("requested_action") or payload_in.get("action") or "hold"
    payload.update({
        "status": "validated_advisory_only",
        "route": "/api/order-gate/validate",
        "request_echo": payload_in,
        "requested_action": requested,
        "allowed_action": requested if requested in ALLOWED_ACTIONS else "hold",
        "mutated_order": False,
        "reject": requested not in ALLOWED_ACTIONS,
        "reason_enum": "ACTION_ALLOWED" if requested in ALLOWED_ACTIONS else "ACTION_NOT_ALLOWED_ENUM",
        "human_message": "Order Gate is advisory-only; OS final approval required before any live order.",
    })
    return payload
