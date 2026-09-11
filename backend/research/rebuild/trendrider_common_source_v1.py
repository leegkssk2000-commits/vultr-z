"""One authorized historical BingX acquisition; no policy or economic execution.

The attempt marker is exclusive and permanent, including after failure. Raw
response bytes and metadata are written before any JSON decoding. This module
does not resume, retry, redirect, read prospective files, or fetch costs.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from hashlib import sha256
import json
import math
from pathlib import Path
import time
from typing import Any, Callable, Mapping
import urllib.error
import urllib.parse
import urllib.request

ENDPOINT = "https://open-api.bingx.com/openApi/swap/v3/quote/klines"
SYMBOLS = ("BTC-USDT", "ETH-USDT")
HOUR_MS = 3_600_000
CUTOFF_MS = 1_788_048_000_000
BAR_COUNT = 1000
FIRST_OPEN_MS = CUTOFF_MS - BAR_COUNT * HOUR_MS
MAX_PAGES = 10
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
SOURCE_SCHEMA = "trendrider.common.source.freeze.v1"


class SourceIntegrityError(RuntimeError):
    """The single acquisition is unusable; no automatic retry is permitted."""


@dataclass(frozen=True)
class Response:
    status: int
    headers: Mapping[str, str]
    body: bytes


def digest_bytes(raw: bytes) -> str:
    return sha256(raw).hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def write_once(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as target:
        target.write(raw)
        target.flush()


def _sealed(value: dict[str, Any]) -> dict[str, Any]:
    return {**value, "receipt_sha256": digest_bytes(canonical_bytes(value))}


def _clock_ms() -> int:
    return time.time_ns() // 1_000_000


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # urllib surfaces the original 3xx as HTTPError. The transport retains
        # that response's bytes and headers without following its Location.
        return None


def http_transport(endpoint: str, params: Mapping[str, Any]) -> Response:
    """Exactly one GET. HTTP errors retain their response bodies; no retries."""
    if endpoint != ENDPOINT:
        raise SourceIntegrityError("SOURCE_ENDPOINT_NOT_ALLOWED")
    url = endpoint + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, method="GET", headers={"Accept": "application/json"})
    opener = urllib.request.build_opener(_NoRedirect())
    try:
        response = opener.open(request, timeout=30)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        return Response(int(response.status), dict(response.headers.items()),
                        response.read(MAX_RESPONSE_BYTES + 1))


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SourceIntegrityError("SOURCE_JSON_DUPLICATE_KEY")
        result[key] = value
    return result


def _decode_json(raw: bytes) -> Any:
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                          parse_constant=lambda value: (_ for _ in ()).throw(
                              SourceIntegrityError("SOURCE_NONFINITE_JSON:" + value)))
    except (ValueError, UnicodeError) as exc:
        raise SourceIntegrityError("SOURCE_JSON_INVALID") from exc


def validate_contract(contract: Any) -> dict[str, Any]:
    if not isinstance(contract, dict) or not isinstance(contract.get("source"), dict):
        raise SourceIntegrityError("SOURCE_CONTRACT_OBJECT_REQUIRED")
    expected = {"endpoint": ENDPOINT, "symbols": list(SYMBOLS), "interval": "1h",
                "cutoff_ms": CUTOFF_MS, "bars_per_symbol": BAR_COUNT,
                "page_limit": BAR_COUNT, "max_pages_per_symbol": MAX_PAGES}
    source = contract["source"]
    for key, value in expected.items():
        if source.get(key) != value or type(source.get(key)) is not type(value):
            raise SourceIntegrityError("SOURCE_CONTRACT_MISMATCH:" + key)
    return expected


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise SourceIntegrityError("SOURCE_NUMBER_INVALID:" + field)
    try:
        result = float(value)
    except (ValueError, OverflowError) as exc:
        raise SourceIntegrityError("SOURCE_NUMBER_INVALID:" + field) from exc
    if not math.isfinite(result):
        raise SourceIntegrityError("SOURCE_NONFINITE:" + field)
    return result


def _timestamp(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise SourceIntegrityError("SOURCE_TIMESTAMP_TYPE")
    try:
        result = int(value)
    except ValueError as exc:
        raise SourceIntegrityError("SOURCE_TIMESTAMP_INVALID") from exc
    if isinstance(value, str) and str(result) != value:
        raise SourceIntegrityError("SOURCE_TIMESTAMP_NONCANONICAL")
    if result % HOUR_MS or not FIRST_OPEN_MS <= result < CUTOFF_MS:
        raise SourceIntegrityError("SOURCE_TIMESTAMP_GRID_OR_WINDOW")
    return result


def _field(row: Mapping[str, Any], names: tuple[str, ...]) -> Any:
    present = [row[key] for key in names if key in row]
    if not present:
        raise SourceIntegrityError("SOURCE_FIELD_MISSING:" + names[0])
    if any(str(value) != str(present[0]) for value in present[1:]):
        raise SourceIntegrityError("SOURCE_ALIAS_CONFLICT:" + names[0])
    return present[0]


def decode_page(raw: bytes, symbol: str, expected_latest_ms: int,
                remaining: int) -> list[dict[str, Any]]:
    if symbol not in SYMBOLS or len(raw) > MAX_RESPONSE_BYTES:
        raise SourceIntegrityError("SOURCE_SYMBOL_OR_RESPONSE_LIMIT")
    payload = _decode_json(raw)
    if (not isinstance(payload, dict) or type(payload.get("code")) is not int
            or payload["code"] != 0 or not isinstance(payload.get("data"), list)):
        raise SourceIntegrityError("SOURCE_API_PAYLOAD_INVALID")
    source_rows = payload["data"]
    if not source_rows or len(source_rows) > remaining:
        raise SourceIntegrityError("SOURCE_PAGE_COUNT")
    rows = []
    seen = set()
    for item in source_rows:
        if isinstance(item, dict):
            if "symbol" in item and item["symbol"] != symbol:
                raise SourceIntegrityError("SOURCE_SYMBOL_MISMATCH")
            stamp = _timestamp(_field(item, ("time", "openTime", "timestamp")))
            values = {key: _number(_field(item, (key,)), key)
                      for key in ("open", "high", "low", "close")}
            values["volume"] = _number(_field(item, ("volume", "vol", "baseVolume")), "volume")
        elif isinstance(item, list) and len(item) >= 6:
            stamp = _timestamp(item[0])
            values = {key: _number(item[index], key) for index, key in
                      enumerate(("open", "high", "low", "close", "volume"), start=1)}
        else:
            raise SourceIntegrityError("SOURCE_ROW_SHAPE")
        if stamp in seen:
            raise SourceIntegrityError("SOURCE_DUPLICATE_TIMESTAMP")
        seen.add(stamp)
        if (min(values[key] for key in ("open", "high", "low", "close")) <= 0
                or values["volume"] < 0
                or values["low"] > min(values["open"], values["close"])
                or values["high"] < max(values["open"], values["close"])
                or values["low"] > values["high"]):
            raise SourceIntegrityError("SOURCE_OHLC_OR_VOLUME_INVALID")
        rows.append({"symbol": symbol, "ts_ms": stamp, **values})
    rows.sort(key=lambda row: row["ts_ms"])
    if rows[-1]["ts_ms"] != expected_latest_ms:
        raise SourceIntegrityError("SOURCE_PAGE_END_MISMATCH")
    if any(b["ts_ms"] - a["ts_ms"] != HOUR_MS for a, b in zip(rows, rows[1:])):
        raise SourceIntegrityError("SOURCE_PAGE_GAP")
    return rows


def collect(contract_path: str | Path, output_dir: str | Path, *,
            transport: Callable[[str, Mapping[str, Any]], Response] | None = None) -> dict[str, Any]:
    """Acquire once into a new empty directory. Failure raises and leaves evidence.

    Successful normalized files are JSON lists at sources/{symbol}.json. The
    result is DATA_FREEZE.json, containing exact byte hashes, clocks, and every
    raw request. Failure writes FAILURE_MANIFEST.json with the same raw index.
    An existing attempt or any existing output is never resumed or overwritten.
    """
    contract_path, output = Path(contract_path), Path(output_dir)
    contract_raw = contract_path.read_bytes()
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise SourceIntegrityError("SOURCE_OUTPUT_NOT_EMPTY_NO_RESUME")
    marker = _sealed({"schema": "trendrider.common.source.attempt.v1", "started_at_ms": _clock_ms(),
                      "contract_sha256": digest_bytes(contract_raw), "attempt_ordinal": 1,
                      "retry_authorized": False})
    try:
        write_once(output / "ATTEMPT_STARTED.json", canonical_bytes(marker))
    except FileExistsError as exc:
        raise SourceIntegrityError("SOURCE_ATTEMPT_ALREADY_CONSUMED") from exc
    requests: list[dict[str, Any]] = []
    normalized: dict[str, Any] = {}
    active_request = None
    try:
        write_once(output / "SOURCE_CONTRACT.json", contract_raw)
        source = validate_contract(_decode_json(contract_raw))
        transport_fn = transport or http_transport
        for symbol in SYMBOLS:
            accumulated = []
            seen = set()
            end_time = CUTOFF_MS - 1
            for page_index in range(MAX_PAGES):
                remaining = BAR_COUNT - len(accumulated)
                params = {"symbol": symbol, "interval": "1h", "limit": min(BAR_COUNT, remaining),
                          "endTime": end_time}
                stem = f"raw/{symbol}_{page_index:02d}"
                active_request = {"endpoint": ENDPOINT, "params": params, "page_index": page_index,
                                  "requested_at_ms": _clock_ms(), "transport_retry_count": 0}
                write_once(output / (stem + ".request.json"), canonical_bytes(active_request))
                response = transport_fn(ENDPOINT, params)
                if not isinstance(response, Response) or not isinstance(response.body, bytes):
                    raise SourceIntegrityError("SOURCE_TRANSPORT_RESPONSE_TYPE")
                raw_path = stem + ".bin"
                write_once(output / raw_path, response.body)
                metadata = _sealed({**active_request, "received_at_ms": _clock_ms(),
                                    "http_status": response.status,
                                    "response_headers": dict(response.headers),
                                    "raw_path": raw_path, "raw_sha256": digest_bytes(response.body),
                                    "raw_bytes": len(response.body), "saved_before_decode": True})
                write_once(output / (stem + ".response.json"), canonical_bytes(metadata))
                requests.append(metadata)
                if response.status != 200:
                    raise SourceIntegrityError("SOURCE_HTTP_STATUS:" + str(response.status))
                page = decode_page(response.body, symbol, (end_time // HOUR_MS) * HOUR_MS, remaining)
                if any(row["ts_ms"] in seen for row in page):
                    raise SourceIntegrityError("SOURCE_GLOBAL_DUPLICATE")
                seen.update(row["ts_ms"] for row in page)
                accumulated.extend(page)
                if len(accumulated) == BAR_COUNT:
                    break
                next_end = page[0]["ts_ms"] - 1
                if next_end >= end_time:
                    raise SourceIntegrityError("SOURCE_PAGINATION_STALLED")
                end_time = next_end
            else:
                raise SourceIntegrityError("SOURCE_PAGE_BUDGET_EXHAUSTED")
            accumulated.sort(key=lambda row: row["ts_ms"])
            expected_clock = list(range(FIRST_OPEN_MS, CUTOFF_MS, HOUR_MS))
            if [row["ts_ms"] for row in accumulated] != expected_clock:
                raise SourceIntegrityError("SOURCE_EXACT_CLOCK_MISMATCH")
            normalized_path = "sources/" + symbol + ".json"
            normalized_raw = canonical_bytes(accumulated)
            write_once(output / normalized_path, normalized_raw)
            normalized[symbol] = {"path": normalized_path, "sha256": digest_bytes(normalized_raw),
                                  "bytes": len(normalized_raw), "bars": BAR_COUNT,
                                  "first_open_ms": FIRST_OPEN_MS, "last_open_ms": CUTOFF_MS - HOUR_MS,
                                  "last_close_ms": CUTOFF_MS, "gap": 0, "duplicate": 0,
                                  "malformed_rows_dropped": 0}
        if contract_path.read_bytes() != contract_raw:
            raise SourceIntegrityError("SOURCE_CONTRACT_CHANGED_DURING_FETCH")
        manifest = _sealed({"schema": SOURCE_SCHEMA, "state": "FROZEN_COMMON_HISTORICAL_DEV",
                            "contract_sha256": digest_bytes(contract_raw), "source": source,
                            "normalized": normalized, "requests": requests,
                            "dataset_sha256": digest_bytes(canonical_bytes(normalized)),
                            "completed_at_ms": _clock_ms(), "dataset_fetch_attempts": 1,
                            "http_get_count": len(requests), "transport_retries": 0,
                            "production_grade": False, "formal_credit": 0,
                            "prospective_records_decoded": 0, "economic_runs": 0,
                            "volume_semantics": "SOURCE_REPORTED_VOLUME_NO_UNIT_CLAIM"})
        write_once(output / "DATA_FREEZE.json", canonical_bytes(manifest))
        return manifest
    except Exception as exc:
        failure = _sealed({"schema": SOURCE_SCHEMA, "state": "BLOCKED_DATA",
                           "contract_sha256": digest_bytes(contract_raw),
                           "error_type": type(exc).__name__, "reason": str(exc),
                           "requests": requests, "last_attempted_request": active_request,
                           "normalized": normalized, "dataset_fetch_attempts": 1,
                           "http_response_count": len(requests), "transport_retries": 0,
                           "retry_authorized": False, "production_grade": False,
                           "formal_credit": 0, "economic_runs": 0, "failed_at_ms": _clock_ms()})
        write_once(output / "FAILURE_MANIFEST.json", canonical_bytes(failure))
        if isinstance(exc, SourceIntegrityError):
            raise
        raise SourceIntegrityError("SOURCE_ACQUISITION_FAILED:" + type(exc).__name__) from exc


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(json.dumps(collect(args.contract, args.output), sort_keys=True))
