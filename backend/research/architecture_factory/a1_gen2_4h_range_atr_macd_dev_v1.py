#!/usr/bin/env python3
from __future__ import annotations
import json,hashlib
from pathlib import Path
from backend.research.architecture_factory.a1_gen2_4h_range_atr_regime_dev_v1 import signal as atr_signal, metrics, HOLD
from backend.research.architecture_factory.a1_gen2_generic_dev_econ_v1 import BOUNDARY,SYMBOLS,bars

def ema(vals,n):
 if len(vals)<n:return None
 k=2.0/(n+1.0);v=sum(vals[:n])/n
 for x in vals[n:]:v=x*k+v*(1-k)
 return v

def macd_hist(rs,i):
 if i<35:return None
 closes=[float(x['close']) for x in rs[:i+1]]
 line=[]
 for j in range(25,i+1):
  sub=closes[:j+1];e12=ema(sub,12);e26=ema(sub,26)
  line.append(e12-e26)
 if len(line)<9:return None
 sig=ema(line,9)
 return line[-1]-sig

def signal(rs,i):
 side=atr_signal(rs,i)
 if side is None:return None
 h=macd_hist(rs,i)
 if h is None:return None
 if side=='long' and h>0:return side
 if side=='short' and h<0:return side
 return None

def run():
 rows=[];src={}
 for sym in SYMBOLS:
  rs=bars(sym,'4h');src[sym]={'bars':len(rs)};i=50
  while i<len(rs)-HOLD-1:
   side=signal(rs,i)
   if side is None:i+=1;continue
   ei=i+1;xi=ei+HOLD-1;ep=float(rs[ei]['open']);xp=float(rs[xi]['close']);gross=(xp/ep-1)*10000*(1 if side=='long' else -1)
   rows.append({'symbol':sym,'side':side,'gross_bps':gross});i=xi+1
 g=[x['gross_bps'] for x in rows];m=metrics(g)
 r={'schema_version':'zel.a1_gen2_4h_range_atr_macd_dev.v1','boundary':BOUNDARY,'development_only':True,'prospective':False,'isolated_axis':True,'parameter_sweep':False,'tuned_thresholds':0,'architecture':'4H_RANGE_ATR_PLUS_STANDARD_MACD_12_26_9_DIRECTION','metrics':m,'economic_candidate':bool(m['trades']>=40 and (m['net_expectancy_bps'] or 0)>0 and (m['profit_factor'] or 0)>1 and (m['payoff'] or 0)>=1),'by_symbol':{s:metrics([x['gross_bps'] for x in rows if x['symbol']==s]) for s in SYMBOLS},'by_side':{s:metrics([x['gross_bps'] for x in rows if x['side']==s]) for s in ('long','short') if any(x['side']==s for x in rows)},'cost_stress':{str(c):metrics(g,float(c)) for c in (14,28,40)},'source_summary':src,'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED','live_trade_authority':'BLOCKED'}
 r['receipt_sha256']=hashlib.sha256(json.dumps(r,sort_keys=True,separators=(',',':')).encode()).hexdigest();return r
if __name__=='__main__':
 r=run();Path('out').mkdir(exist_ok=True);Path('out/a1_gen2_4h_range_atr_macd_dev_v1.json').write_text(json.dumps(r,indent=2,sort_keys=True)+'\n');print(json.dumps(r,sort_keys=True))
