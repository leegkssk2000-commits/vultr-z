"""One authorized 2-component factorial: G, R, GR; six first native FULLs.

Old 72/128 history is copied unchanged before appending 73-75 / 129-134.
Parents are read, never replayed. No market/provider requests or live changes.
Every attempt must be committed and remotely read back before its execution.
"""
import argparse, gzip, hashlib, json, math, os, subprocess, time, traceback
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from backend.research.rebuild import c63_daily_ema21_study_v1 as d
from backend.research.rebuild import c63_transplant_v1 as child
ROOT=d.ROOT; p,a=d.p,d.a
read,gz,h,put,need=d.read,d.gz,d.h,d.put,d.need
SCOPE='C63_CUMULATIVE_TRANSPLANT_AFTER_PR1244_V1'
OUT='research/development_evidence/'+SCOPE
OLD='research/development_evidence/C70_PRICE_CONFIRMATION_SUCCESSOR_V1'
INPUTS=d.INPUTS
PERIODS=('DEV2025','SEEN2026')
VARIANTS=child.VARIANTS
KEY='c63_transplant_after_pr1244_allocation'
PLAN=[(v,per) for v in VARIANTS for per in PERIODS]

def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT,text=True,timeout=45).strip()
def atomic(path,value):
    path=Path(path);tmp=path.with_suffix('.pending')
    with tmp.open('xb') as f:f.write(p.canonical(value));f.flush();os.fsync(f.fileno())
    os.replace(tmp,path)
def sources():
    result=d.sources()
    for name in ('c63_transplant_v1.py','test_c63_transplant_v1.py','c63_transplant_study_v1.py'):
        name='backend/research/rebuild/'+name;result[name]=h(ROOT/name)
    result[OUT+'/DESIGN.md']=h(ROOT/OUT/'DESIGN.md')
    return result

def freeze():
    need(os.environ.get('TRANSPLANT_PREFLIGHT')=='PASSED','FULL_CHECKOUT_PREFLIGHT')
    d.prior.verify_spec(ROOT/INPUTS)
    prior=read(ROOT/d.OUT/'SPEC.json')
    data=(ROOT/OLD/'BUDGET.json').read_bytes();b=json.loads(data)
    need((b['cumulative_actual'],b['cumulative_actual_evaluations'])==(72,128),'HISTORY_NOT72_128')
    need(KEY not in b,'DUPLICATE_ALLOCATION')
    need(os.environ.get('GITHUB_RUN_ATTEMPT')=='1','NO_RETRY')
    need(not (ROOT/OUT/'SPEC.json').exists(),'ALREADY_FROZEN')
    p.write_new(ROOT/OUT/'HISTORY_PRIOR.json',data)
    spec=dict(scope=SCOPE,variants=VARIANTS,plan=PLAN,max_candidates=3,max_FULL=6,
        candidate_ordinals=dict(G=73,R=74,GR=75),evaluation_ordinals=list(range(129,135)),
        source_files_sha256=sources(),input_packet_sha256=prior['input_packet_sha256'],periods=prior['periods'],
        parent_results_sha256={per:h(ROOT/d.prior.OUT/per/'RESULT.json.gz') for per in PERIODS},
        history_sha256=h(ROOT/OUT/'HISTORY_PRIOR.json'),source_commit=git('rev-parse','HEAD'),
        owner_run=os.environ['GITHUB_RUN_ID'],frozen_ns=time.time_ns(),
        objective='Exceed C63 terminal net AND full cost2 in EACH used period; retain eight original WR/net/cost2/DD objectives, winner and concentration reporting. Never choose by 2026 alone.',
        transplant_G='C63 eligible AND (strict prior squeeze-high escape OR completed daily21 support). Added daily history only matters on nonescape entries; native safety never overridden.',
        transplant_R='At completed held19 once, close>entry and close>EMA20>EMA50 allows at most20 extra bars beyond original20. Native floor/momentum remain first. Held20 onward close<=EMA20 exits next actual open, hard cap40. No clock reset.',
        independent=False,formal_credit=0,used_DEV=True,parent_replays=0,API_calls=0,new_market=0,unused_OOS=0,orders=0,deploy=0,
        original_C70_alias='C70_LOCAL_registered71_not_PR1243_deferred70',retry=False,automatic_successor=False)
    for per,sha in spec['input_packet_sha256'].items():need(h(ROOT/INPUTS/(per+'.json.gz'))==sha,'INPUT_HASH')
    put(ROOT/OUT/'SPEC.json',spec)
    b[KEY]=dict(max_candidates=3,max_executions=6,reserved=0,started=0,completed=0,failed=0,remaining=6,retry=False)
    put(ROOT/OUT/'BUDGET.json',b)

def check():
    s=read(ROOT/OUT/'SPEC.json');need(s['source_files_sha256']==sources(),'SOURCE_DRIFT')
    need(s['history_sha256']==h(ROOT/OUT/'HISTORY_PRIOR.json')==h(ROOT/OLD/'BUDGET.json'),'HISTORY_DRIFT')
    for per,sha in s['input_packet_sha256'].items():need(h(ROOT/INPUTS/(per+'.json.gz'))==sha,'INPUT_DRIFT')
    for per,sha in s['parent_results_sha256'].items():need(h(ROOT/d.prior.OUT/per/'RESULT.json.gz')==sha,'PARENT_DRIFT')
    return s

def reserve(variant,per):
    s=check();j=PLAN.index((variant,per));b=read(ROOT/OUT/'BUDGET.json');q=b[KEY]
    need(q['reserved']==q['started']==q['completed']==j and not q['failed'],'DUPLICATE_OR_PRIOR_FAILURE')
    need(os.environ.get('GITHUB_RUN_ATTEMPT')=='1' and s['owner_run']==os.environ['GITHUB_RUN_ID'],'OWNER')
    folder=ROOT/OUT/variant/per
    put(folder/'ATTEMPT.json',dict(scope=SCOPE,variant=variant,period=per,ordinal=129+j,
        candidate_ordinal=73+j//2,owner_run=s['owner_run'],status='RESERVED_NOT_STARTED',
        spec_sha256=h(ROOT/OUT/'SPEC.json'),time_ns=time.time_ns()))
    q['reserved']+=1;q['remaining']-=1;atomic(ROOT/OUT/'BUDGET.json',b)

def execute(variant,per,remote):
    s=check();j=PLAN.index((variant,per));folder=ROOT/OUT/variant/per
    at=read(folder/'ATTEMPT.json');head=git('rev-parse','HEAD')
    need(head==remote and at['owner_run']==os.environ['GITHUB_RUN_ID'] and os.environ.get('GITHUB_RUN_ATTEMPT')=='1','REMOTE_OWNER')
    need(subprocess.check_output(['git','show',head+':'+OUT+'/'+variant+'/'+per+'/ATTEMPT.json'],cwd=ROOT)==(folder/'ATTEMPT.json').read_bytes(),'CLAIM_NOT_COMMITTED')
    b=read(ROOT/OUT/'BUDGET.json');q=b[KEY]
    need(q['reserved']==j+1 and q['started']==q['completed']==j and not q['failed'],'NO_REPEATED_ECONOMICS')
    need(b['cumulative_actual_evaluations']==128+j,'EVALUATION_ORDINAL')
    packet=gz(ROOT/INPUTS/(per+'.json.gz'));d.prior.previous.shared.old.inherited.packet_check(per,packet);cal=s['periods'][per]
    put(folder/'EXECUTION_STARTED.json',dict(claim_commit=head,remote_readback_sha=remote,owner_run=s['owner_run'],time_ns=time.time_ns()))
    if j%2==0:
        need(b['cumulative_actual']==72+j//2,'CANDIDATE_ORDINAL')
        b['cumulative_actual']+=1;b['new_candidate_runs']+=1
        b['candidate_trials'].append(dict(candidate=child.RULES[variant],ordinal=73+j//2,first_evaluation=129+j,scope=SCOPE))
    b['cumulative_actual_evaluations']+=1;q['started']+=1
    b['trials'].append(dict(at,actual_experiment_ordinal=129+j,status='STARTED'));atomic(ROOT/OUT/'BUDGET.json',b)
    try:
        with p.native.sensitivity():
            raw={sym:child.replay(rows,eval_start_ms=cal['start_ms'],eval_end_ms=cal['runoff_end_ms'],variant=variant)
                 for sym,rows in sorted(packet['rows_by'].items())}
        with patch.dict(d.prior.previous.integration.engine.RULES,{'M1':child.RULES[variant]}):
            result=d.prior.previous.integration.charge_and_mark(raw,'M1',packet,cal)
        result.update(scope=SCOPE,variant=variant,period=per,direct_parent='C63',spec_sha256=h(ROOT/OUT/'SPEC.json'))
        parent=gz(ROOT/d.prior.OUT/per/'RESULT.json.gz');key=lambda e:(e['symbol'],e['signal_index'],e['signal_ts'])
        need({key(e) for e in parent['events']}=={key(e) for e in result['events']},'ORIGINAL_SIGNAL_POOL_CHANGED')
        for name,obj in [('RAW.json.gz',raw),('RESULT.json.gz',result)]:p.write_new(folder/name,gzip.compress(p.canonical(obj),mtime=0))
        put(folder/'ACCOUNTING_C63.json',a.compare(parent,result))
        put(folder/'RECEIPT.json',dict(status='COMPLETED',variant=variant,period=per,candidate_ordinal=73+j//2,
            evaluation_ordinal=129+j,claim_commit=head,raw_sha256=h(folder/'RAW.json.gz'),result_sha256=h(folder/'RESULT.json.gz'),
            spec_sha256=h(ROOT/OUT/'SPEC.json'),metrics=a.snapshot(result)))
        q['completed']+=1;b['trials'][-1]['status']='COMPLETED';atomic(ROOT/OUT/'BUDGET.json',b)
        print(json.dumps(dict(variant=variant,period=per,metrics=a.snapshot(result))))
    except BaseException as exc:
        put(folder/'FAILURE.json',dict(status='FAILED_CONSUMED',error=str(exc),traceback=traceback.format_exc(),retry=False))
        q['failed']+=1;b['trials'][-1]['status']='FAILED_CONSUMED';atomic(ROOT/OUT/'BUDGET.json',b);raise

def summarize():
    check();b=read(ROOT/OUT/'BUDGET.json');need(b[KEY]['completed']==6 and b[KEY]['failed']==0,'INCOMPLETE')
    data={};statuses={};lines=['# C63 cumulative transplant — six first native FULLs','',
        'Used DEV, fixed original notional trade-bps; open marks and model costs included. No independent PASS, account-return or live-adoption claim.','',
        '|Period|Variant|Closed/open|WR %|Net bps|Cost2 bps|Daily DD bps|PF|',
        '|---|---|---:|---:|---:|---:|---:|---:|']
    for per in PERIODS:
        parent=gz(ROOT/d.prior.OUT/per/'RESULT.json.gz');snap={'C63':a.snapshot(parent)}
        for v in VARIANTS:snap[v]=a.snapshot(gz(ROOT/OUT/v/per/'RESULT.json.gz'))
        snap['C70_LOCAL']=read(ROOT/OLD/'IMPORT_ARITHMETIC.json')[per]['C70_LOCAL']
        snap['C72']=a.snapshot(gz(ROOT/OLD/per/'RESULT.json.gz'))
        checks={v:d.prior.previous.checks(snap['C63'],snap[v]) for v in VARIANTS}
        interaction={k:snap['GR'][k]-snap['G'][k]-snap['R'][k]+snap['C63'][k]
            for k in ('terminal_net_bps','terminal_cost2x_net_bps')}
        data[per]=dict(snapshots=snap,checks=checks,full_factorial_interaction_bps=interaction,
            attribution={v:read(ROOT/OUT/v/per/'ACCOUNTING_C63.json') for v in VARIANTS})
        for v in ('C63','C70_LOCAL','C72','G','R','GR'):
            m=snap[v];fmt=lambda x:'NA' if x is None else f'{x:.2f}'
            lines.append('|'+ '|'.join([per,v,f"{m['closed']}/{m['open']}",fmt(None if m['win_rate'] is None else 100*m['win_rate'])]+[fmt(m[k]) for k in ('terminal_net_bps','terminal_cost2x_net_bps','marked_DD_trade_sum_bps','PF')])+'|')
    for v in VARIANTS:
        goal=all(all(data[per]['checks'][v].values()) for per in PERIODS)
        gain=all(data[per]['checks'][v]['net_up'] and data[per]['checks'][v]['cost2_up'] for per in PERIODS)
        statuses[v]='DEVELOPMENT_GOAL_MET' if goal else 'PARTIAL_IMPROVEMENT' if gain else 'REJECT_KEEP_C63'
    result=dict(scope=SCOPE,statuses=statuses,periods=data,candidates=b['cumulative_actual'],evaluations=b['cumulative_actual_evaluations'],
        new_candidates=3,new_FULL=6,parent_replays=0,formal_credit=0,independent=False,report_only=True,automatic_successor=False)
    put(ROOT/OUT/'SUMMARY.json',result)
    lines+=['',json.dumps(statuses), '', 'FULL interaction = GR - G - R + C63, not an independent causal estimate. All losses and foregone wins stay in each accounting report.','']
    (ROOT/OUT/'REPORT.md').write_text('\n'.join(lines))
    put(ROOT/OUT/'EVIDENCE_HASHES.json',{str(x.relative_to(ROOT/OUT)):h(x) for x in (ROOT/OUT).rglob('*') if x.is_file() and x.name!='EVIDENCE_HASHES.json'})
    print('\n'.join(lines))

def verify():
    check();hashes=read(ROOT/OUT/'EVIDENCE_HASHES.json')
    for name,sha in hashes.items():need(h(ROOT/OUT/name)==sha,'EVIDENCE_CHANGED:'+name)
    summary=read(ROOT/OUT/'SUMMARY.json')
    for v,per in PLAN:
        folder=ROOT/OUT/v/per;res=gz(folder/'RESULT.json.gz');receipt=read(folder/'RECEIPT.json')
        need(h(folder/'RESULT.json.gz')==receipt['result_sha256'],'RESULT_HASH')
        need(a.snapshot(res)==receipt['metrics']==summary['periods'][per]['snapshots'][v],'SNAPSHOT_MISMATCH')
        packet=gz(ROOT/INPUTS/(per+'.json.gz'));cal=read(ROOT/OUT/'SPEC.json')['periods'][per]
        derived=p.old.metrics(res['trades'],res['open_observations'],cal,packet['rows_by'],packet['costs'])
        need(derived==res['metrics'],'NATIVE_MARK_ARITHMETIC')
    print('SAVED_SOURCE_HASHES_AND_MARK_ARITHMETIC_PASS_NO_REPLAY')

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('action',choices=['freeze','reserve','execute','summarize','verify'])
    ap.add_argument('--variant',choices=VARIANTS);ap.add_argument('--period',choices=PERIODS);ap.add_argument('--remote')
    args=ap.parse_args()
    if args.action=='freeze':freeze()
    elif args.action=='reserve':reserve(args.variant,args.period)
    elif args.action=='execute':execute(args.variant,args.period,args.remote)
    elif args.action=='summarize':summarize()
    else:verify()
