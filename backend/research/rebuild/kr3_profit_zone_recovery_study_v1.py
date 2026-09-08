"""One child of C51; two finite FULLs. No search or prior strategy reruns."""
import argparse,gzip,json,os,subprocess,time,traceback
from pathlib import Path
from unittest.mock import patch
from backend.research.rebuild import kr3_profit_zone_study_v1 as prior
from backend.research.rebuild import kr3_profit_zone_recovery_v1 as c
p,a,ROOT=prior.p,prior.a,prior.ROOT
OLD=prior.OUT
SCOPE='KR3_C51_ONCE_RECOVERY_AFTER_PR1224_V1'
OUT='research/development_evidence/'+SCOPE
KEY='kr3_c51_once_recovery_allocation'
PERIODS=prior.PERIODS
read,gz,h,need,put=prior.read,prior.gz,prior.h,prior.need,prior.put

def baseline(period):return gz(ROOT/OLD/period/'RESULT.json.gz')
def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT,text=True).strip()
def save_budget(v):
    path=ROOT/OUT/'BUDGET.json';tmp=path.with_suffix('.pending')
    with tmp.open('xb') as f:f.write(p.canonical(v));f.flush();os.fsync(f.fileno())
    os.replace(tmp,path)
def dependencies():
    old=read(ROOT/OLD/'SPEC.json');v=dict(old['source_files_sha256'])
    for f,digest in v.items():need(h(ROOT/f)==digest,'PARENT51_SOURCE_DRIFT:'+f)
    for name in ('kr3_profit_zone_recovery_v1.py','test_kr3_profit_zone_recovery_v1.py','kr3_profit_zone_recovery_study_v1.py'):
        f='backend/research/rebuild/'+name;v[f]=h(ROOT/f)
    f=OUT+'/DESIGN.md';v[f]=h(ROOT/f)
    return v

def freeze(inputs):
    old=read(ROOT/OLD/'SPEC.json');budget=read(ROOT/OLD/'BUDGET.json')
    need((budget['cumulative_actual'],budget['cumulative_actual_evaluations'])==(51,82),'LATEST_BASELINE_NOT51_82')
    for per in PERIODS:
        packet=gz(Path(inputs)/f'{per}.json.gz');prior.inherited.packet_check(per,packet)
        need(h(Path(inputs)/f'{per}.json.gz')==old['input_packet_sha256'][per],'ORIGINAL_INPUT_BYTES')
    spec=dict(scope=SCOPE,candidate=c.RULE_ID,candidate_ordinal=52,evaluation_ordinals=[83,84],
        direct_parent='KR3_PROFIT_ZONE_PRESERVATION_EXIT_V1',rule=c.RULE,
        source_files_sha256=dependencies(),prior_budget_sha256=h(ROOT/OLD/'BUDGET.json'),
        prior_spec_sha256=h(ROOT/OLD/'SPEC.json'),periods=old['periods'],
        input_packet_sha256=old['input_packet_sha256'],
        parent_results_sha256={per:h(ROOT/OLD/per/'RESULT.json.gz') for per in PERIODS},
        original_KR3_results_sha256=old['baseline_sha256'],
        development_objective=old['development_objective'],
        comparison='CANDIDATE51_DIRECT_PARENT; KR3_ORIGINAL_CUMULATIVE_CONTROL',
        selection='Post-C51 used-DEV diagnosis: one-bar recovery of four parent-win flips. Not independent; no guaranteed recovery. Prior-low discriminator was descriptive-only and not selected; no sweep or hypothetical child PnL.',
        initial_SL_changed=False,entry_changed=False,cost_model_changed=False,
        max_candidates=1,max_full=2,retry=False,independent=False,formal_credit=0,
        market_requests=0,unused_oos=0,paid_ai=0,orders=0,
        code_commit=git('rev-parse','HEAD'),frozen_ns=time.time_ns())
    put(ROOT/OUT/'SPEC.json',spec)
    budget[KEY]=dict(scope=SCOPE,used=0,completed=0,failed=0,max_executions=2,max_candidates=1,retry=False,spec_sha256=h(ROOT/OUT/'SPEC.json'))
    put(ROOT/OUT/'BUDGET.json',budget)
    print('FROZEN_ONE_HYPOTHESIS_NO_MARKET_REPLAY')

def verify_spec(inputs=None):
    s=read(ROOT/OUT/'SPEC.json')
    need(s['source_files_sha256']==dependencies(),'FROZEN_SOURCE_CHANGED')
    need(s['prior_budget_sha256']==h(ROOT/OLD/'BUDGET.json'),'PARENT_BUDGET_CHANGED')
    for per,digest in s['parent_results_sha256'].items():need(h(ROOT/OLD/per/'RESULT.json.gz')==digest,'PARENT51_RESULT_CHANGED')
    if inputs:
        for per,digest in s['input_packet_sha256'].items():need(h(Path(inputs)/f'{per}.json.gz')==digest,'INPUT_CHANGED')
    return s

def reserve(per):
    s=verify_spec();j=PERIODS.index(per);budget=read(ROOT/OUT/'BUDGET.json');slot=budget[KEY]
    need(slot['used']==j and slot['completed']==j,'DUPLICATE_OR_PREVIOUS_NOT_COMPLETE')
    need(os.environ.get('GITHUB_RUN_ATTEMPT')=='1','NO_RETRY')
    need(budget['cumulative_actual_evaluations']==82+j,'EVALUATION_COUNTER')
    at=dict(scope=SCOPE,candidate=c.RULE_ID,candidate_ordinal=52,actual_experiment_ordinal=83+j,
        period=per,status='RESERVED_BEFORE_ENGINE',owner_run=os.environ['GITHUB_RUN_ID'],
        spec_sha256=h(ROOT/OUT/'SPEC.json'),time_ns=time.time_ns(),retry=False)
    put(ROOT/OUT/per/'ATTEMPT.json',at)
    if j==0:
        need(budget['cumulative_actual']==51,'CANDIDATE_COUNTER')
        budget['cumulative_actual']=52;budget['new_candidate_runs']+=1
        budget['candidate_trials'].append(dict(ordinal=52,candidate=c.RULE_ID,first_evaluation=83,scope=SCOPE))
    slot['used']+=1;budget['cumulative_actual_evaluations']=83+j;budget['trials'].append(at);save_budget(budget)

def execute(per,inputs,remote):
    s=verify_spec(inputs);out=ROOT/OUT/per;at=read(out/'ATTEMPT.json');head=git('rev-parse','HEAD')
    need(head==remote and at['owner_run']==os.environ['GITHUB_RUN_ID'],'REMOTE_CLAIM_OR_OWNER')
    need(os.environ.get('GITHUB_RUN_ATTEMPT')=='1' and at['spec_sha256']==h(ROOT/OUT/'SPEC.json'),'NO_RETRY_OR_SPEC_CHANGED')
    rel=str((out/'ATTEMPT.json').relative_to(ROOT))
    need(subprocess.check_output(['git','show',head+':'+rel],cwd=ROOT)==(out/'ATTEMPT.json').read_bytes(),'CLAIM_NOT_COMMITTED')
    put(out/'EXECUTION_STARTED.json',dict(claim_commit=head,remote_readback_sha=remote,owner_run=at['owner_run'],time_ns=time.time_ns()))
    budget=read(ROOT/OUT/'BUDGET.json')
    try:
        with patch.object(prior,'c',c),patch.object(prior,'base',baseline),patch.object(prior,'OUT',OUT):
            raw,result,comparison=prior.run_one(per,gz(Path(inputs)/f'{per}.json.gz'),s)
        result['scope']=SCOPE
        p.write_new(out/'RAW.json.gz',gzip.compress(p.canonical(raw),mtime=0))
        digest=p.write_new(out/'RESULT.json.gz',gzip.compress(p.canonical(result),mtime=0))
        comparison['comparison_type']='CANDIDATE51_TO_ONCE_RECOVERY_FULL'
        put(out/'ACCOUNTING_C51.json',comparison)
        put(out/'ACCOUNTING_KR3.json',a.compare(prior.base(per),result))
        put(out/'RECEIPT.json',dict(status='COMPLETED',period=per,spec_sha256=h(ROOT/OUT/'SPEC.json'),
            result_sha256=digest,raw_sha256=h(out/'RAW.json.gz'),claim_commit=head,metrics=a.snapshot(result),formal_credit=0))
        budget[KEY]['completed']+=1;budget['trials'][-1]['status']='COMPLETED';save_budget(budget)
        print(json.dumps(a.snapshot(result),sort_keys=True))
    except BaseException as exc:
        put(out/'FAILURE.json',dict(status='FAILED_CONSUMED',error=str(exc),traceback=traceback.format_exc(),retry=False))
        budget[KEY]['failed']+=1;budget['trials'][-1]['status']='FAILED_CONSUMED';save_budget(budget)
        raise

def summarize():
    verify_spec();data={};rows=[]
    for per in PERIODS:
        parent=baseline(per);child=gz(ROOT/OUT/per/'RESULT.json.gz');kr3=prior.base(per)
        snaps={k:a.snapshot(v) for k,v in [('KR3',kr3),('C51',parent),('C52',child)]}
        checks=prior.objective_checks(snaps['C51'],snaps['C52'])
        data[per]=dict(snapshots=snaps,checks_vs_C51=checks,
            cumulative_checks_vs_KR3=prior.objective_checks(snaps['KR3'],snaps['C52']),
            comparison=read(ROOT/OUT/per/'ACCOUNTING_C51.json'),
            delta_net=snaps['C52']['terminal_net_bps']-snaps['C51']['terminal_net_bps'],
            delta_cost2=snaps['C52']['terminal_cost2x_net_bps']-snaps['C51']['terminal_cost2x_net_bps'])
        for label,s in snaps.items():
            rows.append(f"|{per}|{label}|{s['closed']}/{s['open']}|{100*s['win_rate']:.2f}|{s['average_win_bps']:.2f}|{s['average_loss_bps']:.2f}|{s['realized_payoff']:.3f}|{s['PF']:.3f}|{s['terminal_net_bps']:.2f}|{s['terminal_cost2x_net_bps']:.2f}|{s['marked_DD_trade_sum_bps']:.2f}|")
    goal=all(all(d['checks_vs_C51'].values()) for d in data.values())
    economics=all(d['delta_net']>0 and d['delta_cost2']>0 for d in data.values())
    status='DEVELOPMENT_GOAL_MET' if goal else 'TRADEOFF' if economics else 'REJECT_NO_CUMULATIVE_ADOPTION'
    put(ROOT/OUT/'SUMMARY.json',dict(status=status,periods=data,new_economic_evaluations=2,independent=False,formal_credit=0))
    text=['# Candidate51 one-close recovery child — measured result','',status,'',
        'Same fixed nominal trade-bps. Both periods USED_DEV; opens marked with original costs. No account returns or G5 PASS.',
        'C51 is the direct parent, KR3 the original cumulative control. No prior strategy was rerun.','',
        '|Period|Rule|Closed/open|WR %|Mean win|Mean loss|Payoff|PF|Terminal net|Cost2|Daily marked DD|',
        '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']+rows+['',
        'One nonpositive-mark breach may wait exactly one completed close; all original exits retain priority. This can enlarge losses. No assured recovery, stop price or positive fill.',
        'Loss/winner, new/removed and open-state bridge: per-period ACCOUNTING_C51.json and ACCOUNTING_KR3.json.',
        'Candidate51 stays preserved; no operational adoption follows this report. Counts52/84 include actual attempts; prior51/82 and all failures remain unchanged.',
        'CI/merge closure is separate. Completed scope must become verify-only; no retry or automatic successor.','']
    (ROOT/OUT/'REPORT.md').write_text('\n'.join(text));print('\n'.join(text))

if __name__=='__main__':
    q=argparse.ArgumentParser();q.add_argument('action',choices=['freeze','reserve','execute','summarize']);q.add_argument('--inputs');q.add_argument('--period',choices=PERIODS);q.add_argument('--remote-sha');x=q.parse_args()
    if x.action=='freeze':freeze(x.inputs)
    elif x.action=='reserve':reserve(x.period)
    elif x.action=='execute':execute(x.period,x.inputs,x.remote_sha)
    else:summarize()
