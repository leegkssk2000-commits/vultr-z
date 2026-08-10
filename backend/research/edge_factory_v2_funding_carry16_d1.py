#!/usr/bin/env python3
from __future__ import annotations

import argparse,csv,gzip,hashlib,json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

PRICE_SHA='41e8029e41e4605c5d21830fd9b6ebcd49f22aadeeefa8768b4531dc0db3e7e3'
FUNDING_SHA='41e3dd04af26a7a0fcab574bcad8dcca88932462960fbb6945b87addf44de5b0'
SYMBOLS=('BTC-USDT','ETH-USDT','SOL-USDT','XRP-USDT','DOGE-USDT','ADA-USDT','LINK-USDT','BCH-USDT','AVAX-USDT','ETC-USDT','UNI-USDT','XLM-USDT','ATOM-USDT','FIL-USDT','APT-USDT','ARB-USDT')
EXCLUDED=('LTC-USDT','DOT-USDT','TRX-USDT','NEAR-USDT')
START=1767225600000
D1_END=1775001600000
PRICE_ROWS=(D1_END-START)//3_600_000
FUND_STEP=8*3_600_000
LOOKBACK_OBS=3
HOLD_HOURS=24
LEG_WEIGHT=0.125
NORMAL_COST=12.30757224
STRESS_COST=14.61514448
REPS=6000

def stable(v:Any)->str:return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False,default=str).encode()).hexdigest()
def fsha(path:Path)->str:
 h=hashlib.sha256()
 with path.open('rb') as f:
  for c in iter(lambda:f.read(1<<20),b''):h.update(c)
 return h.hexdigest()
def load_price(root:Path)->dict[str,pd.DataFrame]:
 m=json.load(open(root/'manifest.json'))
 if m.get('state')!='PASS_BROAD20_FRESH2026_SOURCE' or m.get('dataset_sha256')!=PRICE_SHA:raise RuntimeError('PRICE_SOURCE_AUTHORITY')
 rows={r['symbol']:r for r in m['results']};out={}
 for s in SYMBOLS:
  item=rows[s];p=root/'data'/item['file']
  if fsha(p)!=item['file_sha256']:raise RuntimeError(f'PRICE_FILE_SHA:{s}')
  d=pd.read_csv(p,compression='gzip',nrows=PRICE_ROWS)
  if len(d)!=PRICE_ROWS:raise RuntimeError(f'PRICE_D1_ROWS:{s}:{len(d)}')
  ts=d['timestamp_ms'].to_numpy(np.int64)
  if int(ts[0])!=START or int(ts[-1])!=D1_END-3_600_000 or not np.all(np.diff(ts)==3_600_000):raise RuntimeError(f'PRICE_D1_CONTINUITY:{s}')
  for c in ('open','close'):d[c]=pd.to_numeric(d[c],errors='raise')
  d.index=pd.to_datetime(d.timestamp_ms,unit='ms',utc=True);out[s]=d
 return out
def load_funding(root:Path)->dict[str,pd.DataFrame]:
 m=json.load(open(root/'manifest.json'))
 if m.get('schema_version')!='zel.edge_factory_v2.xsec_ls_funding2026_exact_probe.v1' or m.get('funding_dataset_sha256')!=FUNDING_SHA:raise RuntimeError('FUNDING_SOURCE_AUTHORITY')
 rows={r['symbol']:r for r in m['results']}
 if any(rows[s]['state']!='PASS_EXACT_NATIVE_FUNDING_SCHEDULE' for s in SYMBOLS):raise RuntimeError('FUNDING_UNIVERSE_NOT_SOURCE_COMPLETE')
 if any(rows[s]['state']=='PASS_EXACT_NATIVE_FUNDING_SCHEDULE' for s in EXCLUDED):raise RuntimeError('EXCLUDED_SOURCE_BASIS_DRIFT')
 out={}
 for s in SYMBOLS:
  item=rows[s];p=root/'data'/item['file']
  if fsha(p)!=item['file_sha256']:raise RuntimeError(f'FUNDING_FILE_SHA:{s}')
  vals=[]
  with gzip.open(p,'rt',encoding='utf-8',newline='') as f:
   for r in csv.DictReader(f):
    t=int(r['fundingTime'])
    if t>=D1_END:break
    if t<START:continue
    vals.append((t,float(r['fundingRate'])))
  expected=(D1_END-START)//FUND_STEP
  if len(vals)!=expected:raise RuntimeError(f'FUNDING_D1_ROWS:{s}:{len(vals)}:{expected}')
  ts=np.array([x[0] for x in vals],dtype=np.int64)
  if int(ts[0])!=START or int(ts[-1])!=D1_END-FUND_STEP or not np.all(np.diff(ts)==FUND_STEP):raise RuntimeError(f'FUNDING_D1_CONTINUITY:{s}')
  out[s]=pd.DataFrame({'fundingTime':ts,'fundingRate':[x[1] for x in vals]}).set_index('fundingTime')
 return out
def bootstrap(vals:list[float],confidence:float=.95,seed:int=42)->list[float]:
 a=np.asarray(vals,float)
 if len(a)<2:
  x=float(a.mean()) if len(a) else 0.;return [x,x]
 rng=np.random.default_rng(seed);sims=np.empty(REPS);n=len(a)
 for i in range(REPS):sims[i]=float(rng.choice(a,size=n,replace=True).mean())
 q=(1-confidence)/2;return [float(np.quantile(sims,q)),float(np.quantile(sims,1-q))]
def metric(batches:list[dict[str,Any]],field:str)->dict[str,Any]:
 v=np.array([b[field] for b in batches],float);pos=v[v>0];neg=v[v<0];pf=float(pos.sum()/abs(neg.sum())) if len(neg) and abs(float(neg.sum()))>1e-12 else (999. if len(pos) else 0.);cum=peak=dd=0.
 for x in v:cum+=float(x);peak=max(peak,cum);dd=max(dd,peak-cum)
 return {'mean_bps':float(v.mean()) if len(v) else 0.,'median_bps':float(np.median(v)) if len(v) else 0.,'hit_rate_pct':float((v>0).mean()*100) if len(v) else 0.,'profit_factor':pf,'bootstrap95_mean_bps':bootstrap(list(v),.95,42),'max_drawdown_bps_additive':dd}
def run(price:dict[str,pd.DataFrame],fund:dict[str,pd.DataFrame])->dict[str,Any]:
 fmaps={s:{int(t):float(r) for t,r in zip(fund[s].index,fund[s]['fundingRate'])} for s in SYMBOLS};pidx=price[SYMBOLS[0]].index;ppos={int(t.value//1_000_000):i for i,t in enumerate(pidx)};batches=[];long_part={s:0 for s in SYMBOLS};short_part={s:0 for s in SYMBOLS};first_decision=START+24*3_600_000;last_decision=D1_END-(HOLD_HOURS+1)*3_600_000
 for decision in range(first_decision,last_decision+1,24*3_600_000):
  hist=(decision-16*3_600_000,decision-8*3_600_000,decision);scores={}
  for s in SYMBOLS:
   if not all(t in fmaps[s] for t in hist):raise RuntimeError(f'SIGNAL_FUNDING_MISSING:{s}:{decision}')
   scores[s]=sum(fmaps[s][t] for t in hist)
  ranked=sorted(SYMBOLS,key=lambda s:(scores[s],s));longs=ranked[:4];shorts=ranked[-4:][::-1];entry=decision+3_600_000;exit_=entry+HOLD_HOURS*3_600_000
  if entry not in ppos or exit_ not in ppos:raise RuntimeError(f'PRICE_ENTRY_EXIT_MISSING:{decision}')
  i=ppos[entry];j=ppos[exit_];price_bps=0.
  for s in longs:
   e=float(price[s].open.iloc[i]);x=float(price[s].open.iloc[j]);price_bps+=LEG_WEIGHT*((x/e-1.)*10000.);long_part[s]+=1
  for s in shorts:
   e=float(price[s].open.iloc[i]);x=float(price[s].open.iloc[j]);price_bps-=LEG_WEIGHT*((x/e-1.)*10000.);short_part[s]+=1
  funding_bps=0.;nset=0
  for t in range(decision+8*3_600_000,decision+25*3_600_000,8*3_600_000):
   if not (entry<=t<=exit_):continue
   nset+=1
   for s in longs:
    if t not in fmaps[s]:raise RuntimeError(f'HOLD_FUNDING_MISSING:{s}:{t}')
    funding_bps-=LEG_WEIGHT*fmaps[s][t]*10000.
   for s in shorts:
    if t not in fmaps[s]:raise RuntimeError(f'HOLD_FUNDING_MISSING:{s}:{t}')
    funding_bps+=LEG_WEIGHT*fmaps[s][t]*10000.
  if nset!=3:raise RuntimeError(f'SETTLEMENT_COUNT:{decision}:{nset}')
  before=price_bps+funding_bps;batches.append({'decision_ms':decision,'entry_ms':entry,'exit_ms':exit_,'longs':longs,'shorts':shorts,'price_spread_bps':price_bps,'realized_funding_cashflow_bps':funding_bps,'total_before_cost_bps':before,'total_net_bps':before-NORMAL_COST,'stress_total_net_bps':before-STRESS_COST})
 mid=len(batches)//2;first=[b['total_net_bps'] for b in batches[:mid]];second=[b['total_net_bps'] for b in batches[mid:]];total=metric(batches,'total_net_bps');stress=metric(batches,'stress_total_net_bps');funding=metric(batches,'realized_funding_cashflow_bps');price_m=metric(batches,'price_spread_bps');lb=sum(v>0 for v in long_part.values());sb=sum(v>0 for v in short_part.values());gate={'minimum_batches_75':len(batches)>=75,'long_breadth_12':lb>=12,'short_breadth_12':sb>=12,'mean_total_net_gt0':total['mean_bps']>0,'mean_stress_net_gt0':stress['mean_bps']>0,'mean_realized_funding_cashflow_gt0':funding['mean_bps']>0,'bootstrap95_total_net_low_gt0':total['bootstrap95_mean_bps'][0]>0,'first_half_total_net_gt0':float(np.mean(first))>0 if first else False,'second_half_total_net_gt0':float(np.mean(second))>0 if second else False};passed=all(gate.values())
 return {'schema_version':'zel.edge_factory_v2.funding_carry16_d1.v1','state':'PASS_FUNDING_CARRY16_D1_TO_FROZEN_V1' if passed else 'REJECT_FUNDING_CARRY16_D1_NO_SEARCH_NO_REUSE','candidate_id':'XSEC_FUNDING_CARRY_L4_S4_24H_V1','source':{'price_dataset_sha256':PRICE_SHA,'funding_dataset_sha256':FUNDING_SHA,'D1_price_rows_per_symbol_read':PRICE_ROWS,'D1_funding_rows_per_symbol_read':(D1_END-START)//FUND_STEP,'V1_rows_read':0,'T1_rows_read':0},'contract':{'universe_size':len(SYMBOLS),'trailing_funding_observations':LOOKBACK_OBS,'decision_time':'00:00_UTC_AFTER_SETTLEMENT','entry_lag_hours':1,'holding_hours':HOLD_HOURS,'long_count':4,'short_count':4,'leg_abs_weight':LEG_WEIGHT,'normal_roundtrip_bps':NORMAL_COST,'stress_roundtrip_bps':STRESS_COST,'rule_search_count':0},'portfolio':{'batch_count':len(batches),'long_distinct_symbols':lb,'short_distinct_symbols':sb,'long_participation':long_part,'short_participation':short_part,'first_half_mean_total_net_bps':float(np.mean(first)) if first else 0.,'second_half_mean_total_net_bps':float(np.mean(second)) if second else 0.},'price_component':price_m,'funding_component':funding,'normal_total':total,'stress_total':stress,'gate':gate,'D1_pass':passed,'V1_metrics_inspected':False,'T1_metrics_inspected':False,'AI_used_before_D1':False,'survivor_declared':False,'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED','action':'hold','next':'FREEZE_IDENTICAL_RULE_AND_SCORE_V1_ONLY' if passed else 'DROP_FUNDING_CARRY16_FAMILY_NO_THRESHOLD_DIRECTION_SELECTION_HOLD_SEARCH'}
def main()->int:
 ap=argparse.ArgumentParser();ap.add_argument('--price-root',type=Path,required=True);ap.add_argument('--funding-root',type=Path,required=True);ap.add_argument('--out',type=Path,required=True);a=ap.parse_args();r=run(load_price(a.price_root),load_funding(a.funding_root));r['receipt_sha256']=stable(r);a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(r,indent=2,sort_keys=True,allow_nan=False)+'\n');print(json.dumps({'state':r['state'],'portfolio':r['portfolio'],'price_component':r['price_component'],'funding_component':r['funding_component'],'normal_total':r['normal_total'],'stress_total':r['stress_total'],'gate':r['gate'],'receipt_sha256':r['receipt_sha256']},sort_keys=True));return 0
if __name__=='__main__':raise SystemExit(main())
