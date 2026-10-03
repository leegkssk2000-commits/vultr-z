"""One public-tip candidate and two first FULLs. No parent/candidate repeat."""
import argparse,gzip,json,os,subprocess,time,traceback,math
from copy import deepcopy
from unittest.mock import patch
from backend.research.rebuild import m1_er_range_rescue_study_v1 as prior
from backend.research.rebuild import c63_daily21_deferred_v1 as child
ROOT=prior.ROOT;p,a=prior.p,prior.a
read,gz,h,put,need=prior.read,prior.gz,prior.h,prior.put,prior.need
SCOPE='C63_DAILY21_DEFERRED_RECLAIM_AFTER_PR1242_V1';OUT='research/development_evidence/'+SCOPE
INPUTS='research/development_evidence/TOP5_SOURCE_CHART_MECHANISMS_AFTER_PR1228_V1/INPUTS'
COMPARATOR='research/development_evidence/C63_DAILY_EMA21_HORTON_TIP_AFTER_PR1241_V1'
HISTORY=COMPARATOR+'/BUDGET.json'
KEY='c63_daily21_deferred_allocation';PERIODS=('DEV2025','SEEN2026')

def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT,text=True,timeout=30).strip()
def budget_write(value):
    path=ROOT/OUT/'BUDGET.json';temp=path.with_suffix('.pending')
    with temp.open('xb') as f:f.write(p.canonical(value));f.flush();os.fsync(f.fileno())
    os.replace(temp,path)
def sources():
    result=dict(read(ROOT/COMPARATOR/'SPEC.json')['source_files_sha256'])
    for name,d in result.items():need(h(ROOT/name)==d,'C63_SOURCE_DRIFT:'+name)
    for name in ('c63_daily21_deferred_v1.py','test_c63_daily21_deferred_v1.py','c63_daily21_deferred_study_v1.py'):
        path='backend/research/rebuild/'+name;result[path]=h(ROOT/path)
    for name in ('DESIGN.md','SOURCE_TIP.json'):result[OUT+'/'+name]=h(ROOT/OUT/name)
    return result

def freeze():
    need(os.environ.get('DEFERRED_PREFLIGHT')=='PASSED','FULL_CHECKOUT_PREFLIGHT_REQUIRED')
    prior.verify_spec(ROOT/INPUTS);previous=read(ROOT/prior.OUT/'SPEC.json')
    data=(ROOT/HISTORY).read_bytes();history=json.loads(data)
    need((history['cumulative_actual'],history['cumulative_actual_evaluations'])==(69,122),'HISTORY_NOT69_122')
    need(KEY not in history and history['chart_allocation']['remaining']==6,'DUPLICATE_OR_OLD_SLOTS')
    p.write_new(ROOT/OUT/'HISTORY_PRIOR.json',data)
    spec=dict(scope=SCOPE,candidate=child.RULE_ID,direct_parent=child.parent.RULE_ID,candidate_ordinal=70,evaluation_ordinals=[123,124],max_candidates=1,max_FULL=2,parent_replays=0,fixed_replays=0,
        source_files_sha256=sources(),periods=previous['periods'],input_packet_sha256=previous['input_packet_sha256'],history_path=HISTORY,history_sha256=h(ROOT/OUT/'HISTORY_PRIOR.json'),
        parent_results_sha256={per:{n:h(ROOT/prior.OUT/per/n) for n in ('RAW.json.gz','RESULT.json.gz')} for per in PERIODS},parent_spec_sha256=h(ROOT/prior.OUT/'SPEC.json'),
        comparator_sha256={per:h(ROOT/COMPARATOR/per/'RESULT.json.gz') for per in PERIODS},
        rule='C63 signal qualified once at origin; completed daily21 history required. Already above => original next open. Otherwise pending, native original-open gap must pass. Later closes cancel first on floor/momentum/original20bar clock or a new native raw signal. First valid above-daily21 close => next observed open subject to native gap/window. Original floor/exit priority/20bar total clock retained; waiting does not reset clock. No pending exposure, retry, year/symbol exception or invented EMA fill.',
        code_commit=git('rev-parse','HEAD'),frozen_ns=time.time_ns(),independent=False,formal_credit=0,source_replication=False,objective='Each original used period: WR/net/cost2 up and daily markedDD down, unchanged numeric tolerance. Inherited winner/concentration/risk reporting. No trader account evidence needed or claimed.',retry=False,api_calls=0,market_requests=0,unused_OOS=0,orders=0,selected_on_used_DEV=True)
    put(ROOT/OUT/'SPEC.json',spec)
    history[KEY]=dict(max_candidates=1,max_executions=2,reserved=0,started=0,completed=0,failed=0,remaining=2,retry=False)
    put(ROOT/OUT/'BUDGET.json',history)

def check():
    s=read(ROOT/OUT/'SPEC.json');need(s['source_files_sha256']==sources(),'SOURCE_CHANGED')
    need(h(ROOT/OUT/'HISTORY_PRIOR.json')==s['history_sha256']==h(ROOT/HISTORY),'HISTORY_CHANGED')
    for per,d in s['input_packet_sha256'].items():need(h(ROOT/INPUTS/(per+'.json.gz'))==d,'INPUT_CHANGED')
    for per,files in s['parent_results_sha256'].items():
        for name,d in files.items():need(h(ROOT/prior.OUT/per/name)==d,'PARENT_CHANGED')
    for per,d in s['comparator_sha256'].items():need(h(ROOT/COMPARATOR/per/'RESULT.json.gz')==d,'C69_CHANGED')
    return s

def reserve(per):
    check();j=PERIODS.index(per);b=read(ROOT/OUT/'BUDGET.json');q=b[KEY]
    need(q['reserved']==q['started']==q['completed']==j and q['failed']==0,'ALREADY_RESERVED_OR_INCOMPLETE')
    need(os.environ.get('GITHUB_RUN_ATTEMPT')=='1','NO_RETRY')
    put(ROOT/OUT/per/'ATTEMPT.json',dict(scope=SCOPE,period=per,ordinal=123+j,candidate_ordinal=70,status='RESERVED_NOT_STARTED',owner_run=os.environ['GITHUB_RUN_ID'],spec_sha256=h(ROOT/OUT/'SPEC.json'),time_ns=time.time_ns()))
    q['reserved']+=1;q['remaining']-=1;budget_write(b)

def execute(per,remote):
    s=check();j=PERIODS.index(per);folder=ROOT/OUT/per;at=read(folder/'ATTEMPT.json');head=git('rev-parse','HEAD')
    need(head==remote and at['owner_run']==os.environ['GITHUB_RUN_ID'] and os.environ.get('GITHUB_RUN_ATTEMPT')=='1','REMOTE_OWNER')
    need(subprocess.check_output(['git','show',head+':'+OUT+'/'+per+'/ATTEMPT.json'],cwd=ROOT)==(folder/'ATTEMPT.json').read_bytes(),'UNCOMMITTED_CLAIM')
    b=read(ROOT/OUT/'BUDGET.json');q=b[KEY]
    need(q['reserved']==j+1 and q['started']==q['completed']==j and q['failed']==0,'NO_RETRY_STARTED')
    need(b['cumulative_actual_evaluations']==122+j,'ORDINAL')
    packet=gz(ROOT/INPUTS/(per+'.json.gz'));prior.previous.shared.old.inherited.packet_check(per,packet);cal=s['periods'][per]
    put(folder/'EXECUTION_STARTED.json',dict(claim_commit=head,remote_readback_sha=remote,owner_run=at['owner_run'],time_ns=time.time_ns()))
    if j==0:
        need(b['cumulative_actual']==69,'CANDIDATE_ORDINAL');b['cumulative_actual']+=1;b['new_candidate_runs']+=1
        b['candidate_trials'].append(dict(candidate=child.RULE_ID,ordinal=70,first_evaluation=123,scope=SCOPE))
    b['cumulative_actual_evaluations']+=1;q['started']+=1;b['trials'].append(dict(at,actual_experiment_ordinal=123+j,status='STARTED'));budget_write(b)
    try:
        with p.native.sensitivity():raw={sym:child.replay(rows,eval_start_ms=cal['start_ms'],eval_end_ms=cal['runoff_end_ms']) for sym,rows in sorted(packet['rows_by'].items())}
        with patch.dict(prior.previous.integration.engine.RULES,{'M1':child.RULE_ID}):result=prior.previous.integration.charge_and_mark(raw,'M1',packet,cal)
        result.update(scope=SCOPE,period=per,spec_sha256=h(ROOT/OUT/'SPEC.json'),direct_parent='C63')
        parent=gz(ROOT/prior.OUT/per/'RESULT.json.gz');key=lambda e:(e['symbol'],e['signal_index'],e['signal_ts'])
        need({key(e) for e in parent['events']}=={key(e) for e in result['events']},'C63_ORIGINAL_SIGNAL_POOL')
        for n,obj in [('RAW.json.gz',raw),('RESULT.json.gz',result)]:p.write_new(folder/n,gzip.compress(p.canonical(obj),mtime=0))
        put(folder/'ACCOUNTING_C63.json',a.compare(parent,result))
        put(folder/'ACCOUNTING_C69.json',a.compare(gz(ROOT/COMPARATOR/per/'RESULT.json.gz'),result))
        put(folder/'RECEIPT.json',dict(status='COMPLETED',period=per,candidate_ordinal=70,raw_sha256=h(folder/'RAW.json.gz'),result_sha256=h(folder/'RESULT.json.gz'),spec_sha256=h(ROOT/OUT/'SPEC.json'),claim_commit=head,metrics=a.snapshot(result)))
        q['completed']+=1;b['trials'][-1]['status']='COMPLETED';budget_write(b);print(json.dumps(a.snapshot(result)))
    except BaseException as exc:
        put(folder/'FAILURE.json',dict(error=str(exc),type=type(exc).__name__,traceback=traceback.format_exc(),status='FAILED_CONSUMED',retry=False))
        q['failed']+=1;b['trials'][-1]['status']='FAILED_CONSUMED';budget_write(b);raise

def summarize():
    check();data={};lines=['# C63 / C69 / deferred daily21 confirmation — USED_DEV','',
        'One finite pending-entry adaptation, not Horton Big3 replication. Fixed notional trade-bps with modeled costs/open marks, not account performance. First two FULLs, no parent/comparator repeats.','',
        '|Period|Rule|Closed/open|WR%|Mean win|Mean loss|PF|Payoff|Terminal net|Cost2|Daily DD|',
        '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for per in PERIODS:
        par=gz(ROOT/prior.OUT/per/'RESULT.json.gz');res=gz(ROOT/OUT/per/'RESULT.json.gz');snap={k:a.snapshot(v) for k,v in [('C63',par),('C69',gz(ROOT/COMPARATOR/per/'RESULT.json.gz')),('C70',res)]}
        data[per]=dict(snapshots=snap,checks=prior.previous.checks(snap['C63'],snap['C70']),accounting=read(ROOT/OUT/per/'ACCOUNTING_C63.json'),
            accounting_C69=read(ROOT/OUT/per/'ACCOUNTING_C69.json'),
            history_unavailable_signal_T=sum(e['initial_daily_context']['value'] is None for e in res['events']),
            actual_history_unavailable_veto_T=sum(e['exclusion_reason']==child.daily.MISSING for e in res['events']),
            deferred_admitted_T=sum(e['admission'] and e['wait_bars']>0 for e in res['events']),
            pending_terminal_T=sum(len(v) for v in res.get('pending_entries',{}).values()))
        for label,m in snap.items():
            fmt=lambda v:'NA' if v is None else f'{v:.2f}'
            lines.append('|'+ '|'.join([per,label,f"{m['closed']}/{m['open']}",fmt(None if m['win_rate'] is None else m['win_rate']*100)]+[fmt(m[k]) for k in ('average_win_bps','average_loss_bps','PF','realized_payoff','terminal_net_bps','terminal_cost2x_net_bps','marked_DD_trade_sum_bps')])+'|')
    goal=all(all(v['checks'].values()) for v in data.values());gain=all(v['checks']['net_up'] and v['checks']['cost2_up'] for v in data.values());status='DEVELOPMENT_GOAL_MET' if goal else 'PARTIAL_IMPROVEMENT' if gain else 'REJECT_KEEP_C63'
    put(ROOT/OUT/'SUMMARY.json',dict(status=status,periods=data,candidates=70,evaluations=124,new_candidates=1,new_FULL=2,new_FIXED=0,parent_replay=0,independent=False,formal_credit=0))
    lines+=['',status,'','Original C63 baseline and C69 rejection are preserved. Pending and held time share original20bars. Missing warmup/pending/open states separate. Judgment closes THIS exact hypothesis only; no automatic next candidate or formal credit.',''];(ROOT/OUT/'REPORT.md').write_text('\n'.join(lines));print('\n'.join(lines))
    put(ROOT/OUT/'EVIDENCE_HASHES.json',{str(x.relative_to(ROOT/OUT)):h(x) for x in (ROOT/OUT).rglob('*') if x.is_file() and x.name!='EVIDENCE_HASHES.json'})
if __name__=='__main__':
    q=argparse.ArgumentParser();q.add_argument('action',choices=['freeze','reserve','execute','summarize']);q.add_argument('--period',choices=PERIODS);q.add_argument('--remote');x=q.parse_args()
    if x.action=='freeze':freeze()
    elif x.action=='reserve':reserve(x.period)
    elif x.action=='execute':execute(x.period,x.remote)
    else:summarize()
