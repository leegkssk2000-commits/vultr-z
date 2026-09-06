"""Exactly two user-allocated DEV trials; existing parents and trials immutable."""
from __future__ import annotations
import argparse
import gzip
import json
import math
from pathlib import Path
from backend.research.rebuild import top5_diverse_batch_preparation_v1 as prep
from backend.research.rebuild import top5_no_credit_exit_v1 as prior

old=prep.old
ROOT=old.ROOT
CONTRACT='backend/research/contracts/top5_diverse_batch_execution_v1.json'
OUTPUT='research/development_evidence/TOP5_DIVERSE_EXECUTION_20260906_V1'
INTERVAL=14_400_000
LANES=(prep.KELTNER,prep.SUPERTREND)
BUDGET={'previous_current_parent_applications':18,'new_allocations':2,
        'per_lane':{prep.KELTNER:1,prep.SUPERTREND:1},'cumulative_after':20,
        'automatic_extension':False,'paid_external_AI_calls':0}
TIMING={
    'signal':'Original fully closed 4h bar i; never child outcome labels',
    'parent_entry':'open[i+1]', 'supertrend_child_entry':'open[i+2]',
    'hold':'12 full bars from ACTUAL entry; 48h market exposure',
    'parent_exit':'close[i+12]', 'supertrend_child_exit':'close[i+13]',
    'expiry':'One scheduled fill only at open[i+2]; no revalidation, reschedule or queue carry. Missing bars fail data integrity, not a later fill.',
    'ownership':'Reserve source signal i through waiting and actual exit index inclusive; later signals in that interval are excluded. Shared evaluator unchanged.',
    'tail':'For BOTH variants use i+1+max(parent_delay,child_delay)+hold-1; exit close must be strictly before DEV end. No outcome-based eligibility.',
    'fixed_origin':'All time-eligible parent completed origin signals evaluated individually; descriptive counterfactual may overlap, not a deployable portfolio.',
    'source_match':'lane/symbol/original signal close timestamp/side; delayed entry timestamps remain distinct and never called identical entry.',
}


def source_key(t):
    return old.digest({k:t[k] for k in ('lane_id','symbol','signal_ts','side')})


def eligible_signals(rows, signals, hold, max_delay, end):
    allowed=[]; excluded=[]
    for i in signals:
        last=i+1+max_delay+hold-1
        if last < len(rows) and rows[last]['bar_close_ts'] < end:
            allowed.append(i)
        else: excluded.append(i)
    return allowed,excluded


def evaluate(rows, signals, parent, policy, costs, symbol, scenario, delay=0):
    raw=old.common.evaluate_development_events(rows,signals,
        split_start_ms=policy['development_interval_ms'][0],
        split_end_ms=policy['development_interval_ms'][1],interval_ms=INTERVAL,
        hold_bars=parent['executable_spec']['max_hold_bars'],entry_delay_bars=delay,side='long')
    trades=[]
    for t in raw['trades']:
        t=old.charge(t,symbol,parent['lane_id'],scenario,policy,costs,rows,INTERVAL)
        t.pop('trade_sha256',None)
        t.update(origin_key=source_key(t),entry_delay_bars=delay,
                 risk_scope='FROZEN_V2_FIXED_HOLD_NO_NATIVE_SL_SPECIFIED',
                 pending_reservation_ms=delay*INTERVAL)
        t['trade_sha256']=old.digest(t);trades.append(t)
    completed={t['signal_index'] for t in trades};reasons={e['signal_index']:e['reason'] for e in raw['exclusions']}
    events=[{'lane_id':parent['lane_id'],'symbol':symbol,'signal_index':i,'signal_ts':rows[i]['bar_close_ts'],
             'scenario':scenario,'admission':True,'status':'COMPLETED' if i in completed else 'EXCLUDED',
             'exclusion_reason':None if i in completed else reasons[i]} for i in signals]
    return trades,events


def attribute(parent, child):
    p={source_key(t):t for t in parent};c={source_key(t):t for t in child}
    if len(p)!=len(parent) or len(c)!=len(child):raise RuntimeError('DUPLICATE_ORIGIN')
    shared=sorted(p.keys()&c.keys());removed=sorted(p.keys()-c.keys());added=sorted(c.keys()-p.keys())
    sums=lambda ts:sum(t['net_bps'] for t in ts)
    delta=lambda k:c[k]['net_bps']-p[k]['net_bps']
    wins=[k for k in p if p[k]['net_bps']>0]
    large=sorted(wins,key=lambda k:(-p[k]['net_bps'],k))[:math.ceil(len(wins)*.1)]
    preserved=lambda keys:sum(min(p[k]['net_bps'],max(0.,c[k]['net_bps'])) for k in keys if k in c)
    ratio=lambda keys:preserved(keys)/sum(p[k]['net_bps'] for k in keys) if keys else None
    v={'matching_basis':TIMING['source_match'],'common_T':len(shared),'removed_T':len(removed),'new_T':len(added),
       'common_parent_net_bps':sums([p[k] for k in shared]),'common_child_net_bps':sums([c[k] for k in shared]),
       'common_net_delta_bps':sum(delta(k) for k in shared),
       'removed_parent_net_bps':sums([p[k] for k in removed]),'new_net_bps':sums([c[k] for k in added]),
       'removed_loss_bps':-sum(min(0.,p[k]['net_bps']) for k in removed),
       'missed_winner_bps':sum(max(0.,p[k]['net_bps']) for k in removed),
       'saved_common_loss_bps':sum(max(0.,delta(k)) for k in shared if p[k]['net_bps']<0),
       'worsened_common_loss_bps':sum(max(0.,-delta(k)) for k in shared if p[k]['net_bps']<0),
       'cut_positive_winner_profit_bps':sum(max(0.,p[k]['net_bps']-max(0.,c[k]['net_bps'])) for k in shared if p[k]['net_bps']>0),
       'additional_loss_on_parent_winners_bps':-sum(min(0.,c[k]['net_bps']) for k in shared if p[k]['net_bps']>0),
       'increased_common_winner_bps':sum(max(0.,delta(k)) for k in shared if p[k]['net_bps']>0),
       'winner_to_loss_T':sum(p[k]['net_bps']>0 and c[k]['net_bps']<0 for k in shared),
       'winner_amount_retention':ratio(wins),'large_winner_amount_retention':ratio(large),
       'large_parent_winner_T':len(large),'large_parent_winner_net_bps':sum(p[k]['net_bps'] for k in large),
       'large_winner_preserved_positive_bps':preserved(large),
       'large_winner_remaining_positive_T':sum(k in c and c[k]['net_bps']>0 for k in large),
       'large_winner_unreduced_T':sum(k in c and c[k]['net_bps']>=p[k]['net_bps'] for k in large),
       'gross_delta_bps':sum(t['gross_bps'] for t in child)-sum(t['gross_bps'] for t in parent),
       'cost_saving_bps':sum(t['cost_bps'] for t in parent)-sum(t['cost_bps'] for t in child),
       'funding_saving_bps':sum(t['funding_bps'] for t in parent)-sum(t['funding_bps'] for t in child),
       'net_delta_bps':sums(child)-sums(parent),
       'origins':{'common':shared,'removed':removed,'new':added,'large_parent_winners':large}}
    bridge=v['common_net_delta_bps']-v['removed_parent_net_bps']+v['new_net_bps']
    if abs(v['net_delta_bps']-bridge)>1e-7 or abs(v['net_delta_bps']-v['gross_delta_bps']-v['cost_saving_bps'])>1e-7:
        raise RuntimeError('ORIGIN_ACCOUNTING_PARITY')
    return v


def authorize():
    c=old.read(CONTRACT);old.probe.verify_seal(c,'TWO_TRIAL_ALLOCATION')
    if c['budget']!=BUDGET or c['timing']!=TIMING or c['outcomes_seen_at_freeze'] is not False:
        raise RuntimeError('ALLOCATION_OR_TIMING_DRIFT')
    if c['authorization']!='EXPLICIT_USER_TWO_ADDITIONAL_DEVELOPMENT_TRIALS_PR1187':raise RuntimeError('MISSING_ALLOCATION_SOURCE')
    for k,v in old.probe.DEV_AUTH.items():
        if c.get(k)!=v:raise RuntimeError('FORMAL_AUTHORITY:'+k)
    for k in ('validation_access','OOS_access','G5B_changed','G6_authorized'):
        if c.get(k) is not False:raise RuntimeError('FORBIDDEN_AUTHORITY:'+k)
    for p,sha in {**c['code_files_sha256'],**c['preserved_files_sha256']}.items():
        if old.file_sha(ROOT/p)!=sha:raise RuntimeError('FROZEN_IDENTITY:'+p)
    prior.previous.verify_previous()
    return c


def economic_decision(parent, child, metrics, uncertainty, diagnostics, gate):
    # Match source identities only for retention accounting, retaining actual
    # delayed fills/costs in metrics and every persisted ledger row.
    pp=[dict(t,identity=source_key(t)) for t in parent]
    cc=[dict(t,identity=source_key(t)) for t in child]
    result=old.compare(pp,cc,[],metrics['parent'],metrics['child'],uncertainty,gate)
    risk={
        'grouped_streak_not_worse':diagnostics['child']['lane_simultaneous_close_group_streaks']['max_loss_trade_sum_bps']<=diagnostics['parent']['lane_simultaneous_close_group_streaks']['max_loss_trade_sum_bps'],
        'grouped_DD_not_worse':diagnostics['child']['drawdown_recovery']['closed_group_DD_trade_sum_bps']<=diagnostics['parent']['drawdown_recovery']['closed_group_DD_trade_sum_bps']}
    result['risk_checks']=risk
    if result['decision']=='DEV_PROMISING':
        if not all(risk.values()):result['decision']='DEV_REJECT';result['failed_checks'] += [k for k,v in risk.items() if not v]
        elif result['increment_uncertainty']=='INCLUDES_ZERO':result['decision']='DEV_INCONCLUSIVE'
    result.update(formal_pass=False,operating_adoption=False,code_test_PASS_is_economic_PASS=False)
    return result


def report(receipt):
    lines=['# Two distinct Top5 DEV experiments — actual results','',
           'Keltner removes only EMA20>EMA50. Supertrend retains origin signals and delays entry one 4h bar. No new indicator/exit sweep. Prior 18 applications preserved; two allocated applications consumed, cumulative 20; new allocation remaining=0.',
           '', 'All monetary figures are modeled equal-notional trade bps, not account returns. Fixed-origin timing comparisons may overlap and are not a portfolio. Shared chronological replay determines the economic decision.',
           '', '| Lane | Variant | T | Net E bps | PF | Payoff | Cost2 E bps | Trades/day | Exposure symbol-days | Max grouped loss-run bps |',
           '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    fmt=lambda v:'NA' if v is None else f'{v:.4f}'
    for lane,v in receipt['lanes'].items():
        for stage,m in v['metrics'].items():
            b=m['base_cost'];s=v['diagnostics'][stage]['lane_simultaneous_close_group_streaks']['max_loss_trade_sum_bps']
            vals=[b['expectancy_bps_per_trade'],b['PF'],b['realized_payoff'],m['cost2x']['expectancy_bps_per_trade'],b['completed_trade_rate_per_day'],b['exposure_symbol_days'],s]
            lines.append('| '+lane+' | '+stage+' | '+str(b['completed_T'])+' | '+' | '.join(fmt(x) for x in vals)+' |')
        lines.extend(['',lane+': **'+v['decision']['decision']+'**. Failed checks: '+', '.join(v['decision']['failed_checks']), ''])
    lines+=['','## Attribution, profit preservation and uncertainty','',
            '| Lane | Comparison | Shared / removed / new | Shared net delta | Removed parent net | New net | Net delta | Winner profit retained | Top-decile winner profit retained |',
            '|---|---|---|---:|---:|---:|---:|---:|---:|']
    for lane,v in receipt['lanes'].items():
        for stage,a in v['attribution'].items():
            lines.append(f"| {lane} | {stage} | {a['common_T']} / {a['removed_T']} / {a['new_T']} | "+' | '.join(fmt(a[k]) for k in ['common_net_delta_bps','removed_parent_net_bps','new_net_bps','net_delta_bps','winner_amount_retention','large_winner_amount_retention'])+' |')
        lines+=['',lane+' child-minus-parent paired weekly 95% interval (bps/trade): '+str(v['decision']['child_minus_parent_95pct_interval_bps']),
                'Same-signal fixed-origin comparison is distinct from changed-price entry execution. Source keys match original signal time, not entry time.', '']
    lines+=['','Full gross/net, cost decomposition, common losses, winner-to-loss changes, origin identities, grouped DD/streaks, per-symbol results, tail exclusions and uncertainty are in receipt.json and sealed trade/event ledgers.',
            '', 'Repeated DEV is adaptive evidence, not independent validation. Validation/OOS rows decoded=0. Existing G5B, parents and prior failures preserved. No paid external AI, actual Gemini video input, deployment or trading authority.', '']
    return '\n'.join(lines).encode()


def run(data_dir, verify_only=False):
    c=authorize();out=ROOT/OUTPUT
    if (out/'receipt.json').exists() and not verify_only:raise RuntimeError('TWO_TRIAL_BUDGET_CONSUMED_USE_VERIFY_ONLY')
    p,dev,four,one,access=prior.previous.load_inputs(data_dir)
    if p['combined_data_sha256']!=c['data_sha256'] or p['cost_binding_sha256']!=c['cost_sha256']:raise RuntimeError('DATA_COST_BINDING')
    p={**p,'batch_id':c['batch_id'],'receipt_sha256':c['receipt_sha256'],'code_files_sha256':{**p['code_files_sha256'],**c['code_files_sha256']}}
    parents=old.read(old.FREEZE)['children'];baselines=prior.previous.read_lines(ROOT/old.OUTPUT/'baseline/trades.jsonl.gz')
    old_events=prior.previous.read_lines(ROOT/old.OUTPUT/'baseline/events.jsonl.gz')
    lanes={};ledger=[];event_ledger=[]
    with old.probe.io_boundary([],out):
        for lane in LANES:
            parent=next(x for x in parents if x['lane_id']==lane)
            if old.digest(parent)!=c['parents'][lane]['sha256']:raise RuntimeError('PARENT_CHANGED')
            child_spec,delay=prep.candidate_spec(parent);stages={k:[] for k in ('parent','fixed_origin_child','child')};events={k:[] for k in stages};tail={}
            for symbol,rows in four.items():
                raw=prep.causal_signals(rows,parent['executable_spec']);child_raw=prep.causal_signals(rows,child_spec['executable_spec'])
                if raw!=[e['signal_index'] for e in old_events if e['lane_id']==lane and e['symbol']==symbol]:raise RuntimeError('RAW_PARENT_SIGNAL_DRIFT')
                if lane==prep.SUPERTREND and child_raw!=raw:raise RuntimeError('SUPERTREND_SIGNAL_CHANGED')
                if lane==prep.KELTNER and not set(raw)<=set(child_raw):raise RuntimeError('GATE_REMOVAL_LOST_SIGNAL')
                hold=parent['executable_spec']['max_hold_bars'];end=p['development_interval_ms'][1]
                ps,pt=eligible_signals(rows,raw,hold,delay,end);cs,ct=eligible_signals(rows,child_raw,hold,delay,end)
                bt,be=evaluate(rows,ps,parent,p,dev['cost_by_symbol'],symbol,'parent')
                actual=[t for t in baselines if t['lane_id']==lane and t['symbol']==symbol and t['signal_index'] in set(ps)]
                prior.assert_parent_parity(bt,actual)
                ft=[]
                for t in bt:
                    if delay:
                        ts,_=evaluate(rows,[t['signal_index']],parent,p,dev['cost_by_symbol'],symbol,'fixed_origin_child',delay);ft.extend(ts)
                    else:ft.append(dict(t,scenario='fixed_origin_child'))
                cht,che=evaluate(rows,cs,parent,p,dev['cost_by_symbol'],symbol,'child',delay)
                for k,ts,ev in [('parent',bt,be),('fixed_origin_child',ft,be),('child',cht,che)]:stages[k].extend(ts);events[k].extend(ev)
                tail[symbol]={'parent_raw_T':len(raw),'child_raw_T':len(child_raw),'parent_tail_signals':pt,'child_tail_signals':ct,'parent_completed_removed_for_common_tail':sum(t['lane_id']==lane and t['symbol']==symbol for t in baselines)-len(bt)}
            metrics={k:old.metrics(ts,events[k],p,list(four)) for k,ts in stages.items()}
            for k,ts in stages.items():
                metrics[k]['pending_symbol_days']=sum(t['pending_reservation_ms'] for t in ts)/86_400_000
                metrics[k]['reserved_plus_held_symbol_days']=metrics[k]['pending_symbol_days']+metrics[k]['base_cost']['exposure_symbol_days']
            diagnostics={k:prior.diagnostic.diagnostics(ts,*p['development_interval_ms'])[0] for k,ts in stages.items()}
            unc=old.probe.cluster_uncertainty({'base':stages['parent'],'child':stages['child']},p)
            fixed_unc=old.probe.cluster_uncertainty({'base':stages['parent'],'child':stages['fixed_origin_child']},p)
            attrs={k:attribute(stages['parent'],stages[k]) for k in ('fixed_origin_child','child')}
            lanes[lane]={'metrics':metrics,'diagnostics':diagnostics,'attribution':attrs,'uncertainty':unc,'fixed_origin_uncertainty':fixed_unc,'tail':tail,
                         'decision':economic_decision(stages['parent'],stages['child'],metrics,unc,diagnostics,c['selection_rule']),
                         'parent_ablation_parity':'PASS','fixed_origin_may_overlap':True,'preregistered_ordinal':c['parents'][lane]['cumulative_application_ordinal']}
            for stage,ts in stages.items():
                for t in ts:
                    t=dict(t,comparison_stage=stage,scenario=stage);t.pop('trade_sha256',None);t['trade_sha256']=old.digest(t);ledger.append(t)
                event_ledger.extend(dict(e,comparison_stage=stage,scenario=stage) for e in events[stage])
    if not verify_only:out.mkdir(parents=True,exist_ok=True)
    artifacts={}
    for name,items in [('trades',ledger),('events',event_ledger)]:
        raw=b''.join(old.probe.canonical(t) for t in sorted(items,key=lambda t:(t['lane_id'],t['comparison_stage'],t['symbol'],t['signal_ts'])))
        path=out/(name+'.jsonl.gz');payload=path.read_bytes() if path.exists() else gzip.compress(raw,mtime=0)
        if gzip.decompress(payload)!=raw:raise RuntimeError('REPRODUCTION_DRIFT:'+name)
        old.probe.write_immutable(path,payload,verify_only=verify_only)
        artifacts[name]={'path':str(path.relative_to(ROOT)),'rows':len(items),'file_sha256':old.file_sha(path)}
    r=old.seal({'batch_id':c['batch_id'],'contract_sha256':c['receipt_sha256'],'lanes':lanes,'artifacts':artifacts,
                'source_access':access,'data_sha256':c['data_sha256'],'cost_sha256':c['cost_sha256'],
                'budget':{**BUDGET,'new_allocations_consumed':2,'new_allocations_remaining':0},'data_reuse_history':c['data_reuse_history'],
                'validation_rows_decoded':0,'OOS_rows_decoded':0,'G5B_changed':False,'G6_authorized':False,
                'paid_external_AI_calls':0,'Gemini_actual_video':'NOT_RUN','parameter_sweeps':0,**old.probe.DEV_AUTH})
    old.probe.write_immutable(out/'receipt.json',old.probe.canonical(r),verify_only=verify_only)
    old.probe.write_immutable(out/'RESULTS.md',report(r),verify_only=verify_only)
    paths=[CONTRACT]+[str((out/f).relative_to(ROOT)) for f in ('receipt.json','RESULTS.md','trades.jsonl.gz','events.jsonl.gz')]
    durable=old.seal({'result_receipt_sha256':r['receipt_sha256'],'files_sha256':{p:old.file_sha(ROOT/p) for p in paths},
                      'code_files_sha256':c['code_files_sha256'],'preserved_files_sha256':c['preserved_files_sha256'],**old.probe.DEV_AUTH})
    old.probe.write_immutable(out/'durable_receipt.json',old.probe.canonical(durable),verify_only=verify_only)
    return r


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--data-dir',type=Path,required=True);ap.add_argument('--verify-only',action='store_true');a=ap.parse_args()
    r=run(a.data_dir.resolve(),a.verify_only)
    print(json.dumps({'receipt':r['receipt_sha256'],'lanes':{k:v['decision'] for k,v in r['lanes'].items()}},indent=2))
