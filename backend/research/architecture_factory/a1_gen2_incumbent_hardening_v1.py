#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
import backend.research.architecture_factory.a1_gen2_generic_dev_econ_v1 as econ

ENTRY_RULE="ret(1) < -0.02 or (ret(1) > 0.02 and close < sma('close',50))"
SIDE_RULE="long if ret(1) < -0.02 else short"
HOLD=12; ACTIVATE_BPS=300.0; LOCK_GROSS_BPS=14.0
WINDOW=5; MIN_WEIGHT=0.50
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

def _proportional_symbol_downside_throttle(t):
 hist={s:[] for s in econ.SYMBOLS}; wh={s:[] for s in econ.SYMBOLS}; weighted=[]; trace=[]
 for x in t:
  s=x['symbol']; h=hist[s]; windows=wh[s]; recent=None; benchmark=None; stressed=False; w=1.0
  if len(h)>=WINDOW:
   recent=sum(max(-v,0.0) for v in h[-WINDOW:])/WINDOW
   if windows:
    benchmark=_median(windows)
    stressed=recent>benchmark and recent>0
    if stressed: w=max(MIN_WEIGHT,min(1.0,benchmark/recent))
  weighted.append(x['net_bps']*w)
  trace.append({"symbol":s,"side":x['side'],"weight":w,"recent_downside_bps":recent,"prior_window_median_bps":benchmark,"stressed":stressed})
  h.append(x['net_bps'])
  if len(h)>=WINDOW: windows.append(sum(max(-v,0.0) for v in h[-WINDOW:])/WINDOW)
 return _metrics(weighted),trace

def _pareto(a,b):
 return b['net_pnl_bps']>a['net_pnl_bps'] and b['net_expectancy_bps']>a['net_expectancy_bps'] and b['profit_factor']>a['profit_factor'] and b['drawdown_bps']<a['drawdown_bps']

def run(output:Path):
 t=_trades(); base=_metrics([x['net_bps'] for x in t])
 for k,v in EXPECTED.items():
  if k=='trades': assert base[k]==v,(k,base[k],v)
  else: assert abs(base[k]-v)<1e-6,(k,base[k],v)
 cand,trace=_proportional_symbol_downside_throttle(t); accepted=_pareto(base,cand)
 weights=[r['weight'] for r in trace]
 by_symbol={}
 for s in econ.SYMBOLS:
  rs=[r for r in trace if r['symbol']==s]; by_symbol[s]={"stress_trades":sum(1 for r in rs if r['stressed']),"min_weight":min(r['weight'] for r in rs),"avg_weight":sum(r['weight'] for r in rs)/len(rs)}
 r={"schema_version":"zel.a1_gen2_proportional_symbol_downside_throttle.v1","development_only":True,"incumbent_metrics":base,"axis":{"name":"causal_same_symbol_prior_downside_ratio_proportional_risk_throttle","future_information_used":False,"window_trades":WINDOW,"min_weight":MIN_WEIGHT,"threshold_sweep":False,"signal_rule_changed":False,"exit_rule_changed":False,"trade_path_changed":False,"weight_summary":{"min":min(weights),"avg":sum(weights)/len(weights)},"by_symbol":by_symbol,"new_metrics":cand,"accepted_pareto":accepted,"state":"PASS_PARETO_IMPROVEMENT" if accepted else "SEALED_FAIL_NO_REUSE"},"side_parity_role":"advisory_only","selection_authority":False,"promotion_authority":False,"execution_authority":"NONE","order_authority":"BLOCKED","live_trade_authority":"BLOCKED"}
 output.parent.mkdir(parents=True,exist_ok=True); output.write_text(json.dumps(r,sort_keys=True,indent=2)+'\n'); print('PROPORTIONAL_SYMBOL_DOWNSIDE_THROTTLE='+json.dumps(r,sort_keys=True)); return r
if __name__=='__main__': run(Path('out/a1_gen2_incumbent_hardening_v1.json'))
