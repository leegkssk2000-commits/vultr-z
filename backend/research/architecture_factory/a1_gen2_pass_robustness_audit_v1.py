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
   side=econ._side(BASE['executable_spec']['side_rule'],eng,i);ei=i+1;xi=min(ei+11,len(rs)-1);ep=rs[ei]['open'];xp=rs[xi]['close'];gross=(xp/ep-1)*10000*(1 if side=='long' else -1);sma=_sma50(rs,i)
   out.append({'symbol':symbol,'side':side,'gross_bps':gross,'net_bps':gross-econ.COST_BPS,'signal_regime50':'above_sma50' if rs[i]['close']>=sma else 'below_sma50'});i=max(i+1,xi+1)
 return out
def run(output:Path):
 base=_eval(BASE);bm=_m(base);actual=_actual_trades();result={'schema_version':'zel.a1_gen2_pass_robustness_audit.v3','development_only':True,'candidate_id':BASE['candidate_id'],'baseline':base,'actual_trade_count':len(actual),'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED','live_trade_authority':'BLOCKED','exchange_order_submitted':False,'protected_mutations':0}
 output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(result,sort_keys=True,indent=2)+'\n');return result
if __name__=='__main__':
 run(Path('out/a1_gen2_pass_robustness_audit_v1.json'))
 import backend.research.architecture_factory.a1_gen2_incumbent_hardening_v1 as hardening
 hardening.run(Path('out/a1_gen2_incumbent_hardening_v1.json'))
 import backend.research.architecture_factory.a1_gen2_4h_trend_breakout_dev_v1 as hf
 print('HIGH_FREQ_MAIN_CANDIDATE='+json.dumps(hf.run(),sort_keys=True))
 import backend.research.architecture_factory.a1_gen2_4h_ma_stack_hardening_v1 as hfhard
 print('HIGH_FREQ_MA_STACK_HARDENING='+json.dumps(hfhard.run(),sort_keys=True))
 import backend.research.architecture_factory.a1_gen2_4h_ema_structure_v1 as ema
 print('HIGH_FREQ_EMA_STRUCTURE='+json.dumps(ema.run(),sort_keys=True))
