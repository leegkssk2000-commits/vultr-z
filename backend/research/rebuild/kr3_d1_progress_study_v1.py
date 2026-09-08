"""Finite D1 study. Reserve+push precedes execution; no retry and no formal credit."""
from __future__ import annotations
import argparse,gzip,hashlib,json,os,subprocess,sys,time
from copy import deepcopy
from pathlib import Path
from backend.research.rebuild import kr3_d1_progress_requal_v1 as c
from backend.research.rebuild import step7_kr3_winner_accounting_v1 as a
p=c.p;ROOT=p.ROOT
SCOPE='KR3_D1_PROGRESS_REQUAL_AFTER_PR1216_V1'
OUT=p.CAMPAIGN+'/D1_PROGRESS'
RUNS=('DEV2025','SEEN2026')
KEY='kr3_d1_progress_allocation'
BINDINGS={'DEV2025':{'rows_by':'3cb1bbeb6166a1ae3b32bb9a832faeee579a5d208ecfbfd4bf86004786c70e3a','policy':'d686c9bbcee0515d265d66ea789221b078ecb9aaeafd6c7070810a4a66775552'},'SEEN2026':{'rows_by':'406e72401bec107c31ac17fd9742489f5980ca411b0f848613692fd2d00d29af','policy':'dc08e55afdb1fbf2b952bf9baed3a25a2ebcf7c1b3abed4e0b97f73e5d8ce031'}}
COST='e7b29de0b1810d14e02847917e951301f4d9a30da190ed7c6fc4cafbca581020'

def need(ok,reason):
    if not ok:raise ValueError(reason)
def deps():
    out=p.dependencies()
    for name in ('kr3_d1_progress_requal_v1.py','kr3_d1_progress_study_v1.py','step7_kr3_winner_accounting_v1.py','break_channel_q1_metrics_v1.py'):
        path='backend/research/rebuild/'+name;out[path]=hashlib.sha256((ROOT/path).read_bytes()).hexdigest()
    return out

def freeze():
    return p.native.contracts.seal({'scope':SCOPE,'candidate_id':c.CANDIDATE,'rule':c.RULE,'parent':c.ORIGINAL_D,
       'runs':list(RUNS),'max_candidates':1,'max_executions':2,'candidate_ordinal':46,'evaluation_ordinals':[65,66],
       'input_hashes':BINDINGS,'cost_hash':COST,'files_sha256':deps(),
       'periods':{'DEV2025':{'start_ms':1734595200000,'runoff_end_ms':1766995200000},'SEEN2026':{'start_ms':1778198400000,'runoff_end_ms':1788566400000}},
       'selection':'One rule chosen after both USED_DEV parent outcomes and admission observations. No independent claim. No alternative thresholds scanned.',
       'development_checks':['positive_terminal_net_each_period','positive_all_cost2_each_period','terminal_net_not_worse_than_D_each_period','all_cost2_not_worse_than_D_each_period','marked_DD_not_worse_than_D_each_period'],
       'winner_loss_reporting':'All D and KR3 completed winner capped profit, lost/recovered/new losses, common/removed/new/closed-open exact reconciliation; no future labels in candidate',
       'controls':'Exact saved D direct parent and saved KR3 inheritance comparator. No parent replay.',
       'cost_semantics':p.old.COST_SEMANTICS,'initial_SL':None,'fixed_TP':None,
       'formal_credit':0,'independent':False,'G5A_pass':False,'retry':False,'new_collection':0,'paid_AI':0,'orders':0})
def verify(spec):
    need(p.native.contracts.check_seal(spec) and spec==freeze(),'SPEC_CODE_RULE_DRIFT')
    old=json.loads((ROOT/p.CAMPAIGN/'D_PARENT_2026/SPEC.json').read_bytes())
    for path,h in p.dependencies().items():need(old['files_sha256'].get(path)==h,'ORIGINAL_D_DEPENDENCY_DRIFT:'+path)
def packet_check(period,packet):
    need(period in RUNS,'UNKNOWN_PERIOD')
    for key,h in BINDINGS[period].items():need(p.sha(packet[key])==h,'INPUT_DRIFT:'+key)
    need(p.sha(packet['costs'])==COST,'COST_DRIFT')

def reserve(period,spec):
    verify(spec);i=RUNS.index(period);bp=ROOT/p.BUDGET;budget=json.loads(bp.read_bytes())
    need(budget['cumulative_actual_evaluations']==64+i,'COUNTER_OR_PRIOR_ATTEMPT_CHANGED')
    if i==0:
        need(KEY not in budget and budget['cumulative_actual']==45,'EXISTING_CANDIDATE_OR_SCOPE')
        budget[KEY]={'scope':SCOPE,'used':0,'completed':0,'max_executions':2,'max_candidates':1,'specification_sha256':spec['receipt_sha256'],'no_retry':True}
        budget['cumulative_actual']=46;budget['new_candidate_runs']+=1
        budget['candidate_trials'].append({'ordinal':46,'candidate':c.CANDIDATE,'scope':SCOPE,'first_evaluation':65,'specification_sha256':spec['receipt_sha256']})
    else:
        need(budget['cumulative_actual']==46 and budget[KEY]['used']==1 and budget[KEY]['completed']==1,'PREVIOUS_PERIOD_INCOMPLETE')
    need(not any(t['actual_experiment_ordinal']==65+i for t in budget['trials']),'DUPLICATE_ORDINAL')
    at={'scope':SCOPE,'period':period,'actual_experiment_ordinal':65+i,'candidate_ordinal':46,'specification_sha256':spec['receipt_sha256'],'status':'RESERVED_BEFORE_EXECUTION_PUSH_REQUIRED','github_run_id':os.environ.get('GITHUB_RUN_ID'),'github_run_attempt':os.environ.get('GITHUB_RUN_ATTEMPT'),'started_ns':time.time_ns(),'no_retry':True}
    p.write_new(ROOT/OUT/period/'ATTEMPT.json',p.canonical(at))
    budget['trials'].append(at);budget[KEY]['used']+=1;budget['cumulative_actual_evaluations']=65+i
    bp.write_text(json.dumps(budget,indent=2,sort_keys=True)+'\n')

def run_one(period,packet,spec):
    verify(spec);packet_check(period,packet);calendar=spec['periods'][period];start,end=calendar['start_ms'],calendar['runoff_end_ms']
    out={k:[] for k in ('trades','open_observations','events','trace','reference_opportunities','reference_events')};out['audit']={}
    with p.native.sensitivity():
        for symbol,rows in sorted(packet['rows_by'].items()):
            bundle=p.d.build_bundle(rows,p.d.PARENT_SPEC,eval_start_ms=start,eval_end_ms=end)
            raw=c.replay_symbol(rows,bundle,start=start,end=end)
            charged=p.account.charge_result(raw,symbol,'keltner_trend_main',c.CANDIDATE,packet['policy'],packet['costs'],rows)
            for category in ('trades','open_observations','events','trace'):
                for row in charged[category]:
                    index=row.get('original_signal_index',row.get('signal_index'))
                    row.update(mechanism_origin_id=f'{symbol}:{rows[index]["bar_close_ts"]}',d1_specification_sha256=spec['receipt_sha256'])
                    sk='trade_sha256' if category=='trades' else 'observation_sha256' if category=='open_observations' else None
                    if sk:row.pop(sk,None);row[sk]=p.account.old.digest(row)
                out[category].extend(charged[category])
            for category in ('reference_opportunities','reference_events'):out[category].extend(dict(x,symbol=symbol) for x in raw[category])
            out['audit'][symbol]=raw['audit']
    out.update(scope=SCOPE,period=period,candidate_id=c.CANDIDATE,specification_sha256=spec['receipt_sha256'],formal_credit=0,independent=False)
    out['metrics']=p.old.metrics(out['trades'],out['open_observations'],calendar,packet['rows_by'],packet['costs'])
    return out

def execute(period,packet,spec):
    verify(spec);packet_check(period,packet);b=ROOT/OUT/period
    attempt=(b/'ATTEMPT.json').read_bytes();at=json.loads(attempt)
    need(at['github_run_id']==os.environ.get('GITHUB_RUN_ID') and at['github_run_attempt']=='1','RESERVATION_OWNER')
    head=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
    need(head==os.environ.get('ZEL_D1_RESERVATION_COMMIT'),'RESERVATION_COMMIT_REQUIRED')
    need(subprocess.check_output(['git','show',head+':'+OUT+'/'+period+'/ATTEMPT.json'])==attempt,'RESERVATION_NOT_COMMITTED')
    # Workflow checks the remote branch equals this commit after pushing. A
    # local receipt is never treated as proof of that remote persistence.
    p.write_new(b/'EXECUTION_STARTED.json',p.canonical({'reservation_commit':head,'run':os.environ['GITHUB_RUN_ID'],'time_ns':time.time_ns()}))
    result=run_one(period,packet,spec)
    digest=p.write_new(b/'RESULT.json.gz',gzip.compress(p.canonical(result),mtime=0))
    p.write_new(b/'RECEIPT.json',p.canonical({'scope':SCOPE,'period':period,'status':'COMPLETED','result_sha256':digest,'specification_sha256':spec['receipt_sha256'],'reservation_commit':head,'metrics':a.snapshot(result),'runtime':sys.version,'formal_credit':0}))
    bp=ROOT/p.BUDGET;budget=json.loads(bp.read_bytes());budget[KEY]['completed']+=1
    bp.write_text(json.dumps(budget,indent=2,sort_keys=True)+'\n')
    print(json.dumps(a.snapshot(result),sort_keys=True))

def saved_check(spec):
    verify(spec);found=0
    for period in RUNS:
        b=ROOT/OUT/period
        if not (b/'ATTEMPT.json').exists():continue
        need((b/'RECEIPT.json').exists(),'RESERVED_OR_UNKNOWN_NOT_COMPLETE:'+period)
        receipt=json.loads((b/'RECEIPT.json').read_bytes());raw=(b/'RESULT.json.gz').read_bytes()
        need(hashlib.sha256(raw).hexdigest()==receipt['result_sha256'],'RESULT_BYTES_DRIFT')
        value=json.loads(gzip.decompress(raw));need(value['specification_sha256']==spec['receipt_sha256'],'RESULT_SPEC_DRIFT')
        need(a.snapshot(value)==receipt['metrics'],'STORED_METRICS_DRIFT');found+=1
    return {'completed':found,'expected':2,'formal_pass':False,'economic_replays':0}

def summarize():
    def read(path):return json.loads(gzip.decompress(path.read_bytes()))
    base=ROOT/p.CAMPAIGN;out={};table=[]
    for period in RUNS:
        d=read(base/('MECHANISM_SEPARATION/W6_RECHECK_SHIFTED_EXIT_ANCHOR/RESULT.json.gz' if period=='DEV2025' else 'D_PARENT_2026/RESULT.json.gz'))
        kr3=a.normalize_kr3(read(ROOT/'research/development_evidence/FOCUSED_REPAIR_20260907_V1/KR3'/f'{period}.json.gz'))
        child=read(ROOT/OUT/period/'RESULT.json.gz')
        sd,sc=a.snapshot(d),a.snapshot(child)
        checks={'positive_terminal_net':sc['terminal_net_bps']>0,'positive_all_cost2':sc['terminal_cost2x_net_bps']>0,'net_not_worse_D':sc['terminal_net_bps']>=sd['terminal_net_bps'],'cost2_not_worse_D':sc['terminal_cost2x_net_bps']>=sd['terminal_cost2x_net_bps'],'DD_not_worse_D':sc['marked_DD_trade_sum_bps']<=sd['marked_DD_trade_sum_bps']}
        out[period]={'D_to_D1':a.compare(d,child),'KR3_to_D1':a.compare(kr3,child),'repair_cohorts':a.repair_cohorts(kr3,d,child),'checks':checks,'snapshots':{n:a.snapshot(v) for n,v in [('KR3',kr3),('D',d),('D1',child)]}}
        for n,s in out[period]['snapshots'].items():table.append('|'+ '|'.join([period,n,f"{s['closed']}/{s['open']}",f"{s['win_rate']*100:.2f}",f"{s['realized_payoff']:.3f}",f"{s['PF']:.3f}",f"{s['terminal_net_bps']:.2f}",f"{s['terminal_cost2x_net_bps']:.2f}",f"{s['marked_DD_trade_sum_bps']:.2f}"])+ '|')
    p.write_new(ROOT/OUT/'ACCOUNTING.json',p.canonical(out))
    lines=['# D1 sixth-close progress requalification — actual reused DEV','',c.RULE,'','One new candidate46, two actual FULL evaluations65/66. KR3 and D results reused, not rerun.','All figures are equal fixed-notional trade-bps; no account-return claim. Both periods are USED_DEV and all inherited research cost-proxy limitations apply.','', '|Period|Rule|Closed/open|Win%|Payoff|PF|Terminal net|All-cost2|Marked DD|','|---|---|---:|---:|---:|---:|---:|---:|---:|']+table+['','## Prespecified development checks',json.dumps({k:v['checks'] for k,v in out.items()},indent=2),'','G5A HOLD and formal credit0 remain. Code/CI completion is not economic pass. No parameter retry, no new source/OOS/provider calls/orders.','Full original-signal attribution, lost/restored winners, reopened losses, exposure and symbol concentration: ACCOUNTING.json.','The prior missing HYPE/SOL winners were discovery diagnostics only; no per-symbol or historical outcome rules were used. Remote completion/merge is recorded separately.','']
    p.write_new(ROOT/OUT/'REPORT.md','\n'.join(lines).encode())

def main():
    pa=argparse.ArgumentParser();pa.add_argument('action',choices=['freeze','reserve','execute','verify','summarize']);pa.add_argument('--period',choices=RUNS);pa.add_argument('--input',type=Path);args=pa.parse_args()
    if args.action=='freeze':p.write_new(ROOT/OUT/'SPEC.json',p.canonical(freeze()));return
    spec=json.loads((ROOT/OUT/'SPEC.json').read_bytes())
    if args.action=='verify':print(json.dumps(saved_check(spec)));return
    if args.action=='summarize':summarize();return
    need(args.period is not None,'PERIOD_REQUIRED')
    if args.action=='reserve':reserve(args.period,spec)
    else:
        need(args.input is not None,'INPUT_REQUIRED');execute(args.period,json.loads(gzip.decompress(args.input.read_bytes())),spec)

if __name__=='__main__':main()
