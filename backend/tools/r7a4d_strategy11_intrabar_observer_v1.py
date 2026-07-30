from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

VERSION = "R7A4D_STRATEGY11_INTRABAR_OBSERVER_V1"
START_MS = int(pd.Timestamp("2026-07-27T08:45:00Z").timestamp() * 1000)
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "LINKUSDT")
INTERVALS = {"1m": 60_000, "5m": 300_000}
REQUEST_LIMIT = 1000
ENDPOINTS = (
    "https://open-api.bingx.com/openApi/swap/v3/quote/klines",
    "https://open-api.bingx.com/openApi/swap/v2/quote/klines",
)
SAFETY = {
    "research_only": True,
    "promotion_authority": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "order_authority": "BLOCKED",
    "runtime_bound": False,
    "canonical_mutated": False,
    "registry_mutated": False,
    "w1_metric_input_allowed": False,
    "observer_only": True,
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def request_json(url: str) -> dict[str, Any]:
    last: Exception | None = None
    for attempt in range(4):
        try:
            request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "ZEL-Strategy11-Intrabar/1.0"})
            with urllib.request.urlopen(request, timeout=30) as response:
                value = json.loads(response.read().decode("utf-8"))
            if not isinstance(value, dict):
                raise ValueError("RESPONSE_NOT_OBJECT")
            return value
        except Exception as exc:
            last = exc
            time.sleep(0.75 * (attempt + 1))
    raise RuntimeError(f"REQUEST_FAILED:{type(last).__name__}:{last}")


def rows(payload: Mapping[str, Any]) -> list[Any]:
    value: Any = payload.get("data")
    if isinstance(value, Mapping):
        for key in ("data", "rows", "klines", "list"):
            if isinstance(value.get(key), list):
                return list(value[key])
    return list(value) if isinstance(value, list) else []


def parse(row: Any) -> tuple[int, float, float, float, float, float] | None:
    if isinstance(row, Mapping):
        raw = (
            row.get("time", row.get("timestamp", row.get("openTime"))),
            row.get("open"), row.get("high"), row.get("low"), row.get("close"), row.get("volume", row.get("vol")),
        )
    elif isinstance(row, (list, tuple)) and len(row) >= 6:
        raw = tuple(row[:6])
    else:
        return None
    try:
        timestamp = int(float(raw[0]))
        if timestamp < 10_000_000_000:
            timestamp *= 1000
        elif timestamp > 10_000_000_000_000:
            timestamp //= 1000
        open_, high, low, close, volume = map(float, raw[1:6])
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(value) for value in (open_, high, low, close, volume)):
        return None
    if open_ <= 0 or close <= 0 or volume < 0 or high < max(open_, close) or low > min(open_, close) or high < low:
        return None
    return timestamp, open_, high, low, close, volume


def closed_end(now_ms: int, interval_ms: int) -> int:
    return ((now_ms // interval_ms) - 1) * interval_ms


def fetch(symbol: str, interval: str, interval_ms: int, end_ms: int) -> tuple[pd.DataFrame, str, int]:
    expected = (end_ms - START_MS) // interval_ms + 1
    failures: list[str] = []
    for endpoint in ENDPOINTS:
        try:
            found: dict[int, tuple[int, float, float, float, float, float]] = {}
            cursor = START_MS - interval_ms
            request_end = end_ms + interval_ms
            requests = 0
            max_requests = max(8, math.ceil((expected + 2) / (REQUEST_LIMIT - 1)) + 5)
            while cursor <= request_end and requests < max_requests:
                page_end = min(request_end, cursor + (REQUEST_LIMIT - 1) * interval_ms)
                query = urllib.parse.urlencode({
                    "symbol": symbol[:-4] + "-USDT",
                    "interval": interval,
                    "limit": REQUEST_LIMIT,
                    "startTime": cursor,
                    "endTime": page_end,
                })
                payload = request_json(endpoint + "?" + query)
                if payload.get("code") not in (None, 0, "0"):
                    raise RuntimeError(f"BINGX_CODE:{payload.get('code')}:{payload.get('msg')}")
                page = [item for item in (parse(item) for item in rows(payload)) if item is not None]
                requests += 1
                if not page:
                    raise RuntimeError("EMPTY_PAGE")
                for item in page:
                    if START_MS <= item[0] <= end_ms:
                        found[item[0]] = item
                if len(found) >= expected:
                    break
                next_cursor = max(item[0] for item in page) + interval_ms
                if next_cursor <= cursor:
                    raise RuntimeError("PAGINATION_STALLED")
                cursor = next_cursor
            frame = pd.DataFrame([found[key] for key in sorted(found)], columns=("timestamp_ms", "open", "high", "low", "close", "volume"))
            validate(frame, interval_ms, end_ms)
            return frame, endpoint, requests
        except Exception as exc:
            failures.append(f"{endpoint}:{type(exc).__name__}:{exc}")
    raise RuntimeError("INTRABAR_FETCH_FAILED:" + "|".join(failures))


def validate(frame: pd.DataFrame, interval_ms: int, end_ms: int) -> None:
    if frame.empty:
        raise RuntimeError("EMPTY_FRAME")
    if frame["timestamp_ms"].duplicated().any():
        raise RuntimeError("DUPLICATE_TIMESTAMP")
    timestamps = frame["timestamp_ms"].astype("int64")
    if int(timestamps.iloc[0]) != START_MS or int(timestamps.iloc[-1]) != end_ms:
        raise RuntimeError("BOUNDARY_MISMATCH")
    if len(timestamps) > 1 and not bool((timestamps.diff().dropna() == interval_ms).all()):
        raise RuntimeError("TIMESTAMP_GAP")
    numeric = frame[["open", "high", "low", "close", "volume"]].apply(pd.to_numeric, errors="coerce")
    if not all(math.isfinite(float(value)) for value in numeric.to_numpy().ravel()):
        raise RuntimeError("NONFINITE")
    if bool((numeric[["open", "high", "low", "close"]] <= 0).any().any()) or bool((numeric["volume"] < 0).any()):
        raise RuntimeError("VALUE_INVARIANT")
    if bool((numeric["high"] < numeric[["open", "close", "low"]].max(axis=1)).any()):
        raise RuntimeError("HIGH_INVARIANT")
    if bool((numeric["low"] > numeric[["open", "close", "high"]].min(axis=1)).any()):
        raise RuntimeError("LOW_INVARIANT")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--as-of-ms", type=int)
    args = parser.parse_args()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    now_ms = args.as_of_ms or int(pd.Timestamp.now(tz="UTC").timestamp() * 1000)
    manifest_rows: list[dict[str, Any]] = []
    interval_ends: dict[str, int] = {}
    for interval, interval_ms in INTERVALS.items():
        end_ms = closed_end(now_ms, interval_ms)
        interval_ends[interval] = end_ms
        if end_ms < START_MS:
            raise RuntimeError(f"NO_CLOSED_DATA:{interval}")
        for symbol in SYMBOLS:
            frame, endpoint, requests = fetch(symbol, interval, interval_ms, end_ms)
            path = out / "market" / interval / f"{symbol}.csv"
            path.parent.mkdir(parents=True, exist_ok=True)
            frame.to_csv(path, index=False)
            manifest_rows.append({
                "symbol": symbol,
                "interval": interval,
                "rows": len(frame),
                "first_timestamp_ms": int(frame["timestamp_ms"].iloc[0]),
                "last_timestamp_ms": int(frame["timestamp_ms"].iloc[-1]),
                "sha256": sha256(path),
                "source": endpoint,
                "request_count": requests,
                "gap_count": int((frame["timestamp_ms"].diff().dropna() != interval_ms).sum()),
                "duplicate_count": int(frame["timestamp_ms"].duplicated().sum()),
            })
    counts = {(row["interval"], row["rows"]) for row in manifest_rows}
    parity = {interval: len({row["rows"] for row in manifest_rows if row["interval"] == interval}) == 1 for interval in INTERVALS}
    manifest = {
        "schema_version": "1.0",
        "version": VERSION,
        "state": "PASS_INTRABAR_OBSERVER_COLLECTION",
        "start_ms": START_MS,
        "start": pd.Timestamp(START_MS, unit="ms", tz="UTC").isoformat(),
        "interval_end_ms": interval_ends,
        "symbol_count": len(SYMBOLS),
        "intervals": list(INTERVALS),
        "row_parity": parity,
        "gap_count": sum(int(row["gap_count"]) for row in manifest_rows),
        "duplicate_count": sum(int(row["duplicate_count"]) for row in manifest_rows),
        "rows": manifest_rows,
        "usage_contract": {
            "current_w1_performance_gate": "FORBIDDEN",
            "current_candidate_selection": "FORBIDDEN",
            "allowed": ["INTRABAR_PATH_AMBIGUITY", "MFE_MAE_TIMING", "EXECUTION_STRESS", "W2_W3_OBSERVER"],
        },
        **SAFETY,
    }
    if not all(parity.values()) or manifest["gap_count"] != 0 or manifest["duplicate_count"] != 0:
        raise RuntimeError("INTRABAR_INTEGRITY_FAIL")
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print("PASS_INTRABAR_OBSERVER_COLLECTION")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
