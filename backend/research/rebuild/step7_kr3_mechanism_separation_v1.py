"""Finite DEV diagnostics of wait/recheck/reference/exit-anchor mechanisms.

Not a new selectable strategy. Frozen KR3 and all old results remain immutable.
The four preregistered full chronological policies telescope along one explicit
ordering; effects include interactions and are not universal causal estimates.
No prices, outcomes, credentials, OOS or network are loaded at module import.
"""
from __future__ import annotations
import argparse
from collections import Counter
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import asdict, dataclass
import gzip
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch

from backend.research.rebuild import step7_kr3_dev_validation_v1 as old
native, account = old.native, old.account
kr3, d, reservation = native.kr3, native.d, native.reservation
m2 = native.m2
BAR, HOLD = native.BAR, 12
UNCHECKED, SUPPRESSED, ALLOWED = kr3.UNCHECKED, kr3.SUPPRESSED, kr3.ALLOWED
decide, DECISION, TRIGGER, EXIT = kr3.decide, kr3.DECISION, kr3.TRIGGER, kr3.EXIT
canonical, sha = native.canonical, native.sha
ROOT = Path(__file__).resolve().parents[3]
SCOPE = 'KR3_TIMING_REQUAL_OCCUPANCY_AFTER_PR1212_V1'
CANDIDATE = old.CANDIDATE
CAMPAIGN = 'research/development_evidence/ZEL_PARENT_CLOSURE_TO_G5_SURVIVOR'
OUTPUT = CAMPAIGN + '/MECHANISM_SEPARATION'
BUDGET = CAMPAIGN + '/BUDGET.json'
INHERITED_BUDGET_SHA256 = '1214f044b6529d3baee130b235ab071bc79458d64c8281223203451853fb175f'

@dataclass(frozen=True)
class Mode:
    id: str
    delay: int
    recheck: bool
    reference_anchor: str
    exit_anchor: str
    require_origin_half: bool = True

MODES = (
    Mode('W6_ORIGINAL_REFERENCE', 6, False, 'ORIGIN', 'ORIGIN'),
    Mode('W6_RECHECK_ORIGINAL_REFERENCE', 6, True, 'ORIGIN', 'ORIGIN'),
    Mode('W6_RECHECK_SHIFTED_REFERENCE', 6, True, 'SHIFTED', 'ORIGIN'),
    Mode('W6_RECHECK_SHIFTED_EXIT_ANCHOR', 6, True, 'SHIFTED', 'SHIFTED'),
)


def held_geometry(rows, signal, last_held_index, end):
    # Only bars AFTER actual entry contribute to held excursions. Signal/low/
    # clock ancestry is distinct from execution geometry, never retroactive.
    decision = signal['decision_index']
    value = d._geometry(rows, decision, last_held_index, end)
    origin = signal['origin_index']
    value.update(signal_index=origin, signal_ts=rows[origin]['bar_close_ts'],
                 original_signal_index=origin,
                 decision_index=decision, decision_ts=rows[decision]['bar_close_ts'],
                 feature_available_ts=rows[decision]['bar_close_ts'],
                 exit_anchor_index=signal['exit_anchor_index'])
    return value

def anchored_path(rows, signal, ema20, ema50, end):
    i = signal['exit_anchor_index']; ei = signal['decision_index'] + 1; native_exit = i + HOLD
    signal_low = float(rows[i]['low'])
    entry_price = float(rows[ei]['open'])
    extension = {'decided': False, 'allowed': False}
    final_exit = native_exit
    trace = [{'kind': 'ENTRY_NEXT_OPEN', 'signal_index': i, 'index': ei,
              'ts': rows[ei]['bar_open_ts'], 'price': rows[ei]['open'],
              'frozen_signal_low': signal_low, 'feature_available_ts': rows[i]['bar_close_ts']}]
    pending = None
    state = {"status": UNCHECKED}
    for j in range(ei, min(i + 2 * HOLD, len(rows) - 1) + 1):
        row = rows[j]
        # A pending prior-close order is filled at the next open below, before
        # consulting that next bar's high/low/close or its later timeout.
        if j == final_exit:
            if row['bar_close_ts'] < end:
                raw = held_geometry(rows, signal, j, end)
                trace.append({'kind': 'RUNNER_FINAL_TIME_STOP_CLOSE' if extension['allowed'] else 'ORIGINAL_TIME_STOP_CLOSE', 'signal_index': i,
                              'index': j, 'ts': raw['exit_ts'], 'price': raw['exit_price']})
                raw["low_exit_state"] = deepcopy(state)
                raw['runner_extension'] = deepcopy(extension)
                return raw, None, trace
            break
        ema_hit = ema20[j] <= ema50[j]
        low_hit = float(row['close']) < signal_low
        if not ema_hit and state['status'] == UNCHECKED and low_hit:
            state = decide(state, row, j, signal_low, ema50[j])
            trace.append({'kind': m2.DECISION, 'signal_index': i, **deepcopy(state)})
        active_low = low_hit and state['status'] == ALLOWED
        runner_hit = extension['allowed'] and j >= native_exit and float(row['close']) <= ema20[j]
        if not (ema_hit or active_low or runner_hit):
            if j == native_exit - 1:
                allowed = state['status'] != SUPPRESSED and float(row['close']) > entry_price and float(row['close']) > ema20[j] > ema50[j]
                extension = {'decided': True, 'allowed': allowed, 'index': j,
                    'ts': row['bar_close_ts'], 'observed_close': row['close'],
                    'entry_price': entry_price, 'ema20': ema20[j], 'ema50': ema50[j],
                    'm2_state_at_decision': state['status']}
                trace.append({'kind': DECISION, 'signal_index': i, **deepcopy(extension)})
                if allowed:
                    final_exit = i + 2 * HOLD
            continue
        pending = {'signal_ts': row['bar_close_ts'], 'signal_index': j,
                   'ema20': ema20[j], 'ema50': ema50[j],
                   'signal_low': signal_low, 'observed_close': row['close'],
                   'low_condition': low_hit, 'ema_condition': ema_hit, 'runner_condition': runner_hit}
        # Existing D priority wins when both conditions become known together.
        reason = 'EMA20_NOT_ABOVE_EMA50_NEXT_OPEN' if ema_hit else m2.EXIT if active_low else EXIT
        kind = 'TREND_INVALIDATION_CLOSE' if ema_hit else m2.TRIGGER if active_low else TRIGGER
        trace.append({'kind': kind, 'signal_index': i, 'index': j,
                      'ts': row['bar_close_ts'], **pending})
        # Preserve original entry origin separately from trigger source index.
        trace[-1]['signal_index'] = i
        xi = j + 1
        if xi >= len(rows) or rows[xi]['bar_open_ts'] >= end:
            break
        raw = held_geometry(rows, signal, j, end)
        price = float(rows[xi]['open'])
        gross = (price / raw['entry_price'] - 1.) * 10000.
        raw.update(exit_index=xi, exit_ts=rows[xi]['bar_open_ts'], exit_price=price,
                   gross_bps=gross, hold_ms=rows[xi]['bar_open_ts'] - raw['entry_ts'],
                   mfe_bps=max(raw['mfe_bps'], gross, 0.), mae_bps=min(raw['mae_bps'], gross, 0.),
                   exit_reason=reason, exit_timestamp_semantics='OBSERVED_4H_OPEN',
                   excursion_semantics='HELD_COMPLETE_BARS_PLUS_EXIT_OPEN_ONLY',
                   exit_trigger=deepcopy(pending), frozen_signal_low=signal_low)
        trace.append({'kind': reason, 'signal_index': i, 'index': xi,
                      'ts': raw['exit_ts'], 'price': price})
        raw["low_exit_state"] = deepcopy(state)
        raw["runner_extension"] = deepcopy(extension)
        return raw, None, trace
    raw = held_geometry(rows, signal, len(rows)-1, end)
    for a, b in (('exit_index','mark_index'), ('exit_ts','mark_ts'),
                 ('exit_price','mark_price'), ('gross_bps','gross_mark_bps')):
        raw[b] = raw.pop(a)
    raw.update(status='CENSORED', terminal_liquidation=False, native_hold_bars=HOLD,
        native_planned_exit_ts=rows[i]['bar_close_ts'] + HOLD*BAR,
        original_protective_sl=None,
        native_geometry_scope='FROZEN_V2_FIXED_HOLD_NO_NATIVE_SL_SPECIFIED',
        censor_reason='ORIGINAL_STRICT_END_TIMEOUT_AT_BOUNDARY' if final_exit==len(rows)-1 else 'NATIVE_HOLD_UNFINISHED',
        pending_exit_signal_ts=pending['signal_ts'] if pending else None,
        pending_exit_trigger=deepcopy(pending), frozen_signal_low=signal_low)
    trace.append({'kind':'TERMINAL_MARK', 'signal_index':i, 'index':raw['mark_index'],
        'ts':raw['mark_ts'], 'price':raw['mark_price'], 'censor_reason':raw['censor_reason'],
        'pending_exit_signal_ts':raw['pending_exit_signal_ts']})
    raw["low_exit_state"] = deepcopy(state)
    raw["runner_extension"] = deepcopy(extension)
    raw["runner_planned_exit_index"] = final_exit
    return None, raw, trace



def replay_symbol(rows, bundle, mode, *, start, end):
    """All raw origins, streamed reference clock and next-open actual position.

    ORIGIN reference: latch eligibility at source close, reserve as originally,
    then at the delayed close cancel if that reference has expired or already
    observed an EMA exit. SHIFTED reference: no reference during waiting; reserve
    at the delayed close. Both retain at most one actual position. Rejection
    never releases a ghost reference and never cancels an earlier real entry.
    """
    d.replay(rows, bundle, eval_start_ms=start, eval_end_ms=end,
             enable_change=True, fixed_signal_indices=[])
    if mode.delay < 0 or mode.delay >= HOLD-1:
        raise ValueError('DELAY_BEFORE_EXTENSION_DECISION_REQUIRED')
    originals = {s['signal_index']:s for s in bundle['signals']}
    scheduled, events, traces = {}, {}, []
    trades, opened = [], []
    clock = reservation.initial_clock(eval_start_ms=start, eval_end_ms=end)
    last_actual_exit = -1
    tail_open = False
    original_observer = reservation.n.entry_observation
    for j, row in enumerate(rows):
        # Known source signals are latched on this completed bar, not selected
        # from the baseline's admitted trades or subsequent profit labels.
        if j in originals:
            original_half = original_observer(row)[reservation.n.FEATURE]
            ev = {**originals[j], 'original_signal_index':j,
                  'origin_half':original_half, 'origin_known_at':row['bar_close_ts'],
                  'decision_index':j+mode.delay, 'decision_ts':None,
                  'admission':False, 'status':'WAITING', 'exclusion_reason':None,
                  'reference_created':False}
            events[j] = ev
            scheduled[j+mode.delay] = j
        ready_origin = scheduled.get(j)
        clock_signal = originals.get(j) if mode.reference_anchor == 'ORIGIN' else (
            {'signal_index':j, 'signal_ts':row['bar_close_ts']}
            if ready_origin is not None and row['bar_close_ts'] < end else None)
        if mode.reference_anchor == 'SHIFTED' and clock_signal is not None:
            origin_pass = events[ready_origin]['origin_half'] or not mode.require_origin_half
            def observer(current):
                value = original_observer(current)
                value[reservation.n.FEATURE] = origin_pass and (
                    value[reservation.n.FEATURE] or not mode.recheck)
                return value
            with patch.object(reservation.n, 'entry_observation', observer):
                reservation.advance_clock(clock,row,index=j,ema20=bundle['ema20'][j],
                                          ema50=bundle['ema50'][j],signal=clock_signal)
        else:
            reservation.advance_clock(clock,row,index=j,ema20=bundle['ema20'][j],
                                      ema50=bundle['ema50'][j],signal=clock_signal)
        if mode.reference_anchor == 'ORIGIN' and j in originals:
            known = clock['opportunity_events'][-1]
            ev = events[j]
            ev['reference_created'] = known['reservation_created']
            ev['origin_reference_admitted'] = known['admission']
            if not known['admission']:
                ev.update(status='EXCLUDED', exclusion_reason=known['exclusion_reason'],
                          exclusion_known_at=row['bar_close_ts'])
        if ready_origin is None:
            continue
        ev = events[ready_origin]
        if ev['status'] != 'WAITING':
            continue
        ev['decision_ts'] = row['bar_close_ts']
        ev['recheck_half'] = original_observer(row)[reservation.n.FEATURE]
        ev['recheck_known_at'] = row['bar_close_ts']
        reason = None
        if row['bar_close_ts'] >= end or j+1 >= len(rows):
            reason = 'NO_DELAYED_NEXT_OPEN_IN_CALENDAR'
        elif mode.reference_anchor == 'ORIGIN':
            k = clock['active_opportunity_offset']
            active = None if k is None else clock['reference_opportunities'][k]
            if active is None or active['reference_signal_index'] != ready_origin:
                reason = 'WAIT_REFERENCE_EXPIRED'
            elif active['phase'] not in ('HELD','PENDING_ENTRY_NEXT_OPEN'):
                reason = 'WAIT_REFERENCE_EXIT_ALREADY_OBSERVED'
            elif mode.recheck and not ev['recheck_half']:
                reason = 'DELAYED_HALF_RECHECK_FAILED'
        else:
            known = clock['opportunity_events'][-1]
            ev['reference_created'] = known['reservation_created']
            ev['shifted_reference_signal_index'] = j
            if not known['admission']:
                reason = known['exclusion_reason']
                if reason == reservation.n.VETO_REASON:
                    reason = ('ORIGIN_HALF_FAILED' if mode.require_origin_half and not ev['origin_half']
                              else 'DELAYED_HALF_RECHECK_FAILED')
        if reason is None and (tail_open or row['bar_close_ts'] <= last_actual_exit):
            reason = 'RUNNER_OCCUPIED_AT_DELAYED_DECISION'
        if reason is not None:
            ev.update(status='EXCLUDED',exclusion_reason=reason,
                      exclusion_known_at=row['bar_close_ts'])
            continue
        signal = {'origin_index':ready_origin, 'decision_index':j,
                  'exit_anchor_index':ready_origin if mode.exit_anchor == 'ORIGIN' else j}
        closed, censored, trace = anchored_path(rows,signal,bundle['ema20'],bundle['ema50'],end)
        for t in trace:
            t.update(original_signal_index=ready_origin,decision_index=j,
                     exit_anchor_index=signal['exit_anchor_index'])
        traces.extend(trace)
        value = closed if closed is not None else censored
        value.update(initial_protective_sl=None,tp=None,risk_R=None,
                     waiting_observed_bars=mode.delay,
                     waiting_elapsed_ms=row['bar_close_ts']-rows[ready_origin]['bar_close_ts'])
        ev.update(admission=True,status='COMPLETED' if closed is not None else 'CENSORED')
        if closed is not None:
            trades.append(closed);last_actual_exit=closed['exit_ts']
        else:
            opened.append(censored);tail_open=True
    for ev in events.values():
        if ev['status']=='WAITING':
            ev.update(status='EXCLUDED',exclusion_reason='PENDING_WAIT_AT_END',
                      exclusion_known_at=end)
    rows_events = [events[k] for k in sorted(events)]
    excluded = sum(e['status']=='EXCLUDED' for e in rows_events)
    if len(trades)+len(opened)+excluded != len(originals):
        raise ValueError('ORIGINAL_SIGNAL_DENOMINATOR_PARITY')
    return {'trades':trades,'open_positions':opened,'events':rows_events,'trace':traces,
            'reference_opportunities':deepcopy(clock['reference_opportunities']),
            'reference_events':deepcopy(clock['reference_events']),
            'audit':{'raw_signals':len(originals),'completed':len(trades),'open':len(opened),
                     'excluded':excluded,'same_symbol_max_positions':1,
                     'exclusion_counts':dict(Counter(e['exclusion_reason'] for e in rows_events if e['status']=='EXCLUDED')),
                     'mode':asdict(mode),'future_outcomes_as_features':False,
                     'reference_released_by_actual_exit':False}}


def dependencies():
    result = old.code_dependencies()
    result[str(Path(__file__).resolve().relative_to(ROOT))] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return result


def freeze(packet):
    parent = packet['parent_spec']
    if (not native.contracts.check_seal(parent) or
        parent.get('receipt_sha256') != 'f8d8d8eb5affe35df9d38bc9709e0c69c44f2288538e4fd9239bc6562948f039' or
        parent.get('data_sha256') != '3cb1bbeb6166a1ae3b32bb9a832faeee579a5d208ecfbfd4bf86004786c70e3a' or
        packet['policy'].get('data_ref') != old.evidence.DATA_REF or
        packet['policy'].get('development_interval_ms') != [old.evidence.DEV_START,old.evidence.DEV_END]):
        raise ValueError('ORIGINAL_CANONICAL_DEV_ONLY_NO_SYNTHETIC_AUTHORITY')
    if (set(packet['rows_by']) != set(native.SYMBOLS) or
        any(len(r)!=old.evidence.COUNT for r in packet['rows_by'].values()) or
        packet['lineage'] != parent['data_input_receipt']):
        raise ValueError('EXACT_SEVEN_PREFIXES_AND_ORIGINAL_LINEAGE')
    actual_deps=dependencies()
    for name,expected in parent['code_files_sha256'].items():
        if actual_deps.get(name) != expected:
            raise ValueError('INHERITED_NATIVE_CODE_DRIFT:'+name)
    if (sha(packet['rows_by']),sha(packet['costs']),sha(packet['policy'])) != (
        parent['data_sha256'],parent['cost_sha256'],parent['policy_sha256']):
        raise ValueError('EXACT_PREPARED_DEV_INPUT_REQUIRED')
    if (parent['candidate_sha256'] != CANDIDATE or
        packet['lineage']['decoded_OOS_rows'] != 0 or packet['lineage']['decoded_validation_rows'] != 0):
        raise ValueError('CANDIDATE_OR_SUFFIX_ACCESS')
    return native.contracts.seal({
        'scope':SCOPE,'base_commit':'22f859019c4d39643d2ba8d6481c2ee925bc9831',
        'inherited_budget_sha256':INHERITED_BUDGET_SHA256,
        'candidate_sha256':CANDIDATE,'candidate_hypotheses_preserved':44,'prior_executions':56,
        'modes':[asdict(m) for m in MODES], 'diagnostic_execution_count':4,
        'first_ordinal':57, 'last_ordinal':60,
        'parent_specification_sha256':parent['receipt_sha256'],
        'data_sha256':parent['data_sha256'],'cost_sha256':parent['cost_sha256'],
        'policy_sha256':parent['policy_sha256'],'lineage_sha256':sha(packet['lineage']),
        'start_ms':parent['start_ms'],'entry_stop_ms':parent['entry_stop_ms'],'runoff_end_ms':parent['runoff_end_ms'],
        'files_sha256':dependencies(), 'python_version':list(sys.version_info[:3]),
        'mode_order':'WAIT_POLICY_THEN_ADDED_RECHECK_THEN_REFERENCE_CLOCK_THEN_EXIT_ANCHOR; ORDER_CONDITIONAL_NOT_UNIQUE_ADDITIVE_CAUSAL_EFFECTS',
        'waiting_policy':'NEXT_OPEN_AFTER6_OBSERVED_CLOSES; ORIGINAL_REFERENCE_EXPIRED_OR_EXIT_PENDING_CANCELS_WHEN_OBSERVED',
        'actual_exit_semantics':'ORIGINAL_KR3_FUNCTION_WITH_SEPARATE_FILL_AND_LOW_TIMEOUT_ANCHORS; NO_PRE_ENTRY_LOW_STATE',
        'stored_endpoints':'PR1212_KR3_FULL_AND_SHIFT6_REUSED; NOT_RERUN',
        'last_endpoint_difference':'FINAL_MODE_RETAINS_ORIGIN_HALF; LEGACY_SHIFT6_DISCARDS_ORIGIN_HALF',
        'cost_semantics':old.COST_SEMANTICS,
        'seed':'NO_RANDOM','independent':False,'formal_credit':0,'new_candidate':False,
        'G5A_changed':False,'G5B_changed':False,'paid_AI':0,'market_requests':0,
        'selection':'NONE; ALL_FOUR_ROWS_REPORTED; NO_TUNING_AFTER_OUTCOMES',
    })


def verify(spec, packet):
    if spec != freeze(packet):
        raise ValueError('FROZEN_SPEC_CODE_INPUT_OR_RUNTIME_DRIFT')


def run_mode(mode, packet, spec):
    verify(spec,packet)
    if mode not in MODES:
        raise ValueError('UNFROZEN_REAL_DIAGNOSTIC')
    out={k:[] for k in ('trades','open_observations','events','trace','reference_opportunities','reference_events')}
    out['audit']={}
    with native.sensitivity():
        for symbol,rows in sorted(packet['rows_by'].items()):
            bundle=d.build_bundle(rows,d.PARENT_SPEC,eval_start_ms=spec['start_ms'],eval_end_ms=spec['runoff_end_ms'])
            raw=replay_symbol(rows,bundle,mode,start=spec['start_ms'],end=spec['runoff_end_ms'])
            charged=account.charge_result(raw,symbol,'keltner_trend_main',mode.id,packet['policy'],packet['costs'],rows)
            for kind in ('trades','open_observations','events','trace'):
                for row in charged[kind]:
                    index=row.get('original_signal_index',row.get('signal_index'))
                    row['mechanism_origin_id']=f'{symbol}:{rows[index]["bar_close_ts"]}'
                    row['mechanism_spec_sha256']=spec['receipt_sha256']
                    # Re-seal each new row after adding comparison provenance.
                    seal_key='trade_sha256' if kind=='trades' else 'observation_sha256' if kind=='open_observations' else None
                    if seal_key:
                        row.pop(seal_key,None);row[seal_key]=account.old.digest(row)
                out[kind].extend(charged[kind])
            for kind in ('reference_opportunities','reference_events'):
                out[kind].extend(dict(x,symbol=symbol) for x in raw[kind])
            out['audit'][symbol]=raw['audit']
    out.update(mode=asdict(mode),scope=SCOPE,specification_sha256=spec['receipt_sha256'],
               independent=False,formal_credit=0,new_candidate_selected=False)
    out['metrics']=old.metrics(out['trades'],out['open_observations'],spec,packet['rows_by'],packet['costs'])
    out['economic_digest']=sha({k:out[k] for k in ('trades','open_observations','events','trace','reference_opportunities','reference_events','audit')})
    return out


def write_new(path, data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('xb') as f:
        f.write(data);f.flush();os.fsync(f.fileno())
    return hashlib.sha256(data).hexdigest()



def budget_projection(budget):
    value=deepcopy(budget)
    value.pop('kr3_mechanism_separation_allocation',None)
    value['trials']=[t for t in value['trials'] if t['actual_experiment_ordinal']<=56]
    value['cumulative_actual_evaluations']=56
    return hashlib.sha256((json.dumps(value,sort_keys=True,indent=2)+'\n').encode()).hexdigest()


def require_allocation(spec,budget):
    a=budget.get('kr3_mechanism_separation_allocation',{})
    if (budget_projection(budget)!=INHERITED_BUDGET_SHA256 or
        a.get('scope_key')!=SCOPE or a.get('specification_sha256')!=spec['receipt_sha256'] or
        a.get('max_actual_variants')!=4 or a.get('variant_ids')!=[m.id for m in MODES] or
        a.get('output_path')!=OUTPUT or a.get('no_retry') is not True):
        raise ValueError('SHARED_ALLOCATION_OR_PRESERVED_HISTORY_MISMATCH')
    return a


def reserve_shared(spec,attempt):
    path=ROOT/BUDGET
    with path.with_suffix('.lock').open('a+b') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        budget=json.loads(path.read_bytes());a=require_allocation(spec,budget)
        ordinal=attempt['ordinal']
        if (a['used']>=4 or ordinal!=57+a['used'] or
            budget['cumulative_actual_evaluations']!=ordinal-1 or
            any(t['actual_experiment_ordinal']==ordinal for t in budget['trials'])):
            raise ValueError('DIAGNOSTIC_ALREADY_USED_OR_OUT_OF_ORDER')
        budget['trials'].append({**attempt,'actual_experiment_ordinal':ordinal,
             'specification_sha256':spec['receipt_sha256'],'data_sha256':spec['data_sha256'],
             'classification':'MECHANISM_DIAGNOSTIC_NOT_NEW_CANDIDATE'})
        a['used']+=1;budget['cumulative_actual_evaluations']=ordinal
        temp=path.with_suffix('.pending')
        write_new(temp,(json.dumps(budget,sort_keys=True,indent=2)+'\n').encode())
        os.replace(temp,path)


def execute(packet, spec, outdir):
    verify(spec,packet)
    outdir=Path(outdir)
    if outdir.resolve()!=(ROOT/OUTPUT).resolve():
        raise ValueError('CANONICAL_SCOPE_PATH_REQUIRED_NO_RESET')
    require_allocation(spec,json.loads((ROOT/BUDGET).read_bytes()))
    if (outdir/'RESULT_INDEX.json').exists():
        raise ValueError('ALREADY_EXECUTED_REPORT_ONLY')
    # Claim whole scope once. Failure, cancellation or partial result never resets
    # the claim. Reuse saved completed artifacts; an unknown attempt is not free.
    write_new(outdir/'SCOPE_ATTEMPT.json',canonical({'scope':SCOPE,'spec_sha256':spec['receipt_sha256'],
        'status':'RESERVED_BEFORE_ANY_ECONOMIC_RUN','started_unix_ns':time.time_ns(),'retry_allowed':False}))
    summary=[]
    for ordinal,mode in enumerate(MODES,57):
        folder=outdir/mode.id
        attempt={'ordinal':ordinal,'mode':asdict(mode),'spec_sha256':spec['receipt_sha256'],
                 'status':'RESERVED_BEFORE_REPLAY','retry_allowed':False,'started_unix_ns':time.time_ns()}
        write_new(folder/'ATTEMPT.json',canonical(attempt))
        reserve_shared(spec,attempt)
        try:
            result=run_mode(mode,packet,spec)
            digest=write_new(folder/'RESULT.json.gz',gzip.compress(canonical(result),mtime=0))
            receipt={'ordinal':ordinal,'mode':asdict(mode),'spec_sha256':spec['receipt_sha256'],
                     'status':'COMPLETED','artifact_sha256':digest,'metrics':{k:v for k,v in result['metrics'].items() if k!='daily'},
                     'economic_digest':result['economic_digest'],'new_candidate':False,'formal_credit':0,'runtime':sys.version}
            write_new(folder/'RECEIPT.json',canonical(receipt));summary.append(receipt)
            print(json.dumps(receipt),flush=True)
        except BaseException as exc:
            write_new(folder/'FAILURE.json',canonical({'ordinal':ordinal,'status':'FAILED_CONSUMED',
                'error_type':type(exc).__name__,'message':str(exc),'retry_allowed':False}))
            raise
    write_new(outdir/'RESULT_INDEX.json',canonical({'scope':SCOPE,'spec_sha256':spec['receipt_sha256'],
         'candidate_hypotheses':44,'prior_executions':56,'new_diagnostic_executions':4,'cumulative_executions':60,
         'results':summary,'formal_credit':0,'independent':False,'new_candidates':0}))
    return summary


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',type=Path,required=True);p.add_argument('--out-dir',type=Path,required=True)
    p.add_argument('--freeze',action='store_true');p.add_argument('--execute',action='store_true')
    args=p.parse_args()
    if args.freeze==args.execute: p.error('choose exactly one mode')
    packet=json.loads(gzip.decompress(args.input.read_bytes()))
    if args.freeze:
        write_new(args.out_dir/'SPEC.json',canonical(freeze(packet)))
    else:
        spec=json.loads((args.out_dir/'SPEC.json').read_bytes())
        execute(packet,spec,args.out_dir)

if __name__=='__main__':main()
