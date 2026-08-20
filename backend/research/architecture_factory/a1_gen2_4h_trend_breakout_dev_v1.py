#!/usr/bin/env python3
from __future__ import annotations
import json, hashlib, math
from pathlib import Path
from backend.research.architecture_factory.a1_gen2_generic_dev_econ_v1 import BOUNDARY,COST_BPS,SYMBOLS,bars
SMA_N=50; HOLD=6; SCALED_SHOCK=0.02*math.sqrt(4/24)

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
def sma(rs,i,n=50):
 if i+1<n:return None
 return sum(float(x['close']) for x in rs[i-n+1:i+1])/n
def atr_prev(rs,i,n=14):
 v=[]
 for j in range(i-n,i):
  pc=float(rs[j-1]['close']); h=float(rs[j]['high']); l=float(rs[j]['low']); v.append(max(h-l,abs(h-pc),abs(l-pc)))
 return sum(v)/len(v) if v else 0.0
def rsi(rs,i,n=14):
 if i<n:return None
 gains=[]; losses=[]
 for j in range(i-n+1,i+1):
  d=float(rs[j]['close'])-float(rs[j-1]['close']); gains.append(max(d,0.0)); losses.append(max(-d,0.0))
 ag=sum(gains)/n; al=sum(losses)/n
 if al==0:return 100.0
 rsx=ag/al; return 100.0-(100.0/(1.0+rsx))
def penetration_base(rs,i):
 c=float(rs[i]['close']); o=float(rs[i]['open']); h=float(rs[i]['high']); l=float(rs[i]['low']); prev=float(rs[i-1]['close']); s50=sma(rs,i,50)
 a=atr_prev(rs,i); tr=max(h-l,abs(h-prev),abs(l-prev))
 if not (s50 is not None and a>0 and tr>=1.5*a):return None
 ph=float(rs[i-1]['high']); pl=float(rs[i-1]['low'])
 if c>o and c>s50 and c>ph and (c-ph > h-c):return 'long'
 if c<o and c<s50 and c<pl and (pl-c > c-l):return 'short'
 return None
def signal(mode,rs,i):
 c=float(rs[i]['close']); o=float(rs[i]['open']); h=float(rs[i]['high']); l=float(rs[i]['low']); s50=sma(rs,i,50); prev=float(rs[i-1]['close'])
 if mode=='vol_cont_break_penetration': return penetration_base(rs,i)
 if mode.startswith('penetration_'):
  side=penetration_base(rs,i)
  if side is None:return None
  if mode=='penetration_ma_stack':
   s100=sma(rs,i,100); s200=sma(rs,i,200)
   if s100 is None or s200 is None:return None
   if side=='long' and not (c>s50>s100>s200):return None
   if side=='short' and not (c<s50<s100<s200):return None
  elif mode=='penetration_cross_state':
   s200=sma(rs,i,200)
   if s200 is None:return None
   if side=='long' and not s50>s200:return None
   if side=='short' and not s50<s200:return None
  elif mode=='penetration_ma50_100_state':
   s100=sma(rs,i,100)
   if s100 is None:return None
   if side=='long' and not s50>s100:return None
   if side=='short' and not s50<s100:return None
  elif mode=='penetration_ma100_200_state':
   s100=sma(rs,i,100); s200=sma(rs,i,200)
   if s100 is None or s200 is None:return None
   if side=='long' and not s100>s200:return None
   if side=='short' and not s100<s200:return None
  elif mode=='penetration_ma100_slope':
   s100=sma(rs,i,100); p100=sma(rs,i-1,100)
   if s100 is None or p100 is None:return None
   if side=='long' and not (s50>s100 and s100>p100):return None
   if side=='short' and not (s50<s100 and s100<p100):return None
  elif mode=='penetration_rsi50':
   rv=rsi(rs,i,14)
   if rv is None:return None
   if side=='long' and not rv>50:return None
   if side=='short' and not rv<50:return None
  elif mode=='penetration_fib':
   if i<50:return None
   hi=max(float(x['high']) for x in rs[i-49:i+1]); lo=min(float(x['low']) for x in rs[i-49:i+1]); rng=hi-lo
   if rng<=0:return None
   pos=(c-lo)/rng
   if side=='long' and not pos>=0.618:return None
   if side=='short' and not pos<=0.382:return None
  return side
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
 configs=[
  ('vol_cont_break_penetration','newarch_4h_vol_expansion_priorbar_break_penetration_v1','4H_TR_GE_1P5_ATR14_PRIOR_BAR_BREAK_PENETRATION_GT_DIRECTIONAL_WICK'),
  ('penetration_cross_state','diag_penetration_golden_dead_state_v1','DIAG_PENETRATION_SMA50_VS_SMA200_CROSS_STATE'),
  ('penetration_ma50_100_state','diag_penetration_ma50_100_state_v1','DIAG_PENETRATION_SMA50_VS_SMA100_STATE'),
  ('penetration_ma100_200_state','diag_penetration_ma100_200_state_v1','DIAG_PENETRATION_SMA100_VS_SMA200_STATE'),
  ('penetration_ma100_slope','diag_penetration_ma50_100_slope_v1','DIAG_PENETRATION_SMA50_100_WITH_SMA100_SLOPE'),
  ('penetration_ma_stack','diag_penetration_ma50_100_200_stack_v1','DIAG_PENETRATION_MA50_100_200_STACK'),
  ('penetration_rsi50','diag_penetration_rsi50_center_v1','DIAG_PENETRATION_RSI14_CENTERLINE_CONFIRMATION'),
  ('penetration_fib','diag_penetration_fib_618_382_v1','DIAG_PENETRATION_50BAR_FIB_618_382_LOCATION'),
  ('basis_hf_short_only','basis_premium_collector_4h_scaled_short_only_v1','4H_TIME_SCALED_MEAN_REVERSION_SHORT_SIDE_OWNERSHIP')]
 cand={}
 for mode,cid,arch in configs:cand[cid]={'architecture':arch,**run_one(mode)}
 r={'schema_version':'zel.a1_gen2_highfreq_indicator_matrix.v11','boundary':BOUNDARY,'development_only':True,'prospective':False,'exploratory_matrix':True,'uses_data_strictly_before_gen1_boundary':True,'parameter_sweep':False,'tuned_thresholds':0,'scaled_basis_shock_abs_return':SCALED_SHOCK,'hold_bars':HOLD,'candidates':cand,'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED','live_trade_authority':'BLOCKED'}
 r['receipt_sha256']=hashlib.sha256(json.dumps(r,sort_keys=True,separators=(',',':')).encode()).hexdigest(); return r
if __name__=='__main__':
 r=run(); Path('out').mkdir(exist_ok=True); Path('out/a1_gen2_4h_trend_breakout_dev_v1.json').write_text(json.dumps(r,indent=2,sort_keys=True)+'\n'); print('A1_GEN2_HIGH_FREQ_DUAL='+json.dumps(r,sort_keys=True))
