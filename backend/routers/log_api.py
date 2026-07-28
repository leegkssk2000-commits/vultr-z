from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query
from backend.contracts.change15a5_models import LogReplayResponse, LOG_REPLAY_EXAMPLE

try:
    from backend.engine.state_log_determinism import normalize_log_row, normalize_log_rows
except Exception:
    from engine.state_log_determinism import normalize_log_row, normalize_log_rows
try:
    from backend.contracts.policy_resolver_ssot import resolve_policy_ssot
except Exception:
    from contracts.policy_resolver_ssot import resolve_policy_ssot

router = APIRouter(prefix="/api/log", tags=["log"])

BASE_DIR = Path(os.getenv("Z_BACKEND_BASE_DIR", "/home/z/z/backend"))
LOG_DIR = Path(os.getenv("Z_BOT_DIFF_DIR", str(BASE_DIR / "logs" / "bot_diff")))
JOURNAL_DIR = Path(os.getenv("Z_JOURNAL_DIR", str(BASE_DIR / "data" / "journal")))
STATE_DIR = Path(os.getenv("Z_STATE_DATA_DIR", str(BASE_DIR / "data" / "state")))
TRADE_STATE_PATH = Path(os.getenv("Z_TRADE_STATE_PATH", str(BASE_DIR / "trade_state.json")))


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        if v is None or v == "":
            return default
        return int(float(v))
    except Exception:
        return default


def _safe_str(v: Any, default: str = "") -> str:
    if v is None:
        return default
    try:
        s = str(v).strip()
        return s if s else default
    except Exception:
        return default


def _read_json(path: Path) -> Dict[str, Any]:
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


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    try:
        if not path.exists():
            return out
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict):
                        out.append(obj)
                except Exception:
                    continue
    except Exception:
        return out
    return out


def _trade_state() -> Dict[str, Any]:
    obj = _read_json(TRADE_STATE_PATH)
    return obj if isinstance(obj, dict) else {}


def _source_ts(path: Path) -> Optional[int]:
    try:
        return int(path.stat().st_mtime * 1000)
    except Exception:
        return None


def _journal_files() -> List[Path]:
    files: List[Path] = []
    if JOURNAL_DIR.exists():
        for pat in ("lbot_event.latest.json", "lbot_event.*.jsonl", "lbot_events.*.jsonl", "lbot_events_*.jsonl"):
            files.extend(sorted(JOURNAL_DIR.glob(pat)))
    seen = []
    out: List[Path] = []
    for p in files:
        key = str(p.resolve())
        if key not in seen:
            seen.append(key)
            out.append(p)
    return out


def _normalize_journal_event(row: Dict[str, Any], source_file: Path) -> Dict[str, Any]:
    event = row.get("journal_event") if isinstance(row.get("journal_event"), dict) else row
    decision_id = _safe_str(event.get("decision_id") or row.get("decision_id") or row.get("event_id"))
    incident_id = _safe_str(event.get("incident_id") or row.get("incident_id"))
    source_ts = _source_ts(source_file) or 0
    ts = _safe_int(
        event.get("written_at")
        or event.get("ts")
        or row.get("updated_at")
        or row.get("processed_at")
        or source_ts
        or 0
    )
    normalized = {
        "event": _safe_str(event.get("event_type"), "journal_event"),
        "reason": event.get("decision_reason") or row.get("result_reason"),
        "reason_code": None,
        "replay": {
            "decision_id": decision_id or None,
            "scope": event.get("scope"),
            "bot_name": event.get("bot_name"),
        },
        "incident": {
            "incident_id": incident_id or None,
            "warning_count_delta": None,
        },
        "source": str(source_file),
        "source_file": str(source_file),
        "decision_id": decision_id or None,
        "event_id": event.get("event_id") or row.get("event_id") or incident_id or None,
        "signal_id": event.get("signal_id") or row.get("signal_id"),
        "ts": ts,
        "source_ts": source_ts,
        "team_name": event.get("team_name"),
        "scope": event.get("scope"),
        "bot_name": event.get("bot_name"),
        "summary": {
            "strategy": event.get("strategy") or row.get("strategy"),
            "symbol": event.get("symbol") or row.get("symbol"),
            "decision_action": event.get("decision_action"),
            "executor_result": event.get("executor_result") or row.get("result_reason"),
            "status": event.get("status"),
        },
    }
    return normalize_log_row(normalized, source=f"journal:{source_file.name}")


def _timeline_items(limit: int = 50) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []

    for path in _journal_files():
        if path.suffix == ".json":
            row = _read_json(path)
            if row:
                items.append(_normalize_journal_event(row, path))
        else:
            for row in _read_jsonl(path)[-200:]:
                items.append(_normalize_journal_event(row, path))

    for name in ("seen_event_ids.json", "sync_state.json", "equity.latest.json", "seen_signal_ids.json"):
        path = STATE_DIR / name
        if path.exists():
            items.append(normalize_log_row({
                "event": "state_update",
                "reason": None,
                "reason_code": None,
                "replay": {"decision_id": None, "scope": None, "bot_name": None},
                "incident": {"incident_id": None, "warning_count_delta": None},
                "source": str(path),
                "source_file": str(path),
                "decision_id": None,
                "event_id": name,
                "ts": _source_ts(path) or 0,
                "source_ts": _source_ts(path) or 0,
                "team_name": None,
                "scope": None,
                "bot_name": None,
                "summary": {},
            }, source=f"state:{name}"))

    items = normalize_log_rows(items, source="log_timeline", reverse=True)
    return items[: max(1, min(limit, 200))]


def _ledger_items(limit: int = 50) -> List[Dict[str, Any]]:
    state = _trade_state()
    items = state.get("recent_trades")
    if not isinstance(items, list):
        items = []
    out: List[Dict[str, Any]] = []
    for row in items[: max(1, min(limit, 200))]:
        if not isinstance(row, dict):
            continue
        out.append(normalize_log_row({
            "decision_id": row.get("decision_id"),
            "signal_id": row.get("signal_id"),
            "event_id": row.get("event_id"),
            "symbol": row.get("symbol"),
            "side": row.get("side"),
            "strategy": row.get("strategy"),
            "route": row.get("route"),
            "mode": row.get("mode"),
            "price": row.get("price"),
            "qty": row.get("qty"),
            "pnl": row.get("pnl"),
            "fee": row.get("fee"),
            "note": row.get("reason"),
            "source": f"json:{TRADE_STATE_PATH}",
            "source_ts": state.get("source_ts"),
            "reconcile_status": state.get("reconcile_status", "ok"),
            "ts": row.get("ts"),
        }, source="trade_ledger"))
    return normalize_log_rows(out, source="trade_ledger", reverse=True)


def _replay_items(decision_id: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []

    for path in _journal_files():
        rows: List[Dict[str, Any]]
        if path.suffix == ".json":
            row = _read_json(path)
            rows = [row] if row else []
        else:
            rows = _read_jsonl(path)
        for row in rows:
            normalized = _normalize_journal_event(row, path)
            if _safe_str(normalized.get("decision_id")) == decision_id:
                out.append(normalized)

    state = _trade_state()
    state_ts = state.get("source_ts")
    for key, event_name in (("signals", "trade_signal"), ("recent_trades", "trade_recent")):
        rows = state.get(key)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            if _safe_str(row.get("decision_id")) != decision_id:
                continue
            out.append(normalize_log_row({
                "event": event_name,
                "reason": row.get("reason"),
                "reason_code": None,
                "replay": {
                    "decision_id": row.get("decision_id"),
                    "scope": "trade_state",
                    "bot_name": None,
                },
                "incident": {
                    "incident_id": None,
                    "warning_count_delta": None,
                },
                "source": f"json:{TRADE_STATE_PATH}",
                "source_file": str(TRADE_STATE_PATH),
                "decision_id": row.get("decision_id"),
                "event_id": row.get("event_id") or row.get("signal_id") or event_name,
                "signal_id": row.get("signal_id"),
                "ts": row.get("ts"),
                "team_name": None,
                "scope": "trade_state",
                "bot_name": None,
                "summary": {
                    "strategy": row.get("strategy"),
                    "symbol": row.get("symbol"),
                    "decision_action": row.get("decision_action"),
                    "executor_result": row.get("executor_result"),
                    "status": row.get("status"),
                    "route": row.get("route"),
                    "mode": row.get("mode"),
                },
                "source_ts": state_ts,
            }, source=f"replay:{event_name}"))

    return normalize_log_rows(out, source="log_replay", reverse=True)


def _normalized_freshness(source: str, source_ts: Any) -> Dict[str, Any]:
    ts = _safe_int(source_ts, 0)
    return {
        "source": source,
        "source_raw": source,
        "source_ts": ts,
        "source_ts_epoch_ms": ts,
        "source_ts_iso": None,
        "normalized": bool(source),
        "stale": False,
        "stale_ms": 0,
        "verification_status": "ready",
    }


def _replay_envelope(decision_id: str, state: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    source = payload.get("source") or f"json:{TRADE_STATE_PATH}"
    freshness = _normalized_freshness(str(source), state.get("source_ts"))
    return {
        "backend_ver": payload.get("backend_ver") or "14.5.7b.v1",
        "freshness": freshness,
        "change_digest": {
            "source": "log_replay",
            "decision_id": decision_id,
        },
        "ack": {
            "scope": "decision_id",
            "ttl_s": 600,
            "key": decision_id,
            "status": "ready",
        },
        "contracts": {
            "schema": "15B",
            "ingestion_converged_ver": "15B.1",
        },
        **payload,
    }


def _collection_envelope(contract_version: str, source: str, source_ts: Any, count: int, items: List[Dict[str, Any]], *, key: str, change_source: str, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    freshness = _normalized_freshness(source, source_ts)
    payload: Dict[str, Any] = {
        "contract_version": contract_version,
        "source": source,
        "source_ts": freshness["source_ts"],
        "freshness": freshness,
        "stale": freshness["stale"],
        "stale_ms": freshness["stale_ms"],
        "verification_status": freshness["verification_status"],
        "change_digest": {
            "source": change_source,
            "key": key,
        },
        "ack": {
            "scope": "collection",
            "ttl_s": 600,
            "key": key,
            "status": "ready",
        },
        "contracts": {
            "schema": "15B",
            "ingestion_converged_ver": "15B.1",
        },
        "count": count,
        "items": items,
    }
    if extra:
        payload.update(extra)
    return payload


@router.get("/timeline")
def log_timeline(limit: int = Query(default=50, ge=1, le=200)):
    items = _timeline_items(limit=limit)
    latest_ts = items[0]["ts"] if items else 0
    source = f"json:{TRADE_STATE_PATH}"
    return _collection_envelope(
        "log.timeline.v4",
        source,
        latest_ts,
        len(items),
        items,
        key="timeline",
        change_source="log_timeline",
        extra={
            "reconcile_status": "ok",
        },
    )


@router.get("/ledger")
def log_ledger(limit: int = Query(default=50, ge=1, le=200)):
    items = _ledger_items(limit=limit)
    state = _trade_state()
    source = f"json:{TRADE_STATE_PATH}"
    return _collection_envelope(
        "log.ledger.v3",
        source,
        state.get("source_ts"),
        len(items),
        items,
        key="ledger",
        change_source="log_ledger",
        extra={
            "reconcile_status": state.get("reconcile_status", "ok"),
        },
    )


@router.get("/replay/{decision_id}", response_model=LogReplayResponse, openapi_extra={"examples": [LOG_REPLAY_EXAMPLE]})
def log_replay(decision_id: str):
    items = _replay_items(decision_id)
    state = _trade_state()
    replay_anchor = items[0].get("replay_anchor") if items else None
    first_summary = items[0].get("summary") if items and isinstance(items[0].get("summary"), dict) else {}
    policy_resolution = resolve_policy_ssot({
        "strategy": first_summary.get("strategy") or state.get("strategy") or "btc_trend_v1",
        "profile": state.get("mode") or state.get("profile") or "default",
        "subtype": first_summary.get("subtype") or state.get("subtype") or "default",
        "venue_health": first_summary.get("route") or state.get("reconcile_status") or "",
        "stale": False,
        "feature_flags": [],
    })
    payload = {
        "contract_version": "log.replay.v4",
        "decision_id": decision_id,
        "source": f"json:{TRADE_STATE_PATH}",
        "source_ts": state.get("source_ts"),
        "replay_anchor": replay_anchor,
        "count": len(items),
        "items": items,
        "snapshot_ref": f"json:{TRADE_STATE_PATH}",
        "reason_code": policy_resolution.get("reason_code"),
        "policy_source": policy_resolution.get("policy_source"),
        "resolver_contract_version": policy_resolution.get("resolver_contract_version"),
        "policy_resolution": policy_resolution,
    }
    return _replay_envelope(decision_id, state, payload)


@router.get("/incident/{incident_id}")
def log_incident(incident_id: str):
    items = [row for row in _timeline_items(limit=200) if _safe_str(row.get("incident", {}).get("incident_id")) == incident_id]
    latest_ts = items[0]["ts"] if items else 0
    source = f"json:{TRADE_STATE_PATH}"
    return _collection_envelope(
        "log.incident.v2",
        source,
        latest_ts,
        len(items),
        items,
        key=incident_id,
        change_source="log_incident",
        extra={
            "incident_id": incident_id,
        },
    )
