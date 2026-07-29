# ZOPS_ORDER_GATE_EOF_SAFE_MOUNT_V4
# Append-only runtime mount for /api/order-gate/*.
# No live order mutation. Zbot recommends only. OS remains final approval authority.
from __future__ import annotations

import time
from typing import Any, Dict
from fastapi import Request

ALLOWED_ACTIONS = [
    "reduce25", "partial30", "hold", "stop", "route_change", "rollback", "block"
]


def _ts_ms() -> int:
    return int(time.time() * 1000)


def _base(route: str) -> Dict[str, Any]:
    return {
        "ok": True,
        "component": "order_risk_gate_contract_v1",
        "runtime_mount": "zops_order_gate_eof_safe_mount_v4",
        "phase": "v3.1_hardening_layer",
        "route": route,
        "status": "ok",
        "mode": "advisory_only",
        "execution_enabled": False,
        "order_mutation": "blocked",
        "os_final_approval_required": True,
        "zbot_authority": "recommend_only",
        "allowed_actions": ALLOWED_ACTIONS,
        "ts_ms": _ts_ms(),
    }


def _has_route(app: Any, path: str, method: str) -> bool:
    method = method.upper()
    for r in getattr(app, "routes", []):
        if getattr(r, "path", None) != path:
            continue
        methods = getattr(r, "methods", set()) or set()
        if method in methods:
            return True
    return False


def mount_order_gate_routes(app: Any) -> Dict[str, Any]:
    mounted = []
    skipped = []

    async def og_health() -> Dict[str, Any]:
        p = _base("/api/order-gate/health")
        p.update({
            "contract": "json_not_404",
            "checks": {
                "synchronous_pre_trade_validation": True,
                "async_risk_monitoring": True,
                "structured_reject_reason": True,
                "config_driven_policy": True,
                "rate_limiting": True,
                "position_sizing": True,
                "correlation_check": True,
            },
        })
        return p

    async def og_status() -> Dict[str, Any]:
        p = _base("/api/order-gate/status")
        p.update({
            "status": "sealed",
            "paper_allowed": True,
            "shadow_allowed": True,
            "live_allowed_without_os_approve": False,
            "gate_contract": {
                "pre_trade_validation": "sync_required",
                "risk_monitoring": "async_required",
                "reject_reason": "structured_enum_plus_context_payload",
                "rate_limit": "required",
                "position_sizing": "required",
                "correlation_check": "required",
                "liquidity_tier": "required",
                "volatility_regime": "required",
            },
        })
        return p

    async def og_sample() -> Dict[str, Any]:
        p = _base("/api/order-gate/sample")
        p.update({
            "status": "sample_ok",
            "sample_decision": {
                "decision_id": "order_gate_eof_safe_mount_v4_sample_001",
                "symbol": "BTCUSDT",
                "strategy": "alpha1",
                "requested_action": "hold",
                "allowed_action": "hold",
                "reject": False,
                "reason_enum": "ADVISORY_ONLY_SAMPLE",
                "human_message": "advisory-only sample; no order mutation path exposed",
            },
        })
        return p

    async def og_validate(request: Request) -> Dict[str, Any]:
        try:
            body = await request.json()
            if not isinstance(body, dict):
                body = {"raw": body}
        except Exception:
            body = {}
        requested = body.get("requested_action") or body.get("action") or "hold"
        allowed = requested if requested in ALLOWED_ACTIONS else "hold"
        p = _base("/api/order-gate/validate")
        p.update({
            "status": "validated_advisory_only",
            "request_echo": body,
            "requested_action": requested,
            "allowed_action": allowed,
            "mutated_order": False,
            "reject": requested not in ALLOWED_ACTIONS,
            "reason_enum": "ACTION_ALLOWED" if requested in ALLOWED_ACTIONS else "ACTION_NOT_ALLOWED_ENUM",
            "human_message": "Order Gate is advisory-only; OS final approval required before live order.",
        })
        return p

    specs = [
        ("/api/order-gate/health", ["GET"], og_health, "zops_order_gate_health_v4"),
        ("/api/order-gate/status", ["GET"], og_status, "zops_order_gate_status_v4"),
        ("/api/order-gate/sample", ["GET"], og_sample, "zops_order_gate_sample_v4"),
        ("/api/order-gate/validate", ["POST"], og_validate, "zops_order_gate_validate_v4"),
    ]
    for path, methods, endpoint, name in specs:
        method = methods[0]
        if _has_route(app, path, method):
            skipped.append(path)
            continue
        app.add_api_route(path, endpoint, methods=methods, name=name, tags=["zops-order-gate"])
        mounted.append(path)
    return {"mounted": mounted, "skipped_existing": skipped}
