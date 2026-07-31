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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

VERSION = "ZEL_HISTORICAL_OOS_DATA_COLLECTOR_V1"
AUTHORITY_END_MS = int(pd.Timestamp("2026-07-27T08:30:00Z").timestamp() * 1000)
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "LINKUSDT")
KLINE_ENDPOINTS = (
    "https://open-api.bingx.com/openApi/swap/v3/quote/klines",
    "https://open-api.bingx.com/openApi/swap/v2/quote/klines",
)
FUNDING_ENDPOINTS = (
    "https://open-api.bingx.com/openApi/swap/v2/quote/fundingRate",
    "https://open-api.bingx.com/openApi/swap/v3/quote/fundingRate",
)
INTERVALS = {
    "1m": {"ms": 60_000, "lookback_days": 30, "window_days": 10},
    "15m": {"ms": 900_000, "lookback_days": 180, "window_days": 60},
}
REQUEST_LIMIT = 1000


@dataclass(frozen=True)
class Window:
    interval: str
    window_id: str
    start_ms: int
    end_ms: int


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
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


def align_down(ms: int, interval_ms: int) -> int:
    return (ms // interval_ms) * interval_ms


def build_windows() -> list[Window]:
    windows: list[Window] = []
    for interval, spec in INTERVALS.items():
        interval_ms = int(spec["ms"])
        end_ms = align_down(AUTHORITY_END_MS - interval_ms, interval_ms)
        lookback_ms = int(spec["lookback_days"]) * 24 * 60 * 60 * 1000
        window_ms = int(spec["window_days"]) * 24 * 60 * 60 * 1000
        first_ms = end_ms - lookback_ms + interval_ms
        cursor = first_ms
        index = 1
        while cursor <= end_ms:
            window_end = min(end_ms, cursor + window_ms - interval_ms)
            windows.append(Window(interval, f"{interval}_w{index}", cursor, window_end))
            cursor = window_end + interval_ms
            index += 1
    return windows


def request_json(url: str) -> dict[str, Any]:
    last: Exception | None = None
    for attempt in range(5):
        try:
            req = urllib.request.Request(
                url,
                headers={"Accept": "application/json", "User-Agent": "ZEL-Historical-OOS/1.0"},
            )
            with urllib.request.urlopen(req, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("RESPONSE_NOT_OBJECT")
            return payload
        except Exception as exc:
            last = exc
            time.sleep(0.75 * (attempt + 1))
    raise RuntimeError(f"REQUEST_FAILED:{type(last).__name__}:{last}")


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
            row.get("open"),
            row.get("high"),
            row.get("low"),
            row.get("close"),
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
        values = tuple(map(float, raw[1:6]))
    except (TypeError, ValueError):
        return None
    open_, high, low, close, volume = values
    if not all(math.isfinite(value) for value in values):
        return None
    if open_ <= 0 or close <= 0 or volume < 0:
        return None
    if high < max(open_, close) or low > min(open_, close) or high < low:
        return None
    return ts, open_, high, low, close, volume


def fetch_klines(symbol: str, interval: str, start_ms: int, end_ms: int) -> tuple[pd.DataFrame, str, int]:
    interval_ms = int(INTERVALS[interval]["ms"])
    expected = (end_ms - start_ms) // interval_ms + 1
    errors: list[str] = []
    for endpoint in KLINE_ENDPOINTS:
        try:
            found: dict[int, tuple[int, float, float, float, float, float]] = {}
            cursor = start_ms - interval_ms
            request_end = end_ms + interval_ms
            request_count = 0
            max_requests = max(8, math.ceil((expected + 2) / (REQUEST_LIMIT - 1)) + 8)
            while cursor <= request_end and request_count < max_requests:
                page_end = min(request_end, cursor + (REQUEST_LIMIT - 1) * interval_ms)
                query = urllib.parse.urlencode(
                    {
                        "symbol": symbol[:-4] + "-USDT",
                        "interval": interval,
                        "limit": REQUEST_LIMIT,
                        "startTime": cursor,
                        "endTime": page_end,
                    }
                )
                payload = request_json(endpoint + "?" + query)
                if payload.get("code") not in (None, 0, "0"):
                    raise RuntimeError(f"BINGX_CODE:{payload.get('code')}:{payload.get('msg')}")
                page = [item for item in (parse_kline(row) for row in payload_rows(payload)) if item]
                request_count += 1
                if not page:
                    raise RuntimeError("EMPTY_KLINE_PAGE")
                for item in page:
                    if start_ms <= item[0] <= end_ms:
                        found[item[0]] = item
                if len(found) >= expected:
                    break
                next_cursor = max(item[0] for item in page) + interval_ms
                if next_cursor <= cursor:
                    raise RuntimeError("PAGINATION_STALLED")
                cursor = next_cursor
            frame = pd.DataFrame(
                [found[key] for key in sorted(found)],
                columns=("timestamp_ms", "open", "high", "low", "close", "volume"),
            )
            validate_frame(frame, start_ms, end_ms, interval_ms)
            return frame, endpoint, request_count
        except Exception as exc:
            errors.append(f"{endpoint}:{type(exc).__name__}:{exc}")
    raise RuntimeError("KLINE_FETCH_FAILED:" + "|".join(errors))


def validate_frame(frame: pd.DataFrame, start_ms: int, end_ms: int, interval_ms: int) -> None:
    required = {"timestamp_ms", "open", "high", "low", "close", "volume"}
    if not required.issubset(frame.columns):
        raise RuntimeError("COLUMNS_MISSING")
    frame.sort_values("timestamp_ms", inplace=True)
    expected = (end_ms - start_ms) // interval_ms + 1
    if len(frame) != expected:
        raise RuntimeError(f"ROWS:{len(frame)}!={expected}")
    ts = frame["timestamp_ms"].astype("int64")
    if int(ts.iloc[0]) != start_ms or int(ts.iloc[-1]) != end_ms:
        raise RuntimeError("BOUNDARY_MISMATCH")
    if ts.duplicated().any():
        raise RuntimeError("DUPLICATE_TIMESTAMP")
    if len(ts) > 1 and not bool((ts.diff().dropna() == interval_ms).all()):
        raise RuntimeError("TIMESTAMP_GAP")
    numeric = frame[["open", "high", "low", "close", "volume"]].apply(pd.to_numeric, errors="coerce")
    if not all(math.isfinite(float(value)) for value in numeric.to_numpy().ravel()):
        raise RuntimeError("NONFINITE")
    if bool((numeric[["open", "high", "low", "close"]] <= 0).any().any()):
        raise RuntimeError("PRICE_NONPOSITIVE")
    if bool((numeric["volume"] < 0).any()):
        raise RuntimeError("VOLUME_NEGATIVE")
    if bool((numeric["high"] < numeric[["open", "close", "low"]].max(axis=1)).any()):
        raise RuntimeError("HIGH_INVARIANT")
    if bool((numeric["low"] > numeric[["open", "close", "high"]].min(axis=1)).any()):
        raise RuntimeError("LOW_INVARIANT")


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
            query = urllib.parse.urlencode(
                {
                    "symbol": symbol[:-4] + "-USDT",
                    "startTime": start_ms,
                    "endTime": end_ms,
                    "limit": 1000,
                }
            )
            payload = request_json(endpoint + "?" + query)
            if payload.get("code") not in (None, 0, "0"):
                raise RuntimeError(f"BINGX_CODE:{payload.get('code')}:{payload.get('msg')}")
            rows = [item for item in (parse_funding(row) for row in payload_rows(payload)) if item]
            unique = {int(row["timestamp_ms"]): row for row in rows}
            rows = [unique[key] for key in sorted(unique) if start_ms <= key <= end_ms]
            if not rows:
                raise RuntimeError("NO_FUNDING_ROWS")
            return rows, endpoint
        except Exception as exc:
            errors.append(f"{endpoint}:{type(exc).__name__}:{exc}")
    raise RuntimeError("FUNDING_FETCH_FAILED:" + "|".join(errors))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--status-out", required=True)
    args = parser.parse_args()

    root = Path(args.data_root).resolve()
    status_out = Path(args.status_out).resolve()
    root.mkdir(parents=True, exist_ok=True)
    windows = build_windows()
    rows: list[dict[str, Any]] = []
    total_rows = 0
    total_requests = 0

    for window in windows:
        for symbol in SYMBOLS:
            frame, endpoint, requests = fetch_klines(
                symbol, window.interval, window.start_ms, window.end_ms
            )
            path = root / "market" / window.interval / window.window_id / f"{symbol}.csv"
            path.parent.mkdir(parents=True, exist_ok=True)
            frame.to_csv(path, index=False)
            total_rows += len(frame)
            total_requests += requests
            rows.append(
                {
                    "kind": "market",
                    "symbol": symbol,
                    "interval": window.interval,
                    "window_id": window.window_id,
                    "start_ms": window.start_ms,
                    "start": iso(window.start_ms),
                    "end_ms": window.end_ms,
                    "end": iso(window.end_ms),
                    "rows": len(frame),
                    "sha256": sha256(path),
                    "path": str(path.relative_to(root)),
                    "source": endpoint,
                    "request_count": requests,
                }
            )

    funding_start = min(window.start_ms for window in windows)
    funding_end = max(window.end_ms for window in windows)
    for symbol in SYMBOLS:
        funding, endpoint = fetch_funding(symbol, funding_start, funding_end)
        path = root / "funding" / f"{symbol}.json"
        atomic_json(path, {"symbol": symbol, "rows": funding, "source": endpoint})
        rows.append(
            {
                "kind": "funding",
                "symbol": symbol,
                "start_ms": funding_start,
                "start": iso(funding_start),
                "end_ms": funding_end,
                "end": iso(funding_end),
                "rows": len(funding),
                "sha256": sha256(path),
                "path": str(path.relative_to(root)),
                "source": endpoint,
            }
        )

    manifest = {
        "schema_version": "zel.historical_oos_data.v1",
        "version": VERSION,
        "state": "PASS_HISTORICAL_OOS_DATA_READY",
        "authority_end_ms": AUTHORITY_END_MS,
        "authority_end": iso(AUTHORITY_END_MS),
        "symbols": list(SYMBOLS),
        "interval_policy": INTERVALS,
        "window_count": len(windows),
        "windows": [
            {
                "interval": item.interval,
                "window_id": item.window_id,
                "start_ms": item.start_ms,
                "start": iso(item.start_ms),
                "end_ms": item.end_ms,
                "end": iso(item.end_ms),
            }
            for item in windows
        ],
        "files": rows,
        "total_market_rows": total_rows,
        "total_market_requests": total_requests,
        "forward_overlap_count": 0,
        "forward_ledger_mutated": False,
        "formal_ledger_mutated": False,
        "strategy_source_mutated": False,
        "registry_mutated": False,
        "historical_data_is_promotion_authority": False,
        "final_holdout_accessed": False,
        "research_only": True,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
    }
    atomic_json(root / "manifest.json", manifest)
    atomic_json(status_out, manifest)
    print(
        json.dumps(
            {
                "state": manifest["state"],
                "market_rows": total_rows,
                "files": len(rows),
                "windows": len(windows),
                "requests": total_requests,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
