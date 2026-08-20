#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
import backend.research.architecture_factory.a1_gen2_generic_dev_econ_v1 as econ

ENTRY_RULE="ret(1) < -0.02 or (ret(1) > 0.02 and close < sma('close',50))"
SIDE_RULE="long if ret(1) < -0.02 else short"
HOLD=12; ACTIVATE_BPS=300.0; LOCK_GROSS_BPS=14.0; SHRINK=0.50
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

def _full_sample_side_parity(t):
 loss={s:[abs(x['net_bps']) for x in t if x['side']==s and x['net_bps']<0] for s in ('long','short')}
 avg={s:sum(v)/len(v) for s,v in loss.items()}
 raw={s:min(avg.values())/avg[s] for s in avg}; mean=sum(raw[x['side']] for x in t)/len(t); w={s:raw[s]/mean for s in raw}
 return avg,w,_metrics([x['net_bps']*w[x['side']] for x in t])

def _walk_forward_shrunk(t):
 # Preserve the exact incumbent trade path/order. For each trade, use ONLY completed
 # losses already observed earlier in that path. If either side has no prior loss,
 # stay neutral at 1.0. Once both are observed, inverse-loss-risk weights are pair-
 # normalized to mean 1.0, then shrunk 50% toward neutral. No threshold/weight sweep.
 hist={'long':[],'short':[]}; weighted=[]; trace=[]
 for idx,x in enumerate(t):
  if hist['long'] and hist['short']:
   avg={s:sum(hist[s])/len(hist[s]) for s in ('long','short')}
   raw={s:min(avg.values())/avg[s] for s in avg}
   pair_mean=(raw['long']+raw['short'])/2.0
   normalized={s:raw[s]/pair_mean for s in raw}
   w={s:1.0+SHRINK*(normalized[s]-1.0) for s in normalized}
  else:
   avg={s:(sum(hist[s])/len(hist[s]) if hist[s] else None) for s in ('long','short')}; w={'long':1.0,'short':1.0}
  weighted.append(x['net_bps']*w[x['side']])
  trace.append({"i":idx,"side":x['side'],"weight":w[x['side']],"long_weight":w['long'],"short_weight":w['short']})
  if x['net_bps']<0: hist[x['side']].append(abs(x['net_bps']))
 return _metrics(weighted),trace

def _weight_summary(trace):
 d={s:[] for s in ('long','short')}
 for r in trace: d['long'].append(r['long_weight']); d['short'].append(r['short_weight'])
 return {s:{"min":min(v),"max":max(v),"avg":sum(v)/len(v)} for s,v in d.items()}

def _pareto(a,b):
 return b['net_pnl_bps']>a['net_pnl_bps'] and b['net_expectancy_bps']>a['net_expectancy_bps'] and b['profit_factor']>a['profit_factor'] and b['drawdown_bps']<a['drawdown_bps']

def run(output:Path):
 t=_trades(); base=_metrics([x['net_bps'] for x in t])
 for k,v in EXPECTED.items():
  if k=='trades': assert base[k]==v,(k,base[k],v)
  else: assert abs(base[k]-v)<1e-6,(k,base[k],v)
 avg,w,full=_full_sample_side_parity(t)
 wf,trace=_walk_forward_shrunk(t)
 accepted=_pareto(base,wf)
 r={"schema_version":"zel.a1_gen2_side_parity_walk_forward_shrink_salvage.v1","development_only":True,"incumbent_metrics":base,"full_sample_diagnostic":{"average_abs_loss_bps":avg,"side_weights":w,"metrics":full,"lookahead_contaminated_for_selection":True},"salvage_axis":{"name":"walk_forward_prior_losses_only_side_risk_parity_with_50pct_shrink_to_neutral","future_information_used":False,"shrink_to_neutral":SHRINK,"threshold_sweep":False,"signal_rule_changed":False,"exit_rule_changed":False,"trade_path_changed":False,"weight_summary":_weight_summary(trace),"new_metrics":wf,"accepted_pareto":accepted,"state":"PASS_PARETO_IMPROVEMENT" if accepted else "SEALED_FAIL_NO_REUSE"},"selection_authority":False,"promotion_authority":False,"execution_authority":"NONE","order_authority":"BLOCKED","live_trade_authority":"BLOCKED"}
 output.parent.mkdir(parents=True,exist_ok=True); output.write_text(json.dumps(r,sort_keys=True,indent=2)+'\n'); print('SIDE_PARITY_WALK_FORWARD_SHRINK='+json.dumps(r,sort_keys=True)); return r
if __name__=='__main__': run(Path('out/a1_gen2_incumbent_hardening_v1.json'))
