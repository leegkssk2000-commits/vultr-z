"""C56 saved arithmetic only; independently bind source observations and outcomes."""
import argparse,fnmatch,gzip,hashlib,importlib.util,json,math,re
from collections import Counter,defaultdict
from copy import deepcopy
from pathlib import Path
HERE=Path(__file__).resolve().parent
PARENT='research/development_evidence/KR3_C51_ENTRY_CONTEXT_AB_AFTER_PR1225_V1'
C51='research/development_evidence/KR3_PROFIT_ZONE_PRESERVATION_AFTER_PR1223_V1'
KR3='research/development_evidence/FOCUSED_REPAIR_20260907_V1/KR3'
PERIODS=('DEV2025','SEEN2026');KEY='c54_effort_progress_allocation';BAR=14400000
VETO='RECOVERY_EFFORT_WITHOUT_PROGRESS_VETO';MISSING='RECOVERY_VOLUME_CONTEXT_UNAVAILABLE'
def read(p):return json.loads(Path(p).read_bytes())
def gz(p):return json.loads(gzip.decompress(Path(p).read_bytes()))
def canonical(x):return json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
def digest(x):return hashlib.sha256(canonical(x)).hexdigest()
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def need(ok,msg):
    if not ok:raise ValueError(msg)
def checker(repo):
    s=importlib.util.spec_from_file_location('c51_saved_independent',repo/C51/'verify_saved.py');v=importlib.util.module_from_spec(s);s.loader.exec_module(v);return v

def source_projection(r):
    return sorted([[e['symbol'],e['signal_index'],e['entry_context']['participation'].get('source_bars')] for e in r['events']],key=lambda x:(x[0],x[1]))

def check_features(parent,r,v):
    old=v.index(parent['events']);allowed=set();observations=0
    for e in r['events']:
        o=e['entry_context'];z=o['participation'];i=e['signal_index'];ts=e['signal_ts'];q=o['trend_index']
        need({k:x for k,x in o.items() if k!='participation'}==old[v.identity(e)]['entry_context'],'PARENT_ENTRY_CONTEXT_CHANGED')
        need(o['signal_index']==i and o['available_at']==ts,'FEATURE_CLOCK')
        need(o['B']==(o['extension_atr'] is not None and 0<o['extension_atr']<=1),'PARENT_ATR_PREDICATE')
        if q is None or not 0<=q<i-1:
            need(z==dict(available=False,veto=True,reason=MISSING),'MISSING_EPISODE');veto=True
        else:
            bars=z['source_bars'];need(len(bars)==i-q,'SOURCE_BAR_COUNT')
            for j,row in enumerate(bars,q+1):
                need(row['index']==j and row['ts']==ts-(i-j)*BAR,'SOURCE_CLOCK')
                need(all(type(row[k]) in (float,int) and math.isfinite(row[k]) for k in ('open','close','volume')),'SOURCE_NONFINITE')
                need(row['open']>0 and row['close']>0 and row['volume']>=0,'SOURCE_INVALID')
            previous=bars[:-1];last=bars[-1];n=len(previous)
            mv=sum(x['volume'] for x in previous)/n;mb=sum(abs(x['close']-x['open']) for x in previous)/n
            progress=max(0,last['close']-last['open']);available=mv>0;high=available and last['volume']>mv;weak=progress<=mb
            veto=not available or (high and weak)
            expected=dict(available=available,veto=veto,reason=MISSING if not available else VETO if veto else None,
                pullback_start_index=q+1,pullback_end_index=i-1,pullback_count=n,
                pullback_last_available_at=ts-BAR,mean_pullback_volume=mv,signal_volume=last['volume'],
                mean_pullback_abs_body=mb,signal_bull_body=progress,relative_volume=last['volume']/mv if available else None,
                higher_volume=high,weak_bull_body=weak,available_at=ts,source_bars=bars)
            v.same(z,expected,'PARTICIPATION_ARITHMETIC')
            for key in ('pullback_start_index','pullback_end_index','pullback_count','pullback_last_available_at','available_at'):
                need(type(z[key]) is int and z[key]==expected[key],'EXACT_FEATURE_CLOCK')
            observations+=len(bars)
        good=o['B'] and not veto;reason=e['exclusion_reason']
        if e['status']!='EXCLUDED':need(good,'DISALLOWED_ADMISSION');allowed.add(v.identity(e))
        if reason==VETO:need(o['B'] and veto and z['available'],'WRONG_EFFORT_VETO')
        if reason==MISSING:need(o['B'] and not z['available'],'WRONG_MISSING_VETO')
        if reason=='ENTRY_CONTEXT_B_VETO':need(not o['B'],'WRONG_ATR_VETO')
    need(allowed==set(v.complete_index(r)),'EVENT_POSITION_COVERAGE')
    return observations

def details(parent,r,v):
    p,c=v.complete_index(parent),v.complete_index(r);removed=[p[k] for k in p.keys()-c.keys()]
    changes=[]
    for k in sorted(p.keys()|c.keys()):
        row=c.get(k,p.get(k))[1]
        changes.append(dict(origin=row['origin_key'],symbol=k[0],signal_ts=k[2],delta_bps=v.values(c.get(k))['net_bps']-v.values(p.get(k))['net_bps']))
    by=defaultdict(float)
    for x in changes:by[x['symbol']]+=x['delta_bps']
    winners=sorted([t for t in p.values() if t[0]=='C' and t[1]['net_bps']>0],key=lambda x:(-x[1]['net_bps'],x[1]['origin_key']))
    def retained(items):return sum(min(x[1]['net_bps'],max(0,v.values(c.get(v.identity(x[1])))['net_bps'])) for x in items)/sum(x[1]['net_bps'] for x in items)
    dn=r['metrics']['terminal_net_bps']-parent['metrics']['terminal_net_bps'];largest=max(changes,key=lambda x:(x['delta_bps'],x['origin']))
    return dict(net_delta_bps=dn,cost2_delta_bps=r['metrics']['terminal_cost2x_net_bps']-parent['metrics']['terminal_cost2x_net_bps'],
        avoided_closed_loss_bps=-sum(t[1]['net_bps'] for t in removed if t[0]=='C' and t[1]['net_bps']<0),
        foregone_closed_win_bps=sum(t[1]['net_bps'] for t in removed if t[0]=='C' and t[1]['net_bps']>0),
        avoided_open_mark_bps=-sum(v.values(t)['net_bps'] for t in removed if t[0]=='O'),
        winner_amount_retention=retained(winners),large_winner_retention=retained(winners[:math.ceil(.1*len(winners))]),
        by_symbol_delta_bps=dict(by),largest_positive_origin=largest,without_largest_increment_bps=dn-largest['delta_bps'],
        without_hype_delta_bps=dn-by.get('HYPE-USDT',0.))

def checks(p,c,v):
    def up(a,b):return a is not None and b is not None and a>b and not v.near(a,b)
    return dict(WR_up=up(c['base_cost']['win_rate'],p['base_cost']['win_rate']),terminal_net_up=up(c['terminal_net_bps'],p['terminal_net_bps']),
        cost2_up=up(c['terminal_cost2x_net_bps'],p['terminal_cost2x_net_bps']),daily_DD_down=up(p['marked_DD_trade_sum_bps'],c['marked_DD_trade_sum_bps']))

def markdown_table(per,label,r):
    m=r['metrics'];b=m['base_cost'];fmt=lambda x:'NA' if x is None else f'{x:.2f}'
    return '|'+ '|'.join([per,label,f"{len(r['trades'])}/{len(r['open_observations'])}",fmt(None if b['win_rate'] is None else 100*b['win_rate'])]+[fmt(b[k]) for k in ('average_win_bps','average_loss_bps','realized_payoff','PF')]+[fmt(m[k]) for k in ('terminal_net_bps','terminal_cost2x_net_bps','marked_DD_trade_sum_bps')])+'|'

def verify(root=HERE,pin=None):
    root=Path(root);repo=root.parents[2];v=checker(repo)
    if pin:need(sha(root/'FINAL_HASHES.json')==pin,'MANIFEST_DRIFT')
    for name,d in read(root/'FINAL_HASHES.json').items():need(sha(root/name)==d,'ARTIFACT_DRIFT:'+name)
    spec=read(root/'SPEC.json');budget=read(root/'BUDGET.json');pro=deepcopy(budget);slot=pro.pop(KEY)
    need((slot['reserved'],slot['started'],slot['completed'],slot['failed'],slot['remaining'])==(2,2,2,0,0),'UNFINISHED_EXECUTION')
    need((pro['cumulative_actual'],pro['cumulative_actual_evaluations'])==(56,92),'COUNTS')
    need([x['actual_experiment_ordinal'] for x in pro['trials'][-2:]]==[91,92] and pro['candidate_trials'][-1]['ordinal']==56,'ORDINALS')
    pro['trials']=pro['trials'][:-2];pro['candidate_trials']=pro['candidate_trials'][:-1]
    pro['cumulative_actual']-=1;pro['cumulative_actual_evaluations']-=2;pro['new_candidate_runs']-=1
    need(pro==read(repo/PARENT/'BUDGET.json'),'PRIOR_HISTORY_CHANGED')
    need(sha(repo/PARENT/'BUDGET.json')==spec['prior_budget_sha256'],'PRIOR_BUDGET_DRIFT')
    need(sha(repo/PARENT/'SPEC.json')==spec['parent_spec_sha256'],'PARENT_SPEC_DRIFT')
    for name,d in spec['source_files_sha256'].items():need(sha(repo/name)==d,'FROZEN_SOURCE_DRIFT:'+name)
    wf=(repo/'.github/workflows/kr3-c54-effort-progress-v1.yml').read_text();patterns=re.findall(r"^\s+- '([^']+)'\s*$",wf,re.M)
    for name in set(spec['source_files_sha256'])|{C51+'/COSTS.json',C51+'/verify_saved.py',PARENT+'/BUDGET.json'}:
        need(any(fnmatch.fnmatchcase(name,p) for p in patterns),'UNCOVERED_TRIGGER:'+name)
    costs=read(repo/C51/'COSTS.json');summary=read(root/'SUMMARY.json');binding=read(root/'SOURCE_BINDING.json');ds=read(root/'DETAILS.json');report=(root/'REPORT.md').read_text()
    output={};count=source_rows=0;allchecks=[]
    for per in PERIODS:
        out=root/per;r=gz(out/'RESULT.json.gz');raw=gz(out/'RAW.json.gz');receipt=read(out/'RECEIPT.json');at=read(out/'ATTEMPT.json');start=read(out/'EXECUTION_STARTED.json')
        parent_path=repo/PARENT/'B'/per/'RESULT.json.gz';need(sha(parent_path)==spec['parent_results_sha256'][per],'PARENT_RESULT_DRIFT');parent=gz(parent_path)
        need(receipt['status']=='COMPLETED' and receipt['result_sha256']==sha(out/'RESULT.json.gz') and receipt['raw_sha256']==sha(out/'RAW.json.gz'),'EXECUTED_RECEIPT')
        need(receipt['spec_sha256']==at['spec_sha256']==sha(root/'SPEC.json'),'SPEC_BINDING')
        need(receipt['claim_commit']==start['claim_commit']==start['remote_readback_sha'] and at['owner_run']==start['owner_run'],'REMOTE_CLAIM')
        need(spec['frozen_ns']<at['time_ns']<start['time_ns'],'PREFREEZE_ORDER')
        count+=v.check_raw(raw,r,costs,spec['periods'][per]);v.check_metrics(r);source_rows+=check_features(parent,r,v)
        need(binding[per]['input_packet_sha256']==spec['input_packet_sha256'][per] and binding[per]['projection_sha256']==digest(source_projection(r)),'ORIGINAL_SOURCE_BINDING')
        derived=details(parent,r,v);v.same(ds[per],derived,'DERIVED_DETAILS')
        for ref,label in [(parent,'C54'),(gz(repo/C51/per/'RESULT.json.gz'),'C51')]:
            accounting=read(out/f'ACCOUNTING_{label}.json');v.compare_parent(ref,r,accounting)
        # KR3 is an original cumulative control, not the current parent. Bind its
        # saved bridge totals to the old immutable C54 comparison, not a new replay.
        old_manifest=repo/PARENT/'FINAL_HASHES.json'
        need(sha(old_manifest)=='6aed19ef05f68518c1257916b6239f04120de636e4fd386fb9727fa056d25d64','C54_MANIFEST_DRIFT')
        path='B/'+per+'/ACCOUNTING_KR3.json';need(sha(repo/PARENT/path)==read(old_manifest)[path],'KR3_CONTROL_BRIDGE_DRIFT')
        prior_bridge=read(repo/PARENT/path)['bridges'];kb=read(out/'ACCOUNTING_KR3.json')
        ci0=v.complete_index(r)
        for basis,closed_only in [('closed',True),('marked',False)]:
            pv=prior_bridge[basis]['parent'];cv={key:sum(v.values(t,closed_only)[key] for t in ci0.values()) for key in v.values(None)}
            delta={key:cv[key]-pv[key] for key in cv}
            v.subset(kb['bridges'][basis],dict(parent=pv,child=cv,delta=delta),'KR3_CUMULATIVE_BRIDGE')
            summed={key:sum(group[basis]['delta'][key] for group in kb['groups'].values()) for key in cv}
            v.same(summed,delta,'KR3_GROUP_TOTALS')
        pi,ci=v.complete_index(parent),v.complete_index(r)
        for k in pi.keys()&ci.keys():
            need(pi[k][0]==ci[k][0],'COMMON_STATE_CHANGED');v.same(v.values(pi[k]),v.values(ci[k]),'COMMON_ECONOMICS_CHANGED')
            fields=['entry_price','entry_ts','hold_ms']+(['exit_price','exit_ts','exit_reason'] if pi[k][0]=='C' else ['mark_price','mark_ts'])
            for field in fields:need(pi[k][1].get(field)==ci[k][1].get(field),'COMMON_PATH_CHANGED:'+field)
        cm=checks(parent['metrics'],r['metrics'],v);need(summary['periods'][per]['checks']==cm,'SUMMARY_CHECKS');allchecks.append(cm)
        for label,actual in [('parent',parent),('child',r)]:
            snap=summary['periods'][per][label];m=actual['metrics']
            v.subset(snap,{k:m['base_cost'][k] for k in ('win_rate','average_win_bps','average_loss_bps','realized_payoff','PF')},'SNAPSHOT')
            v.subset(snap,{k:m[k] for k in ('terminal_net_bps','terminal_cost2x_net_bps','marked_DD_trade_sum_bps')},'TOTAL_SNAPSHOT')
            need(markdown_table(per,'C54' if label=='parent' else 'C56',actual) in report,'REPORT_ECONOMIC_TABLE')
        output[per]={'checks':cm,**{k:derived[k] for k in ('net_delta_bps','cost2_delta_bps','avoided_closed_loss_bps','foregone_closed_win_bps','winner_amount_retention','large_winner_retention')}}
    goal=all(all(x.values()) for x in allchecks);econ=all(x['terminal_net_up'] and x['cost2_up'] for x in allchecks)
    status='DEVELOPMENT_GOAL_MET' if goal else 'PARTIAL_IMPROVEMENT' if econ else 'REJECT_KEEP_C54'
    need(summary['status']==status and status in report,'OVERSTATED_GOAL')
    return dict(status=status,raw_positions=count,feature_source_rows=source_rows,candidates=56,evaluations=92,new_economic_replays=0,periods=output)
if __name__=='__main__':
    q=argparse.ArgumentParser();q.add_argument('--manifest-sha256',required=True);x=q.parse_args();print(json.dumps(verify(pin=x.manifest_sha256),indent=2))
