"""One REST/WS-authorized historical source attempt; no economic execution.

Version 5 preserves the frozen V2 window and backward pagination. A separately
sealed official REST/WS same-candle witness authorizes exactly its observed
native timestamp lane. There is no alias fallback, timestamp shift, retry,
redirect, resume, prospective decode, or strategy change. Guard OHLC values are
never numerically interpreted. V1 canonical serialization remains authoritative.
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
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
SCOPE = "TRENDRIDER_UNIFIED_ACK_REPAIR_AFTER_PR1281_V1"
SOURCE_SCHEMA = "trendrider.common.source.freeze.v5"
AUTHORIZATION_SCHEMA = "trendrider.common.source.authorization.v5"
MIN_REQUEST_SPACING_MS = 1100
REQUEST_HEADERS = {"Accept": "application/json", "X-SOURCE-KEY": "BX-AI-SKILL",
                   "Host": "open-api.bingx.com", "Connection": "close",
                   "User-Agent": "Python-urllib/3.12", "Accept-Encoding": "identity"}
SourceIntegrityError = v1.SourceIntegrityError
Response = v1.Response
canonical_bytes = v1.canonical_bytes
digest_bytes = v1.digest_bytes
write_once = v1.write_once


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
    return expected


def authorization_template(contract_sha256: str, semantic_sha256: str) -> dict[str, Any]:
    """Seal and remotely freeze this post-calibration authority before collect."""
    return v1._sealed({
        "schema": AUTHORIZATION_SCHEMA, "scope_key": SCOPE, "state": "AUTHORIZED_SOURCE_ONCE",
        "contract_sha256": contract_sha256,
        "timestamp_semantic_receipt_sha256": semantic_sha256,
        "dataset_fetch_attempts": 1, "max_pages_per_symbol": MAX_PAGES,
        "max_http_requests": len(SYMBOLS) * MAX_PAGES, "retry_authorized": False,
    })


def _sha(value: Any) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def validate_authorization(raw: bytes, expected_sha256: str,
                           contract_raw: bytes, semantic_raw: bytes) -> dict[str, Any]:
    if not _sha(expected_sha256) or digest_bytes(raw) != expected_sha256:
        raise SourceIntegrityError("SOURCE_AUTHORIZATION_RAW_SHA_MISMATCH")
    expected = authorization_template(digest_bytes(contract_raw), digest_bytes(semantic_raw))
    actual = v1._decode_json(raw)
    if canonical_bytes(actual) != canonical_bytes(expected):
        raise SourceIntegrityError("SOURCE_AUTHORIZATION_BINDING_OR_SEAL_MISMATCH")
    return actual


def _calibration_validate(path: str | Path, expected_sha256: str) -> dict[str, Any]:
    from backend.research.rebuild import trendrider_rest_ws_timestamp_v2 as calibration
    return calibration.validate_semantic_receipt(path, expected_sha256)


def validate_semantic_receipt(path: str | Path, expected_sha256: str) -> dict[str, Any]:
    """Validate exact receipt bytes plus all linked raw witness dependencies."""
    try:
        receipt = _calibration_validate(path, expected_sha256)
    except Exception as exc:
        raise SourceIntegrityError("BLOCKED_REST_WS_TIMESTAMP_WITNESS:" + str(exc)) from exc
    lane = receipt.get("supported_canonical_lane")
    expected_transform = {"OBJECT_TIME_OPEN": "IDENTITY_NATIVE_OBJECT_TIME_MS",
                          "ARRAY_OPEN_CLOSE": "IDENTITY_NATIVE_ARRAY_OPEN_MS"}
    if (receipt.get("state") != "PASS" or lane not in expected_transform
            or receipt.get("canonical_open_transform") != expected_transform[lane]
            or type(receipt.get("timestamp_adjustment_ms")) is not int
            or receipt["timestamp_adjustment_ms"] != 0
            or type(receipt.get("hour_ms")) is not int or receipt["hour_ms"] != HOUR_MS
            or receipt.get("symbol") != "BTC-USDT" or receipt.get("interval") != "1h"):
        raise SourceIntegrityError("BLOCKED_REST_WS_TIMESTAMP_WITNESS:CANONICAL_LANE")
    witness = receipt.get("witness", {})
    opened, closed = witness.get("ws_open_ms"), witness.get("ws_close_ms")
    if (type(opened) is not int or type(closed) is not int
            or opened % HOUR_MS or closed - opened not in (HOUR_MS - 1, HOUR_MS)
            or witness.get("ohlc_exact_match") is not True):
        raise SourceIntegrityError("BLOCKED_REST_WS_TIMESTAMP_WITNESS:EXPLICIT_CLOSE")
    expected_rule = ("OPEN_PLUS_HOUR_MINUS_1_MS" if lane == "OBJECT_TIME_OPEN"
                     else "IDENTITY_NATIVE_ARRAY_CLOSE_MS")
    if receipt.get("canonical_close_rule") != expected_rule:
        raise SourceIntegrityError("BLOCKED_REST_WS_TIMESTAMP_WITNESS:CLOSE_CONVENTION")
    # A same-candle timestamp match alone can be a still-forming candle. Issue
    # 1282 authorizes source promotion only after that matched candle was closed
    # when both its WS frame and its REST request were observed. Recheck the
    # exact bound bytes before reading these timestamps; never alter K.t/K.T.
    root = Path(path).parent
    moments = []
    for field, moment_field in (("ws_meta_path", "received_at_ms"),
                                ("rest_request_path", "requested_at_ms")):
        relative = witness[field]
        raw = (root / relative).read_bytes()
        if digest_bytes(raw) != receipt["artifact_sha256"].get(relative):
            raise SourceIntegrityError("BLOCKED_REST_WS_TIMESTAMP_WITNESS:REST_WS_ARTIFACT_HASH:" + relative)
        moments.append(v1._decode_json(raw).get(moment_field))
    if any(type(moment) is not int or moment < closed for moment in moments):
        raise SourceIntegrityError("BLOCKED_REST_WS_TIMESTAMP_WITNESS:CANDLE_NOT_CLOSED")
    return receipt


def _request(endpoint: str, params: Mapping[str, Any], headers: Mapping[str, str]):
    if endpoint != ENDPOINT or dict(headers) != REQUEST_HEADERS:
        raise SourceIntegrityError("SOURCE_TRANSPORT_ENDPOINT_OR_HEADERS")
    if (set(params) != {"symbol", "interval", "limit", "endTime"}
            or params.get("symbol") not in SYMBOLS or params.get("interval") != "1h"
            or type(params.get("limit")) is not int or not 1 <= params["limit"] <= BAR_COUNT
            or type(params.get("endTime")) is not int
            or not FIRST_OPEN_MS <= params["endTime"] < CUTOFF_MS
            or (params["endTime"] + 1) % HOUR_MS):
        raise SourceIntegrityError("SOURCE_TRANSPORT_PARAMS")
    return urllib.request.Request(endpoint + "?" + urllib.parse.urlencode(params),
                                  method="GET", headers=dict(headers))


def http_transport(endpoint: str, params: Mapping[str, Any],
                   headers: Mapping[str, str]) -> Response:
    """Exactly one GET; persistable HTTP errors, no undeclared wire headers."""
    request = _request(endpoint, params, headers)
    opener = urllib.request.build_opener(v1._NoRedirect())
    opener.addheaders = []
    try:
        response = opener.open(request, timeout=30)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        return Response(int(response.status), dict(response.headers.items()),
                        response.read(MAX_RESPONSE_BYTES + 1))


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


def _row_shape(item: Any, symbol: str, lane: str,
               close_delta_ms: int) -> tuple[int, dict[str, Any]]:
    """Shape/time only; admitted and quarantined OHLC remain uninterpreted."""
    if lane == "OBJECT_TIME_OPEN":
        required = {"time", "open", "high", "low", "close", "volume"}
        if (not isinstance(item, dict) or not required.issubset(item)
                or not set(item).issubset(required | {"symbol"})):
            raise SourceIntegrityError("SOURCE_NATIVE_OBJECT_FIELDS_REQUIRED_NO_ALIASES")
        if "symbol" in item and item["symbol"] != symbol:
            raise SourceIntegrityError("SOURCE_SYMBOL_MISMATCH")
        stamp = _native_timestamp(item["time"])
        values = {key: item[key] for key in ("open", "high", "low", "close", "volume")}
    elif lane == "ARRAY_OPEN_CLOSE":
        if not isinstance(item, list) or len(item) < 7:
            raise SourceIntegrityError("SOURCE_NATIVE_ARRAY_OPEN_CLOSE_REQUIRED")
        stamp = _native_timestamp(item[0])
        closed = item[6]
        if (isinstance(closed, bool) or not isinstance(closed, (int, str))
                or (isinstance(closed, str) and not closed.isdecimal())):
            raise SourceIntegrityError("SOURCE_ARRAY_CLOSE_TYPE")
        native_close = int(closed)
        if str(native_close) != str(closed) or native_close - stamp != close_delta_ms:
            raise SourceIntegrityError("SOURCE_ARRAY_CLOSE_CONVENTION_MISMATCH")
        values = {key: item[index] for index, key in
                  enumerate(("open", "high", "low", "close", "volume"), start=1)}
    else:
        raise SourceIntegrityError("SOURCE_WITNESS_LANE_REQUIRED")
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
                remaining: int, requested_limit: int, *,
                lane: str, close_delta_ms: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Select the exact native-open page using timestamps before numeric OHLC.

    A single row at logical_upper is an upper guard. A single row at first-H is
    a lower guard only when the requested extra slot accompanies the complete
    remaining target. Both retain their raw bytes, field shape and native time,
    while their OHLC values are never normalized or economically interpreted.
    Duplicate native times inside a page always fail, including duplicate guards.
    """
    if (lane not in ("OBJECT_TIME_OPEN", "ARRAY_OPEN_CLOSE")
            or type(close_delta_ms) is not int or close_delta_ms not in (HOUR_MS - 1, HOUR_MS)
            or (lane == "OBJECT_TIME_OPEN" and close_delta_ms != HOUR_MS - 1)
            or symbol not in SYMBOLS or len(raw) > MAX_RESPONSE_BYTES
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
    shaped = [_row_shape(item, symbol, lane, close_delta_ms) for item in source_rows]
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
        "supported_canonical_lane": lane, "close_minus_open_ms": close_delta_ms,
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
            authorization_path: str | Path, expected_authorization_sha256: str,
            transport: Callable[[str, Mapping[str, Any], Mapping[str, str]], Response] | None = None,
            monotonic: Callable[[], float] | None = None,
            sleep: Callable[[float], None] | None = None) -> dict[str, Any]:
    """One attempt after remote-sealed PASS; at most three GETs per symbol.

    The output directory must be new/empty and remains consumed after failure.
    Every response byte and metadata record is persisted before decode or input
    revalidation. No future source/economic stage can be entered by this module.
    """
    contract_path, semantic_path = Path(contract_path), Path(semantic_path)
    authorization_path, output = Path(authorization_path), Path(output_dir)
    contract_raw, semantic_raw = contract_path.read_bytes(), semantic_path.read_bytes()
    authorization_raw = authorization_path.read_bytes()
    source = validate_contract(v1._decode_json(contract_raw))
    authority = validate_authorization(authorization_raw, expected_authorization_sha256,
                                       contract_raw, semantic_raw)
    semantic_sha = authority["timestamp_semantic_receipt_sha256"]
    semantic = validate_semantic_receipt(semantic_path, semantic_sha)
    lane = semantic["supported_canonical_lane"]
    native_ws_close_delta = semantic["witness"]["ws_close_ms"] - semantic["witness"]["ws_open_ms"]
    close_delta = HOUR_MS - 1 if lane == "OBJECT_TIME_OPEN" else native_ws_close_delta
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise SourceIntegrityError("SOURCE_OUTPUT_NOT_EMPTY_NO_RESUME")
    marker = v1._sealed({
        "schema": "trendrider.common.source.attempt.v5", "scope_key": SCOPE, "started_at_ms": v1._clock_ms(),
        "contract_sha256": digest_bytes(contract_raw),
        "timestamp_semantic_receipt_sha256": semantic_sha,
        "source_authorization_sha256": expected_authorization_sha256,
        "attempt_ordinal": 1, "max_pages_per_symbol": MAX_PAGES,
        "retry_authorized": False,
    })
    try:
        write_once(output / "ATTEMPT_STARTED_V5.json", canonical_bytes(marker))
    except FileExistsError as exc:
        raise SourceIntegrityError("SOURCE_ATTEMPT_ALREADY_CONSUMED") from exc
    requests: list[dict[str, Any]] = []
    pages: list[dict[str, Any]] = []
    normalized: dict[str, Any] = {}
    clocks: dict[str, list[int]] = {}
    active_request = None
    http_get_count = 0
    previous_started = None
    monotonic_fn, sleep_fn = monotonic or time.monotonic, sleep or time.sleep

    def check_inputs_unchanged():
        if contract_path.read_bytes() != contract_raw:
            raise SourceIntegrityError("SOURCE_CONTRACT_CHANGED_DURING_FETCH")
        if semantic_path.read_bytes() != semantic_raw:
            raise SourceIntegrityError("SOURCE_SEMANTIC_CHANGED_DURING_FETCH")
        if authorization_path.read_bytes() != authorization_raw:
            raise SourceIntegrityError("SOURCE_AUTHORIZATION_CHANGED_DURING_FETCH")
        validate_semantic_receipt(semantic_path, semantic_sha)

    try:
        write_once(output / "SOURCE_CONTRACT_V5.json", contract_raw)
        write_once(output / "REST_WS_TIMESTAMP_SEMANTIC_RECEIPT_V2.json", semantic_raw)
        write_once(output / "SOURCE_AUTHORIZATION_V5.json", authorization_raw)
        transport_fn = transport or http_transport
        for symbol in SYMBOLS:
            accumulated = []
            seen = set()
            logical_upper = CUTOFF_MS
            for page_index in range(MAX_PAGES):
                if previous_started is not None:
                    wait_seconds = MIN_REQUEST_SPACING_MS / 1000 - (monotonic_fn() - previous_started)
                    if wait_seconds > 0:
                        sleep_fn(wait_seconds)
                # The check belongs after pacing; mutation during sleep blocks I/O.
                check_inputs_unchanged()
                remaining = BAR_COUNT - len(accumulated)
                params = {
                    "symbol": symbol, "interval": "1h", "limit": min(BAR_COUNT, remaining + 1),
                    "endTime": logical_upper - 1,
                }
                stem = f"raw/{symbol}_{page_index:02d}"
                active_request = {
                    "endpoint": ENDPOINT, "method": "GET", "params": dict(params),
                    "request_headers": dict(REQUEST_HEADERS), "page_index": page_index,
                    "min_request_spacing_ms": MIN_REQUEST_SPACING_MS,
                    "logical_upper_ms": logical_upper, "remaining_before_page": remaining,
                    "requested_at_ms": v1._clock_ms(), "transport_retry_count": 0,
                    "timestamp_semantic_receipt_sha256": digest_bytes(semantic_raw),
                }
                write_once(output / (stem + ".request.json"), canonical_bytes(active_request))
                _request(ENDPOINT, params, REQUEST_HEADERS)
                check_inputs_unchanged()
                http_get_count += 1  # Reserved before I/O, including transport failure.
                previous_started = monotonic_fn()
                response = transport_fn(ENDPOINT, dict(params), dict(REQUEST_HEADERS))
                if not isinstance(response, Response) or not isinstance(response.body, bytes):
                    raise SourceIntegrityError("SOURCE_TRANSPORT_RESPONSE_TYPE")
                raw_path = stem + ".bin"
                write_once(output / raw_path, response.body)
                metadata = v1._sealed({
                    **active_request, "received_at_ms": v1._clock_ms(),
                    "http_status": response.status, "response_headers": dict(response.headers),
                    "raw_path": raw_path, "raw_sha256": digest_bytes(response.body),
                    "raw_bytes": len(response.body), "saved_before_decode": True,
                    "response_truncated": len(response.body) > MAX_RESPONSE_BYTES,
                })
                write_once(output / (stem + ".response.json"), canonical_bytes(metadata))
                requests.append(metadata)
                check_inputs_unchanged()
                if response.status != 200:
                    raise SourceIntegrityError("SOURCE_HTTP_STATUS:" + str(response.status))
                page, page_detail = decode_page(response.body, symbol, logical_upper,
                                                remaining, params["limit"],
                                                lane=lane, close_delta_ms=close_delta)
                page_receipt = v1._sealed({
                    "schema": "trendrider.common.source.page.v5", "symbol": symbol,
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
                "last_close_ms": CUTOFF_MS - HOUR_MS + close_delta,
                "last_close_exclusive_ms": CUTOFF_MS,
                "timestamp_vector_sha256": digest_bytes(canonical_bytes(actual_clock)),
                "canonical_timestamp_offset_ms": 0, "cutoff_or_later_canonical_rows": 0,
                "gap": 0, "duplicate": 0, "malformed_rows_dropped": 0,
            }
        if clocks[SYMBOLS[0]] != clocks[SYMBOLS[1]]:
            raise SourceIntegrityError("SOURCE_SYMBOL_CLOCK_MISMATCH")
        check_inputs_unchanged()
        manifest = v1._sealed({
            "schema": SOURCE_SCHEMA, "scope_key": SCOPE, "state": "FROZEN_COMMON_HISTORICAL_DEV",
            "contract_sha256": digest_bytes(contract_raw), "source": source,
            "timestamp_semantic_receipt_sha256": digest_bytes(semantic_raw),
            "source_authorization_sha256": expected_authorization_sha256,
            "supported_canonical_lane": lane,
            "canonical_open_transform": semantic["canonical_open_transform"],
            "canonical_close_rule": semantic["canonical_close_rule"],
            "native_ws_close_delta_ms": native_ws_close_delta,
            "canonical_close_delta_ms": close_delta,
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
            "guard_validation": "REQUIRED_NATIVE_LANE_SHAPE_SYMBOL_AND_TIMESTAMP_ONLY_NO_ALIASES; OHLC_VALUES_NOT_INTERPRETED",
            "production_grade": False, "formal_credit": 0,
            "prospective_records_decoded": 0, "economic_runs": 0,
            "volume_semantics": "SOURCE_REPORTED_VOLUME_NO_UNIT_CLAIM",
        })
        write_once(output / "DATA_FREEZE_V5.json", canonical_bytes(manifest))
        return manifest
    except Exception as exc:
        failure = v1._sealed({
            "schema": SOURCE_SCHEMA, "scope_key": SCOPE, "state": "BLOCKED_COMMON_SOURCE_DATA",
            "contract_sha256": digest_bytes(contract_raw),
            "timestamp_semantic_receipt_sha256": digest_bytes(semantic_raw),
            "source_authorization_sha256": expected_authorization_sha256,
            "error_type": type(exc).__name__, "reason": str(exc),
            "requests": requests, "pages": pages, "last_attempted_request": active_request,
            "normalized": normalized, "dataset_fetch_attempts": 1,
            "http_get_count": http_get_count, "http_response_count": len(requests),
            "transport_retries": 0, "retry_authorized": False,
            "production_grade": False, "formal_credit": 0, "economic_runs": 0,
            "failed_at_ms": v1._clock_ms(),
        })
        write_once(output / "FAILURE_MANIFEST_V5.json", canonical_bytes(failure))
        if isinstance(exc, SourceIntegrityError):
            raise
        raise SourceIntegrityError("SOURCE_ACQUISITION_FAILED:" + type(exc).__name__) from exc


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", required=True)
    parser.add_argument("--semantic", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--authorization", required=True)
    parser.add_argument("--authorization-sha256", required=True)
    args = parser.parse_args()
    print(json.dumps(collect(args.contract, args.semantic, args.output,
                             authorization_path=args.authorization,
                             expected_authorization_sha256=args.authorization_sha256), sort_keys=True))
