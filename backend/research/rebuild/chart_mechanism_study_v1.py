"""Sole Work owner: frozen five-lane study, remote claims, no automatic retry.

No economic CI or automatic dispatch. The caller persists and reads back each
claim via the authorized GitHub connector before invoking execute once.
"""
import argparse, gzip, json, os, time, traceback
from pathlib import Path
from backend.research.rebuild import kr3_c51_entry_context_study_v1 as shared
from backend.research.rebuild import chart_mechanism_integration_v1 as integration

p,a,ROOT=shared.p,shared.a,shared.ROOT
SCOPE='TOP5_SOURCE_CHART_MECHANISMS_AFTER_PR1228_V1'
OUT='research/development_evidence/'+SCOPE
PRIOR='research/development_evidence/KR3_C54_PULLBACK_FAILURE_AFTER_PR1227_V1/BUDGET.json'
KEY='chart_allocation'; VARIANTS=integration.engine.VARIANTS; PERIODS=shared.old.PERIODS
read,gz,h,need,put=shared.read,shared.gz,shared.h,shared.need,shared.put
OWNER='WORK_CHART_PR1229_20260909'

def save_budget(value):
    path=ROOT/OUT/'BUDGET.json';tmp=path.with_suffix('.pending')
    with tmp.open('xb') as f:f.write(p.canonical(value));f.flush();os.fsync(f.fileno())
    os.replace(tmp,path)

def baseline(period):return gz(ROOT/shared.OUT/'B'/period/'RESULT.json.gz')

def freeze(inputs):
    inherited=read(ROOT/PRIOR); parent=read(ROOT/shared.OUT/'SPEC.json')
    need((inherited['cumulative_actual'],inherited['cumulative_actual_evaluations'])==(57,94),'LATEST_LEDGER_NOT57_94')
    need(KEY not in inherited,'DUPLICATE_SCOPE')
    shared.verify_spec(inputs)
    files=dict(parent['source_files_sha256'])
    names=['chart_mechanism_features_v1.py','chart_mechanism_execution_v1.py','chart_mechanism_integration_v1.py','chart_mechanism_study_v1.py','test_chart_mechanism_execution_v1.py','test_chart_mechanism_c54_binding_v1.py','test_chart_mechanism_study_v1.py']
    for name in names:files['backend/research/rebuild/'+name]=h(ROOT/'backend/research/rebuild'/name)
    for name in ['REQUEST.txt','SOURCE_REVIEW.md','SOURCE_RECEIPTS.json','LANE_AUTHORITY.json','verify_saved.py','report_saved.py','test_verify_saved.py']:
        files[OUT+'/'+name]=h(ROOT/OUT/name)
    bindings=read(ROOT/OUT/'LANE_AUTHORITY.json')
    spec=dict(scope=SCOPE,rules=integration.engine.RULES,rule_text_path=OUT+'/REQUEST.txt',variants=list(VARIANTS),periods=parent['periods'],
      input_packet_sha256=parent['input_packet_sha256'],source_files_sha256=files,
      prior_budget_path=PRIOR,prior_budget_sha256=h(ROOT/PRIOR),parent_spec_sha256=h(ROOT/shared.OUT/'SPEC.json'),
      parent_results_sha256={per:h(ROOT/shared.OUT/'B'/per/'RESULT.json.gz') for per in PERIODS},
      cost_hash=shared.old.inherited.COST,cost_path=shared.old.OUT+'/COSTS.json',
      lane_status=bindings['lane_status'],volume_bindings=bindings.get('volume_bindings',{}),
      max_candidates=5,max_full=10,retry=False,independent=False,formal_credit=0,
      objective='All four strict checks in BOTH periods: WR up, total marked net up, all cost2 up, daily markedDD down. No new threshold.',
      classification='DEVELOPMENT_GOAL_MET only eight checks; PARTIAL_IMPROVEMENT only both-period net and cost2 improve; otherwise REJECT_KEEP_C54. Standalone M/R do not become C54 children.',
      source_ref='6d6335d1c9ad7ecb1e9597da85c2eb87635561e1',owner=OWNER,frozen_ns=time.time_ns(),
      market_requests=0,unused_oos=0,paid_ai=0,orders=0,parent_replay=0,extra_fixed_replay=0)
    put(ROOT/OUT/'SPEC.json',spec)
    inherited[KEY]=dict(max_candidates=5,max_executions=10,reserved=0,started=0,completed=0,failed=0,remaining=10,retry=False)
    put(ROOT/OUT/'BUDGET.json',inherited)
    for variant,status in spec['lane_status'].items():
        if status!='READY':put(ROOT/OUT/variant/'NOT_RUN.json',dict(status='NOT_RUN',reason=status,consumed=0))

def verify_spec(inputs=None):
    s=read(ROOT/OUT/'SPEC.json')
    for name,digest in s['source_files_sha256'].items():need(h(ROOT/name)==digest,'FROZEN_CODE_CHANGED:'+name)
    need(h(ROOT/PRIOR)==s['prior_budget_sha256'],'PRIOR_LEDGER_CHANGED')
    for per,digest in s['parent_results_sha256'].items():need(h(ROOT/shared.OUT/'B'/per/'RESULT.json.gz')==digest,'C54_RESULT_CHANGED')
    need(p.sha(read(ROOT/s['cost_path']))==s['cost_hash'],'COST_CHANGED')
    if inputs:
        for per,digest in s['input_packet_sha256'].items():need(h(Path(inputs)/f'{per}.json.gz')==digest,'SOURCE_PACKET_CHANGED')
    return s

def reserve(variant,period):
    s=verify_spec();need(variant in VARIANTS and period in PERIODS,'SLOT_NOT_AUTHORIZED')
    need(s['lane_status'][variant]=='READY','LANE_SOURCE_BLOCKED')
    v=read(ROOT/OUT/'BUDGET.json');slot=v[KEY]
    need(slot['remaining']>0 and slot['reserved']==slot['completed']+slot['failed'],'PREVIOUS_RUN_UNRESOLVED')
    out=ROOT/OUT/variant/period
    need(not (out/'ATTEMPT.json').exists(),'NO_SLOT_RETRY')
    at=dict(scope=SCOPE,variant=variant,period=period,ordinal=v['cumulative_actual_evaluations']+1,
      owner_run=OWNER,spec_sha256=h(ROOT/OUT/'SPEC.json'),status='RESERVED_NOT_STARTED',time_ns=time.time_ns(),retry=False)
    put(out/'ATTEMPT.json',at);slot['reserved']+=1;slot['remaining']-=1;save_budget(v)

def execute(variant,period,inputs,remote):
    s=verify_spec(inputs);out=ROOT/OUT/variant/period;at=read(out/'ATTEMPT.json')
    need(at['owner_run']==OWNER and at['variant']==variant and at['period']==period,'CLAIM_OWNER')
    need(at['spec_sha256']==h(ROOT/OUT/'SPEC.json'),'CLAIM_SPEC')
    # Receipt is emitted by root only after fetching the remote exact bytes.
    receipt=read(out/'REMOTE_READBACK.json')
    need(receipt['commit']==remote and receipt['attempt_sha256']==h(out/'ATTEMPT.json') and receipt['budget_sha256']==h(ROOT/OUT/'BUDGET.json'),'REMOTE_READBACK_BINDING')
    packet=gz(Path(inputs)/f'{period}.json.gz');shared.old.inherited.packet_check(period,packet)
    put(out/'EXECUTION_STARTED.json',dict(claim_commit=remote,remote_readback_sha=remote,owner_run=OWNER,time_ns=time.time_ns()))
    v=read(ROOT/OUT/'BUDGET.json');slot=v[KEY]
    need(at['ordinal']==v['cumulative_actual_evaluations']+1,'EVALUATION_COUNTER')
    candidate=next((x['ordinal'] for x in v['candidate_trials'] if x.get('scope')==SCOPE and x.get('candidate')==integration.engine.RULES[variant]),None)
    if candidate is None:
        need(sum(x.get('scope')==SCOPE for x in v['candidate_trials'])<5,'CANDIDATE_CAP')
        v['cumulative_actual']+=1;v['new_candidate_runs']+=1;candidate=v['cumulative_actual']
        v['candidate_trials'].append(dict(scope=SCOPE,candidate=integration.engine.RULES[variant],ordinal=candidate,first_evaluation=at['ordinal']))
    v['cumulative_actual_evaluations']+=1;slot['started']+=1
    v['trials'].append(dict(at,status='STARTED',candidate_ordinal=candidate,actual_experiment_ordinal=at['ordinal']));save_budget(v)
    try:
        raw,result,comp=integration.evaluate_one(variant,period,packet,s['periods'][period],baseline(period),volume_bindings=s['volume_bindings'])
        result.update(scope=SCOPE,period=period,spec_sha256=h(ROOT/OUT/'SPEC.json'))
        p.write_new(out/'RAW.json.gz',gzip.compress(p.canonical(raw),mtime=0))
        p.write_new(out/'RESULT.json.gz',gzip.compress(p.canonical(result),mtime=0))
        put(out/'ACCOUNTING_C54.json',comp)
        put(out/'RECEIPT.json',dict(status='COMPLETED',variant=variant,period=period,candidate_ordinal=candidate,
          result_sha256=h(out/'RESULT.json.gz'),raw_sha256=h(out/'RAW.json.gz'),spec_sha256=h(ROOT/OUT/'SPEC.json'),claim_commit=remote,metrics=a.snapshot(result)))
        slot['completed']+=1;v['trials'][-1]['status']='COMPLETED';save_budget(v)
        print(json.dumps(a.snapshot(result),sort_keys=True))
    except BaseException as exc:
        put(out/'FAILURE.json',dict(status='FAILED_CONSUMED',error=str(exc),traceback=traceback.format_exc(),retry=False))
        slot['failed']+=1;v['trials'][-1]['status']='FAILED_CONSUMED';save_budget(v);raise

if __name__=='__main__':
    q=argparse.ArgumentParser();q.add_argument('action',choices=['freeze','reserve','execute']);q.add_argument('--inputs');q.add_argument('--variant');q.add_argument('--period');q.add_argument('--remote-sha');x=q.parse_args()
    if x.action=='freeze':freeze(x.inputs)
    elif x.action=='reserve':reserve(x.variant,x.period)
    else:execute(x.variant,x.period,x.inputs,x.remote_sha)
