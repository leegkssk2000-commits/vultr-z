#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild import trend_rider_unified_v1_policy as policy

ROOT = Path(__file__).resolve().parents[3]
CONTRACT_PATH = ROOT / 'backend/research/contracts/trendrider_unified_g5a_collector_v1.json'
STATE_PATH = ROOT / 'backend/research/rebuild/g5_trend_rider_unified_state_v1.json'
EVENTS_PATH = ROOT / 'backend/research/rebuild/g5_trend_rider_unified_events_v1.jsonl'
COST_PATH = ROOT / 'backend/research/rebuild/a1_rebuilt_bb_revert_cost_authority_v1.json'
POLICY_PATH = ROOT / 'backend/research/rebuild/trend_rider_unified_v1_policy.py'
SCHEMA = 'zel.g5a.trendrider_unified.event.v1'
STATE_SCHEMA = 'zel.g5a.trendrider_unified.state.v1'
SYMBOLS = ('BTC-USDT','ETH-USDT')
HOUR_MS = 3_600_000
AUTHORITY = dict(selection_authority=False,promotion_authority=False,execution_authority='NONE',order_authority='BLOCKED',live_trade_authority='BLOCKED',formal_credit=0)


def now_ms(): return int(time.time()*1000)
def stable(v): return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False,default=str).encode()).hexdigest()
def read(path): return json.loads(Path(path).read_text())
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def read_events(path):
    if not Path(path).exists(): return []
    return [json.loads(x) for x in Path(path).read_text().splitlines() if x.strip()]

def write_json(path,v):
    Path(path).parent.mkdir(parents=True,exist_ok=True);Path(path).write_text(json.dumps(v,sort_keys=True,indent=2,ensure_ascii=False)+'\n')
def write_events(path,rows):
    Path(path).parent.mkdir(parents=True,exist_ok=True);Path(path).write_text(''.join(json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False)+'\n' for x in rows))

def seal_state(v):
    v=dict(v);v.pop('state_sha256',None);v['state_sha256']=stable(v);return v

def validate_contract(c):
    if c['rule_id'] != policy.RULE_ID: raise RuntimeError('UNIFIED_RULE_ID_DRIFT')
    if c['policy_path'] != 'backend/research/rebuild/trend_rider_unified_v1_policy.py': raise RuntimeError('UNIFIED_POLICY_PATH_DRIFT')
    if c['historical_backfill'] is not False or c['pre_boundary_credit'] != 0: raise RuntimeError('UNIFIED_BOUNDARY_POLICY_DRIFT')
    if c['authority']['order_authority'] != 'BLOCKED': raise RuntimeError('UNIFIED_ORDER_AUTHORITY_DRIFT')

def validate_state(s,c):
    if s['schema_version'] != STATE_SCHEMA or s['rule_id'] != policy.RULE_ID: raise RuntimeError('UNIFIED_STATE_IDENTITY_DRIFT')
    if int(s['boundary_ms']) != int(c['qualification_boundary_ms']): raise RuntimeError('UNIFIED_STATE_BOUNDARY_DRIFT')
    if s['historical_backfill'] is not False: raise RuntimeError('UNIFIED_STATE_BACKFILL_DRIFT')
    core=dict(s);sup=core.pop('state_sha256');
    if stable(core)!=sup: raise RuntimeError('UNIFIED_STATE_HASH')

def validate_chain(rows):
    prev=None;seen=set()
    for i,r in enumerate(rows):
        if r['schema_version']!=SCHEMA or r['seq']!=i or r['prev_sha256']!=prev: raise RuntimeError('UNIFIED_EVENT_CHAIN')
        if r['event_id'] in seen: raise RuntimeError('UNIFIED_EVENT_DUP')
        core=dict(r);sup=core.pop('record_sha256')
        if stable(core)!=sup: raise RuntimeError('UNIFIED_EVENT_HASH')
        seen.add(r['event_id']);prev=sup

def append(rows,payload):
    r=dict(payload,schema_version=SCHEMA,seq=len(rows),prev_sha256=rows[-1]['record_sha256'] if rows else None)
    r['record_sha256']=stable(r);rows.append(r);return r

def closed_bars(symbol,current_ms):
    rows=[dict(x) for x in ev.fetch_bars(symbol,'1h',1000)]
    return [x for x in rows if int(x['ts_ms'])+HOUR_MS<=current_ms]

def probe(symbol,bars,current_ms,cost_authority,boundary_ms):
    if len(bars)<65:return None
    signal_ts=int(bars[-1]['ts_ms']);close_ms=signal_ts+HOUR_MS
    if signal_ts < boundary_ms:return None
    cfg=policy.TrendRiderUnifiedV1Config()
    f=policy.compute_trend_rider_feature(bars,symbol=symbol,now_ts_ms=current_ms,config=cfg)
    lo=bool(f.values.get('long_confirm'));sh=bool(f.values.get('short_confirm'))
    if lo==sh:return None
    cost=ev.fetch_execution_snapshot(symbol,dict(cost_authority))
    intent=policy.build_trend_rider_intent(f,policy_source_sha=ev.git_blob_sha(POLICY_PATH),verified_round_trip_cost_bps=float(cost['pretrade_verified_cost_bps']),config=cfg)
    if bool(getattr(intent,'no_trade')):return None
    side=str(getattr(intent,'side'))
    tail=[dict(x) for x in bars[-65:]]
    tail_sha=stable(tail)
    event_id=stable(dict(rule_id=policy.RULE_ID,symbol=symbol,signal_ts=signal_ts,side=side,feature_sha=f.feature_sha))
    return dict(event_id=event_id,rule_id=policy.RULE_ID,symbol=symbol,signal_ts=signal_ts,signal_bar_close_ms=close_ms,side=side,
                feature_sha=str(f.feature_sha),intent_sha=ev.intent_sha(intent),pretrade_verified_cost_bps=float(cost['pretrade_verified_cost_bps']),
                cost_snapshot_sha256=str(cost['snapshot_sha256']),policy_blob_sha=ev.git_blob_sha(POLICY_PATH),policy_sha256=sha(POLICY_PATH),
                source_bar_tail_sha256=tail_sha,primary_core=bool(f.values.get('primary_core_long_confirm') or f.values.get('primary_core_short_confirm')),
                broad_only=bool(f.values.get('broad_only_long_confirm') or f.values.get('broad_only_short_confirm')),observed_at_ms=current_ms,
                lifecycle_state='SIGNAL_CAPTURED_AWAIT_ECONOMIC_COMPLETION',g5a_economic_credit=False,**AUTHORITY)

def make_state(c):
    return seal_state(dict(schema_version=STATE_SCHEMA,state='UNIFIED_G5A_COLLECTOR_READY_FUTURE_ONLY',rule_id=policy.RULE_ID,
                           architecture=policy.ARCHITECTURE,boundary_ms=int(c['qualification_boundary_ms']),boundary_utc=c['qualification_boundary_utc'],
                           historical_backfill=False,last_scanned_closed_1h_ms=0,policy_sha256=sha(POLICY_PATH),contract_sha256=sha(CONTRACT_PATH),symbols=list(SYMBOLS),**AUTHORITY))

def run(state,events,current_ms):
    c=read(CONTRACT_PATH);validate_contract(c);validate_chain(events)
    if state is None: state=make_state(c)
    else: validate_state(state,c)
    auth=ev.load_json(COST_PATH)
    if auth.get('state')!='FROZEN_REALISTIC_PUBLIC_BINGX_COST_AUTHORITY': raise RuntimeError('UNIFIED_COST_AUTHORITY_INVALID')
    known={r['event_id'] for r in events};new=0;cursor=int(state['last_scanned_closed_1h_ms'])
    for symbol in SYMBOLS:
        bars=closed_bars(symbol,current_ms)
        for j in range(64,len(bars)):
            ts=int(bars[j]['ts_ms'])
            if ts < int(c['qualification_boundary_ms']) or ts <= cursor: continue
            p=probe(symbol,bars[:j+1],current_ms,auth,int(c['qualification_boundary_ms']))
            if p and p['event_id'] not in known:
                append(events,p);known.add(p['event_id']);new+=1
        if bars: cursor=max(cursor,int(bars[-1]['ts_ms']))
    state['last_scanned_closed_1h_ms']=cursor;state['event_T']=len(events);state=seal_state(state)
    status=dict(state=state['state'],new_events=new,event_T=len(events),boundary_ms=state['boundary_ms'],formal_credit=0,
                g5a_economic_completed_T=sum(1 for x in events if x.get('g5a_economic_credit') is True),
                next='ACCUMULATE_FUTURE_ONLY_SIGNAL_EVENTS_AND_BIND_COMPLETED_LIFECYCLE_ACCOUNTING',**{k:v for k,v in AUTHORITY.items() if k!='formal_credit'})
    return state,events,status

def self_test():
    c=read(CONTRACT_PATH);validate_contract(c);s=make_state(c);validate_state(s,c)
    rows=[];append(rows,dict(event_id='x',x=1));validate_chain(rows)
    assert s['boundary_ms']==1789221600000 and s['historical_backfill'] is False
    assert policy.invariant_receipt()['historical_membership_runtime_dependency'] is False
    print('PASS_TRENDRIDER_UNIFIED_G5A_COLLECTOR_V1');return 0

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--self-test',action='store_true');ap.add_argument('--out-dir');args=ap.parse_args()
    if args.self_test: return self_test()
    state=read(STATE_PATH) if STATE_PATH.exists() else None;events=read_events(EVENTS_PATH);s,e,status=run(state,events,now_ms())
    out=Path(args.out_dir or ROOT/'out');out.mkdir(parents=True,exist_ok=True)
    write_json(out/'g5_trend_rider_unified_state_v1.json',s);write_events(out/'g5_trend_rider_unified_events_v1.jsonl',e);write_json(out/'g5_trend_rider_unified_status_v1.json',status)
    print(json.dumps(status,sort_keys=True));return 0

if __name__=='__main__': raise SystemExit(main())
