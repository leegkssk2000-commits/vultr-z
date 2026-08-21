#!/usr/bin/env python3
from __future__ import annotations
import json,hashlib
from pathlib import Path
from backend.research.architecture_factory.a1_gen2_generic_dev_econ_v1 import SYMBOLS,bars
from backend.research.architecture_factory.a1_gen2_4h_range_atr_oos_v1 import prior_bars
from backend.research.architecture_factory.a1_gen2_4h_range_atr_regime_dev_v1 import metrics
HOLD=6
LOOKBACK=6
REQUIRED=5

def signal(rs,i):
 if i<LOOKBACK:return None
 signs=[]
 for j in range(i-LOOKBACK+1,i+1):
  o=float(rs[j]['open']);c=float(rs[j]['close']);signs.append(1 if c>o else -1 if c<o else 0)
 pos=sum(x>0 for x in signs);neg=sum(x<0 for x in signs)
 if pos>=REQUIRED:return 'long'
 if neg>=REQUIRED:return 'short'
 return None

def collect(rs,sym):
 out=[];i=LOOKBACK
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
  dev+=collect(bars(sym,'4h'),sym);prs,_=prior_bars(sym);prior+=collect(prs,sym)
 prior=sorted(prior,key=lambda x:x['entry_ts']);cut=len(prior)//2;w2=prior[:cut];w3=prior[cut:]
 r={'schema_version':'zel.a1_gen2_trend_persistence_runstate.v1','candidate':'4H_5_OF_6_CANDLE_RUNSTATE_PERSISTENCE','external_evidence_ids':['DOI_10.1093_RFS_HHAA113'],'mechanism':'directional sign persistence rather than return-threshold momentum','frozen_spec':{'lookback_bars':6,'same_sign_required':5,'hold_bars':6},'parameter_sweep':False,'dev':m(dev),'prior_all':m(prior),'W2':m(w2),'W3':m(w3),'cost_dev':{str(c):m(dev,c) for c in (14,28,40)},'cost_prior':{str(c):m(prior,c) for c in (14,28,40)},'by_symbol_prior':{s:m([x for x in prior if x['symbol']==s]) for s in SYMBOLS},'by_side_prior':{s:m([x for x in prior if x['side']==s]) for s in ('long','short') if any(x['side']==s for x in prior)},'survivor_candidate':False,'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED','live_trade_authority':'BLOCKED'}
 d,a,b=r['dev'],r['W2'],r['W3'];r['survivor_candidate']=bool(d['trades']>=40 and all((x['net_pnl_bps'] or 0)>0 and (x['profit_factor'] or 0)>=1 and (x['payoff'] or 0)>=1 for x in (d,a,b)) and (r['cost_prior']['28']['net_pnl_bps'] or 0)>0 and (r['cost_prior']['28']['profit_factor'] or 0)>=1)
 r['receipt_sha256']=hashlib.sha256(json.dumps(r,sort_keys=True,separators=(',',':')).encode()).hexdigest();return r
if __name__=='__main__':
 r=run();Path('out').mkdir(exist_ok=True);Path('out/a1_gen2_trend_persistence_runstate_v1.json').write_text(json.dumps(r,indent=2,sort_keys=True)+'\n');print('A1_GEN2_TREND_PERSISTENCE_RUNSTATE_V1='+json.dumps(r,sort_keys=True))
# trigger
