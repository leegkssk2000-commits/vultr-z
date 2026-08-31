#!/usr/bin/env python3
from __future__ import annotations
import argparse,bisect,json
from pathlib import Path
from typing import Any
from backend.research.rebuild import a1_top5_parent_preserving_component_transplant_v1 as base
from backend.research.rebuild import a1_top5_parent_preserving_native_donor_v2 as native

ROOT=Path(__file__).resolve().parents[3]
FREEZE=ROOT/'backend/research/contracts/a1_keltner_parent_reclaim_sleeve_freeze_v1.json'
PARENTS=ROOT/'backend/research/rebuild/a1_production_highwr_rolling_closed_latest.json'
LATEST=ROOT/'backend/research/rebuild/a1_keltner_parent_reclaim_sleeve_fresh_latest.json'
LANE='keltner_trend_main'

def read(p:Path)->dict[str,Any]:
    x=json.loads(p.read_text());
    if not isinstance(x,dict):raise RuntimeError('OBJECT_REQUIRED')
    return x

def run(out:Path)->dict[str,Any]:
    f=read(FREEZE); src=read(PARENTS); boundary=int(f['prospective_boundary']['ms'])
    all_t=[dict(x) for x in src['lanes'][LANE]['closed_trades']]
    parent=[x for x in all_t if int(x['signal_ts'])>=boundary]
    by={}
    for t in parent:by.setdefault(str(t['symbol']),[]).append(t)
    kept=[]; flags={}
    for sym,tt in by.items():
        mx=max(int(x['signal_ts']) for x in tt); bars=base.req(sym,mx+base.TF_MS); ts,ft=native.table(bars)
        for t in tt:
            j=bisect.bisect_right(ts,int(t['signal_ts'])-base.TF_MS)-1
            accept=bool(j>=0 and ft[j]['KELTNER_RECLAIM']); flags[str(t['closed_trade_id'])]=accept
            if accept: kept.append(t)
    m=base.metrics(kept); gate=f['fresh_gate']; n=len(kept)
    formal=bool(n>=int(gate['minimum_fresh_T']) and float(m.get('net_pnl_bps') or 0)>float(gate['net_pnl_bps_gt']) and float(m.get('net_expectancy_bps') or 0)>float(gate['net_expectancy_bps_gt']) and (m.get('profit_factor_unbounded') or float(m.get('profit_factor') or 0)>float(gate['profit_factor_gt'])))
    state='WAIT_FRESH_BOUNDARY' if not parent and max([int(x['signal_ts']) for x in all_t],default=0)<boundary else ('PASS_FRESH_GATE_CANDIDATE' if formal else 'G4_FRESH_ACTIVE_WAIT_MIN_OR_ECON_GATE')
    r={'schema_version':'zel.a1.keltner.parent_reclaim_sleeve.fresh.receipt.v1','state':state,'child_id':f['child_id'],'parent_lane_id':LANE,'boundary_ms':boundary,'boundary_utc':f['prospective_boundary']['utc'],'parent_post_boundary_closed_T':len(parent),'fresh_T':n,'rejected_parent_T':len(parent)-n,'minimum_fresh_T':int(gate['minimum_fresh_T']),'metrics':m,'fresh_gate_pass':formal,'fresh_trade_ids':[str(x['closed_trade_id']) for x in kept],'historical_credit_T':0,'donor_development_credit_T':0,'parent_entry_mutation_count':0,'parent_exit_mutation_count':0,'cost_rededuction_count':0,'new_trade_admission_count':0,'roadmap_blocking':False,'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED','live_trade_authority':'BLOCKED'}
    r['receipt_sha256']=base.sha(r);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(r,indent=2,sort_keys=True,allow_nan=False)+'\n');print(json.dumps({'state':state,'parent_post_boundary_T':len(parent),'fresh_T':n,'metrics':m,'pass':formal},sort_keys=True));return r

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,default=LATEST);a=p.parse_args();run(a.out)
if __name__=='__main__':main()
