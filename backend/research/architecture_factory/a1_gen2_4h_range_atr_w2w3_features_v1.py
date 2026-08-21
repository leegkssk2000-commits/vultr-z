#!/usr/bin/env python3
from __future__ import annotations
import json,hashlib,statistics
from pathlib import Path
from backend.research.architecture_factory.a1_gen2_4h_range_atr_oos_v1 import prior_bars
from backend.research.architecture_factory.a1_gen2_4h_range_atr_regime_dev_v1 import signal,atr,HOLD
from backend.research.architecture_factory.a1_gen2_4h_range_breakout_dev_v1 import RANGE_N,_window_range
from backend.research.architecture_factory.a1_gen2_generic_dev_econ_v1 import SYMBOLS

def med(xs): return statistics.median(xs) if xs else None

def collect():
 out=[]
 for sym in SYMBOLS:
  rs,_=prior_bars(sym); i=50
  while i<len(rs)-HOLD-1:
   side=signal(rs,i)
   if side is None:i+=1;continue
   ei=i+1;xi=ei+HOLD-1;ep=float(rs[ei]['open']);xp=float(rs[xi]['close']);gross=(xp/ep-1)*10000*(1 if side=='long' else -1)
   a=atr(rs,i,14); ap=atr(rs,i-1,14); c=float(rs[i]['close'])
   hist=[atr(rs,j,14) for j in range(i-13,i+1)]; am=sum(hist)/len(hist)
   cur_hi,cur_lo,cur_w=_window_range(rs,i-RANGE_N,i); prev_hi,prev_lo,prev_w=_window_range(rs,i-RANGE_N*2,i-RANGE_N)
   pen=(c-cur_hi if side=='long' else cur_lo-c)
   out.append({'symbol':sym,'side':side,'gross_bps':gross,'entry_ts':int(rs[ei]['ts']),'atr_pct':a/c,'atr_ratio':a/am,'atr_accel':a/ap if ap else None,'contraction':cur_w/prev_w if prev_w else None,'penetration_atr':pen/a if a else None})
   i=xi+1
 return sorted(out,key=lambda x:x['entry_ts'])

def summary(rows):
 fs=['atr_pct','atr_ratio','atr_accel','contraction','penetration_atr']
 return {'trades':len(rows),'net_bps':sum(x['gross_bps']-14 for x in rows),'features':{f:{'median':med([x[f] for x in rows if x[f] is not None]),'win_median':med([x[f] for x in rows if x['gross_bps']-14>0 and x[f] is not None]),'loss_median':med([x[f] for x in rows if x['gross_bps']-14<=0 and x[f] is not None])} for f in fs}}

def run():
 rows=collect();cut=len(rows)//2;w2=rows[:cut];w3=rows[cut:]
 r={'schema_version':'zel.a1_gen2_4h_range_atr_w2w3_features.v1','diagnostic_only':True,'W2':summary(w2),'W3':summary(w3),'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED','live_trade_authority':'BLOCKED'}
 r['receipt_sha256']=hashlib.sha256(json.dumps(r,sort_keys=True,separators=(',',':')).encode()).hexdigest();return r
if __name__=='__main__':
 r=run();Path('out').mkdir(exist_ok=True);Path('out/a1_gen2_4h_range_atr_w2w3_features_v1.json').write_text(json.dumps(r,indent=2,sort_keys=True)+'\n');print('A1_GEN2_4H_RANGE_ATR_W2W3_FEATURES_V1='+json.dumps(r,sort_keys=True))
