"""One entry architecture, two first FULLs; frozen C63 controls, no economic retry."""
import argparse,gzip,json,os,subprocess,time,traceback,math
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from backend.research.rebuild import m1_er_range_rescue_study_v1 as prior
from backend.research.rebuild import c63_pre_release_pullback_v1 as child
ROOT=prior.ROOT
p,a=prior.p,prior.a
read,gz,h,put,need=prior.read,prior.gz,prior.h,prior.put,prior.need
SCOPE='C63_PRE_RELEASE_PULLBACK_ENTRY_V1';OUT='research/development_evidence/'+SCOPE
INPUTS='research/development_evidence/TOP5_SOURCE_CHART_MECHANISMS_AFTER_PR1228_V1/INPUTS'
KEY='c63_pre_release_entry_allocation';PERIODS=('DEV2025','SEEN2026')
HISTORY_SHA='832bf59d9d4c183f2bf8e88d437d75e91867a10a'
HISTORY_PATH='research/development_evidence/C63_PROFIT_CONFIRMED_PIVOT_EXIT_V1/BUDGET.json'
def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT,text=True,timeout=30).strip()
def budget_write(value):
    path=ROOT/OUT/'BUDGET.json';temp=path.with_suffix('.pending')
    with temp.open('xb') as f:f.write(p.canonical(value));f.flush();os.fsync(f.fileno())
    os.replace(temp,path)
def sources():
    result=dict(read(ROOT/prior.OUT/'SPEC.json')['source_files_sha256'])
    for name,d in result.items():need(h(ROOT/name)==d,'C63_SOURCE_DRIFT:'+name)
    for name in ('c63_pre_release_pullback_v1.py','test_c63_pre_release_pullback_v1.py','c63_pre_release_study_v1.py'):
        path='backend/research/rebuild/'+name;result[path]=h(ROOT/path)
    path=OUT+'/DESIGN.md';result[path]=h(ROOT/path)
    return result

def freeze():
    need(os.environ.get('C63_ENTRY_PREFLIGHT')=='PASSED','FULL_CHECKOUT_PREFLIGHT_REQUIRED')
    prior.verify_spec(ROOT/INPUTS)
    previous=read(ROOT/prior.OUT/'SPEC.json')
    data=subprocess.check_output(['git','show',HISTORY_SHA+':'+HISTORY_PATH],cwd=ROOT,timeout=30)
    history=json.loads(data);need((history['cumulative_actual'],history['cumulative_actual_evaluations'])==(67,118),'HISTORY_NOT67_118')
    need(KEY not in history and history['chart_allocation']['remaining']==6,'DUPLICATE_OR_OLD_SLOTS')
    p.write_new(ROOT/OUT/'HISTORY_PRIOR.json',data)
    spec=dict(scope=SCOPE,candidate=child.RULE_ID,comparison_reference='UNCHANGED_C63_NOT_IDENTICAL_ENTRY_PARENT',candidate_ordinal=68,evaluation_ordinals=[119,120],max_candidates=1,max_FULL=2,parent_replays=0,fixed_replays=0,
        source_files_sha256=sources(),periods=previous['periods'],input_packet_sha256=previous['input_packet_sha256'],history_commit=HISTORY_SHA,history_path=HISTORY_PATH,history_sha256=h(ROOT/OUT/'HISTORY_PRIOR.json'),
        parent_results_sha256={per:{n:h(ROOT/prior.OUT/per/n) for n in ('RAW.json.gz','RESULT.json.gz')} for per in PERIODS},parent_spec_sha256=h(ROOT/prior.OUT/'SPEC.json'),
        rule='Known native4h squeeze>=3 consecutive closes, first close>EMA21 and positive native14bar momentum prepares fixedEMA21 and known episode-low. A LATER still-squeezed close after low<=level and close>level/momentum>0 triggers next actual open. Cancel at floor-close or first squeeze end. One setup per episode. No future release selected. Original exit formula/time20 from new actual fill; no limit-price fill.',
        code_commit=git('rev-parse','HEAD'),frozen_ns=time.time_ns(),independent=False,formal_credit=0,source_replication=False,objective='C63 FULL vs candidate: each period WR/net/cost2 up and markedDD down; no equality improvement. Broader profit/risk/retention/concentration separately reported.',retry=False,api_calls=0,market_requests=0,unused_OOS=0,orders=0,selected_on_used_DEV=True)
    put(ROOT/OUT/'SPEC.json',spec)
    history[KEY]=dict(max_candidates=1,max_executions=2,reserved=0,started=0,completed=0,failed=0,remaining=2,retry=False)
    put(ROOT/OUT/'BUDGET.json',history)

def check():
    s=read(ROOT/OUT/'SPEC.json');need(s['source_files_sha256']==sources(),'SOURCE_CHANGED')
    need(h(ROOT/OUT/'HISTORY_PRIOR.json')==s['history_sha256'],'HISTORY_CHANGED')
    for per,d in s['input_packet_sha256'].items():need(h(ROOT/INPUTS/(per+'.json.gz'))==d,'INPUT_CHANGED')
    for per,files in s['parent_results_sha256'].items():
        for n,d in files.items():need(h(ROOT/prior.OUT/per/n)==d,'PARENT_CHANGED')
    return s

def reserve(per):
    check();j=PERIODS.index(per);b=read(ROOT/OUT/'BUDGET.json');q=b[KEY]
    need(q['reserved']==q['started']==q['completed']==j and q['failed']==0,'ALREADY_RESERVED_OR_INCOMPLETE')
    need(os.environ.get('GITHUB_RUN_ATTEMPT')=='1','NO_RETRY')
    put(ROOT/OUT/per/'ATTEMPT.json',dict(scope=SCOPE,period=per,ordinal=119+j,candidate_ordinal=68,status='RESERVED_NOT_STARTED',owner_run=os.environ['GITHUB_RUN_ID'],spec_sha256=h(ROOT/OUT/'SPEC.json'),time_ns=time.time_ns()))
    q['reserved']+=1;q['remaining']-=1;budget_write(b)

def execute(per,remote):
    s=check();j=PERIODS.index(per);folder=ROOT/OUT/per;at=read(folder/'ATTEMPT.json');head=git('rev-parse','HEAD')
    need(head==remote and at['owner_run']==os.environ['GITHUB_RUN_ID'] and os.environ.get('GITHUB_RUN_ATTEMPT')=='1','REMOTE_OWNER')
    need(subprocess.check_output(['git','show',head+':'+OUT+'/'+per+'/ATTEMPT.json'],cwd=ROOT)==(folder/'ATTEMPT.json').read_bytes(),'UNCOMMITTED_CLAIM')
    b=read(ROOT/OUT/'BUDGET.json');q=b[KEY]
    need(q['reserved']==j+1 and q['started']==q['completed']==j and q['failed']==0,'NO_RETRY_STARTED')
    need(b['cumulative_actual_evaluations']==118+j,'ORDINAL')
    packet=gz(ROOT/INPUTS/(per+'.json.gz'));prior.previous.shared.old.inherited.packet_check(per,packet);cal=s['periods'][per]
    put(folder/'EXECUTION_STARTED.json',dict(claim_commit=head,remote_readback_sha=remote,owner_run=at['owner_run'],time_ns=time.time_ns()))
    if j==0:
        need(b['cumulative_actual']==67,'CANDIDATE_ORDINAL');b['cumulative_actual']+=1;b['new_candidate_runs']+=1
        b['candidate_trials'].append(dict(candidate=child.RULE_ID,ordinal=68,first_evaluation=119,scope=SCOPE))
    b['cumulative_actual_evaluations']+=1;q['started']+=1;b['trials'].append(dict(at,actual_experiment_ordinal=119+j,status='STARTED'));budget_write(b)
    try:
        with p.native.sensitivity():raw={sym:child.replay(rows,eval_start_ms=cal['start_ms'],eval_end_ms=cal['runoff_end_ms']) for sym,rows in sorted(packet['rows_by'].items())}
        with patch.dict(prior.previous.integration.engine.RULES,{'M1':child.RULE_ID}):result=prior.previous.integration.charge_and_mark(raw,'M1',packet,cal)
        result.update(scope=SCOPE,period=per,spec_sha256=h(ROOT/OUT/'SPEC.json'),comparison_reference='C63')
        for n,obj in [('RAW.json.gz',raw),('RESULT.json.gz',result)]:p.write_new(folder/n,gzip.compress(p.canonical(obj),mtime=0))
        put(folder/'RECEIPT.json',dict(status='COMPLETED',period=per,candidate_ordinal=68,raw_sha256=h(folder/'RAW.json.gz'),result_sha256=h(folder/'RESULT.json.gz'),spec_sha256=h(ROOT/OUT/'SPEC.json'),claim_commit=head,metrics=a.snapshot(result)))
        q['completed']+=1;b['trials'][-1]['status']='COMPLETED';budget_write(b);print(json.dumps(a.snapshot(result)))
    except BaseException as exc:
        put(folder/'FAILURE.json',dict(error=str(exc),type=type(exc).__name__,traceback=traceback.format_exc(),status='FAILED_CONSUMED',retry=False))
        q['failed']+=1;b['trials'][-1]['status']='FAILED_CONSUMED';budget_write(b);raise

def value(kind,t,field='net'):
    return t[{'net':'net_bps','cost2':'cost2x_net_bps','gross':'gross_bps'}[field]] if kind=='C' else t[{'net':'hypothetical_liquidation_net_mark_bps','cost2':'hypothetical_liquidation_cost2x_net_mark_bps','gross':'gross_mark_bps'}[field]]
def episodes(result):
    out={}
    for kind,key in [('C','trades'),('O','open_observations')]:
        for t in result[key]:
            k=t['symbol']+'|'+t['setup_id'];need(k not in out,'DUPLICATE_EPISODE_POSITION');out[k]=(kind,t)
    return out

def bridge(parent,child_result):
    pmap,cmap=episodes(parent),episodes(child_result);common=pmap.keys()&cmap.keys();removed=pmap.keys()-cmap.keys();new=cmap.keys()-pmap.keys();rows=[]
    terms=dict(common_CC=0.,common_CO=0.,common_OC=0.,common_OO=0.,removed=0.,new=0.)
    for key in sorted(pmap.keys()|cmap.keys()):
        old=pmap.get(key);cur=cmap.get(key);pn=value(*old) if old else 0.;cn=value(*cur) if cur else 0.;group='common_'+old[0]+cur[0] if old and cur else 'removed' if old else 'new';terms[group]+=cn-pn
        rows.append(dict(episode=key,group=group,parent_net_bps=pn,candidate_net_bps=cn,delta_bps=cn-pn,parent_entry_ts=old[1]['entry_ts'] if old else None,candidate_entry_ts=cur[1]['entry_ts'] if cur else None,parent_entry_price=old[1]['entry_price'] if old else None,candidate_entry_price=cur[1]['entry_price'] if cur else None))
    delta=child_result['metrics']['terminal_net_bps']-parent['metrics']['terminal_net_bps'];need(math.isclose(sum(terms.values()),delta,abs_tol=1e-7),'BRIDGE_SUM')
    winners=sorted([(k,v) for k,v in pmap.items() if v[0]=='C' and value(*v)>0],key=lambda z:value(*z[1]),reverse=True)
    def retention(items):
        den=sum(value(*v) for k,v in items);num=sum(min(value(*v),max(0,value(*cmap[k]))) if k in cmap else 0 for k,v in items)
        return dict(n=len(items),parent_profit_bps=den,retained_capped_profit_bps=num,retention=None if not den else num/den)
    top=winners[:max(1,math.ceil(len(winners)*.1))]
    return dict(comparison='SHARED_SQUEEZE_EPISODE_NOT_IDENTICAL_TRADE_OR_FIXED_VIEW',terms=terms,total_delta_bps=delta,rows=rows,common=len(common),removed=len(removed),new=len(new),all_winners=retention(winners),large_winners=retention(top),counts=dict(lower_entry=sum(cmap[k][1]['entry_price']<pmap[k][1]['entry_price'] for k in common),higher_entry=sum(cmap[k][1]['entry_price']>pmap[k][1]['entry_price'] for k in common)),largest_increment=max(rows,key=lambda r:r['delta_bps']) if rows else None)

def summarize():
    check();data={};lines=['# C63 vs pre-release EMA21 pullback — used DEV','', 'One distinct entry architecture, two first FULLs; no fake same-entry FIXED. Same fixed initial notional, existing modeled costs and censored tails; not account performance or creator replication.','', '|Period|Rule|Closed/open|WR%|Mean win|Mean loss|PF|Payoff|Terminal net|Cost2|Daily DD|','|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for per in PERIODS:
        par=gz(ROOT/prior.OUT/per/'RESULT.json.gz');res=gz(ROOT/OUT/per/'RESULT.json.gz');snap={k:a.snapshot(v) for k,v in [('C63',par),('ENTRY',res)]}
        account=bridge(par,res);put(ROOT/OUT/per/'EPISODE_BRIDGE.json',account)
        data[per]=dict(snapshots=snap,checks=prior.previous.checks(snap['C63'],snap['ENTRY']),episode_bridge_summary={k:v for k,v in account.items() if k!='rows'})
        for label,m in snap.items():
            fmt=lambda v:'NA' if v is None else f'{v:.2f}'
            lines.append('|'+ '|'.join([per,label,f"{m['closed']}/{m['open']}",fmt(None if m['win_rate'] is None else m['win_rate']*100)]+[fmt(m[k]) for k in ('average_win_bps','average_loss_bps','PF','realized_payoff','terminal_net_bps','terminal_cost2x_net_bps','marked_DD_trade_sum_bps')])+'|')
    goal=all(all(v['checks'].values()) for v in data.values());gain=all(v['checks']['net_up'] and v['checks']['cost2_up'] for v in data.values());status='DEVELOPMENT_GOAL_MET' if goal else 'PARTIAL_IMPROVEMENT' if gain else 'REJECT_KEEP_C63_PAUSE_THIS_BRANCH'
    put(ROOT/OUT/'SUMMARY.json',dict(status=status,periods=data,candidates=68,evaluations=120,new_candidates=1,new_FULL=2,new_FIXED=0,parent_replay=0,independent=False,formal_credit=0))
    lines+=['',status,'','On rejection, preserve C63 and close this entry hypothesis; no thresholds/period/symbol reselection or return to exit-tweaking within this scope.',''];(ROOT/OUT/'REPORT.md').write_text('\n'.join(lines));print('\n'.join(lines))
    put(ROOT/OUT/'EVIDENCE_HASHES.json',{str(x.relative_to(ROOT/OUT)):h(x) for x in (ROOT/OUT).rglob('*') if x.is_file() and x.name!='EVIDENCE_HASHES.json'})
if __name__=='__main__':
    q=argparse.ArgumentParser();q.add_argument('action',choices=['freeze','reserve','execute','summarize']);q.add_argument('--period',choices=PERIODS);q.add_argument('--remote');x=q.parse_args()
    if x.action=='freeze':freeze()
    elif x.action=='reserve':reserve(x.period)
    elif x.action=='execute':execute(x.period,x.remote)
    else:summarize()
