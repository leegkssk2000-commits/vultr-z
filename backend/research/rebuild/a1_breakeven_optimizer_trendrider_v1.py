#!/usr/bin/env python3
from __future__ import annotations

import argparse, hashlib, json, math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_rr_exit_optimizer_trendrider_v1 as rr_opt
from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild import a1_top5_fixed_rr_payoff_shadow_v1 as rr

ROOT = Path(__file__).resolve().parents[3]
PREV = ROOT / 'backend/research/prep/time_stop_optimizer_latest.json'
OUT_DEFAULT = Path('out/breakeven_optimizer.json')
SCHEMA = 'zel.exit_optimizer.trendrider.breakeven.v1'
FAMILY = 'BREAKEVEN'
SOURCE_ARTIFACT_ID = 9446790894
CONTROL_TIMEOUT_BARS = 48
MAX_CANDIDATES = 12
REQUIRED_T = 25


def read(p: Path) -> dict[str, Any]:
    x = json.loads(p.read_text())
    if not isinstance(x, dict): raise RuntimeError(f'OBJECT_REQUIRED:{p}')
    return x


def stable(v: Any) -> str:
    return hashlib.sha256(json.dumps(v, sort_keys=True, separators=(',', ':'), allow_nan=False, default=str).encode()).hexdigest()


def q(xs: list[float], p: float) -> float:
    ys = sorted(float(x) for x in xs)
    if not ys: raise RuntimeError('EMPTY_QUANTILE')
    i = (len(ys)-1)*p; lo, hi = int(math.floor(i)), int(math.ceil(i))
    if lo == hi: return ys[lo]
    w = i-lo
    return ys[lo]*(1-w)+ys[hi]*w


def one_r(row: Mapping[str, Any], bars: list[dict[str, Any]]) -> tuple[float,float,int,int]:
    idx = {int(b['ts_ms']): i for i,b in enumerate(bars)}
    si, ei = idx.get(int(row['signal_ts'])), idx.get(int(row['entry_ts']))
    if si is None or ei is None: raise RuntimeError(f'ROW_BAR_MISSING:{row.get("symbol")}')
    entry = float(row.get('entry') or bars[ei]['open'])
    r = rr.native_r(row, bars, si, entry)
    if r <= 0: raise RuntimeError('NONPOSITIVE_NATIVE_R')
    return entry, float(r), si, ei


def search_space(rows: list[dict[str, Any]], bars_by: Mapping[str,list[dict[str,Any]]], snaps: Mapping[str,Any]) -> tuple[list[tuple[float,float]],dict[str,Any]]:
    mfe_r=[]; cost_r=[]
    for row in rows:
        sym=str(row['symbol']); bars=list(bars_by[sym]); entry,r,_,ei=one_r(row,bars)
        last=min(len(bars)-1, ei+CONTROL_TIMEOUT_BARS); side=str(row['side']); mfe=0.0
        for j in range(ei,last+1):
            if side=='long': mfe=max(mfe,float(bars[j]['high'])-entry)
            else: mfe=max(mfe,entry-float(bars[j]['low']))
        mfe_r.append(max(0.0,mfe/r))
        snap=snaps[sym]
        base_bps=float(snap['fee_bps'])+float(snap['spread_bps'])+float(snap['impact_bps'])
        r_bps=(r/entry)*10000.0
        if r_bps>0: cost_r.append(base_bps/r_bps)
    pos=[x for x in mfe_r if x>0]
    trigs=sorted({round(max(0.20,min(3.0,q(pos,p))),3) for p in (0.25,0.40,0.55,0.70,0.82,0.90)})
    offs=sorted({0.0, round(max(0.0,min(0.25,q(cost_r,0.50))),3) if cost_r else 0.0})
    pairs=[]
    for t in trigs:
        for o in offs:
            if o < t: pairs.append((t,o))
    pairs=pairs[:MAX_CANDIDATES]
    return pairs, {'method':'DEVELOPMENT_ONLY_MFE_AND_EXECUTION_COST_R_QUANTILES','mfe_r_quantiles':{str(p):q(pos,p) for p in (0.25,0.50,0.75,0.90,0.95)},'cost_r_quantiles':({str(p):q(cost_r,p) for p in (0.50,0.75,0.90)} if cost_r else {}),'trigger_candidates':trigs,'offset_candidates':offs,'candidate_pairs':[{'trigger_r':t,'offset_r':o} for t,o in pairs],'control_timeout_bars':CONTROL_TIMEOUT_BARS}


def simulate(rows:list[dict[str,Any]], bars_by:Mapping[str,list[dict[str,Any]]], snaps:Mapping[str,Any], trigger_r:float|None=None, offset_r:float=0.0, cost_mult:float=1.0, plus_one_bar:bool=False)->list[dict[str,Any]]:
    out=[]
    for row in rows:
        sym=str(row['symbol']); bars=list(bars_by[sym]); idx={int(b['ts_ms']):i for i,b in enumerate(bars)}
        entry,r,_,ei=one_r(row,bars); side=str(row['side'])
        geo=row.get('intent_geometry') if isinstance(row.get('intent_geometry'),Mapping) else {}
        stop=geo.get('sl') if isinstance(geo,Mapping) else None
        if stop is None: stop=entry-r if side=='long' else entry+r
        stop=float(stop); last=min(len(bars)-1,ei+CONTROL_TIMEOUT_BARS)
        armed=False; px=ts=reason=None; hit_index=None
        for j in range(ei,last+1):
            lo,hi=float(bars[j]['low']),float(bars[j]['high'])
            if trigger_r is not None and not armed:
                trigger=entry+trigger_r*r if side=='long' else entry-trigger_r*r
                if (hi>=trigger if side=='long' else lo<=trigger): armed=True
            active_stop=stop
            if armed and trigger_r is not None:
                active_stop=entry+offset_r*r if side=='long' else entry-offset_r*r
            hit=lo<=active_stop if side=='long' else hi>=active_stop
            if hit:
                px,ts,reason,hit_index=active_stop,int(bars[j]['ts_ms']),('BREAKEVEN' if armed and trigger_r is not None else 'SL'),j; break
        if px is None:
            px,ts,reason,hit_index=float(bars[last]['close']),int(bars[last]['ts_ms']),'TIMEOUT',last
        if plus_one_bar and hit_index is not None and hit_index+1<len(bars):
            hit_index+=1; px=float(bars[hit_index]['open']); ts=int(bars[hit_index]['ts_ms']); reason+='_PLUS1'
        snap=snaps[sym]
        funding=ev.funding_cost(int(row['entry_ts']),int(ts),list(snap['funding_rows']))
        base_cost=float(snap['fee_bps'])+float(snap['spread_bps'])+float(snap['impact_bps'])+funding
        cost=cost_mult*base_cost
        gross=(float(px)-entry)/entry*10000.0 if side=='long' else (entry-float(px))/entry*10000.0
        out.append({**{k:row.get(k) for k in ('symbol','signal_ts','entry_ts','side')},'exit_ts':int(ts),'entry':entry,'exit':float(px),'reason':reason,'gross_bps':gross,'realized_cost_bps':cost,'net_bps':gross-cost})
    return out


def evaluate(rows:list[dict[str,Any]], bars_by:Mapping[str,list[dict[str,Any]]], snaps:Mapping[str,Any])->dict[str,Any]:
    pairs,space=search_space(rows,bars_by,snaps)
    if not pairs: return {'state':'NO_ROBUST_BREAKEVEN_OPTIMUM','reason':'EMPTY_DEVELOPMENT_SEARCH_SPACE','search_space':space,'candidate_count':0}
    base=rr_opt.mset(simulate(rows,bars_by,snaps)); base2=rr_opt.mset(simulate(rows,bars_by,snaps,cost_mult=2.0)); base1=rr_opt.mset(simulate(rows,bars_by,snaps,plus_one_bar=True))
    cells=[]
    for i,(t,o) in enumerate(pairs):
        cm=rr_opt.mset(simulate(rows,bars_by,snaps,t,o)); rel=rr_opt.relation(cm,base)
        c2=rr_opt.mset(simulate(rows,bars_by,snaps,t,o,cost_mult=2.0)); c1=rr_opt.mset(simulate(rows,bars_by,snaps,t,o,plus_one_bar=True))
        stress={'COST_2X':{'candidate':c2,'control':base2,'positive':c2['Net_bps']>0,'nonworse_net':c2['Net_bps']>base2['Net_bps']},'PLUS_ONE_BAR':{'candidate':c1,'control':base1,'positive':c1['Net_bps']>0,'nonworse_net':c1['Net_bps']>base1['Net_bps']}}
        cells.append({'index':i,'trigger_r':t,'offset_r':o,'metrics':cm,'relation':rel,'base_pass':rr_opt.pass_relation(rel),'stress':stress,'stress_pass':all(v['positive'] and v['nonworse_net'] for v in stress.values()),'objective':rr_opt.objective(cm,base)})
    for c in cells:
        neigh=[x for x in cells if x is not c and abs(x['trigger_r']-c['trigger_r'])<=0.35 and abs(x['offset_r']-c['offset_r'])<=0.10]
        pos=[x for x in neigh if x['metrics']['Net_bps']>base['Net_bps']]
        frac=len(pos)/len(neigh) if neigh else 0.0
        c['neighbor_stability']={'neighbors':[{'trigger_r':x['trigger_r'],'offset_r':x['offset_r'],'net_delta_bps':x['metrics']['Net_bps']-base['Net_bps']} for x in neigh],'positive_fraction':frac,'plateau_pass':bool(neigh) and frac>=0.50}
        c['robust_pass']=bool(c['base_pass'] and c['stress_pass'] and c['neighbor_stability']['plateau_pass'])
    good=[x for x in cells if x['robust_pass']]
    if not good: return {'state':'NO_ROBUST_BREAKEVEN_OPTIMUM','reason':'DEVELOPMENT_PLATEAU_OR_STRESS_FAIL','search_space':space,'candidate_count':len(cells),'control':base,'cells':cells}
    best=max(float(x['objective']) for x in good); near=[x for x in good if float(x['objective'])>=best-0.02]
    near.sort(key=lambda x:(x['neighbor_stability']['positive_fraction'],-x['trigger_r'],-x['offset_r'],x['objective']),reverse=True)
    return {'state':'PASS_DEVELOPMENT_ONLY_ROBUST_BREAKEVEN_PLATEAU','search_space':space,'candidate_count':len(cells),'control':base,'chosen':near[0],'robust_count':len(good),'cells':cells}


def run(source:Path,out:Path)->dict[str,Any]:
    src=read(source); prev=read(PREV); rows=[dict(x) for x in src.get('trades') or []]
    if len(rows)<REQUIRED_T: raise RuntimeError(f'SSOT_MIN_T_NOT_MET:{len(rows)}')
    if list(src.get('integrity_defects') or []) or int(src.get('duplicate_count') or 0)!=0 or int(src.get('leakage_lookahead_count') or 0)!=0: raise RuntimeError('INELIGIBLE_SOURCE_INTEGRITY')
    if prev.get('state')!='NO_ROBUST_TIME_STOP_OPTIMUM' or prev.get('next_axis')!=FAMILY: raise RuntimeError('TIME_STOP_NOT_CLOSED_OR_WRONG_NEXT_AXIS')
    syms=sorted({str(x['symbol']) for x in rows}); bars_by={s:ev.fetch_bars(s,'1h',1000) for s in syms}; authority=read(rr_opt.COST); snaps={s:ev.fetch_execution_snapshot(s,authority) for s in syms}
    result=evaluate(rows,bars_by,snaps); parent_sha=str(src.get('receipt_sha256') or stable(src)); generation=stable({'schema':SCHEMA,'parent_sha':parent_sha,'family':FAMILY,'source_artifact':SOURCE_ARTIFACT_ID,'search_space':result.get('search_space'),'objective':'ROBUST_REALISTIC_COST_NET_EXPECTANCY_NET_DAY_PARETO','control_timeout_bars':CONTROL_TIMEOUT_BARS})
    now=datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00','Z')
    base={'schema_version':SCHEMA,'strategy_id':'trend_rider','strategy_role':'G4_ECONOMIC_SURVIVOR','parent_sha':parent_sha,'exit_family':FAMILY,'search_generation_sha':generation,'source_artifact_id':SOURCE_ARTIFACT_ID,'T':len(rows),'development_scheme':'FULL_G4_BROAD30_DEVELOPMENT_ONLY_AFTER_HISTORICAL_INTERNAL_OOS_DECLARED_STRUCTURALLY_INSUFFICIENT','validation_scheme':'TRUE_PROSPECTIVE_FIRST_N_REQUIRED_NO_RETUNE','historical_internal_oos_reused':False,'g5_w2_w3_used_for_search':False,'fresh_prospective_used_for_search':False,'entry_logic_frozen':True,'stop_geometry_frozen':True,'rr_geometry_frozen':True,'timeout_geometry_frozen':True,'execution_authority':'NONE','order_authority':'BLOCKED','live_trade_authority':'BLOCKED','selection_authority':False,'promotion_authority':False,'protected_mutations':0,'duplicate':0,'leakage':0,'integrity':0,'search_method':'DEVELOPMENT_ONLY_MFE_COST_QUANTILES_PLUS_NEIGHBOR_PLATEAU','search_budget':MAX_CANDIDATES,'result':result}
    if result.get('state')=='PASS_DEVELOPMENT_ONLY_ROBUST_BREAKEVEN_PLATEAU':
        ch=result['chosen']; params={'breakeven_trigger_r':float(ch['trigger_r']),'breakeven_offset_r':float(ch['offset_r']),'control_timeout_bars':CONTROL_TIMEOUT_BARS,'partial':None,'trailing':None,'runner':None}; child=stable({'parent_sha':parent_sha,'family':FAMILY,'params':params,'generation':generation})
        base.update({'state':'PREREGISTERED_TRUE_PROSPECTIVE_BREAKEVEN','action':'hold','exact_params':params,'exit_child_sha':child,'boundary_ts':now,'control_metrics':result['control'],'candidate_metrics':ch['metrics'],'neighbor_stability':ch['neighbor_stability'],'stress':ch['stress'],'overfit_guard':{'pass_for_promotion':False,'development_plateau_pass':True,'true_prospective_required':True,'candidate_count':result['candidate_count']},'Pareto_relation':'DEVELOPMENT_ONLY_ROBUST_PLATEAU_FROZEN_NOT_PROMOTION_EVIDENCE','next_axis':'TRUE_PROSPECTIVE_FIRST_N_BREAKEVEN_NO_RETUNE'})
    else:
        base.update({'state':'NO_ROBUST_BREAKEVEN_OPTIMUM','action':'route_change','exact_params':None,'exit_child_sha':None,'boundary_ts':None,'control_metrics':result.get('control'),'candidate_metrics':None,'neighbor_stability':None,'stress':None,'overfit_guard':{'pass_for_promotion':False,'development_plateau_pass':False,'true_prospective_required':False,'candidate_count':result.get('candidate_count')},'Pareto_relation':'NO_ADOPTABLE_ROBUST_BREAKEVEN_PLATEAU','next_axis':'PARTIAL'})
    base['artifact_sha']=stable(base); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(base,indent=2,sort_keys=True,allow_nan=False)+'\n'); return base


def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument('--source',type=Path); ap.add_argument('--out',type=Path,default=OUT_DEFAULT); ap.add_argument('--self-test',action='store_true'); a=ap.parse_args()
    if a.self_test:
        assert stable({'b':1,'a':2})==stable({'a':2,'b':1}); assert CONTROL_TIMEOUT_BARS==48 and MAX_CANDIDATES==12; print('PASS_BREAKEVEN_OPTIMIZER_SELF_TEST'); return 0
    if a.source is None: raise SystemExit('--source required')
    r=run(a.source,a.out); print(json.dumps({'state':r['state'],'exact_params':r.get('exact_params'),'boundary_ts':r.get('boundary_ts'),'artifact_sha':r['artifact_sha']},sort_keys=True)); return 0

if __name__=='__main__': raise SystemExit(main())
