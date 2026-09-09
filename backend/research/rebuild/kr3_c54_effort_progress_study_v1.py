"""One C54 successor/two FULLs; freeze and remote runtime claims are mandatory."""
import argparse,gzip,json,os,subprocess,time,traceback,math
from pathlib import Path
from unittest.mock import patch
from backend.research.rebuild import kr3_c51_entry_context_study_v1 as previous
from backend.research.rebuild import kr3_c54_effort_progress_v1 as c
p,a,ROOT=previous.p,previous.a,previous.ROOT
PARENT_OUT=previous.OUT
SCOPE='KR3_C54_EFFORT_PROGRESS_AFTER_PR1226_V1'
OUT='research/development_evidence/'+SCOPE
KEY='c54_effort_progress_allocation';PERIODS=previous.old.PERIODS
read,gz,h,need,put=previous.read,previous.gz,previous.h,previous.need,previous.put

def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT,text=True).strip()
def baseline(per):return gz(ROOT/PARENT_OUT/'B'/per/'RESULT.json.gz')
def save_budget(v):
    target=ROOT/OUT/'BUDGET.json';tmp=target.with_suffix('.pending')
    with tmp.open('xb') as f:f.write(p.canonical(v));f.flush();os.fsync(f.fileno())
    os.replace(tmp,target)
def dependencies():
    v=dict(read(ROOT/PARENT_OUT/'SPEC.json')['source_files_sha256'])
    for name,digest in v.items():need(h(ROOT/name)==digest,'PARENT_SOURCE_DRIFT:'+name)
    for name in ('kr3_c54_effort_progress_v1.py','test_kr3_c54_effort_progress_v1.py','kr3_c54_effort_progress_study_v1.py'):
        name='backend/research/rebuild/'+name;v[name]=h(ROOT/name)
    name=OUT+'/DESIGN.md';v[name]=h(ROOT/name)
    return v

def freeze(inputs):
    previous.verify_spec(inputs);budget=read(ROOT/PARENT_OUT/'BUDGET.json');old=read(ROOT/PARENT_OUT/'SPEC.json')
    need((budget['cumulative_actual'],budget['cumulative_actual_evaluations'])==(55,90),'LATEST_COUNTS_NOT55_90')
    need(KEY not in budget,'DUPLICATE_SCOPE')
    spec=dict(scope=SCOPE,candidate=c.RULE_ID,candidate_ordinal=56,evaluation_ordinals=[91,92],
        source_files_sha256=dependencies(),prior_budget_sha256=h(ROOT/PARENT_OUT/'BUDGET.json'),
        parent_spec_sha256=h(ROOT/PARENT_OUT/'SPEC.json'),input_packet_sha256=old['input_packet_sha256'],periods=old['periods'],
        parent_results_sha256={per:h(ROOT/PARENT_OUT/'B'/per/'RESULT.json.gz') for per in PERIODS},
        max_candidates=1,max_full=2,retry=False,independent=False,formal_credit=0,market_requests=0,unused_oos=0,paid_ai=0,orders=0,
        rule='Keep C54 B. At recovery close veto only if its volume>mean preceding contiguous pullback volume AND positive body<=mean absolute pullback body. Unknown/zero-volume context refuses admission. No other C54 changes.',
        objective='WR/net/cost2 strictly up; daily markedDD strictly down in each USED_DEV period; floating equality is NOT improvement.',
        selection='After C54 single-variable saved volume diagnosis: high recovery volume was not associated with better outcomes. High-volume confirmation was not implemented or economically tested. Narrow high-effort/low-progress conjunction selected before any child economics; no body threshold search or isolated variant PnL. Entire evidence is reused DEV, not independent.',
        code_commit=git('rev-parse','HEAD'),frozen_ns=time.time_ns())
    put(ROOT/OUT/'SPEC.json',spec)
    budget[KEY]=dict(max_candidates=1,max_executions=2,reserved=0,started=0,completed=0,failed=0,remaining=2,retry=False)
    put(ROOT/OUT/'BUDGET.json',budget);print('FROZEN_ONE_CHILD_NO_MARKET_REPLAY')

def verify_spec(inputs=None):
    spec=read(ROOT/OUT/'SPEC.json');need(spec['source_files_sha256']==dependencies(),'FROZEN_CODE_CHANGED')
    need(spec['prior_budget_sha256']==h(ROOT/PARENT_OUT/'BUDGET.json'),'OLD_BUDGET_DRIFT')
    for per,digest in spec['parent_results_sha256'].items():need(h(ROOT/PARENT_OUT/'B'/per/'RESULT.json.gz')==digest,'PARENT_RESULT_DRIFT')
    if inputs:
        for per,digest in spec['input_packet_sha256'].items():need(h(Path(inputs)/f'{per}.json.gz')==digest,'INPUT_DRIFT')
    return spec

def reserve(per):
    spec=verify_spec();j=PERIODS.index(per);budget=read(ROOT/OUT/'BUDGET.json');slot=budget[KEY]
    need(slot['reserved']==slot['completed']==j and not slot['failed'],'DUPLICATE_OR_PREVIOUS_INCOMPLETE')
    need(os.environ.get('GITHUB_RUN_ATTEMPT')=='1','NO_RETRY')
    at=dict(scope=SCOPE,candidate=c.RULE_ID,candidate_ordinal=56,ordinal=91+j,period=per,
        owner_run=os.environ['GITHUB_RUN_ID'],spec_sha256=h(ROOT/OUT/'SPEC.json'),status='RESERVED_NOT_STARTED',time_ns=time.time_ns())
    put(ROOT/OUT/per/'ATTEMPT.json',at);slot['reserved']+=1;slot['remaining']-=1;save_budget(budget)

def execute(per,inputs,remote):
    spec=verify_spec(inputs);j=PERIODS.index(per);out=ROOT/OUT/per;at=read(out/'ATTEMPT.json');head=git('rev-parse','HEAD')
    need(head==remote and at['owner_run']==os.environ['GITHUB_RUN_ID'],'REMOTE_RUNTIME_CLAIM')
    need(os.environ.get('GITHUB_RUN_ATTEMPT')=='1','NO_RETRY')
    need(subprocess.check_output(['git','show',head+':'+str((out/'ATTEMPT.json').relative_to(ROOT))],cwd=ROOT)==(out/'ATTEMPT.json').read_bytes(),'UNCOMMITTED_CLAIM')
    packet=gz(Path(inputs)/f'{per}.json.gz');previous.old.inherited.packet_check(per,packet)
    put(out/'EXECUTION_STARTED.json',dict(claim_commit=head,remote_readback_sha=remote,owner_run=at['owner_run'],time_ns=time.time_ns()))
    budget=read(ROOT/OUT/'BUDGET.json');need(budget['cumulative_actual_evaluations']==90+j,'EVALUATION_COUNT')
    if j==0:
        need(budget['cumulative_actual']==55,'CANDIDATE_COUNT');budget['cumulative_actual']=56;budget['new_candidate_runs']+=1
        budget['candidate_trials'].append(dict(ordinal=56,candidate=c.RULE_ID,first_evaluation=91,scope=SCOPE))
    budget['cumulative_actual_evaluations']+=1;budget[KEY]['started']+=1
    budget['trials'].append(dict(at,status='STARTED',actual_experiment_ordinal=91+j));save_budget(budget)
    try:
        with patch.object(previous,'c',c),patch.object(previous,'baseline',baseline),patch.object(previous,'OUT',OUT),patch.object(previous,'SCOPE',SCOPE):
            raw,result,comparison=previous.run_one('B',per,packet,spec)
        p.write_new(out/'RAW.json.gz',gzip.compress(p.canonical(raw),mtime=0));p.write_new(out/'RESULT.json.gz',gzip.compress(p.canonical(result),mtime=0))
        put(out/'ACCOUNTING_C54.json',comparison)
        put(out/'ACCOUNTING_C51.json',a.compare(gz(ROOT/previous.old.OUT/per/'RESULT.json.gz'),result))
        put(out/'ACCOUNTING_KR3.json',a.compare(previous.old.base(per),result))
        put(out/'RECEIPT.json',dict(status='COMPLETED',period=per,result_sha256=h(out/'RESULT.json.gz'),raw_sha256=h(out/'RAW.json.gz'),spec_sha256=h(ROOT/OUT/'SPEC.json'),claim_commit=head,metrics=a.snapshot(result)))
        budget[KEY]['completed']+=1;budget['trials'][-1]['status']='COMPLETED';save_budget(budget)
        print(json.dumps(a.snapshot(result),sort_keys=True))
    except BaseException as exc:
        put(out/'FAILURE.json',dict(status='FAILED_CONSUMED',error=str(exc),traceback=traceback.format_exc(),retry=False))
        budget[KEY]['failed']+=1;budget['trials'][-1]['status']='FAILED_CONSUMED';save_budget(budget);raise

def checks(parent,child):
    def strict(a,b):return a>b and not math.isclose(a,b,rel_tol=1e-11,abs_tol=1e-7)
    return dict(WR_up=parent['win_rate'] is not None and child['win_rate'] is not None and strict(child['win_rate'],parent['win_rate']),
        terminal_net_up=strict(child['terminal_net_bps'],parent['terminal_net_bps']),
        cost2_up=strict(child['terminal_cost2x_net_bps'],parent['terminal_cost2x_net_bps']),
        daily_DD_down=strict(parent['marked_DD_trade_sum_bps'],child['marked_DD_trade_sum_bps']))

def summarize():
    verify_spec();periods={};lines=['# C54 high-effort / low-progress entry veto: measured result','',
        'Fixed nominal trade-bps; USED_DEV only, original open marks retained; not account returns, live fills or independent/G5 evidence.','',
        '|Period|Rule|Closed/open|WR%|Mean win|Mean loss|Payoff|PF|Terminal net|Cost2|Daily markedDD|',
        '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for per in PERIODS:
        ps=a.snapshot(baseline(per));cs=a.snapshot(gz(ROOT/OUT/per/'RESULT.json.gz'))
        periods[per]=dict(parent=ps,child=cs,checks=checks(ps,cs),accounting=read(ROOT/OUT/per/'ACCOUNTING_C54.json'))
        for label,snap in [('C54',ps),('C56',cs)]:
            fmt=lambda x:'NA' if x is None else f'{x:.2f}'
            lines.append('|'+ '|'.join([per,label,f"{snap['closed']}/{snap['open']}",fmt(None if snap['win_rate'] is None else 100*snap['win_rate'])]+[fmt(snap[k]) for k in ('average_win_bps','average_loss_bps','realized_payoff','PF','terminal_net_bps','terminal_cost2x_net_bps','marked_DD_trade_sum_bps')])+'|')
    allgoal=all(all(x['checks'].values()) for x in periods.values());econ=all(x['checks']['terminal_net_up'] and x['checks']['cost2_up'] for x in periods.values())
    status='DEVELOPMENT_GOAL_MET' if allgoal else 'PARTIAL_IMPROVEMENT' if econ else 'REJECT_KEEP_C54'
    put(ROOT/OUT/'SUMMARY.json',dict(status=status,periods=periods,candidates=56,evaluations=92,new_candidates=1,new_full=2,parent_replay=0,formal_credit=0,independent=False))
    lines+=['',status,'','Existing C54/C51/KR3 remain preserved. No post-result threshold change, opposite-filter search, sizing/exit change or automatic successor.','Gain/harm, removed/new/open states, same-calendar DD, concentration and winner retention are in the three per-period accounting files.','Review/CI/merge closure is recorded separately.','']
    (ROOT/OUT/'REPORT.md').write_text('\n'.join(lines));print('\n'.join(lines))

if __name__=='__main__':
    q=argparse.ArgumentParser();q.add_argument('action',choices=['freeze','reserve','execute','summarize']);q.add_argument('--period',choices=PERIODS);q.add_argument('--inputs');q.add_argument('--remote-sha');x=q.parse_args()
    if x.action=='freeze':freeze(x.inputs)
    elif x.action=='reserve':reserve(x.period)
    elif x.action=='execute':execute(x.period,x.inputs,x.remote_sha)
    else:summarize()
