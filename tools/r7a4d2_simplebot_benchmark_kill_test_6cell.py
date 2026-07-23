#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, importlib.util, json, math, os, statistics, tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd

SIDE_SUMMARY=Path('runtime/r7a4d2_incremental_defect4_ma5_side_specialization_6/ma5_side_specialization_summary_v1.json')
SIDE_TRADES=Path('runtime/r7a4d2_incremental_defect4_ma5_side_specialization_6/ma5_long_only_child_trade_rows_v1.jsonl')
MANIFEST=Path('runtime/r7a4c_historical_simulation_input_lineage/selected_input_manifest_v1.json')
CONTRACT=Path('backend/contracts/ZOS_R7A4D_HISTORICAL_SIMULATION_3600_v1.json')
OUT=Path('runtime/r7a4d2_simplebot_benchmark_kill_test_6cell')
SIDE_SUMMARY_SHA='768609606083497a7a6b1a590ea5182094c44a470ffcdd8acec338eaaeeeaf3d'
SIDE_TRADES_SHA='f5d8dc8c64cd7ee66d354231715d00d81c0c62a72c3faf82523c28e564e564f7'
BENCH={
 'benchmark_ema_cross_long':{'family':'trend','fast':12,'slow':26,'stop':1.5,'target':2.0,'hold':48},
 'benchmark_donchian_breakout_long':{'family':'breakout','lookback':20,'stop':1.25,'target':2.0,'hold':36},
 'benchmark_atr_volatility_breakout_long':{'family':'volatility_breakout','range_atr':1.25,'volume_z':.5,'stop':1.25,'target':2.5,'hold':30},
 'benchmark_vwap_mean_reversion_long':{'family':'mean_reversion','lookback':20,'entry_std':1.25,'stop':.75,'hold':18},
 'benchmark_single_cycle_grid_long':{'family':'grid','lookback':30,'lower_q':.25,'stop':.5,'hold':30},
}
EPS=1e-12

def mod(path:Path,name:str):
 spec=importlib.util.spec_from_file_location(name,path); m=importlib.util.module_from_spec(spec); assert spec and spec.loader; spec.loader.exec_module(m); return m

def load(path:Path):
 v=json.loads(path.read_text()); return v if isinstance(v,dict) else {}

def loadl(path:Path): return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]
def sha(path:Path):
 h=hashlib.sha256();
 with path.open('rb') as f:
  for c in iter(lambda:f.read(1<<20),b''): h.update(c)
 return h.hexdigest()
def snap(paths): return {str(p):sha(p) if p.is_file() and not p.is_symlink() else None for p in paths}
def atom(path:Path,obj):
 path.parent.mkdir(parents=True,exist_ok=True)
 with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=path.parent,delete=False) as f: json.dump(obj,f,ensure_ascii=False,sort_keys=True,indent=2); f.write('\n'); t=Path(f.name)
 os.replace(t,path)
def atoml(path:Path,rows):
 lines=[json.dumps(r,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n' for r in rows]; path.parent.mkdir(parents=True,exist_ok=True)
 with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=path.parent,delete=False) as f: f.writelines(lines); t=Path(f.name)
 os.replace(t,path); return len(lines),hashlib.sha256(''.join(lines).encode()).hexdigest()
def f(v,d=0.):
 try: x=float(v); return x if math.isfinite(x) else d
 except: return d

def signals(bid,frame,mask,H):
 p=BENCH[bid]; c=frame.close.astype(float); o=frame.open.astype(float); hi=frame.high.astype(float); lo=frame.low.astype(float); vol=frame.volume.astype(float); a=H.atr(frame,14); out=[]
 def add(i,stop,target,hold,why):
  if i+1>=len(frame) or not bool(mask.iloc[i]) or not bool(mask.iloc[i+1]): return
  e=float(frame.iloc[i+1].open)
  if all(math.isfinite(x) for x in (e,stop,target)) and 0<stop<e<target: out.append({'signal_bar_index':i,'entry_bar_index':i+1,'stop_price':float(stop),'target_price':float(target),'timeout_bars':max(2,int(hold)),'reason':why})
 if bid=='benchmark_ema_cross_long':
  fast=H.ema(c,p['fast']); slow=H.ema(c,p['slow']); up=(fast>slow)&(fast.shift(1)<=slow.shift(1))&(c>slow); down=(fast<slow)&(fast.shift(1)>=slow.shift(1))
  for x in np.flatnonzero(H.edge_trigger(up).to_numpy(bool)):
   i=int(x); z=f(a.iloc[i],math.nan); add(i,min(float(lo.iloc[i]),float(c.iloc[i])-p['stop']*z),float(c.iloc[i])+p['target']*z,H.next_true_distance(down,i,p['hold']),'ema_12_26_up_cross')
 elif bid=='benchmark_donchian_breakout_long':
  n=p['lookback']; ph=hi.shift(1).rolling(n,min_periods=n).max(); pl=lo.shift(1).rolling(n,min_periods=n).min(); mid=(ph+pl)/2; br=c>ph; fail=c<mid
  for x in np.flatnonzero(H.edge_trigger(br).to_numpy(bool)):
   i=int(x); z=f(a.iloc[i],math.nan); add(i,float(c.iloc[i])-p['stop']*z,float(c.iloc[i])+p['target']*z,H.next_true_distance(fail,i,p['hold']),'donchian_20_up_break')
 elif bid=='benchmark_atr_volatility_breakout_long':
  rng=hi-lo; vm=vol.rolling(20,min_periods=20).mean(); vs=vol.rolling(20,min_periods=20).std(ddof=0).replace(0,np.nan); vz=(vol-vm)/vs; br=(c>o)&(rng>=p['range_atr']*a)&(vz>=p['volume_z'])&(c>=hi.shift(1).rolling(10,min_periods=10).max())
  for x in np.flatnonzero(H.edge_trigger(br).to_numpy(bool)):
   i=int(x); z=f(a.iloc[i],math.nan); add(i,min(float(lo.iloc[i]),float(c.iloc[i])-p['stop']*z),float(c.iloc[i])+p['target']*z,p['hold'],'atr_volume_up_break')
 elif bid=='benchmark_vwap_mean_reversion_long':
  n=p['lookback']; vw=H.rolling_vwap(frame,n); dev=c-vw; sd=dev.rolling(n,min_periods=n).std(ddof=0); lower=vw-p['entry_std']*sd; q=(lo<lower)&(c>lower)&(c>o)
  for x in np.flatnonzero(H.edge_trigger(q).to_numpy(bool)):
   i=int(x); z=f(a.iloc[i],math.nan); add(i,min(float(lo.iloc[i]),float(c.iloc[i])-p['stop']*z),f(vw.iloc[i],math.nan),p['hold'],'vwap_lower_excursion_close_inside')
 else:
  n=p['lookback']; rh=hi.shift(1).rolling(n,min_periods=n).max(); rl=lo.shift(1).rolling(n,min_periods=n).min(); width=rh-rl; lower=rl+p['lower_q']*width; mid=(rh+rl)/2; q=width.between(2*a,8*a)&(lo<=lower)&(c>o)&(c>lower)
  for x in np.flatnonzero(H.edge_trigger(q).to_numpy(bool)):
   i=int(x); z=f(a.iloc[i],math.nan); add(i,min(float(rl.iloc[i])-p['stop']*z,float(lo.iloc[i])-.1*z),f(mid.iloc[i],math.nan),p['hold'],'single_cycle_lower_quartile_grid')
 return out

def trade(frame,mask,s,cost,timing):
 delay=int(cost.get('latency_bars',0))+int(timing.get('additional_entry_delay_bars',0)); xd=int(cost.get('latency_bars',0))+int(timing.get('additional_exit_delay_bars',0)); ei=int(s['entry_bar_index'])+delay; measured=np.flatnonzero(mask.to_numpy(bool))
 if not len(measured): return None
 last=int(measured[-1])
 if ei>=len(frame) or ei>last or not bool(mask.iloc[ei]): return None
 entry=float(frame.iloc[ei].open); stop=float(s['stop_price']); target=float(s['target_price'])
 if not 0<stop<entry<target:return None
 risk=(entry-stop)/entry*100; timeout=min(ei+int(s['timeout_bars']),last); reason='segment_end'; ti=last; ref=float(frame.iloc[last].close)
 for i in range(ei,last+1):
  h=float(frame.iloc[i].high); l=float(frame.iloc[i].low)
  if l<=stop: reason='stop';ti=i;ref=stop;break
  if h>=target: reason='take_profit';ti=i;ref=target;break
  if i>=timeout: reason='rule_exit_or_timeout';ti=i;ref=float(frame.iloc[i].close);break
 xi=min(ti+xd,last); exitp=ref if xd==0 and reason in {'stop','take_profit'} else float(frame.iloc[xi].close if reason=='segment_end' else frame.iloc[xi].open); gross=(exitp-entry)/entry*100; rt=2*(f(cost.get('fee_bps_per_side'))+f(cost.get('slippage_bps_per_side')))/100; hold=max(xi-ei,0); fund=f(cost.get('funding_bps_per_8h'))/100*(hold*5/60)/8; net=gross-rt-fund; path=frame.iloc[ei:xi+1]
 return {'entry_index':ei,'exit_index':xi,'entry_price':entry,'exit_price':exitp,'stop_price':stop,'target_price':target,'risk_pct':risk,'gross_return_pct':gross,'round_trip_cost_pct':rt,'funding_cost_pct':fund,'net_return_pct':net,'net_r':net/risk,'exit_reason':reason,'holding_bars':hold,'mfe_pct':max(float(path.high.max())-entry,0)/entry*100,'mae_pct':max(entry-float(path.low.min()),0)/entry*100}

def metrics(rows):
 rows=sorted(rows,key=lambda r:(int(r.get('fold',-1)),str(r.get('segment_id','')),int(r.get('entry_index',-1)),str(r.get('timing_id','')))); vals=[f(r.get('net_r')) for r in rows]; pnl=[f(r.get('net_return_pct')) for r in rows]; win=[x for x in vals if x>0]; loss=[-x for x in vals if x<0]; folds=defaultdict(float); er=pr=dd=ep=pp=dp=0.
 for r,v,p in zip(rows,vals,pnl): folds[int(r.get('fold',-1))]+=v;er+=v;pr=max(pr,er);dd=max(dd,pr-er);ep+=p;pp=max(pp,ep);dp=max(dp,pp-ep)
 gp=sum(win);gl=sum(loss); unique={(r.get('segment_id'),r.get('entry_index'),r.get('signal_reason')) for r in rows}
 return {'trade_count':len(rows),'unique_event_count':len(unique),'symbol_count':len({r.get('symbol') for r in rows}),'fold_count':len(folds),'positive_fold_count':sum(v>0 for v in folds.values()),'win_count':len(win),'loss_count':len(loss),'win_rate_pct':len(win)/len(rows)*100 if rows else 0.,'net_r_sum':sum(vals),'net_pnl_sum_pct':sum(pnl),'expectancy_r':statistics.mean(vals) if vals else 0.,'profit_factor':gp/gl if gl>EPS else (math.inf if gp>0 else 0.),'max_drawdown_r':dd,'max_drawdown_pct':dp,'fold_net_r':{str(k):v for k,v in sorted(folds.items())},'symbol_histogram':dict(sorted(Counter(str(r.get('symbol','')) for r in rows).items())),'regime_histogram':dict(sorted(Counter(str(r.get('regime','')) for r in rows).items()))}
def corr(a,b):
 x=[f(a.get(str(i))) for i in range(6)];y=[f(b.get(str(i))) for i in range(6)];return None if statistics.pstdev(x)<=EPS or statistics.pstdev(y)<=EPS else float(np.corrcoef(x,y)[0,1])
def dominates(x,m):
 checks=[x['net_r_sum']>=m['net_r_sum']-EPS,x['net_pnl_sum_pct']>=m['net_pnl_sum_pct']-EPS,x['profit_factor']>=m['profit_factor']-EPS,x['positive_fold_count']>=m['positive_fold_count'],x['max_drawdown_r']<=m['max_drawdown_r']+EPS,x['expectancy_r']>=m['expectancy_r']-EPS]; strict=[a>b+EPS for a,b in [(x['net_r_sum'],m['net_r_sum']),(x['net_pnl_sum_pct'],m['net_pnl_sum_pct']),(x['profit_factor'],m['profit_factor']),(x['expectancy_r'],m['expectancy_r'])]]+[x['positive_fold_count']>m['positive_fold_count'],x['max_drawdown_r']<m['max_drawdown_r']-EPS]
 return x['trade_count']>=24 and x['symbol_count']>=3 and all(checks) and sum(strict)>=2

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--root',default='/home/z/z');ap.add_argument('--target-sha',default='UNKNOWN');ap.add_argument('--raw-module',required=True);ap.add_argument('--helper-module',required=True);a=ap.parse_args();root=Path(a.root).resolve();R=mod(Path(a.raw_module),'raw');H=mod(Path(a.helper_module),'helper'); req=[root/SIDE_SUMMARY,root/SIDE_TRADES,root/MANIFEST,root/CONTRACT]; missing=[str(p) for p in req if not p.is_file()]
 if missing: print('STATE=HOLD_SIMPLEBOT_BENCHMARK_KILL_TEST_6CELL_INPUT');print('BLOCKERS='+json.dumps(['MISSING:'+','.join(missing)]));print('RC=2');return 2
 ss,st,man,con=load(req[0]),loadl(req[1]),load(req[2]),load(req[3]);block=[]
 if sha(req[0])!=SIDE_SUMMARY_SHA or sha(req[1])!=SIDE_TRADES_SHA:block.append('MA5_SIDE_HASH_MISMATCH')
 if ss.get('state')!='PASS_INCREMENTAL_DEFECT4_MA5_SIDE_SPECIALIZATION_6' or not (ss.get('pass_checks') or {}).get('repair_pass'):block.append('MA5_SIDE_NOT_PASS')
 if len(st)!=78 or {r.get('side') for r in st}!={'long'}:block.append('MA5_ROWS_INVALID')
 seg={str(r['segment_id']):r for r in man.get('selected_segments',[]) if isinstance(r,dict)};costs=[x for x in con.get('cost_profiles',[]) if isinstance(x,dict)];times=[x for x in con.get('perturbations',[]) if isinstance(x,dict)]
 if man.get('state')!='PASS' or len(seg)!=24:block.append('MANIFEST_INVALID')
 if len(costs)*len(times)!=6:block.append('STRESS_INVALID')
 if block:print('STATE=HOLD_SIMPLEBOT_BENCHMARK_KILL_TEST_6CELL_INPUT');print('BLOCKERS='+json.dumps(block));print('RC=2');return 2
 srcsha={str(x['source_path']):str(x.get('source_sha256','')) for x in seg.values()}; paths=req+[root/R.safe_repo_path(str(x['source_path'])) for x in seg.values()]; protected=[Path(str(x)) for x in con.get('protected_paths',[])]; before=snap(paths+protected);sc={};fc={};mc={};sg={};trades=[];cells=[]
 for bid,p in BENCH.items():
  for sid,s in sorted(seg.items()):
   sp=str(s['source_path'])
   if sp not in sc: sc[sp]=R.fixed_ohlcv_frame(root/R.safe_repo_path(sp),srcsha[sp])
   if sid not in fc:
    fc[sid]=R.resample_for_segment(sc[sp],int(s['start_row']),int(s['end_row_exclusive']),'5m');mc[sid]=R.measurement_mask(fc[sid],int(s['start_row']),int(s['end_row_exclusive']))
   sg[(bid,sid)]=signals(bid,fc[sid],mc[sid],H)
  for ci,cost in enumerate(costs):
   for ti,tim in enumerate(times):
    cr=[]
    for sid,s in sorted(seg.items()):
     last=-1
     for q in sg[(bid,sid)]:
      if int(q['entry_bar_index'])<=last:continue
      z=trade(fc[sid],mc[sid],q,cost,tim)
      if z is None:continue
      last=int(z['exit_index']);z.update({'lane_id':bid+':5m','benchmark_id':bid,'family':p['family'],'cost_profile_id':str(cost['id']),'timing_id':f'timing_{ti}','segment_id':sid,'fold':int(s['fold']),'regime':str(s['regime']),'symbol':str(s['symbol']),'side':'long','signal_reason':q['reason']});trades.append(z);cr.append(z)
    cells.append({'benchmark_id':bid,'family':p['family'],'cost_profile_id':str(cost['id']),'timing_id':f'timing_{ti}',**metrics(cr)})
 ma5cells=[{'benchmark_id':'ma5_long_only_side_specialization','family':'zel_ma5','cost_profile_id':cp,'timing_id':ti,**metrics([r for r in st if r.get('cost_profile_id')==cp and r.get('timing_id')==ti])} for cp in [f'cost_profile_{i}' for i in range(3)] for ti in [f'timing_{i}' for i in range(2)]];msev=metrics([r for r in st if r.get('cost_profile_id')=='cost_profile_2']);mworst=next(x for x in ma5cells if x['cost_profile_id']=='cost_profile_2' and x['timing_id']=='timing_1');lanes=[]
 for bid,p in BENCH.items():
  sev=metrics([r for r in trades if r['benchmark_id']==bid and r['cost_profile_id']=='cost_profile_2']);worst=next(x for x in cells if x['benchmark_id']==bid and x['cost_profile_id']=='cost_profile_2' and x['timing_id']=='timing_1');lanes.append({'benchmark_id':bid,'family':p['family'],'parameters':p,'positive_stress_cell_count':sum(1 for x in cells if x['benchmark_id']==bid and x['net_r_sum']>0 and x['profit_factor']>1 and x['expectancy_r']>0),'severe_profile_metrics':sev,'worst_severe_cell_metrics':worst,'dominates_ma5':dominates(sev,msev),'severe_fold_correlation_to_ma5':corr(sev['fold_net_r'],msev['fold_net_r'])})
 dom=[x for x in lanes if x['dominates_ma5']];cls='RETIRE_STANDALONE_MA5' if msev['net_r_sum']<=0 or msev['profit_factor']<=1 or msev['positive_fold_count']<4 else ('RETIRE_STANDALONE_MA5_SIMPLEBOTS_DOMINATE' if len(dom)>=2 else ('RETIRE_STANDALONE_MA5_REDUNDANT' if len(dom)==1 and f(dom[0]['severe_fold_correlation_to_ma5'],-2)>=.8 else ('MA5_COMPLEMENTARY_OOS_ONLY' if len(dom)==1 else 'MA5_CONTINUE_INDEPENDENT_OOS')));nxt={'MA5_CONTINUE_INDEPENDENT_OOS':'R7.A4D2_MA5_INDEPENDENT_OOS_EXPANSION','MA5_COMPLEMENTARY_OOS_ONLY':'R7.A4D2_MA5_COMPLEMENTARITY_OOS_AUDIT','RETIRE_STANDALONE_MA5':'R7.A4D2_MA5_OBSERVER_MATERIAL_RECLASSIFY','RETIRE_STANDALONE_MA5_SIMPLEBOTS_DOMINATE':'R7.A4D2_MA5_OBSERVER_MATERIAL_RECLASSIFY','RETIRE_STANDALONE_MA5_REDUNDANT':'R7.A4D2_MA5_OBSERVER_MATERIAL_RECLASSIFY'}[cls];mut=[p for p,v in before.items() if snap([Path(p)])[p]!=v]
 if mut:block.append('INPUT_MUTATION:'+','.join(mut))
 state='PASS_SIMPLEBOT_BENCHMARK_KILL_TEST_6CELL' if not block else 'HOLD_SIMPLEBOT_BENCHMARK_KILL_TEST_6CELL';out=root/OUT;out.mkdir(parents=True,exist_ok=True);tc,tsh=atoml(out/'simplebot_benchmark_trade_rows_v1.jsonl',trades);cc,csh=atoml(out/'simplebot_benchmark_cell_rows_v1.jsonl',cells+ma5cells);result={'schema':'r7a4d2_simplebot_benchmark_kill_test_6cell_v1','state':state,'target_commit':a.target_sha,'blocker_count':len(block),'blockers':block,'benchmark_count':len(BENCH),'benchmark_cell_count':len(cells),'benchmark_trade_count':tc,'ma5_severe_profile_metrics':msev,'ma5_worst_severe_cell_metrics':mworst,'benchmark_lane_rows':lanes,'strict_dominating_simplebots':[x['benchmark_id'] for x in dom],'ma5_classification':cls,'input_mutation_count':len(mut),'trade_sha256':tsh,'cell_sha256':csh,'strategy_mutation_allowed':False,'registry_mutation_allowed':False,'router_mutation_allowed':False,'service_mutation_allowed':False,'shadow_start_allowed':False,'paper_live_order_allowed':False,'next_stage':nxt if not block else 'R7.A4D2_SIMPLEBOT_BENCHMARK_DIAGNOSE'};atom(out/'simplebot_benchmark_kill_test_summary_v1.json',result)
 print('STATE='+state);print('BLOCKER_COUNT='+str(len(block)));print('BENCHMARK_CELL_COUNT='+str(len(cells)));print(f"MA5_SEVERE_PROFILE_NET_R={msev['net_r_sum']:.12f}");print(f"MA5_SEVERE_PROFILE_PF={msev['profit_factor']:.12f}");print(f"MA5_WORST_SEVERE_CELL_NET_R={mworst['net_r_sum']:.12f}")
 for x in lanes:
  m=x['severe_profile_metrics'];w=x['worst_severe_cell_metrics'];print(f"SIMPLEBOT={x['benchmark_id']}|ROWS={m['trade_count']}|NET_R={m['net_r_sum']:.12f}|PF={m['profit_factor']:.12f}|DD_R={m['max_drawdown_r']:.12f}|POS_FOLDS={m['positive_fold_count']}/6|WORST_CELL={w['net_r_sum']:.12f}|DOMINATES_MA5={str(x['dominates_ma5']).lower()}")
 print('MA5_CLASSIFICATION='+cls);print('NEXT_STAGE='+result['next_stage']);print('SUMMARY_JSON='+str(out/'simplebot_benchmark_kill_test_summary_v1.json'));print('BLOCKERS='+json.dumps(block));print('RC='+('0' if not block else '2'));return 0 if not block else 2
if __name__=='__main__':raise SystemExit(main())
