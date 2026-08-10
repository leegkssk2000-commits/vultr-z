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
PARTS={'D1':(1775001600000,1777593600000),'V1':(1777593600000,1780272000000),'T1':(1780272000000,1785542400000)}
FUND_STEP=8*3_600_000;HOLD_HOURS=8;LEG_WEIGHT=.125;NORMAL_COST=12.30757224;STRESS_COST=14.61514448;REPS=6000

def stable(v:Any)->str:return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False,default=str).encode()).hexdigest()
def fsha(p:Path)->str:
 h=hashlib.sha256()
 with p.open('rb') as f:
  for c in iter(lambda:f.read(1<<20),b''):h.update(c)
 return h.hexdigest()
def load_price(root:Path,start:int,end:int):
 m=json.load(open(root/'manifest.json'))
 if m.get('state')!='PASS_BROAD20_FRESH2026_SOURCE' or m.get('dataset_sha256')!=PRICE_SHA:raise RuntimeError('PRICE_AUTH')
 rows={r['symbol']:r for r in m['results']};out={};expected=(end-start)//3_600_000
 for s in SYMBOLS:
  item=rows[s];p=root/'data'/item['file']
  if fsha(p)!=item['file_sha256']:raise RuntimeError('PRICE_SHA:'+s)
  vals=[]
  with gzip.open(p,'rt',encoding='utf-8',newline='') as f:
   for r in csv.DictReader(f):
    t=int(r['timestamp_ms'])
    if t<start:continue
    if t>=end:break
    vals.append(r)
  if len(vals)!=expected:raise RuntimeError(f'PRICE_ROWS:{s}:{len(vals)}:{expected}')
  d=pd.DataFrame(vals);d['timestamp_ms']=pd.to_numeric(d['timestamp_ms'],errors='raise').astype('int64')
  for c in ('open','close'):d[c]=pd.to_numeric(d[c],errors='raise')
  ts=d.timestamp_ms.to_numpy(np.int64)
  if int(ts[0])!=start or int(ts[-1])!=end-3_600_000 or not np.all(np.diff(ts)==3_600_000):raise RuntimeError('PRICE_CONTINUITY:'+s)
  d.index=pd.to_datetime(d.timestamp_ms,unit='ms',utc=True);out[s]=d
 return out
def load_funding(root:Path,start:int,end:int):
 m=json.load(open(root/'manifest.json'))
 if m.get('schema_version')!='zel.edge_factory_v2.xsec_ls_funding2026_exact_probe.v1' or m.get('funding_dataset_sha256')!=FUNDING_SHA:raise RuntimeError('FUND_AUTH')
 rows={r['symbol']:r for r in m['results']}
 if any(rows[s]['state']!='PASS_EXACT_NATIVE_FUNDING_SCHEDULE' for s in SYMBOLS):raise RuntimeError('FUND_UNIVERSE')
 if any(rows[s]['state']=='PASS_EXACT_NATIVE_FUNDING_SCHEDULE' for s in EXCLUDED):raise RuntimeError('EXCLUDED_DRIFT')
 out={};expected=(end-start)//FUND_STEP
 for s in SYMBOLS:
  item=rows[s];p=root/'data'/item['file']
  if fsha(p)!=item['file_sha256']:raise RuntimeError('FUND_SHA:'+s)
  vals=[]
  with gzip.open(p,'rt',encoding='utf-8',newline='') as f:
   for r in csv.DictReader(f):
    t=int(r['fundingTime'])
    if t<start:continue
    if t>=end:break
    vals.append((t,float(r['fundingRate'])))
  if len(vals)!=expected:raise RuntimeError(f'FUND_ROWS:{s}:{len(vals)}:{expected}')
  ts=np.array([x[0] for x in vals],np.int64)
  if int(ts[0])!=start or int(ts[-1])!=end-FUND_STEP or not np.all(np.diff(ts)==FUND_STEP):raise RuntimeError('FUND_CONTINUITY:'+s)
  out[s]={t:r for t,r in vals}
 return out
def bootstrap(v:list[float],confidence=.95,seed=42):
 a=np.asarray(v,float)
 if len(a)<2:
  x=float(a.mean()) if len(a) else 0.;return [x,x]
 rng=np.random.default_rng(seed);n=len(a);sims=np.empty(REPS)
 for i in range(REPS):sims[i]=rng.choice(a,n,replace=True).mean()
 q=(1-confidence)/2;return [float(np.quantile(sims,q)),float(np.quantile(sims,1-q))]
def metrics(bs,field):
 v=np.array([b[field] for b in bs],float);pos=v[v>0];neg=v[v<0];pf=float(pos.sum()/abs(neg.sum())) if len(neg) and abs(float(neg.sum()))>1e-12 else (999. if len(pos) else 0.);cum=peak=dd=0.
 for x in v:cum+=float(x);peak=max(peak,cum);dd=max(dd,peak-cum)
 return {'mean_bps':float(v.mean()) if len(v) else 0.,'median_bps':float(np.median(v)) if len(v) else 0.,'hit_rate_pct':float((v>0).mean()*100) if len(v) else 0.,'profit_factor':pf,'bootstrap95_mean_bps':bootstrap(list(v),.95,42),'max_drawdown_bps_additive':dd}
def evaluate(price,fund,start,end,stage):
 pidx=price[SYMBOLS[0]].index;ppos={int(t.value//1_000_000):i for i,t in enumerate(pidx)};bs=[];lp={s:0 for s in SYMBOLS};sp={s:0 for s in SYMBOLS}
 for t in range(start,end,FUND_STEP):
  entry=t+3_600_000;exit_=t+9*3_600_000;nextfund=t+FUND_STEP
  if exit_>=end or nextfund>=end:continue
  scores={s:fund[s][t] for s in SYMBOLS};ranked=sorted(SYMBOLS,key=lambda s:(scores[s],s));longs=ranked[:4];shorts=ranked[-4:][::-1]
  if entry not in ppos or exit_ not in ppos:raise RuntimeError(f'PRICE_BOUNDARY:{t}')
  i=ppos[entry];j=ppos[exit_];price_bps=0.;fund_bps=0.
  for s in longs:
   e=float(price[s].open.iloc[i]);x=float(price[s].open.iloc[j]);price_bps+=LEG_WEIGHT*((x/e-1)*10000);fund_bps-=LEG_WEIGHT*fund[s][nextfund]*10000;lp[s]+=1
  for s in shorts:
   e=float(price[s].open.iloc[i]);x=float(price[s].open.iloc[j]);price_bps-=LEG_WEIGHT*((x/e-1)*10000);fund_bps+=LEG_WEIGHT*fund[s][nextfund]*10000;sp[s]+=1
  before=price_bps+fund_bps;bs.append({'decision_ms':t,'entry_ms':entry,'exit_ms':exit_,'longs':longs,'shorts':shorts,'price_spread_bps':price_bps,'next_funding_cashflow_bps':fund_bps,'total_before_cost_bps':before,'total_net_bps':before-NORMAL_COST,'stress_total_net_bps':before-STRESS_COST})
 mid=len(bs)//2;first=[b['total_net_bps'] for b in bs[:mid]];second=[b['total_net_bps'] for b in bs[mid:]];normal=metrics(bs,'total_net_bps');stress=metrics(bs,'stress_total_net_bps');fundm=metrics(bs,'next_funding_cashflow_bps');pricem=metrics(bs,'price_spread_bps');lb=sum(v>0 for v in lp.values());sb=sum(v>0 for v in sp.values());gate={'minimum_batches_80':len(bs)>=80,'long_breadth_12':lb>=12,'short_breadth_12':sb>=12,'mean_total_net_gt0':normal['mean_bps']>0,'mean_stress_total_net_gt0':stress['mean_bps']>0,'mean_next_funding_cashflow_gt0':fundm['mean_bps']>0,'bootstrap95_total_net_low_gt0':normal['bootstrap95_mean_bps'][0]>0,'first_half_total_net_gt0':float(np.mean(first))>0 if first else False,'second_half_total_net_gt0':float(np.mean(second))>0 if second else False};passed=all(gate.values())
 return {'stage':stage,'state':(f'PASS_FUNDING_UNWIND16_{stage}_TO_'+('FROZEN_V1' if stage=='D1' else 'FROZEN_T1')) if passed else f'REJECT_FUNDING_UNWIND16_{stage}_NO_SEARCH_NO_REUSE','candidate_id':'XSEC_FUNDING_UNWIND_L4_S4_8H_V1','window':{'start_ms':start,'end_exclusive_ms':end},'portfolio':{'batch_count':len(bs),'long_distinct_symbols':lb,'short_distinct_symbols':sb,'long_participation':lp,'short_participation':sp,'first_half_mean_total_net_bps':float(np.mean(first)) if first else 0.,'second_half_mean_total_net_bps':float(np.mean(second)) if second else 0.},'price_component':pricem,'funding_component':fundm,'normal_total':normal,'stress_total':stress,'gate':gate,'pass':passed}
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--stage',choices=('D1','V1'),required=True);ap.add_argument('--price-root',type=Path,required=True);ap.add_argument('--funding-root',type=Path,required=True);ap.add_argument('--parent-d1',type=Path);ap.add_argument('--out',type=Path,required=True);a=ap.parse_args();start,end=PARTS[a.stage]
 if a.stage=='V1':
  if not a.parent_d1:raise RuntimeError('V1_PARENT_REQUIRED')
  p=json.load(open(a.parent_d1))
  if p.get('state')!='PASS_FUNDING_UNWIND16_D1_TO_FROZEN_V1' or not p.get('pass'):raise RuntimeError('V1_PARENT_NOT_PASS')
 r=evaluate(load_price(a.price_root,start,end),load_funding(a.funding_root,start,end),start,end,a.stage);r.update({'schema_version':'zel.edge_factory_v2.funding_unwind16_f2.v1','source':{'price_dataset_sha256':PRICE_SHA,'funding_dataset_sha256':FUNDING_SHA,'T1_rows_read':0},'contract':{'universe_size':16,'current_funding_score_only':True,'holding_hours':8,'long_count':4,'short_count':4,'leg_abs_weight':LEG_WEIGHT,'normal_roundtrip_bps':NORMAL_COST,'stress_roundtrip_bps':STRESS_COST,'rule_search_count':0},'AI_used':False,'survivor_declared':False,'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED','action':'hold','next':('RUN_IDENTICAL_V1' if a.stage=='D1' and r['pass'] else 'FREEZE_T1_AND_AI_RED_TEAM' if a.stage=='V1' and r['pass'] else 'DROP_FUNDING_UNWIND16_FAMILY')});r['receipt_sha256']=stable(r);a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(r,indent=2,sort_keys=True,allow_nan=False)+'\n');print(json.dumps({'stage':a.stage,'state':r['state'],'portfolio':r['portfolio'],'price_component':r['price_component'],'funding_component':r['funding_component'],'normal_total':r['normal_total'],'stress_total':r['stress_total'],'gate':r['gate'],'receipt_sha256':r['receipt_sha256']},sort_keys=True));return 0
if __name__=='__main__':raise SystemExit(main())
