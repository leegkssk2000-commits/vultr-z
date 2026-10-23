#!/usr/bin/env python3
"""Offline B-native 1m -> 30m K117 indicator context readiness; NO signals/fills.

Verify original cursor+receipt chain from immutable source. This performs
no market HTTP calls, order calls, or mutations. Source volume is UNKNOWN
and cannot be promoted here. Open/entry history cannot be backfilled.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

SOURCE = "https://open-api.bingx.com/openApi/swap/v3/quote/klines"
SYMBOLS = ("BTC-USDT","ETH-USDT","SOL-USDT","XRP-USDT","LINK-USDT","DOGE-USDT")
MINUTE = 60_000
TF = 1_800_000
REQUIRED_BARS = 121
SCHEMA = "k117.original_source.ohlc_context_coverage.v1"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe(root: Path, relative: str) -> Path:
    if not isinstance(relative,str) or relative.startswith("/"):
        raise ValueError("INVALID_RELATIVE_PATH")
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root.resolve()):
        raise ValueError("PATH_ESCAPE")
    if not candidate.is_file():
        raise ValueError("MISSING_RECEIPT_FILE")
    return candidate


def to_30m(windows: list[dict], at_ms: int) -> dict:
    """Metadata receipt rows only; no OHLC/NAV/fill or synthetic as-of."""
    minutes: dict[int, int] = {}
    previous_end = None
    for r in windows:
        start,end = int(r["start_ms"]),int(r["end_exclusive_ms"])
        available=int(r["received_at_ms"])
        if start % MINUTE or end % MINUTE or end <= start:
            raise ValueError("BAD_REQUEST_WINDOW")
        if previous_end is not None and start != previous_end:
            raise ValueError("WINDOW_CHAIN_DISCONTINUITY")
        if available < end:
            raise ValueError("RECEIPT_BEFORE_WINDOW_FINISH")
        if available > at_ms:
            raise ValueError("FUTURE_RECEIPT_WAS_USED")
        miss = r.get("missing_minutes")
        if not isinstance(miss,list) or any(type(v)!=int or v < start or v >= end or v % MINUTE for v in miss) or len(set(miss)) != len(miss):
            raise ValueError("BAD_GAP_RECORD")
        for stamp in range(start,end,MINUTE):
            if stamp not in miss:
                if stamp in minutes:
                    raise ValueError("DUPLICATE_MINUTE")
                minutes[stamp] = available
        previous_end=end
    buckets=defaultdict(list)
    for ms,received in minutes.items():
        buckets[(ms//TF)*TF].append((ms,received))
    completed={}
    for opened,items in buckets.items():
        if len(items)==30 and min(ms for ms,_ in items)==opened and max(ms for ms,_ in items)==opened+TF-MINUTE:
            completed[opened]=max(opened+TF,max(received for _,received in items))
    if not completed:
        return {"complete_bars":0,"latest_contiguous_bars":0,"earliest_open_ms":None,"latest_open_ms":None,"last_complete_available_ts_ms":None,"native_121_indicator_prefix_ready":False}
    opens=sorted(completed)
    streak=1
    for prev,cur in zip(opens[-2::-1],opens[:0:-1]):
        if cur-prev!=TF:
            break
        streak+=1
    return {"complete_bars":len(opens),"latest_contiguous_bars":streak,"earliest_open_ms":opens[0],
        "latest_open_ms":opens[-1],"last_complete_available_ts_ms":completed[opens[-1]],
        "native_121_indicator_prefix_ready":streak>=REQUIRED_BARS}


def inspect_source(root: Path, at_ms: int, expected_b_source_id: str | None=None) -> dict:
    raw=(root/"IDENTITY.json").read_bytes()
    identity=json.loads(raw)
    identity_sha=sha(raw)
    if identity.get("source")!=SOURCE or identity.get("interval")!="1m" or identity.get("timeZone") != 0:
        raise ValueError("SOURCE_IDENTITY_MISMATCH")
    if identity.get("volume_units")!="UNKNOWN" or identity.get("synthetic_fill") is not False:
        raise ValueError("ORIGINAL_SOURCE_IDENTITY_MUTATED")
    if set(identity.get("symbols",[]))!=set(SYMBOLS):
        raise ValueError("WRONG_SYMBOL_SET")
    if expected_b_source_id is not None and identity_sha != expected_b_source_id:
        raise ValueError("IDENTITY_SHA_CHANGED")
    before=(root/"CURSOR.json").read_bytes()
    cursor=json.loads(before)
    if cursor.get("identity_sha256") != identity_sha or set(cursor.get("symbols",{})) != set(SYMBOLS):
        raise ValueError("CURSOR_IDENTITY_OR_SYMBOLS_CHANGED")
    lanes={}
    for symbol in SYMBOLS:
        records=cursor["symbols"][symbol]
        if not isinstance(records,list) or not records:
            raise ValueError("EMPTY_RECEIPT_STREAM")
        windows=[]
        for entry in records:
            receipt_raw=safe(root,entry["path"]).read_bytes()
            if sha(receipt_raw)!=entry.get("sha256"):
                raise ValueError("RECEIPT_SHA_MISMATCH")
            r=json.loads(receipt_raw)
            if (r.get("symbol")!=symbol or r.get("source")!=SOURCE or r.get("http_status")!=200
                or r.get("synthetic_fill") is not False or r.get("volume_units")!="UNKNOWN"
                or r.get("query",{}).get("interval")!="1m" or not r.get("body_sha256") or not r.get("normalized_sha256")):
                raise ValueError("INCONSISTENT_RECEIPT_SOURCE")
            windows.append(r)
        lane=to_30m(windows,at_ms)
        lane.update({"raw_receipt_count":len(records),"reported_gap_minutes":sum(len(x["missing_minutes"]) for x in windows)})
        lanes[symbol]=lane
    if sha((root/"CURSOR.json").read_bytes())!=sha(before):
        raise ValueError("SOURCE_CURSOR_CHANGED_DURING_READ")
    return {"schema":SCHEMA,"state":"INDICATOR_CONTEXT_COVERAGE_ONLY_FORMAL_SHADOW_HOLD",
        "source_identity_sha256":identity_sha,"source_cursor_snapshot_sha256":sha(before),
        "source_volume_units":"UNKNOWN","original_source_unchanged":True,
        "asof_ms":at_ms,"per_symbol":lanes,
        "all_symbols_121_contiguous_30m_bars":all(v["native_121_indicator_prefix_ready"] for v in lanes.values()),
        "provenance_scope":"per-request RECEIPT SHA verified; minute completeness from immutable missing-minute records; raw OHLCV replay should independently be verified before actual native indicator decisions",
        "operational_code_gap":"Existing K117 consumer uses ONLY B STATE.market of a bounded 24h epoch, while source contains earlier complete 30m prefix; consumer also hardcodes higher_timeframe_complete=False and stale_authority=None.",
        "signal_policy_executed":False,"trading_volume_unit_bound":False,
        "recorded_next_open":False,"funding_verified":False,"market_calls":0,
        "orders":0,"formal_shadow_pass":False}


def self_test() -> None:
    def w(start=0,end=30*MINUTE,receive=30*MINUTE,missing=None):
        return {"start_ms":start,"end_exclusive_ms":end,"received_at_ms":receive,"missing_minutes":missing or []}
    assert to_30m([w()],31*MINUTE)["complete_bars"]==1
    assert to_30m([w(missing=[6*MINUTE])],31*MINUTE)["complete_bars"]==0
    try:
        to_30m([w()],30*MINUTE-1)
    except ValueError:
        pass
    else:
        raise AssertionError("FUTURE_RECEIPT_ACCEPTED")
    assert to_30m([w(start=i*TF,end=(i+1)*TF,receive=(i+1)*TF) for i in range(121)],122*TF)["native_121_indicator_prefix_ready"]
    assert not to_30m([w(start=i*TF,end=(i+1)*TF,receive=(i+1)*TF) for i in range(120)],121*TF)["native_121_indicator_prefix_ready"]
    errors=[
      ([w(start=0,end=TF,receive=TF),w(start=2*TF,end=3*TF,receive=3*TF)],"CHAIN"),
      ([w(start=0,end=TF,receive=TF+1)],"FUTURE"),
      ([w(missing=[4*MINUTE,4*MINUTE])],"DUPLICATE_GAP"),
      ([w(start=0,end=TF-1,receive=TF)],"GRID")
    ]
    for rows,_ in errors:
        try:
            to_30m(rows,TF)
        except ValueError:
            pass
        else:
            raise AssertionError("ACCEPTED_CORRUPT_INPUT")
    assert SCHEMA.startswith("k117.")
    assert SOURCE.startswith("https://")
    print(json.dumps({"synthetic_checks":11,"result":"PASS","orders":0,"market_requests":0}))


def main() -> None:
    ap=argparse.ArgumentParser()
    ap.add_argument("--source-root",type=Path)
    ap.add_argument("--expected-source-identity-sha256")
    ap.add_argument("--self-test",action="store_true")
    args=ap.parse_args()
    if args.self_test:
        self_test()
        return
    if args.source_root is None:
        ap.error("--source-root required")
    print(json.dumps(inspect_source(args.source_root,int(time.time()*1000),args.expected_source_identity_sha256),indent=2,sort_keys=True))


if __name__=="__main__":
    main()
