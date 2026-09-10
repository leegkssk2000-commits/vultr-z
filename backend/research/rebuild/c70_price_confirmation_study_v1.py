"""Finite successor: one new hypothesis, two native FULLs, no replayed parents.

Prior PR1243C70 and local alias C70 are different hypotheses. Preserve both,
append the local one as import71, then new candidate72/evaluations127-128.
"""
import argparse,gzip,json,math,os,subprocess,time,traceback
from copy import deepcopy
from unittest.mock import patch
from backend.research.rebuild import c63_daily_ema21_study_v1 as d
from backend.research.rebuild import c70_price_confirmation_v1 as child
ROOT=d.ROOT;p,a=d.p,d.a;read,gz,h,put,need=d.read,d.gz,d.h,d.put,d.need
SCOPE='C70_PRICE_CONFIRMATION_SUCCESSOR_V1';OUT='research/development_evidence/'+SCOPE
PERIODS=('DEV2025','SEEN2026');KEY='c70_price_confirmation_successor_allocation'
PREVIOUS='235445c114c89bed9fd5638ff3a0e3dc77932927'
PREVIOUS_HISTORY='research/development_evidence/C63_DAILY21_DEFERRED_RECLAIM_AFTER_PR1242_V1/BUDGET.json'
def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT,text=True,timeout=35).strip()
def save(b):
    target=ROOT/OUT/'BUDGET.json';temp=target.with_suffix('.pending')
    with temp.open('xb') as f:f.write(p.canonical(b));f.flush();os.fsync(f.fileno())
    os.replace(temp,target)
def controls(per,packet,cal):
    c63=gz(ROOT/d.prior.OUT/per/'RESULT.json.gz');c69=gz(ROOT/d.OUT/per/'RESULT.json.gz')
    meta=read(ROOT/OUT/'LOCAL_C70_IMPORT.json')['periods'][per]
    wanted={tuple(v) for v in meta['admitted']};old=deepcopy(c63)
    for k in ('trades','open_observations'):old[k]=[t for t in old[k] if (t['symbol'],t['signal_index'],t['signal_ts']) in wanted]
    need(sum(len(old[k]) for k in ('trades','open_observations'))==len(wanted),'LOCAL_IMPORT_ORIGINS')
    old['metrics']=p.old.metrics(old['trades'],old['open_observations'],cal,packet['rows_by'],packet['costs'])
    actual=a.snapshot(old)
    for k in ('closed','open','win_rate','average_win_bps','average_loss_bps','PF','realized_payoff','terminal_net_bps','terminal_cost2x_net_bps','marked_DD_trade_sum_bps'):
        x,y=actual[k],meta['snapshot'][k];need(x==y or math.isclose(x,y,rel_tol=1e-11,abs_tol=1e-7),'LOCAL_IMPORT_METRIC:'+k)
    return {'C63':c63,'C69':c69,'C70_LOCAL':old}
def pins():
    src=dict(read(ROOT/d.OUT/'SPEC.json')['source_files_sha256'])
    for name,value in src.items():need(h(ROOT/name)==value,'PARENT_SOURCE:'+name)
    for name in ('c70_price_confirmation_v1.py','c70_price_confirmation_study_v1.py','test_c70_price_confirmation_v1.py'):
        path='backend/research/rebuild/'+name;src[path]=h(ROOT/path)
    for name in ('DESIGN.md','SOURCE_TIP.json','LOCAL_C70_IMPORT.json'):src[OUT+'/'+name]=h(ROOT/OUT/name)
    return src
def freeze(inputs):
    need(os.environ.get('PRICE_PREFLIGHT')=='PASSED','FULL_CHECKOUT_PREFLIGHT')
    d.prior.verify_spec(inputs);old=read(ROOT/d.OUT/'SPEC.json')
    history_bytes=subprocess.check_output(['git','show',PREVIOUS+':'+PREVIOUS_HISTORY],cwd=ROOT,timeout=30)
    history=json.loads(history_bytes);need((history['cumulative_actual'],history['cumulative_actual_evaluations'])==(70,124),'PR1243_HISTORY')
    need(KEY not in history,'DUPLICATE_SCOPE')
    p.write_new(ROOT/OUT/'HISTORY_BEFORE_IMPORT.json',history_bytes)
    local=read(ROOT/OUT/'LOCAL_C70_IMPORT.json')
    need(local['original_ledger']['completed']==2 and local['original_ledger']['failed']==0,'LOCAL_IMPORT_INCOMPLETE')
    history['candidate_trials'].append(dict(candidate='C69_DAILY21_OR_NONFALLING_SMA5_STRICT_RANGE_ESCAPE_V1',ordinal=71,first_evaluation=125,scope=local['original_scope'],imported_from_local=True,original_provisional_ordinal=70,source_spec_sha256=local['original_spec_sha256']))
    for j,v in enumerate(local['original_ledger']['attempts']):history['trials'].append(dict(v,actual_experiment_ordinal=125+j,imported_from_local=True,source_local_evaluation=v['local_evaluation']))
    history['cumulative_actual']=71;history['cumulative_actual_evaluations']=126;history['new_candidate_runs']+=1
    history['c70local_price_context_import_sha256']=h(ROOT/OUT/'LOCAL_C70_IMPORT.json')
    history[KEY]=dict(max_candidates=1,max_executions=2,reserved=0,started=0,completed=0,failed=0,remaining=2,retry=False)
    proof={}
    for per in PERIODS:
        need(h(inputs/(per+'.json.gz'))==old['input_packet_sha256'][per],'INPUT_HASH')
        proof[per]={k:a.snapshot(v) for k,v in controls(per,gz(inputs/(per+'.json.gz')),old['periods'][per]).items()}
    put(ROOT/OUT/'IMPORT_ARITHMETIC.json',proof)
    put(ROOT/OUT/'SPEC.json',dict(scope=SCOPE,candidate=child.RULE_ID,candidate_ordinal=72,evaluation_ordinals=[127,128],max_candidates=1,max_FULL=2,source_files_sha256=pins(),periods=old['periods'],input_packet_sha256=old['input_packet_sha256'],prior_history_sha256=h(ROOT/OUT/'HISTORY_BEFORE_IMPORT.json'),prior_history_commit=PREVIOUS,local_import_sha256=h(ROOT/OUT/'LOCAL_C70_IMPORT.json'),code_commit=git('rev-parse','HEAD'),frozen_ns=time.time_ns(),rule='C63 eligible AND [C69 eligible OR (daily21 available AND close>SMA5 AND strict original squeeze-high breakout AND close>prior UTC session high)]. Prior session precedes SIGNAL BAR OPEN-DATE, not close-date. No slope, partial day, delay, new signal/exit/size/cost change.',objective='WR/net/cost2 up and dailyDD down in each original used period versus C63; C69/localC70 comparisons and all-winner/topdecile retention required. No post-outcome retune.',independent=False,formal_credit=0,selected_on_used_DEV=True,parent_strategy_replays=0,api_calls=0,market_requests=0,retry=False))
    put(ROOT/OUT/'BUDGET.json',history)
def check(inputs):
    s=read(ROOT/OUT/'SPEC.json');need(s['source_files_sha256']==pins(),'FROZEN_SOURCE_CHANGED')
    need(s['prior_history_sha256']==h(ROOT/OUT/'HISTORY_BEFORE_IMPORT.json'),'HISTORY_CHANGED')
    for per,value in s['input_packet_sha256'].items():need(h(inputs/(per+'.json.gz'))==value,'INPUT_CHANGED')
    return s
def reserve(per,inputs):
    s=check(inputs);j=PERIODS.index(per);b=read(ROOT/OUT/'BUDGET.json');q=b[KEY]
    need(os.environ.get('GITHUB_RUN_ATTEMPT')=='1','NO_RETRY')
    need(q['reserved']==q['started']==q['completed']==j and q['failed']==0,'PRIOR_UNRESOLVED_OR_DUPLICATE')
    put(ROOT/OUT/per/'ATTEMPT.json',dict(scope=SCOPE,period=per,candidate_ordinal=72,ordinal=127+j,owner_run=os.environ['GITHUB_RUN_ID'],status='RESERVED_NOT_STARTED',spec_sha256=h(ROOT/OUT/'SPEC.json'),time_ns=time.time_ns()))
    q['reserved']+=1;q['remaining']-=1;save(b)
def execute(per,inputs,remote):
    s=check(inputs);j=PERIODS.index(per);folder=ROOT/OUT/per;at=read(folder/'ATTEMPT.json');head=git('rev-parse','HEAD')
    need(head==remote and at['owner_run']==os.environ['GITHUB_RUN_ID'] and os.environ.get('GITHUB_RUN_ATTEMPT')=='1','CLAIM_OWNER')
    need(subprocess.check_output(['git','show',head+':'+OUT+'/'+per+'/ATTEMPT.json'],cwd=ROOT)==(folder/'ATTEMPT.json').read_bytes(),'UNCOMMITTED_CLAIM')
    b=read(ROOT/OUT/'BUDGET.json');q=b[KEY];need(q['reserved']==j+1 and q['started']==q['completed']==j and not q['failed'],'NO_REPEAT')
    need(b['cumulative_actual_evaluations']==126+j,'ORDINAL')
    packet=gz(inputs/(per+'.json.gz'));d.prior.previous.shared.old.inherited.packet_check(per,packet);cal=s['periods'][per]
    put(folder/'EXECUTION_STARTED.json',dict(claim_commit=head,remote_readback_sha=remote,owner_run=at['owner_run'],time_ns=time.time_ns()))
    if j==0:
        need(b['cumulative_actual']==71,'CANDIDATE_COUNT');b['cumulative_actual']+=1;b['new_candidate_runs']+=1
        b['candidate_trials'].append(dict(candidate=child.RULE_ID,ordinal=72,first_evaluation=127,scope=SCOPE))
    b['cumulative_actual_evaluations']+=1;q['started']+=1;b['trials'].append(dict(at,actual_experiment_ordinal=127+j,status='STARTED'));save(b)
    try:
        with p.native.sensitivity():raw={sym:child.replay(rows,eval_start_ms=cal['start_ms'],eval_end_ms=cal['runoff_end_ms']) for sym,rows in sorted(packet['rows_by'].items())}
        with patch.dict(d.prior.previous.integration.engine.RULES,{'M1':child.RULE_ID}):result=d.prior.previous.integration.charge_and_mark(raw,'M1',packet,cal)
        result.update(scope=SCOPE,period=per,spec_sha256=h(ROOT/OUT/'SPEC.json'),direct_parent='C70_LOCAL')
        ctrl=controls(per,packet,cal);key=lambda e:(e['symbol'],e['signal_index'],e['signal_ts'])
        need({key(e) for e in result['events']}=={key(e) for e in ctrl['C63']['events']},'ORIGINAL_SIGNAL_POOL')
        for name,obj in [('RAW.json.gz',raw),('RESULT.json.gz',result)]:p.write_new(folder/name,gzip.compress(p.canonical(obj),mtime=0))
        for label in ('C63','C69'):put(folder/('ACCOUNTING_'+label+'.json'),a.compare(ctrl[label],result))
        put(folder/'RECEIPT.json',dict(status='COMPLETED',period=per,candidate_ordinal=72,raw_sha256=h(folder/'RAW.json.gz'),result_sha256=h(folder/'RESULT.json.gz'),spec_sha256=h(ROOT/OUT/'SPEC.json'),claim_commit=head,metrics=a.snapshot(result)))
        q['completed']+=1;b['trials'][-1]['status']='COMPLETED';save(b);print(json.dumps(a.snapshot(result)))
    except BaseException as exc:
        put(folder/'FAILURE.json',dict(status='FAILED_CONSUMED',error=str(exc),traceback=traceback.format_exc(),retry=False));q['failed']+=1;b['trials'][-1]['status']='FAILED_CONSUMED';save(b);raise
def summarize(inputs):
    check(inputs);data={}
    for per in PERIODS:
        result=gz(ROOT/OUT/per/'RESULT.json.gz');snap=read(ROOT/OUT/'IMPORT_ARITHMETIC.json')[per];snap['C72']=a.snapshot(result)
        data[per]=dict(snapshots=snap,checks={name:d.prior.previous.checks(s,snap['C72']) for name,s in snap.items() if name!='C72'})
    goal=all(all(x['checks']['C63'].values()) for x in data.values());gain=all(x['checks']['C63']['net_up'] and x['checks']['C63']['cost2_up'] for x in data.values())
    status='DEVELOPMENT_GOAL_MET' if goal else 'PARTIAL_IMPROVEMENT' if gain else 'REJECT_KEEP_C63'
    put(ROOT/OUT/'SUMMARY.json',dict(status=status,periods=data,candidates=72,evaluations=128,new_candidates=1,new_FULL=2,imported_local_candidates=1,imported_local_evaluations=2,parent_replays=0,formal_credit=0,independent=False,report_only=True,further_dispatch_allowed=False))
    put(ROOT/OUT/'EVIDENCE_HASHES.json',{str(x.relative_to(ROOT/OUT)):h(x) for x in (ROOT/OUT).rglob('*') if x.is_file() and x.name!='EVIDENCE_HASHES.json'})
    print(json.dumps(read(ROOT/OUT/'SUMMARY.json'),indent=2))
if __name__=='__main__':
    from pathlib import Path
    q=argparse.ArgumentParser();q.add_argument('action',choices=['freeze','reserve','execute','summarize']);q.add_argument('--inputs',type=Path,required=True);q.add_argument('--period',choices=PERIODS);q.add_argument('--remote');v=q.parse_args()
    if v.action=='freeze':freeze(v.inputs)
    elif v.action=='reserve':reserve(v.period,v.inputs)
    elif v.action=='execute':execute(v.period,v.inputs,v.remote)
    else:summarize(v.inputs)
