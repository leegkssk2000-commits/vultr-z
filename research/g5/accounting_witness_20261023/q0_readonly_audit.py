#!/usr/bin/env python3
"""Read-only Q0 archive witness and frozen-model arithmetic; no collector/replay.

Native scalar functions are AST-loaded without executing their modules, preventing
source access or policy-entry side effects. Independent arithmetic uses Decimal
and enumerates settlements. Model outcomes are never formal G5/account returns.
"""
from __future__ import annotations
import argparse
import ast
import hashlib
import json
import math
import platform
import sys
import types
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

SOURCE_SHA = 'dd59cdb4fa5d6347cb40f55c8e014ef790c0fe63'
BASE = 'backend/research/rebuild/'
INPUTS = [
    BASE+'g5_q0_convex_state_v1.json', BASE+'g5_q0_convex_events_v1.jsonl',
    BASE+'g5_q0_convex_collector_v1.py', BASE+'q0_prospective_engine_v1.py',
    BASE+'q0_convex_intrabar_adapter_v1.py', BASE+'q0_prospective_accounting_v1.py',
    BASE+'break_channel_source_v1.py', BASE+'top5_development_repair_v1.py',
    BASE+'a1_rebuilt_bb_revert_evaluator_v1.py',
    'backend/research/architecture_factory/g5a_development_probe_v1.py',
    'backend/research/architecture_factory/g5a_stage_candidate_v1.py',
    'backend/research/contracts/q0_convex_g5a_collector_v1.json',
    'research/g5/TOP5_G5A_PHASE1_STATUS_V1.json',
]

def stable(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False,default=str).encode()).hexdigest()

def sha(value):
    return hashlib.sha256(value).hexdigest()

def load_function(text, name, namespace):
    node=next(n for n in ast.parse(text).body if isinstance(n,ast.FunctionDef) and n.name==name)
    exec(compile(ast.Module(body=[node],type_ignores=[]),'<native:'+name+'>','exec'),namespace)
    return namespace[name]

def metric(rows, key):
    grouped=defaultdict(float)
    for row in rows: grouped[row['exit_ts']]+=row[key]
    positive=sum(max(0.,r[key]) for r in rows)
    negative=-sum(min(0.,r[key]) for r in rows)
    total=peak=dd=0.;streak=max_streak=0
    for _,value in sorted(grouped.items()):
        total+=value;peak=max(peak,total);dd=max(dd,peak-total)
        streak=streak+1 if value<0 else 0;max_streak=max(max_streak,streak)
    return dict(T=len(rows),sum_trade_bps=sum(r[key] for r in rows),
                mean_trade_bps=sum(r[key] for r in rows)/len(rows) if rows else None,
                PF=positive/negative if negative else None,
                WR_percent=100*sum(r[key]>0 for r in rows)/len(rows) if rows else None,
                realized_closed_group_DD_trade_bps=dd,
                max_negative_exit_group_streak=max_streak,
                account_DD_percent=None,
                worst_trade_bps=min((r[key] for r in rows),default=None),
                ordinary_winner_retention=None,large_winner_retention=None)

def build(root, extra=None):
    root=Path(root);extra=Path(extra) if extra else root
    blobs={p:((root/p) if (root/p).exists() else (extra/p)).read_bytes() for p in INPUTS}
    state=json.loads(blobs[INPUTS[0]])
    events=[json.loads(x) for x in blobs[INPUTS[1]].decode().splitlines() if x.strip()]
    contract=json.loads(blobs['backend/research/contracts/q0_convex_g5a_collector_v1.json'])
    monitor=json.loads(blobs['research/g5/TOP5_G5A_PHASE1_STATUS_V1.json'])['lanes']['Q0 Convex Channel Breakout']
    errors=[]
    check=lambda condition,label: errors.append(label) if not condition else None
    core=dict(state);seal=core.pop('state_sha256')
    check(stable(core)==seal,'STATE_INTERNAL_HASH')
    check(sha(blobs[INPUTS[0]])==monitor['state_sha256'],'MONITOR_STATE_FILE_HASH')
    check(sha(blobs['backend/research/contracts/q0_convex_g5a_collector_v1.json'])==state['contract_sha256'],'CONTRACT_HASH')
    check(state['boundary_ms']==contract['qualification_boundary_ms'],'BOUNDARY')
    check(state['cost_freeze_observed_at_ms']<state['boundary_ms'],'COST_FREEZE_BEFORE_BOUNDARY')
    for field,path in [('engine_sha256',BASE+'q0_prospective_engine_v1.py'),('intrabar_adapter_sha256',BASE+'q0_convex_intrabar_adapter_v1.py')]:
        check(state[field]==sha(blobs[path]),field)
    prev=None;ids=set();source_rows=defaultdict(dict);context_gaps=0;source_conflicts=0
    for index,event in enumerate(events):
        core=dict(event);seal=core.pop('record_sha256')
        check(stable(core)==seal,f'EVENT_HASH:{index}')
        check(event['seq']==index and event['prev_sha256']==prev,f'EVENT_CHAIN:{index}')
        check(event['event_id'] not in ids,f'EVENT_DUPLICATE:{index}')
        check(event['rule_id']==contract['rule_id'],f'EVENT_RULE:{index}')
        prev=seal;ids.add(event['event_id'])
        if event['kind']=='SIGNAL_CAPTURED':
            rows=event['source_context_rows']
            check(stable(rows)==event['source_context_sha256'],f'CONTEXT_HASH:{index}')
            check(len(rows)==18,f'CONTEXT_SIZE:{index}')
            check(all(r['bar_close_ts']<=event['signal_ts'] for r in rows),f'CONTEXT_FUTURE:{index}')
            context_gaps+=sum(b['bar_open_ts']!=a['bar_close_ts'] for a,b in zip(rows,rows[1:]))
            for row in rows:
                old=source_rows[event['symbol']].get(row['bar_open_ts'])
                source_conflicts+=old is not None and old!=row
                source_rows[event['symbol']][row['bar_open_ts']]=row
    check(context_gaps==0,'SIGNAL_CONTEXT_GAPS')
    check(source_conflicts==0,'SOURCE_REVISIONS_CONFLICT')
    for symbol,item in state['cost_models'].items():
        check(stable(item['model'])==item['model_sha256'],'COST_HASH:'+symbol)
    raw={(symbol,t['signal_ts']):t for symbol,item in state['engine_state']['by_symbol'].items() for t in item['trades']}
    final=[e for e in events if e['kind']=='LIFECYCLE_FINALIZED']
    signals=[e for e in events if e['kind']=='SIGNAL_CAPTURED']
    witnesses={e['campaign_id']:e for e in events if e['kind']=='INTRABAR_STOP_WITNESS'}
    check(len(events)==state['event_T'],'EVENT_COUNT')
    check(len(signals)==state['signal_T']==monitor['fresh_signal_T'],'SIGNAL_COUNT')
    check(len(raw)==len(final)==state['finalized_T']==monitor['fresh_closed_T'],'FINALIZED_COUNT')
    check(len({(e['symbol'],e['signal_ts']) for e in final})==len(final),'FINALIZED_DUPLICATE')
    ns={'__builtins__':__builtins__,'math':math}
    boundaries=load_function(blobs[BASE+'a1_rebuilt_bb_revert_evaluator_v1.py'].decode(),'expected_funding_boundaries',ns)
    module_name='backend.research.rebuild.a1_rebuilt_bb_revert_evaluator_v1'
    original_module=sys.modules.get(module_name)
    isolated_module=types.ModuleType(module_name);isolated_module.expected_funding_boundaries=boundaries
    sys.modules[module_name]=isolated_module
    native_cost=load_function(blobs['backend/research/architecture_factory/g5a_stage_candidate_v1.py'].decode(),'development_cost',ns)
    ns['parent']=types.SimpleNamespace(development_cost=native_cost)
    parts=load_function(blobs['backend/research/architecture_factory/g5a_development_probe_v1.py'].decode(),'cost_components',ns)
    intrabar_ns={'__builtins__':__builtins__,'Sequence':list,'Mapping':dict,'Any':object,'MINUTE_MS':60_000,'BAR_MS':14_400_000}
    normalize=load_function(blobs[BASE+'q0_convex_intrabar_adapter_v1.py'].decode(),'normalize_minute_rows',intrabar_ns)
    first_cross=load_function(blobs[BASE+'q0_convex_intrabar_adapter_v1.py'].decode(),'first_cross',intrabar_ns)
    trade_rows=[];stop_checks=[];arithmetic_diffs=[];missing_entry=[];missing_exit=[];missing_held=0
    for event in final:
        key=(event['symbol'],event['signal_ts']);t=raw[key];symbol=key[0]
        check(stable(t)==event['raw_lifecycle_sha256'],'RAW_LIFECYCLE_HASH:'+event['campaign_id'])
        check(state['boundary_ms']<=t['signal_ts']<=t['entry_ts']<=t['exit_ts']<=state['last_scanned_closed_4h_ms'],'CLOCK:'+event['campaign_id'])
        for name in ['entry_ts','exit_ts','entry_price','exit_price','gross_bps','mfe_bps','mae_bps']:
            check(event[name]==t[name],name+':'+event['campaign_id'])
        model=state['cost_models'][symbol]
        check(event['cost_model_sha256']==model['model_sha256'],'TRADE_COST_HASH:'+event['campaign_id'])
        calc=(t['exit_price']/t['entry_price']-1)*10000
        check(math.isclose(calc,t['gross_bps'],abs_tol=1e-9),'GROSS:'+event['campaign_id'])
        native_parts=parts(t['entry_ts'],t['exit_ts'],model['model'])
        native_charge=max(20.,native_parts['cost_bps'])
        independent_settlements=list(range((t['entry_ts']//28_800_000+1)*28_800_000,t['exit_ts']+1,28_800_000))
        m={k:Decimal(str(v)) for k,v in model['model'].items()}
        independent_cost=max(Decimal(20),m['fee_bps']+m['spread_bps']+m['impact_bps']+len(independent_settlements)*m['funding_p95_per_settlement_bps'])
        difference=float(independent_cost)-native_charge;arithmetic_diffs.append(abs(difference))
        check(abs(difference)<1e-10,'COST_ARITHMETIC:'+event['campaign_id'])
        check(len(independent_settlements)==native_parts['funding_settlements_crossed'],'SETTLEMENT_ARITHMETIC:'+event['campaign_id'])
        entry_row=source_rows[symbol].get(t['entry_ts'])
        if entry_row is None: missing_entry.append(event['campaign_id'])
        else: check(entry_row['open']==t['entry_price'],'ENTRY_OPEN_SOURCE:'+event['campaign_id'])
        held=list(range(t['entry_ts'],t['exit_ts']//14_400_000*14_400_000,14_400_000))
        missing_held+=sum(ts not in source_rows[symbol] for ts in held)
        if event['intrabar_witness_required']:
            check(event['campaign_id'] in witnesses,'STOP_WITNESS_MISSING:'+event['campaign_id'])
            w=witnesses[event['campaign_id']]['witness'];minutes=w['full_stop_bar_1m_rows']
            normalized=normalize(minutes,w['exit_4h_bar_open_ts'],w['exit_4h_bar_close_ts'])
            cross_idx,cross=first_cross(normalized,t['entry_stop_price'])
            fill=cross['open'] if cross['open']<=t['entry_stop_price'] else t['entry_stop_price']
            exit_ts=cross['bar_open_ts'] if cross['open']<=t['entry_stop_price'] else cross['bar_close_ts']
            core=dict(w);sealed=core.pop('witness_sha256');core.pop('symbol')
            # Native resolve_trade seals the witness before repair_new_intrabar_trades adds symbol.
            check(stable(core)==sealed,'WITNESS_NATIVE_SEAL:'+event['campaign_id'])
            check(stable(minutes)==w['full_stop_bar_1m_rows_sha256']==t['intrabar_witness_sha256'],'MINUTE_ROWS_HASH:'+event['campaign_id'])
            check(cross_idx==w['first_cross_index'] and cross==w['first_cross'],'FIRST_CROSS:'+event['campaign_id'])
            check(fill==w['fill_price']==t['exit_price'] and exit_ts==w['resolved_exit_ts']==t['exit_ts'],'STOP_FILL_TIME:'+event['campaign_id'])
            check(stable(cross)==t['intrabar_first_cross_row_sha256'],'CROSS_HASH:'+event['campaign_id'])
            stop_checks.append(dict(campaign_id=event['campaign_id'],rows_T=len(minutes),gaps=0,duplicate_minutes=0,
                                   cross_index=cross_idx,resolution_ms=0 if cross['open']<=t['entry_stop_price'] else 60_000,
                                   settlement_on_cross_upper_bound=t['exit_ts']%28_800_000==0,
                                   source_observed_at_ms=witnesses[event['campaign_id']]['observed_at_ms']))
        else:
            exit_row=source_rows[symbol].get(t['exit_ts'])
            if exit_row is None:missing_exit.append(event['campaign_id'])
            else:check(exit_row['open']==t['exit_price'],'EXIT_OPEN_SOURCE:'+event['campaign_id'])
        trade_rows.append(dict(campaign_id=event['campaign_id'],symbol=symbol,signal_ts=t['signal_ts'],entry_ts=t['entry_ts'],exit_ts=t['exit_ts'],
                               exit_reason=t['exit_reason'],gross_bps=calc,fee_bps=native_parts['fee_bps'],spread_bps=native_parts['spread_bps'],impact_bps=native_parts['impact_bps'],
                               modeled_funding_p95_bps=native_parts['funding_bps'],modeled_settlements=len(independent_settlements),
                               frozen_floor_reserve_bps=native_charge-native_parts['cost_bps'],model_cost_bps=native_charge,
                               model_net1x_bps=calc-native_charge,model_net2x_bps=calc-2*native_charge,
                               actual_signed_funding_bps=None,actual_fee_bps=None,actual_fill_verified=False,
                               entry_open_source_archived=entry_row is not None,raw_lifecycle_sha256=event['raw_lifecycle_sha256']))
    if original_module is None:sys.modules.pop(module_name,None)
    else:sys.modules[module_name]=original_module
    signal_status=Counter(e['status'] for item in state['engine_state']['by_symbol'].values() for e in item['events'])
    signal_latency=[e['observed_at_ms']-e['signal_ts'] for e in signals]
    finish_latency=[e['observed_at_ms']-e['exit_ts'] for e in final]
    return dict(schema='zel.g5.q0.readonly_accounting_witness.v1',source_sha=SOURCE_SHA,
        identity=contract['rule_id'],boundary_ms=state['boundary_ms'],last_scanned_closed_4h_ms=state['last_scanned_closed_4h_ms'],
        state_path=INPUTS[0],state_sha256=sha(blobs[INPUTS[0]]),event_path=INPUTS[1],event_sha256=sha(blobs[INPUTS[1]]),
        input_manifest=[dict(path=p,sha256=sha(b),bytes=len(b)) for p,b in blobs.items()],
        environment=dict(python=platform.python_version(),platform=platform.platform()),
        method='EXISTING_NATIVE_SCALAR_COST_COMPONENTS_PLUS_INDEPENDENT_DECIMAL_SETTLEMENT_ENUMERATION; NO_STRATEGY_REPLAY',
        integrity=dict(state_and_event_chain_errors=errors,monitor_state_hash_matches=sha(blobs[INPUTS[0]])==monitor['state_sha256'],
            context_gaps=context_gaps,source_conflicting_revisions=source_conflicts,duplicate_event_ids=len(events)-len(ids),
            full_holding_4h_continuity='NOT_PROVEN_ARCHIVE_INCOMPLETE',missing_held_4h_rows_count=missing_held,
            missing_entry_4h_source_T=len(missing_entry),missing_nonstop_exit_4h_source_T=len(missing_exit),
            missing_entry_campaign_ids=missing_entry,missing_nonstop_exit_campaign_ids=missing_exit,
            cost_arithmetic_max_abs_diff_bps=max(arithmetic_diffs,default=0)),
        counts=dict(signal_T=len(signals),raw_closed_T=len(raw),finalized_event_T=len(final),closed_verified_ledger_T=len(trade_rows),
            closed_fully_source_and_actual_cost_verified_T=0,stop_witness_T=len(stop_checks),minute_rows_verified=sum(x['rows_T'] for x in stop_checks),
            open_T=sum(item['position'] is not None for item in state['engine_state']['by_symbol'].values()),
            pending_entry_T=sum(item['pending_entry'] is not None for item in state['engine_state']['by_symbol'].values()),
            censored_open_T=state['censored_open_T'],unknown_exit_T=state['unknown_exit_T'],engine_signal_status_counts=dict(signal_status)),
        source_timing=dict(signal_journal_lag_ms_min=min(signal_latency),signal_journal_lag_ms_max=max(signal_latency),
            finalized_journal_lag_ms_min=min(finish_latency),finalized_journal_lag_ms_max=max(finish_latency),
            source_receive_timestamps=None,latency_interpretation='JOURNAL_OBSERVED_AT_MINUS_EVENT_TIME; NOT_ORDER_OR_NETWORK_DELIVERY_LATENCY'),
        stop_witness_checks=stop_checks,trade_rows=trade_rows,
        model_diagnostic=None if errors else dict(basis='FROZEN_PUBLIC_SNAPSHOT_FEE_SPREAD_IMPACT_PLUS_P95_FUNDING_RESERVE_20BPS_FLOOR',
            unit='EQUAL_NOTIONAL_SUM_OF_TRADE_BPS_NOT_ACCOUNT_RETURN',cost1x_total_bps=sum(x['model_cost_bps'] for x in trade_rows),
            cost2x_total_bps=2*sum(x['model_cost_bps'] for x in trade_rows),gross=metric(trade_rows,'gross_bps'),
            cost1x=metric(trade_rows,'model_net1x_bps'),cost2x=metric(trade_rows,'model_net2x_bps'),
            actual_funding_available=False,actual_account_fee_available=False,actual_fill_available=False),
        official_accounting=dict(status='G5_ACCOUNTING_INPUT_BLOCKED',first_field=errors[0] if errors else 'entry_source_4h_open_row',
            reason='INTEGRITY_FAILURE' if errors else str(len(missing_entry))+' of '+str(len(raw))+' entry opens have no original 4h source row in this exact native state/event archive; collector prices are not independent source proof.',
            further_missing=['full_held_4h_source_path','native_source_received_at_ms','actual_signed_funding_settlements','actual_account_fee_and_fill_receipts'],
            net1x_bps=None,net2x_bps=None,PF=None,WR_percent=None,account_DD_percent=None),
        authority=dict(formal_pass_authority=False,g5a_rows_reusable_for_g5b=False,formal_credit=0,orders='BLOCKED',collector_invocations=0,economic_heavy_runs=0),
        limitations=['Frozen scenario costs are genuine stored model parameters, not paid exchange charges.',
            'All ten stop timestamps are first-cross minute upper bounds; no subminute execution claim.',
            'Q0 prospective accounting build additionally needs full source rows and its own locked B entry observations; unrelated Q0_FROZEN archive is not this G5 lane.',
            'Loss streak groups all trades at identical exit timestamps; no arbitrary intra-group order.'])

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',required=True);ap.add_argument('--extra-root');ap.add_argument('--out',required=True);args=ap.parse_args()
    report=build(args.root,args.extra_root)
    Path(args.out).write_text(json.dumps(report,indent=2,sort_keys=True,allow_nan=False)+'\n')
    print(json.dumps({k:report[k] for k in ['counts','integrity','model_diagnostic','official_accounting']},sort_keys=True))

if __name__=='__main__':main()
