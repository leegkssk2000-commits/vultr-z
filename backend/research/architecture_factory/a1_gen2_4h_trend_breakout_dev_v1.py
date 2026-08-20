#!/usr/bin/env python3
from __future__ import annotations
import json, hashlib, math
from pathlib import Path
from backend.research.architecture_factory.a1_gen2_generic_dev_econ_v1 import BOUNDARY,COST_BPS,SYMBOLS,bars
LOOKBACK=20; SMA_N=50; HOLD=6
SCALED_SHOCK=0.02*math.sqrt(4/24)

def pf(xs):
 gp=sum(x for x in xs if x>0); gl=-sum(x for x in xs if x<0); return None if gl<=0 else gp/gl
def payoff(xs):
 w=[x for x in xs if x>0]; l=[-x for x in xs if x<0]; return None if not w or not l else (sum(w)/len(w))/(sum(l)/len(l))
def dd(xs):
 e=p=m=0.0
 for x in xs:e+=x;p=max(p,e);m=max(m,p-e)
 return m
def metrics(g,cost=COST_BPS):
 n=[x-cost for x in g]; z=len(n)
 return {'trades':z,'gross_expectancy_bps':sum(g)/z if z else None,'net_expectancy_bps':sum(n)/z if z else None,'net_pnl_bps':sum(n),'profit_factor':pf(n),'payoff':payoff(n),'win_rate':sum(x>0 for x in n)/z if z else None,'drawdown_bps':dd(n),'cost_bps_per_trade':cost}
def sma(rs,i,n=50): return sum(float(x['close']) for x in rs[i-n+1:i+1])/n
def atr_prev(rs,i,n=14):
 v=[]
 for j in range(i-n,i):
  pc=float(rs[j-1]['close']); h=float(rs[j]['high']); l=float(rs[j]['low']); v.append(max(h-l,abs(h-pc),abs(l-pc)))
 return sum(v)/len(v) if v else 0.0
def signal(mode,rs,i):
 c=float(rs[i]['close']); o=float(rs[i]['open']); s50=sma(rs,i); prev=float(rs[i-1]['close'])
 if mode in ('vol_cont','vol_cont_slope','vol_cont_break'):
  a=atr_prev(rs,i); tr=max(float(rs[i]['high'])-float(rs[i]['low']),abs(float(rs[i]['high'])-prev),abs(float(rs[i]['low'])-prev))
  if not (a>0 and tr>=1.5*a): return None
  rising=s50>sma(rs,i-1); falling=s50<sma(rs,i-1); ph=float(rs[i-1]['high']); pl=float(rs[i-1]['low'])
  if c>o and c>s50:
   if mode=='vol_cont_slope' and not rising:return None
   if mode=='vol_cont_break' and not c>ph:return None
   return 'long'
  if c<o and c<s50:
   if mode=='vol_cont_slope' and not falling:return None
   if mode=='vol_cont_break' and not c<pl:return None
   return 'short'
  return None
 r=c/prev-1 if prev else 0.0
 if abs(r)<SCALED_SHOCK:return None
 if mode=='basis_hf_short_only': return 'short' if r>0 and c<s50 else None
 return None
def run_one(mode):
 rows=[]; src={}
 for sym in SYMBOLS:
  rs=bars(sym,'4h'); src[sym]={'bars':len(rs),'first_ts':int(rs[0]['ts']) if rs else None,'last_ts':int(rs[-1]['ts']) if rs else None}; i=50
  while i<len(rs)-HOLD-1:
   side=signal(mode,rs,i)
   if side is None:i+=1;continue
   ei=i+1; xi=ei+HOLD-1; ep=float(rs[ei]['open']); xp=float(rs[xi]['close']); gross=(xp/ep-1)*10000*(1 if side=='long' else -1)
   rows.append({'symbol':sym,'side':side,'gross_bps':gross}); i=xi+1
 g=[x['gross_bps'] for x in rows]; m=metrics(g)
 by_symbol={s:metrics([x['gross_bps'] for x in rows if x['symbol']==s]) for s in SYMBOLS}
 by_side={s:metrics([x['gross_bps'] for x in rows if x['side']==s]) for s in ('long','short') if any(x['side']==s for x in rows)}
 costs={str(c):metrics(g,float(c)) for c in (14,28,40)}
 econ=bool(m['trades']>=40 and (m['net_expectancy_bps'] or 0)>0 and (m['profit_factor'] or 0)>1 and (m['payoff'] or 0)>=1)
 return {'metrics':m,'economic_candidate':econ,'source_summary':src,'by_symbol':by_symbol,'by_side':by_side,'cost_stress':costs}
def run():
 configs=[('vol_cont','newarch_4h_vol_expansion_continuation_v1','4H_TR_GE_1P5_ATR14_SMA50_CONTINUATION'),('vol_cont_slope','newarch_4h_vol_expansion_sma50_slope_v1','4H_TR_GE_1P5_ATR14_SMA50_SLOPE_ALIGNED_CONTINUATION'),('vol_cont_break','newarch_4h_vol_expansion_priorbar_break_v1','4H_TR_GE_1P5_ATR14_PRIOR_BAR_BREAK_CONTINUATION'),('basis_hf_short_only','basis_premium_collector_4h_scaled_short_only_v1','4H_TIME_SCALED_MEAN_REVERSION_SHORT_SIDE_OWNERSHIP')]
 cand={}
 for mode,cid,arch in configs:cand[cid]={'architecture':arch,**run_one(mode)}
 r={'schema_version':'zel.a1_gen2_highfreq_dual_dev.v6','boundary':BOUNDARY,'development_only':True,'prospective':False,'uses_data_strictly_before_gen1_boundary':True,'parameter_sweep':False,'tuned_thresholds':0,'scaled_basis_shock_abs_return':SCALED_SHOCK,'hold_bars':HOLD,'candidates':cand,'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED','live_trade_authority':'BLOCKED'}
 r['receipt_sha256']=hashlib.sha256(json.dumps(r,sort_keys=True,separators=(',',':')).encode()).hexdigest(); return r
if __name__=='__main__':
 r=run(); Path('out').mkdir(exist_ok=True); Path('out/a1_gen2_4h_trend_breakout_dev_v1.json').write_text(json.dumps(r,indent=2,sort_keys=True)+'\n'); print('A1_GEN2_HIGH_FREQ_DUAL='+json.dumps(r,sort_keys=True))
