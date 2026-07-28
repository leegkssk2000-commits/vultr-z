from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from backend.contracts.null_error_contract import (
    NULL_ERROR_CONTRACT_VERSION,
    coalesce,
    safe_bool,
    safe_dict,
    safe_int,
    safe_str,
)


def _non_empty_map(**kwargs: Any) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in kwargs.items():
        if v is None:
            continue
        if isinstance(v, str) and not v.strip():
            continue
        out[k] = v
    return out


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return "" if not value else json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, (list, tuple, set)):
        return "" if not value else json.dumps(list(value), ensure_ascii=False, separators=(",", ":"))
    text = str(value).strip()
    return "" if text in {"{}", "[]", "None", "null"} else text


def _first_ts(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def _mtime_from_paths(paths: Dict[str, Any]) -> Any:
    best = None
    for raw in paths.values():
        try:
            path = Path(str(raw))
        except Exception:
            continue
        try:
            if path.exists():
                ts = int(path.stat().st_mtime * 1000)
                best = ts if best is None else max(best, ts)
        except Exception:
            continue
    return best


def build_frontend_bridge_meta(
    payload: Optional[Dict[str, Any]] = None,
    *,
    source: str = "",
    source_ts: Any = None,
    stale: Any = None,
    stale_ms: Any = None,
    reconcile_status: Any = None,
    journal_event: Optional[Dict[str, Any]] = None,
    paper_state: Optional[Dict[str, Any]] = None,
    paths: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload_dict = safe_dict(payload)
    journal = safe_dict(journal_event)
    paper = safe_dict(paper_state)
    path_dict = safe_dict(paths)

    effective_route = safe_str(
        coalesce(
            payload_dict.get("effective_route"),
            payload_dict.get("route"),
            journal.get("effective_route"),
            journal.get("route"),
            paper.get("effective_route"),
            paper.get("route"),
        )
    )
    decision_action = safe_str(
        coalesce(
            payload_dict.get("decision_action"),
            journal.get("decision_action"),
            payload_dict.get("last_action"),
            paper.get("decision_action"),
            "hold",
        ),
        "hold",
    )
    risk_action = safe_str(
        coalesce(
            payload_dict.get("risk_action"),
            journal.get("risk_action"),
            paper.get("risk_action"),
            decision_action,
            "hold",
        ),
        "hold",
    )
    why_now = _clean_text(
        coalesce(
            payload_dict.get("decision_reason"),
            payload_dict.get("reason"),
            payload_dict.get("detail"),
            journal.get("decision_reason"),
            journal.get("reason"),
            paper.get("decision_reason"),
            paper.get("reason"),
        )
    )
    decision_id = safe_str(
        coalesce(
            payload_dict.get("decision_id"),
            journal.get("decision_id"),
            paper.get("decision_id"),
            payload_dict.get("signal_id"),
            journal.get("signal_id"),
        )
    )
    signal_id = safe_str(
        coalesce(
            payload_dict.get("signal_id"),
            journal.get("signal_id"),
            paper.get("signal_id"),
        )
    )
    source_value = safe_str(
        coalesce(
            source,
            payload_dict.get("source"),
            journal.get("source"),
            paper.get("source"),
        )
    )
    source_ts_value = _first_ts(
        source_ts,
        payload_dict.get("source_ts"),
        journal.get("source_ts"),
        paper.get("source_ts"),
        payload_dict.get("written_at"),
        payload_dict.get("updated_at"),
        payload_dict.get("ts_ms"),
        journal.get("written_at"),
        journal.get("updated_at"),
        journal.get("ts_ms"),
        paper.get("written_at"),
        paper.get("updated_at"),
        paper.get("ts_ms"),
        _mtime_from_paths(path_dict),
    )
    stale_value = safe_bool(
        coalesce(stale, payload_dict.get("stale"), journal.get("stale"), paper.get("stale"), False),
        False,
    )
    stale_ms_value = safe_int(
        coalesce(stale_ms, payload_dict.get("stale_ms"), journal.get("stale_ms"), paper.get("stale_ms"), 0),
        0,
    )
    reconcile_value = safe_str(
        coalesce(
            reconcile_status,
            payload_dict.get("reconcile_status"),
            journal.get("reconcile_status"),
            paper.get("reconcile_status"),
            "ok",
        ),
        "ok",
    )

    verification_status = "hold" if stale_value or reconcile_value not in {"ok", "ready"} else "ready"
    why_not_now = _clean_text(
        coalesce(
            payload_dict.get("why_not_now"),
            payload_dict.get("blocked_reason"),
            paper.get("blocked_reason"),
        )
    )
    route_reason = _clean_text(
        coalesce(
            payload_dict.get("route_reason"),
            why_now,
            journal.get("decision_reason"),
            journal.get("reason"),
        )
    )
    next_best_action = safe_str(
        coalesce(
            payload_dict.get("next_best_action"),
            risk_action,
            decision_action,
            "hold",
        ),
        "hold",
    )
    change_digest = " | ".join(
        [x for x in [decision_action, effective_route, why_now] if isinstance(x, str) and x.strip()]
    )[:240]

    replay_anchor = _non_empty_map(
        decision_id=decision_id or None,
        signal_id=signal_id or None,
        source=source_value or None,
        source_ts=source_ts_value,
        journal_event_path=path_dict.get("journal_event_path"),
        paper_state_path=path_dict.get("paper_state_path"),
    )

    recovery_path = safe_str(
        coalesce(
            payload_dict.get("recovery_path"),
            path_dict.get("journal_event_path"),
            path_dict.get("paper_state_path"),
            source_value,
        )
    )

    meta = {
        "backend_ver": NULL_ERROR_CONTRACT_VERSION,
        "contract_version": safe_str(payload_dict.get("contract_version"), NULL_ERROR_CONTRACT_VERSION),
        "source": source_value,
        "source_ts": source_ts_value,
        "stale": stale_value,
        "stale_ms": stale_ms_value,
        "reconcile_status": reconcile_value,
        "decision_id": decision_id or None,
        "verification_status": verification_status,
        "change_digest": change_digest,
        "delta_summary": change_digest,
        "why_now": why_now,
        "why_not_now": why_not_now,
        "route_reason": route_reason,
        "next_best_action": next_best_action,
        "recovery_path": recovery_path,
        "replay_anchor": replay_anchor,
    }
    return meta


def enrich_frontend_bridge(
    payload: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    out = dict(safe_dict(payload))
    out.update(build_frontend_bridge_meta(out, **kwargs))
    return out
