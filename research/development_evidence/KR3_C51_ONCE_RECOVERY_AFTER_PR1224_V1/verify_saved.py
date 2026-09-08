"""Immutable byte + independent raw/cost/metric/bridge checks. Never replay."""
import argparse,gzip,hashlib,importlib.util,json
from copy import deepcopy
from pathlib import Path
HERE=Path(__file__).resolve().parent
OLD=HERE.parent/'KR3_PROFIT_ZONE_PRESERVATION_AFTER_PR1223_V1'
ROOT=HERE.parents[2]
spec=importlib.util.spec_from_file_location('c51_saved_verifier',OLD/'verify_saved.py')
v=importlib.util.module_from_spec(spec);spec.loader.exec_module(v)
read,gz,need,same,near=v.read,v.gz,v.need,v.same,v.near
KEY='kr3_c51_once_recovery_allocation'
def h(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def check_recovery(raw,costs):
    counts={'deferred':0,'recovered':0,'confirmed':0,'preempted_or_open':0}
    for symbol,one in raw.items():
        for t in one['trades']+one['open_positions']:
            state=t.get('profit_zone_state',{});events=state.get('recovery_events',[])
            if not events:
                need(not state.get('recovery_used',False),'USED_WITHOUT_DEFER');continue
            need(state.get('recovery_used') is True and 1<=len(events)<=2,'ONCE_ONLY_STATE')
            first=events[0]
            need(first['kind']=='DEFER_FIRST_NONPOSITIVE_BREACH','FIRST_EVENT')
            need(first['index']>state['armed_index'] and first['close']<first['prior_line'],'DEFER_AFTER_ARM_BELOW_LINE')
            for event in events:
                parts,cost,n=v.costs_for(costs[symbol],t['entry_ts'],event['ts'])
                same(event['decision_cost']['cost_bps'],cost,'RECOVERY_CURRENT_COST')
                need(event['decision_cost']['model_accrual_cutoff_ts']==event['ts'],'RECOVERY_COST_CLOCK')
                mark=(event['close']/t['entry_price']-1.)*10000.-cost
                same(event['completed_close_net_mark_bps'],mark,'RECOVERY_MARK_FROM_PRICE')
            need(first['completed_close_net_mark_bps']<=0.,'DEFER_POSITIVE_MARK')
            counts['deferred']+=1
            if len(events)==2:
                second=events[1]
                need(second['index']==first['index']+1 and second['ts']==first['ts']+14400000,'ONE_CLOSE_ONLY')
                same(second['prior_line'],first['prior_line'],'NO_LOWERED_PENDING_LINE')
                need(state['recovery_pending_index'] is None,'RESOLVED_PENDING_REMAINS')
                if second['kind']=='RECOVERED_GRACE_CONSUMED':
                    need(second['close']>=second['prior_line'],'FAKE_RECOVERY');counts['recovered']+=1
                elif second['kind']=='CONFIRM_AFTER_ONE_CLOSE':
                    need(second['close']<second['prior_line'],'FALSE_CONFIRMATION');counts['confirmed']+=1
                else:raise ValueError('UNRECOGNIZED_RECOVERY_EVENT')
            else:
                need(state['recovery_pending_index']==first['index'],'LOST_PENDING_STATE')
                need(t.get('exit_reason')!='KR3_PROFIT_ZONE_SUPPORT_LOST_NEXT_OPEN','UNCONFIRMED_NEW_EXIT')
                counts['preempted_or_open']+=1
    return counts

def math_period(per,root=HERE):
    root=Path(root);s=read(root/'SPEC.json');raw=gz(root/per/'RAW.json.gz');r=gz(root/per/'RESULT.json.gz')
    old=root.parent/OLD.name;parent=gz(old/per/'RESULT.json.gz');costs=read(old/'COSTS.json')
    count=v.check_raw(raw,r,costs,s['periods'][per]);v.check_metrics(r)
    recovery=check_recovery(raw,costs)
    bridge=v.compare_parent(parent,r,read(root/per/'ACCOUNTING_C51.json'))
    summary=read(root/'SUMMARY.json')['periods'][per];cs=summary['snapshots']['C52'];ps=summary['snapshots']['C51']
    cm,pm=r['metrics'],parent['metrics']
    checks={'WR_up':cm['base_cost']['win_rate']>pm['base_cost']['win_rate'],
        'terminal_net_up':cm['terminal_net_bps']>pm['terminal_net_bps'],
        'cost2_up':cm['terminal_cost2x_net_bps']>pm['terminal_cost2x_net_bps'],
        'daily_DD_down':cm['marked_DD_trade_sum_bps']<pm['marked_DD_trade_sum_bps']}
    same(summary['checks_vs_C51'],checks,'ACTUAL_EIGHT_CHECKS')
    for snap,actual in [(ps,pm),(cs,cm)]:
        for key in ('terminal_net_bps','terminal_cost2x_net_bps','marked_DD_trade_sum_bps'):same(snap[key],actual[key],'SUMMARY_TOTAL')
        for key in ('win_rate','average_win_bps','average_loss_bps','realized_payoff','PF'):same(snap[key],actual['base_cost'][key],'SUMMARY_BASE')
    same(summary['delta_net'],bridge['net_delta'],'SUMMARY_NET_DELTA')
    receipt=read(root/per/'RECEIPT.json')
    same(receipt['result_sha256'],h(root/per/'RESULT.json.gz'),'RESULT_RECEIPT')
    same(receipt['raw_sha256'],h(root/per/'RAW.json.gz'),'RAW_RECEIPT')
    return dict(rows=count,checks=checks,recovery=recovery,bridge=bridge)

def verify(pin):
    need(h(HERE/'FINAL_HASHES.json')==pin,'FINAL_MANIFEST_PIN')
    for file,digest in read(HERE/'FINAL_HASHES.json').items():need(h(HERE/file)==digest,'EVIDENCE_DRIFT:'+file)
    s=read(HERE/'SPEC.json')
    for file,digest in s['source_files_sha256'].items():need(h(ROOT/file)==digest,'FROZEN_SOURCE_DRIFT:'+file)
    need(h(OLD/'BUDGET.json')==s['prior_budget_sha256'],'PARENT_BUDGET_DRIFT')
    budget=read(HERE/'BUDGET.json');slot=budget[KEY]
    need((budget['cumulative_actual'],budget['cumulative_actual_evaluations'],slot['used'],slot['completed'],slot['failed'])==(52,84,2,2,0),'SCOPE_COUNTS')
    projection=deepcopy(budget);projection.pop(KEY)
    need([t['actual_experiment_ordinal'] for t in projection['trials'][-2:]]==[83,84],'NEW_ORDINALS')
    projection['trials']=projection['trials'][:-2];projection['candidate_trials']=projection['candidate_trials'][:-1]
    projection['cumulative_actual']-=1;projection['cumulative_actual_evaluations']-=2;projection['new_candidate_runs']-=1
    same(projection,read(OLD/'BUDGET.json'),'PRIOR_HISTORY_CHANGED')
    out={}
    for per in ('DEV2025','SEEN2026'):
        need(h(OLD/per/'RESULT.json.gz')==s['parent_results_sha256'][per],'PARENT_RESULT_DRIFT')
        receipt=read(HERE/per/'RECEIPT.json');started=read(HERE/per/'EXECUTION_STARTED.json');attempt=read(HERE/per/'ATTEMPT.json')
        need(receipt['status']=='COMPLETED' and receipt['spec_sha256']==attempt['spec_sha256']==h(HERE/'SPEC.json'),'RECEIPT_SPEC')
        need(started['claim_commit']==started['remote_readback_sha']==receipt['claim_commit'],'REMOTE_CLAIM_NOT_CONFIRMED')
        out[per]=math_period(per)
    all8=all(all(x['checks'].values()) for x in out.values())
    need((read(HERE/'SUMMARY.json')['status']=='DEVELOPMENT_GOAL_MET')==all8,'FALSE_GOAL_STATUS')
    return dict(status='STORED_COMPARISON_VERIFIED_NO_REPLAY',periods=out,candidates=52,evaluations=84,market_replays=0)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--manifest-sha256',required=True);x=p.parse_args()
    print(json.dumps(verify(x.manifest_sha256),indent=2))
