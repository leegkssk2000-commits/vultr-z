from __future__ import annotations

import time
from typing import Any, Dict

from fastapi import APIRouter, Body

router = APIRouter(tags=["zops-order-gate-alias-for-harness-v1"])


def _now_ms() -> int:
    return int(time.time() * 1000)


def _fallback_health() -> Dict[str, Any]:
    return {
        "ok": True,
        "component": "order_gate_alias_for_harness_v1",
        "alias_for": "gate_contract_v1",
        "advisory_only": True,
        "execution_enabled": False,
        "order_mutation": "blocked",
        "os_final_approval_required": True,
        "zbot_authority": "recommend_only",
        "ts_ms": _now_ms(),
    }


def _fallback_status() -> Dict[str, Any]:
    return {
        "ok": True,
        "component": "order_gate_alias_for_harness_v1",
        "status": "alias_ready",
        "phase": "v3.1_hardening_layer",
        "advisory_only": True,
        "execution_enabled": False,
        "order_mutation": "blocked",
        "os_final_approval_required": True,
        "zbot_authority": "recommend_only",
        "contract": {
            "advisory_only": True,
            "order_mutation": "blocked",
            "OS final approval required": True,
            "routes_return_json_not_404": True,
        },
        "ts_ms": _now_ms(),
    }


def _fallback_validate(payload: Dict[str, Any]) -> Dict[str, Any]:
    # Fail-closed alias if the original gate router is unavailable.
    return {
        "ok": True,
        "gate_pass": False,
        "allowed_action": "hold",
        "advisory_only": True,
        "execution_enabled": False,
        "order_mutation": "blocked",
        "os_final_approval_required": True,
        "zbot_authority": "recommend_only",
        "reject_reasons": ["ALIAS_FALLBACK_ORIGINAL_GATE_UNAVAILABLE", "HOLD_FIXED"],
        "input_echo": payload or {},
        "ts_ms": _now_ms(),
    }


def _call_original(name: str, payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
    try:
        try:
            from routers import gate_contract_v1 as g  # type: ignore
        except Exception:
            from backend.routers import gate_contract_v1 as g  # type: ignore
        fn = getattr(g, name)
        if payload is None:
            out = fn()
        else:
            out = fn(payload or {})
        if isinstance(out, dict):
            out.setdefault("alias_route", "/api/order-gate")
            out.setdefault("order_mutation", "blocked")
            out.setdefault("os_final_approval_required", True)
            out.setdefault("zbot_authority", "recommend_only")
            return out
    except Exception as exc:
        fb = _fallback_status() if name in {"gate_status", "gate_policy"} else _fallback_health()
        fb["original_call_error"] = str(exc)
        return fb
    return _fallback_health()


@router.get("/api/order-gate/health")
def order_gate_health() -> Dict[str, Any]:
    return _call_original("gate_health")


@router.get("/api/order-gate/status")
def order_gate_status() -> Dict[str, Any]:
    return _call_original("gate_status")


@router.get("/api/order-gate/policy")
def order_gate_policy() -> Dict[str, Any]:
    return _call_original("gate_policy")


@router.get("/api/order-gate/sample")
def order_gate_sample() -> Dict[str, Any]:
    sample = {
        "symbol": "BTCUSDT",
        "strategy": "alpha1",
        "mode": "shadow",
        "action": "hold",
        "price": 100000,
        "pos_pct": 0,
        "lev": 1,
        "entry_ts": _now_ms(),
        "liq_buffer_pct": 99,
        "funding_8h_pct": 0.0,
        "dd_day_pct": 0.0,
        "dd_total_pct": 0.0,
        "source": {"sealed": True, "cf": True},
        "os_approved": False,
    }
    out = _call_original("gate_pretrade", sample)
    out["sample"] = sample
    return out


@router.post("/api/order-gate/pretrade")
def order_gate_pretrade(envelope: Dict[str, Any] = Body(default_factory=dict)) -> Dict[str, Any]:
    try:
        return _call_original("gate_pretrade", envelope or {})
    except Exception:
        return _fallback_validate(envelope or {})


@router.post("/api/order-gate/risk")
def order_gate_risk(envelope: Dict[str, Any] = Body(default_factory=dict)) -> Dict[str, Any]:
    try:
        return _call_original("gate_risk", envelope or {})
    except Exception:
        return _fallback_validate(envelope or {})


@router.post("/api/order-gate/ack")
def order_gate_ack(envelope: Dict[str, Any] = Body(default_factory=dict)) -> Dict[str, Any]:
    try:
        return _call_original("gate_ack", envelope or {})
    except Exception:
        return {
            "ok": True,
            "ack": True,
            "mutation": "none",
            "order_mutation": "blocked",
            "os_final_approval_required": True,
            "zbot_authority": "recommend_only",
            "received": envelope or {},
            "ts_ms": _now_ms(),
        }
