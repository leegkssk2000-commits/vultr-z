#!/usr/bin/env python3
from __future__ import annotations
import json,hashlib
from pathlib import Path
from backend.research.architecture_factory.a1_gen2_4h_range_atr_regime_dev_v1 import signal as base_signal,atr,metrics,HOLD
from backend.research.architecture_factory.a1_gen2_generic_dev_econ_v1 import SYMBOLS,bars
from backend.research.architecture_factory.a1_gen2_4h_range_atr_oos_v1 import prior_bars

VOL_N=100

def signal(rs,i):
 side=base_signal(rs,i)
 if side is None or i<VOL_N:return None
 a=atr(rs,i,14); c=float(rs[i]['close'])
 vals=[]
 for j in range(i-VOL_N+1,i+1):
  aj=atr(rs,j,14)
  if aj is not None: vals.append(aj/float(rs[j]['close']))
 if a is None or len(vals)<VOL_N-14:return None
 if not (a/c <= sum(vals)/len(vals)):return None
 return side

def collect(rs,sym):
 out=[];i=max(100,VOL_N)
 while i<len(rs)-HOLD-1:
  side=signal(rs,i)
  if side is None:i+=1;continue
  ei=i+1;xi=ei+HOLD-1;ep=float(rs[ei]['open']);xp=float(rs[xi]['close']);gross=(xp/ep-1)*10000*(1 if side=='long' else -1)
  out.append({'symbol':sym,'side':side,'gross_bps':gross,'entry_ts':int(rs[ei]['ts'])});i=xi+1
 return out

def m(rows,cost=14):return metrics([x['gross_bps'] for x in rows],float(cost))

def run():
 dev=[];prior=[]
 for sym in SYMBOLS:
  dev+=collect(bars(sym,'4h'),sym);rs,_=prior_bars(sym);prior+=collect(rs,sym)
 prior=sorted(prior,key=lambda x:x['entry_ts']);cut=len(prior)//2;w2=prior[:cut];w3=prior[cut:]
 r={'schema_version':'zel.a1_gen2_4h_range_atr_volcap_repair.v2','candidate':'4H_RANGE_ATR_PLUS_SELF_NORMALIZED_ATR_PCT_CAP','repair_axis':'ATR14/close <= own rolling100 mean ATR14/close','parameter_sweep':False,'tuned_numeric_cutoff':False,'dev':m(dev),'prior_all':m(prior),'W2':m(w2),'W3':m(w3),'cost_stress_dev':{str(c):m(dev,c) for c in (14,28,40)},'cost_stress_prior':{str(c):m(prior,c) for c in (14,28,40)},'by_symbol_prior':{s:m([x for x in prior if x['symbol']==s]) for s in SYMBOLS},'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED','live_trade_authority':'BLOCKED'}
 r['repair_promising']=bool(r['dev']['net_pnl_bps']>0 and r['dev']['profit_factor']>1 and r['W2']['net_pnl_bps']>0 and r['W2']['profit_factor']>1 and r['W3']['net_pnl_bps']>0 and r['W3']['profit_factor']>1)
 r['receipt_sha256']=hashlib.sha256(json.dumps(r,sort_keys=True,separators=(',',':')).encode()).hexdigest();return r
if __name__=='__main__':
 r=run();Path('out').mkdir(exist_ok=True);Path('out/a1_gen2_4h_range_atr_volcap_repair_v2.json').write_text(json.dumps(r,indent=2,sort_keys=True)+'\n');print('A1_GEN2_4H_RANGE_ATR_VOLCAP_REPAIR_V2='+json.dumps(r,sort_keys=True))
