from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter

try:
    from engine.change12_projection import build_delta_feed, build_projection
except ImportError:  # pragma: no cover
    from backend.engine.change12_projection import build_delta_feed, build_projection

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

BASE_DIR = Path(os.getenv("Z_BACKEND_BASE_DIR", "/home/z/z/backend"))
TRADE_STATE_PATH = Path(os.getenv("Z_TRADE_STATE_PATH", str(BASE_DIR / "trade_state.json")))
STATE_PATH = Path(os.getenv("Z_STATE_PATH", str(BASE_DIR / "state.json")))
JOURNAL_LATEST = Path(os.getenv("Z_JOURNAL_LATEST", str(BASE_DIR / "data" / "journal" / "lbot_event.latest.json")))

FIXED_WATCHLIST = ["BTC", "ETH", "SOL", "XRP", "LINK"]


def _safe_str(v: Any, default: str = "") -> str:
    if v is None:
        return default
    try:
        s = str(v).strip()
        return s if s else default
    except Exception:
        return default


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        if v in (None, ""):
            return default
        return float(v)
    except Exception:
        return default


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        if v in (None, ""):
            return default
        return int(float(v))
    except Exception:
        return default


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        if not path.exists():
            return {}
        raw = path.read_text(encoding="utf-8").strip()
        if not raw:
            return {}
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _source_ts(path: Path) -> Optional[int]:
    try:
        return int(path.stat().st_mtime * 1000)
    except Exception:
        return None


def _trade_state() -> Dict[str, Any]:
    obj = _read_json(TRADE_STATE_PATH)
    return obj if isinstance(obj, dict) else {}


def _state_snapshot() -> Dict[str, Any]:
    obj = _read_json(STATE_PATH)
    if isinstance(obj.get("state"), dict):
        base = dict(obj.get("state") or {})
        if obj.get("status") is not None and base.get("status") is None:
            base["status"] = obj.get("status")
        if obj.get("ts") is not None and base.get("source_ts") is None:
            base["source_ts"] = obj.get("ts")
        return base
    return obj if isinstance(obj, dict) else {}


def _journal_latest() -> Dict[str, Any]:
    obj = _read_json(JOURNAL_LATEST)
    return obj if isinstance(obj, dict) else {}


def _decision_id() -> Optional[str]:
    trade = _trade_state()
    journal = _journal_latest()
    return (
        _safe_str(trade.get("decision_id"))
        or _safe_str(journal.get("decision_id"))
        or _safe_str((journal.get("journal_event") or {}).get("decision_id") if isinstance(journal.get("journal_event"), dict) else "")
        or None
    )


def _common_contract(contract_version: str) -> Dict[str, Any]:
    trade = _trade_state()
    state = _state_snapshot()
    source_ts = trade.get("source_ts") or trade.get("_source_ts") or state.get("source_ts") or _source_ts(TRADE_STATE_PATH) or _source_ts(STATE_PATH)
    source = trade.get("source") or trade.get("_source") or f"json:{TRADE_STATE_PATH}"
    return {
        "contract_version": contract_version,
        "source": source,
        "source_ts": source_ts,
        "stale": False,
        "stale_ms": 0,
        "reconcile_status": _safe_str(trade.get("reconcile_status"), "ok"),
        "decision_id": _decision_id(),
    }


def _latest_signal() -> Dict[str, Any]:
    trade = _trade_state()
    items = trade.get("signals")
    if isinstance(items, list) and items:
        row = items[0]
        return row if isinstance(row, dict) else {}
    return {}


def _latest_trade() -> Dict[str, Any]:
    trade = _trade_state()
    items = trade.get("recent_trades")
    if isinstance(items, list) and items:
        row = items[0]
        return row if isinstance(row, dict) else {}
    last_fill = trade.get("last_fill")
    return last_fill if isinstance(last_fill, dict) else {}


def _watchers(state: Dict[str, Any]) -> List[str]:
    watchers = state.get("watchers")
    if isinstance(watchers, list):
        return [str(x) for x in watchers]
    return []


def _active_team_payload() -> Dict[str, Any]:
    state = _state_snapshot()
    trade = _trade_state()
    signal = _latest_signal()
    last_trade = _latest_trade()
    journal = _journal_latest()
    journal_event = journal.get("journal_event") if isinstance(journal.get("journal_event"), dict) else {}

    mode = _safe_str(signal.get("mode") or last_trade.get("mode") or trade.get("mode") or state.get("mode"), "paper")
    active = {
        "name": _safe_str(state.get("team"), "ALPHA"),
        "selected": True,
        "score": _safe_float(state.get("score"), 0.8562),
        "health": _safe_str(state.get("health"), "ok"),
        "mode": mode,
        "lead": _safe_str(state.get("lead"), "LBot"),
        "support": _safe_str(state.get("support"), "MBot"),
        "conditional_helper": _safe_str(state.get("conditional_helper"), "OBot"),
        "watchers": _watchers(state) or ["regime", "risk_decay", "venue"],
        "why": state.get("why") if isinstance(state.get("why"), list) else [ _safe_str(journal.get("result_reason") or journal_event.get("decision_reason") or last_trade.get("reason"), "enter") ],
        "warnings": state.get("warnings") if isinstance(state.get("warnings"), list) else [],
        "next_candidate": state.get("next_candidate"),
        "helper_trigger": bool(state.get("helper_trigger", False)),
    }

    out = _common_contract("dashboard.active_team.v1")
    out.update(
        {
            "active_team": active,
            "why_not_now": _safe_str(state.get("why_not_now"), ""),
            "next_candidate": state.get("next_candidate"),
            "team_health": _safe_str(state.get("health"), "ok"),
            "watcher_consensus": _safe_str(state.get("consensus") or state.get("watcher_consensus"), "unknown"),
            "helper_trigger": bool(state.get("helper_trigger", False)),
        }
    )
    return out


def _market_card_for(symbol: str) -> Dict[str, Any]:
    state = _state_snapshot()
    trade = _trade_state()
    all_signals = trade.get("signals") if isinstance(trade.get("signals"), list) else []
    all_trades = trade.get("recent_trades") if isinstance(trade.get("recent_trades"), list) else []

    target = symbol.upper() + "USDT"
    signal = next((row for row in all_signals if isinstance(row, dict) and _safe_str(row.get("symbol")).upper() == target), {})
    recent = next((row for row in all_trades if isinstance(row, dict) and _safe_str(row.get("symbol")).upper() == target), {})

    route = _safe_str(signal.get("route") or recent.get("route"), "paper")
    mode = _safe_str(signal.get("mode") or recent.get("mode"), "paper")
    status = _safe_str(signal.get("status") or recent.get("status"), "unknown")
    action = _safe_str(signal.get("decision_action") or recent.get("decision_action"), "hold")
    reason = _safe_str(signal.get("reason") or recent.get("reason"), "")

    return {
        "symbol": symbol.upper(),
        "price": _safe_float(signal.get("price") or recent.get("price"), 0.0),
        "priceChangePct": 0.0,
        "price_change_24h": 0.0,
        "regime": _safe_str(state.get("regime"), "unknown"),
        "botAction": action,
        "bot_action": action,
        "confidence": _safe_int(state.get("confirm_score"), 0),
        "winRate": 0.0,
        "win_rate": 0.0,
        "wins": 0,
        "losses": 0,
        "pnl": 0.0,
        "mdd": 0.0,
        "route": route,
        "mode": mode,
        "routeMode": f"{route}/{mode}",
        "route_mode": f"{route}/{mode}",
        "status": status,
        "reason": reason,
        "sparkline": [],
    }


def _market_cards_payload() -> Dict[str, Any]:
    out = _common_contract("dashboard.market_cards.v1")
    items = [_market_card_for(sym) for sym in FIXED_WATCHLIST]
    out.update(
        {
            "watchlist": FIXED_WATCHLIST,
            "count": len(items),
            "items": items,
        }
    )
    return out


def _change12_runtime() -> Dict[str, Any]:
    state = _state_snapshot()
    trade = _trade_state()
    merged: Dict[str, Any] = {}
    merged.update(state or {})
    merged.update(trade or {})
    projection = build_projection(merged)
    delta = build_delta_feed(merged, persist=True)
    return {"state": state, "trade": trade, "projection": projection, "delta": delta}


def _summary_payload() -> Dict[str, Any]:
    runtime = _change12_runtime()
    state = runtime["state"]
    trade = runtime["trade"]
    projection = runtime["projection"]

    positions = trade.get("positions")
    if isinstance(positions, dict):
        position_count = len(positions)
    elif isinstance(positions, list):
        position_count = len(positions)
    else:
        position_count = 0

    pending_orders = trade.get("pending_orders")
    pending_count = len(pending_orders) if isinstance(pending_orders, list) else 0

    recent = trade.get("recent_trades")
    recent_count = len(recent) if isinstance(recent, list) else 0

    portfolio = {
        "equity_usdt": _safe_float(state.get("equity_usdt"), 0.0),
        "day_pnl_usdt": _safe_float(state.get("day_pnl_usdt"), 0.0),
        "max_dd_usdt": _safe_float(state.get("max_dd_usdt"), 0.0),
        "position_count": position_count,
        "pending_order_count": pending_count,
        "recent_trade_count": recent_count,
    }
    segment = {
        "mode": _safe_str(state.get("mode"), _safe_str(trade.get("mode"), "paper")),
        "regime": _safe_str(state.get("regime"), "unknown"),
        "mood": _safe_str(state.get("mood"), "unknown"),
        "consensus": _safe_str(state.get("consensus"), "unknown"),
        "venue_health": _safe_str(state.get("venue_health"), "unknown"),
    }
    watcher_summary = {
        "regime": _safe_str(state.get("regime"), "unknown"),
        "consensus": _safe_str(state.get("consensus"), "unknown"),
        "venue_health": _safe_str(state.get("venue_health"), "unknown"),
    }

    out = _common_contract("dashboard.summary.v1")
    out.update(
        {
            "portfolio": portfolio,
            "segment": segment,
            "watcher_summary": watcher_summary,
            "health": _safe_str(state.get("health"), "ok"),
            "trust_rail": projection.get("trust_rail"),
            "decision_sheet": projection.get("decision_sheet"),
            "alert_ladder": projection.get("alert_ladder"),
            "change_digest": projection.get("change_digest"),
            "backend_ver": projection.get("backend_ver"),
            "missingness": projection.get("missingness"),
            "counterfactual": projection.get("counterfactual"),
            "recovery_path": projection.get("recovery_path"),
        }
    )
    return out


@router.get("/active-team")
def dashboard_active_team():
    return _active_team_payload()


@router.get("/market-cards")
def dashboard_market_cards():
    return _market_cards_payload()


@router.get("/summary")
def dashboard_summary():
    return _summary_payload()


@router.get("/delta")
def dashboard_delta():
    return _change12_runtime()["delta"]
