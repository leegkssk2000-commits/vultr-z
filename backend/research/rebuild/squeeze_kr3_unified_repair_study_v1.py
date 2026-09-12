"""Issue #1292: no-outcome execution repair for frozen Squeeze/KR3 U1/U2/U3.

Only repaired implementation boundary: select packet['costs'][symbol] before child replay.
Candidate85/eval153 from #1291 stays FAILED_CONSUMED and is never reused.
"""
import argparse, json, os, subprocess, time, traceback
from math import fsum
from pathlib import Path

from backend.research.rebuild import squeeze_kr3_unified_v1 as child
from backend.research.rebuild import squeeze_kr3_unified_study_v1 as old
from backend.research.rebuild import c70_tm_capreuse_account_v1 as capacc
from backend.research.rebuild import c63_c70_trader_account_v1 as acct

ROOT=acct.ROOT
SCOPE='SQUEEZE_KR3_TRUE_COMPONENT_UNIFIED_EXECUTION_REPAIR_AFTER_1291_V1'
OUT=ROOT/'research/development_evidence'/SCOPE
OLD=ROOT/'research/development_evidence'/child.SCOPE
HISTORY=OLD/'BUDGET.json'
BRANCH='codex/squeeze-kr3-unified-repair-1292'
KEY='squeeze_kr3_unified_repair_1292_allocation'
PERIODS=('DEV2025','SEEN2026')
PLAN=[(v,p) for v in child.VARIANTS for p in PERIODS]
CANDIDATES={'U1':86,'U2':87,'U3':88}
EVALS={('U1','DEV2025'):154,('U1','SEEN2026'):155,
       ('U2','DEV2025'):156,('U2','SEEN2026'):157,
       ('U3','DEV2025'):158,('U3','SEEN2026'):159}

h=acct.h; read=acct.read; gz=acct.gz; put=acct.put

def need(ok,msg):
    if not ok: raise RuntimeError(msg)

def git(*args):
    return subprocess.check_output(['git',*args],cwd=ROOT,text=True,timeout=45).strip()

def atomic(path,obj):
    path=Path(path); tmp=path.with_suffix(path.suffix+'.pending')
    data=acct.canon(obj)+b'\n'
    with tmp.open('xb') as f:
        f.write(data); f.flush(); os.fsync(f.fileno())
    os.replace(tmp,path)

def owner():
    need(os.environ.get('GITHUB_RUN_ATTEMPT')=='1','NO_RETRY')
    need(os.environ.get('GITHUB_REF_NAME')==BRANCH,'BRANCH_OWNER')
    return os.environ['GITHUB_RUN_ID']

def symbol_cost(packet,symbol):
    costs=packet.get('costs')
    need(isinstance(costs,dict) and symbol in costs,'PER_SYMBOL_COST_MISSING:'+symbol)
    cost=costs[symbol]
    need(isinstance(cost,dict),'PER_SYMBOL_COST_NOT_DICT:'+symbol)
    for name in ('fee_bps','spread_bps','impact_bps','funding_p95_per_settlement_bps'):
        need(name in cost,'PER_SYMBOL_COST_FIELD:'+symbol+':'+name)
    return cost

def sources():
    paths=[
      'backend/research/rebuild/squeeze_kr3_unified_v1.py',
      'backend/research/rebuild/squeeze_kr3_unified_repair_study_v1.py',
      'backend/research/rebuild/test_squeeze_kr3_unified_repair_v1.py',
      'backend/research/rebuild/c70_tm_capreuse_v1.py',
      'backend/research/rebuild/c70_tm_capreuse_account_v1.py',
      'backend/research/rebuild/c63_c70_trader_management_v1.py',
      'backend/research/rebuild/kr3_c51_entry_context_v1.py',
      'backend/research/rebuild/kr3_profit_zone_exit_v1.py',
      'research/development_evidence/SQUEEZE_KR3_TRUE_COMPONENT_UNIFIED_EXECUTION_REPAIR_AFTER_1291_V1/DESIGN.md',
      'research/development_evidence/SQUEEZE_KR3_TRUE_COMPONENT_UNIFIED_AFTER_TOP6_V1/U1/DEV2025/FAILURE.json',
    ]
    return {p:h(ROOT/p) for p in paths}

def parent(per):
    return gz(capacc.OUT/per/'RESULT.json.gz')

def persist(message):
    git('add','--',str(OUT.relative_to(ROOT)))
    git('commit','-m',message+' [skip ci]')
    head=git('rev-parse','HEAD')
    git('push','origin','HEAD:refs/heads/'+BRANCH)
    remote=git('ls-remote','origin','refs/heads/'+BRANCH).split()[0]
    need(remote==head,'REMOTE_READBACK_MISMATCH')
    return head

def charge(raw_by,packet,cal,rule):
    result=dict(trades=[],open_observations=[],events=[],trace=[],audit={},candidate=rule,
                independent=False,formal_credit=0,operating_adoption=False)
    for symbol,rr in sorted(raw_by.items()):
        for raw in rr['trades']+rr['open_positions']:
            status,row=capacc.campaign(raw,symbol,packet)
            row['candidate']=rule
            row['evidence_type']='SQUEEZE_KR3_TRUE_COMPONENT_SYNTHESIS_USED_DEV'
            row.pop('trade_sha256',None); row.pop('observation_sha256',None)
            row['trade_sha256' if status=='C' else 'observation_sha256']=acct.p.sha(row)
            result['trades' if status=='C' else 'open_observations'].append(row)
        result['events'].extend(dict(e,symbol=symbol) for e in rr['events'])
        result['trace'].extend(dict(t,symbol=symbol) for t in rr['trace'])
        result['audit'][symbol]=rr['audit']
    result['metrics']=acct.metrics(result,packet,cal)
    return result

def freeze():
    need(os.environ.get('SKR1292_PREFLIGHT')=='PASSED','PREFLIGHT_REQUIRED')
    need(not (OUT/'SPEC.json').exists(),'ALREADY_FROZEN')
    history=read(HISTORY)
    need((history['cumulative_actual'],history['cumulative_actual_evaluations'])==(85,153),'HISTORY_NOT85_153')
    q0=history['squeeze_kr3_unified_1291_allocation']
    need((q0['reserved'],q0['started'],q0['completed'],q0['failed'])==(1,1,0,1),'OLD_FAILURE_STATE_DRIFT')
    need((OLD/'U1/DEV2025/FAILURE.json').exists(),'OLD_FAILURE_MISSING')
    need(not (OLD/'U1/DEV2025/RESULT.json.gz').exists(),'OLD_FAILURE_HAS_RESULT')
    need(KEY not in history,'DUPLICATE_ALLOCATION')
    capspec=read(capacc.OUT/'SPEC.json')
    packet_hashes={p:h(ROOT/acct.INPUTS/(p+'.json.gz')) for p in PERIODS}
    for p,digest in packet_hashes.items():
        need(digest==capspec['input_packet_sha256'][p],'INPUT_DRIFT:'+p)
    put(OUT/'HISTORY_PRIOR.json',history)
    spec=dict(schema='zel.squeeze_kr3.unified.repair.spec.v1',scope=SCOPE,issue=1292,
        predecessor_issue=1291,predecessor_failed_candidate=85,predecessor_failed_evaluation=153,
        predecessor_failure_sha256=h(OLD/'U1/DEV2025/FAILURE.json'),predecessor_economic_result_count=0,
        branch=BRANCH,owner_run=owner(),source_commit=git('rev-parse','HEAD'),frozen_ns=time.time_ns(),
        variants=list(child.VARIANTS),plan=[list(x) for x in PLAN],candidate_ordinals=CANDIDATES,
        evaluation_ordinals={v:{p:EVALS[(v,p)] for p in PERIODS} for v in child.VARIANTS},
        max_candidates=3,max_FULL=6,parent='C70_TM_CAPREUSE_V1_candidate82',
        parent_results_sha256={p:h(capacc.OUT/p/'RESULT.json.gz') for p in PERIODS},
        parent_snapshots_sha256={p:h(capacc.OUT/p/'SNAPSHOT.json') for p in PERIODS},
        input_packet_sha256=packet_hashes,periods=capspec['periods'],source_files_sha256=sources(),
        history_sha256=h(OUT/'HISTORY_PRIOR.json'),
        implementation_repair='packet.costs WHOLE_MAP -> packet.costs[symbol] ONLY',
        scientific_rules_changed=False,selection_objective='Highest combined terminal net across both USED_DEV periods; eligibility each period net>0,cost2>0,PF>=1; tie combined cost2,lower worst DD,weighted WR.',
        WR_is_hard_gate=False,formal_credit=0,used_DEV=True,Q_track_access=0,new_market=0,unused_OOS=0,
        paid_AI=0,orders=0,deploy=0,retry=False,automatic_successor=False)
    put(OUT/'SPEC.json',spec)
    history[KEY]=dict(scope=SCOPE,max_candidates=3,max_executions=6,reserved=0,started=0,completed=0,
        failed=0,remaining=6,retry=False,candidate_ordinals=CANDIDATES,evaluation_ordinals=list(range(154,160)))
    put(OUT/'BUDGET.json',history)
    put(OUT/'STATUS.json',dict(scope=SCOPE,state='PREPARED',owner_run=spec['owner_run'],formal_credit=0))
    print('SKR1292_FROZEN_NO_OUTCOME_REPAIR')

def check():
    spec=read(OUT/'SPEC.json')
    need(spec['owner_run']==owner(),'OWNER_CHANGED')
    need(spec['source_files_sha256']==sources(),'SOURCE_DRIFT')
    need(spec['history_sha256']==h(OUT/'HISTORY_PRIOR.json')==h(HISTORY),'HISTORY_DRIFT')
    for p in PERIODS:
        need(h(ROOT/acct.INPUTS/(p+'.json.gz'))==spec['input_packet_sha256'][p],'INPUT_DRIFT:'+p)
        need(h(capacc.OUT/p/'RESULT.json.gz')==spec['parent_results_sha256'][p],'PARENT_RESULT_DRIFT:'+p)
        need(h(capacc.OUT/p/'SNAPSHOT.json')==spec['parent_snapshots_sha256'][p],'PARENT_SNAPSHOT_DRIFT:'+p)
    return spec

def reserve(v,p):
    spec=check(); j=PLAN.index((v,p)); b=read(OUT/'BUDGET.json'); q=b[KEY]
    need(q['reserved']==q['started']==q['completed']==j and q['failed']==0,'ALLOCATION_STATE')
    folder=OUT/v/p
    put(folder/'ATTEMPT.json',dict(scope=SCOPE,variant=v,period=p,candidate_ordinal=CANDIDATES[v],
        evaluation_ordinal=EVALS[(v,p)],state='RESERVED_NOT_STARTED',owner_run=spec['owner_run'],
        spec_sha256=h(OUT/'SPEC.json'),retry=False,time_ns=time.time_ns()))
    q['reserved']+=1; q['remaining']-=1; atomic(OUT/'BUDGET.json',b)
    return persist('Reserve repaired '+v+' '+p)

def execute(v,p,claim):
    spec=check(); j=PLAN.index((v,p)); folder=OUT/v/p
    need(git('ls-remote','origin','refs/heads/'+BRANCH).split()[0]==claim,'CLAIM_MOVED')
    b=read(OUT/'BUDGET.json'); q=b[KEY]
    need(q['reserved']==j+1 and q['started']==q['completed']==j and q['failed']==0,'BAD_EXECUTION_STATE')
    if p=='DEV2025':
        need(b['cumulative_actual']==CANDIDATES[v]-1,'CANDIDATE_ORDINAL')
        b['cumulative_actual']+=1
        b['new_candidate_runs']=b.get('new_candidate_runs',0)+1
        b['candidate_trials'].append(dict(candidate=child.RULES[v],ordinal=CANDIDATES[v],first_evaluation=EVALS[(v,p)],
            scope=SCOPE,execution_repair_after_no_output_candidate85=True))
    need(b['cumulative_actual_evaluations']==EVALS[(v,p)]-1,'EVALUATION_ORDINAL')
    b['cumulative_actual_evaluations']+=1; q['started']+=1
    b['trials'].append(dict(scope=SCOPE,candidate=child.RULES[v],variant=v,period=p,
        candidate_ordinal=CANDIDATES[v],evaluation_ordinal=EVALS[(v,p)],status='STARTED',retry=False))
    put(folder/'EXECUTION_STARTED.json',dict(scope=SCOPE,variant=v,period=p,claim_commit=claim,
        owner_run=spec['owner_run'],time_ns=time.time_ns()))
    atomic(OUT/'BUDGET.json',b); atomic(OUT/'STATUS.json',dict(scope=SCOPE,state='RUNNING',owner_run=spec['owner_run']))
    started=persist('Durably start repaired '+v+' '+p)
    try:
        packet=gz(ROOT/acct.INPUTS/(p+'.json.gz')); cal=spec['periods'][p]
        raw={}
        for symbol,rows in sorted(packet['rows_by'].items()):
            cost=symbol_cost(packet,symbol)
            raw[symbol]=child.replay(rows,eval_start_ms=cal['start_ms'],eval_end_ms=cal['runoff_end_ms'],
                                     cost=cost,variant=v)
        result=charge(raw,packet,cal,child.RULES[v]); parent_result=parent(p)
        snap=capacc.snapshot(result,parent_result); decomp=acct.decomposition(parent_result,result)
        put(folder/'RAW.json.gz',raw); put(folder/'RESULT.json.gz',result); put(folder/'SNAPSHOT.json',snap); put(folder/'DECOMPOSITION.json',decomp)
        put(folder/'RECEIPT.json',dict(state='COMPLETED',scope=SCOPE,variant=v,period=p,
            candidate_ordinal=CANDIDATES[v],evaluation_ordinal=EVALS[(v,p)],claim_commit=claim,started_commit=started,
            raw_sha256=h(folder/'RAW.json.gz'),result_sha256=h(folder/'RESULT.json.gz'),
            snapshot_sha256=h(folder/'SNAPSHOT.json'),decomposition_sha256=h(folder/'DECOMPOSITION.json'),formal_credit=0,retry=False))
        b=read(OUT/'BUDGET.json'); q=b[KEY]; q['completed']+=1; b['trials'][-1]['status']='COMPLETED'; atomic(OUT/'BUDGET.json',b)
        return persist('Persist repaired '+v+' '+p+' result')
    except BaseException as exc:
        put(folder/'FAILURE.json',dict(state='FAILED_CONSUMED',error=str(exc),traceback=traceback.format_exc(),retry=False))
        b=read(OUT/'BUDGET.json'); q=b[KEY]; q['failed']+=1; b['trials'][-1]['status']='FAILED_CONSUMED'; atomic(OUT/'BUDGET.json',b)
        atomic(OUT/'STATUS.json',dict(scope=SCOPE,state='CHECKPOINTED_BLOCKED',owner_run=spec['owner_run']))
        persist('Persist repaired consumed failure '+v+' '+p)
        raise

def _campaign_values(result):
    rows=result['trades']; wins=[float(t['net_bps']) for t in rows if float(t['net_bps'])>0]; losses=[float(t['net_bps']) for t in rows if float(t['net_bps'])<0]
    mw=fsum(wins)/len(wins) if wins else None; ml=fsum(losses)/len(losses) if losses else None
    return dict(closed=len(rows),wins=len(wins),losses=len(losses),win_rate=len(wins)/len(rows) if rows else None,
                PF=fsum(wins)/abs(fsum(losses)) if losses else None,payoff=mw/abs(ml) if mw is not None and ml else None)

def _one(label,p,result,snap):
    x=_campaign_values(result)
    x.update(label=label,period=p,open=snap['open'],terminal_net_bps=snap['terminal_net_bps'],
        terminal_cost2x_net_bps=snap['terminal_cost2x_net_bps'],marked_DD_bps=snap['marked_DD_trade_sum_bps'],
        ordinary_winner_retention=snap.get('ordinary_winner_retention'),top_decile_winner_retention=snap.get('top_decile_winner_retention'),
        loss_tail_worst_bps=snap.get('loss_tail_worst_bps'),loss_tail_worst_decile_mean_bps=snap.get('loss_tail_worst_decile_mean_bps'),
        quantity_exposure_symbol_days=snap.get('quantity_exposure_symbol_days'),mean_quantity_exposure_positions=snap.get('mean_quantity_exposure_positions'))
    return x

def _combined(label,pdata,results):
    rows=[t for r in results for t in r['trades']]; wins=[float(t['net_bps']) for t in rows if float(t['net_bps'])>0]; losses=[float(t['net_bps']) for t in rows if float(t['net_bps'])<0]
    mw=fsum(wins)/len(wins) if wins else None; ml=fsum(losses)/len(losses) if losses else None
    return dict(label=label,closed=len(rows),open=sum(x['open'] for x in pdata.values()),wins=len(wins),losses=len(losses),
        win_rate=len(wins)/len(rows) if rows else None,terminal_net_bps=fsum(x['terminal_net_bps'] for x in pdata.values()),
        terminal_cost2x_net_bps=fsum(x['terminal_cost2x_net_bps'] for x in pdata.values()),
        PF=fsum(wins)/abs(fsum(losses)) if losses else None,payoff=mw/abs(ml) if mw is not None and ml else None,
        worst_period_marked_DD_bps=max(x['marked_DD_bps'] for x in pdata.values()),per_period=pdata)

def _parent_combined():
    pdata={}; results=[]
    for p in PERIODS:
        r=parent(p); snap=read(capacc.OUT/p/'SNAPSHOT.json'); pdata[p]=_one('CAPREUSE',p,r,snap); results.append(r)
    return _combined('CAPREUSE',pdata,results)

def _child_combined(v):
    pdata={}; results=[]; decomps=[]; raws=[]
    for p in PERIODS:
        folder=OUT/v/p; receipt=read(folder/'RECEIPT.json')
        for name,key in [('RAW.json.gz','raw_sha256'),('RESULT.json.gz','result_sha256'),('SNAPSHOT.json','snapshot_sha256'),('DECOMPOSITION.json','decomposition_sha256')]:
            need(h(folder/name)==receipt[key],'SAVED_HASH:'+v+':'+p+':'+name)
        r=gz(folder/'RESULT.json.gz'); snap=read(folder/'SNAPSHOT.json'); pdata[p]=_one(v,p,r,snap); results.append(r)
        decomps.append(read(folder/'DECOMPOSITION.json')); raws.append(gz(folder/'RAW.json.gz'))
    c=_combined(v,pdata,results)
    c['eligible']=all(pdata[p]['terminal_net_bps']>0 and pdata[p]['terminal_cost2x_net_bps']>0 and pdata[p]['PF'] is not None and pdata[p]['PF']>=1 for p in PERIODS)
    c['k1_veto_T']=sum(sum(a.get('k1_veto_T',0) for a in raw['audit'].values()) for raw in raws)
    c['k2_arm_T']=sum(sum(a.get('k2_arm_T',0) for a in raw['audit'].values()) for raw in raws)
    c['k2_trigger_T']=sum(sum(a.get('k2_trigger_T',0) for a in raw['audit'].values()) for raw in raws)
    fields=('reduced_existing_loss_gross_bps','extended_existing_win_gross_bps','cut_existing_win_gross_bps','added_existing_loss_gross_bps','additional_common_cost_funding_bps','occupancy_new_excluded_net_bps','terminal_delta_bps')
    c['component_bridge']={f:fsum(float(d[f]) for d in decomps) for f in fields}
    return c

def finalize():
    spec=check(); b=read(OUT/'BUDGET.json'); q=b[KEY]
    need((q['reserved'],q['started'],q['completed'],q['failed'])==(6,6,6,0),'NOT_SIX_CLEAN_FULLS')
    parentc=_parent_combined(); candidates={v:_child_combined(v) for v in child.VARIANTS}
    eligible=[x for x in candidates.values() if x['eligible']]
    eligible.sort(key=lambda x:(x['terminal_net_bps'],x['terminal_cost2x_net_bps'],-x['worst_period_marked_DD_bps'],x['win_rate']),reverse=True)
    best=eligible[0] if eligible else None
    selected=best['label'] if best and best['terminal_net_bps']>parentc['terminal_net_bps'] else 'CAPREUSE'
    state='SELECTED_NEW_CUMULATIVE_INCUMBENT' if selected!='CAPREUSE' else 'KEEP_CAPREUSE_NO_CHILD_BEAT_COMBINED_NET'
    summary=dict(schema='zel.squeeze_kr3.true_component_unified.repaired_final.v1',scope=SCOPE,
        predecessor_failed_candidate=85,predecessor_failed_evaluation=153,parent=parentc,candidates=candidates,
        selected=selected,state=state,selection_objective=spec['selection_objective'],selection_contract_frozen_before_outcomes=True,
        formal_credit=0,used_DEV=True,Q_track_touched=False,candidate_count=3,economic_FULL_count=6,
        new_future_boundary_required=selected!='CAPREUSE',automatic_successor=False)
    put(OUT/'SUMMARY.json',summary)
    if selected!='CAPREUSE':
        chosen=candidates[selected]
        seal=dict(schema='zel.squeeze_kr3.unified_v1.seal.v1',strategy_name='Squeeze-KR3 Unified v1',selected=selected,
            architecture=child.RULES[selected],candidate_ordinal=CANDIDATES[selected],source_files_sha256=spec['source_files_sha256'],
            result_receipts={p:h(OUT/selected/p/'RECEIPT.json') for p in PERIODS},combined=chosen,formal_credit=0,
            historical_used_dev_only=True,prospective_boundary_required_after_merge=True)
        put(OUT/'INCUMBENT_SEAL.json',seal)
    put(OUT/'FINAL_STATUS.json',dict(strategy_name='Squeeze-KR3 Unified v1' if selected!='CAPREUSE' else None,
        selected_incumbent=selected,state=state,formal_credit=0,Q_track_touched=False,prospective_boundary_required=selected!='CAPREUSE'))
    lines=['# Squeeze-KR3 true-component Unified 결과','',('Squeeze-KR3 Unified = 생성됨' if selected!='CAPREUSE' else 'Squeeze-KR3 Unified = 생성안됨'),'',f'- 선택: `{selected}`',f'- 상태: `{state}`','',
      '| 후보 | Combined Net | Combined cost2 | Weighted WR | PF | Payoff | Worst DD | Eligible |','|---|---:|---:|---:|---:|---:|---:|---|']
    for name,c in [('CAPREUSE',parentc)]+[(v,candidates[v]) for v in child.VARIANTS]:
        lines.append(f"| {name} | {c['terminal_net_bps']:.2f} | {c['terminal_cost2x_net_bps']:.2f} | {100*(c['win_rate'] or 0):.2f}% | {(c['PF'] or 0):.3f} | {(c['payoff'] or 0):.3f} | {c['worst_period_marked_DD_bps']:.2f} | {c.get('eligible',True)} |")
    lines+=['','## 기간별']
    for name,c in [('CAPREUSE',parentc)]+[(v,candidates[v]) for v in child.VARIANTS]:
        for p in PERIODS:
            x=c['per_period'][p]
            lines.append(f"- {name} {p}: closed/open={x['closed']}/{x['open']}, WR={100*(x['win_rate'] or 0):.2f}%, net={x['terminal_net_bps']:.2f}, cost2={x['terminal_cost2x_net_bps']:.2f}, PF={(x['PF'] or 0):.3f}, payoff={(x['payoff'] or 0):.3f}, DD={x['marked_DD_bps']:.2f}")
    lines+=['','## component 기여']
    for v in child.VARIANTS:
        c=candidates[v]; d=c['component_bridge']
        lines.append(f"- {v}: K1 veto={c['k1_veto_T']}, K2 arm={c['k2_arm_T']}, K2 trigger={c['k2_trigger_T']}, net Δ={d['terminal_delta_bps']:.2f}, loss-reduction gross={d['reduced_existing_loss_gross_bps']:.2f}, winner-extension gross={d['extended_existing_win_gross_bps']:.2f}, winner-cut gross={d['cut_existing_win_gross_bps']:.2f}, added-loss gross={d['added_existing_loss_gross_bps']:.2f}, occupancy net={d['occupancy_new_excluded_net_bps']:.2f}")
    lines+=['','candidate85/eval153 no-output implementation failure is preserved and not reused. All six repaired FULLs are USED_DEV/formal_credit=0. Q-track/fresh/G5 data access=0.']
    (OUT/'REPORT_KO.md').write_text('\n'.join(lines)+'\n')
    atomic(OUT/'STATUS.json',dict(scope=SCOPE,state=state,selected=selected,formal_credit=0,report_only=True))
    persist('Finalize repaired Squeeze/KR3 Unified selection')
    print(json.dumps(summary,sort_keys=True))

def run_all():
    freeze(); persist('Freeze repaired Squeeze/KR3 Unified contract')
    for v,p in PLAN:
        claim=reserve(v,p); execute(v,p,claim)
    finalize()

if __name__=='__main__':
    ap=argparse.ArgumentParser(); ap.add_argument('--all',action='store_true'); ap.add_argument('--freeze',action='store_true'); ap.add_argument('--finalize',action='store_true')
    args=ap.parse_args()
    if args.all: run_all()
    elif args.freeze: freeze()
    elif args.finalize: finalize()
    else: ap.error('choose --all/--freeze/--finalize')
