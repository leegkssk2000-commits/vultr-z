from __future__ import annotations

import os
import time
from typing import Any, Dict

from fastapi import APIRouter, Body, Request

router = APIRouter(tags=["alimi"])

STARTED_AT = time.time()

ALLOWED_ACTIONS = ["reduce25", "partial30", "hold", "stop", "route_change", "rollback", "block"]


def _tv_symbol() -> str:
    return os.environ.get("ALIMI_TV_SYMBOL", "BINANCE:BTCUSDT").strip() or "BINANCE:BTCUSDT"


def _tv_url() -> str:
    configured = os.environ.get("ALIMI_TV_URL", "").strip()
    if configured:
        return configured
    return f"https://www.tradingview.com/chart/?symbol={_tv_symbol()}"


def _status() -> Dict[str, Any]:
    now = time.time()
    return {
        "ok": True,
        "service": "alimi",
        "phase": "phase-5B_alimi_message_contract",
        "ts": now,
        "uptime_sec": round(now - STARTED_AT, 3),
        "authority": "advisory_only",
        "route": "Zbot/Lico sealed envelope -> Alimi external notify bridge",
        "bundle_key": "symbol/strategy",
        "bundle_window_min": int(os.environ.get("ALIMI_BUNDLE_WINDOW_MIN", "10")),
        "quiet_hours": {
            "start": os.environ.get("ALIMI_QUIET_START", "01:00"),
            "end": os.environ.get("ALIMI_QUIET_END", "07:00"),
            "tz": os.environ.get("ALIMI_QUIET_TZ", "Europe/Berlin"),
            "critical_bypass": True,
        },
        "policy": {
            "notify_mode": "violation_only",
            "order_mutation": "blocked",
            "source_required": ["cf:/", "sheets:", "lico_seal"],
            "allowed_actions": ALLOWED_ACTIONS,
        },
        "current": {
            "state": "idle",
            "violation": False,
            "sev": "m",
            "action": "hold",
            "symbol": os.environ.get("ALIMI_SYMBOL", "BTCUSDT"),
            "strategy": os.environ.get("ALIMI_STRATEGY", "alpha1"),
            "metric": "no violation banner required",
            "source": "alimi:backend_status",
        },
        "tradingview": {
            "enabled": True,
            "mode": "view_only",
            "symbol": _tv_symbol(),
            "url": _tv_url(),
        },
        "autotrade_effect": "none",
    }


@router.get("/api/alimi/health", include_in_schema=False)
@router.get("/api/v1/alimi/health", include_in_schema=False)
def alimi_health() -> Dict[str, Any]:
    return {"ok": True, "status": "ok", "service": "alimi", "phase": "phase-5B_alimi_message_contract", "ts": time.time()}


@router.get("/api/alimi/status", include_in_schema=False)
@router.get("/api/v1/alimi/status", include_in_schema=False)
def alimi_status() -> Dict[str, Any]:
    return _status()


@router.get("/api/alimi/bundle", include_in_schema=False)
@router.get("/api/v1/alimi/bundle", include_in_schema=False)
def alimi_bundle() -> Dict[str, Any]:
    st = _status()
    return {
        "ok": True,
        "bundle_key": st["bundle_key"],
        "bundle_window_min": st["bundle_window_min"],
        "policy": "one message per symbol/strategy window unless severity escalates or action changes",
        "autotrade_effect": "none",
    }


@router.get("/api/alimi/outbox", include_in_schema=False)
@router.get("/api/v1/alimi/outbox", include_in_schema=False)
def alimi_outbox() -> Dict[str, Any]:
    st = _status()
    cur = st["current"]
    preview = f"ALERT:{cur['symbol']}/{cur['strategy']}|{cur['metric']}|{cur['action']}|sev={cur['sev']}|src={cur['source']}"
    return {"ok": True, "pending": 0, "mode": "violation_only", "preview": preview, "autotrade_effect": "none"}


@router.get("/api/alimi/tv-link", include_in_schema=False)
@router.get("/api/v1/alimi/tv-link", include_in_schema=False)
def alimi_tv_link() -> Dict[str, Any]:
    return {"ok": True, "mode": "view_only", "symbol": _tv_symbol(), "url": _tv_url(), "autotrade_effect": "none"}


@router.post("/api/alimi/ack", include_in_schema=False)
@router.post("/api/v1/alimi/ack", include_in_schema=False)
def alimi_ack(payload: Dict[str, Any] = Body(default_factory=dict)) -> Dict[str, Any]:
    return {"ok": True, "accepted": True, "kind": "ack", "payload": payload, "autotrade_effect": "none"}


@router.post("/api/alimi/suppress", include_in_schema=False)
@router.post("/api/v1/alimi/suppress", include_in_schema=False)
def alimi_suppress(payload: Dict[str, Any] = Body(default_factory=dict)) -> Dict[str, Any]:
    return {"ok": True, "accepted": True, "kind": "suppress", "payload": payload, "autotrade_effect": "none"}

# --- ZOPS_ALIMI_DOMAIN_GATE_V1_START ---
def _domain_status(host: str = "") -> Dict[str, Any]:
    domain = os.environ.get("ALIMI_PUBLIC_DOMAIN", "alimi.z-os.vip").strip() or "alimi.z-os.vip"
    return {
        "ok": True,
        "service": "alimi",
        "phase": "phase-5C_alimi_domain_gate",
        "domain": domain,
        "host": host,
        "target": os.environ.get("ALIMI_STATIC_ROOT", "/var/www/z-os-app"),
        "backend": os.environ.get("ALIMI_BACKEND_UPSTREAM", "127.0.0.1:8000"),
        "mode": "external_notify_bridge",
        "authority": "advisory_only",
        "notify_mode": "violation_only",
        "order_mutation": "blocked",
        "autotrade_effect": "none",
        "endpoints": ["/api/alimi/health", "/api/alimi/status", "/api/alimi/outbox", "/api/alimi/domain", "/api/alimi/replay"],
        "routes": {"api": "/api/alimi/*", "app": "SPA fallback to index.html"},
        "ts": time.time(),
    }


@router.get("/api/alimi/domain", include_in_schema=False)
@router.get("/api/v1/alimi/domain", include_in_schema=False)
def alimi_domain(request: Request) -> Dict[str, Any]:
    return _domain_status(request.headers.get("host", ""))
# --- ZOPS_ALIMI_DOMAIN_GATE_V1_END ---

# --- ZOPS_ALIMI_REPLAY_TRACKER_V1_START ---
def _replay_status() -> Dict[str, Any]:
    st = _status()
    tv = st.get("tradingview", {})
    return {
        "ok": True,
        "service": "alimi",
        "phase": "phase-5C_alimi_tradingview_replay_tracker",
        "mode": "view_only_replay",
        "symbol": tv.get("symbol") or _tv_symbol(),
        "url": tv.get("url") or _tv_url(),
        "source": "alimi:tradingview_replay_anchor",
        "zlice": "replay_ready",
        "window_min": int(st.get("bundle_window_min") or 10),
        "authority": "advisory_only",
        "order_mutation": "blocked",
        "autotrade_effect": "none",
        "notes": ["TradingView context only", "Z-OS keeps signal authority", "no order path"],
        "ts": time.time(),
    }


@router.get("/api/alimi/replay", include_in_schema=False)
@router.get("/api/v1/alimi/replay", include_in_schema=False)
def alimi_replay() -> Dict[str, Any]:
    return _replay_status()
# --- ZOPS_ALIMI_REPLAY_TRACKER_V1_END ---
