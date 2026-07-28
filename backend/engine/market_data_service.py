from __future__ import annotations

import asyncio
import json
import logging
import os
import ssl
import urllib.parse
import urllib.request
from typing import Any, Dict, Iterable, List, Sequence, Tuple

from backend.engine.market_data_feed import MarketDataFeed, DummyAdapter

logger = logging.getLogger(__name__)

BINGX_OPEN_API_BASE = os.getenv("BINGX_OPEN_API_BASE", "https://open-api.bingx.com").rstrip("/")


def _as_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


def _norm_symbol(symbol: str) -> str:
    s = (symbol or "").strip().upper()
    if not s:
        return "BTC-USDT"
    if "/" in s:
        return s.replace("/", "-")
    if "-" in s:
        return s
    if s.endswith("USDT"):
        return s[:-4] + "-USDT"
    return f"{s}-USDT"


def _norm_timeframe(tf: str) -> str:
    s = (tf or "1h").strip().lower()
    mapping = {
        "1m": "1m",
        "5m": "5m",
        "15m": "15m",
        "30m": "30m",
        "1h": "1h",
        "2h": "2h",
        "4h": "4h",
        "6h": "6h",
        "8h": "8h",
        "12h": "12h",
        "1d": "1d",
        "3d": "3d",
        "1w": "1w",
    }
    return mapping.get(s, "1h")


class BingXPublicAdapter:
    name = "bingx"

    def __init__(self, base_url: str = BINGX_OPEN_API_BASE, timeout: float = 6.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = float(timeout)

    def _get_json(self, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        url = f"{self.base_url}{path}?{query}"
        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "z-os-market/1.0",
            },
        )

        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=self.timeout, context=ctx) as resp:
            raw = resp.read()
        return json.loads(raw.decode("utf-8"))

    def _extract_data(self, payload: Dict[str, Any]) -> Any:
        if not isinstance(payload, dict):
            return None
        data = payload.get("data")
        if data is None:
            return None
        if isinstance(data, dict):
            if "items" in data:
                return data.get("items")
            if "list" in data:
                return data.get("list")
            return data
        return data

    async def fetch_candles(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        norm_symbol = _norm_symbol(symbol)
        interval = _norm_timeframe(timeframe)
        n = max(7, min(int(limit or 7), 200))

        def _work() -> List[Dict[str, Any]]:
            payload = self._get_json(
                "/openApi/swap/v3/quote/klines",
                {
                    "symbol": norm_symbol,
                    "interval": interval,
                    "limit": n,
                },
            )
            data = self._extract_data(payload) or []
            out: List[Dict[str, Any]] = []

            if isinstance(data, list):
                for row in data:
                    if isinstance(row, (list, tuple)) and len(row) >= 6:
                        out.append(
                            {
                                "ts": row[0],
                                "op": row[1],
                                "hi": row[2],
                                "lo": row[3],
                                "cl": row[4],
                                "vol": row[5],
                            }
                        )
                    elif isinstance(row, dict):
                        out.append(
                            {
                                "ts": row.get("time") or row.get("ts") or row.get("timestamp"),
                                "op": row.get("open") or row.get("openPrice") or row.get("o"),
                                "hi": row.get("high") or row.get("highPrice") or row.get("h"),
                                "lo": row.get("low") or row.get("lowPrice") or row.get("l"),
                                "cl": row.get("close") or row.get("closePrice") or row.get("c"),
                                "vol": row.get("volume") or row.get("vol") or row.get("v") or 0,
                            }
                        )
            elif isinstance(data, dict):
                rows = data.get("candles") or data.get("items") or []
                if isinstance(rows, list):
                    for row in rows:
                        if isinstance(row, dict):
                            out.append(
                                {
                                    "ts": row.get("time") or row.get("ts") or row.get("timestamp"),
                                    "op": row.get("open") or row.get("openPrice") or row.get("o"),
                                    "hi": row.get("high") or row.get("highPrice") or row.get("h"),
                                    "lo": row.get("low") or row.get("lowPrice") or row.get("l"),
                                    "cl": row.get("close") or row.get("closePrice") or row.get("c"),
                                    "vol": row.get("volume") or row.get("vol") or row.get("v") or 0,
                                }
                            )

            return out

        return await asyncio.to_thread(_work)

    async def get_latest_ticker(self, symbol: str) -> Dict[str, Any]:
        norm_symbol = _norm_symbol(symbol)

        def _work() -> Dict[str, Any]:
            payload = self._get_json(
                "/openApi/swap/v2/quote/ticker",
                {
                    "symbol": norm_symbol,
                },
            )
            data = self._extract_data(payload)
            row: Dict[str, Any]

            if isinstance(data, list):
                row = data[0] if data else {}
            elif isinstance(data, dict):
                row = data
            else:
                row = {}

            last = row.get("lastPrice") or row.get("price") or row.get("last")
            price_change_pct = (
                row.get("priceChangePercent")
                or row.get("priceChangePercent24h")
                or row.get("change")
                or row.get("changePercent")
                or 0
            )
            bid = row.get("bidPrice") or row.get("bid") or last
            ask = row.get("askPrice") or row.get("ask") or last
            vol = row.get("volume") or row.get("vol") or row.get("quoteVolume") or 0

            return {
                "ts": row.get("time") or row.get("timestamp") or row.get("ts"),
                "bid": bid,
                "ask": ask,
                "last": last,
                "vol": vol,
                "extra": {
                    "symbol": norm_symbol,
                    "priceChangePercent": _as_float(price_change_pct),
                    "raw": row,
                    "provider": "bingx_public",
                },
            }

        return await asyncio.to_thread(_work)


DEFAULT_SYMBOLS: List[Tuple[str, str, str]] = [
    ("bingx", "BTC-USDT", "1h"),
    ("bingx", "ETH-USDT", "1h"),
    ("bingx", "SOL-USDT", "1h"),
    ("bingx", "LINK-USDT", "1h"),
    ("bingx", "XRP-USDT", "1h"),
]


def _env_default_symbols() -> List[Tuple[str, str, str]]:
    raw = os.getenv("MARKET_DEFAULT_SYMBOLS", "").strip()
    if not raw:
        return list(DEFAULT_SYMBOLS)

    exchange = (os.getenv("MARKET_EXCHANGE", "bingx") or "bingx").strip().lower()
    timeframe = _norm_timeframe(os.getenv("MARKET_TIMEFRAME", "1h"))

    items: List[Tuple[str, str, str]] = []
    for token in raw.split(","):
        s = token.strip().upper()
        if not s:
            continue
        items.append((exchange, _norm_symbol(s), timeframe))
    return items or list(DEFAULT_SYMBOLS)


class MarketDataService:
    def __init__(self, max_candles: int = 500) -> None:
        self.feed = MarketDataFeed(max_candles=max_candles)
        self.feed.register_adapter(DummyAdapter())

        try:
            self.feed.register_adapter(BingXPublicAdapter())
            logger.info("MarketDataService: bingx public adapter registered")
        except Exception as e:  # pragma: no cover
            logger.warning("MarketDataService: bingx public adapter disabled: %s", e)

        self._symbols: List[Tuple[str, str, str]] = _env_default_symbols()
        self._interval: float = float(os.getenv("MARKET_SYNC_INTERVAL_SEC", "6.0"))

    def set_symbols(self, symbols: Sequence[Tuple[str, str, str]]) -> None:
        self._symbols = list(symbols)

    def get_symbols(self) -> List[Tuple[str, str, str]]:
        return list(self._symbols)

    def set_watchlist(
        self,
        symbols: Iterable[str],
        exchange: str = "bingx",
        timeframe: str = "1h",
    ) -> None:
        next_symbols: List[Tuple[str, str, str]] = []
        for symbol in symbols:
            s = str(symbol).strip().upper()
            if not s:
                continue
            next_symbols.append((exchange, _norm_symbol(s), _norm_timeframe(timeframe)))
        if next_symbols:
            self._symbols = next_symbols

    def set_interval(self, interval_sec: float) -> None:
        self._interval = max(2.0, float(interval_sec))

    async def sync_once(self) -> None:
        for exchange, symbol, timeframe in self._symbols:
            try:
                await self.feed.sync_symbol(exchange, symbol, timeframe, limit=32)
                ticker = self.feed.get_latest_ticker(exchange, symbol)
                logger.info("mdfeed: %s %s %s ticker=%s", exchange, symbol, timeframe, ticker)
            except Exception as e:
                logger.exception("mdfeed error: %s %s %s : %s", exchange, symbol, timeframe, e)

    async def run_loop(self) -> None:
        logger.info("MarketDataService loop start: symbols=%s", self._symbols)
        while True:
            await self.sync_once()
            await asyncio.sleep(self._interval)


MARKET_DATA_SERVICE = MarketDataService()


async def _demo() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    await MARKET_DATA_SERVICE.run_loop()


if __name__ == "__main__":
    asyncio.run(_demo())