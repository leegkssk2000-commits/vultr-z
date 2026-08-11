from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import time
from pathlib import Path
from typing import Any, Mapping

from backend.engine.market_data_service import BingXPublicAdapter

SCHEMA = "zel.production_bingx_freshness.v1"


def stable_sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _float(value: Any, name: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"MARKET_NUMERIC_INVALID:{name}") from exc
    if not math.isfinite(out):
        raise RuntimeError(f"MARKET_NUMERIC_NONFINITE:{name}")
    return out


def _int(value: Any, name: str) -> int:
    out = _float(value, name)
    if not out.is_integer():
        raise RuntimeError(f"MARKET_INTEGER_INVALID:{name}")
    return int(out)


def normalize_bingx_ticker(
    ticker: Mapping[str, Any],
    *,
    symbol: str,
    max_stale_ms: float,
    now_ms: int | None = None,
) -> dict[str, Any]:
    """Validate one BingX-native ticker. Dummy/fallback payloads are forbidden."""

    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    extra = ticker.get("extra")
    extra = dict(extra) if isinstance(extra, Mapping) else {}
    provider = str(extra.get("provider") or "").lower()
    if provider != "bingx_public":
        raise RuntimeError(f"MARKET_PROVIDER_NOT_BINGX_NATIVE:{provider or 'MISSING'}")

    source_symbol = str(extra.get("symbol") or symbol).replace("-", "").upper()
    expected_symbol = str(symbol).replace("-", "").upper()
    if source_symbol != expected_symbol:
        raise RuntimeError(f"MARKET_SYMBOL_MISMATCH:{source_symbol}:{expected_symbol}")

    ts_ms = _int(ticker.get("ts"), "ticker.ts")
    age_ms = now - ts_ms
    if age_ms < 0:
        raise RuntimeError("MARKET_TIMESTAMP_IN_FUTURE")
    if age_ms > float(max_stale_ms):
        raise RuntimeError(f"MARKET_DATA_STALE:{age_ms}")

    bid = _float(ticker.get("bid"), "ticker.bid")
    ask = _float(ticker.get("ask"), "ticker.ask")
    last = _float(ticker.get("last"), "ticker.last")
    if bid <= 0 or ask <= 0 or last <= 0:
        raise RuntimeError("MARKET_PRICE_NONPOSITIVE")
    if bid > ask:
        raise RuntimeError("MARKET_CROSSED_BOOK")
    if not (bid * 0.98 <= last <= ask * 1.02):
        raise RuntimeError("MARKET_LAST_OUTSIDE_SANITY_BAND")

    reference_price = (bid + ask) / 2.0
    spread_bps = (ask - bid) / reference_price * 10_000.0
    receipt = {
        "schema_version": SCHEMA,
        "state": "PASS_BINGX_FRESH",
        "exchange": "BINGX",
        "symbol": expected_symbol,
        "source_timestamp_ms": ts_ms,
        "observed_at_ms": now,
        "age_ms": age_ms,
        "bid": bid,
        "ask": ask,
        "last": last,
        "reference_price": reference_price,
        "spread_bps": spread_bps,
        "provider": provider,
        "dummy_fallback_used": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    return receipt


async def fetch_fresh_bingx_quote_async(
    symbol: str,
    *,
    max_stale_ms: float,
    now_ms: int | None = None,
    adapter: BingXPublicAdapter | None = None,
) -> dict[str, Any]:
    native = adapter or BingXPublicAdapter()
    ticker = await native.get_latest_ticker(symbol)
    if not isinstance(ticker, Mapping):
        raise RuntimeError("BINGX_TICKER_NOT_MAPPING")
    return normalize_bingx_ticker(ticker, symbol=symbol, max_stale_ms=max_stale_ms, now_ms=now_ms)


def fetch_fresh_bingx_quote(
    symbol: str,
    *,
    max_stale_ms: float,
    now_ms: int | None = None,
    adapter: BingXPublicAdapter | None = None,
) -> dict[str, Any]:
    """Synchronous process-boundary wrapper used by the PAPER source adapter."""

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(
            fetch_fresh_bingx_quote_async(
                symbol,
                max_stale_ms=max_stale_ms,
                now_ms=now_ms,
                adapter=adapter,
            )
        )
    raise RuntimeError("BINGX_FRESHNESS_SYNC_CALLED_INSIDE_RUNNING_EVENT_LOOP")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ZEL strict BingX-native PAPER freshness probe")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--max-stale-ms", type=float, default=None)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    max_stale = args.max_stale_ms
    if max_stale is None:
        raw = os.environ.get("ZEL_DATA_STALE_MS")
        if raw is None or not raw.strip():
            raise RuntimeError("MARKET_STALE_THRESHOLD_UNBOUND:ZEL_DATA_STALE_MS")
        max_stale = _float(raw, "ZEL_DATA_STALE_MS")
    receipt = fetch_fresh_bingx_quote(args.symbol, max_stale_ms=max_stale)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
