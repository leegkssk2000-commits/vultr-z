#!/usr/bin/env python3
from __future__ import annotations
import json,hashlib
from pathlib import Path
from backend.research.architecture_factory.a1_gen2_4h_range_atr_exhaustion_repair_v3 import collect as collect_v3, m
from backend.research.architecture_factory.a1_gen2_generic_dev_econ_v1 import SYMBOLS,bars
from backend.research.architecture_factory.a1_gen2_4h_range_atr_oos_v1 import prior_bars

def owned(rows):
 out=[]
 for x in rows:
  if x['symbol']=='BTC-USDT': out.append(x)
  elif x['symbol']=='ETH-USDT' and x['side']=='short': out.append(x)
 return out

def run():
 dev=[];prior=[]
 for sym in SYMBOLS:
  dev+=owned(collect_v3(bars(sym,'4h'),sym))
  prs,_=prior_bars(sym);prior+=owned(collect_v3(prs,sym))
 prior=sorted(prior,key=lambda x:x['entry_ts']);cut=len(prior)//2;w2=prior[:cut];w3=prior[cut:]
 r={'schema_version':'zel.a1_gen2_4h_range_atr_ownership_repair.v5','candidate':'4H_RANGE_ATR_1ATR_OWNERSHIP_SPLIT','repair_axis':'symbol_side_ownership','ownership_rule':'BTC long+short; ETH short only','parameter_sweep':False,'dev':m(dev),'prior_all':m(prior),'W2':m(w2),'W3':m(w3),'cost_dev':{str(c):m(dev,c) for c in (14,28,40)},'cost_prior':{str(c):m(prior,c) for c in (14,28,40)},'by_symbol_prior':{s:m([x for x in prior if x['symbol']==s]) for s in SYMBOLS},'by_side_prior':{s:m([x for x in prior if x['side']==s]) for s in ('long','short') if any(x['side']==s for x in prior)},'repair_promising':False,'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED','live_trade_authority':'BLOCKED'}
 d,p,w3m=r['dev'],r['prior_all'],r['W3'];r['repair_promising']=bool((d['net_pnl_bps'] or 0)>0 and (d['profit_factor'] or 0)>1 and (p['net_pnl_bps'] or 0)>0 and (p['profit_factor'] or 0)>1 and (w3m['net_pnl_bps'] or 0)>0 and (w3m['profit_factor'] or 0)>1)
 r['receipt_sha256']=hashlib.sha256(json.dumps(r,sort_keys=True,separators=(',',':')).encode()).hexdigest();return r
if __name__=='__main__':
 r=run();Path('out').mkdir(exist_ok=True);Path('out/a1_gen2_4h_range_atr_ownership_repair_v5.json').write_text(json.dumps(r,indent=2,sort_keys=True)+'\n');print('A1_GEN2_4H_RANGE_ATR_OWNERSHIP_REPAIR_V5='+json.dumps(r,sort_keys=True))
