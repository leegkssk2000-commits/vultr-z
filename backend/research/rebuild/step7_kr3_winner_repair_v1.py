"""One predeclared entry-recheck repair; original B reservation/exit owners.

Used DEV only. This module never reads prices at import or dispatches a provider.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import asdict
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path
import sys
import time

from backend.research.rebuild import step7_kr3_mechanism_separation_v1 as parent

ROOT, CAMPAIGN = parent.ROOT, parent.CAMPAIGN
SCOPE = 'KR3_REQUAL_WINNER_REPAIR_AFTER_PR1213_V1'
OUTPUT = CAMPAIGN+'/WINNER_REPAIR'
BUDGET = CAMPAIGN+'/BUDGET.json'
B_MODE = parent.MODES[1]
CANDIDATE = 'KR3_B_FIRST_FOLLOWUP_RANGE_CONFIRMATION_DEV_V1'
RUNS = ('E-DEV2025','B-SEEN2026','E-SEEN2026')
canonical, sha = parent.canonical, parent.sha
write_new = parent.write_new
RULE = {
 'early_check':'ONLY origin_index+1 completed close; never scan alternatives',
 'early_conditions':'close>origin.high AND close>EMA20>EMA50 AND close>=(high+low)/2',
 'fallback':'If early price conditions fail, keep original B origin+6 upper-half recheck',
 'origin':'Original raw EMA signal and original upper-half eligibility; original admission clock',
 'clock':'advance original reference before each completed-close decision; do not release on rejection or actual exit',
 'cancel':'Observed reference expiry/EMA exit, unavailable next open, or actual occupied at qualified decision cancels permanently',
 'occupancy':'same-symbol max1; prior exit owns its close; no queued retry after a qualified occupied decision',
 'fill':'Next observed open after confirmation; no retrospective bar6 cancellation',
 'exit':'parent.anchored_path unchanged with ORIGIN low/timeout/extension, actual decision-index held geometry; no pre-entry low state',
 'SL':None,'TP':None,'maximum_wait_observed_bars':6,
 'feature_available_at':'original OHLC at origin close; followup OHLC/EMA and reference state at decision close',
}


def early_confirmation(rows, bundle, origin, index):
    row=rows[index]
    return (index==origin+1 and row['close']>rows[origin]['high']
            and row['close']>bundle['ema20'][index]>bundle['ema50'][index]
            and parent.reservation.n.entry_observation(row)[parent.reservation.n.FEATURE])


def replay_symbol(rows, bundle, *, start, end):
    parent.d.replay(rows,bundle,eval_start_ms=start,eval_end_ms=end,
                    enable_change=True,fixed_signal_indices=[])
    originals={s['signal_index']:s for s in bundle['signals']}
    scheduled=defaultdict(list);events={};traces=[];trades=[];opened=[]
    clock=parent.reservation.initial_clock(eval_start_ms=start,eval_end_ms=end)
    last_actual_exit=-1;tail_open=False
    observer=parent.reservation.n.entry_observation
    for j,row in enumerate(rows):
        if j in originals:
            events[j]={**originals[j],'original_signal_index':j,
                'origin_half':observer(row)[parent.reservation.n.FEATURE],
                'origin_known_at':row['bar_close_ts'],'decision_index':None,'decision_ts':None,
                'admission':False,'status':'WAITING','exclusion_reason':None,
                'reference_created':False,'confirmation_checks':[]}
            scheduled[j+1].append(j);scheduled[j+6].append(j)
        parent.reservation.advance_clock(clock,row,index=j,ema20=bundle['ema20'][j],
                                         ema50=bundle['ema50'][j],signal=originals.get(j))
        if j in originals:
            known=clock['opportunity_events'][-1];ev=events[j]
            ev.update(reference_created=known['reservation_created'],origin_reference_admitted=known['admission'])
            if not known['admission']:
                ev.update(status='EXCLUDED',exclusion_reason=known['exclusion_reason'],exclusion_known_at=row['bar_close_ts'])
        for origin in sorted(scheduled.get(j,())):
            ev=events[origin]
            if ev['status']!='WAITING':continue
            is_early=j==origin+1
            half=observer(row)[parent.reservation.n.FEATURE]
            confirms=early_confirmation(rows,bundle,origin,j) if is_early else half
            ev['confirmation_checks'].append({'index':j,'available_at':row['bar_close_ts'],
                'early':is_early,'confirmed':bool(confirms),'upper_half':half,
                'close':row['close'],'high':row['high'],'low':row['low'],
                'origin_high':rows[origin]['high'],'ema20':bundle['ema20'][j],'ema50':bundle['ema50'][j]})
            k=clock['active_opportunity_offset']
            active=None if k is None else clock['reference_opportunities'][k]
            reason=None
            if row['bar_close_ts']>=end or j+1>=len(rows):reason='NO_CONFIRMATION_NEXT_OPEN_IN_CALENDAR'
            elif active is None or active['reference_signal_index']!=origin:reason='WAIT_REFERENCE_EXPIRED'
            elif active['phase'] not in ('HELD','PENDING_ENTRY_NEXT_OPEN'):reason='WAIT_REFERENCE_EXIT_ALREADY_OBSERVED'
            if reason is None and is_early and not confirms:continue
            if reason is None and not confirms:reason='DELAYED_HALF_RECHECK_FAILED'
            if reason is None and (tail_open or row['bar_close_ts']<=last_actual_exit):
                reason='RUNNER_OCCUPIED_AT_CONFIRMATION'
            ev.update(decision_index=j,decision_ts=row['bar_close_ts'],recheck_half=half,
                      recheck_known_at=row['bar_close_ts'],confirmation_kind='FIRST_FOLLOWUP_RANGE' if is_early else 'B_SIXTH_BAR')
            if reason:
                ev.update(status='EXCLUDED',exclusion_reason=reason,exclusion_known_at=row['bar_close_ts']);continue
            signal={'origin_index':origin,'decision_index':j,'exit_anchor_index':origin}
            closed,censored,trace=parent.anchored_path(rows,signal,bundle['ema20'],bundle['ema50'],end)
            for t in trace:
                t.update(original_signal_index=origin,decision_index=j,exit_anchor_index=origin)
                if t['kind']=='ENTRY_NEXT_OPEN':t['feature_available_ts']=row['bar_close_ts']
            traces.extend(trace);value=closed if closed is not None else censored
            value.update(initial_protective_sl=None,tp=None,risk_R=None,
                waiting_observed_bars=j-origin,waiting_elapsed_ms=row['bar_close_ts']-rows[origin]['bar_close_ts'])
            ev.update(admission=True,status='COMPLETED' if closed is not None else 'CENSORED')
            if closed is not None:trades.append(closed);last_actual_exit=closed['exit_ts']
            else:opened.append(censored);tail_open=True
    for ev in events.values():
        if ev['status']=='WAITING':ev.update(status='EXCLUDED',exclusion_reason='PENDING_WAIT_AT_END',exclusion_known_at=end)
    ordered=[events[k] for k in sorted(events)]
    excluded=sum(e['status']=='EXCLUDED' for e in ordered)
    if len(trades)+len(opened)+excluded!=len(originals):raise ValueError('RAW_SIGNAL_DENOMINATOR')
    return {'trades':trades,'open_positions':opened,'events':ordered,'trace':traces,
      'reference_opportunities':deepcopy(clock['reference_opportunities']),
      'reference_events':deepcopy(clock['reference_events']),
      'audit':{'raw_signals':len(originals),'completed':len(trades),'open':len(opened),'excluded':excluded,
        'same_symbol_max_positions':1,'exclusion_counts':dict(Counter(e['exclusion_reason'] for e in ordered if e['status']=='EXCLUDED')),
        'future_outcomes_as_features':False,'reference_released_by_actual_exit':False,'candidate':CANDIDATE}}


def dependencies():
    result=parent.dependencies()
    for name in ('step7_kr3_winner_repair_v1.py','step7_kr3_winner_accounting_v1.py',
                 'break_channel_q1_metrics_v1.py','q0_b_seen_adapter_v1.py','q0_b_seen_replication_v1.py'):
        path='backend/research/rebuild/'+name
        result[path]=hashlib.sha256((ROOT/path).read_bytes()).hexdigest()
    return result


def freeze(packets,inputs):
    return parent.native.contracts.seal({'scope':SCOPE,'candidate_id':CANDIDATE,'rule':RULE,
      'direct_parent':asdict(B_MODE),'inherited_parent':parent.CANDIDATE,'runs':list(RUNS),
      'input_bindings':inputs,'files_sha256':dependencies(),'runtime':list(sys.version_info[:3]),
      'periods':{k:{'start_ms':p['policy']['development_interval_ms'][0],
          'runoff_end_ms':p['policy']['development_interval_ms'][1]} for k,p in packets.items()},
      'packet_shas':{k:{x:sha(p[x]) for x in ('rows_by','costs','policy','lineage')} for k,p in packets.items()},
      'cost_semantics':parent.old.COST_SEMANTICS,'seed':'NO_RANDOM','max_candidates':1,'max_executions':3,
      'prior_candidates':44,'prior_evaluations':60,'new_candidate_ordinal':45,'evaluation_ordinals':[61,62,63],
      'comparison':'B and KR3 separately; all signal denominators, capped original-winner retention, mean loss, terminal net/cost2, marked DD, exposure and concentration',
      'relative_checks':['terminal_net_improved_vs_B','all_cost2_terminal_not_worse_vs_B','marked_DD_not_worse_vs_B','KR3_capped_winner_retention_improved_vs_B'],
      'formal_owner':'No registered entry-repair formal pass contract; unchanged research proxy costs and attribution owners, numerical comparisons only; formal HOLD',
      'independent':False,'formal_credit':0,'orders':0,'new_collection':0,'no_automatic_retry':True})


def verify(spec,packets):
    if not parent.native.contracts.check_seal(spec) or spec!=freeze(packets,spec['input_bindings']):
        raise ValueError('FROZEN_RULE_CODE_DATA_DRIFT')
    expected={'DEV2025':([1734595200000,1766995200000],2250,'3cb1bbeb6166a1ae3b32bb9a832faeee579a5d208ecfbfd4bf86004786c70e3a'),
      'SEEN2026':([1778198400000,1788566400000],3748,'406e72401bec107c31ac17fd9742489f5980ca411b0f848613692fd2d00d29af')}
    if set(packets)!=set(expected):raise ValueError('EXACT_AUTHORIZED_TWO_PERIODS')
    for key,(calendar,n,digest) in expected.items():
        p=packets[key]
        if (p['policy']['development_interval_ms']!=calendar or set(p['rows_by'])!=set(parent.native.SYMBOLS)
            or any(len(r)!=n for r in p['rows_by'].values()) or sha(p['rows_by'])!=digest):
            raise ValueError('AUTHORIZED_INPUT_PREFIX_REQUIRED:'+key)
        expected_policy={'DEV2025':'d686c9bbcee0515d265d66ea789221b078ecb9aaeafd6c7070810a4a66775552',
          'SEEN2026':'dc08e55afdb1fbf2b952bf9baed3a25a2ebcf7c1b3abed4e0b97f73e5d8ce031'}
        if sha(p['costs'])!='e7b29de0b1810d14e02847917e951301f4d9a30da190ed7c6fc4cafbca581020' or sha(p['policy'])!=expected_policy[key]:
            raise ValueError('ORIGINAL_PERIOD_POLICY_AND_COST_REQUIRED:'+key)


def run_one(name,packets,spec):
    verify(spec,packets)
    if name not in RUNS:raise ValueError('UNFROZEN_EXECUTION')
    kind,period=name.split('-');packet=packets[period];calendar=spec['periods'][period]
    start,end=calendar['start_ms'],calendar['runoff_end_ms']
    out={k:[] for k in ('trades','open_observations','events','trace','reference_opportunities','reference_events')};out['audit']={}
    with parent.native.sensitivity():
        for symbol,rows in sorted(packet['rows_by'].items()):
            bundle=parent.d.build_bundle(rows,parent.d.PARENT_SPEC,eval_start_ms=start,eval_end_ms=end)
            raw=(replay_symbol(rows,bundle,start=start,end=end) if kind=='E' else
                 parent.replay_symbol(rows,bundle,B_MODE,start=start,end=end))
            charged=parent.account.charge_result(raw,symbol,'keltner_trend_main',name,packet['policy'],packet['costs'],rows)
            for category in ('trades','open_observations','events','trace'):
                for row in charged[category]:
                    i=row.get('original_signal_index',row.get('signal_index'))
                    row.update(mechanism_origin_id=f'{symbol}:{rows[i]["bar_close_ts"]}',winner_spec_sha256=spec['receipt_sha256'])
                    sk='trade_sha256' if category=='trades' else 'observation_sha256' if category=='open_observations' else None
                    if sk:row.pop(sk,None);row[sk]=parent.account.old.digest(row)
                out[category].extend(charged[category])
            for category in ('reference_opportunities','reference_events'):
                out[category].extend(dict(x,symbol=symbol) for x in raw[category])
            out['audit'][symbol]=raw['audit']
    out.update(run=name,candidate_id=CANDIDATE if kind=='E' else B_MODE.id,scope=SCOPE,
       specification_sha256=spec['receipt_sha256'],independent=False,formal_credit=0,new_candidate_selected=False)
    out['metrics']=parent.old.metrics(out['trades'],out['open_observations'],calendar,packet['rows_by'],packet['costs'])
    out['economic_digest']=sha({k:out[k] for k in ('trades','open_observations','events','trace','reference_opportunities','reference_events','audit')})
    return out


def reserve(spec,name):
    path=ROOT/BUDGET
    with path.with_suffix('.lock').open('a+b') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        budget=json.loads(path.read_bytes());a=budget.get('kr3_winner_repair_allocation',{})
        i=RUNS.index(name);ordinal=61+i
        if (a.get('scope_key')!=SCOPE or a.get('specification_sha256')!=spec['receipt_sha256']
            or a.get('runs')!=list(RUNS) or a.get('used')!=i or a.get('max_executions')!=3
            or budget['cumulative_actual_evaluations']!=ordinal-1
            or any(t['actual_experiment_ordinal']==ordinal for t in budget['trials'])):
            raise ValueError('CANONICAL_SHARED_ALLOCATION_ALREADY_USED_OR_CHANGED')
        attempt={'run':name,'scope':SCOPE,'actual_experiment_ordinal':ordinal,'candidate_ordinal':45 if name.startswith('E-') else None,
          'specification_sha256':spec['receipt_sha256'],'status':'RESERVED_BEFORE_REPLAY','started_unix_ns':time.time_ns(),
          'pid':os.getpid(),'retry_allowed':False}
        parent.write_new(ROOT/OUTPUT/name/'ATTEMPT.json',canonical(attempt))
        budget['trials'].append(attempt);a['used']+=1;budget['cumulative_actual_evaluations']=ordinal
        if i==0:
            if budget['cumulative_actual']!=44:raise ValueError('CANDIDATE_HISTORY_MOVED')
            budget['cumulative_actual']=45;budget['new_candidate_runs']+=1
            budget.setdefault('candidate_trials',[]).append({'ordinal':45,'candidate':CANDIDATE,'scope':SCOPE,'first_evaluation':ordinal,'specification_sha256':spec['receipt_sha256']})
        temp=path.with_suffix('.pending');parent.write_new(temp,(json.dumps(budget,sort_keys=True,indent=2)+'\n').encode());os.replace(temp,path)
        return attempt


def execute(packets,spec,outdir):
    verify(spec,packets);outdir=Path(outdir)
    if outdir.resolve()!=(ROOT/OUTPUT).resolve():raise ValueError('CANONICAL_PATH_NO_RENAMED_RETRY')
    parent.write_new(outdir/'SCOPE_ATTEMPT.json',canonical({'scope':SCOPE,'specification_sha256':spec['receipt_sha256'],
        'started_unix_ns':time.time_ns(),'status':'CLAIMED_NOT_COMPLETED','retry_allowed':False}))
    results=[]
    for name in RUNS:
        attempt=reserve(spec,name);folder=outdir/name
        try:
            value=run_one(name,packets,spec)
            digest=parent.write_new(folder/'RESULT.json.gz',gzip.compress(canonical(value),mtime=0))
            receipt={**attempt,'status':'COMPLETED','finished_unix_ns':time.time_ns(),'artifact_sha256':digest,
                'economic_digest':value['economic_digest'],'metrics':{k:v for k,v in value['metrics'].items() if k!='daily'}}
            parent.write_new(folder/'RECEIPT.json',canonical(receipt));results.append(receipt)
            print(json.dumps({'run':name,'ordinal':attempt['actual_experiment_ordinal'],'status':'COMPLETED',
                  'closed_T':value['metrics']['closed_T'],'open_T':value['metrics']['open_T']}),flush=True)
        except BaseException as exc:
            parent.write_new(folder/'FAILURE.json',canonical({**attempt,'status':'FAILED_CONSUMED','error':str(exc),'error_type':type(exc).__name__}))
            raise
    parent.write_new(outdir/'RESULT_INDEX.json',canonical({'scope':SCOPE,'specification_sha256':spec['receipt_sha256'],
       'results':results,'actual_evaluations':3,'candidate_hypotheses':45,'cumulative_evaluations':63,'formal_credit':0}))
    return results


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--execute',action='store_true');args=parser.parse_args()
    packets=json.loads(gzip.decompress(args.input.read_bytes()))
    spec=json.loads((ROOT/OUTPUT/'SPEC.json').read_bytes())
    if not args.execute:raise SystemExit('EXPLICIT_EXECUTE_REQUIRED')
    execute(packets,spec,ROOT/OUTPUT)

if __name__=='__main__':main()
