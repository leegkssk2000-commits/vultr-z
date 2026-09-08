"""Independent saved raw->charged/cost/metric verification, no engine or replay.

The original runtime artifacts and pre-outcome spec are immutable. Market-path
correctness is not established by hashes alone; this checker binds every raw
geometry field to charged output and independently reconstructs common costs.
Daily DD is checked against the saved mark curve, not claimed as a new market
revaluation. No package install, data download, strategy import or execution.
"""
import argparse,gzip,hashlib,json,math
from copy import deepcopy
from pathlib import Path
HERE=Path(__file__).resolve().parent
PRIOR='research/benchmarks/D2_HLHB_CALENDAR_REPAIR_AFTER_PR1220_V1/BUDGET.json'
PARENT='research/development_evidence/FOCUSED_REPAIR_20260907_V1/KR3'
PERIODS=('DEV2025','SEEN2026')
KEY='kr3_whole_failure_allocation'
BAR=14_400_000
STEP=28_800_000

def canonical(x): return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
def sha(raw): return hashlib.sha256(raw).hexdigest()
def read(p): return json.loads(Path(p).read_bytes())
def gz(p): return json.loads(gzip.decompress(Path(p).read_bytes()))
def need(ok,msg):
    if not ok: raise ValueError(msg)
def near(x,y): return math.isfinite(float(x)) and math.isfinite(float(y)) and math.isclose(x,y,rel_tol=1e-11,abs_tol=1e-7)
def same(x,y,where):
    if isinstance(y,dict):
        need(isinstance(x,dict) and set(x)==set(y),'DICT_KEYS:'+where)
        for k,v in y.items(): same(x[k],v,where+'.'+str(k))
    elif isinstance(y,list):
        need(isinstance(x,list) and len(x)==len(y),'LIST_LENGTH:'+where)
        for i,v in enumerate(y): same(x[i],v,where+'.'+str(i))
    elif isinstance(y,(float,int)) and not isinstance(y,bool): need(near(x,y),'NUMBER:'+where)
    else: need(x==y,'VALUE:'+where)
def subset(x,y,where):
    for key,value in y.items():
        need(key in x,'MISSING_RAW_FIELD:'+where+'.'+key)
        same(x[key],value,where+'.'+key)
def identity(t): return (t['symbol'],t['signal_index'],t['signal_ts'],t.get('side','long'))
def index(rows):
    d={identity(t):t for t in rows};need(len(d)==len(rows),'DUPLICATE_ORIGIN');return d

def costs_for(binding,entry,end):
    count=max(0,end//STEP-entry//STEP)
    parts={k:binding[k] for k in ('fee_bps','spread_bps','impact_bps')}
    parts['slippage_bps']=0.0;parts['funding_bps']=count*binding['funding_p95_per_settlement_bps']
    total=sum(parts.values());parts['frozen_floor_reserve_bps']=max(0.,20.-total)
    return parts,sum(parts.values()),count

def check_raw(raw,result,costs,calendar):
    start,end=calendar['start_ms'],calendar['runoff_end_ms']
    expected={k:[] for k in ('trades','open_observations','events','trace')}
    refs={}
    for symbol,v in sorted(raw.items()):
        need(symbol in costs,'MISSING_SYMBOL_COST')
        for source,target in [('trades','trades'),('open_positions','open_observations'),('events','events'),('trace','trace')]:
            expected[target].extend(dict(t,symbol=symbol) for t in v[source])
        refs[symbol]=v['reference_checkpoint']
    same(result['reference_states'],refs,'RAW_REFERENCE')
    for key in ('events','trace'):
        need(len(expected[key])==len(result[key]),'RAW_EVENT_TRACE_COUNT')
        for i,(rawrow,row) in enumerate(zip(expected[key],result[key])):subset(row,rawrow,key+str(i))
    for kind in ('trades','open_observations'):
        src,dst=index(expected[kind]),index(result[kind]);need(src.keys()==dst.keys(),'RAW_RESULT_ORIGINS')
        for key,r in src.items():
            t=dst[key];subset(t,r,'RAW_GEOMETRY')
            is_closed=kind=='trades';exit_ts=t['exit_ts'] if is_closed else t['mark_ts']
            price=t['exit_price'] if is_closed else t['mark_price']
            need(start<=t['entry_ts']<end and t['entry_ts']<=exit_ts<=end,'INVALID_CALENDAR')
            need(t['entry_index']==t['signal_index']+1 and t['entry_ts']==t['signal_ts'],'ENTRY_WAS_CHANGED')
            need(t['side']=='long' and t['entry_price']>0 and price>0,'INVALID_PRICE_OR_SIDE')
            gross=(price/t['entry_price']-1)*10000
            same(t['gross_bps' if is_closed else 'gross_mark_bps'],gross,'GROSS_FROM_PRICES')
            same(t['hold_ms'],exit_ts-t['entry_ts'],'HOLD_TIME')
            parts,total,count=costs_for(costs[t['symbol']],t['entry_ts'],exit_ts)
            if is_closed:
                subset(t,parts,'INDEPENDENT_COST')
                same(t['cost_bps'],total,'COST_TOTAL');same(t['funding_settlements_crossed'],count,'FUNDING_COUNT')
                same(t['net_bps'],gross-total,'NET_FROM_RAW');same(t['cost2x_net_bps'],gross-2*total,'COST2_FROM_RAW')
                need(t['status']=='COMPLETED','CLOSED_STATUS')
            else:
                need(t['status']=='CENSORED' and not t['actual_exit'] and not t['terminal_liquidation'],'OPEN_IS_NOT_FILL')
                need(exit_ts==end,'OPEN_TERMINAL_CLOCK')
                same(t['hypothetical_cost_components_bps'],parts,'OPEN_COST_PARTS')
                same(t['funding_settlements_elapsed'],count,'OPEN_FUNDING_COUNT')
                same(t['hypothetical_liquidation_cost_bps'],total,'OPEN_COST')
                same(t['hypothetical_liquidation_net_mark_bps'],gross-total,'OPEN_NET')
                same(t['hypothetical_liquidation_cost2x_net_mark_bps'],gross-2*total,'OPEN_COST2')
            need(t['formal_credit']==0 and t['independent'] is False and t['exchange_order_submitted'] is False,'CREDIT_OR_ORDER_DRIFT')
    return len(expected['trades'])+len(expected['open_observations'])

def check_metrics(result):
    ts,opens,m=result['trades'],result['open_observations'],result['metrics']
    win=[t['net_bps'] for t in ts if t['net_bps']>0];loss=[t['net_bps'] for t in ts if t['net_bps']<0]
    need((m['closed_T'],m['open_T'])==(len(ts),len(opens)),'TRADE_COUNTS')
    bc={'completed_T':len(ts),'wins':len(win),'losses':len(loss),'flat':len(ts)-len(win)-len(loss),
        'win_rate':len(win)/len(ts),'net_bps':sum(t['net_bps'] for t in ts),
        'gross_bps':sum(t['gross_bps'] for t in ts),'average_win_bps':sum(win)/len(win),
        'average_loss_bps':sum(loss)/len(loss),'PF':sum(win)/-sum(loss),
        'realized_payoff':(sum(win)/len(win))/(-sum(loss)/len(loss))}
    subset(m['base_cost'],bc,'METRICS')
    net=bc['net_bps']+sum(t['hypothetical_liquidation_net_mark_bps'] for t in opens)
    net2=sum(t['cost2x_net_bps'] for t in ts)+sum(t['hypothetical_liquidation_cost2x_net_mark_bps'] for t in opens)
    same(m['terminal_net_bps'],net,'TERMINAL_NET');same(m['terminal_cost2x_net_bps'],net2,'TERMINAL_COST2')
    same(m['open_hypothetical_net_mark_bps'],net-bc['net_bps'],'OPEN_MARK_TOTAL')
    peak=dd=previous=0.
    for row in m['daily']:
        value=row['cumulative_net_mark_bps'];same(row['value'],value-previous,'DAILY_DELTA')
        peak=max(peak,value);dd=max(dd,peak-value);previous=value
    same(previous,net,'DAILY_TERMINAL');same(m['daily'][-1]['cumulative_cost2x_mark_bps'],net2,'DAILY_COST2')
    same(m['marked_DD_trade_sum_bps'],dd,'DAILY_DD')
    return net

def compare_parent(parent,result,accounting):
    same(parent['reference_states'],result['reference_states'],'PARENT_REFERENCE')
    need(index(parent['events']).keys()==index(result['events']).keys(),'PARENT_SIGNAL_POOL')
    p,c=index(parent['trades']),index(result['trades'])
    need(p.keys()==c.keys(),'COMMON_ORIGINS_CHANGED')
    op,oc=index(parent['open_observations']),index(result['open_observations']);need(op.keys()==oc.keys(),'OPEN_ORIGINS_CHANGED')
    for k,t in p.items():
        for field in ('entry_ts','entry_index','entry_price','signal_index','signal_ts','side'):same(c[k][field],t[field],'PARENT_ENTRY')
    for k,t in op.items():
        for field in ('entry_ts','entry_index','entry_price','mark_ts','mark_price','hypothetical_liquidation_net_mark_bps'):
            same(oc[k][field],t[field],'PARENT_OPEN')
    parts=dict(saved_common_loss_bps=0.,worsened_common_loss_bps=0.,cut_positive_winner_profit_bps=0.,
        additional_loss_on_parent_winners_bps=0.,increased_common_winner_bps=0.,winner_to_loss_T=0)
    for k,t in p.items():
        pn,cn=t['net_bps'],c[k]['net_bps'];delta=cn-pn
        if pn<0:
            if delta>=0:parts['saved_common_loss_bps']+=delta
            else:parts['worsened_common_loss_bps']-=delta
        elif pn>0:
            parts['cut_positive_winner_profit_bps']+=max(0,pn-max(cn,0))
            parts['increased_common_winner_bps']+=max(0,cn-pn)
            if cn<0:parts['additional_loss_on_parent_winners_bps']-=cn;parts['winner_to_loss_T']+=1
    subset(accounting['resolved_common_effects'],parts,'GAIN_HARM_ACCOUNTING')
    delta=sum(c[k]['net_bps']-t['net_bps'] for k,t in p.items())
    same(accounting['resolved_common_effects']['net_delta_bps'],delta,'PARENT_NET_DELTA')
    need(accounting['four_way_terminal_delta']['new']==accounting['four_way_terminal_delta']['removed']==accounting['four_way_terminal_delta']['closed_open_transitions']==0,'FOURWAY_NOT_ZERO')
    return dict(net_delta=delta,**parts)

def verify(root=HERE,pin=None):
    root=Path(root);repo=root.parents[2];manifest_raw=(root/'FINAL_HASHES.json').read_bytes()
    if pin:need(sha(manifest_raw)==pin,'MANIFEST_DRIFT')
    for name,digest in json.loads(manifest_raw).items():need(sha((root/name).read_bytes())==digest,'FILE_DRIFT:'+name)
    spec=read(root/'SPEC.json');costs=read(root/'COSTS.json')
    need(sha(canonical(costs))==spec['cost_hash'],'FROZEN_COST_DRIFT')
    for name,digest in spec['source_files_sha256'].items():need(sha((repo/name).read_bytes())==digest,'CODE_DRIFT:'+name)
    need(sha((repo/PRIOR).read_bytes())==spec['prior_budget_sha256'],'PRIOR_BUDGET_DRIFT')
    budget=read(root/'BUDGET.json');projection=deepcopy(budget);allocation=projection.pop(KEY)
    need((allocation['used'],allocation['completed'],allocation['failed'])==(2,2,0),'INCOMPLETE_ALLOCATION')
    need((projection['cumulative_actual'],projection['cumulative_actual_evaluations'])==(50,80),'FINAL_COUNTS')
    need([x['actual_experiment_ordinal'] for x in projection['trials'][-2:]]==[79,80],'TRIAL_ORDINALS')
    need(projection['candidate_trials'][-1]['ordinal']==50,'CANDIDATE_ORDINAL')
    projection['trials']=projection['trials'][:-2];projection['candidate_trials']=projection['candidate_trials'][:-1]
    projection['cumulative_actual']-=1;projection['cumulative_actual_evaluations']-=2;projection['new_candidate_runs']-=1
    need(projection==read(repo/PRIOR),'OLD_HISTORY_CHANGED')
    answer={}
    for period in PERIODS:
        folder=root/period;receipt=read(folder/'RECEIPT.json');attempt=read(folder/'ATTEMPT.json');started=read(folder/'EXECUTION_STARTED.json')
        need(receipt['status']=='COMPLETED','RUN_NOT_COMPLETE')
        need(started['claim_commit']==started['remote_readback_sha']==receipt['claim_commit'],'RUNTIME_CLAIM')
        need(attempt['time_ns']<started['time_ns']<receipt['finished_ns'],'ATTEMPT_TIME_ORDER')
        need(receipt['spec_sha256']==attempt['spec_sha256']==sha((root/'SPEC.json').read_bytes()),'SPEC_RECEIPT')
        need(sha((folder/'RAW.json.gz').read_bytes())==receipt['raw_sha256'] and sha((folder/'RESULT.json.gz').read_bytes())==receipt['result_sha256'],'RAW_RESULT_RECEIPT')
        pp=repo/PARENT/(period+'.json.gz');need(sha(pp.read_bytes())==spec['baseline_sha256'][period],'PARENT_BYTES_CHANGED')
        raw,result,parent=gz(folder/'RAW.json.gz'),gz(folder/'RESULT.json.gz'),gz(pp)['views']['FULL']
        count=check_raw(raw,result,costs,spec['periods'][period]);net=check_metrics(result)
        comparison=compare_parent(parent,result,read(folder/'ACCOUNTING.json'))
        answer[period]={'raw_bound_rows':count,'net':net,**comparison}
    return {'status':'SAVED_RAW_AND_COSTS_VERIFIED; ECONOMIC_REJECT','candidate_total':50,'evaluation_total':80,
            'new_replays':0,'results':answer}
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--manifest-sha256',required=True);x=p.parse_args()
    print(json.dumps(verify(pin=x.manifest_sha256),indent=2))
