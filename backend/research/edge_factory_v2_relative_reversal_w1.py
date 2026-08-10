#!/usr/bin/env python3
from __future__ import annotations

import argparse, hashlib, json
from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd

DATASET_SHA='53676bb379635c6f81908be2c20e1598e00bffa4d0e08d8b492646416b8a46d8'
W1_START_MS=1771027200000
W1_END_MS=1774828800000
SYMBOLS=('BTC-USDT','ETH-USDT','LINK-USDT','SOL-USDT','XRP-USDT')
ALTS=('ETH-USDT','LINK-USDT','SOL-USDT','XRP-USDT')
LOOKBACK_HOURS=24
GRID_HOURS=4
HOLD_HOURS=4
ROUNDTRIP_COST_BPS=8.0
MIN_EVENTS=30
BOOT_REPS=4000
BOOT_SEED=42

def canonical_sha(v:Any)->str:
    return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False,default=str).encode()).hexdigest()

def load_hourly(root:Path)->dict[str,pd.DataFrame]:
    m=json.loads((root/'manifest.json').read_text())
    if m.get('state')!='PASS_BINGX_1M_GAP_EXCLUDED_DATASET_STAGED' or m.get('dataset_sha256')!=DATASET_SHA:
        raise RuntimeError('DATASET_AUTHORITY')
    rows=[r for r in m.get('results',[]) if r.get('segment_id')=='POST_GAP']
    if len(rows)!=5: raise RuntimeError(f'POST_GAP_CARDINALITY:{len(rows)}')
    out={}
    for r in rows:
        s=str(r['symbol']); p=root/'data'/str(r['file'])
        if hashlib.sha256(p.read_bytes()).hexdigest()!=r['file_sha256']: raise RuntimeError(f'FILE_SHA:{s}')
        if int(r['row_count'])!=192030 or int(r['missing_interval_count'])!=0 or int(r['duplicate_timestamp_count'])!=0:
            raise RuntimeError(f'FILE_INTEGRITY:{s}')
        d=pd.read_csv(p,compression='gzip')
        d['timestamp']=pd.to_datetime(d['timestamp_ms'],unit='ms',utc=True)
        d=d.set_index('timestamp').sort_index()
        h=d[['open','high','low','close','volume']].resample('1h',label='left',closed='left').agg({'open':'first','high':'max','low':'min','close':'last','volume':'sum'}).dropna()
        out[s]=h
    if set(out)!=set(SYMBOLS): raise RuntimeError(f'SYMBOL_SET:{sorted(out)}')
    common=None
    for h in out.values(): common=h.index if common is None else common.intersection(h.index)
    if common is None or len(common)<100: raise RuntimeError('COMMON_INDEX')
    return {s:out[s].loc[common].copy() for s in SYMBOLS}

def daily_bootstrap(events:list[dict[str,Any]])->list[float]:
    if not events: return [0.0,0.0]
    f=pd.DataFrame(events)
    f['day']=pd.to_datetime(f['entry_ms'],unit='ms',utc=True).dt.floor('D')
    daily=f.groupby('day',sort=True)['net_bps'].mean().to_numpy(dtype=float)
    if len(daily)<2:
        x=float(daily[0]) if len(daily) else 0.0; return [x,x]
    rng=np.random.default_rng(BOOT_SEED); sims=np.empty(BOOT_REPS,dtype=float); n=len(daily)
    for i in range(BOOT_REPS): sims[i]=float(rng.choice(daily,size=n,replace=True).mean())
    return [float(np.quantile(sims,.025)),float(np.quantile(sims,.975))]

def summarize(events:list[dict[str,Any]],breadth_required:int=3)->dict[str,Any]:
    vals=np.array([float(x['net_bps']) for x in events],dtype=float)
    by={}
    for e in events: by.setdefault(str(e['symbol']),[]).append(float(e['net_bps']))
    sm={s:float(np.mean(v)) for s,v in sorted(by.items())}; pos=sum(v>0 for v in sm.values()); ci=daily_bootstrap(events)
    mean=float(vals.mean()) if len(vals) else 0.0
    if len(events)>=MIN_EVENTS and mean>0 and pos>=breadth_required and ci[0]>0: state='PASS_W1_EFFECT_DISCOVERY'
    elif len(events)>=MIN_EVENTS and mean>0: state='HOLD_W1_POSITIVE_NOT_ROBUST'
    else: state='REJECT_W1_NONPOSITIVE_OR_NARROW'
    return {'state':state,'event_count':len(events),'independent_day_count':len({pd.Timestamp(e['entry_ms'],unit='ms',tz='UTC').floor('D') for e in events}),'mean_net_bps_after_cost_floor':mean,'mean_raw_bps':mean+ROUNDTRIP_COST_BPS,'net_hit_rate_pct':float((vals>0).mean()*100) if len(vals) else 0.0,'daily_block_bootstrap95_net_bps':ci,'positive_symbol_count':pos,'breadth_required':breadth_required,'symbol_mean_net_bps':sm}

def evaluate(hourly:dict[str,pd.DataFrame])->dict[str,Any]:
    times=hourly['BTC-USDT'].index; start=pd.Timestamp(W1_START_MS,unit='ms',tz='UTC'); end=pd.Timestamp(W1_END_MS,unit='ms',tz='UTC')
    xsec=[]; rel=[]
    for i in range(LOOKBACK_HOURS+1,len(times)-HOLD_HOURS):
        t=times[i]
        if t<start or t>=end or t.hour%GRID_HOURS!=0: continue
        ret24={}
        for s in SYMBOLS:
            h=hourly[s]; prev=float(h['close'].iloc[i-1]); lag=float(h['close'].iloc[i-1-LOOKBACK_HOURS])
            if not np.isfinite(prev) or not np.isfinite(lag) or lag<=0: break
            ret24[s]=prev/lag-1.0
        if len(ret24)!=len(SYMBOLS): continue
        def pnl(s:str):
            h=hourly[s]; entry=float(h['open'].iloc[i]); exit_=float(h['open'].iloc[i+HOLD_HOURS])
            if not np.isfinite(entry) or not np.isfinite(exit_) or entry<=0: return None
            raw=(exit_/entry-1.0)*10000.0
            return {'symbol':s,'entry_ms':int(t.value//1_000_000),'exit_ms':int(times[i+HOLD_HOURS].value//1_000_000),'raw_bps':float(raw),'net_bps':float(raw-ROUNDTRIP_COST_BPS)}
        loser=min(SYMBOLS,key=lambda s:(ret24[s],s)); row=pnl(loser)
        if row is not None: row['signal_24h_return']=float(ret24[loser]); xsec.append(row)
        btc=ret24['BTC-USDT']; scores={s:ret24[s]-btc for s in ALTS}; laggard=min(ALTS,key=lambda s:(scores[s],s)); row=pnl(laggard)
        if row is not None: row['signal_alt_minus_btc_24h_return']=float(scores[laggard]); rel.append(row)
    results={'XSEC_LOSER_REVERSAL_LONG':summarize(xsec),'BTC_RELATIVE_LAGGARD_REVERSAL_LONG':summarize(rel)}
    passes=[{'family':f,**r} for f,r in results.items() if r['state']=='PASS_W1_EFFECT_DISCOVERY']
    passes.sort(key=lambda x:(-float(x['mean_net_bps_after_cost_floor']),x['family']))
    candidates=[{'family':x['family'],'authority':'W2_HYPOTHESIS_ONLY_NOT_SURVIVOR','event_count':x['event_count'],'mean_net_bps_after_cost_floor':x['mean_net_bps_after_cost_floor'],'daily_block_bootstrap95_net_bps':x['daily_block_bootstrap95_net_bps'],'positive_symbol_count':x['positive_symbol_count']} for x in passes[:1]]
    return {'schema_version':'zel.edge_factory_v2.relative_reversal_w1.v1','state':'PASS_RELATIVE_REVERSAL_W1_WITH_CANDIDATE' if candidates else 'HOLD_RELATIVE_REVERSAL_W1_NO_CANDIDATE','dataset':{'run_id':30971232337,'sha256':DATASET_SHA,'w1_start_ms':W1_START_MS,'w1_end_exclusive_ms':W1_END_MS,'symbols':list(SYMBOLS)},'contract':{'timeframe':'1h','lookback_hours':LOOKBACK_HOURS,'decision_grid_hours':GRID_HOURS,'holding_hours':HOLD_HOURS,'entry':'NEXT_1H_OPEN_AFTER_LAST_COMPLETED_BAR','roundtrip_cost_floor_bps':ROUNDTRIP_COST_BPS,'parameter_search':0,'candidate_budget':1},'results':results,'w2_candidate_count':len(candidates),'w2_candidates':candidates,'ai_used_for_discovery':False,'w2_w3_metrics_inspected':False,'survivor_declared':False,'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED','action':'hold'}

def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument('--dataset-root',type=Path,required=True); ap.add_argument('--out',type=Path,required=True); a=ap.parse_args()
    r=evaluate(load_hourly(a.dataset_root)); r['receipt_sha256']=canonical_sha(r); a.out.parent.mkdir(parents=True,exist_ok=True); a.out.write_text(json.dumps(r,indent=2,sort_keys=True,allow_nan=False)+'\n')
    print(json.dumps({'state':r['state'],'receipt_sha256':r['receipt_sha256'],'results':r['results'],'w2_candidates':r['w2_candidates']},sort_keys=True)); return 0

if __name__=='__main__': raise SystemExit(main())
