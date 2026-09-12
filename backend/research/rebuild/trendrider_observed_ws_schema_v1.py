"""Decode the immutable PR1283 observed transport shape without inferring time.

The observed array's ``T`` remains ``native_T`` until an independent REST
semantic witness passes. Legacy ACK and documented nested candle semantics are
delegated to the immutable v2 decoder. This module performs no network or
economic work and has no frame history that could alter an earlier decision.
"""
from __future__ import annotations

from decimal import Decimal
import gzip
import io
import json
import zlib

from backend.research.rebuild import trendrider_rest_ws_timestamp_v2 as legacy

SourceIntegrityError = legacy.SourceIntegrityError
HOUR_MS, MAX_BYTES = legacy.HOUR_MS, legacy.MAX_BYTES
SYMBOL, CHANNEL, SESSION_ID = legacy.SYMBOL, legacy.CHANNEL, legacy.SESSION_ID
OBSERVED_SCHEMA = "observed_root_array_v1"


def _payload(raw: bytes, binary: bool) -> dict | None:
    if len(raw) > MAX_BYTES:
        raise SourceIntegrityError("REST_WS_FRAME_LIMIT")
    if binary:
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
                decoded = stream.read(MAX_BYTES + 1)
        except (OSError, EOFError, zlib.error) as exc:
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
        return None
    try:
        payload = json.loads(message, parse_float=Decimal,
                             object_pairs_hook=legacy.unique_object)
    except (ValueError, TypeError) as exc:
        raise SourceIntegrityError("REST_WS_JSON") from exc
    if not isinstance(payload, dict):
        raise SourceIntegrityError("REST_WS_ENVELOPE")
    return payload


def _observed_candle(item: dict) -> dict:
    required = {"o", "h", "l", "c", "v", "T"}
    if not isinstance(item, dict) or set(item) != required:
        raise SourceIntegrityError("OBSERVED_WS_EXPLICIT_KLINE_FIELDS")
    native_t = item["T"]
    if type(native_t) is not int or native_t < 0 or native_t % HOUR_MS:
        raise SourceIntegrityError("OBSERVED_WS_NATIVE_T_INTEGER_GRID")
    ohlc = {name: legacy.number(item[key]) for name, key in
            (("open", "o"), ("high", "h"), ("low", "l"), ("close", "c"))}
    numbers = {name: Decimal(value) for name, value in ohlc.items()}
    if (numbers["high"] < max(numbers.values())
            or numbers["low"] > min(numbers.values())):
        raise SourceIntegrityError("REST_WS_OHLC_RANGE")
    return {"native_T": native_t, "ohlc": ohlc,
            "volume": legacy.number(item["v"], volume=True)}


def decode_ws(raw: bytes, binary: bool, *, expected_request_id: str | None = None) -> dict:
    """Classify one complete frame; reject every mixed or partially invalid array.

    Observed results contain ``candles`` with unclassified ``native_T`` values,
    never ``open_ms`` or ``close_ms``. Documented nested frames retain the exact
    pre-existing v2 return value, including their explicit native open/close.
    """
    payload = _payload(raw, binary)
    # Every control candidate takes precisely the proven v2 ACK branch, even
    # when malformed data or a market channel accompanies a request id.
    if (payload is None or "id" in payload
            or (payload.get("dataType", "") == ""
                and any(key in payload for key in ("code", "msg")))):
        return legacy.decode_ws(raw, binary, expected_request_id=expected_request_id)
    if "s" not in payload and not isinstance(payload.get("data"), list):
        return legacy.decode_ws(raw, binary, expected_request_id=expected_request_id)
    if type(payload.get("code")) is not int or payload["code"] != 0:
        raise SourceIntegrityError("OBSERVED_WS_CODE")
    if payload.get("dataType") != CHANNEL:
        raise SourceIntegrityError("REST_WS_CHANNEL_IDENTITY")
    if payload.get("s") != SYMBOL:
        raise SourceIntegrityError("REST_WS_SYMBOL_IDENTITY")
    if set(payload) != {"code", "dataType", "s", "data"}:
        raise SourceIntegrityError("OBSERVED_WS_MIXED_OR_UNKNOWN_FIELDS")
    items = payload["data"]
    if not isinstance(items, list) or not items:
        raise SourceIntegrityError("OBSERVED_WS_NONEMPTY_DATA_ARRAY")
    candles = [_observed_candle(item) for item in items]
    if len({row["native_T"] for row in candles}) != len(candles):
        raise SourceIntegrityError("OBSERVED_WS_DUPLICATE_NATIVE_T")
    return {"kind": "kline", "schema": OBSERVED_SCHEMA, "symbol": SYMBOL,
            "interval": "1h", "channel": CHANNEL, "candles": candles}
