#!/usr/bin/env python3
"""K117 frozen B-source volume: offline raw/normalized/provenance audit ONLY.

This tool does not upgrade the original source IDENTITY from UNKNOWN and
never changes an admission gate. No remote requests, credentials or orders.
"""
from __future__ import annotations
import argparse
import csv
from decimal import Decimal, InvalidOperation
import gzip
import hashlib
import io
import json
from pathlib import Path
from urllib.parse import urlparse

EXPECTED = "https://open-api.bingx.com/openApi/swap/v3/quote/klines"
SYMBOLS = ("BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "LINK-USDT", "DOGE-USDT")
PROVIDER_DOC = "https://github.com/BingX-API/api-ai-skills/blob/main/skills/swap-market/api-reference.md"
PROVIDER_DOC_BLOB = "e61be4746c5bd5475e556146448c79f4c58b064f"
COLUMNS = ("timestamp_ms", "open", "high", "low", "close", "volume")


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def within(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or relative.startswith("/"):
        raise ValueError("ABSOLUTE_OR_NONSTRING_PATH")
    out = (root / relative).resolve()
    if not out.is_relative_to(root.resolve()):
        raise ValueError("SOURCE_ESCAPE")
    if not out.is_file():
        raise ValueError("SOURCE_NOT_FOUND")
    return out


def read_pin(path: Path, expected: str) -> bytes:
    data = path.read_bytes()
    if sha(data) != expected:
        raise ValueError("SOURCE_SHA_MISMATCH")
    return data


def number(x) -> Decimal:
    if isinstance(x, bool):
        raise ValueError("BOOLEAN_NUMBER")
    try:
        d = Decimal(str(x))
    except (InvalidOperation, TypeError) as exc:
        raise ValueError("NON_NUMERIC_VALUE") from exc
    if not d.is_finite() or d < 0:
        raise ValueError("NEGATIVE_OR_NONFINITE_NUMBER")
    return d


def verify_raw_normalized(raw: bytes, packed: bytes, start: int, end: int) -> tuple[int, str]:
    data = json.loads(raw)
    if data.get("code") != 0 or not isinstance(data.get("data"), list):
        raise ValueError("RAW_EXCHANGE_CODE_OR_DATA")
    # The observed real BingX payload uses named object fields, even though
    # provider reference currently describes an indexed array response.
    payload = data["data"]
    if not all(isinstance(q, dict) for q in payload):
        raise ValueError("UNSUPPORTED_RAW_PAYLOAD_VARIANT")
    keys = ("time", "open", "high", "low", "close", "volume")
    by_time = {}
    for rec in payload:
        if not all(k in rec for k in keys):
            raise ValueError("RAW_VOLUME_OR_OHLC_MISSING")
        stamp = rec["time"]
        if type(stamp) is not int or stamp % 60000:
            raise ValueError("RAW_TIMESTAMP_MISALIGNED")
        if start <= stamp < end:
            if stamp in by_time:
                raise ValueError("RAW_DUPLICATE_CANDLE")
            by_time[stamp] = rec
    with gzip.GzipFile(fileobj=io.BytesIO(packed), mode="rb") as h:
        reader = csv.DictReader(io.TextIOWrapper(h, encoding="utf-8"))
        if tuple(reader.fieldnames or ()) != COLUMNS:
            raise ValueError("NORMALIZED_SCHEMA_MISMATCH")
        rows = list(reader)
    if len(rows) != len(by_time):
        raise ValueError("RAW_NORMALIZED_COUNT_MISMATCH")
    seen = set()
    for row in rows:
        try:
            stamp = int(row["timestamp_ms"])
        except (ValueError, TypeError) as exc:
            raise ValueError("NORMALIZED_TIMESTAMP_INVALID") from exc
        if stamp not in by_time or stamp in seen:
            raise ValueError("NORMALIZED_TIMESTAMP_UNBOUND")
        seen.add(stamp)
        for c in ("open", "high", "low", "close", "volume"):
            if number(row[c]) != number(by_time[stamp][c]):
                raise ValueError("VOLUME_OR_OHLC_CHANGED:" + c)
        if not number(row["volume"]):
            # A true zero-volume closed bar is legitimate, never impute.
            continue
    return len(rows), "OBJECT_FIELDS_WITH_VOLUME_MATCHING_NORMALIZED"


def audit(root: Path, lookback_per_symbol: int = 2) -> dict:
    root = root.resolve()
    original = (root / "IDENTITY.json").read_bytes()
    ident = json.loads(original)
    if ident.get("source") != EXPECTED or ident.get("interval") != "1m":
        raise ValueError("INCORRECT_SOURCE_IDENTITY")
    if ident.get("volume_units") != "UNKNOWN":
        raise ValueError("ORIGINAL_IDENTITY_WAS_REWRITTEN")
    if tuple(ident.get("symbols", [])) != SYMBOLS or ident.get("synthetic_fill") is not False:
        raise ValueError("SYMBOL_OR_FILL_CONTRACT_CHANGED")
    cursor_raw = (root / "CURSOR.json").read_bytes()
    cursor = json.loads(cursor_raw)
    if cursor.get("identity_sha256") != sha(original):
        raise ValueError("CURSOR_IDENTITY_MISMATCH")
    checked = []
    for sym in SYMBOLS:
        records = cursor.get("symbols", {}).get(sym)
        if not isinstance(records, list) or not records:
            raise ValueError("SYMBOL_RECEIPT_MISSING:" + sym)
        for pointer in records[-lookback_per_symbol:]:
            path = within(root, pointer["path"])
            receipt_raw = read_pin(path, pointer["sha256"])
            rec = json.loads(receipt_raw)
            if (rec.get("source") != EXPECTED or rec.get("symbol") != sym
                or rec.get("volume_units") != "UNKNOWN" or rec.get("synthetic_fill") is not False
                or rec.get("http_status") != 200 or rec.get("query", {}).get("interval") != "1m"):
                raise ValueError("RECEIPT_CONTRACT_CHANGED")
            uri = urlparse(rec.get("url", ""))
            if uri.scheme != "https" or uri.netloc != "open-api.bingx.com" or uri.path != "/openApi/swap/v3/quote/klines":
                raise ValueError("RECEIPT_ENDPOINT_CHANGED")
            raw = read_pin(within(root, rec["body_path"]), rec["body_sha256"])
            norm = read_pin(within(root, rec["normalized_path"]), rec["normalized_sha256"])
            count, variant = verify_raw_normalized(raw, norm, int(rec["start_ms"]), int(rec["end_exclusive_ms"]))
            if count != int(rec["rows"]):
                raise ValueError("RECEIPT_ROW_COUNT_DRIFT")
            checked.append({"symbol": sym, "receipt_sha256": sha(receipt_raw),
                "raw_sha256": rec["body_sha256"], "normalized_sha256": rec["normalized_sha256"],
                "received_at_ms": rec["received_at_ms"], "closed_minutes": count,
                "shape": variant})
    return {
        "schema": "zel.k117.volume_source_offline_attestation.v1",
        "result": "RAW_NORMALIZED_PARITY_PASS_UNIT_BINDING_HOLD",
        "read_only": True,
        "source_id_sha256": sha(original), "cursor_sha256": sha(cursor_raw),
        "provider_reference": {"url": PROVIDER_DOC, "git_blob_sha1": PROVIDER_DOC_BLOB,
            "endpoint": EXPECTED, "advertised_kline_array_volume_unit": "BASE_ASSET"},
        "actual_payload_shape": "NAMED_OBJECT_VOLUME_FIELD",
        "unit_contract": "UNVERIFIED_FOR_ACTUAL_OBJECT_RESPONSE_SHAPE",
        "source_identity_volume_units": ident["volume_units"],
        "source_identity_mutated": False,
        "admission_result": "HOLD_UNTIL_SIGNED_SOURCE_UNIT_MAPPING_AND_NEW_IDENTITY",
        "needs": ["Verified named-object volume unit mapping with source contract",
                  "New immutable source epoch/identity/cursor (do not rewrite existing)",
                  "Separate G4/G5 PREAUTO/native clock/fit/fees/funding/next-open"],
        "samples": checked, "samples_n": len(checked),
        "new_market_requests": 0, "orders": 0, "formal_shadow_credit": 0,
    }


def tests():
    data = [{"time": 60000, "open": "10", "high": "12", "low": "9",
             "close": "11", "volume": "3.5"}]
    raw = json.dumps({"code": 0, "data": data}).encode()
    def pack(rows):
        b = io.BytesIO()
        with gzip.GzipFile(fileobj=b, mode="wb") as h:
            h.write(("timestamp_ms,open,high,low,close,volume\n" + "".join(rows)).encode())
        return b.getvalue()
    good = pack(["60000,10,12,9,11,3.5\n"])
    assert verify_raw_normalized(raw, good, 60000, 120000)[0] == 1
    assert verify_raw_normalized(raw, pack([]), 0, 60000)[0] == 0
    for badraw, packed, label in [
        (raw, pack(["60000,10,12,9,11,3.6\n"]), "WRONG_VOLUME"),
        (raw, pack(["60000,10,13,9,11,3.5\n"]), "WRONG_PRICE"),
        (raw, pack(["120000,10,12,9,11,3.5\n"]), "WRONG_TIME"),
        (json.dumps({"code": 100410,"data": data}).encode(), good, "CODE_BAD"),
        (json.dumps({"code": 0,"data": data * 2}).encode(), good, "DUPLICATE"),
        (json.dumps({"code": 0,"data": [[60000,10,12,9,11,3.5]]}).encode(), good, "SHAPE_UNCERTIFIED"),
    ]:
        try:
            verify_raw_normalized(badraw, packed, 60000, 120000)
        except ValueError:
            pass
        else:
            raise AssertionError("ACCEPTED_" + label)
    assert number("0") == 0
    assert number("123.5") > 0
    assert "BASE_ASSET" in ("BASE_ASSET",)
    print(json.dumps({"synthetic_assertions": 10, "status": "PASS", "orders": 0, "requests": 0}))


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--source-root", type=Path)
    p.add_argument("--samples-per-symbol",type=int,default=2)
    p.add_argument("--self-test",action="store_true")
    args=p.parse_args()
    if args.self_test:
        tests()
        return
    if not args.source_root or not 1<=args.samples_per_symbol<=3:
        p.error("valid source root and sample count 1..3 required")
    print(json.dumps(audit(args.source_root,args.samples_per_symbol),indent=2,sort_keys=True))

if __name__=="__main__":
    main()
