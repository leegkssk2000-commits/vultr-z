"""One source-only successor acquisition with bounded timestamp guard handling.

The v1 collector and every strategy/economic rule remain immutable. This version
requires a separately sealed native-open semantic receipt before any GET. It
changes only source window membership and backward pagination: native timestamps
are never shifted, boundary guards never enter normalized prices, and raw bytes
are persisted before decoding. No retry, resume, redirect, or economic execution.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable, Mapping

from backend.research.rebuild import trendrider_common_source_v1 as v1

ENDPOINT = v1.ENDPOINT
SYMBOLS = v1.SYMBOLS
HOUR_MS = v1.HOUR_MS
CUTOFF_MS = v1.CUTOFF_MS
BAR_COUNT = v1.BAR_COUNT
FIRST_OPEN_MS = v1.FIRST_OPEN_MS
MAX_PAGES = 3
MAX_RESPONSE_BYTES = v1.MAX_RESPONSE_BYTES
SOURCE_SCHEMA = "trendrider.common.source.freeze.v2"
SEMANTIC_SCHEMA = "trendrider.common.timestamp.semantic.v1"
SEMANTIC_RULES = {
    "canonical_transform": "IDENTITY_NATIVE_OPEN_MS",
    "canonical_bar_timestamp": "OPEN_TIME_MS",
    "endpoint": ENDPOINT,
    "interval_ms": HOUR_MS,
    "request_end_time_rule": "LOGICAL_UPPER_MINUS_ONE_MS",
    "pagination_rule": "NEXT_LOGICAL_UPPER_MIN_ADMITTED_OPEN",
}

SourceIntegrityError = v1.SourceIntegrityError
Response = v1.Response
canonical_bytes = v1.canonical_bytes
digest_bytes = v1.digest_bytes
write_once = v1.write_once
http_transport = v1.http_transport


def validate_contract(contract: Any) -> dict[str, Any]:
    if not isinstance(contract, dict) or not isinstance(contract.get("source"), dict):
        raise SourceIntegrityError("SOURCE_CONTRACT_OBJECT_REQUIRED")
    expected = {
        "endpoint": ENDPOINT, "symbols": list(SYMBOLS), "interval": "1h",
        "cutoff_ms": CUTOFF_MS, "first_open_ms": FIRST_OPEN_MS,
        "bars_per_symbol": BAR_COUNT, "page_limit": BAR_COUNT,
        "max_pages_per_symbol": MAX_PAGES,
    }
    source = contract["source"]
    for key, value in expected.items():
        if source.get(key) != value or type(source.get(key)) is not type(value):
            raise SourceIntegrityError("SOURCE_CONTRACT_MISMATCH:" + key)
    semantic_sha = source.get("timestamp_semantic_receipt_sha256")
    if (not isinstance(semantic_sha, str) or len(semantic_sha) != 64
            or any(char not in "0123456789abcdef" for char in semantic_sha)):
        raise SourceIntegrityError("SOURCE_SEMANTIC_SHA_REQUIRED")
    return {**expected, "timestamp_semantic_receipt_sha256": semantic_sha}


def validate_semantic_receipt(raw: bytes, expected_sha256: str) -> dict[str, Any]:
    """Only the exact pre-frozen, internally sealed identity receipt authorizes GET."""
    if digest_bytes(raw) != expected_sha256:
        raise SourceIntegrityError("BLOCKED_TIMESTAMP_SEMANTIC:RAW_SHA_MISMATCH")
    receipt = v1._decode_json(raw)
    if (not isinstance(receipt, dict) or receipt.get("schema") != SEMANTIC_SCHEMA
            or receipt.get("state") != "PASS"):
        raise SourceIntegrityError("BLOCKED_TIMESTAMP_SEMANTIC:PASS_RECEIPT_REQUIRED")
    if (receipt.get("native_timestamp_meaning") != "OPEN_TIME_MS"
            or receipt.get("acquisition_authorized") is not True):
        raise SourceIntegrityError("BLOCKED_TIMESTAMP_SEMANTIC:EXPLICIT_NATIVE_OPEN_AUTHORIZATION_REQUIRED")
    unsigned = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    if receipt.get("receipt_sha256") != digest_bytes(canonical_bytes(unsigned)):
        raise SourceIntegrityError("BLOCKED_TIMESTAMP_SEMANTIC:INTERNAL_SHA_MISMATCH")
    for key, value in SEMANTIC_RULES.items():
        if receipt.get(key) != value or type(receipt.get(key)) is not type(value):
            raise SourceIntegrityError("BLOCKED_TIMESTAMP_SEMANTIC:RULE_MISMATCH:" + key)
    return receipt


def _native_timestamp(value: Any) -> int:
    # Unlike v1._timestamp, this validates native shape/grid before membership.
    # No price or timezone heuristic can alter a native timestamp.
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise SourceIntegrityError("SOURCE_TIMESTAMP_TYPE")
    try:
        result = int(value)
    except ValueError as exc:
        raise SourceIntegrityError("SOURCE_TIMESTAMP_INVALID") from exc
    if isinstance(value, str) and str(result) != value:
        raise SourceIntegrityError("SOURCE_TIMESTAMP_NONCANONICAL")
    if result < 0 or result % HOUR_MS:
        raise SourceIntegrityError("SOURCE_TIMESTAMP_GRID")
    return result


def _row_shape(item: Any, symbol: str) -> tuple[int, dict[str, Any]]:
    """Read required field presence/aliases, but do not interpret OHLC values yet."""
    if isinstance(item, dict):
        if "symbol" in item and item["symbol"] != symbol:
            raise SourceIntegrityError("SOURCE_SYMBOL_MISMATCH")
        stamp = _native_timestamp(v1._field(item, ("time", "openTime", "timestamp")))
        values = {key: v1._field(item, (key,)) for key in ("open", "high", "low", "close")}
        values["volume"] = v1._field(item, ("volume", "vol", "baseVolume"))
    elif isinstance(item, list) and len(item) >= 6:
        stamp = _native_timestamp(item[0])
        values = {key: item[index] for index, key in
                  enumerate(("open", "high", "low", "close", "volume"), start=1)}
    else:
        raise SourceIntegrityError("SOURCE_ROW_SHAPE")
    return stamp, values


def _admitted_prices(values: Mapping[str, Any]) -> dict[str, float]:
    normalized = {key: v1._number(value, key) for key, value in values.items()}
    if (min(normalized[key] for key in ("open", "high", "low", "close")) <= 0
            or normalized["volume"] < 0
            or normalized["low"] > min(normalized["open"], normalized["close"])
            or normalized["high"] < max(normalized["open"], normalized["close"])
            or normalized["low"] > normalized["high"]):
        raise SourceIntegrityError("SOURCE_OHLC_OR_VOLUME_INVALID")
    return normalized


def decode_page(raw: bytes, symbol: str, logical_upper_ms: int,
                remaining: int, requested_limit: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Select the exact native-open page using timestamps before numeric OHLC.

    A single row at logical_upper is an upper guard. A single row at first-H is
    a lower guard only when the requested extra slot accompanies the complete
    remaining target. Both retain their raw bytes, field shape and native time,
    while their OHLC values are never normalized or economically interpreted.
    Duplicate native times inside a page always fail, including duplicate guards.
    """
    if (symbol not in SYMBOLS or len(raw) > MAX_RESPONSE_BYTES
            or type(logical_upper_ms) is not int
            or not FIRST_OPEN_MS < logical_upper_ms <= CUTOFF_MS
            or logical_upper_ms % HOUR_MS
            or type(remaining) is not int
            or remaining != (logical_upper_ms - FIRST_OPEN_MS) // HOUR_MS
            or type(requested_limit) is not int
            or requested_limit != min(BAR_COUNT, remaining + 1)):
        raise SourceIntegrityError("SOURCE_PAGE_PARAMETERS_INVALID")
    payload = v1._decode_json(raw)
    if (not isinstance(payload, dict) or type(payload.get("code")) is not int
            or payload["code"] != 0 or not isinstance(payload.get("data"), list)):
        raise SourceIntegrityError("SOURCE_API_PAYLOAD_INVALID")
    source_rows = payload["data"]
    if not source_rows or len(source_rows) > requested_limit:
        raise SourceIntegrityError("SOURCE_PAGE_COUNT")

    # First pass is shape/time only. No admitted price is interpreted until the
    # whole response has passed timestamp membership and duplicate validation.
    shaped = [_row_shape(item, symbol) for item in source_rows]
    stamps = [stamp for stamp, _ in shaped]
    if len(set(stamps)) != len(stamps):
        raise SourceIntegrityError("SOURCE_DUPLICATE_TIMESTAMP")
    selected = []
    guards = []
    for stamp, values in shaped:
        if FIRST_OPEN_MS <= stamp < logical_upper_ms:
            selected.append((stamp, values))
        elif stamp == logical_upper_ms:
            guards.append({"native_open_ms": stamp, "reason": "UPPER_BOUNDARY_GUARD",
                           "economic_input": False, "ohlc_values_interpreted": False})
        elif stamp == FIRST_OPEN_MS - HOUR_MS:
            guards.append({"native_open_ms": stamp, "reason": "LOWER_BOUNDARY_EXTRA_GUARD",
                           "economic_input": False, "ohlc_values_interpreted": False})
        else:
            raise SourceIntegrityError("SOURCE_TIMESTAMP_OUTSIDE_PAGE_GUARDS")
    if not selected:
        raise SourceIntegrityError("SOURCE_PAGINATION_STALLED")
    selected.sort(key=lambda item: item[0])
    selected_clock = [stamp for stamp, _ in selected]
    if selected_clock[-1] != logical_upper_ms - HOUR_MS:
        raise SourceIntegrityError("SOURCE_PAGE_END_MISMATCH")
    if any(b - a != HOUR_MS for a, b in zip(selected_clock, selected_clock[1:])):
        raise SourceIntegrityError("SOURCE_PAGE_GAP")
    if any(guard["reason"] == "LOWER_BOUNDARY_EXTRA_GUARD" for guard in guards):
        if requested_limit != remaining + 1 or len(selected) != remaining:
            raise SourceIntegrityError("SOURCE_LOWER_GUARD_NOT_BOUNDED_EXTRA")
    rows = [{"symbol": symbol, "ts_ms": stamp, **_admitted_prices(values)}
            for stamp, values in selected]
    receipt = {
        "logical_upper_ms": logical_upper_ms, "target_first_open_ms": FIRST_OPEN_MS,
        "requested_limit": requested_limit, "remaining_before_page": remaining,
        "raw_rows": len(source_rows), "raw_native_timestamps": stamps,
        "admitted_rows": len(rows), "admitted_native_timestamps": selected_clock,
        "guard_rows": len(guards), "guards": guards,
        "guard_rows_economic_input": 0, "canonical_timestamp_offset_ms": 0,
        "malformed_rows_dropped": 0, "duplicate_rows_dropped": 0,
        "next_logical_upper_ms": selected_clock[0],
    }
    return rows, receipt


def collect(contract_path: str | Path, semantic_path: str | Path, output_dir: str | Path, *,
            transport: Callable[[str, Mapping[str, Any]], Response] | None = None) -> dict[str, Any]:
    """One attempt, at most three GETs per symbol, into a new empty evidence root.

    Semantic/contract rejection precedes the attempt marker and all HTTP. Once
    the exclusive marker exists the attempt remains consumed even after failure.
    DATA_FREEZE_V2.json is emitted only for exact equal 1000-bar native clocks.
    """
    contract_path, semantic_path = Path(contract_path), Path(semantic_path)
    output = Path(output_dir)
    contract_raw, semantic_raw = contract_path.read_bytes(), semantic_path.read_bytes()
    source = validate_contract(v1._decode_json(contract_raw))
    validate_semantic_receipt(semantic_raw, source["timestamp_semantic_receipt_sha256"])
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise SourceIntegrityError("SOURCE_OUTPUT_NOT_EMPTY_NO_RESUME")
    marker = v1._sealed({
        "schema": "trendrider.common.source.attempt.v2", "started_at_ms": v1._clock_ms(),
        "contract_sha256": digest_bytes(contract_raw),
        "timestamp_semantic_receipt_sha256": digest_bytes(semantic_raw),
        "attempt_ordinal": 1, "max_pages_per_symbol": MAX_PAGES,
        "retry_authorized": False,
    })
    try:
        write_once(output / "ATTEMPT_STARTED_V2.json", canonical_bytes(marker))
    except FileExistsError as exc:
        raise SourceIntegrityError("SOURCE_ATTEMPT_ALREADY_CONSUMED") from exc
    requests: list[dict[str, Any]] = []
    pages: list[dict[str, Any]] = []
    normalized: dict[str, Any] = {}
    clocks: dict[str, list[int]] = {}
    active_request = None
    http_get_count = 0

    def check_inputs_unchanged():
        if contract_path.read_bytes() != contract_raw:
            raise SourceIntegrityError("SOURCE_CONTRACT_CHANGED_DURING_FETCH")
        if semantic_path.read_bytes() != semantic_raw:
            raise SourceIntegrityError("SOURCE_SEMANTIC_CHANGED_DURING_FETCH")

    try:
        write_once(output / "SOURCE_CONTRACT_V2.json", contract_raw)
        write_once(output / "TIMESTAMP_SEMANTIC_RECEIPT.json", semantic_raw)
        transport_fn = transport or http_transport
        for symbol in SYMBOLS:
            accumulated = []
            seen = set()
            logical_upper = CUTOFF_MS
            for page_index in range(MAX_PAGES):
                check_inputs_unchanged()
                remaining = BAR_COUNT - len(accumulated)
                params = {
                    "symbol": symbol, "interval": "1h", "limit": min(BAR_COUNT, remaining + 1),
                    "endTime": logical_upper - 1,
                }
                stem = f"raw/{symbol}_{page_index:02d}"
                active_request = {
                    "endpoint": ENDPOINT, "params": params, "page_index": page_index,
                    "logical_upper_ms": logical_upper, "remaining_before_page": remaining,
                    "requested_at_ms": v1._clock_ms(), "transport_retry_count": 0,
                    "timestamp_semantic_receipt_sha256": digest_bytes(semantic_raw),
                }
                write_once(output / (stem + ".request.json"), canonical_bytes(active_request))
                http_get_count += 1
                response = transport_fn(ENDPOINT, params)
                if not isinstance(response, Response) or not isinstance(response.body, bytes):
                    raise SourceIntegrityError("SOURCE_TRANSPORT_RESPONSE_TYPE")
                raw_path = stem + ".bin"
                write_once(output / raw_path, response.body)
                metadata = v1._sealed({
                    **active_request, "received_at_ms": v1._clock_ms(),
                    "http_status": response.status, "response_headers": dict(response.headers),
                    "raw_path": raw_path, "raw_sha256": digest_bytes(response.body),
                    "raw_bytes": len(response.body), "saved_before_decode": True,
                })
                write_once(output / (stem + ".response.json"), canonical_bytes(metadata))
                requests.append(metadata)
                if response.status != 200:
                    raise SourceIntegrityError("SOURCE_HTTP_STATUS:" + str(response.status))
                page, page_detail = decode_page(response.body, symbol, logical_upper,
                                                remaining, params["limit"])
                page_receipt = v1._sealed({
                    "schema": "trendrider.common.source.page.v2", "symbol": symbol,
                    "page_index": page_index, "raw_sha256": digest_bytes(response.body),
                    **page_detail,
                })
                write_once(output / (stem + ".page.json"), canonical_bytes(page_receipt))
                pages.append(page_receipt)
                if any(row["ts_ms"] in seen for row in page):
                    raise SourceIntegrityError("SOURCE_GLOBAL_DUPLICATE")
                seen.update(row["ts_ms"] for row in page)
                accumulated.extend(page)
                if len(accumulated) == BAR_COUNT:
                    break
                next_upper = page[0]["ts_ms"]
                if next_upper >= logical_upper:
                    raise SourceIntegrityError("SOURCE_PAGINATION_STALLED")
                logical_upper = next_upper
            else:
                raise SourceIntegrityError("SOURCE_PAGE_BUDGET_EXHAUSTED")

            accumulated.sort(key=lambda row: row["ts_ms"])
            expected_clock = list(range(FIRST_OPEN_MS, CUTOFF_MS, HOUR_MS))
            actual_clock = [row["ts_ms"] for row in accumulated]
            if actual_clock != expected_clock:
                raise SourceIntegrityError("SOURCE_EXACT_CLOCK_MISMATCH")
            clocks[symbol] = actual_clock
            normalized_path = "sources/" + symbol + ".json"
            normalized_raw = canonical_bytes(accumulated)
            write_once(output / normalized_path, normalized_raw)
            normalized[symbol] = {
                "path": normalized_path, "sha256": digest_bytes(normalized_raw),
                "bytes": len(normalized_raw), "bars": BAR_COUNT,
                "first_open_ms": FIRST_OPEN_MS, "last_open_ms": CUTOFF_MS - HOUR_MS,
                "last_close_ms": CUTOFF_MS, "timestamp_vector_sha256": digest_bytes(canonical_bytes(actual_clock)),
                "canonical_timestamp_offset_ms": 0, "cutoff_or_later_canonical_rows": 0,
                "gap": 0, "duplicate": 0, "malformed_rows_dropped": 0,
            }
        if clocks[SYMBOLS[0]] != clocks[SYMBOLS[1]]:
            raise SourceIntegrityError("SOURCE_SYMBOL_CLOCK_MISMATCH")
        check_inputs_unchanged()
        manifest = v1._sealed({
            "schema": SOURCE_SCHEMA, "state": "FROZEN_COMMON_HISTORICAL_DEV",
            "contract_sha256": digest_bytes(contract_raw), "source": source,
            "timestamp_semantic_receipt_sha256": digest_bytes(semantic_raw),
            "canonical_transform": SEMANTIC_RULES["canonical_transform"],
            "normalized": normalized, "requests": requests, "pages": pages,
            "dataset_sha256": digest_bytes(canonical_bytes(normalized)),
            "completed_at_ms": v1._clock_ms(), "dataset_fetch_attempts": 1,
            "http_get_count": http_get_count, "transport_retries": 0,
            "pages_per_symbol": {symbol: sum(page["symbol"] == symbol for page in pages) for symbol in SYMBOLS},
            "raw_rows": sum(page["raw_rows"] for page in pages),
            "admitted_rows": sum(page["admitted_rows"] for page in pages),
            "guard_rows": sum(page["guard_rows"] for page in pages),
            "guard_rows_economic_input": 0, "canonical_timestamp_offset_ms": 0,
            "symbol_timestamp_vectors_exact_equal": True,
            "guard_validation": "REQUIRED_ROW_SHAPE_SYMBOL_ALIASES_AND_NATIVE_TIMESTAMP_ONLY; OHLC_VALUES_NOT_INTERPRETED",
            "production_grade": False, "formal_credit": 0,
            "prospective_records_decoded": 0, "economic_runs": 0,
            "volume_semantics": "SOURCE_REPORTED_VOLUME_NO_UNIT_CLAIM",
        })
        write_once(output / "DATA_FREEZE_V2.json", canonical_bytes(manifest))
        return manifest
    except Exception as exc:
        failure = v1._sealed({
            "schema": SOURCE_SCHEMA, "state": "BLOCKED_COMMON_SOURCE_DATA",
            "contract_sha256": digest_bytes(contract_raw),
            "timestamp_semantic_receipt_sha256": digest_bytes(semantic_raw),
            "error_type": type(exc).__name__, "reason": str(exc),
            "requests": requests, "pages": pages, "last_attempted_request": active_request,
            "normalized": normalized, "dataset_fetch_attempts": 1,
            "http_get_count": http_get_count, "http_response_count": len(requests),
            "transport_retries": 0, "retry_authorized": False,
            "production_grade": False, "formal_credit": 0, "economic_runs": 0,
            "failed_at_ms": v1._clock_ms(),
        })
        write_once(output / "FAILURE_MANIFEST_V2.json", canonical_bytes(failure))
        if isinstance(exc, SourceIntegrityError):
            raise
        raise SourceIntegrityError("SOURCE_ACQUISITION_FAILED:" + type(exc).__name__) from exc


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", required=True)
    parser.add_argument("--semantic", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(json.dumps(collect(args.contract, args.semantic, args.output), sort_keys=True))
