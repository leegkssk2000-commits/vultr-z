#!/usr/bin/env python3
from __future__ import annotations

import argparse, hashlib, json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT=Path(__file__).resolve().parents[3]
R=ROOT/'backend/research/rebuild'
TOP5=R/'a1_top5_latest_only_ssot_v1.json'
PROSPECTIVE=R/'a1_top5_replacement_child_prospective_v2_latest.json'
ARRIVAL=R/'a1_top5_replacement_child_v2_arrival_telemetry_latest.json'
CLEAN_RUN=R/'g5_clean_runner_run_latest_v1.json'
FORWARD=R/'g5_forward_real_bridge_latest_v1.json'
BBO_STATE=R/'g5_trend_rider_bbo_oos_state_v1.json'
BBO_EVENTS=R/'g5_trend_rider_bbo_oos_events_v1.jsonl'
SCHEMA='zel.g5.pipeline_watchdog.v1'
AUTH={'formal_credit':0,'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED','live_trade_authority':'BLOCKED'}

def stable(v:Any)->str:
    return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False,default=str).encode()).hexdigest()

def load(p:Path)->dict[str,Any]:
    if not p.exists(): return {}
    v=json.loads(p.read_text()); return v if isinstance(v,dict) else {}

def load_jsonl(p:Path)->list[dict[str,Any]]:
    if not p.exists(): return []
    return [v for v in (json.loads(x) for x in p.read_text().splitlines() if x.strip()) if isinstance(v,dict)]

def iv(v:Any)->int:
    try:return int(v or 0)
    except:return 0

def fv(v:Any)->float|None:
    try:return float(v)
    except:return None

def funnel(arrival:Mapping[str,Any], settled:Mapping[str,Any])->dict[str,Any]:
    raw=iv(arrival.get('raw_signal_count') or arrival.get('raw_signal_T'))
    actionable=iv(arrival.get('collector_actionable_signal_count') or arrival.get('eligible_T'))
    maturing=iv(arrival.get('maturing_count'))
    closed_candidate=iv(arrival.get('closed_candidate_count'))
    await_entry=iv(arrival.get('awaiting_entry_count'))
    settled_closed=iv(settled.get('closed_T') or settled.get('closed'))
    metrics=settled.get('metrics') if isinstance(settled.get('metrics'),dict) else {}
    net=fv(metrics.get('net_pnl_bps') if metrics else settled.get('net_pnl_bps'))
    pf=fv(metrics.get('profit_factor') if metrics else settled.get('profit_factor'))
    if settled_closed>0:
        cls='ECONOMIC_EVIDENCE_NEGATIVE' if net is not None and net<=0 else 'ECONOMIC_EVIDENCE_ACCUMULATING'
    elif closed_candidate>0:
        cls='CLOSED_CANDIDATE_WAITING_SETTLEMENT_OR_WRITER'
    elif maturing>0:
        cls='SIGNAL_LIVE_MATURING'
    elif await_entry>0:
        cls='SIGNAL_WAITING_ENTRY'
    elif raw>0 and actionable==0:
        cls='ADMISSION_REJECTING_ALL_RAW_SIGNALS'
    elif actionable>0:
        cls='ACTIONABLE_SIGNAL_NOT_OPENED'
    else:
        cls='SIGNAL_STARVATION'
    return {'raw_signal_T':raw,'actionable_signal_T':actionable,'maturing_T':maturing,'closed_candidate_T':closed_candidate,'awaiting_entry_T':await_entry,'settled_closed_T':settled_closed,'net_pnl_bps':net,'profit_factor':pf,'classification':cls}

def build(now:datetime|None=None)->dict[str,Any]:
    now=now or datetime.now(timezone.utc)
    top5,pros,arr,clean,forward,bbo_state=map(load,[TOP5,PROSPECTIVE,ARRIVAL,CLEAN_RUN,FORWARD,BBO_STATE])
    bbo_events=load_jsonl(BBO_EVENTS)
    arr_lanes=arr.get('lanes') if isinstance(arr.get('lanes'),dict) else {}
    pros_lanes=pros.get('lanes') if isinstance(pros.get('lanes'),dict) else {}
    lane_ids=sorted(set(arr_lanes)|set(pros_lanes))
    funnels={k:funnel(arr_lanes.get(k,{}) if isinstance(arr_lanes.get(k,{}),dict) else {}, pros_lanes.get(k,{}) if isinstance(pros_lanes.get(k,{}),dict) else {}) for k in lane_ids}

    ev=clean.get('evaluation_counts') if isinstance(clean.get('evaluation_counts'),dict) else {}
    life=clean.get('lifecycle_counts') if isinstance(clean.get('lifecycle_counts'),dict) else {}
    clean_new,clean_signal,clean_no=iv(ev.get('new')),iv(ev.get('signal')),iv(ev.get('no_signal'))
    clean_cls='SIGNAL_STARVATION' if clean_new>0 and clean_signal==0 and clean_no==clean_new else 'ACTIVE_SIGNAL_FLOW'

    prod_t,bridge_open=iv(forward.get('production_grade_T_total')),iv(forward.get('bridge_open_T'))
    forward_cls='PRODUCTION_GRADE_EVIDENCE_ACCUMULATING' if prod_t>0 else ('OPEN_NOT_CLOSED' if bridge_open>0 else ('UPSTREAM_SIGNAL_STARVATION' if clean_signal==0 else 'PROVENANCE_OR_WRITER_PATH_REVIEW_REQUIRED'))

    bbo_confirmed=sum(x.get('bbo_confirm') is True for x in bbo_events); bbo_rejected=sum(x.get('bbo_confirm') is False for x in bbo_events)
    bbo_cursor_observable=bool(bbo_state.get('last_scanned_closed_1h_ms') or bbo_state.get('last_scan_ms') or bbo_state.get('last_scanned_bar_ms'))
    bbo_cls='BBO_EVIDENCE_ACCUMULATING' if bbo_events else ('BBO_CAPTURE_GAP_UNOBSERVABLE' if not bbo_cursor_observable else 'BBO_CANDIDATE_SIGNAL_STARVATION')

    blockers=[]
    if clean_cls=='SIGNAL_STARVATION': blockers.append('CLEAN_RUNNER_SIGNAL_STARVATION')
    bad={'SIGNAL_STARVATION','ADMISSION_REJECTING_ALL_RAW_SIGNALS','ACTIONABLE_SIGNAL_NOT_OPENED','CLOSED_CANDIDATE_WAITING_SETTLEMENT_OR_WRITER','ECONOMIC_EVIDENCE_NEGATIVE'}
    blockers += [f'{k}:{v["classification"]}' for k,v in funnels.items() if v['classification'] in bad]
    if bbo_cls!='BBO_EVIDENCE_ACCUMULATING': blockers.append(f'TRENDRIDER_BBO:{bbo_cls}')
    if forward_cls!='PRODUCTION_GRADE_EVIDENCE_ACCUMULATING': blockers.append(f'FORWARD_REAL:{forward_cls}')

    out={'schema_version':SCHEMA,'generated_at_utc':now.isoformat().replace('+00:00','Z'),'state':'G5_BOTTLENECKS_PRESENT' if blockers else 'G5_PIPELINE_FLOWING','bottlenecks':blockers,
      'clean_runner':{'generated_at_utc':clean.get('generated_at_utc'),'new_evaluations':clean_new,'signal_T':clean_signal,'no_signal_T':clean_no,'open_T':iv(life.get('opened')),'closed_T':iv(life.get('closed')),'ledger_written_T':iv(life.get('ledger_written')),'classification':clean_cls},
      'replacement_lanes':funnels,
      'trendrider_bbo':{'activation_ms':iv(bbo_state.get('activation_ms')),'candidate_T':len(bbo_events),'confirmed_T':bbo_confirmed,'rejected_T':bbo_rejected,'capture_cursor_observable':bbo_cursor_observable,'classification':bbo_cls},
      'forward_real':{'state':forward.get('state'),'bridge_open_T':bridge_open,'production_grade_T':prod_t,'classification':forward_cls},
      'broad_control':{'role':'FAILED_CONTROL_ONLY__DO_NOT_WAIT_OR_RETUNE'},
      'guards':{'historical_backfill':False,'strategy_retune':False,'rr_exit_mutation':False,'g6_advance':False},**AUTH}
    out['receipt_sha256']=stable(out); return out

def self_test()->int:
    cases=[({'raw_signal_count':0},{},'SIGNAL_STARVATION'),({'raw_signal_count':2,'collector_actionable_signal_count':0},{},'ADMISSION_REJECTING_ALL_RAW_SIGNALS'),({'collector_actionable_signal_count':1,'maturing_count':1},{},'SIGNAL_LIVE_MATURING'),({'closed_candidate_count':1},{},'CLOSED_CANDIDATE_WAITING_SETTLEMENT_OR_WRITER'),({}, {'closed_T':2,'metrics':{'net_pnl_bps':-1}},'ECONOMIC_EVIDENCE_NEGATIVE')]
    for a,s,w in cases: assert funnel(a,s)['classification']==w
    return 0

def main()->int:
    p=argparse.ArgumentParser(); p.add_argument('--output',default='out/g5_pipeline_watchdog_latest_v1.json'); p.add_argument('--self-test',action='store_true'); a=p.parse_args()
    if a.self_test:return self_test()
    out=build(); q=Path(a.output); q.parent.mkdir(parents=True,exist_ok=True); q.write_text(json.dumps(out,indent=2,sort_keys=True,ensure_ascii=False,allow_nan=False)+'\n'); print(json.dumps({'state':out['state'],'bottlenecks':out['bottlenecks']},sort_keys=True)); return 0
if __name__=='__main__': raise SystemExit(main())
