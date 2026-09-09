"""One preregistered M1 entry-rescue hypothesis, two first FULLs only."""
import argparse,gzip,json,os,subprocess,time,traceback
from pathlib import Path
from unittest.mock import patch
from backend.research.rebuild import m1_er14_study_v1 as previous
from backend.research.rebuild import m1_er_range_rescue_v1 as child
p,a,ROOT=previous.p,previous.a,previous.ROOT
SCOPE='M1_ER_RANGE_RESCUE_AFTER_PR1232_V1'
OUT='research/development_evidence/'+SCOPE
PRIOR=previous.OUT
OLD=previous.OLD
KEY='m1_er_range_rescue_allocation'
PERIODS=previous.PERIODS
read,gz,h,need,put=previous.read,previous.gz,previous.h,previous.need,previous.put

def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT,text=True).strip()
def parent(per):return previous.baseline(per)
def comparator(per):return gz(ROOT/PRIOR/per/'RESULT.json.gz')
def save_budget(value):
    target=ROOT/OUT/'BUDGET.json';tmp=target.with_suffix('.pending')
    with tmp.open('xb') as f:f.write(p.canonical(value));f.flush();os.fsync(f.fileno())
    os.replace(tmp,target)
def dependencies():
    src=dict(read(ROOT/PRIOR/'SPEC.json')['source_files_sha256'])
    for name,digest in src.items():need(h(ROOT/name)==digest,'PARENT_FROZEN_SOURCE_DRIFT:'+name)
    for name in ('m1_er_range_rescue_v1.py','test_m1_er_range_rescue_v1.py','m1_er_range_rescue_study_v1.py'):
        key='backend/research/rebuild/'+name;src[key]=h(ROOT/key)
    key=OUT+'/DESIGN.md';src[key]=h(ROOT/key)
    return src

def freeze(inputs):
    previous.verify_spec(inputs);prior=read(ROOT/PRIOR/'SPEC.json');budget=read(ROOT/PRIOR/'BUDGET.json')
    need((budget['cumulative_actual'],budget['cumulative_actual_evaluations'])==(62,104),'LATEST_LEDGER_NOT62_104')
    need(KEY not in budget,'DUPLICATE_SCOPE')
    spec=dict(scope=SCOPE,rule=child.RULE_ID,direct_parent=child.er.parent.RULES['M1'],diagnostic_comparator=child.er.RULE_ID,
        candidate_ordinal=63,evaluation_ordinals=[105,106],periods=prior['periods'],input_packet_sha256=prior['input_packet_sha256'],
        source_files_sha256=dependencies(),prior_budget_sha256=h(ROOT/PRIOR/'BUDGET.json'),prior_spec_sha256=h(ROOT/PRIOR/'SPEC.json'),
        parent_results_sha256=prior['parent_results_sha256'],saved_c54_sha256=prior['saved_c54_sha256'],
        comparator_sha256={per:{n:h(ROOT/PRIOR/per/n) for n in ('RAW.json.gz','RESULT.json.gz')} for per in PERIODS},
        rule_text='Original M1 AND (ER14 increases OR close strictly exceeds maximum high of preceding contiguous squeeze episode). Missing ER never bypassed; ties to range high do not rescue. Signal high excluded. All C62 ER-pass eligibility retained.',
        objective=prior['objective'],max_candidates=1,max_full=2,retry=False,independent=False,formal_credit=0,
        selected_on_used_DEV=True,market_requests=0,unused_oos=0,paid_ai=0,orders=0,parent_replay=0,
        code_commit=git('rev-parse','HEAD'),frozen_ns=time.time_ns())
    put(ROOT/OUT/'SPEC.json',spec)
    budget[KEY]=dict(max_candidates=1,max_executions=2,reserved=0,started=0,completed=0,failed=0,remaining=2,retry=False)
    put(ROOT/OUT/'BUDGET.json',budget)

def verify_spec(inputs=None):
    spec=read(ROOT/OUT/'SPEC.json');need(spec['source_files_sha256']==dependencies(),'FROZEN_SOURCE_CHANGED')
    need(h(ROOT/PRIOR/'BUDGET.json')==spec['prior_budget_sha256'] and h(ROOT/PRIOR/'SPEC.json')==spec['prior_spec_sha256'],'PRIOR_CHANGED')
    for per,files in spec['parent_results_sha256'].items():
        for n,d in files.items():need(h(ROOT/OLD/'M1'/per/n)==d,'M1_CHANGED')
    for per,files in spec['comparator_sha256'].items():
        for n,d in files.items():need(h(ROOT/PRIOR/per/n)==d,'C62_CHANGED')
    for per,d in spec['saved_c54_sha256'].items():need(h(ROOT/previous.shared.OUT/'B'/per/'RESULT.json.gz')==d,'C54_CHANGED')
    if inputs:
        for per,d in spec['input_packet_sha256'].items():need(h(Path(inputs)/f'{per}.json.gz')==d,'INPUT_CHANGED')
    return spec

def reserve(per):
    spec=verify_spec();j=PERIODS.index(per);budget=read(ROOT/OUT/'BUDGET.json');slot=budget[KEY]
    need(slot['reserved']==slot['started']==slot['completed']==j and slot['failed']==0,'DUPLICATE_OR_UNRESOLVED')
    need(os.environ.get('GITHUB_RUN_ATTEMPT')=='1','NO_RETRY')
    at=dict(scope=SCOPE,period=per,candidate_ordinal=63,ordinal=105+j,owner_run=os.environ['GITHUB_RUN_ID'],spec_sha256=h(ROOT/OUT/'SPEC.json'),status='RESERVED_NOT_STARTED',time_ns=time.time_ns())
    put(ROOT/OUT/per/'ATTEMPT.json',at);slot['reserved']+=1;slot['remaining']-=1;save_budget(budget)

def execute(per,inputs,remote):
    spec=verify_spec(inputs);j=PERIODS.index(per);out=ROOT/OUT/per;at=read(out/'ATTEMPT.json');head=git('rev-parse','HEAD')
    need(head==remote and at['owner_run']==os.environ['GITHUB_RUN_ID'],'RUNTIME_OWNER_OR_CLAIM')
    need(os.environ.get('GITHUB_RUN_ATTEMPT')=='1' and at['spec_sha256']==h(ROOT/OUT/'SPEC.json'),'NO_RETRY_SPEC')
    need(subprocess.check_output(['git','show',head+':'+str((out/'ATTEMPT.json').relative_to(ROOT))],cwd=ROOT)==(out/'ATTEMPT.json').read_bytes(),'UNCOMMITTED_CLAIM')
    budget=read(ROOT/OUT/'BUDGET.json');slot=budget[KEY]
    need(slot['reserved']==j+1 and slot['started']==slot['completed']==j and slot['failed']==0,'ALREADY_STARTED')
    need(budget['cumulative_actual_evaluations']==104+j,'EVALUATION_COUNT')
    packet=gz(Path(inputs)/f'{per}.json.gz');previous.shared.old.inherited.packet_check(per,packet);cal=spec['periods'][per]
    put(out/'EXECUTION_STARTED.json',dict(claim_commit=head,remote_readback_sha=remote,owner_run=at['owner_run'],time_ns=time.time_ns()))
    if j==0:
        need(budget['cumulative_actual']==62,'CANDIDATE_COUNT');budget['cumulative_actual']+=1;budget['new_candidate_runs']+=1
        budget['candidate_trials'].append(dict(scope=SCOPE,candidate=child.RULE_ID,ordinal=63,first_evaluation=105))
    budget['cumulative_actual_evaluations']+=1;slot['started']+=1;budget['trials'].append(dict(at,status='STARTED',actual_experiment_ordinal=105+j));save_budget(budget)
    try:
        with p.native.sensitivity():
            raw={s:child.replay(rows,eval_start_ms=cal['start_ms'],eval_end_ms=cal['runoff_end_ms']) for s,rows in sorted(packet['rows_by'].items())}
        with patch.dict(previous.integration.engine.RULES,{'M1':child.RULE_ID}):result=previous.integration.charge_and_mark(raw,'M1',packet,cal)
        result.update(scope=SCOPE,period=per,spec_sha256=h(ROOT/OUT/'SPEC.json'),direct_parent=spec['direct_parent'])
        identity=lambda e:(e['symbol'],e['signal_index'],e['signal_ts'])
        need({identity(e) for e in result['events']}=={identity(e) for e in parent(per)['events']},'M1_SIGNAL_POOL_CHANGED')
        p.write_new(out/'RAW.json.gz',gzip.compress(p.canonical(raw),mtime=0));p.write_new(out/'RESULT.json.gz',gzip.compress(p.canonical(result),mtime=0))
        put(out/'ACCOUNTING_M1.json',a.compare(parent(per),result));put(out/'ACCOUNTING_C62.json',a.compare(comparator(per),result))
        put(out/'RECEIPT.json',dict(status='COMPLETED',period=per,candidate_ordinal=63,result_sha256=h(out/'RESULT.json.gz'),raw_sha256=h(out/'RAW.json.gz'),spec_sha256=h(ROOT/OUT/'SPEC.json'),claim_commit=head,metrics=a.snapshot(result)))
        slot['completed']+=1;budget['trials'][-1]['status']='COMPLETED';save_budget(budget);print(json.dumps(a.snapshot(result)))
    except BaseException as exc:
        put(out/'FAILURE.json',dict(status='FAILED_CONSUMED',error=str(exc),traceback=traceback.format_exc(),retry=False))
        slot['failed']+=1;budget['trials'][-1]['status']='FAILED_CONSUMED';save_budget(budget);raise

def summarize():
    verify_spec();data={};lines=['# M1 ER or prior squeeze-range escape — USED_DEV comparison','',
        'Original M1 is direct parent; rejected C62 is diagnostic only. Fixed notional trade-bps, original open marks, not account returns or independent/G5 evidence.','',
        '|Period|Rule|Closed/open|WR%|Mean win|Mean loss|Payoff|PF|Terminal net|Cost2|Daily DD|',
        '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for per in PERIODS:
        refs={'M1':parent(per),'C62':comparator(per),'C63':gz(ROOT/OUT/per/'RESULT.json.gz')};snap={k:a.snapshot(v) for k,v in refs.items()}
        data[per]=dict(snapshots=snap,checks=previous.checks(snap['M1'],snap['C63']),accounting_M1=read(ROOT/OUT/per/'ACCOUNTING_M1.json'),accounting_C62=read(ROOT/OUT/per/'ACCOUNTING_C62.json'))
        for label,s in snap.items():
            fmt=lambda x:'NA' if x is None else f'{x:.2f}'
            lines.append('|'+ '|'.join([per,label,f"{s['closed']}/{s['open']}",fmt(None if s['win_rate'] is None else 100*s['win_rate'])]+[fmt(s[k]) for k in ('average_win_bps','average_loss_bps','realized_payoff','PF','terminal_net_bps','terminal_cost2x_net_bps','marked_DD_trade_sum_bps')])+'|')
    goal=all(all(v['checks'].values()) for v in data.values());gain=all(v['checks']['net_up'] and v['checks']['cost2_up'] for v in data.values())
    status='DEVELOPMENT_GOAL_MET' if goal else 'PARTIAL_IMPROVEMENT' if gain else 'REJECT_KEEP_M1_AND_C54'
    put(ROOT/OUT/'SUMMARY.json',dict(status=status,periods=data,candidates=63,evaluations=106,new_candidates=1,new_full=2,selected_on_used_DEV=True,independent=False,formal_credit=0))
    lines+=['',status,'','All retained C62 eligibility is preserved, but added actual occupancy can displace later trades: inspect full attribution rather than assuming monotone trade sets. No year/symbol exceptions, buffer search, exit/sizing change or automatic next candidate.','']
    (ROOT/OUT/'REPORT.md').write_text('\n'.join(lines));print('\n'.join(lines))
    files={str(x.relative_to(ROOT/OUT)):h(x) for x in (ROOT/OUT).rglob('*') if x.is_file() and x.name!='EVIDENCE_HASHES.json'}
    put(ROOT/OUT/'EVIDENCE_HASHES.json',files)

if __name__=='__main__':
    q=argparse.ArgumentParser();q.add_argument('action',choices=['freeze','reserve','execute','summarize']);q.add_argument('--inputs');q.add_argument('--period',choices=PERIODS);q.add_argument('--remote-sha');x=q.parse_args()
    if x.action=='freeze':freeze(x.inputs)
    elif x.action=='reserve':reserve(x.period)
    elif x.action=='execute':execute(x.period,x.inputs,x.remote_sha)
    else:summarize()
