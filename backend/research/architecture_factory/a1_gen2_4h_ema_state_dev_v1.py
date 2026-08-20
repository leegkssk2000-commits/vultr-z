#!/usr/bin/env python3
from __future__ import annotations
import json, hashlib
from pathlib import Path
from backend.research.architecture_factory.a1_gen2_4h_trend_breakout_dev_v1 import penetration_base, metrics
from backend.research.architecture_factory.a1_gen2_generic_dev_econ_v1 import BOUNDARY, COST_BPS, SYMBOLS, bars

HOLD=6

def ema(rs,i,n):
 if i+1<n:return None
 k=2.0/(n+1.0)
 v=sum(float(x['close']) for x in rs[:n])/n
 for j in range(n,i+1):v=float(rs[j]['close'])*k+v*(1-k)
 return v

def signal(mode,rs,i):
 side=penetration_base(rs,i)
 if side is None:return None
 e20=ema(rs,i,20); e50=ema(rs,i,50)
 if e20 is None or e50 is None:return None
 if mode=='ema20_50_state':
  if side=='long' and not e20>e50:return None
  if side=='short' and not e20<e50:return None
 elif mode=='ema20_50_slope':
  p20=ema(rs,i-1,20);p50=ema(rs,i-1,50)
  if p20 is None or p50 is None:return None
  if side=='long' and not (e20>e50 and e20>p20 and e50>p50):return None
  if side=='short' and not (e20<e50 and e20<p20 and e50<p50):return None
 return side

def run_one(mode):
 rows=[];src={}
 for sym in SYMBOLS:
  rs=bars(sym,'4h');src[sym]={'bars':len(rs),'first_ts':int(rs[0]['ts']) if rs else None,'last_ts':int(rs[-1]['ts']) if rs else None};i=50
  while i<len(rs)-HOLD-1:
   side=signal(mode,rs,i)
   if side is None:i+=1;continue
   ei=i+1;xi=ei+HOLD-1;ep=float(rs[ei]['open']);xp=float(rs[xi]['close']);gross=(xp/ep-1)*10000*(1 if side=='long' else -1)
   rows.append({'symbol':sym,'side':side,'gross_bps':gross});i=xi+1
 g=[x['gross_bps'] for x in rows];m=metrics(g)
 return {'metrics':m,'economic_candidate':bool(m['trades']>=40 and (m['net_expectancy_bps'] or 0)>0 and (m['profit_factor'] or 0)>1 and (m['payoff'] or 0)>=1),'by_symbol':{s:metrics([x['gross_bps'] for x in rows if x['symbol']==s]) for s in SYMBOLS},'by_side':{s:metrics([x['gross_bps'] for x in rows if x['side']==s]) for s in ('long','short') if any(x['side']==s for x in rows)},'cost_stress':{str(c):metrics(g,float(c)) for c in (14,28,40)},'source_summary':src}

def run():
 cand={
  'diag_penetration_ema20_50_state_v1':{'architecture':'DIAG_PENETRATION_EMA20_VS_EMA50_STATE',**run_one('ema20_50_state')},
  'diag_penetration_ema20_50_slope_v1':{'architecture':'DIAG_PENETRATION_EMA20_50_STATE_WITH_BOTH_SLOPES',**run_one('ema20_50_slope')},
 }
 r={'schema_version':'zel.a1_gen2_4h_ema_state_dev.v1','boundary':BOUNDARY,'development_only':True,'prospective':False,'isolated_axis':True,'uses_data_strictly_before_gen1_boundary':True,'parameter_sweep':False,'tuned_thresholds':0,'hold_bars':HOLD,'candidates':cand,'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED','live_trade_authority':'BLOCKED'}
 r['receipt_sha256']=hashlib.sha256(json.dumps(r,sort_keys=True,separators=(',',':')).encode()).hexdigest();return r
if __name__=='__main__':
 r=run();Path('out').mkdir(exist_ok=True);Path('out/a1_gen2_4h_ema_state_dev_v1.json').write_text(json.dumps(r,indent=2,sort_keys=True)+'\n');print('A1_GEN2_4H_EMA_STATE='+json.dumps(r,sort_keys=True))
