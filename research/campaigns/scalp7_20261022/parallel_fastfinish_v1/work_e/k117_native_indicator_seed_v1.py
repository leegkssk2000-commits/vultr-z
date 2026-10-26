#!/usr/bin/env python3
"""Build one immutable, as-of B-source K117 OHLC context seed; NO trades/orders.

The 1m receipts are actual and immutable. Historical *availability* uses each
receipt's genuine received_at_ms, not a fabricated bar-close receipt time.
This seed cannot authorize any historical admission, cost, or formal Shadow.
"""
from __future__ import annotations
import argparse
import csv
from collections import defaultdict
from decimal import Decimal
import gzip
import hashlib
import json
import os
from pathlib import Path
import time

SYMBOLS = ("BTC-USDT","ETH-USDT","SOL-USDT","XRP-USDT","LINK-USDT","DOGE-USDT")
SOURCE = "https://open-api.bingx.com/openApi/swap/v3/quote/klines"
ORIGINAL_SHA = "f6306e27c39c0cb58930d18afbd99fbfabb42aa349a5cb82473389d707a995d0"
TF = 1_800_000
MINUTE = 60_000


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def encode(value) -> bytes:
    return (json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)+"\n").encode()


def secure(root: Path, name: str) -> Path:
    if not isinstance(name,str) or name.startswith("/"):
        raise ValueError("INVALID_RELATIVE_PATH")
    p=(root/name).resolve()
    if not p.is_relative_to(root.resolve()) or not p.is_file():
        raise ValueError("MISSING_OR_UNSAFE_SOURCE")
    return p


def read_price(text: str) -> Decimal:
    p=Decimal(text)
    if not p.is_finite() or p<=0:
        raise ValueError("BAD_PRICE")
    return p


def prices_to_bars(minutes: list[dict], asof: int) -> list[dict]:
    prev=None
    groups=defaultdict(list)
    for row in minutes:
        ts=row["timestamp_ms"]
        if type(ts) is not int or ts%MINUTE or (prev is not None and ts<=prev):
            raise ValueError("BAD_ORDER_OR_TIME")
        prev=ts
        if type(row["received_at_ms"]) is not int or row["received_at_ms"]<ts+MINUTE:
            raise ValueError("FAKE_RECEIPT_TIME")
        if row["received_at_ms"]>asof:
            raise ValueError("FUTURE_RECEIPT")
        o,h,l,c=[read_price(row[q]) for q in ("open","high","low","close")]
        if h<max(o,l,c) or l>min(o,h,c):
            raise ValueError("BAD_OHLC")
        groups[(ts//TF)*TF].append((ts,row["received_at_ms"],o,h,l,c))
    result=[]
    for opened in sorted(groups):
        g=groups[opened]
        if len(g)!=30 or g[0][0]!=opened or g[-1][0]!=opened+TF-MINUTE:
            continue  # Preserve gaps: incomplete bucket is NOT a bar.
        # All constituent minutes exactly occupy the 30m grid.
        if any(g[i][0] != opened+i*MINUTE for i in range(30)):
            continue
        result.append({"open_ts_ms":opened,"close_ts_ms":opened+TF,
            "available_ts_ms":max(opened+TF,max(x[1] for x in g)),
            "open":str(g[0][2]),"high":str(max(x[3] for x in g)),
            "low":str(min(x[4] for x in g)),"close":str(g[-1][5])})
    return result


def verify_append_only_cursor(before: dict, after: dict) -> bool:
    if before.get("identity_sha256") != after.get("identity_sha256"):
        raise ValueError("SOURCE_IDENTITY_CHANGED_DURING_CAPTURE")
    if set(before.get("symbols", {})) != set(after.get("symbols", {})):
        raise ValueError("SOURCE_SYMBOLS_CHANGED_DURING_CAPTURE")
    advanced = False
    for name, saved in before["symbols"].items():
        current = after["symbols"][name]
        if len(current) < len(saved) or current[:len(saved)] != saved:
            raise ValueError("SOURCE_CURSOR_NOT_APPEND_ONLY")
        if len(current) > len(saved):
            advanced = True
    return advanced


def extract_source(root: Path, asof: int) -> dict:
    ident_raw=(root/"IDENTITY.json").read_bytes()
    ident=json.loads(ident_raw)
    if sha(ident_raw)!=ORIGINAL_SHA or ident.get("volume_units")!="UNKNOWN" or ident.get("synthetic_fill") is not False:
        raise ValueError("FROZEN_SOURCE_IDENTITY_CHANGED")
    if ident.get("source")!=SOURCE or ident.get("interval")!="1m" or set(ident.get("symbols",[]))!=set(SYMBOLS):
        raise ValueError("FROZEN_SOURCE_SEMANTICS_CHANGED")
    cursor_raw=(root/"CURSOR.json").read_bytes()
    cursor=json.loads(cursor_raw)
    if cursor.get("identity_sha256")!=ORIGINAL_SHA or set(cursor.get("symbols",{}))!=set(SYMBOLS):
        raise ValueError("CURSOR_IDENTITY_CHANGED")
    frames={}
    for sym in SYMBOLS:
        chunks=cursor["symbols"][sym]
        if not chunks:
            raise ValueError("EMPTY_REAL_SOURCE")
        expected_start=ident["start_ms"]
        minrows=[]
        for entry in chunks:
            rec_raw=secure(root,entry["path"]).read_bytes()
            if sha(rec_raw)!=entry.get("sha256"):
                raise ValueError("RECEIPT_SHA_CHANGED")
            rec=json.loads(rec_raw)
            if (rec.get("source")!=SOURCE or rec.get("symbol")!=sym
                or rec.get("start_ms")!=expected_start or rec.get("http_status")!=200
                or rec.get("synthetic_fill") is not False or rec.get("volume_units")!="UNKNOWN"):
                raise ValueError("RECEIPT_SEMANTICS_DRIFT")
            if rec["received_at_ms"]>asof:
                raise ValueError("SOURCE_FUTURE_RECEIPT")
            # Both exact raw-body and normalized-file SHA are checked, with
            # the official original source collector as normalization owner.
            if sha(secure(root,rec["body_path"]).read_bytes())!=rec["body_sha256"]:
                raise ValueError("ORIGINAL_RAW_SHA_MISMATCH")
            packed=secure(root,rec["normalized_path"]).read_bytes()
            if sha(packed)!=rec["normalized_sha256"]:
                raise ValueError("ORIGINAL_NORMALIZED_SHA_MISMATCH")
            with gzip.GzipFile(fileobj=__import__("io").BytesIO(packed),mode="rb") as z:
                reader=csv.DictReader(__import__("io").TextIOWrapper(z,encoding="utf8"))
                if tuple(reader.fieldnames or ()) != ("timestamp_ms","open","high","low","close","volume"):
                    raise ValueError("NORMALIZED_SCHEMA_CHANGED")
                sample=list(reader)
            if len(sample)!=rec["rows"]:
                raise ValueError("NORMALIZED_RECORD_COUNT_CHANGED")
            actual={int(q["timestamp_ms"]) for q in sample}
            expected=set(range(rec["start_ms"],rec["end_exclusive_ms"],MINUTE))
            if actual != expected-set(rec["missing_minutes"]) or len(actual)!=len(sample):
                raise ValueError("MINUTE_GAP_OR_DUPLICATE_MISMATCH")
            for row in sample:
                row["timestamp_ms"]=int(row["timestamp_ms"])
                row["received_at_ms"]=int(rec["received_at_ms"])
            minrows.extend(sample)
            expected_start=rec["end_exclusive_ms"]
        bars=prices_to_bars(minrows,asof)
        if len(bars)<121:
            raise ValueError("INDICATOR_121_SOURCE_BARS_MISSING:"+sym)
        tail=bars[-121:]
        if any(tail[i]["close_ts_ms"]!=tail[i+1]["open_ts_ms"] for i in range(len(tail)-1)):
            raise ValueError("GAP_IN_LATEST_121_BARS:"+sym)
        frames[sym]=tail
    after_raw = (root/"CURSOR.json").read_bytes()
    advanced = verify_append_only_cursor(cursor, json.loads(after_raw))
    return {
        "cursor_append_only_advanced_during_capture": advanced,
        "source_cursor_after_capture_sha256": sha(after_raw),
        "schema":"k117.source_ohlc_indicator_seed.v1",
        "source_identity_sha256":ORIGINAL_SHA,
        "source_cursor_sha256":sha(cursor_raw),
        "source_volume_units":"UNKNOWN",
        "captured_at_ms":asof,
        "replay_makes_historical_trades":False,
        "fresh_trading_eligible_from_ms":asof,
        "formal_shadow_authority":False,
        "next_open_quote_available":False,
        "cost_funding_admission_verified":False,
        "orders":0,
        "market_requests":0,
        "frames":frames,
    }


def write_once(out_dir: Path, body: dict) -> dict:
    if out_dir.exists():
        raise ValueError("SEED_DESTINATION_ALREADY_EXISTS")
    out_dir.mkdir(parents=True,exist_ok=False)
    try:
        data=encode(body)
        for name,raw in (("CONTEXT_OHLC_ONLY.json",data),("MANIFEST.json",encode({
            "content_sha256":sha(data),"identity":body["source_identity_sha256"],
            "cursor_sha256":body["source_cursor_sha256"],"bar_count_by_symbol":{k:len(v) for k,v in body["frames"].items()},
            "source_ohlc_is_actual":True,"historical_position_admissions":0,
            "shadow_formal_pass":False,"orders":0,"unit_authority":"HOLD_UNKNOWN"}))):
            with (out_dir/name).open("xb") as f:
                f.write(raw);f.flush();os.fsync(f.fileno())
        dirfd=os.open(str(out_dir),os.O_RDONLY)
        try:os.fsync(dirfd)
        finally:os.close(dirfd)
        return {"sha256":sha(data),"output":str(out_dir),"symbol_bars":{k:len(v) for k,v in body["frames"].items()}}
    except Exception:
        # Never publish half a seed.
        for p in out_dir.iterdir():
            p.unlink()
        out_dir.rmdir()
        raise


def tests() -> None:
    seed=[{"timestamp_ms":i*MINUTE,"received_at_ms":i*MINUTE+MINUTE,
           "open":"10","high":"12","low":"9","close":"11"} for i in range(30)]
    z=prices_to_bars(seed,2*TF)
    assert len(z)==1 and z[0]["open_ts_ms"]==0
    assert z[0]["available_ts_ms"]==TF
    assert not prices_to_bars(seed[:-1],2*TF)
    assert not prices_to_bars(seed[:10]+seed[11:],2*TF)
    for bad in [dict(seed[0],timestamp_ms=1),dict(seed[0],received_at_ms=-1),
                dict(seed[0],high="8"),dict(seed[0],close="nan"),
                dict(seed[0],received_at_ms=3*TF)]:
        try:prices_to_bars([bad]+seed[1:],2*TF)
        except ValueError:pass
        else:raise AssertionError("BAD_SOURCE_ACCEPTED")
    x = {"identity_sha256":"a","symbols":{"BTC":[{"sha256":"a"}]}}
    y = {"identity_sha256":"a","symbols":{"BTC":[{"sha256":"a"},{"sha256":"b"}]}}
    assert verify_append_only_cursor(x, y) is True
    try:
        verify_append_only_cursor(x, {"identity_sha256":"a","symbols":{"BTC":[{"sha256":"X"}]}})
    except ValueError:
        pass
    else:
        raise AssertionError("SOURCE_HISTORY_REWRITE_ACCEPTED")
    assert SOURCE.startswith("https://")
    assert ORIGINAL_SHA and len(ORIGINAL_SHA)==64
    print(json.dumps({"self_tests":12,"result":"PASS","market_requests":0,"orders":0}))


def main() -> None:
    ap=argparse.ArgumentParser()
    ap.add_argument("--self-test",action="store_true")
    ap.add_argument("--source-root",type=Path)
    ap.add_argument("--out-dir",type=Path)
    args=ap.parse_args()
    if args.self_test:
        tests();return
    if not args.source_root or not args.out_dir:
        ap.error("source root + isolated new destination required")
    captured=int(time.time()*1000)
    body=extract_source(args.source_root,captured)
    result=write_once(args.out_dir,body)
    print(json.dumps({"status":"OHLC_CONTEXT_SEEDED_FORMAL_ADMISSION_HOLD",**result,
        "source_cursor_sha256":body["source_cursor_sha256"],
        "captured_at_ms":captured},sort_keys=True))


if __name__=="__main__":
    main()
