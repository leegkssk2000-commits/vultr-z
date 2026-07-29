from __future__ import annotations

import json
from hashlib import sha1
from typing import Any, Dict, Iterable, List, Optional


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return default


def _first_non_empty(*values: Any) -> Optional[str]:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _payload_digest(row: Dict[str, Any]) -> str:
    try:
        raw = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except Exception:
        raw = repr(sorted(row.items()))
    return sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:12]


def build_replay_anchor(row: Dict[str, Any], *, source: str = "", index: Optional[int] = None) -> str:
    decision_id = _first_non_empty(row.get("decision_id"), row.get("signal_id")) or "na"
    event_id = _first_non_empty(row.get("event_id"), row.get("signal_id"), row.get("incident_id"))
    if event_id is None and index is not None:
        event_id = f"idx:{index}"
    event_id = event_id or "na"
    ts = _safe_int(row.get("source_ts"), _safe_int(row.get("ts"), _safe_int(row.get("server_ts"))))
    source_name = _first_non_empty(source, row.get("event"), row.get("type")) or "row"
    digest = _payload_digest(row)
    return f"{decision_id}:{event_id}:{ts}:{source_name}:{digest}"


def normalize_log_row(row: Dict[str, Any], *, source: str = "", index: Optional[int] = None) -> Dict[str, Any]:
    item = dict(row or {})
    item["ts"] = _safe_int(item.get("ts"), _safe_int(item.get("server_ts")))
    item["source_ts"] = _safe_int(item.get("source_ts"), item["ts"])
    item["decision_id"] = _first_non_empty(item.get("decision_id"), item.get("signal_id")) or ""
    item["event_id"] = _first_non_empty(item.get("event_id"), item.get("signal_id"), item.get("incident_id")) or ""
    item["symbol"] = _first_non_empty(item.get("symbol"), item.get("ticker"), item.get("market")) or ""
    item["strategy"] = _first_non_empty(item.get("strategy"), item.get("strategy_key"), item.get("route")) or ""
    item["replay_anchor"] = build_replay_anchor(item, source=source, index=index)
    return item


def sort_log_rows(rows: Iterable[Dict[str, Any]], *, reverse: bool = False) -> List[Dict[str, Any]]:
    return sorted(
        rows,
        key=lambda item: (
            _safe_int(item.get("source_ts"), _safe_int(item.get("ts"))),
            _safe_int(item.get("ts")),
            str(item.get("decision_id") or ""),
            str(item.get("event_id") or ""),
            str(item.get("replay_anchor") or ""),
        ),
        reverse=reverse,
    )


def normalize_log_rows(rows: Iterable[Dict[str, Any]], *, source: str = "", reverse: bool = False) -> List[Dict[str, Any]]:
    normalized = [normalize_log_row(row, source=source, index=index) for index, row in enumerate(rows or []) if isinstance(row, dict)]
    return sort_log_rows(normalized, reverse=reverse)
