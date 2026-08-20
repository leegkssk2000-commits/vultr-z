#!/usr/bin/env python3
from __future__ import annotations
import json, hashlib
from pathlib import Path
from backend.research.architecture_factory.a1_gen2_generic_dev_econ_v1 import BOUNDARY,COST_BPS,SYMBOLS,bars
CID='newarch_4h_trend_breakout_v1'; LOOKBACK=20; SMA_N=50; HOLD=6

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
def run():
 out=[]; src={}
 for sym in SYMBOLS:
  rs=bars(sym,'4h'); src[sym]={'bars':len(rs),'first_ts':int(rs[0]['ts']) if rs else None,'last_ts':int(rs[-1]['ts']) if rs else None}
  i=max(LOOKBACK,SMA_N)
  while i<len(rs)-HOLD-1:
   closes=[float(x['close']) for x in rs[i-SMA_N+1:i+1]]; sma=sum(closes)/len(closes)
   prev=rs[i-LOOKBACK:i]; hi=max(float(x['high']) for x in prev); lo=min(float(x['low']) for x in prev); c=float(rs[i]['close'])
   side=None
   if c>hi and c>sma: side='long'
   elif c<lo and c<sma: side='short'
   if side is None:i+=1;continue
   ei=i+1; xi=ei+HOLD-1; ep=float(rs[ei]['open']); xp=float(rs[xi]['close']); gross=(xp/ep-1)*10000*(1 if side=='long' else -1)
   out.append({'symbol':sym,'side':side,'signal_ts':int(rs[i]['ts']),'entry_ts':int(rs[ei]['ts']),'exit_ts':int(rs[xi]['ts']),'gross_bps':gross,'net_bps':gross-COST_BPS}); i=xi+1
 m=metrics(out); econ=bool(m['trades']>=40 and (m['net_expectancy_bps'] or 0)>0 and (m['profit_factor'] or 0)>1 and (m['payoff'] or 0)>=1)
 r={'schema_version':'zel.a1_gen2_4h_trend_breakout_dev.v1','candidate_id':CID,'architecture':'4H_20BAR_BREAKOUT_WITH_SMA50_REGIME','boundary':BOUNDARY,'development_only':True,'prospective':False,'uses_data_strictly_before_gen1_boundary':True,'source_summary':src,'metrics':m,'economic_candidate':econ,'parameter_sweep':False,'tuned_thresholds':0,'entry_timing':'next_bar_open','hold_bars':HOLD,'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED','live_trade_authority':'BLOCKED'}
 r['receipt_sha256']=hashlib.sha256(json.dumps(r,sort_keys=True,separators=(',',':')).encode()).hexdigest(); return r
if __name__=='__main__':
 r=run(); Path('out').mkdir(exist_ok=True); Path('out/a1_gen2_4h_trend_breakout_dev_v1.json').write_text(json.dumps(r,indent=2,sort_keys=True)+'\n'); print('A1_GEN2_4H_TREND_BREAKOUT='+json.dumps(r,sort_keys=True))
