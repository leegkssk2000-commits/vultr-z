#!/usr/bin/env python3
from __future__ import annotations
import json, hashlib, math
from pathlib import Path
from backend.research.architecture_factory.a1_gen2_generic_dev_econ_v1 import BOUNDARY,COST_BPS,SYMBOLS,bars
LOOKBACK=20; SMA_N=50; HOLD=6

def pf(xs):
 gp=sum(x for x in xs if x>0); gl=-sum(x for x in xs if x<0); return None if gl<=0 else gp/gl
def payoff(xs):
 w=[x for x in xs if x>0]; l=[-x for x in xs if x<0]; return None if not w or not l else (sum(w)/len(w))/(sum(l)/len(l))
def dd(xs):
 e=p=m=0.0
 for x in xs:e+=x;p=max(p,e);m=max(m,p-e)
 return m
def metrics(ts):
 n=[x['net_bps'] for x in ts]; g=[x['gross_bps'] for x in ts]; z=len(n)
 return {'trades':z,'gross_expectancy_bps':sum(g)/z if z else None,'net_expectancy_bps':sum(n)/z if z else None,'net_pnl_bps':sum(n),'profit_factor':pf(n),'payoff':payoff(n),'win_rate':sum(x>0 for x in n)/z if z else None,'drawdown_bps':dd(n),'cost_bps_per_trade':COST_BPS}
def sma(rs,i,n=50): return sum(float(x['close']) for x in rs[i-n+1:i+1])/n
def atr_prev(rs,i,n=14):
 v=[]
 for j in range(i-n,i):
  pc=float(rs[j-1]['close']); h=float(rs[j]['high']); l=float(rs[j]['low']); v.append(max(h-l,abs(h-pc),abs(l-pc)))
 return sum(v)/len(v) if v else 0.0
def add_trade(out,rs,i,side):
 ei=i+1; xi=ei+HOLD-1
 if xi>=len(rs): return len(rs)
 ep=float(rs[ei]['open']); xp=float(rs[xi]['close']); gross=(xp/ep-1)*10000*(1 if side=='long' else -1)
 out.append({'side':side,'signal_ts':int(rs[i]['ts']),'entry_ts':int(rs[ei]['ts']),'exit_ts':int(rs[xi]['ts']),'gross_bps':gross,'net_bps':gross-COST_BPS})
 return xi+1
def econ_flag(m): return bool(m['trades']>=40 and (m['net_expectancy_bps'] or 0)>0 and (m['profit_factor'] or 0)>1 and (m['payoff'] or 0)>=1)
def run_one(mode):
 out=[]; src={}; scaled_shock=0.02*math.sqrt(4/24)
 for sym in SYMBOLS:
  rs=bars(sym,'4h'); src[sym]={'bars':len(rs),'first_ts':int(rs[0]['ts']) if rs else None,'last_ts':int(rs[-1]['ts']) if rs else None}; i=50
  while i<len(rs)-HOLD-1:
   c=float(rs[i]['close']); o=float(rs[i]['open']); s50=sma(rs,i); side=None
   if mode=='breakout':
    prev=rs[i-LOOKBACK:i]; hi=max(float(x['high']) for x in prev); lo=min(float(x['low']) for x in prev)
    if c>hi and c>s50: side='long'
    elif c<lo and c<s50: side='short'
   elif mode=='vol_cont':
    a=atr_prev(rs,i); tr=max(float(rs[i]['high'])-float(rs[i]['low']),abs(float(rs[i]['high'])-float(rs[i-1]['close'])),abs(float(rs[i]['low'])-float(rs[i-1]['close'])))
    if a>0 and tr>=1.5*a:
     if c>o and c>s50: side='long'
     elif c<o and c<s50: side='short'
   else:
    prev=float(rs[i-1]['close']); r=c/prev-1 if prev else 0.0
    if abs(r)>=scaled_shock:
     if r<0: side='long'
     elif r>0 and (mode=='basis_hf_raw' or c<s50): side='short'
   if side is None: i+=1; continue
   j=add_trade(out,rs,i,side); out[-1]['symbol']=sym; i=j
 m=metrics(out)
 return {'metrics':m,'economic_candidate':econ_flag(m),'source_summary':src}
def run():
 configs=[('breakout','newarch_4h_trend_breakout_v1','4H_20BAR_BREAKOUT_WITH_SMA50_REGIME'),('vol_cont','newarch_4h_vol_expansion_continuation_v1','4H_TR_GE_1P5_ATR14_SMA50_CONTINUATION'),('basis_hf_raw','basis_premium_collector_4h_scaled_raw_v1','4H_TIME_SCALED_LARGE_MOVE_MEAN_REVERSION_RAW'),('basis_hf_repaired','basis_premium_collector_4h_scaled_short_veto_v1','4H_TIME_SCALED_LARGE_MOVE_MEAN_REVERSION_SHORT_ADVERSE_REGIME_VETO')]
 cand={}
 for mode,cid,arch in configs:
  z=run_one(mode); cand[cid]={'architecture':arch,**z}
 r={'schema_version':'zel.a1_gen2_highfreq_dual_dev.v2','boundary':BOUNDARY,'development_only':True,'prospective':False,'uses_data_strictly_before_gen1_boundary':True,'parameter_sweep':False,'tuned_thresholds':0,'scaled_basis_shock_abs_return':0.02*math.sqrt(4/24),'hold_bars':HOLD,'candidates':cand,'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED','live_trade_authority':'BLOCKED'}
 r['receipt_sha256']=hashlib.sha256(json.dumps(r,sort_keys=True,separators=(',',':')).encode()).hexdigest(); return r
if __name__=='__main__':
 r=run(); Path('out').mkdir(exist_ok=True); Path('out/a1_gen2_4h_trend_breakout_dev_v1.json').write_text(json.dumps(r,indent=2,sort_keys=True)+'\n'); print('A1_GEN2_HIGH_FREQ_DUAL='+json.dumps(r,sort_keys=True))
