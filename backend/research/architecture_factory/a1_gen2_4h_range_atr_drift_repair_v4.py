#!/usr/bin/env python3
from __future__ import annotations
import json,hashlib
from pathlib import Path
from backend.research.architecture_factory.a1_gen2_4h_range_atr_exhaustion_repair_v3 import signal as exhaustion_signal, HOLD, m
from backend.research.architecture_factory.a1_gen2_generic_dev_econ_v1 import SYMBOLS,bars
from backend.research.architecture_factory.a1_gen2_4h_range_atr_oos_v1 import prior_bars

RANGE_N=6

def signal(rs,i):
 side=exhaustion_signal(rs,i)
 if side is None or i<2*RANGE_N:return None
 cur=rs[i-RANGE_N:i]; prev=rs[i-2*RANGE_N:i-RANGE_N]
 cur_mid=(max(float(x['high']) for x in cur)+min(float(x['low']) for x in cur))/2
 prev_mid=(max(float(x['high']) for x in prev)+min(float(x['low']) for x in prev))/2
 if side=='long' and not (cur_mid>prev_mid):return None
 if side=='short' and not (cur_mid<prev_mid):return None
 return side

def collect(rs,sym):
 out=[];i=50
 while i<len(rs)-HOLD-1:
  side=signal(rs,i)
  if side is None:i+=1;continue
  ei=i+1;xi=ei+HOLD-1;ep=float(rs[ei]['open']);xp=float(rs[xi]['close']);gross=(xp/ep-1)*10000*(1 if side=='long' else -1)
  out.append({'symbol':sym,'side':side,'gross_bps':gross,'entry_ts':int(rs[ei]['ts'])});i=xi+1
 return out

def run():
 dev=[];prior=[]
 for sym in SYMBOLS:
  dev+=collect(bars(sym,'4h'),sym)
  prs,_=prior_bars(sym);prior+=collect(prs,sym)
 prior=sorted(prior,key=lambda x:x['entry_ts']);cut=len(prior)//2;w2=prior[:cut];w3=prior[cut:]
 r={'schema_version':'zel.a1_gen2_4h_range_atr_drift_repair.v4','candidate':'4H_RANGE_ATR_EXHAUSTION_PLUS_RANGE_MIDPOINT_DRIFT','repair_axis':'range_drift_alignment','parameter_sweep':False,'dev':m(dev),'prior_all':m(prior),'W2':m(w2),'W3':m(w3),'cost_dev':{str(c):m(dev,c) for c in (14,28,40)},'cost_prior':{str(c):m(prior,c) for c in (14,28,40)},'by_symbol_prior':{s:m([x for x in prior if x['symbol']==s]) for s in SYMBOLS},'by_side_prior':{s:m([x for x in prior if x['side']==s]) for s in ('long','short') if any(x['side']==s for x in prior)},'repair_promising':False,'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED','live_trade_authority':'BLOCKED'}
 d=r['dev'];p=r['prior_all'];w3m=r['W3'];r['repair_promising']=bool((d['net_pnl_bps'] or 0)>0 and (d['profit_factor'] or 0)>1 and (p['net_pnl_bps'] or 0)>0 and (p['profit_factor'] or 0)>1 and (w3m['net_pnl_bps'] or 0)>0 and (w3m['profit_factor'] or 0)>1)
 r['receipt_sha256']=hashlib.sha256(json.dumps(r,sort_keys=True,separators=(',',':')).encode()).hexdigest();return r
if __name__=='__main__':
 r=run();Path('out').mkdir(exist_ok=True);Path('out/a1_gen2_4h_range_atr_drift_repair_v4.json').write_text(json.dumps(r,indent=2,sort_keys=True)+'\n');print('A1_GEN2_4H_RANGE_ATR_DRIFT_REPAIR_V4='+json.dumps(r,sort_keys=True))
