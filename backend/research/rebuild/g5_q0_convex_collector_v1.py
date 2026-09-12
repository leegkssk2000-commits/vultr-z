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
from backend.research.rebuild import q0_prospective_engine_v1 as engine
from backend.research.rebuild import q0_convex_intrabar_adapter_v1 as intrabar

ROOT=Path(__file__).resolve().parents[3]
CONTRACT_PATH=ROOT/'backend/research/contracts/q0_convex_g5a_collector_v1.json'
STATE_PATH=ROOT/'backend/research/rebuild/g5_q0_convex_state_v1.json'
EVENTS_PATH=ROOT/'backend/research/rebuild/g5_q0_convex_events_v1.jsonl'
COST_PATH=ROOT/'backend/research/rebuild/a1_rebuilt_bb_revert_cost_authority_v1.json'
ENGINE_PATH=ROOT/'backend/research/rebuild/q0_prospective_engine_v1.py'
INTRABAR_PATH=ROOT/'backend/research/rebuild/q0_convex_intrabar_adapter_v1.py'
STATE_SCHEMA='zel.g5a.q0_convex.state.v1'
EVENT_SCHEMA='zel.g5a.q0_convex.event.v1'
BAR_MS=14_400_000
MINUTE_MS=60_000
DAY_MS=86_400_000
SYMBOLS=('1000PEPE-USDT','BCH-USDT','BTC-USDT','ETH-USDT','HYPE-USDT','LINK-USDT','SOL-USDT')
AUTHORITY=dict(selection_authority=False,promotion_authority=False,execution_authority='NONE',order_authority='BLOCKED',live_trade_authority='BLOCKED',formal_credit=0)


def now_ms()->int:return int(time.time()*1000)
def stable(v:Any)->str:return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False,default=str).encode()).hexdigest()
def sha(path:Path)->str:return hashlib.sha256(path.read_bytes()).hexdigest()
def read(path:Path)->dict[str,Any]:return json.loads(path.read_text())

def write_json(path:Path,v:Any)->None:
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(v,sort_keys=True,indent=2,ensure_ascii=False)+'\n')
def read_events(path:Path)->list[dict[str,Any]]:
    if not path.exists():return []
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]
def write_events(path:Path,rows:Sequence[Mapping[str,Any]])->None:
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(''.join(json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False)+'\n' for x in rows))
def seal_state(v:Mapping[str,Any])->dict[str,Any]:
    out=deepcopy(dict(v));out.pop('state_sha256',None);out['state_sha256']=stable(out);return out

def append(rows:list[dict[str,Any]],payload:Mapping[str,Any])->dict[str,Any]:
    row=dict(payload,schema_version=EVENT_SCHEMA,seq=len(rows),prev_sha256=rows[-1]['record_sha256'] if rows else None)
    row['record_sha256']=stable(row);rows.append(row);return row

def validate_chain(rows:Sequence[Mapping[str,Any]])->None:
    prev=None;ids=set()
    for i,row in enumerate(rows):
        if row['schema_version']!=EVENT_SCHEMA or int(row['seq'])!=i or row['prev_sha256']!=prev:raise RuntimeError('Q0_EVENT_CHAIN')
        if row['event_id'] in ids:raise RuntimeError('Q0_EVENT_DUP')
        core=dict(row);sup=core.pop('record_sha256')
        if stable(core)!=sup:raise RuntimeError('Q0_EVENT_HASH')
        ids.add(row['event_id']);prev=sup

def validate_contract(c:Mapping[str,Any])->None:
    if c['rule_id']!=intrabar.RULE_ID:raise RuntimeError('Q0_RULE_ID_DRIFT')
    if tuple(c['symbols'])!=SYMBOLS:raise RuntimeError('Q0_SYMBOL_DRIFT')
    if int(c['qualification_boundary_ms'])%DAY_MS or int(c['collection_end_ms'])%DAY_MS:raise RuntimeError('Q0_DAILY_BOUNDARY_DRIFT')
    if c['historical_backfill'] is not False or c['authority']['order_authority']!='BLOCKED':raise RuntimeError('Q0_AUTHORITY_DRIFT')
    if c['signal_entry_rules']['retune'] is not False:raise RuntimeError('Q0_RETUNE_FORBIDDEN')

def validate_state(s:Mapping[str,Any],c:Mapping[str,Any])->None:
    if s['schema_version']!=STATE_SCHEMA or s['rule_id']!=intrabar.RULE_ID:raise RuntimeError('Q0_STATE_IDENTITY_DRIFT')
    if int(s['boundary_ms'])!=int(c['qualification_boundary_ms']) or s['historical_backfill'] is not False:raise RuntimeError('Q0_STATE_BOUNDARY_DRIFT')
    if s['engine_state']['schema']!=engine.SCHEMA or int(s['engine_state']['start'])!=int(c['qualification_boundary_ms']):raise RuntimeError('Q0_ENGINE_STATE_DRIFT')
    for symbol in SYMBOLS:
        item=s['cost_models'].get(symbol)
        if not item or stable(item['model'])!=item['model_sha256']:raise RuntimeError('Q0_COST_MODEL_HASH:'+symbol)
    core=deepcopy(dict(s));sup=core.pop('state_sha256')
    if stable(core)!=sup:raise RuntimeError('Q0_STATE_HASH')

def _norm4(raw:Mapping[str,Any])->dict[str,Any]:
    ts=int(raw['ts_ms']);return dict(bar_open_ts=ts,bar_close_ts=ts+BAR_MS,open=float(raw['open']),high=float(raw['high']),low=float(raw['low']),close=float(raw['close']),volume=float(raw.get('volume',0.0)))
def fetch_4h(symbol:str,current_ms:int)->list[dict[str,Any]]:
    rows=[_norm4(x) for x in ev.fetch_bars(symbol,'4h',1000) if int(x['ts_ms'])+BAR_MS<=current_ms]
    rows.sort(key=lambda x:x['bar_open_ts']);return rows
def fetch_1m(symbol:str)->list[dict[str,Any]]:
    return [dict(ts_ms=int(x['ts_ms']),open=float(x['open']),high=float(x['high']),low=float(x['low']),close=float(x['close']),volume=float(x.get('volume',0.0))) for x in ev.fetch_bars(symbol,'1m',1000)]
def _cost(snapshot:Mapping[str,Any])->dict[str,float]:
    return dict(fee_bps=float(snapshot['fee_bps']),spread_bps=float(snapshot['spread_bps']),impact_bps=float(snapshot['impact_bps']),funding_p95_per_settlement_bps=float(snapshot['funding_p95_abs_bps']))
def freeze_costs(authority:Mapping[str,Any])->dict[str,Any]:
    out={}
    for symbol in SYMBOLS:
        snap=ev.fetch_execution_snapshot(symbol,dict(authority));model=_cost(snap)
        out[symbol]=dict(model=model,model_sha256=stable(model),public_snapshot_sha256=str(snap['snapshot_sha256']),pretrade_verified_cost_bps=float(snap['pretrade_verified_cost_bps']),
                         fee_bps=float(snap['fee_bps']),spread_bps=float(snap['spread_bps']),impact_bps=float(snap['impact_bps']),funding_p95_abs_bps=float(snap['funding_p95_abs_bps']))
    return out

def common_warmup(rows_by:Mapping[str,Sequence[Mapping[str,Any]]],boundary:int,max_bars:int=180)->dict[str,list[dict[str,Any]]]:
    maps={s:{int(r['bar_open_ts']):dict(r) for r in rows_by[s] if int(r['bar_close_ts'])<boundary} for s in SYMBOLS}
    common=set.intersection(*(set(x) for x in maps.values()))
    if not common:raise RuntimeError('Q0_COMMON_WARMUP_EMPTY')
    end=max(common);stamps=[];cursor=end
    while cursor in common and len(stamps)<max_bars:
        stamps.append(cursor);cursor-=BAR_MS
    stamps=sorted(stamps)
    if len(stamps)<18:raise RuntimeError('Q0_COMMON_WARMUP_TOO_SHORT')
    return {s:[deepcopy(maps[s][t]) for t in stamps] for s in SYMBOLS}

def make_state(c:Mapping[str,Any],current_ms:int,rows_by:Mapping[str,Sequence[Mapping[str,Any]]],authority:Mapping[str,Any])->dict[str,Any]:
    boundary=int(c['qualification_boundary_ms'])
    # A Q0 confirmation can occur exactly at the daily boundary, so costs and
    # warmup must be sealed before that boundary, not after the first trade.
    if current_ms>=boundary:raise RuntimeError('Q0_PHASE0_MISSED_BOUNDARY_NEW_LATER_BOUNDARY_REQUIRED')
    warm=common_warmup(rows_by,boundary)
    es=engine.initialize(warm,list(SYMBOLS),boundary,int(c['collection_end_ms']))
    return seal_state(dict(schema_version=STATE_SCHEMA,state='Q0_CONVEX_CHANNEL_BREAKOUT_G5A_READY_FUTURE_ONLY',rule_id=intrabar.RULE_ID,
        strategy_name='Q0 Convex Channel Breakout',boundary_ms=boundary,boundary_utc=c['qualification_boundary_utc'],historical_backfill=False,
        collection_end_ms=int(c['collection_end_ms']),cost_models=freeze_costs(authority),cost_freeze_observed_at_ms=current_ms,
        warmup_sha256=stable(warm),warmup_first_open_ms=warm[SYMBOLS[0]][0]['bar_open_ts'],warmup_last_close_ms=warm[SYMBOLS[0]][-1]['bar_close_ts'],
        engine_sha256=sha(ENGINE_PATH),intrabar_adapter_sha256=sha(INTRABAR_PATH),contract_sha256=sha(CONTRACT_PATH),engine_state=es,
        signal_T=0,finalized_T=0,event_T=0,unknown_exit_T=0,censored_open_T=0,**AUTHORITY))

def _campaign(symbol:str,signal_ts:int)->str:return stable(dict(rule_id=intrabar.RULE_ID,symbol=symbol,signal_ts=int(signal_ts),side='long'))
def _context(rows:Sequence[Mapping[str,Any]],signal_ts:int)->list[dict[str,Any]]:
    eligible=[dict(r) for r in rows if int(r['bar_close_ts'])<=signal_ts]
    return eligible[-18:]

def _append_new_journal(state:dict[str,Any],events:list[dict[str,Any]],rows_by:Mapping[str,Sequence[Mapping[str,Any]]],witnesses:Sequence[Mapping[str,Any]],current_ms:int)->tuple[int,int]:
    signal_known={x['campaign_id'] for x in events if x.get('kind')=='SIGNAL_CAPTURED'}
    final_known={x['campaign_id'] for x in events if x.get('kind')=='LIFECYCLE_FINALIZED'}
    witness_known={x['campaign_id'] for x in events if x.get('kind')=='INTRABAR_STOP_WITNESS'}
    witness_map={(str(w['symbol']),int(w['signal_ts'])):dict(w) for w in witnesses}
    ns=nf=0;boundary=int(state['boundary_ms'])
    for symbol in SYMBOLS:
        s=state['engine_state']['by_symbol'][symbol];cost=state['cost_models'][symbol]
        for e in s['events']:
            if e.get('direction')!='UP' or int(e['signal_ts'])<boundary:continue
            cid=_campaign(symbol,int(e['signal_ts']))
            if cid not in signal_known:
                ctx=_context(rows_by[symbol],int(e['signal_ts']))
                append(events,dict(event_id=stable(dict(kind='SIGNAL_CAPTURED',campaign_id=cid)),kind='SIGNAL_CAPTURED',campaign_id=cid,rule_id=intrabar.RULE_ID,
                    symbol=symbol,signal_ts=int(e['signal_ts']),side='long',latched_stop=float(e['features']['lower']),latched_upper=float(e['features']['upper']),preparation=bool(e['features'].get('preparation')),
                    source_context_rows=ctx,source_context_sha256=stable(ctx),cost_model_sha256=cost['model_sha256'],engine_sha256=state['engine_sha256'],intrabar_adapter_sha256=state['intrabar_adapter_sha256'],
                    observed_at_ms=current_ms,lifecycle_state=str(e['status']),duplicate=False,censored=e['status']=='CENSORED',unknown_exit=False,g5a_economic_credit=False,**AUTHORITY));signal_known.add(cid);ns+=1
        for t in s['trades']:
            if int(t['signal_ts'])<boundary:continue
            cid=_campaign(symbol,int(t['signal_ts']));w=witness_map.get((symbol,int(t['signal_ts'])))
            if w is not None and cid not in witness_known:
                append(events,dict(event_id=stable(dict(kind='INTRABAR_STOP_WITNESS',campaign_id=cid,witness_sha256=w['witness_sha256'])),kind='INTRABAR_STOP_WITNESS',campaign_id=cid,
                    rule_id=intrabar.RULE_ID,symbol=symbol,signal_ts=int(t['signal_ts']),witness=w,observed_at_ms=current_ms,formal_credit=0,order_authority='BLOCKED',live_trade_authority='BLOCKED'))
                witness_known.add(cid)
            if cid not in final_known:
                unknown=bool(t.get('exit_reason')=='PROTECTIVE_STOP_INTRABAR' and not t.get('intrabar_stop_4h_timing_resolved'))
                append(events,dict(event_id=stable(dict(kind='LIFECYCLE_FINALIZED',campaign_id=cid,exit_ts=int(t['exit_ts']))),kind='LIFECYCLE_FINALIZED',campaign_id=cid,rule_id=intrabar.RULE_ID,
                    symbol=symbol,signal_ts=int(t['signal_ts']),entry_ts=int(t['entry_ts']),exit_ts=int(t['exit_ts']),entry_price=float(t['entry_price']),exit_price=float(t['exit_price']),
                    side='long',exit_reason=str(t['exit_reason']),exit_timestamp_semantics=str(t.get('exit_timestamp_semantics')),
                    gross_bps=float(t['gross_bps']),mfe_bps=float(t['mfe_bps']),mae_bps=float(t['mae_bps']),raw_lifecycle_sha256=stable(t),
                    cost_model_sha256=cost['model_sha256'],pretrade_verified_cost_bps=cost['pretrade_verified_cost_bps'],engine_sha256=state['engine_sha256'],intrabar_adapter_sha256=state['intrabar_adapter_sha256'],
                    observed_at_ms=current_ms,lifecycle_state='FINALIZED_PENDING_G5A_ECONOMIC_ACCOUNTING',duplicate=False,censored=False,unknown_exit=unknown,
                    intrabar_witness_required=t['exit_reason']=='PROTECTIVE_STOP_INTRABAR',intrabar_witness_present=(cid in witness_known or t['exit_reason']!='PROTECTIVE_STOP_INTRABAR'),g5a_economic_credit=False,**AUTHORITY));final_known.add(cid);nf+=1
    return ns,nf

def run(state:dict[str,Any]|None,events:list[dict[str,Any]],current_ms:int)->tuple[dict[str,Any],list[dict[str,Any]],dict[str,Any]]:
    c=read(CONTRACT_PATH);validate_contract(c);validate_chain(events)
    rows_by={s:fetch_4h(s,current_ms) for s in SYMBOLS}
    auth=ev.load_json(COST_PATH)
    if auth.get('state')!='FROZEN_REALISTIC_PUBLIC_BINGX_COST_AUTHORITY':raise RuntimeError('Q0_COST_AUTHORITY_INVALID')
    if state is None:state=make_state(c,current_ms,rows_by,auth)
    else:validate_state(state,c)
    es=deepcopy(state['engine_state']);all_witnesses=[];new_batches=0
    maps={s:{int(r['bar_open_ts']):r for r in rows_by[s]} for s in SYMBOLS}
    latest_common_close=min(max((int(r['bar_close_ts']) for r in rows_by[s]),default=0) for s in SYMBOLS)
    while int(es['cursor_close_ts'])+BAR_MS<=latest_common_close and int(es['cursor_close_ts'])<int(es['end']):
        open_ts=int(es['cursor_close_ts']);batch={}
        for symbol in SYMBOLS:
            row=maps[symbol].get(open_ts)
            if row is None:raise RuntimeError('Q0_4H_SOURCE_GAP:'+symbol+':'+str(open_ts))
            batch[symbol]=deepcopy(row)
        before=deepcopy(es);after=engine.advance(es,batch)
        needs=[]
        for symbol in SYMBOLS:
            prior_n=len(before['by_symbol'][symbol]['trades'])
            for t in after['by_symbol'][symbol]['trades'][prior_n:]:
                if t.get('exit_reason')=='PROTECTIVE_STOP_INTRABAR':needs.append(symbol)
        minute={symbol:fetch_1m(symbol) for symbol in sorted(set(needs))}
        after,w=intrabar.repair_new_intrabar_trades(before,after,batch,rows_by,minute)
        all_witnesses.extend(w);es=after;new_batches+=1
    state['engine_state']=es
    ns,nf=_append_new_journal(state,events,rows_by,all_witnesses,current_ms)
    snap=engine.snapshot(es)
    state['signal_T']=sum(1 for x in events if x.get('kind')=='SIGNAL_CAPTURED')
    state['finalized_T']=sum(1 for x in events if x.get('kind')=='LIFECYCLE_FINALIZED')
    state['event_T']=len(events)
    state['unknown_exit_T']=sum(1 for x in events if x.get('kind')=='LIFECYCLE_FINALIZED' and x.get('unknown_exit'))
    state['censored_open_T']=sum(len(snap[s]['open_positions']) for s in SYMBOLS)
    state['last_scanned_closed_4h_ms']=int(es['cursor_close_ts'])
    state=seal_state(state)
    status=dict(state=state['state'],boundary_ms=state['boundary_ms'],new_batches=new_batches,new_signals=ns,new_finalized=nf,signal_T=state['signal_T'],finalized_T=state['finalized_T'],
                unknown_exit_T=state['unknown_exit_T'],censored_open_T=state['censored_open_T'],formal_credit=0,g5a_economic_completed_T=0,
                next='ACCUMULATE_FUTURE_ONLY_FINALIZED_LIFECYCLES_THEN_RUN_SEPARATE_G5A_ECONOMIC_ACCOUNTING',**{k:v for k,v in AUTHORITY.items() if k!='formal_credit'})
    return state,events,status

def self_test()->int:
    c=read(CONTRACT_PATH);validate_contract(c);rows=[];append(rows,dict(event_id='x',kind='TEST',campaign_id='c'));validate_chain(rows)
    assert int(c['qualification_boundary_ms'])==1789257600000 and int(c['collection_end_ms'])==1799625600000
    assert c['historical_backfill'] is False and c['source']['post_stop_HLC_in_crossing_minute_used_for_MFE_MAE'] is False
    print('PASS_Q0_CONVEX_G5A_COLLECTOR_V1');return 0

def main()->int:
    ap=argparse.ArgumentParser();ap.add_argument('--self-test',action='store_true');ap.add_argument('--out-dir');args=ap.parse_args()
    if args.self_test:return self_test()
    state=read(STATE_PATH) if STATE_PATH.exists() else None;events=read_events(EVENTS_PATH);s,e,status=run(state,events,now_ms())
    out=Path(args.out_dir or ROOT/'out');out.mkdir(parents=True,exist_ok=True)
    write_json(out/'g5_q0_convex_state_v1.json',s);write_events(out/'g5_q0_convex_events_v1.jsonl',e);write_json(out/'g5_q0_convex_status_v1.json',status)
    print(json.dumps(status,sort_keys=True));return 0

if __name__=='__main__':raise SystemExit(main())
