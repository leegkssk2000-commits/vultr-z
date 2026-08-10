#!/usr/bin/env python3
from __future__ import annotations

import argparse, hashlib, json
from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd

DATASET_SHA='87ff0595f7ab90728af265eaf1b5aa79571317de61c6f68ce890526f3eff3c28'
D1_ROWS=4416; V1_ROWS=4344; READ_ROWS=D1_ROWS+V1_ROWS
DATA_START_MS=1719792000000
V1_START_MS=1735689600000; V1_END_MS=1751328000000
SYMBOLS=('BTC-USDT','ETH-USDT','LINK-USDT','SOL-USDT','XRP-USDT'); ALTS=('ETH-USDT','LINK-USDT','SOL-USDT','XRP-USDT')
TRAIL=720; GRID=4; HOLD=4; COST_BPS=8.0; MIN_EVENTS=60; BOOT_REPS=6000; BOOT_SEED=42; QLOW=.005; QHIGH=.995
FAMILIES=('TS_TREND_TOP_QUINTILE_LONG','NEGATIVE_SHOCK_REVERSAL_LONG','VOLUME_SHOCK_CONTINUATION_LONG','BTC_RELATIVE_DIVERGENCE_REVERSAL_LONG','HIGH_DISPERSION_LAGGARD_REVERSAL_LONG')
D1_MEAN={
 'TS_TREND_TOP_QUINTILE_LONG':8.04358678802424,
 'NEGATIVE_SHOCK_REVERSAL_LONG':19.507806120159184,
 'VOLUME_SHOCK_CONTINUATION_LONG':34.7398883757952,
 'BTC_RELATIVE_DIVERGENCE_REVERSAL_LONG':1.8780153372983275,
 'HIGH_DISPERSION_LAGGARD_REVERSAL_LONG':28.599546000990177,
}

def stable_sha(v:Any)->str:
    return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False,default=str).encode()).hexdigest()

def load_v1(root:Path)->dict[str,pd.DataFrame]:
    m=json.loads((root/'manifest.json').read_text())
    if m.get('state')!='PASS_FRESH_18M_1H_DATA_STAGED' or m.get('dataset_sha256')!=DATASET_SHA: raise RuntimeError('DATASET_AUTHORITY')
    if m['partitions']['D1_DISCOVERY']['rows_per_symbol']!=D1_ROWS or m['partitions']['V1_VALIDATION']['rows_per_symbol']!=V1_ROWS: raise RuntimeError('PARTITION_AUTHORITY')
    out={}
    for item in m['results']:
        s=str(item['symbol']); p=root/'data'/str(item['file'])
        if hashlib.sha256(p.read_bytes()).hexdigest()!=item['file_sha256']: raise RuntimeError(f'FILE_SHA:{s}')
        d=pd.read_csv(p,compression='gzip',nrows=READ_ROWS)
        if len(d)!=READ_ROWS: raise RuntimeError(f'READ_ROWS:{s}:{len(d)}')
        ts=d['timestamp_ms'].to_numpy(dtype=np.int64)
        if int(ts[0])!=DATA_START_MS or int(ts[-1])!=V1_END_MS-3_600_000: raise RuntimeError(f'VEND_BOUNDARY:{s}:{ts[0]}:{ts[-1]}')
        if not np.all(np.diff(ts)==3_600_000): raise RuntimeError(f'CONTINUITY:{s}')
        for c in ('open','high','low','close','volume'): d[c]=pd.to_numeric(d[c],errors='raise')
        d.index=pd.to_datetime(d['timestamp_ms'],unit='ms',utc=True); out[s]=d
    if set(out)!=set(SYMBOLS): raise RuntimeError(f'SYMBOL_SET:{sorted(out)}')
    return out

def make_signals(frames):
    sig={}
    for s,d in frames.items():
        close=d['close']; vol=d['volume']
        r24=close.shift(1)/close.shift(25)-1
        r4=close.shift(1)/close.shift(5)-1
        v4=vol.shift(1).rolling(4,min_periods=4).sum()
        sig[s]={
            'r24':r24,'r4':r4,'v4':v4,
            'r24_q80':r24.shift(1).rolling(TRAIL,min_periods=TRAIL).quantile(.8),
            'r4_q10':r4.shift(1).rolling(TRAIL,min_periods=TRAIL).quantile(.1),
            'v4_q90':v4.shift(1).rolling(TRAIL,min_periods=TRAIL).quantile(.9),
        }
    btc=sig['BTC-USDT']['r24']
    for s in ALTS:
        rel=sig[s]['r24']-btc
        sig[s]['rel24']=rel
        sig[s]['rel24_q10']=rel.shift(1).rolling(TRAIL,min_periods=TRAIL).quantile(.1)
    rf=pd.concat({s:sig[s]['r24'] for s in SYMBOLS},axis=1)
    disp=rf.std(axis=1,ddof=0)
    return {'per_symbol':sig,'r24_frame':rf,'disp':disp,'disp_q90':disp.shift(1).rolling(TRAIL,min_periods=TRAIL).quantile(.9)}

def bootstrap_daily(events):
    if not events:return [0.0,0.0]
    f=pd.DataFrame(events); f['day']=pd.to_datetime(f['entry_ms'],unit='ms',utc=True).dt.floor('D')
    daily=f.groupby('day',sort=True)['net_bps'].mean().to_numpy(dtype=float)
    if len(daily)<2:
        x=float(daily[0]) if len(daily) else 0.0; return [x,x]
    rng=np.random.default_rng(BOOT_SEED); sims=np.empty(BOOT_REPS,dtype=float); n=len(daily)
    for i in range(BOOT_REPS): sims[i]=float(rng.choice(daily,size=n,replace=True).mean())
    return [float(np.quantile(sims,QLOW)),float(np.quantile(sims,QHIGH))]

def summarize(family,events):
    vals=np.array([float(e['net_bps']) for e in events],dtype=float); raw=np.array([float(e['raw_bps']) for e in events],dtype=float); by={}; counts={}
    for e in events:
        s=str(e['symbol']); by.setdefault(s,[]).append(float(e['net_bps'])); counts[s]=counts.get(s,0)+1
    means={s:float(np.mean(v)) for s,v in sorted(by.items())}; pos=sum(v>0 for v in means.values()); ci=bootstrap_daily(events); mean=float(vals.mean()) if len(vals) else 0.0
    strict=len(events)>=MIN_EVENTS and mean>0 and pos>=3 and ci[0]>0 and D1_MEAN[family]>0
    state='PASS_V1_EXACT_REPLICATION' if strict else ('HOLD_V1_POSITIVE_NOT_ROBUST' if len(events)>=MIN_EVENTS and mean>0 else 'REJECT_V1_NONPOSITIVE_OR_NARROW')
    return {'state':state,'event_count':len(events),'independent_day_count':len({pd.Timestamp(e['entry_ms'],unit='ms',tz='UTC').floor('D') for e in events}),'mean_raw_bps':float(raw.mean()) if len(raw) else 0.0,'mean_net_bps_after_cost_floor':mean,'net_hit_rate_pct':float((vals>0).mean()*100) if len(vals) else 0.0,'daily_cluster_bootstrap99_net_bps':ci,'positive_symbol_count':pos,'symbol_mean_net_bps':means,'symbol_event_count':dict(sorted(counts.items())),'d1_mean_net_bps':D1_MEAN[family],'same_family_d1_mean_positive':D1_MEAN[family]>0}

def run(frames):
    ss=make_signals(frames); idx=frames['BTC-USDT'].index; start=pd.Timestamp(V1_START_MS,unit='ms',tz='UTC'); end=pd.Timestamp(V1_END_MS,unit='ms',tz='UTC'); events={f:[] for f in FAMILIES}
    def add(fam,s,i,sv):
        if i+HOLD>=len(idx):return
        xt=idx[i+HOLD]
        if xt>=end:return
        entry=float(frames[s]['open'].iloc[i]); exit_=float(frames[s]['open'].iloc[i+HOLD])
        if not np.isfinite(entry) or not np.isfinite(exit_) or entry<=0:return
        raw=(exit_/entry-1.0)*10000.0
        events[fam].append({'symbol':s,'entry_ms':int(idx[i].value//1_000_000),'exit_ms':int(xt.value//1_000_000),'signal_value':float(sv),'raw_bps':float(raw),'net_bps':float(raw-COST_BPS)})
    for i,t in enumerate(idx):
        if t<start or t>=end or t.hour%GRID!=0:continue
        for s in SYMBOLS:
            z=ss['per_symbol'][s]; r24,q80=z['r24'].iloc[i],z['r24_q80'].iloc[i]
            if np.isfinite(r24) and np.isfinite(q80) and r24>=q80:add('TS_TREND_TOP_QUINTILE_LONG',s,i,r24-q80)
            r4,q10=z['r4'].iloc[i],z['r4_q10'].iloc[i]
            if np.isfinite(r4) and np.isfinite(q10) and r4<=q10:add('NEGATIVE_SHOCK_REVERSAL_LONG',s,i,q10-r4)
            v4,vq=z['v4'].iloc[i],z['v4_q90'].iloc[i]
            if np.isfinite(r4) and np.isfinite(v4) and np.isfinite(vq) and r4>0 and v4>=vq:add('VOLUME_SHOCK_CONTINUATION_LONG',s,i,v4/vq-1 if vq>0 else 0.0)
        for s in ALTS:
            z=ss['per_symbol'][s]; rel,q=z['rel24'].iloc[i],z['rel24_q10'].iloc[i]
            if np.isfinite(rel) and np.isfinite(q) and rel<=q:add('BTC_RELATIVE_DIVERGENCE_REVERSAL_LONG',s,i,q-rel)
        disp,dq=ss['disp'].iloc[i],ss['disp_q90'].iloc[i]; row=ss['r24_frame'].iloc[i]
        if np.isfinite(disp) and np.isfinite(dq) and disp>=dq and row.notna().all():
            loser=min(SYMBOLS,key=lambda s:(float(row[s]),s)); add('HIGH_DISPERSION_LAGGARD_REVERSAL_LONG',loser,i,disp-dq)
    results={f:summarize(f,events[f]) for f in FAMILIES}
    passing=[{'family':f,**r} for f,r in results.items() if r['state']=='PASS_V1_EXACT_REPLICATION']
    passing.sort(key=lambda x:(-float(x['daily_cluster_bootstrap99_net_bps'][0]),-float(x['mean_net_bps_after_cost_floor']),x['family']))
    candidates=[{'family':x['family'],'authority':'T1_HYPOTHESIS_ONLY_NOT_SURVIVOR','event_count':x['event_count'],'mean_net_bps_after_cost_floor':x['mean_net_bps_after_cost_floor'],'daily_cluster_bootstrap99_net_bps':x['daily_cluster_bootstrap99_net_bps'],'positive_symbol_count':x['positive_symbol_count']} for x in passing[:2]]
    return {'schema_version':'zel.edge_factory_v2.v1_exact_replication.v1','state':'PASS_V1_WITH_T1_CANDIDATE' if candidates else 'HOLD_V1_NO_EXACT_REPLICATION_CANDIDATE','protocol_change_reason':'OLDER_2023_INDEPENDENT_BINGX_1H_HISTORY_UNAVAILABLE','parent_d1_receipt_sha256':'2e5914daf8f4fbd020b05173d9482da6e60fa474cc3ad66d12660ef0c6e41bfe','source':{'run_id':31429880433,'artifact_id':9078686271,'dataset_sha256':DATASET_SHA,'d1_rows_read':D1_ROWS,'v1_rows_read':V1_ROWS,'t1_rows_read':0},'v1':{'start_ms':V1_START_MS,'end_exclusive_ms':V1_END_MS,'timeframe':'1h','decision_grid_hours':GRID,'holding_hours':HOLD,'cost_bps_roundtrip':COST_BPS},'results':results,'t1_candidate_count':len(candidates),'t1_candidates':candidates,'t1_metrics_inspected':False,'ai_used_before_v1_replication':False,'survivor_declared':False,'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED','action':'hold'}

def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument('--dataset-root',type=Path,required=True); ap.add_argument('--out',type=Path,required=True); a=ap.parse_args(); r=run(load_v1(a.dataset_root)); r['receipt_sha256']=stable_sha(r); a.out.parent.mkdir(parents=True,exist_ok=True); a.out.write_text(json.dumps(r,indent=2,sort_keys=True,allow_nan=False)+'\n'); print(json.dumps({'state':r['state'],'results':r['results'],'t1_candidates':r['t1_candidates'],'receipt_sha256':r['receipt_sha256']},sort_keys=True)); return 0

if __name__=='__main__':raise SystemExit(main())
