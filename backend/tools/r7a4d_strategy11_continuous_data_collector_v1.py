from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

VERSION = "R7A4D_STRATEGY11_CONTINUOUS_DATA_COLLECTOR_V1"
INTERVAL = "15m"
INTERVAL_MS = 900_000
REQUEST_LIMIT = 1000
AUTHORITY_END_MS = int(pd.Timestamp("2026-07-27T08:30:00Z").timestamp() * 1000)
FIRST_EVALUATION_MS = AUTHORITY_END_MS + INTERVAL_MS
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "LINKUSDT")
KLINE_ENDPOINTS = (
    "https://open-api.bingx.com/openApi/swap/v3/quote/klines",
    "https://open-api.bingx.com/openApi/swap/v2/quote/klines",
)
FUNDING_ENDPOINTS = (
    "https://open-api.bingx.com/openApi/swap/v2/quote/fundingRate",
    "https://open-api.bingx.com/openApi/swap/v3/quote/fundingRate",
)


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def iso(ms: int) -> str:
    return pd.Timestamp(ms, unit="ms", tz="UTC").isoformat()


def aligned_closed_end(now_ms: int) -> int:
    return ((now_ms // INTERVAL_MS) - 1) * INTERVAL_MS


def request_json(url: str) -> dict[str, Any]:
    error: Exception | None = None
    for attempt in range(4):
        try:
            req = urllib.request.Request(
                url,
                headers={"Accept": "application/json", "User-Agent": "ZEL-Strategy11-Continuous/1.0"},
            )
            with urllib.request.urlopen(req, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("RESPONSE_NOT_OBJECT")
            return payload
        except Exception as exc:
            error = exc
            time.sleep(0.75 * (attempt + 1))
    raise RuntimeError(f"REQUEST_FAILED:{type(error).__name__}:{error}")


def payload_rows(payload: Mapping[str, Any]) -> list[Any]:
    data: Any = payload.get("data")
    if isinstance(data, Mapping):
        for key in ("data", "rows", "klines", "list", "fundingRates"):
            if isinstance(data.get(key), list):
                return list(data[key])
    return list(data) if isinstance(data, list) else []


def parse_kline(row: Any) -> tuple[int, float, float, float, float, float] | None:
    if isinstance(row, Mapping):
        raw = (
            row.get("time", row.get("timestamp", row.get("openTime"))),
            row.get("open"), row.get("high"), row.get("low"), row.get("close"),
            row.get("volume", row.get("vol")),
        )
    elif isinstance(row, (list, tuple)) and len(row) >= 6:
        raw = tuple(row[:6])
    else:
        return None
    try:
        ts = int(float(raw[0]))
        if ts < 10_000_000_000:
            ts *= 1000
        elif ts > 10_000_000_000_000:
            ts //= 1000
        open_, high, low, close, volume = map(float, raw[1:6])
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(v) for v in (open_, high, low, close, volume)):
        return None
    if open_ <= 0 or close <= 0 or volume < 0:
        return None
    if high < max(open_, close) or low > min(open_, close) or high < low:
        return None
    return ts, open_, high, low, close, volume


def fetch_klines(symbol: str, start_ms: int, end_ms: int) -> tuple[pd.DataFrame, str, int]:
    expected = (end_ms - start_ms) // INTERVAL_MS + 1
    errors: list[str] = []
    for endpoint in KLINE_ENDPOINTS:
        try:
            found: dict[int, tuple[int, float, float, float, float, float]] = {}
            cursor = start_ms - INTERVAL_MS
            request_end = end_ms + INTERVAL_MS
            request_count = 0
            max_requests = max(8, math.ceil((expected + 2) / (REQUEST_LIMIT - 1)) + 5)
            while cursor <= request_end and request_count < max_requests:
                page_end = min(request_end, cursor + (REQUEST_LIMIT - 1) * INTERVAL_MS)
                query = urllib.parse.urlencode({
                    "symbol": symbol[:-4] + "-USDT",
                    "interval": INTERVAL,
                    "limit": REQUEST_LIMIT,
                    "startTime": cursor,
                    "endTime": page_end,
                })
                payload = request_json(endpoint + "?" + query)
                if payload.get("code") not in (None, 0, "0"):
                    raise RuntimeError(f"BINGX_CODE:{payload.get('code')}:{payload.get('msg')}")
                page = [item for item in (parse_kline(row) for row in payload_rows(payload)) if item is not None]
                request_count += 1
                if not page:
                    raise RuntimeError("EMPTY_KLINE_PAGE")
                for item in page:
                    if start_ms <= item[0] <= end_ms:
                        found[item[0]] = item
                if len(found) >= expected:
                    break
                next_cursor = max(item[0] for item in page) + INTERVAL_MS
                if next_cursor <= cursor:
                    raise RuntimeError("PAGINATION_STALLED")
                cursor = next_cursor
            frame = pd.DataFrame(
                [found[key] for key in sorted(found)],
                columns=("timestamp_ms", "open", "high", "low", "close", "volume"),
            )
            if len(frame) != expected:
                raise RuntimeError(f"ROWS:{len(frame)}!={expected}")
            return frame, endpoint, request_count
        except Exception as exc:
            errors.append(f"{endpoint}:{type(exc).__name__}:{exc}")
    raise RuntimeError("KLINE_FETCH_FAILED:" + "|".join(errors))


def parse_funding(row: Any) -> dict[str, Any] | None:
    if not isinstance(row, Mapping):
        return None
    raw_ts = row.get("fundingTime", row.get("time", row.get("timestamp")))
    raw_rate = row.get("fundingRate", row.get("rate"))
    try:
        ts = int(float(raw_ts))
        if ts < 10_000_000_000:
            ts *= 1000
        elif ts > 10_000_000_000_000:
            ts //= 1000
        rate = float(raw_rate)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(rate):
        return None
    return {"timestamp_ms": ts, "funding_rate": rate}


def fetch_funding(symbol: str, start_ms: int, end_ms: int) -> tuple[list[dict[str, Any]], str]:
    errors: list[str] = []
    for endpoint in FUNDING_ENDPOINTS:
        try:
            query = urllib.parse.urlencode({
                "symbol": symbol[:-4] + "-USDT",
                "startTime": start_ms,
                "endTime": end_ms,
                "limit": 1000,
            })
            payload = request_json(endpoint + "?" + query)
            if payload.get("code") not in (None, 0, "0"):
                raise RuntimeError(f"BINGX_CODE:{payload.get('code')}:{payload.get('msg')}")
            rows = [item for item in (parse_funding(row) for row in payload_rows(payload)) if item is not None]
            rows = sorted({int(row["timestamp_ms"]): row for row in rows}.values(), key=lambda row: row["timestamp_ms"])
            rows = [row for row in rows if start_ms <= int(row["timestamp_ms"]) <= end_ms]
            if not rows:
                raise RuntimeError("NO_FUNDING_ROWS")
            return rows, endpoint
        except Exception as exc:
            errors.append(f"{endpoint}:{type(exc).__name__}:{exc}")
    raise RuntimeError("FUNDING_FETCH_FAILED:" + "|".join(errors))


def validate_full(frame: pd.DataFrame, latest_end_ms: int) -> None:
    required = {"timestamp_ms", "open", "high", "low", "close", "volume"}
    if not required.issubset(frame.columns):
        raise RuntimeError("COLUMNS_MISSING")
    frame.sort_values("timestamp_ms", inplace=True)
    if frame["timestamp_ms"].duplicated().any():
        raise RuntimeError("DUPLICATE_TIMESTAMP")
    ts = frame["timestamp_ms"].astype("int64")
    if int(ts.iloc[0]) != FIRST_EVALUATION_MS or int(ts.iloc[-1]) != latest_end_ms:
        raise RuntimeError("BOUNDARY_MISMATCH")
    if len(ts) > 1 and not bool((ts.diff().dropna() == INTERVAL_MS).all()):
        raise RuntimeError("TIMESTAMP_GAP")
    numeric = frame[["open", "high", "low", "close", "volume"]].apply(pd.to_numeric, errors="coerce")
    if not all(math.isfinite(float(value)) for value in numeric.to_numpy().ravel()):
        raise RuntimeError("OHLCV_NONFINITE")
    if bool((numeric[["open", "high", "low", "close"]] <= 0).any().any()):
        raise RuntimeError("PRICE_NONPOSITIVE")
    if bool((numeric["volume"] < 0).any()):
        raise RuntimeError("VOLUME_NEGATIVE")
    if bool((numeric["high"] < numeric[["open", "close", "low"]].max(axis=1)).any()):
        raise RuntimeError("HIGH_INVARIANT")
    if bool((numeric["low"] > numeric[["open", "close", "high"]].min(axis=1)).any()):
        raise RuntimeError("LOW_INVARIANT")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--status-out", required=True)
    parser.add_argument("--as-of-ms", type=int)
    args = parser.parse_args()

    root = Path(args.data_root).resolve()
    status_out = Path(args.status_out).resolve()
    root.mkdir(parents=True, exist_ok=True)
    now_ms = args.as_of_ms or int(pd.Timestamp.now(tz="UTC").timestamp() * 1000)
    latest_end_ms = aligned_closed_end(now_ms)
    if latest_end_ms < FIRST_EVALUATION_MS:
        raise RuntimeError("NO_NEW_CLOSED_BAR")

    symbol_rows: list[dict[str, Any]] = []
    total_added = 0
    for symbol in SYMBOLS:
        market_path = root / "market" / f"{symbol}.csv"
        if market_path.exists():
            existing = pd.read_csv(market_path)
            last_ms = int(existing["timestamp_ms"].max())
            fetch_start = last_ms + INTERVAL_MS
        else:
            existing = pd.DataFrame(columns=("timestamp_ms", "open", "high", "low", "close", "volume"))
            fetch_start = FIRST_EVALUATION_MS
        endpoint = None
        requests = 0
        added = 0
        if fetch_start <= latest_end_ms:
            new, endpoint, requests = fetch_klines(symbol, fetch_start, latest_end_ms)
            added = len(new)
            total_added += added
            combined = pd.concat([existing, new], ignore_index=True)
        else:
            combined = existing.copy()
        combined = combined.drop_duplicates(subset=["timestamp_ms"], keep="last").sort_values("timestamp_ms")
        combined = combined[(combined["timestamp_ms"] >= FIRST_EVALUATION_MS) & (combined["timestamp_ms"] <= latest_end_ms)]
        validate_full(combined, latest_end_ms)
        market_path.parent.mkdir(parents=True, exist_ok=True)
        combined.to_csv(market_path, index=False)

        funding_path = root / "funding" / f"{symbol}.json"
        old_funding: list[dict[str, Any]] = []
        if funding_path.exists():
            payload = json.loads(funding_path.read_text(encoding="utf-8"))
            old_funding = list(payload.get("rows", []))
        funding_start = max(FIRST_EVALUATION_MS - 8 * 60 * 60 * 1000, (max((int(r["timestamp_ms"]) for r in old_funding), default=0) + 1))
        funding_endpoint = None
        if funding_start <= latest_end_ms:
            new_funding, funding_endpoint = fetch_funding(symbol, funding_start, latest_end_ms)
            merged = {int(row["timestamp_ms"]): row for row in old_funding + new_funding}
            old_funding = [merged[key] for key in sorted(merged)]
        if not old_funding:
            raise RuntimeError(f"FUNDING_EMPTY:{symbol}")
        atomic_json(funding_path, {"symbol": symbol, "rows": old_funding, "source": funding_endpoint})

        symbol_rows.append({
            "symbol": symbol,
            "rows": len(combined),
            "added_rows": added,
            "first_timestamp_ms": int(combined["timestamp_ms"].iloc[0]),
            "last_timestamp_ms": int(combined["timestamp_ms"].iloc[-1]),
            "market_sha256": sha256(market_path),
            "funding_sha256": sha256(funding_path),
            "funding_events": len(old_funding),
            "kline_source": endpoint,
            "funding_source": funding_endpoint,
            "request_count": requests,
        })

    available = (latest_end_ms - AUTHORITY_END_MS) // INTERVAL_MS
    manifest = {
        "schema_version": "1.0",
        "version": VERSION,
        "state": "PASS",
        "blockers": [],
        "authority_end_ms": AUTHORITY_END_MS,
        "authority_end": iso(AUTHORITY_END_MS),
        "first_evaluation_ms": FIRST_EVALUATION_MS,
        "first_evaluation": iso(FIRST_EVALUATION_MS),
        "latest_closed_end_ms": latest_end_ms,
        "latest_closed_end": iso(latest_end_ms),
        "available_non_overlap_bars": int(available),
        "missing_to_w1_480": max(0, 480 - int(available)),
        "w1_ready": int(available) >= 480,
        "total_added_rows_this_run": total_added,
        "symbols": symbol_rows,
        "canonical_mutated": False,
        "registry_mutated": False,
        "protected_mutations": 0,
        "execution_allowed": False,
        "order_authority": "BLOCKED",
    }
    atomic_json(root / "manifest.json", manifest)
    atomic_json(status_out, manifest)
    print(json.dumps({
        "state": manifest["state"],
        "available": manifest["available_non_overlap_bars"],
        "missing": manifest["missing_to_w1_480"],
        "added": total_added,
        "w1_ready": manifest["w1_ready"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
