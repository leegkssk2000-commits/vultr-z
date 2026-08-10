#!/usr/bin/env python3
from __future__ import annotations

import argparse, hashlib, json
from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd

DATASET_SHA='87ff0595f7ab90728af265eaf1b5aa79571317de61c6f68ce890526f3eff3c28'
SYMBOLS=('BTC-USDT','ETH-USDT','LINK-USDT','SOL-USDT','XRP-USDT')
T1_START_MS=1751328000000;T1_END_MS=1767225600000
ROWS_TOTAL=13176;TRAIL=720;GRID=4;HOLD=4;NORMAL_COST=8.0;STRESS_COST=16.0
MIN_BATCHES=60;NORMAL_REPS=6000;STRESS_REPS=6000

def stable_sha(v:Any)->str:return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False,default=str).encode()).hexdigest()
def load(root:Path)->dict[str,pd.DataFrame]:
 m=json.loads((root/'manifest.json').read_text())
 if m.get('state')!='PASS_FRESH_18M_1H_DATA_STAGED' or m.get('dataset_sha256')!=DATASET_SHA:raise RuntimeError('DATASET_AUTHORITY')
 if m['partitions']['T1_TEST']['rows_per_symbol']!=4416:raise RuntimeError('T1_PARTITION_AUTHORITY')
 out={}
 for item in m['results']:
  s=str(item['symbol']);p=root/'data'/str(item['file'])
  if hashlib.sha256(p.read_bytes()).hexdigest()!=item['file_sha256']:raise RuntimeError(f'FILE_SHA:{s}')
  d=pd.read_csv(p,compression='gzip')
  if len(d)!=ROWS_TOTAL:raise RuntimeError(f'ROW_COUNT:{s}:{len(d)}')
  ts=d['timestamp_ms'].to_numpy(dtype=np.int64)
  if not np.all(np.diff(ts)==3_600_000):raise RuntimeError(f'CONTINUITY:{s}')
  for c in ('open','high','low','close','volume'):d[c]=pd.to_numeric(d[c],errors='raise')
  d.index=pd.to_datetime(d['timestamp_ms'],unit='ms',utc=True);out[s]=d
 if set(out)!=set(SYMBOLS):raise RuntimeError(f'SYMBOL_SET:{sorted(out)}')
 return out

def daily_bootstrap(batches:list[dict[str,Any]],field:str,reps:int,seed:int,low_q:float,high_q:float)->list[float]:
 if not batches:return [0.,0.]
 f=pd.DataFrame(batches);f['day']=pd.to_datetime(f['entry_ms'],unit='ms',utc=True).dt.floor('D');daily=f.groupby('day',sort=True)[field].mean().to_numpy(dtype=float)
 if len(daily)<2:
  x=float(daily[0]) if len(daily) else 0.;return [x,x]
 rng=np.random.default_rng(seed);sims=np.empty(reps,dtype=float);n=len(daily)
 for i in range(reps):sims[i]=float(rng.choice(daily,size=n,replace=True).mean())
 return [float(np.quantile(sims,low_q)),float(np.quantile(sims,high_q))]
def metrics(batches:list[dict[str,Any]],field:str,confidence:float,reps:int,seed:int)->dict[str,Any]:
 vals=np.array([float(x[field]) for x in batches],dtype=float);positive=vals[vals>0];negative=vals[vals<0];cum=0.;peak=0.;maxdd=0.
 for x in vals:
  cum+=float(x);peak=max(peak,cum);maxdd=max(maxdd,peak-cum)
 loss=abs(float(negative.sum()));pf=float(positive.sum())/loss if loss>1e-12 else (999.0 if len(positive) else 0.0)
 alpha=(1-confidence)/2;ci=daily_bootstrap(batches,field,reps,seed,alpha,1-alpha)
 return {'batch_count':len(batches),'independent_day_count':len({pd.Timestamp(x['entry_ms'],unit='ms',tz='UTC').floor('D') for x in batches}),'mean_net_bps':float(vals.mean()) if len(vals) else 0.,'median_net_bps':float(np.median(vals)) if len(vals) else 0.,'hit_rate_pct':float((vals>0).mean()*100) if len(vals) else 0.,'profit_factor':pf,'max_drawdown_bps_additive':maxdd,'bootstrap_confidence':confidence,'daily_cluster_bootstrap_net_bps':ci}
def run(frames):
 idx=frames['BTC-USDT'].index;start=pd.Timestamp(T1_START_MS,unit='ms',tz='UTC');end=pd.Timestamp(T1_END_MS,unit='ms',tz='UTC');sig={}
 for s,d in frames.items():
  r4=d['close'].shift(1)/d['close'].shift(5)-1
  v4=d['volume'].shift(1).rolling(4,min_periods=4).sum()
  vq=v4.shift(1).rolling(TRAIL,min_periods=TRAIL).quantile(.9)
  sig[s]={'r4':r4,'v4':v4,'vq':vq}
 batches=[];participation={s:0 for s in SYMBOLS};leg_net={s:[] for s in SYMBOLS};leg_count=0
 for i,t in enumerate(idx):
  if t<start or t>=end or t.hour%GRID!=0 or i+HOLD>=len(idx):continue
  xt=idx[i+HOLD]
  if xt>=end:continue
  legs=[]
  for s in SYMBOLS:
   z=sig[s];r4,v4,vq=z['r4'].iloc[i],z['v4'].iloc[i],z['vq'].iloc[i]
   if not(np.isfinite(r4) and np.isfinite(v4) and np.isfinite(vq)):continue
   if not(r4>0 and v4>=vq):continue
   entry=float(frames[s]['open'].iloc[i]);exit_=float(frames[s]['open'].iloc[i+HOLD])
   if not(np.isfinite(entry) and np.isfinite(exit_) and entry>0):continue
   raw=(exit_/entry-1)*10000.;normal=raw-NORMAL_COST;stress=raw-STRESS_COST
   legs.append({'symbol':s,'raw_bps':float(raw),'normal_net_bps':float(normal),'stress_net_bps':float(stress)})
  if not legs:continue
  for leg in legs:
   s=leg['symbol'];participation[s]+=1;leg_net[s].append(leg['normal_net_bps']);leg_count+=1
  batches.append({'entry_ms':int(t.value//1_000_000),'exit_ms':int(xt.value//1_000_000),'leg_count':len(legs),'symbols':[x['symbol'] for x in legs],'normal_net_bps':float(np.mean([x['normal_net_bps'] for x in legs])),'stress_net_bps':float(np.mean([x['stress_net_bps'] for x in legs]))})
 normal=metrics(batches,'normal_net_bps',.99,NORMAL_REPS,42);stress=metrics(batches,'stress_net_bps',.95,STRESS_REPS,43);distinct=sum(v>0 for v in participation.values())
 passed=(normal['batch_count']>=MIN_BATCHES and normal['mean_net_bps']>0 and normal['daily_cluster_bootstrap_net_bps'][0]>0 and stress['mean_net_bps']>0 and stress['daily_cluster_bootstrap_net_bps'][0]>0 and distinct>=3)
 state='PASS_T1_VOLUME_SHOCK_SURVIVOR_CANDIDATE_NOT_FINAL_SURVIVOR' if passed else 'REJECT_T1_VOLUME_SHOCK_NO_RESCUE_NO_TUNING'
 return {'schema_version':'zel.edge_factory_v2.volume_shock_t1.v1','state':state,'candidate_id':'VOLUME_SHOCK_EQW_PORTFOLIO_LONG_V1','source':{'run_id':31429880433,'artifact_id':9078686271,'dataset_sha256':DATASET_SHA,'t1_start_ms':T1_START_MS,'t1_end_exclusive_ms':T1_END_MS,'t1_rows_per_symbol':4416},'signal_contract':{'timeframe':'1h','decision_grid_hours':GRID,'holding_hours':HOLD,'trailing_distribution_hours':TRAIL,'parameter_search':0,'portfolio_weighting':'EQUAL_WEIGHT_ACROSS_ELIGIBLE_LEGS'},'cost_contract':{'normal_roundtrip_bps_per_leg':NORMAL_COST,'stress_roundtrip_bps_per_leg':STRESS_COST},'portfolio':{'batch_count':len(batches),'leg_count':leg_count,'distinct_symbols_participating':distinct,'symbol_batch_participation':participation,'symbol_mean_normal_leg_net_bps':{s:(float(np.mean(v)) if v else None) for s,v in leg_net.items()}},'normal':normal,'stress':stress,'gate':{'minimum_portfolio_batches':MIN_BATCHES,'normal_mean_gt_zero':normal['mean_net_bps']>0,'normal_bootstrap99_lower_gt_zero':normal['daily_cluster_bootstrap_net_bps'][0]>0,'stress_mean_gt_zero':stress['mean_net_bps']>0,'stress_bootstrap95_lower_gt_zero':stress['daily_cluster_bootstrap_net_bps'][0]>0,'minimum_distinct_symbols_3':distinct>=3,'dd_threshold_applied':False},'dd_report_only_no_ssot_threshold':True,'t1_reuse_allowed_after_result':False,'survivor_declared':False,'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED','action':'hold','next':'BIND_EXACT_BINGX_FEE_SLIPPAGE_FUNDING_AND_SSOT_DD_THEN_SURVIVOR_REGISTRY_CANDIDACY' if passed else 'DROP_VOLUME_SHOCK_AND_ROUTE_TO_BROADER_ECONOMIC_SOURCE_OR_LIQUID_UNIVERSE_NO_T1_REUSE'}
def main()->int:
 ap=argparse.ArgumentParser();ap.add_argument('--dataset-root',type=Path,required=True);ap.add_argument('--out',type=Path,required=True);a=ap.parse_args();r=run(load(a.dataset_root));r['receipt_sha256']=stable_sha(r);a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(r,indent=2,sort_keys=True,allow_nan=False)+'\n');print(json.dumps({'state':r['state'],'portfolio':r['portfolio'],'normal':r['normal'],'stress':r['stress'],'receipt_sha256':r['receipt_sha256']},sort_keys=True));return 0
if __name__=='__main__':raise SystemExit(main())
