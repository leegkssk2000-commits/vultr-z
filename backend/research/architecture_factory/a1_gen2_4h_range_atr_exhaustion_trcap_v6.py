#!/usr/bin/env python3
from __future__ import annotations
import json,hashlib
from pathlib import Path
from backend.research.architecture_factory.a1_gen2_4h_range_atr_exhaustion_repair_v3 import signal as signal_v3,m
from backend.research.architecture_factory.a1_gen2_4h_range_atr_regime_dev_v1 import atr
from backend.research.architecture_factory.a1_gen2_generic_dev_econ_v1 import SYMBOLS,bars
from backend.research.architecture_factory.a1_gen2_4h_range_atr_oos_v1 import prior_bars
HOLD=6

def signal(rs,i,sym):
 s=signal_v3(rs,i)
 if s is None:return None
 if sym=='ETH-USDT' and s!='short':return None
 a=atr(rs,i,14)
 if a is None:return None
 pc=float(rs[i-1]['close']);tr=max(float(rs[i]['high'])-float(rs[i]['low']),abs(float(rs[i]['high'])-pc),abs(float(rs[i]['low'])-pc))
 if tr>2.0*a:return None
 return s

def collect(rs,sym):
 out=[];i=50
 while i<len(rs)-HOLD-1:
  s=signal(rs,i,sym)
  if s is None:i+=1;continue
  ei=i+1;xi=ei+HOLD-1;ep=float(rs[ei]['open']);xp=float(rs[xi]['close']);g=(xp/ep-1)*10000*(1 if s=='long' else -1)
  out.append({'symbol':sym,'side':s,'gross_bps':g,'entry_ts':int(rs[ei]['ts'])});i=xi+1
 return out

def run():
 dev=[];prior=[]
 for sym in SYMBOLS:
  dev+=collect(bars(sym,'4h'),sym);prs,_=prior_bars(sym);prior+=collect(prs,sym)
 prior=sorted(prior,key=lambda x:x['entry_ts']);cut=len(prior)//2;w2=prior[:cut];w3=prior[cut:]
 r={'schema_version':'zel.a1_gen2_4h_range_atr_exhaustion_trcap.v6','candidate':'V5_OWNERSHIP_PLUS_SIGNAL_TR_LE_2ATR','repair_axis':'signal_bar_range_exhaustion','frozen_natural_unit':'true_range_le_2ATR','parameter_sweep':False,'dev':m(dev),'prior_all':m(prior),'W2':m(w2),'W3':m(w3),'cost_dev':{str(c):m(dev,c) for c in (14,28,40)},'cost_prior':{str(c):m(prior,c) for c in (14,28,40)},'retention_vs_v5_prior':len(prior)/39.0,'survivor_candidate':False,'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED'}
 d,a,b=r['dev'],r['W2'],r['W3'];r['survivor_candidate']=bool(r['retention_vs_v5_prior']>=0.60 and all((x['net_pnl_bps'] or 0)>0 and (x['profit_factor'] or 0)>=1 and (x['payoff'] or 0)>=1 for x in (d,a,b)) and (r['cost_prior']['28']['net_pnl_bps'] or 0)>0 and (r['cost_prior']['28']['profit_factor'] or 0)>=1)
 r['receipt_sha256']=hashlib.sha256(json.dumps(r,sort_keys=True,separators=(',',':')).encode()).hexdigest();return r
if __name__=='__main__':
 r=run();Path('out').mkdir(exist_ok=True);Path('out/a1_gen2_4h_range_atr_exhaustion_trcap_v6.json').write_text(json.dumps(r,indent=2,sort_keys=True)+'\n');print('A1_GEN2_4H_RANGE_ATR_EXHAUSTION_TRCAP_V6='+json.dumps(r,sort_keys=True))
# trigger
