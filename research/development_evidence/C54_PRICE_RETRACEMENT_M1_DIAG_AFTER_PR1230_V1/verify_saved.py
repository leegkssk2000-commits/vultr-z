"""Saved arithmetic/causal-context verifier. No strategy or market replay."""
import argparse,fnmatch,gzip,hashlib,importlib.util,json,math,re
from collections import defaultdict
from copy import deepcopy
from pathlib import Path
HERE=Path(__file__).resolve().parent
C54='research/development_evidence/KR3_C51_ENTRY_CONTEXT_AB_AFTER_PR1225_V1'
C51='research/development_evidence/KR3_PROFIT_ZONE_PRESERVATION_AFTER_PR1223_V1'
OLD='research/development_evidence/TOP5_SOURCE_CHART_MECHANISMS_AFTER_PR1228_V1'
MODES=('FIB','SHIFTED');PERIODS=('DEV2025','SEEN2026');KEY='price_only_retracement_allocation'
def read(p):return json.loads(Path(p).read_bytes())
def gz(p):return json.loads(gzip.decompress(Path(p).read_bytes()))
def canon(x):return json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def need(ok,msg):
    if not ok:raise ValueError(msg)
def checker(repo):
    s=importlib.util.spec_from_file_location('prior_saved',repo/C51/'verify_saved.py');v=importlib.util.module_from_spec(s);s.loader.exec_module(v);return v

def check_context(parent,result,mode,v):
    old=v.index(parent['events']);positions=set(v.complete_index(result));admitted=set()
    for e in result['events']:
        o=e['entry_context'];x=o['price_context'];i=e['signal_index'];t=e['signal_ts'];q=o['trend_index']
        need({k:z for k,z in o.items() if k!='price_context'}==old[v.identity(e)]['entry_context'],'ORIGINAL_CONTEXT_CHANGED')
        need(type(x['available_at']) is int and x['available_at']==t and x['signal_index']==i,'PRICE_CONTEXT_CLOCK')
        need(x['volume_used'] is False and x['avwap_used'] is False and x['mode']==mode,'VOLUME_OR_VARIANT_DRIFT')
        if x['anchor'] is None:eligible=False;need(x['depth'] is None,'UNANCHORED_DEPTH')
        else:
            an=x['anchor'];lo,hi=an['low'],an['high']
            need(q is not None and lo['index']<hi['index']<=q<i-1,'ANCHOR_OCCURRENCE_CLOCK')
            for z in (lo,hi):
                need(z['known_index']==z['index']+2 and z['known_index']<i,'LOOKAHEAD_PIVOT')
                need(z['available_at']==t-(i-z['known_index'])*14400000,'PIVOT_AVAILABILITY')
            need(an['known_at']==max(lo['available_at'],hi['available_at']) and an['known_at']<t,'PAIR_AVAILABILITY')
            need(x['pullback_start']==q+1 and x['pullback_end']==i-1,'PULLBACK_WINDOW')
            depth=(hi['price']-x['pullback_low'])/(hi['price']-lo['price']);v.same(x['depth'],depth,'RETRACEMENT_ARITHMETIC')
            lower,upper=(.382,.618) if mode=='FIB' else (.350,.586);eligible=lower<=depth<=upper
        need(x['eligible']==eligible,'INCORRECT_ZONE_GATE')
        if e['status']!='EXCLUDED':need(o['B'] and eligible,'INELIGIBLE_POSITION');admitted.add(v.identity(e))
        if e['exclusion_reason']=='PRICE_RETRACEMENT_ZONE_VETO':need(o['B'] and x['anchor'] is not None and not eligible,'INCORRECT_ZONE_VETO')
        if e['exclusion_reason']=='NO_CONFIRMED_PRICE_ANCHOR':need(o['B'] and x['anchor'] is None,'INCORRECT_ANCHOR_VETO')
    need(admitted==positions and set(old)==set(v.index(result['events'])),'EVENT_COVERAGE')
    return hashlib.sha256(canon(sorted([[e['symbol'],e['signal_index'],e['entry_context']['price_context']] for e in result['events']],key=lambda z:(z[0],z[1])))).hexdigest()

def check_cell(root,per,mode,v,costs,spec):
    d=root/mode/per;repo=root.parents[2];r=gz(d/'RESULT.json.gz');raw=gz(d/'RAW.json.gz');parent=gz(repo/C54/'B'/per/'RESULT.json.gz')
    receipt,at,started=[read(d/name) for name in ('RECEIPT.json','ATTEMPT.json','EXECUTION_STARTED.json')]
    need(receipt['status']=='COMPLETED' and receipt['raw_sha256']==sha(d/'RAW.json.gz') and receipt['result_sha256']==sha(d/'RESULT.json.gz'),'RESULT_RECEIPT')
    need(receipt['spec_sha256']==at['spec_sha256']==sha(root/'SPEC.json'),'SPEC_IDENTITY')
    need(receipt['claim_commit']==started['claim_commit']==started['remote_readback_sha'] and at['owner_run']==started['owner_run'],'RUNTIME_CLAIM')
    need(spec['frozen_ns']<at['time_ns']<started['time_ns'],'PRE_OUTCOME_FREEZE')
    count=v.check_raw(raw,r,costs,spec['periods'][per]);v.check_metrics(r);v.compare_parent(parent,r,read(d/'ACCOUNTING_C54.json'))
    proof=read(root/'PRICE_SOURCE_PROOF.json')[mode+'/'+per]
    need(proof['source_projection_sha256']==check_context(parent,r,mode,v) and proof['input_packet_sha256']==spec['input_packet_sha256'][per],'PRICE_SOURCE_BINDING')
    pi,ci=v.complete_index(parent),v.complete_index(r)
    for key in pi.keys()&ci.keys():
        need(pi[key][0]==ci[key][0],'COMMON_STATE_CHANGED');v.same(v.values(pi[key]),v.values(ci[key]),'COMMON_ECONOMICS')
        for field in ('entry_ts','entry_price','exit_ts','exit_price','mark_ts','mark_price','exit_reason','hold_ms'):need(pi[key][1].get(field)==ci[key][1].get(field),'COMMON_GEOMETRY')
    return count

def check_m1(root,v,costs):
    repo=root.parents[2];saved=read(root/'M1_DIAGNOSIS.json');total=0
    for per in PERIODS:
        r=gz(repo/OLD/'M1'/per/'RESULT.json.gz');raw=gz(repo/OLD/'M1'/per/'RAW.json.gz');groups=defaultdict(lambda:dict(count=0,net_bps=0.));exits=defaultdict(lambda:dict(count=0,wins=0,net_bps=0.));rows=[]
        v.check_metrics(r)
        for t in r['trades']:
            symbol=t['symbol'];i=t['signal_index'];source=next(x for x in raw[symbol]['trades'] if x['signal_index']==i)
            v.subset(t,source,'M1_RAW_GEOMETRY');gross=(t['exit_price']/t['entry_price']-1)*10000
            parts,cost,_=v.costs_for(costs[symbol],t['entry_ts'],t['exit_ts']);v.subset(t,parts,'M1_COST');v.same(t['net_bps'],gross-cost,'M1_NET');v.same(t['cost2x_net_bps'],gross-2*cost,'M1_COST2')
            observed=[z for z in raw[symbol]['trace'] if z.get('signal_index')==i and z['kind']=='HELD_CLOSE_OBSERVATION']
            need(observed and all(t['entry_ts']<z['ts']<=t['exit_ts'] for z in observed),'M1_CLOCK')
            path=[(z['ts'],(z['close']/t['entry_price']-1)*10000-v.costs_for(costs[symbol],t['entry_ts'],z['ts'])[1]) for z in observed]
            positive=[t0 for t0,n in path if n>0];group='FINAL_WIN' if t['net_bps']>0 else 'FINAL_FLAT' if t['net_bps']==0 else 'POSITIVE_CLOSE_THEN_LOSS' if positive else 'NEVER_POSITIVE_HELD_CLOSE_LOSS'
            groups[group]['count']+=1;groups[group]['net_bps']+=t['net_bps'];reason=t['exit_reason'];exits[reason]['count']+=1;exits[reason]['wins']+=int(t['net_bps']>0);exits[reason]['net_bps']+=t['net_bps']
            rows.append(dict(symbol=symbol,origin=t['origin_key'],entry_ts=t['entry_ts'],exit_ts=t['exit_ts'],final_net_bps=t['net_bps'],exit_reason=reason,group=group,held_closes=len(path),observed_peak_net_bps=max(n for _,n in path),first_positive_ts=positive[0] if positive else None))
        v.same(saved[per]['groups'],dict(groups),'M1_GROUPS');v.same(saved[per]['exit_reasons'],dict(exits),'M1_EXITS');v.same(saved[per]['rows'],rows,'M1_DIAGNOSTIC_ROWS')
        need(saved[per]['open_positions']==len(r['open_observations']) and saved[per]['labels_are_execution_features'] is False,'M1_STATUS')
        for name,d in saved[per]['source_sha256'].items():need(sha(repo/OLD/'M1'/per/name)==d,'M1_SOURCE_HASH')
        total+=len(rows)
    return total

def verify(root=HERE,pin=None):
    root=Path(root);repo=root.parents[2];v=checker(repo)
    if pin:need(sha(root/'FINAL_HASHES.json')==pin,'MANIFEST_DRIFT')
    for name,d in read(root/'FINAL_HASHES.json').items():need(sha(root/name)==d,'ARTIFACT_DRIFT:'+name)
    spec=read(root/'SPEC.json');budget=read(root/'BUDGET.json');projected=deepcopy(budget);slot=projected.pop(KEY)
    need((slot['reserved'],slot['started'],slot['completed'],slot['failed'],slot['remaining'])==(4,4,4,0,0),'UNFINISHED_SCOPE')
    need((projected['cumulative_actual'],projected['cumulative_actual_evaluations'])==(61,102),'WRONG_COUNTER')
    need([x['actual_experiment_ordinal'] for x in projected['trials'][-4:]]==[99,100,101,102] and [x['ordinal'] for x in projected['candidate_trials'][-2:]]==[60,61],'WRONG_ORDINALS')
    projected['trials']=projected['trials'][:-4];projected['candidate_trials']=projected['candidate_trials'][:-2];projected['cumulative_actual']-=2;projected['cumulative_actual_evaluations']-=4;projected['new_candidate_runs']-=2
    need(projected==read(repo/OLD/'BUDGET.json'),'OLD_HISTORY_CHANGED')
    need(projected['chart_allocation']['remaining']==spec['prior_unused_TF_slots']==6,'OLD_TF_SLOTS_CHANGED')
    need(sha(repo/OLD/'BUDGET.json')==spec['prior_budget_sha256'] and sha(repo/OLD/'SPEC.json')==spec['prior_spec_sha256'],'OLD_BYTES_CHANGED')
    for name,d in spec['source_files_sha256'].items():need(sha(repo/name)==d,'FROZEN_SOURCE_CHANGED:'+name)
    for per,d in spec['parent_results_sha256'].items():need(sha(repo/C54/'B'/per/'RESULT.json.gz')==d,'C54_BYTES_CHANGED')
    for per,files in spec['m1_results_sha256'].items():
        for name,d in files.items():need(sha(repo/OLD/'M1'/per/name)==d,'ORIGINAL_M1_FROZEN_BYTES')
    wf=(repo/'.github/workflows/c54-price-retracement-v1.yml').read_text();patterns=re.findall(r"^\s+- '([^']+)'\s*$",wf,re.M)
    required=set(spec['source_files_sha256'])|{C51+'/COSTS.json',C51+'/verify_saved.py',OLD+'/BUDGET.json'}
    for name in required:need(any(fnmatch.fnmatchcase(name,q) for q in patterns),'UNCOVERED_DEPENDENCY:'+name)
    costs=read(repo/C51/'COSTS.json');count=sum(check_cell(root,per,m,v,costs,spec) for per in PERIODS for m in MODES)
    summary=read(root/'SUMMARY.json');report=(root/'REPORT.md').read_text()
    for per in PERIODS:
        ps=gz(repo/C54/'B'/per/'RESULT.json.gz')['metrics']
        for m in MODES:
            cm=gz(root/m/per/'RESULT.json.gz')['metrics'];entry=summary['periods'][per][m]
            def up(x,y):return x is not None and y is not None and x>y and not v.near(x,y)
            flags=dict(WR_up=up(cm['base_cost']['win_rate'],ps['base_cost']['win_rate']),net_up=up(cm['terminal_net_bps'],ps['terminal_net_bps']),cost2_up=up(cm['terminal_cost2x_net_bps'],ps['terminal_cost2x_net_bps']),DD_down=up(ps['marked_DD_trade_sum_bps'],cm['marked_DD_trade_sum_bps']))
            need(flags==entry['checks'],'SUMMARY_FLAGS')
            v.subset(entry['snapshot'],{k:cm[k] for k in ('terminal_net_bps','terminal_cost2x_net_bps','marked_DD_trade_sum_bps')},'SUMMARY_TOTALS')
            v.subset(entry['snapshot'],{k:cm['base_cost'][k] for k in ('win_rate','realized_payoff','PF')},'SUMMARY_COMPLETED')
            snap=entry['snapshot'];fmt=lambda x:'NA' if x is None else f'{x:.2f}'
            table='|'+ '|'.join([per,m,f"{snap['closed']}/{snap['open']}",fmt(None if snap['win_rate'] is None else 100*snap['win_rate'])]+[fmt(snap[k]) for k in ('realized_payoff','PF','terminal_net_bps','terminal_cost2x_net_bps','marked_DD_trade_sum_bps')]+[fmt(snap['terminal_net_bps']-ps['terminal_net_bps'])])+'|'
            need(table in report,'REPORT_ECONOMIC_TABLE')
    status={m:('DEVELOPMENT_GOAL_MET' if all(all(summary['periods'][per][m]['checks'].values()) for per in PERIODS) else 'PARTIAL_IMPROVEMENT' if all(summary['periods'][per][m]['checks']['net_up'] and summary['periods'][per][m]['checks']['cost2_up'] for per in PERIODS) else 'REJECT_KEEP_C54') for m in MODES}
    need(status==summary['status'],'GOAL_CLASSIFICATION')
    return dict(status=status,child_raw_positions=count,original_M1_closed_checked=check_m1(root,v,costs),candidates=61,evaluations=102,old_TF_unused_slots=6,new_economic_replay=0)
if __name__=='__main__':
    q=argparse.ArgumentParser();q.add_argument('--manifest-sha256',required=True);a=q.parse_args();print(json.dumps(verify(pin=a.manifest_sha256),indent=2))
