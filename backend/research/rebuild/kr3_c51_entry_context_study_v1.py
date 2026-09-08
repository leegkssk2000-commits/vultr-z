"""Three preregistered hypotheses, six serial FULLs; old C51 is not rerun."""
import argparse,gzip,json,os,subprocess,time,traceback
from pathlib import Path
from backend.research.rebuild import kr3_profit_zone_study_v1 as old
from backend.research.rebuild import kr3_c51_entry_context_v1 as c
p,a,ROOT=old.p,old.a,old.ROOT
SCOPE='KR3_C51_ENTRY_CONTEXT_AB_AFTER_PR1225_V1'
OUT='research/development_evidence/'+SCOPE
PRIOR='research/development_evidence/KR3_C51_ONCE_RECOVERY_AFTER_PR1224_V1/BUDGET.json'
KEY='c51_entry_context_ab_allocation'
RUNS=[(m,per) for m in c.MODES for per in old.PERIODS]
read,gz,h,need,put=old.read,old.gz,old.h,old.need,old.put

def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT,text=True).strip()
def baseline(per):return gz(ROOT/old.OUT/per/'RESULT.json.gz')
def save_budget(v):
    target=ROOT/OUT/'BUDGET.json';tmp=target.with_suffix('.pending')
    with tmp.open('xb') as f:f.write(p.canonical(v));f.flush();os.fsync(f.fileno())
    os.replace(tmp,target)
def dependencies():
    prior=read(ROOT/old.OUT/'SPEC.json');v=dict(prior['source_files_sha256'])
    for path,digest in v.items():need(h(ROOT/path)==digest,'PARENT_SOURCE_DRIFT:'+path)
    for name in ('kr3_c51_entry_context_v1.py','test_kr3_c51_entry_context_v1.py','kr3_c51_entry_context_study_v1.py','top5_external_features_v1.py','policy_kernel_v1.py'):
        path='backend/research/rebuild/'+name;v[path]=h(ROOT/path)
    path=OUT+'/DESIGN.md';v[path]=h(ROOT/path)
    return v

def freeze(inputs):
    budget=read(ROOT/PRIOR);ps=read(ROOT/old.OUT/'SPEC.json')
    need((budget['cumulative_actual'],budget['cumulative_actual_evaluations'])==(52,84),'LATEST_BASELINE_NOT52_84')
    need(KEY not in budget,'DUPLICATE_SCOPE')
    for per in old.PERIODS:
        packet=gz(Path(inputs)/f'{per}.json.gz');old.inherited.packet_check(per,packet)
        need(h(Path(inputs)/f'{per}.json.gz')==ps['input_packet_sha256'][per],'PARENT_INPUT_BYTES')
    spec=dict(scope=SCOPE,candidates=c.RULES,candidate_ordinals={'A':53,'B':54,'AB':55},evaluation_ordinals=list(range(85,91)),
        runs=RUNS,constants=c.CONSTANTS,source_files_sha256=dependencies(),
        prior_budget_sha256=h(ROOT/PRIOR),parent_spec_sha256=h(ROOT/old.OUT/'SPEC.json'),
        parent_results_sha256={per:h(ROOT/old.OUT/per/'RESULT.json.gz') for per in old.PERIODS},
        original_KR3_results_sha256=ps['baseline_sha256'],periods=ps['periods'],input_packet_sha256=ps['input_packet_sha256'],
        objective=ps['development_objective'],direct_parent=c.parent.RULE_ID,
        max_candidates=3,max_full=6,retry=False,independent=False,formal_credit=0,
        selection='Fixed-before-outcomes factorial A/B/AB; no market-based threshold calibration, broad search, new collection or RVOL. A uses immediate pre-pullback trend, not recovery-bar ADX. B uses one lagged ATR range, not an optimized cutoff.',
        reference='Original causal reference reservations remain even when eligibility vetoes the actual trade. Whole actual-slot sequence replayed; admissions need not be subset of C51.',
        unchanged=['EMA_seed','C51_exit_path','cost_model','SL_TP','sizing','universe'],
        market_requests=0,unused_oos=0,paid_ai=0,orders=0,code_commit=git('rev-parse','HEAD'),frozen_ns=time.time_ns())
    put(ROOT/OUT/'SPEC.json',spec)
    budget[KEY]=dict(max_candidates=3,max_executions=6,reserved=0,started=0,completed=0,failed=0,remaining=6,retry=False)
    put(ROOT/OUT/'BUDGET.json',budget)
    print('ALL_THREE_RULES_FROZEN_BEFORE_FIRST_ECONOMIC_RESULT')

def verify_spec(inputs=None):
    s=read(ROOT/OUT/'SPEC.json');need(s['source_files_sha256']==dependencies(),'FROZEN_CODE_CHANGED')
    need(h(ROOT/PRIOR)==s['prior_budget_sha256'],'PRIOR_HISTORY_CHANGED')
    for per,digest in s['parent_results_sha256'].items():need(h(ROOT/old.OUT/per/'RESULT.json.gz')==digest,'PARENT_RESULT_DRIFT')
    if inputs:
        for per,digest in s['input_packet_sha256'].items():need(h(Path(inputs)/f'{per}.json.gz')==digest,'INPUT_PACKET_DRIFT')
    return s

def reserve(mode,per):
    s=verify_spec();j=RUNS.index((mode,per));v=read(ROOT/OUT/'BUDGET.json');slot=v[KEY]
    need(slot['reserved']==slot['completed']==j and slot['failed']==0,'DUPLICATE_OR_PREVIOUS_INCOMPLETE')
    need(os.environ.get('GITHUB_RUN_ATTEMPT')=='1','NO_RETRY')
    at=dict(scope=SCOPE,mode=mode,period=per,candidate_ordinal=s['candidate_ordinals'][mode],ordinal=85+j,
            owner_run=os.environ['GITHUB_RUN_ID'],spec_sha256=h(ROOT/OUT/'SPEC.json'),status='RESERVED_NOT_STARTED',time_ns=time.time_ns())
    put(ROOT/OUT/mode/per/'ATTEMPT.json',at);slot['reserved']+=1;slot['remaining']-=1;save_budget(v)

def run_one(mode,per,packet,spec):
    old.inherited.packet_check(per,packet);cal=spec['periods'][per];start,end=cal['start_ms'],cal['runoff_end_ms']
    raw_all={};result={k:[] for k in ('trades','open_observations','events','trace')};result['audit']={};result['reference_states']={}
    with p.native.sensitivity():
        for symbol,rows in sorted(packet['rows_by'].items()):
            bundle=p.d.build_bundle(rows,p.d.PARENT_SPEC,eval_start_ms=start,eval_end_ms=end)
            raw=c.replay(rows,bundle,eval_start_ms=start,eval_end_ms=end,cost_model=packet['costs'][symbol],mode=mode)
            raw_all[symbol]=raw
            charged=p.account.charge_result(raw,symbol,'keltner_trend_main',c.RULES[mode],packet['policy'],packet['costs'],rows)
            for k in ('trades','open_observations','events','trace'):result[k].extend(charged[k])
            result['audit'][symbol]=raw['audit'];result['reference_states'][symbol]=raw['reference_checkpoint']
    parent=baseline(per)
    need(parent['reference_states']==result['reference_states'],'REFERENCE_RESERVATION_CHANGED')
    need({(e['symbol'],e['signal_index'],e['signal_ts']) for e in parent['events']}=={(e['symbol'],e['signal_index'],e['signal_ts']) for e in result['events']},'SIGNAL_UNIVERSE_CHANGED')
    result.update(scope=SCOPE,mode=mode,candidate=c.RULES[mode],period=per,spec_sha256=h(ROOT/OUT/'SPEC.json'),independent=False,formal_credit=0)
    result['metrics']=p.old.metrics(result['trades'],result['open_observations'],cal,packet['rows_by'],packet['costs'])
    comp=a.compare(parent,result);comp['comparison_type']='C51_ENTRY_ELIGIBILITY_FULL_'+mode
    return raw_all,result,comp

def execute(mode,per,inputs,remote):
    s=verify_spec(inputs);out=ROOT/OUT/mode/per;at=read(out/'ATTEMPT.json');head=git('rev-parse','HEAD');j=RUNS.index((mode,per))
    need(head==remote and at['owner_run']==os.environ['GITHUB_RUN_ID'],'REMOTE_CLAIM_OR_OWNER')
    need(os.environ.get('GITHUB_RUN_ATTEMPT')=='1' and at['spec_sha256']==h(ROOT/OUT/'SPEC.json'),'SPEC_OR_RETRY')
    rel=str((out/'ATTEMPT.json').relative_to(ROOT))
    need(subprocess.check_output(['git','show',head+':'+rel],cwd=ROOT)==(out/'ATTEMPT.json').read_bytes(),'CLAIM_NOT_PERSISTED')
    packet=gz(Path(inputs)/f'{per}.json.gz');old.inherited.packet_check(per,packet)
    put(out/'EXECUTION_STARTED.json',dict(claim_commit=head,remote_readback_sha=remote,time_ns=time.time_ns(),owner_run=at['owner_run']))
    v=read(ROOT/OUT/'BUDGET.json');need(v['cumulative_actual_evaluations']==84+j,'ACTUAL_EVALUATION_COUNTER')
    if per=='DEV2025':
        need(v['cumulative_actual']==52+c.MODES.index(mode),'ACTUAL_CANDIDATE_COUNTER')
        v['cumulative_actual']+=1;v['new_candidate_runs']+=1
        v['candidate_trials'].append(dict(ordinal=s['candidate_ordinals'][mode],candidate=c.RULES[mode],first_evaluation=85+j,scope=SCOPE))
    v['cumulative_actual_evaluations']+=1;v[KEY]['started']+=1
    v['trials'].append(dict(at,status='STARTED',actual_experiment_ordinal=85+j));save_budget(v)
    try:
        raw,result,comp=run_one(mode,per,packet,s)
        p.write_new(out/'RAW.json.gz',gzip.compress(p.canonical(raw),mtime=0));p.write_new(out/'RESULT.json.gz',gzip.compress(p.canonical(result),mtime=0))
        put(out/'ACCOUNTING_C51.json',comp);put(out/'ACCOUNTING_KR3.json',a.compare(old.base(per),result))
        put(out/'RECEIPT.json',dict(status='COMPLETED',mode=mode,period=per,result_sha256=h(out/'RESULT.json.gz'),raw_sha256=h(out/'RAW.json.gz'),spec_sha256=h(ROOT/OUT/'SPEC.json'),claim_commit=head,metrics=a.snapshot(result)))
        v[KEY]['completed']+=1;v['trials'][-1]['status']='COMPLETED';save_budget(v)
        print(json.dumps(a.snapshot(result),sort_keys=True))
    except BaseException as exc:
        put(out/'FAILURE.json',dict(status='FAILED_CONSUMED',error=str(exc),traceback=traceback.format_exc(),retry=False))
        v[KEY]['failed']+=1;v['trials'][-1]['status']='FAILED_CONSUMED';save_budget(v);raise

def checks(ps,cs):
    return {'WR_up':ps['win_rate'] is not None and cs['win_rate'] is not None and cs['win_rate']>ps['win_rate'],
        'terminal_net_up':cs['terminal_net_bps']>ps['terminal_net_bps'],
        'cost2_up':cs['terminal_cost2x_net_bps']>ps['terminal_cost2x_net_bps'],
        'daily_DD_down':cs['marked_DD_trade_sum_bps']<ps['marked_DD_trade_sum_bps']}

def summarize():
    verify_spec();data={};lines=['# C51 ADX/DMI and ATR entry factorial — measured USED_DEV','',
      'C51 preserved, three fixed hypotheses; same nominal trade-bps, terminal open marks included, no account return/G5/OOS claim.','',
      '|Period|Mode|Closed/open|WR %|Payoff|PF|Terminal net|Cost2|Daily marked DD|Net delta vs C51|',
      '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for per in old.PERIODS:
        ps=a.snapshot(baseline(per));data[per]={'C51':ps}
        for mode in ('C51',)+c.MODES:
            s=ps if mode=='C51' else a.snapshot(gz(ROOT/OUT/mode/per/'RESULT.json.gz'))
            if mode!='C51':data[per][mode]=dict(snapshot=s,checks=checks(ps,s),delta=s['terminal_net_bps']-ps['terminal_net_bps'],accounting=read(ROOT/OUT/mode/per/'ACCOUNTING_C51.json'))
            def fmt(x):return 'NA' if x is None else f'{x:.2f}'
            lines.append('|'+ '|'.join([per,mode,f"{s['closed']}/{s['open']}",fmt(None if s['win_rate'] is None else 100*s['win_rate']),fmt(s['realized_payoff']),fmt(s['PF']),fmt(s['terminal_net_bps']),fmt(s['terminal_cost2x_net_bps']),fmt(s['marked_DD_trade_sum_bps']),fmt(s['terminal_net_bps']-ps['terminal_net_bps'])])+'|')
        data[per]['AB_net_interaction']=data[per]['AB']['delta']-data[per]['A']['delta']-data[per]['B']['delta']
    decisions={m:('DEVELOPMENT_GOAL_MET' if all(all(data[per][m]['checks'].values()) for per in old.PERIODS)
                 else 'TRADEOFF' if all(data[per][m]['checks']['terminal_net_up'] and data[per][m]['checks']['cost2_up'] for per in old.PERIODS)
                 else 'REJECT_NO_CUMULATIVE_ADOPTION') for m in c.MODES}
    put(ROOT/OUT/'SUMMARY.json',dict(scope=SCOPE,decisions=decisions,periods=data,candidates=55,evaluations=90,new_candidates=3,new_full=6,parent_replay=0,independent=False,formal_credit=0))
    lines+=['',json.dumps(decisions,sort_keys=True),'','A/B/AB were frozen before any outcome. Constants are research hypotheses, not optimal values or SSOT thresholds.',
        'Signal-pool/reference parity checked; unchanged exit rules do not imply unchanged FULL entries. All vetoes and new/removed/open contribution are in per-cell accounting.',
        'Cost model/20bps floor and C51 profit protection are unchanged. No RVOL, SL/TP/sizing or timeframe change. No automatic successor or retuning.',
        'Stored C51 remains a development reference; any suggested new benchmark needs explicit interpretation, never automatic live adoption.','']
    (ROOT/OUT/'REPORT.md').write_text('\n'.join(lines));print('\n'.join(lines))

if __name__=='__main__':
    q=argparse.ArgumentParser();q.add_argument('action',choices=['freeze','reserve','execute','summarize']);q.add_argument('--inputs');q.add_argument('--mode',choices=c.MODES);q.add_argument('--period',choices=old.PERIODS);q.add_argument('--remote-sha');x=q.parse_args()
    if x.action=='freeze':freeze(x.inputs)
    elif x.action=='reserve':reserve(x.mode,x.period)
    elif x.action=='execute':execute(x.mode,x.period,x.inputs,x.remote_sha)
    else:summarize()
