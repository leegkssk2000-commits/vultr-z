#!/usr/bin/env python3
from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path
from typing import Any, Mapping

TRADE_KEY_FIELDS=("symbol","signal_ts","entry_ts","side")
def trade_key(t): return tuple(t[k] for k in TRADE_KEY_FIELDS)
def _maxdd(vals):
    eq=peak=worst=0.0
    for v in vals:
        eq+=float(v); peak=max(peak,eq); worst=max(worst,peak-eq)
    return worst
def metrics(rows):
    rows=[dict(x) for x in rows]
    if not rows: return {"trades":0,"net_pnl_bps":0.0,"net_expectancy_bps":None,"profit_factor":None,"profit_factor_unbounded":False,"win_rate":None,"drawdown_bps":0.0}
    vals=[float(x["net_bps"]) for x in rows]; wins=[v for v in vals if v>0]; losses=[-v for v in vals if v<0]; gp=sum(wins); gl=sum(losses)
    return {"trades":len(vals),"net_pnl_bps":sum(vals),"net_expectancy_bps":sum(vals)/len(vals),"profit_factor":gp/gl if gl>0 else None,"profit_factor_unbounded":bool(gp>0 and gl==0),"win_rate":len(wins)/len(vals),"drawdown_bps":_maxdd(vals)}

ROOT=Path(__file__).resolve().parents[3]
PARENT = ROOT / 'backend/research/rebuild/a1_trendrider_wr8125_exact16_trade_receipt_v1.json'
FRESH2 = ROOT / 'backend/research/rebuild/a1_trendrider_8125_fresh2_source_v1.json'
SCHEMA = 'zel.a1.trendrider.8125.fresh2_highamp_rescue.v1'

def read(path: Path) -> dict[str, Any]:
    v=json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(v,dict): raise RuntimeError(f'OBJECT_REQUIRED:{path}')
    return v

def payoff(rows: list[Mapping[str, Any]]) -> float | None:
    wins=[float(x['net_bps']) for x in rows if float(x['net_bps'])>0]
    losses=[-float(x['net_bps']) for x in rows if float(x['net_bps'])<0]
    if not wins or not losses: return None
    return (sum(wins)/len(wins))/(sum(losses)/len(losses))

def strict(parent, added):
    pm=metrics(parent); am=metrics(added); cm=metrics(parent+added)
    pp=payoff(parent); cp=payoff(parent+added)
    checks={
      'combined_wr_non_decrease': float(cm['win_rate'] or 0)>=float(pm['win_rate'] or 0),
      'combined_pnl_non_decrease': float(cm['net_pnl_bps'] or 0)>=float(pm['net_pnl_bps'] or 0),
      'combined_expectancy_non_decrease': float(cm['net_expectancy_bps'] or 0)>=float(pm['net_expectancy_bps'] or 0),
      'combined_pf_non_decrease': bool(cm.get('profit_factor_unbounded')) or (cm.get('profit_factor') is not None and float(cm['profit_factor'])>=float(pm['profit_factor'])),
      'combined_payoff_non_decrease': pp is None or (cp is not None and cp>=pp),
      'combined_dd_non_increase': float(cm['drawdown_bps'] or 0)<=float(pm['drawdown_bps'] or 0),
      'added_wr_at_least_parent': float(am['win_rate'] or 0)>=float(pm['win_rate'] or 0),
      'added_expectancy_at_least_parent': float(am['net_expectancy_bps'] or 0)>=float(pm['net_expectancy_bps'] or 0),
      'added_pf_at_least_parent': bool(am.get('profit_factor_unbounded')) or (am.get('profit_factor') is not None and float(am['profit_factor'])>=float(pm['profit_factor'])),
      'added_pnl_positive': float(am['net_pnl_bps'] or 0)>0,
    }
    return all(checks.values()),checks,am,cm,cp

def row(t): return {k:t.get(k) for k in ('symbol','signal_ts','entry_ts','side','net_bps','reason')}
def make_hypothetical(x): return {'symbol':'FUTURE-HIGHAMP','signal_ts':9999999999999,'entry_ts':9999999999999,'side':'long','net_bps':x,'reason':'DIAGNOSTIC_FUTURE_WIN'}
def required_future_win(parent,fixed,subset):
    def ok(x): return strict(parent,fixed+subset+[make_hypothetical(x)])[0]
    if not ok(50000.0): return None
    lo,hi=0.0,50000.0
    for _ in range(80):
        mid=(lo+hi)/2
        if ok(mid): hi=mid
        else: lo=mid
    return hi

def run(broad_path: Path):
    pd=read(PARENT); fd=read(FRESH2); bd=read(broad_path)
    parent=[dict(x) for x in pd.get('trades') or []]; fresh=[dict(x) for x in fd.get('trades') or []]; broad=[dict(x) for x in bd.get('trades') or []]
    if len(parent)!=16 or abs(float(pd['metrics']['win_rate'])-.8125)>1e-12: raise RuntimeError('PARENT_16T_8125_MISMATCH')
    if len(fresh)!=2 or any(float(x['net_bps'])<=0 for x in fresh): raise RuntimeError('FRESH2_MISMATCH')
    if len(broad)!=30 or abs(float(bd['metrics']['win_rate'])-.70)>1e-12: raise RuntimeError('BROAD30_70_MISMATCH')
    pkeys={trade_key(x) for x in parent}; fkeys={trade_key(x) for x in fresh}
    if pkeys & fkeys: raise RuntimeError('FRESH2_OVERLAPS_PARENT')
    overlap=[x for x in broad if trade_key(x) in pkeys]
    distinct=[x for x in broad if trade_key(x) not in pkeys and trade_key(x) not in fkeys]
    if len(overlap)!=15 or len(distinct)!=15: raise RuntimeError(f'EXPECTED_15_OVERLAP_15_DISTINCT:{len(overlap)}:{len(distinct)}')
    strict_pass=[]; all_rows=[]
    for n in range(len(distinct)+1):
      for comb in itertools.combinations(distinct,n):
        subset=[dict(x) for x in comb]; added=fresh+subset
        ok,checks,am,cm,cp=strict(parent,added)
        item={'donor_T':n,'added_T':len(added),'combined_T':len(parent)+len(added),'checks':checks,'added_metrics':am,'combined_metrics':cm,'combined_payoff':cp,'donor_rows':[row(x) for x in subset]}
        all_rows.append(item)
        if ok: strict_pass.append(item)
    c24=[x for x in all_rows if x['combined_T']==24]; c24.sort(key=lambda x:(sum(bool(v) for v in x['checks'].values()),float(x['combined_metrics']['net_expectancy_bps']),float(x['combined_payoff'] or 0)),reverse=True)
    c25=[x for x in all_rows if x['combined_T']==25]; c25.sort(key=lambda x:(sum(bool(v) for v in x['checks'].values()),float(x['combined_payoff'] or 0),float(x['combined_metrics']['net_expectancy_bps'])),reverse=True)
    future=[]
    for n in range(len(distinct)+1):
      for comb in itertools.combinations(distinct,n):
        subset=[dict(x) for x in comb]; req=required_future_win(parent,fresh,subset)
        if req is not None: future.append({'current_donor_T':n,'required_one_unseen_winner_bps':req,'current_combined_T':18+n,'donor_rows':[row(x) for x in subset]})
    future.sort(key=lambda x:(x['required_one_unseen_winner_bps'],x['current_donor_T']))
    return {'schema_version':SCHEMA,'state':'PASS_STRICT_RESCUE_FOUND' if strict_pass else 'HOLD_NO_STRICT_RESCUE_IN_BROAD30','strategy_id':'trend_rider','parent_T':16,'parent_metrics':metrics(parent),'parent_payoff':payoff(parent),'fresh2_T':2,'fresh2_metrics':metrics(fresh),'broad30_T':30,'broad_overlap_parent_T':len(overlap),'broad_distinct_T':len(distinct),'oracle_subset_count':2**len(distinct)-1,'strict_rescue_count':len(strict_pass),'strict_rescue_best':strict_pass[0] if strict_pass else None,'closest_24T':c24[0] if c24 else None,'closest_25T':c25[0] if c25 else None,'minimum_one_unseen_winner_rescue':future[0] if future else None,'oracle_is_promotion_evidence':False,'outcome_used_for_feasibility_only':True,'fresh2_fixed_not_deleted':True,'parent_immutable':True,'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED','live_trade_authority':'BLOCKED','action':'hold','next':'REQUIRE_OUTCOME_BLIND_GATE_PLUS_NEW_HIGH_AMPLITUDE_FRESH_T' if not strict_pass else 'FREEZE_CAUSAL_GATE_AND_REQUIRE_PROSPECTIVE_CONFIRMATION'}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--broad-source',type=Path,required=True); ap.add_argument('--out',type=Path,default=Path('out/a1_trendrider_8125_fresh2_highamp_rescue_v1.json')); args=ap.parse_args()
    r=run(args.broad_source); args.out.parent.mkdir(parents=True,exist_ok=True); args.out.write_text(json.dumps(r,indent=2,sort_keys=True,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps({'state':r['state'],'strict_rescue_count':r['strict_rescue_count'],'closest24':r['closest_24T']['combined_metrics'],'closest24_payoff':r['closest_24T']['combined_payoff'],'closest25':r['closest_25T']['combined_metrics'],'closest25_payoff':r['closest_25T']['combined_payoff'],'future':r['minimum_one_unseen_winner_rescue']},sort_keys=True)); return 0
if __name__=='__main__': raise SystemExit(main())
