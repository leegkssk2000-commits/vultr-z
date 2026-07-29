from __future__ import annotations
from backend.contracts.null_error_contract import NULL_ERROR_CONTRACT_VERSION

import json
from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Query
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.state.db_access import get_db

router = APIRouter(prefix="/timeline", tags=["timeline"])


def _utc_iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _table_exists(db: Session, name: str) -> bool:
    try:
        bind = db.get_bind()
        dialect = getattr(bind.dialect, "name", "") or ""

        if dialect == "sqlite":
            row = db.execute(
                text(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name=:name"
                ),
                {"name": name},
            ).first()
            return row is not None

        insp = inspect(bind)
        return bool(insp.has_table(name))
    except Exception:
        return False


def _ensure_timeline_table(db: Session) -> None:
    bind = db.get_bind()
    dialect = getattr(bind.dialect, "name", "") or ""

    if dialect == "sqlite":
        db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS timeline_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    level TEXT NOT NULL DEFAULT 'info',
                    category TEXT NOT NULL DEFAULT 'system',
                    message TEXT NOT NULL DEFAULT '',
                    meta TEXT NULL
                )
                """
            )
        )
        db.commit()
        return

    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS timeline_events (
                id INTEGER PRIMARY KEY,
                ts VARCHAR(64) NOT NULL,
                level VARCHAR(32) NOT NULL DEFAULT 'info',
                category VARCHAR(64) NOT NULL DEFAULT 'system',
                message TEXT NOT NULL,
                meta TEXT NULL
            )
            """
        )
    )
    db.commit()


def _parse_meta(value: Any) -> Any:
    if value is None:
        return None

    if isinstance(value, (dict, list, int, float, bool)):
        return value

    if isinstance(value, (bytes, bytearray)):
        try:
            value = value.decode("utf-8")
        except Exception:
            return str(value)

    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None

        if (s.startswith("{") and s.endswith("}")) or (
            s.startswith("[") and s.endswith("]")
        ):
            try:
                return json.loads(s)
            except Exception:
                return s

        return s

    return str(value)


@router.get("", summary="Timeline events")
def get_timeline(
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    _ensure_timeline_table(db)

    try:
        rows = db.execute(
            text(
                """
                SELECT id, ts, level, category, message, meta
                FROM timeline_events
                ORDER BY id DESC
                LIMIT :limit
                """
            ),
            {"limit": limit},
        ).mappings().all()
    except SQLAlchemyError as exc:
        return [
            {
                "id": 1,
                "ts": _utc_iso_now(),
                "level": "error",
                "category": "system",
                "message": f"timeline query failed: {exc.__class__.__name__}",
                "meta": None,
            }
        ]

    out: List[Dict[str, Any]] = []
    for row in rows:
        ts = row.get("ts")
        if isinstance(ts, datetime):
            ts_out = ts.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        else:
            ts_out = str(ts) if ts is not None else None

        out.append(
            {
                "id": row.get("id"),
                "ts": ts_out,
                "level": row.get("level") or "info",
                "category": row.get("category") or "system",
                "message": row.get("message") or "",
                "meta": _parse_meta(row.get("meta")),
            }
        )

    return out


@router.post("/append", summary="Append timeline event")
def append_timeline_event(
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    _ensure_timeline_table(db)

    ts = str(payload.get("ts") or _utc_iso_now())
    level = str(payload.get("level") or "info")
    category = str(payload.get("category") or "system")
    message = str(payload.get("message") or "")
    meta = payload.get("meta")

    meta_text = None
    if meta is not None:
        try:
            meta_text = json.dumps(meta, ensure_ascii=False)
        except Exception:
            meta_text = str(meta)

    db.execute(
        text(
            """
            INSERT INTO timeline_events (
                ts, level, category, message, meta
            ) VALUES (
                :ts, :level, :category, :message, :meta
            )
            """
        ),
        {
            "ts": ts,
            "level": level,
            "category": category,
            "message": message,
            "meta": meta_text,
        },
    )
    db.commit()

    row = db.execute(text("SELECT last_insert_rowid() AS id")).mappings().first()
    event_id = int(row["id"]) if row and row.get("id") is not None else 0

    return {
        "ok": True,
        "id": event_id,
        "ts": ts,
        "level": level,
        "category": category,
        "message": message,
        "meta": meta,
    }



NULL_ERROR_CONTRACT_MARKER = NULL_ERROR_CONTRACT_VERSION
