"""One preregistered, entry-only state experiment on the reused Top5 DEV ledger.

State consumes raw eligible signals, including signals during native ownership.
This is deliberately a first-signal policy, not hindsight selection of a first fill.
"""
from __future__ import annotations
import argparse
import copy
import gzip
import json
from collections import defaultdict
from pathlib import Path
from unittest.mock import patch
from backend.research.rebuild import top5_external_repair_v1 as previous
from backend.research.rebuild import top5_external_metrics_v1 as attribution

old = previous.old
ROOT = old.ROOT
OUTPUT = 'research/development_evidence/TOP5_STATE_20260906_V1'
CONTRACT = 'backend/research/contracts/top5_state_children_v1.json'


def states(rows, lane, events):
    """Prefix causal setup states. No trade outcomes or validation inputs."""
    closes = [r['close'] for r in rows]
    ema20 = old.native.kernel.ema(closes, 20)
    ema50 = old.native.kernel.ema(closes, 50)
    signals = {e['signal_index']: e.get('side', 'long') for e in events}
    result = {}; used = {'long': False, 'short': False}; epoch = {'long': 0, 'short': 0}
    broken_level = None; armed = False
    for i, row in enumerate(rows):
        close = row['close']; side = signals.get(i, 'long')
        if lane in old.LANES[:2]:
            for direction, sign in [('long', 1), ('short', -1)]:
                if sign * (close - ema50[i]) <= 0:
                    if used[direction]: epoch[direction] += 1
                    used[direction] = False
            eligible = not used[side]
            reason = 'FIRST_RAW_SIGNAL_SINCE_EMA50_RESET' if eligible else 'REPEAT_SAME_EMA50_SETUP'
        elif lane == old.LANES[2]:
            if broken_level is not None and close <= broken_level:
                broken_level = None; epoch['long'] += 1
            eligible = broken_level is None and i > 0 and rows[i-1]['close'] > rows[i-1]['open']
            reason = 'PREPARED_FIRST_BREAK' if eligible else 'ACTIVE_BREAK_OR_UNPREPARED'
        elif lane == old.LANES[3]:
            intact = ema20[i] > ema50[i] and close > ema50[i] and (i > 0 and ema50[i] > ema50[i-1])
            if not intact:
                if armed: epoch['long'] += 1
                armed = False
            eligible = armed and intact and close > ema20[i]
            reason = 'INTACT_TREND_PULLBACK_RECOVERY' if eligible else 'NO_INTACT_PULLBACK_SETUP'
            if intact and close <= ema20[i]: armed = True
        else:
            if close <= ema20[i] or ema20[i] <= ema50[i]:
                if used['long']: epoch['long'] += 1
                used['long'] = False
            eligible = not used['long']
            reason = 'FIRST_EXPANSION_AFTER_PULLBACK' if eligible else 'REPEAT_LATE_EXPANSION'
        if i in signals:
            result[i] = {'state_entry_pass': bool(eligible), 'setup_id': f'{side}:{epoch[side]}',
                         'reason': reason, 'ema20': ema20[i], 'ema50': ema50[i],
                         'break_level_before_signal': broken_level,
                         'available_ts': row.get('bar_close_ts', row.get('ts_ms', row.get('ts',0))+3_600_000)}
            if lane in old.LANES[:2] or lane == old.LANES[4]: used[side] = True
            elif lane == old.LANES[2] and broken_level is None:
                broken_level = max(r['high'] for r in rows[max(0, i-50):i]) if i else None
            elif lane == old.LANES[3]:
                armed = False; epoch['long'] += 1
    return result


def populations():
    previous.verify_previous()
    base = previous.read_lines(ROOT / old.OUTPUT / 'baseline/trades.jsonl.gz')
    events = previous.read_lines(ROOT / old.OUTPUT / 'baseline/events.jsonl.gz')
    first = previous.read_lines(ROOT / old.OUTPUT / 'comparison/trades.jsonl.gz')
    second = previous.read_lines(ROOT / previous.OUTPUT / 'comparison/trades.jsonl.gz')
    return base, events, first, second


def loss_groups(trades, rows_by_symbol, state_maps):
    groups = defaultdict(list); reentry = []; seen = set()
    for t in sorted(trades, key=lambda t: (t['signal_ts'], t['symbol'], t['identity'])):
        rows = rows_by_symbol[t['symbol']]; sign = 1 if t['side'] == 'long' else -1
        # Only marks strictly before the exit bar, whose intrabar order is unknown.
        marks = [sign*(r['close']/t['entry_price']-1)*10000 for r in rows[t['entry_index']:t['exit_index']]]
        prior_mark_above_cost = max(marks, default=0.) > t['cost_bps']
        if t['net_bps'] >= 0: label = 'NET_WIN_OR_FLAT'
        elif prior_mark_above_cost: label = 'PROFIT_GIVEBACK_CLOSED_MARK_OBSERVER'
        elif t['gross_bps'] >= 0: label = 'MOVE_BELOW_COST'
        else: label = 'DIRECTION_LOSS_WITHOUT_PRIOR_PROFITABLE_CLOSE'
        groups[label].append(t)
        setup = (t['symbol'], state_maps[t['symbol']][t['signal_index']]['setup_id'])
        if setup in seen: reentry.append(t)
        seen.add(setup)
    def sums(ts):
        return {'T': len(ts), 'gross_bps': sum(t['gross_bps'] for t in ts), 'net_bps': sum(t['net_bps'] for t in ts),
                'winning_profit_bps': sum(max(0,t['net_bps']) for t in ts), 'loss_bps': -sum(min(0,t['net_bps']) for t in ts)}
    return {'exclusive_outcome_classes': {k:sums(v) for k,v in sorted(groups.items())},
            'same_setup_reentry': sums(reentry), 'exit_observation_credit': 0, 'optimized_exit_selected': False}


def prepare(data_dir):
    p, dev, four, one, access = previous.load_inputs(data_dir)
    base, events, first, second = populations(); maps = {}; report = {}
    for lane in old.LANES:
        rows = one if lane in old.LANES[:2] else four
        maps[lane] = {s:states(rs,lane,[e for e in events if e['lane_id']==lane and e['symbol']==s]) for s,rs in rows.items()}
        selected = [t for t in base if t['lane_id']==lane]
        accepted = [t for t in selected if maps[lane][t['symbol']][t['signal_index']]['state_entry_pass']]
        rejected = [t for t in selected if not maps[lane][t['symbol']][t['signal_index']]['state_entry_pass']]
        report[lane] = {'existing_parent': loss_groups(selected, rows, maps[lane]),
                        'first_setup_parent_T':len(accepted), 'repeat_or_unprepared_parent_T':len(rejected),
                        'repeat_or_unprepared_parent_net_bps':sum(t['net_bps'] for t in rejected),
                        'repeat_or_unprepared_parent_winner_bps':sum(max(0,t['net_bps']) for t in rejected)}
    return p,dev,four,one,access,base,events,first,second,maps,report


def run(data_dir, mode):
    p,dev,four,one,access,base,events,first,second,maps,report = prepare(data_dir)
    out = ROOT/OUTPUT
    if mode != 'verify': out.mkdir(parents=True, exist_ok=True)
    if mode == 'diagnose':
        value = old.seal({'state':'PARENT_DIAGNOSIS_ONLY', 'lanes':report, 'new_child_economics_run':False,
                          'validation_rows_decoded':0, 'OOS_rows_decoded':0, 'source_access':access, **old.probe.DEV_AUTH})
        old.probe.write_immutable(out/'diagnosis.json',old.probe.canonical(value))
        return value
    contract = old.read(CONTRACT); old.probe.verify_seal(contract,'STATE_PREREGISTRATION')
    if contract['new_child_budget_per_lane'] != 1 or contract['outcomes_seen_at_freeze'] is not False:
        raise RuntimeError('STATE_PREREGISTRATION_BUDGET')
    if contract['optional_component_bindings'] != {'G7':[], 'G8':[], 'G9':[]}:
        raise RuntimeError('UNREVIEWED_OPTIONAL_COMPONENT_COUPLING')
    for path,sha in {**contract['code_files_sha256'], **contract['evidence_files_sha256']}.items():
        if old.file_sha(ROOT/path) != sha: raise RuntimeError('STATE_FROZEN_IDENTITY:'+path)
    p = {**p,'batch_id':contract['batch_id'], 'receipt_sha256':contract['receipt_sha256'],
         'code_files_sha256':{**p['code_files_sha256'],**contract['code_files_sha256']}}
    frozen = old.read(old.FREEZE)['children']
    gate = old.read('backend/research/contracts/a1_top5_entry_transplant_replay_v1.json')['selection_rule']
    results = {}; all_trades = []; all_events = []
    for lane in old.LANES:
        cfg=contract['lanes'][lane]; native=lane in old.LANES[:2]; rows=one if native else four
        parent = [t for t in base if t['lane_id']==lane]
        failed1 = [t for t in first if t['lane_id']==lane and t['scenario']=='child']
        failed2 = [t for t in second if t['lane_id']==lane and t['scenario']=='child']
        if cfg['run_authorized'] is not True:
            versions={'parent':parent,'pr1180_child':failed1}
            if failed2: versions['pr1181_child']=failed2
            results[lane]={'child_id':None, 'rule':cfg['rule'], 'comparison':{'decision':'NOT_RUN', 'reason':cfg['reason']},
                          'metrics':{k:old.metrics(v,[],p,list(rows)) for k,v in versions.items()},
                          'loss_classes':{k:loss_groups(v,rows,maps[lane]) for k,v in versions.items()},
                          'validation':'NOT_RUN','OOS':'NOT_RUN','P0':'UNCONFIRMED',
                          'prior_break_validation':'PRESERVED_REJECT_NOT_INDEPENDENT' if lane==old.LANES[2] else 'NOT_RUN'}
            continue
        child=[]; ce=[]
        for s,rs in rows.items():
            original = old.geometry
            def extended(r,i,side='long'):
                return {**original(r,i,side), **maps[lane][s].get(i,{'state_entry_pass':False})}
            with patch.object(old,'geometry',extended):
                if native: ts, es = old.one_hour(rs,s,lane,p,dev['cost_by_symbol'],'state_child','state_entry_pass')
                else:
                    spec=next(x for x in frozen if x['lane_id']==lane)
                    ts,es=old.four_hour(rs,s,spec,p,dev['cost_by_symbol'],'state_child','state_entry_pass')
            child.extend(ts); ce.extend(es)
        raw_events=[e for e in events if e['lane_id']==lane]
        pm=old.metrics(parent,raw_events,p,list(rows)); cm=old.metrics(child,ce,p,list(rows))
        control=sorted(parent,key=lambda t:old.digest(['fixed_seed_1179',t['identity']]))[:len(child)]
        uncertainty=old.probe.cluster_uncertainty({'base':parent,'child':child,'matched_hash_control':control},p)
        comparison=old.compare(parent,child,control,pm,cm,uncertainty,gate)
        versions={'parent':parent,'pr1180_child':failed1,'state_child':child}
        if failed2: versions['pr1181_child']=failed2
        results[lane]={'child_id':cfg['child_id'], 'rule':cfg['rule'], 'comparison':comparison,
                      'metrics':{k:old.metrics(v,ce if k=='state_child' else [],p,list(rows)) for k,v in versions.items()},
                      'attribution':{k:attribution.attribution(v,child) for k,v in versions.items() if k!='state_child'},
                      'loss_classes':{k:loss_groups(v,rows,maps[lane]) for k,v in versions.items()},
                      'diagnostics':{k:attribution.diagnostics(v,*p['development_interval_ms'])[0] for k,v in versions.items()},
                      'uncertainty':uncertainty, 'validation':'NOT_RUN', 'OOS':'NOT_RUN', 'P0':'UNCONFIRMED',
                      'break_seen_validation_not_independent':lane==old.LANES[2]}
        all_trades.extend(child); all_events.extend(ce)
    artifacts={}
    for name,values in [('trades',all_trades),('events',all_events)]:
        plain=b''.join(old.probe.canonical(x) for x in sorted(values,key=lambda x:(x['lane_id'],x['symbol'],x['signal_ts'])))
        path=out/(name+'.jsonl.gz'); data=path.read_bytes() if path.exists() else gzip.compress(plain,mtime=0)
        if gzip.decompress(data)!=plain: raise RuntimeError('STATE_REPRODUCTION_DRIFT:'+name)
        old.probe.write_immutable(path,data,verify_only=mode=='verify')
        artifacts[name]={'path':str(path.relative_to(ROOT)),'rows':len(values),'file_sha256':old.file_sha(path)}
    from backend.research.rebuild.g5_g14_governance_validator_v1 import optional_stage_applicability
    # Disabled components are never called by this entry-admission adapter. The
    # same frozen default native owner, ledger, data and cost are the control.
    default_sha=old.digest({'native_control':old.read(old.POLICY)['code_files_sha256'],
                            'ledger':old.file_sha(ROOT/old.OUTPUT/'baseline/trades.jsonl.gz'),
                            'data':p['combined_data_sha256'],'cost':p['cost_binding_sha256']})
    optional={}
    for stage in (7,8,9):
        proof={'enabled':False, 'bindings':contract['optional_component_bindings'][f'G{stage}'], 'reviewed':True,
               'code_sha256':old.digest(p['code_files_sha256']), 'config_sha256':contract['receipt_sha256'],
               'baseline_behaviour_sha256':default_sha,'disabled_behaviour_sha256':default_sha,
               'safety_checks':{k:True for k in ['risk','stop','cost','integrity','explicit_live_approval']}}
        optional[f'G{stage}']={'scope':'THIS_UNBOUND_DEV_ADAPTER_ONLY_NOT_OPERATING_RUNTIME','evidence':proof,
                              **optional_stage_applicability(stage,proof)}
    value=old.seal({'batch_id':contract['batch_id'], 'contract_sha256':contract['receipt_sha256'], 'lanes':results,
                   'optional_stage_applicability':optional,
                   'artifacts':artifacts, 'data_sha256':p['combined_data_sha256'], 'cost_sha256':p['cost_binding_sha256'],
                   'code_sha256':old.digest(p['code_files_sha256']), 'source_access':access,
                   'validation_rows_decoded':0, 'OOS_rows_decoded':0, 'paid_AI_calls':0,
                   'Gemini_direct_video':'NOT_RUN_MISSING_AUTHENTICATED_MANUAL_TRANSPORT',
                   'exit_candidates_tested':0, 'new_G5B_T':0, **old.probe.DEV_AUTH})
    old.probe.write_immutable(out/'receipt.json',old.probe.canonical(value),verify_only=mode=='verify')
    return value


if __name__=='__main__':
    ap=argparse.ArgumentParser(); ap.add_argument('--data-dir',type=Path,required=True)
    ap.add_argument('--mode',choices=['diagnose','run','verify'],required=True); args=ap.parse_args()
    r=run(args.data_dir.resolve(),args.mode)
    print(json.dumps({'receipt_sha256':r['receipt_sha256'], 'lanes':{k:v.get('comparison',v) for k,v in r['lanes'].items()}},indent=2))
