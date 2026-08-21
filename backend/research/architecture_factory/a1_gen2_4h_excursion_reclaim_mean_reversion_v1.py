#!/usr/bin/env python3
from __future__ import annotations
import json,hashlib,math
from pathlib import Path
from backend.research.architecture_factory.a1_gen2_generic_dev_econ_v1 import SYMBOLS,bars
from backend.research.architecture_factory.a1_gen2_4h_range_atr_oos_v1 import prior_bars
from backend.research.architecture_factory.a1_gen2_4h_range_atr_regime_dev_v1 import metrics,atr
MAX_HOLD=8

def mean_std(rs,i,n=20):
 xs=[float(x['close']) for x in rs[i-n+1:i+1]]
 m=sum(xs)/len(xs);sd=math.sqrt(sum((x-m)**2 for x in xs)/len(xs));return m,sd

def sma(rs,i,n):return sum(float(x['close']) for x in rs[i-n+1:i+1])/n

def setup(rs,i):
 if i<50:return None
 m,sd=mean_std(rs,i,20);a=atr(rs,i,14)
 if not a or sd<=0:return None
 # explicit non-trend gate: MA separation must be inside one ATR
 if abs(sma(rs,i,20)-sma(rs,i,50))>=a:return None
 c=float(rs[i]['close'])
 if c<m-2*sd:return ('long',m,float(rs[i]['low']))
 if c>m+2*sd:return ('short',m,float(rs[i]['high']))
 return None

def collect(rs,sym):
 out=[];i=50
 while i<len(rs)-MAX_HOLD-2:
  st=setup(rs,i)
  if st is None:i+=1;continue
  side,target,extreme=st
  # next bar must reclaim back inside the 2-sigma boundary; decision only after that bar closes
  j=i+1;m1,sd1=mean_std(rs,j,20);c1=float(rs[j]['close'])
  if side=='long' and not c1>m1-2*sd1:i+=1;continue
  if side=='short' and not c1<m1+2*sd1:i+=1;continue
  ei=j+1;ep=float(rs[ei]['open']);exit_px=None;xi=None
  # excursion invalidation at original extreme, local-mean target, then 8-bar time stop
  for k in range(ei,min(len(rs),ei+MAX_HOLD)):
   mk,_=mean_std(rs,k,20);lo=float(rs[k]['low']);hi=float(rs[k]['high'])
   if side=='long':
    if lo<=extreme:exit_px=extreme;xi=k;break
    if hi>=mk:exit_px=mk;xi=k;break
   else:
    if hi>=extreme:exit_px=extreme;xi=k;break
    if lo<=mk:exit_px=mk;xi=k;break
  if exit_px is None:
   xi=min(len(rs)-1,ei+MAX_HOLD-1);exit_px=float(rs[xi]['close'])
  g=(exit_px/ep-1)*10000*(1 if side=='long' else -1)
  out.append({'symbol':sym,'side':side,'gross_bps':g,'entry_ts':int(rs[ei]['ts'])});i=xi+1
 return out

def m(rows,c=14):return metrics([x['gross_bps'] for x in rows],float(c))

def run():
 dev=[];prior=[]
 for sym in SYMBOLS:
  dev+=collect(bars(sym,'4h'),sym);prs,_=prior_bars(sym);prior+=collect(prs,sym)
 prior=sorted(prior,key=lambda x:x['entry_ts']);cut=len(prior)//2;w2=prior[:cut];w3=prior[cut:]
 r={'schema_version':'zel.a1_gen2_4h_excursion_reclaim_mean_reversion.v1','candidate':'4H_2SIGMA_EXCURSION_NEXTBAR_RECLAIM_MEAN_TARGET','external_evidence_ids':['ARXIV_1212.4890','LEDGER_2021_213','SSRN_5775962','BINGX_PERP_FEE_VIP0'],'frozen_spec':{'excursion_sigma':2,'reclaim':'next_bar_close_inside_band','nontrend':'abs_sma20_sma50_lt_atr14','target':'rolling_sma20','invalidation':'setup_extreme','max_hold_bars':8},'parameter_sweep':False,'dev':m(dev),'prior_all':m(prior),'W2':m(w2),'W3':m(w3),'cost_dev':{str(c):m(dev,c) for c in (14,28,40)},'cost_prior':{str(c):m(prior,c) for c in (14,28,40)},'by_symbol_prior':{s:m([x for x in prior if x['symbol']==s]) for s in SYMBOLS},'by_side_prior':{s:m([x for x in prior if x['side']==s]) for s in ('long','short') if any(x['side']==s for x in prior)},'survivor_candidate':False,'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED','live_trade_authority':'BLOCKED'}
 d,a,b=r['dev'],r['W2'],r['W3'];r['survivor_candidate']=bool(d['trades']>=40 and all((x['net_pnl_bps'] or 0)>0 and (x['profit_factor'] or 0)>=1 and (x['payoff'] or 0)>=1 for x in (d,a,b)) and (r['cost_prior']['28']['net_pnl_bps'] or 0)>0 and (r['cost_prior']['28']['profit_factor'] or 0)>=1)
 r['receipt_sha256']=hashlib.sha256(json.dumps(r,sort_keys=True,separators=(',',':')).encode()).hexdigest();return r
if __name__=='__main__':
 r=run();Path('out').mkdir(exist_ok=True);Path('out/a1_gen2_4h_excursion_reclaim_mean_reversion_v1.json').write_text(json.dumps(r,indent=2,sort_keys=True)+'\n');print('A1_GEN2_4H_EXCURSION_RECLAIM_MEAN_REVERSION_V1='+json.dumps(r,sort_keys=True))
