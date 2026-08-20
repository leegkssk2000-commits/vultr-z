#!/usr/bin/env python3
from __future__ import annotations
import json, hashlib
from pathlib import Path
from backend.research.architecture_factory.a1_gen2_4h_trend_breakout_dev_v1 import penetration_base, metrics
from backend.research.architecture_factory.a1_gen2_generic_dev_econ_v1 import BOUNDARY, SYMBOLS, bars

HOLD=6
RANGE_N=6

def _window_range(rs,a,b):
 hi=max(float(x['high']) for x in rs[a:b]); lo=min(float(x['low']) for x in rs[a:b]); return hi,lo,hi-lo

def signal(rs,i):
 side=penetration_base(rs,i)
 if side is None or i < RANGE_N*2:return None
 cur_hi,cur_lo,cur_w=_window_range(rs,i-RANGE_N,i)
 prev_hi,prev_lo,prev_w=_window_range(rs,i-RANGE_N*2,i-RANGE_N)
 if not (cur_w < prev_w):return None
 c=float(rs[i]['close'])
 if side=='long' and c>cur_hi:return 'long'
 if side=='short' and c<cur_lo:return 'short'
 return None

def run():
 rows=[];src={}
 for sym in SYMBOLS:
  rs=bars(sym,'4h');src[sym]={'bars':len(rs),'first_ts':int(rs[0]['ts']) if rs else None,'last_ts':int(rs[-1]['ts']) if rs else None};i=max(50,RANGE_N*2)
  while i<len(rs)-HOLD-1:
   side=signal(rs,i)
   if side is None:i+=1;continue
   ei=i+1;xi=ei+HOLD-1;ep=float(rs[ei]['open']);xp=float(rs[xi]['close']);gross=(xp/ep-1)*10000*(1 if side=='long' else -1)
   rows.append({'symbol':sym,'side':side,'gross_bps':gross});i=xi+1
 g=[x['gross_bps'] for x in rows];m=metrics(g)
 r={'schema_version':'zel.a1_gen2_4h_range_breakout_dev.v1','boundary':BOUNDARY,'development_only':True,'prospective':False,'isolated_axis':True,'parameter_sweep':False,'tuned_thresholds':0,'hold_bars':HOLD,'range_bars':RANGE_N,'architecture':'4H_PENETRATION_PLUS_6BAR_RANGE_CONTRACTION_BREAKOUT','metrics':m,'economic_candidate':bool(m['trades']>=40 and (m['net_expectancy_bps'] or 0)>0 and (m['profit_factor'] or 0)>1 and (m['payoff'] or 0)>=1),'by_symbol':{s:metrics([x['gross_bps'] for x in rows if x['symbol']==s]) for s in SYMBOLS},'by_side':{s:metrics([x['gross_bps'] for x in rows if x['side']==s]) for s in ('long','short') if any(x['side']==s for x in rows)},'cost_stress':{str(c):metrics(g,float(c)) for c in (14,28,40)},'source_summary':src,'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED','live_trade_authority':'BLOCKED'}
 r['receipt_sha256']=hashlib.sha256(json.dumps(r,sort_keys=True,separators=(',',':')).encode()).hexdigest();return r

if __name__=='__main__':
 r=run();Path('out').mkdir(exist_ok=True);Path('out/a1_gen2_4h_range_breakout_dev_v1.json').write_text(json.dumps(r,indent=2,sort_keys=True)+'\n');print('A1_GEN2_4H_RANGE_BREAKOUT='+json.dumps(r,sort_keys=True))
