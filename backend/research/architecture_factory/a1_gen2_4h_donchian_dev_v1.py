#!/usr/bin/env python3
from __future__ import annotations
import json,hashlib
from pathlib import Path
from backend.research.architecture_factory.a1_gen2_4h_trend_breakout_dev_v1 import penetration_base,metrics
from backend.research.architecture_factory.a1_gen2_generic_dev_econ_v1 import BOUNDARY,SYMBOLS,bars
HOLD=6; DONCHIAN_N=20

def signal(rs,i):
 side=penetration_base(rs,i)
 if side is None or i<DONCHIAN_N:return None
 c=float(rs[i]['close']); hi=max(float(x['high']) for x in rs[i-DONCHIAN_N:i]); lo=min(float(x['low']) for x in rs[i-DONCHIAN_N:i])
 if side=='long' and c>hi:return side
 if side=='short' and c<lo:return side
 return None

def run():
 rows=[];src={}
 for sym in SYMBOLS:
  rs=bars(sym,'4h');src[sym]={'bars':len(rs),'first_ts':int(rs[0]['ts']) if rs else None,'last_ts':int(rs[-1]['ts']) if rs else None};i=50
  while i<len(rs)-HOLD-1:
   side=signal(rs,i)
   if side is None:i+=1;continue
   ei=i+1;xi=ei+HOLD-1;ep=float(rs[ei]['open']);xp=float(rs[xi]['close']);g=(xp/ep-1)*10000*(1 if side=='long' else -1)
   rows.append({'symbol':sym,'side':side,'gross_bps':g});i=xi+1
 g=[x['gross_bps'] for x in rows];m=metrics(g)
 r={'schema_version':'zel.a1_gen2_4h_donchian_dev.v1','boundary':BOUNDARY,'development_only':True,'prospective':False,'isolated_axis':True,'parameter_sweep':False,'donchian_bars':DONCHIAN_N,'hold_bars':HOLD,'candidate_id':'diag_penetration_donchian20_v1','metrics':m,'economic_candidate':bool(m['trades']>=40 and (m['net_expectancy_bps'] or 0)>0 and (m['profit_factor'] or 0)>1 and (m['payoff'] or 0)>=1),'by_symbol':{s:metrics([x['gross_bps'] for x in rows if x['symbol']==s]) for s in SYMBOLS},'by_side':{s:metrics([x['gross_bps'] for x in rows if x['side']==s]) for s in ('long','short') if any(x['side']==s for x in rows)},'cost_stress':{str(c):metrics(g,float(c)) for c in (14,28,40)},'source_summary':src,'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED','live_trade_authority':'BLOCKED'}
 r['receipt_sha256']=hashlib.sha256(json.dumps(r,sort_keys=True,separators=(',',':')).encode()).hexdigest();return r
if __name__=='__main__':
 r=run();Path('out').mkdir(exist_ok=True);Path('out/a1_gen2_4h_donchian_dev_v1.json').write_text(json.dumps(r,indent=2,sort_keys=True)+'\n');print('A1_GEN2_4H_DONCHIAN='+json.dumps(r,sort_keys=True))
