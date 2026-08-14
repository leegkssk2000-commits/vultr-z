from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Mapping

SCHEMA = "zel.production_bingx_market_sources.v1"
POLICY_SCHEMA = "zel.production_bingx_market_sources_policy.v1"
DEFAULT_POLICY = Path("config/zel_production_bingx_market_sources_v1.json")


def validate_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    if policy.get("schema_version") != POLICY_SCHEMA:
        raise RuntimeError("BINGX_MARKET_SOURCE_POLICY_SCHEMA_INVALID")
    if str(policy.get("mode") or "").upper() != "PAPER":
        raise RuntimeError("BINGX_MARKET_SOURCE_NON_PAPER_FORBIDDEN")
    if policy.get("role") != "PUBLIC_MARKET_SOURCE_VERIFIER_NOT_STRATEGY":
        raise RuntimeError("BINGX_MARKET_SOURCE_ROLE_DRIFT")
    if policy.get("selection_authority") is not False or policy.get("promotion_authority") is not False:
        raise RuntimeError("BINGX_MARKET_SOURCE_SELECTION_AUTHORITY_FORBIDDEN")
    if policy.get("execution_authority") != "NONE" or policy.get("order_authority") != "BLOCKED":
        raise RuntimeError("BINGX_MARKET_SOURCE_EXECUTION_FORBIDDEN")
    if policy.get("live_trade_authority") != "BLOCKED" or policy.get("exchange_order_submitted") is not False:
        raise RuntimeError("BINGX_MARKET_SOURCE_LIVE_FORBIDDEN")
    if policy.get("source_code_mutation_allowed") is not False or policy.get("self_modification_allowed") is not False:
        raise RuntimeError("BINGX_MARKET_SOURCE_MUTATION_FORBIDDEN")
    if str(policy.get("base_url") or "").rstrip("/") not in {"https://open-api.bingx.com", "https://open-api.bingx.pro"}:
        raise RuntimeError("BINGX_MARKET_SOURCE_BASE_URL_INVALID")
    symbols = policy.get("symbols")
    if not isinstance(symbols, list) or not symbols:
        raise RuntimeError("BINGX_MARKET_SOURCE_SYMBOLS_MISSING")
    if any(not str(x).endswith("-USDT") or len(str(x)) > 24 for x in symbols):
        raise RuntimeError("BINGX_MARKET_SOURCE_SYMBOL_INVALID")
    if str(policy.get("kline_interval") or "") not in {"1m", "3m", "5m", "15m", "30m", "1h"}:
        raise RuntimeError("BINGX_MARKET_SOURCE_INTERVAL_INVALID")
    if int(policy.get("kline_limit") or 0) not in range(2, 1441):
        raise RuntimeError("BINGX_MARKET_SOURCE_KLINE_LIMIT_INVALID")
    if int(policy.get("depth_limit") or 0) not in {5, 10, 20, 50, 100, 500, 1000}:
        raise RuntimeError("BINGX_MARKET_SOURCE_DEPTH_LIMIT_INVALID")
    return dict(policy)


def _request_json(url: str, timeout: int = 20) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "ZEL-PAPER-RESEARCH/1.0", "X-SOURCE-KEY": "BX-AI-SKILL"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        payload = json.load(response)
    if not isinstance(payload, Mapping):
        raise RuntimeError("BINGX_MARKET_SOURCE_RESPONSE_NOT_OBJECT")
    return dict(payload)


def _get(base_url: str, path: str, params: Mapping[str, Any], fetcher: Callable[[str], Mapping[str, Any]]) -> Any:
    query = dict(params)
    query["timestamp"] = int(time.time() * 1000)
    payload = fetcher(f"{base_url}{path}?{urllib.parse.urlencode(query)}")
    if int(payload.get("code", -1)) != 0:
        raise RuntimeError(f"BINGX_MARKET_SOURCE_API_ERROR:{payload.get('code')}:{str(payload.get('msg') or '')[:200]}")
    return payload.get("data")


def _validate_klines(data: Any, minimum: int = 2) -> dict[str, Any]:
    if not isinstance(data, list) or len(data) < minimum:
        raise RuntimeError("BINGX_MARKET_SOURCE_KLINES_INSUFFICIENT")
    last = data[-1]
    # BingX official SKILL currently documents/runtime-returns the 7-field core
    # [openTime, open, high, low, close, volume, closeTime]. The companion
    # api-reference documents optional extended fields through index 10.
    if not isinstance(last, list) or len(last) < 7:
        raise RuntimeError("BINGX_MARKET_SOURCE_KLINE_SCHEMA_INVALID")
    for idx in range(7):
        try:
            float(last[idx])
        except (TypeError, ValueError, OverflowError) as exc:
            raise RuntimeError(f"BINGX_MARKET_SOURCE_KLINE_FIELD_INVALID:{idx}") from exc
    out = {
        "row_count": len(data),
        "field_count": len(last),
        "last_open_time_ms": int(float(last[0])),
        "last_close_time_ms": int(float(last[6])),
        "last_close": float(last[4]),
        "last_base_volume": float(last[5]),
        "extended_trade_fields_bound": len(last) >= 11,
    }
    if len(last) >= 11:
        try:
            out.update(
                {
                    "last_quote_volume": float(last[7]),
                    "last_trade_count": int(float(last[8])),
                    "last_taker_buy_base_volume": float(last[9]),
                    "last_taker_buy_quote_volume": float(last[10]),
                }
            )
        except (TypeError, ValueError, OverflowError) as exc:
            raise RuntimeError("BINGX_MARKET_SOURCE_EXTENDED_KLINE_FIELD_INVALID") from exc
    return out


def _validate_depth(data: Any) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        raise RuntimeError("BINGX_MARKET_SOURCE_DEPTH_NOT_OBJECT")
    bids, asks = data.get("bids"), data.get("asks")
    if not isinstance(bids, list) or not bids or not isinstance(asks, list) or not asks:
        raise RuntimeError("BINGX_MARKET_SOURCE_DEPTH_EMPTY")
    try:
        best_bid, bid_qty = float(bids[0][0]), float(bids[0][1])
        best_ask, ask_qty = float(asks[0][0]), float(asks[0][1])
    except (TypeError, ValueError, IndexError, OverflowError) as exc:
        raise RuntimeError("BINGX_MARKET_SOURCE_DEPTH_SCHEMA_INVALID") from exc
    if best_bid <= 0 or best_ask <= 0 or best_ask < best_bid:
        raise RuntimeError("BINGX_MARKET_SOURCE_DEPTH_PRICE_INVALID")
    return {
        "best_bid": best_bid,
        "best_ask": best_ask,
        "best_bid_qty": bid_qty,
        "best_ask_qty": ask_qty,
        "spread_bps": (best_ask - best_bid) / ((best_ask + best_bid) / 2.0) * 10000.0,
        "book_timestamp_ms": int(data.get("T") or 0),
    }


def verify_sources(
    policy: Mapping[str, Any],
    *,
    fetcher: Callable[[str], Mapping[str, Any]] | None = None,
    now_ms: int | None = None,
) -> dict[str, Any]:
    cfg = validate_policy(policy)
    caller = fetcher or _request_json
    base_url = str(cfg["base_url"]).rstrip("/")
    rows = []
    for symbol in cfg["symbols"]:
        klines = _get(base_url, "/openApi/swap/v3/quote/klines", {"symbol": symbol, "interval": cfg["kline_interval"], "limit": int(cfg["kline_limit"])}, caller)
        depth = _get(base_url, "/openApi/swap/v2/quote/depth", {"symbol": symbol, "limit": int(cfg["depth_limit"])}, caller)
        rows.append({"symbol": symbol, "kline": _validate_klines(klines), "depth": _validate_depth(depth)})
    return {
        "schema_version": SCHEMA,
        "state": "PASS_BINGX_PUBLIC_MARKET_SOURCES_VERIFIED",
        "role": "PUBLIC_MARKET_SOURCE_VERIFIER_NOT_STRATEGY",
        "provider": "BINGX_PUBLIC_USDT_PERPETUAL",
        "verified_sources": ["ohlcv", "volume", "l2_order_book"],
        "source_bindings": {"ohlcv_source_bound": True, "volume_source_bound": True, "l2_order_book_source_bound": True},
        "history_coverage_bound": False,
        "economic_signal_enabled": False,
        "symbols": rows,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "source_code_mutation_applied": False,
        "self_modification_applied": False,
        "updated_at_ms": int(time.time() * 1000) if now_ms is None else int(now_ms),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Verify BingX public OHLCV/volume/L2 sources without trading authority")
    ap.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    ap.add_argument("--output", type=Path)
    ns = ap.parse_args(argv)
    result = verify_sources(json.loads(ns.policy.read_text(encoding="utf-8")))
    text = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if ns.output:
        ns.output.parent.mkdir(parents=True, exist_ok=True)
        ns.output.write_text(text, encoding="utf-8")
    print(json.dumps({"state": result["state"], "verified_sources": result["verified_sources"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
