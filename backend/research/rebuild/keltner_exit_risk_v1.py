"""Keltner PR1184 attribution and bounded observable/label analysis, no replay.

Outcome labels live beside, never inside, prefix-only trigger observations.
This module cannot generate a trading child or call the old exit replay.
"""
from __future__ import annotations
import argparse
from bisect import bisect_left
from collections import defaultdict
import gzip
import json
import math
from pathlib import Path
import random

from backend.research.rebuild import top5_no_credit_exit_v1 as prior
from backend.research.rebuild import keltner_exit_risk_streaks_v1 as streak_audit

old=prior.old
ROOT=prior.ROOT
LANE='keltner_trend_main'
CONTRACT='backend/research/contracts/keltner_exit_risk_v1.json'
OUTPUT='research/development_evidence/KELTNER_EXIT_RISK_20260906_V1'
PRIMARY_QUESTION={
    'observable':'original_trend_intact',
    'definition':'EMA20 > EMA50 AND trigger close > EMA50',
    'parameter_owner':'Existing frozen Keltner V2 EMA20/50; no fitted threshold',
    'direction':'Intact trend should be more frequent among cut parent winners than among saved parent losses',
    'purpose':'Assess evidence for distinguishing normal pullback from failed continuation at the existing exit trigger',
    'screen':'Positive all-symbol week-bootstrap lower 95% bound; positive in both reused DEV calendar halves and each leave-one-symbol-out subset; at least two occupied weeks per label',
    'no_fallback_search':'Auxiliary continuous observations cannot nominate a replacement filter if this question fails',
}


def trigger_observation(rows, *, entry_ts,entry_price,trigger_ts,armed_ts,binding,spec):
    """Read only bars closed by the recorded decision time, never the fill bar."""
    closes=[r['bar_close_ts'] for r in rows]
    i=bisect_left(closes,trigger_ts)
    if i==len(rows) or closes[i]!=trigger_ts or not entry_ts<armed_ts<trigger_ts:
        raise RuntimeError('TRIGGER_OR_ARM_TIMESTAMP')
    prefix=[dict(r,ts=r['bar_open_ts']) for r in rows[:i+1]]
    arrays,_=old.dsl._features(prefix,spec)
    e20=arrays['ema20'][-1];e50=arrays['ema50'][-1];close=prefix[-1]['close']
    if e20 is None or e50 is None:raise RuntimeError('TRIGGER_FEATURE_UNAVAILABLE')
    mark=prior.mark_net(entry_price,'long',entry_ts,close,trigger_ts,binding)
    if mark>1e-8:raise RuntimeError('RECORDED_EXIT_TRIGGER_NOT_NONPOSITIVE')
    return {'available_ts':trigger_ts,'last_consumed_bar_close_ts':prefix[-1]['bar_close_ts'],
            'close':close,'ema20':e20,'ema50':e50,'original_trend_intact':e20>e50 and close>e50,
            'close_to_ema50_bps':(close/e50-1)*10000,
            'ema20_to_ema50_bps':(e20/e50-1)*10000,
            'held_closed_bars':(trigger_ts-entry_ts)//(4*prior.HOUR),
            'closed_bars_since_arm':(trigger_ts-armed_ts)//(4*prior.HOUR),
            'current_net_mark_bps':mark,'only_prefix_prices_used':True}


def outcome_label(parent,child,large_winner_keys):
    """Ex-post answers in entry-notional net bps; not executable inputs."""
    p=parent['net_bps'];c=child['net_bps']
    saved=max(0.,max(0.,-p)-max(0.,-c)) if p<0 else 0.
    cut=max(0.,p-max(0.,c)) if p>0 else 0.
    return {'label_scope':'DEVELOPMENT_ANSWER_ONLY_NOT_EXECUTION_FEATURE',
            'saved_parent_loss':saved>0,'cut_parent_winner':cut>0,
            'cut_large_parent_winner':prior.entry_key(parent) in large_winner_keys and cut>0,
            'saved_loss_bps':saved,'cut_winner_profit_bps':cut,
            'extra_loss_on_parent_winner_bps':max(0.,-c) if p>0 else 0.,
            'worsened_parent_loss_bps':max(0.,p-c) if p<0 else 0.,
            'parent_net_bps':p,'fixed_exit_net_bps':c,'net_delta_bps':c-p,
            'cost2_net_delta_bps':child['cost2x_net_bps']-parent['cost2x_net_bps'],
            'gross_delta_bps':child['gross_bps']-parent['gross_bps'],
            'funding_saving_bps':parent['funding_bps']-child['funding_bps']}


def class_summary(rows):
    result={}
    for label in ['saved_parent_loss','cut_parent_winner','cut_large_parent_winner']:
        selected=[r for r in rows if r['answer'][label]]
        result[label]={'T':len(selected),'intact_T':sum(r['observation']['original_trend_intact'] for r in selected),
                       'saved_loss_bps':sum(r['answer']['saved_loss_bps'] for r in selected),
                       'cut_winner_profit_bps':sum(r['answer']['cut_winner_profit_bps'] for r in selected),
                       'net_delta_bps':sum(r['answer']['net_delta_bps'] for r in selected),
                       'cost2_delta_bps':sum(r['answer']['cost2_net_delta_bps'] for r in selected),
                       'observables':{k:{'median':old.probe.quantile([r['observation'][k] for r in selected],.5),
                                         'q25':old.probe.quantile([r['observation'][k] for r in selected],.25),
                                         'q75':old.probe.quantile([r['observation'][k] for r in selected],.75)}
                                      for k in ['close_to_ema50_bps','ema20_to_ema50_bps','held_closed_bars','closed_bars_since_arm','current_net_mark_bps']}}
        result[label]['intact_fraction']=result[label]['intact_T']/len(selected) if selected else None
    return result


def separation(rows):
    c=class_summary(rows)
    win=c['cut_parent_winner']['intact_fraction'];loss=c['saved_parent_loss']['intact_fraction']
    return None if win is None or loss is None else win-loss


def evidence_screen(rows,policy):
    start,end=policy['development_interval_ms'];mid=(start+end)//2
    weeks=list(range(old.probe.week(start),old.probe.week(end-1)+1))
    # Resample all symbols jointly in the SAME calendar-week blocks used by
    # the existing DEV evaluator. No shuffled future labels become features.
    by_week=defaultdict(list)
    for r in rows:by_week[old.probe.week(r['trigger_ts'])].append(r)
    rng=random.Random(policy['uncertainty']['seed']);draws=[]
    for _ in range(policy['uncertainty']['replications']):
        sample=[r for w in (rng.choice(weeks) for _ in weeks) for r in by_week[w]]
        value=separation(sample)
        if value is not None:draws.append(value)
    ci=[old.probe.quantile(draws,.025),old.probe.quantile(draws,.975)]
    halves={name:separation([r for r in rows if a<=r['trigger_ts']<b]) for name,a,b in [('early_DEV',start,mid),('late_DEV',mid,end)]}
    leave={s:separation([r for r in rows if r['symbol']!=s]) for s in policy['symbols']}
    occupied={label:len({old.probe.week(r['trigger_ts']) for r in rows if r['answer'][label]}) for label in ['cut_parent_winner','saved_parent_loss']}
    checks={'positive_lower_week_bound':ci[0] is not None and ci[0]>0,
            'both_reused_DEV_halves_positive':all(v is not None and v>0 for v in halves.values()),
            'all_leave_one_symbol_out_positive':all(v is not None and v>0 for v in leave.values()),
            'two_occupied_weeks_per_label':all(v>=2 for v in occupied.values())}
    return {'point_separation':separation(rows),'separation_95pct_interval':ci,'reused_DEV_halves':halves,
            'leave_one_symbol_out':leave,'occupied_weeks':occupied,'nonempty_resamples':len(draws),
            'checks':checks,'passed':all(checks.values()),'primary_tests':1,'thresholds_swept':0,
            'method':'JOINT_SYMBOL_TRIGGER_WEEK_BLOCK_BOOTSTRAP; REUSED_DEV_SENSITIVITY_NOT_INDEPENDENT_VALIDATION',
            'formal_statistical_pass':False,'auxiliary_features_used_for_policy_selection':False}


def authorize():
    c=old.read(CONTRACT);old.probe.verify_seal(c,'KELTNER_RISK_ANALYSIS')
    if c['primary_question']!=PRIMARY_QUESTION or c['new_economic_replays_authorized_in_analysis']!=0:
        raise RuntimeError('ANALYSIS_SCOPE_CHANGED')
    for k,v in old.probe.DEV_AUTH.items():
        if c[k]!=v:raise RuntimeError('KELTNER_AUTHORITY:'+k)
    for path,sha in {**c['code_files_sha256'],**c['evidence_files_sha256']}.items():
        if old.file_sha(ROOT/path)!=sha:raise RuntimeError('KELTNER_ANALYSIS_IDENTITY:'+path)
    prior.authorize()
    return c


def run(data_dir,verify_only=False):
    c=authorize();p=old.read(old.POLICY)
    receipt=old.read(prior.OUTPUT+'/receipt.json')
    all_trades=prior.previous.read_lines(ROOT/prior.OUTPUT/'trades.jsonl.gz')
    trades={name:[t for t in all_trades if t['lane_id']==LANE and t['comparison_stage']==stage]
            for name,stage in [('parent','fixed_base'),('fixed','fixed_child'),('full','lifecycle_child')]}
    # No shared evaluator call: the old ledgers are the only economic source.
    for name,ts in trades.items():
        seen=set()
        for t in ts:
            if t['trade_sha256']!=old.digest({k:v for k,v in t.items() if k!='trade_sha256'}):raise RuntimeError('TRADE_SEAL')
            key=prior.entry_key(t)
            if key in seen:raise RuntimeError('DUPLICATE_ENTRY')
            seen.add(key)
    parents={prior.entry_key(t):t for t in trades['parent']}
    fixed={prior.entry_key(t):t for t in trades['fixed']}
    if parents.keys()!=fixed.keys():raise RuntimeError('FIXED_ENTRY_POPULATION')
    prior.assert_parent_parity(trades['parent'],[t for t in all_trades if t['lane_id']==LANE and t['comparison_stage']=='lifecycle_base'])
    dev=old.require_development(old.read(old.probe.STAGE),ROOT)
    if dev['receipt_sha256']!=c['cost_sha256']:raise RuntimeError('COST_BINDING_DRIFT')
    manifest=json.loads((data_dir/'development_manifest.json').read_text())
    allowed=[data_dir/'development_manifest.json']+[data_dir/f for f in manifest['dataset_files']]+[data_dir/f['path'] for f in manifest['cost_snapshots'].values()]
    with old.probe.io_boundary(allowed,ROOT/OUTPUT):
        data,access=old.probe.load_development(data_dir,c['inherited_probe_policy'],dev)
    spec=next(s for s in old.read(old.FREEZE)['children'] if s['lane_id']==LANE)['executable_spec']
    winners=sorted([t for t in trades['parent'] if t['net_bps']>0],key=lambda t:(-t['net_bps'],prior.entry_key(t)))
    large={prior.entry_key(t) for t in winners[:math.ceil(len(winners)*.1)]}
    records=[]
    with old.probe.io_boundary([],ROOT/OUTPUT):
        for key,parent in sorted(parents.items()):
            child=fixed[key];trace=child['exit_overlay']
            if not trace['exit_changed']:continue
            obs=trigger_observation(data[parent['symbol']],entry_ts=parent['entry_ts'],entry_price=parent['entry_price'],
                trigger_ts=trace['trigger_at_ms'],armed_ts=trace['armed_at_ms'],binding=dev['cost_by_symbol'][parent['symbol']],spec=spec)
            if abs(obs['current_net_mark_bps']-trace['trigger_mark_net_bps'])>1e-8:raise RuntimeError('TRIGGER_TRACE_PARITY')
            records.append({'entry_key':key,'symbol':parent['symbol'],'trigger_ts':trace['trigger_at_ms'],
                            'source_parent_trade_sha256':parent['trade_sha256'],'source_child_trade_sha256':child['trade_sha256'],
                            'observation':obs,'answer':outcome_label(parent,child,large)})
        screen=evidence_screen(records,p)
        risk=streak_audit.build(trades['parent'],trades['fixed'],trades['full'])
    old_metrics=receipt['lanes'][LANE]
    decision='EVIDENCE_SUPPORTS_ONE_SEPARATELY_PREREGISTERED_CHILD' if screen['passed'] else 'CLOSE_CURRENT_FAMILY_NO_SUPPORT_IN_PREREGISTERED_SCREEN'
    result=old.seal({'analysis_id':c['analysis_id'],'contract_sha256':c['receipt_sha256'],
        'source_result_sha256':receipt['receipt_sha256'],'data_sha256':c['data_sha256'],'cost_sha256':c['cost_sha256'],
        'metrics':{name:old_metrics['metrics'][stage] for name,stage in [('parent','fixed_base'),('fixed','fixed_child'),('full','lifecycle_child')]},
        'diagnostics':{name:old_metrics['diagnostics'][stage] for name,stage in [('parent','fixed_base'),('fixed','fixed_child'),('full','lifecycle_child')]},
        'uncertainty':old_metrics['uncertainty'],'attribution':old_metrics['attribution'],
        'streak_attribution':risk,'triggered_parent_T':len(records),'unchanged_parent_T':len(parents)-len(records),
        'trigger_classes':class_summary(records),'primary_observable_screen':screen,
        'by_symbol':{s:class_summary([r for r in records if r['symbol']==s]) for s in p['symbols']},
        'by_natural_trend_state':{str(b):class_summary([r for r in records if r['observation']['original_trend_intact']==b]) for b in [False,True]},
        'large_winner_definition':'Top ceil(10% of positive-net parent trades), inherited descriptive diagnostic convention; never an execution feature',
        'decision':decision,'new_child_id':None,'new_economic_replays':0,'old_exit_reruns':0,
        'inference_scope':'ONE_PREDECLARED_STRUCTURAL_OBSERVABLE; NOT_PROOF_THAT_ALL_POSSIBLE_EXIT_FEATURES_FAIL',
        'data_reuse_history':c['data_reuse_history'],'source_access':access,'validation_rows_decoded':0,'OOS_rows_decoded':0,
        'paid_AI_calls':0,'G6_authorized':False,'operating_G5B_changed':False,'other_Top5_rejected_by_this_analysis':False,
        **old.probe.DEV_AUTH})
    out=ROOT/OUTPUT
    if not verify_only:out.mkdir(parents=True,exist_ok=True)
    plain=b''.join(old.probe.canonical(r) for r in records);path=out/'trigger_observations.jsonl.gz'
    payload=path.read_bytes() if path.exists() else gzip.compress(plain,mtime=0)
    if gzip.decompress(payload)!=plain:raise RuntimeError('OBSERVATION_REPRODUCTION_DRIFT')
    old.probe.write_immutable(path,payload,verify_only=verify_only)
    old.probe.write_immutable(out/'receipt.json',old.probe.canonical(result),verify_only=verify_only)
    old.probe.write_immutable(out/'RESULTS.md',render(result),verify_only=verify_only)
    files=[CONTRACT,str(path.relative_to(ROOT)),OUTPUT+'/receipt.json',OUTPUT+'/RESULTS.md']
    durable=old.seal({'analysis_id':c['analysis_id'],'result_receipt_sha256':result['receipt_sha256'],
                     'files_sha256':{f:old.file_sha(ROOT/f) for f in files},'code_files_sha256':c['code_files_sha256'],
                     'preserved_files_sha256':c['evidence_files_sha256'],'new_economic_replays':0,**old.probe.DEV_AUTH})
    old.probe.write_immutable(out/'durable_receipt.json',old.probe.canonical(durable),verify_only=verify_only)
    return result


def render(r):
    lines=['# Keltner: average economics and loss-sequence risk','',
           'Existing PR1184 trades and exit traces only. No rerun of the breakeven exit, new trading simulation or holdout access. All amounts are modelled entry-notional trade bps, not account returns.',
           '', '| Population | T | Net E | PF | WR % | Payoff | Cost2 E | Exposure days | Max grouped streak loss |',
           '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for name,m in r['metrics'].items():
        b=m['base_cost'];s=r['diagnostics'][name]['lane_simultaneous_close_group_streaks']
        lines.append(f"| {name} | {b['completed_T']} | {b['expectancy_bps_per_trade']:.4f} | {b['PF']:.4f} | {100*b['win_rate']:.2f} | {b['realized_payoff']:.4f} | {m['cost2x']['expectancy_bps_per_trade']:.4f} | {b['exposure_symbol_days']:.4f} | {s['max_loss_trade_sum_bps']:.4f} |")
    lines += ['', 'Maxima occur over different windows and are not an additive causal loss decomposition. Same-calendar-window accounting separates exit amount, exit timing, excluded entries and new entries. Simultaneous exits are netted before a streak resets.',
              '', '```json',json.dumps({
                  'worst_runs':{name:v['worst_amount_run'] for name,v in r['streak_attribution']['populations'].items()},
                  'whole_development_bridges':r['streak_attribution']['whole_development_bridges'],
                  'same_window_comparisons':[{k:v for k,v in w.items() if k in ['sources','start_utc','end_utc','bridges','nonnegative_reset_observations']} for w in r['streak_attribution']['selected_worst_windows']]},indent=2,sort_keys=True),'```',
              '', 'Trigger-time evidence uses the original EMA20/EMA50 structure. Outcome labels are stored separately and are never feature inputs. Large winners use an outcome-only top-decile label.',
              '', '```json',json.dumps({'classes':r['trigger_classes'],'primary_screen':r['primary_observable_screen']},indent=2,sort_keys=True),'```',
              '', '**Decision: '+r['decision']+'**',
              '', 'No child has been run by this analysis. A positive screen would require its own frozen parent/code/config/budget before any new child result. A negative screen closes this tested family; it does not discard Keltner or other Top5 lanes.',
              '', 'Reused DEV evidence is adaptive, not independent validation. PR1183 state-child decisions and Break validation REJECT remain unchanged. G5B/G6/order/live authority and collection are unchanged; paid calls = 0.',
              '', 'Data reuse and prior trials:', '', '```json',json.dumps(r['data_reuse_history'],indent=2,sort_keys=True),'```']
    return ('\n'.join(lines)+'\n').encode()


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--data-dir',type=Path,required=True);ap.add_argument('--verify-only',action='store_true');a=ap.parse_args()
    r=run(a.data_dir.resolve(),a.verify_only)
    print(json.dumps({'receipt_sha256':r['receipt_sha256'],'decision':r['decision'],'triggered_parent_T':r['triggered_parent_T'],'screen':r['primary_observable_screen']},indent=2))
