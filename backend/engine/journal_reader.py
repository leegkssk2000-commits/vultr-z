from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.contracts.frontend_bridge_contract import enrich_frontend_bridge


BASE_DIR = Path("/home/z/z/backend/data")
STATE_DIR = BASE_DIR / "state"
SYNC_DIR = BASE_DIR / "sync"
JOURNAL_DIR = BASE_DIR / "journal"
PAPER_DIR = BASE_DIR / "paper"

LBT_EVENT_LATEST = JOURNAL_DIR / "lbot_event.latest.json"
PAPER_STATE_LATEST = PAPER_DIR / "paper_state.latest.json"


def _read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def _read_jsonl(path: Path, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    try:
        if not path.exists():
            return rows

        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                    if isinstance(row, dict):
                        rows.append(row)
                except Exception:
                    continue
    except Exception:
        return []

    if limit is not None and limit > 0:
        return rows[-limit:]
    return rows


def _day_key(day: Optional[str] = None) -> str:
    if day:
        return str(day).strip()

    latest = _read_json(JOURNAL_DIR / "equity_curve.latest.json", {})
    if isinstance(latest, dict) and latest.get("date"):
        return str(latest["date"])

    return ""


def _first_non_empty(*values: Any) -> Any:
    for v in values:
        if v is None:
            continue
        if isinstance(v, str) and not v.strip():
            continue
        return v
    return None


def get_state_snapshot() -> Dict[str, Any]:
    positions_latest = _read_json(STATE_DIR / "positions.latest.json", {})
    equity_latest = _read_json(STATE_DIR / "equity.latest.json", {})
    trades_latest = _read_json(STATE_DIR / "trades.latest.json", {})
    sync_state = _read_json(STATE_DIR / "sync_state.json", {})

    positions_items = positions_latest.get("items", []) if isinstance(positions_latest, dict) else []
    trades_items = trades_latest.get("items", []) if isinstance(trades_latest, dict) else []

    return {
        "positions_latest": positions_latest if isinstance(positions_latest, dict) else {},
        "equity_latest": equity_latest if isinstance(equity_latest, dict) else {},
        "trades_latest": trades_latest if isinstance(trades_latest, dict) else {},
        "sync_state": sync_state if isinstance(sync_state, dict) else {},
        "positions_count": len(positions_items) if isinstance(positions_items, list) else 0,
        "trades_count": len(trades_items) if isinstance(trades_items, list) else 0,
    }


def get_equity_curve_latest() -> Dict[str, Any]:
    return _read_json(JOURNAL_DIR / "equity_curve.latest.json", {})


def get_dd_curve_latest() -> Dict[str, Any]:
    return _read_json(JOURNAL_DIR / "dd_curve.latest.json", {})


def get_equity_curve(day: Optional[str] = None, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    dk = _day_key(day)
    if not dk:
        return []
    return _read_jsonl(JOURNAL_DIR / f"equity_curve.{dk}.jsonl", limit=limit)


def get_dd_curve(day: Optional[str] = None, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    dk = _day_key(day)
    if not dk:
        return []
    return _read_jsonl(JOURNAL_DIR / f"dd_curve.{dk}.jsonl", limit=limit)


def get_sync_notes(day: Optional[str] = None, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    dk = _day_key(day)
    if not dk:
        return []
    return _read_jsonl(JOURNAL_DIR / f"sync_notes.{dk}.jsonl", limit=limit)


def get_trade_notes(day: Optional[str] = None, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    dk = _day_key(day)
    if not dk:
        return []
    return _read_jsonl(JOURNAL_DIR / f"trade_notes.{dk}.jsonl", limit=limit)


def get_daily_sync_log(day: Optional[str] = None, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    dk = _day_key(day)
    if not dk:
        return []
    return _read_jsonl(SYNC_DIR / f"sync.{dk}.jsonl", limit=limit)


def get_daily_equity_log(day: Optional[str] = None, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    dk = _day_key(day)
    if not dk:
        return []
    return _read_jsonl(SYNC_DIR / f"equity_daily.{dk}.jsonl", limit=limit)


def _read_latest_journal_event() -> Dict[str, Any]:
    raw = _read_json(LBT_EVENT_LATEST, {})
    if not isinstance(raw, dict):
        return {}

    je = raw.get("journal_event")
    if isinstance(je, dict):
        return je

    return raw


def _read_latest_paper_state() -> Dict[str, Any]:
    raw = _read_json(PAPER_STATE_LATEST, {})
    return raw if isinstance(raw, dict) else {}


def _paper_state_selected(raw: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {}

    sel = _first_non_empty(
        raw.get("paper_state_selected"),
        raw.get("selected"),
    )
    return sel if isinstance(sel, dict) else {}


def _paper_positions(raw: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {}

    pos = raw.get("positions")
    return pos if isinstance(pos, dict) else {}


def _paper_positions_count(raw: Dict[str, Any]) -> int:
    return len(_paper_positions(raw))

def _path_source_ts(*paths: Path) -> Optional[int]:
    values: List[int] = []
    for path in paths:
        try:
            if path.exists():
                values.append(int(path.stat().st_mtime * 1000))
        except Exception:
            continue
    return max(values) if values else None


def _summary_paths() -> Dict[str, str]:
    return {
        "journal_event_path": str(LBT_EVENT_LATEST),
        "paper_state_path": str(PAPER_STATE_LATEST),
    }



def build_journal_summary(day: Optional[str] = None) -> Dict[str, Any]:
    state = get_state_snapshot()
    equity_curve_latest = get_equity_curve_latest()
    dd_curve_latest = get_dd_curve_latest()

    equity_curve_rows = get_equity_curve(day=day)
    dd_curve_rows = get_dd_curve(day=day)
    sync_note_rows = get_sync_notes(day=day)
    trade_note_rows = get_trade_notes(day=day)
    sync_log_rows = get_daily_sync_log(day=day)
    equity_log_rows = get_daily_equity_log(day=day)

    equity_latest = state.get("equity_latest", {})
    positions_latest = state.get("positions_latest", {})
    trades_latest = state.get("trades_latest", {})
    sync_state = state.get("sync_state", {})

    journal_event_latest = _read_latest_journal_event()
    paper_state_latest = _read_latest_paper_state()
    paper_state_selected = _paper_state_selected(paper_state_latest)

    state_positions_count = _first_non_empty(
        state.get("positions_count"),
        0,
    )
    state_trades_count = _first_non_empty(
        state.get("trades_count"),
        0,
    )

    payload = {
        "ok": True,
        "day": _day_key(day),
        "state": {
            "sync_state": sync_state,
            "positions_count": state_positions_count,
            "trades_count": state_trades_count,
            "equity": float(equity_latest.get("equity", 0.0) or 0.0),
            "balance": float(equity_latest.get("balance", 0.0) or 0.0),
            "available": float(equity_latest.get("available", 0.0) or 0.0),
            "used_margin": float(equity_latest.get("used_margin", 0.0) or 0.0),
            "positions_updated_at": positions_latest.get("updated_at", 0),
            "equity_updated_at": equity_latest.get("updated_at", 0),
            "trades_updated_at": trades_latest.get("updated_at", 0),

            # LBot / paper Ãà Ãß°¡
            "paper_positions_count": _paper_positions_count(paper_state_latest),
            "paper_state_updated_at": _first_non_empty(
                paper_state_latest.get("updated_at"),
                paper_state_latest.get("ts"),
                0,
            ),
        },
        "latest": {
            "equity_curve": equity_curve_latest,
            "dd_curve": dd_curve_latest,

            # ÃÖ½Å LBot / paper Ãà Ãß°¡
            "journal_event": journal_event_latest,
            "paper_state_selected": paper_state_selected,
            "paper_state": paper_state_latest,
        },
        "counts": {
            "equity_curve_rows": len(equity_curve_rows),
            "dd_curve_rows": len(dd_curve_rows),
            "sync_note_rows": len(sync_note_rows),
            "trade_note_rows": len(trade_note_rows),
            "sync_log_rows": len(sync_log_rows),
            "equity_log_rows": len(equity_log_rows),
        },
    }
    return enrich_frontend_bridge(
        payload,
        source="journal_summary",
        source_ts=_path_source_ts(LBT_EVENT_LATEST, PAPER_STATE_LATEST),
        stale=paper_state_latest.get("stale"),
        stale_ms=paper_state_latest.get("stale_ms"),
        reconcile_status=paper_state_latest.get("reconcile_status"),
        journal_event=journal_event_latest,
        paper_state=paper_state_latest,
        paths=_summary_paths(),
    )


def build_journal_bundle(day: Optional[str] = None, limit: Optional[int] = None) -> Dict[str, Any]:
    return {
        "ok": True,
        "day": _day_key(day),
        "summary": build_journal_summary(day=day),
        "equity_curve_latest": get_equity_curve_latest(),
        "dd_curve_latest": get_dd_curve_latest(),
        "equity_curve": get_equity_curve(day=day, limit=limit),
        "dd_curve": get_dd_curve(day=day, limit=limit),
        "sync_notes": get_sync_notes(day=day, limit=limit),
        "trade_notes": get_trade_notes(day=day, limit=limit),
        "sync_log": get_daily_sync_log(day=day, limit=limit),
        "equity_log": get_daily_equity_log(day=day, limit=limit),

        # Á¤ÇÕ¼º °Ë»ç¿ë ÃÖ½Å Ãà ³ëÃâ
        "journal_event_latest": _read_latest_journal_event(),
        "paper_state_latest": _read_latest_paper_state(),
    }


if __name__ == "__main__":
    print(build_journal_bundle(limit=5)["summary"]["counts"])
