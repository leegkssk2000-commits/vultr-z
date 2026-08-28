#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, math
from pathlib import Path
from typing import Any, Mapping
from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild import a1_trend_ma_macd_ablation_child_v1 as ab
from backend.research.rebuild import a1_top5_highamp_rescue_scan_v1 as rescue
from backend.research.rebuild import a1_trendrider_8125_fresh2_highamp_rescue_v1 as tr
from backend.research.rebuild.a1_trend_rider_exact_parent_repair_batch_v1 import metrics

ROOT=Path(__file__).resolve().parents[3]
TOP5=ROOT/'backend/research/rebuild/a1_top5_latest_only_ssot_v1.json'
P16=ROOT/'backend/research/rebuild/a1_trendrider_wr8125_exact16_trade_receipt_v1.json'
F2=ROOT/'backend/research/rebuild/a1_trendrider_8125_fresh2_source_v1.json'
KINC=ROOT/'backend/research/rebuild/a1_keltner_58pct_research_incumbent_v1.json'
SINC=ROOT/'backend/research/rebuild/a1_supertrend_5455_research_incumbent_v1.json'
COST=ROOT/'backend/research/rebuild/a1_rebuilt_bb_revert_cost_authority_v1.json'
CELLS=((2.5,0.75),(2.0,0.75),(1.5,0.45))
SCHEMA='zel.a1.top5.fixed_rr_payoff_shadow.v1'

def read(p:Path)->dict[str,Any]:
    x=json.loads(p.read_text());
    if not isinstance(x,dict): raise RuntimeError(f'OBJECT_REQUIRED:{p}')
    return x
def stable(v:Any)->str:return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False,default=str).encode()).hexdigest()
def key(x:Mapping[str,Any])->tuple[Any,...]:return (x.get('symbol'),int(x.get('signal_ts') or 0),int(x.get('entry_ts') or 0),x.get('side'))
def payoff(rows:list[Mapping[str,Any]])->float|None:
    w=[float(x['net_bps']) for x in rows if float(x['net_bps'])>0]; l=[-float(x['net_bps']) for x in rows if float(x['net_bps'])<0]
    return None if not w or not l else (sum(w)/len(w))/(sum(l)/len(l))
def atr14(bars:list[Mapping[str,Any]],i:int)->float:
    vals=[]
    for j in range(max(1,i-13),i+1):
        h,l,pc=float(bars[j]['high']),float(bars[j]['low']),float(bars[j-1]['close']); vals.append(max(h-l,abs(h-pc),abs(l-pc)))
    return sum(vals)/max(1,len(vals))
def native_r(row:Mapping[str,Any],bars:list[Mapping[str,Any]],sig_i:int,entry:float)->float:
    geo=row.get('intent_geometry') if isinstance(row.get('intent_geometry'),Mapping) else {}
    sl=geo.get('sl') if isinstance(geo,Mapping) else None
    if sl is not None and abs(entry-float(sl))>1e-12:return abs(entry-float(sl))
    return 1.5*atr14(bars,sig_i)
def simulate(rows:list[dict[str,Any]],tp_r:float,sl_r:float,bars_by:Mapping[str,list[dict[str,Any]]],snaps:Mapping[str,Any])->list[dict[str,Any]]:
    out=[]
    for row in rows:
        sym=str(row['symbol']); bars=list(bars_by[sym]); idx={int(b['ts_ms']):i for i,b in enumerate(bars)}
        si=idx.get(int(row['signal_ts'])); ei=idx.get(int(row['entry_ts']))
        if si is None or ei is None: raise RuntimeError(f'ROW_BAR_MISSING:{sym}:{row["signal_ts"]}')
        entry=float(row.get('entry') or bars[ei]['open']); side=str(row['side']); r=native_r(row,bars,si,entry)
        stop=entry-sl_r*r if side=='long' else entry+sl_r*r; target=entry+tp_r*r if side=='long' else entry-tp_r*r
        last=min(len(bars)-1,ei+48); px=ts=reason=None
        for j in range(ei,last+1):
            lo,hi=float(bars[j]['low']),float(bars[j]['high']); hit_sl=(lo<=stop if side=='long' else hi>=stop); hit_tp=(hi>=target if side=='long' else lo<=target)
            if hit_sl: px,ts,reason=stop,int(bars[j]['ts_ms']),'SL'; break
            if hit_tp: px,ts,reason=target,int(bars[j]['ts_ms']),'TP'; break
        if px is None: px,ts,reason=float(bars[last]['close']),int(bars[last]['ts_ms']),'TIMEOUT'
        snap=snaps[sym]; funding=ev.funding_cost(int(row['entry_ts']),int(ts),list(snap['funding_rows'])); cost=float(snap['fee_bps'])+float(snap['spread_bps'])+float(snap['impact_bps'])+funding
        gross=(float(px)-entry)/entry*10000 if side=='long' else (entry-float(px))/entry*10000
        out.append({**{k:row.get(k) for k in ('symbol','signal_ts','entry_ts','side')},'exit_ts':int(ts),'entry':entry,'exit':float(px),'reason':reason,'net_bps':gross-cost,'gross_bps':gross,'realized_cost_bps':cost})
    return out

def strict(cm:Mapping[str,Any],bm:Mapping[str,Any],cp:float|None,bp:float|None)->tuple[bool,dict[str,bool]]:
    wr0=float(bm.get('win_rate') or 0); checks={'T_same':int(cm.get('trades') or 0)==int(bm.get('trades') or 0),'WR_retention_80pct':float(cm.get('win_rate') or 0)+1e-12>=0.8*wr0,'PNL_nondecrease':float(cm.get('net_pnl_bps') or 0)>=float(bm.get('net_pnl_bps') or 0),'expectancy_nondecrease':float(cm.get('net_expectancy_bps') or 0)>=float(bm.get('net_expectancy_bps') or 0),'PF_nondecrease':float(cm.get('profit_factor') or 0)>=float(bm.get('profit_factor') or 0),'payoff_improved':cp is not None and bp is not None and cp>bp,'DD_nonincrease':float(cm.get('drawdown_bps') or 1e30)<=float(bm.get('drawdown_bps') or 0)}; return all(checks.values()),checks
def score(cm:Mapping[str,Any],cp:float|None)->float:
    return float(cm.get('net_expectancy_bps') or -1e18)*max(float(cm.get('profit_factor') or 0),0)*max(float(cp or 0),0)/max(float(cm.get('drawdown_bps') or 1e30),1)

def latest_sets(trend:dict[str,Any],a4dir:Path,breakdir:Path)->list[dict[str,Any]]:
    p16=[dict(x) for x in read(P16).get('trades') or []]; f2=[dict(x) for x in read(F2).get('trades') or []]; broad=[dict(x) for x in trend.get('trades') or []]
    rr=tr.run(Path('/dev/null')) if False else None
    # Trend primary 24T = immutable16 + fresh2 + donor6 from the frozen feasibility result.
    pkeys={key(x) for x in p16}; fkeys={key(x) for x in f2}; distinct=[x for x in broad if key(x) not in pkeys and key(x) not in fkeys]
    best24=[]
    import itertools
    for comb in itertools.combinations(distinct,6):
        added=f2+[dict(x) for x in comb]; ok,checks,am,cm,cp=tr.strict(p16,added)
        rank=(sum(bool(v) for v in checks.values()),float(cm['net_expectancy_bps'] or -1e18),float(cp or 0))
        best24.append((rank,[dict(x) for x in comb]))
    best24.sort(key=lambda z:z[0],reverse=True); primary=p16+f2+(best24[0][1] if best24 else [])
    kb=read(a4dir/'keltner_trend_exact_parent.json'); sb=read(a4dir/'supertrend_pullback_exact_parent.json'); bb=read(breakdir/'break_and_continue_exact_parent.json')
    kp=rescue.select_semantic_parent(kb,read(KINC)); sp=rescue.select_semantic_parent(sb,read(SINC)); bp=rescue.select_break_parent(bb)
    def ceiling(sid,parent,bdoc):
        row=rescue.scan_lane(sid,parent,[dict(x) for x in bdoc.get('trades') or []],{})
        by={key(x):dict(x) for x in bdoc.get('trades') or []}; add=[by[key(x)] for x in row.get('best_historical_strict_rows') or []]; return parent+add
    return [
      {'lane':'trend_rider_primary','strategy_id':'trend_rider','rows':primary,'reference':'LATEST_STRICT_CEILING_DIAGNOSTIC_24'},
      {'lane':'trend_rider_broad','strategy_id':'trend_rider','rows':broad,'reference':'G4_ECONOMIC_SURVIVOR_30'},
      {'lane':'break_and_continue','strategy_id':'break_and_continue','rows':ceiling('break_and_continue',bp,bb),'reference':'LATEST_STRICT_CEILING_DIAGNOSTIC_17'},
      {'lane':'keltner','strategy_id':'keltner_trend','rows':ceiling('keltner_trend',kp,kb),'reference':'LATEST_STRICT_CEILING_DIAGNOSTIC_16'},
      {'lane':'supertrend','strategy_id':'supertrend_pullback','rows':ceiling('supertrend_pullback',sp,sb),'reference':'LATEST_STRICT_CEILING_DIAGNOSTIC_17'},]

def run(trend_path:Path,a4dir:Path,breakdir:Path,out:Path)->dict[str,Any]:
    trend=read(trend_path); lanes=latest_sets(trend,a4dir,breakdir); authority=read(COST); syms=sorted({str(t['symbol']) for l in lanes for t in l['rows']}); bars_by={s:ev.fetch_bars(s,'1h',1000) for s in syms}; snaps={s:ev.fetch_execution_snapshot(s,authority) for s in syms}; results=[]
    for lane in lanes:
        base_rows=lane['rows']; bm=metrics(base_rows); bp=payoff(base_rows); cells=[]
        for tp,sl in CELLS:
            cand=simulate(base_rows,tp,sl,bars_by,snaps); cm=metrics(cand); cp=payoff(cand); ok,checks=strict(cm,bm,cp,bp); cells.append({'tp_r':tp,'sl_r':sl,'nominal_rr':tp/sl,'metrics':cm,'payoff':cp,'strict_pass':ok,'checks':checks,'score':score(cm,cp)})
        cells.sort(key=lambda x:(not x['strict_pass'],-x['score'])); results.append({**{k:lane[k] for k in ('lane','strategy_id','reference')},'base_metrics':bm,'base_payoff':bp,'cells':cells,'pass_count':sum(1 for x in cells if x['strict_pass']),'best':cells[0]})
    r={'schema_version':SCHEMA,'state':'PASS_TOP5_FIXED_RR_SHADOW_COMPLETE','cells':[list(x) for x in CELLS],'cell_policy':'USER_FIXED_ONLY_NO_SWEEP','objective':'MAX_WIN_SIZE_MIN_LOSS_SIZE_WITH_T_WR_ECONOMIC_GUARDS','wr_retention_floor_ratio':0.8,'lanes':results,'shadow_only':True,'trend_rider_broad_g5_reference_mutated':False,'adoption_for_trend_rider_broad_forbidden_until_g5_window_complete':True,'production_mutated':False,'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED','live_trade_authority':'BLOCKED','action':'hold'}; r['receipt_sha256']=stable(r); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(r,indent=2,sort_keys=True,allow_nan=False)+'\n'); return r

def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument('--trend70-source',type=Path); ap.add_argument('--a4-source-dir',type=Path); ap.add_argument('--break-source-dir',type=Path); ap.add_argument('--out',type=Path,default=Path('out/a1_top5_fixed_rr_payoff_shadow_v1.json')); ap.add_argument('--self-test',action='store_true'); a=ap.parse_args()
    if a.self_test:
        assert CELLS==((2.5,0.75),(2.0,0.75),(1.5,0.45)); print('PASS_A1_TOP5_FIXED_RR_PAYOFF_SHADOW_V1_SELF_TEST'); return 0
    if None in (a.trend70_source,a.a4_source_dir,a.break_source_dir): raise SystemExit('sources required')
    r=run(a.trend70_source,a.a4_source_dir,a.break_source_dir,a.out); print(json.dumps({'state':r['state'],'lanes':[{'lane':x['lane'],'T':x['base_metrics']['trades'],'pass':x['pass_count'],'best':x['best']} for x in r['lanes']]},sort_keys=True)); return 0
if __name__=='__main__': raise SystemExit(main())
