#!/usr/bin/env python3
from __future__ import annotations
import json,statistics
from datetime import datetime,timezone
from pathlib import Path
from typing import Any
import backend.research.architecture_factory.a1_gen2_generic_dev_econ_v1 as econ
INCUMBENT={"candidate_id":"repair_short_above_sma50_veto_v1","strategy_id":"NEW","provider":"deterministic_repair","required_sources":["ohlcv","volume"],"evidence_ids":["F11","F16"],"executable_spec":{"bar_interval":"1d","features":[],"entry_rule":"ret(1) < -0.02 or (ret(1) > 0.02 and close < sma('close',50))","side_rule":"long if ret(1) < -0.02 else short","exit_rule":"time_stop","max_hold_bars":12,"entry_timing":"next_bar_open","cost_model":"verified_14bps_or_more","development_data_rule":"strictly_before_GEN1_boundary"}}
EXPECTED={"trades":227,"net_pnl_bps":30409.952836041128,"net_expectancy_bps":133.96454993850716,"profit_factor":1.4015761936875084,"drawdown_bps":7629.590881650351}
def _from_gross(g,cost=14.0):
 n=[x-cost for x in g];z=len(n);return {'trades':z,'cost_bps_per_trade':cost,'gross_expectancy_bps':sum(g)/z if z else None,'net_expectancy_bps':sum(n)/z if z else None,'net_pnl_bps':sum(n),'profit_factor':econ._pf(n) if z else None,'payoff':econ._payoff(n) if z else None,'win_rate':sum(x>0 for x in n)/z if z else None,'drawdown_bps':econ._dd(n) if z else 0.0}
def _stats(rows,cost=14.0,flip=False):return _from_gross([(-1 if flip else 1)*float(t['gross_bps']) for t in rows],cost)
def _trades():
 out=[];s=INCUMBENT['executable_spec'];hold=12
 for symbol in econ.SYMBOLS:
  rs=econ.bars(symbol,'1d');eng=econ.Expr(rs,{});i=30
  while i<len(rs)-1:
   try:fire=bool(eng.eval(s['entry_rule'],i))
   except Exception:fire=False
   if not fire:i+=1;continue
   side=econ._side(s['side_rule'],eng,i);ei=i+1;xi=min(ei+hold-1,len(rs)-1);ep=rs[ei]['open'];xp=rs[xi]['close'];gross=(xp/ep-1)*10000*(1 if side=='long' else -1);mfe=0.0;mae=0.0;first200=None
   for d,j in enumerate(range(ei,xi+1),start=1):
    if side=='long':fav=(rs[j]['high']/ep-1)*10000;adv=(1-rs[j]['low']/ep)*10000
    else:fav=(1-rs[j]['low']/ep)*10000;adv=(rs[j]['high']/ep-1)*10000
    mfe=max(mfe,fav);mae=max(mae,adv)
    if first200 is None and fav>=200:first200=d
   prev=rs[i-1]['close'];ret=rs[i]['close']/prev-1 if prev else 0;w=[x['close'] for x in rs[max(0,i-49):i+1]];sma=sum(w)/len(w);reg='above_sma50' if rs[i]['close']>=sma else 'below_sma50';year=datetime.fromtimestamp(rs[i]['ts']/1000,tz=timezone.utc).year;a=abs(ret);bucket='2_3pct' if a<.03 else ('3_4pct' if a<.04 else ('4_5pct' if a<.05 else '5pct_plus'))
   out.append({'symbol':symbol,'side':side,'gross_bps':gross,'mfe_bps':mfe,'mae_bps':mae,'first_200_day':first200,'signal_ret1':ret,'shock_bucket':bucket,'signal_regime50':reg,'signal_year':year,'year_side_regime':f'{year}|{side}|{reg}','year_side_regime_shock':f'{year}|{side}|{reg}|{bucket}','entry_ts':int(rs[ei]['ts']),'exit_ts':int(rs[xi]['ts'])});i=max(i+1,xi+1)
 return out
def _group(rows,key,cost=14.0):
 d={}
 for r in rows:d.setdefault(str(r[key]),[]).append(r)
 return {k:_stats(v,cost) for k,v in sorted(d.items())}
def _mfe_summary(trades):
 losers=[t for t in trades if t['gross_bps']-14<0];winners=[t for t in trades if t['gross_bps']-14>0]
 def avg(xs,k):return sum(t[k] for t in xs)/len(xs) if xs else None
 capture={}
 for th in (100,200,300,500):
  x=[t for t in losers if t['mfe_bps']>=th];capture[str(th)]={'losing_trades_that_reached_mfe':len(x),'final_net_loss_bps':sum(t['gross_bps']-14 for t in x),'share_of_all_losses':len(x)/len(losers) if losers else 0}
 return {'winner_count':len(winners),'loser_count':len(losers),'winner_avg_mfe_bps':avg(winners,'mfe_bps'),'winner_avg_mae_bps':avg(winners,'mae_bps'),'loser_avg_mfe_bps':avg(losers,'mfe_bps'),'loser_avg_mae_bps':avg(losers,'mae_bps'),'loser_median_mfe_bps':statistics.median([t['mfe_bps'] for t in losers]) if losers else None,'loser_median_mae_bps':statistics.median([t['mae_bps'] for t in losers]) if losers else None,'mfe_then_loss_capture':capture}
def run(output:Path):
 row=econ.evaluate_candidate(INCUMBENT);m=row.get('metrics') or {}
 for k,v in EXPECTED.items():
  if k=='trades':
   if int(m.get(k) or 0)!=v:raise RuntimeError(f'INCUMBENT_MISMATCH:{k}')
  elif abs(float(m.get(k) or 0)-float(v))>1e-6:raise RuntimeError(f'INCUMBENT_MISMATCH:{k}')
 trades=_trades();base=_stats(trades)
 if base['trades']!=227 or abs(base['net_pnl_bps']-EXPECTED['net_pnl_bps'])>1e-6:raise RuntimeError('INCUMBENT_PATH_MISMATCH')
 costs={str(c):_stats(trades,float(c)) for c in (14,20,28,40)};by_symbol=_group(trades,'symbol');by_side=_group(trades,'side');by_year=_group(trades,'signal_year');by_regime=_group(trades,'signal_regime50');focus=[t for t in trades if t['signal_year']==2026];neg=_stats(trades,14,True)
 temporal={'2026':_stats(focus),'by_side':_group(focus,'side'),'by_symbol':_group(focus,'symbol'),'by_regime50':_group(focus,'signal_regime50'),'by_shock':_group(focus,'shock_bucket'),'by_side_regime':_group(focus,'year_side_regime'),'by_side_regime_shock':_group(focus,'year_side_regime_shock')}
 losses=sorted([t for t in trades if t['gross_bps']-14<0],key=lambda t:t['gross_bps']-14);total=-sum(t['gross_bps']-14 for t in losses);top=-sum(t['gross_bps']-14 for t in losses[:10]);partial_gross=[(.3*200+.7*t['gross_bps']) if t['mfe_bps']>=200 else t['gross_bps'] for t in trades];partial=_from_gross(partial_gross);pareto=partial['net_pnl_bps']>base['net_pnl_bps'] and partial['net_expectancy_bps']>base['net_expectancy_bps'] and partial['profit_factor']>base['profit_factor'] and partial['drawdown_bps']<base['drawdown_bps']
 result={'schema_version':'zel.a1_gen2_incumbent_hardening.v3','development_only':True,'candidate_id':INCUMBENT['candidate_id'],'incumbent_metrics':base,'cost_stress':costs,'by_symbol':by_symbol,'by_side':by_side,'by_year':by_year,'by_regime50':by_regime,'temporal_fragility_attribution':temporal,'mfe_mae':_mfe_summary(trades),'partial30_200bps_counterfactual':{'path_preserved':True,'threshold_bps':200,'partial_fraction':0.30,'old_metrics':base,'new_metrics':partial,'accepted_pareto':pareto,'state':'PASS_PARETO_IMPROVEMENT' if pareto else 'SEALED_FAIL_NO_REUSE'},'negative_controls':{'side_flip_same_events':neg},'loss_concentration':{'loss_trade_count':len(losses),'total_loss_bps':total,'top10_loss_bps':top,'top10_share_of_loss':top/total if total else 0},'hardening_summary':{'robust_cost_28':costs['28']['net_expectancy_bps']>0 and costs['28']['profit_factor']>1,'both_symbols_positive':all(x['net_expectancy_bps']>0 and x['profit_factor']>1 for x in by_symbol.values()),'negative_control_ok':neg['net_expectancy_bps']<0 and neg['profit_factor']<1,'year_positive_count':sum(1 for x in by_year.values() if x['net_expectancy_bps']>0 and x['profit_factor']>1),'year_total':len(by_year)},'alpha_proof_prep_only':True,'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED','live_trade_authority':'BLOCKED','exchange_order_submitted':False,'protected_mutations':0}
 output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(result,sort_keys=True,indent=2)+'\n');print('MFE_PARTIAL_TEST='+json.dumps({'mfe_mae':result['mfe_mae'],'partial':result['partial30_200bps_counterfactual']},sort_keys=True));return result
if __name__=='__main__':run(Path('out/a1_gen2_incumbent_hardening_v1.json'))
