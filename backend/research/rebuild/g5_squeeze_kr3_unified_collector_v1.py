#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import time
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping, Sequence

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild import squeeze_kr3_future_dual_generator_v1 as generator
from backend.research.rebuild import squeeze_kr3_native_sleeve_v1 as arbiter

ROOT = Path(__file__).resolve().parents[3]
CONTRACT_PATH = ROOT / 'backend/research/contracts/squeeze_kr3_unified_g5a_collector_v1.json'
STATE_PATH = ROOT / 'backend/research/rebuild/g5_squeeze_kr3_unified_state_v1.json'
EVENTS_PATH = ROOT / 'backend/research/rebuild/g5_squeeze_kr3_unified_events_v1.jsonl'
COST_PATH = ROOT / 'backend/research/rebuild/a1_rebuilt_bb_revert_cost_authority_v1.json'
GENERATOR_PATH = ROOT / 'backend/research/rebuild/squeeze_kr3_future_dual_generator_v1.py'
ARBITER_PATH = ROOT / 'backend/research/rebuild/squeeze_kr3_native_sleeve_v1.py'
SCHEMA = 'zel.g5a.squeeze_kr3_unified.event.v1'
STATE_SCHEMA = 'zel.g5a.squeeze_kr3_unified.state.v1'
BAR_MS = 14_400_000
SYMBOLS = ('1000PEPE-USDT','BCH-USDT','BTC-USDT','ETH-USDT','HYPE-USDT','LINK-USDT','SOL-USDT')
AUTHORITY = dict(selection_authority=False,promotion_authority=False,execution_authority='NONE',order_authority='BLOCKED',live_trade_authority='BLOCKED',formal_credit=0)


def now_ms() -> int: return int(time.time()*1000)
def stable(v: Any) -> str: return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False,default=str).encode()).hexdigest()
def read(path: Path) -> dict[str,Any]: return json.loads(path.read_text())
def sha(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()

def read_events(path: Path) -> list[dict[str,Any]]:
    if not path.exists(): return []
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]

def write_json(path: Path,v: Any) -> None:
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(v,sort_keys=True,indent=2,ensure_ascii=False)+'\n')
def write_events(path: Path,rows: Sequence[Mapping[str,Any]]) -> None:
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(''.join(json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False)+'\n' for x in rows))

def seal_state(v: Mapping[str,Any]) -> dict[str,Any]:
    out=dict(v);out.pop('state_sha256',None);out['state_sha256']=stable(out);return out

def validate_contract(c: Mapping[str,Any]) -> None:
    if c['rule_id'] != generator.RULE_ID: raise RuntimeError('SQUEEZE_KR3_RULE_ID_DRIFT')
    if c['historical_backfill'] is not False or int(c['historical_formal_credit']) != 0: raise RuntimeError('SQUEEZE_KR3_BOUNDARY_POLICY_DRIFT')
    if tuple(c['symbols']) != SYMBOLS: raise RuntimeError('SQUEEZE_KR3_SYMBOL_UNIVERSE_DRIFT')
    if c['component_identity']['core'] != generator.CORE_RULE or c['component_identity']['donor'] != generator.DONOR_RULE: raise RuntimeError('SQUEEZE_KR3_COMPONENT_DRIFT')
    if c['authority']['order_authority'] != 'BLOCKED' or c['authority']['live_trade_authority'] != 'BLOCKED': raise RuntimeError('SQUEEZE_KR3_AUTHORITY_DRIFT')

def validate_chain(rows: Sequence[Mapping[str,Any]]) -> None:
    prev=None;ids=set()
    for i,row in enumerate(rows):
        if row['schema_version']!=SCHEMA or int(row['seq'])!=i or row['prev_sha256']!=prev: raise RuntimeError('SQUEEZE_KR3_EVENT_CHAIN')
        if row['event_id'] in ids: raise RuntimeError('SQUEEZE_KR3_EVENT_DUP')
        core=dict(row);sup=core.pop('record_sha256')
        if stable(core)!=sup: raise RuntimeError('SQUEEZE_KR3_EVENT_HASH')
        ids.add(row['event_id']);prev=sup

def append(rows: list[dict[str,Any]],payload: Mapping[str,Any]) -> dict[str,Any]:
    row=dict(payload,schema_version=SCHEMA,seq=len(rows),prev_sha256=rows[-1]['record_sha256'] if rows else None)
    row['record_sha256']=stable(row);rows.append(row);return row

def validate_state(s: Mapping[str,Any],c: Mapping[str,Any]) -> None:
    if s['schema_version']!=STATE_SCHEMA or s['rule_id']!=generator.RULE_ID: raise RuntimeError('SQUEEZE_KR3_STATE_IDENTITY_DRIFT')
    if int(s['boundary_ms'])!=int(c['qualification_boundary_ms']) or s['historical_backfill'] is not False: raise RuntimeError('SQUEEZE_KR3_STATE_BOUNDARY_DRIFT')
    for symbol in SYMBOLS:
        item=s['cost_models'].get(symbol)
        if not item or stable(item['model'])!=item['model_sha256']: raise RuntimeError('SQUEEZE_KR3_COST_MODEL_HASH:'+symbol)
    core=dict(s);sup=core.pop('state_sha256')
    if stable(core)!=sup: raise RuntimeError('SQUEEZE_KR3_STATE_HASH')

def cost_from_snapshot(snapshot: Mapping[str,Any]) -> dict[str,float]:
    return {
        'fee_bps':float(snapshot['fee_bps']),
        'spread_bps':float(snapshot['spread_bps']),
        'impact_bps':float(snapshot['impact_bps']),
        'funding_p95_per_settlement_bps':float(snapshot['funding_p95_abs_bps']),
    }

def freeze_cost_models(authority: Mapping[str,Any]) -> dict[str,Any]:
    out={}
    for symbol in SYMBOLS:
        snap=ev.fetch_execution_snapshot(symbol,dict(authority))
        model=cost_from_snapshot(snap)
        out[symbol]={
            'model':model,
            'model_sha256':stable(model),
            'public_snapshot_sha256':str(snap['snapshot_sha256']),
            'pretrade_verified_cost_bps':float(snap['pretrade_verified_cost_bps']),
            'fee_bps':float(snap['fee_bps']),
            'spread_bps':float(snap['spread_bps']),
            'impact_bps':float(snap['impact_bps']),
            'funding_p95_abs_bps':float(snap['funding_p95_abs_bps']),
        }
    return out

def make_state(c: Mapping[str,Any],current_ms: int,authority: Mapping[str,Any]) -> dict[str,Any]:
    boundary=int(c['qualification_boundary_ms'])
    # Cost identity must exist before the first eligible 4h signal can complete.
    if current_ms >= boundary + BAR_MS: raise RuntimeError('SQUEEZE_KR3_COST_FREEZE_MISSED_FIRST_ELIGIBLE_SIGNAL_CLOSE_NEW_BOUNDARY_REQUIRED')
    models=freeze_cost_models(authority)
    return seal_state(dict(
        schema_version=STATE_SCHEMA,state='SQUEEZE_KR3_UNIFIED_G5A_COLLECTOR_READY_FUTURE_ONLY',rule_id=generator.RULE_ID,
        architecture=generator.ARCHITECTURE,boundary_ms=boundary,boundary_utc=c['qualification_boundary_utc'],historical_backfill=False,
        last_scanned_closed_4h_ms=0,signal_T=0,finalized_T=0,event_T=0,cost_models=models,cost_freeze_observed_at_ms=current_ms,
        contract_sha256=sha(CONTRACT_PATH),generator_sha256=sha(GENERATOR_PATH),arbiter_sha256=sha(ARBITER_PATH),symbols=list(SYMBOLS),**AUTHORITY))

def closed_source_rows(symbol: str,current_ms: int) -> list[dict[str,Any]]:
    bars=ev.fetch_bars(symbol,'4h',1000)
    out=[]
    for bar in bars:
        ts=int(bar['ts_ms'])
        if ts+BAR_MS>current_ms: continue
        out.append(dict(bar_open_ts=ts,bar_close_ts=ts+BAR_MS,open=float(bar['open']),high=float(bar['high']),low=float(bar['low']),close=float(bar['close']),volume=float(bar['volume'])))
    return out

def campaign_id(component: str,row: Mapping[str,Any]) -> str:
    return stable(dict(rule_id=generator.RULE_ID,component=component,symbol=row['symbol'],signal_ts=int(row['signal_ts']),entry_ts=int(row['entry_ts']),side=row.get('side','long')))

def accepted_campaigns(result: Mapping[str,Any],source_rows: Sequence[Mapping[str,Any]]) -> list[tuple[str,dict[str,Any]]]:
    out=[]
    for row in result['core_campaigns']:
        out.append(('CAPREUSE82_CORE',deepcopy(row)))
    plan=result['arbitration_plan']
    for item in plan['accepted_natural']:
        out.append(('C54_B_DONOR',deepcopy(item['row'])))
    for item in plan['accepted_preempt']:
        row=arbiter.preempt_raw(item['row'],source_rows,int(item['preempt_ts']))
        row['symbol']=item['key'][0];row['unified_component']='C54_B_DONOR';row['unified_rule_id']=generator.RULE_ID
        out.append(('C54_B_DONOR',row))
    # An identity can only appear once in the current causal reconstruction.
    seen=set();unique=[]
    for component,row in sorted(out,key=lambda x:(int(x[1]['signal_ts']),x[0],x[1]['symbol'])):
        cid=campaign_id(component,row)
        if cid in seen: continue
        seen.add(cid);unique.append((component,row))
    return unique

def source_window_sha(rows: Sequence[Mapping[str,Any]]) -> str: return stable(list(rows))

def run(state: dict[str,Any] | None,events: list[dict[str,Any]],current_ms: int) -> tuple[dict[str,Any],list[dict[str,Any]],dict[str,Any]]:
    c=read(CONTRACT_PATH);validate_contract(c);validate_chain(events)
    cost_authority=ev.load_json(COST_PATH)
    if cost_authority.get('state')!='FROZEN_REALISTIC_PUBLIC_BINGX_COST_AUTHORITY': raise RuntimeError('SQUEEZE_KR3_COST_AUTHORITY_INVALID')
    if state is None: state=make_state(c,current_ms,cost_authority)
    else: validate_state(state,c)
    captured={x['campaign_id'] for x in events if x.get('kind')=='SIGNAL_CAPTURED'}
    finalized={x['campaign_id'] for x in events if x.get('kind')=='LIFECYCLE_FINALIZED'}
    new_signal=new_final=0;cursor=int(state['last_scanned_closed_4h_ms']);boundary=int(c['qualification_boundary_ms'])
    for symbol in SYMBOLS:
        rows=closed_source_rows(symbol,current_ms)
        if rows: cursor=max(cursor,int(rows[-1]['bar_open_ts']))
        if not rows or int(rows[-1]['bar_close_ts'])<=boundary: continue
        result=generator.generate_symbol_campaigns(rows,symbol=symbol,eval_start_ms=boundary,eval_end_ms=int(rows[-1]['bar_close_ts']),cost_model=state['cost_models'][symbol]['model'])
        win_sha=source_window_sha(rows);cost_item=state['cost_models'][symbol]
        for component,row in accepted_campaigns(result,rows):
            if int(row['signal_ts'])<boundary: continue
            cid=campaign_id(component,row)
            if cid not in captured:
                append(events,dict(
                    event_id=stable(dict(campaign_id=cid,kind='SIGNAL_CAPTURED')),kind='SIGNAL_CAPTURED',campaign_id=cid,rule_id=generator.RULE_ID,
                    component=component,symbol=symbol,signal_ts=int(row['signal_ts']),entry_ts=int(row['entry_ts']),side=row.get('side','long'),
                    allocation_numerator=row.get('allocation_numerator',1),allocation_denominator=row.get('allocation_denominator',1),
                    cost_model_sha256=cost_item['model_sha256'],public_cost_snapshot_sha256=cost_item['public_snapshot_sha256'],
                    pretrade_verified_cost_bps=cost_item['pretrade_verified_cost_bps'],source_window_sha256=win_sha,
                    generator_sha256=state['generator_sha256'],arbiter_sha256=state['arbiter_sha256'],observed_at_ms=current_ms,
                    lifecycle_state='SIGNAL_CAPTURED_AWAIT_FINALIZATION',duplicate=False,censored=('exit_ts' not in row),unknown_exit=False,
                    g5a_economic_credit=False,**AUTHORITY));captured.add(cid);new_signal+=1
            if 'exit_ts' in row and cid not in finalized:
                reason=row.get('exit_reason')
                if reason is None: raise RuntimeError('SQUEEZE_KR3_FINAL_WITHOUT_EXIT_REASON')
                append(events,dict(
                    event_id=stable(dict(campaign_id=cid,kind='LIFECYCLE_FINALIZED',exit_ts=int(row['exit_ts']))),kind='LIFECYCLE_FINALIZED',campaign_id=cid,
                    rule_id=generator.RULE_ID,component=component,symbol=symbol,signal_ts=int(row['signal_ts']),entry_ts=int(row['entry_ts']),
                    exit_ts=int(row['exit_ts']),exit_reason=str(reason),side=row.get('side','long'),gross_bps=float(row.get('gross_bps',0.0)),
                    raw_lifecycle_sha256=stable(row),cost_model_sha256=cost_item['model_sha256'],source_window_sha256=win_sha,
                    generator_sha256=state['generator_sha256'],arbiter_sha256=state['arbiter_sha256'],observed_at_ms=current_ms,
                    lifecycle_state='FINALIZED_PENDING_G5A_ECONOMIC_ACCOUNTING',duplicate=False,censored=False,unknown_exit=False,
                    g5a_economic_credit=False,**AUTHORITY));finalized.add(cid);new_final+=1
    state['last_scanned_closed_4h_ms']=cursor;state['signal_T']=len(captured);state['finalized_T']=len(finalized);state['event_T']=len(events);state=seal_state(state)
    status=dict(state=state['state'],boundary_ms=boundary,new_signals=new_signal,new_finalized=new_final,signal_T=len(captured),finalized_T=len(finalized),
                formal_credit=0,g5a_economic_completed_T=0,next='ACCUMULATE_FUTURE_ONLY_LIFECYCLES_THEN_BIND_FINALIZED_ROWS_TO_G5A_ECONOMIC_ACCOUNTING',
                **{k:v for k,v in AUTHORITY.items() if k!='formal_credit'})
    return state,events,status

def self_test() -> int:
    c=read(CONTRACT_PATH);validate_contract(c)
    dummy={s:{'model':{'fee_bps':10.0,'spread_bps':1.0,'impact_bps':2.0,'funding_p95_per_settlement_bps':1.0},'model_sha256':'','public_snapshot_sha256':'x','pretrade_verified_cost_bps':14.0} for s in SYMBOLS}
    for x in dummy.values(): x['model_sha256']=stable(x['model'])
    s=seal_state(dict(schema_version=STATE_SCHEMA,state='SQUEEZE_KR3_UNIFIED_G5A_COLLECTOR_READY_FUTURE_ONLY',rule_id=generator.RULE_ID,architecture=generator.ARCHITECTURE,
        boundary_ms=int(c['qualification_boundary_ms']),boundary_utc=c['qualification_boundary_utc'],historical_backfill=False,last_scanned_closed_4h_ms=0,signal_T=0,finalized_T=0,event_T=0,
        cost_models=dummy,cost_freeze_observed_at_ms=0,contract_sha256=sha(CONTRACT_PATH),generator_sha256=sha(GENERATOR_PATH),arbiter_sha256=sha(ARBITER_PATH),symbols=list(SYMBOLS),**AUTHORITY))
    validate_state(s,c);rows=[];append(rows,dict(event_id='x',kind='TEST',campaign_id='c'));validate_chain(rows)
    inv=generator.invariant_receipt();assert inv['saved_campaign_membership_input'] is False and inv['core_priority'] and inv['donor_requires_core_flat']
    assert int(c['qualification_boundary_ms'])%BAR_MS==0 and c['historical_backfill'] is False
    print('PASS_SQUEEZE_KR3_UNIFIED_G5A_COLLECTOR_V1');return 0

def main() -> int:
    ap=argparse.ArgumentParser();ap.add_argument('--self-test',action='store_true');ap.add_argument('--out-dir');args=ap.parse_args()
    if args.self_test:return self_test()
    state=read(STATE_PATH) if STATE_PATH.exists() else None;events=read_events(EVENTS_PATH);s,e,status=run(state,events,now_ms())
    out=Path(args.out_dir or ROOT/'out');out.mkdir(parents=True,exist_ok=True)
    write_json(out/'g5_squeeze_kr3_unified_state_v1.json',s);write_events(out/'g5_squeeze_kr3_unified_events_v1.jsonl',e);write_json(out/'g5_squeeze_kr3_unified_status_v1.json',status)
    print(json.dumps(status,sort_keys=True));return 0

if __name__=='__main__': raise SystemExit(main())
