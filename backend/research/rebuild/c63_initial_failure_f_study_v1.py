"""Two jointly frozen F successors, four serial first FULLs, saved-only closure.

Reuse the frozen native engine, charge/mark and symmetric accounting owners.
No downloads, parameter selection, parent replay, paid API, orders or retries.
"""
import argparse
import gzip
import json
import math
import os
import subprocess
import time
import traceback
from pathlib import Path
from unittest.mock import patch
from backend.research.rebuild import c63_r_b20_study_v1 as prior
from backend.research.rebuild import c63_initial_failure_f_v1 as child

ROOT, p, a = prior.ROOT, prior.p, prior.a
read, gz, h, put, need = prior.read, prior.gz, prior.h, prior.put, prior.need
SCOPE = child.SCOPE
OUT = 'research/development_evidence/' + SCOPE
KEY = 'c63_initial_failure_f_after_pr1247_allocation'
BRANCH = 'research/c63-initial-failure-f-after-pr1247-v1'
PERIODS = prior.PERIODS
VARIANTS = child.VARIANTS
PLAN = [(v, per) for v in VARIANTS for per in PERIODS]
LABELS = ('C63', 'R', 'R_B20')
integration = prior.prior.d.prior.previous.integration
INPUTS = prior.INPUTS


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True, timeout=45).strip()


def atomic(name, value):
    prior.atomic(ROOT / OUT / name, value)


def ensure_execution_scope(scope, status):
    need(scope == SCOPE and status in ('PREPARED', 'RUNNING'), 'SCOPE_CLOSED_OR_UNAUTHORIZED')


def owner():
    need(os.environ.get('GITHUB_RUN_ATTEMPT') == '1', 'NO_RETRY')
    need(os.environ.get('GITHUB_REF_NAME') == BRANCH, 'BRANCH_OWNER')
    return os.environ['GITHUB_RUN_ID']


def sources():
    result = prior.sources()
    for name in ('c63_initial_failure_f_v1.py', 'test_c63_initial_failure_f_v1.py', 'c63_initial_failure_f_study_v1.py'):
        path='backend/research/rebuild/'+name;result[path]=h(ROOT/path)
    for name in ('DESIGN.md','WORK_NEXT.txt','PRE_OUTCOME_WORKFLOW.yml'):
        path=OUT+'/'+name;result[path]=h(ROOT/path)
    return result


def baseline(label, per):
    return gz(ROOT/prior.OUT/per/'RESULT.json.gz') if label=='R_B20' else prior.baseline(label, per)


def freeze():
    run = owner()
    need(os.environ.get('F1248_PREFLIGHT') == 'PASSED', 'FULL_CHECKOUT_PREFLIGHT')
    need(not (ROOT / OUT / 'SPEC.json').exists(), 'ALREADY_FROZEN')
    inherited = prior.check()
    data = (ROOT / prior.OUT / 'BUDGET.json').read_bytes()
    budget = json.loads(data)
    need((budget['cumulative_actual'], budget['cumulative_actual_evaluations']) == (76, 136), 'LATEST_HISTORY_NOT76_136')
    need(KEY not in budget, 'DUPLICATE_ALLOCATION')
    p.write_new(ROOT / OUT / 'HISTORY_PRIOR.json', data)
    preserved = dict(inherited['source_files_sha256'])
    for folder in (ROOT / prior.OUT, ROOT / prior.prior.OUT, ROOT / prior.prior.d.prior.OUT):
        for path in folder.rglob('*'):
            if path.is_file(): preserved[str(path.relative_to(ROOT))] = h(path)
    put(ROOT / OUT / 'PRESERVATION.json', preserved)
    packet_hashes, cost_hashes, policy_hashes = {}, {}, {}
    for per in PERIODS:
        path = ROOT / INPUTS / (per + '.json.gz')
        need(h(path) == inherited['input_packet_sha256'][per], 'INPUT_HASH')
        packet = gz(path)
        prior.prior.d.prior.previous.shared.old.inherited.packet_check(per, packet)
        packet_hashes[per] = h(path)
        cost_hashes[per] = p.sha(packet['costs'])
        policy_hashes[per] = p.sha(packet['policy'])
    spec = dict(scope=SCOPE, max_candidates=2, max_FULL=4, variants=VARIANTS, plan=PLAN, periods=inherited['periods'],
        candidate_ordinal=None, evaluation_ordinals=[], ordinal_assignment='ACTUAL_START_ONLY',
        historical_candidates=76, historical_evaluations=136, owner_run=run,
        source_commit=git('rev-parse', 'HEAD'), frozen_ns=time.time_ns(),
        source_files_sha256=sources(), input_packet_sha256=packet_hashes,
        costs_sha256=cost_hashes, policy_sha256=policy_hashes,
        history_sha256=h(ROOT / OUT / 'HISTORY_PRIOR.json'),
        preservation_sha256=h(ROOT / OUT / 'PRESERVATION.json'),
        parent_results_sha256={label: {per: p.sha(baseline(label, per)) for per in PERIODS}
                               for label in LABELS},
        objective=inherited['objective'], judgment_owner='m1_er14_study_v1.checks',
        rule='F_ONLY=C63+F; B20_F=R_B20+F. Held3..19, three held observations M[t-2]>M[t-1]>M[t]>0 and close<native EMA20, after original priority; whole position next actual open.',
        independent=False, formal_credit=0, used_DEV=True, selected_on_used_DEV=True,
        parent_replays=0, fixed_replays=0, retry=False, new_market=0, unused_OOS=0,
        paid_ai=0, orders=0, deploy=0, automatic_successor=False)
    put(ROOT / OUT / 'SPEC.json', spec)
    budget[KEY] = dict(max_candidates=2, max_executions=4, reserved=0, started=0,
                       completed=0, failed=0, remaining=4, retry=False)
    put(ROOT / OUT / 'BUDGET.json', budget)
    put(ROOT / OUT / 'STATUS.json', dict(scope=SCOPE, status='PREPARED', owner_run=run))
    print('RULE_CODE_INPUT_COST_JUDGMENT_FROZEN_BEFORE_ECONOMICS')


def check():
    spec = read(ROOT / OUT / 'SPEC.json')
    need(spec['scope'] == SCOPE and spec['source_files_sha256'] == sources(), 'SOURCE_DRIFT')
    need(h(ROOT / OUT / 'HISTORY_PRIOR.json') == spec['history_sha256'] ==
         h(ROOT / prior.OUT / 'BUDGET.json'), 'HISTORY_DRIFT')
    need(h(ROOT / OUT / 'PRESERVATION.json') == spec['preservation_sha256'], 'PRESERVATION_DRIFT')
    for name, digest in read(ROOT / OUT / 'PRESERVATION.json').items():
        need(h(ROOT / name) == digest, 'PARENT_CHANGED:' + name)
    for per in PERIODS:
        need(h(ROOT / INPUTS / (per + '.json.gz')) == spec['input_packet_sha256'][per], 'INPUT_DRIFT')
    return spec


def reserve(variant, per):
    spec = check(); run = owner(); j = PLAN.index((variant, per))
    state = read(ROOT / OUT / 'STATUS.json')
    ensure_execution_scope(state['scope'], state['status'])
    need(spec['owner_run'] == run, 'OWNER_CHANGED')
    budget = read(ROOT / OUT / 'BUDGET.json'); q = budget[KEY]
    need(q['reserved'] == q['started'] == q['completed'] == j and not q['failed'], 'NO_RETRY_OR_DUPLICATE_SLOT')
    put(ROOT / OUT / variant / per / 'ATTEMPT.json', dict(scope=SCOPE, variant=variant, period=per,
        candidate_ordinal=None, evaluation_ordinal=None, status='RESERVED_NOT_STARTED',
        owner_run=run, spec_sha256=h(ROOT / OUT / 'SPEC.json'), time_ns=time.time_ns()))
    q['reserved'] += 1; q['remaining'] -= 1
    atomic('BUDGET.json', budget)


def persist(message):
    git('add', '--', OUT)
    git('commit', '-m', message + ' [skip ci]')
    head = git('rev-parse', 'HEAD')
    git('push', 'origin', 'HEAD:refs/heads/' + BRANCH)
    remote = git('ls-remote', 'origin', 'refs/heads/' + BRANCH).split()[0]
    need(remote == head, 'REMOTE_READBACK_MISMATCH')
    return head


def execute(variant, per, remote):
    spec = check(); j = PLAN.index((variant, per)); run = owner()
    state = read(ROOT / OUT / 'STATUS.json'); ensure_execution_scope(state['scope'], state['status'])
    folder = ROOT / OUT / variant / per
    attempt = read(folder / 'ATTEMPT.json'); head = git('rev-parse', 'HEAD')
    need(head == remote and spec['owner_run'] == attempt['owner_run'] == run, 'REMOTE_OWNER')
    need(git('ls-remote', 'origin', 'refs/heads/' + BRANCH).split()[0] == head, 'REMOTE_CLAIM_CHANGED')
    need(subprocess.check_output(['git','show',head+':'+OUT+'/'+variant+'/'+per+'/ATTEMPT.json'], cwd=ROOT)
         == (folder / 'ATTEMPT.json').read_bytes(), 'CLAIM_NOT_COMMITTED')
    budget = read(ROOT / OUT / 'BUDGET.json'); q = budget[KEY]
    need(q['reserved'] == j+1 and q['started'] == q['completed'] == j and not q['failed'], 'NO_REPEATED_ECONOMICS')
    need(budget['cumulative_actual_evaluations'] == 136+j, 'EVALUATION_ORDINAL')
    packet = gz(ROOT / INPUTS / (per + '.json.gz')); cal = spec['periods'][per]
    prior.prior.d.prior.previous.shared.old.inherited.packet_check(per, packet)
    need(p.sha(packet['costs']) == spec['costs_sha256'][per] and
         p.sha(packet['policy']) == spec['policy_sha256'][per], 'COST_POLICY_DRIFT')
    put(folder / 'EXECUTION_STARTED.json', dict(scope=SCOPE, variant=variant, period=per,
        candidate_ordinal=77+j//2, evaluation_ordinal=137+j, claim_commit=head,
        remote_readback_sha=remote, owner_run=run, time_ns=time.time_ns()))
    if j % 2 == 0:
        need(budget['cumulative_actual'] == 76+j//2, 'CANDIDATE_ORDINAL')
        budget['cumulative_actual'] += 1; budget['new_candidate_runs'] += 1
        budget['candidate_trials'].append(dict(candidate=child.RULES[variant], ordinal=77+j//2, first_evaluation=137+j, scope=SCOPE))
    budget['cumulative_actual_evaluations'] += 1; q['started'] += 1
    budget['trials'].append(dict(attempt, candidate_ordinal=77+j//2, evaluation_ordinal=137+j,
        actual_experiment_ordinal=137+j, status='STARTED'))
    atomic('BUDGET.json', budget)
    atomic('STATUS.json', dict(scope=SCOPE, status='RUNNING', owner_run=run))
    try:
        started_commit = persist('Durably start '+variant+' '+per + '; no retry')
        with p.native.sensitivity():
            raw = {sym: child.replay(rows, eval_start_ms=cal['start_ms'],
                eval_end_ms=cal['runoff_end_ms'],variant=variant) for sym, rows in sorted(packet['rows_by'].items())}
        with patch.dict(prior.prior.d.prior.previous.integration.engine.RULES, {'M1': child.RULES[variant]}):
            result = prior.prior.d.prior.previous.integration.charge_and_mark(raw, 'M1', packet, cal)
        result.update(scope=SCOPE, period=per, variant=variant, direct_parent='C63' if variant=='F_ONLY' else 'R_B20', spec_sha256=h(ROOT / OUT / 'SPEC.json'))
        signal_key = lambda e: (e['symbol'], e['signal_index'], e['signal_ts'])
        need({signal_key(e) for e in baseline('C63', per)['events']} ==
             {signal_key(e) for e in result['events']}, 'ORIGINAL_SIGNAL_POOL_CHANGED')
        for name, obj in [('RAW.json.gz', raw), ('RESULT.json.gz', result)]:
            p.write_new(folder / name, gzip.compress(p.canonical(obj), mtime=0))
        for label in LABELS:
            accounting = json.loads(p.canonical(a.compare(baseline(label, per), result)))
            accounting['comparison_type'] = 'EXIT_REPAIR_WITH_FULL_OCCUPANCY'
            put(folder / ('ACCOUNTING_' + label + '.json'), accounting)
        put(folder / 'RECEIPT.json', dict(status='COMPLETED', period=per,
            candidate_ordinal=77+j//2, evaluation_ordinal=137+j, claim_commit=head,
            started_commit=started_commit, owner_run=run,
            raw_sha256=h(folder / 'RAW.json.gz'), result_sha256=h(folder / 'RESULT.json.gz'),
            spec_sha256=h(ROOT / OUT / 'SPEC.json'), metrics=a.snapshot(result)))
        q['completed'] += 1; budget['trials'][-1]['status'] = 'COMPLETED'
        atomic('BUDGET.json', budget)
        print(json.dumps(dict(period=per, metrics=a.snapshot(result))))
    except BaseException as exc:
        put(folder / 'FAILURE.json', dict(status='FAILED_CONSUMED', error=str(exc),
            traceback=traceback.format_exc(), retry=False))
        q['failed'] += 1; budget['trials'][-1]['status'] = 'FAILED_CONSUMED'
        atomic('BUDGET.json', budget)
        atomic('STATUS.json', dict(scope=SCOPE, status='CHECKPOINTED_BLOCKED', owner_run=run))
        raise


def aggregate(results):
    trades = [t for r in results for t in r['trades']]
    wins = [t['net_bps'] for t in trades if t['net_bps'] > 0]
    losses = [t['net_bps'] for t in trades if t['net_bps'] < 0]
    mean_win = sum(wins)/len(wins) if wins else None
    mean_loss = sum(losses)/len(losses) if losses else None
    return dict(closed=len(trades), open=sum(len(r['open_observations']) for r in results),
        win_rate=len(wins)/len(trades) if trades else None,
        average_win_bps=mean_win, average_loss_bps=mean_loss,
        realized_payoff=mean_win/abs(mean_loss) if mean_win is not None and mean_loss else None,
        PF=sum(wins)/abs(sum(losses)) if losses else None,
        terminal_net_bps=sum(r['metrics']['terminal_net_bps'] for r in results),
        terminal_cost2x_net_bps=sum(r['metrics']['terminal_cost2x_net_bps'] for r in results),
        marked_DD_trade_sum_bps=None, basis='DISJOINT_PERIOD_ARITHMETIC_NOT_CONTINUOUS_ACCOUNT')


def closed_risk(result):
    ordered = sorted(result['trades'], key=lambda t:(t['exit_ts'],t['symbol'],t['signal_ts']))
    streak = worst = 0
    for trade in ordered:
        streak = streak+1 if trade['net_bps'] < 0 else 0; worst = max(worst, streak)
    losses = sorted(t['net_bps'] for t in ordered if t['net_bps'] < 0)
    tail = losses[:max(1,math.ceil(len(losses)*.1))]
    return dict(max_consecutive_closed_losses=worst,
        streak_basis='CLOSED_TRADE_EXIT_ORDER_WITH_SYMBOL_SIGNAL_TIEBREAK; see original simultaneous-close groups too',
        worst_closed_net_bps=min(losses) if losses else None,
        worst_decile_loss_mean_bps=sum(tail)/len(tail) if tail else None)


def risk_and_winners(parent, result, accounting):
    pi, ci = a.index(parent), a.index(result)
    large = set(accounting['large_winner']['origins'])
    ordinary = [k for k in pi if pi[k][0]=='C' and pi[k][1]['net_bps']>0 and k not in large]
    total = sum(pi[k][1]['net_bps'] for k in ordinary)
    kept = sum(min(pi[k][1]['net_bps'],max(0,ci[k][1]['net_bps']))
               for k in ordinary if k in ci and ci[k][0]=='C')
    return dict(**closed_risk(result),
        ordinary_winner_parent_T=len(ordinary), ordinary_winner_parent_bps=total,
        ordinary_winner_preserved_bps=kept, ordinary_winner_retention_lower=kept/total if total else None,
        large_winner=accounting['large_winner'], concentration=accounting['concentration'])


def comparison(parent, result):
    out=json.loads(p.canonical(a.compare(parent,result)))
    out['comparison_type']='EXIT_REPAIR_WITH_FULL_OCCUPANCY'
    return out


def derive_summary():
    datasets={per:{label:baseline(label,per) for label in LABELS} for per in PERIODS}
    data={}
    for per in PERIODS:
        for v in VARIANTS:datasets[per][v]=gz(ROOT/OUT/v/per/'RESULT.json.gz')
        rows=datasets[per];snap={k:a.snapshot(v) for k,v in rows.items()}
        variants={}
        for v in VARIANTS:
            accounts={label:comparison(rows[label],rows[v]) for label in LABELS}
            positions=rows[v]['trades']+rows[v]['open_observations']
            raw=gz(ROOT/OUT/v/per/'RAW.json.gz')
            rawpositions=[t for r in raw.values() for k in ('trades','open_positions') for t in r[k]]
            variants[v]=dict(checks_vs_C63=prior.prior.d.prior.previous.checks(snap['C63'],snap[v]),
                attribution=accounts,additional_risk={label:risk_and_winners(rows[label],rows[v],accounts[label]) for label in LABELS},
                F_fills=sum(t['exit_reason']==child.EXIT+'_NEXT_OPEN' for t in rows[v]['trades']),
                F_pending=sum((t.get('pending_exit_trigger') or {}).get('reason')==child.EXIT for t in rows[v]['open_observations']),
                extension_decisions=sum(bool(t.get('runner_context',{}).get('extended')) for t in rawpositions),
                actual_extended_positions=sum(t['f_context']['actual_extended_held_bars']>0 for t in rawpositions),
                actual_extended_held_bars=sum(t['f_context']['actual_extended_held_bars'] for t in rawpositions))
        interaction=snap['B20_F']['terminal_net_bps']-snap['F_ONLY']['terminal_net_bps']-snap['R_B20']['terminal_net_bps']+snap['C63']['terminal_net_bps']
        data[per]=dict(snapshots=snap,variants=variants,risk_by_rule={k:closed_risk(v) for k,v in rows.items()},
            full_net_interaction_bps=interaction,interaction_semantics='DESCRIPTIVE_ARITHMETIC_NOT_INDEPENDENT_CAUSAL_EFFECT')
    combined={label:aggregate([datasets[per][label] for per in PERIODS]) for label in LABELS+VARIANTS}
    decisions={}
    for v in VARIANTS:
        checks=[data[per]['variants'][v]['checks_vs_C63'] for per in PERIODS]
        goal=all(all(x.values()) for x in checks)
        gain=all(x['net_up'] and x['cost2_up'] for x in checks)
        decisions[v]='DEVELOPMENT_GOAL_MET' if goal else 'PARTIAL_IMPROVEMENT' if gain else 'REJECT_KEEP_C63'
    return dict(scope=SCOPE,decisions=decisions,disjoint_arithmetic=combined,periods=data,
        candidates=78,evaluations=140,new_candidates=2,new_FULL=4,parent_replays=0,new_FIXED=0,
        formal_credit=0,independent=False,operating_adoption=False,report_only=True,automatic_successor=False)


def render(summary):
    fmt=lambda x:'—' if x is None else f'{x:.2f}'
    lines=['# C63 / R_B20 / F_ONLY / B20_F — first FULL results','',
        'Two disjoint USED_DEV windows, fixed notional trade-bps. Costs are inherited research models; unfinished positions include hypothetical net marks. No continuous/compound account return, independent evidence or operating adoption. R is a preserved secondary comparator.','',
        '|Window|Rule|Closed/open|WR %|Mean win|Mean loss|Payoff|PF|Terminal net|Full cost2|Daily marked DD|',
        '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for per,rows in [('DISJOINT SUM',summary['disjoint_arithmetic'])]+[(per,summary['periods'][per]['snapshots']) for per in PERIODS]:
        for label,m in rows.items():
            lines.append('|'+ '|'.join([per,label,f"{m['closed']}/{m['open']}",fmt(100*m['win_rate'])]+
                [fmt(m[k]) for k in ('average_win_bps','average_loss_bps','realized_payoff','PF','terminal_net_bps','terminal_cost2x_net_bps','marked_DD_trade_sum_bps')])+'|')
    lines+=['',json.dumps(summary['decisions']),'']
    for per in PERIODS:
        row=summary['periods'][per];lines+=['## '+per,'', 'FULL net interaction (descriptive only): '+fmt(row['full_net_interaction_bps'])+' bps.','']
        for v in VARIANTS:
            x=row['variants'][v];lines+=['### '+v,'','C63 frozen checks: '+json.dumps(x['checks_vs_C63']),
                'F fills/pending: '+str(x['F_fills'])+'/'+str(x['F_pending'])+
                '; extension flags / actual held21+ positions: '+str(x['extension_decisions'])+'/'+str(x['actual_extended_positions'])+'.','']
            for label in ('C63','R_B20'):
                acc=x['attribution'][label];risk=x['additional_risk'][label]
                lines+=['Against '+label+':','',
                    '- Four-way total net bridge: '+json.dumps(acc['four_way_terminal_delta']),
                    '- Saved/worsened losses, harmed/improved winners and cost change (cost is already in net, not added twice): '+json.dumps(acc['resolved_common_effects']),
                    '- Ordinary/top-decile winner amount retention: '+fmt(risk['ordinary_winner_retention_lower'])+'/'+fmt(acc['large_winner']['amount_retention_lower']),
                    '- Same-calendar risk at BOTH actual parent/candidate peak-to-trough windows: '+json.dumps(acc['same_calendar_risk']),
                    '- Closed loss streak/worst/loss-decile: '+json.dumps(closed_risk(gz(ROOT/OUT/v/per/'RESULT.json.gz'))),
                    '- Exposure: '+json.dumps(row['snapshots'][v]['exposure']),'']
    lines+=['All origin CC/CO/OC/OO/new/removed rows, gross/cost/net/cost2 bridges, concentration, and full same-DD-window contributions remain in ACCOUNTING_*.json and SUMMARY.json. The native signal pool is preserved; actual FULL entry sets can change after actual F fills. No selected-winner exemptions or extra FIXED replay.','',
        'Changed files are the new F adapter, focused synthetic tests, scope study, workflow and this scope evidence only. No deployment. Rollback disables this research successor while preserving all attempts, budgets, sources and results. This scope ends REPORT_ONLY, with no automatic next experiment.','']
    return '\n'.join(lines)


def summarize():
    check();b=read(ROOT/OUT/'BUDGET.json');need(b[KEY]['completed']==4 and not b[KEY]['failed'],'INCOMPLETE')
    summary=derive_summary();put(ROOT/OUT/'SUMMARY.json',summary)
    (ROOT/OUT/'REPORT.md').write_text(render(summary))
    atomic('STATUS.json',dict(scope=SCOPE,status='REPORT_ONLY',decisions=summary['decisions'],owner_run=owner(),
        owned_economic_executions=[],automatic_retry=False,automatic_successor=False))
    put(ROOT/OUT/'EVIDENCE_HASHES.json',{str(x.relative_to(ROOT/OUT)):h(x) for x in sorted((ROOT/OUT).rglob('*'))
        if x.is_file() and x.name!='EVIDENCE_HASHES.json'})
    print(json.dumps(dict(decisions=summary['decisions'],disjoint_arithmetic=summary['disjoint_arithmetic'])))


def verify():
    spec=check();hashes=read(ROOT/OUT/'EVIDENCE_HASHES.json')
    actual={str(x.relative_to(ROOT/OUT)) for x in (ROOT/OUT).rglob('*') if x.is_file() and x.name!='EVIDENCE_HASHES.json'}
    need(actual==set(hashes),'EVIDENCE_COVERAGE')
    for name,digest in hashes.items():need(h(ROOT/OUT/name)==digest,'EVIDENCE_DRIFT:'+name)
    summary=read(ROOT/OUT/'SUMMARY.json');budget=read(ROOT/OUT/'BUDGET.json');q=budget[KEY]
    need((budget['cumulative_actual'],budget['cumulative_actual_evaluations'])==(78,140),'CUMULATIVE_LEDGER')
    need(q['reserved']==q['started']==q['completed']==4 and q['failed']==q['remaining']==0,'ALLOCATION')
    inherited=read(ROOT/OUT/'HISTORY_PRIOR.json')
    need(budget['trials'][:-4]==inherited['trials'] and budget['candidate_trials'][:-2]==inherited['candidate_trials'],'OLD_TRIALS_CHANGED')
    for key,value in inherited.items():
        if key not in ('trials','candidate_trials','cumulative_actual','cumulative_actual_evaluations','new_candidate_runs'):
            need(budget[key]==value,'OLD_BUDGET_CHANGED:'+key)
    for j,(v,per) in enumerate(PLAN):
        folder=ROOT/OUT/v/per;raw=gz(folder/'RAW.json.gz');result=gz(folder/'RESULT.json.gz')
        receipt=read(folder/'RECEIPT.json');packet=gz(ROOT/INPUTS/(per+'.json.gz'))
        need(h(folder/'RAW.json.gz')==receipt['raw_sha256'] and h(folder/'RESULT.json.gz')==receipt['result_sha256'],'RAW_RESULT_HASH')
        need((receipt['candidate_ordinal'],receipt['evaluation_ordinal'])==(77+j//2,137+j),'ACTUAL_ORDINAL')
        with patch.dict(integration.engine.RULES,{'M1':child.RULES[v]}):
            charged=integration.charge_and_mark(raw,'M1',packet,spec['periods'][per])
        for key,value in charged.items():need(value==result[key],'RAW_COST_METRIC_MISMATCH:'+key)
        need(a.snapshot(result)==receipt['metrics']==summary['periods'][per]['snapshots'][v],'METRIC_REPORT_PARITY')
        for label in LABELS:
            need(comparison(baseline(label,per),result)==read(folder/('ACCOUNTING_'+label+'.json')),'ATTRIBUTION_PARITY')
    need(derive_summary()==summary,'JUDGMENT_RISK_INTERACTION_SUMMARY_PARITY')
    need((ROOT/OUT/'REPORT.md').read_text()==render(summary),'REPORT_PARITY')
    need(read(ROOT/OUT/'STATUS.json')['status']=='REPORT_ONLY','SCOPE_NOT_CLOSED')
    print('SAVED_RAW_COST_METRICS_ATTRIBUTION_DD_WINDOWS_JUDGMENT_PASS_NO_STRATEGY_REPLAY')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['freeze','reserve','execute','summarize','verify'])
    parser.add_argument('--period',choices=PERIODS);parser.add_argument('--variant',choices=VARIANTS);parser.add_argument('--remote')
    args=parser.parse_args()
    if args.action=='freeze':freeze()
    elif args.action=='reserve':reserve(args.variant,args.period)
    elif args.action=='execute':execute(args.variant,args.period,args.remote)
    elif args.action=='summarize':summarize()
    else:verify()
