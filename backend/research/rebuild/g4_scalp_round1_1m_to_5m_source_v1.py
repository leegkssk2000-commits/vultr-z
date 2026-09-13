#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE_ROOT = ROOT / "research/development_evidence/G4_SCALP_INTRADAY_REBASE_V1"
CONTRACT_PATH = EVIDENCE_ROOT / "ROUND1_CONTRACT.json"
DEFAULT_CACHE = Path("/tmp/g4_scalp_round1_cache")
DEFAULT_RECEIPT = EVIDENCE_ROOT / "ROUND1_NATIVE/SOURCE_REPAIR_RECEIPT.json"

VERSION = "G4_SCALP_ROUND1_1M_TO_5M_SOURCE_V1"
SCHEMA = "zel.g4_scalp.round1.source_repair.1m_to_5m.v1"
BASE_URL = "https://open-api.bingx.com"
ENDPOINT = "/openApi/swap/v3/quote/klines"
ONE_MINUTE_MS = 60_000
FIVE_MINUTE_MS = 300_000
CHUNK_LIMIT = 1000
SAFE_CHUNK_BARS = CHUNK_LIMIT - 1
WARMUP_5M_BARS = 320
POST_WINDOW_5M_BARS = 48
OLD_COLLECTOR_BRANCH = "zel-bingx-1m-backfill-stage-v1"
OLD_COLLECTOR_PATH = "backend/tools/zel_bingx_1m_backfill_stage_v1.py"
OLD_COLLECTOR_SHA256_GIT_BLOB = "73a1218dfd9427743728fc943f33abef759640e8"


def stable_sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def utc_ms(value: str) -> int:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp() * 1000)


def read_contract() -> dict[str, Any]:
    value = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("ROUND1_CONTRACT_OBJECT_REQUIRED")
    return value


def _request_payload(symbol: str, start_ms: int, end_ms: int, *, attempts: int = 6) -> Mapping[str, Any]:
    params = {
        "symbol": symbol,
        "interval": "1m",
        "startTime": int(start_ms),
        "endTime": int(end_ms),
        "limit": CHUNK_LIMIT,
    }
    url = f"{BASE_URL}{ENDPOINT}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": VERSION,
            "X-SOURCE-KEY": "BX-AI-SKILL",
        },
    )
    last_error: str | None = None
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=35) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, Mapping):
                raise RuntimeError("BINGX_PAYLOAD_OBJECT_REQUIRED")
            if int(payload.get("code", -1)) != 0:
                raise RuntimeError(f"BINGX_CODE:{payload.get('code')}:{payload.get('msg')}")
            return payload
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, RuntimeError) as exc:
            last_error = f"{type(exc).__name__}:{exc}"
            if attempt == attempts:
                break
            time.sleep(min(2 ** (attempt - 1), 12))
    raise RuntimeError(f"BINGX_1M_REQUEST_FAILED:{symbol}:{start_ms}:{end_ms}:{last_error}")


def _extract_rows(payload: Mapping[str, Any]) -> list[Any]:
    data = payload.get("data")
    if isinstance(data, list):
        return data
    if isinstance(data, Mapping):
        for key in ("data", "rows", "items", "list", "klines"):
            child = data.get(key)
            if isinstance(child, list):
                return child
    raise RuntimeError("BINGX_1M_ROWS_MISSING")


def _normalize(raw: Any) -> dict[str, float | int]:
    if isinstance(raw, Mapping):
        ts = raw.get("openTime", raw.get("time", raw.get("timestamp")))
        o, h, l, c = raw.get("open"), raw.get("high"), raw.get("low"), raw.get("close")
        v = raw.get("volume", raw.get("vol", raw.get("baseVolume", 0.0)))
    elif isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)) and len(raw) >= 5:
        ts, o, h, l, c = raw[:5]
        v = raw[5] if len(raw) > 5 else 0.0
    else:
        raise RuntimeError(f"UNSUPPORTED_1M_ROW:{type(raw).__name__}")
    row = {
        "ts_ms": int(float(ts)),
        "open": float(o),
        "high": float(h),
        "low": float(l),
        "close": float(c),
        "volume": float(v or 0.0),
    }
    if not all(math.isfinite(float(row[k])) for k in ("open", "high", "low", "close", "volume")):
        raise RuntimeError(f"NONFINITE_1M_ROW:{row['ts_ms']}")
    if min(float(row[k]) for k in ("open", "high", "low", "close")) <= 0.0:
        raise RuntimeError(f"NONPOSITIVE_1M_PRICE:{row['ts_ms']}")
    if float(row["high"]) < max(float(row["open"]), float(row["close"]), float(row["low"])):
        raise RuntimeError(f"OHLC_HIGH_INVALID:{row['ts_ms']}")
    if float(row["low"]) > min(float(row["open"]), float(row["close"]), float(row["high"])):
        raise RuntimeError(f"OHLC_LOW_INVALID:{row['ts_ms']}")
    if float(row["volume"]) < 0.0:
        raise RuntimeError(f"NEGATIVE_1M_VOLUME:{row['ts_ms']}")
    return row


def _request_chunk(symbol: str, start_ms: int, end_ms: int) -> list[dict[str, float | int]]:
    rows = [_normalize(raw) for raw in _extract_rows(_request_payload(symbol, start_ms, end_ms))]
    return sorted(rows, key=lambda row: int(row["ts_ms"]))


def _ranges(values: Sequence[int]) -> Iterable[tuple[int, int]]:
    if not values:
        return
    start = prev = int(values[0])
    for ts in values[1:]:
        ts = int(ts)
        if ts != prev + ONE_MINUTE_MS:
            yield start, prev + ONE_MINUTE_MS
            start = ts
        prev = ts
    yield start, prev + ONE_MINUTE_MS


def fetch_exact_1m(symbol: str, start_ms: int, end_ms: int) -> tuple[list[dict[str, float | int]], dict[str, Any]]:
    if start_ms % ONE_MINUTE_MS or end_ms % ONE_MINUTE_MS or end_ms <= start_ms:
        raise RuntimeError("UNALIGNED_1M_WINDOW")
    rows_by_ts: dict[int, dict[str, float | int]] = {}
    requests = 0
    conflicting_duplicates = 0
    cursor = start_ms
    while cursor < end_ms:
        chunk_end = min(cursor + SAFE_CHUNK_BARS * ONE_MINUTE_MS, end_ms)
        rows = _request_chunk(symbol, cursor, chunk_end)
        requests += 1
        for row in rows:
            ts = int(row["ts_ms"])
            if cursor <= ts < chunk_end:
                prior = rows_by_ts.get(ts)
                if prior is not None and prior != row:
                    conflicting_duplicates += 1
                    raise RuntimeError(f"CONFLICTING_1M_DUPLICATE:{symbol}:{ts}")
                rows_by_ts[ts] = row
        cursor = chunk_end
        time.sleep(0.06)

    repair_rounds: list[dict[str, Any]] = []
    for repair_round in range(1, 3):
        missing = [ts for ts in range(start_ms, end_ms, ONE_MINUTE_MS) if ts not in rows_by_ts]
        if not missing:
            break
        repaired_before = len(missing)
        range_count = 0
        for gap_start, gap_end in _ranges(missing):
            cursor = gap_start
            while cursor < gap_end:
                chunk_end = min(cursor + SAFE_CHUNK_BARS * ONE_MINUTE_MS, gap_end)
                rows = _request_chunk(symbol, cursor, chunk_end)
                requests += 1
                range_count += 1
                for row in rows:
                    ts = int(row["ts_ms"])
                    if start_ms <= ts < end_ms:
                        prior = rows_by_ts.get(ts)
                        if prior is not None and prior != row:
                            raise RuntimeError(f"CONFLICTING_1M_DUPLICATE_REPAIR:{symbol}:{ts}")
                        rows_by_ts[ts] = row
                cursor = chunk_end
                time.sleep(0.10)
        missing_after = [ts for ts in range(start_ms, end_ms, ONE_MINUTE_MS) if ts not in rows_by_ts]
        repair_rounds.append({
            "round": repair_round,
            "missing_before": repaired_before,
            "missing_after": len(missing_after),
            "gap_requests": range_count,
            "first_missing_after": missing_after[:10],
        })
        if not missing_after:
            break

    expected_count = (end_ms - start_ms) // ONE_MINUTE_MS
    missing = [ts for ts in range(start_ms, end_ms, ONE_MINUTE_MS) if ts not in rows_by_ts]
    if missing:
        raise RuntimeError(f"ONE_MINUTE_COVERAGE_FAIL:{symbol}:missing={len(missing)}:first={missing[:10]}")
    rows = [rows_by_ts[ts] for ts in range(start_ms, end_ms, ONE_MINUTE_MS)]
    if len(rows) != expected_count:
        raise RuntimeError(f"ONE_MINUTE_COUNT_FAIL:{symbol}:{len(rows)}!={expected_count}")
    return rows, {
        "rows_1m": len(rows),
        "expected_rows_1m": expected_count,
        "requests": requests,
        "repair_rounds": repair_rounds,
        "conflicting_duplicates": conflicting_duplicates,
        "first_ts": int(rows[0]["ts_ms"]),
        "last_ts": int(rows[-1]["ts_ms"]),
        "coverage_pass": True,
    }


def aggregate_exact_5m(rows_1m: Sequence[Mapping[str, Any]], start_ms: int, end_ms: int) -> list[dict[str, float | int]]:
    if start_ms % FIVE_MINUTE_MS or end_ms % FIVE_MINUTE_MS or end_ms <= start_ms:
        raise RuntimeError("UNALIGNED_5M_WINDOW")
    by_ts = {int(row["ts_ms"]): row for row in rows_1m}
    if len(by_ts) != len(rows_1m):
        raise RuntimeError("DUPLICATE_1M_INPUT_TO_AGGREGATOR")
    out: list[dict[str, float | int]] = []
    for bucket in range(start_ms, end_ms, FIVE_MINUTE_MS):
        expected = [bucket + i * ONE_MINUTE_MS for i in range(5)]
        if any(ts not in by_ts for ts in expected):
            missing = [ts for ts in expected if ts not in by_ts]
            raise RuntimeError(f"FIVE_MINUTE_BUCKET_INCOMPLETE:{bucket}:{missing}")
        group = [by_ts[ts] for ts in expected]
        out.append({
            "ts_ms": bucket,
            "open": float(group[0]["open"]),
            "high": max(float(row["high"]) for row in group),
            "low": min(float(row["low"]) for row in group),
            "close": float(group[-1]["close"]),
            "volume": sum(float(row.get("volume", 0.0)) for row in group),
        })
    expected_5m = (end_ms - start_ms) // FIVE_MINUTE_MS
    if len(out) != expected_5m:
        raise RuntimeError(f"FIVE_MINUTE_COUNT_FAIL:{len(out)}!={expected_5m}")
    for idx, row in enumerate(out):
        expected_ts = start_ms + idx * FIVE_MINUTE_MS
        if int(row["ts_ms"]) != expected_ts:
            raise RuntimeError(f"FIVE_MINUTE_CONTINUITY_FAIL:{idx}:{row['ts_ms']}!={expected_ts}")
    return out


def _self_test() -> None:
    start = 300_000
    rows = []
    for i in range(10):
        px = 100.0 + i
        rows.append({
            "ts_ms": start + i * ONE_MINUTE_MS,
            "open": px,
            "high": px + 2.0,
            "low": px - 1.0,
            "close": px + 1.0,
            "volume": float(i + 1),
        })
    agg = aggregate_exact_5m(rows, start, start + 10 * ONE_MINUTE_MS)
    assert len(agg) == 2
    assert agg[0]["open"] == 100.0 and agg[0]["close"] == 105.0
    assert agg[0]["high"] == 106.0 and agg[0]["low"] == 99.0
    assert agg[0]["volume"] == 15.0
    broken = list(rows)
    del broken[3]
    try:
        aggregate_exact_5m(broken, start, start + 10 * ONE_MINUTE_MS)
    except RuntimeError as exc:
        assert "FIVE_MINUTE_BUCKET_INCOMPLETE" in str(exc)
    else:
        raise AssertionError("missing 1m row must fail closed")


def prepare(cache_dir: Path, receipt_path: Path) -> dict[str, Any]:
    _self_test()
    contract = read_contract()
    window_start = utc_ms(str(contract["window"]["start_utc_inclusive"]))
    window_end = utc_ms(str(contract["window"]["end_utc_exclusive"]))
    fetch_start = window_start - WARMUP_5M_BARS * FIVE_MINUTE_MS
    fetch_end = window_end + POST_WINDOW_5M_BARS * FIVE_MINUTE_MS
    cache_dir.mkdir(parents=True, exist_ok=True)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    symbol_receipts: dict[str, Any] = {}

    for symbol in contract["universe"]["symbols"]:
        cache_path = cache_dir / f"{str(symbol).replace('-', '_')}_5m.json.gz"
        print(f"SOURCE_REPAIR_SYMBOL_START:{symbol}", flush=True)
        rows_1m, source_receipt = fetch_exact_1m(str(symbol), fetch_start, fetch_end)
        rows_5m = aggregate_exact_5m(rows_1m, fetch_start, fetch_end)
        with gzip.open(cache_path, "wt", encoding="utf-8", compresslevel=6) as fh:
            json.dump(rows_5m, fh, separators=(",", ":"), allow_nan=False)
        source_receipt.update({
            "rows_5m": len(rows_5m),
            "expected_rows_5m": (fetch_end - fetch_start) // FIVE_MINUTE_MS,
            "source_1m_sha256": stable_sha(rows_1m),
            "aggregated_5m_sha256": stable_sha(rows_5m),
            "cache_file": cache_path.name,
            "aggregation": {
                "bucket_ms": FIVE_MINUTE_MS,
                "required_1m_rows_per_bucket": 5,
                "open": "first_1m_open",
                "high": "max_1m_high",
                "low": "min_1m_low",
                "close": "last_1m_close",
                "volume": "sum_1m_volume",
                "missing_1m_policy": "FAIL_CLOSED_NO_SYNTHETIC_FILL",
            },
        })
        symbol_receipts[str(symbol)] = source_receipt
        print(f"SOURCE_REPAIR_SYMBOL_COMPLETE:{symbol}:5m={len(rows_5m)}", flush=True)
        del rows_1m
        del rows_5m

    receipt = {
        "schema_version": SCHEMA,
        "state": "ROUND1_SOURCE_REPAIRED_EXACT_1M_TO_5M",
        "scope_key": contract.get("scope_key"),
        "issue": contract.get("issue"),
        "window_start_ms": window_start,
        "window_end_ms": window_end,
        "fetch_start_ms": fetch_start,
        "fetch_end_ms": fetch_end,
        "symbols": symbol_receipts,
        "source": {
            "exchange": "BingX",
            "endpoint": f"{BASE_URL}{ENDPOINT}",
            "interval": "1m",
            "collector_lineage_reused": True,
            "old_collector_branch": OLD_COLLECTOR_BRANCH,
            "old_collector_path": OLD_COLLECTOR_PATH,
            "old_collector_git_blob_sha": OLD_COLLECTOR_SHA256_GIT_BLOB,
            "historical_rows_fetched_from_same_public_1m_endpoint": True,
            "old_artifact_rows_silently_reused": False,
        },
        "integrity": {
            "exact_1m_continuity_required": True,
            "exact_five_rows_per_5m_bucket_required": True,
            "synthetic_fill": False,
            "forward_fill": False,
            "window_shortening": False,
            "strategy_rule_change": False,
            "cost_change": False,
            "selection_authority": False,
            "promotion_authority": False,
            "order_authority": "BLOCKED",
            "live_trade_authority": "BLOCKED",
        },
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"state": receipt["state"], "symbols": list(symbol_receipts), "receipt_sha256": receipt["receipt_sha256"]}, sort_keys=True), flush=True)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        _self_test()
        print("SELF_TEST_PASS")
        return
    prepare(args.cache_dir, args.receipt)


if __name__ == "__main__":
    main()
