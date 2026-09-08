"""One profit-zone exit hypothesis, two used-period FULLs, no auto successor.
Runtime reservation is persisted/read back by workflow before each execution.
"""
from __future__ import annotations
import argparse,gzip,hashlib,json,os,subprocess,sys,time,traceback
from pathlib import Path
from copy import deepcopy
from backend.research.rebuild import kr3_profit_zone_exit_v1 as c
from backend.research.rebuild import kr3_d2_failure_study_v1 as inherited
p,a=inherited.p,inherited.a
ROOT=p.ROOT
SCOPE='KR3_PROFIT_ZONE_PRESERVATION_AFTER_PR1223_V1'
OUT='research/development_evidence/'+SCOPE
PRIOR='research/development_evidence/KR3_WHOLE_FAILURE_AFTER_PR1221_V1/BUDGET.json'
PERIODS=('DEV2025','SEEN2026')
KEY='kr3_profit_zone_allocation'

def read(path):return json.loads(Path(path).read_bytes())
def gz(path):return json.loads(gzip.decompress(Path(path).read_bytes()))
def h(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def need(ok,reason):
    if not ok:raise ValueError(reason)
def put(path,value):return p.write_new(Path(path),p.canonical(value))
def save_budget(value):
    path=ROOT/OUT/'BUDGET.json';tmp=path.with_suffix('.pending')
    with tmp.open('xb') as f:f.write(p.canonical(value));f.flush();os.fsync(f.fileno())
    os.replace(tmp,path)
def base(period):
    return a.normalize_kr3(gz(ROOT/'research/development_evidence/FOCUSED_REPAIR_20260907_V1/KR3'/f'{period}.json.gz'))
def comparator_paths():
    return {period:{
        'KR3':'research/development_evidence/FOCUSED_REPAIR_20260907_V1/KR3/'+period+'.json.gz',
        'D':p.CAMPAIGN+('/MECHANISM_SEPARATION/W6_RECHECK_SHIFTED_EXIT_ANCHOR/RESULT.json.gz' if period=='DEV2025' else '/D_PARENT_2026/RESULT.json.gz'),
        'D2':p.CAMPAIGN+'/D2_FAILURE/'+period+'/RESULT.json.gz',
        'CANDIDATE50':'research/development_evidence/KR3_WHOLE_FAILURE_AFTER_PR1221_V1/'+period+'/RESULT.json.gz',
    } for period in PERIODS}

def dependencies():
    old=read(ROOT/p.CAMPAIGN/'D2_FAILURE/SPEC.json')
    for name,digest in old['files_sha256'].items():need(h(ROOT/name)==digest,'INHERITED_SOURCE_DRIFT:'+name)
    result=dict(old['files_sha256'])
    for name in ('kr3_profit_zone_exit_v1.py','kr3_profit_zone_study_v1.py','test_kr3_profit_zone_exit_v1.py'):
        rel='backend/research/rebuild/'+name;result[rel]=h(ROOT/rel)
    for name in ('verify_saved.py','test_verify_saved.py'):
        rel=OUT+'/'+name;result[rel]=h(ROOT/rel)
    for name in ('REQUEST.txt','AUTHORITY.json','DUPLICATE_RULE_AUDIT.json','PRE_OUTCOME_WORKFLOW.yml'):
        rel=OUT+'/'+name;result[rel]=h(ROOT/rel)
    return result

def prepare(source,out):
    from backend.research.rebuild import step7_kr3_dev_evidence_v1 as e
    from backend.research.rebuild import q0_b_seen_adapter_v1 as q
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    rows,policy,costs,lineage=e.load_dev_slice(source)
    dev={'rows_by':rows,'policy':policy,'costs':costs,'lineage':lineage}
    contract=read(ROOT/'research/development_evidence/Q0_B_SEEN_2026_V1/SPEC.json')
    policy,metadata,rows,access=q.load_seen_inputs(str(source),contract)
    seen={'rows_by':rows,'policy':policy,'costs':metadata['cost_by_symbol'],'lineage':{'source_ref':e.DATA_REF,'access':access,'independent':False}}
    for period,value in zip(PERIODS,(dev,seen)):
        inherited.packet_check(period,value)
        p.write_new(out/f'{period}.json.gz',gzip.compress(p.canonical(value),mtime=0))
    print('EXACT_ORIGINAL_USED_PREFIXES_READY_NO_REPLAY')

def freeze(inputs):
    budget=read(ROOT/PRIOR)
    need((budget['cumulative_actual'],budget['cumulative_actual_evaluations'])==(50,80),'LATEST_HISTORY_NOT50_80')
    need(KEY not in budget,'SCOPE_ALREADY_EXISTS')
    previous=read(ROOT/p.CAMPAIGN/'D2_FAILURE/SPEC.json')
    packets={period:gz(Path(inputs)/f'{period}.json.gz') for period in PERIODS}
    for period,v in packets.items():inherited.packet_check(period,v)
    spec={'scope':SCOPE,'candidate':c.RULE_ID,'candidate_ordinal':51,'evaluation_ordinals':[81,82],
      'rule':c.RULE,'parent':'KELTNER_KR3_PRIOR_SUPPRESSED_BREACH_EXTENSION_VETO_DEV_V1',
      'input_hashes':inherited.BINDINGS,'cost_hash':inherited.COST,'periods':previous['periods'],
      'source_files_sha256':dependencies(),'prior_budget_sha256':h(ROOT/PRIOR),
      'baseline_sha256':{period:h(ROOT/'research/development_evidence/FOCUSED_REPAIR_20260907_V1/KR3'/f'{period}.json.gz') for period in PERIODS},
      'saved_comparator_paths':comparator_paths(),
      'saved_comparator_sha256':{period:{name:h(ROOT/path) for name,path in paths.items()} for period,paths in comparator_paths().items()},
      'input_packet_sha256':{period:h(Path(inputs)/f'{period}.json.gz') for period in PERIODS},
      'selection':'User-approved one causal EMA20 profit-zone protection hypothesis. Original KR3 direct parent; no candidate50 failure exit, D waiting/requalification or moved anchor. Both periods USED_DEV; no threshold search; no independent credit.',
      'maximum_new_candidates':1,'maximum_full_evaluations':2,'retry':False,'independent':False,'formal_credit':0,
      'development_objective':['win_rate_strictly_increases_each_period','terminal_net_strictly_increases_each_period','all_cost2_strictly_increases_each_period','daily_marked_DD_strictly_decreases_each_period'],
      'objective_semantics':'All four strict checks must hold in BOTH USED_DEV periods; zero-net closed trades are flat, opens never wins. Development goal only; no G5/operating SSOT change.',
      'classification':{'DEVELOPMENT_GOAL_MET':'all eight strict checks true','REJECT':'terminal net and cost2 fail to increase in BOTH periods','TRADEOFF':'otherwise when joint goal fails; no promotion'},
      'decision_cost':'Original common model fee/spread/impact plus funding settlements elapsed at decision close only, unchanged 20bps floor; no final holding duration/cost in earlier signal.',
      'risk_and_authority':'No changed SL/TP sizing, D waiting/recheck, shifted anchors, leverage, live/order/OOS or paid model authority.',
      'cost_semantics':p.old.COST_SEMANTICS,'source_ref':'6d6335d1c9ad7ecb1e9597da85c2eb87635561e1',
      'code_commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True,cwd=ROOT).strip(),
      'frozen_at_ns':time.time_ns()}
    put(ROOT/OUT/'SPEC.json',spec)
    need(packets['DEV2025']['costs']==packets['SEEN2026']['costs'],'COST_BINDING_PERIOD_MISMATCH')
    put(ROOT/OUT/'COSTS.json',packets['DEV2025']['costs'])
    budget[KEY]={'scope':SCOPE,'used':0,'completed':0,'failed':0,'max_executions':2,'max_candidates':1,'retry':False,'spec_sha256':h(ROOT/OUT/'SPEC.json')}
    put(ROOT/OUT/'BUDGET.json',budget)

def verify_spec(inputs=None):
    s=read(ROOT/OUT/'SPEC.json')
    need(s['source_files_sha256']==dependencies(),'FROZEN_CODE_CHANGED')
    need(s['prior_budget_sha256']==h(ROOT/PRIOR),'PREVIOUS_BUDGET_CHANGED')
    for period,digest in s['baseline_sha256'].items():
        need(digest==h(ROOT/'research/development_evidence/FOCUSED_REPAIR_20260907_V1/KR3'/f'{period}.json.gz'),'PARENT_RESULT_CHANGED')
    need(s['saved_comparator_paths']==comparator_paths(),'COMPARATOR_PATH_CHANGED')
    for period,paths in s['saved_comparator_paths'].items():
        for name,path in paths.items():need(h(ROOT/path)==s['saved_comparator_sha256'][period][name],'SAVED_COMPARATOR_CHANGED:'+period+':'+name)
    need(p.sha(read(ROOT/OUT/'COSTS.json'))==s['cost_hash'],'FROZEN_COSTS_CHANGED')
    if inputs:
        for period,digest in s['input_packet_sha256'].items():need(digest==h(Path(inputs)/f'{period}.json.gz'),'PACKET_CHANGED')
    return s

def reserve(period):
    s=verify_spec();j=PERIODS.index(period);budget=read(ROOT/OUT/'BUDGET.json');allocation=budget[KEY]
    need(allocation['used']==j and allocation['completed']==j,'PREVIOUS_RUN_NOT_COMPLETED_OR_DUPLICATE')
    need(budget['cumulative_actual_evaluations']==80+j,'COUNTER_CHANGED')
    need(not any(t['actual_experiment_ordinal']==81+j for t in budget['trials']),'DUPLICATE_ORDINAL')
    need(os.environ.get('GITHUB_RUN_ATTEMPT')=='1','NO_WORKFLOW_RETRY')
    attempt={'scope':SCOPE,'candidate':c.RULE_ID,'candidate_ordinal':51,'actual_experiment_ordinal':81+j,'period':period,
      'status':'RESERVED_BEFORE_EXECUTION','owner_run':os.environ['GITHUB_RUN_ID'],'spec_sha256':h(ROOT/OUT/'SPEC.json'),'time_ns':time.time_ns(),'retry':False}
    put(ROOT/OUT/period/'ATTEMPT.json',attempt)
    if j==0:
        need(budget['cumulative_actual']==50,'CANDIDATE_COUNTER_CHANGED')
        budget['cumulative_actual']=51;budget['new_candidate_runs']+=1
        budget['candidate_trials'].append({'ordinal':51,'candidate':c.RULE_ID,'first_evaluation':81,'scope':SCOPE})
    allocation['used']+=1;budget['cumulative_actual_evaluations']=81+j;budget['trials'].append(attempt)
    save_budget(budget)

def run_one(period,packet,spec):
    inherited.packet_check(period,packet);cal=spec['periods'][period];start,end=cal['start_ms'],cal['runoff_end_ms']
    raw_all={};out={k:[] for k in ['trades','open_observations','events','trace']};out['audit']={};out['reference_states']={}
    with p.native.sensitivity():
        for symbol,rows in sorted(packet['rows_by'].items()):
            bundle=p.d.build_bundle(rows,p.d.PARENT_SPEC,eval_start_ms=start,eval_end_ms=end)
            raw=c.replay(rows,bundle,eval_start_ms=start,eval_end_ms=end,cost_model=packet['costs'][symbol])
            raw_all[symbol]=raw
            charged=p.account.charge_result(raw,symbol,'keltner_trend_main',c.RULE_ID,packet['policy'],packet['costs'],rows)
            for key in ('trades','open_observations','events','trace'):out[key].extend(charged[key])
            out['audit'][symbol]=raw['audit'];out['reference_states'][symbol]=raw['reference_checkpoint']
    parent=base(period)
    need(parent['reference_states']==out['reference_states'],'REFERENCE_RESERVATION_CHANGED')
    need({(e['symbol'],e['signal_index'],e['signal_ts']) for e in parent['events']}=={(e['symbol'],e['signal_index'],e['signal_ts']) for e in out['events']},'ORIGINAL_SIGNAL_POOL_CHANGED')
    out.update(scope=SCOPE,candidate=c.RULE_ID,period=period,independent=False,formal_credit=0,spec_sha256=h(ROOT/OUT/'SPEC.json'))
    out['metrics']=p.old.metrics(out['trades'],out['open_observations'],cal,packet['rows_by'],packet['costs'])
    comparison=a.compare(parent,out);comparison['comparison_type']='KR3_EXIT_ONLY_FULL_REPLAY'
    return raw_all,out,comparison

def execute(period,inputs,remote):
    s=verify_spec(inputs);b=ROOT/OUT/period;at=read(b/'ATTEMPT.json')
    head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    need(head==remote and at['owner_run']==os.environ['GITHUB_RUN_ID'],'REMOTE_CLAIM_OWNER_MISMATCH')
    need(os.environ.get('GITHUB_RUN_ATTEMPT')=='1' and at['period']==period and at['status']=='RESERVED_BEFORE_EXECUTION','NO_RETRY_OR_INVALID_ATTEMPT')
    need(at['spec_sha256']==h(ROOT/OUT/'SPEC.json'),'RESERVATION_SPEC_CHANGED')
    need(subprocess.check_output(['git','show',head+':'+str((b/'ATTEMPT.json').relative_to(ROOT))],cwd=ROOT)==(b/'ATTEMPT.json').read_bytes(),'CLAIM_NOT_COMMITTED')
    put(b/'EXECUTION_STARTED.json',{'claim_commit':head,'remote_readback_sha':remote,'time_ns':time.time_ns(),'pid':os.getpid(),'owner_run':at['owner_run']})
    budget=read(ROOT/OUT/'BUDGET.json')
    try:
        raw,result,compare=run_one(period,gz(Path(inputs)/f'{period}.json.gz'),s)
        p.write_new(b/'RAW.json.gz',gzip.compress(p.canonical(raw),mtime=0))
        digest=p.write_new(b/'RESULT.json.gz',gzip.compress(p.canonical(result),mtime=0))
        put(b/'ACCOUNTING.json',compare)
        put(b/'RECEIPT.json',{'status':'COMPLETED','period':period,'result_sha256':digest,'raw_sha256':h(b/'RAW.json.gz'),
             'spec_sha256':h(ROOT/OUT/'SPEC.json'),'claim_commit':head,'finished_ns':time.time_ns(),'metrics':a.snapshot(result),'formal_credit':0})
        budget[KEY]['completed']+=1;budget['trials'][-1]['status']='COMPLETED';save_budget(budget)
        print(json.dumps(a.snapshot(result),sort_keys=True))
    except BaseException as exc:
        put(b/'FAILURE.json',{'status':'FAILED_CONSUMED','error':str(exc),'traceback':traceback.format_exc(),'retry':False})
        budget[KEY]['failed']+=1;budget['trials'][-1]['status']='FAILED_CONSUMED';save_budget(budget)
        raise

def objective_checks(parent, child):
    return {'WR_up':child['win_rate']>parent['win_rate'],
        'terminal_net_up':child['terminal_net_bps']>parent['terminal_net_bps'],
        'cost2_up':child['terminal_cost2x_net_bps']>parent['terminal_cost2x_net_bps'],
        'daily_DD_down':child['marked_DD_trade_sum_bps']<parent['marked_DD_trade_sum_bps']}


def summarize():
    verify_spec();data={};rows=[]
    for period in PERIODS:
        parent=base(period);child=gz(ROOT/OUT/period/'RESULT.json.gz');ps,cs=a.snapshot(parent),a.snapshot(child)
        compare=read(ROOT/OUT/period/'ACCOUNTING.json')
        snapshots={'KR3':ps,'PROFIT_ZONE':cs}
        for label,path in comparator_paths()[period].items():
            if label!='KR3':snapshots[label]=a.snapshot(gz(ROOT/path))
        data[period]={'parent':ps,'child':cs,'net_delta':cs['terminal_net_bps']-ps['terminal_net_bps'],
          'cost2_delta':cs['terminal_cost2x_net_bps']-ps['terminal_cost2x_net_bps'],
          'DD_delta':cs['marked_DD_trade_sum_bps']-ps['marked_DD_trade_sum_bps'],
          'WR_delta_percentage_points':100*(cs['win_rate']-ps['win_rate']),
          'signal_reference_parity':True,'comparison':compare,'snapshots':snapshots,
          'checks':objective_checks(ps,cs)}
        for label,s in snapshots.items():
            rows.append('|'+ '|'.join([period,label,f"{s['closed']}/{s['open']}",f"{100*s['win_rate']:.2f}",
                f"{s['average_win_bps']:.2f}",f"{s['average_loss_bps']:.2f}",f"{s['realized_payoff']:.3f}",
                f"{s['PF']:.3f}",f"{s['terminal_net_bps']:.2f}",f"{s['terminal_cost2x_net_bps']:.2f}",
                f"{s['marked_DD_trade_sum_bps']:.2f}"])+ '|')
    passed=all(all(x['checks'].values()) for x in data.values())
    rejected=all(not x['checks']['terminal_net_up'] and not x['checks']['cost2_up'] for x in data.values())
    verdict='DEVELOPMENT_GOAL_MET' if passed else 'REJECT' if rejected else 'TRADEOFF'
    summary={'scope':SCOPE,'verdict':verdict,'joint_development_goal_met':passed,'periods':data,
        'formal_credit':0,'independent':False,'candidate_total':51,'evaluation_total':82,
        'new_full_runs':2,'parent_replays':0,'new_collection':0,'paid_AI':0,'orders':0}
    put(ROOT/OUT/'SUMMARY.json',summary)
    lines=['# KR3 profit-zone preservation — two USED_DEV periods','',c.RULE,'',
      '**Verdict: '+verdict+'**. User joint development goal requires WR/net/cost2 strictly higher AND daily marked DD strictly lower in each period.',
      'Equal notional trade-bps including hypothetical open marks, not account returns. Both periods USED_DEV; no independent or formal credit.',
      'Single candidate51, two FULL evaluations81/82. KR3/D/D2/candidate50 are stored comparators only; no parent/FIXED economic replay.','',
      '|Period|Rule|Closed/open|WR%|Avg win|Avg loss|Payoff|PF|Terminal net|All-cost2|Daily marked DD|',
      '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|',*rows,'',
      'Prespecified strict checks: '+json.dumps({k:v['checks'] for k,v in data.items()},sort_keys=True),'',
      'Full common/new/removed/closed-open attribution, loss-to-win/win-to-loss, ordinary and large winner damage, loss streaks, exposure and symbol/event concentration are in SUMMARY.json and period ACCOUNTING.json.',
      'Original entry rules and signal/reference pool are preserved; identical FULL admission sets are not assumed. Changed occupancy is included in attribution.',
      'Research activation cost uses fee/spread/impact plus funding elapsed at decision close and a20bps floor. Final trade funding is never supplied as an earlier decision feature. Cost estimates are historical DEV proxies, not actual fills or live fee/funding evidence.',
      'Protection triggers at completed close against the prior line; exit is next open, including adverse gaps. A protected line is not a guaranteed execution price. No next open inside the window means pending/censored.',
      'Daily DD is based on the frozen daily marked aggregate; no intrabar liquidation or worst intrabar account-DD claim. Open marks are hypothetical and excluded from win rate/PF and winner labels.',
      'No G5 or operating SSOT change, live promotion, new collection, OOS or paid AI. No parameter retry or auto follow-up trial.',
      'This result report precedes final review/CI/merge closure; closing checks read saved outputs and synthetic tests only.']
    p.write_new(ROOT/OUT/'REPORT.md','\n'.join(lines).encode())
    files={str(path.relative_to(ROOT/OUT)):h(path) for path in sorted((ROOT/OUT).rglob('*'))
        if path.is_file() and path.name not in ('FINAL_HASHES.json',) and '__pycache__' not in path.parts}
    put(ROOT/OUT/'FINAL_HASHES.json',files)
    print('\n'.join(lines))

if __name__=='__main__':
    q=argparse.ArgumentParser();q.add_argument('action',choices=['prepare','freeze','reserve','execute','summarize']);q.add_argument('--source');q.add_argument('--inputs');q.add_argument('--period',choices=PERIODS);q.add_argument('--remote-sha');x=q.parse_args()
    if x.action=='prepare':prepare(x.source,x.inputs)
    elif x.action=='freeze':freeze(x.inputs)
    elif x.action=='reserve':reserve(x.period)
    elif x.action=='execute':execute(x.period,x.inputs,x.remote_sha)
    else:summarize()
