from __future__ import annotations

import json
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter

router = APIRouter(prefix="/api/lico", tags=["lico"])

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
CONTRACT_PATH = BASE_DIR / "contracts" / "ZOS_LICO_CONTRACT_v1.json"
SOURCES_PATH = DATA_DIR / "lico_sources.json"
SNAPSHOT_PATH = DATA_DIR / "lico_snapshot.json"

CACHE_TTL_SEC = 60
SOURCE_TIMEOUT_SEC = 2.5
_cache: Dict[str, Any] = {"ts": 0.0, "payload": None}


def _now_ms() -> int:
    return int(time.time() * 1000)


def _load_json(path: Path, fallback: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback
    return fallback


def _default_contract() -> Dict[str, Any]:
    return {
        "contract": "ZOS_LICO_CONTRACT_v1",
        "component": "LICO",
        "role": "risk_intel_readonly",
        "authority": "advisory_only",
        "autotrade_effect": "none",
        "allowed_actions": ["read", "summarize", "classify", "notify", "inspect"],
        "blocked_actions": [
            "place_order", "cancel_order", "modify_order", "route_order", "change_position",
            "change_leverage", "set_stop", "promote_strategy", "override_guard"
        ],
        "guardrails": {
            "read_only_api": True,
            "get_only_routes": True,
            "no_app_side_execution": True,
            "no_bot_decision_authority": True,
            "source_required": True,
            "stale_policy": "flag_and_hold_context_only",
        },
    }


def _default_sources() -> Dict[str, Any]:
    return {
        "registry": "LICO_SOURCE_REGISTRY_v2_LIVE_SEAL",
        "mode": "official_sources_first_readonly_probe",
        "sources": [],
    }


def _source_probe(src: Dict[str, Any]) -> Dict[str, Any]:
    url = str(src.get("url") or "")
    start = time.time()
    status = "offline"
    http_status = None
    reason = "not_checked"
    if not url.startswith(("https://", "http://")):
        elapsed = int((time.time() - start) * 1000)
        return {**src, "live_status": "invalid", "http_status": None, "elapsed_ms": elapsed, "reason": "invalid_url", "checked_at_ms": _now_ms()}

    headers = {
        "User-Agent": "ZOS-LICO-ReadOnlyProbe/1.0",
        "Accept": "application/json,text/html,*/*;q=0.8",
        "Cache-Control": "no-cache",
    }
    req = urllib.request.Request(url, headers=headers, method="GET")
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=SOURCE_TIMEOUT_SEC, context=ctx) as resp:
            http_status = int(getattr(resp, "status", 0) or 0)
            # Read a tiny chunk only. This is reachability/seal proof, not ingestion.
            try:
                resp.read(256)
            except Exception:
                pass
            if 200 <= http_status < 400:
                status = "live"
                reason = "ok"
            elif http_status in (401, 403, 429):
                status = "blocked"
                reason = f"http_{http_status}"
            else:
                status = "degraded"
                reason = f"http_{http_status}"
    except urllib.error.HTTPError as exc:
        http_status = int(getattr(exc, "code", 0) or 0)
        if http_status in (401, 403, 429):
            status = "blocked"
        else:
            status = "degraded"
        reason = f"http_{http_status}"
    except Exception as exc:
        status = "offline"
        reason = exc.__class__.__name__

    elapsed = int((time.time() - start) * 1000)
    return {
        **src,
        "live_status": status,
        "http_status": http_status,
        "elapsed_ms": elapsed,
        "reason": reason,
        "checked_at_ms": _now_ms(),
    }


def _contract() -> Dict[str, Any]:
    c = _load_json(CONTRACT_PATH, _default_contract())
    c.setdefault("authority", "advisory_only")
    c.setdefault("autotrade_effect", "none")
    return c


def _sources_registry() -> Dict[str, Any]:
    reg = _load_json(SOURCES_PATH, _default_sources())
    if not isinstance(reg, dict):
        return _default_sources()
    if not isinstance(reg.get("sources"), list):
        reg["sources"] = []
    return reg


def _live_payload(force: bool = False) -> Dict[str, Any]:
    now = time.time()
    if (not force) and _cache.get("payload") and (now - float(_cache.get("ts") or 0.0) < CACHE_TTL_SEC):
        return _cache["payload"]

    registry = _sources_registry()
    raw_sources: List[Dict[str, Any]] = [s for s in registry.get("sources", []) if isinstance(s, dict)]
    checked = [_source_probe(s) for s in raw_sources]
    total = len(checked)
    live = sum(1 for s in checked if s.get("live_status") == "live")
    blocked = sum(1 for s in checked if s.get("live_status") == "blocked")
    degraded = sum(1 for s in checked if s.get("live_status") == "degraded")
    offline = sum(1 for s in checked if s.get("live_status") == "offline")
    invalid = sum(1 for s in checked if s.get("live_status") == "invalid")
    official = sum(1 for s in checked if s.get("authority") == "official")
    exchange_api = sum(1 for s in checked if s.get("authority") == "exchange_api")
    # Keep fail-safe: Lico remains sealed/read-only even if all sources are unreachable.
    payload = {
        "component": "LICO",
        "phase": "4B_live_source_seal",
        "registry": registry.get("registry", "LICO_SOURCE_REGISTRY_v2_LIVE_SEAL"),
        "mode": registry.get("mode", "official_sources_first_readonly_probe"),
        "ts_ms": _now_ms(),
        "cache_ttl_sec": CACHE_TTL_SEC,
        "source_count": total,
        "live_sources": live,
        "blocked_sources": blocked,
        "degraded_sources": degraded,
        "offline_sources": offline,
        "invalid_sources": invalid,
        "official_sources": official,
        "exchange_api_sources": exchange_api,
        "live_ok": total > 0 and live > 0,
        "source_seal": "sealed" if total > 0 and live > 0 else "unsealed",
        "read_only": True,
        "orders_enabled": False,
        "mutation_enabled": False,
        "authority": "advisory_only",
        "autotrade_effect": "none",
        "sources": checked,
    }
    _cache["ts"] = now
    _cache["payload"] = payload
    return payload


def _snapshot_from_live(live: Dict[str, Any]) -> Dict[str, Any]:
    snapshot = _load_json(SNAPSHOT_PATH, {})
    if not isinstance(snapshot, dict):
        snapshot = {}
    source_count = int(live.get("source_count") or 0)
    live_sources = int(live.get("live_sources") or 0)
    live_ok = bool(live.get("live_ok"))
    severity = "clear" if live_ok else "watch"
    headline = "Lico live source seal active" if live_ok else "Lico source seal needs verification"
    drivers = [
        f"source_seal={live.get('source_seal')}",
        f"live_sources={live_sources}/{source_count}",
        "read_only=true",
        "orders=blocked",
        "mutation=blocked",
    ]
    return {
        **snapshot,
        "headline": headline,
        "severity": severity,
        "impact_score": 0,
        "drivers": drivers,
        "next_action": "hold",
        "market_effect": "context_only",
        "summary_ko": "LICO는 실시간 출처 연결성만 검증하며 주문·전략 권한은 없다.",
        "source_seal": live.get("source_seal"),
        "source_count": source_count,
        "live_sources": live_sources,
        "sources": [s.get("id") for s in live.get("sources", []) if s.get("id")],
        "ts_ms": live.get("ts_ms"),
    }


@router.get("/health")
def lico_health() -> Dict[str, Any]:
    contract = _contract()
    live = _live_payload(False)
    return {
        "status": "ok" if live.get("live_ok") else "watch",
        "component": "LICO",
        "phase": live.get("phase"),
        "authority": contract.get("authority", "advisory_only"),
        "autotrade_effect": contract.get("autotrade_effect", "none"),
        "read_only": True,
        "orders_enabled": False,
        "mutation_enabled": False,
        "complete_ok": True,
        "source_count": live.get("source_count", 0),
        "live_sources": live.get("live_sources", 0),
        "source_seal": live.get("source_seal"),
        "live_ok": live.get("live_ok"),
        "ts_ms": _now_ms(),
    }


@router.get("/sources")
def lico_sources() -> Dict[str, Any]:
    return _live_payload(False)


@router.get("/live")
def lico_live() -> Dict[str, Any]:
    return _live_payload(False)


@router.get("/snapshot")
def lico_snapshot() -> Dict[str, Any]:
    live = _live_payload(False)
    return _snapshot_from_live(live)


@router.get("/guard")
def lico_guard() -> Dict[str, Any]:
    live = _live_payload(False)
    return {
        "component": "LICO",
        "allowed_action": "hold",
        "authority": "advisory_only",
        "read_only": True,
        "orders_enabled": False,
        "mutation_enabled": False,
        "autotrade_effect": "none",
        "source_seal": live.get("source_seal"),
        "live_sources": live.get("live_sources", 0),
        "source_count": live.get("source_count", 0),
        "message": "LICO can only inspect and explain source context. It cannot submit, route, modify, or cancel orders.",
        "ts_ms": _now_ms(),
    }
