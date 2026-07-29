from __future__ import annotations
from backend.contracts.null_error_contract import NULL_ERROR_CONTRACT_VERSION, normalize_collection_response
from backend.contracts.frontend_bridge_contract import enrich_frontend_bridge

from typing import Optional

from fastapi import APIRouter, Query

from backend.engine.journal_reader import (
    build_journal_bundle,
    build_journal_summary,
    get_daily_equity_log,
    get_daily_sync_log,
    get_dd_curve,
    get_dd_curve_latest,
    get_equity_curve,
    get_equity_curve_latest,
    get_sync_notes,
    get_trade_notes,
)

router = APIRouter(prefix="/api/v1/journal", tags=["journal"])


@router.get("/health")
def journal_health() -> dict:
    return {"ok": True, "service": "journal_api"}


@router.get("/summary")
def journal_summary(
    day: Optional[str] = Query(default=None, description="YYYYMMDD"),
) -> dict:
    return build_journal_summary(day=day)


@router.get("/bundle")
def journal_bundle(
    day: Optional[str] = Query(default=None, description="YYYYMMDD"),
    limit: int = Query(default=100, ge=1, le=5000),
) -> dict:
    return build_journal_bundle(day=day, limit=limit)


@router.get("/equity-curve/latest")
def journal_equity_curve_latest() -> dict:
    return get_equity_curve_latest()


@router.get("/dd-curve/latest")
def journal_dd_curve_latest() -> dict:
    return get_dd_curve_latest()


@router.get("/equity-curve")
def journal_equity_curve(
    day: Optional[str] = Query(default=None, description="YYYYMMDD"),
    limit: int = Query(default=100, ge=1, le=5000),
) -> dict:
    rows = get_equity_curve(day=day, limit=limit)
    payload = normalize_collection_response(rows)
    payload["day"] = day
    return enrich_frontend_bridge(payload, source="journal_equity_curve")


@router.get("/dd-curve")
def journal_dd_curve(
    day: Optional[str] = Query(default=None, description="YYYYMMDD"),
    limit: int = Query(default=100, ge=1, le=5000),
) -> dict:
    rows = get_dd_curve(day=day, limit=limit)
    payload = normalize_collection_response(rows)
    payload["day"] = day
    return enrich_frontend_bridge(payload, source="journal_dd_curve")


@router.get("/sync-notes")
def journal_sync_notes(
    day: Optional[str] = Query(default=None, description="YYYYMMDD"),
    limit: int = Query(default=100, ge=1, le=5000),
) -> dict:
    rows = get_sync_notes(day=day, limit=limit)
    payload = normalize_collection_response(rows)
    payload["day"] = day
    return enrich_frontend_bridge(payload, source="journal_sync_notes")


@router.get("/trade-notes")
def journal_trade_notes(
    day: Optional[str] = Query(default=None, description="YYYYMMDD"),
    limit: int = Query(default=100, ge=1, le=5000),
) -> dict:
    rows = get_trade_notes(day=day, limit=limit)
    payload = normalize_collection_response(rows)
    payload["day"] = day
    return enrich_frontend_bridge(payload, source="journal_trade_notes")


@router.get("/sync-log")
def journal_sync_log(
    day: Optional[str] = Query(default=None, description="YYYYMMDD"),
    limit: int = Query(default=100, ge=1, le=5000),
) -> dict:
    rows = get_daily_sync_log(day=day, limit=limit)
    payload = normalize_collection_response(rows)
    payload["day"] = day
    return enrich_frontend_bridge(payload, source="journal_sync_log")


@router.get("/equity-log")
def journal_equity_log(
    day: Optional[str] = Query(default=None, description="YYYYMMDD"),
    limit: int = Query(default=100, ge=1, le=5000),
) -> dict:
    rows = get_daily_equity_log(day=day, limit=limit)
    payload = normalize_collection_response(rows)
    payload["day"] = day
    return enrich_frontend_bridge(payload, source="journal_equity_log")


NULL_ERROR_CONTRACT_MARKER = NULL_ERROR_CONTRACT_VERSION
