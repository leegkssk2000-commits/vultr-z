"""One partial candidate, TWO counted FULL applications, stored C63 controls.
FIXED direct effect is the same result, not a second replay: entry/final occupancy
is checked identical for every origin/event, with a nonzero residual always held.
"""
import argparse,gzip,json,os,subprocess,time,traceback
from pathlib import Path
from backend.research.rebuild import m1_er_range_rescue_study_v1 as parent
from backend.research.rebuild import c63_partial_profit_v1 as child
p,a,ROOT=parent.p,parent.a,parent.ROOT
read,gz,h,need,put=parent.read,parent.gz,parent.h,parent.need,parent.put
PERIODS=parent.PERIODS
SCOPE='C63_PARTIAL_REALIZATION_AFTER_PR1238_V1'
OUT='research/development_evidence/'+SCOPE
LATEST='research/development_evidence/C63_FAILED_BREAKOUT_EXIT_AFTER_PR1233_V1'
KEY='c63_partial_profit_allocation'
CODE=['backend/research/rebuild/'+n for n in ('c63_partial_profit_v1.py','c63_partial_profit_study_v1.py','test_c63_partial_profit_v1.py')]

def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT,text=True,timeout=30).strip()
def baseline(per):return gz(ROOT/parent.OUT/per/'RESULT.json.gz')
def save_budget(b):
    target=ROOT/OUT/'BUDGET.json';tmp=target.with_suffix('.pending')
    with tmp.open('xb') as f:f.write(p.canonical(b));f.flush();os.fsync(f.fileno())
    os.replace(tmp,target)
def dependencies():
    result=dict(read(ROOT/parent.OUT/'SPEC.json')['source_files_sha256'])
    for name,d in result.items():need(h(ROOT/name)==d,'C63_DEPENDENCY_DRIFT:'+name)
    for name in CODE+[OUT+'/DESIGN.md']:result[name]=h(ROOT/name)
    return result


def synthetic_cost_preflight(inputs):
    """Native charge/mark smoke with ARTIFICIAL prices, original cost schema only.
    No original price is supplied to a strategy, no results retained as evidence.
    """
    from copy import deepcopy
    from backend.research.rebuild.test_chart_mechanism_execution_v1 import momentum_fixture,rows_of
    packet=gz(Path(inputs)/'DEV2025.json.gz')
    bars=momentum_fixture();rows=rows_of(bars);end=len(bars)*parent.child.BAR
    symbol=sorted(packet['costs'])[0]
    raw=parent.child.replay(rows,eval_start_ms=0,eval_end_ms=end)
    need(len(raw['trades'])>0,'ARTIFICIAL_SETUP_MISSING')
    for t in raw['trades']+raw['open_positions']:
        t['partial_realization']=dict(decisions=[],trigger=None,fill=None,pending_at_end=False)
    t=raw['trades'][0];j=t['entry_index']+1
    trigger=dict(reason=child.REASON,index=j,signal_index=j,signal_ts=bars[j+1].open_ts,
                 decision_ts=bars[j+1].open_ts,observed_close=bars[j].close,fraction=[1,3])
    t['partial_realization'].update(trigger=trigger,fill=dict(index=j+1,ts=bars[j+1].open_ts,price=bars[j+1].open,trigger=trigger))
    fake=dict(rows_by={symbol:rows},costs=packet['costs'],policy=packet['policy'])
    result=child.charge_and_mark({symbol:raw},fake,dict(start_ms=0,runoff_end_ms=end))
    x=result['trades'][0];need(len(x['weighted_legs'])==2,'LEG_CHARGE_MISSING')
    a.owner._values(('C',x))
    need(abs(x['fee_bps']-sum(z['row']['fee_bps']*z['numerator']/z['denominator'] for z in x['weighted_legs']))<1e-10,'ENTRY_FEE_DUPLICATION')
    # Open-tail accounting has one realized fraction, never a completed win.
    raw=parent.child.replay(rows[:40],eval_start_ms=0,eval_end_ms=40*parent.child.BAR)
    need(len(raw['open_positions'])>0,'ARTIFICIAL_OPEN_MISSING')
    for v in raw['trades']+raw['open_positions']:v['partial_realization']=deepcopy(t['partial_realization'])
    fake['rows_by']={symbol:rows[:40]}
    result=child.charge_and_mark({symbol:raw},fake,dict(start_ms=0,runoff_end_ms=40*parent.child.BAR))
    need(not result['trades'] and len(result['open_observations'])==1,'PARTIAL_AS_FULL_WIN')
    x=result['open_observations'][0];a.owner._values(('O',x))
    need(abs(x['realized_partial_net_bps']+x['remaining_hypothetical_net_mark_bps']-x['hypothetical_liquidation_net_mark_bps'])<1e-8,'OPEN_REALIZED_SPLIT')
    print('ARTIFICIAL_NATIVE_COST_AND_DAILY_CLOSED_OPEN_PREFLIGHT_PASS; ZERO_MARKET_EVALUATIONS')

def freeze(inputs):
    parent.verify_spec(inputs);old=read(ROOT/parent.OUT/'SPEC.json');b=read(ROOT/LATEST/'BUDGET.json')
    need((b['cumulative_actual'],b['cumulative_actual_evaluations'])==(64,110),'LATEST_NOT64_110')
    need(KEY not in b,'SCOPE_EXISTS')
    spec=dict(scope=SCOPE,rule=child.RULE_ID,direct_parent=parent.child.RULE_ID,candidate_ordinal=65,
        evaluation_ordinals=[111,112],max_candidates=1,max_full=2,max_fixed_replays=0,
        fixed_view='SAME_ORIGIN_ACCOUNTING_OF_FULL; final exit/occupancy invariance proved; not a separate replay',
        periods=old['periods'],input_packet_sha256=old['input_packet_sha256'],
        source_files_sha256=dependencies(),prior_budget_sha256=h(ROOT/LATEST/'BUDGET.json'),
        parent_spec_sha256=h(ROOT/parent.OUT/'SPEC.json'),
        parent_results_sha256={per:{n:h(ROOT/parent.OUT/per/n) for n in ('RAW.json.gz','RESULT.json.gz')} for per in PERIODS},
        rule_text='At first held completed close: native exit reason NONE, 0<current native momentum<previous completed native momentum and native accrued modeled net>0; sell original1/3 at next actual open strictly before end. At gaps execute that next open even when the gain disappears. Keep original2/3 and all native final exits, entries and occupancy; no BE/trail/new SL/target/entry/sizing rule.',
        cost='Original proportional fixed-notional unit charge for each leg, weighted1/3+2/3; entry costs allocated once; elapsed funding stops separately; all-cost2. Full-cost open marks kept and realized part separately shown. Not exchange lot/minfee/depth/fills.',
        objective='Same existing four strict DEV checks versus C63: WR/net/cost2 up, markedDD down in EACH period. Equality not improvement. Report loss size, ordinary/topdecile winner harm and concentration.',
        original_trader_replication=False,source_relation='Only staged original-position fraction is inherited from PR1238. Timing predicate is an explicitly new ZEL/native-M1 adaptation, NOT Carter exact highs/Fib/options timing.',
        retry=False,independent=False,formal_credit=0,parent_replay=0,market_requests=0,unused_oos=0,paid_ai=0,orders=0,
        code_commit=git('rev-parse','HEAD'),frozen_ns=time.time_ns())
    put(ROOT/OUT/'SPEC.json',spec)
    b[KEY]=dict(max_candidates=1,max_executions=2,reserved=0,started=0,completed=0,failed=0,remaining=2,retry=False)
    put(ROOT/OUT/'BUDGET.json',b)

def verify_spec(inputs=None):
    s=read(ROOT/OUT/'SPEC.json');need(s['source_files_sha256']==dependencies(),'FROZEN_CODE_CHANGED')
    need(s['prior_budget_sha256']==h(ROOT/LATEST/'BUDGET.json'),'LATEST_LEDGER_CHANGED')
    need(s['parent_spec_sha256']==h(ROOT/parent.OUT/'SPEC.json'),'PARENT_SPEC_CHANGED')
    for per,files in s['parent_results_sha256'].items():
        for n,d in files.items():need(h(ROOT/parent.OUT/per/n)==d,'C63_RESULT_CHANGED')
    if inputs:
        for per,d in s['input_packet_sha256'].items():need(h(Path(inputs)/f'{per}.json.gz')==d,'INPUT_CHANGED')
    return s

def reserve(per):
    s=verify_spec();j=PERIODS.index(per);b=read(ROOT/OUT/'BUDGET.json');slot=b[KEY]
    need(slot['reserved']==slot['started']==slot['completed']==j and not slot['failed'],'DUPLICATE_OR_UNRESOLVED')
    need(os.environ.get('GITHUB_RUN_ATTEMPT')=='1','NO_RETRY')
    at=dict(scope=SCOPE,period=per,view='FULL',candidate_ordinal=65,ordinal=111+j,
        owner_run=os.environ['GITHUB_RUN_ID'],spec_sha256=h(ROOT/OUT/'SPEC.json'),
        status='RESERVED_NOT_STARTED',time_ns=time.time_ns())
    put(ROOT/OUT/per/'ATTEMPT.json',at);slot['reserved']+=1;slot['remaining']-=1;save_budget(b)

def parity(par,result):
    pi,ci=a.index(par),a.index(result);need(set(pi)==set(ci),'ORIGIN_SET')
    for k in pi:
        ps,pp=pi[k];cs,cc=ci[k];need(ps==cs,'CLOSED_OPEN_STATUS')
        for field in ('signal_ts','entry_ts','entry_price','fixed_floor','fixed_target','hold_ms'):
            need(pp.get(field)==cc.get(field),'ORIGINAL_GEOMETRY:'+field)
        for field in (('exit_ts','exit_price','exit_reason') if ps=='C' else ('mark_ts','mark_price','censor_reason')):
            need(pp.get(field)==cc.get(field),'FINAL_EXIT_CHANGED:'+field)
    key=lambda e:(e['symbol'],e['signal_index'],e['signal_ts'])
    old={key(e):(e['admission'],e['status'],e['exclusion_reason']) for e in par['events']}
    new={key(e):(e['admission'],e['status'],e['exclusion_reason']) for e in result['events']}
    need(old==new and len(old)==len(par['events']) and len(new)==len(result['events']),'FULL_ADMISSION_OCCUPANCY_CHANGED')
    return dict(status='PASS',positions=len(pi),signals=len(old),closed_open_or_new_removed=0,
        fixed_direct_view_equals_full=True,reason='Residual never flat before native final exit; all event admission/reasons and final clocks identical')

def execute(per,inputs,remote):
    s=verify_spec(inputs);j=PERIODS.index(per);out=ROOT/OUT/per;at=read(out/'ATTEMPT.json');head=git('rev-parse','HEAD')
    need(head==remote and at['owner_run']==os.environ['GITHUB_RUN_ID'],'RUNTIME_CLAIM_OWNER')
    need(os.environ.get('GITHUB_RUN_ATTEMPT')=='1' and at['spec_sha256']==h(ROOT/OUT/'SPEC.json'),'NO_RETRY_SPEC')
    need(subprocess.check_output(['git','show',head+':'+str((out/'ATTEMPT.json').relative_to(ROOT))],cwd=ROOT,timeout=30)==(out/'ATTEMPT.json').read_bytes(),'UNCOMMITTED_CLAIM')
    b=read(ROOT/OUT/'BUDGET.json');slot=b[KEY]
    need(slot['reserved']==j+1 and slot['started']==slot['completed']==j and not slot['failed'],'ALREADY_STARTED')
    need(b['cumulative_actual_evaluations']==110+j,'EVALUATION_COUNT')
    packet=gz(Path(inputs)/f'{per}.json.gz');parent.previous.shared.old.inherited.packet_check(per,packet);cal=s['periods'][per]
    par=baseline(per)
    put(out/'EXECUTION_STARTED.json',dict(claim_commit=head,remote_readback_sha=remote,owner_run=at['owner_run'],time_ns=time.time_ns()))
    if j==0:
        need(b['cumulative_actual']==64,'CANDIDATE_COUNT');b['cumulative_actual']+=1;b['new_candidate_runs']+=1
        b['candidate_trials'].append(dict(scope=SCOPE,candidate=child.RULE_ID,ordinal=65,first_evaluation=111))
    b['cumulative_actual_evaluations']+=1;slot['started']+=1;b['trials'].append(dict(at,status='STARTED',actual_experiment_ordinal=111+j));save_budget(b)
    try:
        with p.native.sensitivity():
            raw={sym:child.replay(rows,eval_start_ms=cal['start_ms'],eval_end_ms=cal['runoff_end_ms'],cost_model=packet['costs'][sym]) for sym,rows in sorted(packet['rows_by'].items())}
        result=child.charge_and_mark(raw,packet,cal)
        result.update(scope=SCOPE,period=per,view='FULL',spec_sha256=h(ROOT/OUT/'SPEC.json'),direct_parent=s['direct_parent'])
        checked=parity(par,result);result['entry_final_occupancy_parity']=checked
        p.write_new(out/'RAW.json.gz',gzip.compress(p.canonical(raw),mtime=0))
        p.write_new(out/'RESULT.json.gz',gzip.compress(p.canonical(result),mtime=0))
        compared=a.compare(par,result);compared['comparison_type']='PARTIAL_ONLY_FIXED_EQUALS_FULL_PROVEN'
        put(out/'ACCOUNTING_C63.json',compared)
        put(out/'RECEIPT.json',dict(status='COMPLETED',period=per,candidate_ordinal=65,
            result_sha256=h(out/'RESULT.json.gz'),raw_sha256=h(out/'RAW.json.gz'),
            spec_sha256=h(ROOT/OUT/'SPEC.json'),claim_commit=head,metrics=a.snapshot(result),parity=checked))
        slot['completed']+=1;b['trials'][-1]['status']='COMPLETED';save_budget(b);print(json.dumps(a.snapshot(result)))
    except BaseException as exc:
        put(out/'FAILURE.json',dict(status='FAILED_CONSUMED',error=str(exc),traceback=traceback.format_exc(),retry=False))
        slot['failed']+=1;b['trials'][-1]['status']='FAILED_CONSUMED';save_budget(b);raise

def summarize():
    verify_spec();data={};lines=['# C63 one-third profitable momentum-deceleration partial — USED_DEV','',
        'A ZEL adaptation, not exact creator/options replication. Same complete-position WR denominator, native final occupancy and open tails. Leg returns/costs weighted on ORIGINAL notional. No account return or independent evidence.','',
        '|Period|Rule|Closed/open|WR%|Mean win|Mean loss|Payoff|PF|Terminal net|Cost2|Daily DD|',
        '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for per in PERIODS:
        result=gz(ROOT/OUT/per/'RESULT.json.gz');par=baseline(per);snaps={'C63':a.snapshot(par),'C65':a.snapshot(result)}
        data[per]=dict(snapshots=snaps,checks=parent.previous.checks(snaps['C63'],snaps['C65']),
            accounting=read(ROOT/OUT/per/'ACCOUNTING_C63.json'),partial_filled_T=result['metrics']['partial_completed_T'],
            weighted_exposure_symbol_days=result['metrics']['reference_notional_symbol_days'],
            realized_partial_net_in_unfinished_bps=result['metrics']['realized_partial_net_in_unfinished_bps'],
            remaining_only_open_mark_bps=result['metrics']['remaining_only_open_mark_bps'],
            invariance=result['entry_final_occupancy_parity'])
        for label,v in snaps.items():
            fmt=lambda x:'NA' if x is None else f'{x:.2f}'
            lines.append('|'+ '|'.join([per,label,f"{v['closed']}/{v['open']}",fmt(None if v['win_rate'] is None else 100*v['win_rate'])]+[fmt(v[k]) for k in ('average_win_bps','average_loss_bps','realized_payoff','PF','terminal_net_bps','terminal_cost2x_net_bps','marked_DD_trade_sum_bps')])+'|')
    goal=all(all(v['checks'].values()) for v in data.values())
    gain=all(v['checks']['net_up'] and v['checks']['cost2_up'] for v in data.values())
    status='DEVELOPMENT_GOAL_MET' if goal else 'PARTIAL_IMPROVEMENT' if gain else 'REJECT_KEEP_C63'
    summary=dict(status=status,periods=data,candidates=65,evaluations=112,new_candidates=1,new_full=2,
        separate_fixed_replays=0,fixed_full_equality='PROVED_BY_SAME_ENTRY_AND_FINAL_OCCUPANCY',
        independent=False,formal_credit=0,G5_status='HOLD',operating_adoption=False,automatic_next_candidate=False)
    put(ROOT/OUT/'SUMMARY.json',summary)
    lines+=['',status,'','No parameter retune or second candidate. Native residual final exit is unchanged; differences are realized partial price, its shorter funding/exposure, and saved ordinary/large winner harms. The same-origin direct view is mathematically identical to FULL here, not another market evaluation.','']
    (ROOT/OUT/'REPORT.md').write_text('\n'.join(lines));print('\n'.join(lines))
    put(ROOT/OUT/'EVIDENCE_HASHES.json',{str(x.relative_to(ROOT/OUT)):h(x) for x in (ROOT/OUT).rglob('*') if x.is_file() and x.name!='EVIDENCE_HASHES.json'})

if __name__=='__main__':
    q=argparse.ArgumentParser();q.add_argument('action',choices=['smoke','freeze','reserve','execute','summarize']);q.add_argument('--period',choices=PERIODS);q.add_argument('--inputs');q.add_argument('--remote-sha');x=q.parse_args()
    if x.action=='smoke':synthetic_cost_preflight(x.inputs)
    elif x.action=='freeze':freeze(x.inputs)
    elif x.action=='reserve':reserve(x.period)
    elif x.action=='execute':execute(x.period,x.inputs,x.remote_sha)
    else:summarize()
