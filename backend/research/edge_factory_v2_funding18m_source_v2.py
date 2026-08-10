from __future__ import annotations

import argparse, csv, gzip, hashlib, json, ssl, time
import urllib.parse, urllib.request
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

VERSION='ZEL_EDGE_FACTORY_V2_FUNDING18M_SOURCE_V2'
SCHEMA='zel.edge_factory_v2.funding18m_source_v2.v1'
BASES=('https://open-api.bingx.com','https://open-api.bingx.pro')
ENDPOINT='/openApi/swap/v2/quote/fundingRate'
SYMBOLS=('BTC-USDT','ETH-USDT','LINK-USDT','SOL-USDT','XRP-USDT')
START_MS=1719792000000
END_MS=1767225600000
PRIMARY_CHUNK_MS=7*24*60*60*1000
REPAIR_CHUNK_MS=24*60*60*1000
MAX_GAP_MS=24*60*60*1000
LIMIT=1000
CSV_FIELDS=('fundingTime','fundingRate')
PARTITIONS={
 'D1':(1719792000000,1735689600000),
 'V1':(1735689600000,1751328000000),
 'T1':(1751328000000,1767225600000),
}

def stable_sha(v:Any)->str:
    return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def file_sha(path:Path)->str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1<<20),b''): h.update(chunk)
    return h.hexdigest()

def to_ms(v:Any)->int:
    x=int(float(v)); return x*1000 if x<10_000_000_000 else x

def rate_text(v:Any)->str:
    try: n=Decimal(str(v))
    except (InvalidOperation,ValueError) as exc: raise RuntimeError(f'INVALID_FUNDING_RATE:{v}') from exc
    if not n.is_finite(): raise RuntimeError(f'NONFINITE_FUNDING_RATE:{v}')
    return format(n,'f')

def extract_rows(data:Any)->list[dict[str,Any]]:
    if isinstance(data,list): return [x for x in data if isinstance(x,dict)]
    if isinstance(data,dict):
        for key in ('data','list','rows','fundingRates','result'):
            value=data.get(key)
            if isinstance(value,list): return [x for x in value if isinstance(x,dict)]
        return [data]
    return []

def request_window(symbol:str,start:int,end:int,attempts:int=5)->list[dict[str,Any]]:
    ctx=ssl.create_default_context(); last=''
    params={'symbol':symbol,'startTime':start,'endTime':end,'limit':LIMIT}
    for attempt in range(1,attempts+1):
        for base in BASES:
            try:
                req=urllib.request.Request(base+ENDPOINT+'?'+urllib.parse.urlencode(params),headers={'Accept':'application/json','User-Agent':VERSION})
                with urllib.request.urlopen(req,timeout=20,context=ctx) as resp:
                    obj=json.loads(resp.read().decode())
                if isinstance(obj,dict) and obj.get('code') not in (None,0):
                    raise RuntimeError(f"BINGX_CODE:{obj.get('code')}:{obj.get('msg')}")
                data=obj.get('data',obj) if isinstance(obj,dict) else obj
                out=[]
                for row in extract_rows(data):
                    if 'fundingTime' not in row or 'fundingRate' not in row: continue
                    ts=to_ms(row['fundingTime'])
                    if start<=ts<end:
                        out.append({'fundingTime':ts,'fundingRate':rate_text(row['fundingRate'])})
                return sorted(out,key=lambda x:int(x['fundingTime']))
            except Exception as exc:
                last=f'{base}:{type(exc).__name__}:{str(exc)[:180]}'
        if attempt<attempts: time.sleep(min(2**attempt,12))
    raise RuntimeError(f'FUNDING_REQUEST_FAILED:{symbol}:{start}:{end}:{last}')

def merge_rows(target:dict[int,dict[str,Any]], rows:list[dict[str,Any]], symbol:str)->None:
    for row in rows:
        ts=int(row['fundingTime']); prior=target.get(ts)
        if prior is not None and prior!=row: raise RuntimeError(f'CONFLICTING_DUPLICATE:{symbol}:{ts}')
        target[ts]=row

def windows(start:int,end:int,chunk:int):
    cursor=start
    while cursor<end:
        nxt=min(cursor+chunk,end); yield cursor,nxt; cursor=nxt

def gap_windows(ts:list[int])->list[tuple[int,int]]:
    out=[]
    if not ts: return [(START_MS,END_MS)]
    if ts[0]-START_MS>MAX_GAP_MS: out.append((START_MS,ts[0]))
    for a,b in zip(ts,ts[1:]):
        if b-a>MAX_GAP_MS: out.append((a,b))
    if END_MS-ts[-1]>MAX_GAP_MS: out.append((ts[-1],END_MS))
    return out

def partition_integrity(ts:list[int],start:int,end:int)->dict[str,Any]:
    xs=[x for x in ts if start<=x<end]
    internal=[b-a for a,b in zip(xs,xs[1:])]
    first_delay=(xs[0]-start)/3_600_000 if xs else None
    last_gap=(end-xs[-1])/3_600_000 if xs else None
    max_gap=max(internal)/3_600_000 if internal else None
    days=len({x//86_400_000 for x in xs})
    passed=bool(xs and first_delay<=24 and last_gap<=24 and (max_gap is None or max_gap<=24) and days>=150)
    return {'row_count':len(xs),'distinct_observation_days':days,'first_delay_hours':first_delay,'last_gap_hours':last_gap,'maximum_internal_interarrival_hours':max_gap,'pass':passed}

def collect_symbol(symbol:str,out_dir:Path)->dict[str,Any]:
    by:dict[int,dict[str,Any]]={}; primary_requests=0; repair_requests=0
    for a,b in windows(START_MS,END_MS,PRIMARY_CHUNK_MS):
        merge_rows(by,request_window(symbol,a,b),symbol); primary_requests+=1; time.sleep(.03)
    before=sorted(by); detected=gap_windows(before)
    for gap_start,gap_end in detected:
        for a,b in windows(gap_start,gap_end,REPAIR_CHUNK_MS):
            merge_rows(by,request_window(symbol,a,b),symbol); repair_requests+=1; time.sleep(.03)
    ordered=[by[k] for k in sorted(by)]; ts=[int(x['fundingTime']) for x in ordered]
    duplicate_count=len(ts)-len(set(ts))
    monotonic=all(b>a for a,b in zip(ts,ts[1:]))
    remaining=gap_windows(ts)
    max_gap=max((b-a for a,b in zip(ts,ts[1:])),default=0)/3_600_000 if ts else None
    first_delay=(ts[0]-START_MS)/3_600_000 if ts else None
    last_gap=(END_MS-ts[-1])/3_600_000 if ts else None
    parts={name:partition_integrity(ts,*bounds) for name,bounds in PARTITIONS.items()}
    passed=bool(ts and duplicate_count==0 and monotonic and first_delay<=24 and last_gap<=24 and max_gap<=24 and not remaining and all(x['pass'] for x in parts.values()))
    path=out_dir/f"{symbol.replace('-','')}_funding_v2_{START_MS}_{END_MS}.csv.gz"
    with gzip.open(path,'wt',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=CSV_FIELDS); w.writeheader(); w.writerows(ordered)
    return {
        'symbol':symbol,'state':'PASS_NATIVE_FUNDING_CONTINUITY' if passed else 'HOLD_NATIVE_FUNDING_CONTINUITY_GAP',
        'row_count':len(ordered),'primary_request_count':primary_requests,'repair_request_count':repair_requests,
        'detected_gap_count_before_repair':len(detected),'remaining_gap_count_after_repair':len(remaining),
        'remaining_gap_boundaries_ms':[[a,b] for a,b in remaining],
        'duplicate_timestamp_count':duplicate_count,'strict_monotonic_timestamps':monotonic,
        'first_timestamp_ms':ts[0] if ts else None,'last_timestamp_ms':ts[-1] if ts else None,
        'first_delay_hours':first_delay,'last_gap_hours':last_gap,'maximum_internal_interarrival_hours':max_gap,
        'partition_integrity':parts,'file':path.name,'file_sha256':file_sha(path),'file_bytes':path.stat().st_size,
    }

def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument('--out-dir',type=Path,required=True); ap.add_argument('--manifest',type=Path,required=True); args=ap.parse_args()
    args.out_dir.mkdir(parents=True,exist_ok=True)
    results=[collect_symbol(s,args.out_dir) for s in SYMBOLS]
    all_pass=all(r['state']=='PASS_NATIVE_FUNDING_CONTINUITY' for r in results)
    manifest={
        'schema_version':SCHEMA,'version':VERSION,'generated_at':datetime.now(timezone.utc).isoformat(),
        'state':'PASS_FUNDING18M_V2_SOURCE_BOUND' if all_pass else 'HOLD_FUNDING18M_V2_SOURCE_GAPS',
        'source':{'base_urls':list(BASES),'endpoint':ENDPOINT,'auth_required':False,'start_ms':START_MS,'end_exclusive_ms':END_MS,'primary_chunk_days':7,'gap_repair_chunk_days':1,'limit':LIMIT},
        'symbols':list(SYMBOLS),'results':results,
        'hard_integrity':{'maximum_internal_interarrival_hours':24,'partition_boundary_max_hours':24,'minimum_distinct_observation_days_per_partition':150,'all_symbols_pass':all_pass},
        'funding_signal_hypotheses_defined':False,'economics_inspected':False,'d1_funding_metrics_inspected':False,'v1_funding_metrics_inspected':False,'t1_funding_metrics_inspected':False,
        'raw_funding_values_logged':False,'interpolation_used':False,'synthetic_funding_used':False,'forward_fill_used':False,'ai_used':False,
        'canonical_mutated':False,'registry_mutated':False,'runtime_mutated':False,'selection_authority':False,'promotion_authority':False,'survivor_declared':False,
        'execution_authority':'NONE','order_authority':'BLOCKED','action':'hold',
        'next':'FREEZE_CROSS_SECTIONAL_FUNDING_PRIMITIVES_BEFORE_D1_FUNDING_SCORE' if all_pass else 'SOURCE_HOLD_OR_ROUTE_TO_OTHER_NATIVE_POSITIONING_SOURCE'
    }
    manifest['funding_dataset_sha256']=stable_sha([{'symbol':r['symbol'],'file_sha256':r['file_sha256']} for r in results])
    manifest['receipt_sha256']=stable_sha(manifest)
    args.manifest.parent.mkdir(parents=True,exist_ok=True); args.manifest.write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'state':manifest['state'],'funding_dataset_sha256':manifest['funding_dataset_sha256'],'receipt_sha256':manifest['receipt_sha256'],'summaries':[{k:r[k] for k in ('symbol','state','row_count','detected_gap_count_before_repair','remaining_gap_count_after_repair','maximum_internal_interarrival_hours','primary_request_count','repair_request_count')} for r in results]},sort_keys=True))
    return 0

if __name__=='__main__': raise SystemExit(main())
