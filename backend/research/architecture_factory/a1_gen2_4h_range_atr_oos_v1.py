#!/usr/bin/env python3
from __future__ import annotations
import json,hashlib,urllib.parse,urllib.request
from pathlib import Path
from backend.research.architecture_factory.a1_gen2_4h_range_atr_regime_dev_v1 import signal,metrics,HOLD
from backend.research.architecture_factory.a1_gen2_generic_dev_econ_v1 import KLINE_API,SYMBOLS,bars,_decode_rows

PAGES=3
INTERVAL='4h'

def req(params):
 url=KLINE_API+'?'+urllib.parse.urlencode(params)
 with urllib.request.urlopen(url,timeout=30) as r:
  x=json.loads(r.read().decode())
 if isinstance(x,dict) and x.get('code') not in (None,0): raise RuntimeError(f"BINGX:{x.get('code')}:{x.get('msg')}")
 return x

def prior_bars(sym):
 dev=bars(sym,INTERVAL)
 if not dev:return [],None
 first=int(dev[0]['ts']); end=first-1; all_rows={}
 for _ in range(PAGES):
  page=sorted(_decode_rows(req({'symbol':sym,'interval':INTERVAL,'limit':1000,'endTime':end})),key=lambda z:z['ts'])
  page=[r for r in page if int(r['ts'])<first]
  if not page:break
  for r in page:all_rows[int(r['ts'])]=r
  oldest=int(page[0]['ts']); end=oldest-1
  if len(page)<900:break
 return [all_rows[k] for k in sorted(all_rows)],first

def collect(rs,sym):
 out=[]; i=50
 while i<len(rs)-HOLD-1:
  side=signal(rs,i)
  if side is None:i+=1;continue
  ei=i+1;xi=ei+HOLD-1; ep=float(rs[ei]['open']); xp=float(rs[xi]['close']); gross=(xp/ep-1)*10000*(1 if side=='long' else -1)
  out.append({'symbol':sym,'side':side,'gross_bps':gross,'entry_ts':int(rs[ei]['ts'])}); i=xi+1
 return out

def m(rows,cost=14):return metrics([x['gross_bps'] for x in rows],float(cost))

def run():
 rows=[]; src={}
 for sym in SYMBOLS:
  rs,dev_first=prior_bars(sym); r=collect(rs,sym); rows+=r; src[sym]={'bars':len(rs),'trades':len(r),'first_ts':int(rs[0]['ts']) if rs else None,'last_ts':int(rs[-1]['ts']) if rs else None,'dev_first_ts':dev_first}
 rows=sorted(rows,key=lambda x:x['entry_ts']); n=len(rows); cut=n//2; w2=rows[:cut];w3=rows[cut:]
 base=m(rows); costs={str(c):m(rows,c) for c in (14,28,40)}; by_symbol={s:m([x for x in rows if x['symbol']==s]) for s in SYMBOLS}; by_side={s:m([x for x in rows if x['side']==s]) for s in ('long','short') if any(x['side']==s for x in rows)}
 windows={'W2':m(w2),'W3':m(w3)}
 gate=bool(n>=80 and all((windows[w]['net_pnl_bps'] or 0)>0 and (windows[w]['profit_factor'] or 0)>1 for w in windows) and (costs['28']['net_pnl_bps'] or 0)>0 and (costs['28']['profit_factor'] or 0)>1 and (costs['40']['net_pnl_bps'] or 0)>0 and (costs['40']['profit_factor'] or 0)>1 and all((x['net_pnl_bps'] or 0)>0 and (x['profit_factor'] or 0)>1 for x in by_symbol.values()))
 r={'schema_version':'zel.a1_gen2_4h_range_atr_oos.v1','candidate':'4H_RANGE_BREAKOUT_PLUS_ATR14_ABOVE_ITS_14BAR_MEAN','frozen_parameters':True,'historical_oos_only':True,'prospective':False,'development_overlap':False,'metrics':base,'cost_stress':costs,'windows':windows,'by_symbol':by_symbol,'by_side':by_side,'source_summary':src,'oos_gate':{'pass':gate,'min_trades':80,'w2_w3_positive':all((windows[w]['net_pnl_bps'] or 0)>0 and (windows[w]['profit_factor'] or 0)>1 for w in windows),'cost40_positive':(costs['40']['net_pnl_bps'] or 0)>0 and (costs['40']['profit_factor'] or 0)>1},'survivor':False,'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED','live_trade_authority':'BLOCKED'}
 r['receipt_sha256']=hashlib.sha256(json.dumps(r,sort_keys=True,separators=(',',':')).encode()).hexdigest();return r
if __name__=='__main__':
 r=run();Path('out').mkdir(exist_ok=True);Path('out/a1_gen2_4h_range_atr_oos_v1.json').write_text(json.dumps(r,indent=2,sort_keys=True)+'\n');print('A1_GEN2_4H_RANGE_ATR_OOS_V1='+json.dumps(r,sort_keys=True))
