#!/usr/bin/env python3
from __future__ import annotations
import json,hashlib,datetime as dt
from pathlib import Path
from backend.research.architecture_factory.a1_gen2_4h_range_atr_regime_dev_v1 import signal, metrics, HOLD
from backend.research.architecture_factory.a1_gen2_generic_dev_econ_v1 import BOUNDARY,SYMBOLS,bars

def collect():
 rows=[]
 for sym in SYMBOLS:
  rs=bars(sym,'4h');i=50
  while i<len(rs)-HOLD-1:
   side=signal(rs,i)
   if side is None:i+=1;continue
   ei=i+1;xi=ei+HOLD-1;ep=float(rs[ei]['open']);xp=float(rs[xi]['close']);gross=(xp/ep-1)*10000*(1 if side=='long' else -1)
   ts=int(rs[ei]['ts']);year=dt.datetime.utcfromtimestamp(ts/1000).year if ts>10_000_000_000 else dt.datetime.utcfromtimestamp(ts).year
   rows.append({'symbol':sym,'side':side,'gross_bps':gross,'year':year});i=xi+1
 return rows

def run():
 rows=collect();g=[x['gross_bps'] for x in rows];base=metrics(g)
 by_symbol={s:metrics([x['gross_bps'] for x in rows if x['symbol']==s]) for s in SYMBOLS}
 by_side={s:metrics([x['gross_bps'] for x in rows if x['side']==s]) for s in ('long','short') if any(x['side']==s for x in rows)}
 years=sorted(set(x['year'] for x in rows));by_year={str(y):metrics([x['gross_bps'] for x in rows if x['year']==y]) for y in years}
 costs={str(c):metrics(g,float(c)) for c in (14,28,40)}
 side_flip=metrics([-x for x in g])
 losses=sorted([-x for x in g if x<0],reverse=True);loss_sum=sum(losses);top10=sum(losses[:10]);top10_share=(top10/loss_sum if loss_sum>0 else 0.0)
 hardening={
  'cost_28_positive':(costs['28']['net_pnl_bps'] or 0)>0 and (costs['28']['profit_factor'] or 0)>1,
  'cost_40_positive':(costs['40']['net_pnl_bps'] or 0)>0 and (costs['40']['profit_factor'] or 0)>1,
  'both_symbols_positive':all((m['net_pnl_bps'] or 0)>0 and (m['profit_factor'] or 0)>1 for m in by_symbol.values()),
  'both_sides_positive':all((m['net_pnl_bps'] or 0)>0 and (m['profit_factor'] or 0)>1 for m in by_side.values()) if len(by_side)==2 else False,
  'negative_control_ok':(side_flip['net_pnl_bps'] or 0)<0 and (side_flip['profit_factor'] or 9)<1,
  'year_positive_count':sum(1 for m in by_year.values() if (m['net_pnl_bps'] or 0)>0 and (m['profit_factor'] or 0)>1),
  'year_total':len(by_year),
  'top10_loss_share':top10_share,
 }
 hardening['near_survivor']=bool(base['trades']>=80 and all([hardening['cost_28_positive'],hardening['cost_40_positive'],hardening['both_symbols_positive'],hardening['both_sides_positive'],hardening['negative_control_ok']]) and hardening['year_positive_count']>=max(1,hardening['year_total']-1) and top10_share<0.60)
 r={'schema_version':'zel.a1_gen2_4h_range_atr_hardening.v1','boundary':BOUNDARY,'development_only':True,'prospective':False,'candidate':'4H_RANGE_BREAKOUT_PLUS_ATR14_ABOVE_ITS_14BAR_MEAN','metrics':base,'cost_stress':costs,'by_symbol':by_symbol,'by_side':by_side,'by_year':by_year,'side_flip_negative_control':side_flip,'hardening':hardening,'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED','live_trade_authority':'BLOCKED'}
 r['receipt_sha256']=hashlib.sha256(json.dumps(r,sort_keys=True,separators=(',',':')).encode()).hexdigest();return r
if __name__=='__main__':
 r=run();Path('out').mkdir(exist_ok=True);Path('out/a1_gen2_4h_range_atr_hardening_v1.json').write_text(json.dumps(r,indent=2,sort_keys=True)+'\n');print(json.dumps(r,sort_keys=True))
