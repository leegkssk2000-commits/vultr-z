#!/usr/bin/env python3
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
import backend.research.architecture_factory.a1_gen2_generic_dev_econ_v1 as econ

ENTRY_RULE="ret(1) < -0.02 or (ret(1) > 0.02 and close < sma('close',50))"
SIDE_RULE="long if ret(1) < -0.02 else short"
HOLD=12; ACTIVATE_BPS=300.0; LOCK_GROSS_BPS=14.0; LOSS_STREAK_TRIGGER=2
EXPECTED={"trades":227,"net_pnl_bps":32456.553693428767,"net_expectancy_bps":142.98041274638223,"profit_factor":1.7661077778815002,"drawdown_bps":3222.578836366174}

def _metrics(net):
 n=len(net)
 return {"trades":n,"net_expectancy_bps":sum(net)/n if n else None,"net_pnl_bps":sum(net),"profit_factor":econ._pf(net) if n else None,"payoff":econ._payoff(net) if n else None,"win_rate":sum(x>0 for x in net)/n if n else None,"drawdown_bps":econ._dd(net) if n else 0.0}

def _one_trade(rs,eng,i,symbol):
 side=econ._side(SIDE_RULE,eng,i); ei=i+1; xi=min(ei+HOLD-1,len(rs)-1); ep=rs[ei]['open']; activated=False; gross=None
 for j in range(ei,xi+1):
  if activated:
   floor=ep*(1+LOCK_GROSS_BPS/10000) if side=='long' else ep*(1-LOCK_GROSS_BPS/10000)
   if side=='long' and rs[j]['low']<=floor: gross=(min(floor,rs[j]['open'])/ep-1)*10000; break
   if side=='short' and rs[j]['high']>=floor: gross=(1-max(floor,rs[j]['open'])/ep)*10000; break
  fav=(rs[j]['high']/ep-1)*10000 if side=='long' else (1-rs[j]['low']/ep)*10000
  if fav>=ACTIVATE_BPS: activated=True
 if gross is None:
  xp=rs[xi]['close']; gross=(xp/ep-1)*10000*(1 if side=='long' else -1)
 return {"symbol":symbol,"side":side,"net_bps":gross-14.0,"signal_ts":int(rs[i]['ts']),"signal_year":datetime.fromtimestamp(rs[i]['ts']/1000,tz=timezone.utc).year,"slot_end_i":xi}

def _trades(cooldown=False):
 out=[]; skipped=[]
 for symbol in econ.SYMBOLS:
  rs=econ.bars(symbol,'1d'); eng=econ.Expr(rs,{}); i=30; loss_streak=0
  while i<len(rs)-1:
   try: fire=bool(eng.eval(ENTRY_RULE,i))
   except Exception: fire=False
   if not fire: i+=1; continue
   tr=_one_trade(rs,eng,i,symbol)
   if cooldown and loss_streak>=LOSS_STREAK_TRIGGER:
    skipped.append({k:tr[k] for k in ('symbol','side','net_bps','signal_ts','signal_year')}); loss_streak=0; i=max(i+1,tr['slot_end_i']+1); continue
   out.append({k:tr[k] for k in ('symbol','side','net_bps','signal_ts','signal_year')})
   loss_streak=loss_streak+1 if tr['net_bps']<0 else 0
   i=max(i+1,tr['slot_end_i']+1)
 return out,skipped

def _side_weights(t):
 loss={s:[abs(x['net_bps']) for x in t if x['side']==s and x['net_bps']<0] for s in ('long','short')}
 avg={s:sum(v)/len(v) for s,v in loss.items()}
 raw={s:min(avg.values())/avg[s] for s in avg}; mean=sum(raw[x['side']] for x in t)/len(t)
 return avg,{s:raw[s]/mean for s in raw}

def _max_dd_window(rows,weights=None):
 vals=[x['net_bps']*(weights[x['side']] if weights else 1.0) for x in rows]
 cum=0.0; peak=0.0; peak_idx=-1; best=(0.0,0,0)
 for i,v in enumerate(vals):
  cum+=v
  if cum>peak: peak=cum; peak_idx=i
  dd=peak-cum
  if dd>best[0]: best=(dd,peak_idx+1,i)
 dd,s,e=best; seg=rows[s:e+1] if e>=s else []
 def counts(key):
  d={}
  for x in seg:d[str(x[key])]=d.get(str(x[key]),0)+1
  return d
 return {"drawdown_bps":dd,"start_index":s,"end_index":e,"trade_count":len(seg),"by_side":counts('side'),"by_symbol":counts('symbol'),"by_year":counts('signal_year'),"segment_unweighted_net_bps":sum(x['net_bps'] for x in seg),"segment_weighted_net_bps":sum(x['net_bps']*(weights[x['side']] if weights else 1.0) for x in seg)}

def _pareto(a,b):
 return b['net_pnl_bps']>a['net_pnl_bps'] and b['net_expectancy_bps']>a['net_expectancy_bps'] and b['profit_factor']>a['profit_factor'] and b['drawdown_bps']<a['drawdown_bps']

def run(output:Path):
 base_t,_=_trades(False); base=_metrics([x['net_bps'] for x in base_t])
 for k,v in EXPECTED.items():
  if k=='trades': assert base[k]==v,(k,base[k],v)
  else: assert abs(base[k]-v)<1e-6,(k,base[k],v)

 avg,w=_side_weights(base_t)
 side_parity=_metrics([x['net_bps']*w[x['side']] for x in base_t])
 cooldown_t,skipped=_trades(True); cooldown=_metrics([x['net_bps'] for x in cooldown_t])
 side_cd=_metrics([x['net_bps']*w[x['side']] for x in cooldown_t])

 r={"schema_version":"zel.a1_gen2_cooldown_and_side_parity_diagnostic.v1","development_only":True,"incumbent_metrics":base,
 "cooldown_axis":{"name":"after_two_consecutive_losses_skip_next_eligible_12d_slot","loss_streak_trigger":LOSS_STREAK_TRIGGER,"threshold_sweep":False,"skipped_slots":len(skipped),"skipped_ex_post":{"net_bps":sum(x['net_bps'] for x in skipped),"losses":sum(x['net_bps']<0 for x in skipped),"wins":sum(x['net_bps']>0 for x in skipped)},"new_metrics":cooldown,"accepted_pareto":_pareto(base,cooldown),"state":"PASS_PARETO_IMPROVEMENT" if _pareto(base,cooldown) else "SEALED_FAIL_NO_REUSE"},
 "side_parity_salvage":{"original_average_abs_loss_bps":avg,"original_side_weights":w,"original_metrics":side_parity,"max_dd_attribution":_max_dd_window(base_t,w),"incumbent_max_dd_attribution":_max_dd_window(base_t,None),"same_cooldown_combination_metrics":side_cd,"combination_accepted_pareto_vs_incumbent":_pareto(base,side_cd),"combination_state":"PASS_PARETO_IMPROVEMENT" if _pareto(base,side_cd) else "SEALED_FAIL_NO_REUSE","interpretation_guard":"diagnostic_and_single_prespecified_cooldown_only_no_weight_sweep"},
 "selection_authority":False,"promotion_authority":False,"execution_authority":"NONE","order_authority":"BLOCKED","live_trade_authority":"BLOCKED"}
 output.parent.mkdir(parents=True,exist_ok=True); output.write_text(json.dumps(r,sort_keys=True,indent=2)+'\n')
 print('COOLDOWN_SIDE_PARITY_DIAGNOSTIC='+json.dumps(r,sort_keys=True)); return r
if __name__=='__main__': run(Path('out/a1_gen2_incumbent_hardening_v1.json'))
