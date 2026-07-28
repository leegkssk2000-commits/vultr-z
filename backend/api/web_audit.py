from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import APIRouter

router = APIRouter(prefix="/api/web", tags=["web-audit"])

ALLOWED_ACTIONS = ["reduce25", "partial30", "hold", "stop", "route_change", "rollback", "block"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _snapshot() -> Dict[str, Any]:
    symbol = "BTCUSDT"
    strategy = "alpha1"
    return {
        "ok": True,
        "service": "web-audit",
        "phase": "phase-6A_web_audit_replay",
        "ts": _now(),
        "uptime_sec": 0,
        "authority": "read_only",
        "mode": "view_only",
        "mutation": "blocked",
        "order_mutation": "blocked",
        "source_required": ["cf:/", "sheets:/"],
        "allowed_actions": ALLOWED_ACTIONS,
        "current": {
            "state": "idle",
            "violation": False,
            "sev": "m",
            "action": "hold",
            "symbol": symbol,
            "strategy": strategy,
            "metric": "no violation banner required",
        },
        "tradingview": {
            "enabled": True,
            "mode": "view_only",
            "symbol": "BINANCE:BTCUSDT",
            "url": "https://www.tradingview.com/chart/?symbol=BINANCE:BTCUSDT",
        },
        "replay": [
            {"t": "T-04", "lane": "source", "state": "sealed", "note": "CF/GS source gate only"},
            {"t": "T-03", "lane": "proof", "state": "verified", "note": "receipt + lineage before action"},
            {"t": "T-02", "lane": "lico", "state": "read_only", "note": "live source seal active"},
            {"t": "T-01", "lane": "alimi", "state": "silent", "note": "violation-only external notification"},
            {"t": "T+00", "lane": "web", "state": "view_only", "note": "TradingView/result viewer only"},
        ],
        "links": {
            "health": "/api/web/health",
            "status": "/api/web/status",
            "replay": "/api/web/replay",
            "tradingview": "https://www.tradingview.com/chart/?symbol=BINANCE:BTCUSDT",
        },
        "autotrade_effect": "none",
    }


@router.get("/health")
def health() -> Dict[str, Any]:
    data = _snapshot()
    return {"ok": True, "service": data["service"], "phase": data["phase"], "ts": data["ts"], "authority": data["authority"], "mutation": data["mutation"]}


@router.get("/status")
def status() -> Dict[str, Any]:
    return _snapshot()


@router.get("/replay")
def replay() -> Dict[str, Any]:
    data = _snapshot()
    return {"ok": True, "phase": data["phase"], "ts": data["ts"], "items": data["replay"], "current": data["current"]}


@router.post("/ack")
def ack(payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
    data = _snapshot()
    return {
        "ok": True,
        "accepted": True,
        "effect": "ack_only",
        "order_mutation": "blocked",
        "payload_seen": bool(payload),
        "current": data["current"],
        "ts": data["ts"],
    }
