#!/usr/bin/env python3
from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd
DATASET_SHA='5738d5b092f090a22f8680b76cb359f9db44c06bbdc92b318b13e28c8fc42878'
SYMBOLS=('BTC-USDT','ETH-USDT','SOL-USDT','XRP-USDT','DOGE-USDT','ADA-USDT','LINK-USDT','LTC-USDT','BCH-USDT','DOT-USDT','AVAX-USDT','TRX-USDT','ETC-USDT','UNI-USDT','XLM-USDT','ATOM-USDT','NEAR-USDT','FIL-USDT','APT-USDT','ARB-USDT')
D1_ROWS=4416;RAW_START=1719792000000;SCORE_START=1722384000000;SCORE_MID=1729036800000;END=1735689600000;TRAIL=720;GRID=4;HOLD=4;N_COST=8.;S_COST=16.;MIN_BATCH=100;MIN_BREADTH=12;REPS=6000;SEED=42
FAMS=('XSEC_MOMENTUM_TOP20_LONG','XSEC_RISK_ADJ_MOMENTUM_TOP20_LONG','HIGH_DISPERSION_BOTTOM20_REVERSAL_LONG','IDIO_4H_SHOCK_REVERSAL_LONG')
def sha(v:Any)->str:return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False,default=str).encode()).hexdigest()
def load(root:Path):
 m=json.load(open(root/'manifest.json'))
 if m['state']!='PASS_BROAD20_SOURCE_UNIVERSE' or m['dataset_sha256']!=DATASET_SHA or m['accepted_count']!=20:raise RuntimeError('SOURCE_AUTH')
 out={}
 for item in m['results']:
  if item['state']!='PASS_EXACT_18M_SOURCE':raise RuntimeError('SOURCE_ROW')
  s=item['symbol'];p=root/'data'/item['file']
  if hashlib.sha256(p.read_bytes()).hexdigest()!=item['file_sha256']:raise RuntimeError('FILE_SHA:'+s)
  d=pd.read_csv(p,compression='gzip',nrows=D1_ROWS)
  if len(d)!=D1_ROWS:raise RuntimeError('D1_ROWS:'+s)
  ts=d.timestamp_ms.to_numpy(np.int64)
  if ts[0]!=RAW_START or ts[-1]!=END-3600000 or not np.all(np.diff(ts)==3600000):raise RuntimeError('D1_BOUND:'+s)
  for c in ('open','close','volume'):d[c]=pd.to_numeric(d[c],errors='raise')
  d.index=pd.to_datetime(d.timestamp_ms,unit='ms',utc=True);out[s]=d
 return out
def features(fr):
 r24={};r4={};risk={}
 for s,d in fr.items():
  c=d.close;ret1=c.pct_change();r24[s]=c.shift(1)/c.shift(25)-1;r4[s]=c.shift(1)/c.shift(5)-1;risk[s]=ret1.shift(1).rolling(168,min_periods=168).std()
 rf=pd.concat(r24,axis=1);r4f=pd.concat(r4,axis=1);riskf=pd.concat(risk,axis=1);disp=rf.std(axis=1,ddof=0);dispq=disp.shift(1).rolling(TRAIL,min_periods=TRAIL).quantile(.8);idio=r4f.sub(r4f.median(axis=1),axis=0);idioq=pd.DataFrame(index=idio.index,columns=idio.columns,dtype=float)
 for s in SYMBOLS:idioq[s]=idio[s].shift(1).rolling(TRAIL,min_periods=TRAIL).quantile(.1)
 return rf,rf/riskf.replace(0,np.nan),disp,dispq,idio,idioq
def boot(b):
 f=pd.DataFrame(b);f['day']=pd.to_datetime(f.entry_ms,unit='ms',utc=True).dt.floor('D');daily=f.groupby('day')['normal'].mean().to_numpy(float)
 if len(daily)<2:return [float(daily.mean()) if len(daily) else 0.]*2
 rng=np.random.default_rng(SEED);vals=np.empty(REPS);n=len(daily)
 for i in range(REPS):vals[i]=rng.choice(daily,n,replace=True).mean()
 return [float(np.quantile(vals,.005)),float(np.quantile(vals,.995))]
def metrics(b):
 vals=np.array([x['normal'] for x in b],float);stress=np.array([x['stress'] for x in b],float);by={};first=[];second=[]
 for x in b:
  for s in x['symbols']:by[s]=by.get(s,0)+1
  (first if x['entry_ms']<SCORE_MID else second).append(x['normal'])
 ci=boot(b);pos=vals[vals>0];neg=vals[vals<0];pf=float(pos.sum()/abs(neg.sum())) if len(neg) else (999. if len(pos) else 0.)
 return {'batch_count':len(b),'independent_day_count':len({pd.Timestamp(x['entry_ms'],unit='ms',tz='UTC').floor('D') for x in b}),'mean_normal_bps':float(vals.mean()) if len(vals) else 0.,'mean_stress_bps':float(stress.mean()) if len(stress) else 0.,'normal_hit_rate_pct':float((vals>0).mean()*100) if len(vals) else 0.,'normal_profit_factor':pf,'daily_cluster_bootstrap99_normal_bps':ci,'distinct_symbols_participating':len(by),'symbol_batch_participation':dict(sorted(by.items())),'first_half_mean_normal_bps':float(np.mean(first)) if first else 0.,'second_half_mean_normal_bps':float(np.mean(second)) if second else 0.}
def run(fr):
 rf,raf,disp,dq,idio,iq=features(fr);idx=fr[SYMBOLS[0]].index;start=pd.Timestamp(SCORE_START,unit='ms',tz='UTC');end=pd.Timestamp(END,unit='ms',tz='UTC');bs={f:[] for f in FAMS}
 def add(fam,i,legs):
  if not legs or i+HOLD>=len(idx):return
  xt=idx[i+HOLD]
  if xt>=end:return
  raw=[]
  for s in legs:
   e=float(fr[s].open.iloc[i]);x=float(fr[s].open.iloc[i+HOLD]);raw.append((x/e-1)*10000)
  bs[fam].append({'entry_ms':int(idx[i].value//1_000_000),'exit_ms':int(xt.value//1_000_000),'symbols':list(legs),'leg_count':len(legs),'normal':float(np.mean(raw)-N_COST),'stress':float(np.mean(raw)-S_COST)})
 for i,t in enumerate(idx):
  if t<start or t>=end or t.hour%GRID:continue
  row=rf.iloc[i].dropna()
  if len(row)==20:add(FAMS[0],i,list(row.sort_values(ascending=False).head(4).index))
  row=raf.iloc[i].replace([np.inf,-np.inf],np.nan).dropna()
  if len(row)==20:add(FAMS[1],i,list(row.sort_values(ascending=False).head(4).index))
  if np.isfinite(disp.iloc[i]) and np.isfinite(dq.iloc[i]) and disp.iloc[i]>=dq.iloc[i]:
   row=rf.iloc[i].dropna()
   if len(row)==20:add(FAMS[2],i,list(row.sort_values().head(4).index))
  rv=idio.iloc[i];qv=iq.iloc[i];eligible=[s for s in SYMBOLS if np.isfinite(rv[s]) and np.isfinite(qv[s]) and rv[s]<=qv[s]]
  if eligible:add(FAMS[3],i,sorted(eligible,key=lambda s:(float(rv[s]),s))[:4])
 res={f:metrics(bs[f]) for f in FAMS};passes=[]
 for f,m in res.items():
  strict=m['batch_count']>=MIN_BATCH and m['distinct_symbols_participating']>=MIN_BREADTH and m['mean_normal_bps']>0 and m['daily_cluster_bootstrap99_normal_bps'][0]>0 and m['mean_stress_bps']>0 and m['first_half_mean_normal_bps']>0 and m['second_half_mean_normal_bps']>0
  m['state']='PASS_D1_BROAD_EFFECT' if strict else ('HOLD_D1_BROAD_POSITIVE_NOT_ROBUST' if m['batch_count']>=MIN_BATCH and m['mean_normal_bps']>0 else 'REJECT_D1_BROAD_NONPOSITIVE_OR_THIN')
  if strict:passes.append({'family':f,**m})
 passes.sort(key=lambda x:(-x['daily_cluster_bootstrap99_normal_bps'][0],-x['mean_stress_bps'],-x['mean_normal_bps'],x['family']))
 c=[{'family':x['family'],'authority':'V1_HYPOTHESIS_ONLY_NOT_SURVIVOR','batch_count':x['batch_count'],'mean_normal_bps':x['mean_normal_bps'],'mean_stress_bps':x['mean_stress_bps'],'ci99':x['daily_cluster_bootstrap99_normal_bps'],'breadth':x['distinct_symbols_participating']} for x in passes[:2]]
 return {'schema_version':'zel.edge_factory_v2.broad20_d1.v1','state':'PASS_BROAD20_D1_WITH_V1_CANDIDATE' if c else 'HOLD_BROAD20_D1_NO_CANDIDATE','source':{'run_id':31433969475,'artifact_id':9080341361,'dataset_sha256':DATASET_SHA,'d1_rows_per_symbol_read':4416,'v1_rows_read':0,'t1_rows_read':0},'results':res,'v1_candidate_count':len(c),'v1_candidates':c,'v1_metrics_inspected':False,'t1_metrics_inspected':False,'ai_used_for_discovery':False,'survivor_declared':False,'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED','action':'hold'}
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--dataset-root',type=Path,required=True);ap.add_argument('--out',type=Path,required=True);a=ap.parse_args();r=run(load(a.dataset_root));r['receipt_sha256']=sha(r);a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(r,indent=2,sort_keys=True)+'\n');print(json.dumps({'state':r['state'],'results':r['results'],'v1_candidates':r['v1_candidates'],'receipt_sha256':r['receipt_sha256']},sort_keys=True));return 0
if __name__=='__main__':raise SystemExit(main())
