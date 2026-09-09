"""Independent saved-price/ER/range/first-exit/cost and attribution checks.

No strategy engine imports or alternate economic replay. Original input mode
reconstructs causal witnesses; routine CI verifies their pinned projections
and identical retained M1 paths without downloading historical prices.
"""
import argparse,fnmatch,hashlib,importlib.util,json,math,re
from collections import Counter
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
HERE=Path(__file__).resolve().parent
PRIOR='research/development_evidence/M1_ER14_ENTRY_AFTER_PR1231_V1'
EVIDENCE_SHA='c73471529767d0e522430b4e6bcd718a8f20ee59338b15b1d40ec506864f4aba'
KEY='m1_er_range_rescue_allocation'
BAR=14400000

def load(root=HERE):
    repo=Path(root).parents[2];path=repo/PRIOR/'verify_saved.py'
    if hashlib.sha256(path.read_bytes()).hexdigest()!='e02eaa4404bed983f20b690a16ced0cb58401feb2dfb44e24e6becaad3b965c6':raise ValueError('PRIOR_CHECKER_DRIFT')
    s=importlib.util.spec_from_file_location('prior_er_saved',path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
    return m,m.checker(repo)
old,v=load()
read,gz,sha,canon,need=old.read,old.gz,old.sha,old.canon,old.need
PERIODS=old.PERIODS
ORIGINAL_FEATURE=old.feature

def feature(event,source,checker):
    e=deepcopy(event);x=e['er_context'];r=x['range_context'];i=e['signal_index'];ts=e['signal_ts'];q=e['episode_start']
    x['eligible']=x['er_increase'];x['reason']=None if x['eligible'] else 'ER14_NOT_INCREASING'
    er_ok=ORIGINAL_FEATURE(e,source,checker)
    need(type(q) is int and 0<=q<i,'RANGE_EPISODE')
    highs=r['source_highs'];need(len(highs)==i-q,'RANGE_SOURCE_LENGTH')
    for j,z in enumerate(highs,q):
        need(type(z['index']) is int and z['index']==j and type(z['ts']) is int and z['ts']==ts-(i-j)*BAR,'RANGE_SOURCE_CLOCK')
        need(type(z['high']) in (int,float) and math.isfinite(z['high']) and z['high']>0,'RANGE_SOURCE_VALUE')
        if str(j) in source and 'high' in source[str(j)]:need(z['high']==source[str(j)]['high'],'RANGE_ORIGINAL_PRICE')
    high=max(z['high'] for z in highs);close=source[str(i)]['close'];escape=close>high;rescued=not er_ok and escape
    expected=dict(episode_start=q,episode_end=i-1,prior_high=high,signal_close=close,strict_escape=escape,rescued=rescued,
        available_at=ts,prior_available_at=ts-BAR,source_highs=highs)
    need(r==expected,'RANGE_ARITHMETIC_OR_CLOCK')
    actual=event['er_context'];allowed=er_ok or rescued
    need(actual['eligible'] is allowed and actual['reason']==(None if allowed else 'ER14_NOT_INCREASING'),'RESCUE_ELIGIBILITY')
    return allowed

def range_projection(result):
    return sorted([[e['symbol'],e['signal_index'],e['er_context']['range_context']] for e in result['events']],key=lambda x:(x[0],x[1]))

def originals(inputs,root=HERE):
    root=Path(root);repo=root.parents[2];spec=read(root/'SPEC.json');answer={}
    for per in PERIODS:
        path=Path(inputs)/f'{per}.json.gz';need(sha(path)==spec['input_packet_sha256'][per],'SOURCE_PACKET_SHA')
        packet=gz(path);raw=gz(root/per/'RAW.json.gz');result=gz(root/per/'RESULT.json.gz');original=gz(repo/old.OLD/'M1'/per/'RAW.json.gz');witness={}
        for symbol,data in raw.items():
            rows=packet['rows_by'][symbol];keep=set()
            for e in data['events']:
                i=e['signal_index'];keep.update(range(i-15,min(len(rows),i+2)));keep.update(range(e['episode_start'],i+1))
            for t in data['trades']+data['open_positions']:
                last=t.get('exit_index',t.get('mark_index'));keep.update(range(max(0,t['entry_index']-14),last+1))
            witness[symbol]={str(i):{k:rows[i][k] for k in ('bar_open_ts','bar_close_ts','open','high','low','close')} for i in sorted(keep)}
        with patch.object(old,'feature',feature):n,signals=old.check_raw(raw,result,original,packet['costs'],spec['periods'][per],witness,v)
        erproj=sorted([[e['symbol'],e['signal_index'],e['er_context']['source_closes']] for e in result['events']],key=lambda x:(x[0],x[1]))
        answer[per]=dict(original_input_sha256=sha(path),source_projection_sha256=hashlib.sha256(canon(erproj)).hexdigest(),
            range_projection_sha256=hashlib.sha256(canon(range_projection(result))).hexdigest(),raw_sha256=sha(root/per/'RAW.json.gz'),result_sha256=sha(root/per/'RESULT.json.gz'),
            positions=n,signals=signals,source_rows=sum(len(x) for x in witness.values()),source_first_exit_check=True,economic_replays=0)
    return answer

def details(parent,c62,result):
    pi,qi,ci=[v.complete_index(x) for x in (parent,c62,result)]
    restored=[]
    for k in sorted((pi.keys()&ci.keys())-qi.keys()):
        t=ci[k][1]
        restored.append(dict(symbol=k[0],signal_ts=k[2],origin=t['origin_key'],state=ci[k][0],net_bps=v.values(ci[k])['net_bps'],original_net_bps=v.values(pi[k])['net_bps']))
    return dict(versus_M1=old.detail(parent,result,v),versus_C62=old.detail(c62,result,v),
        restored_original_positions=restored,restored_winners=sum(x['state']=='C' and x['net_bps']>0 for x in restored),
        reallowed_losers=sum(x['state']=='C' and x['net_bps']<0 for x in restored),
        restored_winner_net_bps=sum(x['net_bps'] for x in restored if x['state']=='C' and x['net_bps']>0),
        reallowed_loss_net_bps=sum(x['net_bps'] for x in restored if x['state']=='C' and x['net_bps']<0),
        original_outcome_labels_are_features=False)

def verify(root=HERE,derived_sha=None):
    root=Path(root);repo=root.parents[2]
    need(sha(root/'EVIDENCE_HASHES.json')==EVIDENCE_SHA,'EVIDENCE_MANIFEST_DRIFT')
    for name,d in read(root/'EVIDENCE_HASHES.json').items():need(sha(root/name)==d,'EXECUTED_EVIDENCE_DRIFT:'+name)
    if derived_sha:need(sha(root/'DERIVED.json')==derived_sha,'DERIVED_FILE_DRIFT')
    spec=read(root/'SPEC.json');budget=deepcopy(read(root/'BUDGET.json'));slot=budget.pop(KEY)
    need((slot['reserved'],slot['started'],slot['completed'],slot['failed'],slot['remaining'])==(2,2,2,0,0),'UNFINISHED_SCOPE')
    need((budget['cumulative_actual'],budget['cumulative_actual_evaluations'])==(63,106),'COUNTS')
    need(budget['candidate_trials'][-1]['ordinal']==63 and [t['actual_experiment_ordinal'] for t in budget['trials'][-2:]]==[105,106],'ORDINALS')
    budget['candidate_trials']=budget['candidate_trials'][:-1];budget['trials']=budget['trials'][:-2];budget['cumulative_actual']-=1;budget['cumulative_actual_evaluations']-=2;budget['new_candidate_runs']-=1
    need(budget==read(repo/PRIOR/'BUDGET.json') and budget['chart_allocation']['remaining']==6,'PRIOR_HISTORY_CHANGED')
    need(sha(repo/PRIOR/'BUDGET.json')==spec['prior_budget_sha256'] and sha(repo/PRIOR/'SPEC.json')==spec['prior_spec_sha256'],'PRIOR_BYTES_CHANGED')
    for name,d in spec['source_files_sha256'].items():need(sha(repo/name)==d,'FROZEN_SOURCE_DRIFT:'+name)
    for per,files in spec['parent_results_sha256'].items():
        for name,d in files.items():need(sha(repo/old.OLD/'M1'/per/name)==d,'M1_DRIFT')
    for per,files in spec['comparator_sha256'].items():
        for name,d in files.items():need(sha(repo/PRIOR/per/name)==d,'C62_DRIFT')
    for per,d in spec['saved_c54_sha256'].items():need(sha(repo/old.C54/'B'/per/'RESULT.json.gz')==d,'C54_DRIFT')
    meta=read(root/'DERIVED.json');summary=read(root/'SUMMARY.json');costs=read(repo/old.C51/'COSTS.json');report=(root/'REPORT.md').read_text();count=signals=0;allflags=[]
    for per in PERIODS:
        d=root/per;r=gz(d/'RESULT.json.gz');raw=gz(d/'RAW.json.gz');parent=gz(repo/old.OLD/'M1'/per/'RESULT.json.gz');prior=gz(repo/PRIOR/per/'RESULT.json.gz');pr=gz(repo/old.OLD/'M1'/per/'RAW.json.gz')
        proof=meta['source_proof'][per];at=read(d/'ATTEMPT.json');start=read(d/'EXECUTION_STARTED.json');receipt=read(d/'RECEIPT.json')
        need(receipt['status']=='COMPLETED' and receipt['raw_sha256']==sha(d/'RAW.json.gz')==proof['raw_sha256'] and receipt['result_sha256']==sha(d/'RESULT.json.gz')==proof['result_sha256'],'RESULT_RECEIPT')
        need(receipt['spec_sha256']==at['spec_sha256']==sha(root/'SPEC.json'),'SPEC_IDENTITY')
        need(receipt['claim_commit']==start['claim_commit']==start['remote_readback_sha'] and at['owner_run']==start['owner_run'],'RUNTIME_CLAIM')
        need(spec['frozen_ns']<at['time_ns']<start['time_ns'],'PRE_OUTCOME_FREEZE')
        need(proof['original_input_sha256']==spec['input_packet_sha256'][per] and proof['range_projection_sha256']==hashlib.sha256(canon(range_projection(r))).hexdigest(),'RANGE_SOURCE_BINDING')
        with patch.object(old,'feature',feature):n,s=old.check_preserved(raw,r,pr,parent,costs,spec['periods'][per],proof,v)
        need((n,s)==(proof['positions'],proof['signals']),'PROOF_COUNTS');count+=n;signals+=s
        v.check_metrics(r)
        for ref,label in ((parent,'M1'),(prior,'C62')):v.compare_parent(ref,r,read(d/f'ACCOUNTING_{label}.json'))
        derived=details(parent,prior,r);v.same(meta['details'][per],derived,'DERIVED_DETAILS')
        flags=old.checks(parent,r,v);need(flags==summary['periods'][per]['checks'],'SUMMARY_FLAGS');allflags.append(flags)
        for label,result in (('M1',parent),('C62',prior),('C63',r)):
            m=result['metrics'];b=m['base_cost'];snap=summary['periods'][per]['snapshots'][label]
            v.subset(snap,{k:m[k] for k in ('terminal_net_bps','terminal_cost2x_net_bps','marked_DD_trade_sum_bps')},'SUMMARY_TOTALS')
            v.subset(snap,{k:b[k] for k in ('win_rate','average_win_bps','average_loss_bps','PF','realized_payoff')},'SUMMARY_AVERAGES')
            need(snap['closed']==len(result['trades']) and snap['open']==len(result['open_observations']),'SUMMARY_COUNTS')
            fmt=lambda x:'NA' if x is None else f'{x:.2f}'
            row='|'+ '|'.join([per,label,f"{snap['closed']}/{snap['open']}",fmt(None if b['win_rate'] is None else 100*b['win_rate'])]+[fmt(b[k]) for k in ('average_win_bps','average_loss_bps','realized_payoff','PF')]+[fmt(m[k]) for k in ('terminal_net_bps','terminal_cost2x_net_bps','marked_DD_trade_sum_bps')])+'|'
            need(row in report,'REPORT_TABLE')
    goal=all(all(f.values()) for f in allflags);gain=all(f['net_up'] and f['cost2_up'] for f in allflags)
    need(summary['status']==('DEVELOPMENT_GOAL_MET' if goal else 'PARTIAL_IMPROVEMENT' if gain else 'REJECT_KEEP_M1_AND_C54'),'FALSE_GOAL')
    return dict(status=summary['status'],positions=count,signals=signals,candidates=63,evaluations=106,new_economic_replays=0,details=meta['details'])

if __name__=='__main__':
    q=argparse.ArgumentParser();q.add_argument('--derived-sha256',required=True);q.add_argument('--inputs');x=q.parse_args()
    if x.inputs:need(originals(x.inputs)==read(HERE/'DERIVED.json')['source_proof'],'ORIGINAL_SOURCE_PROOF_MISMATCH')
    print(json.dumps(verify(derived_sha=x.derived_sha256),indent=2))
