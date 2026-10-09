"""Read-only, stdlib audit of the three pinned canonical BingX archives.

Suitable for `python3 - --runtime-root PATH` with this file supplied on stdin.
No collector imports, HTTP requests, cache writes, signals, PnL, or orders.
Reported 23:59 minute rows are provenance witnesses, not certification of
historical open/close semantics or actual historical delivery/fill clocks.
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
import stat
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "zel.issue1388.canonical_daily_close_audit.v1"
HISTORY_SCHEMA = "zel.economic7.canonical_history.v1"
SOURCE = "https://open-api.bingx.com/openApi/swap/v3/quote/klines"
RUNTIME_ROOT = "/home/z/z/runtime/economic7_campaign_20260915"
SYMBOLS = ("BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "LINK-USDT", "DOGE-USDT")
MINUTE_MS, DAY_MS = 60_000, 86_400_000
START_MS, CUTOFF_MS = 1757894400000, 1789430400000
GAP_DAY_MS, GAP_START_MS, GAP_END_MS = 1770940800000, 1771014720000, 1771014960000
REQUIRED_SUFFIX_DAYS = 361
COLLECTOR_CODE_SHA256 = "2605da3467fc2442b8c2eaa9755ed7e89780907dbd7d2aef544bf37a64224203"
SOURCE_INVENTORY_SHA256 = "53c64616fa98ddd446533cbc7b8e90eb2866ce9b1b0b3243df4211d59f155ba2"
SOURCE_INVENTORY_FILES = 17_541
MANIFEST_HASHES = {
    "canonical_12m/MANIFEST.json": "fc7787854399348856ba13df5961c29af2ddc8655e162135cd44603b20a562c3",
    "canonical_gapday_prefix/MANIFEST.json": "9ffef229544bdc7ec78c54dda6545565e64ba6757970844458538eadc2b4515c",
    "canonical_postgap_20260213/MANIFEST.json": "bce71f9b39dee91d7ebe074da0407d672f1ead645ade5ccd788c45f96cee5bf7",
}
FIELDS = ("timestamp_ms", "open", "high", "low", "close", "volume")
MAX_JSON_BYTES, MAX_BODY_BYTES, MAX_GZIP_BYTES = 262_144, 2_097_152, 2_097_152
MAX_INFLATED_BYTES, MAX_OUTPUT_BYTES = 2_097_152, 2_097_152
PROOF_FIELDS = [
    "daily_receipt_file_sha256", "daily_receipt_self_sha256", "artifact_1m_sha256",
    "terminal_request_receipt_file_sha256", "terminal_http_body_sha256",
    "terminal_normalized_chunk_sha256", "terminal_normalized_row_sha256",
    "terminal_raw_row_sha256", "all_chunks_binding_sha256",
]
CLOCK_FIELDS = [
    "actual_request_requested_at_utc_ms", "actual_request_received_at_utc_ms",
    "actual_archive_known_at_utc_ms",
]


class AuditError(ValueError):
    """Source integrity failed; this never requests replacement observations."""


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def integer(value: Any, *, text_allowed: bool = False) -> int:
    if isinstance(value, bool):
        raise AuditError("BOOLEAN_TIMESTAMP_OR_COUNT")
    if isinstance(value, int):
        return value
    if text_allowed and isinstance(value, str) and re.fullmatch(r"[0-9]+", value):
        return int(value)
    raise AuditError("EXACT_INTEGER_REQUIRED_NO_FLOAT_TRUNCATION")


def utc_ms(value: Any) -> int:
    if not isinstance(value, str):
        raise AuditError("RETRIEVAL_UTC_REQUIRED")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AuditError("INVALID_RETRIEVAL_UTC") from exc
    if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
        raise AuditError("RETRIEVAL_UTC_REQUIRED")
    return int(parsed.timestamp() * 1000)


def utc_text(ts: int) -> str:
    return datetime.fromtimestamp(ts / 1000, timezone.utc).isoformat()


def _loads(raw: bytes) -> Any:
    try:
        return json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
    except (ValueError, UnicodeDecodeError) as exc:
        raise AuditError("INVALID_JSON") from exc


def _self_hash(value: Mapping[str, Any], field: str) -> None:
    if value.get(field) != sha(json_bytes({k: v for k, v in value.items() if k != field})):
        raise AuditError("SELF_HASH_MISMATCH:" + field)


def _metadata(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


class Reader:
    """Bounded reads plus an end-of-audit second digest/stat pass; no writes."""
    def __init__(self, root: Path, seconds: int = 480):
        self.root = root.resolve()
        self.deadline = time.monotonic() + seconds
        self.files: dict[str, tuple[tuple[int, ...], str, int]] = {}
        self.raw_timestamp_field_sets: set[tuple[str, ...]] = set()

    def check_time(self) -> None:
        if time.monotonic() > self.deadline:
            raise AuditError("AUDIT_TIME_LIMIT")

    def path(self, relative: str) -> Path:
        p = Path(relative)
        if p.is_absolute() or ".." in p.parts or not p.parts or p.parts[0] not in {x.split("/")[0] for x in MANIFEST_HASHES}:
            raise AuditError("PATH_OUTSIDE_THREE_CANONICAL_ROOTS")
        result = self.root / p
        for parent in (result, *result.parents):
            if parent == self.root:
                break
            if parent.is_symlink():
                raise AuditError("SYMLINK_SOURCE_FORBIDDEN")
        if not result.resolve().is_relative_to(self.root):
            raise AuditError("SOURCE_PATH_ESCAPE")
        return result

    def read(self, relative: str, limit: int) -> tuple[bytes, str]:
        self.check_time()
        p = self.path(relative)
        before = p.stat()
        if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
            raise AuditError("NON_REGULAR_OR_OVERSIZE_SOURCE:" + relative)
        parts, digest, size = [], hashlib.sha256(), 0
        with p.open("rb") as handle:
            if _metadata(os.fstat(handle.fileno())) != _metadata(before):
                raise AuditError("SOURCE_CHANGED_BEFORE_READ")
            while block := handle.read(65_536):
                size += len(block)
                if size > limit:
                    raise AuditError("SOURCE_READ_LIMIT")
                parts.append(block); digest.update(block); self.check_time()
            if _metadata(os.fstat(handle.fileno())) != _metadata(before):
                raise AuditError("SOURCE_CHANGED_DURING_READ")
        if _metadata(p.stat()) != _metadata(before) or size != before.st_size:
            raise AuditError("SOURCE_CHANGED_AFTER_READ")
        binding = (_metadata(before), digest.hexdigest(), limit)
        if relative in self.files and self.files[relative] != binding:
            raise AuditError("SOURCE_CHANGED_BETWEEN_READS")
        self.files[relative] = binding
        return b"".join(parts), digest.hexdigest()

    def json(self, relative: str, expected: str | None = None) -> tuple[dict[str, Any], str]:
        raw, digest = self.read(relative, MAX_JSON_BYTES)
        if expected is not None and digest != expected:
            raise AuditError("FILE_HASH_MISMATCH:" + relative)
        value = _loads(raw)
        if not isinstance(value, dict):
            raise AuditError("JSON_MAPPING_REQUIRED")
        return value, digest

    def finish(self) -> dict[str, Any]:
        before_digest, after_digest = hashlib.sha256(), hashlib.sha256()
        for relative, (metadata, expected, limit) in sorted(self.files.items()):
            before_digest.update(json_bytes([relative, list(metadata), expected]))
            raw, actual = self.read(relative, limit)
            del raw
            if actual != expected:
                raise AuditError("SOURCE_CHANGED_END_OF_AUDIT")
            after_digest.update(json_bytes([relative, list(self.files[relative][0]), actual]))
        if before_digest.hexdigest() != after_digest.hexdigest():
            raise AuditError("SOURCE_INVENTORY_CHANGED")
        return {
            "files_checked": len(self.files),
            "source_bytes_per_digest_pass": sum(v[0][2] for v in self.files.values()),
            "before_inventory_metadata_and_digest_sha256": before_digest.hexdigest(),
            "after_inventory_metadata_and_digest_sha256": after_digest.hexdigest(),
            "inode_size_mtime_ctime_and_second_digest_match": True,
        }


def normalize_row(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict) or any(k not in raw for k in FIELDS[1:]):
        raise AuditError("RAW_NAMED_OHLCV_MAPPING_REQUIRED")
    times = [integer(raw[k], text_allowed=True) for k in ("time", "openTime", "timestamp") if k in raw]
    if not times or len(set(times)) != 1 or times[0] < 0 or times[0] % MINUTE_MS:
        raise AuditError("RAW_TIMESTAMP_ALIAS_OR_MINUTE_GRID")
    numbers = {}
    for key in FIELDS[1:]:
        if raw[key] is None or isinstance(raw[key], bool):
            raise AuditError("INVALID_SOURCE_NUMBER:" + key)
        try:
            number = Decimal(str(raw[key]))
        except InvalidOperation as exc:
            raise AuditError("INVALID_SOURCE_NUMBER:" + key) from exc
        if not number.is_finite() or (number < 0 if key == "volume" else number <= 0):
            raise AuditError("NONFINITE_OR_NONPOSITIVE_SOURCE:" + key)
        numbers[key] = number
    if numbers["high"] < max(numbers["open"], numbers["low"], numbers["close"]) or numbers["low"] > min(numbers["open"], numbers["high"], numbers["close"]):
        raise AuditError("SOURCE_OHLC_GEOMETRY")
    return {"timestamp_ms": times[0], **{k: format(v, "f") for k, v in numbers.items()}}


def _response_rows(raw: bytes, start: int, end: int, allowed_missing: set[int]) -> tuple[list[dict[str, Any]], dict[int, str], set[tuple[str, ...]]]:
    value = _loads(raw)
    if not isinstance(value, dict) or str(value.get("code")) != "0" or not isinstance(value.get("data"), list) or not value["data"]:
        raise AuditError("HTTP_BODY_SOURCE_DATA_INVALID")
    indexed, raw_hashes, field_sets = {}, {}, set()
    for item in value["data"]:
        row = normalize_row(item); ts = row["timestamp_ms"]
        if not start <= ts < end or ts >= CUTOFF_MS:
            raise AuditError("SOURCE_ROW_OUTSIDE_REQUEST_OR_FIXED_CUTOFF")
        if ts in indexed:
            raise AuditError("RAW_DUPLICATE_TIMESTAMP")
        indexed[ts] = row; raw_hashes[ts] = sha(json_bytes(item))
        field_sets.add(tuple(k for k in ("time", "openTime", "timestamp", "closeTime") if k in item))
    expected = set(range(start, end, MINUTE_MS))
    if expected - indexed.keys() != allowed_missing or indexed.keys() - expected:
        raise AuditError("RAW_MISSING_MINUTES_NOT_EXACT_EXPECTED_SET")
    # Native HTTP rows may be reverse chronological. Normalized artifacts must
    # nevertheless equal the exact ascending minute grid; no CSV reordering.
    return [indexed[t] for t in sorted(indexed)], raw_hashes, field_sets


def _csv_rows(raw: bytes) -> list[dict[str, Any]]:
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as handle:
            inflated = handle.read(MAX_INFLATED_BYTES + 1)
        if len(inflated) > MAX_INFLATED_BYTES:
            raise AuditError("GZIP_INFLATION_LIMIT")
        reader = csv.DictReader(io.StringIO(inflated.decode(), newline=""))
        if tuple(reader.fieldnames or ()) != FIELDS:
            raise AuditError("CSV_EXACT_FIELD_SET_REQUIRED")
        rows = []
        for row in reader:
            if set(row) != set(FIELDS) or any(v is None for v in row.values()):
                raise AuditError("CSV_ROW_SHAPE")
            row["timestamp_ms"] = integer(row["timestamp_ms"], text_allowed=True)
            rows.append(row)
        return rows
    except (OSError, EOFError, UnicodeDecodeError) as exc:
        raise AuditError("INVALID_GZIP_CSV") from exc


def _request(reader: Reader, segment: str, symbol: str, start: int, end: int, receipt_sha: str, *, allowed_missing: set[int] | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    stem = f"{segment}/requests/{symbol}/{start}_{end}"
    receipt, receipt_digest = reader.json(stem + ".receipt.json", receipt_sha)
    expected_query = {"symbol": symbol, "interval": "1m", "timeZone": 0, "startTime": start, "endTime": end - 1, "limit": 1000}
    query = receipt.get("query")
    expected_body = f"requests/{symbol}/{start}_{end}.body"
    identity = {
        "schema": HISTORY_SCHEMA + ".http_response", "source": SOURCE,
        "symbol": symbol, "interval": "1m", "start_ms": start,
        "end_exclusive_ms": end, "http_status": 200, "body_path": expected_body,
        "source_timezone": "UTC", "volume_unit": "UNKNOWN",
    }
    if any(receipt.get(k) != v for k, v in identity.items()) or not isinstance(query, dict) or {k: v for k, v in query.items() if k != "timestamp"} != expected_query:
        raise AuditError("HTTP_RECEIPT_IDENTITY_OR_QUERY")
    url_parts = str(receipt.get("url") or "").split("?", 1)
    pairs = [part.split("=", 1) for part in url_parts[1].split("&")] if len(url_parts) == 2 else []
    if url_parts[0] != SOURCE or any(len(pair) != 2 for pair in pairs) or len({p[0] for p in pairs}) != len(pairs) or dict(pairs) != {k: str(v) for k, v in query.items()}:
        raise AuditError("HTTP_URL_QUERY_MISMATCH")
    requested, received = utc_ms(receipt.get("requested_at_utc")), utc_ms(receipt.get("received_at_utc"))
    if received < requested or received < end:
        raise AuditError("ARCHIVE_RETRIEVAL_CHRONOLOGY")
    if "timestamp" in query and not requested <= integer(query["timestamp"]) <= received:
        raise AuditError("REQUEST_CLOCK_TIMESTAMP_OUTSIDE_RETRIEVAL")
    body, body_digest = reader.read(segment + "/" + expected_body, MAX_BODY_BYTES)
    if body_digest != receipt.get("body_sha256") or integer(receipt.get("body_bytes")) != len(body):
        raise AuditError("HTTP_BODY_HASH_OR_SIZE")
    rows, raw_hashes, fields = _response_rows(body, start, end, allowed_missing or set())
    reader.raw_timestamp_field_sets.update(fields)
    return rows, {
        "request_receipt_sha256": receipt_digest, "body_sha256": body_digest,
        "requested_ms": requested, "received_ms": received, "raw_row_hashes": raw_hashes,
    }


def _windows(start: int, end: int) -> list[tuple[int, int]]:
    return [(t, min(t + 999 * MINUTE_MS, end)) for t in range(start, end, 999 * MINUTE_MS)]


def audit_daily(reader: Reader, segment: str, symbol: str, start: int, end: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if start % MINUTE_MS or end % MINUTE_MS or end <= start or end > CUTOFF_MS or (start // DAY_MS != (end - 1) // DAY_MS):
        raise AuditError("DAILY_WINDOW_INVALID_OR_FUTURE")
    relative = f"{segment}/daily_receipts/{symbol}/{start}_{end}.json"
    receipt, file_digest = reader.json(relative)
    _self_hash(receipt, "receipt_sha256")
    expected_rows = (end - start) // MINUTE_MS
    identity = {
        "schema": HISTORY_SCHEMA + ".daily", "symbol": symbol, "start_ms": start,
        "end_exclusive_ms": end, "start_utc": utc_text(start), "end_exclusive_utc": utc_text(end),
        "rows_1m": expected_rows, "expected_rows_1m": expected_rows, "gap_count": 0,
        "duplicate_count": 0, "volume_unit": "UNKNOWN", "synthetic_fill": False, "forward_fill": False,
    }
    if any(receipt.get(k) != v for k, v in identity.items()):
        raise AuditError("DAILY_RECEIPT_IDENTITY_OR_COVERAGE")
    for k in ("start_ms", "end_exclusive_ms", "rows_1m", "expected_rows_1m", "gap_count", "duplicate_count"):
        integer(receipt.get(k))
    artifacts, sources = receipt.get("artifacts"), receipt.get("source_receipts")
    windows = _windows(start, end)
    if not isinstance(artifacts, list) or len(artifacts) != 4 or [a.get("timeframe_minutes") for a in artifacts if isinstance(a, dict)] != [1, 15, 30, 60] or not isinstance(sources, list) or len(sources) != len(windows):
        raise AuditError("DAILY_ARTIFACT_OR_CHUNK_SET")
    all_rows, bindings = [], []
    for info, (a, b) in zip(sources, windows):
        if not isinstance(info, dict):
            raise AuditError("DAILY_SOURCE_MAPPING")
        normalized_path = f"normalized_chunks/{symbol}/{a}_{b}.csv.gz"
        if info.get("path") != f"requests/{symbol}/{a}_{b}.receipt.json" or info.get("normalized_path") != normalized_path:
            raise AuditError("DAILY_SOURCE_PATH")
        rows, binding = _request(reader, segment, symbol, a, b, info.get("sha256"))
        raw_csv, normalized_digest = reader.read(segment + "/" + normalized_path, MAX_GZIP_BYTES)
        if normalized_digest != info.get("normalized_sha256") or _csv_rows(raw_csv) != rows:
            raise AuditError("NORMALIZED_CHUNK_HASH_OR_RAW_ROW_BINDING")
        binding.update(start_ms=a, end_ms=b, normalized_sha256=normalized_digest)
        all_rows.extend(rows); bindings.append(binding)
    if [r["timestamp_ms"] for r in all_rows] != list(range(start, end, MINUTE_MS)):
        raise AuditError("DAILY_MINUTE_GRID_DUPLICATE_OR_REORDERED")
    artifact = artifacts[0]
    expected_artifact = f"1m/{symbol}/{start}_{end}.csv.gz"
    if artifact.get("path") != expected_artifact or artifact.get("row_count") != expected_rows or artifact.get("incomplete_boundary_buckets_excluded") != []:
        raise AuditError("DAILY_1M_ARTIFACT_IDENTITY")
    actual, artifact_digest = reader.read(segment + "/" + expected_artifact, MAX_GZIP_BYTES)
    if artifact_digest != artifact.get("sha256") or _csv_rows(actual) != all_rows:
        raise AuditError("DAILY_1M_ARTIFACT_HASH_OR_SOURCE_BINDING")
    terminal = all_rows[-1]; binding = bindings[-1]
    chain = [{k: v for k, v in item.items() if k != "raw_row_hashes"} for item in bindings]
    proof = [file_digest, receipt["receipt_sha256"], artifact_digest,
             binding["request_receipt_sha256"], binding["body_sha256"], binding["normalized_sha256"],
             sha(json_bytes(terminal)), binding["raw_row_hashes"][terminal["timestamp_ms"]], sha(json_bytes(chain))]
    return all_rows, {"proof": proof, "clock": [binding["requested_ms"], binding["received_ms"], max(x["received_ms"] for x in bindings)]}


def audit_prefix(reader: Reader, manifest: Mapping[str, Any], symbol: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    infos = [x for x in manifest.get("symbols", []) if isinstance(x, dict) and x.get("symbol") == symbol]
    if len(infos) != 1 or infos[0].get("rows_1m") != 1232:
        raise AuditError("PREFIX_SYMBOL_OR_ROW_COUNT")
    info = infos[0]; sources = info.get("sources"); all_rows, chain = [], []
    windows = _windows(GAP_DAY_MS, GAP_DAY_MS + DAY_MS)
    if not isinstance(sources, list) or len(sources) != 2:
        raise AuditError("PREFIX_SOURCE_CHUNK_SET")
    for source, (a, b) in zip(sources, windows):
        expected_ref = f"{RUNTIME_ROOT}/canonical_12m/requests/{symbol}/{a}_{b}.receipt.json"
        if not isinstance(source, dict) or source.get("receipt") != expected_ref:
            raise AuditError("PREFIX_NATIVE_RECEIPT_PATH")
        missing = set(range(GAP_START_MS, GAP_END_MS, MINUTE_MS)) & set(range(a, b, MINUTE_MS))
        rows, binding = _request(reader, "canonical_12m", symbol, a, b, source.get("receipt_sha256"), allowed_missing=missing)
        if binding["body_sha256"] != source.get("body_sha256"):
            raise AuditError("PREFIX_BODY_MANIFEST_HASH")
        if not missing:
            normalized, normalized_digest = reader.read(f"canonical_12m/normalized_chunks/{symbol}/{a}_{b}.csv.gz", MAX_GZIP_BYTES)
            if _csv_rows(normalized) != rows:
                raise AuditError("PREFIX_FIRST_NORMALIZED_CHUNK_RAW_BINDING")
            binding["normalized_sha256"] = normalized_digest
        all_rows.extend(rows); chain.append({k: v for k, v in binding.items() if k != "raw_row_hashes"})
    if [r["timestamp_ms"] for r in all_rows] != [t for t in range(GAP_DAY_MS, GAP_DAY_MS + DAY_MS, MINUTE_MS) if not GAP_START_MS <= t < GAP_END_MS]:
        raise AuditError("PREFIX_RAW_GAP_DUPLICATE_OR_ORDER")
    prefix_rows = [r for r in all_rows if r["timestamp_ms"] < GAP_START_MS]
    artifacts = info.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) != 4 or not isinstance(artifacts[0], dict):
        raise AuditError("PREFIX_ARTIFACT_SET")
    artifact = artifacts[0]
    relative = f"canonical_gapday_prefix/{symbol}/1m.csv.gz"
    if artifact.get("file") != f"{RUNTIME_ROOT}/{relative}" or artifact.get("rows") != 1232 or artifact.get("boundary_buckets_excluded") != []:
        raise AuditError("PREFIX_NATIVE_ARTIFACT_IDENTITY")
    raw, artifact_digest = reader.read(relative, MAX_GZIP_BYTES)
    if artifact_digest != artifact.get("sha256") or _csv_rows(raw) != prefix_rows:
        raise AuditError("PREFIX_1M_RAW_BINDING_OR_HASH")
    return prefix_rows, [r for r in all_rows if r["timestamp_ms"] >= GAP_END_MS], {
        "prefix_1m_sha256": artifact_digest, "prefix_raw_request_chain_sha256": sha(json_bytes(chain)),
        "prefix_archive_known_at_utc_ms": max(x["received_ms"] for x in chain),
        "request_receipt_file_sha256": [x["request_receipt_sha256"] for x in chain],
        "http_body_sha256": [x["body_sha256"] for x in chain],
        "rows_1m": 1232, "missing_minutes_preserved": list(range(GAP_START_MS, GAP_END_MS, MINUTE_MS)),
    }


def project_calendar(days: list[dict[str, Any]]) -> dict[str, Any]:
    """Fixed cutoff/date coverage, never arbitrary as-of or stale 361 closes."""
    expected = list(range(START_MS, CUTOFF_MS, DAY_MS))
    if len(days) != 365 or [integer(x.get("day_start_ms")) for x in days] != expected:
        raise AuditError("FIXED_365_CALENDAR_OR_FINAL_CUTOFF_ANCHOR_MISSING")
    for day in days:
        start = day["day_start_ms"]
        if integer(day.get("terminal_ts_ms")) != start + DAY_MS - MINUTE_MS or integer(day.get("model_available_ts_ms")) != start + DAY_MS:
            raise AuditError("MISSING_23_59_TERMINAL_OR_DAY_CLOSE_MODEL")
        count = integer(day.get("count_1m"))
        if count != (1436 if start == GAP_DAY_MS else 1440) or integer(day.get("missing_1m")) != 1440 - count:
            raise AuditError("UNEXPECTED_INTRADAY_GAPS_OR_SYNTHETIC_FILL")
        try:
            close = Decimal(str(day.get("close")))
        except InvalidOperation as exc:
            raise AuditError("INVALID_DAILY_CLOSE") from exc
        if not close.is_finite() or close <= 0 or isinstance(day.get("close"), bool):
            raise AuditError("INVALID_DAILY_CLOSE")
    suffix = days[-REQUIRED_SUFFIX_DAYS:]
    if suffix[0]["day_start_ms"] != CUTOFF_MS - REQUIRED_SUFFIX_DAYS * DAY_MS or suffix[-1]["model_available_ts_ms"] != CUTOFF_MS:
        raise AuditError("DATED_361_SUFFIX_MISSING_CUTOFF_ANCHOR")
    return {
        "verified_reported_terminal_rows": 365, "suffix_count": len(suffix),
        "suffix_start_utc": utc_text(suffix[0]["day_start_ms"]),
        "suffix_end_exclusive_utc": utc_text(CUTOFF_MS),
        "suffix_calendar_sha256": sha(json_bytes(suffix)),
        "source_minutes": sum(x["count_1m"] for x in days), "calendar": days,
    }


def _manifest_identity(manifest: Mapping[str, Any], segment: str) -> None:
    if segment == "canonical_gapday_prefix":
        required = {"schema": "zel.economic7.partial_source_fragment.v1", "start_ms": GAP_DAY_MS,
                    "end_exclusive_ms": GAP_START_MS, "rows_1m": None, "volume_unit": "UNKNOWN",
                    "synthetic_fill": False, "source_code_sha256": COLLECTOR_CODE_SHA256,
                    "state": "EXACT_CONTIGUOUS_PREFIX_FROM_PRESERVED_RESPONSES"}
        required.pop("rows_1m")
        symbols = [x.get("symbol") for x in manifest.get("symbols", []) if isinstance(x, dict)]
    else:
        _self_hash(manifest, "manifest_sha256")
        required = {"schema": HISTORY_SCHEMA, "source": SOURCE, "source_interval": "1m",
                    "source_timezone": "UTC", "volume_unit": "UNKNOWN", "synthetic_fill": False,
                    "forward_fill": False, "code_sha256": COLLECTOR_CODE_SHA256,
                    "start_ms": START_MS if segment == "canonical_12m" else GAP_END_MS,
                    "end_exclusive_ms": CUTOFF_MS, "execution_authority": "NONE", "order_authority": "BLOCKED"}
        symbols = manifest.get("symbols")
    if any(manifest.get(k) != v for k, v in required.items()) or not isinstance(symbols, list) or len(symbols) != 6 or set(symbols) != set(SYMBOLS):
        raise AuditError("PINNED_MANIFEST_IDENTITY:" + segment)


def _inventory_names(reader: Reader) -> set[str]:
    names = set(MANIFEST_HASHES)
    for segment in ("canonical_12m", "canonical_postgap_20260213"):
        for sub, pattern in (("daily_receipts", "*.json"), ("requests", "*.receipt.json"),
                             ("requests", "*.body"), ("normalized_chunks", "*.csv.gz"), ("1m", "*.csv.gz")):
            for path in (reader.root / segment / sub).rglob(pattern):
                names.add(str(path.relative_to(reader.root)))
                if len(names) > SOURCE_INVENTORY_FILES:
                    raise AuditError("ARCHIVE_INVENTORY_EXTRA_FILES")
                reader.check_time()
    names.update(str(p.relative_to(reader.root)) for p in (reader.root / "canonical_gapday_prefix").glob("*/1m.csv.gz"))
    return names


def verify_inventory(reader: Reader) -> dict[str, Any]:
    names = _inventory_names(reader)
    read_names = set(reader.files) - {"canonical_12m/FREEZE.json", "canonical_postgap_20260213/FREEZE.json"}
    if names != read_names or len(names) != SOURCE_INVENTORY_FILES:
        raise AuditError("EXACT_17541_FILE_INVENTORY_SET_MISMATCH")
    actual = sha(json_bytes({name: reader.files[name][1] for name in names}))
    if actual != SOURCE_INVENTORY_SHA256:
        raise AuditError("PINNED_FULL_SOURCE_INVENTORY_HASH_MISMATCH")
    return {"files": len(names), "actual_sha256": actual, "expected_sha256": SOURCE_INVENTORY_SHA256}


def audit(runtime_root: Path) -> dict[str, Any]:
    reader = Reader(runtime_root)
    manifests, manifest_proofs = {}, {}
    for relative, expected in MANIFEST_HASHES.items():
        value, digest = reader.json(relative, expected)
        segment = relative.split("/")[0]; _manifest_identity(value, segment)
        manifests[segment] = value
        manifest_proofs[segment] = {"file_sha256": digest, "self_sha256": value.get("manifest_sha256"), "collector_code_sha256": COLLECTOR_CODE_SHA256}
        if segment != "canonical_gapday_prefix":
            freeze, freeze_hash = reader.json(segment + "/FREEZE.json")
            if any(value.get(k) != v for k, v in freeze.items()) or freeze.get("code_sha256") != COLLECTOR_CODE_SHA256:
                raise AuditError("FREEZE_MANIFEST_BINDING")
            manifest_proofs[segment]["freeze_file_sha256"] = freeze_hash
    summaries = {}
    for symbol in SYMBOLS:
        days = []
        for start in range(START_MS, GAP_DAY_MS, DAY_MS):
            rows, proof = audit_daily(reader, "canonical_12m", symbol, start, start + DAY_MS)
            days.append(_day(start, rows, proof))
        prefix, original_suffix, prefix_proof = audit_prefix(reader, manifests["canonical_gapday_prefix"], symbol)
        for start in range(GAP_DAY_MS, CUTOFF_MS, DAY_MS):
            part_start = GAP_END_MS if start == GAP_DAY_MS else start
            rows, proof = audit_daily(reader, "canonical_postgap_20260213", symbol, part_start, start + DAY_MS)
            if start == GAP_DAY_MS:
                if rows != original_suffix:
                    raise AuditError("GAPDAY_OVERLAPPING_RAW_SOURCES_DISAGREE")
                rows = prefix + rows
                proof["clock"][2] = max(proof["clock"][2], prefix_proof["prefix_archive_known_at_utc_ms"])
                proof["proof"][-1] = sha(json_bytes([proof["proof"][-1], prefix_proof, manifest_proofs["canonical_gapday_prefix"]]))
            days.append(_day(start, rows, proof))
        summaries[symbol] = {**project_calendar(days), "gapday_prefix_proof": prefix_proof}
    inventory = verify_inventory(reader)
    stability = reader.finish()
    if _inventory_names(reader) != set(reader.files) - {"canonical_12m/FREEZE.json", "canonical_postgap_20260213/FREEZE.json"}:
        raise AuditError("ARCHIVE_FILE_SET_CHANGED_END_OF_AUDIT")
    result = {
        "schema": SCHEMA, "state": "REPORTED_TERMINAL_CLOSE_SOURCE_CHAIN_VERIFIED",
        "classification": "RETROSPECTIVE_DEVELOPMENT_CLOSE_ONLY_INPUT_AUDIT",
        "source": SOURCE, "native_market": "BINGX_USDT_M_PERPETUAL_ENDPOINT",
        "start_utc": utc_text(START_MS), "cutoff_exclusive_utc": utc_text(CUTOFF_MS),
        "cutoff_exclusive_ms": CUTOFF_MS, "per_day_proof_fields": PROOF_FIELDS,
        "per_day_clock_fields": CLOCK_FIELDS, "pinned_manifests": manifest_proofs,
        "source_read_stability": stability, "symbols": summaries,
        "pinned_full_source_inventory": inventory,
        "reported_raw_timestamp_field_sets": sorted([list(x) for x in reader.raw_timestamp_field_sets]),
        "source_timestamp_semantics": "UNVERIFIED_REPORTED_GRID_NO_OPEN_CLOSE_AUTHORITY",
        "exact_utc_final_daily_close_semantic_certification": False,
        "availability_basis": "BAR_CLOSE_MODEL_NOT_OBSERVED_HISTORICAL_DELIVERY",
        "historical_delivery_latency": "UNOBSERVED", "historical_realtime_fidelity": False,
        "actual_archive_retrieval_clock_separate_from_historical_model": True,
        "synthetic_fill": False, "forward_fill": False, "missing_1m_per_symbol": 4,
        "full_daily_open_high_low_volume_authority": "UNAVAILABLE_CLOSE_ONLY_GAP_PRESERVED",
        "volume_units": "UNKNOWN", "chronology_economic_eligible": False,
        "strategy_ready": False, "new_http_requests": 0, "network_calls": 0,
        "remote_writes": 0, "new_economic_executions": 0, "pnl_computed": False,
        "execution_authority": "NONE", "order_authority": "BLOCKED", "promotion_authority": False,
    }
    result["receipt_sha256"] = sha(json_bytes(result))
    if len(json_bytes(result)) > MAX_OUTPUT_BYTES:
        raise AuditError("OUTPUT_SIZE_LIMIT")
    return result


def _day(start: int, rows: list[dict[str, Any]], proof: Mapping[str, Any]) -> dict[str, Any]:
    terminal = start + DAY_MS - MINUTE_MS
    expected = [t for t in range(start, start + DAY_MS, MINUTE_MS) if not GAP_START_MS <= t < GAP_END_MS]
    if [row["timestamp_ms"] for row in rows] != expected or not rows or rows[-1]["timestamp_ms"] != terminal:
        raise AuditError("DAY_GAP_OR_MISSING_TERMINAL_CLOSE")
    return {"day_start_ms": start, "terminal_ts_ms": terminal, "model_available_ts_ms": start + DAY_MS,
            "close": rows[-1]["close"], "count_1m": len(rows), "missing_1m": 1440 - len(rows), **proof}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", type=Path, default=Path(RUNTIME_ROOT))
    args = parser.parse_args(argv)
    try:
        result = audit(args.runtime_root)
    except (AuditError, OSError, KeyError, TypeError, OverflowError) as exc:
        result = {"schema": SCHEMA, "state": "BLOCKED_CANONICAL_CLOSE_SOURCE_AUDIT",
                  "reason": f"{type(exc).__name__}:{exc}", "strategy_ready": False,
                  "chronology_economic_eligible": False, "network_calls": 0, "remote_writes": 0,
                  "new_economic_executions": 0, "pnl_computed": False, "execution_authority": "NONE"}
        sys.stdout.buffer.write(json_bytes(result)); return 2
    sys.stdout.buffer.write(json_bytes(result)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
