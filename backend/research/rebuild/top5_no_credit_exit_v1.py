"""Preregistered G5 DEV exit overlay on frozen native/common evaluator trades.

No operating imports, validation access, parameter search or formal exit credit.
The existing engines generate potential trades; their ownership primitives select
the full lifecycle. A disabled overlay must reproduce the frozen parent prefix.
"""
from __future__ import annotations
import argparse
import gzip
import json
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from backend.research.rebuild import top5_external_repair_v1 as previous
from backend.research.rebuild import top5_external_metrics_v1 as diagnostic

old = previous.old
ROOT = old.ROOT
CONTRACT = 'backend/research/contracts/top5_no_credit_exit_v1.json'
OUTPUT = 'research/development_evidence/TOP5_EXIT_20260906_V1'
GOVERNANCE = 'backend/research/rebuild/g5_g14_governance_contract_v1.json'
HOUR = 3_600_000
RULE = {
    'id': 'COST_COVERED_CLOSE_THEN_NONPOSITIVE_CLOSE_NEXT_OPEN_V1',
    'arm': 'First held closed bar with gross mark minus accrued bound exit cost > 0',
    'trigger': 'A later held closed bar with gross mark minus accrued bound exit cost <= 0',
    'fill': 'NEXT_BAR_OPEN; no exit on the triggering close',
    'priority': 'Prior native SL/TP/timeout wins; pending next-open exit precedes that bar intrabar path',
    'gap': 'Pending exit fills at observed open, including a gap through the unchanged stop',
    'cost': 'Existing bound model plus unchanged 20bps floor; funding recomputed through actual modelled exit',
    'cost2x': 'Same frozen actions and fills, double all charged cost; no alternative trigger search',
}


def entry_key(t):
    return old.digest({k:t[k] for k in ('lane_id','symbol','signal_ts','entry_ts','side')})


def mark_net(entry_price, side, entry_ts, close_price, close_ts, binding):
    sign = 1 if side == 'long' else -1
    gross = sign * (close_price-entry_price) / entry_price * 10000
    return gross - max(20., old.probe.cost_components(entry_ts,close_ts,binding)['cost_bps'])


def overlay(trade, event, rows, policy, costs, scenario, enabled=True):
    """Only preceding closed marks can schedule an exit; never outcome labels."""
    t = dict(trade); interval = t['native_interval_ms']; pending = None; armed_at = None
    trace = {'entry_key':entry_key(t), 'armed_at_ms':None, 'trigger_at_ms':None,
             'trigger_mark_net_bps':None, 'exit_changed':False, 'rule':RULE['id']}
    if enabled:
        for j in range(t['entry_index'], t['exit_index']+1):
            row = rows[j]
            open_ts = row.get('bar_open_ts', row.get('ts_ms'))
            if pending is not None:
                # This branch reads the OPEN only. The same bar's high/low and
                # final close are unavailable at this fill and cannot influence it.
                px = row['open']; sign = 1 if t['side']=='long' else -1
                sl = event.get('sl')
                gap_stop = sl is not None and sign*(px-sl) <= 0
                path = rows[t['entry_index']:j]
                hi = max([px]+[r['high'] for r in path]); lo = min([px]+[r['low'] for r in path])
                t.update(exit_index=j, exit_ts=open_ts, exit_price=px,
                         exit_reason='PENDING_EXIT_GAP_THROUGH_STOP' if gap_stop else 'COST_COVERED_PROFIT_LOST_NEXT_OPEN',
                         gross_bps=sign*(px-t['entry_price'])/t['entry_price']*10000,
                         hold_ms=open_ts-t['entry_ts'], native_exit_bar_open_ts=open_ts,
                         exit_timestamp_semantics='EXACT_NEXT_BAR_OPEN_MODELLED',
                         mfe_bps=max(0.,(hi/t['entry_price']-1)*10000 if sign>0 else (1-lo/t['entry_price'])*10000),
                         mae_bps=min(0.,(lo/t['entry_price']-1)*10000 if sign>0 else (1-hi/t['entry_price'])*10000),
                         excursion_semantics='HELD_COMPLETE_BARS_PLUS_EXIT_OPEN_ONLY')
                trace.update(exit_changed=True, trigger_at_ms=pending[0], trigger_mark_net_bps=pending[1])
                break
            # The original engine has already modelled SL-first / TP / timeout.
            # A terminal bar cannot provide a close signal to an already closed position.
            if j == t['exit_index']:
                break
            close_ts = open_ts+interval
            value = mark_net(t['entry_price'],t['side'],t['entry_ts'],row['close'],close_ts,costs[t['symbol']])
            if armed_at is not None and value <= 0:
                pending = (close_ts,value)
            elif value > 0 and armed_at is None:
                armed_at = close_ts
    trace['armed_at_ms'] = armed_at
    t.pop('trade_sha256',None)
    t.update(entry_key=entry_key(t), exit_overlay=trace,
             initial_risk=dict(event.get('risk_size',{})), initial_exposure=dict(event.get('exposure',{})),
             original_protective_sl=event.get('sl'), original_tp=event.get('tp'),
             native_geometry_scope='FROZEN_NATIVE_SL' if interval==HOUR else 'FROZEN_V2_FIXED_HOLD_NO_NATIVE_SL_SPECIFIED')
    return old.charge(t,t['symbol'],t['lane_id'],scenario,policy,costs,rows,interval)


def candidate_pool(rows, symbol, lane, policy, costs, source_events):
    """Independent potential exits from the ORIGINAL evaluators, not a new engine.

    Lifecycle admission uses a time-only common eligibility rule: the maximum
    original hold must finish strictly before DEV end. This avoids the native
    owner's outcome-dependent incomplete-tail censoring. Fixed-entry comparison
    still includes every previously sealed completed parent trade.
    """
    native = lane in old.LANES[:2]; ownership = {}; end = policy['development_interval_ms'][1]
    if native:
        owner = old.native.owner; actual = owner.ev.execution_ownership_policy
        def observe(intent):
            value = actual(intent); ownership[intent.signal_ts+HOUR] = value
            return value
        with patch.object(owner.ev,'ownership_blocked',lambda *a:False), \
             patch.object(owner.ev,'execution_ownership_policy',observe):
            potential, events = old.one_hour(rows,symbol,lane,policy,costs,'potential')
    else:
        spec = next(x for x in old.read(old.FREEZE)['children'] if x['lane_id']==lane)['executable_spec']
        events = [dict(e) for e in source_events]; potential = []
        for e in events:
            answer = old.common.evaluate_development_events(rows,[e['signal_index']],
                split_start_ms=policy['development_interval_ms'][0],split_end_ms=end,
                interval_ms=4*HOUR,hold_bars=spec['max_hold_bars'])
            potential.extend(old.charge(t,symbol,lane,'potential',policy,costs,rows,4*HOUR) for t in answer['trades'])
    if [(e['signal_index'],e['signal_ts'],e.get('side','long')) for e in events] != \
       [(e['signal_index'],e['signal_ts'],e.get('side','long')) for e in source_events]:
        raise RuntimeError('FROZEN_RAW_ENTRY_SIGNAL_PARITY')
    by_signal = {t['signal_index']:t for t in potential}; pool = []; audited = []
    for e in events:
        e = dict(e); ei = e['signal_index']+1
        horizon = ei+max(1,int(e['timeout']['bars'])) if native else ei+spec['max_hold_bars']-1
        interval = HOUR if native else 4*HOUR
        eligible = horizon < len(rows)-1 and rows[horizon].get('bar_close_ts',rows[horizon].get('ts_ms',0)+interval) < end
        e['full_lifecycle_eligible'] = eligible
        e['ownership'] = list(ownership[e['signal_ts']]) if native else [True,0]
        e['time_only_max_hold_end_index'] = horizon
        e['exclusion_reason'] = None if eligible else 'MAX_HOLD_CROSSES_COMMON_DEV_END_EMBARGO'
        if eligible:
            if e['signal_index'] not in by_signal: raise RuntimeError('ELIGIBLE_POTENTIAL_TRADE_MISSING')
            pool.append((by_signal[e['signal_index']],e))
        audited.append(e)
    return pool,audited


def lifecycle(pool, rows, policy, costs, scenario, enabled):
    trades = []; events = []; blocked_until = -1; last_exit_index = -1
    for raw,event in sorted(pool,key=lambda x:x[0]['signal_index']):
        e = dict(event); native = raw['native_interval_ms']==HOUR; owns,cooldown = e['ownership']
        blocked = old.native.owner.ev.ownership_blocked(raw['entry_ts'],blocked_until) if native else raw['signal_index']<=last_exit_index
        if owns and blocked:
            e.update(status='EXCLUDED',exclusion_reason='POSITION_OWNERSHIP_OR_FROZEN_COOLDOWN')
        else:
            t = overlay(raw,e,rows,policy,costs,scenario,enabled); trades.append(t)
            e.update(status='COMPLETED',exclusion_reason=None)
            if native and owns:
                # Keep the native model's exit-bar-open cooldown convention.
                blocked_until = old.native.owner.ev.reserve_position_ownership(
                    exit_ts=t['native_exit_bar_open_ts'],open_horizon_ts=None,
                    cooldown_bars=cooldown,timeframe_ms=HOUR)
            last_exit_index=t['exit_index']
        e['scenario']=scenario;events.append(e)
    return trades,events


def assert_parent_parity(actual, expected):
    a={entry_key(t):t for t in actual};b={entry_key(t):t for t in expected}
    if len(a)!=len(actual) or len(b)!=len(expected) or set(a)!=set(b):
        raise RuntimeError('PARENT_ENTRY_PARITY_OR_DUPLICATE')
    fields=('entry_price','exit_price','entry_ts','exit_ts','side','gross_bps','net_bps','cost_bps','hold_ms')
    for key in a:
        if any(a[key][f]!=b[key][f] for f in fields): raise RuntimeError('PARENT_ENGINE_ABLATION_PARITY')


def attribute(parent, child):
    p={entry_key(t):t for t in parent};c={entry_key(t):t for t in child}
    if len(p)!=len(parent) or len(c)!=len(child): raise RuntimeError('DUPLICATE_ENTRY')
    shared=sorted(p.keys()&c.keys());removed=sorted(p.keys()-c.keys());added=sorted(c.keys()-p.keys())
    for k in shared:
        if any(p[k][f]!=c[k][f] for f in ('entry_price','entry_ts','side')): raise RuntimeError('ENTRY_GEOMETRY_DRIFT')
    delta=lambda k:c[k]['net_bps']-p[k]['net_bps']
    winners=[k for k in p if p[k]['net_bps']>0]
    values={
        'common_T':len(shared),'removed_T':len(removed),'new_T':len(added),
        'improved_parent_loss_bps':sum(max(0.,delta(k)) for k in shared if p[k]['net_bps']<0),
        'worsened_parent_loss_bps':sum(max(0.,-delta(k)) for k in shared if p[k]['net_bps']<0),
        'cut_parent_winner_bps':sum(max(0.,-delta(k)) for k in shared if p[k]['net_bps']>0),
        'increased_parent_winner_bps':sum(max(0.,delta(k)) for k in shared if p[k]['net_bps']>0),
        'removed_loss_bps':-sum(min(0.,p[k]['net_bps']) for k in removed),
        'missed_winner_bps':sum(max(0.,p[k]['net_bps']) for k in removed),
        'new_net_bps':sum(c[k]['net_bps'] for k in added),
        'new_loss_bps':-sum(min(0.,c[k]['net_bps']) for k in added),
        'new_profit_bps':sum(max(0.,c[k]['net_bps']) for k in added),
        'winner_to_loss_T':sum(p[k]['net_bps']>0 and c[k]['net_bps']<0 for k in shared),
        'winner_count_retention':sum(k in c and c[k]['net_bps']>0 for k in winners)/len(winners) if winners else None,
        'winner_amount_retention':sum(min(p[k]['net_bps'],max(0.,c[k]['net_bps'])) for k in winners if k in c)/sum(p[k]['net_bps'] for k in winners) if winners else None,
        'common_exit_net_delta_bps':sum(delta(k) for k in shared),
        'gross_delta_bps':sum(t['gross_bps'] for t in child)-sum(t['gross_bps'] for t in parent),
        'cost_saving_bps':sum(t['cost_bps'] for t in parent)-sum(t['cost_bps'] for t in child),
        'funding_saving_bps':sum(t['funding_bps'] for t in parent)-sum(t['funding_bps'] for t in child),
        'net_delta_bps':sum(t['net_bps'] for t in child)-sum(t['net_bps'] for t in parent),
        'identities':{'common':shared,'removed':removed,'new':added},
    }
    decomposition=values['common_exit_net_delta_bps']+values['removed_loss_bps']-values['missed_winner_bps']+values['new_net_bps']
    if abs(values['net_delta_bps']-decomposition)>1e-7 or abs(values['net_delta_bps']-values['gross_delta_bps']-values['cost_saving_bps'])>1e-7:
        raise RuntimeError('EXIT_NET_ATTRIBUTION_PARITY')
    return values


def authorize():
    contract=old.read(CONTRACT);old.probe.verify_seal(contract,'EXIT_PREREGISTRATION')
    if contract['rule']!=RULE or contract['exit_hypotheses_per_lane']!=1 or contract['outcomes_seen_at_freeze'] is not False:
        raise RuntimeError('EXIT_RULE_OR_BUDGET_CHANGED')
    for key,value in old.probe.DEV_AUTH.items():
        if contract.get(key)!=value:raise RuntimeError('EXIT_AUTHORITY:'+key)
    if contract['G6_authorized'] is not False or contract['validation_access_authorized'] is not False or contract['OOS_access_authorized'] is not False:
        raise RuntimeError('FORMAL_OR_HELDOUT_AUTHORITY')
    for path,value in {**contract['code_files_sha256'],**contract['evidence_files_sha256']}.items():
        if old.file_sha(ROOT/path)!=value:raise RuntimeError('EXIT_FROZEN_IDENTITY:'+path)
    scope=old.read(GOVERNANCE)['effective_development_objective']['development_exit_experiment']
    if scope!=contract['governance_scope']:raise RuntimeError('EXIT_SCOPE_DRIFT')
    previous.verify_previous()
    return contract


def verdict(metrics, attrs, uncertainty, gate):
    c=metrics['lifecycle_child']['base_cost'];f=metrics['fixed_child']['base_cost']
    if c['completed_T']<gate['minimum_closed_T'] or f['completed_T']<gate['minimum_closed_T'] or c['PF'] is None:
        return {'decision':'INSUFFICIENT','failed_checks':['SAMPLE_OR_UNDEFINED_PF']}
    checks={
        'fixed_entry_net_improves':attrs['fixed']['net_delta_bps']>0,
        'full_lifecycle_net_improves':attrs['lifecycle']['net_delta_bps']>0,
        'full_lifecycle_positive_net':c['net_bps']>0,
        'full_lifecycle_PF_above_one':c['PF']>1,
        'full_lifecycle_cost2_positive':metrics['lifecycle_child']['cost2x']['net_bps']>0,
        # Preservation is reported as a continuous measure, not a tuned cutoff.
    }
    failed=[k for k,v in checks.items() if not v]
    if failed:return {'decision':'DEV_REJECT','failed_checks':failed}
    pairs=uncertainty['lifecycle']['paired_base_minus_control_95pct_interval_bps']['child']
    return {'decision':'DEV_PROMISING_NO_CREDIT' if pairs[1]<0 else 'DEV_INCONCLUSIVE',
            'failed_checks':[] if pairs[1]<0 else ['PAIRED_WEEK_INCREMENT_UNCERTAIN']}


def report(receipt):
    lines=['# Top5 fixed-entry and lifecycle exit experiment (G5 DEV / no credit)','',
           'One cost-covered-close reversal rule, frozen before outcomes. Entries and original risk/SL are unchanged. Every completed parent winner and loser is included in the fixed-entry stage.',
           '', 'Metrics are sums/means of modelled trade bps, not account returns or actual fills. Funding is the existing research proxy, not signed trade-time funding. Native SL intrabar timestamp is the original upper-bound model; next-open overlay fills are timestamped at that open.',
           '', 'Lifecycle admission excludes the same time-only incomplete maximum-hold tail for parent and child. It reuses original raw signals, native ownership/cooldown and common V2 occupancy. Validation/OOS reads: 0. Previously seen Break validation remains REJECT.',
           '', '| Lane | Stage | T | Gross E | Net E | PF | WR % | Payoff | Cost2 E | Exposure days |',
           '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    def fmt(x):return 'NA' if x is None else f'{x:.4f}'
    for lane,result in receipt['lanes'].items():
        for name,m in result['metrics'].items():
            b=m['base_cost'];lines.append(f"| {lane} | {name} | {b['completed_T']} | {fmt(b['gross_expectancy_bps'])} | {fmt(b['expectancy_bps_per_trade'])} | {fmt(b['PF'])} | {fmt(100*b['win_rate'] if b['win_rate'] is not None else None)} | {fmt(b['realized_payoff'])} | {fmt(m['cost2x']['expectancy_bps_per_trade'])} | {fmt(b['exposure_symbol_days'])} |")
        lines.extend(['',f"{lane}: **{result['comparison']['decision']}**. Fixed-entry attribution: `{json.dumps({k:v for k,v in result['attribution']['fixed'].items() if k!='identities'},sort_keys=True)}`.",
                      f"Lifecycle attribution: `{json.dumps({k:v for k,v in result['attribution']['lifecycle'].items() if k!='identities'},sort_keys=True)}`.",
                      f"Loss streak / drawdown / recovery: `{json.dumps({k:{'streak':v['lane_simultaneous_close_group_streaks'],'drawdown':v['drawdown_recovery']} for k,v in result['diagnostics'].items()},sort_keys=True)}`.",
                      f"Uncertainty: `{json.dumps(result['uncertainty'],sort_keys=True)}`.", ''])
    lines += ['No new entry filter, exit sweep, formal G5A/G5B/G6 credit, operating replacement or live authority. All prior rejected children and immutable originals remain unchanged. Gemini actual video: NOT_RUN; paid calls: 0.']
    return ('\n'.join(lines)+'\n').encode()


def run(data_dir,verify_only=False):
    contract=authorize();p,dev,four,one,access=previous.load_inputs(data_dir)
    if p['combined_data_sha256']!=contract['data_sha256'] or p['cost_binding_sha256']!=contract['cost_sha256']:
        raise RuntimeError('EXIT_DATA_COST_BINDING')
    p={**p,'batch_id':contract['batch_id'],'receipt_sha256':contract['receipt_sha256'],
       'code_files_sha256':{**p['code_files_sha256'],**contract['code_files_sha256']}}
    parent=previous.read_lines(ROOT/old.OUTPUT/'baseline/trades.jsonl.gz')
    events=previous.read_lines(ROOT/old.OUTPUT/'baseline/events.jsonl.gz')
    result={};ledgers=[];event_ledger=[]
    # All data was admitted by the existing scoped loader. No further file reads
    # are needed by the causal overlay except the frozen V2 specification.
    with old.probe.io_boundary([ROOT/old.FREEZE],ROOT/OUTPUT):
        for lane in old.LANES:
            data=one if lane in old.LANES[:2] else four;costs=dev['cost_by_symbol']
            base=[t for t in parent if t['lane_id']==lane];es=[e for e in events if e['lane_id']==lane]
            fmap={(e['symbol'],e['signal_index']):e for e in es}
            fixed=[overlay(t,fmap[t['symbol'],t['signal_index']],data[t['symbol']],p,costs,'fixed_child') for t in base]
            full_base=[];full_child=[];be=[];ce=[];audit=[];eligible=set()
            for symbol,rows in data.items():
                pool,raw_events=candidate_pool(rows,symbol,lane,p,costs,[e for e in es if e['symbol']==symbol])
                eligible.update((symbol,e['signal_index']) for e in raw_events if e['full_lifecycle_eligible'])
                bt,bes=lifecycle(pool,rows,p,costs,'lifecycle_base',False)
                ct,ces=lifecycle(pool,rows,p,costs,'lifecycle_child',True)
                full_base.extend(bt);full_child.extend(ct);be.extend(bes);ce.extend(ces);audit.extend(raw_events)
            expected=[t for t in base if (t['symbol'],t['signal_index']) in eligible]
            assert_parent_parity(full_base,expected)
            if {entry_key(t) for t in fixed}!={entry_key(t) for t in base}:raise RuntimeError('FIXED_ENTRY_SAMPLE_DRIFT')
            versions={'fixed_base':base,'fixed_child':fixed,'lifecycle_base':full_base,'lifecycle_child':full_child}
            event_versions={'fixed_base':es,'fixed_child':es,'lifecycle_base':be,'lifecycle_child':ce}
            metrics={k:old.metrics(v,event_versions[k],p,list(data)) for k,v in versions.items()}
            attrs={'fixed':attribute(base,fixed),'lifecycle':attribute(full_base,full_child)}
            unc={'fixed':old.probe.cluster_uncertainty({'base':base,'child':fixed},p),
                 'lifecycle':old.probe.cluster_uncertainty({'base':full_base,'child':full_child},p)}
            result[lane]={'parent_id':p['parents'][lane]['id'],'child_id':contract['lanes'][lane]['child_id'],
                          'metrics':metrics,'attribution':attrs,'uncertainty':unc,
                          'diagnostics':{k:diagnostic.diagnostics(v,*p['development_interval_ms'])[0] for k,v in versions.items()},
                          'parent_ablation_parity':'PASS','all_parent_winners_and_losers_in_fixed_stage':True,
                          'time_only_tail':{'raw_signals_excluded':sum(not e['full_lifecycle_eligible'] for e in audit),
                                            'parent_completed_excluded_from_lifecycle':len(base)-len(full_base)},
                          'exit_changed':{k:sum(t.get('exit_overlay',{}).get('exit_changed',False) for t in v) for k,v in versions.items()},
                          'comparison':verdict(metrics,attrs,unc,contract['inherited_selection_rule']),'P0':'UNCONFIRMED',
                          'validation':'NOT_RUN','OOS':'NOT_RUN','formal_pass':False}
            for k,v in versions.items():
                for t in v:
                    item=dict(t,comparison_stage=k);item.pop('trade_sha256',None)
                    item['trade_sha256']=old.digest(item);ledgers.append(item)
            event_ledger.extend(dict(e,comparison_stage='raw_pool') for e in audit)
            event_ledger.extend(dict(e,comparison_stage=k) for k,evs in [('lifecycle_base',be),('lifecycle_child',ce)] for e in evs)
    out=ROOT/OUTPUT
    if not verify_only:out.mkdir(parents=True,exist_ok=True)
    artifacts={}
    for name,values in [('trades',ledgers),('events',event_ledger)]:
        plain=b''.join(old.probe.canonical(x) for x in sorted(values,key=lambda t:(t['lane_id'],t['comparison_stage'],t['symbol'],t['signal_ts'])))
        path=out/(name+'.jsonl.gz');payload=path.read_bytes() if path.exists() else gzip.compress(plain,mtime=0)
        if gzip.decompress(payload)!=plain:raise RuntimeError('EXIT_REPRODUCTION_DRIFT:'+name)
        old.probe.write_immutable(path,payload,verify_only=verify_only)
        artifacts[name]={'path':str(path.relative_to(ROOT)),'rows':len(values),'file_sha256':old.file_sha(path)}
    receipt=old.seal({'batch_id':contract['batch_id'],'contract_sha256':contract['receipt_sha256'],
                      'source_master_sha':contract['source_master_sha'],'data_sha256':p['combined_data_sha256'],
                      'cost_sha256':p['cost_binding_sha256'],'code_sha256':old.digest(p['code_files_sha256']),
                      'source_access':access,'lanes':result,'artifacts':artifacts,
                      'validation_rows_decoded':0,'OOS_rows_decoded':0,'scope':'G5_DEV_EXECUTABLE_EXIT_COMPARISON_NO_CREDIT',
                      'unique_exit_hypotheses':1,'lane_trials':5,'parameter_sweeps':0,
                      'G6_authorized':False,'new_G5B_T':0,'G5B_fresh_T_added':0,'production_credit':0,
                      'paid_AI_calls':0,'Gemini_direct_video':'NOT_RUN_NO_AUTHENTICATED_MANUAL_TRANSPORT',
                      'prior_failures_preserved':True,'Break_validation':'PRESERVED_REJECT_ALREADY_SEEN',**old.probe.DEV_AUTH})
    old.probe.write_immutable(out/'receipt.json',old.probe.canonical(receipt),verify_only=verify_only)
    old.probe.write_immutable(out/'RESULTS.md',report(receipt),verify_only=verify_only)
    files=[CONTRACT]+[str((out/x).relative_to(ROOT)) for x in ('receipt.json','RESULTS.md','trades.jsonl.gz','events.jsonl.gz')]
    durable=old.seal({'batch_id':contract['batch_id'],'result_receipt_sha256':receipt['receipt_sha256'],
                      'files_sha256':{path:old.file_sha(ROOT/path) for path in files},
                      'preserved_files_sha256':contract['evidence_files_sha256'],
                      'code_files_sha256':contract['code_files_sha256'],'paid_AI_calls':0,'G6_authorized':False,**old.probe.DEV_AUTH})
    old.probe.write_immutable(out/'durable_receipt.json',old.probe.canonical(durable),verify_only=verify_only)
    return receipt


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--data-dir',type=Path,required=True);ap.add_argument('--verify-only',action='store_true');a=ap.parse_args()
    r=run(a.data_dir.resolve(),a.verify_only)
    print(json.dumps({'receipt_sha256':r['receipt_sha256'],'lanes':{k:{'comparison':v['comparison'],'fixed_delta':v['attribution']['fixed']['net_delta_bps'],'lifecycle_delta':v['attribution']['lifecycle']['net_delta_bps']} for k,v in r['lanes'].items()}},indent=2))
