from __future__ import annotations

from hashlib import sha256
import json
from statistics import median

REQUIRED=("record_id","ts_utc","symbol","source_sha","source_type")

class ExecutionQualityError(ValueError):
    pass


def canonical_digest(records:list[dict])->str:
    payload=json.dumps(records,sort_keys=True,separators=(",",":"))
    return sha256(payload.encode()).hexdigest()


def append_record(records:list[dict], record:dict, *, parent_digest:str|None=None)->list[dict]:
    missing=[k for k in REQUIRED if record.get(k) is None]
    if missing: raise ExecutionQualityError("missing:"+",".join(missing))
    if any(str(x["record_id"])==str(record["record_id"]) for x in records):
        raise ExecutionQualityError("duplicate_record_id")
    if records:
        expected=canonical_digest(records)
        if parent_digest!=expected: raise ExecutionQualityError("parent_digest_mismatch")
    elif parent_digest not in (None,""):
        raise ExecutionQualityError("unexpected_parent_digest")
    return records+[dict(record)]


def size_bucket(notional_usdt:float)->str:
    x=float(notional_usdt)
    edges=[1000,5000,10000,25000,50000]
    for e in edges:
        if x<=e: return f"LE_{e}"
    return "GT_50000"


def _values(records,key):
    return [float(r[key]) for r in records if r.get(key) is not None]


def calibrate(records:list[dict])->dict:
    ids=[str(r.get("record_id")) for r in records]
    if len(ids)!=len(set(ids)): raise ExecutionQualityError("duplicate_record_id")
    by_bucket={}
    for r in records:
        if r.get("notional_usdt") is None or r.get("depth_vwap_impact_bps") is None: continue
        b=size_bucket(float(r["notional_usdt"]))
        by_bucket.setdefault(b,[]).append(float(r["depth_vwap_impact_bps"]))
    def stats(key):
        v=sorted(_values(records,key))
        if not v: return {"n":0,"median":None,"p95":None}
        idx=max(0,min(len(v)-1,int(round(.95*(len(v)-1)))))
        return {"n":len(v),"median":median(v),"p95":v[idx]}
    rejects=[bool(r.get("rejected")) for r in records if r.get("rejected") is not None]
    partial=[float(r["partial_fill_ratio"]) for r in records if r.get("partial_fill_ratio") is not None]
    return {
      "records":len(records),
      "spread_bps":stats("spread_bps"),
      "latency_ms":stats("latency_ms"),
      "funding_bps":stats("funding_bps"),
      "stop_slippage_bps":stats("stop_slippage_bps"),
      "size_bucket_slippage_bps":{k:{"n":len(v),"median":median(v)} for k,v in sorted(by_bucket.items())},
      "reject_rate":sum(rejects)/len(rejects) if rejects else None,
      "partial_fill_ratio_median":median(partial) if partial else None,
      "order_submission_performed":False
    }
