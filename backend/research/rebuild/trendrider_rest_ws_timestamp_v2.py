"""One bounded REST/WS timestamp witness, entirely separate from economics.

Network imports occur only in the explicitly invoked live transports. Synthetic
transports exercise the same owner. All application wire bytes precede decoding.
"""
from __future__ import annotations

import argparse
import asyncio
from decimal import Decimal, InvalidOperation
import gzip
import io
import json
from pathlib import Path
import time
from typing import Any, Mapping
import urllib.parse

from backend.research.rebuild import trendrider_common_source_v1 as base

SourceIntegrityError = base.SourceIntegrityError
canonical_bytes, digest_bytes, write_once = base.canonical_bytes, base.digest_bytes, base.write_once
HOUR_MS = 3_600_000
SCOPE = "TRENDRIDER_UNIFIED_ACK_REPAIR_AFTER_PR1281_V1"
WS_ENDPOINT = "wss://open-api-swap.bingx.com/swap-market"
REST_ENDPOINT = base.ENDPOINT
CHANNEL = "BTC-USDT@kline_1h"
SYMBOL = "BTC-USDT"
SESSION_ID = "trendrider-rest-ws-1282-v2"
PROTOCOL_SCHEMA = "trendrider.rest.ws.timestamp.protocol.v2"
RECEIPT_SCHEMA = "trendrider.rest.ws.timestamp.semantic.receipt.v2"
MAX_BYTES = 1_048_576
REQUEST_HEADERS = {"Accept": "application/json", "X-SOURCE-KEY": "BX-AI-SKILL",
                   "Host": "open-api.bingx.com", "Connection": "close",
                   "User-Agent": "TrendRider-Semantic-Witness/1", "Accept-Encoding": "identity"}


def sealed(value):
    return base._sealed(value)


def check_seal(value):
    if not isinstance(value, dict) or value.get("receipt_sha256") != digest_bytes(
            canonical_bytes({k: v for k, v in value.items() if k != "receipt_sha256"})):
        raise SourceIntegrityError("REST_WS_RECEIPT_SEAL")


def protocol_template(authority_sha256: str) -> dict:
    return sealed({
        "schema": PROTOCOL_SCHEMA, "scope_key": SCOPE, "session_id": SESSION_ID,
        "authority_sha256": authority_sha256, "ws_endpoint": WS_ENDPOINT,
        "rest_endpoint": REST_ENDPOINT, "symbol": SYMBOL, "interval": "1h",
        "subscription": {"id": SESSION_ID, "reqType": "sub", "dataType": CHANNEL},
        "max_sessions": 1, "max_subscriptions": 1, "max_rest_requests": 2,
        "session_timeout_seconds": 180, "connect_timeout_seconds": 30,
        "rest_timeout_seconds": 30, "second_rest_after_first_start_seconds": 60,
        "min_rest_spacing_ms": 1100, "retry_count": 0, "redirects": False,
        "reconnect": False, "websocket_protocol_ping_interval": None,
        "runtime_dependencies": {"websockets": "16.0", "aiohttp": "3.13.5"},
        "first_rest": "IMMEDIATELY_AFTER_FIRST_VALID_CURRENT_OR_PREVIOUS_HOUR_WS_KLINE",
        "target": "FIRST_VALID_WS_OPEN_TIMESTAMP_FIXED_FOR_ENTIRE_SESSION",
        "second_rest": "ONLY_IF_NO_EXACT_MATCH_AT_FIRST_REST_START_PLUS_60_SECONDS",
        "rest_params": {"symbol": SYMBOL, "interval": "1h", "startTime": "WS_K_t",
                        "endTime": "WS_K_t_PLUS_HOUR_MINUS_1", "limit": 3},
        "rest_headers": dict(REQUEST_HEADERS), "hour_ms": HOUR_MS,
        "max_raw_frame_bytes": MAX_BYTES, "max_decompressed_frame_bytes": MAX_BYTES,
        "max_application_frames": 1000, "max_rest_raw_bytes": MAX_BYTES,
        "ws_binary_encoding": "GZIP_UTF8", "text_encoding": "UTF8",
        "application_ping": "Ping", "application_pong": "Pong",
        "subscription_ack": {"classification": "SUBSCRIPTION_ACK_OK",
            "id": "EXACT_CURRENT_SUBSCRIPTION_REQUEST_ID", "code": "INT_ZERO_NOT_BOOL",
            "msg": "STRING", "data": "ABSENT_OR_NULL", "dataType": "ABSENT_OR_EMPTY",
            "mixed_control_kline": "REJECT", "effect": "CONSUME_AND_CONTINUE_WAITING",
            "kline_first": "PRESERVE_V1_ALLOWED", "timeout_without_kline": "BLOCKED_WS_KLINE_TIMEOUT"},
        "identity": {"dataType": CHANNEL, "data.s": SYMBOL},
        "numeric_comparison": "EXACT_FINITE_DECIMAL_OHLC_NO_TOLERANCE",
        "volume": "RECORD_NONNEGATIVE_FINITE_DECIMAL_NOT_REQUIRED_FOR_OHLC_MATCH",
        "object_timestamp": "TIME_EQUALS_WS_K_t_AND_EXACT_OHLC",
        "object_canonical_close_delta_ms": HOUR_MS - 1,
        "object_native_ws_close_delta_ms": [HOUR_MS - 1, HOUR_MS],
        "array_timestamp": "POSITION_0_EQUALS_WS_K_t_AND_POSITION_6_EQUALS_WS_K_T_AND_EXACT_OHLC",
        "array_close_delta_ms": [HOUR_MS - 1, HOUR_MS],
        "allowed_rest_guard_open_offsets_ms": [-HOUR_MS, HOUR_MS],
        "timestamp_adjustment_ms": 0, "economics": 0, "outcome_independent": True,
        "fatal_errors_abort_remaining_requests": True,
    })


def validate_protocol(raw: bytes, authority_raw: bytes) -> dict:
    protocol = base._decode_json(raw)
    if canonical_bytes(protocol) != canonical_bytes(protocol_template(digest_bytes(authority_raw))):
        raise SourceIntegrityError("REST_WS_PROTOCOL_OR_AUTHORITY_CHANGED")
    authority = base._decode_json(authority_raw)
    try:
        assert authority["scope_key"] == SCOPE
        assert authority["status"] == "DOCUMENT_AUTHORITY_PINNED_NOT_A_LIVE_WITNESS"
        ws = authority["official_ws"]
        assert ws["endpoint"] == WS_ENDPOINT
        assert ws["kline_fields"]["data.K.t"] == "start timestamp in milliseconds"
        assert ws["kline_fields"]["data.K.T"] == "close timestamp in milliseconds"
        indices = authority["official_rest"]["array_field_indices"]
        assert indices["open_timestamp_ms"] == 0 and indices["close_timestamp_ms"] == 6
        assert authority["sources"] and all(s["exact_utf8_git_blob_match"] is True
            and s["path_at_commit_verified"] is True for s in authority["sources"])
    except (KeyError, TypeError, AssertionError) as exc:
        raise SourceIntegrityError("REST_WS_OFFICIAL_AUTHORITY_INCOMPLETE") from exc
    return protocol


def timestamp(value) -> int:
    if type(value) is int and value >= 0:
        return value
    if isinstance(value, str) and value.isascii() and value.isdecimal() and str(int(value)) == value:
        return int(value)
    raise SourceIntegrityError("REST_WS_TIMESTAMP_TYPE")


def number(value, *, volume=False) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise SourceIntegrityError("REST_WS_NUMERIC_TYPE")
    try:
        value = Decimal(value)
    except InvalidOperation as exc:
        raise SourceIntegrityError("REST_WS_NUMERIC_INVALID") from exc
    if not value.is_finite() or (value < 0 if volume else value <= 0):
        raise SourceIntegrityError("REST_WS_NUMERIC_RANGE")
    return format(value, "f")


def candle(opened, closed, values, volume, schema) -> dict:
    opened, closed = timestamp(opened), None if closed is None else timestamp(closed)
    vals = dict(zip(("open", "high", "low", "close"), (number(v) for v in values)))
    dec = {k: Decimal(v) for k, v in vals.items()}
    if dec["high"] < max(dec.values()) or dec["low"] > min(dec.values()):
        raise SourceIntegrityError("REST_WS_OHLC_RANGE")
    return {"schema": schema, "open_ms": opened, "close_ms": closed,
            "ohlc": vals, "volume": number(volume, volume=True)}


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SourceIntegrityError("REST_WS_DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def safe_error(exc):
    # Exception messages may contain environment proxy URLs or credentials.
    if isinstance(exc, SourceIntegrityError):
        text = str(exc)
        if text.replace("_", "").replace(":", "").isalnum():
            return text
    return type(exc).__name__


def decode_ws(raw: bytes, binary: bool, *, expected_request_id: str | None = None) -> dict:
    expected_request_id = SESSION_ID if expected_request_id is None else expected_request_id
    if len(raw) > MAX_BYTES:
        raise SourceIntegrityError("REST_WS_FRAME_LIMIT")
    if binary:
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
                decoded = stream.read(MAX_BYTES + 1)
        except (OSError, EOFError) as exc:
            raise SourceIntegrityError("REST_WS_GZIP") from exc
    else:
        decoded = raw
    if len(decoded) > MAX_BYTES:
        raise SourceIntegrityError("REST_WS_DECOMPRESSED_LIMIT")
    try:
        message = decoded.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SourceIntegrityError("REST_WS_UTF8") from exc
    if message == "Ping":
        return {"kind": "ping"}
    try:
        payload = json.loads(message, parse_float=Decimal, object_pairs_hook=unique_object)
    except (ValueError, TypeError) as exc:
        raise SourceIntegrityError("REST_WS_JSON") from exc
    if not isinstance(payload, dict):
        raise SourceIntegrityError("REST_WS_ENVELOPE")
    # Control envelopes are decided before market-channel validation. In
    # particular, the immutable PR1281 wire ACK contains an explicit data:null.
    if ("id" in payload or (payload.get("dataType", "") == ""
            and any(key in payload for key in ("code", "msg")))):
        if payload.get("id") != expected_request_id:
            raise SourceIntegrityError("REST_WS_ACK_ID_MISMATCH")
        if type(payload.get("code")) is not int or payload["code"] != 0:
            raise SourceIntegrityError("REST_WS_ACK_CODE")
        if not isinstance(payload.get("msg"), str):
            raise SourceIntegrityError("REST_WS_ACK_MSG")
        if payload.get("data") is not None:
            raise SourceIntegrityError("REST_WS_ACK_NON_NULL_DATA")
        if "dataType" in payload and payload["dataType"] != "":
            raise SourceIntegrityError("REST_WS_ACK_DATATYPE")
        if set(payload) - {"id", "code", "msg", "data", "dataType"}:
            raise SourceIntegrityError("REST_WS_ACK_MIXED_OR_UNKNOWN_FIELDS")
        return {"kind": "ack", "classification": "SUBSCRIPTION_ACK_OK",
                "subscription_request_id": expected_request_id,
                "data_form": "NULL" if "data" in payload else "ABSENT",
                "data_type_form": "EMPTY" if "dataType" in payload else "ABSENT"}
    if payload.get("dataType") != CHANNEL:
        raise SourceIntegrityError("REST_WS_CHANNEL_IDENTITY")
    data = payload.get("data")
    if not isinstance(data, dict) or data.get("s") != SYMBOL:
        raise SourceIntegrityError("REST_WS_SYMBOL_IDENTITY")
    k = data.get("K")
    if not isinstance(k, dict) or any(name not in k for name in ("t", "T", "o", "h", "l", "c", "v")):
        raise SourceIntegrityError("REST_WS_EXPLICIT_KLINE_FIELDS")
    row = candle(k["t"], k["T"], [k[n] for n in ("o", "h", "l", "c")], k["v"], "ws")
    if row["open_ms"] % HOUR_MS or row["close_ms"] - row["open_ms"] not in (HOUR_MS - 1, HOUR_MS):
        raise SourceIntegrityError("REST_WS_CLOSE_CONVENTION")
    return {"kind": "kline", **row, "symbol": SYMBOL, "interval": "1h", "channel": CHANNEL}


def decode_rest(raw: bytes, target: int) -> list[dict]:
    if len(raw) > MAX_BYTES:
        raise SourceIntegrityError("REST_WS_REST_RESPONSE_LIMIT")
    try:
        payload = json.loads(raw, parse_float=Decimal, object_pairs_hook=unique_object)
    except (ValueError, UnicodeDecodeError) as exc:
        raise SourceIntegrityError("REST_WS_REST_JSON") from exc
    if (not isinstance(payload, dict) or type(payload.get("code")) is not int or payload["code"] != 0
            or not isinstance(payload.get("data"), list) or not 1 <= len(payload["data"]) <= 3):
        raise SourceIntegrityError("REST_WS_REST_ENVELOPE")
    result = []
    for item in payload["data"]:
        if isinstance(item, dict):
            if ("symbol" in item and item["symbol"] != SYMBOL) or ("interval" in item and item["interval"] != "1h"):
                raise SourceIntegrityError("REST_WS_REST_EXPLICIT_IDENTITY")
            if any(k not in item for k in ("open", "high", "low", "close", "volume", "time")):
                raise SourceIntegrityError("REST_WS_REST_OBJECT_FIELDS")
            if any(k in item for k in ("timestamp", "openTime", "closeTime", "open_time", "close_time")):
                raise SourceIntegrityError("REST_WS_REST_TIMESTAMP_ALIAS")
            row = candle(item["time"], None, [item[k] for k in ("open", "high", "low", "close")], item["volume"], "object")
        elif isinstance(item, list) and len(item) >= 7:
            row = candle(item[0], item[6], item[1:5], item[5], "array")
            if row["close_ms"] - row["open_ms"] not in (HOUR_MS - 1, HOUR_MS):
                raise SourceIntegrityError("REST_WS_REST_ARRAY_CLOSE")
        else:
            raise SourceIntegrityError("REST_WS_REST_ROW_SHAPE")
        if row["open_ms"] not in (target - HOUR_MS, target, target + HOUR_MS) or row["open_ms"] % HOUR_MS:
            raise SourceIntegrityError("REST_WS_REST_OPEN_GRID_OR_CLOSE_TIME")
        result.append(row)
    if len({r["schema"] for r in result}) != 1 or len({r["open_ms"] for r in result}) != len(result):
        raise SourceIntegrityError("REST_WS_REST_MIXED_OR_DUPLICATE")
    if sum(r["open_ms"] == target for r in result) != 1:
        raise SourceIntegrityError("REST_WS_REST_TARGET_NOT_EXACTLY_ONCE")
    return result


def exact_match(rest: Mapping, ws: Mapping) -> bool:
    if (ws.get("kind") != "kline" or ws.get("symbol") != SYMBOL or ws.get("interval") != "1h"
            or ws.get("channel") != CHANNEL or rest["open_ms"] != ws["open_ms"]):
        return False
    if any(Decimal(rest["ohlc"][k]) != Decimal(ws["ohlc"][k]) for k in ("open", "high", "low", "close")):
        return False
    if rest["schema"] == "object":
        return ws["close_ms"] - ws["open_ms"] in (HOUR_MS - 1, HOUR_MS)
    return rest["schema"] == "array" and rest["close_ms"] == ws["close_ms"]


def header_pairs(headers):
    return list(headers.raw_items()) if hasattr(headers, "raw_items") else list(headers.items())


class PartialRESTFailure(SourceIntegrityError):
    def __init__(self, response, cause):
        super().__init__("REST_WS_PARTIAL_RESPONSE:" + type(cause).__name__)
        self.response = response


async def live_rest(params):
    import aiohttp
    if aiohttp.__version__ != "3.13.5":
        raise SourceIntegrityError("REST_WS_AIOHTTP_VERSION")
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30),
            headers=dict(REQUEST_HEADERS), auto_decompress=False,
            skip_auto_headers={"User-Agent", "Accept-Encoding", "Accept"},
            trust_env=True, connector=aiohttp.TCPConnector(force_close=True)) as session:
        # Version pinned above: prevent internal idempotent reconnect retry.
        session._retry_connection = False
        async with session.get(REST_ENDPOINT, params=params, allow_redirects=False) as response:
            chunks = bytearray()
            try:
                async for chunk in response.content.iter_chunked(65536):
                    chunks.extend(chunk[:MAX_BYTES + 1 - len(chunks)])
                    if len(chunks) > MAX_BYTES:
                        break
            except (Exception, asyncio.CancelledError) as exc:
                raise PartialRESTFailure(base.Response(response.status, dict(response.headers), bytes(chunks)), exc) from None
            return base.Response(response.status, dict(response.headers), bytes(chunks))


async def live_connect():
    import websockets
    if websockets.__version__ != "16.0":
        raise SourceIntegrityError("REST_WS_WEBSOCKETS_VERSION")
    from websockets.asyncio.client import connect
    class NoRedirectConnect(connect):
        def process_redirect(self, exc):
            return exc
    # Direct await performs one connection; never use reconnecting async iterator.
    return await NoRedirectConnect(WS_ENDPOINT, open_timeout=30, close_timeout=2,
                                   ping_interval=None, compression=None, max_size=MAX_BYTES,
                                   max_queue=1000)


class Clock:
    def monotonic(self):
        return time.monotonic()
    def wall_ms(self):
        return time.time_ns() // 1_000_000
    async def sleep(self, delay):
        await asyncio.sleep(delay)


def rest_params(target):
    return {"symbol": SYMBOL, "interval": "1h", "startTime": target,
            "endTime": target + HOUR_MS - 1, "limit": 3}


def ack_decision(row, meta):
    """A saved prefix decision depends only on this raw frame and request id."""
    return {"session_id": SESSION_ID, "ordinal": meta["ordinal"],
            "received_at_ms": meta["received_at_ms"], "raw_path": meta["raw_path"],
            "raw_sha256": meta["raw_sha256"], "decision": dict(row)}


async def run_calibration(output_dir, protocol_path, authority_path, *, connect=None,
                          rest=None, clock=None) -> dict:
    """Consume one session. Every failure is terminal; there is no resume path."""
    output, protocol_path, authority_path = map(Path, (output_dir, protocol_path, authority_path))
    protocol_raw, authority_raw = protocol_path.read_bytes(), authority_path.read_bytes()
    validate_protocol(protocol_raw, authority_raw)
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise SourceIntegrityError("REST_WS_OUTPUT_NONEMPTY_NO_RESUME")
    clock, connect_fn, rest_fn = clock or Clock(), connect or live_connect, rest or live_rest
    started_ms, started = clock.wall_ms(), clock.monotonic()
    deadline = started + 180
    def unchanged():
        if protocol_path.read_bytes() != protocol_raw or authority_path.read_bytes() != authority_raw:
            raise SourceIntegrityError("REST_WS_FROZEN_INPUT_CHANGED")
    def save(name, value):
        write_once(output / name, canonical_bytes(sealed(value)))
    save("CALIBRATION_ATTEMPT_STARTED.json", {"scope_key": SCOPE, "session_id": SESSION_ID,
        "attempt_ordinal": 1, "started_at_ms": started_ms, "protocol_sha256": digest_bytes(protocol_raw),
        "authority_sha256": digest_bytes(authority_raw), "retry_count": 0})
    write_once(output / "PROBE_PROTOCOL.json", protocol_raw)
    write_once(output / "OFFICIAL_SCHEMA_AUTHORITY.json", authority_raw)
    ws = None
    receiver = pending_rest = None
    observations, rest_observations, ack_chronology = [], [], []
    counts = {"ws_sessions": 0, "ws_subscriptions": 0, "rest_requests": 0,
              "ws_application_frames": 0, "application_pings": 0, "application_pongs": 0,
              "subscription_acks": 0}
    errors = []
    changed = asyncio.Event()
    target = None
    matched = None
    first_rest_start = None
    fatal = None
    async def receive():
        nonlocal target, fatal
        try:
            while clock.monotonic() < deadline:
                message = await ws.recv()
                counts["ws_application_frames"] += 1
                ordinal = counts["ws_application_frames"]
                if ordinal > 1000:
                    raise SourceIntegrityError("REST_WS_FRAME_COUNT_LIMIT")
                binary = isinstance(message, bytes)
                if not binary and not isinstance(message, str):
                    raise SourceIntegrityError("REST_WS_WIRE_TYPE")
                raw = message if binary else message.encode("utf-8")
                stem = f"raw/ws_{ordinal:04d}"
                meta = {"session_id": SESSION_ID, "ordinal": ordinal, "binary": binary,
                        "received_at_ms": clock.wall_ms(), "raw_path": stem + ".bin",
                        "raw_sha256": digest_bytes(raw), "raw_bytes": len(raw)}
                write_once(output / (stem + ".bin"), raw)
                save(stem + ".meta.json", meta)
                try:
                    row = decode_ws(raw, binary)  # Both raw and metadata exist first.
                except SourceIntegrityError as exc:
                    if str(exc).startswith("REST_WS_ACK_"):
                        save(stem + ".ack_rejected.json", ack_decision(
                            {"kind": "ack_rejected", "classification": safe_error(exc)}, meta))
                    raise
                if row["kind"] == "ping":
                    counts["application_pings"] += 1
                    unchanged()
                    save(f"raw/pong_{counts['application_pings']:04d}.json", {
                        "session_id": SESSION_ID, "payload": "Pong", "sent_at_ms": clock.wall_ms(),
                        "in_reply_to_raw_sha256": meta["raw_sha256"]})
                    counts["application_pongs"] += 1
                    await ws.send("Pong")
                elif row["kind"] == "ack":
                    decision_path = stem + ".ack.json"
                    save(decision_path, ack_decision(row, meta))
                    counts["subscription_acks"] += 1
                    ack_chronology.append({"ordinal": ordinal,
                        "classification": row["classification"], "raw_path": meta["raw_path"],
                        "raw_sha256": meta["raw_sha256"], "decision_path": decision_path})
                elif row["kind"] == "kline":
                    if target is None:
                        now_hour = meta["received_at_ms"] // HOUR_MS * HOUR_MS
                        if row["open_ms"] not in (now_hour, now_hour - HOUR_MS):
                            raise SourceIntegrityError("REST_WS_NOT_CURRENT_OR_PREVIOUS_HOUR")
                        target = row["open_ms"]
                    observations.append({"candle": row, "raw_path": meta["raw_path"],
                        "raw_sha256": meta["raw_sha256"], "meta_path": stem + ".meta.json"})
                changed.set()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            fatal = "WS_RECEIVE:" + safe_error(exc)
            changed.set()
    async def fetch_rest():
        nonlocal first_rest_start
        ordinal = counts["rest_requests"] + 1
        if ordinal > 2:
            raise SourceIntegrityError("REST_WS_REST_BUDGET")
        if first_rest_start is not None:
            await clock.sleep(max(0, first_rest_start + 1.1 - clock.monotonic()))
        unchanged()  # Check after all spacing and immediately before reservation.
        params = rest_params(target)
        stem = f"raw/rest_{ordinal}"
        now = clock.monotonic()
        if ordinal == 1:
            first_rest_start = now
        request = {"session_id": SESSION_ID, "ordinal": ordinal, "method": "GET",
            "endpoint": REST_ENDPOINT, "params": params, "headers": dict(REQUEST_HEADERS),
            "requested_at_ms": clock.wall_ms(), "target_open_ms": target, "retry_count": 0}
        save(stem + ".request.json", request)
        counts["rest_requests"] = ordinal  # Persist request count before actual I/O.
        partial_failure = None
        try:
            response = await rest_fn(params)
        except PartialRESTFailure as exc:
            response = exc.response
            partial_failure = safe_error(exc)
        except Exception as exc:
            save(stem + ".failure.json", {"session_id": SESSION_ID,
                "error_type": type(exc).__name__, "error": safe_error(exc), "retry_count": 0})
            raise
        write_once(output / (stem + ".bin"), response.body)
        meta = {"session_id": SESSION_ID, "ordinal": ordinal, "status": response.status,
            "headers": dict(response.headers), "received_at_ms": clock.wall_ms(),
            "raw_path": stem + ".bin", "raw_sha256": digest_bytes(response.body),
            "raw_bytes": len(response.body), "request_path": stem + ".request.json",
            "body_read_complete": partial_failure is None, "partial_failure": partial_failure}
        save(stem + ".response.json", meta)
        if partial_failure:
            raise SourceIntegrityError(partial_failure)
        if response.status != 200:
            raise SourceIntegrityError("REST_WS_HTTP_STATUS")
        rows = decode_rest(response.body, target)  # Raw + status saved before decode.
        return {"rows": rows, "meta": meta, "meta_path": stem + ".response.json"}
    def find_match():
        for response in rest_observations:
            for row in response["rows"]:
                if row["open_ms"] != target:
                    continue
                for frame in observations:
                    if frame["candle"]["open_ms"] == target and exact_match(row, frame["candle"]):
                        return row, response, frame
        return None
    try:
        unchanged()
        save("WS_CONNECT_REQUEST.json", {"session_id": SESSION_ID, "endpoint": WS_ENDPOINT,
            "attempt_ordinal": 1, "requested_at_ms": clock.wall_ms(), "redirects": False,
            "reconnect": False, "retry_count": 0})
        counts["ws_sessions"] = 1
        ws = await asyncio.wait_for(connect_fn(), timeout=30)
        response = getattr(ws, "response", None)
        save("WS_HANDSHAKE_RESPONSE.json", {"session_id": SESSION_ID,
            "status": getattr(response, "status_code", 101),
            "headers": header_pairs(getattr(response, "headers", {})), "received_at_ms": clock.wall_ms()})
        unchanged()
        save("WS_SUBSCRIBE_REQUEST.json", {"session_id": SESSION_ID,
            "sent_at_ms": clock.wall_ms(), "payload": protocol_template("unused")["subscription"]})
        counts["ws_subscriptions"] = 1
        await ws.send(json.dumps(protocol_template("unused")["subscription"], separators=(",", ":")))
        receiver = asyncio.create_task(receive())
        while clock.monotonic() < deadline:
            if fatal:
                raise SourceIntegrityError(fatal)
            if pending_rest is not None and pending_rest.done():
                rest_observations.append(pending_rest.result())
                pending_rest = None
            matched = find_match()
            if matched:
                break
            now = clock.monotonic()
            if target is not None and pending_rest is None:
                if counts["rest_requests"] == 0 or (counts["rest_requests"] == 1
                        and now >= first_rest_start + 60):
                    # Do not dispatch a 30-second request beyond the one-session deadline.
                    if deadline - now >= 30:
                        pending_rest = asyncio.create_task(fetch_rest())
            changed.clear()
            wake = asyncio.create_task(changed.wait())
            timer = asyncio.create_task(clock.sleep(min(0.05, max(0, deadline - clock.monotonic()))))
            await asyncio.wait([wake, timer] + ([pending_rest] if pending_rest else []),
                               return_when=asyncio.FIRST_COMPLETED)
            for task in (wake, timer):
                if not task.done():
                    task.cancel()
            await asyncio.gather(wake, timer, return_exceptions=True)
        unchanged()
        if not matched:
            errors.append("BLOCKED_WS_KLINE_TIMEOUT" if target is None else
                          "NO_EXACT_REST_WS_TIMESTAMP_OHLC_WITNESS")
    except Exception as exc:
        errors.append(safe_error(exc))
        if ws is None:
            response = getattr(exc, "response", None)
            body = getattr(response, "body", b"") or b""
            write_once(output / "WS_HANDSHAKE_FAILURE.bin", bytes(body))
            save("WS_HANDSHAKE_FAILURE.json", {"session_id": SESSION_ID,
                "error_type": type(exc).__name__, "error": safe_error(exc),
                "status": getattr(response, "status_code", None),
                "headers": header_pairs(getattr(response, "headers", {})),
                "raw_sha256": digest_bytes(bytes(body)), "raw_bytes": len(body)})
    finally:
        if receiver is not None and not receiver.done():
            receiver.cancel()
        if receiver is not None:
            await asyncio.gather(receiver, return_exceptions=True)
        if pending_rest is not None:
            # A dispatched HTTP call must finish and archive its response even
            # when the WS lane fails; never abandon an uncancellable thread.
            try:
                if pending_rest.done():
                    pending_rest.result()
                else:
                    await asyncio.wait_for(pending_rest, max(0.001, deadline - clock.monotonic()))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                errors.append("REST_FINALIZE:" + safe_error(exc))
        if ws is not None:
            remaining = deadline - clock.monotonic()
            try:
                if remaining > 0:
                    await asyncio.wait_for(ws.close(), timeout=min(2, remaining))
                elif getattr(ws, "transport", None) is not None:
                    ws.transport.abort()
            except Exception as exc:
                if getattr(ws, "transport", None) is not None:
                    ws.transport.abort()
                errors.append("WS_CLOSE:" + safe_error(exc))
        try:
            unchanged()
        except Exception as exc:
            errors.append(safe_error(exc))
    witness = None
    if matched and not errors:
        row, response, frame = matched
        witness = {"rest_schema": row["schema"], "ws_open_ms": frame["candle"]["open_ms"],
            "ws_close_ms": frame["candle"]["close_ms"], "rest_timestamp_ms": row["open_ms"],
            "rest_close_ms": row["close_ms"], "ohlc_exact_match": True,
            "rest_ohlc": row["ohlc"], "ws_ohlc": frame["candle"]["ohlc"],
            "rest_volume": row["volume"], "ws_volume": frame["candle"]["volume"],
            "volume_exact_match": Decimal(row["volume"]) == Decimal(frame["candle"]["volume"]),
            "ws_raw_path": frame["raw_path"], "ws_raw_sha256": frame["raw_sha256"],
            "ws_meta_path": frame["meta_path"], "rest_raw_path": response["meta"]["raw_path"],
            "rest_raw_sha256": response["meta"]["raw_sha256"],
            "rest_meta_path": response["meta_path"], "rest_request_path": response["meta"]["request_path"]}
    state = ("PASS" if witness is not None else "BLOCKED_WS_KLINE_TIMEOUT"
             if errors == ["BLOCKED_WS_KLINE_TIMEOUT"] else "BLOCKED_REST_WS_TIMESTAMP_WITNESS")
    artifact_sha = {p.relative_to(output).as_posix(): digest_bytes(p.read_bytes())
                    for p in sorted(output.rglob("*")) if p.is_file()}
    result = sealed({"schema": RECEIPT_SCHEMA, "scope_key": SCOPE, "state": state,
        "session_id": SESSION_ID, "symbol": SYMBOL, "interval": "1h", "hour_ms": HOUR_MS,
        "started_at_ms": started_ms, "finished_at_ms": clock.wall_ms(),
        "duration_seconds": round(clock.monotonic() - started, 6), "counts": counts,
        "actual_ws_sessions": counts["ws_sessions"], "actual_ws_subscriptions": counts["ws_subscriptions"],
        "actual_rest_requests": counts["rest_requests"], "retry_count": 0,
        "timestamp_adjustment_ms": 0, "outcome_independent": True,
        "economic_executions": 0, "source_acquisition_authorized": state == "PASS",
        "authority_sha256": digest_bytes(authority_raw), "protocol_sha256": digest_bytes(protocol_raw),
        "supported_canonical_lane": ("OBJECT_TIME_OPEN" if witness["rest_schema"] == "object" else "ARRAY_OPEN_CLOSE") if witness else None,
        "canonical_open_transform": ("IDENTITY_NATIVE_OBJECT_TIME_MS" if witness["rest_schema"] == "object" else "IDENTITY_NATIVE_ARRAY_OPEN_MS") if witness else None,
        "canonical_close_rule": ("OPEN_PLUS_HOUR_MINUS_1_MS" if witness["rest_schema"] == "object" else "IDENTITY_NATIVE_ARRAY_CLOSE_MS") if witness else None,
        "close_minus_open_ms": witness["ws_close_ms"] - witness["ws_open_ms"] if witness else None,
        "native_ws_close_delta_ms": witness["ws_close_ms"] - witness["ws_open_ms"] if witness else None,
        "canonical_close_delta_ms": (HOUR_MS - 1 if witness["rest_schema"] == "object" else witness["ws_close_ms"] - witness["ws_open_ms"]) if witness else None,
        "witness": witness, "ack_chronology": ack_chronology,
        "errors": errors, "artifact_sha256": artifact_sha})
    write_once(output / "REST_WS_TIMESTAMP_SEMANTIC_RECEIPT_V2.json", canonical_bytes(result))
    return result


def _artifact(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise SourceIntegrityError("REST_WS_ARTIFACT_PATH")
    path = root / relative
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        raise SourceIntegrityError("REST_WS_ARTIFACT_PATH")
    return path


def validate_semantic_receipt(receipt_path: str | Path, expected_sha256: str | None = None) -> dict:
    """Verify PASS and recompute its same-session witness from hash-bound raw files."""
    path = Path(receipt_path)
    raw = path.read_bytes()
    if expected_sha256 is not None and digest_bytes(raw) != expected_sha256:
        raise SourceIntegrityError("REST_WS_SEMANTIC_RECEIPT_HASH")
    receipt = base._decode_json(raw)
    check_seal(receipt)
    if (receipt.get("schema") != RECEIPT_SCHEMA or receipt.get("scope_key") != SCOPE
            or receipt.get("state") != "PASS" or receipt.get("errors") != []
            or receipt.get("source_acquisition_authorized") is not True
            or receipt.get("outcome_independent") is not True or receipt.get("timestamp_adjustment_ms") != 0
            or receipt.get("economic_executions") != 0 or receipt.get("retry_count") != 0):
        raise SourceIntegrityError("REST_WS_SEMANTIC_NOT_PASS")
    if receipt.get("session_id") != SESSION_ID or receipt.get("symbol") != SYMBOL or receipt.get("interval") != "1h" or receipt.get("hour_ms") != HOUR_MS:
        raise SourceIntegrityError("REST_WS_SEMANTIC_IDENTITY")
    counts = receipt.get("counts", {})
    if (counts.get("ws_sessions") != 1 or counts.get("ws_subscriptions") != 1
            or type(counts.get("rest_requests")) is not int or not 1 <= counts["rest_requests"] <= 2
            or receipt.get("actual_rest_requests") != counts["rest_requests"]):
        raise SourceIntegrityError("REST_WS_SEMANTIC_BUDGET")
    if (receipt.get("actual_ws_sessions") != 1 or receipt.get("actual_ws_subscriptions") != 1
            or not 0 <= receipt.get("duration_seconds", -1) <= 180
            or receipt.get("finished_at_ms", 0) < receipt.get("started_at_ms", 0)):
        raise SourceIntegrityError("REST_WS_SESSION_DURATION")
    root = path.parent
    mapping = receipt.get("artifact_sha256")
    if not isinstance(mapping, dict) or not mapping:
        raise SourceIntegrityError("REST_WS_ARTIFACT_MANIFEST")
    for relative, digest in mapping.items():
        if digest_bytes(_artifact(root, relative).read_bytes()) != digest:
            raise SourceIntegrityError("REST_WS_ARTIFACT_HASH:" + relative)
    def load(name):
        if name not in mapping:
            raise SourceIntegrityError("REST_WS_UNBOUND_ARTIFACT:" + name)
        return _artifact(root, name).read_bytes()
    validate_protocol(load("PROBE_PROTOCOL.json"), load("OFFICIAL_SCHEMA_AUTHORITY.json"))
    if receipt["protocol_sha256"] != digest_bytes(load("PROBE_PROTOCOL.json")) or receipt["authority_sha256"] != digest_bytes(load("OFFICIAL_SCHEMA_AUTHORITY.json")):
        raise SourceIntegrityError("REST_WS_AUTHORITY_BINDING")
    rest_requests = sorted(k for k in mapping if k.startswith("raw/rest_") and k.endswith(".request.json"))
    frame_meta = sorted(k for k in mapping if k.startswith("raw/ws_") and k.endswith(".meta.json"))
    if (len(rest_requests) != counts["rest_requests"] or len(frame_meta) != counts["ws_application_frames"]
            or counts["application_pongs"] != counts["application_pings"]):
        raise SourceIntegrityError("REST_WS_ARTIFACT_COUNTS")
    subscribe = base._decode_json(load("WS_SUBSCRIBE_REQUEST.json"))
    check_seal(subscribe)
    if subscribe.get("payload") != protocol_template("unused")["subscription"]:
        raise SourceIntegrityError("REST_WS_SUBSCRIPTION_BINDING")
    request_times = []
    for ordinal, name in enumerate(rest_requests, 1):
        req = base._decode_json(load(name))
        check_seal(req)
        if req.get("ordinal") != ordinal or req.get("session_id") != SESSION_ID:
            raise SourceIntegrityError("REST_WS_REQUEST_ORDINAL")
        request_times.append(timestamp(req["requested_at_ms"]))
    if len(request_times) == 2 and request_times[1] - request_times[0] < 60_000:
        raise SourceIntegrityError("REST_WS_SECOND_REQUEST_TOO_EARLY")
    first_kline = None
    recomputed_acks = []
    for name in frame_meta:
        meta = base._decode_json(load(name))
        check_seal(meta)
        if not receipt["started_at_ms"] <= meta["received_at_ms"] <= receipt["finished_at_ms"]:
            raise SourceIntegrityError("REST_WS_FRAME_OUTSIDE_SESSION")
        wire = load(meta["raw_path"])
        if digest_bytes(wire) != meta["raw_sha256"] or len(wire) != meta["raw_bytes"]:
            raise SourceIntegrityError("REST_WS_FRAME_RAW_BINDING")
        frame = decode_ws(wire, meta["binary"])
        if frame["kind"] == "ack":
            decision_path = name.removesuffix(".meta.json") + ".ack.json"
            decision_raw = load(decision_path)
            if decision_raw != canonical_bytes(sealed(ack_decision(frame, meta))):
                raise SourceIntegrityError("REST_WS_ACK_DECISION_BINDING")
            recomputed_acks.append({"ordinal": meta["ordinal"],
                "classification": frame["classification"], "raw_path": meta["raw_path"],
                "raw_sha256": meta["raw_sha256"], "decision_path": decision_path})
        if frame["kind"] == "kline" and first_kline is None:
            first_kline = (frame, meta)
    if (receipt.get("ack_chronology") != recomputed_acks
            or counts.get("subscription_acks") != len(recomputed_acks)):
        raise SourceIntegrityError("REST_WS_ACK_CHRONOLOGY_BINDING")
    if first_kline is None:
        raise SourceIntegrityError("REST_WS_FIRST_KLINE_MISSING")
    first_frame, first_meta = first_kline
    now_hour = first_meta["received_at_ms"] // HOUR_MS * HOUR_MS
    if first_frame["open_ms"] not in (now_hour, now_hour - HOUR_MS):
        raise SourceIntegrityError("REST_WS_FIRST_KLINE_NOT_CURRENT_OR_PREVIOUS")
    if request_times[0] < first_meta["received_at_ms"]:
        raise SourceIntegrityError("REST_WS_REST_PRECEDES_FIRST_KLINE")
    witness = receipt["witness"]
    wmeta = base._decode_json(load(witness["ws_meta_path"]))
    rmeta = base._decode_json(load(witness["rest_meta_path"]))
    request = base._decode_json(load(witness["rest_request_path"]))
    for item in (wmeta, rmeta, request):
        check_seal(item)
        if item.get("session_id") != SESSION_ID:
            raise SourceIntegrityError("REST_WS_SESSION_BINDING")
    wr, rr = load(witness["ws_raw_path"]), load(witness["rest_raw_path"])
    if (digest_bytes(wr) != witness["ws_raw_sha256"] or digest_bytes(rr) != witness["rest_raw_sha256"]
            or wmeta["raw_sha256"] != digest_bytes(wr) or rmeta["raw_sha256"] != digest_bytes(rr)
            or wmeta["raw_bytes"] != len(wr) or rmeta["raw_bytes"] != len(rr) or rmeta["status"] != 200
            or wmeta["raw_path"] != witness["ws_raw_path"] or rmeta["raw_path"] != witness["rest_raw_path"]
            or rmeta["request_path"] != witness["rest_request_path"]
            or rmeta.get("body_read_complete") is not True or rmeta.get("partial_failure") is not None):
        raise SourceIntegrityError("REST_WS_RAW_BINDING")
    wsrow = decode_ws(wr, wmeta["binary"])
    target = wsrow["open_ms"]
    if target != first_frame["open_ms"]:
        raise SourceIntegrityError("REST_WS_FROZEN_TARGET_CHANGED")
    for moment in (request["requested_at_ms"], rmeta["received_at_ms"], wmeta["received_at_ms"]):
        if not receipt["started_at_ms"] <= moment <= receipt["finished_at_ms"]:
            raise SourceIntegrityError("REST_WS_MATCH_OUTSIDE_SESSION")
    if rmeta["received_at_ms"] < request["requested_at_ms"]:
        raise SourceIntegrityError("REST_WS_RESPONSE_PRECEDES_REQUEST")
    if (request["params"] != rest_params(target) or request["headers"] != REQUEST_HEADERS
            or request["endpoint"] != REST_ENDPOINT or request["method"] != "GET"
            or request["target_open_ms"] != target):
        raise SourceIntegrityError("REST_WS_REQUEST_BINDING")
    rows = decode_rest(rr, target)
    matches = [r for r in rows if exact_match(r, wsrow)]
    if len(matches) != 1:
        raise SourceIntegrityError("REST_WS_WITNESS_RECOMPUTE_FAILED")
    row = matches[0]
    if (witness["rest_schema"] != row["schema"] or witness["ws_open_ms"] != target
            or witness["ws_close_ms"] != wsrow["close_ms"] or witness["rest_timestamp_ms"] != target
            or witness["rest_close_ms"] != row["close_ms"] or witness["ohlc_exact_match"] is not True
            or witness["rest_ohlc"] != row["ohlc"] or witness["ws_ohlc"] != wsrow["ohlc"]):
        raise SourceIntegrityError("REST_WS_WITNESS_FIELDS")
    object_lane = row["schema"] == "object"
    if (receipt["supported_canonical_lane"] != ("OBJECT_TIME_OPEN" if object_lane else "ARRAY_OPEN_CLOSE")
            or receipt["canonical_open_transform"] != ("IDENTITY_NATIVE_OBJECT_TIME_MS" if object_lane else "IDENTITY_NATIVE_ARRAY_OPEN_MS")
            or receipt["canonical_close_rule"] != ("OPEN_PLUS_HOUR_MINUS_1_MS" if object_lane else "IDENTITY_NATIVE_ARRAY_CLOSE_MS")):
        raise SourceIntegrityError("REST_WS_CANONICAL_RULE")
    delta = wsrow["close_ms"] - target
    if (receipt.get("native_ws_close_delta_ms") != delta or receipt.get("close_minus_open_ms") != delta
            or receipt.get("canonical_close_delta_ms") != (HOUR_MS - 1 if object_lane else delta)):
        raise SourceIntegrityError("REST_WS_CLOSE_RULE_BINDING")
    return receipt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--authority", required=True)
    args = parser.parse_args()
    result = asyncio.run(run_calibration(args.output, args.protocol, args.authority))
    print(json.dumps({"state": result["state"], "counts": result["counts"], "errors": result["errors"]}))


if __name__ == "__main__":
    main()
