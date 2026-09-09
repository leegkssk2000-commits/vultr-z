"""One approved M1 entry child / two serial first FULLs. No automatic retries."""
import argparse,gzip,json,math,os,subprocess,time,traceback
from pathlib import Path
from unittest.mock import patch
from backend.research.rebuild import kr3_c51_entry_context_study_v1 as shared
from backend.research.rebuild import chart_mechanism_integration_v1 as integration
from backend.research.rebuild import m1_er14_entry_v1 as child
p,a,ROOT=shared.p,shared.a,shared.ROOT
OLD='research/development_evidence/TOP5_SOURCE_CHART_MECHANISMS_AFTER_PR1228_V1'
PRIOR='research/development_evidence/C54_PRICE_RETRACEMENT_M1_DIAG_AFTER_PR1230_V1'
SCOPE='M1_ER14_ENTRY_AFTER_PR1231_V1'
OUT='research/development_evidence/'+SCOPE
KEY='m1_er14_entry_allocation'
PERIODS=shared.old.PERIODS
read,gz,h,need,put=shared.read,shared.gz,shared.h,shared.need,shared.put

def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT,text=True).strip()
def baseline(per):return gz(ROOT/OLD/'M1'/per/'RESULT.json.gz')
def save_budget(value):
    target=ROOT/OUT/'BUDGET.json';tmp=target.with_suffix('.pending')
    with tmp.open('xb') as f:f.write(p.canonical(value));f.flush();os.fsync(f.fileno())
    os.replace(tmp,target)
def dependencies():
    src=dict(read(ROOT/PRIOR/'SPEC.json')['source_files_sha256'])
    for name,digest in src.items():need(h(ROOT/name)==digest,'PRIOR_FROZEN_SOURCE_DRIFT:'+name)
    for name in ('m1_er14_entry_v1.py','test_m1_er14_entry_v1.py','m1_er14_study_v1.py'):
        key='backend/research/rebuild/'+name;src[key]=h(ROOT/key)
    key=OUT+'/DESIGN.md';src[key]=h(ROOT/key)
    return src

def freeze(inputs):
    prior=read(ROOT/PRIOR/'SPEC.json');budget=read(ROOT/PRIOR/'BUDGET.json')
    need((budget['cumulative_actual'],budget['cumulative_actual_evaluations'])==(61,102),'LATEST_LEDGER_NOT61_102')
    need(KEY not in budget,'DUPLICATE_SCOPE')
    for per,digest in prior['input_packet_sha256'].items():
        need(h(Path(inputs)/f'{per}.json.gz')==digest,'ORIGINAL_PACKET_BYTES')
        shared.old.inherited.packet_check(per,gz(Path(inputs)/f'{per}.json.gz'))
    spec=dict(scope=SCOPE,rule=child.RULE_ID,direct_parent=child.parent.RULES['M1'],candidate_ordinal=62,evaluation_ordinals=[103,104],
        periods=prior['periods'],input_packet_sha256=prior['input_packet_sha256'],source_files_sha256=dependencies(),
        prior_budget_sha256=h(ROOT/PRIOR/'BUDGET.json'),prior_spec_sha256=h(ROOT/PRIOR/'SPEC.json'),
        parent_results_sha256={per:{name:h(ROOT/OLD/'M1'/per/name) for name in ('RAW.json.gz','RESULT.json.gz')} for per in PERIODS},
        saved_c54_sha256=prior['parent_results_sha256'],max_candidates=1,max_full=2,retry=False,
        rule_text='Original M1 long release AND ER14(signal)>ER14(previous). abs(Ci-Ci-14)/fsum(abs(Cj-Cj-1)) over14changes. Zero path ER0; missing history unavailable; ties veto. No absolute cutoff, opposite rule or alternate N.',
        unchanged=['M1_original_signal','next_open_entry','fixed_floor','momentum_nonpositive_exit','20bar_exit','costs','sizing','actual_occupancy_convention'],
        objective='Compared directly with saved M1: each period WR/net/cost2 up, markedDD down. Numeric equality not improvement. C54 a separate unchanged control only.',
        independent=False,formal_credit=0,market_requests=0,unused_oos=0,paid_ai=0,orders=0,parent_replay=0,
        code_commit=git('rev-parse','HEAD'),frozen_ns=time.time_ns())
    put(ROOT/OUT/'SPEC.json',spec)
    budget[KEY]=dict(max_candidates=1,max_executions=2,reserved=0,started=0,completed=0,failed=0,remaining=2,retry=False)
    put(ROOT/OUT/'BUDGET.json',budget)

def verify_spec(inputs=None):
    spec=read(ROOT/OUT/'SPEC.json');need(spec['source_files_sha256']==dependencies(),'FROZEN_SOURCE_CHANGED')
    need(spec['prior_budget_sha256']==h(ROOT/PRIOR/'BUDGET.json') and spec['prior_spec_sha256']==h(ROOT/PRIOR/'SPEC.json'),'PRIOR_CHANGED')
    for per,files in spec['parent_results_sha256'].items():
        for name,digest in files.items():need(h(ROOT/OLD/'M1'/per/name)==digest,'ORIGINAL_M1_CHANGED')
    for per,digest in spec['saved_c54_sha256'].items():need(h(ROOT/shared.OUT/'B'/per/'RESULT.json.gz')==digest,'C54_CHANGED')
    if inputs:
        for per,digest in spec['input_packet_sha256'].items():need(h(Path(inputs)/f'{per}.json.gz')==digest,'ORIGINAL_INPUT_CHANGED')
    return spec

def applicability(inputs):
    # Frozen rule on saved original signals, with no outcomes read for selection.
    spec=verify_spec(inputs);answer={};total=0
    for per in PERIODS:
        packet=gz(Path(inputs)/f'{per}.json.gz');cal=spec['periods'][per];saved=baseline(per)
        bars={symbol:child.parent.to_bars(rows,cal['start_ms'],cal['runoff_end_ms']) for symbol,rows in packet['rows_by'].items()}
        records=[dict(symbol=e['symbol'],signal_index=e['signal_index'],context=child.context(bars[e['symbol']],e['signal_index'])) for e in saved['events']]
        veto=sum(not r['context']['eligible'] for r in records)
        changed=sum(bool(e['admission']) and not r['context']['eligible'] for e,r in zip(saved['events'],records));total+=changed
        answer[per]=dict(raw_signals=len(records),eligible=len(records)-veto,veto=veto,original_admissions_vetoed=changed,records=records,input_packet_sha256=spec['input_packet_sha256'][per])
    put(ROOT/OUT/'APPLICABILITY.json',dict(periods=answer,any_changed=total>0,economic_replay=0,rule_frozen_before_features=True))
    if not total:
        put(ROOT/OUT/'NOT_RUN.json',dict(status='NOT_RUN_REDUNDANT_ON_ALL_ORIGINAL_SIGNALS',consumed=0))
    print('ER_ELIGIBILITY_CHANGED' if total else 'NOT_RUN_REDUNDANT')

def reserve(per):
    spec=verify_spec();j=PERIODS.index(per);budget=read(ROOT/OUT/'BUDGET.json');slot=budget[KEY]
    need(read(ROOT/OUT/'APPLICABILITY.json')['any_changed'],'REDUNDANT_RULE_NO_ECONOMICS')
    need(slot['reserved']==slot['completed']==j and slot['failed']==0,'DUPLICATE_OR_PREVIOUS_UNRESOLVED')
    need(os.environ.get('GITHUB_RUN_ATTEMPT')=='1','NO_RETRY')
    at=dict(scope=SCOPE,period=per,candidate_ordinal=62,ordinal=103+j,owner_run=os.environ['GITHUB_RUN_ID'],spec_sha256=h(ROOT/OUT/'SPEC.json'),status='RESERVED_NOT_STARTED',time_ns=time.time_ns())
    put(ROOT/OUT/per/'ATTEMPT.json',at);slot['reserved']+=1;slot['remaining']-=1;save_budget(budget)

def execute(per,inputs,remote):
    spec=verify_spec(inputs);j=PERIODS.index(per);out=ROOT/OUT/per;at=read(out/'ATTEMPT.json');head=git('rev-parse','HEAD')
    need(head==remote and at['owner_run']==os.environ['GITHUB_RUN_ID'],'RUNTIME_CLAIM_OR_OWNER')
    need(os.environ.get('GITHUB_RUN_ATTEMPT')=='1' and at['spec_sha256']==h(ROOT/OUT/'SPEC.json'),'NO_RETRY_OR_SPEC')
    need(subprocess.check_output(['git','show',head+':'+str((out/'ATTEMPT.json').relative_to(ROOT))],cwd=ROOT)==(out/'ATTEMPT.json').read_bytes(),'UNCOMMITTED_CLAIM')
    budget=read(ROOT/OUT/'BUDGET.json');slot=budget[KEY]
    need(slot['reserved']==j+1 and slot['started']==slot['completed']==j and slot['failed']==0,'ALREADY_STARTED')
    need(budget['cumulative_actual_evaluations']==102+j,'EVALUATION_COUNT')
    packet=gz(Path(inputs)/f'{per}.json.gz');shared.old.inherited.packet_check(per,packet);cal=spec['periods'][per]
    put(out/'EXECUTION_STARTED.json',dict(claim_commit=head,remote_readback_sha=remote,time_ns=time.time_ns(),owner_run=at['owner_run']))
    if j==0:
        need(budget['cumulative_actual']==61,'CANDIDATE_COUNT');budget['cumulative_actual']+=1;budget['new_candidate_runs']+=1
        budget['candidate_trials'].append(dict(scope=SCOPE,candidate=child.RULE_ID,ordinal=62,first_evaluation=103))
    budget['cumulative_actual_evaluations']+=1;slot['started']+=1;budget['trials'].append(dict(at,status='STARTED',actual_experiment_ordinal=103+j));save_budget(budget)
    try:
        with p.native.sensitivity():
            raw={symbol:child.replay(rows,eval_start_ms=cal['start_ms'],eval_end_ms=cal['runoff_end_ms']) for symbol,rows in sorted(packet['rows_by'].items())}
        with patch.dict(integration.engine.RULES,{'M1':child.RULE_ID}):result=integration.charge_and_mark(raw,'M1',packet,cal)
        result.update(scope=SCOPE,period=per,spec_sha256=h(ROOT/OUT/'SPEC.json'),direct_parent=spec['direct_parent'])
        parent=baseline(per);key=lambda e:(e['symbol'],e['signal_index'],e['signal_ts'])
        need({key(e) for e in parent['events']}=={key(e) for e in result['events']},'ORIGINAL_SIGNAL_POOL_CHANGED')
        comparison=a.compare(parent,result);comparison['comparison_type']='SQUEEZE_M1_ER14_ENTRY_FULL'
        p.write_new(out/'RAW.json.gz',gzip.compress(p.canonical(raw),mtime=0));p.write_new(out/'RESULT.json.gz',gzip.compress(p.canonical(result),mtime=0))
        put(out/'ACCOUNTING_M1.json',comparison)
        put(out/'RECEIPT.json',dict(status='COMPLETED',period=per,candidate_ordinal=62,result_sha256=h(out/'RESULT.json.gz'),raw_sha256=h(out/'RAW.json.gz'),spec_sha256=h(ROOT/OUT/'SPEC.json'),claim_commit=head,metrics=a.snapshot(result)))
        slot['completed']+=1;budget['trials'][-1]['status']='COMPLETED';save_budget(budget);print(json.dumps(a.snapshot(result)))
    except BaseException as exc:
        put(out/'FAILURE.json',dict(status='FAILED_CONSUMED',error=str(exc),traceback=traceback.format_exc(),retry=False))
        slot['failed']+=1;budget['trials'][-1]['status']='FAILED_CONSUMED';save_budget(budget);raise

def checks(parent,child):
    def up(x,y):return x is not None and y is not None and x>y and not math.isclose(x,y,rel_tol=1e-11,abs_tol=1e-7)
    return dict(WR_up=up(child['win_rate'],parent['win_rate']),net_up=up(child['terminal_net_bps'],parent['terminal_net_bps']),cost2_up=up(child['terminal_cost2x_net_bps'],parent['terminal_cost2x_net_bps']),DD_down=up(parent['marked_DD_trade_sum_bps'],child['marked_DD_trade_sum_bps']))

def summarize():
    verify_spec();data={};lines=['# M1 ER14-increase entry comparison','',
      'Direct parent is original Squeeze M1, not C54. Same nominal trade-bps including unchanged open-mark convention; USED_DEV, not account return or G5.',
      '', '|Period|Strategy|Closed/open|WR%|Mean win|Mean loss|Payoff|PF|Terminal net|All-cost2|Daily DD|',
      '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for per in PERIODS:
        ps=a.snapshot(baseline(per));cs=a.snapshot(gz(ROOT/OUT/per/'RESULT.json.gz'));data[per]=dict(parent=ps,child=cs,checks=checks(ps,cs),accounting=read(ROOT/OUT/per/'ACCOUNTING_M1.json'))
        for label,s in [('M1',ps),('ER14',cs)]:
            fmt=lambda x:'NA' if x is None else f'{x:.2f}'
            lines.append('|'+ '|'.join([per,label,f"{s['closed']}/{s['open']}",fmt(None if s['win_rate'] is None else 100*s['win_rate'])]+[fmt(s[k]) for k in ('average_win_bps','average_loss_bps','realized_payoff','PF','terminal_net_bps','terminal_cost2x_net_bps','marked_DD_trade_sum_bps')])+'|')
    goal=all(all(x['checks'].values()) for x in data.values());gain=all(x['checks']['net_up'] and x['checks']['cost2_up'] for x in data.values())
    status='DEVELOPMENT_GOAL_MET' if goal else 'PARTIAL_IMPROVEMENT' if gain else 'REJECT_KEEP_M1_AND_C54'
    put(ROOT/OUT/'SUMMARY.json',dict(status=status,periods=data,candidates=62,evaluations=104,new_candidates=1,new_full=2,parent_replay=0,formal_credit=0,independent=False))
    lines+=['',status,'','No cutoffs, opposite rule, extra period or post-outcome candidate tested. C54 and original M1 remain preserved. Original AVWAP6unused slots unchanged. Full gain/harm and new/removed/open origin groups are in ACCOUNTING_M1.','']
    (ROOT/OUT/'REPORT.md').write_text('\n'.join(lines));print('\n'.join(lines))

if __name__=='__main__':
    q=argparse.ArgumentParser();q.add_argument('action',choices=['freeze','applicability','reserve','execute','summarize']);q.add_argument('--inputs');q.add_argument('--period',choices=PERIODS);q.add_argument('--remote-sha');x=q.parse_args()
    if x.action=='freeze':freeze(x.inputs)
    elif x.action=='applicability':applicability(x.inputs)
    elif x.action=='reserve':reserve(x.period)
    elif x.action=='execute':execute(x.period,x.inputs,x.remote_sha)
    else:summarize()
