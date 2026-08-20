#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
import backend.research.architecture_factory.a1_gen2_generic_dev_econ_v1 as econ

ENTRY_RULE="ret(1) < -0.02 or (ret(1) > 0.02 and close < sma('close',50))"
SIDE_RULE="long if ret(1) < -0.02 else short"
HOLD=12; BASE_ACT=300.0; CONF_ACT=400.0; LOCK_GROSS_BPS=14.0; ATR_N=14
EXPECTED={"trades":227,"net_pnl_bps":32456.553693428767,"net_expectancy_bps":142.98041274638223,"profit_factor":1.7661077778815002,"drawdown_bps":3222.578836366174}

def _metrics(net):
 n=len(net); return {"trades":n,"net_expectancy_bps":sum(net)/n if n else None,"net_pnl_bps":sum(net),"profit_factor":econ._pf(net) if n else None,"payoff":econ._payoff(net) if n else None,"win_rate":sum(x>0 for x in net)/n if n else None,"drawdown_bps":econ._dd(net) if n else 0.0}

def _gross(side,ep,px): return (px/ep-1)*10000 if side=='long' else (1-px/ep)*10000

def _atr(rs,i):
 trs=[]
 for j in range(i-ATR_N+1,i+1):
  pc=rs[j-1]['close']; trs.append(max(rs[j]['high']-rs[j]['low'],abs(rs[j]['high']-pc),abs(rs[j]['low']-pc)))
 return sum(trs)/len(trs)

def _outcome(rs,side,ei,xi,ep,act):
 activated=False
 for j in range(ei,xi+1):
  if activated:
   floor=ep*(1+LOCK_GROSS_BPS/10000) if side=='long' else ep*(1-LOCK_GROSS_BPS/10000)
   if side=='long' and rs[j]['low']<=floor: return _gross(side,ep,min(floor,rs[j]['open']))-14.0
   if side=='short' and rs[j]['high']>=floor: return _gross(side,ep,max(floor,rs[j]['open']))-14.0
  fav=(rs[j]['high']/ep-1)*10000 if side=='long' else (1-rs[j]['low']/ep)*10000
  if fav>=act: activated=True
 return _gross(side,ep,rs[xi]['close'])-14.0

def _trades():
 out=[]
 for symbol in econ.SYMBOLS:
  rs=econ.bars(symbol,'1d'); eng=econ.Expr(rs,{}); i=30
  while i<len(rs)-1:
   try: fire=bool(eng.eval(ENTRY_RULE,i))
   except Exception: fire=False
   if not fire: i+=1; continue
   side=econ._side(SIDE_RULE,eng,i); ei=i+1; xi=min(ei+HOLD-1,len(rs)-1); ep=rs[ei]['open']; atr=_atr(rs,i); shock=abs(rs[i]['close']-rs[i-1]['close'])
   out.append({"symbol":symbol,"side":side,"signal_ts":int(rs[i]['ts']),"exit_ts":int(rs[xi]['ts']),"atr_confirm":shock>=atr,"base_net_bps":_outcome(rs,side,ei,xi,ep,BASE_ACT),"conf_net_bps":_outcome(rs,side,ei,xi,ep,CONF_ACT)})
   i=max(i+1,xi+1)
 return out

def _causal_side_flags(t):
 # At each signal, use only trades whose original 12D slot already completed.
 flags={id(x):False for x in t}; done=[]
 for x in sorted(t,key=lambda z:z['signal_ts']):
  eligible=[z for z in t if z['exit_ts']<x['signal_ts']]
  loss={s:[abs(z['base_net_bps']) for z in eligible if z['side']==s and z['base_net_bps']<0] for s in ('long','short')}
  if len(loss['long'])>=5 and len(loss['short'])>=5:
   avg={s:sum(v)/len(v) for s,v in loss.items()}; favorable=min(avg,key=avg.get); flags[id(x)]=(x['side']==favorable)
 return flags

def _pareto(a,b): return b['net_pnl_bps']>a['net_pnl_bps'] and b['net_expectancy_bps']>a['net_expectancy_bps'] and b['profit_factor']>a['profit_factor'] and b['drawdown_bps']<a['drawdown_bps']

def run(output:Path):
 t=_trades(); base=_metrics([x['base_net_bps'] for x in t]); flags=_causal_side_flags(t)
 for k,v in EXPECTED.items():
  if k=='trades': assert base[k]==v,(k,base[k],v)
  else: assert abs(base[k]-v)<1e-6,(k,base[k],v)
 trig=[x for x in t if x['atr_confirm'] and flags[id(x)]]; cand_net=[x['conf_net_bps'] if x in trig else x['base_net_bps'] for x in t]; cand=_metrics(cand_net); accepted=_pareto(base,cand)
 r={"schema_version":"zel.a1_gen2_atr_side_advisory_delayed_lock.v1","development_only":True,"incumbent_metrics":base,"axis":{"name":"atr1x_and_causal_lower_side_loss_risk_delays_lock_300_to_400_only","future_information_used":False,"side_advisory":"completed_prior_trades_only_min_5_losses_each_side","atr_period":ATR_N,"base_activation_bps":BASE_ACT,"confidence_activation_bps":CONF_ACT,"threshold_sweep":False,"signal_deleted":False,"position_size_changed":False,"trigger_trade_count":len(trig),"trigger_base_net_bps":sum(x['base_net_bps'] for x in trig),"trigger_candidate_net_bps":sum(x['conf_net_bps'] for x in trig),"new_metrics":cand,"accepted_pareto":accepted,"state":"PASS_PARETO_IMPROVEMENT" if accepted else "SEALED_FAIL_NO_REUSE"},"selection_authority":False,"promotion_authority":False,"execution_authority":"NONE","order_authority":"BLOCKED","live_trade_authority":"BLOCKED"}
 output.parent.mkdir(parents=True,exist_ok=True); output.write_text(json.dumps(r,sort_keys=True,indent=2)+'\n'); print('ATR_SIDE_ADVISORY_DELAYED_LOCK='+json.dumps(r,sort_keys=True)); return r
if __name__=='__main__': run(Path('out/a1_gen2_incumbent_hardening_v1.json'))
