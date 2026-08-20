#!/usr/bin/env python3
from __future__ import annotations
import json,hashlib
from pathlib import Path
from backend.research.architecture_factory.a1_gen2_4h_range_breakout_dev_v1 import signal as range_signal, metrics, HOLD
from backend.research.architecture_factory.a1_gen2_generic_dev_econ_v1 import BOUNDARY,SYMBOLS,bars

def tr(rs,i):
 if i<1:return None
 h=float(rs[i]['high']);l=float(rs[i]['low']);pc=float(rs[i-1]['close'])
 return max(h-l,abs(h-pc),abs(l-pc))
def atr(rs,i,n=14):
 if i<n:return None
 xs=[tr(rs,j) for j in range(i-n+1,i+1)]
 return sum(xs)/n if all(x is not None for x in xs) else None
def signal(rs,i):
 side=range_signal(rs,i)
 if side is None or i<28:return None
 a=atr(rs,i,14)
 hist=[atr(rs,j,14) for j in range(i-13,i+1)]
 if a is None or any(x is None for x in hist):return None
 if not (a > sum(hist)/len(hist)):return None
 return side

def run():
 rows=[];src={}
 for sym in SYMBOLS:
  rs=bars(sym,'4h');src[sym]={'bars':len(rs),'first_ts':int(rs[0]['ts']) if rs else None,'last_ts':int(rs[-1]['ts']) if rs else None};i=50
  while i<len(rs)-HOLD-1:
   side=signal(rs,i)
   if side is None:i+=1;continue
   ei=i+1;xi=ei+HOLD-1;ep=float(rs[ei]['open']);xp=float(rs[xi]['close']);gross=(xp/ep-1)*10000*(1 if side=='long' else -1)
   rows.append({'symbol':sym,'side':side,'gross_bps':gross});i=xi+1
 g=[x['gross_bps'] for x in rows];m=metrics(g)
 r={'schema_version':'zel.a1_gen2_4h_range_atr_regime_dev.v1','boundary':BOUNDARY,'development_only':True,'prospective':False,'isolated_axis':True,'parameter_sweep':False,'tuned_thresholds':0,'architecture':'4H_RANGE_BREAKOUT_PLUS_ATR14_ABOVE_ITS_14BAR_MEAN','metrics':m,'economic_candidate':bool(m['trades']>=40 and (m['net_expectancy_bps'] or 0)>0 and (m['profit_factor'] or 0)>1 and (m['payoff'] or 0)>=1),'by_symbol':{s:metrics([x['gross_bps'] for x in rows if x['symbol']==s]) for s in SYMBOLS},'by_side':{s:metrics([x['gross_bps'] for x in rows if x['side']==s]) for s in ('long','short') if any(x['side']==s for x in rows)},'cost_stress':{str(c):metrics(g,float(c)) for c in (14,28,40)},'source_summary':src,'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED','live_trade_authority':'BLOCKED'}
 r['receipt_sha256']=hashlib.sha256(json.dumps(r,sort_keys=True,separators=(',',':')).encode()).hexdigest();return r
if __name__=='__main__':
 r=run();Path('out').mkdir(exist_ok=True);Path('out/a1_gen2_4h_range_atr_regime_dev_v1.json').write_text(json.dumps(r,indent=2,sort_keys=True)+'\n');print('A1_GEN2_4H_RANGE_ATR_REGIME='+json.dumps(r,sort_keys=True))
