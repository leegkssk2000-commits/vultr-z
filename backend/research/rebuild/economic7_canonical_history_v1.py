"""Immutable BingX 1m history with resumable public-response receipts.

No economics or order execution. Observed history remains development evidence.
Unknown volume units never acquire authority merely from a successful response.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import os
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

SCHEMA = "zel.economic7.canonical_history.v1"
BASE_URL = "https://open-api.bingx.com"
ENDPOINT = "/openApi/swap/v3/quote/klines"
MINUTE_MS = 60_000
DAY_MS = 86_400_000
MAX_BARS = 999
FIELDS = ("timestamp_ms", "open", "high", "low", "close", "volume")
Fetch = Callable[[str], tuple[int, bytes]]


class HistoryError(RuntimeError):
    """Preserved source evidence failed its explicit integrity contract."""


class RequestBudgetReached(HistoryError):
    """A bounded run can resume later without requesting completed chunks."""


def sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()


def utc_text(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, timezone.utc).isoformat()


def parse_utc(value: str) -> int:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HistoryError("INVALID_UTC_TIMESTAMP") from exc
    offset = parsed.utcoffset()
    if parsed.tzinfo is None or offset is None:
        raise HistoryError("TIMEZONE_REQUIRED")
    if offset.total_seconds() != 0:
        raise HistoryError("UTC_REQUIRED")
    value_ms = int(parsed.timestamp() * 1000)
    if parsed.microsecond or value_ms % MINUTE_MS:
        raise HistoryError("EXACT_MINUTE_BOUNDARY_REQUIRED")
    return value_ms


def immutable_bytes(path: Path, raw: bytes) -> None:
    """Atomic create-if-absent; never silently replace evidence."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != raw:
            raise HistoryError(f"IMMUTABLE_CONFLICT:{path.name}")
        return
    fd, temporary_name = tempfile.mkstemp(prefix=".staging-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != raw:
                raise HistoryError(f"IMMUTABLE_CONFLICT:{path.name}")
    finally:
        temporary.unlink(missing_ok=True)


def atomic_json(path: Path, value: Any) -> None:
    """Only mutable run status uses replacement; response evidence is immutable."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=".status-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(json_bytes(value))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def daily_windows(start_ms: int, end_ms: int) -> list[tuple[int, int]]:
    if start_ms % MINUTE_MS or end_ms % MINUTE_MS or end_ms <= start_ms:
        raise HistoryError("INVALID_MINUTE_RANGE")
    windows = []
    cursor = start_ms
    while cursor < end_ms:
        next_ms = min((cursor // DAY_MS + 1) * DAY_MS, end_ms)
        windows.append((cursor, next_ms))
        cursor = next_ms
    return windows


def request_windows(start_ms: int, end_ms: int) -> list[tuple[int, int]]:
    return [
        (cursor, min(cursor + MAX_BARS * MINUTE_MS, end_ms))
        for cursor in range(start_ms, end_ms, MAX_BARS * MINUTE_MS)
    ]


def decimal_value(value: Any, field: str) -> Decimal:
    if value is None or isinstance(value, bool):
        raise HistoryError(f"MISSING_OR_INVALID_FIELD:{field}")
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise HistoryError(f"INVALID_DECIMAL:{field}") from exc
    if not result.is_finite() or (result < 0 if field == "volume" else result <= 0):
        raise HistoryError(f"INVALID_DECIMAL_RANGE:{field}")
    return result


def normalize_row(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise HistoryError("NAMED_MAPPING_REQUIRED_NO_POSITIONAL_GUESS")
    missing = [field for field in FIELDS[1:] if field not in raw]
    if missing:
        raise HistoryError("MISSING_NAMED_FIELDS:" + ",".join(missing))
    timestamp_fields = [
        raw[key] for key in ("time", "openTime", "timestamp") if key in raw
    ]
    if not timestamp_fields:
        raise HistoryError("MISSING_TIMESTAMP_FIELD")
    timestamps = []
    for value in timestamp_fields:
        if isinstance(value, bool):
            raise HistoryError("INVALID_TIMESTAMP")
        try:
            ts_decimal = Decimal(str(value))
        except InvalidOperation as exc:
            raise HistoryError("INVALID_TIMESTAMP") from exc
        if not ts_decimal.is_finite() or ts_decimal != ts_decimal.to_integral_value():
            raise HistoryError("NON_INTEGER_TIMESTAMP")
        timestamps.append(int(ts_decimal))
    if len(set(timestamps)) != 1:
        raise HistoryError("CONFLICTING_TIMESTAMP_ALIASES")
    ts_ms = timestamps[0]
    if ts_ms < 0 or ts_ms % MINUTE_MS:
        raise HistoryError("TIMESTAMP_OFF_UTC_MINUTE_GRID")
    numbers = {field: decimal_value(raw[field], field) for field in FIELDS[1:]}
    if numbers["high"] < max(numbers["open"], numbers["close"], numbers["low"]):
        raise HistoryError("OHLC_HIGH_INVALID")
    if numbers["low"] > min(numbers["open"], numbers["close"], numbers["high"]):
        raise HistoryError("OHLC_LOW_INVALID")
    return {
        "timestamp_ms": ts_ms,
        **{field: format(value, "f") for field, value in numbers.items()},
    }


def response_rows(raw: bytes, start_ms: int, end_ms: int) -> list[dict[str, Any]]:
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise HistoryError("SOURCE_INVALID_JSON") from exc
    if not isinstance(payload, dict):
        raise HistoryError("SOURCE_RESPONSE_MAPPING_REQUIRED")
    if str(payload.get("code")) != "0":
        raise HistoryError(f"SOURCE_REJECTED_CODE:{payload.get('code')}")
    source_rows = payload.get("data")
    if not isinstance(source_rows, list):
        raise HistoryError("SOURCE_DATA_LIST_REQUIRED")
    if not source_rows:
        raise HistoryError("HISTORY_UNAVAILABLE_EMPTY_RESPONSE")
    indexed: dict[int, dict[str, Any]] = {}
    for source_row in source_rows:
        row = normalize_row(source_row)
        ts_ms = int(row["timestamp_ms"])
        if not start_ms <= ts_ms < end_ms:
            raise HistoryError(f"SOURCE_TIMESTAMP_OUTSIDE_REQUEST:{ts_ms}")
        if ts_ms in indexed:
            previous = indexed[ts_ms]
            if previous != row:
                raise HistoryError(f"CONFLICTING_DUPLICATE:{ts_ms}")
            raise HistoryError(f"DUPLICATE_TIMESTAMP:{ts_ms}")
        indexed[ts_ms] = row
    expected = range(start_ms, end_ms, MINUTE_MS)
    missing = [ts for ts in expected if ts not in indexed]
    if missing:
        raise HistoryError(
            f"HISTORY_GAP:missing={len(missing)}:first={missing[0]}:"
            f"requested={start_ms}:{end_ms}"
        )
    return [indexed[ts] for ts in expected]


def aggregate_rows(
    rows: Sequence[Mapping[str, Any]], minutes: int
) -> tuple[list[dict[str, Any]], list[int]]:
    if minutes not in (15, 30, 60):
        raise HistoryError("UNSUPPORTED_AGGREGATION")
    interval = minutes * MINUTE_MS
    buckets: dict[int, dict[int, Mapping[str, Any]]] = {}
    for row in rows:
        ts_ms = int(row["timestamp_ms"])
        if ts_ms % MINUTE_MS:
            raise HistoryError("AGGREGATION_OFF_GRID")
        bucket = buckets.setdefault(ts_ms // interval * interval, {})
        if ts_ms in bucket:
            raise HistoryError("AGGREGATION_DUPLICATE")
        bucket[ts_ms] = row
    output, incomplete = [], []
    for opening, bucket in sorted(buckets.items()):
        expected = list(range(opening, opening + interval, MINUTE_MS))
        if sorted(bucket) != expected:
            incomplete.append(opening)
            continue
        ordered = [bucket[ts] for ts in expected]
        output.append(
            {
                "timestamp_ms": opening,
                "open": ordered[0]["open"],
                "high": format(max(Decimal(str(row["high"])) for row in ordered), "f"),
                "low": format(min(Decimal(str(row["low"])) for row in ordered), "f"),
                "close": ordered[-1]["close"],
                "volume": format(
                    sum((Decimal(str(row["volume"])) for row in ordered), Decimal(0)),
                    "f",
                ),
            }
        )
    return output, incomplete


def csv_gzip(rows: Sequence[Mapping[str, Any]]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return gzip.compress(buffer.getvalue().encode(), mtime=0)


def public_fetch(url: str) -> tuple[int, bytes]:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": SCHEMA},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return int(response.status), response.read()
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read()


def saved_response(
    out: Path,
    symbol: str,
    start_ms: int,
    end_ms: int,
    budget: dict[str, int],
    fetch: Fetch,
) -> tuple[bytes, dict[str, Any]]:
    query = {
        "symbol": symbol,
        "interval": "1m",
        "timeZone": 0,
        "startTime": start_ms,
        "endTime": end_ms - 1,
        "limit": 1000,
    }
    url = BASE_URL + ENDPOINT + "?" + urllib.parse.urlencode(query)
    stem = out / "requests" / symbol / f"{start_ms}_{end_ms}"
    body_path = stem.with_suffix(".body")
    receipt_path = stem.with_suffix(".receipt.json")
    if receipt_path.exists():
        receipt = json.loads(receipt_path.read_bytes())
        if (
            {k: v for k, v in receipt.get("query", {}).items() if k != "timestamp"}
            != query
            or receipt.get("url", "").split("?")[0] != BASE_URL + ENDPOINT
            or receipt.get("source") != BASE_URL + ENDPOINT
        ):
            raise HistoryError("CACHED_RECEIPT_REQUEST_MISMATCH")
        if not body_path.exists():
            raise HistoryError("CACHED_BODY_MISSING")
        raw = body_path.read_bytes()
        if sha_bytes(raw) != receipt.get("body_sha256"):
            raise HistoryError("CACHED_BODY_HASH_MISMATCH")
        if receipt.get("http_status") != 200:
            raise HistoryError(f"SOURCE_HTTP_STATUS:{receipt.get('http_status')}")
        budget["reused"] += 1
        return raw, receipt
    if body_path.exists():
        raise HistoryError("ORPHAN_RAW_BODY_REQUIRES_RECEIPT_RECOVERY")
    if budget["maximum"] and budget["used"] >= budget["maximum"]:
        raise RequestBudgetReached("MAX_REQUESTS_REACHED")
    requested_at = datetime.now(timezone.utc).isoformat()
    query["timestamp"] = int(datetime.now(timezone.utc).timestamp() * 1000)
    url = BASE_URL + ENDPOINT + "?" + urllib.parse.urlencode(query)
    budget["used"] += 1
    try:
        status, raw = fetch(url)
    except OSError as exc:
        transport = {
            "schema": SCHEMA + ".transport_failure",
            "url": url,
            "query": query,
            "requested_at_utc": requested_at,
            "body_received": False,
            "error": f"{type(exc).__name__}:{exc}",
        }
        immutable_bytes(
            stem.with_suffix(
                ".transport." + sha_bytes(json_bytes(transport)) + ".json"
            ),
            json_bytes(transport),
        )
        raise HistoryError(f"SOURCE_TRANSPORT_FAILURE:{type(exc).__name__}") from exc
    if status != 200:
        attempt = str(int(datetime.now(timezone.utc).timestamp() * 1_000_000))
        body_path = stem.with_suffix(f".http{status}.{attempt}.body")
        receipt_path = stem.with_suffix(f".http{status}.{attempt}.receipt.json")
    # The unparsed original body and request receipt precede JSON/schema checks.
    immutable_bytes(body_path, raw)
    receipt = {
        "schema": SCHEMA + ".http_response",
        "source": BASE_URL + ENDPOINT,
        "url": url,
        "query": query,
        "symbol": symbol,
        "interval": "1m",
        "start_ms": start_ms,
        "end_exclusive_ms": end_ms,
        "requested_at_utc": requested_at,
        "received_at_utc": datetime.now(timezone.utc).isoformat(),
        "http_status": status,
        "body_path": str(body_path.relative_to(out)),
        "body_sha256": sha_bytes(raw),
        "body_bytes": len(raw),
        "source_timezone": "UTC",
        "timestamp_semantics": "UNVERIFIED_REPORTED_GRID_NO_OPEN_CLOSE_AUTHORITY",
        "volume_unit": "UNKNOWN",
    }
    immutable_bytes(receipt_path, json_bytes(receipt))
    if status != 200:
        raise HistoryError(f"SOURCE_HTTP_STATUS:{status}")
    return raw, receipt


def verify_daily_receipt(
    out: Path,
    receipt: Mapping[str, Any],
    symbol: str,
    start_ms: int,
    end_ms: int,
) -> None:
    if not isinstance(receipt, dict):
        raise HistoryError("DAILY_RECEIPT_MAPPING_REQUIRED")
    expected_rows = (end_ms - start_ms) // MINUTE_MS
    unsigned = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    if receipt.get("receipt_sha256") != sha_bytes(json_bytes(unsigned)):
        raise HistoryError("DAILY_RECEIPT_SELF_HASH_MISMATCH")
    if (
        receipt.get("schema") != SCHEMA + ".daily"
        or receipt.get("symbol") != symbol
        or receipt.get("start_ms") != start_ms
        or receipt.get("end_exclusive_ms") != end_ms
        or receipt.get("start_utc") != utc_text(start_ms)
        or receipt.get("end_exclusive_utc") != utc_text(end_ms)
        or receipt.get("rows_1m") != expected_rows
        or receipt.get("expected_rows_1m") != expected_rows
        or receipt.get("gap_count") != 0
        or receipt.get("duplicate_count") != 0
        or receipt.get("volume_unit") != "UNKNOWN"
        or receipt.get("synthetic_fill") is not False
        or receipt.get("forward_fill") is not False
    ):
        raise HistoryError("DAILY_RECEIPT_IDENTITY_OR_COVERAGE_MISMATCH")
    artifacts = receipt.get("artifacts")
    sources = receipt.get("source_receipts")
    windows = request_windows(start_ms, end_ms)
    if (
        not isinstance(artifacts, list)
        or len(artifacts) != 4
        or not all(isinstance(item, dict) for item in artifacts)
        or [item.get("timeframe_minutes") for item in artifacts] != [1, 15, 30, 60]
    ):
        raise HistoryError("DAILY_REQUIRED_ARTIFACT_SET_MISMATCH")
    if (
        not isinstance(sources, list)
        or len(sources) != len(windows)
        or not all(isinstance(item, dict) for item in sources)
    ):
        raise HistoryError("DAILY_REQUIRED_SOURCE_CHUNKS_MISMATCH")
    all_rows: list[dict[str, Any]] = []
    for source, (chunk_start, chunk_end) in zip(sources, windows):
        stem = Path("requests") / symbol / f"{chunk_start}_{chunk_end}"
        expected_receipt = str(stem.with_suffix(".receipt.json"))
        expected_body = str(stem.with_suffix(".body"))
        expected_normalized = str(
            Path("normalized_chunks") / symbol / f"{chunk_start}_{chunk_end}.csv.gz"
        )
        if (
            source.get("path") != expected_receipt
            or source.get("normalized_path") != expected_normalized
        ):
            raise HistoryError("DAILY_SOURCE_CHUNK_PATH_MISMATCH")
        receipt_raw = (out / expected_receipt).read_bytes()
        if sha_bytes(receipt_raw) != source.get("sha256"):
            raise HistoryError("DAILY_SOURCE_RECEIPT_HASH_MISMATCH")
        source_receipt = json.loads(receipt_raw)
        if not isinstance(source_receipt, dict):
            raise HistoryError("DAILY_SOURCE_RECEIPT_MAPPING_REQUIRED")
        query = source_receipt.get("query", {})
        expected_query = {
            "symbol": symbol,
            "interval": "1m",
            "timeZone": 0,
            "startTime": chunk_start,
            "endTime": chunk_end - 1,
            "limit": 1000,
        }
        if (
            source_receipt.get("body_path") != expected_body
            or source_receipt.get("source") != BASE_URL + ENDPOINT
            or source_receipt.get("symbol") != symbol
            or source_receipt.get("interval") != "1m"
            or source_receipt.get("start_ms") != chunk_start
            or source_receipt.get("end_exclusive_ms") != chunk_end
            or source_receipt.get("http_status") != 200
            or not isinstance(query, dict)
            or {key: value for key, value in query.items() if key != "timestamp"}
            != expected_query
        ):
            raise HistoryError("DAILY_SOURCE_REQUEST_IDENTITY_MISMATCH")
        body = (out / expected_body).read_bytes()
        if sha_bytes(body) != source_receipt.get("body_sha256"):
            raise HistoryError("DAILY_SOURCE_BODY_HASH_MISMATCH")
        source_rows = response_rows(body, chunk_start, chunk_end)
        normalized = (out / expected_normalized).read_bytes()
        if sha_bytes(normalized) != source.get("normalized_sha256"):
            raise HistoryError("DAILY_NORMALIZED_CHUNK_HASH_MISMATCH")
        if normalized != csv_gzip(source_rows):
            raise HistoryError("DAILY_NORMALIZED_CHUNK_SOURCE_MISMATCH")
        all_rows.extend(source_rows)
    if len(all_rows) != expected_rows:
        raise HistoryError("DAILY_VERIFIED_ROW_COUNT_MISMATCH")
    incomplete: list[int]
    for artifact, minutes in zip(artifacts, (1, 15, 30, 60)):
        if minutes == 1:
            aggregate, incomplete = all_rows, []
        else:
            aggregate, incomplete = aggregate_rows(all_rows, minutes)
        expected_path = str(
            Path(f"{minutes}m") / symbol / f"{start_ms}_{end_ms}.csv.gz"
        )
        if (
            artifact.get("path") != expected_path
            or artifact.get("row_count") != len(aggregate)
            or artifact.get("incomplete_boundary_buckets_excluded") != incomplete
        ):
            raise HistoryError("DAILY_ARTIFACT_IDENTITY_OR_COVERAGE_MISMATCH")
        actual = (out / expected_path).read_bytes()
        if sha_bytes(actual) != artifact.get("sha256"):
            raise HistoryError("DAILY_ARTIFACT_HASH_MISMATCH")
        if actual != csv_gzip(aggregate):
            raise HistoryError("DAILY_ARTIFACT_SOURCE_BINDING_MISMATCH")


def collect(
    *,
    out: Path,
    symbols: Sequence[str],
    start_ms: int,
    end_ms: int,
    max_requests: int = 0,
    fetch: Fetch = public_fetch,
) -> dict[str, Any]:
    if not symbols or len(set(symbols)) != len(symbols):
        raise HistoryError("NONEMPTY_UNIQUE_SYMBOLS_REQUIRED")
    if any(re.fullmatch(r"[A-Z0-9]+-USDT", symbol) is None for symbol in symbols):
        raise HistoryError("INVALID_BINGX_USDT_SYMBOL")
    if max_requests < 0:
        raise HistoryError("NEGATIVE_REQUEST_BUDGET")
    windows = daily_windows(start_ms, end_ms)
    if (
        end_ms
        > int(datetime.now(timezone.utc).timestamp() * 1000) // MINUTE_MS * MINUTE_MS
    ):
        raise HistoryError("CURRENT_OR_FUTURE_UNCLOSED_BAR_REQUESTED")
    out.mkdir(parents=True, exist_ok=True)
    freeze = {
        "schema": SCHEMA,
        "source": BASE_URL + ENDPOINT,
        "symbols": list(symbols),
        "start_ms": start_ms,
        "end_exclusive_ms": end_ms,
        "source_timezone": "UTC",
        "source_interval": "1m",
        "timestamp_semantics": "UNVERIFIED_REPORTED_GRID_NO_OPEN_CLOSE_AUTHORITY",
        "aggregation_minutes": [15, 30, 60],
        "volume_unit": "UNKNOWN",
        "volume_authority": "UNVERIFIED_NO_BASE_OR_CONTRACT_UNIT_CLAIM",
        "cost_authority": "UNBOUND_NOT_ECONOMIC_INPUT",
        "code_sha256": sha_bytes(Path(__file__).read_bytes()),
        "synthetic_fill": False,
        "forward_fill": False,
        "historical_evidence_class": "DEVELOPMENT_HISTORY_NOT_FRESH_OOS",
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_authority": "BLOCKED",
    }
    immutable_bytes(out / "FREEZE.json", json_bytes(freeze))
    budget = {"used": 0, "reused": 0, "maximum": max_requests}
    symbol_reports = []
    errors = []
    stopped = False
    for symbol in symbols:
        completed = []
        for day_start, day_end in windows:
            daily_receipt_path = (
                out / "daily_receipts" / symbol / f"{day_start}_{day_end}.json"
            )
            if daily_receipt_path.exists():
                day_receipt = json.loads(daily_receipt_path.read_bytes())
                verify_daily_receipt(out, day_receipt, symbol, day_start, day_end)
                completed.append(day_receipt)
                continue
            day_rows = []
            source_receipts = []
            try:
                for chunk_start, chunk_end in request_windows(day_start, day_end):
                    raw, source_receipt = saved_response(
                        out, symbol, chunk_start, chunk_end, budget, fetch
                    )
                    rows = response_rows(raw, chunk_start, chunk_end)
                    normalized_path = (
                        out
                        / "normalized_chunks"
                        / symbol
                        / f"{chunk_start}_{chunk_end}.csv.gz"
                    )
                    immutable_bytes(normalized_path, csv_gzip(rows))
                    source_path = (
                        Path("requests")
                        / symbol
                        / f"{chunk_start}_{chunk_end}.receipt.json"
                    )
                    source_receipts.append(
                        {
                            "path": str(source_path),
                            "sha256": sha_bytes(json_bytes(source_receipt)),
                            "normalized_path": str(normalized_path.relative_to(out)),
                            "normalized_sha256": sha_bytes(
                                normalized_path.read_bytes()
                            ),
                        }
                    )
                    day_rows.extend(rows)
            except RequestBudgetReached as exc:
                errors.append(
                    {"symbol": symbol, "day_start": day_start, "reason": str(exc)}
                )
                stopped = True
                break
            except (HistoryError, OSError, ValueError) as exc:
                error = {
                    "symbol": symbol,
                    "day_start": day_start,
                    "reason": f"{type(exc).__name__}:{exc}",
                    "new_requests_used": budget["used"],
                    "status": "HOLD_SOURCE_INTEGRITY",
                }
                errors.append(error)
                error_bytes = json_bytes(error)
                immutable_bytes(
                    out / "failures" / (sha_bytes(error_bytes) + ".json"),
                    error_bytes,
                )
                # A failed interval is never bypassed to fabricate contiguous history.
                break
            artifacts = []
            incomplete: list[int]
            for minutes in (1, 15, 30, 60):
                if minutes == 1:
                    aggregate, incomplete = day_rows, []
                else:
                    aggregate, incomplete = aggregate_rows(day_rows, minutes)
                target = out / f"{minutes}m" / symbol / f"{day_start}_{day_end}.csv.gz"
                raw_csv = csv_gzip(aggregate)
                immutable_bytes(target, raw_csv)
                artifacts.append(
                    {
                        "timeframe_minutes": minutes,
                        "path": str(target.relative_to(out)),
                        "sha256": sha_bytes(raw_csv),
                        "row_count": len(aggregate),
                        "incomplete_boundary_buckets_excluded": incomplete,
                    }
                )
            day_receipt = {
                "schema": SCHEMA + ".daily",
                "symbol": symbol,
                "start_ms": day_start,
                "end_exclusive_ms": day_end,
                "start_utc": utc_text(day_start),
                "end_exclusive_utc": utc_text(day_end),
                "rows_1m": len(day_rows),
                "expected_rows_1m": (day_end - day_start) // MINUTE_MS,
                "gap_count": 0,
                "duplicate_count": 0,
                "source_receipts": source_receipts,
                "artifacts": artifacts,
                "volume_unit": "UNKNOWN",
                "synthetic_fill": False,
                "forward_fill": False,
            }
            day_receipt["receipt_sha256"] = sha_bytes(json_bytes(day_receipt))
            immutable_bytes(daily_receipt_path, json_bytes(day_receipt))
            completed.append(day_receipt)
        symbol_reports.append(
            {
                "symbol": symbol,
                "completed_days_or_boundary_parts": len(completed),
                "requested_days_or_boundary_parts": len(windows),
                "rows_1m": sum(day["rows_1m"] for day in completed),
                "expected_rows_1m": (end_ms - start_ms) // MINUTE_MS,
                "coverage_start_ms": completed[0]["start_ms"] if completed else None,
                "coverage_end_exclusive_ms": (
                    completed[-1]["end_exclusive_ms"] if completed else None
                ),
                "coverage_days": sum(day["rows_1m"] for day in completed) / 1440,
                "complete": len(completed) == len(windows),
            }
        )
        if stopped:
            break
    all_complete = len(symbol_reports) == len(symbols) and all(
        item["complete"] for item in symbol_reports
    )
    state = (
        "DATA_VALID_VOLUME_AUTHORITY_UNKNOWN"
        if all_complete
        else "PARTIAL_REQUEST_LIMIT" if stopped else "HOLD_SOURCE_INTEGRITY"
    )
    manifest: dict[str, Any] = {
        **freeze,
        "state": state,
        "data_integrity_complete": all_complete,
        "promotion_authority": False,
        "requested_days": (end_ms - start_ms) / DAY_MS,
        "new_requests_used": budget["used"],
        "source_responses_reused": budget["reused"],
        "max_requests_this_run": max_requests,
        "symbols_coverage": symbol_reports,
        "symbols_not_started": list(symbols[len(symbol_reports) :]),
        "failures_or_limit": errors,
        "notes": [
            "No unsupported interval is filled, inferred, or silently skipped.",
            "A failed old interval does not establish the provider's maximum history.",
            "An explicit later requested range needs a separate immutable output root.",
            "Only complete UTC-aligned aggregate buckets are emitted.",
            "Unknown volume units block volume-sensitive economic authority.",
            "Collection completeness is not Core or fresh OOS promotion.",
        ],
    }
    manifest["manifest_sha256"] = sha_bytes(json_bytes(manifest))
    immutable_bytes(
        out / "run_receipts" / (manifest["manifest_sha256"] + ".json"),
        json_bytes(manifest),
    )
    atomic_json(out / "MANIFEST.json", manifest)
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--start", required=True, help="Inclusive UTC minute timestamp")
    parser.add_argument("--end", required=True, help="Exclusive UTC minute timestamp")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--max-requests", type=int, default=1, help="New HTTP calls; 0 is unlimited"
    )
    args = parser.parse_args(argv)
    import fcntl

    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / "collection.lock").open("a") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(json.dumps({"state": "HOLD_COLLECTION_ALREADY_RUNNING"}))
            return 2
        try:
            report = collect(
                out=args.out,
                symbols=args.symbols,
                start_ms=parse_utc(args.start),
                end_ms=parse_utc(args.end),
                max_requests=args.max_requests,
            )
        except (HistoryError, OSError, ValueError) as exc:
            print(
                json.dumps(
                    {"state": "HOLD_INTEGRITY", "reason": f"{type(exc).__name__}:{exc}"}
                )
            )
            return 2
    print(
        json.dumps(
            {
                "state": report["state"],
                "requested_days": report["requested_days"],
                "new_requests_used": report["new_requests_used"],
                "symbols_coverage": report["symbols_coverage"],
                "failures_or_limit": report["failures_or_limit"],
            },
            sort_keys=True,
        )
    )
    return 0 if report["data_integrity_complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
