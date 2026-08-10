#!/usr/bin/env python3
from __future__ import annotations

import argparse,hashlib,json,ssl,time,urllib.parse,urllib.request
from datetime import datetime,timezone
from pathlib import Path
from typing import Any

BASES=('https://open-api.bingx.com','https://open-api.bingx.pro')
SYMBOLS=('BTC-USDT','ETH-USDT','SOL-USDT','XRP-USDT','LINK-USDT')
ENDPOINTS={'premium_index':'/openApi/swap/v2/quote/premiumIndex','open_interest':'/openApi/swap/v2/quote/openInterest'}
FIELDS={'premium_index':('symbol','markPrice','indexPrice','lastFundingRate','fundingIntervalHours','nextFundingTime','updateTime'),'open_interest':('symbol','openInterest','time')}

def sha(v:Any)->str:return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def to_ms(v:Any)->int:
 x=int(float(v));return x*1000 if x<10_000_000_000 else x
def get(path:str,symbol:str):
 ctx=ssl.create_default_context();errors=[]
 for base in BASES:
  try:
   url=base+path+'?'+urllib.parse.urlencode({'symbol':symbol});req=urllib.request.Request(url,headers={'User-Agent':'ZEL-EdgeFactoryV2-positioning-burst/1.0','Accept':'application/json'});t0=time.perf_counter()
   with urllib.request.urlopen(req,timeout=15,context=ctx) as resp:obj=json.loads(resp.read().decode())
   latency=(time.perf_counter()-t0)*1000
   if isinstance(obj,dict) and obj.get('code') not in (None,0):raise RuntimeError(f"code={obj.get('code')} msg={obj.get('msg')}")
   data=obj.get('data',obj) if isinstance(obj,dict) else obj
   if isinstance(data,list):
    if len(data)!=1 or not isinstance(data[0],dict):raise RuntimeError('LIST_CARDINALITY')
    data=data[0]
   if not isinstance(data,dict):raise RuntimeError('PAYLOAD_TYPE')
   return data,base,latency
  except Exception as e:errors.append(f'{base}:{type(e).__name__}:{str(e)[:160]}')
 raise RuntimeError(' | '.join(errors))
def record(feature,symbol,payload,base,latency,collected):
 values={k:payload.get(k) for k in FIELDS[feature] if k in payload};tskey='updateTime' if feature=='premium_index' else 'time';required=('markPrice','indexPrice','updateTime') if feature=='premium_index' else ('openInterest','time')
 missing=[k for k in required if payload.get(k) in (None,'')]
 if missing:raise RuntimeError(f'SCHEMA:{feature}:{symbol}:{missing}')
 return {'schema_version':'zel.edge_factory_v2.positioning_record.v1','feature':feature,'symbol':symbol,'source_endpoint':ENDPOINTS[feature],'source_base':base,'source_timestamp_ms':to_ms(payload[tskey]),'collected_at_ms':collected,'latency_ms':latency,'values':values,'source_payload_sha256':sha(payload)}
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--out-dir',type=Path,required=True);ap.add_argument('--samples',type=int,default=7);ap.add_argument('--interval-seconds',type=int,default=60);a=ap.parse_args()
 if a.samples<2 or a.samples>20 or a.interval_seconds<1:raise RuntimeError('BURST_CONTRACT')
 a.out_dir.mkdir(parents=True,exist_ok=True);all_records=[];snapshots=[]
 for n in range(a.samples):
  collected=int(datetime.now(timezone.utc).timestamp()*1000);rows=[]
  for feature in ('premium_index','open_interest'):
   for symbol in SYMBOLS:
    payload,base,lat=get(ENDPOINTS[feature],symbol);rows.append(record(feature,symbol,payload,base,lat,collected))
  keys={(r['feature'],r['symbol']) for r in rows};expected={(f,s) for f in ENDPOINTS for s in SYMBOLS}
  if keys!=expected:raise RuntimeError('SNAPSHOT_PARITY')
  snapshot={'sample_index':n,'collected_at_ms':collected,'record_count':len(rows),'records':rows,'snapshot_sha256':sha(rows)};snapshots.append(snapshot);all_records.extend(rows)
  (a.out_dir/f'snapshot_{n:02d}.json').write_text(json.dumps(snapshot,indent=2,sort_keys=True,allow_nan=False)+'\n')
  if n<a.samples-1:time.sleep(a.interval_seconds)
 # source-only quality: collection times strict; source timestamps may legitimately repeat.
 ctimes=[x['collected_at_ms'] for x in snapshots];strict=all(b>a for a,b in zip(ctimes,ctimes[1:]));pairs={}
 for r in all_records:pairs.setdefault((r['feature'],r['symbol']),[]).append(r)
 summary={}
 for (f,s),rs in sorted(pairs.items()):
  summary[f'{f}:{s}']={'samples':len(rs),'distinct_source_timestamps':len({r['source_timestamp_ms'] for r in rs}),'distinct_payload_hashes':len({r['source_payload_sha256'] for r in rs}),'source_timestamp_non_decreasing':all(b['source_timestamp_ms']>=a['source_timestamp_ms'] for a,b in zip(rs,rs[1:])),'max_latency_ms':max(r['latency_ms'] for r in rs)}
 ok=strict and len(all_records)==a.samples*len(SYMBOLS)*len(ENDPOINTS) and all(v['samples']==a.samples and v['source_timestamp_non_decreasing'] for v in summary.values())
 manifest={'schema_version':'zel.edge_factory_v2.positioning_burst_source.v1','state':'PASS_POSITIONING_BURST_SOURCE' if ok else 'HOLD_POSITIONING_BURST_SOURCE_INTEGRITY','generated_at':datetime.now(timezone.utc).isoformat(),'symbols':list(SYMBOLS),'features':list(ENDPOINTS),'sample_count':a.samples,'interval_seconds':a.interval_seconds,'record_count':len(all_records),'strict_collection_time':strict,'pair_summary':summary,'economics_inspected':False,'derived_basis_emitted':False,'signal_generation_enabled':False,'replay_allowed':False,'AI_used':False,'selection_authority':False,'promotion_authority':False,'survivor_declared':False,'execution_authority':'NONE','order_authority':'BLOCKED','action':'hold','next':'DESIGN_DURABLE_POSITIONING_HISTORY_PERSISTENCE' if ok else 'SOURCE_HOLD'};manifest['receipt_sha256']=sha(manifest);(a.out_dir/'manifest.json').write_text(json.dumps(manifest,indent=2,sort_keys=True,allow_nan=False)+'\n');print(json.dumps({'state':manifest['state'],'record_count':manifest['record_count'],'pair_summary':summary,'receipt_sha256':manifest['receipt_sha256']},sort_keys=True));return 0
if __name__=='__main__':raise SystemExit(main())
