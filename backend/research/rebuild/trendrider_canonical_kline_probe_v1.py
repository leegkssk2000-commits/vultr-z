"""Two preregistered timestamp-only probes; no prices or economic evaluation.

Only native array open/close positions can establish the supported canonical
lane. Object ``time`` remains diagnostic, even when it equals requested time.
Every request and raw response is persisted before timestamp JSON decoding.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import time
from typing import Any, Callable, Mapping
import urllib.error
import urllib.parse
import urllib.request

from backend.research.rebuild import trendrider_common_source_v1 as v1

Response = v1.Response
SourceIntegrityError = v1.SourceIntegrityError
canonical_bytes = v1.canonical_bytes
digest_bytes = v1.digest_bytes
write_once = v1.write_once
ENDPOINT = v1.ENDPOINT
HOUR_MS = v1.HOUR_MS
PROBE_T_MS = 1_784_332_800_000  # 2026-07-18T00:00:00Z, before replay input.
MAX_RESPONSE_BYTES = 1024 * 1024
PROTOCOL_SCHEMA = "trendrider.canonical.kline.probe.protocol.v1"
RECEIPT_SCHEMA = "trendrider.canonical.kline.timestamp.receipt.v1"
REQUEST_HEADERS = {"Accept": "application/json", "X-SOURCE-KEY": "BX-AI-SKILL",
                   "Host": "open-api.bingx.com", "Connection": "close",
                   "User-Agent": "Python-urllib/3.12", "Accept-Encoding": "identity"}
CLOSE_CONVENTIONS = {HOUR_MS - 1: "INCLUSIVE_LAST_MILLISECOND",
                     HOUR_MS: "EXCLUSIVE_NEXT_OPEN"}


def protocol_template(official_authority_sha256: str) -> dict[str, Any]:
    """Exact pre-outcome protocol; seal/hash the authority file before calling."""
    return v1._sealed({
        "schema": PROTOCOL_SCHEMA,
        "official_authority_sha256": official_authority_sha256,
        "endpoint": ENDPOINT, "method": "GET", "request_headers": dict(REQUEST_HEADERS),
        "probes": [
            {"id": label, "params": {"symbol": "BTC-USDT", "interval": "1h",
             "startTime": stamp, "endTime": stamp + HOUR_MS - 1, "limit": 3}}
            for label, stamp in (("A", PROBE_T_MS), ("B", PROBE_T_MS + HOUR_MS))],
        "max_http_calls": 2, "max_attempts": 1, "retry_count": 0,
        "redirects": False, "timeout_seconds": 30,
        "min_request_spacing_ms": 1100,
        "raw_read_cap_bytes": MAX_RESPONSE_BYTES,
        "supported_canonical_lane": "ARRAY_ONLY",
        "array_timestamp_positions": {"open": 0, "close": 6},
        "allowed_row_count": [1, 2, 3],
        "required_target_rows": 1,
        "allowed_guard_open_offsets_ms": [-HOUR_MS, HOUR_MS],
        "close_minus_open_ms": [HOUR_MS - 1, HOUR_MS],
        "require_one_close_convention_across_all_rows_and_probes": True,
        "canonical_open_transform": "IDENTITY_NATIVE_ARRAY_OPEN_MS",
        "canonical_close_exclusive_transform": "NATIVE_OPEN_PLUS_INTERVAL_MS",
        "object_mapping": "BLOCKED_WITHOUT_INDEPENDENT_CROSS_SCHEMA_WITNESS",
        "semantic_failure_continues_adjacent_probe": True,
        "fatal_abort": ["TRANSPORT", "HTTP_STATUS", "RESPONSE_LIMIT", "JSON",
                        "API_ENVELOPE", "ROW_SHAPE", "TIMESTAMP_TYPE"],
        "ohlc_numeric_interpretation": False, "economic_executions": 0,
        "outcome_independent": True,
    })


def validate_protocol(raw: bytes, authority_raw: bytes) -> dict[str, Any]:
    protocol = v1._decode_json(raw)
    expected = protocol_template(digest_bytes(authority_raw))
    # Canonical byte equality is deliberately type-strict: True is not 1.
    if canonical_bytes(protocol) != canonical_bytes(expected):
        raise SourceIntegrityError("PROBE_PROTOCOL_OR_AUTHORITY_HASH_MISMATCH")
    if not isinstance(v1._decode_json(authority_raw), dict):
        raise SourceIntegrityError("PROBE_AUTHORITY_RECEIPT_OBJECT_REQUIRED")
    return protocol


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _request(endpoint: str, params: Mapping[str, Any], headers: Mapping[str, str]):
    if endpoint != ENDPOINT or dict(headers) != REQUEST_HEADERS:
        raise SourceIntegrityError("PROBE_TRANSPORT_ENDPOINT_OR_HEADERS")
    expected = [probe["params"] for probe in protocol_template("unused")["probes"]]
    if canonical_bytes(dict(params)) not in [canonical_bytes(value) for value in expected]:
        raise SourceIntegrityError("PROBE_TRANSPORT_PARAMS")
    return urllib.request.Request(endpoint + "?" + urllib.parse.urlencode(params),
                                  method="GET", headers=dict(headers))


def http_transport(endpoint: str, params: Mapping[str, Any],
                   headers: Mapping[str, str]) -> Response:
    """One urllib GET, no redirect/retry; retain HTTPError bodies and cap+1 bytes."""
    request = _request(endpoint, params, headers)
    opener = urllib.request.build_opener(_NoRedirect())
    opener.addheaders = []  # No undeclared default User-Agent.
    try:
        response = opener.open(request, timeout=30)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        return Response(int(response.status), dict(response.headers.items()),
                        response.read(MAX_RESPONSE_BYTES + 1))


def _timestamp(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise SourceIntegrityError("PROBE_TIMESTAMP_TYPE")
    try:
        stamp = int(value)
    except ValueError as exc:
        raise SourceIntegrityError("PROBE_TIMESTAMP_TYPE") from exc
    if stamp < 0 or (isinstance(value, str) and str(stamp) != value):
        raise SourceIntegrityError("PROBE_TIMESTAMP_TYPE")
    return stamp


def decode_timestamp_probe(raw: bytes, target_ms: int) -> dict[str, Any]:
    """Inspect shape/timestamps only; prices, volume, features and returns unused.

Structural/transport failures abort the remaining call. Valid JSON/schema with
incompatible timestamp evidence yields a semantic failure and still observes B.
    """
    payload = v1._decode_json(raw)
    if (not isinstance(payload, dict) or type(payload.get("code")) is not int
            or payload["code"] != 0 or not isinstance(payload.get("data"), list)):
        raise SourceIntegrityError("PROBE_API_ENVELOPE")
    rows = payload["data"]
    detail: dict[str, Any] = {"target_open_ms": target_ms, "row_count": len(rows),
                             "ohlc_values_interpreted": False,
                             "guard_rows_economic_input": 0}
    shapes = set()
    arrays, objects = [], []
    for row in rows:
        if isinstance(row, list):
            if len(row) < 7:
                raise SourceIntegrityError("PROBE_ROW_SHAPE_ARRAY_CLOSE_MISSING")
            shapes.add("array")
            opened, closed = _timestamp(row[0]), _timestamp(row[6])
            arrays.append({"native_open_ms": opened, "native_close_ms": closed,
                           "close_minus_open_ms": closed - opened,
                           "canonical_close_exclusive_ms": opened + HOUR_MS,
                           "is_target": opened == target_ms})
        elif isinstance(row, dict):
            if not all(name in row for name in ("open", "high", "low", "close")):
                raise SourceIntegrityError("PROBE_ROW_SHAPE_OBJECT_OHLC_FIELDS_MISSING")
            if not any(name in row for name in ("volume", "vol", "baseVolume")):
                raise SourceIntegrityError("PROBE_ROW_SHAPE_OBJECT_VOLUME_MISSING")
            fields = {name: _timestamp(row[name]) for name in
                      ("time", "timestamp", "openTime", "closeTime", "open_time", "close_time")
                      if name in row}
            if not fields:
                raise SourceIntegrityError("PROBE_ROW_SHAPE_OBJECT_TIMESTAMP_MISSING")
            shapes.add("object")
            objects.append({"field_names": sorted(fields), "timestamp_fields": fields})
        else:
            raise SourceIntegrityError("PROBE_ROW_SHAPE")
    detail.update({"array_timestamp_rows": arrays, "object_timestamp_rows": objects,
                   "schemas": sorted(shapes), "guard_count": sum(not row["is_target"] for row in arrays)})
    reasons = []
    if not 1 <= len(rows) <= 3:
        reasons.append("PROBE_ROW_COUNT")
    if shapes == {"object"}:
        reasons.append("OBJECT_TIME_WITHOUT_CROSS_SCHEMA_WITNESS")
    elif shapes != {"array"}:
        reasons.append("MIXED_OR_EMPTY_CANONICAL_KLINE_SCHEMA")
    else:
        opens = [row["native_open_ms"] for row in arrays]
        deltas = {row["close_minus_open_ms"] for row in arrays}
        if len(set(opens)) != len(opens):
            reasons.append("PROBE_DUPLICATE_OPEN_TIMESTAMP")
        if opens.count(target_ms) != 1:
            reasons.append("PROBE_TARGET_OPEN_NOT_EXACTLY_ONCE")
        if any(stamp % HOUR_MS or stamp not in (target_ms - HOUR_MS, target_ms, target_ms + HOUR_MS)
               for stamp in opens):
            reasons.append("PROBE_OPEN_GRID_OR_GUARD_RANGE")
        if len(deltas) != 1 or not deltas.issubset(CLOSE_CONVENTIONS):
            reasons.append("PROBE_NATIVE_CLOSE_CONVENTION")
        if not reasons:
            detail["native_close_convention"] = CLOSE_CONVENTIONS[next(iter(deltas))]
    detail.update({"state": "PASS" if not reasons else "FAIL_SEMANTIC", "reasons": reasons})
    return detail


def probe(protocol_path: str | Path, official_schema_receipt_path: str | Path,
          output_dir: str | Path, *,
          transport: Callable[[str, Mapping[str, Any], Mapping[str, str]], Response] | None = None
          ) -> dict[str, Any]:
    """Reserve once, observe A/B within the fixed budget, return a saved terminal receipt.

Invalid preflight files raise before reservation/network. Acquired failures are
terminal BLOCKED receipts, with attempted call count including transport errors.
No resume/retry and no successful object mapping are implemented.
    """
    protocol_path, authority_path, output = (Path(protocol_path),
                                            Path(official_schema_receipt_path), Path(output_dir))
    protocol_raw, authority_raw = protocol_path.read_bytes(), authority_path.read_bytes()
    protocol = validate_protocol(protocol_raw, authority_raw)
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise SourceIntegrityError("PROBE_OUTPUT_NOT_EMPTY_NO_RESUME")
    marker = v1._sealed({"schema": "trendrider.canonical.kline.probe.attempt.v1",
                         "started_at_ms": v1._clock_ms(), "attempt_ordinal": 1,
                         "protocol_sha256": digest_bytes(protocol_raw),
                         "official_authority_sha256": digest_bytes(authority_raw),
                         "retry_count": 0, "economic_executions": 0})
    try:
        write_once(output / "CALIBRATION_ATTEMPT_STARTED.json", canonical_bytes(marker))
    except FileExistsError as exc:
        raise SourceIntegrityError("PROBE_ATTEMPT_ALREADY_CONSUMED") from exc
    write_once(output / "PROBE_PROTOCOL.json", protocol_raw)
    write_once(output / "OFFICIAL_SCHEMA_AUTHORITY.json", authority_raw)
    observations, raw_index = [], []
    calls = 0
    fatal_reason = None
    transport_fn = transport or http_transport
    previous_request_started = None
    def inputs_unchanged():
        try:
            return protocol_path.read_bytes() == protocol_raw and authority_path.read_bytes() == authority_raw
        except OSError:
            return False
    for spec in protocol["probes"]:
        if previous_request_started is not None:
            remaining = protocol["min_request_spacing_ms"] / 1000 - (time.monotonic() - previous_request_started)
            if remaining > 0:
                time.sleep(remaining)
        # Pacing yields control; recheck the frozen files after that wait and
        # immediately before preparing/persisting the outbound request.
        if not inputs_unchanged():
            fatal_reason = "PROBE_PREREGISTERED_INPUT_CHANGED"
            write_once(output / ("raw/probe_" + spec["id"] + ".failure.json"), canonical_bytes(v1._sealed({
                "probe_id": spec["id"], "reason": fatal_reason, "actual_http_calls": calls,
                "retry_count": 0, "raw_response_saved": False, "request_dispatched": False})))
            break
        stem = "raw/probe_" + spec["id"]
        request = _request(ENDPOINT, spec["params"], REQUEST_HEADERS)
        request_metadata = {
            "probe_id": spec["id"], "endpoint": ENDPOINT, "method": "GET",
            "params": spec["params"], "url": request.full_url,
            "query": urllib.parse.urlsplit(request.full_url).query,
            "request_headers": dict(REQUEST_HEADERS),
            "urllib_request_header_items": [list(pair) for pair in request.header_items()],
            "opener_default_headers": [], "redirects": False,
            "timeout_seconds": 30, "raw_read_cap_bytes": MAX_RESPONSE_BYTES,
            "min_request_spacing_ms": protocol["min_request_spacing_ms"],
            "requested_at_ms": v1._clock_ms(), "retry_count": 0,
        }
        write_once(output / (stem + ".request.json"), canonical_bytes(request_metadata))
        previous_request_started = time.monotonic()
        calls += 1  # A transport failure consumes the already-reserved call.
        try:
            response = transport_fn(ENDPOINT, dict(spec["params"]), dict(REQUEST_HEADERS))
            if (not isinstance(response, Response) or not isinstance(response.body, bytes)
                    or type(response.status) is not int):
                raise SourceIntegrityError("PROBE_TRANSPORT_RESPONSE_TYPE")
            write_once(output / (stem + ".bin"), response.body)
            meta = v1._sealed({
                **request_metadata, "received_at_ms": v1._clock_ms(),
                "http_status": response.status, "response_headers": dict(response.headers),
                "response_headers_representation": "MAPPING_DUPLICATE_HEADER_VALUES_MAY_BE_PROJECTED",
                "raw_path": stem + ".bin", "raw_sha256": digest_bytes(response.body),
                "saved_raw_bytes": len(response.body),
                "truncated": len(response.body) > MAX_RESPONSE_BYTES,
                "full_response_length_known": len(response.body) <= MAX_RESPONSE_BYTES,
                "saved_before_decode": True,
            })
            write_once(output / (stem + ".response.json"), canonical_bytes(meta))
            raw_index.append(meta)
            if len(response.body) > MAX_RESPONSE_BYTES:
                raise SourceIntegrityError("PROBE_RESPONSE_LIMIT")
            if response.status != 200:
                raise SourceIntegrityError("PROBE_HTTP_STATUS:" + str(response.status))
            result = decode_timestamp_probe(response.body, spec["params"]["startTime"])
            observations.append({"probe_id": spec["id"], **result})
        except Exception as exc:
            fatal_reason = str(exc) if isinstance(exc, SourceIntegrityError) else "PROBE_TRANSPORT:" + type(exc).__name__
            error = v1._sealed({"probe_id": spec["id"], "reason": fatal_reason,
                                "actual_http_calls": calls, "retry_count": 0,
                                "raw_response_saved": bool(raw_index and raw_index[-1]["probe_id"] == spec["id"])})
            write_once(output / (stem + ".failure.json"), canonical_bytes(error))
            break
    reasons = [reason for result in observations for reason in result["reasons"]]
    if fatal_reason:
        reasons.append(fatal_reason)
    if len(observations) != 2:
        reasons.append("TWO_ADJACENT_PROBES_NOT_COMPLETED")
    conventions = {result.get("native_close_convention") for result in observations}
    if len(observations) == 2 and all(result["state"] == "PASS" for result in observations) and len(conventions) != 1:
        reasons.append("PROBE_ADJACENT_CLOSE_CONVENTION_MISMATCH")
    if not inputs_unchanged():
        reasons.append("PROBE_PREREGISTERED_INPUT_CHANGED")
    passed = not reasons
    receipt = v1._sealed({
        "schema": RECEIPT_SCHEMA,
        "state": "PASS_CANONICAL_KLINE_ARRAY" if passed else "BLOCKED_CANONICAL_KLINE_SCHEMA",
        "reasons": sorted(set(reasons)), "completed_at_ms": v1._clock_ms(),
        "protocol_sha256": digest_bytes(protocol_raw),
        "official_authority_sha256": digest_bytes(authority_raw),
        "actual_http_calls": calls, "max_http_calls": 2, "attempt_ordinal": 1,
        "retry_count": 0, "raw_responses": raw_index, "probe_outcomes": observations,
        "supported_canonical_lane": "ARRAY_ONLY" if passed else None,
        "object_time_mapping_authorized": False,
        "canonical_open_transform": "IDENTITY_NATIVE_ARRAY_OPEN_MS" if passed else None,
        "canonical_close_exclusive_transform": "NATIVE_OPEN_PLUS_INTERVAL_MS" if passed else None,
        "native_close_convention": next(iter(conventions)) if passed else None,
        "interval_ms": HOUR_MS, "endpoint": ENDPOINT,
        "ohlc_numeric_interpretation": False, "economic_executions": 0,
        "guard_rows_economic_input": 0, "outcome_independent": True,
        "acquisition_authorized": passed,
    })
    write_once(output / "CANONICAL_KLINE_TIMESTAMP_RECEIPT.json", canonical_bytes(receipt))
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--official-schema-receipt", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    result = probe(args.protocol, args.official_schema_receipt, args.output_dir)
    print(canonical_bytes({key: result[key] for key in
                           ("state", "reasons", "actual_http_calls", "economic_executions")}).decode(), end="")


if __name__ == "__main__":
    main()
