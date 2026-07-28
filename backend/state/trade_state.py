from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List


DEFAULT_TRADE_STATE: Dict[str, Any] = {
    "status": "ok",
    "position": None,
    "positions": [],
    "pending_orders": [],
    "recent_trades": [],
    "signals": [],
    "last_fill": None,
    "last_fill_ts": None,
    "funding_info": {},
    "funding_next_ts": None,
    "reconcile_status": "ok",
    "stale": False,
    "stale_ms": 0,
    "decision_id": None,
    "backend_ver": "",
    "missingness": {"count": 0, "fields": [], "ratio": 0.0, "status": "ok"},
    "counterfactual": {},
    "recovery_path": [],
    "alert_ladder": {"level": "silent", "server_contract": {}},
    "alert_ladder_level": "silent",
    "alert_ladder_changed_at_ms": 0,
    "confidence": "high",
    "confidence_score": 1.0,
    "change_digest": "steady",
    "trust_rail": {},
    "decision_sheet": {},
    "core_contract": {},
    "source": "json:/home/z/z/backend/trade_state.json",
    "source_ts": None,
    "_source": "json:/home/z/z/backend/trade_state.json",
    "_source_ts": None,
    "_raw": {},
}


def _safe_load(path: Path) -> Dict[str, Any] | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return raw
    except Exception:
        return None
    return None


def _candidate_paths() -> List[Path]:
    vals = [
        os.getenv("Z_TRADE_STATE_PATH"),
        "/home/z/z/backend/trade_state.json",
        "/home/z/z/backend/state/trade_state.json",
        "/home/z/z/backend/trade_state/trade_state.json",
    ]
    out: List[Path] = []
    for value in vals:
        if not value:
            continue
        p = Path(value)
        if p not in out:
            out.append(p)
    return out


def _pick_path() -> Path | None:
    for path in _candidate_paths():
        if path.exists():
            return path
    return None


def _write_path() -> Path:
    existing = _pick_path()
    if existing is not None:
        return existing
    return _candidate_paths()[0]


def _unwrap(raw: Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(raw.get("state"), dict):
        base = dict(raw.get("state") or {})
        if raw.get("status") is not None and base.get("status") is None:
            base["status"] = raw.get("status")
        if raw.get("ts") is not None and base.get("source_ts") is None:
            base["source_ts"] = int(raw.get("ts"))
        return base
    return dict(raw)


def _normalize(path: Path | None, raw: Dict[str, Any] | None) -> Dict[str, Any]:
    out = dict(DEFAULT_TRADE_STATE)
    raw = raw or {}
    base = _unwrap(raw)

    if path:
        fallback_source = f"json:{path}"
        fallback_ts = int(path.stat().st_mtime)
    else:
        fallback_source = DEFAULT_TRADE_STATE["source"]
        fallback_ts = None

    out.update(base)
    out["source"] = base.get("source") or base.get("_source") or fallback_source
    out["source_ts"] = base.get("source_ts") or base.get("_source_ts") or fallback_ts
    out["_source"] = out["source"]
    out["_source_ts"] = out["source_ts"]
    out["_raw"] = raw
    try:
        from engine.change12_projection import augment_trade_state

        out = augment_trade_state(out)
    except Exception:
        pass
    return out


def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def read_trade_state() -> Dict[str, Any]:
    path = _pick_path()
    if not path:
        return dict(DEFAULT_TRADE_STATE)
    raw = _safe_load(path)
    return _normalize(path, raw)


def write_trade_state(state: Dict[str, Any]) -> Dict[str, Any]:
    path = _write_path()
    now_ms = int(time.time() * 1000)
    merged = dict(DEFAULT_TRADE_STATE)
    merged.update(read_trade_state())
    merged.update(state or {})
    merged["source"] = f"json:{path}"
    merged["source_ts"] = now_ms
    merged["_source"] = merged["source"]
    merged["_source_ts"] = merged["source_ts"]
    try:
        from engine.change12_projection import augment_trade_state

        merged = augment_trade_state(merged)
    except Exception:
        pass
    _atomic_write_json(path, merged)
    return merged


def _append_unique_front(items: List[Dict[str, Any]], item: Dict[str, Any], key_candidates: List[str], limit: int) -> List[Dict[str, Any]]:
    keys = [str(item.get(k)) for k in key_candidates if item.get(k) not in (None, "", "None")]
    out: List[Dict[str, Any]] = [item]
    for row in items:
        dup = False
        if keys:
            row_keys = [str(row.get(k)) for k in key_candidates if row.get(k) not in (None, "", "None")]
            dup = bool(set(keys) & set(row_keys))
        if not dup:
            out.append(row)
    return out[:limit]


def append_signal(signal: Dict[str, Any], limit: int = 50) -> Dict[str, Any]:
    state = read_trade_state()
    signals = state.get("signals")
    if not isinstance(signals, list):
        signals = []
    signal = dict(signal or {})
    signal.setdefault("ts", int(time.time() * 1000))
    state["signals"] = _append_unique_front(signals, signal, ["signal_id", "decision_id", "event_id"], limit)
    if signal.get("decision_id") not in (None, "", "None"):
        state["decision_id"] = signal.get("decision_id")
    state["last_fill_ts"] = signal.get("ts", state.get("last_fill_ts"))
    return write_trade_state(state)


def append_recent_trade(trade_item: Dict[str, Any], limit: int = 50) -> Dict[str, Any]:
    state = read_trade_state()
    recent = state.get("recent_trades")
    if not isinstance(recent, list):
        recent = []
    trade_item = dict(trade_item or {})
    trade_item.setdefault("ts", int(time.time() * 1000))
    state["recent_trades"] = _append_unique_front(recent, trade_item, ["signal_id", "decision_id", "event_id"], limit)
    if trade_item.get("decision_id") not in (None, "", "None"):
        state["decision_id"] = trade_item.get("decision_id")
    state["last_fill"] = trade_item
    state["last_fill_ts"] = trade_item.get("ts", state.get("last_fill_ts"))
    return write_trade_state(state)


def sync_webhook_result(
    *,
    decision_id: str,
    signal_id: str,
    event_id: str,
    symbol: str,
    side: str,
    strategy: str,
    route: str,
    mode: str,
    price: Any,
    qty: Any,
    accepted_at: int,
    result_reason: str,
    result_summary: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    result_summary = dict(result_summary or {})
    signal_item = {
        "event_id": event_id,
        "decision_id": decision_id,
        "signal_id": signal_id,
        "symbol": symbol,
        "side": side,
        "strategy": strategy,
        "route": route,
        "mode": mode,
        "price": price,
        "qty": qty,
        "accepted_at": accepted_at,
        "status": result_summary.get("status", "ready"),
        "decision_action": result_summary.get("decision_action", "hold"),
        "executor_status": result_summary.get("executor_status", "ready"),
        "executor_result": result_summary.get("executor_result", result_reason),
        "reason": result_reason,
        "ts": accepted_at * 1000,
    }
    append_signal(signal_item, limit=100)

    trade_item = {
        "event_id": event_id,
        "decision_id": decision_id,
        "signal_id": signal_id,
        "symbol": symbol,
        "side": side,
        "strategy": strategy,
        "route": route,
        "mode": mode,
        "price": price,
        "qty": qty,
        "status": result_summary.get("status", "ready"),
        "decision_action": result_summary.get("decision_action", "hold"),
        "executor_result": result_summary.get("executor_result", result_reason),
        "reason": result_reason,
        "ts": accepted_at * 1000,
    }
    return append_recent_trade(trade_item, limit=100)
