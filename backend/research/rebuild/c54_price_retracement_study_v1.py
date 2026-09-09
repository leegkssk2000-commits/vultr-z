"""Two pre-frozen hypotheses/four FULLs plus read-only M1 path diagnosis.

Existing runner/costs and C54 controls reused. No old T/F budget consumed.
"""
import argparse,gzip,json,math,os,subprocess,time,traceback
from collections import defaultdict
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from backend.research.rebuild import kr3_c51_entry_context_study_v1 as shared
from backend.research.rebuild import c54_price_retracement_v1 as child
p,a,ROOT=shared.p,shared.a,shared.ROOT
C54_OUT=shared.OUT
OLD='research/development_evidence/TOP5_SOURCE_CHART_MECHANISMS_AFTER_PR1228_V1'
SCOPE='C54_PRICE_RETRACEMENT_M1_DIAG_AFTER_PR1230_V1'
OUT='research/development_evidence/'+SCOPE
KEY='price_only_retracement_allocation'
PERIODS=shared.old.PERIODS
RUNS=[(m,per) for m in child.MODES for per in PERIODS]
read,gz,h,need,put=shared.read,shared.gz,shared.h,shared.need,shared.put

def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT,text=True).strip()
def baseline(per):return gz(ROOT/C54_OUT/'B'/per/'RESULT.json.gz')
def save_budget(v):
    path=ROOT/OUT/'BUDGET.json';tmp=path.with_suffix('.pending')
    with tmp.open('xb') as f:f.write(p.canonical(v));f.flush();os.fsync(f.fileno())
    os.replace(tmp,path)

def dependencies():
    src=dict(read(ROOT/OLD/'SPEC.json')['source_files_sha256'])
    for name,digest in src.items():need(h(ROOT/name)==digest,'PRIOR_FROZEN_SOURCE_DRIFT:'+name)
    for name in ('c54_price_retracement_v1.py','test_c54_price_retracement_v1.py','c54_price_retracement_study_v1.py'):
        path='backend/research/rebuild/'+name;src[path]=h(ROOT/path)
    path=OUT+'/DESIGN.md';src[path]=h(ROOT/path)
    return src

def freeze(inputs):
    old=read(ROOT/OLD/'SPEC.json');budget=read(ROOT/OLD/'BUDGET.json')
    need((budget['cumulative_actual'],budget['cumulative_actual_evaluations'])==(59,98),'LATEST_COUNTS_NOT59_98')
    need(KEY not in budget,'DUPLICATE_SCOPE')
    shared.verify_spec(inputs)
    spec=dict(scope=SCOPE,rules=child.RULES,runs=RUNS,periods=old['periods'],
        input_packet_sha256=old['input_packet_sha256'],source_files_sha256=dependencies(),
        prior_budget_sha256=h(ROOT/OLD/'BUDGET.json'),prior_spec_sha256=h(ROOT/OLD/'SPEC.json'),
        parent_results_sha256={per:h(ROOT/C54_OUT/'B'/per/'RESULT.json.gz') for per in PERIODS},
        m1_results_sha256={per:{n:h(ROOT/OLD/'M1'/per/n) for n in ('RAW.json.gz','RESULT.json.gz')} for per in PERIODS},
        prior_unused_TF_slots=budget['chart_allocation']['remaining'],
        candidate_ordinals={'FIB':60,'SHIFTED':61},evaluation_ordinals=[99,100,101,102],
        max_candidates=2,max_full=4,retry=False,independent=False,formal_credit=0,
        objective='Each period WR/net/cost2 up and daily markedDD down; numeric equality is not improvement.',
        rule='C54 plus only confirmed price-retracement zone; radius2 pivots known through signal i-1; original pre-pullback q; deepest low q+1..i-1. FIB .382-.618, SHIFTED .350-.586. No AVWAP or volume predicate. Exact original price anchors and widths reused; old blocked T/F not reinterpreted.',
        market_requests=0,unused_oos=0,paid_ai=0,orders=0,parent_replay=0,
        source_commit=git('rev-parse','HEAD'),frozen_ns=time.time_ns())
    put(ROOT/OUT/'SPEC.json',spec)
    budget[KEY]=dict(max_candidates=2,max_executions=4,reserved=0,started=0,completed=0,failed=0,remaining=4,retry=False)
    put(ROOT/OUT/'BUDGET.json',budget)

def verify_spec(inputs=None):
    spec=read(ROOT/OUT/'SPEC.json');need(spec['source_files_sha256']==dependencies(),'FROZEN_SOURCE_CHANGED')
    need(spec['prior_budget_sha256']==h(ROOT/OLD/'BUDGET.json'),'PRIOR_BUDGET_DRIFT')
    need(spec['prior_spec_sha256']==h(ROOT/OLD/'SPEC.json'),'PRIOR_SPEC_DRIFT')
    for per,digest in spec['parent_results_sha256'].items():need(h(ROOT/C54_OUT/'B'/per/'RESULT.json.gz')==digest,'C54_CHANGED')
    for per,files in spec['m1_results_sha256'].items():
        for n,d in files.items():need(h(ROOT/OLD/'M1'/per/n)==d,'M1_RESULT_DRIFT')
    if inputs:
        for per,digest in spec['input_packet_sha256'].items():need(h(Path(inputs)/f'{per}.json.gz')==digest,'ORIGINAL_INPUT_DRIFT')
    return spec

def reserve(mode,per):
    spec=verify_spec();j=RUNS.index((mode,per));budget=read(ROOT/OUT/'BUDGET.json');slot=budget[KEY]
    need(slot['reserved']==slot['completed']==j and slot['failed']==0,'DUPLICATE_OR_UNFINISHED_PRIOR')
    need(os.environ.get('GITHUB_RUN_ATTEMPT')=='1','NO_RETRY')
    at=dict(scope=SCOPE,mode=mode,period=per,candidate_ordinal=spec['candidate_ordinals'][mode],ordinal=99+j,
            owner_run=os.environ['GITHUB_RUN_ID'],spec_sha256=h(ROOT/OUT/'SPEC.json'),status='RESERVED_NOT_STARTED',time_ns=time.time_ns())
    put(ROOT/OUT/mode/per/'ATTEMPT.json',at);slot['reserved']+=1;slot['remaining']-=1;save_budget(budget)

def execute(mode,per,inputs,remote):
    spec=verify_spec(inputs);j=RUNS.index((mode,per));out=ROOT/OUT/mode/per;at=read(out/'ATTEMPT.json');head=git('rev-parse','HEAD')
    need(head==remote and at['owner_run']==os.environ['GITHUB_RUN_ID'],'REMOTE_CLAIM_OR_OWNER')
    need(os.environ.get('GITHUB_RUN_ATTEMPT')=='1' and at['spec_sha256']==h(ROOT/OUT/'SPEC.json'),'NO_RETRY_SPEC')
    need(subprocess.check_output(['git','show',head+':'+str((out/'ATTEMPT.json').relative_to(ROOT))],cwd=ROOT)==(out/'ATTEMPT.json').read_bytes(),'CLAIM_NOT_COMMITTED')
    packet=gz(Path(inputs)/f'{per}.json.gz');shared.old.inherited.packet_check(per,packet)
    budget=read(ROOT/OUT/'BUDGET.json');need(budget['cumulative_actual_evaluations']==98+j,'ACTUAL_EVALUATIONS')
    put(out/'EXECUTION_STARTED.json',dict(claim_commit=head,remote_readback_sha=remote,time_ns=time.time_ns(),owner_run=at['owner_run']))
    if per=='DEV2025':
        need(budget['cumulative_actual']==59+child.MODES.index(mode),'ACTUAL_CANDIDATES')
        budget['cumulative_actual']+=1;budget['new_candidate_runs']+=1
        budget['candidate_trials'].append(dict(scope=SCOPE,ordinal=spec['candidate_ordinals'][mode],candidate=child.RULES[mode],first_evaluation=99+j))
    budget['cumulative_actual_evaluations']+=1;budget[KEY]['started']+=1
    budget['trials'].append(dict(at,status='STARTED',actual_experiment_ordinal=99+j));save_budget(budget)
    try:
        with patch.object(shared,'c',child),patch.object(shared,'baseline',baseline),patch.object(shared,'OUT',OUT),patch.object(shared,'SCOPE',SCOPE):
            raw,result,comp=shared.run_one(mode,per,packet,spec)
        p.write_new(out/'RAW.json.gz',gzip.compress(p.canonical(raw),mtime=0));p.write_new(out/'RESULT.json.gz',gzip.compress(p.canonical(result),mtime=0))
        comp['comparison_type']='PRICE_ONLY_RETRACEMENT_VS_C54_FULL';put(out/'ACCOUNTING_C54.json',comp)
        put(out/'RECEIPT.json',dict(status='COMPLETED',mode=mode,period=per,result_sha256=h(out/'RESULT.json.gz'),raw_sha256=h(out/'RAW.json.gz'),spec_sha256=h(ROOT/OUT/'SPEC.json'),claim_commit=head,metrics=a.snapshot(result)))
        budget[KEY]['completed']+=1;budget['trials'][-1]['status']='COMPLETED';save_budget(budget)
        print(json.dumps(a.snapshot(result),sort_keys=True))
    except BaseException as exc:
        put(out/'FAILURE.json',dict(status='FAILED_CONSUMED',error=str(exc),traceback=traceback.format_exc(),retry=False))
        budget[KEY]['failed']+=1;budget['trials'][-1]['status']='FAILED_CONSUMED';save_budget(budget);raise

def diagnose_m1():
    # Outcome grouping of saved paths only. No hypothetical candidate fills/returns.
    from backend.research.rebuild.kr3_profit_zone_exit_v1 import decision_cost
    costs=read(ROOT/shared.old.OUT/'COSTS.json');answer={}
    for per in PERIODS:
        r=gz(ROOT/OLD/'M1'/per/'RESULT.json.gz');raw=gz(ROOT/OLD/'M1'/per/'RAW.json.gz')
        groups=defaultdict(lambda:dict(count=0,net_bps=0.));exits=defaultdict(lambda:dict(count=0,wins=0,net_bps=0.));rows=[]
        for t in r['trades']:
            symbol=t['symbol'];i=t['signal_index'];tr=[z for z in raw[symbol]['trace'] if z.get('signal_index')==i and z['kind']=='HELD_CLOSE_OBSERVATION']
            need(tr and all(t['entry_ts']<z['ts']<=t['exit_ts'] for z in tr),'M1_HELD_CLOCK')
            observed=[dict(ts=z['ts'],net_mark_bps=(z['close']/t['entry_price']-1)*10000-decision_cost(t['entry_ts'],z['ts'],costs[symbol])['cost_bps']) for z in tr]
            had_positive=any(z['net_mark_bps']>0 for z in observed)
            group='FINAL_WIN' if t['net_bps']>0 else 'FINAL_FLAT' if t['net_bps']==0 else 'POSITIVE_CLOSE_THEN_LOSS' if had_positive else 'NEVER_POSITIVE_HELD_CLOSE_LOSS'
            groups[group]['count']+=1;groups[group]['net_bps']+=t['net_bps']
            reason=t['exit_reason'];exits[reason]['count']+=1;exits[reason]['wins']+=int(t['net_bps']>0);exits[reason]['net_bps']+=t['net_bps']
            rows.append(dict(symbol=symbol,origin=t['origin_key'],entry_ts=t['entry_ts'],exit_ts=t['exit_ts'],final_net_bps=t['net_bps'],exit_reason=reason,group=group,held_closes=len(tr),observed_peak_net_bps=max(z['net_mark_bps'] for z in observed),first_positive_ts=next((z['ts'] for z in observed if z['net_mark_bps']>0),None)))
        need(len(rows)==len(r['trades']) and math.isclose(sum(g['net_bps'] for g in groups.values()),sum(t['net_bps'] for t in r['trades']),abs_tol=1e-7),'M1_GROUP_ACCOUNTING')
        answer[per]=dict(groups=dict(groups),exit_reasons=dict(exits),rows=rows,open_positions=len(r['open_observations']),source_sha256={n:h(ROOT/OLD/'M1'/per/n) for n in ('RAW.json.gz','RESULT.json.gz')},new_strategy_replays=0,labels_are_execution_features=False,cost_semantics='ORIGINAL_TIME_ACCRUED_RESEARCH_PROXY_NOT_ACTUAL_FILLS',independent=False)
    return answer

def checks(parent,result):
    def up(x,y):return x is not None and y is not None and x>y and not math.isclose(x,y,rel_tol=1e-11,abs_tol=1e-7)
    return dict(WR_up=up(result['win_rate'],parent['win_rate']),net_up=up(result['terminal_net_bps'],parent['terminal_net_bps']),cost2_up=up(result['terminal_cost2x_net_bps'],parent['terminal_cost2x_net_bps']),DD_down=up(parent['marked_DD_trade_sum_bps'],result['marked_DD_trade_sum_bps']))

def summarize():
    verify_spec();data={};lines=['# Price-only C54 retracement comparison','',
      'New FIB/SHIFTED hypotheses without AVWAP, not the old blocked T1/F1/F0. USED_DEV, equal-notional trade-bps including open marks, no independent/G5/live claim.','',
      '|Period|Rule|Closed/open|WR%|Payoff|PF|Terminal net|Cost2|Daily DD|Delta vs C54|',
      '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for per in PERIODS:
        ps=a.snapshot(baseline(per));data[per]={'C54':ps}
        for mode in ('C54',)+child.MODES:
            snap=ps if mode=='C54' else a.snapshot(gz(ROOT/OUT/mode/per/'RESULT.json.gz'))
            fmt=lambda x:'NA' if x is None else f'{x:.2f}'
            lines.append('|'+ '|'.join([per,mode,f"{snap['closed']}/{snap['open']}",fmt(None if snap['win_rate'] is None else 100*snap['win_rate'])]+[fmt(snap[k]) for k in ('realized_payoff','PF','terminal_net_bps','terminal_cost2x_net_bps','marked_DD_trade_sum_bps')]+[fmt(snap['terminal_net_bps']-ps['terminal_net_bps'])])+'|')
            if mode!='C54':data[per][mode]=dict(snapshot=snap,checks=checks(ps,snap),accounting=read(ROOT/OUT/mode/per/'ACCOUNTING_C54.json'))
    status={m:('DEVELOPMENT_GOAL_MET' if all(all(data[per][m]['checks'].values()) for per in PERIODS) else 'PARTIAL_IMPROVEMENT' if all(data[per][m]['checks']['net_up'] and data[per][m]['checks']['cost2_up'] for per in PERIODS) else 'REJECT_KEEP_C54') for m in child.MODES}
    put(ROOT/OUT/'SUMMARY.json',dict(status=status,periods=data,candidates=61,evaluations=102,new_candidates=2,new_full=4,old_TF_slots_unchanged=True,independent=False,formal_credit=0))
    put(ROOT/OUT/'M1_DIAGNOSIS.json',diagnose_m1())
    lines+=['',json.dumps(status),'','No parameter calibration/automatic next candidate. Old AVWAP source block persists; no volume used by these two variants. M1 diagnostics regroup unchanged original net amounts, never hypothetical recovery profits.','']
    (ROOT/OUT/'REPORT.md').write_text('\n'.join(lines));print('\n'.join(lines))

if __name__=='__main__':
    q=argparse.ArgumentParser();q.add_argument('action',choices=['freeze','reserve','execute','summarize']);q.add_argument('--inputs');q.add_argument('--mode',choices=child.MODES);q.add_argument('--period',choices=PERIODS);q.add_argument('--remote-sha');x=q.parse_args()
    if x.action=='freeze':freeze(x.inputs)
    elif x.action=='reserve':reserve(x.mode,x.period)
    elif x.action=='execute':execute(x.mode,x.period,x.inputs,x.remote_sha)
    else:summarize()
