#!/usr/bin/env python3
from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
DATASET_SHA='5738d5b092f090a22f8680b76cb359f9db44c06bbdc92b318b13e28c8fc42878'
SYMBOLS=('BTC-USDT','ETH-USDT','SOL-USDT','XRP-USDT','DOGE-USDT','ADA-USDT','LINK-USDT','LTC-USDT','BCH-USDT','DOT-USDT','AVAX-USDT','TRX-USDT','ETC-USDT','UNI-USDT','XLM-USDT','ATOM-USDT','NEAR-USDT','FIL-USDT','APT-USDT','ARB-USDT')
FEATURES=('RET_4H','RET_24H','RET_72H','RET_168H','REALIZED_VOL_24H','REALIZED_VOL_168H','VOLUME_4H_TO_TRAILING168H_MEDIAN_RATIO','DISTANCE_TO_PRIOR_24H_HIGH','DISTANCE_TO_PRIOR_24H_LOW')
D1_ROWS=4416;V1_ROWS=4344;READ_ROWS=8760;RAW_START=1719792000000;TRAIN_START=1722384000000;D1_END=1735689600000;V1_START=1735689600000;V1_MID=1743508800000;V1_END=1751328000000;GRID=4;HOLD=4;N_COST=8.;S_COST=16.;ALPHA=100.;REPS=6000

def stable(v:Any)->str:return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False,default=str).encode()).hexdigest()
def load(root:Path):
 m=json.load(open(root/'manifest.json'))
 if m['state']!='PASS_BROAD20_SOURCE_UNIVERSE' or m['dataset_sha256']!=DATASET_SHA or m['accepted_count']!=20:raise RuntimeError('SOURCE_AUTH')
 out={}
 for item in m['results']:
  s=item['symbol'];p=root/'data'/item['file']
  if item['state']!='PASS_EXACT_18M_SOURCE' or hashlib.sha256(p.read_bytes()).hexdigest()!=item['file_sha256']:raise RuntimeError('SOURCE_FILE:'+s)
  d=pd.read_csv(p,compression='gzip',nrows=READ_ROWS)
  if len(d)!=READ_ROWS:raise RuntimeError('READ_ROWS:'+s)
  ts=d.timestamp_ms.to_numpy(np.int64)
  if ts[0]!=RAW_START or ts[-1]!=V1_END-3600000 or not np.all(np.diff(ts)==3600000):raise RuntimeError('BOUNDARY:'+s)
  for c in ('open','high','low','close','volume'):d[c]=pd.to_numeric(d[c],errors='raise')
  d.index=pd.to_datetime(d.timestamp_ms,unit='ms',utc=True);out[s]=d
 return out

def feature_frames(fr):
 cols={name:{} for name in FEATURES}
 for s,d in fr.items():
  c=d.close;ret1=c.pct_change();vol=d.volume
  cols['RET_4H'][s]=c.shift(1)/c.shift(5)-1
  cols['RET_24H'][s]=c.shift(1)/c.shift(25)-1
  cols['RET_72H'][s]=c.shift(1)/c.shift(73)-1
  cols['RET_168H'][s]=c.shift(1)/c.shift(169)-1
  cols['REALIZED_VOL_24H'][s]=ret1.shift(1).rolling(24,min_periods=24).std(ddof=0)
  cols['REALIZED_VOL_168H'][s]=ret1.shift(1).rolling(168,min_periods=168).std(ddof=0)
  v4=vol.shift(1).rolling(4,min_periods=4).sum();vmed=v4.shift(1).rolling(168,min_periods=168).median()
  cols['VOLUME_4H_TO_TRAILING168H_MEDIAN_RATIO'][s]=v4/vmed.replace(0,np.nan)
  prior_high=d.high.shift(1).rolling(24,min_periods=24).max();prior_low=d.low.shift(1).rolling(24,min_periods=24).min();prior_close=c.shift(1)
  cols['DISTANCE_TO_PRIOR_24H_HIGH'][s]=prior_close/prior_high-1
  cols['DISTANCE_TO_PRIOR_24H_LOW'][s]=prior_close/prior_low-1
 return {k:pd.concat(v,axis=1) for k,v in cols.items()}

def xsec_z(row:pd.Series)->pd.Series:
 x=row.astype(float);mu=x.mean();sd=x.std(ddof=0)
 return (x-mu)/sd if np.isfinite(sd) and sd>1e-12 else x*0.0

def feature_matrix(ff,i):
 z=[]
 for name in FEATURES:
  row=ff[name].iloc[i].replace([np.inf,-np.inf],np.nan)
  if row.isna().any():return None
  z.append(xsec_z(row).reindex(SYMBOLS).to_numpy(float))
 return np.column_stack(z)

def future_returns(fr,i):
 vals=[]
 for s in SYMBOLS:
  e=float(fr[s].open.iloc[i]);x=float(fr[s].open.iloc[i+HOLD]);vals.append((x/e-1)*10000.)
 return np.array(vals,float)

def boot(b,field,confidence,seed):
 f=pd.DataFrame(b);f['day']=pd.to_datetime(f.entry_ms,unit='ms',utc=True).dt.floor('D');daily=f.groupby('day')[field].mean().to_numpy(float)
 if len(daily)<2:return [float(daily.mean()) if len(daily) else 0.]*2
 rng=np.random.default_rng(seed);n=len(daily);sims=np.empty(REPS)
 for j in range(REPS):sims[j]=rng.choice(daily,n,replace=True).mean()
 a=(1-confidence)/2;return [float(np.quantile(sims,a)),float(np.quantile(sims,1-a))]
def metrics(b):
 normal=np.array([x['normal_bps'] for x in b],float);stress=np.array([x['stress_bps'] for x in b],float);alpha=np.array([x['selection_alpha_bps'] for x in b],float);first=[x['normal_bps'] for x in b if x['entry_ms']<V1_MID];second=[x['normal_bps'] for x in b if x['entry_ms']>=V1_MID];parts={}
 for x in b:
  for s in x['symbols']:parts[s]=parts.get(s,0)+1
 pos=normal[normal>0];neg=normal[normal<0];pf=float(pos.sum()/abs(neg.sum())) if len(neg) else (999. if len(pos) else 0.)
 return {'batch_count':len(b),'distinct_symbols_participating':len(parts),'symbol_batch_participation':dict(sorted(parts.items())),'mean_normal_net_bps':float(normal.mean()) if len(normal) else 0.,'mean_stress_net_bps':float(stress.mean()) if len(stress) else 0.,'mean_selection_alpha_bps':float(alpha.mean()) if len(alpha) else 0.,'normal_hit_rate_pct':float((normal>0).mean()*100) if len(normal) else 0.,'normal_profit_factor':pf,'normal_daily_cluster_bootstrap95_bps':boot(b,'normal_bps',.95,42),'selection_alpha_daily_cluster_bootstrap95_bps':boot(b,'selection_alpha_bps',.95,43),'first_half_mean_normal_bps':float(np.mean(first)) if first else 0.,'second_half_mean_normal_bps':float(np.mean(second)) if second else 0.}
def run(fr):
 ff=feature_frames(fr);idx=fr[SYMBOLS[0]].index;train_start=pd.Timestamp(TRAIN_START,unit='ms',tz='UTC');d1_end=pd.Timestamp(D1_END,unit='ms',tz='UTC');v1_start=pd.Timestamp(V1_START,unit='ms',tz='UTC');v1_end=pd.Timestamp(V1_END,unit='ms',tz='UTC')
 X=[];Y=[];train_times=0
 for i,t in enumerate(idx):
  if t<train_start or t>=d1_end or t.hour%GRID or i+HOLD>=len(idx) or idx[i+HOLD]>=d1_end:continue
  x=feature_matrix(ff,i)
  if x is None:continue
  future=future_returns(fr,i);target=future-future.mean();X.append(x);Y.append(target);train_times+=1
 X=np.vstack(X);Y=np.concatenate(Y)
 model=Ridge(alpha=ALPHA,fit_intercept=False,solver='svd');model.fit(X,Y);coef=[float(x) for x in model.coef_];coef_sha=stable({'features':FEATURES,'alpha':ALPHA,'coef':coef})
 batches=[]
 for i,t in enumerate(idx):
  if t<v1_start or t>=v1_end or t.hour%GRID or i+HOLD>=len(idx) or idx[i+HOLD]>=v1_end:continue
  x=feature_matrix(ff,i)
  if x is None:continue
  pred=model.predict(x);order=np.argsort(pred);sel=[SYMBOLS[j] for j in order[-4:][::-1]];future=future_returns(fr,i);top=np.mean([future[SYMBOLS.index(s)] for s in sel]);bench=float(future.mean())
  batches.append({'entry_ms':int(t.value//1_000_000),'exit_ms':int(idx[i+HOLD].value//1_000_000),'symbols':sel,'normal_bps':float(top-N_COST),'stress_bps':float(top-S_COST),'selection_alpha_bps':float(top-bench)})
 m=metrics(batches);passed=m['batch_count']>=900 and m['distinct_symbols_participating']>=12 and m['mean_normal_net_bps']>0 and m['mean_stress_net_bps']>0 and m['mean_selection_alpha_bps']>0 and m['normal_daily_cluster_bootstrap95_bps'][0]>0 and m['selection_alpha_daily_cluster_bootstrap95_bps'][0]>0 and m['first_half_mean_normal_bps']>0 and m['second_half_mean_normal_bps']>0
 return {'schema_version':'zel.edge_factory_v2.ridge20_v1.v1','state':'PASS_RIDGE20_V1_TO_T1_CANDIDATE' if passed else 'REJECT_RIDGE20_V1_NO_SEARCH_NO_REUSE','source':{'run_id':31433969475,'artifact_id':9080341361,'dataset_sha256':DATASET_SHA,'d1_rows_per_symbol_read':D1_ROWS,'v1_rows_per_symbol_read':V1_ROWS,'t1_rows_read':0},'training':{'decision_timestamp_count':train_times,'sample_count':int(len(Y)),'feature_count':len(FEATURES),'features':list(FEATURES),'target':'FUTURE_4H_EXCESS_BPS_VS_CROSS_SECTIONAL_MEAN','model':'Ridge','alpha':ALPHA,'fit_intercept':False,'solver':'svd','hyperparameter_search':0,'coefficient_vector':coef,'coefficient_sha256':coef_sha},'V1':m,'gate':{'minimum_batches_900':m['batch_count']>=900,'minimum_breadth_12':m['distinct_symbols_participating']>=12,'normal_mean_gt0':m['mean_normal_net_bps']>0,'stress_mean_gt0':m['mean_stress_net_bps']>0,'selection_alpha_mean_gt0':m['mean_selection_alpha_bps']>0,'normal_ci95_low_gt0':m['normal_daily_cluster_bootstrap95_bps'][0]>0,'alpha_ci95_low_gt0':m['selection_alpha_daily_cluster_bootstrap95_bps'][0]>0,'first_half_gt0':m['first_half_mean_normal_bps']>0,'second_half_gt0':m['second_half_mean_normal_bps']>0},'V1_model_retrained':False,'T1_metrics_inspected':False,'ai_used_before_V1':False,'survivor_declared':False,'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED','action':'hold','next':'FREEZE_IDENTICAL_MODEL_COEFFICIENT_SHA_AND_T1_GATE' if passed else 'DROP_MODEL_NO_HYPERPARAMETER_SEARCH_NO_V1_REUSE'}
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--dataset-root',type=Path,required=True);ap.add_argument('--out',type=Path,required=True);a=ap.parse_args();r=run(load(a.dataset_root));r['receipt_sha256']=stable(r);a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(r,indent=2,sort_keys=True,allow_nan=False)+'\n');print(json.dumps({'state':r['state'],'training':r['training'],'V1':r['V1'],'gate':r['gate'],'receipt_sha256':r['receipt_sha256']},sort_keys=True));return 0
if __name__=='__main__':raise SystemExit(main())
