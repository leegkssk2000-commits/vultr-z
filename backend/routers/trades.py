from __future__ import annotations
from backend.contracts.null_error_contract import NULL_ERROR_CONTRACT_VERSION

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.state.db_access import get_db

router = APIRouter(prefix="/trades", tags=["trades"])

# 프로젝트/DB마다 테이블명이 다를 수 있어서 후보를 넓게 잡음
_CANDIDATE_TABLES = (
    "trades",
    "trade",
    "journal_trades",
    "journal_trade",
    "trades_journal",
    "trade_journal",
)

BASE_DIR = Path("/home/z/z/backend")
DATA_DIR = BASE_DIR / "data"
STATE_DIR = DATA_DIR / "state"
TRADES_LATEST_PATH = STATE_DIR / "trades.latest.json"


def _to_float(v: Any, default: float = 0.0) -> float:
    if v is None:
        return default
    try:
        if isinstance(v, str) and not v.strip():
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _to_iso(v: Any) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.isoformat()
    try:
        return str(v)
    except Exception:
        return None


def _to_int(v: Any, default: int = 0) -> int:
    try:
        if v is None or v == "":
            return default
        return int(float(v))
    except Exception:
        return default


def _safe_dict(v: Any) -> dict[str, Any]:
    return v if isinstance(v, dict) else {}


def _safe_list(v: Any) -> list[Any]:
    return v if isinstance(v, list) else []


def _clean_symbol(v: Any) -> str:
    s = str(v or "").strip().upper()
    return "".join(ch for ch in s if ch.isalnum())


def _first(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def _resolve_trades_table(db: Session) -> str:
    """
    후보 테이블들 중 실제 존재/조회 가능한 첫 번째 테이블명을 반환.
    """
    probe_cols = "id"
    for tbl in _CANDIDATE_TABLES:
        try:
            db.execute(text(f"SELECT {probe_cols} FROM {tbl} LIMIT 1"))
            return tbl
        except SQLAlchemyError:
            continue
    raise HTTPException(
        status_code=500,
        detail="Trades table not found. Expected one of: " + ", ".join(_CANDIDATE_TABLES),
    )


def _read_trades_latest() -> list[dict[str, Any]]:
    try:
        if not TRADES_LATEST_PATH.exists():
            return []
        raw = json.loads(TRADES_LATEST_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []

    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]

    if isinstance(raw, dict):
        for key in ("items", "trades", "rows", "data"):
            if isinstance(raw.get(key), list):
                return [x for x in raw[key] if isinstance(x, dict)]

    return []


def _normalize_fallback_row(row: dict[str, Any], idx: int) -> dict[str, Any]:
    meta = _safe_dict(row.get("meta"))
    signal = _safe_dict(row.get("signal"))
    payload = _safe_dict(row.get("payload"))

    qty = _to_float(
        _first(
            row.get("qty"),
            row.get("quantity"),
            row.get("size"),
            row.get("filled_qty"),
            row.get("executed_qty"),
            row.get("position_qty"),
            payload.get("qty"),
            meta.get("qty"),
        )
    )
    price = _to_float(
        _first(
            row.get("price"),
            row.get("fill_price"),
            row.get("avg_price"),
            row.get("entry_price"),
            row.get("last_fill_price"),
            payload.get("price"),
            meta.get("price"),
        )
    )
    pnl = _to_float(
        _first(
            row.get("pnl"),
            row.get("realized_pnl"),
            row.get("realizedPnl"),
            payload.get("pnl"),
            payload.get("realized_pnl"),
            meta.get("pnl"),
        )
    )
    fee = _to_float(
        _first(
            row.get("fee"),
            row.get("fees"),
            row.get("commission"),
            payload.get("fee"),
            meta.get("fee"),
        )
    )

    ts_raw = _first(
        row.get("closed_at"),
        row.get("ts"),
        row.get("timestamp"),
        row.get("updated_at"),
        row.get("time"),
        payload.get("ts"),
        meta.get("ts"),
    )

    if isinstance(ts_raw, (int, float)):
        closed_at = datetime.utcfromtimestamp(float(ts_raw)).isoformat()
        sort_ts = float(ts_raw)
    else:
        closed_at = _to_iso(ts_raw)
        sort_ts = 0.0

    return {
        "id": _first(row.get("id"), row.get("trade_id"), idx),
        "symbol": _first(
            row.get("symbol"),
            row.get("pair"),
            signal.get("symbol"),
            payload.get("symbol"),
            meta.get("symbol"),
            "",
        ),
        "side": _first(
            row.get("side"),
            row.get("action"),
            row.get("direction"),
            signal.get("side"),
            payload.get("side"),
            meta.get("side"),
        ),
        "qty": qty,
        "price": price,
        "pnl": pnl,
        "fee": fee,
        "closed_at": closed_at,
        "note": _first(row.get("note"), row.get("reason"), row.get("status"), meta.get("note"), ""),
        "source": "trades_latest",
        "_sort_ts": sort_ts,
    }


def _fallback_recent_trades(limit: int, symbol: Optional[str]) -> list[dict[str, Any]]:
    rows = _read_trades_latest()
    items = [_normalize_fallback_row(row, idx) for idx, row in enumerate(rows, start=1)]

    if symbol:
        want = _clean_symbol(symbol)
        items = [x for x in items if _clean_symbol(x.get("symbol")) == want]

    items.sort(
        key=lambda x: (
            _to_int(x.get("_sort_ts"), 0),
            _to_int(x.get("id"), 0),
        ),
        reverse=True,
    )

    out = []
    for item in items[:limit]:
        item.pop("_sort_ts", None)
        out.append(item)
    return out


@router.get(
    "/recent",
    summary="최근 체결 내역",
    description="최근 체결(또는 종료된 트레이드) 목록을 반환합니다.",
)
def get_recent_trades(
    limit: int = Query(50, ge=1, le=500, description="최대 반환 개수 (1~500)"),
    symbol: Optional[str] = Query(None, description="심볼 필터 (예: BTC-USDT)"),
    db: Session = Depends(get_db),
):
    try:
        tbl = _resolve_trades_table(db)
    except HTTPException:
        return _fallback_recent_trades(limit=limit, symbol=symbol)

    base_sql = f"""
        SELECT
            id,
            symbol,
            side,
            qty,
            price,
            pnl,
            fee,
            closed_at,
            note
        FROM {tbl}
    """

    where = []
    params: dict[str, Any] = {"limit": limit}
    if symbol:
        where.append("symbol = :symbol")
        params["symbol"] = symbol

    if where:
        base_sql += " WHERE " + " AND ".join(where)

    base_sql += """
        ORDER BY
            (closed_at IS NULL) ASC,
            closed_at DESC,
            id DESC
        LIMIT :limit
    """

    try:
        rows = db.execute(text(base_sql), params).mappings().all()
    except SQLAlchemyError:
        return _fallback_recent_trades(limit=limit, symbol=symbol)

    results = []
    for r in rows:
        results.append(
            {
                "id": r.get("id"),
                "symbol": r.get("symbol"),
                "side": r.get("side"),
                "qty": _to_float(r.get("qty")),
                "price": _to_float(r.get("price")),
                "pnl": _to_float(r.get("pnl")),
                "fee": _to_float(r.get("fee")),
                "closed_at": _to_iso(r.get("closed_at")),
                "note": r.get("note"),
                "source": "trades_db",
            }
        )
    return results


NULL_ERROR_CONTRACT_MARKER = NULL_ERROR_CONTRACT_VERSION
