from __future__ import annotations

import hashlib
import json
import math
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Body
from pydantic import BaseModel, Field

router = APIRouter(tags=["zops-order-risk-gate-v1"])

POLICY_PATH = Path(os.getenv("ZOPS_GATE_POLICY_PATH", Path(__file__).resolve().parents[1] / "config" / "zops_gate_policy_v1.json"))
_ALLOWED = {"reduce25", "partial30", "hold", "stop", "route_change", "rollback", "block"}


def _now_ms() -> int:
    return int(time.time() * 1000)


def _load_policy() -> Dict[str, Any]:
    fallback = {
        "policy_id": "zops_gate_policy_v1_fallback",
        "runtime": {"execution_enabled": False, "advisory_only": True, "paper_allowed": True, "shadow_allowed": True, "live_allowed_without_os_approve": False},
        "allowed_actions": sorted(_ALLOWED),
        "minimum_data_fields": ["symbol", "strategy", "price", "pos_pct", "lev", "entry_ts", "liq_price_or_liq_buffer_pct", "funding_8h_pct", "dd_day_pct", "dd_total_pct", "source"],
        "risk_limits": {"max_leverage": 20, "max_abs_pos_pct": 100, "min_liq_buffer_pct": 2.5, "max_dd_day_pct": 3.0, "max_dd_total_pct": 12.0, "max_funding_8h_abs_pct": 0.08, "max_data_stale_ms": 15000, "max_order_latency_ms": 750, "max_slippage_bps": 12},
        "authority": {"os_final_approval_required": True, "zbot_authority": "recommend_only", "gate_role": "pre_trade_validation_only"},
    }
    try:
        if POLICY_PATH.exists():
            data = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
            fallback.update(data)
    except Exception as exc:  # keep route alive; fail closed
        fallback["policy_load_error"] = str(exc)
    return fallback


def _float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        x = float(value)
        if math.isnan(x) or math.isinf(x):
            return None
        return x
    except Exception:
        return None


def _dig(payload: Dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload:
            return payload.get(key)
    risk = payload.get("risk") if isinstance(payload.get("risk"), dict) else {}
    pos = payload.get("position") if isinstance(payload.get("position"), dict) else {}
    market = payload.get("market") if isinstance(payload.get("market"), dict) else {}
    src = payload.get("source") if isinstance(payload.get("source"), dict) else {}
    for obj in (risk, pos, market, src):
        for key in keys:
            if key in obj:
                return obj.get(key)
    return None


def _source_sealed(source: Any) -> bool:
    if source is None:
        return False
    if isinstance(source, str):
        s = source.lower()
        return s.startswith("cf:") or s.startswith("sheets:") or "sealed" in s or "source_seal" in s
    if isinstance(source, dict):
        return bool(source.get("sealed") or source.get("source_seal") or source.get("cf") or source.get("sheets"))
    return False


def _missing(payload: Dict[str, Any]) -> List[str]:
    checks: List[Tuple[str, Any]] = [
        ("symbol", _dig(payload, "symbol")),
        ("strategy", _dig(payload, "strategy", "strategy_id")),
        ("price", _dig(payload, "price", "mark_price", "last_price")),
        ("pos_pct", _dig(payload, "pos_pct", "position_pct", "pos%")),
        ("lev", _dig(payload, "lev", "leverage")),
        ("entry_ts", _dig(payload, "entry_ts", "entry_time")),
        ("liq_price_or_liq_buffer_pct", _dig(payload, "liq_buffer_pct", "liq_price", "liquidation_price")),
        ("funding_8h_pct", _dig(payload, "funding_8h_pct", "funding8h_pct")),
        ("dd_day_pct", _dig(payload, "dd_day_pct", "drawdown_day_pct")),
        ("dd_total_pct", _dig(payload, "dd_total_pct", "drawdown_total_pct")),
        ("source", _dig(payload, "source", "src")),
    ]
    return [name for name, value in checks if value in (None, "", [])]


def _decision_id(payload: Dict[str, Any], action: str) -> str:
    basis = json.dumps({"payload": payload, "action": action, "ts_bucket": int(time.time() // 10)}, sort_keys=True, default=str)
    return f"gate_{time.strftime('%Y%m%d_%H%M%S')}_{hashlib.sha256(basis.encode()).hexdigest()[:12]}"


def _validate(payload: Dict[str, Any]) -> Dict[str, Any]:
    policy = _load_policy()
    limits = policy.get("risk_limits", {}) or {}
    runtime = policy.get("runtime", {}) or {}
    action_raw = str(_dig(payload, "action", "requested_action", "allowed_action") or "hold").strip()
    action = action_raw if action_raw in _ALLOWED else "block"
    reasons: List[str] = []
    severity = "ok"

    missing = _missing(payload)
    if missing:
        reasons.append("MINDATA_MISSING")
        severity = "hold"
        action = "hold"

    if action_raw and action_raw not in _ALLOWED:
        reasons.append("ACTION_NOT_ALLOWED")
        severity = "block"
        action = "block"

    if not _source_sealed(_dig(payload, "source", "src")):
        reasons.append("SOURCE_NOT_SEALED")
        if severity != "block":
            severity = "hold"
            action = "hold"

    mode = str(_dig(payload, "mode", "execution_mode") or "shadow").lower()
    os_approved = bool(_dig(payload, "os_approved", "os_approval", "manual_approve"))
    if mode == "live" and not os_approved:
        reasons.append("OS_APPROVAL_REQUIRED")
        severity = "block"
        action = "block"

    if not bool(runtime.get("execution_enabled", False)) and mode == "live":
        reasons.append("EXECUTION_DISABLED")
        severity = "block"
        action = "block"

    age_ms = _float(_dig(payload, "age_ms", "source_age_ms", "data_age_ms"))
    if age_ms is not None and age_ms > float(limits.get("max_data_stale_ms", 15000)):
        reasons.append("STALE_DATA")
        severity = "hold" if severity == "ok" else severity
        if severity != "block":
            action = "hold"

    lev = _float(_dig(payload, "lev", "leverage"))
    if lev is not None and lev > float(limits.get("max_leverage", 20)):
        reasons.append("LEV_EXCEEDED")
        severity = "block"
        action = "block"

    pos_pct = _float(_dig(payload, "pos_pct", "position_pct", "pos%"))
    if pos_pct is not None and abs(pos_pct) > float(limits.get("max_abs_pos_pct", 100)):
        reasons.append("EXPOSURE_EXCEEDED")
        severity = "block"
        action = "block"

    liq_buffer = _float(_dig(payload, "liq_buffer_pct", "liquidation_buffer_pct"))
    if liq_buffer is not None and liq_buffer < float(limits.get("min_liq_buffer_pct", 2.5)):
        reasons.append("LIQ_BUFFER_LOW")
        severity = "block"
        action = "block"

    dd_day = _float(_dig(payload, "dd_day_pct", "drawdown_day_pct"))
    if dd_day is not None and abs(dd_day) > float(limits.get("max_dd_day_pct", 3.0)):
        reasons.append("DD_DAY_EXCEEDED")
        severity = "block"
        action = "block"

    dd_total = _float(_dig(payload, "dd_total_pct", "drawdown_total_pct"))
    if dd_total is not None and abs(dd_total) > float(limits.get("max_dd_total_pct", 12.0)):
        reasons.append("DD_TOTAL_EXCEEDED")
        severity = "block"
        action = "block"

    funding = _float(_dig(payload, "funding_8h_pct", "funding8h_pct"))
    if funding is not None and abs(funding) > float(limits.get("max_funding_8h_abs_pct", 0.08)):
        reasons.append("FUNDING_SPIKE")
        if severity != "block":
            severity = "hold"
            action = "hold"

    latency_ms = _float(_dig(payload, "order_latency_ms", "latency_ms"))
    if latency_ms is not None and latency_ms > float(limits.get("max_order_latency_ms", 750)):
        reasons.append("ORDER_LATENCY_EXCEEDED")
        if severity != "block":
            severity = "hold"
            action = "hold"

    slippage_bps = _float(_dig(payload, "slippage_bps", "expected_slippage_bps"))
    if slippage_bps is not None and abs(slippage_bps) > float(limits.get("max_slippage_bps", 12)):
        reasons.append("SLIPPAGE_BUDGET_EXCEEDED")
        if severity != "block":
            severity = "hold"
            action = "hold"

    gate_pass = not reasons and action != "block"
    if not gate_pass and action not in {"hold", "block"}:
        action = "hold"
    if not reasons:
        reasons = ["OK_PRETRADE_VALIDATION_ONLY"]

    return {
        "ok": True,
        "gate_pass": gate_pass,
        "advisory_only": bool(runtime.get("advisory_only", True)),
        "execution_enabled": bool(runtime.get("execution_enabled", False)),
        "os_final_approval_required": True,
        "zbot_authority": "recommend_only",
        "allowed_action": action,
        "reject_reasons": reasons,
        "missing_fields": missing,
        "severity": severity,
        "mode": mode,
        "decision_id": _decision_id(payload, action),
        "ts_ms": _now_ms(),
        "policy_id": policy.get("policy_id", "zops_gate_policy_v1"),
        "risk_limits": limits,
    }


class GateEnvelope(BaseModel):
    symbol: Optional[str] = None
    strategy: Optional[str] = None
    mode: Optional[str] = Field(default="shadow", description="paper|shadow|live")
    action: Optional[str] = None
    price: Optional[float] = None
    pos_pct: Optional[float] = None
    lev: Optional[float] = None
    entry_ts: Optional[Any] = None
    liq_buffer_pct: Optional[float] = None
    liq_price: Optional[float] = None
    funding_8h_pct: Optional[float] = None
    dd_day_pct: Optional[float] = None
    dd_total_pct: Optional[float] = None
    source: Optional[Any] = None
    os_approved: Optional[bool] = False


@router.get("/api/gate/health")
@router.get("/api/v1/gate/health")
def gate_health() -> Dict[str, Any]:
    policy = _load_policy()
    return {
        "ok": True,
        "component": "order_risk_gate_contract_v1",
        "policy_id": policy.get("policy_id"),
        "execution_enabled": bool((policy.get("runtime") or {}).get("execution_enabled", False)),
        "advisory_only": bool((policy.get("runtime") or {}).get("advisory_only", True)),
        "os_final_approval_required": True,
        "ts_ms": _now_ms(),
    }


@router.get("/api/gate/policy")
@router.get("/api/v1/gate/policy")
def gate_policy() -> Dict[str, Any]:
    return {"ok": True, "policy": _load_policy(), "ts_ms": _now_ms()}


@router.get("/api/gate/status")
@router.get("/api/v1/gate/status")
def gate_status() -> Dict[str, Any]:
    policy = _load_policy()
    runtime = policy.get("runtime", {}) or {}
    return {
        "ok": True,
        "component": "order_risk_gate_contract_v1",
        "phase": "v3.1_hardening_layer",
        "status": "sealed" if POLICY_PATH.exists() else "fallback",
        "mode": "advisory_only" if runtime.get("advisory_only", True) else "enforced",
        "execution_enabled": bool(runtime.get("execution_enabled", False)),
        "paper_allowed": bool(runtime.get("paper_allowed", True)),
        "shadow_allowed": bool(runtime.get("shadow_allowed", True)),
        "live_allowed_without_os_approve": bool(runtime.get("live_allowed_without_os_approve", False)),
        "os_final_approval_required": True,
        "zbot_authority": "recommend_only",
        "allowed_actions": policy.get("allowed_actions", sorted(_ALLOWED)),
        "policy_id": policy.get("policy_id", "zops_gate_policy_v1"),
        "ts_ms": _now_ms(),
    }


@router.post("/api/gate/pretrade")
@router.post("/api/v1/gate/pretrade")
def gate_pretrade(envelope: Dict[str, Any] = Body(default_factory=dict)) -> Dict[str, Any]:
    return _validate(envelope or {})


@router.post("/api/gate/risk")
@router.post("/api/v1/gate/risk")
def gate_risk(envelope: Dict[str, Any] = Body(default_factory=dict)) -> Dict[str, Any]:
    return _validate(envelope or {})


@router.post("/api/gate/ack")
@router.post("/api/v1/gate/ack")
def gate_ack(envelope: Dict[str, Any] = Body(default_factory=dict)) -> Dict[str, Any]:
    # Audit-only acknowledgement surface. It never approves live orders.
    return {
        "ok": True,
        "ack": True,
        "mutation": "none",
        "os_final_approval_required": True,
        "zbot_authority": "recommend_only",
        "received": envelope or {},
        "ts_ms": _now_ms(),
    }
