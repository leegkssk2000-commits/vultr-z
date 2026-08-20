#!/usr/bin/env python3
from __future__ import annotations
import json
from copy import deepcopy
from datetime import datetime,timezone
from pathlib import Path
import backend.research.architecture_factory.a1_gen2_generic_dev_econ_v1 as econ
BASE={"candidate_id":"new_architecture_basis_premium_collector","strategy_id":"NEW","provider":"openai","required_sources":["ohlcv","volume"],"executable_spec":{"bar_interval":"1d","features":[{"name":"ret_sma_7","formula":"sma(ret(1),7)"}],"entry_rule":"ret(1) < -0.02 or ret(1) > 0.02","side_rule":"long if ret(1) < -0.02 else short","exit_rule":"time_stop","max_hold_bars":12,"entry_timing":"next_bar_open","cost_model":"verified_14bps_or_more","development_data_rule":"strictly_before_GEN1_boundary"}}
def _eval(c):return econ.evaluate_candidate(c)
def _m(r):
 x=r.get('metrics') or {};return {k:x.get(k) for k in ('trades','gross_expectancy_bps','net_expectancy_bps','net_pnl_bps','profit_factor','payoff','win_rate','drawdown_bps','events_per_day','net_bps_per_calendar_day','cost_bps_per_trade')}
def _variant(cid,entry,side='long if ret(1) < -0.02 else short'):
 c=deepcopy(BASE);c['candidate_id']=cid;c['executable_spec']['entry_rule']=entry;c['executable_spec']['side_rule']=side;return c
def _metrics(g):
 n=[x-econ.COST_BPS for x in g];z=len(n);return {'trades':z,'gross_expectancy_bps':sum(g)/z if z else None,'net_expectancy_bps':sum(n)/z if z else None,'net_pnl_bps':sum(n),'profit_factor':econ._pf(n) if z else None,'payoff':econ._payoff(n) if z else None,'win_rate':sum(x>0 for x in n)/z if z else None,'drawdown_bps':econ._dd(n) if z else 0.0,'cost_bps_per_trade':econ.COST_BPS}
def _stats(rows):return _metrics([float(x['gross_bps']) for x in rows])
def _sma50(rs,i):
 w=[x['close'] for x in rs[max(0,i-49):i+1]];return sum(w)/len(w)
def _atr14(rs,i):
 vals=[]
 for j in range(max(1,i-13),i+1):
  pc=rs[j-1]['close'];vals.append(max(rs[j]['high']-rs[j]['low'],abs(rs[j]['high']-pc),abs(rs[j]['low']-pc)))
 return sum(vals)/len(vals) if vals else 0.0
def _actual_trades():
 out=[]
 for symbol in econ.SYMBOLS:
  rs=econ.bars(symbol,'1d');eng=econ.Expr(rs,{});i=30
  while i<len(rs)-1:
   try:fire=bool(eng.eval(BASE['executable_spec']['entry_rule'],i))
   except Exception:fire=False
   if not fire:i+=1;continue
   side=econ._side(BASE['executable_spec']['side_rule'],eng,i);ei=i+1;xi=min(ei+11,len(rs)-1);ep=rs[ei]['open'];xp=rs[xi]['close'];gross=(xp/ep-1)*10000*(1 if side=='long' else -1);prev=rs[i-1]['close'];ret=rs[i]['close']/prev-1 if prev else 0;sma=_sma50(rs,i)
   out.append({'symbol':symbol,'side':side,'gross_bps':gross,'net_bps':gross-econ.COST_BPS,'signal_ret1':ret,'signal_regime50':'above_sma50' if rs[i]['close']>=sma else 'below_sma50','signal_year':datetime.fromtimestamp(rs[i]['ts']/1000,tz=timezone.utc).year,'entry_ts':int(rs[ei]['ts']),'exit_ts':int(rs[xi]['ts'])});i=max(i+1,xi+1)
 return out
def _custom(mode):
 gross=[];entry_rule="ret(1) < -0.02 or (ret(1) > 0.02 and close < sma('close',50))";side_rule='long if ret(1) < -0.02 else short'
 for symbol in econ.SYMBOLS:
  rs=econ.bars(symbol,'1d');eng=econ.Expr(rs,{});i=30
  while i<len(rs)-1:
   try:fire=bool(eng.eval(entry_rule,i))
   except Exception:fire=False
   if not fire:i+=1;continue
   side=econ._side(side_rule,eng,i);below=rs[i]['close']<_sma50(rs,i);hold=6 if mode=='6d' and side=='long' and below else 12;ei=i+1;xi=min(ei+hold-1,len(rs)-1);ep=rs[ei]['open'];xp=rs[xi]['close'];actual_xi=xi
   if mode=='2atr':
    atr=_atr14(rs,i);stop=ep-2*atr if side=='long' else ep+2*atr
    for j in range(ei,xi+1):
     if side=='long' and rs[j]['low']<=stop:
      xp=min(stop,rs[j]['open']);actual_xi=j;break
     if side=='short' and rs[j]['high']>=stop:
      xp=max(stop,rs[j]['open']);actual_xi=j;break
   gross.append((xp/ep-1)*10000*(1 if side=='long' else -1));i=max(i+1,actual_xi+1)
 return _metrics(gross)
def _group(rows,key):
 d={}
 for t in rows:d.setdefault(str(t[key]),[]).append(t)
 return {k:_stats(v) for k,v in sorted(d.items())}
def _delta(a,b):return {'net_expectancy_bps':(b.get('net_expectancy_bps') or 0)-(a.get('net_expectancy_bps') or 0),'net_pnl_bps':(b.get('net_pnl_bps') or 0)-(a.get('net_pnl_bps') or 0),'profit_factor':(b.get('profit_factor') or 0)-(a.get('profit_factor') or 0),'payoff':(b.get('payoff') or 0)-(a.get('payoff') or 0),'win_rate':(b.get('win_rate') or 0)-(a.get('win_rate') or 0),'drawdown_bps':(b.get('drawdown_bps') or 0)-(a.get('drawdown_bps') or 0),'trades':(b.get('trades') or 0)-(a.get('trades') or 0)}
def _pareto(a,b):return (b.get('net_expectancy_bps') or -1e99)>(a.get('net_expectancy_bps') or -1e99) and (b.get('net_pnl_bps') or -1e99)>(a.get('net_pnl_bps') or -1e99) and (b.get('profit_factor') or -1e99)>(a.get('profit_factor') or -1e99) and (b.get('drawdown_bps') or 1e99)<(a.get('drawdown_bps') or 1e99)
def run(output:Path):
 base=_eval(BASE);bm=_m(base);actual=_actual_trades();ast=_stats(actual)
 if ast['trades']!=bm['trades'] or abs(ast['net_pnl_bps']-bm['net_pnl_bps'])>1e-6:raise RuntimeError('ATTRIBUTION_PATH_MISMATCH')
 bad=_variant('repair_regime_owned_large_move_reversion_v1',"(ret(1) < -0.02 and close > sma('close',50)) or (ret(1) > 0.02 and close < sma('close',50))");rm=_m(_eval(bad));losses=sorted([t for t in actual if t['net_bps']<0],key=lambda x:x['net_bps']);tl=-sum(t['net_bps'] for t in losses);t10=-sum(t['net_bps'] for t in losses[:10]);attr={'actual_path_verified':True,'actual_trade_count':len(actual),'actual_metrics':ast,'by_side':_group(actual,'side'),'by_symbol':_group(actual,'symbol'),'by_year':_group(actual,'signal_year'),'by_regime50':_group(actual,'signal_regime50'),'loss_concentration':{'loss_trade_count':len(losses),'total_loss_bps':tl,'top10_loss_bps':t10,'top10_share_of_loss':t10/tl if tl else 0,'worst10':[{k:t[k] for k in ('symbol','side','net_bps','signal_ret1','signal_regime50','signal_year','entry_ts','exit_ts')} for t in losses[:10]]}}
 r2=_eval(_variant('repair_short_above_sma50_veto_v1',"ret(1) < -0.02 or (ret(1) > 0.02 and close < sma('close',50))"));m2=_m(r2);a2=_pareto(bm,m2)
 m3=_m(_eval(_variant('repair_falling_knife_ge3pct_below_sma50_veto_v1',"(ret(1) < -0.02 and (close >= sma('close',50) or ret(1) > -0.03)) or (ret(1) > 0.02 and close < sma('close',50))")));m4=_custom('6d');m5=_custom('2atr')
 result={'schema_version':'zel.a1_gen2_pass_robustness_audit.v2','development_only':True,'candidate_id':BASE['candidate_id'],'mechanism_integrity':{'relabel':'large_move_mean_reversion'},'baseline':base,'actual_path_attribution':attr,'sealed_failed_repair':{'axis':'regime_ownership_only','old_metrics':bm,'new_metrics':rm,'delta':_delta(bm,rm),'accepted':False,'state':'SEALED_FAIL_NO_REUSE'},'second_axis_repair':{'axis':'short_adverse_regime_veto_only','threshold_changed':False,'holding_horizon_changed':False,'long_rule_changed':False,'new_metrics':m2,'old_metrics':bm,'delta':_delta(bm,m2),'repair':r2,'accepted_for_further_prep':a2,'state':'PASS_PARETO_IMPROVEMENT' if a2 else 'SEALED_FAIL_NO_REUSE'},'third_axis_repair':{'axis':'long_falling_knife_veto_ge3pct_below_sma50_only','old_metrics':m2,'new_metrics':m3,'delta':_delta(m2,m3),'accepted_for_further_prep':_pareto(m2,m3),'state':'PASS_PARETO_IMPROVEMENT' if _pareto(m2,m3) else 'SEALED_FAIL_NO_REUSE'},'fourth_axis_repair':{'axis':'long_below_sma50_time_stop_12d_to_6d_only','old_metrics':m2,'new_metrics':m4,'delta':_delta(m2,m4),'accepted_for_further_prep':_pareto(m2,m4),'state':'PASS_PARETO_IMPROVEMENT' if _pareto(m2,m4) else 'SEALED_FAIL_NO_REUSE'},'fifth_axis_repair':{'axis':'two_atr14_adverse_stop_only','hypothesis_source':'Gemini ATR-stop suggestion; fixed 2ATR, no sweep','gap_model':'worse_of_stop_or_bar_open','entry_rule_changed':False,'time_stop_changed':False,'old_metrics':m2,'new_metrics':m5,'delta':_delta(m2,m5),'accepted_for_further_prep':_pareto(m2,m5),'state':'PASS_PARETO_IMPROVEMENT' if _pareto(m2,m5) else 'SEALED_FAIL_NO_REUSE'},'next_repair_authority':'PRESERVE_LATEST_ACCEPTED_ONLY','selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED','live_trade_authority':'BLOCKED','exchange_order_submitted':False,'protected_mutations':0}
 output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(result,sort_keys=True,indent=2)+'\n');print('ROBUSTNESS_ATR_TEST='+json.dumps({'second':result['second_axis_repair'],'fifth':result['fifth_axis_repair']},sort_keys=True));return result
if __name__=='__main__':
 run(Path('out/a1_gen2_pass_robustness_audit_v1.json'))
 import backend.research.architecture_factory.a1_gen2_incumbent_hardening_v1 as hardening
 hardening.run(Path('out/a1_gen2_incumbent_hardening_v1.json'))
 import backend.research.architecture_factory.a1_gen2_4h_trend_breakout_dev_v1 as hf
 print('HIGH_FREQ_MAIN_CANDIDATE='+json.dumps(hf.run(),sort_keys=True))
