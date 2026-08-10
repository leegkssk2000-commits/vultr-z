from __future__ import annotations

import argparse, csv, gzip, hashlib, json, ssl, time
import urllib.parse, urllib.request
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

VERSION='ZEL_EDGE_FACTORY_V2_FUNDING18M_COLLECT_V1'
SCHEMA='zel.edge_factory_v2.funding18m_collect.v1'
BASES=('https://open-api.bingx.com','https://open-api.bingx.pro')
ENDPOINT='/openApi/swap/v2/quote/fundingRate'
SYMBOLS=('BTC-USDT','ETH-USDT','LINK-USDT','SOL-USDT','XRP-USDT')
START_MS=1719792000000
END_MS=1767225600000
CHUNK_MS=30*24*60*60*1000
LIMIT=1000
CSV_FIELDS=('fundingTime','fundingRate')

def canonical_sha(v:Any)->str:return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def file_sha(path:Path)->str:
 h=hashlib.sha256()
 with path.open('rb') as f:
  for c in iter(lambda:f.read(1<<20),b''):h.update(c)
 return h.hexdigest()
def to_ms(v:Any)->int:
 x=int(float(v));return x*1000 if x<10_000_000_000 else x
def rate_text(v:Any)->str:
 try:n=Decimal(str(v))
 except (InvalidOperation,ValueError) as exc:raise RuntimeError(f'INVALID_FUNDING_RATE:{v}') from exc
 if not n.is_finite():raise RuntimeError(f'NONFINITE_FUNDING_RATE:{v}')
 return format(n,'f')
def rows(data:Any)->list[dict[str,Any]]:
 if isinstance(data,list):return [x for x in data if isinstance(x,dict)]
 if isinstance(data,dict):
  for k in ('data','list','rows','fundingRates','result'):
   v=data.get(k)
   if isinstance(v,list):return [x for x in v if isinstance(x,dict)]
  return [data]
 return []
def get(symbol:str,start:int,end:int,attempts:int=5)->list[dict[str,Any]]:
 ctx=ssl.create_default_context();last=''
 params={'symbol':symbol,'startTime':start,'endTime':end,'limit':LIMIT}
 for attempt in range(1,attempts+1):
  for base in BASES:
   try:
    req=urllib.request.Request(base+ENDPOINT+'?'+urllib.parse.urlencode(params),headers={'Accept':'application/json','User-Agent':VERSION})
    with urllib.request.urlopen(req,timeout=20,context=ctx) as resp:obj=json.loads(resp.read().decode())
    if isinstance(obj,dict) and obj.get('code') not in (None,0):raise RuntimeError(f"BINGX_CODE:{obj.get('code')}:{obj.get('msg')}")
    data=obj.get('data',obj) if isinstance(obj,dict) else obj
    out=[]
    for r in rows(data):
     if 'fundingTime' not in r or 'fundingRate' not in r:continue
     ts=to_ms(r['fundingTime'])
     if start<=ts<end:out.append({'fundingTime':ts,'fundingRate':rate_text(r['fundingRate'])})
    return sorted(out,key=lambda x:x['fundingTime'])
   except Exception as exc:last=f'{base}:{type(exc).__name__}:{str(exc)[:180]}'
  if attempt<attempts:time.sleep(min(2**attempt,12))
 raise RuntimeError(f'FUNDING_REQUEST_FAILED:{symbol}:{start}:{end}:{last}')
def collect(symbol:str,out_dir:Path)->dict[str,Any]:
 by={};cursor=START_MS;requests=0
 while cursor<END_MS:
  end=min(cursor+CHUNK_MS,END_MS);chunk=get(symbol,cursor,end);requests+=1
  for r in chunk:
   ts=int(r['fundingTime']);prior=by.get(ts)
   if prior is not None and prior!=r:raise RuntimeError(f'CONFLICTING_DUPLICATE:{symbol}:{ts}')
   by[ts]=r
  cursor=end;time.sleep(.05)
 ordered=[by[k] for k in sorted(by)]
 if len(ordered)<100:raise RuntimeError(f'LOW_ROW_COUNT:{symbol}:{len(ordered)}')
 ts=[int(x['fundingTime']) for x in ordered]
 if len(ts)!=len(set(ts)):raise RuntimeError(f'DUPLICATE_TS:{symbol}')
 if any(b<=a for a,b in zip(ts,ts[1:])):raise RuntimeError(f'NON_MONOTONIC:{symbol}')
 first_delay_h=(ts[0]-START_MS)/3_600_000;last_gap_h=(END_MS-ts[-1])/3_600_000
 if first_delay_h>24:raise RuntimeError(f'START_COVERAGE_GAP:{symbol}:{first_delay_h}')
 if last_gap_h>24:raise RuntimeError(f'END_COVERAGE_GAP:{symbol}:{last_gap_h}')
 days=len({x//86_400_000 for x in ts})
 if days<100:raise RuntimeError(f'LOW_DAY_BREADTH:{symbol}:{days}')
 intervals=[b-a for a,b in zip(ts,ts[1:])]
 hist={}
 for x in intervals:hist[str(x)]=hist.get(str(x),0)+1
 path=out_dir/f"{symbol.replace('-','')}_funding_{START_MS}_{END_MS}.csv.gz"
 with gzip.open(path,'wt',encoding='utf-8',newline='') as f:
  w=csv.DictWriter(f,fieldnames=CSV_FIELDS);w.writeheader();w.writerows(ordered)
 partitions={'D1':sum(1719792000000<=x<1735689600000 for x in ts),'V1':sum(1735689600000<=x<1751328000000 for x in ts),'T1':sum(1751328000000<=x<1767225600000 for x in ts)}
 return {'symbol':symbol,'row_count':len(ordered),'request_count':requests,'duplicate_timestamp_count':0,'first_timestamp_ms':ts[0],'last_timestamp_ms':ts[-1],'first_delay_hours':first_delay_h,'last_gap_hours':last_gap_h,'distinct_observation_days':days,'interval_ms_histogram':dict(sorted(hist.items())),'partition_row_counts':partitions,'file':path.name,'file_sha256':file_sha(path),'file_bytes':path.stat().st_size}
def main()->int:
 ap=argparse.ArgumentParser();ap.add_argument('--out-dir',type=Path,required=True);ap.add_argument('--manifest',type=Path,required=True);a=ap.parse_args();a.out_dir.mkdir(parents=True,exist_ok=True)
 results=[collect(s,a.out_dir) for s in SYMBOLS]
 manifest={'schema_version':SCHEMA,'version':VERSION,'generated_at':datetime.now(timezone.utc).isoformat(),'state':'PASS_FUNDING18M_SOURCE_BOUND','source':{'base_urls':list(BASES),'endpoint':ENDPOINT,'auth_required':False,'start_ms':START_MS,'end_exclusive_ms':END_MS,'chunk_days':30,'limit':LIMIT},'symbols':list(SYMBOLS),'results':results,'funding_signal_hypotheses_defined':False,'economics_inspected':False,'d1_funding_metrics_inspected':False,'v1_funding_metrics_inspected':False,'t1_funding_metrics_inspected':False,'raw_funding_values_logged':False,'ai_used':False,'canonical_mutated':False,'registry_mutated':False,'runtime_mutated':False,'selection_authority':False,'promotion_authority':False,'survivor_declared':False,'execution_authority':'NONE','order_authority':'BLOCKED','action':'hold','next':'FREEZE_CROSS_SECTIONAL_FUNDING_PRIMITIVES_BEFORE_D1_FUNDING_SCORE'}
 manifest['funding_dataset_sha256']=canonical_sha([{'symbol':r['symbol'],'file_sha256':r['file_sha256']} for r in results]);manifest['receipt_sha256']=canonical_sha(manifest);a.manifest.parent.mkdir(parents=True,exist_ok=True);a.manifest.write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
 print(json.dumps({'state':manifest['state'],'funding_dataset_sha256':manifest['funding_dataset_sha256'],'receipt_sha256':manifest['receipt_sha256'],'summaries':[{k:r[k] for k in ('symbol','row_count','first_timestamp_ms','last_timestamp_ms','distinct_observation_days','partition_row_counts','interval_ms_histogram')} for r in results]},sort_keys=True));return 0
if __name__=='__main__':raise SystemExit(main())
