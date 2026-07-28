from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_STATE_FILE = Path(os.getenv("Z_STATE_FILE", str(BASE_DIR / "state.json")))
DB_CANDIDATES = [
    Path(os.getenv("Z_STATE_DB_PATH", str(BASE_DIR / "z_state.db"))),
    BASE_DIR / "state" / "z_state.db",
]
JSON_CANDIDATES = [
    DEFAULT_STATE_FILE,
    BASE_DIR / "state.json",
    BASE_DIR / "state" / "state.json",
    BASE_DIR / "state_data.json",
    BASE_DIR / "state" / "state_data.json",
]


DEFAULT_MARKET_STATE: Dict[str, Any] = {
    "contract_version": "market.state.v1",
    "regime": "trend",
    "mood": "calm",
    "trend_score": 0.82,
    "confirm_score": 0.64,
    "breakout_score": 0.58,
    "drawdown_score": 0.31,
    "consensus": "high",
    "intuition_score": 78.0,
    "venue_health": "strong",
    "decay_pct": 4.0,
    "dd_day_pct": 1.2,
    "dd_total_pct": 2.4,
    "liq_buffer_pct": 18.0,
    "funding_8h_pct": 0.01,
    "stale": False,
    "stale_ms": 0,
    "freeze_mode": False,
    "session_blocked": False,
    "shadow_preferred": False,
    "reconcile_status": "ok",
    "decision_id": None,
    "source": f"json:{DEFAULT_STATE_FILE}",
    "source_ts": None,
    "_source": f"json:{DEFAULT_STATE_FILE}",
    "_source_ts": None,
    "_raw": {},
}

_ALIAS_MAP = {
    "market_regime": "regime",
    "risk_decay_pct": "decay_pct",
    "funding_rate_8h": "funding_8h_pct",
    "funding": "funding_8h_pct",
    "liq_buffer": "liq_buffer_pct",
    "liq_buffer_percent": "liq_buffer_pct",
    "exchange_health": "venue_health",
    "venue_status": "venue_health",
    "dd_day": "dd_day_pct",
    "dd_total": "dd_total_pct",
}

_CONTAINER_KEYS = (
    "market_state",
    "state",
    "snapshot",
    "payload",
    "data",
    "context",
)

_NESTED_KEYS = (
    "market",
    "regime_state",
    "signals",
    "trade_context",
    "meta",
)


def _safe_dict(x: Any) -> Dict[str, Any]:
    return x if isinstance(x, dict) else {}


def _source_ts_from_path(path: Path) -> Optional[int]:
    try:
        return int(path.stat().st_mtime * 1000)
    except Exception:
        return None


def _read_json_file(path: Path) -> Dict[str, Any]:
    try:
        if not path.exists():
            return {}
        raw = path.read_text(encoding="utf-8").strip()
        if not raw:
            return {}
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _try_import_state_api() -> Dict[str, Any]:
    candidates = [
        ("state.z_state_manager", "get_state_for_api"),
        ("backend.state.z_state_manager", "get_state_for_api"),
    ]
    for module_name, attr_name in candidates:
        try:
            module = __import__(module_name, fromlist=[attr_name])
            fn = getattr(module, attr_name, None)
            if callable(fn):
                obj = fn()
                if isinstance(obj, dict):
                    return obj
        except Exception:
            continue
    return {}


def _try_import_manager_snapshot() -> Dict[str, Any]:
    candidates = [
        ("state.z_state_manager", "STATE_MANAGER"),
        ("backend.state.z_state_manager", "STATE_MANAGER"),
    ]
    for module_name, attr_name in candidates:
        try:
            module = __import__(module_name, fromlist=[attr_name])
            manager = getattr(module, attr_name, None)
            snap = getattr(manager, "snapshot", None)
            if callable(snap):
                obj = snap()
                if isinstance(obj, dict):
                    return obj
        except Exception:
            continue
    return {}


def _try_load_latest_db_snapshot() -> Dict[str, Any]:
    candidates = [
        ("state.z_state_db", "ZStateDB"),
        ("backend.state.z_state_db", "ZStateDB"),
    ]
    for module_name, attr_name in candidates:
        try:
            module = __import__(module_name, fromlist=[attr_name])
            db_cls = getattr(module, attr_name, None)
            if db_cls is None:
                continue
            for db_path in DB_CANDIDATES:
                if not db_path.exists():
                    continue
                db = db_cls(str(db_path))
                loader = getattr(db, "load_latest", None)
                if not callable(loader):
                    continue
                snap = loader()
                if snap is None:
                    continue
                if hasattr(snap, "payload"):
                    payload = getattr(snap, "payload", None)
                    if isinstance(payload, dict):
                        return {"payload": payload, "source": f"db:{db_path}", "source_ts": _source_ts_from_path(db_path)}
                if isinstance(snap, dict):
                    enriched = dict(snap)
                    enriched.setdefault("source", f"db:{db_path}")
                    enriched.setdefault("source_ts", _source_ts_from_path(db_path))
                    return enriched
        except Exception:
            continue
    return {}


def _first_nonempty_with_source(items: Iterable[Tuple[Dict[str, Any], str, Optional[int]]]) -> Tuple[Dict[str, Any], str, Optional[int]]:
    for item, source, source_ts in items:
        if isinstance(item, dict) and item:
            return item, source, source_ts
    return {}, DEFAULT_MARKET_STATE["source"], DEFAULT_MARKET_STATE["source_ts"]


def _unwrap_containers(obj: Dict[str, Any]) -> Dict[str, Any]:
    cur = _safe_dict(obj)
    seen = set()

    while cur and id(cur) not in seen:
        seen.add(id(cur))

        moved = False
        for key in _CONTAINER_KEYS:
            nxt = cur.get(key)
            if isinstance(nxt, dict) and nxt:
                cur = nxt
                moved = True
                break
        if moved:
            continue

        for key in _NESTED_KEYS:
            nxt = cur.get(key)
            if isinstance(nxt, dict) and nxt:
                merged = dict(cur)
                merged.update(nxt)
                cur = merged
                moved = True
                break
        if not moved:
            break

    return cur


def _normalize_market_state(raw: Dict[str, Any], fallback_source: str, fallback_source_ts: Optional[int]) -> Dict[str, Any]:
    src_top = _safe_dict(raw)
    src = _unwrap_containers(src_top)
    out = dict(DEFAULT_MARKET_STATE)

    for key in list(out.keys()):
        if key in {"contract_version", "source", "source_ts", "_source", "_source_ts", "_raw"}:
            continue
        if key in src and src[key] is not None:
            out[key] = src[key]
        elif key in src_top and src_top[key] is not None:
            out[key] = src_top[key]

    for src_key, dst_key in _ALIAS_MAP.items():
        if src_key in src and src[src_key] is not None:
            out[dst_key] = src[src_key]
        elif src_key in src_top and src_top[src_key] is not None:
            out[dst_key] = src_top[src_key]

    if "freeze" in src and isinstance(src["freeze"], bool):
        out["freeze_mode"] = src["freeze"]
    elif "freeze" in src_top and isinstance(src_top["freeze"], bool):
        out["freeze_mode"] = src_top["freeze"]

    stale_ms = src.get("stale_ms", src_top.get("stale_ms", 0))
    try:
        stale_ms = int(float(stale_ms or 0))
    except Exception:
        stale_ms = 0
    out["stale_ms"] = stale_ms

    stale = src.get("stale", src_top.get("stale"))
    if stale is None:
        out["stale"] = stale_ms > 0
    else:
        out["stale"] = bool(stale)

    out["contract_version"] = (
        src.get("contract_version")
        or src_top.get("contract_version")
        or DEFAULT_MARKET_STATE["contract_version"]
    )
    out["reconcile_status"] = (
        src.get("reconcile_status")
        or src_top.get("reconcile_status")
        or DEFAULT_MARKET_STATE["reconcile_status"]
    )
    out["decision_id"] = src.get("decision_id", src_top.get("decision_id"))

    source = (
        src.get("source")
        or src_top.get("source")
        or src.get("_source")
        or src_top.get("_source")
        or fallback_source
    )
    source_ts = (
        src.get("source_ts")
        if src.get("source_ts") is not None
        else src_top.get("source_ts")
    )
    if source_ts is None:
        source_ts = src.get("_source_ts")
    if source_ts is None:
        source_ts = src_top.get("_source_ts")
    if source_ts is None:
        source_ts = fallback_source_ts

    out["source"] = source
    out["source_ts"] = source_ts
    out["_source"] = src.get("_source") or src_top.get("_source") or source
    out["_source_ts"] = src.get("_source_ts") or src_top.get("_source_ts") or source_ts
    out["_raw"] = src_top

    return out


def read_state_snapshot() -> Dict[str, Any]:
    data, source, source_ts = _first_nonempty_with_source(
        [
            (_try_import_state_api(), "runtime:state_api", None),
            (_try_import_manager_snapshot(), "runtime:state_manager", None),
            (_try_load_latest_db_snapshot(), f"db:{DB_CANDIDATES[0]}", _source_ts_from_path(DB_CANDIDATES[0])),
            *(
                (_read_json_file(path), f"json:{path}", _source_ts_from_path(path))
                for path in JSON_CANDIDATES
            ),
        ]
    )

    if not data:
        out = dict(DEFAULT_MARKET_STATE)
        out["_raw"] = {}
        return out

    out = _safe_dict(data)
    out.setdefault("contract_version", DEFAULT_MARKET_STATE["contract_version"])
    out.setdefault("reconcile_status", DEFAULT_MARKET_STATE["reconcile_status"])
    out.setdefault("source", out.get("_source") or source)
    out.setdefault("source_ts", out.get("_source_ts") or source_ts)
    out.setdefault("_source", out.get("source"))
    out.setdefault("_source_ts", out.get("source_ts"))
    out.setdefault("_raw", data)
    return out


def read_market_state() -> Dict[str, Any]:
    raw = read_state_snapshot()
    if not raw:
        return dict(DEFAULT_MARKET_STATE)

    fallback_source = raw.get("source") or raw.get("_source") or DEFAULT_MARKET_STATE["source"]
    fallback_source_ts = raw.get("source_ts")
    if fallback_source_ts is None:
        fallback_source_ts = raw.get("_source_ts")

    return _normalize_market_state(raw, fallback_source, fallback_source_ts)


def read_current_state() -> Dict[str, Any]:
    return read_market_state()


__all__ = ["read_state_snapshot", "read_market_state", "read_current_state"]
