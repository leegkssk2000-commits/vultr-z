#!/usr/bin/env python3
from __future__ import annotations
import json
from backend.research.architecture_factory.a1_gen2_4h_trend_breakout_dev_v1 import SYMBOLS,bars,penetration_base,metrics,HOLD

def ema_series(rs,n):
 a=2.0/(n+1.0); out=[]; e=None
 for r in rs:
  c=float(r['close']); e=c if e is None else a*c+(1-a)*e; out.append(e)
 return out

def run_one(mode):
 rows=[]
 for sym in SYMBOLS:
  rs=bars(sym,'4h'); e20=ema_series(rs,20); e50=ema_series(rs,50); i=200
  while i<len(rs)-HOLD-1:
   side=penetration_base(rs,i)
   if side is None:i+=1;continue
   c=float(rs[i]['close'])
   if mode=='ema20_50_state':
    ok=(side=='long' and c>e20[i]>e50[i]) or (side=='short' and c<e20[i]<e50[i])
   elif mode=='ema20_50_slope':
    ok=((side=='long' and c>e20[i]>e50[i] and e20[i]>e20[i-1] and e50[i]>e50[i-1]) or
        (side=='short' and c<e20[i]<e50[i] and e20[i]<e20[i-1] and e50[i]<e50[i-1]))
   else: ok=False
   if not ok:i+=1;continue
   ei=i+1; xi=ei+HOLD-1; ep=float(rs[ei]['open']); xp=float(rs[xi]['close']); gross=(xp/ep-1)*10000*(1 if side=='long' else -1)
   rows.append({'symbol':sym,'side':side,'gross_bps':gross}); i=xi+1
 g=[x['gross_bps'] for x in rows]
 return {'metrics':metrics(g),'cost_stress':{str(c):metrics(g,float(c)) for c in (14,28,40)},'by_symbol':{s:metrics([x['gross_bps'] for x in rows if x['symbol']==s]) for s in SYMBOLS},'by_side':{s:metrics([x['gross_bps'] for x in rows if x['side']==s]) for s in ('long','short') if any(x['side']==s for x in rows)}}

def run():
 return {'development_only':True,'parameter_sweep':False,'selection_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED','candidates':{'ema20_50_state':run_one('ema20_50_state'),'ema20_50_slope':run_one('ema20_50_slope')}}
if __name__=='__main__': print('HIGH_FREQ_EMA_STRUCTURE='+json.dumps(run(),sort_keys=True))
