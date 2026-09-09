"""One exit hypothesis; FIXED+FULL in each of two previously-used periods.
All four first economic applications count, no hidden fixed-view runs.
"""
import argparse,gzip,json,os,subprocess,time,traceback
from pathlib import Path
from unittest.mock import patch
from backend.research.rebuild import m1_er_range_rescue_study_v1 as prior
from backend.research.rebuild import c63_profit_pivot_exit_v1 as child
p,a,ROOT=prior.p,prior.a,prior.ROOT
integration=prior.previous.integration
SCOPE='C63_PROFIT_CONFIRMED_PIVOT_EXIT_V1'
OUT='research/development_evidence/'+SCOPE
KEY='c63_profit_pivot_allocation'
LATEST='research/development_evidence/C63_PARTIAL_REALIZATION_AFTER_PR1238_V1'
PERIODS=prior.PERIODS
RUNS=[(per,view) for per in PERIODS for view in ('FIXED','FULL')]
read,gz,h,need,put=prior.read,prior.gz,prior.h,prior.need,prior.put

def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT,text=True).strip()
def baseline(per):return gz(ROOT/prior.OUT/per/'RESULT.json.gz')
def save_budget(v):
    target=ROOT/OUT/'BUDGET.json';tmp=target.with_suffix('.pending')
    with tmp.open('xb') as f:f.write(p.canonical(v));f.flush();os.fsync(f.fileno())
    os.replace(tmp,target)
def dependencies():
    src=dict(read(ROOT/prior.OUT/'SPEC.json')['source_files_sha256'])
    for name,digest in src.items():need(h(ROOT/name)==digest,'PARENT_SOURCE_DRIFT:'+name)
    for name in ('c63_profit_pivot_exit_v1.py','test_c63_profit_pivot_exit_v1.py','c63_profit_pivot_study_v1.py'):
        key='backend/research/rebuild/'+name;src[key]=h(ROOT/key)
    key=OUT+'/DESIGN.md';src[key]=h(ROOT/key)
    key=OUT+'/LOCAL_HISTORY_IMPORT.json';src[key]=h(ROOT/key)
    return src

def freeze(inputs):
    prior.verify_spec(inputs);ps=read(ROOT/prior.OUT/'SPEC.json');budget=read(ROOT/LATEST/'BUDGET.json')
    need((budget['cumulative_actual'],budget['cumulative_actual_evaluations'])==(65,112),'LATEST_NOT65_112')
    need(KEY not in budget,'DUPLICATE_SCOPE')
    spec=dict(scope=SCOPE,rule=child.RULE_ID,direct_parent=prior.child.RULE_ID,candidate_ordinal=67,
        evaluation_ordinals=[115,116,117,118],run_order=RUNS,max_candidates=1,max_economic_applications=4,max_full=2,max_fixed=2,
        periods=ps['periods'],input_packet_sha256=ps['input_packet_sha256'],source_files_sha256=dependencies(),
        prior_budget_sha256=h(ROOT/LATEST/'BUDGET.json'),prior_spec_sha256=h(ROOT/prior.OUT/'SPEC.json'),
        parent_results_sha256={per:{n:h(ROOT/prior.OUT/per/n) for n in ('RAW.json.gz','RESULT.json.gz')} for per in PERIODS},
        objective='C63 FULL comparison: WR/net/cost2 up, daily markedDD down in each used period; report mean/worst loss and winner harm. Numeric equality is not improvement.',
        rule_text='C63 entry/size/native exits preserved. A radius2 strictly confirmed LOW formed at/after entry may activate or raise protection iff low>entry*(1+currently accrued original roundtrip cost/10000). At each held close test only previously activated protection: close<level requests full exit next actual open. Native exit priority first. New confirmation applies only to subsequent closes. Never lower protection. No partial, grace, buffer, future funding, guaranteed profit or resident stop.',
        retry=False,independent=False,formal_credit=0,selected_on_used_DEV=True,parent_replay=0,
        market_requests=0,unused_oos=0,paid_ai=0,orders=0,old_AVWAP_slots_unchanged=True,
        code_commit=git('rev-parse','HEAD'),frozen_ns=time.time_ns())
    put(ROOT/OUT/'SPEC.json',spec)
    imported=read(ROOT/OUT/'LOCAL_HISTORY_IMPORT.json');hist=imported['original_local_execution_ledger']
    need(hist['local_new_candidates']==1 and hist['local_new_economic_applications']==2 and hist['local_decision']=='REJECT_KEEP_C63','LOCAL_IMPORT_INVALID')
    need(all(t.get('candidate')!=imported['original_local_spec']['rule'] for t in budget['candidate_trials']),'LOCAL_ALREADY_IMPORTED')
    budget['candidate_trials'].append(dict(scope=hist['scope'],candidate=imported['original_local_spec']['rule'],ordinal=66,first_evaluation=113,imported_from_local=True,original_provisional_ordinal=65,source_spec_sha256=imported['original_local_spec_sha256']))
    for j,e in enumerate(hist['events']):budget['trials'].append(dict(scope=hist['scope'],candidate_ordinal=66,actual_experiment_ordinal=113+j,original_local_attempt=e['attempt'],original_local_completion=e['completion'],status='COMPLETED_IMPORTED_NO_REPLAY'))
    budget['cumulative_actual']=66;budget['cumulative_actual_evaluations']=114;budget['new_candidate_runs']+=1
    budget['local_prior_import_receipt_sha256']=h(ROOT/OUT/'LOCAL_HISTORY_IMPORT.json')
    budget[KEY]=dict(max_candidates=1,max_executions=4,max_full=2,max_fixed=2,reserved=0,started=0,completed=0,failed=0,remaining=4,retry=False)
    put(ROOT/OUT/'BUDGET.json',budget)

def verify_spec(inputs=None):
    s=read(ROOT/OUT/'SPEC.json');need(s['source_files_sha256']==dependencies(),'FROZEN_CODE_CHANGED')
    need(s['prior_budget_sha256']==h(ROOT/LATEST/'BUDGET.json') and s['prior_spec_sha256']==h(ROOT/prior.OUT/'SPEC.json'),'PARENT_CHANGED')
    for per,files in s['parent_results_sha256'].items():
        for name,d in files.items():need(h(ROOT/prior.OUT/per/name)==d,'C63_RESULT_CHANGED')
    if inputs:
        for per,d in s['input_packet_sha256'].items():need(h(Path(inputs)/f'{per}.json.gz')==d,'INPUT_CHANGED')
    return s

def reserve(per,view):
    s=verify_spec();j=RUNS.index((per,view));b=read(ROOT/OUT/'BUDGET.json');slot=b[KEY]
    need(slot['reserved']==slot['started']==slot['completed']==j and not slot['failed'],'DUPLICATE_OR_UNRESOLVED')
    need(os.environ.get('GITHUB_RUN_ATTEMPT')=='1','NO_RETRY')
    at=dict(scope=SCOPE,period=per,view=view,candidate_ordinal=67,ordinal=115+j,owner_run=os.environ['GITHUB_RUN_ID'],spec_sha256=h(ROOT/OUT/'SPEC.json'),status='RESERVED_NOT_STARTED',time_ns=time.time_ns())
    put(ROOT/OUT/per/view/'ATTEMPT.json',at);slot['reserved']+=1;slot['remaining']-=1;save_budget(b)

def execute(per,view,inputs,remote):
    s=verify_spec(inputs);j=RUNS.index((per,view));out=ROOT/OUT/per/view;at=read(out/'ATTEMPT.json');head=git('rev-parse','HEAD')
    need(head==remote and at['owner_run']==os.environ['GITHUB_RUN_ID'],'RUNTIME_CLAIM_OWNER')
    need(os.environ.get('GITHUB_RUN_ATTEMPT')=='1' and at['spec_sha256']==h(ROOT/OUT/'SPEC.json'),'NO_RETRY_SPEC')
    need(subprocess.check_output(['git','show',head+':'+str((out/'ATTEMPT.json').relative_to(ROOT))],cwd=ROOT)==(out/'ATTEMPT.json').read_bytes(),'UNCOMMITTED_CLAIM')
    b=read(ROOT/OUT/'BUDGET.json');slot=b[KEY]
    need(slot['reserved']==j+1 and slot['started']==slot['completed']==j and not slot['failed'],'ALREADY_STARTED')
    need(b['cumulative_actual_evaluations']==114+j,'EVALUATION_COUNT')
    packet=gz(Path(inputs)/f'{per}.json.gz');prior.previous.shared.old.inherited.packet_check(per,packet);cal=s['periods'][per]
    par=baseline(per);parent_raw=gz(ROOT/prior.OUT/per/'RAW.json.gz')
    put(out/'EXECUTION_STARTED.json',dict(claim_commit=head,remote_readback_sha=remote,owner_run=at['owner_run'],time_ns=time.time_ns()))
    if j==0:
        need(b['cumulative_actual']==66,'CANDIDATE_COUNT');b['cumulative_actual']+=1;b['new_candidate_runs']+=1
        b['candidate_trials'].append(dict(scope=SCOPE,candidate=child.RULE_ID,ordinal=67,first_evaluation=115))
    b['cumulative_actual_evaluations']+=1;slot['started']+=1;b['trials'].append(dict(at,status='STARTED',actual_experiment_ordinal=115+j));save_budget(b)
    try:
        raw={}
        with p.native.sensitivity():
            for symbol,rows in sorted(packet['rows_by'].items()):
                fixed=None if view=='FULL' else [x['signal_index'] for k in ('trades','open_positions') for x in parent_raw[symbol][k]]
                raw[symbol]=child.replay(rows,eval_start_ms=cal['start_ms'],eval_end_ms=cal['runoff_end_ms'],cost_model=packet['costs'][symbol],fixed_signal_indices=fixed)
        with patch.dict(integration.engine.RULES,{'M1':child.RULE_ID}):result=integration.charge_and_mark(raw,'M1',packet,cal)
        result.update(scope=SCOPE,period=per,view=view,spec_sha256=h(ROOT/OUT/'SPEC.json'),direct_parent=s['direct_parent'])
        identity=lambda x:(x['symbol'],x['signal_index'],x['signal_ts'])
        if view=='FULL':need({identity(x) for x in result['events']}=={identity(x) for x in par['events']},'C63_SIGNAL_POOL')
        else:
            old={identity(x):x for k in ('trades','open_observations') for x in par[k]};new={identity(x):x for k in ('trades','open_observations') for x in result[k]}
            need(set(old)==set(new),'FIXED_C63_ORIGINS')
            for key in old:need((old[key]['entry_ts'],old[key]['entry_price'])==(new[key]['entry_ts'],new[key]['entry_price']),'FIXED_FILL')
        p.write_new(out/'RAW.json.gz',gzip.compress(p.canonical(raw),mtime=0));p.write_new(out/'RESULT.json.gz',gzip.compress(p.canonical(result),mtime=0))
        put(out/'ACCOUNTING_C63.json',a.compare(par,result))
        if view=='FULL':put(out/'ACCOUNTING_M1.json',a.compare(prior.parent(per),result))
        put(out/'RECEIPT.json',dict(status='COMPLETED',period=per,view=view,candidate_ordinal=67,result_sha256=h(out/'RESULT.json.gz'),raw_sha256=h(out/'RAW.json.gz'),spec_sha256=h(ROOT/OUT/'SPEC.json'),claim_commit=head,metrics=a.snapshot(result)))
        slot['completed']+=1;b['trials'][-1]['status']='COMPLETED';save_budget(b);print(json.dumps(a.snapshot(result)))
    except BaseException as exc:
        put(out/'FAILURE.json',dict(status='FAILED_CONSUMED',error=str(exc),traceback=traceback.format_exc(),retry=False))
        slot['failed']+=1;b['trials'][-1]['status']='FAILED_CONSUMED';save_budget(b);raise

def summarize():
    verify_spec();data={};lines=['# C63 profit-zone confirmed-pivot exit — used DEV','',
        'One candidate, four counted applications: FIXED and FULL in each original period. C63 controls reused, not rerun. Fixed nominal trade-bps; hypothetical open marks included; no account return or formal/live credit.','',
        '|Period|Rule|Closed/open|WR%|Mean win|Mean loss|Payoff|PF|Terminal net|Cost2|Daily DD|',
        '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for per in PERIODS:
        refs={'C63':baseline(per),**{v:gz(ROOT/OUT/per/v/'RESULT.json.gz') for v in ('FIXED','FULL')}}
        snaps={k:a.snapshot(v) for k,v in refs.items()}
        data[per]=dict(snapshots=snaps,checks=prior.previous.checks(snaps['C63'],snaps['FULL']),
            fixed_accounting=read(ROOT/OUT/per/'FIXED/ACCOUNTING_C63.json'),full_accounting=read(ROOT/OUT/per/'FULL/ACCOUNTING_C63.json'))
        for label,s in snaps.items():
            fmt=lambda x:'NA' if x is None else f'{x:.2f}'
            lines.append('|'+ '|'.join([per,label,f"{s['closed']}/{s['open']}",fmt(None if s['win_rate'] is None else 100*s['win_rate'])]+[fmt(s[k]) for k in ('average_win_bps','average_loss_bps','realized_payoff','PF','terminal_net_bps','terminal_cost2x_net_bps','marked_DD_trade_sum_bps')])+'|')
    goal=all(all(x['checks'].values()) for x in data.values());gain=all(x['checks']['net_up'] and x['checks']['cost2_up'] for x in data.values())
    status='DEVELOPMENT_GOAL_MET' if goal else 'PARTIAL_IMPROVEMENT' if gain else 'REJECT_KEEP_C63'
    put(ROOT/OUT/'SUMMARY.json',dict(status=status,periods=data,candidates=67,evaluations=118,new_candidates=1,new_full=2,new_fixed=2,parent_replay=0,independent=False,formal_credit=0))
    lines+=['',status,'','Original C63 and M1/C54 remain preserved. FIXED direct exit effects and FULL occupancy effects are not conflated. No automatic second exit, winner-specific exceptions or threshold retuning.','']
    (ROOT/OUT/'REPORT.md').write_text('\n'.join(lines));print('\n'.join(lines))
    put(ROOT/OUT/'EVIDENCE_HASHES.json',{str(x.relative_to(ROOT/OUT)):h(x) for x in (ROOT/OUT).rglob('*') if x.is_file() and x.name!='EVIDENCE_HASHES.json'})


def preflight(inputs):
    s=verify_spec(inputs);report={}
    from backend.research.rebuild.chart_mechanism_features_v1 import confirmed_pivots
    from backend.research.rebuild.chart_mechanism_execution_v1 import to_bars
    from backend.research.rebuild.kr3_profit_zone_exit_v1 import decision_cost
    for per in PERIODS:
        packet=gz(Path(inputs)/f'{per}.json.gz');cal=s['periods'][per];raw=gz(ROOT/prior.OUT/per/'RAW.json.gz')
        counters=dict(positions=0,activations=0,early_trigger_positions=0)
        for symbol,x in raw.items():
            bars=to_bars(packet['rows_by'][symbol],cal['start_ms'],cal['runoff_end_ms'])
            # Price-feature availability is keyed by the explicit confirmation timestamp.
            pp={q['known_index']:q for q in confirmed_pivots(bars,len(bars)-1) if q['kind']=='LOW'}
            for t in x['trades']+x['open_positions']:
                counters['positions']+=1;state=child.Protection(t['entry_index'],t['entry_price'])
                for ob in x['trace']:
                    if ob['kind']!='HELD_CLOSE_OBSERVATION' or ob['signal_index']!=t['signal_index']:continue
                    j=ob['index'];need(ob['close']==bars[j].close,'PREFLIGHT_SOURCE_CLOSE')
                    cost=decision_cost(t['entry_ts'],ob['ts'],packet['costs'][symbol])['cost_bps']
                    dec=state.step(j,ob['close'],cost,pp.get(j),ob['exit_reason'])
                    counters['activations']+=int(dec['activated'] is not None)
                    if dec['selected_reason']==child.REASON:counters['early_trigger_positions']+=1;break
        report[per]=counters
    put(ROOT/OUT/'NONTRIVIAL_PREFLIGHT.json',dict(periods=report,no_counterfactual_profit_computed=True,economic_replays=0))
    return any(v['early_trigger_positions'] for v in report.values())

if __name__=='__main__':
    q=argparse.ArgumentParser();q.add_argument('action',choices=['freeze','preflight','reserve','execute','summarize']);q.add_argument('--period',choices=PERIODS);q.add_argument('--view',choices=['FIXED','FULL']);q.add_argument('--inputs');q.add_argument('--remote-sha');x=q.parse_args()
    if x.action=='freeze':freeze(x.inputs)
    elif x.action=='preflight':
        if not preflight(x.inputs):raise SystemExit('NOT_RUN_NO_ELIGIBLE_PROTECTIVE_EXIT')
    elif x.action=='reserve':reserve(x.period,x.view)
    elif x.action=='execute':execute(x.period,x.view,x.inputs,x.remote_sha)
    else:summarize()
