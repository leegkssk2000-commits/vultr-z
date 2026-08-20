#!/usr/bin/env python3
from __future__ import annotations
import json, statistics
from pathlib import Path
import backend.research.architecture_factory.a1_gen2_generic_dev_econ_v1 as econ

ENTRY_RULE="ret(1) < -0.02 or (ret(1) > 0.02 and close < sma('close',50))"
SIDE_RULE="long if ret(1) < -0.02 else short"
HOLD=12; ACT=300.0; LOCK_GROSS_BPS=14.0; ATR_N=14; STRESS_WEIGHT=0.75
EXPECTED={"trades":227,"net_pnl_bps":32456.553693428767,"net_expectancy_bps":142.98041274638223,"profit_factor":1.7661077778815002,"drawdown_bps":3222.578836366174}

def _metrics(net):
 n=len(net); return {"trades":n,"net_expectancy_bps":sum(net)/n if n else None,"net_pnl_bps":sum(net),"profit_factor":econ._pf(net) if n else None,"payoff":econ._payoff(net) if n else None,"win_rate":sum(x>0 for x in net)/n if n else None,"drawdown_bps":econ._dd(net) if n else 0.0}
def _gross(side,ep,px): return (px/ep-1)*10000 if side=='long' else (1-px/ep)*10000
def _atr(rs,i):
 trs=[]
 for j in range(i-ATR_N+1,i+1):
  pc=rs[j-1]['close']; trs.append(max(rs[j]['high']-rs[j]['low'],abs(rs[j]['high']-pc),abs(rs[j]['low']-pc)))
 return sum(trs)/len(trs)
def _outcome(rs,side,ei,xi,ep):
 activated=False
 for j in range(ei,xi+1):
  if activated:
   floor=ep*(1+LOCK_GROSS_BPS/10000) if side=='long' else ep*(1-LOCK_GROSS_BPS/10000)
   if side=='long' and rs[j]['low']<=floor: return _gross(side,ep,min(floor,rs[j]['open']))-14.0
   if side=='short' and rs[j]['high']>=floor: return _gross(side,ep,max(floor,rs[j]['open']))-14.0
  fav=(rs[j]['high']/ep-1)*10000 if side=='long' else (1-rs[j]['low']/ep)*10000
  if fav>=ACT: activated=True
 return _gross(side,ep,rs[xi]['close'])-14.0
def _trades():
 out=[]
 for symbol in econ.SYMBOLS:
  rs=econ.bars(symbol,'1d'); eng=econ.Expr(rs,{}); i=30
  while i<len(rs)-1:
   try: fire=bool(eng.eval(ENTRY_RULE,i))
   except Exception: fire=False
   if not fire: i+=1; continue
   side=econ._side(SIDE_RULE,eng,i); ei=i+1; xi=min(ei+HOLD-1,len(rs)-1); ep=rs[ei]['open']; atr=_atr(rs,i); shock=abs(rs[i]['close']-rs[i-1]['close']); shock_atr=shock/atr if atr else 0.0
   w=[x['close'] for x in rs[max(0,i-49):i+1]]; sma50=sum(w)/len(w); above=rs[i]['close']>=sma50
   out.append({"symbol":symbol,"side":side,"signal_ts":int(rs[i]['ts']),"exit_ts":int(rs[xi]['ts']),"shock_atr":shock_atr,"above_sma50":above,"net_bps":_outcome(rs,side,ei,xi,ep)})
   i=max(i+1,xi+1)
 return out
def _pareto_vs_incumbent(base,b): return b['net_pnl_bps']>base['net_pnl_bps'] and b['net_expectancy_bps']>base['net_expectancy_bps'] and b['profit_factor']>base['profit_factor'] and b['drawdown_bps']<base['drawdown_bps']
def run(output:Path):
 t=_trades(); base=_metrics([x['net_bps'] for x in t])
 for k,v in EXPECTED.items():
  if k=='trades': assert base[k]==v,(k,base[k],v)
  else: assert abs(base[k]-v)<1e-6,(k,base[k],v)
 veto=[x for x in t if x['side']=='long' and x['above_sma50'] and x['shock_atr']>=1.0]
 kept=[x for x in t if x not in veto]; near=_metrics([x['net_bps'] for x in kept])
 stress_ids=set()
 for x in sorted(kept,key=lambda z:z['signal_ts']):
  if x['symbol']!='ETH-USDT' or x['above_sma50']: continue
  prior=[z for z in kept if z['symbol']==x['symbol'] and z['exit_ts']<x['signal_ts'] and z['net_bps']<0]
  if len(prior)>=10:
   losses=[abs(z['net_bps']) for z in prior]; recent=losses[-5:]
   if sum(recent)/5.0 > statistics.median(losses): stress_ids.add(id(x))
 weighted=[x['net_bps']*(STRESS_WEIGHT if id(x) in stress_ids else 1.0) for x in kept]; cand=_metrics(weighted); accepted=_pareto_vs_incumbent(base,cand)
 r={"schema_version":"zel.a1_gen2_nearpass_localized_eth_stress_throttle.v1","development_only":True,"incumbent_metrics":base,"near_pass":{"rule":"long_above_sma50_and_shock_ge_1x_atr14_veto_only","metrics":near,"veto_trade_count":len(veto)},"axis":{"name":"nearpass_plus_eth_below_sma50_causal_loss_stress_weight_0p75","future_information_used":False,"stress_definition":"same_symbol completed prior losses only; recent5 mean abs loss > prior-loss median; min10 prior losses","stress_weight":STRESS_WEIGHT,"threshold_sweep":False,"trigger_trade_count":len(stress_ids),"trigger_base_net_bps":sum(x['net_bps'] for x in kept if id(x) in stress_ids),"new_metrics":cand,"accepted_pareto_vs_original_incumbent":accepted,"state":"PASS_PARETO_IMPROVEMENT" if accepted else "SEALED_FAIL_NO_REUSE"},"selection_authority":False,"promotion_authority":False,"execution_authority":"NONE","order_authority":"BLOCKED","live_trade_authority":"BLOCKED"}
 output.parent.mkdir(parents=True,exist_ok=True); output.write_text(json.dumps(r,sort_keys=True,indent=2)+'\n'); print('NEARPASS_LOCALIZED_ETH_STRESS='+json.dumps(r,sort_keys=True)); return r
if __name__=='__main__': run(Path('out/a1_gen2_incumbent_hardening_v1.json'))
