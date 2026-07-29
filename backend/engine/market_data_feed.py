from __future__ import annotations

import asyncio
import math
import random
import time
from typing import Any, Dict, List, Optional, Tuple


def _now_ms() -> int:
    return int(time.time() * 1000)


def _as_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


def _norm_exchange(exchange: str) -> str:
    return (exchange or "dummy").strip().lower()


def _norm_symbol(symbol: str) -> str:
    s = (symbol or "").strip().upper()
    if not s:
        return "BTC-USDT"
    if "/" in s:
        return s.replace("/", "-")
    return s


def _norm_timeframe(tf: str) -> str:
    s = (tf or "1h").strip().lower()
    allowed = {"1m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d", "1w"}
    return s if s in allowed else "1h"


class DummyAdapter:
    """
    외부 의존성 없는 mock adapter.
    백엔드가 죽지 않도록 항상 fallback 가능.
    """
    name = "dummy"

    def _seed(self, symbol: str) -> int:
        return sum(ord(c) for c in _norm_symbol(symbol))

    async def fetch_candles(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        n = max(7, min(int(limit or 7), 500))
        seed = self._seed(symbol)
        rnd = random.Random(seed + int(time.time() // 60))

        base_map = {
            "BTC-USDT": 66000.0,
            "ETH-USDT": 3200.0,
            "SOL-USDT": 180.0,
            "LINK-USDT": 22.0,
            "XRP-USDT": 0.72,
        }
        sym = _norm_symbol(symbol)
        base = base_map.get(sym, 100.0 + (seed % 2000))

        out: List[Dict[str, Any]] = []
        last = base

        step_ms_map = {
            "1m": 60_000,
            "5m": 300_000,
            "15m": 900_000,
            "30m": 1_800_000,
            "1h": 3_600_000,
            "2h": 7_200_000,
            "4h": 14_400_000,
            "6h": 21_600_000,
            "8h": 28_800_000,
            "12h": 43_200_000,
            "1d": 86_400_000,
            "3d": 259_200_000,
            "1w": 604_800_000,
        }
        step_ms = step_ms_map.get(_norm_timeframe(timeframe), 3_600_000)
        ts = _now_ms() - (n * step_ms)

        for i in range(n):
            drift = math.sin((i + seed % 9) / 3.0) * 0.006
            noise = rnd.uniform(-0.003, 0.003)
            change = drift + noise

            op = last
            cl = max(0.0001, op * (1 + change))
            hi = max(op, cl) * (1 + rnd.uniform(0.0005, 0.004))
            lo = min(op, cl) * (1 - rnd.uniform(0.0005, 0.004))
            vol = abs(cl - op) * rnd.uniform(80, 300)

            out.append(
                {
                    "ts": ts + (i * step_ms),
                    "op": round(op, 8),
                    "hi": round(hi, 8),
                    "lo": round(lo, 8),
                    "cl": round(cl, 8),
                    "vol": round(vol, 8),
                }
            )
            last = cl

        return out

    async def get_latest_ticker(self, symbol: str) -> Dict[str, Any]:
        candles = await self.fetch_candles(symbol, "1h", limit=7)
        last = _as_float(candles[-1]["cl"], 0.0)
        prev = _as_float(candles[-2]["cl"], last) if len(candles) >= 2 else last
        change_pct = 0.0 if prev <= 0 else ((last - prev) / prev) * 100.0

        spread = max(last * 0.0002, 0.0001)
        return {
            "ts": _now_ms(),
            "bid": round(last - spread, 8),
            "ask": round(last + spread, 8),
            "last": round(last, 8),
            "vol": round(sum(_as_float(c["vol"], 0.0) for c in candles), 8),
            "extra": {
                "symbol": _norm_symbol(symbol),
                "priceChangePercent": round(change_pct, 4),
                "provider": "dummy",
            },
        }


class MarketDataFeed:
    """
    단일 프로세스 인메모리 market cache.

    기대 인터페이스:
    - register_adapter(adapter)
    - await sync_symbol(exchange, symbol, timeframe, limit=32)
    - get_latest_ticker(exchange, symbol)
    - get_candles(exchange, symbol, timeframe, limit=7)
    """

    def __init__(self, max_candles: int = 500) -> None:
        self.max_candles = max(20, int(max_candles or 500))
        self._adapters: Dict[str, Any] = {}
        self._ticker_cache: Dict[Tuple[str, str], Dict[str, Any]] = {}
        self._candle_cache: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = {}
        self._lock = asyncio.Lock()

    def register_adapter(self, adapter: Any) -> None:
        name = getattr(adapter, "name", None)
        if not name:
            raise ValueError("adapter.name is required")
        self._adapters[_norm_exchange(str(name))] = adapter

    def has_adapter(self, exchange: str) -> bool:
        return _norm_exchange(exchange) in self._adapters

    def get_adapter(self, exchange: str) -> Any:
        key = _norm_exchange(exchange)
        if key in self._adapters:
            return self._adapters[key]
        if "dummy" in self._adapters:
            return self._adapters["dummy"]
        raise KeyError(f"adapter not found: {exchange}")

    async def sync_symbol(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        limit: int = 100,
    ) -> None:
        ex = _norm_exchange(exchange)
        sym = _norm_symbol(symbol)
        tf = _norm_timeframe(timeframe)

        adapter = self.get_adapter(ex)

        candles = await adapter.fetch_candles(sym, tf, limit=limit)
        ticker = await adapter.get_latest_ticker(sym)

        if not isinstance(candles, list):
            candles = []
        if not isinstance(ticker, dict):
            ticker = {}

        normalized_candles: List[Dict[str, Any]] = []
        for row in candles[-self.max_candles:]:
            if not isinstance(row, dict):
                continue
            normalized_candles.append(
                {
                    "ts": row.get("ts") or row.get("time") or row.get("timestamp") or _now_ms(),
                    "op": _as_float(row.get("op") or row.get("open") or row.get("o"), 0.0),
                    "hi": _as_float(row.get("hi") or row.get("high") or row.get("h"), 0.0),
                    "lo": _as_float(row.get("lo") or row.get("low") or row.get("l"), 0.0),
                    "cl": _as_float(row.get("cl") or row.get("close") or row.get("c"), 0.0),
                    "vol": _as_float(row.get("vol") or row.get("volume") or row.get("v"), 0.0),
                }
            )

        normalized_ticker = {
            "ts": ticker.get("ts") or ticker.get("time") or ticker.get("timestamp") or _now_ms(),
            "bid": _as_float(ticker.get("bid"), 0.0),
            "ask": _as_float(ticker.get("ask"), 0.0),
            "last": _as_float(ticker.get("last") or ticker.get("price"), 0.0),
            "vol": _as_float(ticker.get("vol") or ticker.get("volume"), 0.0),
            "extra": dict(ticker.get("extra") or {}),
        }

        async with self._lock:
            self._candle_cache[(ex, sym, tf)] = normalized_candles
            self._ticker_cache[(ex, sym)] = normalized_ticker

    def set_ticker(self, exchange: str, symbol: str, ticker: Dict[str, Any]) -> None:
        ex = _norm_exchange(exchange)
        sym = _norm_symbol(symbol)
        self._ticker_cache[(ex, sym)] = {
            "ts": ticker.get("ts") or _now_ms(),
            "bid": _as_float(ticker.get("bid"), 0.0),
            "ask": _as_float(ticker.get("ask"), 0.0),
            "last": _as_float(ticker.get("last"), 0.0),
            "vol": _as_float(ticker.get("vol"), 0.0),
            "extra": dict(ticker.get("extra") or {}),
        }

    def set_candles(self, exchange: str, symbol: str, timeframe: str, candles: List[Dict[str, Any]]) -> None:
        ex = _norm_exchange(exchange)
        sym = _norm_symbol(symbol)
        tf = _norm_timeframe(timeframe)
        out: List[Dict[str, Any]] = []
        for row in candles[-self.max_candles:]:
            if not isinstance(row, dict):
                continue
            out.append(
                {
                    "ts": row.get("ts") or _now_ms(),
                    "op": _as_float(row.get("op"), 0.0),
                    "hi": _as_float(row.get("hi"), 0.0),
                    "lo": _as_float(row.get("lo"), 0.0),
                    "cl": _as_float(row.get("cl"), 0.0),
                    "vol": _as_float(row.get("vol"), 0.0),
                }
            )
        self._candle_cache[(ex, sym, tf)] = out

    def get_latest_ticker(self, exchange: str, symbol: str) -> Optional[Dict[str, Any]]:
        ex = _norm_exchange(exchange)
        sym = _norm_symbol(symbol)
        return self._ticker_cache.get((ex, sym))

    def get_candles(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        limit: int = 7,
    ) -> List[Dict[str, Any]]:
        ex = _norm_exchange(exchange)
        sym = _norm_symbol(symbol)
        tf = _norm_timeframe(timeframe)
        rows = self._candle_cache.get((ex, sym, tf), [])
        if limit <= 0:
            return list(rows)
        return list(rows[-limit:])


if __name__ == "__main__":
    async def _demo() -> None:
        feed = MarketDataFeed()
        feed.register_adapter(DummyAdapter())
        await feed.sync_symbol("dummy", "BTC-USDT", "1h", limit=12)
        print(feed.get_latest_ticker("dummy", "BTC-USDT"))
        print(feed.get_candles("dummy", "BTC-USDT", "1h", limit=3))

    asyncio.run(_demo())