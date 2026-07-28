"""Read-only dashboard HTTP surface.

The dashboard never creates or migrates database tables. Database ownership
belongs to the verified ledger writer; missing or incompatible storage fails
closed to empty read results instead of creating a second authority.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from flask import Blueprint, jsonify, render_template

from config.settings import DB_PATH as SETTINGS_DB_PATH


bp = Blueprint(
    "dashboard_bp",
    __name__,
    template_folder="../templates",
    static_folder="../static",
)


def _z_home() -> Path:
    return Path(os.getenv("Z_HOME", "/home/z/z")).expanduser().resolve()


def _db_path() -> Path:
    return Path(os.getenv("Z_DASHBOARD_DB_PATH", SETTINGS_DB_PATH)).expanduser().resolve()


def _tasks_path() -> Path:
    return Path(os.getenv("Z_ROUTINE_TASKS_PATH", str(_z_home() / "620_tasks.json"))).expanduser().resolve()


def _conn() -> sqlite3.Connection:
    path = _db_path()
    if not path.is_file():
        raise FileNotFoundError(path)
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _safe_exec(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    try:
        with _conn() as connection:
            cursor = connection.execute(sql, params)
            return [dict(row) for row in cursor.fetchall()]
    except (FileNotFoundError, sqlite3.Error, OSError):
        return []


def _table_columns(table: str) -> set[str]:
    rows = _safe_exec(f"pragma table_info({table})")
    return {str(row.get("name")) for row in rows if row.get("name")}


@bp.route("/")
def index():
    return render_template("index.html")


@bp.route("/api/summary")
def summary():
    trade_count = _safe_exec("select count(*) n from trades")
    wins = _safe_exec("select avg(case when pnl>0 then 1 else 0 end) win from trades")
    pnl = _safe_exec("select sum(pnl) pnl from trades")
    return jsonify(
        {
            "trades": trade_count[0]["n"] if trade_count else 0,
            "win_rate": round((wins[0]["win"] or 0) * 100, 2) if wins else 0,
            "pnl_sum": round(pnl[0]["pnl"], 2) if pnl and pnl[0]["pnl"] is not None else 0,
            "read_only": True,
            "db_bound": _db_path().is_file(),
        }
    )


@bp.route("/api/winrates/by_symbol")
def win_by_symbol():
    return jsonify(
        _safe_exec(
            """
            select symbol,
                   round(avg(case when pnl>0 then 1.0 else 0 end)*100,2) as win_rate,
                   count(*) as trades
            from trades
            group by symbol
            having count(*)>=5
            order by trades desc
            limit 50
            """
        )
    )


@bp.route("/api/winrates/by_strategy")
def win_by_strategy():
    return jsonify(
        _safe_exec(
            """
            select coalesce(strategy,'unknown') as strategy,
                   round(avg(case when pnl>0 then 1.0 else 0 end)*100,2) as win_rate,
                   count(*) as trades
            from trades
            group by strategy
            having count(*)>=5
            order by trades desc
            """
        )
    )


@bp.route("/api/winrates/long_short")
def win_long_short():
    return jsonify(
        _safe_exec(
            """
            select upper(side) as side,
                   round(avg(case when pnl>0 then 1.0 else 0 end)*100,2) as win_rate,
                   count(*) trades
            from trades
            group by upper(side)
            """
        )
    )


@bp.route("/api/pnl/monthly")
def pnl_monthly():
    return jsonify(
        _safe_exec(
            """
            select strftime('%Y-%m', ts) as ym,
                   round(sum(pnl),2) as pnl
            from trades
            group by ym
            order by ym
            """
        )
    )


@bp.route("/api/scanner/alts")
def scanner_alts():
    return jsonify(
        _safe_exec(
            """
            select symbol, round(change24,2) as change24, round(vol24,2) as vol24
            from market_snapshots
            where ts >= datetime('now','-1 day')
            order by change24 desc
            limit 50
            """
        )
    )


@bp.route("/api/routine/status")
def routine_status():
    output: dict[str, Any] = {"phase": "unknown", "progress": 0, "next": "n/a"}
    path = _tasks_path()
    try:
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                output["phase"] = data.get("phase", "unknown")
                output["progress"] = data.get("progress", 0)
                output["next"] = data.get("next", "n/a")
    except (OSError, ValueError, TypeError):
        pass
    output["read_only"] = True
    return jsonify(output)


@bp.route("/api/metrics2")
def metrics2():
    columns = _table_columns("metrics")
    if not {"ts", "key", "value"}.issubset(columns):
        return jsonify([])
    return jsonify(_safe_exec("select ts,key,value from metrics order by ts desc limit 50"))


@bp.route("/health")
def health():
    return jsonify(status="ok", read_only=True, db_bound=_db_path().is_file()), 200


@bp.route("/healthz")
def healthz():
    return jsonify(ok=True, read_only=True), 200
