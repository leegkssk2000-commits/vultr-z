#!/usr/bin/env python3
from __future__ import annotations
import json,hashlib
from pathlib import Path
from backend.research.architecture_factory.a1_gen2_4h_range_breakout_dev_v1 import range_signal, HOLD
from backend.research.architecture_factory.a1_gen2_4h_range_atr_regime_dev_v1 import atr, metrics
from backend.research.architecture_factory.a1_gen2_generic_dev_econ_v1 import SYMBOLS,bars
from backend.research.architecture_factory.a1_gen2_4h_range_atr_oos_v1 import prior_bars

RANGE_N=6

def signal(rs,i):
 side=range_signal(rs,i)
 if side is None or i<28:return None
 a=atr(rs,i,14)
 hist=[atr(rs,j,14) for j in range(i-13,i+1)]
 if a is None or any(x is None for x in hist):return None
 if not (a > sum(hist)/len(hist)):return None
 hi=max(float(x['high']) for x in rs[i-RANGE_N:i]); lo=min(float(x['low']) for x in rs[i-RANGE_N:i]); c=float(rs[i]['close'])
 pen=(c-hi) if side=='long' else (lo-c)
 if pen<0 or pen>a:return None
 return side

def collect(rs,sym):
 out=[];i=50
 while i<len(rs)-HOLD-1:
  side=signal(rs,i)
  if side is None:i+=1;continue
  ei=i+1;xi=ei+HOLD-1;ep=float(rs[ei]['open']);xp=float(rs[xi]['close']);gross=(xp/ep-1)*10000*(1 if side=='long' else -1)
  out.append({'symbol':sym,'side':side,'gross_bps':gross,'entry_ts':int(rs[ei]['ts'])});i=xi+1
 return out

def m(rows,c=14):return metrics([x['gross_bps'] for x in rows],float(c))

def run():
 dev=[];prior=[]
 for sym in SYMBOLS:
  dev+=collect(bars(sym,'4h'),sym)
  prs,_=prior_bars(sym);prior+=collect(prs,sym)
 prior=sorted(prior,key=lambda x:x['entry_ts']);cut=len(prior)//2;w2=prior[:cut];w3=prior[cut:]
 r={'schema_version':'zel.a1_gen2_4h_range_atr_exhaustion_repair.v3','candidate':'4H_RANGE_ATR_PLUS_PENETRATION_LE_1ATR','repair_axis':'breakout_exhaustion_veto','parameter_sweep':False,'frozen_natural_unit':'penetration_le_1ATR','dev':m(dev),'prior_all':m(prior),'W2':m(w2),'W3':m(w3),'cost_dev':{str(c):m(dev,c) for c in (14,28,40)},'cost_prior':{str(c):m(prior,c) for c in (14,28,40)},'by_symbol_prior':{s:m([x for x in prior if x['symbol']==s]) for s in SYMBOLS},'by_side_prior':{s:m([x for x in prior if x['side']==s]) for s in ('long','short') if any(x['side']==s for x in prior)},'repair_promising':False,'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED','live_trade_authority':'BLOCKED'}
 d=r['dev'];p=r['prior_all'];w3m=r['W3'];r['repair_promising']=bool((d['net_pnl_bps'] or 0)>0 and (d['profit_factor'] or 0)>1 and (p['net_pnl_bps'] or 0)>0 and (p['profit_factor'] or 0)>1 and (w3m['net_pnl_bps'] or 0)>0 and (w3m['profit_factor'] or 0)>1)
 r['receipt_sha256']=hashlib.sha256(json.dumps(r,sort_keys=True,separators=(',',':')).encode()).hexdigest();return r
if __name__=='__main__':
 r=run();Path('out').mkdir(exist_ok=True);Path('out/a1_gen2_4h_range_atr_exhaustion_repair_v3.json').write_text(json.dumps(r,indent=2,sort_keys=True)+'\n');print('A1_GEN2_4H_RANGE_ATR_EXHAUSTION_REPAIR_V3='+json.dumps(r,sort_keys=True))
