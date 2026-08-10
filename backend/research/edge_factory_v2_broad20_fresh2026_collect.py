from __future__ import annotations

import argparse,csv,gzip,hashlib,json,time
import urllib.parse,urllib.request
from datetime import datetime,timezone
from decimal import Decimal,InvalidOperation
from pathlib import Path
from typing import Any,Mapping,Sequence

VERSION='ZEL_EDGE_FACTORY_V2_BROAD20_FRESH2026_COLLECT_V1'
BASE='https://open-api.bingx.com';ENDPOINT='/openApi/swap/v3/quote/klines';INTERVAL='1h';STEP=3_600_000;LIMIT=1000;SAFE=999
START=1767225600000;END=1785542400000;EXPECTED=5088
SYMBOLS=('BTC-USDT','ETH-USDT','SOL-USDT','XRP-USDT','DOGE-USDT','ADA-USDT','LINK-USDT','LTC-USDT','BCH-USDT','DOT-USDT','AVAX-USDT','TRX-USDT','ETC-USDT','UNI-USDT','XLM-USDT','ATOM-USDT','NEAR-USDT','FIL-USDT','APT-USDT','ARB-USDT')
FIELDS=('timestamp_ms','open','high','low','close','volume')

def stable(v:Any)->str:return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def fsha(p:Path)->str:
 h=hashlib.sha256()
 with p.open('rb') as f:
  for c in iter(lambda:f.read(1<<20),b''):h.update(c)
 return h.hexdigest()
def dec(v:Any,name:str)->str:
 try:n=Decimal(str(v))
 except (InvalidOperation,ValueError) as e:raise RuntimeError(f'INVALID_DECIMAL:{name}:{v}') from e
 if not n.is_finite():raise RuntimeError(f'NONFINITE:{name}')
 if name!='volume' and n<=0:raise RuntimeError(f'NONPOSITIVE:{name}')
 if name=='volume' and n<0:raise RuntimeError('NEGATIVE_VOLUME')
 return format(n,'f')
def extract(obj:Any):
 if isinstance(obj,list):return obj
 if isinstance(obj,Mapping):
  for k in ('data','rows','items','list','klines'):
   v=obj.get(k)
   if isinstance(v,list):return v
 raise RuntimeError('ROWS_MISSING')
def norm(r:Any)->dict[str,Any]:
 if isinstance(r,Mapping):v={'timestamp_ms':r.get('openTime',r.get('time',r.get('timestamp'))),'open':r.get('open'),'high':r.get('high'),'low':r.get('low'),'close':r.get('close'),'volume':r.get('volume',r.get('vol',0))}
 elif isinstance(r,Sequence) and not isinstance(r,(str,bytes)) and len(r)>=6:v={'timestamp_ms':r[0],'open':r[1],'high':r[2],'low':r[3],'close':r[4],'volume':r[5]}
 else:raise RuntimeError('ROW_SHAPE')
 ts=int(float(v['timestamp_ms']));row={'timestamp_ms':ts,'open':dec(v['open'],'open'),'high':dec(v['high'],'high'),'low':dec(v['low'],'low'),'close':dec(v['close'],'close'),'volume':dec(v['volume'],'volume')}
 o,h,l,c=map(Decimal,(row['open'],row['high'],row['low'],row['close']))
 if h<max(o,c,l) or l>min(o,c,h):raise RuntimeError(f'OHLC_INVALID:{ts}')
 return row
def request(symbol:str,a:int,b:int,attempts:int=5):
 q={'symbol':symbol,'interval':INTERVAL,'startTime':a,'endTime':b,'limit':LIMIT};url=BASE+ENDPOINT+'?'+urllib.parse.urlencode(q);last=''
 for i in range(1,attempts+1):
  try:
   req=urllib.request.Request(url,headers={'Accept':'application/json','User-Agent':VERSION})
   with urllib.request.urlopen(req,timeout=25) as resp:obj=json.loads(resp.read())
   if isinstance(obj,dict) and int(obj.get('code',0))!=0:raise RuntimeError(f"CODE:{obj.get('code')}:{obj.get('msg')}")
   data=obj.get('data',obj) if isinstance(obj,dict) else obj
   return sorted((norm(x) for x in extract(data)),key=lambda x:x['timestamp_ms'])
  except Exception as e:
   last=f'{type(e).__name__}:{str(e)[:200]}'
   if i<attempts:time.sleep(min(2**i,10))
 raise RuntimeError(f'REQUEST_FAILED:{symbol}:{a}:{b}:{last}')
def collect(symbol:str,out:Path):
 by={};cursor=START;requests=0
 while cursor<END:
  b=min(cursor+SAFE*STEP,END);rows=request(symbol,cursor,b);requests+=1
  for row in rows:
   ts=int(row['timestamp_ms'])
   if cursor<=ts<b:
    if ts in by and by[ts]!=row:raise RuntimeError(f'CONFLICT_DUP:{symbol}:{ts}')
    by[ts]=row
  cursor=b;time.sleep(.04)
 expected=list(range(START,END,STEP));missing=[x for x in expected if x not in by];extra=[x for x in by if x<START or x>=END]
 if missing or extra:raise RuntimeError(f'COVERAGE:{symbol}:rows={len(by)}:missing={len(missing)}:extra={len(extra)}:first_missing={missing[:3]}')
 ordered=[by[x] for x in expected];p=out/f"{symbol.replace('-','')}_1h_fresh2026.csv.gz"
 with gzip.open(p,'wt',encoding='utf-8',newline='') as f:w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader();w.writerows(ordered)
 return {'symbol':symbol,'row_count':len(ordered),'request_count':requests,'first_timestamp_ms':int(ordered[0]['timestamp_ms']),'last_timestamp_ms':int(ordered[-1]['timestamp_ms']),'missing_interval_count':0,'duplicate_timestamp_count':0,'file':p.name,'file_sha256':fsha(p),'file_bytes':p.stat().st_size}
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--out-dir',type=Path,required=True);ap.add_argument('--manifest',type=Path,required=True);a=ap.parse_args();a.out_dir.mkdir(parents=True,exist_ok=True)
 if (END-START)//STEP!=EXPECTED:raise RuntimeError('EXPECTED_CONTRACT')
 rows=[collect(s,a.out_dir) for s in SYMBOLS]
 if any(r['row_count']!=EXPECTED for r in rows):raise RuntimeError('ROW_COUNT')
 m={'schema_version':'zel.edge_factory_v2.broad20_fresh2026_source.v1','version':VERSION,'generated_at':datetime.now(timezone.utc).isoformat(),'state':'PASS_BROAD20_FRESH2026_SOURCE','source':{'base_url':BASE,'endpoint':ENDPOINT,'interval':INTERVAL,'start_ms':START,'end_exclusive_ms':END},'symbols':list(SYMBOLS),'rows_per_symbol':EXPECTED,'total_rows':EXPECTED*20,'results':rows,'economics_inspected':False,'market_neutral_rule_defined':False,'ai_used':False,'survivor_declared':False,'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED','action':'hold','next':'FREEZE_ONE_XSEC_MOMENTUM_LONG4_SHORT4_RULE_BEFORE_ANY_FRESH2026_SCORE'}
 m['dataset_sha256']=stable([{'symbol':r['symbol'],'file_sha256':r['file_sha256']} for r in rows]);m['receipt_sha256']=stable(m);a.manifest.parent.mkdir(parents=True,exist_ok=True);a.manifest.write_text(json.dumps(m,indent=2,sort_keys=True)+'\n');print(json.dumps({'state':m['state'],'total_rows':m['total_rows'],'dataset_sha256':m['dataset_sha256'],'receipt_sha256':m['receipt_sha256']},sort_keys=True));return 0
if __name__=='__main__':raise SystemExit(main())
