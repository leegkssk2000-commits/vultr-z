#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
import backend.research.architecture_factory.a1_gen2_generic_dev_econ_v1 as econ

ENTRY_RULE="ret(1) < -0.02 or (ret(1) > 0.02 and close < sma('close',50))"
SIDE_RULE="long if ret(1) < -0.02 else short"
HOLD=12; ACTIVATE_BPS=300.0; LOCK_GROSS_BPS=14.0
EXPECTED={"trades":227,"net_pnl_bps":32456.553693428767,"net_expectancy_bps":142.98041274638223,"profit_factor":1.7661077778815002,"drawdown_bps":3222.578836366174}

def _metrics(net):
 n=len(net); return {"trades":n,"net_expectancy_bps":sum(net)/n,"net_pnl_bps":sum(net),"profit_factor":econ._pf(net),"payoff":econ._payoff(net),"win_rate":sum(x>0 for x in net)/n,"drawdown_bps":econ._dd(net)}

def _trades():
 out=[]
 for symbol in econ.SYMBOLS:
  rs=econ.bars(symbol,'1d'); eng=econ.Expr(rs,{}); i=30
  while i<len(rs)-1:
   try: fire=bool(eng.eval(ENTRY_RULE,i))
   except Exception: fire=False
   if not fire: i+=1; continue
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
   out.append({"symbol":symbol,"side":side,"net_bps":gross-14.0}); i=max(i+1,xi+1)
 return out

def run(output:Path):
 t=_trades(); base=_metrics([x['net_bps'] for x in t])
 for k,v in EXPECTED.items():
  if k=='trades': assert base[k]==v
  else: assert abs(base[k]-v)<1e-6,(k,base[k],v)
 # Independent risk axis: no signal/exit deletion. Scale only the historically higher-loss side
 # to equalize average absolute losing-trade risk with the lower-loss side; normalize weights
 # back to mean 1.0 so aggregate gross exposure is unchanged.
 loss={s:[abs(x['net_bps']) for x in t if x['side']==s and x['net_bps']<0] for s in ('long','short')}
 avg={s:sum(v)/len(v) for s,v in loss.items()}
 raw={s:min(avg.values())/avg[s] for s in avg}; mean=sum(raw[x['side']] for x in t)/len(t); w={s:raw[s]/mean for s in raw}
 weighted=[x['net_bps']*w[x['side']] for x in t]; cand=_metrics(weighted)
 accepted=cand['net_pnl_bps']>base['net_pnl_bps'] and cand['net_expectancy_bps']>base['net_expectancy_bps'] and cand['profit_factor']>base['profit_factor'] and cand['drawdown_bps']<base['drawdown_bps']
 r={"schema_version":"zel.a1_gen2_independent_axis_side_loss_risk_parity.v1","development_only":True,"incumbent_metrics":base,"axis":{"name":"side_loss_risk_parity_mean_exposure_normalized","signal_rule_changed":False,"exit_rule_changed":False,"mean_weight":sum(w[x['side']] for x in t)/len(t),"average_abs_loss_bps":avg,"side_weights":w,"new_metrics":cand,"accepted_pareto":accepted,"state":"PASS_PARETO_IMPROVEMENT" if accepted else "SEALED_FAIL_NO_REUSE"},"selection_authority":False,"promotion_authority":False,"execution_authority":"NONE","order_authority":"BLOCKED","live_trade_authority":"BLOCKED"}
 output.parent.mkdir(parents=True,exist_ok=True); output.write_text(json.dumps(r,sort_keys=True,indent=2)+'\n'); print('INDEPENDENT_SIDE_RISK_PARITY='+json.dumps(r,sort_keys=True)); return r
if __name__=='__main__': run(Path('out/a1_gen2_incumbent_hardening_v1.json'))
