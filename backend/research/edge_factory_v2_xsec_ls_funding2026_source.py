from __future__ import annotations

import argparse,csv,gzip,hashlib,json,ssl,time
import urllib.parse,urllib.request
from datetime import datetime,timezone
from decimal import Decimal,InvalidOperation
from pathlib import Path
from typing import Any

BASES=('https://open-api.bingx.com','https://open-api.bingx.pro')
ENDPOINT='/openApi/swap/v2/quote/fundingRate'
SYMBOLS=('BTC-USDT','ETH-USDT','SOL-USDT','XRP-USDT','DOGE-USDT','ADA-USDT','LINK-USDT','LTC-USDT','BCH-USDT','DOT-USDT','AVAX-USDT','TRX-USDT','ETC-USDT','UNI-USDT','XLM-USDT','ATOM-USDT','NEAR-USDT','FIL-USDT','APT-USDT','ARB-USDT')
START=1767225600000;END=1785542400000;DAY=86400000;PRIMARY=7*DAY;REPAIR=DAY;MAXGAP=DAY;LIMIT=1000

def stable(v:Any)->str:return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def fsha(p:Path)->str:
 h=hashlib.sha256()
 with p.open('rb') as f:
  for c in iter(lambda:f.read(1<<20),b''):h.update(c)
 return h.hexdigest()
def ms(v:Any)->int:
 x=int(float(v));return x*1000 if x<10_000_000_000 else x
def rate(v:Any)->str:
 try:n=Decimal(str(v))
 except (InvalidOperation,ValueError) as e:raise RuntimeError(f'BAD_RATE:{v}') from e
 if not n.is_finite():raise RuntimeError('NONFINITE_RATE')
 return format(n,'f')
def rows(x:Any):
 if isinstance(x,list):return [r for r in x if isinstance(r,dict)]
 if isinstance(x,dict):
  for k in ('data','list','rows','fundingRates','result'):
   v=x.get(k)
   if isinstance(v,list):return [r for r in v if isinstance(r,dict)]
  return [x]
 return []
def get(symbol,a,b,attempts=5):
 ctx=ssl.create_default_context();last='';q={'symbol':symbol,'startTime':a,'endTime':b,'limit':LIMIT}
 for attempt in range(1,attempts+1):
  for base in BASES:
   try:
    req=urllib.request.Request(base+ENDPOINT+'?'+urllib.parse.urlencode(q),headers={'Accept':'application/json','User-Agent':'ZEL-XSEC-LS-FUNDING2026/1.0'})
    with urllib.request.urlopen(req,timeout=20,context=ctx) as resp:o=json.loads(resp.read().decode())
    if isinstance(o,dict) and o.get('code') not in (None,0,'0'):raise RuntimeError(f"CODE:{o.get('code')}:{o.get('msg')}")
    data=o.get('data',o) if isinstance(o,dict) else o;out=[]
    for r in rows(data):
     if 'fundingTime' not in r or 'fundingRate' not in r:continue
     t=ms(r['fundingTime'])
     if a<=t<b:out.append({'fundingTime':t,'fundingRate':rate(r['fundingRate'])})
    return sorted(out,key=lambda z:z['fundingTime'])
   except Exception as e:last=f'{base}:{type(e).__name__}:{str(e)[:180]}'
  if attempt<attempts:time.sleep(min(2**attempt,10))
 raise RuntimeError(f'FETCH_FAILED:{symbol}:{a}:{b}:{last}')
def windows(a,b,chunk):
 while a<b:
  n=min(a+chunk,b);yield a,n;a=n
def merge(d,rs,s):
 for r in rs:
  t=int(r['fundingTime'])
  if t in d and d[t]!=r:raise RuntimeError(f'CONFLICT:{s}:{t}')
  d[t]=r
def gaps(ts):
 out=[]
 if not ts:return [(START,END)]
 if ts[0]-START>MAXGAP:out.append((START,ts[0]))
 for a,b in zip(ts,ts[1:]):
  if b-a>MAXGAP:out.append((a,b))
 if END-ts[-1]>MAXGAP:out.append((ts[-1],END))
 return out
def collect(s,out):
 d={};n1=n2=0
 for a,b in windows(START,END,PRIMARY):merge(d,get(s,a,b),s);n1+=1;time.sleep(.02)
 before=sorted(d);det=gaps(before)
 for ga,gb in det:
  for a,b in windows(ga,gb,REPAIR):merge(d,get(s,a,b),s);n2+=1;time.sleep(.02)
 ordered=[d[k] for k in sorted(d)];ts=[r['fundingTime'] for r in ordered];rem=gaps(ts);maxgap=max((b-a for a,b in zip(ts,ts[1:])),default=0)/3600000 if ts else None;first=(ts[0]-START)/3600000 if ts else None;last=(END-ts[-1])/3600000 if ts else None
 ok=bool(ts and len(ts)==len(set(ts)) and all(b>a for a,b in zip(ts,ts[1:])) and first<=24 and last<=24 and maxgap<=24 and not rem)
 p=out/f"{s.replace('-','')}_funding2026.csv.gz"
 with gzip.open(p,'wt',encoding='utf-8',newline='') as f:w=csv.DictWriter(f,fieldnames=('fundingTime','fundingRate'));w.writeheader();w.writerows(ordered)
 return {'symbol':s,'state':'PASS_FUNDING2026_CONTINUITY' if ok else 'HOLD_FUNDING2026_GAP','row_count':len(ordered),'primary_requests':n1,'repair_requests':n2,'gaps_before':len(det),'gaps_after':len(rem),'remaining_gap_boundaries_ms':[[a,b] for a,b in rem],'first_timestamp_ms':ts[0] if ts else None,'last_timestamp_ms':ts[-1] if ts else None,'first_delay_hours':first,'last_gap_hours':last,'max_interarrival_hours':maxgap,'duplicate_timestamp_count':len(ts)-len(set(ts)),'file':p.name,'file_sha256':fsha(p)}
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--out-dir',type=Path,required=True);ap.add_argument('--manifest',type=Path,required=True);a=ap.parse_args();a.out_dir.mkdir(parents=True,exist_ok=True);rs=[collect(s,a.out_dir) for s in SYMBOLS];ok=all(r['state']=='PASS_FUNDING2026_CONTINUITY' for r in rs)
 m={'schema_version':'zel.edge_factory_v2.xsec_ls_funding2026_source.v1','generated_at':datetime.now(timezone.utc).isoformat(),'state':'PASS_XSEC_LS_FUNDING2026_SOURCE' if ok else 'HOLD_XSEC_LS_FUNDING2026_SOURCE_GAPS','source':{'endpoint':ENDPOINT,'start_ms':START,'end_exclusive_ms':END,'primary_chunk_days':7,'repair_chunk_days':1},'results':rs,'all20_pass':ok,'funding_values_logged':False,'economics_inspected':False,'candidate_entries_replayed':False,'ai_used':False,'selection_authority':False,'promotion_authority':False,'survivor_declared':False,'execution_authority':'NONE','order_authority':'BLOCKED','action':'hold','next':'REPRICE_EXACT_PRICE_EDGE_WITH_OBSERVED_FUNDING' if ok else 'HOLD_FINAL_SURVIVOR_SOURCE_GAP'}
 m['funding_dataset_sha256']=stable([{'symbol':r['symbol'],'file_sha256':r['file_sha256']} for r in rs]);m['receipt_sha256']=stable(m);a.manifest.parent.mkdir(parents=True,exist_ok=True);a.manifest.write_text(json.dumps(m,indent=2,sort_keys=True)+'\n');print(json.dumps({'state':m['state'],'funding_dataset_sha256':m['funding_dataset_sha256'],'receipt_sha256':m['receipt_sha256'],'summaries':[{k:r[k] for k in ('symbol','state','row_count','gaps_before','gaps_after','max_interarrival_hours')} for r in rs]},sort_keys=True));return 0
if __name__=='__main__':raise SystemExit(main())
