from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import ssl
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Mapping

SCHEMA = "zel.production_l2_order_book_data.v1"
BASES = ("https://open-api.bingx.com", "https://open-api.bingx.pro")
ENDPOINT = "/openApi/swap/v2/quote/depth"
SYMBOLS = ("BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "LINK-USDT")
LIMIT = 100
DEFAULT_OUT = Path("/home/z/z/ledger/production_l2_order_book_data_v1.json")
DEFAULT_HISTORY = Path("/home/z/z/ledger/production_l2_order_book_history_v1.ndjson")


def stable_sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _finite(value: Any, label: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"L2_NUMERIC_INVALID:{label}") from exc
    if not math.isfinite(out):
        raise RuntimeError(f"L2_NUMERIC_NONFINITE:{label}")
    return out


def fetch_json(path: str, params: Mapping[str, Any]) -> tuple[dict[str, Any], str, float]:
    if path != ENDPOINT:
        raise RuntimeError("L2_ENDPOINT_DRIFT")
    ctx = ssl.create_default_context()
    errors: list[str] = []
    for base in BASES:
        try:
            url = base + path + "?" + urllib.parse.urlencode(dict(params))
            req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "ZEL-production-l2/1.0"})
            started = time.perf_counter()
            with urllib.request.urlopen(req, timeout=12, context=ctx) as response:
                obj = json.loads(response.read().decode("utf-8"))
            latency_ms = (time.perf_counter() - started) * 1000.0
            if not isinstance(obj, dict):
                raise RuntimeError("payload_not_object")
            if obj.get("code") not in (None, 0):
                raise RuntimeError(f"code={obj.get('code')} msg={obj.get('msg')}")
            data = obj.get("data", obj)
            if not isinstance(data, dict):
                raise RuntimeError("data_not_object")
            return data, base, latency_ms
        except Exception as exc:
            errors.append(f"{base}:{type(exc).__name__}:{str(exc)[:160]}")
    raise RuntimeError("L2_BINGX_FETCH_FAILED:" + " | ".join(errors))


def _levels(raw: Any, label: str) -> list[tuple[float, float]]:
    if not isinstance(raw, list) or not raw:
        raise RuntimeError(f"L2_LEVELS_EMPTY:{label}")
    out: list[tuple[float, float]] = []
    for i, row in enumerate(raw):
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            raise RuntimeError(f"L2_LEVEL_INVALID:{label}:{i}")
        price = _finite(row[0], f"{label}.{i}.price")
        qty = _finite(row[1], f"{label}.{i}.qty")
        if price <= 0.0 or qty <= 0.0:
            raise RuntimeError(f"L2_LEVEL_NONPOSITIVE:{label}:{i}")
        out.append((price, qty))
    return out


def normalize(symbol: str, payload: Mapping[str, Any], source_base: str, latency_ms: float, observed_at_ms: int) -> dict[str, Any]:
    bids = _levels(payload.get("bids"), f"{symbol}.bids")
    asks = _levels(payload.get("asks"), f"{symbol}.asks")
    best_bid = max(p for p, _ in bids)
    best_ask = min(p for p, _ in asks)
    if best_bid >= best_ask:
        raise RuntimeError(f"L2_CROSSED_BOOK:{symbol}")
    mid = (best_bid + best_ask) / 2.0
    bid_notional = sum(p * q for p, q in bids)
    ask_notional = sum(p * q for p, q in asks)
    total = bid_notional + ask_notional
    if total <= 0.0:
        raise RuntimeError(f"L2_NOTIONAL_EMPTY:{symbol}")
    imbalance = (bid_notional - ask_notional) / total
    sign = 1 if imbalance > 0.0 else -1 if imbalance < 0.0 else 0
    return {
        "symbol": symbol,
        "source_endpoint": ENDPOINT,
        "source_base": source_base,
        "source_observed_at_ms": int(observed_at_ms),
        "latency_ms": float(latency_ms),
        "book_limit": LIMIT,
        "bid_level_count": len(bids),
        "ask_level_count": len(asks),
        "best_bid": best_bid,
        "best_ask": best_ask,
        "mid": mid,
        "spread_bps": (best_ask / best_bid - 1.0) * 10_000.0,
        "bid_notional_returned_book": bid_notional,
        "ask_notional_returned_book": ask_notional,
        "imbalance_returned_book": imbalance,
        "primary_imbalance_sign": sign,
        "source_payload_sha256": stable_sha(dict(payload)),
    }


def collect_snapshot(
    *,
    fetcher: Callable[[str, Mapping[str, Any]], tuple[dict[str, Any], str, float]] = fetch_json,
    symbols: tuple[str, ...] = SYMBOLS,
    now_ms: int | None = None,
) -> dict[str, Any]:
    observed = int(time.time() * 1000) if now_ms is None else int(now_ms)
    rows: list[dict[str, Any]] = []
    for symbol in symbols:
        payload, base, latency = fetcher(ENDPOINT, {"symbol": symbol, "limit": LIMIT})
        rows.append(normalize(symbol, payload, base, latency, observed))
    if len(rows) != len(symbols) or {r["symbol"] for r in rows} != set(symbols):
        raise RuntimeError("L2_SYMBOL_PARITY_FAIL")
    snapshot: dict[str, Any] = {
        "schema_version": SCHEMA,
        "state": "PASS_L2_ORDER_BOOK_NATIVE_SNAPSHOT",
        "observed_at_ms": observed,
        "symbols": list(symbols),
        "record_count": len(rows),
        "records": rows,
        "native_endpoint": ENDPOINT,
        "endpoint_lineage": "BINGX_REAL_CALIBRATION_V1_PR570",
        "normalization": "FULL_RETURNED_BOOK_NOTIONAL_IMBALANCE_NO_THRESHOLD_SEARCH",
        "prospective_history": True,
        "history_ready_for_economic_claim": False,
        "history_state": "PROSPECTIVE_HISTORY_ACCUMULATING",
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "action": "hold",
    }
    snapshot["receipt_sha256"] = stable_sha(snapshot)
    return snapshot


def atomic_write(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(path)


def append_history(path: Path, snapshot: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    with path.open("a", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        fh.write(line)
        fh.flush()
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    path.chmod(0o600)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Verified BingX native L2 read-only owner")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--history", type=Path, default=DEFAULT_HISTORY)
    ap.add_argument("--append-history", action="store_true")
    ns = ap.parse_args(argv)
    result = collect_snapshot()
    atomic_write(ns.out, result)
    if ns.append_history:
        append_history(ns.history, result)
    print(json.dumps({
        "state": result["state"],
        "record_count": result["record_count"],
        "native_endpoint": result["native_endpoint"],
        "history_appended": bool(ns.append_history),
        "receipt_sha256": result["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
