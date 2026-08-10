#!/usr/bin/env python3
from __future__ import annotations

import argparse,hashlib,json
from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd

DATASET_SHA='41e8029e41e4605c5d21830fd9b6ebcd49f22aadeeefa8768b4531dc0db3e7e3'
SYMBOLS=('BTC-USDT','ETH-USDT','SOL-USDT','XRP-USDT','DOGE-USDT','ADA-USDT','LINK-USDT','LTC-USDT','BCH-USDT','DOT-USDT','AVAX-USDT','TRX-USDT','ETC-USDT','UNI-USDT','XLM-USDT','ATOM-USDT','NEAR-USDT','FIL-USDT','APT-USDT','ARB-USDT')
START=1767225600000;END=1785542400000;MID=(START+END)//2;ROWS=5088;LOOKBACK=24;GRID=4;HOLD=4;NORMAL_COST=8.;STRESS_COST=16.;REPS=6000

def stable(v:Any)->str:return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False,default=str).encode()).hexdigest()
def load(root:Path):
 m=json.load(open(root/'manifest.json'))
 if m['state']!='PASS_BROAD20_FRESH2026_SOURCE' or m['dataset_sha256']!=DATASET_SHA or m['rows_per_symbol']!=ROWS:raise RuntimeError('SOURCE_AUTHORITY')
 out={}
 for item in m['results']:
  s=item['symbol'];p=root/'data'/item['file']
  if hashlib.sha256(p.read_bytes()).hexdigest()!=item['file_sha256']:raise RuntimeError('FILE_SHA:'+s)
  d=pd.read_csv(p,compression='gzip')
  if len(d)!=ROWS:raise RuntimeError('ROW_COUNT:'+s)
  ts=d.timestamp_ms.to_numpy(np.int64)
  if ts[0]!=START or ts[-1]!=END-3_600_000 or not np.all(np.diff(ts)==3_600_000):raise RuntimeError('CONTINUITY:'+s)
  for c in ('open','close'):d[c]=pd.to_numeric(d[c],errors='raise')
  d.index=pd.to_datetime(d.timestamp_ms,unit='ms',utc=True);out[s]=d
 if set(out)!=set(SYMBOLS):raise RuntimeError('SYMBOL_SET')
 return out

def bootstrap(batches,field,confidence,seed):
 f=pd.DataFrame(batches);f['day']=pd.to_datetime(f.entry_ms,unit='ms',utc=True).dt.floor('D');daily=f.groupby('day',sort=True)[field].mean().to_numpy(float)
 if len(daily)<2:return [float(daily.mean()) if len(daily) else 0.]*2
 rng=np.random.default_rng(seed);n=len(daily);sims=np.empty(REPS)
 for i in range(REPS):sims[i]=rng.choice(daily,n,replace=True).mean()
 a=(1-confidence)/2;return [float(np.quantile(sims,a)),float(np.quantile(sims,1-a))]
def metric(batches,field,confidence,seed):
 v=np.array([x[field] for x in batches],float);pos=v[v>0];neg=v[v<0];loss=abs(float(neg.sum()));pf=float(pos.sum())/loss if loss>1e-12 else (999. if len(pos) else 0.);cum=peak=dd=0.
 for x in v:
  cum+=float(x);peak=max(peak,cum);dd=max(dd,peak-cum)
 return {'batch_count':len(batches),'mean_bps':float(v.mean()) if len(v) else 0.,'median_bps':float(np.median(v)) if len(v) else 0.,'hit_rate_pct':float((v>0).mean()*100) if len(v) else 0.,'profit_factor':pf,'daily_cluster_bootstrap_bps':bootstrap(batches,field,confidence,seed),'max_drawdown_bps_additive':dd}
def run(fr):
 idx=fr[SYMBOLS[0]].index;ret24={s:fr[s].close.shift(1)/fr[s].close.shift(25)-1 for s in SYMBOLS};batches=[];long_part={s:0 for s in SYMBOLS};short_part={s:0 for s in SYMBOLS}
 for i,t in enumerate(idx):
  if t.hour%GRID!=0 or i+HOLD>=len(idx):continue
  row={s:float(ret24[s].iloc[i]) for s in SYMBOLS if np.isfinite(ret24[s].iloc[i])}
  if len(row)!=20:continue
  ranked=sorted(SYMBOLS,key=lambda s:(row[s],s));shorts=ranked[:4];longs=ranked[-4:][::-1];long_raw=[];short_raw=[]
  for s in longs:
   e=float(fr[s].open.iloc[i]);x=float(fr[s].open.iloc[i+HOLD]);long_raw.append((x/e-1.)*10000.);long_part[s]+=1
  for s in shorts:
   e=float(fr[s].open.iloc[i]);x=float(fr[s].open.iloc[i+HOLD]);short_raw.append((x/e-1.)*10000.);short_part[s]+=1
  raw=.5*float(np.mean(long_raw))-.5*float(np.mean(short_raw));normal=raw-NORMAL_COST;stress=raw-STRESS_COST
  batches.append({'entry_ms':int(t.value//1_000_000),'exit_ms':int(idx[i+HOLD].value//1_000_000),'longs':longs,'shorts':shorts,'raw_spread_bps':raw,'normal_net_bps':normal,'stress_net_bps':stress})
 normal=metric(batches,'normal_net_bps',.99,42);stress=metric(batches,'stress_net_bps',.95,43);first=[x['normal_net_bps'] for x in batches if x['entry_ms']<MID];second=[x['normal_net_bps'] for x in batches if x['entry_ms']>=MID];lb=sum(v>0 for v in long_part.values());sb=sum(v>0 for v in short_part.values())
 gate={'minimum_batches_1000':normal['batch_count']>=1000,'long_breadth_12':lb>=12,'short_breadth_12':sb>=12,'normal_mean_gt0':normal['mean_bps']>0,'stress_mean_gt0':stress['mean_bps']>0,'normal_ci99_low_gt0':normal['daily_cluster_bootstrap_bps'][0]>0,'stress_ci95_low_gt0':stress['daily_cluster_bootstrap_bps'][0]>0,'first_half_normal_gt0':float(np.mean(first))>0 if first else False,'second_half_normal_gt0':float(np.mean(second))>0 if second else False,'normal_pf_gt1':normal['profit_factor']>1.0}
 passed=all(gate.values());state='PASS_FRESH2026_MARKET_NEUTRAL_PRICE_EDGE_CANDIDATE_NOT_SURVIVOR' if passed else 'REJECT_FRESH2026_MARKET_NEUTRAL_NO_SEARCH_NO_REUSE'
 return {'schema_version':'zel.edge_factory_v2.xsec_momentum_ls_fresh2026.v1','state':state,'candidate_id':'XSEC_MOMENTUM_LS_24H_TOP4_BOTTOM4_V1','source':{'run_id':31435447148,'artifact_id':9080824711,'dataset_sha256':DATASET_SHA,'rows_per_symbol':ROWS},'contract':{'lookback_hours':LOOKBACK,'decision_grid_hours':GRID,'holding_hours':HOLD,'long_count':4,'short_count':4,'long_gross_weight':.5,'short_gross_weight':.5,'gross_exposure':1.0,'net_exposure':0.0,'direction_search':0,'lookback_search':0,'selection_count_search':0,'holding_period_search':0,'normal_cost_bps':NORMAL_COST,'stress_cost_bps':STRESS_COST,'funding_included':False},'portfolio':{'batch_count':len(batches),'long_distinct_symbols':lb,'short_distinct_symbols':sb,'long_participation':long_part,'short_participation':short_part,'first_half_mean_normal_bps':float(np.mean(first)) if first else 0.,'second_half_mean_normal_bps':float(np.mean(second)) if second else 0.},'normal':normal,'stress':stress,'gate':gate,'funding_required_before_final_survivor':passed,'fresh2026_reuse_allowed_after_result':False,'ai_used_before_score':False,'survivor_declared':False,'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED','action':'hold','next':'BIND_RECENT2026_NATIVE_FUNDING_AND_EXACT_EXECUTION_COSTS_BEFORE_SURVIVOR_REGISTRY' if passed else 'DROP_CANDIDATE_NO_DIRECTION_LOOKBACK_TOPBOTTOM_HOLD_SEARCH_NO_FRESH2026_REUSE'}
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--dataset-root',type=Path,required=True);ap.add_argument('--out',type=Path,required=True);a=ap.parse_args();r=run(load(a.dataset_root));r['receipt_sha256']=stable(r);a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(r,indent=2,sort_keys=True,allow_nan=False)+'\n');print(json.dumps({'state':r['state'],'portfolio':r['portfolio'],'normal':r['normal'],'stress':r['stress'],'gate':r['gate'],'receipt_sha256':r['receipt_sha256']},sort_keys=True));return 0
if __name__=='__main__':raise SystemExit(main())
