from __future__ import annotations
from backend.contracts.null_error_contract import NULL_ERROR_CONTRACT_VERSION

import asyncio
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

try:
    from backend.engine.market_data_service import MARKET_DATA_SERVICE  # type: ignore
except Exception:  # pragma: no cover
    from engine.market_data_service import MARKET_DATA_SERVICE  # type: ignore

router = APIRouter(prefix="/api/v1/market", tags=["market"])

DATA_ROOT = Path(os.getenv("Z_DATA_ROOT", "/home/z/z/backend/data"))
SETTINGS_FILE = DATA_ROOT / "settings" / "lbot_settings.json"
STATE_FILE = Path(os.getenv("Z_STATE_FILE", "/home/z/z/backend/state.json"))

WATCHLIST: List[str] = [x.strip().upper() for x in os.getenv("MARKET_WATCHLIST", "BTC,ETH,SOL,LINK,XRP").split(",") if x.strip()]
DEFAULT_EXCHANGE = os.getenv("MARKET_EXCHANGE", "bingx").strip().lower() or "bingx"
DEFAULT_TIMEFRAME = os.getenv("MARKET_TIMEFRAME", "1h").strip().lower() or "1h"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        if path.exists():
            raw = path.read_text(encoding="utf-8").strip()
            if raw:
                obj = json.loads(raw)
                if isinstance(obj, dict):
                    return obj
    except Exception:
        pass
    return {}


def _to_feed_symbol(symbol: str) -> str:
    s = (symbol or "").strip().upper()
    if not s:
        return "BTC-USDT"
    if "-" in s:
        return s
    if "/" in s:
        return s.replace("/", "-")
    if s.endswith("USDT"):
        return s[:-4] + "-USDT"
    return f"{s}-USDT"


def _as_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


def _closes_to_sparkline(candles: List[Any], fallback_last: float = 0.0) -> List[float]:
    out: List[float] = []
    for c in candles[-7:]:
        if isinstance(c, dict):
            out.append(_as_float(c.get("cl") or c.get("close") or c.get("last"), 0.0))
        else:
            try:
                out.append(_as_float(getattr(c, "cl")))
            except Exception:
                pass
    out = [x for x in out if x > 0]
    if not out and fallback_last > 0:
        out = [fallback_last] * 7
    return out[-7:]


def _compute_change_pct(last_price: float, sparkline: List[float], ticker_extra: Dict[str, Any]) -> float:
    direct = _as_float(
        ticker_extra.get("priceChangePercent")
        or ticker_extra.get("price_change_pct")
        or ticker_extra.get("changePercent"),
        0.0,
    )
    if direct != 0.0:
        return round(direct, 2)

    if len(sparkline) >= 2 and sparkline[0] > 0:
        return round(((last_price - sparkline[0]) / sparkline[0]) * 100.0, 2)

    return 0.0


def _swing_pct(values: List[float]) -> float:
    if not values:
        return 0.0
    lo = min(values)
    hi = max(values)
    if lo <= 0:
        return 0.0
    return ((hi - lo) / lo) * 100.0


def _compute_regime(last_price: float, sparkline: List[float], change_pct: float) -> str:
    if len(sparkline) < 2:
        return "weak"

    first = sparkline[0]
    last = sparkline[-1]
    swing = _swing_pct(sparkline)
    up = last > first

    if change_pct <= -1.5 and not up:
        return "risk-off"
    if change_pct >= 1.5 and last >= max(sparkline[:-1]):
        return "breakout"
    if abs(change_pct) <= 0.9 and swing <= 2.0:
        return "range"
    if up and change_pct > 0:
        return "trend"
    return "weak"


def _status_for(regime: str, kill_switch: bool) -> str:
    if kill_switch:
        return "block"
    if regime == "risk-off":
        return "block"
    if regime in {"range", "breakout"}:
        return "warn"
    return "safe"


def _action_for(regime: str, status: str) -> str:
    if status == "block":
        return "hold"
    if regime == "trend":
        return "enter"
    if regime == "breakout":
        return "add"
    if regime == "range":
        return "reduce"
    return "hold"


def _confidence_for(regime: str, status: str) -> int:
    base = {
        "trend": 78,
        "breakout": 71,
        "range": 66,
        "weak": 59,
        "risk-off": 42,
    }.get(regime, 55)

    if status == "warn":
        base -= 5
    if status == "block":
        base -= 18
    return max(20, min(95, int(base)))


def _load_runtime_flags() -> Dict[str, Any]:
    settings = _read_json(SETTINGS_FILE)
    state = _read_json(STATE_FILE)

    mode = str(settings.get("mode") or state.get("mode") or "live").lower()
    route = str(settings.get("route") or state.get("route") or "paper").lower()
    exchange_enabled = bool(settings.get("exchange_enabled") or state.get("exchange_enabled") or False)
    kill_switch = bool(settings.get("kill_switch") or state.get("kill_switch") or False)

    ingress = "safe" if bool(state) else "warn"
    runtime = "block" if kill_switch else ("safe" if exchange_enabled and route == "live" else "warn")
    panel_state = "safe" if (state.get("status") or "ready") == "ready" else "warn"
    control = "block" if kill_switch else ("warn" if route != "live" else "safe")

    overall = "SAFE"
    if "block" in {ingress, runtime, panel_state, control}:
        overall = "BLOCK"
    elif "warn" in {ingress, runtime, panel_state, control}:
        overall = "WARN"

    return {
        "mode": mode,
        "route": route,
        "kill_switch": kill_switch,
        "exchange_enabled": exchange_enabled,
        "panels": {
            "ingress": ingress,
            "runtime": runtime,
            "state": panel_state,
            "control": control,
        },
        "overall": overall,
        "last_signal_ts": str(state.get("last_signal_ts") or state.get("signal_id") or settings.get("updated_at") or ""),
    }


def _item_from_live(symbol: str, flags: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    feed_symbol = _to_feed_symbol(symbol)

    ticker = (
        MARKET_DATA_SERVICE.feed.get_latest_ticker(DEFAULT_EXCHANGE, feed_symbol)
        or MARKET_DATA_SERVICE.feed.get_latest_ticker("dummy", feed_symbol)
    )
    candles = MARKET_DATA_SERVICE.feed.get_candles(DEFAULT_EXCHANGE, feed_symbol, DEFAULT_TIMEFRAME, limit=7)
    if not candles:
        candles = MARKET_DATA_SERVICE.feed.get_candles("dummy", feed_symbol, DEFAULT_TIMEFRAME, limit=7)

    if not ticker and not candles:
        return None

    ticker_extra: Dict[str, Any] = {}
    last_price = 0.0

    if isinstance(ticker, dict):
        last_price = _as_float(ticker.get("last") or ticker.get("price"), 0.0)
        ticker_extra = dict(ticker.get("extra") or {})
    else:
        try:
            last_price = _as_float(getattr(ticker, "last"), 0.0)
            ticker_extra = dict(getattr(ticker, "extra", {}) or {})
        except Exception:
            last_price = 0.0
            ticker_extra = {}

    sparkline = _closes_to_sparkline(candles, fallback_last=last_price)
    if last_price <= 0 and sparkline:
        last_price = sparkline[-1]

    if last_price <= 0:
        return None

    price_change_pct = _compute_change_pct(last_price, sparkline, ticker_extra)
    regime = _compute_regime(last_price, sparkline, price_change_pct)
    status = _status_for(regime, bool(flags["kill_switch"]))
    bot_action = _action_for(regime, status)
    confidence = _confidence_for(regime, status)

    # stats are currently UI-safe placeholders until strategy ledger wiring lands
    wins = {
        "trend": 23,
        "breakout": 14,
        "range": 11,
        "weak": 9,
        "risk-off": 9,
    }.get(regime, 10)
    losses = {
        "trend": 8,
        "breakout": 7,
        "range": 8,
        "weak": 9,
        "risk-off": 9,
    }.get(regime, 8)
    win_rate = round((wins / max(wins + losses, 1)) * 100.0, 1)
    pnl = round(price_change_pct * 1.2, 2)
    mdd = round(-max(0.8, min(12.0, _swing_pct(sparkline) * 0.9)), 2)

    src = ticker_extra.get("provider") or "bingx_public"

    return {
        "symbol": symbol,
        "price": round(last_price, 4) if last_price < 100 else round(last_price, 2),
        "priceChangePct": round(price_change_pct, 2),
        "price_change_24h": round(price_change_pct, 2),
        "regime": regime,
        "botAction": bot_action,
        "bot_action": bot_action,
        "confidence": confidence,
        "winRate": win_rate,
        "win_rate": win_rate,
        "wins": wins,
        "losses": losses,
        "pnl": pnl,
        "mdd": mdd,
        "route": flags["route"],
        "mode": flags["mode"],
        "routeMode": f'{flags["mode"]}/{flags["route"]}',
        "route_mode": f'{flags["mode"]}/{flags["route"]}',
        "status": status,
        "sparkline": sparkline,
        "reason": "kill_switch_triggered" if flags["kill_switch"] else f"market_feed:{regime}",
        "lastSignalTs": flags["last_signal_ts"],
        "last_signal_ts": flags["last_signal_ts"],
        "updatedAt": _now_iso(),
        "updated_at": _now_iso(),
        "source": "mixed" if src == "bingx_public" else src,
        "marketSource": src,
        "statsSource": "placeholder",
    }


def _mock_item(symbol: str, flags: Dict[str, Any]) -> Dict[str, Any]:
    base_map = {
        "BTC": 66000.0,
        "ETH": 3200.0,
        "SOL": 180.0,
        "LINK": 22.0,
        "XRP": 0.72,
    }
    base = base_map.get(symbol, 100.0)
    spark = [round(base * x, 4) for x in (0.98, 1.00, 1.01, 1.03, 1.02, 1.05, 1.06)]
    regime = "trend"
    status = _status_for(regime, bool(flags["kill_switch"]))
    action = _action_for(regime, status)

    return {
        "symbol": symbol,
        "price": round(base * 1.01, 4) if base < 100 else round(base * 1.01, 2),
        "priceChangePct": 1.0,
        "price_change_24h": 1.0,
        "regime": regime,
        "botAction": action,
        "bot_action": action,
        "confidence": 55,
        "winRate": 60,
        "win_rate": 60,
        "wins": 12,
        "losses": 8,
        "pnl": 1.2,
        "mdd": -3.5,
        "route": flags["route"],
        "mode": flags["mode"],
        "routeMode": f'{flags["mode"]}/{flags["route"]}',
        "route_mode": f'{flags["mode"]}/{flags["route"]}',
        "status": status,
        "sparkline": spark,
        "reason": "fallback_mock",
        "lastSignalTs": flags["last_signal_ts"],
        "last_signal_ts": flags["last_signal_ts"],
        "updatedAt": _now_iso(),
        "updated_at": _now_iso(),
        "source": "mock",
        "marketSource": "mock",
        "statsSource": "placeholder",
    }


async def _build_cards_payload() -> Dict[str, Any]:
    flags = _load_runtime_flags()
    MARKET_DATA_SERVICE.set_watchlist(WATCHLIST, exchange=DEFAULT_EXCHANGE, timeframe=DEFAULT_TIMEFRAME)

    try:
        await MARKET_DATA_SERVICE.sync_once()
    except Exception:
        pass

    items: List[Dict[str, Any]] = []
    any_real = False
    for symbol in WATCHLIST:
        item = _item_from_live(symbol, flags)
        if item is None:
            item = _mock_item(symbol, flags)
        else:
            if str(item.get("marketSource")) == "bingx_public":
                any_real = True
        items.append(item)

    top_source = "mixed" if any_real else "mock"

    return {
        "watchlist": WATCHLIST,
        "items": items,
        "overall": flags["overall"],
        "panels": flags["panels"],
        "updatedAt": _now_iso(),
        "updated_at": _now_iso(),
        "source": top_source,
    }


@router.get("/cards")
async def market_cards() -> Dict[str, Any]:
    return await _build_cards_payload()


@router.get("/stream")
async def market_stream(
    interval: float = Query(default=4.0, ge=2.0, le=30.0),
) -> StreamingResponse:
    async def event_gen() -> AsyncIterator[str]:
        while True:
            payload = await _build_cards_payload()
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            await asyncio.sleep(interval)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

NULL_ERROR_CONTRACT_MARKER = NULL_ERROR_CONTRACT_VERSION
