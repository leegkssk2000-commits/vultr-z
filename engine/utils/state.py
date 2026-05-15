"""Small state helpers with fail-closed defaults."""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BASE = Path(__file__).resolve().parents[2]
DB = Path(os.getenv("DB_PATH", str(BASE / "db" / "z.sqlite")))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _q1(sql: str, params: tuple[Any, ...] = ()) -> Any:
    if not DB.exists():
        return None
    try:
        with sqlite3.connect(DB) as con:
            cur = con.cursor()
            cur.execute(sql, params)
            row = cur.fetchone()
            return row[0] if row else None
    except sqlite3.Error:
        return None


def load_state() -> tuple[str, datetime]:
    mode = _q1("SELECT mode FROM app_state WHERE id=1")
    started_at = _q1("SELECT started_at FROM app_state WHERE id=1")
    if mode not in {"paper", "shadow"}:
        return "paper", _now()
    try:
        started = datetime.fromisoformat(str(started_at or "").replace("Z", "+00:00"))
    except ValueError:
        started = _now()
    return str(mode), started


def update_mode(mode: str) -> bool:
    if mode not in {"paper", "shadow"} or not DB.exists():
        return False
    try:
        with sqlite3.connect(DB) as con:
            con.execute("UPDATE app_state SET mode=? WHERE id=1", (mode,))
            con.commit()
        return True
    except sqlite3.Error:
        return False


def ok_performance(min_trades: int, min_pnl: float) -> bool:
    trades = int(_q1("SELECT COUNT(1) FROM trades") or 0)
    pnl = float(_q1("SELECT COALESCE(SUM(pnl),0) FROM trades") or 0.0)
    return trades >= min_trades and pnl >= min_pnl
