#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
import backend.research.architecture_factory.a1_gen2_generic_dev_econ_v1 as econ

ENTRY_RULE="ret(1) < -0.02 or (ret(1) > 0.02 and close < sma('close',50))"
SIDE_RULE="long if ret(1) < -0.02 else short"
HOLD=12; BASE_ACT=300.0; LOCK_GROSS_BPS=14.0; ATR_N=14
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
   side=econ._side(SIDE_RULE,eng,i); ei=i+1; xi=min(ei+HOLD-1,len(rs)-1); ep=rs[ei]['open']; atr=_atr(rs,i); shock=abs(rs[i]['close']-rs[i-1]['close']); shock_atr=shock/atr if atr else 0.0
   w=[x['close'] for x in rs[max(0,i-49):i+1]]; sma50=sum(w)/len(w); regime='above_sma50' if rs[i]['close']>=sma50 else 'below_sma50'
   score=max(0.0,min(1.0,shock_atr-1.0)); act=BASE_ACT+100.0*score
   out.append({"symbol":symbol,"side":side,"regime50":regime,"shock_atr":shock_atr,"base_net_bps":_outcome(rs,side,ei,xi,ep,BASE_ACT),"candidate_net_bps":_outcome(rs,side,ei,xi,ep,act),"activation_bps":act})
   i=max(i+1,xi+1)
 return out
def _group(rows,key):
 d={}
 for x in rows: d.setdefault(str(x[key]),[]).append(x['base_net_bps'])
 return {k:_metrics(v) for k,v in sorted(d.items())}
def _shock_bins(rows):
 bins={'lt1':[],'1to1p25':[],'1p25to1p5':[],'ge1p5':[]}
 for x in rows:
  a=x['shock_atr']; k='lt1' if a<1 else '1to1p25' if a<1.25 else '1p25to1p5' if a<1.5 else 'ge1p5'; bins[k].append(x['base_net_bps'])
 return {k:_metrics(v) if v else {"trades":0} for k,v in bins.items()}
def _pareto(a,b): return b['net_pnl_bps']>a['net_pnl_bps'] and b['net_expectancy_bps']>a['net_expectancy_bps'] and b['profit_factor']>a['profit_factor'] and b['drawdown_bps']<a['drawdown_bps']
def run(output:Path):
 t=_trades(); base=_metrics([x['base_net_bps'] for x in t]); cand=_metrics([x['candidate_net_bps'] for x in t])
 for k,v in EXPECTED.items():
  if k=='trades': assert base[k]==v,(k,base[k],v)
  else: assert abs(base[k]-v)<1e-6,(k,base[k],v)
 hi=[x for x in t if x['shock_atr']>=1.0]; accepted=_pareto(base,cand)
 r={"schema_version":"zel.a1_gen2_atr_alpha_decomposition_continuous_lock.v1","development_only":True,"incumbent_metrics":base,"diagnostic":{"atr_high_quality_trade_count":len(hi),"atr_high_quality_metrics":_metrics([x['base_net_bps'] for x in hi]),"by_symbol":_group(hi,'symbol'),"by_side":_group(hi,'side'),"by_regime50":_group(hi,'regime50'),"by_shock_atr_bin":_shock_bins(t)},"axis":{"name":"continuous_atr_shock_confidence_delays_profit_lock_300_to_max400","future_information_used":False,"threshold_sweep":False,"signal_deleted":False,"position_size_changed":False,"base_activation_bps":BASE_ACT,"max_activation_bps":400.0,"score_formula":"clip(shock_atr-1,0,1)","changed_trade_count":sum(1 for x in t if abs(x['candidate_net_bps']-x['base_net_bps'])>1e-9),"new_metrics":cand,"accepted_pareto":accepted,"state":"PASS_PARETO_IMPROVEMENT" if accepted else "SEALED_FAIL_NO_REUSE"},"atr_role":"advisory_only_unless_pareto","side_parity_role":"advisory_only","selection_authority":False,"promotion_authority":False,"execution_authority":"NONE","order_authority":"BLOCKED","live_trade_authority":"BLOCKED"}
 output.parent.mkdir(parents=True,exist_ok=True); output.write_text(json.dumps(r,sort_keys=True,indent=2)+'\n'); print('ATR_ALPHA_DECOMP_CONTINUOUS_LOCK='+json.dumps(r,sort_keys=True)); return r
if __name__=='__main__': run(Path('out/a1_gen2_incumbent_hardening_v1.json'))
