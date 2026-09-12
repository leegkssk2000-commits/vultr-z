"""Issue #1294: one CAPREUSE-core + exact-C54-donor union, two USED_DEV FULLs."""
import argparse,gzip,json,os,subprocess,time,traceback
from collections import defaultdict
from copy import deepcopy
from math import fsum,isclose
from pathlib import Path

from backend.research.rebuild import squeeze_kr3_native_sleeve_v1 as u
from backend.research.rebuild import c70_tm_capreuse_account_v1 as capacc
from backend.research.rebuild import c63_c70_trader_account_v1 as acct
from backend.research.rebuild import kr3_c51_entry_context_study_v1 as c54study

ROOT=acct.ROOT
SCOPE='SQUEEZE_KR3_CORE_PLUS_C54_NATIVE_SLEEVE_AFTER_PR1293_V1'
OUT=ROOT/'research/development_evidence'/SCOPE
PRIOR=ROOT/'research/development_evidence/SQUEEZE_KR3_TRUE_COMPONENT_UNIFIED_EXECUTION_REPAIR_AFTER_1291_V1/BUDGET.json'
C54=ROOT/'research/development_evidence/KR3_C51_ENTRY_CONTEXT_AB_AFTER_PR1225_V1/B'
C54SPEC=ROOT/'research/development_evidence/KR3_C51_ENTRY_CONTEXT_AB_AFTER_PR1225_V1/SPEC.json'
BRANCH='codex/squeeze-kr3-native-sleeve-1294'
KEY='squeeze_kr3_native_sleeve_1294_allocation'
PERIODS=('DEV2025','SEEN2026')
CANDIDATE=89
EVALS={'DEV2025':160,'SEEN2026':161}
p=c54study.p

h=acct.h;read=acct.read;gz=acct.gz;put=acct.put

def need(ok,msg):
    if not ok: raise RuntimeError(msg)

def git(*args): return subprocess.check_output(['git',*args],cwd=ROOT,text=True,timeout=45).strip()

def atomic(path,obj):
    path=Path(path);tmp=path.with_suffix(path.suffix+'.pending');data=acct.canon(obj)+b'\n'
    with tmp.open('xb') as f:f.write(data);f.flush();os.fsync(f.fileno())
    os.replace(tmp,path)

def owner():
    need(os.environ.get('GITHUB_RUN_ATTEMPT')=='1','NO_RETRY')
    need(os.environ.get('GITHUB_REF_NAME')==BRANCH,'BRANCH_OWNER')
    return os.environ['GITHUB_RUN_ID']

def deps():
    paths=['backend/research/rebuild/squeeze_kr3_native_sleeve_v1.py',
           'backend/research/rebuild/squeeze_kr3_native_sleeve_study_v1.py',
           'backend/research/rebuild/test_squeeze_kr3_native_sleeve_v1.py',
           'backend/research/rebuild/c70_tm_capreuse_account_v1.py',
           'backend/research/rebuild/kr3_c51_entry_context_v1.py',
           'backend/research/rebuild/kr3_c51_entry_context_study_v1.py',
           'research/development_evidence/SQUEEZE_KR3_CORE_PLUS_C54_NATIVE_SLEEVE_AFTER_PR1293_V1/DESIGN.md']
    return {x:h(ROOT/x) for x in paths}

def persist(msg):
    git('add','--',str(OUT.relative_to(ROOT)));git('commit','-m',msg+' [skip ci]')
    head=git('rev-parse','HEAD');git('push','origin','HEAD:refs/heads/'+BRANCH)
    remote=git('ls-remote','origin','refs/heads/'+BRANCH).split()[0];need(remote==head,'REMOTE_READBACK')
    return head

def freeze():
    need(os.environ.get('SKR1294_PREFLIGHT')=='PASSED','PREFLIGHT_REQUIRED')
    need(not (OUT/'SPEC.json').exists(),'ALREADY_FROZEN')
    prior=read(PRIOR);need((prior['cumulative_actual'],prior['cumulative_actual_evaluations'])==(88,159),'HISTORY_NOT88_159')
    need(KEY not in prior,'DUPLICATE_SCOPE')
    caps=read(capacc.OUT/'SPEC.json');c54s=read(C54SPEC)
    need(caps['input_packet_sha256']==c54s['input_packet_sha256'],'PARENT_DONOR_PACKET_IDENTITY_MISMATCH')
    packet_hash={x:h(ROOT/acct.INPUTS/(x+'.json.gz')) for x in PERIODS}
    need(packet_hash==caps['input_packet_sha256'],'INPUT_PACKET_DRIFT')
    put(OUT/'HISTORY_PRIOR.json',prior)
    spec=dict(schema='zel.squeeze_kr3.native_sleeve.spec.v1',scope=SCOPE,issue=1294,branch=BRANCH,owner_run=owner(),
      source_commit=git('rev-parse','HEAD'),frozen_ns=time.time_ns(),candidate=u.RULE_ID,candidate_ordinal=CANDIDATE,
      evaluation_ordinals=EVALS,periods=caps['periods'],input_packet_sha256=packet_hash,
      core_result_sha256={x:h(capacc.OUT/x/'RESULT.json.gz') for x in PERIODS},
      core_snapshot_sha256={x:h(capacc.OUT/x/'SNAPSHOT.json') for x in PERIODS},
      donor_result_sha256={x:h(C54/x/'RESULT.json.gz') for x in PERIODS},donor_raw_sha256={x:h(C54/x/'RAW.json.gz') for x in PERIODS},
      donor_spec_sha256=h(C54SPEC),source_files_sha256=deps(),prior_budget_sha256=h(PRIOR),
      architecture='CAPREUSE82 immutable core priority OR exact saved C54/B native donor campaign at original open when same-symbol core fully flat; later core entry preempts donor at that observable open.',
      donor_source='EXACT_SAVED_C54_ACTUAL_CAMPAIGNS_ONLY_NO_COUNTERFACTUAL_REQUALIFICATION',
      core_priority=True,core_retention_required=1.0,donor_full_size_only=True,partial_core_spare_not_used=True,
      selection='Eligibility core retention100%, each-period net>0/cost2>0/PF>=1, donor accepted>=1. Adopt iff two-period combined net strictly exceeds CAPREUSE.',
      WR_hard_gate=False,max_candidates=1,max_full=2,retry=False,formal_credit=0,used_DEV=True,Q_track_access=0,
      new_market=0,unused_OOS=0,paid_AI=0,orders=0,deploy=0,automatic_successor=False)
    put(OUT/'SPEC.json',spec)
    prior[KEY]=dict(scope=SCOPE,max_candidates=1,max_executions=2,reserved=0,started=0,completed=0,failed=0,remaining=2,
                    candidate_ordinal=CANDIDATE,evaluation_ordinals=[160,161],retry=False)
    put(OUT/'BUDGET.json',prior);put(OUT/'STATUS.json',dict(scope=SCOPE,state='PREPARED',formal_credit=0,owner_run=spec['owner_run']))
    print('U4_NATIVE_SLEEVE_FROZEN_BEFORE_OUTCOME')

def check():
    s=read(OUT/'SPEC.json');need(s['owner_run']==owner(),'OWNER_CHANGED');need(s['source_files_sha256']==deps(),'SOURCE_DRIFT')
    need(s['prior_budget_sha256']==h(PRIOR)==h(OUT/'HISTORY_PRIOR.json'),'PRIOR_HISTORY_DRIFT')
    need(s['donor_spec_sha256']==h(C54SPEC),'DONOR_SPEC_DRIFT')
    for per in PERIODS:
        need(h(ROOT/acct.INPUTS/(per+'.json.gz'))==s['input_packet_sha256'][per],'INPUT_DRIFT:'+per)
        need(h(capacc.OUT/per/'RESULT.json.gz')==s['core_result_sha256'][per],'CORE_RESULT_DRIFT:'+per)
        need(h(capacc.OUT/per/'SNAPSHOT.json')==s['core_snapshot_sha256'][per],'CORE_SNAPSHOT_DRIFT:'+per)
        need(h(C54/per/'RESULT.json.gz')==s['donor_result_sha256'][per],'DONOR_RESULT_DRIFT:'+per)
        need(h(C54/per/'RAW.json.gz')==s['donor_raw_sha256'][per],'DONOR_RAW_DRIFT:'+per)
    return s

def reserve(per):
    s=check();i=PERIODS.index(per);b=read(OUT/'BUDGET.json');q=b[KEY]
    need(q['reserved']==q['started']==q['completed']==i and q['failed']==0,'ALLOCATION_STATE')
    folder=OUT/per;put(folder/'ATTEMPT.json',dict(scope=SCOPE,period=per,candidate_ordinal=CANDIDATE,evaluation_ordinal=EVALS[per],
         owner_run=s['owner_run'],status='RESERVED_NOT_STARTED',spec_sha256=h(OUT/'SPEC.json'),retry=False,time_ns=time.time_ns()))
    q['reserved']+=1;q['remaining']-=1;atomic(OUT/'BUDGET.json',b);return persist('Reserve U4 '+per)

def _value(status,row):
    return acct.bridge._values((status,row))['net_bps']

def _charge_preempt(raw,symbol,packet,ts):
    rows=packet['rows_by'][symbol];pre=u.preempt_raw(raw,rows,ts)
    rr=dict(trades=[pre],open_positions=[],events=[],trace=[],audit={})
    charged=p.account.charge_result(rr,symbol,'keltner_trend_main',u.RULE_ID,packet['policy'],packet['costs'],rows)
    need(len(charged['trades'])==1 and not charged['open_observations'],'PREEMPT_CHARGE_SHAPE')
    row=charged['trades'][0];row['sleeve_role']='C54_NATIVE_DONOR_PREEMPTED_BY_CORE';row.pop('trade_sha256',None);row['trade_sha256']=p.sha(row)
    return row

def run_union(per,packet,s):
    cal=s['periods'][per];parent=gz(capacc.OUT/per/'RESULT.json.gz');donor=gz(C54/per/'RESULT.json.gz');rawdonor=gz(C54/per/'RAW.json.gz')
    core_rows=parent['trades']+parent['open_observations'];donor_rows=donor['trades']+donor['open_observations']
    plan=u.chronological_plan(core_rows,donor_rows);rawidx=u.raw_index(rawdonor)
    natural=[];preempt=[];events=[];by_symbol=defaultdict(float)
    for item in plan['accepted_natural']:
        row=deepcopy(item['row']);row['sleeve_role']='C54_NATIVE_DONOR_NATURAL'
        natural.append(row);status='C' if 'exit_ts' in row else 'O';by_symbol[row['symbol']]+=_value(status,row)
        events.append(dict(kind='DONOR_ACCEPTED_NATURAL',origin=list(item['key']),entry_ts=row['entry_ts'],end_ts=u.end_ts(row)))
    for item in plan['accepted_preempt']:
        k=item['key'];need(k in rawidx,'PREEMPT_RAW_NOT_FOUND:'+repr(k))
        row=_charge_preempt(rawidx[k],k[0],packet,item['preempt_ts']);preempt.append(row);by_symbol[row['symbol']]+=_value('C',row)
        events.append(dict(kind='DONOR_ACCEPTED_CORE_PREEMPT',origin=list(k),entry_ts=row['entry_ts'],exit_ts=row['exit_ts'],core_origin=list(item['core_key'])))
    for x in plan['excluded']:events.append(dict(kind='DONOR_EXCLUDED',origin=list(x['key']),reason=x['reason'],ts=x['ts']))
    accepted=natural+preempt
    core_keys={u.key(r) for r in core_rows};need(not any(u.key(r) in core_keys for r in accepted),'DONOR_DUPLICATES_CORE')
    result=deepcopy(parent);result['trades']=deepcopy(parent['trades'])+[r for r in accepted if 'exit_ts' in r]
    result['open_observations']=deepcopy(parent['open_observations'])+[r for r in accepted if 'exit_ts' not in r]
    result['events']=deepcopy(parent.get('events',[]))+events
    result['trace']=deepcopy(parent.get('trace',[]))+events
    result['candidate']=u.RULE_ID;result['formal_credit']=0;result['independent']=False
    result['metrics']=acct.metrics(result,packet,cal)
    # Immutable-core byte/economic identity: every parent row is exactly retained.
    parent_map={u.key(r):r for r in core_rows};child_map={u.key(r):r for r in result['trades']+result['open_observations']}
    need(all(k in child_map and child_map[k]==v for k,v in parent_map.items()),'CORE_ROW_MUTATION_OR_LOSS')
    snap=acct.snapshot(result,parent);decomp=acct.decomposition(parent,result)
    snap.update(core_retention_fraction=1.0,donor_source_T=len(donor_rows),donor_accepted_T=len(accepted),
                donor_natural_T=len(natural),donor_preempted_T=len(preempt),donor_excluded_T=len(plan['excluded']),
                donor_exclusions=dict(__import__('collections').Counter(x['reason'] for x in plan['excluded'])),
                donor_net_contribution_bps=fsum(by_symbol.values()),donor_net_by_symbol=dict(by_symbol),
                arbitration_event_count=plan['event_count'])
    need(isclose(snap['terminal_net_bps']-acct.snapshot(parent)['terminal_net_bps'],snap['donor_net_contribution_bps'],rel_tol=1e-10,abs_tol=1e-6),'DONOR_NET_BRIDGE')
    return result,snap,decomp,dict(plan=plan,events=events,donor_net_by_symbol=dict(by_symbol))

def execute(per,claim):
    s=check();i=PERIODS.index(per);folder=OUT/per
    need(git('ls-remote','origin','refs/heads/'+BRANCH).split()[0]==claim,'CLAIM_MOVED')
    b=read(OUT/'BUDGET.json');q=b[KEY];need(q['reserved']==i+1 and q['started']==q['completed']==i and q['failed']==0,'EXEC_STATE')
    if i==0:
        need(b['cumulative_actual']==88,'CANDIDATE_COUNTER');b['cumulative_actual']=89;b['new_candidate_runs']=b.get('new_candidate_runs',0)+1
        b['candidate_trials'].append(dict(ordinal=89,candidate=u.RULE_ID,scope=SCOPE,first_evaluation=160))
    need(b['cumulative_actual_evaluations']==159+i,'EVAL_COUNTER');b['cumulative_actual_evaluations']=EVALS[per];q['started']+=1
    b['trials'].append(dict(scope=SCOPE,candidate=u.RULE_ID,period=per,candidate_ordinal=89,evaluation_ordinal=EVALS[per],status='STARTED',retry=False))
    put(folder/'EXECUTION_STARTED.json',dict(scope=SCOPE,period=per,claim_commit=claim,owner_run=s['owner_run'],time_ns=time.time_ns()))
    atomic(OUT/'BUDGET.json',b);atomic(OUT/'STATUS.json',dict(scope=SCOPE,state='RUNNING',formal_credit=0,owner_run=s['owner_run']))
    started=persist('Durably start U4 '+per)
    try:
        packet=gz(ROOT/acct.INPUTS/(per+'.json.gz'));result,snap,decomp,arb=run_union(per,packet,s)
        put(folder/'RESULT.json.gz',result);put(folder/'SNAPSHOT.json',snap);put(folder/'DECOMPOSITION.json',decomp);put(folder/'ARBITRATION.json.gz',arb)
        put(folder/'RECEIPT.json',dict(state='COMPLETED',scope=SCOPE,period=per,candidate_ordinal=89,evaluation_ordinal=EVALS[per],
             claim_commit=claim,started_commit=started,result_sha256=h(folder/'RESULT.json.gz'),snapshot_sha256=h(folder/'SNAPSHOT.json'),
             decomposition_sha256=h(folder/'DECOMPOSITION.json'),arbitration_sha256=h(folder/'ARBITRATION.json.gz'),formal_credit=0,retry=False))
        b=read(OUT/'BUDGET.json');q=b[KEY];q['completed']+=1;b['trials'][-1]['status']='COMPLETED';atomic(OUT/'BUDGET.json',b)
        return persist('Persist U4 '+per+' result')
    except BaseException as exc:
        put(folder/'FAILURE.json',dict(state='FAILED_CONSUMED',error=str(exc),traceback=traceback.format_exc(),retry=False));b=read(OUT/'BUDGET.json');b[KEY]['failed']+=1;b['trials'][-1]['status']='FAILED_CONSUMED';atomic(OUT/'BUDGET.json',b);persist('Persist U4 failure '+per);raise

def finalize():
    s=check();b=read(OUT/'BUDGET.json');q=b[KEY];need((q['reserved'],q['started'],q['completed'],q['failed'])==(2,2,2,0),'NOT_TWO_CLEAN_FULLS')
    ps={p:read(capacc.OUT/p/'SNAPSHOT.json') for p in PERIODS};cs={p:read(OUT/p/'SNAPSHOT.json') for p in PERIODS}
    parent_net=fsum(x['terminal_net_bps'] for x in ps.values());child_net=fsum(x['terminal_net_bps'] for x in cs.values())
    eligible=all(cs[p]['core_retention_fraction']==1 and cs[p]['terminal_net_bps']>0 and cs[p]['terminal_cost2x_net_bps']>0 and cs[p]['PF'] is not None and cs[p]['PF']>=1 and cs[p]['donor_accepted_T']>=1 for p in PERIODS)
    selected='U4' if eligible and child_net>parent_net else 'CAPREUSE'
    state='SELECTED_SQUEEZE_KR3_UNIFIED_V1' if selected=='U4' else 'KEEP_CAPREUSE_AND_C54_SEPARATE'
    summary=dict(schema='zel.squeeze_kr3.native_sleeve.final.v1',scope=SCOPE,parent={p:ps[p] for p in PERIODS},U4={p:cs[p] for p in PERIODS},
      parent_combined_net_bps=parent_net,U4_combined_net_bps=child_net,combined_delta_bps=child_net-parent_net,eligible=eligible,selected=selected,state=state,
      candidate=89,evaluations=[160,161],formal_credit=0,used_DEV=True,Q_track_touched=False,automatic_successor=False)
    put(OUT/'SUMMARY.json',summary)
    if selected=='U4':put(OUT/'INCUMBENT_SEAL.json',dict(schema='zel.squeeze_kr3.unified_v1.native_sleeve.seal.v1',strategy_name='Squeeze-KR3 Unified v1',candidate=u.RULE_ID,
        source_scope=SCOPE,candidate_ordinal=89,result_receipts={p:h(OUT/p/'RECEIPT.json') for p in PERIODS},combined_net_bps=child_net,formal_credit=0,prospective_boundary_required_after_merge=True))
    put(OUT/'FINAL_STATUS.json',dict(strategy_name='Squeeze-KR3 Unified v1' if selected=='U4' else None,selected_incumbent=selected,state=state,formal_credit=0,report_only=True))
    put(OUT/'STATUS.json',dict(scope=SCOPE,state=state,selected=selected,formal_credit=0,report_only=True,remaining_execution=[]))
    lines=['# Squeeze-KR3 native-sleeve Unified 결과','',('Squeeze-KR3 Unified = 생성됨' if selected=='U4' else 'Squeeze-KR3 Unified = 생성안됨'),'',
      f'- 선택: `{selected}`',f'- combined net: CAPREUSE {parent_net:.2f} → U4 {child_net:.2f} ({child_net-parent_net:+.2f})','',
      '|Period|Rule|Closed/open|WR|PF|Payoff|Net|Cost2|DD|Donor accepted/natural/preempted/excluded|','|---|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for p0 in PERIODS:
        for name,x in [('CAPREUSE',ps[p0]),('U4',cs[p0])]:
            extra='-' if name=='CAPREUSE' else f"{x['donor_accepted_T']}/{x['donor_natural_T']}/{x['donor_preempted_T']}/{x['donor_excluded_T']}"
            lines.append(f"|{p0}|{name}|{x['closed']}/{x['open']}|{100*x['win_rate']:.2f}%|{x['PF']:.3f}|{x['realized_payoff']:.3f}|{x['terminal_net_bps']:.2f}|{x['terminal_cost2x_net_bps']:.2f}|{x['marked_DD_trade_sum_bps']:.2f}|{extra}|")
    lines+=['','Core retention is exactly100%; U4 is one chronological strategy with core-priority donor arbitration, not arithmetic addition. USED_DEV/formal_credit=0; Q/fresh/G5 data access0.']
    (OUT/'REPORT_KO.md').write_text('\n'.join(lines)+'\n');persist('Finalize U4 native sleeve selection');print(json.dumps(summary,sort_keys=True))

def run_all():
    freeze();persist('Freeze U4 native sleeve contract')
    for per in PERIODS:
        claim=reserve(per);execute(per,claim)
    finalize()

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--all',action='store_true');args=ap.parse_args()
    if args.all:run_all()
    else:ap.error('--all required')
