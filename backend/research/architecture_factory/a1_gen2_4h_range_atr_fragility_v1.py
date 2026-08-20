#!/usr/bin/env python3
from __future__ import annotations
import json,hashlib
from pathlib import Path
from backend.research.architecture_factory.a1_gen2_4h_range_atr_hardening_v1 import collect
from backend.research.architecture_factory.a1_gen2_4h_range_atr_regime_dev_v1 import metrics

def run():
 rows=collect(); g=[x['gross_bps'] for x in rows]; base=metrics(g)
 ordered=sorted(range(len(rows)),key=lambda i:abs(rows[i]['gross_bps']),reverse=True)
 loo=[]
 for k in (1,3,5,10):
  drop=set(ordered[:k]); m=metrics([x['gross_bps'] for i,x in enumerate(rows) if i not in drop]); loo.append({'drop_abs_extremes':k,'metrics':m})
 chunks=[]; n=len(rows)
 for parts in (2,3,4):
  for p in range(parts):
   a=(n*p)//parts;b=(n*(p+1))//parts;m=metrics([x['gross_bps'] for x in rows[a:b]]);chunks.append({'parts':parts,'part':p+1,'metrics':m})
 worst_loo=min((x['metrics']['profit_factor'] or 0) for x in loo); positive_loo=all((x['metrics']['net_pnl_bps'] or 0)>0 and (x['metrics']['profit_factor'] or 0)>1 for x in loo)
 positive_halves=all((x['metrics']['net_pnl_bps'] or 0)>0 and (x['metrics']['profit_factor'] or 0)>1 for x in chunks if x['parts']==2)
 gate=bool(base['trades']>=80 and positive_loo and positive_halves and worst_loo>1.10)
 r={'schema_version':'zel.a1_gen2_4h_range_atr_fragility.v1','candidate':'4H_RANGE_BREAKOUT_PLUS_ATR14_ABOVE_ITS_14BAR_MEAN','frozen_parameters':True,'development_only':True,'prospective':False,'metrics':base,'leave_extremes_out':loo,'chronological_chunks':chunks,'fragility_gate':{'positive_leave_extremes_out':positive_loo,'positive_halves':positive_halves,'worst_loo_pf':worst_loo,'pass':gate},'survivor':False,'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED','live_trade_authority':'BLOCKED'}
 r['receipt_sha256']=hashlib.sha256(json.dumps(r,sort_keys=True,separators=(',',':')).encode()).hexdigest();return r
if __name__=='__main__':
 r=run();Path('out').mkdir(exist_ok=True);Path('out/a1_gen2_4h_range_atr_fragility_v1.json').write_text(json.dumps(r,indent=2,sort_keys=True)+'\n');print('A1_GEN2_4H_RANGE_ATR_FRAGILITY_V1='+json.dumps(r,sort_keys=True))
