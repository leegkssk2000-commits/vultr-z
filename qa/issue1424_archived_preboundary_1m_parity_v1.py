"""Source-frozen CPU parity on original archived public BingX 1m candles.

Research regression ONLY. All observations precede sealed G5 boundary.
Do not credit any recorded PnL or replay claim.
"""
from __future__ import annotations
import csv
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import time
import types

sys.path.insert(0, str(Path.cwd()))
from backend.research.architecture_factory import a1_external_research_exact8_through_a3_runner_v1 as runner

CORE = runner.core
BASE_SHA = "d57993aa4168bb2bf9546fe3af1c6ce7d27a9c23"
TESTED_SHA = "695c6ae37689d0d07eb934f68b3be21c262c0cf3"
SOURCE = "https://open-api.bingx.com/openApi/swap/v3/quote/klines"
SEG = "canonical_postgap_20260213"
MANIFEST_SHA = "bce71f9b39dee91d7ebe074da0407d672f1ead645ade5ccd788c45f96cee5bf7"
START = 1786752000000  # 2026-08-15T00:00:00Z
END = 1787270400000    # 2026-08-21T00:00:00Z
SEAL = 1787350320000   # Exact8 G5 fresh 2026-08-21T22:12:00Z
DAY = 86400000
MINUTE = 60000
assert END < SEAL and (END-START) == 6*DAY
SYMS = ("BTC-USDT", "ETH-USDT")
OUT = Path("out/issue1424_archived_real_dev_parity")
OUT.mkdir(parents=True, exist_ok=True)
RESULT = {
    "schema":"zel.issue1424.real_archived_preboundary_parity.v1",
    "state":"HOLD_UNVERIFIED_ARCHIVE",
    "baseline_sha":BASE_SHA, "candidate_sha":TESTED_SHA,
    "time_start_ms":START, "time_end_exclusive_ms":END,
    "fresh_boundary_ms":SEAL, "preboundary_data_only":True,
    "raw_source_receipt_count":0, "source_verified":False,
    "formal_economic_credit":0, "economic_replay_claims":0,
    "selection_authority":False, "promotion_authority":False,
    "order_authority":"BLOCKED", "live_trade_authority":"BLOCKED",
    "historical_receipt_network_delivery_observed":False,
    "account_nav_verified":False, "historical_funding_realized":False,
    "source_files":[], "six_lanes":[]
}
def save():
    (OUT/"report.json").write_text(json.dumps(RESULT,sort_keys=True,indent=2,allow_nan=False)+"\n")
def digest(b):
    return hashlib.sha256(b).hexdigest()
def open_archive(path):
    with tarfile.open(path,"r:gz") as tf:
        files={}
        for item in tf:
            if not item.isfile() or item.issym() or item.islnk() or not item.name.startswith(SEG+"/") or ".." in Path(item.name).parts:
                raise RuntimeError("INVALID_ARCHIVED_SOURCE_TAR_MEMBER")
            if item.name in files:
                raise RuntimeError("DUPLICATE_ARCHIVED_SOURCE_TAR_MEMBER")
            body=tf.extractfile(item)
            if body is None:raise RuntimeError("SOURCE_TAR_MEMBER_NOT_FILE")
            files[item.name]=body.read()
        return files
def get(files,rel):
    path=SEG+"/"+rel
    if path not in files:raise RuntimeError("REQUIRED_ARCHIVED_DEV_SOURCE_MISSING:"+path)
    return files[path]
def f(row,k):
    try: v=float(row[k])
    except (ValueError,KeyError,TypeError) as exc: raise RuntimeError("SOURCE_CSV_COLUMN_INVALID:"+k) from exc
    if not math.isfinite(v):raise RuntimeError("SOURCE_NUMERIC_NONFINITE:"+k)
    return v
def readminute(gzip_bytes,sym,start):
    raw=gzip.decompress(gzip_bytes).decode()
    reader=csv.DictReader(io.StringIO(raw))
    assert {"timestamp_ms","open","high","low","close","volume"}.issubset(set(reader.fieldnames or [])),"SOURCE_CSV_FIELDS_MISSING"
    out=[]
    for row in reader:
        ts=int(row["timestamp_ms"])
        if ts%MINUTE or not start<=ts<start+DAY:raise RuntimeError("DEV_SOURCE_TIMESTAMP_OUTSIDE_EXPECTED_DAY")
        o,h,l,c,v=(f(row,k) for k in ("open","high","low","close","volume"))
        if min(o,h,l,c)<=0 or h<max(o,l,c) or l>min(o,h,c) or v<0:
            raise RuntimeError("DEV_SOURCE_INVALID_OHLC")
        out.append({"ts_ms":ts,"open":o,"high":h,"low":l,"close":c,"volume":v})
    if len(out)!=1440 or [x["ts_ms"] for x in out]!=list(range(start,start+DAY,MINUTE)):
        raise RuntimeError(f"DEV_SOURCE_MINUTE_GRID_FAILED:{sym}:{start}:{len(out)}")
    return out
def aggregate(rows,interval):
    n=interval//MINUTE
    result=[]
    for i in range(0,len(rows),n):
        chunk=rows[i:i+n]
        if len(chunk)!=n:continue
        ts=chunk[0]["ts_ms"]
        if ts%interval or chunk[-1]["ts_ms"]!=ts+interval-MINUTE:raise RuntimeError("SOURCE_AGGREGATION_GAP")
        result.append({
            "ts_ms":ts,"open":chunk[0]["open"],
            "high":max(x["high"] for x in chunk),
            "low":min(x["low"] for x in chunk),
            "close":chunk[-1]["close"],
            "volume":sum(x["volume"] for x in chunk)
        })
    return result
def read60(data,start):
    rows=list(csv.DictReader(io.StringIO(gzip.decompress(data).decode())))
    if len(rows)!=24:raise RuntimeError("SAVED_60M_COUNT_INVALID")
    for k,row in enumerate(rows):
        if int(row["open_ts_ms"])!=start+k*3600000:raise RuntimeError("SAVED_60M_TIME_DRIFT")
    return rows
def load_and_check(files):
    manifest=get(files,"MANIFEST.json")
    if digest(manifest)!=MANIFEST_SHA:raise RuntimeError("CANONICAL_POSTGAP_MANIFEST_HASH_DRIFT")
    obj=json.loads(manifest)
    if obj.get("source")!=SOURCE or obj.get("source_interval")!="1m":
        raise RuntimeError("CANONICAL_POSTGAP_SOURCE_IDENTITY_DRIFT")
    stream={}
    for sym in SYMS:
        minutes=[]
        savedhours=[]
        for start in range(START,END,DAY):
            stem=f"{start}_{start+DAY}"
            receipt_path=f"daily_receipts/{sym}/{stem}.json"
            receipt_bytes=get(files,receipt_path)
            receipt=json.loads(receipt_bytes)
            if receipt.get("symbol")!=sym or int(receipt["start_ms"])!=start or int(receipt["end_exclusive_ms"])!=start+DAY:
                raise RuntimeError("RECEIPT_SYMBOL_OR_WINDOW_MISMATCH")
            if receipt.get("source")!=SOURCE:raise RuntimeError("RECEIPT_SOURCE_MISMATCH")
            by_path={a.get("path"):a for a in receipt.get("artifacts",[])}
            paths=[f"1m/{sym}/{stem}.csv.gz",f"60m/{sym}/{stem}.csv.gz"]
            verified={}
            for rel in paths:
                if rel not in by_path:raise RuntimeError("RECEIPT_SOURCE_ARTIFACT_MISSING:"+rel)
                raw=get(files,rel)
                reported=by_path[rel].get("sha256")
                if digest(raw)!=reported:raise RuntimeError("RAW_DAILY_SOURCE_SHA_MISMATCH:"+rel)
                verified[rel]=raw
            minutes+=readminute(verified[paths[0]],sym,start)
            savedhours+=read60(verified[paths[1]],start)
            RESULT["source_files"].append({
                "symbol":sym,"day_start_ms":start,
                "receipt_sha256":digest(receipt_bytes),
                "one_minute_sha256":digest(verified[paths[0]]),
                "sixty_minute_sha256":digest(verified[paths[1]]),
                "source_canonical_manifest_sha256":MANIFEST_SHA,
            })
        assert len(minutes)==6*1440 and len(savedhours)==6*24
        h1=aggregate(minutes,3600000)
        for a,b in zip(h1,savedhours):
            for key in ("open","high","low","close","volume"):
                if not math.isclose(a[key],float(b[key]),rel_tol=1e-9,abs_tol=1e-6):
                    raise RuntimeError(f"ORIGINAL_60M_AGGREGATION_PARITY_FAIL:{sym}:{a['ts_ms']}:{key}")
        stream[f"{sym}|3600000"]=h1
        stream[f"{sym}|300000"]=aggregate(minutes,300000)
        print(json.dumps({"verified_source":sym,"rows_1m":len(minutes),"rows_5m":len(stream[f'{sym}|300000']),"rows_1h":len(h1),"sixty_minute_archive_parity":True,"source_only":True}),flush=True)
    RESULT["source_verified"]=True
    RESULT["raw_source_receipt_count"]=len(RESULT["source_files"])
    return stream
def replay(stream):
    codepath="backend/research/architecture_factory/a1_external_research_exact8_through_a3_v1.py"
    source=subprocess.check_output(["git","show",BASE_SHA+":"+codepath],text=True)
    old=types.ModuleType("issue1424_bingx_archive_original")
    old.__file__=str(Path.cwd()/codepath)
    sys.modules[old.__name__]=old
    exec(compile(source,old.__file__,"exec"),old.__dict__)
    spec=CORE.read(CORE.SPEC_PATH)
    state={"boundary_ms":START,"streams":stream,"cost_snapshot_by_symbol":{x:{"pretrade_verified_cost_bps":14.0} for x in SYMS},"integrity_defects":[]}
    for pid in CORE.SOURCE_READY:
        t0=time.perf_counter()
        original=old.replay_child(pid,state,spec)
        old_time=time.perf_counter()-t0
        t1=time.perf_counter()
        optimized=CORE.replay_child(pid,state,spec)
        new_time=time.perf_counter()-t1
        h0=CORE.stable_sha(original);h1=CORE.stable_sha(optimized)
        if h0!=h1:raise RuntimeError("REAL_DEV_OLD_NEW_LEDGER_MISMATCH:"+pid)
        if original["integrity_defects"]:raise RuntimeError("DEV_POLICY_INTEGRITY_DEFECTS:"+pid+":"+str(original["integrity_defects"][:2]))
        row={
            "identity":pid, "parent_opportunities":len(original["parent_opportunities"]),
            "child_trades":len(original["child_trades"]), "baseline_hash":h0,
            "optimized_hash":h1, "original_seconds":round(old_time,5),
            "optimized_seconds":round(new_time,5), "same_full_replay":True,
            "cost_source":"FROZEN_RESEARCH_SCENARIO_14BPS_NOT_HISTORICAL_REALIZED",
            "formal_economic_credit":0,
        }
        RESULT["six_lanes"].append(row)
        print(json.dumps(row,sort_keys=True),flush=True)
    RESULT["total_parent_opportunities"]=sum(x["parent_opportunities"] for x in RESULT["six_lanes"])
    RESULT["total_child_trades"]=sum(x["child_trades"] for x in RESULT["six_lanes"])
    RESULT["cpu_baseline_seconds"]=round(sum(x["original_seconds"] for x in RESULT["six_lanes"]),4)
    RESULT["cpu_optimized_seconds"]=round(sum(x["optimized_seconds"] for x in RESULT["six_lanes"]),4)
    RESULT["state"]="PASS_REAL_ARCHIVED_PREBOUNDARY_PARITY_ONLY_NOT_ECONOMIC_EVIDENCE" if RESULT["total_child_trades"]>0 else "HOLD_REAL_ARCHIVED_PREBOUNDARY_0_CHILD_TRADES"
try:
    if len(sys.argv)!=2:raise RuntimeError("REQUIRED_FROZEN_ARCHIVE_FILE")
    replay(load_and_check(open_archive(Path(sys.argv[1]))))
except Exception as exc:
    RESULT["state"]="HOLD_REAL_DEV_ARCHIVE_SOURCE_OR_PARITY"
    RESULT["blocker"]=type(exc).__name__+":"+str(exc)
    save()
    print(json.dumps({"state":RESULT["state"],"blocker":RESULT["blocker"],"formal_economic_credit":0}),flush=True)
    raise
save()
print(json.dumps({"state":RESULT["state"],"verified_receipts":RESULT["raw_source_receipt_count"],"lanes":len(RESULT["six_lanes"]),"child_trades":RESULT["total_child_trades"],"formal_economic_credit":0}),flush=True)
