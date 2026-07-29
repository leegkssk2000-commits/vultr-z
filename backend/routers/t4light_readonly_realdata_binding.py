from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(os.getenv("ZEL_REPO_ROOT", os.getenv("ZEL_ROOT", "/home/z/z")))

READONLY_FLAGS = {
    "read_only": True,
    "execution_allowed": False,
    "mutation_allowed": False,
    "may_emit_to_bot": False,
    "emit": False,
    "mutate": False,
    "order": False,
    "p4_final_action_only": True,
    "p8_final_action_authority": False,
}

SQLITE_METRICS_SOURCE = "backend/data/metrics.sqlite"

PNL_EQUITY_SOURCES = [
    "backend/data/state/equity.latest.json",
    "backend/data/journal/equity_curve.latest.json",
    "backend/state.json",
    "data/portfolio/zops_portfolio_state_v7_3_1_4_latest.json",
    "data/portfolio/latest.json",
    "data/portfolio/zops_portfolio_pnl_bars_v7_3_1_4_latest.json",
    "data/portfolio/zops_portfolio_equity_curve_v7_3_1_4_latest.json",
]

VIRTUAL_SOURCES = [
    "backend/data/paper/paper_state.latest.json",
    "data/portfolio/zops_portfolio_virtual_v7_3_1_4_latest.json",
    "data/portfolio/latest.json",
]

BOT_TEAM_SOURCES = [
    "data/zico/zico_120pct_realdata_command_surface_tmp_canonical_v7_3_2_1_latest.json",
    "data/zico/zico_ceo_pro_terminal_dashboard_v7_3_1_6_latest.json",
    "data/zico/zico_ceo_pro_dashboard_single_fab_v7_3_1_5_latest.json",
]


def _path(rel: str) -> Path:
    return ROOT / rel


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            text = value.strip().replace(",", "")
            if not text:
                return None
            return float(text)
        except ValueError:
            return None
    return None


def _first_num(obj: dict[str, Any], keys: Iterable[str]) -> float | None:
    for key in keys:
        if key in obj:
            value = _num(obj.get(key))
            if value is not None:
                return value
    return None


def _read_json_value(rel: str) -> tuple[Any | None, dict[str, Any]]:
    path = _path(rel)
    inv = {"path": rel, "present": path.exists(), "bytes": 0, "accepted": False, "reason": "missing"}
    if not path.exists() or not path.is_file():
        return None, inv
    inv["bytes"] = path.stat().st_size
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        inv["reason"] = f"invalid_json:{type(exc).__name__}"
        return None, inv
    inv["reason"] = "loaded"
    return data, inv


def _is_unbound(obj: dict[str, Any]) -> bool:
    dq = obj.get("data_quality") if isinstance(obj.get("data_quality"), dict) else {}
    reason = str(dq.get("reason", "")).lower()
    return dq.get("state") == "UNBOUND" or obj.get("portfolio_source_bound") is False or "skeleton" in reason


def _rows(obj: dict[str, Any], keys: Iterable[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for key in keys:
        value = obj.get(key)
        if isinstance(value, list):
            out.extend(item for item in value if isinstance(item, dict))
    return out


def _epoch_ms_from_date(value: Any) -> int | None:
    if value is None:
        return None
    number = _num(value)
    if number is not None:
        return int(number if number > 10_000_000_000 else number * 1000)
    text = str(value).strip()
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return int(datetime.strptime(text, fmt).replace(tzinfo=timezone.utc).timestamp() * 1000)
        except ValueError:
            pass
    return None


def _hold(route: str, missing: list[dict[str, Any]], required_fields: list[str]) -> dict[str, Any]:
    return {
        "schema": "zel.t4light.readonly.binding_result.v1",
        "route": route,
        "status": "DATA_HOLD",
        "portfolio_source_bound": False,
        "data_quality": {
            "state": "DATA_HOLD",
            "reason": "required real source not found or source is an unbound skeleton",
            "required_fields": required_fields,
        },
        "missing_sources": missing,
        **READONLY_FLAGS,
    }


def _sqlite_connect(rel: str) -> tuple[sqlite3.Connection | None, dict[str, Any]]:
    path = _path(rel)
    inv = {"path": rel, "present": path.exists(), "bytes": 0, "accepted": False, "reason": "missing"}
    if not path.exists() or not path.is_file():
        return None, inv
    inv["bytes"] = path.stat().st_size
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        inv["reason"] = "loaded"
        return conn, inv
    except Exception as exc:
        inv["reason"] = f"sqlite_open_failed:{type(exc).__name__}"
        return None, inv


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return bool(row)


def _sqlite_pnl_equity() -> tuple[dict[str, Any] | None, dict[str, Any]]:
    conn, inv = _sqlite_connect(SQLITE_METRICS_SOURCE)
    if conn is None:
        return None, inv
    try:
        equity_rows = []
        if _table_exists(conn, "equity_daily"):
            equity_rows = conn.execute(
                "SELECT date,equity_usdt,realized_pnl,unrealized_pnl,ts FROM equity_daily ORDER BY date ASC"
            ).fetchall()
        daily_rows = []
        if _table_exists(conn, "daily_metrics"):
            daily_rows = conn.execute("SELECT date,pnl FROM daily_metrics ORDER BY date ASC").fetchall()
        summary = None
        if _table_exists(conn, "metrics_summary"):
            summary = conn.execute("SELECT realized_pnl FROM metrics_summary WHERE id=1").fetchone()
    finally:
        conn.close()

    points: list[dict[str, Any]] = []
    for row in equity_rows:
        equity = _num(row["equity_usdt"])
        ts_ms = _epoch_ms_from_date(row["ts"]) or _epoch_ms_from_date(row["date"])
        if equity is not None and ts_ms is not None:
            points.append({"ts_ms": ts_ms, "equity_usdt": equity})

    bars: list[dict[str, Any]] = []
    for row in daily_rows:
        pnl = _num(row["pnl"])
        if pnl is not None and row["date"]:
            bars.append({"bucket": str(row["date"]), "pnl_usdt": pnl})

    today_pnl = bars[-1]["pnl_usdt"] if bars else None
    if today_pnl is None and summary is not None:
        today_pnl = _num(summary["realized_pnl"])
    if today_pnl is None and equity_rows:
        last = equity_rows[-1]
        realized = _num(last["realized_pnl"]) or 0.0
        unrealized = _num(last["unrealized_pnl"]) or 0.0
        today_pnl = realized + unrealized

    if today_pnl is None or not points:
        inv["reason"] = "sqlite_missing_today_pnl_or_equity_daily_rows"
        return None, inv

    inv["accepted"] = True
    inv["reason"] = "metrics_sqlite_equity_daily_bound"
    return {"today_pnl": today_pnl, "equity_series": points, "pnl_bars": bars, "source": inv}, inv


def _json_pnl_equity(obj: dict[str, Any]) -> dict[str, Any] | None:
    today_pnl = _first_num(
        obj,
        ["today_pnl", "todayPnl", "daily_pnl", "day_pnl_usdt", "pnl_today", "net_day_pnl", "realized_pnl", "realized_pnl_day", "unrealized_pnl", "pnl"],
    )
    if today_pnl is None:
        realized = _first_num(obj, ["realized_pnl_day", "realized_pnl"])
        unrealized = _first_num(obj, ["unrealized_pnl"])
        if realized is not None or unrealized is not None:
            today_pnl = (realized or 0.0) + (unrealized or 0.0)

    points: list[dict[str, Any]] = []
    for point in _rows(obj, ["equity_series", "equity_curve", "curve", "points", "series"]):
        ts = _first_num(point, ["ts_ms", "timestamp", "time", "ts", "x"])
        equity = _first_num(point, ["equity_usdt", "equity", "balance", "nav", "value", "y"])
        ts_ms = _epoch_ms_from_date(ts)
        if ts_ms is not None and equity is not None:
            points.append({"ts_ms": ts_ms, "equity_usdt": equity})

    if not points:
        equity = _first_num(obj, ["equity_usdt", "equity", "balance", "account_equity"])
        ts = _first_num(obj, ["ts_ms", "updated_at", "ts", "source_ts_ms", "created_ts_ms"])
        ts_ms = _epoch_ms_from_date(ts)
        if equity is not None and ts_ms is not None:
            points.append({"ts_ms": ts_ms, "equity_usdt": equity})

    bars: list[dict[str, Any]] = []
    for bar in _rows(obj, ["pnl_bars", "bars", "items"]):
        bucket = bar.get("bucket") or bar.get("date") or bar.get("x")
        pnl = _first_num(bar, ["pnl_usdt", "pnl", "net", "amount", "value", "y"])
        if bucket is not None and pnl is not None:
            bars.append({"bucket": str(bucket), "pnl_usdt": pnl})

    if today_pnl is None or not points:
        return None
    return {"today_pnl": today_pnl, "equity_series": points, "pnl_bars": bars}


def bind_pnl_equity() -> dict[str, Any]:
    missing: list[dict[str, Any]] = []
    sqlite_payload, sqlite_inv = _sqlite_pnl_equity()
    if sqlite_payload is not None:
        return {
            "schema": "zel.t4light.pnl_equity.readonly.bound.v1",
            "route": "/api/portfolio/state",
            "status": "PASS",
            "portfolio_source_bound": True,
            "today_pnl": sqlite_payload["today_pnl"],
            "equity_series": sqlite_payload["equity_series"],
            "pnl_bars": sqlite_payload["pnl_bars"],
            "source_inventory": [sqlite_payload["source"]],
            "data_quality": {"state": "BOUND_REAL_SOURCE", "reason": "metrics.sqlite equity_daily/daily_metrics source passed guard checks"},
            **READONLY_FLAGS,
        }
    missing.append(sqlite_inv)

    for rel in PNL_EQUITY_SOURCES:
        value, inv = _read_json_value(rel)
        if not isinstance(value, dict):
            missing.append(inv)
            continue
        if _is_unbound(value):
            inv["reason"] = "unbound_skeleton_refused"
            missing.append(inv)
            continue
        payload = _json_pnl_equity(value)
        if payload is None:
            inv["reason"] = "missing_today_pnl_or_equity_series"
            missing.append(inv)
            continue
        inv["accepted"] = True
        return {
            "schema": "zel.t4light.pnl_equity.readonly.bound.v1",
            "route": "/api/portfolio/state",
            "status": "PASS",
            "portfolio_source_bound": True,
            "today_pnl": payload["today_pnl"],
            "equity_series": payload["equity_series"],
            "pnl_bars": payload["pnl_bars"],
            "source_inventory": [inv],
            "data_quality": {"state": "BOUND_REAL_SOURCE", "reason": "real JSON PNL/equity source passed guard checks"},
            **READONLY_FLAGS,
        }

    return _hold("/api/portfolio/state", missing, ["today_pnl", "equity_series[].ts_ms", "equity_series[].equity_usdt"])


def _virtual_from_paper_state(obj: dict[str, Any]) -> dict[str, Any] | None:
    rows: list[dict[str, Any]] = []
    positions = obj.get("positions") if isinstance(obj.get("positions"), dict) else {}
    for key, pos in positions.items():
        if not isinstance(pos, dict):
            continue
        symbol = pos.get("symbol") or str(key).split("::", 1)[0]
        realized = _first_num(pos, ["realized_pnl", "pnl", "net_pnl"])
        unrealized = _first_num(pos, ["unrealized_pnl"])
        pnl = (realized or 0.0) + (unrealized or 0.0) if realized is not None or unrealized is not None else None
        if symbol and pnl is not None:
            rows.append({"symbol": str(symbol), "virtual_asset_pnl": pnl})

    selected = obj.get("paper_state_selected") if isinstance(obj.get("paper_state_selected"), dict) else {}
    if selected and not rows:
        symbol = selected.get("symbol") or obj.get("last_symbol")
        realized = _first_num(selected, ["realized_pnl", "pnl", "net_pnl"])
        unrealized = _first_num(selected, ["unrealized_pnl"])
        pnl = (realized or 0.0) + (unrealized or 0.0) if realized is not None or unrealized is not None else None
        if symbol and pnl is not None:
            rows.append({"symbol": str(symbol), "virtual_asset_pnl": pnl})

    scalar = _first_num(obj, ["virtual_asset_pnl", "virtual_pnl", "paper_pnl", "realized_pnl", "unrealized_pnl"])
    if scalar is None and rows:
        scalar = sum(row["virtual_asset_pnl"] for row in rows)
    if scalar is None and not rows:
        return None
    return {"virtual_asset_pnl": scalar, "asset_rows": rows}


def bind_virtual_asset_pnl() -> dict[str, Any]:
    missing: list[dict[str, Any]] = []
    for rel in VIRTUAL_SOURCES:
        value, inv = _read_json_value(rel)
        if not isinstance(value, dict):
            missing.append(inv)
            continue
        if _is_unbound(value):
            inv["reason"] = "unbound_skeleton_refused"
            missing.append(inv)
            continue

        payload = _virtual_from_paper_state(value)
        if payload is None:
            scalar = _first_num(value, ["virtual_asset_pnl", "virtual_pnl", "paper_pnl", "sim_pnl"])
            rows = []
            for row in _rows(value, ["asset_rows", "virtual_assets", "assets", "rows", "items"]):
                symbol = row.get("symbol") or row.get("asset") or row.get("coin")
                pnl = _first_num(row, ["virtual_asset_pnl", "virtual_pnl", "pnl", "net_pnl", "amount"])
                if symbol and pnl is not None:
                    rows.append({"symbol": str(symbol), "virtual_asset_pnl": pnl})
            if scalar is not None or rows:
                payload = {"virtual_asset_pnl": scalar if scalar is not None else sum(row["virtual_asset_pnl"] for row in rows), "asset_rows": rows}

        if payload is None:
            inv["reason"] = "missing_virtual_asset_pnl"
            missing.append(inv)
            continue
        inv["accepted"] = True
        return {
            "schema": "zel.t4light.virtual_asset_pnl.readonly.bound.v1",
            "route": "/api/portfolio/virtual",
            "status": "PASS",
            "portfolio_source_bound": True,
            "virtual_asset_pnl": payload["virtual_asset_pnl"],
            "asset_rows": payload["asset_rows"],
            "source_inventory": [inv],
            "data_quality": {"state": "BOUND_REAL_SOURCE", "reason": "paper/virtual asset PNL source passed guard checks"},
            **READONLY_FLAGS,
        }

    return _hold("/api/portfolio/virtual", missing, ["virtual_asset_pnl", "asset_rows[].virtual_asset_pnl"])


def _direct_bot_team_stats(obj: dict[str, Any]) -> list[dict[str, Any]]:
    teams: list[dict[str, Any]] = []
    for row in _rows(obj, ["bot_team_stats", "team_stats", "botTeams", "teams", "rows", "items"]):
        name = row.get("team") or row.get("name") or row.get("strategy") or row.get("bot")
        win_rate = _first_num(row, ["win_rate", "winRate", "hit_rate", "success_rate"])
        contribution = _first_num(row, ["contribution", "contribution_pnl", "pnl", "net_pnl", "realized_pnl"])
        if name and win_rate is not None and contribution is not None:
            teams.append({"team": str(name), "win_rate": win_rate, "contribution": contribution})
    return teams


def _metrics_bot_team_stats() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    conn, inv = _sqlite_connect(SQLITE_METRICS_SOURCE)
    if conn is None:
        return [], inv
    try:
        summary = None
        if _table_exists(conn, "metrics_summary"):
            summary = conn.execute("SELECT total_trades,win_rate_30d,realized_pnl FROM metrics_summary WHERE id=1").fetchone()
        daily = None
        if _table_exists(conn, "daily_metrics"):
            daily = conn.execute("SELECT total_trades,win_rate,pnl FROM daily_metrics ORDER BY date DESC LIMIT 1").fetchone()
    finally:
        conn.close()

    total = _num(summary["total_trades"]) if summary is not None else None
    win_rate = _num(summary["win_rate_30d"]) if summary is not None else None
    contribution = _num(summary["realized_pnl"]) if summary is not None else None
    if (total is None or total <= 0) and daily is not None:
        total = _num(daily["total_trades"])
        win_rate = _num(daily["win_rate"])
        contribution = _num(daily["pnl"])

    if total is None or total <= 0 or win_rate is None or contribution is None:
        inv["reason"] = "metrics_sqlite_has_no_nonempty_team_or_trade_stats"
        return [], inv

    inv["accepted"] = True
    inv["reason"] = "metrics_sqlite_summary_bound_as_global_team_stats"
    return [
        {
            "team": "GLOBAL_METRICS",
            "win_rate": win_rate,
            "contribution": contribution,
            "total_trades": int(total),
            "source": SQLITE_METRICS_SOURCE,
        }
    ], inv


def bind_bot_team_stats() -> dict[str, Any]:
    missing: list[dict[str, Any]] = []
    teams, inv = _metrics_bot_team_stats()
    if teams:
        return {
            "schema": "zel.t4light.bot_team_stats.readonly.bound.v1",
            "route": "/api/v1/bot/state",
            "status": "PASS",
            "bot_team_stats": teams,
            "source_inventory": [inv],
            "data_quality": {"state": "BOUND_REAL_SOURCE", "reason": "metrics.sqlite win_rate/contribution source passed guard checks"},
            **READONLY_FLAGS,
        }
    missing.append(inv)

    for rel in BOT_TEAM_SOURCES:
        value, source_inv = _read_json_value(rel)
        if not isinstance(value, dict):
            missing.append(source_inv)
            continue
        if _is_unbound(value):
            source_inv["reason"] = "unbound_skeleton_refused"
            missing.append(source_inv)
            continue
        teams = _direct_bot_team_stats(value)
        if not teams:
            source_inv["reason"] = "missing_bot_team_win_rate_contribution"
            missing.append(source_inv)
            continue
        source_inv["accepted"] = True
        return {
            "schema": "zel.t4light.bot_team_stats.readonly.bound.v1",
            "route": "/api/v1/bot/state",
            "status": "PASS",
            "bot_team_stats": teams,
            "source_inventory": [source_inv],
            "data_quality": {"state": "BOUND_REAL_SOURCE", "reason": "bot team stats source passed guard checks"},
            **READONLY_FLAGS,
        }

    return _hold("/api/v1/bot/state", missing, ["bot_team_stats[].team", "bot_team_stats[].win_rate", "bot_team_stats[].contribution"])


def binding_state() -> dict[str, Any]:
    sections = {
        "pnl_equity": bind_pnl_equity(),
        "virtual_asset_pnl": bind_virtual_asset_pnl(),
        "bot_team_stats": bind_bot_team_stats(),
    }
    complete = all(section.get("status") == "PASS" for section in sections.values())
    return {
        "schema": "zel.t4light.binding_state.v1",
        "status": "PASS" if complete else "DATA_HOLD",
        "json_score": "13/13" if complete else "9/13",
        "route_split": "unchanged",
        "roots": "unchanged",
        "order_capability": "blocked",
        **READONLY_FLAGS,
        **sections,
    }
