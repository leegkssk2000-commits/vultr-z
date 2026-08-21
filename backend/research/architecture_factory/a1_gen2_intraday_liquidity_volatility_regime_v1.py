#!/usr/bin/env python3
from __future__ import annotations
import json,hashlib
from datetime import datetime,timezone
from pathlib import Path
from backend.research.architecture_factory.a1_gen2_generic_dev_econ_v1 import SYMBOLS,bars
from backend.research.architecture_factory.a1_gen2_4h_range_atr_oos_v1 import prior_bars
from backend.research.architecture_factory.a1_gen2_4h_range_atr_regime_dev_v1 import metrics,atr
HOLD=2
ACTIVE_HOURS={12,16}

def signal(rs,i):
 if i<21:return None
 h=datetime.fromtimestamp(int(rs[i]['ts'])/1000,tz=timezone.utc).hour
 if h not in ACTIVE_HOURS:return None
 v=float(rs[i]['volume']); vm=sum(float(x['volume']) for x in rs[i-19:i+1])/20
 a=atr(rs,i,14)
 if a is None:return None
 pc=float(rs[i-1]['close']); tr=max(float(rs[i]['high'])-float(rs[i]['low']),abs(float(rs[i]['high'])-pc),abs(float(rs[i]['low'])-pc))
 if not (v>vm and tr>a):return None
 o=float(rs[i]['open']);c=float(rs[i]['close'])
 if c==o:return None
 return 'long' if c>o else 'short'

def collect(rs,sym):
 out=[];i=21
 while i<len(rs)-HOLD-1:
  s=signal(rs,i)
  if s is None:i+=1;continue
  ei=i+1;xi=ei+HOLD-1;ep=float(rs[ei]['open']);xp=float(rs[xi]['close']);g=(xp/ep-1)*10000*(1 if s=='long' else -1)
  out.append({'symbol':sym,'side':s,'gross_bps':g,'entry_ts':int(rs[ei]['ts'])});i=xi+1
 return out

def m(rows,c=14):return metrics([x['gross_bps'] for x in rows],float(c))

def run():
 dev=[];prior=[]
 for sym in SYMBOLS:
  dev+=collect(bars(sym,'4h'),sym); prs,_=prior_bars(sym);prior+=collect(prs,sym)
 prior=sorted(prior,key=lambda x:x['entry_ts']);cut=len(prior)//2;w2=prior[:cut];w3=prior[cut:]
 r={'schema_version':'zel.a1_gen2_intraday_liquidity_volatility_regime.v1','candidate':'4H_ACTIVE_OVERLAP_VOLUME_TR_IMPULSE_CONTINUATION','external_evidence_ids':['SSRN_6401099','RQFA_2024_INTRADAY_CRYPTO'],'frozen_spec':{'hours_utc':[12,16],'volume':'current_gt_sma20','true_range':'current_gt_atr14','direction':'bar_body','hold_bars':HOLD},'parameter_sweep':False,'dev':m(dev),'prior_all':m(prior),'W2':m(w2),'W3':m(w3),'cost_dev':{str(c):m(dev,c) for c in (14,28,40)},'cost_prior':{str(c):m(prior,c) for c in (14,28,40)},'by_symbol_prior':{s:m([x for x in prior if x['symbol']==s]) for s in SYMBOLS},'by_side_prior':{s:m([x for x in prior if x['side']==s]) for s in ('long','short') if any(x['side']==s for x in prior)},'survivor_candidate':False,'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED','live_trade_authority':'BLOCKED'}
 d,p,a,b=r['dev'],r['prior_all'],r['W2'],r['W3']; r['survivor_candidate']=bool(d['trades']>=40 and all((x['net_pnl_bps'] or 0)>0 and (x['profit_factor'] or 0)>=1 and (x['payoff'] or 0)>=1 for x in (d,a,b)) and (r['cost_prior']['28']['net_pnl_bps'] or 0)>0)
 r['receipt_sha256']=hashlib.sha256(json.dumps(r,sort_keys=True,separators=(',',':')).encode()).hexdigest();return r
if __name__=='__main__':
 r=run();Path('out').mkdir(exist_ok=True);Path('out/a1_gen2_intraday_liquidity_volatility_regime_v1.json').write_text(json.dumps(r,indent=2,sort_keys=True)+'\n');print('A1_GEN2_INTRADAY_LIQUIDITY_VOLATILITY_REGIME_V1='+json.dumps(r,sort_keys=True))
# trigger
