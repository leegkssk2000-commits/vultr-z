"""Bounded owner for Issue #1291: three frozen component syntheses, six USED_DEV FULLs."""
import argparse, gzip, json, math, os, subprocess, time, traceback
from pathlib import Path
from math import fsum

from backend.research.rebuild import squeeze_kr3_unified_v1 as child
from backend.research.rebuild import c70_tm_capreuse_account_v1 as capacc
from backend.research.rebuild import c63_c70_trader_account_v1 as acct

ROOT=acct.ROOT
OUT=ROOT/'research/development_evidence'/child.SCOPE
INPUTS=acct.INPUTS
HISTORY=ROOT/'research/development_evidence/C70_LOT_LEVEL_RISK_AFTER_PR1264_V1/BUDGET.json'
BRANCH='codex/squeeze-kr3-unified-1291'
KEY='squeeze_kr3_unified_1291_allocation'
PERIODS=('DEV2025','SEEN2026')
PLAN=[(v,p) for v in child.VARIANTS for p in PERIODS]
CANDIDATES={'U1':85,'U2':86,'U3':87}
EVALS={('U1','DEV2025'):153,('U1','SEEN2026'):154,
       ('U2','DEV2025'):155,('U2','SEEN2026'):156,
       ('U3','DEV2025'):157,('U3','SEEN2026'):158}


def h(path): return acct.h(path)
def read(path): return acct.read(path)
def gz(path): return acct.gz(path)
def put(path,obj): return acct.put(path,obj)
def need(ok,msg):
    if not ok: raise RuntimeError(msg)
def git(*args): return subprocess.check_output(['git',*args],cwd=ROOT,text=True,timeout=45).strip()

def atomic(path,obj):
    path=Path(path);tmp=path.with_suffix(path.suffix+'.pending')
    data=acct.canon(obj)+b'\n'
    with tmp.open('xb') as f:
        f.write(data);f.flush();os.fsync(f.fileno())
    os.replace(tmp,path)

def owner():
    need(os.environ.get('GITHUB_RUN_ATTEMPT')=='1','NO_RETRY')
    need(os.environ.get('GITHUB_REF_NAME')==BRANCH,'BRANCH_OWNER')
    return os.environ['GITHUB_RUN_ID']

def sources():
    paths=[
      'backend/research/rebuild/squeeze_kr3_unified_v1.py',
      'backend/research/rebuild/squeeze_kr3_unified_study_v1.py',
      'backend/research/rebuild/test_squeeze_kr3_unified_v1.py',
      'backend/research/rebuild/c70_tm_capreuse_v1.py',
      'backend/research/rebuild/c63_c70_trader_management_v1.py',
      'backend/research/rebuild/kr3_c51_entry_context_v1.py',
      'backend/research/rebuild/kr3_profit_zone_exit_v1.py',
      'research/development_evidence/SQUEEZE_KR3_TRUE_COMPONENT_UNIFIED_AFTER_TOP6_V1/DESIGN.md',
    ]
    return {p:h(ROOT/p) for p in paths}

def parent(per): return gz(capacc.OUT/per/'RESULT.json.gz')

def charge(raw_by,packet,cal,rule):
    result=dict(trades=[],open_observations=[],events=[],trace=[],audit={},candidate=rule,
                independent=False,formal_credit=0,operating_adoption=False)
    for symbol,rr in sorted(raw_by.items()):
        for raw in rr['trades']+rr['open_positions']:
            status,row=capacc.campaign(raw,symbol,packet)
            row['candidate']=rule
            row['evidence_type']='SQUEEZE_KR3_TRUE_COMPONENT_SYNTHESIS_USED_DEV'
            row.pop('trade_sha256',None);row.pop('observation_sha256',None)
            row['trade_sha256' if status=='C' else 'observation_sha256']=acct.p.sha(row)
            result['trades' if status=='C' else 'open_observations'].append(row)
        result['events'].extend(dict(e,symbol=symbol) for e in rr['events'])
        result['trace'].extend(dict(t,symbol=symbol) for t in rr['trace'])
        result['audit'][symbol]=rr['audit']
    result['metrics']=acct.metrics(result,packet,cal)
    return result

def freeze():
    need(os.environ.get('SKR1291_PREFLIGHT')=='PASSED','FULL_CHECKOUT_PREFLIGHT_REQUIRED')
    need(not (OUT/'SPEC.json').exists(),'ALREADY_FROZEN')
    history=read(HISTORY)
    need((history['cumulative_actual'],history['cumulative_actual_evaluations'])==(84,152),'LATEST_HISTORY_NOT84_152')
    need(KEY not in history,'DUPLICATE_ALLOCATION')
    capspec=read(capacc.OUT/'SPEC.json')
    packet_hashes={}
    for per in PERIODS:
        path=ROOT/INPUTS/(per+'.json.gz')
        need(h(path)==capspec['input_packet_sha256'][per],'INPUT_PACKET_DRIFT:'+per)
        packet_hashes[per]=h(path)
    preserved=capspec.get('preserved_files_sha256',{})
    for p in ('backend/research/rebuild/kr3_c51_entry_context_v1.py','backend/research/rebuild/kr3_profit_zone_exit_v1.py'):
        if p in preserved: need(h(ROOT/p)==preserved[p],'DONOR_SOURCE_DRIFT:'+p)
    put(OUT/'HISTORY_PRIOR.json',history)
    spec=dict(scope=child.SCOPE,issue=1291,branch=BRANCH,owner_run=owner(),
        source_commit=git('rev-parse','HEAD'),frozen_ns=time.time_ns(),
        variants=list(child.VARIANTS),plan=[list(x) for x in PLAN],candidate_ordinals=CANDIDATES,
        evaluation_ordinals={v:{p:EVALS[(v,p)] for p in PERIODS} for v in child.VARIANTS},
        max_candidates=3,max_FULL=6,parent='C70_TM_CAPREUSE_V1_candidate82',
        parent_results_sha256={p:h(capacc.OUT/p/'RESULT.json.gz') for p in PERIODS},
        input_packet_sha256=packet_hashes,periods=capspec['periods'],source_files_sha256=sources(),
        history_sha256=h(OUT/'HISTORY_PRIOR.json'),
        selection_objective='Highest combined terminal net across both USED_DEV periods; eligibility requires each period net>0,cost2>0,PF>=1; tie cost2,worst-DD,weighted-WR.',
        WR_is_hard_gate=False,formal_credit=0,used_DEV=True,new_market=0,unused_OOS=0,
        paid_AI=0,orders=0,deploy=0,retry=False,automatic_successor=False,
        K1='Exact C54 B semantic: 0<(signal_close-EMA20)/previous_bar_Wilder_ATR14<=1.',
        K2='Exact C51 profit-zone idea adapted only to residual after actual D3 partial; core floor/BE/SMA10 priority unchanged.')
    put(OUT/'SPEC.json',spec)
    history[KEY]=dict(scope=child.SCOPE,max_candidates=3,max_executions=6,reserved=0,started=0,
                      completed=0,failed=0,remaining=6,retry=False,candidate_ordinals=CANDIDATES,
                      evaluation_ordinals=list(range(153,159)))
    put(OUT/'BUDGET.json',history)
    put(OUT/'STATUS.json',dict(scope=child.SCOPE,state='PREPARED',owner_run=spec['owner_run']))
    print('SKR1291_FROZEN_BEFORE_OUTCOMES')

def check():
    s=read(OUT/'SPEC.json')
    need(s['owner_run']==owner(),'OWNER_CHANGED')
    need(s['source_files_sha256']==sources(),'SOURCE_DRIFT')
    need(s['history_sha256']==h(OUT/'HISTORY_PRIOR.json')==h(HISTORY),'HISTORY_DRIFT')
    for per in PERIODS:
        need(h(ROOT/INPUTS/(per+'.json.gz'))==s['input_packet_sha256'][per],'INPUT_DRIFT:'+per)
        need(h(capacc.OUT/per/'RESULT.json.gz')==s['parent_results_sha256'][per],'PARENT_RESULT_DRIFT:'+per)
    return s

def persist(message):
    git('add','--',str(OUT.relative_to(ROOT)))
    git('commit','-m',message+' [skip ci]')
    head=git('rev-parse','HEAD')
    git('push','origin','HEAD:refs/heads/'+BRANCH)
    remote=git('ls-remote','origin','refs/heads/'+BRANCH).split()[0]
    need(remote==head,'REMOTE_READBACK_MISMATCH')
    return head

def reserve(variant,per):
    s=check();j=PLAN.index((variant,per));b=read(OUT/'BUDGET.json');q=b[KEY]
    need(q['reserved']==q['started']==q['completed']==j and q['failed']==0,'DUPLICATE_OR_PRIOR_FAILURE')
    folder=OUT/variant/per
    put(folder/'ATTEMPT.json',dict(scope=child.SCOPE,variant=variant,period=per,
        candidate_ordinal=CANDIDATES[variant],evaluation_ordinal=EVALS[(variant,per)],
        state='RESERVED_NOT_STARTED',owner_run=s['owner_run'],spec_sha256=h(OUT/'SPEC.json'),time_ns=time.time_ns()))
    q['reserved']+=1;q['remaining']-=1;atomic(OUT/'BUDGET.json',b)
    return persist('Reserve '+variant+' '+per)

def execute(variant,per,claim):
    s=check();j=PLAN.index((variant,per));folder=OUT/variant/per
    need(git('ls-remote','origin','refs/heads/'+BRANCH).split()[0]==claim,'CLAIM_MOVED')
    b=read(OUT/'BUDGET.json');q=b[KEY]
    need(q['reserved']==j+1 and q['started']==q['completed']==j and q['failed']==0,'BAD_EXECUTION_STATE')
    if per=='DEV2025':
        need(b['cumulative_actual']==CANDIDATES[variant]-1,'CANDIDATE_ORDINAL')
        b['cumulative_actual']+=1
        b['new_candidate_runs']=b.get('new_candidate_runs',0)+1
        b['candidate_trials'].append(dict(candidate=child.RULES[variant],ordinal=CANDIDATES[variant],
            first_evaluation=EVALS[(variant,per)],scope=child.SCOPE))
    need(b['cumulative_actual_evaluations']==EVALS[(variant,per)]-1,'EVALUATION_ORDINAL')
    b['cumulative_actual_evaluations']+=1;q['started']+=1
    b['trials'].append(dict(scope=child.SCOPE,candidate=child.RULES[variant],variant=variant,period=per,
        candidate_ordinal=CANDIDATES[variant],evaluation_ordinal=EVALS[(variant,per)],status='STARTED',retry=False))
    put(folder/'EXECUTION_STARTED.json',dict(scope=child.SCOPE,variant=variant,period=per,
        claim_commit=claim,owner_run=s['owner_run'],time_ns=time.time_ns()))
    atomic(OUT/'BUDGET.json',b);atomic(OUT/'STATUS.json',dict(scope=child.SCOPE,state='RUNNING',owner_run=s['owner_run']))
    started=persist('Durably start '+variant+' '+per)
    try:
        packet=gz(ROOT/INPUTS/(per+'.json.gz'));cal=s['periods'][per]
        raw={sym:child.replay(rows,eval_start_ms=cal['start_ms'],eval_end_ms=cal['runoff_end_ms'],
                              cost=packet['costs'],variant=variant)
             for sym,rows in sorted(packet['rows_by'].items())}
        result=charge(raw,packet,cal,child.RULES[variant])
        parent_result=parent(per)
        snap=capacc.snapshot(result,parent_result)
        decomp=acct.decomposition(parent_result,result)
        put(folder/'RAW.json.gz',raw);put(folder/'RESULT.json.gz',result)
        put(folder/'SNAPSHOT.json',snap);put(folder/'DECOMPOSITION.json',decomp)
        put(folder/'RECEIPT.json',dict(state='COMPLETED',variant=variant,period=per,
            candidate_ordinal=CANDIDATES[variant],evaluation_ordinal=EVALS[(variant,per)],
            claim_commit=claim,started_commit=started,raw_sha256=h(folder/'RAW.json.gz'),
            result_sha256=h(folder/'RESULT.json.gz'),snapshot_sha256=h(folder/'SNAPSHOT.json'),
            decomposition_sha256=h(folder/'DECOMPOSITION.json'),formal_credit=0))
        b=read(OUT/'BUDGET.json');q=b[KEY];q['completed']+=1;b['trials'][-1]['status']='COMPLETED';atomic(OUT/'BUDGET.json',b)
        return persist('Persist '+variant+' '+per+' result')
    except BaseException as exc:
        put(folder/'FAILURE.json',dict(state='FAILED_CONSUMED',error=str(exc),traceback=traceback.format_exc(),retry=False))
        b=read(OUT/'BUDGET.json');q=b[KEY];q['failed']+=1;b['trials'][-1]['status']='FAILED_CONSUMED';atomic(OUT/'BUDGET.json',b)
        atomic(OUT/'STATUS.json',dict(scope=child.SCOPE,state='CHECKPOINTED_BLOCKED',owner_run=s['owner_run']))
        persist('Persist consumed failure '+variant+' '+per)
        raise

def combined(label,results):
    snaps=[capacc.snapshot(r,parent(p)) for p,r in zip(PERIODS,results)] if label!='CAPREUSE' else [capacc.snapshot(r) for r in results]
    trades=[t for r in results for t in r['trades']]
    wins=[t['net_bps'] for t in trades if t['net_bps']>0];losses=[t['net_bps'] for t in trades if t['net_bps']<0]
    mean_win=fsum(wins)/len(wins) if wins else None;mean_loss=fsum(losses)/len(losses) if losses else None
    return dict(label=label,closed=sum(s['closed'] for s in snaps),open=sum(s['open'] for s in snaps),
        win_rate=len(wins)/len(trades) if trades else None,
        terminal_net_bps=fsum(s['terminal_net_bps'] for s in snaps),
        terminal_cost2x_net_bps=fsum(s['terminal_cost2x_net_bps'] for s in snaps),
        PF=fsum(wins)/abs(fsum(losses)) if losses else None,
        realized_payoff=mean_win/abs(mean_loss) if mean_win is not None and mean_loss else None,
        worst_period_marked_DD_bps=max(s['marked_DD_trade_sum_bps'] for s in snaps),
        per_period={p:s for p,s in zip(PERIODS,snaps)})

def finalize():
    s=check();b=read(OUT/'BUDGET.json');q=b[KEY]
    need(q['completed']==6 and q['failed']==0,'NOT_ALL_COMPLETED')
    parent_results=[parent(p) for p in PERIODS];parent_combined=combined('CAPREUSE',parent_results)
    candidates={}
    for v in child.VARIANTS:
        rs=[gz(OUT/v/p/'RESULT.json.gz') for p in PERIODS]
        c=combined(v,rs)
        eligible=all(c['per_period'][p]['terminal_net_bps']>0 and c['per_period'][p]['terminal_cost2x_net_bps']>0 and
                     c['per_period'][p]['PF'] is not None and c['per_period'][p]['PF']>=1 for p in PERIODS)
        c['eligible']=eligible
        c['k1_veto_T']=sum(sum(a.get('k1_veto_T',0) for a in r['audit'].values()) for r in rs)
        c['k2_trigger_T']=sum(sum(a.get('k2_trigger_T',0) for a in r['audit'].values()) for r in rs)
        candidates[v]=c
    eligible=[c for c in candidates.values() if c['eligible']]
    eligible.sort(key=lambda c:(c['terminal_net_bps'],c['terminal_cost2x_net_bps'],-c['worst_period_marked_DD_bps'],c['win_rate']),reverse=True)
    best=eligible[0] if eligible else None
    selected=best['label'] if best and best['terminal_net_bps']>parent_combined['terminal_net_bps'] else 'CAPREUSE'
    state='SELECTED_NEW_CUMULATIVE_INCUMBENT' if selected!='CAPREUSE' else 'KEEP_CAPREUSE_NO_CHILD_BEAT_COMBINED_NET'
    summary=dict(scope=child.SCOPE,parent=parent_combined,candidates=candidates,selected=selected,state=state,
        selection_objective=s['selection_objective'],formal_credit=0,used_DEV=True,
        Q_track_touched=False,new_future_boundary_required=selected!='CAPREUSE')
    put(OUT/'SUMMARY.json',summary)
    lines=['# Squeeze-KR3 Unified 결과','',f"- 최종 상태: `{state}`",f"- 선택: `{selected}`",'',
           '|candidate|combined net|combined cost2|weighted WR|PF|payoff|worst DD|eligible|','|---|---:|---:|---:|---:|---:|---:|---|']
    for name,c in [('CAPREUSE',parent_combined)]+[(v,candidates[v]) for v in child.VARIANTS]:
        lines.append(f"|{name}|{c['terminal_net_bps']:.2f}|{c['terminal_cost2x_net_bps']:.2f}|{(c['win_rate'] or 0)*100:.2f}%|{(c['PF'] or 0):.3f}|{(c['realized_payoff'] or 0):.3f}|{c['worst_period_marked_DD_bps']:.2f}|{c.get('eligible',True)}|")
    lines+=['','## 기간별','']
    for name,c in [('CAPREUSE',parent_combined)]+[(v,candidates[v]) for v in child.VARIANTS]:
        for p in PERIODS:
            x=c['per_period'][p]
            lines.append(f"- {name} {p}: closed/open={x['closed']}/{x['open']}, WR={x['win_rate']*100:.2f}%, net={x['terminal_net_bps']:.2f}, cost2={x['terminal_cost2x_net_bps']:.2f}, PF={x['PF']:.3f}, payoff={x['realized_payoff']:.3f}, DD={x['marked_DD_trade_sum_bps']:.2f}")
    lines+=['','USED_DEV/formal_credit=0. Q-track/fresh/G5 data는 사용하지 않았다.']
    (OUT/'REPORT_KO.md').write_text('\n'.join(lines)+'\n')
    atomic(OUT/'STATUS.json',dict(scope=child.SCOPE,state=state,selected=selected,formal_credit=0,report_only=True))
    persist('Finalize Squeeze/KR3 Unified selection')
    print(json.dumps(summary,sort_keys=True))

def run_all():
    freeze();persist('Freeze Squeeze/KR3 Unified contract')
    for variant,per in PLAN:
        claim=reserve(variant,per);execute(variant,per,claim)
    finalize()

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--all',action='store_true');ap.add_argument('--freeze',action='store_true');ap.add_argument('--finalize',action='store_true')
    args=ap.parse_args()
    if args.all: run_all()
    elif args.freeze: freeze()
    elif args.finalize: finalize()
    else: ap.error('choose --all/--freeze/--finalize')
