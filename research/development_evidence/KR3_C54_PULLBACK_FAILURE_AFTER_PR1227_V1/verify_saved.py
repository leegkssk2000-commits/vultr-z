"""Saved checks only. No strategy import, source request or economic replay."""
import argparse,gzip,hashlib,importlib.util,json,math,fnmatch,re
from pathlib import Path
from copy import deepcopy
HERE=Path(__file__).resolve().parent
PARENT='research/development_evidence/KR3_C51_ENTRY_CONTEXT_AB_AFTER_PR1225_V1'
C51='research/development_evidence/KR3_PROFIT_ZONE_PRESERVATION_AFTER_PR1223_V1'
PRIOR='research/development_evidence/KR3_C54_EFFORT_PROGRESS_AFTER_PR1226_V1'
KEY='c54_pullback_failure_allocation';PERIODS=('DEV2025','SEEN2026');BAR=14400000
FLOOR='C54_ORIGINAL_PULLBACK_FLOOR_LOST_CLOSE';EXIT='C54_ORIGINAL_PULLBACK_FLOOR_LOST_NEXT_OPEN'
def read(p):return json.loads(Path(p).read_bytes())
def gz(p):return json.loads(gzip.decompress(Path(p).read_bytes()))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def canonical(x):return json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
def digest(x):return hashlib.sha256(canonical(x)).hexdigest()
def need(ok,msg):
    if not ok:raise ValueError(msg)
def checker(repo):
    spec=importlib.util.spec_from_file_location('c51_independent_saved',repo/C51/'verify_saved.py');v=importlib.util.module_from_spec(spec);spec.loader.exec_module(v);return v

def projection(raw):
    result=[]
    for sym,r in sorted(raw.items()):
        for t in r['trades']+r['open_positions']:
            i=t['signal_index'];closed='exit_price' in t
            result.append({'symbol':sym,'signal_index':i,'floor':t['original_pullback_floor'],
              'entry_index':t['entry_index'],'entry_ts':t['entry_ts'],'entry_price':t['entry_price'],
              'end_index':t['exit_index'] if closed else t['mark_index'],
              'end_ts':t['exit_ts'] if closed else t['mark_ts'],
              'end_price':t['exit_price'] if closed else t['mark_price'],
              'semantics':t.get('exit_timestamp_semantics') if closed else 'MARKED_LAST_CLOSE',
              'floor_triggers':[{k:x[k] for k in ('index','ts','observed_close')} for x in r['trace'] if x['signal_index']==i and x['kind']==FLOOR]})
    return sorted(result,key=lambda x:(x['symbol'],x['signal_index']))

def check_floor(raw,result,parent,v):
    pe=v.index(parent['events']);ce=v.index(result['events'])
    need(pe.keys()==ce.keys(),'SIGNAL_UNIVERSE')
    for k,e in ce.items():need(e['entry_context']==pe[k]['entry_context'],'C54_ENTRY_FEATURE_CHANGED')
    count=0
    for sym,r in raw.items():
        events={e['signal_index']:e for e in r['events']}
        positions={t['signal_index']:t for t in r['trades']+r['open_positions']}
        for i,t in positions.items():
            floor=t['original_pullback_floor'];q=events[i]['entry_context']['trend_index'];ts=t['signal_ts']
            if q is None:
                need(floor==dict(available=False,reason='NO_PREENTRY_PULLBACK',signal_index=i),'MISSING_FLOOR')
            else:
                need(floor['available'] and floor['trend_index']==q and floor['start_index']==q+1 and floor['end_index']==i,'FLOOR_ORIGIN')
                need(floor['available_at']==ts and q<i-1,'FLOOR_AVAILABLE')
                source=floor['source'];need(len(source)==i-q,'FLOOR_SOURCE_LENGTH')
                for j,row in enumerate(source,q+1):
                    need(type(row['index']) is int and row['index']==j and row['bar_close_ts']==ts+(j-i)*BAR,'FLOOR_SOURCE_CLOCK')
                    need(type(row['low']) in (int,float) and math.isfinite(row['low']) and row['low']>0,'FLOOR_SOURCE_LOW')
                v.same(floor['price'],min(x['low'] for x in source),'FLOOR_MINIMUM')
            trace=[x for x in r['trace'] if x['signal_index']==i]
            entry=[x for x in trace if x['kind']=='ENTRY_NEXT_OPEN']
            need(len(entry)==1 and entry[0]['original_pullback_floor']==floor,'ENTRY_FLOOR_BINDING')
            hits=[x for x in trace if x['kind']==FLOOR];fills=[x for x in trace if x['kind']==EXIT]
            need(len(hits)<=1 and len(fills)<=1,'DUPLICATE_FLOOR_INTENT')
            if hits:
                x=hits[0];j=x['index'];count+=1
                need(floor['available'] and j>=t['entry_index'] and x['ts']==ts+(j-i)*BAR,'TRIGGER_CLOCK')
                need(x['original_pullback_floor_condition'] is True and x['original_pullback_floor']==floor,'TRIGGER_FLOOR')
                need(x['observed_close']<floor['price'] and not x['ema_condition'] and not x['runner_condition'],'TRIGGER_PREDICATE')
                need(t['profit_zone_state']['armed_index'] is None,'FLOOR_AFTER_C51_ARM')
                need(t['low_exit_state']['status']=='LOW_EXIT_SUPPRESSED_FOR_THIS_POSITION','PARENT_LOW_PRIORITY')
                if 'exit_price' in t:
                    need(t['exit_reason']==EXIT and len(fills)==1 and t['exit_index']==j+1 and t['exit_ts']==x['ts'],'FLOOR_NEXT_OPEN')
                    v.same(fills[0]['price'],t['exit_price'],'FLOOR_FILL_PRICE')
                    need(t['exit_trigger']['original_pullback_floor']==floor,'RAW_TRIGGER_ANCHOR')
                else:
                    need(not fills and t['pending_exit_signal_ts']==x['ts'],'PENDING_OUTSIDE_WINDOW')
            else:need(not fills and t.get('exit_reason')!=EXIT,'FILL_WITHOUT_INTENT')
    return count

def checks(pm,cm,v):
    def up(a,b):return a is not None and b is not None and a>b and not v.near(a,b)
    return {'WR_up':up(cm['base_cost']['win_rate'],pm['base_cost']['win_rate']),
            'terminal_net_up':up(cm['terminal_net_bps'],pm['terminal_net_bps']),
            'cost2_up':up(cm['terminal_cost2x_net_bps'],pm['terminal_cost2x_net_bps']),
            'daily_DD_down':up(pm['marked_DD_trade_sum_bps'],cm['marked_DD_trade_sum_bps'])}

def verify(root=HERE,pin=None):
    root=Path(root);repo=root.parents[2];v=checker(repo)
    if pin:need(sha(root/'FINAL_HASHES.json')==pin,'MANIFEST_DRIFT')
    for p,h in read(root/'FINAL_HASHES.json').items():need(sha(root/p)==h,'ARTIFACT_DRIFT:'+p)
    spec=read(root/'SPEC.json');budget=read(root/'BUDGET.json');old=read(repo/PRIOR/'BUDGET.json')
    need(sha(repo/PRIOR/'BUDGET.json')==spec['prior_budget_sha256'],'PRIOR_BUDGET')
    need(sha(repo/PARENT/'SPEC.json')==spec['parent_spec_sha256'],'PARENT_SPEC')
    for p,h in spec['source_files_sha256'].items():need(sha(repo/p)==h,'FROZEN_SOURCE:'+p)
    pro=deepcopy(budget);slot=pro.pop(KEY)
    need((slot['reserved'],slot['started'],slot['completed'],slot['failed'],slot['remaining'])==(2,2,2,0,0),'INCOMPLETE_SCOPE')
    need((pro['cumulative_actual'],pro['cumulative_actual_evaluations'])==(57,94),'COUNTS')
    need([x['actual_experiment_ordinal'] for x in pro['trials'][-2:]]==[93,94] and pro['candidate_trials'][-1]['ordinal']==57,'ORDINALS')
    pro['trials']=pro['trials'][:-2];pro['candidate_trials']=pro['candidate_trials'][:-1]
    pro['cumulative_actual']-=1;pro['cumulative_actual_evaluations']-=2;pro['new_candidate_runs']-=1
    need(pro==old,'OLD_HISTORY_CHANGED')
    patterns=re.findall(r"^\s+- '([^']+)'\s*$",(repo/'.github/workflows/kr3-c54-pullback-failure-v1.yml').read_text(),re.M)
    for p in set(spec['source_files_sha256'])|{C51+'/COSTS.json',C51+'/verify_saved.py',PRIOR+'/BUDGET.json'}:
        need(any(fnmatch.fnmatchcase(p,q) for q in patterns),'UNTRIGGERED_DEPENDENCY:'+p)
    costs=read(repo/C51/'COSTS.json');summary=read(root/'SUMMARY.json');binding=read(root/'SOURCE_BINDING.json')
    details={};rows=triggers=0;allchecks=[]
    for per in PERIODS:
        d=root/per;r=gz(d/'RESULT.json.gz');raw=gz(d/'RAW.json.gz');receipt=read(d/'RECEIPT.json');claim=read(d/'ATTEMPT.json');start=read(d/'EXECUTION_STARTED.json')
        need(receipt['status']=='COMPLETED' and sha(d/'RESULT.json.gz')==receipt['result_sha256'] and sha(d/'RAW.json.gz')==receipt['raw_sha256'],'EXECUTION_ARTIFACT')
        need(receipt['claim_commit']==start['claim_commit']==start['remote_readback_sha'] and claim['owner_run']==start['owner_run'],'REMOTE_CLAIM')
        need(spec['frozen_ns']<claim['time_ns']<start['time_ns'],'PRE_OUTCOME_ORDER')
        need(claim['spec_sha256']==receipt['spec_sha256']==sha(root/'SPEC.json'),'SPEC_IDENTITY')
        pp=repo/PARENT/'B'/per/'RESULT.json.gz';need(sha(pp)==spec['parent_results_sha256'][per],'PARENT_RESULT')
        parent=gz(pp);rows+=v.check_raw(raw,r,costs,spec['periods'][per]);v.check_metrics(r)
        triggers+=check_floor(raw,r,parent,v)
        need(binding[per]['input_packet_sha256']==spec['input_packet_sha256'][per] and binding[per]['projection_sha256']==digest(projection(raw)),'ORIGINAL_SOURCE_BINDING')
        a=read(d/'ACCOUNTING_C54.json');details[per]=v.compare_parent(parent,r,a)
        v.compare_parent(gz(repo/C51/per/'RESULT.json.gz'),r,read(d/'ACCOUNTING_C51.json'))
        cm=checks(parent['metrics'],r['metrics'],v);allchecks.append(cm)
        need(summary['periods'][per]['checks']==cm,'OBJECTIVE_CHECKS')
        for label,doc in [('parent',parent),('child',r)]:
            snap=summary['periods'][per][label];m=doc['metrics']
            v.subset(snap,{k:m['base_cost'][k] for k in ('win_rate','average_win_bps','average_loss_bps','realized_payoff','PF')},'SUMMARY_METRICS')
            v.subset(snap,{k:m[k] for k in ('terminal_net_bps','terminal_cost2x_net_bps','marked_DD_trade_sum_bps')},'SUMMARY_TOTALS')
    status='DEVELOPMENT_GOAL_MET' if all(all(c.values()) for c in allchecks) else 'PARTIAL_IMPROVEMENT' if all(c['terminal_net_up'] and c['cost2_up'] for c in allchecks) else 'REJECT_KEEP_C54'
    need(status==summary['status'],'FALSE_PASS')
    return dict(status=status,candidates=57,evaluations=94,raw_positions=rows,floor_intents=triggers,economic_replays=0,periods=details)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--manifest-sha256',required=True);x=p.parse_args();print(json.dumps(verify(pin=x.manifest_sha256),indent=2))
