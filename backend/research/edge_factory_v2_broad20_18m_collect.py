from __future__ import annotations
import argparse,csv,gzip,hashlib,json,time
import urllib.error,urllib.parse,urllib.request
from datetime import datetime,timezone
from decimal import Decimal,InvalidOperation
from pathlib import Path
from typing import Any,Iterable,Mapping,Sequence
VERSION='ZEL_EDGE_FACTORY_V2_BROAD20_18M_DATA_V1';SCHEMA='zel.edge_factory_v2.broad20_18m_data.v1'
BASE='https://open-api.bingx.com';ENDPOINT='/openApi/swap/v3/quote/klines';INTERVAL='1h';INTERVAL_MS=3_600_000;LIMIT=1000;SAFE_BARS=999
SYMBOLS=('BTC-USDT','ETH-USDT','SOL-USDT','XRP-USDT','DOGE-USDT','ADA-USDT','LINK-USDT','LTC-USDT','BCH-USDT','DOT-USDT','AVAX-USDT','TRX-USDT','ETC-USDT','UNI-USDT','XLM-USDT','ATOM-USDT','NEAR-USDT','FIL-USDT','APT-USDT','ARB-USDT')
CORE=('BTC-USDT','ETH-USDT','SOL-USDT','XRP-USDT','LINK-USDT');MIN_ACCEPTED=12;START=1719792000000;END=1767225600000;EXPECTED=13176;FIELDS=('timestamp_ms','open','high','low','close','volume')
PARTS={'D1_DISCOVERY':(1719792000000,1735689600000),'V1_VALIDATION':(1735689600000,1751328000000),'T1_TEST':(1751328000000,1767225600000)}
def stable(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def fsha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for c in iter(lambda:f.read(1<<20),b''):h.update(c)
 return h.hexdigest()
def dec(v,f):
 try:n=Decimal(str(v))
 except (InvalidOperation,ValueError) as e:raise RuntimeError(f'INVALID_DECIMAL:{f}:{v}') from e
 if not n.is_finite():raise RuntimeError(f'NONFINITE:{f}')
 if f!='volume' and n<=0:raise RuntimeError(f'NONPOSITIVE:{f}')
 if f=='volume' and n<0:raise RuntimeError('NEG_VOLUME')
 return format(n,'f')
def extract(o):
 if isinstance(o,list):return o
 if isinstance(o,Mapping):
  for k in ('data','rows','items','list','klines'):
   v=o.get(k)
   if isinstance(v,list):return v
 raise RuntimeError('ROWS_MISSING')
def norm(r):
 if isinstance(r,Mapping):v={'timestamp_ms':r.get('openTime',r.get('time',r.get('timestamp'))),'open':r.get('open'),'high':r.get('high'),'low':r.get('low'),'close':r.get('close'),'volume':r.get('volume',r.get('vol',0))}
 elif isinstance(r,Sequence) and not isinstance(r,(str,bytes)) and len(r)>=6:v={'timestamp_ms':r[0],'open':r[1],'high':r[2],'low':r[3],'close':r[4],'volume':r[5]}
 else:raise RuntimeError('ROW_SHAPE')
 ts=int(float(v['timestamp_ms']));row={'timestamp_ms':ts,'open':dec(v['open'],'open'),'high':dec(v['high'],'high'),'low':dec(v['low'],'low'),'close':dec(v['close'],'close'),'volume':dec(v['volume'],'volume')};o,h,l,c=map(Decimal,(row['open'],row['high'],row['low'],row['close']))
 if h<max(o,c,l) or l>min(o,c,h):raise RuntimeError(f'OHLC:{ts}')
 return row
def req(symbol,a,b,attempts=4):
 q={'symbol':symbol,'interval':INTERVAL,'startTime':a,'endTime':b,'limit':LIMIT};request=urllib.request.Request(BASE+ENDPOINT+'?'+urllib.parse.urlencode(q),headers={'Accept':'application/json','User-Agent':VERSION});last=''
 for i in range(1,attempts+1):
  try:
   with urllib.request.urlopen(request,timeout=25) as resp:o=json.loads(resp.read())
   if isinstance(o,dict) and int(o.get('code',0))!=0:raise RuntimeError(f"CODE:{o.get('code')}:{o.get('msg')}")
   data=o.get('data',o) if isinstance(o,dict) else o;return sorted((norm(x) for x in extract(data)),key=lambda x:x['timestamp_ms'])
  except Exception as e:last=f'{type(e).__name__}:{str(e)[:200]}';time.sleep(min(2**i,8))
 raise RuntimeError(last)
def collect(symbol,out):
 try:
  by={};cursor=START;requests=0
  while cursor<END:
   b=min(cursor+SAFE_BARS*INTERVAL_MS,END);rows=req(symbol,cursor,b);requests+=1
   for r in rows:
    ts=int(r['timestamp_ms'])
    if cursor<=ts<b:
     if ts in by and by[ts]!=r:raise RuntimeError(f'CONFLICT_DUP:{ts}')
     by[ts]=r
   cursor=b;time.sleep(.05)
  exp=list(range(START,END,INTERVAL_MS));missing=[x for x in exp if x not in by];unexpected=[x for x in by if x<START or x>=END]
  if missing or unexpected:raise RuntimeError(f'COVERAGE:rows={len(by)} missing={len(missing)} unexpected={len(unexpected)} first_missing={missing[:3]}')
  ordered=[by[x] for x in exp];path=out/f"{symbol.replace('-','')}_1h_{START}_{END}.csv.gz"
  with gzip.open(path,'wt',encoding='utf-8',newline='') as f:w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader();w.writerows(ordered)
  pc={k:sum(a<=int(r['timestamp_ms'])<b for r in ordered) for k,(a,b) in PARTS.items()}
  return {'symbol':symbol,'state':'PASS_EXACT_18M_SOURCE','row_count':len(ordered),'request_count':requests,'first_timestamp_ms':int(ordered[0]['timestamp_ms']),'last_timestamp_ms':int(ordered[-1]['timestamp_ms']),'missing_interval_count':0,'duplicate_timestamp_count':0,'partition_row_counts':pc,'file':path.name,'file_sha256':fsha(path),'error':None}
 except Exception as e:return {'symbol':symbol,'state':'HOLD_SOURCE_UNAVAILABLE','row_count':0,'request_count':0,'file':None,'file_sha256':None,'error':f'{type(e).__name__}:{str(e)[:500]}'}
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--out-dir',type=Path,required=True);ap.add_argument('--manifest',type=Path,required=True);a=ap.parse_args();a.out_dir.mkdir(parents=True,exist_ok=True);rows=[collect(s,a.out_dir) for s in SYMBOLS];accepted=[r['symbol'] for r in rows if r['state']=='PASS_EXACT_18M_SOURCE'];failed=[r['symbol'] for r in rows if r['state']!='PASS_EXACT_18M_SOURCE'];core_ok=all(x in accepted for x in CORE);ok=len(accepted)>=MIN_ACCEPTED and core_ok
 m={'schema_version':SCHEMA,'version':VERSION,'generated_at':datetime.now(timezone.utc).isoformat(),'state':'PASS_BROAD20_SOURCE_UNIVERSE' if ok else 'HOLD_BROAD20_SOURCE_UNIVERSE','source':{'base_url':BASE,'endpoint':ENDPOINT,'interval':INTERVAL,'start_ms':START,'end_exclusive_ms':END,'safe_chunk_bars':SAFE_BARS},'candidate_symbols':list(SYMBOLS),'core_symbols_required':list(CORE),'minimum_accepted_symbols':MIN_ACCEPTED,'accepted_symbols':accepted,'failed_symbols':failed,'accepted_count':len(accepted),'core_symbols_pass':core_ok,'results':rows,'economics_inspected':False,'d1_metrics_inspected':False,'v1_metrics_inspected':False,'t1_metrics_inspected':False,'ai_used':False,'strategy_hypotheses_defined':False,'selection_authority':False,'promotion_authority':False,'survivor_declared':False,'execution_authority':'NONE','order_authority':'BLOCKED','action':'hold','next':'FREEZE_BROAD_CROSS_SECTIONAL_ECONOMIC_PRIMITIVES_BEFORE_D1_SCORE' if ok else 'ROUTE_TO_NON_BINGX_RESEARCH_SOURCE_OR_WAIT_FOR_NEW_NATIVE_DATA_AUTHORITY'}
 m['dataset_sha256']=stable([{'symbol':r['symbol'],'file_sha256':r['file_sha256']} for r in rows if r['file_sha256']]);m['receipt_sha256']=stable(m);a.manifest.write_text(json.dumps(m,indent=2,sort_keys=True)+'\n');print(json.dumps({'state':m['state'],'accepted_count':m['accepted_count'],'accepted_symbols':accepted,'failed_symbols':failed,'dataset_sha256':m['dataset_sha256'],'receipt_sha256':m['receipt_sha256']},sort_keys=True));return 0
if __name__=='__main__':raise SystemExit(main())
