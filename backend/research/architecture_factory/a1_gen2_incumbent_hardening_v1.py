#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
import backend.research.architecture_factory.a1_gen2_generic_dev_econ_v1 as econ

ENTRY_RULE="ret(1) < -0.02 or (ret(1) > 0.02 and close < sma('close',50))"
SIDE_RULE="long if ret(1) < -0.02 else short"
HOLD=12; ACTIVATE_BPS=300.0; LOCK_GROSS_BPS=14.0
ETH_WINDOW=5; ETH_STRESS_WEIGHT=0.50
EXPECTED={"trades":227,"net_pnl_bps":32456.553693428767,"net_expectancy_bps":142.98041274638223,"profit_factor":1.7661077778815002,"drawdown_bps":3222.578836366174}

def _metrics(net):
 n=len(net)
 return {"trades":n,"net_expectancy_bps":sum(net)/n if n else None,"net_pnl_bps":sum(net),"profit_factor":econ._pf(net) if n else None,"payoff":econ._payoff(net) if n else None,"win_rate":sum(x>0 for x in net)/n if n else None,"drawdown_bps":econ._dd(net) if n else 0.0}

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
   out.append({"symbol":symbol,"side":side,"net_bps":gross-14.0,"signal_ts":int(rs[i]['ts'])}); i=max(i+1,xi+1)
 return out

def _median(xs):
 s=sorted(xs); n=len(s)
 if not n: return None
 return s[n//2] if n%2 else (s[n//2-1]+s[n//2])/2.0

def _eth_loss_stress_throttle(t):
 # Causal only: BTC always stays 1.0. For each ETH trade, use completed prior ETH trades only.
 # Downside state = mean downside of the previous 5 ETH trades. Compare it with the median of
 # all earlier completed 5-trade downside windows. If current downside is above that own-history
 # median, ETH weight is fixed at 0.50; otherwise 1.0. No bps threshold and no sweep.
 eth_hist=[]; window_hist=[]; weighted=[]; trace=[]
 for x in t:
  w=1.0; recent=None; benchmark=None; stressed=False
  if x['symbol']=='ETH-USDT':
   if len(eth_hist)>=ETH_WINDOW:
    recent=sum(max(-v,0.0) for v in eth_hist[-ETH_WINDOW:])/ETH_WINDOW
    if window_hist:
     benchmark=_median(window_hist)
     stressed=recent>benchmark
     if stressed: w=ETH_STRESS_WEIGHT
   weighted.append(x['net_bps']*w)
   trace.append({"symbol":x['symbol'],"side":x['side'],"weight":w,"recent_downside_bps":recent,"prior_window_median_bps":benchmark,"stressed":stressed})
   eth_hist.append(x['net_bps'])
   if len(eth_hist)>=ETH_WINDOW:
    window_hist.append(sum(max(-v,0.0) for v in eth_hist[-ETH_WINDOW:])/ETH_WINDOW)
  else:
   weighted.append(x['net_bps']); trace.append({"symbol":x['symbol'],"side":x['side'],"weight":1.0,"stressed":False})
 return _metrics(weighted),trace

def _pareto(a,b):
 return b['net_pnl_bps']>a['net_pnl_bps'] and b['net_expectancy_bps']>a['net_expectancy_bps'] and b['profit_factor']>a['profit_factor'] and b['drawdown_bps']<a['drawdown_bps']

def run(output:Path):
 t=_trades(); base=_metrics([x['net_bps'] for x in t])
 for k,v in EXPECTED.items():
  if k=='trades': assert base[k]==v,(k,base[k],v)
  else: assert abs(base[k]-v)<1e-6,(k,base[k],v)
 cand,trace=_eth_loss_stress_throttle(t); accepted=_pareto(base,cand)
 stress=[r for r in trace if r.get('symbol')=='ETH-USDT' and r.get('stressed')]
 r={"schema_version":"zel.a1_gen2_eth_prior_loss_volatility_throttle.v1","development_only":True,"incumbent_metrics":base,"side_parity_advisory":{"enabled_for_signal_assist_only":True,"sizing_authority":False,"order_authority":False,"note":"retain side-risk relation as advisory/confidence feature only; no direct exposure mutation"},"axis":{"name":"eth_prior_completed_loss_volatility_state_50pct_risk_throttle","future_information_used":False,"eth_window_trades":ETH_WINDOW,"eth_stress_weight":ETH_STRESS_WEIGHT,"threshold_sweep":False,"btc_weight":1.0,"signal_rule_changed":False,"exit_rule_changed":False,"trade_path_changed":False,"stress_trade_count":len(stress),"new_metrics":cand,"accepted_pareto":accepted,"state":"PASS_PARETO_IMPROVEMENT" if accepted else "SEALED_FAIL_NO_REUSE"},"selection_authority":False,"promotion_authority":False,"execution_authority":"NONE","order_authority":"BLOCKED","live_trade_authority":"BLOCKED"}
 output.parent.mkdir(parents=True,exist_ok=True); output.write_text(json.dumps(r,sort_keys=True,indent=2)+'\n'); print('ETH_PRIOR_LOSS_VOL_THROTTLE='+json.dumps(r,sort_keys=True)); return r
if __name__=='__main__': run(Path('out/a1_gen2_incumbent_hardening_v1.json'))
