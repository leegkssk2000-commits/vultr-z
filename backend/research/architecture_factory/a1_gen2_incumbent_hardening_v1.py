#!/usr/bin/env python3
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import backend.research.architecture_factory.a1_gen2_generic_dev_econ_v1 as econ
INCUMBENT={"candidate_id":"repair_short_above_sma50_veto_v1","strategy_id":"NEW","provider":"deterministic_repair","required_sources":["ohlcv","volume"],"evidence_ids":["F11","F16"],"executable_spec":{"bar_interval":"1d","features":[],"entry_rule":"ret(1) < -0.02 or (ret(1) > 0.02 and close < sma('close',50))","side_rule":"long if ret(1) < -0.02 else short","exit_rule":"time_stop","max_hold_bars":12,"entry_timing":"next_bar_open","cost_model":"verified_14bps_or_more","development_data_rule":"strictly_before_GEN1_boundary","parameter_provenance":"fixed_from_accepted_single_axis_repair"}}
EXPECTED={"trades":227,"net_pnl_bps":30409.952836041128,"net_expectancy_bps":133.96454993850716,"profit_factor":1.4015761936875084,"drawdown_bps":7629.590881650351}
def _stats(rows:list[dict[str,Any]],cost:float=14.0,flip:bool=False)->dict[str,Any]:
 g=[]; n=[]
 for t in rows:
  x=float(t['gross_bps']); x=-x if flip else x; g.append(x); n.append(x-cost)
 z=len(n)
 return {"trades":z,"cost_bps_per_trade":cost,"gross_expectancy_bps":sum(g)/z if z else None,"net_expectancy_bps":sum(n)/z if z else None,"net_pnl_bps":sum(n),"profit_factor":econ._pf(n) if z else None,"payoff":econ._payoff(n) if z else None,"win_rate":sum(x>0 for x in n)/z if z else None,"drawdown_bps":econ._dd(n) if z else 0.0}
def _trades()->list[dict[str,Any]]:
 out=[]; spec=INCUMBENT['executable_spec']; hold=int(spec['max_hold_bars'])
 for symbol in econ.SYMBOLS:
  rs=econ.bars(symbol,'1d'); eng=econ.Expr(rs,{}) ; i=30
  while i<len(rs)-1:
   try: fire=bool(eng.eval(spec['entry_rule'],i))
   except Exception: fire=False
   if not fire: i+=1; continue
   side=econ._side(spec['side_rule'],eng,i); entry_i=i+1; exit_i=min(entry_i+hold-1,len(rs)-1)
   ep=rs[entry_i]['open']; xp=rs[exit_i]['close']; gross=(xp/ep-1.0)*10000*(1 if side=='long' else -1)
   prev=rs[i-1]['close']; ret=rs[i]['close']/prev-1.0 if prev else 0.0; w=[x['close'] for x in rs[max(0,i-49):i+1]]; sma50=sum(w)/len(w)
   regime='above_sma50' if rs[i]['close']>=sma50 else 'below_sma50'; year=datetime.fromtimestamp(rs[i]['ts']/1000,tz=timezone.utc).year; a=abs(ret)
   bucket='2_3pct' if a<0.03 else ('3_4pct' if a<0.04 else ('4_5pct' if a<0.05 else '5pct_plus'))
   out.append({'symbol':symbol,'side':side,'gross_bps':gross,'signal_ret1':ret,'shock_bucket':bucket,'signal_regime50':regime,'signal_year':year,'year_side':f'{year}|{side}','year_regime':f'{year}|{regime}','year_side_regime':f'{year}|{side}|{regime}','year_side_regime_shock':f'{year}|{side}|{regime}|{bucket}','entry_ts':int(rs[entry_i]['ts']),'exit_ts':int(rs[exit_i]['ts'])})
   i=max(i+1,exit_i+1)
 return out
def _group(rows:list[dict[str,Any]],key:str,cost:float=14.0)->dict[str,Any]:
 d={}
 for r in rows:d.setdefault(str(r[key]),[]).append(r)
 return {k:_stats(v,cost) for k,v in sorted(d.items())}
def run(output:Path)->dict[str,Any]:
 row=econ.evaluate_candidate(INCUMBENT); m=row.get('metrics') or {}
 for k,v in EXPECTED.items():
  if k=='trades':
   if int(m.get(k) or 0)!=v: raise RuntimeError(f'INCUMBENT_MISMATCH:{k}:{m.get(k)}:{v}')
  elif abs(float(m.get(k) or 0)-float(v))>1e-6: raise RuntimeError(f'INCUMBENT_MISMATCH:{k}:{m.get(k)}:{v}')
 trades=_trades(); base=_stats(trades,14.0)
 if base['trades']!=EXPECTED['trades'] or abs(base['net_pnl_bps']-EXPECTED['net_pnl_bps'])>1e-6: raise RuntimeError('INCUMBENT_PATH_MISMATCH')
 costs={str(c):_stats(trades,float(c)) for c in (14,20,28,40)}; by_symbol=_group(trades,'symbol'); by_side=_group(trades,'side'); by_year=_group(trades,'signal_year'); by_regime=_group(trades,'signal_regime50')
 focus=[t for t in trades if t['signal_year']==2026]; temporal={"2026":_stats(focus),"by_side":_group(focus,'side'),"by_symbol":_group(focus,'symbol'),"by_regime50":_group(focus,'signal_regime50'),"by_shock":_group(focus,'shock_bucket'),"by_side_regime":_group(focus,'year_side_regime'),"by_side_regime_shock":_group(focus,'year_side_regime_shock')}
 neg=_stats(trades,14.0,flip=True); losses=sorted([t for t in trades if float(t['gross_bps'])-14<0],key=lambda t:float(t['gross_bps'])-14); total=-sum(float(t['gross_bps'])-14 for t in losses); top=-sum(float(t['gross_bps'])-14 for t in losses[:10])
 result={"schema_version":"zel.a1_gen2_incumbent_hardening.v2","development_only":True,"candidate_id":INCUMBENT['candidate_id'],"incumbent_metrics":base,"cost_stress":costs,"by_symbol":by_symbol,"by_side":by_side,"by_year":by_year,"by_regime50":by_regime,"temporal_fragility_attribution":temporal,"negative_controls":{"side_flip_same_events":neg},"loss_concentration":{"loss_trade_count":len(losses),"total_loss_bps":total,"top10_loss_bps":top,"top10_share_of_loss":top/total if total else 0.0},"hardening_summary":{"robust_cost_28":bool((costs['28']['net_expectancy_bps'] or 0)>0 and (costs['28']['profit_factor'] or 0)>1),"both_symbols_positive":all((x.get('net_expectancy_bps') or 0)>0 and (x.get('profit_factor') or 0)>1 for x in by_symbol.values()),"negative_control_ok":bool((neg.get('net_expectancy_bps') or 0)<0 and (neg.get('profit_factor') or 9)<1),"year_positive_count":sum(1 for x in by_year.values() if (x.get('net_expectancy_bps') or 0)>0 and (x.get('profit_factor') or 0)>1),"year_total":len(by_year)},"alpha_proof_prep_only":True,"selection_authority":False,"promotion_authority":False,"execution_authority":"NONE","order_authority":"BLOCKED","live_trade_authority":"BLOCKED","exchange_order_submitted":False,"protected_mutations":0}
 output.parent.mkdir(parents=True,exist_ok=True); output.write_text(json.dumps(result,sort_keys=True,indent=2)+'\n'); print('HARDENING_V2='+json.dumps(result,sort_keys=True)); return result
if __name__=='__main__':run(Path('out/a1_gen2_incumbent_hardening_v1.json'))
