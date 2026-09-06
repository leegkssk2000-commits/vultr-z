"""One additive, frozen DEV trial: signal-low failure, never an operating policy."""
from __future__ import annotations
import argparse
import gzip
import json
from pathlib import Path
from unittest.mock import patch
from backend.research.rebuild import top5_no_credit_exit_v1 as prior

old = prior.old
ROOT = old.ROOT
LANE = 'supertrend_pullback_main'
CONTRACT = 'backend/research/contracts/supertrend_signal_invalidation_v1.json'
OUTPUT = 'research/development_evidence/SUPERTREND_INVALIDATION_20260906_V1'
RULE = 'HELD_CLOSE_BELOW_FROZEN_SIGNAL_LOW_EXIT_NEXT_OPEN'
SCOPE = {
    'scope': 'G5_DEV_NO_CREDIT', 'lane': LANE, 'additional_trial_budget': 1,
    'rule': RULE, 'owner': 'backend/research/rebuild/supertrend_signal_invalidation_v1.py',
    'contract': CONTRACT, 'prior_trial_budgets_reset': False,
    'entries_fixed': True, 'initial_risk_fixed': True, 'protective_stop_fixed': True,
    'all_parent_wins_and_losses': True, 'next_open_fill': True,
    'full_lifecycle_required': True, 'formal_credit': 0, 'G6_authorized': False,
    'operating_replacement': False, 'validation_access': False, 'OOS_access': False,
    'live_order_execution_authority': 'UNCHANGED_BLOCKED',
}


def overlay(trade, event, rows, policy, costs, scenario, enabled=True):
    """Signal low is known before entry. Only held closes schedule an open fill."""
    t = dict(trade)
    if t['side'] != 'long' or t['lane_id'] != LANE:
        raise RuntimeError('UNAUTHORIZED_LANE_OR_SIDE')
    if not 0 <= t['signal_index'] < t['entry_index'] <= t['exit_index'] < len(rows):
        raise RuntimeError('INVALID_EVENT_ORDER')
    interval = t['native_interval_ms']
    level = rows[t['signal_index']]['low']
    available = rows[t['signal_index']].get('bar_open_ts', rows[t['signal_index']].get('ts_ms')) + interval
    if available > t['entry_ts']:
        raise RuntimeError('SIGNAL_LEVEL_NOT_AVAILABLE_AT_ENTRY')
    trace = {'rule': RULE, 'signal_low': level, 'level_available_ts': available,
             'trigger_at_ms': None, 'trigger_close': None, 'exit_changed': False}
    if enabled:
        # Native terminal bar cannot produce a signal after the position closes.
        for j in range(t['entry_index'], t['exit_index']):
            if rows[j]['close'] >= level:
                continue
            k = j + 1
            px = rows[k]['open']
            stamp = rows[k].get('bar_open_ts', rows[k].get('ts_ms'))
            trigger = rows[j].get('bar_open_ts', rows[j].get('ts_ms')) + interval
            if stamp != trigger:
                raise RuntimeError('NONCONTIGUOUS_NEXT_OPEN')
            held = rows[t['entry_index']:k]
            hi = max([px] + [r['high'] for r in held])
            lo = min([px] + [r['low'] for r in held])
            t.update(exit_index=k, exit_ts=stamp, exit_price=px,
                     exit_reason='SIGNAL_LOW_INVALIDATION_NEXT_OPEN',
                     gross_bps=(px/t['entry_price']-1)*10000,
                     hold_ms=stamp-t['entry_ts'], native_exit_bar_open_ts=stamp,
                     exit_timestamp_semantics='EXACT_NEXT_BAR_OPEN_MODELLED',
                     mfe_bps=max(0., (hi/t['entry_price']-1)*10000),
                     mae_bps=min(0., (lo/t['entry_price']-1)*10000),
                     excursion_semantics='HELD_COMPLETE_BARS_PLUS_EXIT_OPEN_ONLY')
            trace.update(trigger_at_ms=trigger, trigger_close=rows[j]['close'], exit_changed=True)
            break
    t.pop('trade_sha256', None)
    t.update(entry_key=prior.entry_key(t), exit_overlay=trace,
             initial_risk=dict(event.get('risk_size', {})),
             initial_exposure=dict(event.get('exposure', {})),
             original_protective_sl=event.get('sl'), original_tp=event.get('tp'),
             native_geometry_scope='FROZEN_V2_FIXED_HOLD_NO_NATIVE_SL_SPECIFIED')
    return old.charge(t,t['symbol'],t['lane_id'],scenario,policy,costs,rows,interval)


def authorize():
    c = old.read(CONTRACT)
    old.probe.verify_seal(c, 'SIGNAL_INVALIDATION_PREREGISTRATION')
    if c['scope'] != SCOPE or c['new_rule_outcomes_seen_at_freeze'] is not False:
        raise RuntimeError('SCOPE_OR_OUTCOME_FREEZE_DRIFT')
    governance = old.read(prior.GOVERNANCE)['effective_development_objective']
    if governance.get('supertrend_signal_invalidation_followup') != SCOPE:
        raise RuntimeError('FOLLOWUP_SCOPE_NOT_AUTHORIZED')
    if governance['development_exit_experiment'] != c['preserved_prior_exit_scope']:
        raise RuntimeError('PR1184_SCOPE_CHANGED')
    for key,value in old.probe.DEV_AUTH.items():
        if c.get(key) != value: raise RuntimeError('FORMAL_AUTHORITY:'+key)
    for path,value in {**c['code_files_sha256'], **c['evidence_files_sha256']}.items():
        if old.file_sha(ROOT/path) != value: raise RuntimeError('FROZEN_IDENTITY:'+path)
    prior.previous.verify_previous()
    return c


def report(r):
    v = r['result']
    lines = ['# Supertrend signal invalidation — reused DEV, no credit', '',
             'One preregistered follow-up after PR1185. Long held close below the frozen signal-bar low exits at the next open. No sweep, entry filter, or cost-cover overlay. Original fixed hold and absent V2 protective-stop specification are preserved.', '',
             'Modelled equal-notional trade bps; not account returns or actual fills. Funding uses the existing research proxy. Prior DEV outcomes were already seen; this is adaptive development, not independent validation.', '',
             '| Version | T | Gross E bps | Net E bps | PF | WR % | Payoff | Cost2 E bps |',
             '|---|---:|---:|---:|---:|---:|---:|---:|']
    for name,m in v['metrics'].items():
        b=m['base_cost']; c=m['cost2x']
        lines.append(f"| {name} | {b['completed_T']} | {b['gross_bps']/max(1,b['completed_T']):.4f} | {b['expectancy_bps_per_trade']:.4f} | {b['PF']} | {100*b['win_rate']:.2f} | {b['realized_payoff']} | {c['expectancy_bps_per_trade']:.4f} |")
    lines += ['', '**Decision: '+v['comparison']['decision']+'**', '',
              'Full attribution, uncertainty, risk and prior cost-cover child comparison:',
              '```json', json.dumps({k:v[k] for k in ['comparison','attribution','diagnostics','uncertainty','prior_exit_child','time_only_tail']},indent=2), '```', '',
              'No operating change, validation/OOS access, paid AI, G5B/G6 credit or order authority. Prior failures and trial history are retained.']
    return ('\n'.join(lines)+'\n').encode()


def run(data_dir, verify_only=False):
    c=authorize(); p,dev,four,one,access=prior.previous.load_inputs(data_dir)
    if p['combined_data_sha256']!=c['data_sha256'] or p['cost_binding_sha256']!=c['cost_sha256']:
        raise RuntimeError('DATA_COST_BINDING')
    p={**p,'batch_id':c['batch_id'],'receipt_sha256':c['receipt_sha256'],
       'code_files_sha256':{**p['code_files_sha256'],**c['code_files_sha256']}}
    read=prior.previous.read_lines
    base=[t for t in read(ROOT/old.OUTPUT/'baseline/trades.jsonl.gz') if t['lane_id']==LANE]
    es=[e for e in read(ROOT/old.OUTPUT/'baseline/events.jsonl.gz') if e['lane_id']==LANE]
    previous_receipt=old.read(prior.OUTPUT+'/receipt.json')['lanes'][LANE]
    fmap={(e['symbol'],e['signal_index']):e for e in es}
    costs=dev['cost_by_symbol']; full_base=[]; full_child=[]; be=[]; ce=[]; audit=[]; eligible=set()
    with old.probe.io_boundary([ROOT/old.FREEZE], ROOT/OUTPUT):
        fixed=[overlay(t,fmap[t['symbol'],t['signal_index']],four[t['symbol']],p,costs,'fixed_child') for t in base]
        # Reuse the existing evaluator, eligibility and ownership. Only the overlay differs.
        with patch.object(prior,'overlay',overlay):
            for symbol,rows in four.items():
                pool,a=prior.candidate_pool(rows,symbol,LANE,p,costs,[e for e in es if e['symbol']==symbol])
                eligible.update((symbol,e['signal_index']) for e in a if e['full_lifecycle_eligible'])
                bt,b=prior.lifecycle(pool,rows,p,costs,'lifecycle_base',False)
                ct,d=prior.lifecycle(pool,rows,p,costs,'lifecycle_child',True)
                full_base.extend(bt); full_child.extend(ct); be.extend(b); ce.extend(d); audit.extend(a)
        prior.assert_parent_parity(full_base,[t for t in base if (t['symbol'],t['signal_index']) in eligible])
        if {prior.entry_key(t) for t in fixed}!={prior.entry_key(t) for t in base}:
            raise RuntimeError('FIXED_ENTRY_DRIFT')
        versions={'fixed_base':base,'fixed_child':fixed,'lifecycle_base':full_base,'lifecycle_child':full_child}
        metrics={k:old.metrics(v,es if k.startswith('fixed') else be if k=='lifecycle_base' else ce,p,list(four)) for k,v in versions.items()}
        attrs={'fixed':prior.attribute(base,fixed),'lifecycle':prior.attribute(full_base,full_child)}
        unc={'fixed':old.probe.cluster_uncertainty({'base':base,'child':fixed},p),
             'lifecycle':old.probe.cluster_uncertainty({'base':full_base,'child':full_child},p)}
        diagnostics={k:prior.diagnostic.diagnostics(v,*p['development_interval_ms'])[0] for k,v in versions.items()}
        result={'metrics':metrics,'attribution':attrs,'uncertainty':unc,'diagnostics':diagnostics,
                'comparison':prior.verdict(metrics,attrs,unc,c['inherited_selection_rule']),
                'prior_exit_child':{'metrics':previous_receipt['metrics']['lifecycle_child'],
                                    'decision':previous_receipt['comparison'],
                                    'rerun':False},
                'parent_ablation_parity':'PASS','all_parent_wins_and_losses':True,
                'time_only_tail':{'raw_signals_excluded':sum(not e['full_lifecycle_eligible'] for e in audit),
                                  'parent_completed_excluded':len(base)-len(full_base)}}
    out=ROOT/OUTPUT; artifacts={}
    if not verify_only: out.mkdir(parents=True,exist_ok=True)
    ledgers=[]
    for stage,ts in versions.items():
        for t in ts:
            item=dict(t,comparison_stage=stage); item.pop('trade_sha256',None)
            item['trade_sha256']=old.digest(item);ledgers.append(item)
    events=[dict(e,comparison_stage=stage) for stage,vs in [('raw_pool',audit),('lifecycle_base',be),('lifecycle_child',ce)] for e in vs]
    for name,vs in [('trades',ledgers),('events',events)]:
        plain=b''.join(old.probe.canonical(t) for t in sorted(vs,key=lambda t:(t['comparison_stage'],t['symbol'],t['signal_ts'])))
        path=out/(name+'.jsonl.gz'); payload=path.read_bytes() if path.exists() else gzip.compress(plain,mtime=0)
        if gzip.decompress(payload)!=plain: raise RuntimeError('REPRODUCTION_DRIFT:'+name)
        old.probe.write_immutable(path,payload,verify_only=verify_only)
        artifacts[name]={'path':str(path.relative_to(ROOT)),'rows':len(vs),'file_sha256':old.file_sha(path)}
    r=old.seal({'batch_id':c['batch_id'],'contract_sha256':c['receipt_sha256'],'result':result,
                'source_access':access,'data_sha256':c['data_sha256'],'cost_sha256':c['cost_sha256'],
                'artifacts':artifacts,'new_exit_hypotheses':1,'parameter_sweeps':0,
                'validation_rows_decoded':0,'OOS_rows_decoded':0,'paid_AI_calls':0,
                'G6_authorized':False,'production_credit':0,'operating_replacement':False,
                'prior_failures_preserved':True,'data_reuse_history':c['data_reuse_history'],**old.probe.DEV_AUTH})
    old.probe.write_immutable(out/'receipt.json',old.probe.canonical(r),verify_only=verify_only)
    old.probe.write_immutable(out/'RESULTS.md',report(r),verify_only=verify_only)
    paths=[CONTRACT]+[str((out/x).relative_to(ROOT)) for x in ('receipt.json','RESULTS.md','trades.jsonl.gz','events.jsonl.gz')]
    durable=old.seal({'batch_id':c['batch_id'],'result_receipt_sha256':r['receipt_sha256'],
                     'files_sha256':{x:old.file_sha(ROOT/x) for x in paths},
                     'preserved_files_sha256':c['evidence_files_sha256'],'code_files_sha256':c['code_files_sha256'],**old.probe.DEV_AUTH})
    old.probe.write_immutable(out/'durable_receipt.json',old.probe.canonical(durable),verify_only=verify_only)
    return r


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--data-dir',type=Path,required=True);ap.add_argument('--verify-only',action='store_true');a=ap.parse_args()
    r=run(a.data_dir.resolve(),a.verify_only)
    print(json.dumps({'receipt':r['receipt_sha256'],'decision':r['result']['comparison'],
                      'fixed_delta_bps':r['result']['attribution']['fixed']['net_delta_bps'],
                      'full_delta_bps':r['result']['attribution']['lifecycle']['net_delta_bps']},indent=2))
