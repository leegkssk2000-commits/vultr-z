"""Independent saved-record checks; no engine, market request or replay."""
import argparse,gzip,hashlib,importlib.util,json
from copy import deepcopy
from pathlib import Path
HERE=Path(__file__).resolve().parent
PARENT='research/development_evidence/KR3_PROFIT_ZONE_PRESERVATION_AFTER_PR1223_V1'
PRIOR='research/development_evidence/KR3_C51_ONCE_RECOVERY_AFTER_PR1224_V1/BUDGET.json'
KEY='c51_entry_context_ab_allocation'
MODES=('A','B','AB');PERIODS=('DEV2025','SEEN2026')
def read(p):return json.loads(Path(p).read_bytes())
def gz(p):return json.loads(gzip.decompress(Path(p).read_bytes()))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def require(ok,msg):
    if not ok:raise ValueError(msg)
def load_checker(repo):
    spec=importlib.util.spec_from_file_location('saved_c51_independent',repo/PARENT/'verify_saved.py')
    v=importlib.util.module_from_spec(spec);spec.loader.exec_module(v);return v

def check_context(result,mode):
    admitted=set()
    for event in result['events']:
        obs=event['entry_context'];i=event['signal_index'];t=event['signal_ts']
        require(obs['signal_index']==i and obs['available_at']==t,'FEATURE_CLOCK')
        if obs['trend_index'] is not None:
            require(obs['trend_index']<i-1 and obs['trend_available_at']<t,'PRE_PULLBACK_CLOCK')
        require(obs['atr_available_at'] is None or obs['atr_available_at']<t,'ATR_NOT_LAGGED')
        if obs['A']:
            require(obs['adx']>=25 and obs['adx']>obs['adx_previous'] and obs['plus_di']>obs['minus_di'],'A_NUMERIC_PREDICATE')
        b=obs['extension_atr'] is not None and 0<obs['extension_atr']<=1
        require(obs['B']==b,'B_NUMERIC_PREDICATE')
        allowed=obs['A'] if mode=='A' else obs['B'] if mode=='B' else obs['A'] and obs['B']
        if event['status']!='EXCLUDED':
            require(allowed,'DISALLOWED_ENTRY');admitted.add((event['symbol'],i,t))
        if str(event['exclusion_reason']).startswith('ENTRY_CONTEXT_'):
            require(not allowed and event['admission'] is False,'WRONG_VETO')
    positions={(t['symbol'],t['signal_index'],t['signal_ts']) for k in ('trades','open_observations') for t in result[k]}
    require(admitted==positions,'ADMISSION_POSITION_MISMATCH')
    return len(positions)

def verify(root=HERE,pin=None):
    root=Path(root);repo=root.parents[2];v=load_checker(repo)
    if pin:require(sha(root/'FINAL_HASHES.json')==pin,'MANIFEST_DRIFT')
    for p,digest in read(root/'FINAL_HASHES.json').items():require(sha(root/p)==digest,'ARTIFACT_DRIFT:'+p)
    spec=read(root/'SPEC.json');costs=read(repo/PARENT/'COSTS.json')
    for p,digest in spec['source_files_sha256'].items():require(sha(repo/p)==digest,'FROZEN_SOURCE_DRIFT:'+p)
    require(sha(repo/PRIOR)==spec['prior_budget_sha256'],'PRIOR_BUDGET_DRIFT')
    budget=read(root/'BUDGET.json');projection=deepcopy(budget);slot=projection.pop(KEY)
    require((slot['reserved'],slot['started'],slot['completed'],slot['failed'],slot['remaining'])==(6,6,6,0,0),'INCOMPLETE_SCOPE')
    require((projection['cumulative_actual'],projection['cumulative_actual_evaluations'])==(55,90),'FINAL_COUNTS')
    require([t['actual_experiment_ordinal'] for t in projection['trials'][-6:]]==list(range(85,91)),'EVALUATION_ORDINALS')
    require([t['ordinal'] for t in projection['candidate_trials'][-3:]]==[53,54,55],'CANDIDATE_ORDINALS')
    projection['trials']=projection['trials'][:-6];projection['candidate_trials']=projection['candidate_trials'][:-3]
    projection['cumulative_actual']-=3;projection['cumulative_actual_evaluations']-=6;projection['new_candidate_runs']-=3
    require(projection==read(repo/PRIOR),'OLD_HISTORY_MODIFIED')
    summary=read(root/'SUMMARY.json');answer={};rows=0
    for per in PERIODS:
        require(sha(repo/PARENT/per/'RESULT.json.gz')==spec['parent_results_sha256'][per],'C51_RESULT_DRIFT')
        parent=gz(repo/PARENT/per/'RESULT.json.gz');pidx=v.complete_index(parent)
        deltas={}
        for mode in MODES:
            d=root/mode/per;r=gz(d/'RESULT.json.gz');raw=gz(d/'RAW.json.gz');at=read(d/'ATTEMPT.json');start=read(d/'EXECUTION_STARTED.json');receipt=read(d/'RECEIPT.json')
            require(receipt['status']=='COMPLETED','RUN_NOT_COMPLETE')
            require(sha(d/'RESULT.json.gz')==receipt['result_sha256'] and sha(d/'RAW.json.gz')==receipt['raw_sha256'],'RAW_RECEIPT_DRIFT')
            require(receipt['spec_sha256']==at['spec_sha256']==sha(root/'SPEC.json'),'SPEC_IDENTITY')
            require(start['claim_commit']==start['remote_readback_sha']==receipt['claim_commit'],'REMOTE_RUNTIME_CLAIM')
            require(spec['frozen_ns']<at['time_ns']<start['time_ns'],'PRE_OUTCOME_ORDER')
            rows+=v.check_raw(raw,r,costs,spec['periods'][per]);v.check_metrics(r);check_context(r,mode)
            attribution=v.compare_parent(parent,r,read(d/'ACCOUNTING_C51.json'));cidx=v.complete_index(r)
            # Entry-only hypotheses must preserve complete economic rows for retained origins.
            for k in pidx.keys()&cidx.keys():
                require(pidx[k][0]==cidx[k][0],'COMMON_STATE_CHANGED')
                v.same(v.values(pidx[k]),v.values(cidx[k]),'COMMON_C51_ECONOMICS')
                for field in ('entry_price','entry_ts','hold_ms'):
                    v.same(pidx[k][1].get(field),cidx[k][1].get(field),'COMMON_PATH_'+field)
                for field in ('exit_price','exit_ts','exit_reason') if cidx[k][0]=='C' else ('mark_price','mark_ts'):
                    v.same(pidx[k][1].get(field),cidx[k][1].get(field),'COMMON_PATH_'+field)
            pm,cm=parent['metrics'],r['metrics']
            checks={'WR_up':cm['base_cost']['win_rate'] is not None and cm['base_cost']['win_rate']>pm['base_cost']['win_rate'],
                'terminal_net_up':cm['terminal_net_bps']>pm['terminal_net_bps'],
                'cost2_up':cm['terminal_cost2x_net_bps']>pm['terminal_cost2x_net_bps'],
                'daily_DD_down':cm['marked_DD_trade_sum_bps']<pm['marked_DD_trade_sum_bps']}
            v.same(summary['periods'][per][mode]['checks'],checks,'SUMMARY_CHECKS')
            v.same(summary['periods'][per][mode]['delta'],attribution['net_delta'],'SUMMARY_DELTA')
            v.subset(summary['periods'][per][mode]['snapshot'],{k:cm[k] for k in ('terminal_net_bps','terminal_cost2x_net_bps','marked_DD_trade_sum_bps')},'SUMMARY_TOTALS')
            deltas[mode]=attribution['net_delta'];answer[mode+'/'+per]={'checks':checks,**attribution}
        v.same(summary['periods'][per]['AB_net_interaction'],deltas['AB']-deltas['A']-deltas['B'],'INTERACTION')
    interpretation=read(root/'INTERPRETATION.json')
    require(interpretation['adjudication']=='B_PARTIAL_ECONOMIC_IMPROVEMENT_STRICT_JOINT_GOAL_NOT_ESTABLISHED','FALSE_STRICT_GOAL_CLAIM')
    pdd=summary['periods']['SEEN2026']['C51']['marked_DD_trade_sum_bps'];cdd=summary['periods']['SEEN2026']['B']['snapshot']['marked_DD_trade_sum_bps']
    require(v.near(pdd,cdd),'DD_EQUALITY_NOTE_STALE')
    return {'status':'SAVED_RAW_COST_METRICS_ATTRIBUTION_VERIFIED','candidate_total':55,'evaluation_total':90,'raw_rows':rows,'new_economic_replays':0,'results':answer}
if __name__=='__main__':
    q=argparse.ArgumentParser();q.add_argument('--manifest-sha256',required=True);args=q.parse_args()
    print(json.dumps(verify(pin=args.manifest_sha256),indent=2))
