from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

VERSION = "ZEL_BINGX_1M_BACKFILL_STAGE_V1"
SCHEMA = "zel.bingx.1m_backfill.stage.v1"
BASE_URL = "https://open-api.bingx.com"
ENDPOINT = "/openApi/swap/v3/quote/klines"
INTERVAL = "1m"
INTERVAL_MS = 60_000
CHUNK_LIMIT = 1000
SAFE_CHUNK_BARS = CHUNK_LIMIT - 1
SYMBOLS = ("BTC-USDT", "ETH-USDT", "LINK-USDT", "SOL-USDT", "XRP-USDT")
START_UTC = "2026-01-28T08:30:00+00:00"
END_EXCLUSIVE_UTC = "2026-06-27T08:30:00+00:00"
CSV_FIELDS = ("timestamp_ms", "open", "high", "low", "close", "volume")


def stable_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def utc_ms(value: str) -> int:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp() * 1000)


def decimal_text(value: Any, field: str) -> str:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise RuntimeError(f"INVALID_DECIMAL:{field}:{value}") from exc
    if not number.is_finite():
        raise RuntimeError(f"NONFINITE_DECIMAL:{field}:{value}")
    if field != "volume" and number <= 0:
        raise RuntimeError(f"NONPOSITIVE_PRICE:{field}:{value}")
    if field == "volume" and number < 0:
        raise RuntimeError(f"NEGATIVE_VOLUME:{value}")
    return format(number, "f")


def extract_rows(payload: Mapping[str, Any]) -> list[Any]:
    if int(payload.get("code", -1)) != 0:
        raise RuntimeError(f"BINGX_CODE:{payload.get('code')}:{payload.get('msg')}")
    data = payload.get("data")
    if isinstance(data, list):
        return data
    if isinstance(data, Mapping):
        for key in ("data", "rows", "items", "list", "klines"):
            child = data.get(key)
            if isinstance(child, list):
                return child
    raise RuntimeError("BINGX_KLINE_ROWS_MISSING")


def normalize_row(raw: Any) -> dict[str, Any]:
    if isinstance(raw, Mapping):
        timestamp = raw.get("openTime", raw.get("time", raw.get("timestamp")))
        values = {
            "timestamp_ms": timestamp,
            "open": raw.get("open"),
            "high": raw.get("high"),
            "low": raw.get("low"),
            "close": raw.get("close"),
            "volume": raw.get("volume", raw.get("vol", 0)),
        }
    elif isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)) and len(raw) >= 6:
        values = {
            "timestamp_ms": raw[0],
            "open": raw[1],
            "high": raw[2],
            "low": raw[3],
            "close": raw[4],
            "volume": raw[5],
        }
    else:
        raise RuntimeError(f"UNSUPPORTED_KLINE_ROW:{type(raw).__name__}")
    try:
        timestamp_ms = int(float(values["timestamp_ms"]))
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"INVALID_TIMESTAMP:{values.get('timestamp_ms')}") from exc
    row = {
        "timestamp_ms": timestamp_ms,
        "open": decimal_text(values["open"], "open"),
        "high": decimal_text(values["high"], "high"),
        "low": decimal_text(values["low"], "low"),
        "close": decimal_text(values["close"], "close"),
        "volume": decimal_text(values["volume"], "volume"),
    }
    open_price = Decimal(row["open"])
    high_price = Decimal(row["high"])
    low_price = Decimal(row["low"])
    close_price = Decimal(row["close"])
    if high_price < max(open_price, close_price, low_price):
        raise RuntimeError(f"OHLC_HIGH_INVALID:{timestamp_ms}")
    if low_price > min(open_price, close_price, high_price):
        raise RuntimeError(f"OHLC_LOW_INVALID:{timestamp_ms}")
    return row


def request_chunk(symbol: str, start_ms: int, end_ms: int, *, attempts: int = 5) -> list[dict[str, Any]]:
    params = {
        "symbol": symbol,
        "interval": INTERVAL,
        "startTime": start_ms,
        "endTime": end_ms,
        "limit": CHUNK_LIMIT,
    }
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(
        f"{BASE_URL}{ENDPOINT}?{query}",
        headers={
            "Accept": "application/json",
            "User-Agent": VERSION,
            "X-SOURCE-KEY": "BX-AI-SKILL",
        },
    )
    last_error: str | None = None
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read())
            rows = [normalize_row(row) for row in extract_rows(payload)]
            return sorted(rows, key=lambda row: int(row["timestamp_ms"]))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, RuntimeError) as exc:
            last_error = f"{type(exc).__name__}:{exc}"
            if attempt == attempts:
                break
            time.sleep(min(2**attempt, 20))
    raise RuntimeError(f"BINGX_REQUEST_FAILED:{symbol}:{start_ms}:{end_ms}:{last_error}")


def expected_timestamps(start_ms: int, end_exclusive_ms: int) -> Iterable[int]:
    return range(start_ms, end_exclusive_ms, INTERVAL_MS)


def collect_symbol(symbol: str, out_dir: Path, start_ms: int, end_exclusive_ms: int) -> dict[str, Any]:
    rows_by_timestamp: dict[int, dict[str, Any]] = {}
    requests = 0
    cursor = start_ms
    while cursor < end_exclusive_ms:
        # BingX can return one fewer bar when a request spans the full 1,000-bar limit.
        # Keep each deterministic request below that boundary; filtering still enforces
        # the exact frozen half-open interval and detects conflicting duplicates.
        chunk_end_exclusive = min(cursor + SAFE_CHUNK_BARS * INTERVAL_MS, end_exclusive_ms)
        rows = request_chunk(symbol, cursor, chunk_end_exclusive)
        requests += 1
        for row in rows:
            timestamp_ms = int(row["timestamp_ms"])
            if cursor <= timestamp_ms < chunk_end_exclusive:
                prior = rows_by_timestamp.get(timestamp_ms)
                if prior is not None and prior != row:
                    raise RuntimeError(f"CONFLICTING_DUPLICATE:{symbol}:{timestamp_ms}")
                rows_by_timestamp[timestamp_ms] = row
        cursor = chunk_end_exclusive
        time.sleep(0.12)

    expected = list(expected_timestamps(start_ms, end_exclusive_ms))
    missing = [timestamp for timestamp in expected if timestamp not in rows_by_timestamp]
    unexpected = sorted(timestamp for timestamp in rows_by_timestamp if timestamp < start_ms or timestamp >= end_exclusive_ms)
    if missing or unexpected:
        raise RuntimeError(
            f"COVERAGE_FAIL:{symbol}:missing={len(missing)}:unexpected={len(unexpected)}:"
            f"first_missing={missing[:5]}"
        )
    ordered = [rows_by_timestamp[timestamp] for timestamp in expected]
    output = out_dir / f"{symbol.replace('-', '')}_1m_{start_ms}_{end_exclusive_ms}.csv.gz"
    with gzip.open(output, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(ordered)
    return {
        "symbol": symbol,
        "interval": INTERVAL,
        "start_ms": start_ms,
        "end_exclusive_ms": end_exclusive_ms,
        "start_utc": datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc).isoformat(),
        "end_exclusive_utc": datetime.fromtimestamp(end_exclusive_ms / 1000, tz=timezone.utc).isoformat(),
        "expected_row_count": len(expected),
        "row_count": len(ordered),
        "request_count": requests,
        "duplicate_timestamp_count": 0,
        "missing_interval_count": 0,
        "unexpected_timestamp_count": 0,
        "first_timestamp_ms": int(ordered[0]["timestamp_ms"]),
        "last_timestamp_ms": int(ordered[-1]["timestamp_ms"]),
        "file": output.name,
        "file_bytes": output.stat().st_size,
        "file_sha256": file_sha(output),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        sample = normalize_row([1_700_000_000_000, "10", "12", "9", "11", "3"])
        assert sample["timestamp_ms"] == 1_700_000_000_000
        assert sample["high"] == "12" and sample["low"] == "9"
        assert len(list(expected_timestamps(0, 180_000))) == 3
        assert SAFE_CHUNK_BARS == 999
        assert list(expected_timestamps(0, SAFE_CHUNK_BARS * INTERVAL_MS))[-1] == (SAFE_CHUNK_BARS - 1) * INTERVAL_MS
        print("PASS")
        return 0

    start_ms = utc_ms(START_UTC)
    end_exclusive_ms = utc_ms(END_EXCLUSIVE_UTC)
    if end_exclusive_ms <= start_ms or (end_exclusive_ms - start_ms) % INTERVAL_MS != 0:
        raise RuntimeError("INVALID_FROZEN_BOUNDARY")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    results = [collect_symbol(symbol, args.out_dir, start_ms, end_exclusive_ms) for symbol in SYMBOLS]
    expected_per_symbol = (end_exclusive_ms - start_ms) // INTERVAL_MS
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": "PASS_BINGX_1M_BACKFILL_STAGED",
        "source": {
            "base_url": BASE_URL,
            "endpoint": ENDPOINT,
            "auth_required": False,
            "interval": INTERVAL,
            "chunk_limit": CHUNK_LIMIT,
            "safe_chunk_bars": SAFE_CHUNK_BARS,
            "source_header": "BX-AI-SKILL",
        },
        "frozen_boundaries": {
            "start_utc": START_UTC,
            "end_exclusive_utc": END_EXCLUSIVE_UTC,
            "start_ms": start_ms,
            "end_exclusive_ms": end_exclusive_ms,
        },
        "symbols": list(SYMBOLS),
        "expected_rows_per_symbol": expected_per_symbol,
        "expected_total_rows": expected_per_symbol * len(SYMBOLS),
        "actual_total_rows": sum(int(row["row_count"]) for row in results),
        "results": results,
        "economics_inspected": False,
        "holdout_metrics_inspected": False,
        "strategy_rules_mutated": False,
        "canonical_mutated": False,
        "registry_mutated": False,
        "runtime_mutated": False,
        "formal_ledger_mutated": False,
        "shadow_mutated": False,
        "paper_mutated": False,
        "live_mutated": False,
        "protected_mutations": 0,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
        "next": "VERIFY_AND_SEAL_BACKFILL_PARTITIONS",
    }
    if manifest["actual_total_rows"] != manifest["expected_total_rows"]:
        raise RuntimeError("TOTAL_ROW_COUNT_MISMATCH")
    manifest["dataset_sha256"] = stable_sha(
        [{"symbol": row["symbol"], "file_sha256": row["file_sha256"]} for row in results]
    )
    manifest["receipt_sha256"] = stable_sha(manifest)
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "state": manifest["state"],
                "actual_total_rows": manifest["actual_total_rows"],
                "dataset_sha256": manifest["dataset_sha256"],
                "receipt_sha256": manifest["receipt_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
