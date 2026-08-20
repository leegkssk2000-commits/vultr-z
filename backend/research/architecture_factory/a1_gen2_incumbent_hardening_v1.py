#!/usr/bin/env python3
from __future__ import annotations
import json, statistics
from datetime import datetime, timezone
from pathlib import Path
import backend.research.architecture_factory.a1_gen2_generic_dev_econ_v1 as econ
ENTRY_RULE="ret(1) < -0.02 or (ret(1) > 0.02 and close < sma('close',50))"; SIDE_RULE="long if ret(1) < -0.02 else short"
HOLD=12; ACT=300.; LOCK=14.; ATR_N=14; W=.75
BASE={"trades":227,"net_pnl_bps":32456.553693428767,"net_expectancy_bps":142.98041274638223,"profit_factor":1.7661077778815002,"drawdown_bps":3222.578836366174}
STRICT={"trades":206,"net_pnl_bps":32617.829889702687,"net_expectancy_bps":158.33898004710042,"profit_factor":1.889707229544646,"drawdown_bps":3149.2984443634814}
def m(a):
 n=len(a); return {"trades":n,"net_expectancy_bps":sum(a)/n if n else None,"net_pnl_bps":sum(a),"profit_factor":econ._pf(a) if n else None,"payoff":econ._payoff(a) if n else None,"win_rate":sum(x>0 for x in a)/n if n else None,"drawdown_bps":econ._dd(a) if n else 0.}
def gross(s,e,p): return (p/e-1)*10000 if s=='long' else (1-p/e)*10000
def atr(rs,i):
 a=[]
 for j in range(i-ATR_N+1,i+1):
  pc=rs[j-1]['close']; a.append(max(rs[j]['high']-rs[j]['low'],abs(rs[j]['high']-pc),abs(rs[j]['low']-pc)))
 return sum(a)/len(a)
def outcome(rs,s,ei,xi,ep):
 on=False
 for j in range(ei,xi+1):
  if on:
   f=ep*(1+LOCK/10000) if s=='long' else ep*(1-LOCK/10000)
   if s=='long' and rs[j]['low']<=f:return gross(s,ep,min(f,rs[j]['open']))-14
   if s=='short' and rs[j]['high']>=f:return gross(s,ep,max(f,rs[j]['open']))-14
  fav=(rs[j]['high']/ep-1)*10000 if s=='long' else (1-rs[j]['low']/ep)*10000
  if fav>=ACT:on=True
 return gross(s,ep,rs[xi]['close'])-14
def trades():
 out=[]
 for sym in econ.SYMBOLS:
  rs=econ.bars(sym,'1d'); e=econ.Expr(rs,{}); i=30
  while i<len(rs)-1:
   try:fire=bool(e.eval(ENTRY_RULE,i))
   except Exception:fire=False
   if not fire:i+=1;continue
   s=econ._side(SIDE_RULE,e,i); sf='short' if s=='long' else 'long'; ei=i+1; xi=min(ei+11,len(rs)-1); ep=rs[ei]['open']; ar=atr(rs,i); q=abs(rs[i]['close']-rs[i-1]['close'])/ar if ar else 0; sma=sum(x['close'] for x in rs[max(0,i-49):i+1])/len(rs[max(0,i-49):i+1])
   out.append({'symbol':sym,'side':s,'signal_ts':int(rs[i]['ts']),'exit_ts':int(rs[xi]['ts']),'year':datetime.fromtimestamp(rs[i]['ts']/1000,tz=timezone.utc).year,'shock_atr':q,'above':rs[i]['close']>=sma,'n':outcome(rs,s,ei,xi,ep),'nf':outcome(rs,sf,ei,xi,ep)}); i=max(i+1,xi+1)
 return out
def check(x,e):
 for k,v in e.items(): assert x[k]==v if k=='trades' else abs(x[k]-v)<1e-6,(k,x[k],v)
def run(output:Path):
 t=trades(); b=m([x['n'] for x in t]); check(b,BASE); veto=[x for x in t if x['side']=='long' and x['above'] and x['shock_atr']>=1]; kept=[x for x in t if x not in veto]; stress=set()
 for x in sorted(kept,key=lambda z:z['signal_ts']):
  if x['symbol']!='ETH-USDT' or x['above']:continue
  p=[z for z in kept if z['symbol']==x['symbol'] and z['exit_ts']<x['signal_ts'] and z['n']<0]
  if len(p)>=10:
   a=[abs(z['n']) for z in p]
   if sum(a[-5:])/5>statistics.median(a):stress.add(id(x))
 def val(x,c=14,flip=False):return ((x['nf'] if flip else x['n'])+14-c)*(W if id(x) in stress else 1)
 s=m([val(x) for x in kept]); check(s,STRICT); costs={str(c):m([val(x,c) for x in kept]) for c in (14,28,40)}
 def grp(k):
  d={}
  for x in kept:d.setdefault(str(x[k]),[]).append(val(x))
  return {a:m(v) for a,v in sorted(d.items())}
 sy=grp('symbol'); sd=grp('side'); yr=grp('year'); neg=m([val(x,14,True) for x in kept]); losses=sorted([-val(x) for x in kept if val(x)<0],reverse=True); tl=sum(losses); lc={'loss_trade_count':len(losses),'total_loss_bps':tl,'top10_loss_bps':sum(losses[:10]),'top10_share_of_loss':sum(losses[:10])/tl if tl else 0}
 flags={'cost40':costs['40']['net_pnl_bps']>0 and costs['40']['profit_factor']>1,'symbols':all(v['net_pnl_bps']>0 and v['profit_factor']>1 for v in sy.values()),'negative_control':neg['net_pnl_bps']<0 and neg['profit_factor']<1}; ok=all(flags.values())
 r={'schema_version':'zel.a1_gen2_strict_pareto_hardening.v1','candidate_id':'atr_long_veto_eth_stress075','metrics':s,'cost_stress':costs,'by_symbol':sy,'by_side':sd,'by_year':yr,'negative_control':neg,'loss_concentration':lc,'flags':flags,'hardening_pass':ok,'state':'PASS_HARDENING' if ok else 'HOLD_HARDENING','future_information_used':False,'threshold_sweep':False}
 output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(r,sort_keys=True,indent=2)+'\n');print('STRICT_PASS_HARDENING='+json.dumps(r,sort_keys=True));return r
if __name__=='__main__':run(Path('out/a1_gen2_incumbent_hardening_v1.json'))
