#!/usr/bin/env python3
from __future__ import annotations
import json, hashlib, math
from pathlib import Path
from backend.research.architecture_factory.a1_gen2_4h_trend_breakout_dev_v1 import penetration_base, metrics
from backend.research.architecture_factory.a1_gen2_generic_dev_econ_v1 import BOUNDARY, SYMBOLS, bars

HOLD=6
BB_N=20
LOOK=6

def _bw(rs,i):
 if i+1<BB_N:return None
 xs=[float(x['close']) for x in rs[i-BB_N+1:i+1]];m=sum(xs)/BB_N;var=sum((x-m)**2 for x in xs)/BB_N;sd=math.sqrt(var)
 return 0.0 if m==0 else (4.0*sd)/m

def signal(rs,i):
 side=penetration_base(rs,i)
 if side is None or i<BB_N+LOOK*2:return None
 cur=_bw(rs,i);prev=_bw(rs,i-1)
 a=[_bw(rs,j) for j in range(i-LOOK,i)]
 b=[_bw(rs,j) for j in range(i-LOOK*2,i-LOOK)]
 if cur is None or prev is None or any(x is None for x in a+b):return None
 if not (sum(a)/len(a) < sum(b)/len(b) and cur>prev):return None
 return side

def run():
 rows=[];src={}
 for sym in SYMBOLS:
  rs=bars(sym,'4h');src[sym]={'bars':len(rs),'first_ts':int(rs[0]['ts']) if rs else None,'last_ts':int(rs[-1]['ts']) if rs else None};i=max(50,BB_N+LOOK*2)
  while i<len(rs)-HOLD-1:
   side=signal(rs,i)
   if side is None:i+=1;continue
   ei=i+1;xi=ei+HOLD-1;ep=float(rs[ei]['open']);xp=float(rs[xi]['close']);gross=(xp/ep-1)*10000*(1 if side=='long' else -1)
   rows.append({'symbol':sym,'side':side,'gross_bps':gross});i=xi+1
 g=[x['gross_bps'] for x in rows];m=metrics(g)
 r={'schema_version':'zel.a1_gen2_4h_bollinger_expansion_dev.v1','boundary':BOUNDARY,'development_only':True,'prospective':False,'isolated_axis':True,'parameter_sweep':False,'tuned_thresholds':0,'architecture':'4H_PENETRATION_PLUS_BB20_6BAR_COMPRESSION_TO_EXPANSION','metrics':m,'economic_candidate':bool(m['trades']>=40 and (m['net_expectancy_bps'] or 0)>0 and (m['profit_factor'] or 0)>1 and (m['payoff'] or 0)>=1),'by_symbol':{s:metrics([x['gross_bps'] for x in rows if x['symbol']==s]) for s in SYMBOLS},'by_side':{s:metrics([x['gross_bps'] for x in rows if x['side']==s]) for s in ('long','short') if any(x['side']==s for x in rows)},'cost_stress':{str(c):metrics(g,float(c)) for c in (14,28,40)},'source_summary':src,'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED','live_trade_authority':'BLOCKED'}
 r['receipt_sha256']=hashlib.sha256(json.dumps(r,sort_keys=True,separators=(',',':')).encode()).hexdigest();return r

if __name__=='__main__':
 r=run();Path('out').mkdir(exist_ok=True);Path('out/a1_gen2_4h_bollinger_expansion_dev_v1.json').write_text(json.dumps(r,indent=2,sort_keys=True)+'\n');print('A1_GEN2_4H_BOLLINGER_EXPANSION='+json.dumps(r,sort_keys=True))
