#!/usr/bin/env python3
from __future__ import annotations
import json, hashlib
from datetime import datetime, timezone
from pathlib import Path
from backend.research.architecture_factory.a1_gen2_generic_dev_econ_v1 import BOUNDARY,COST_BPS,SYMBOLS,bars
from backend.research.architecture_factory.a1_gen2_4h_trend_breakout_dev_v1 import signal,metrics
MODE='penetration_ma_stack'; HOLD=6

def year_of(ts:int)->int:
 return datetime.fromtimestamp(ts/1000,timezone.utc).year

def run():
 rows=[]; src={}
 for sym in SYMBOLS:
  rs=bars(sym,'4h'); src[sym]={'bars':len(rs),'first_ts':int(rs[0]['ts']) if rs else None,'last_ts':int(rs[-1]['ts']) if rs else None}; i=200
  while i<len(rs)-HOLD-1:
   side=signal(MODE,rs,i)
   if side is None:i+=1;continue
   ei=i+1; xi=ei+HOLD-1; ep=float(rs[ei]['open']); xp=float(rs[xi]['close']); gross=(xp/ep-1)*10000*(1 if side=='long' else -1)
   rows.append({'symbol':sym,'side':side,'gross_bps':gross,'entry_ts':int(rs[ei]['ts']),'year':year_of(int(rs[ei]['ts']))}); i=xi+1
 g=[x['gross_bps'] for x in rows]; m=metrics(g)
 by_symbol={s:metrics([x['gross_bps'] for x in rows if x['symbol']==s]) for s in SYMBOLS}
 by_side={s:metrics([x['gross_bps'] for x in rows if x['side']==s]) for s in ('long','short') if any(x['side']==s for x in rows)}
 years=sorted(set(x['year'] for x in rows)); by_year={str(y):metrics([x['gross_bps'] for x in rows if x['year']==y]) for y in years}
 costs={str(c):metrics(g,float(c)) for c in (14,28,40)}
 neg=metrics([-x for x in g])
 span_days=((max(x['entry_ts'] for x in rows)-min(x['entry_ts'] for x in rows))/86400000.0) if len(rows)>1 else None
 events_per_day=(len(rows)/span_days) if span_days and span_days>0 else None
 flags={
  'cost40_positive':(costs['40']['net_pnl_bps'] or 0)>0 and (costs['40']['profit_factor'] or 0)>1,
  'symbols_positive':all((v['net_pnl_bps'] or 0)>0 and (v['profit_factor'] or 0)>1 for v in by_symbol.values()),
  'sides_positive':all((v['net_pnl_bps'] or 0)>0 and (v['profit_factor'] or 0)>1 for v in by_side.values()),
  'years_positive':all((v['net_pnl_bps'] or 0)>0 and ((v['profit_factor'] or 0)>1 if v['profit_factor'] is not None else True) for v in by_year.values()),
  'negative_control_breaks':(neg['net_pnl_bps'] or 0)<0 and (neg['profit_factor'] or 999)<1,
 }
 r={'schema_version':'zel.a1_gen2_4h_ma_stack_hardening.v1','boundary':BOUNDARY,'candidate_id':'4h_penetration_ma50_100_200_stack','development_only':True,'prospective':False,'future_information_used':False,'parameter_sweep':False,'metrics':m,'events_per_day':events_per_day,'by_symbol':by_symbol,'by_side':by_side,'by_year':by_year,'cost_stress':costs,'negative_control':neg,'flags':flags,'hardening_pass':all(flags.values()),'source_summary':src,'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED','live_trade_authority':'BLOCKED'}
 r['receipt_sha256']=hashlib.sha256(json.dumps(r,sort_keys=True,separators=(',',':')).encode()).hexdigest(); return r
if __name__=='__main__':
 r=run(); Path('out').mkdir(exist_ok=True); Path('out/a1_gen2_4h_ma_stack_hardening_v1.json').write_text(json.dumps(r,indent=2,sort_keys=True)+'\n'); print('A1_GEN2_4H_MA_STACK_HARDENING='+json.dumps(r,sort_keys=True))
