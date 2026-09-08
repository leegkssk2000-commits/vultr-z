"""Independent saved raw->charged/cost/metric verification, no engine or replay.

The original runtime artifacts and pre-outcome spec are immutable. Market-path
correctness is not established by hashes alone; this checker binds every raw
geometry field to charged output and independently reconstructs common costs.
Daily DD is checked against the saved mark curve, not claimed as a new market
revaluation. No package install, data download, strategy import or execution.
"""
import argparse,gzip,hashlib,json,math
from collections import Counter,defaultdict
from copy import deepcopy
from pathlib import Path
HERE=Path(__file__).resolve().parent
PRIOR='research/development_evidence/KR3_WHOLE_FAILURE_AFTER_PR1221_V1/BUDGET.json'
PARENT='research/development_evidence/FOCUSED_REPAIR_20260907_V1/KR3'
PERIODS=('DEV2025','SEEN2026')
KEY='kr3_profit_zone_allocation'
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

def check_guard_trace(raw,binding):
    positions={t['signal_index']:t for key in ('trades','open_positions') for t in raw[key]}
    state={};arms=exits=0
    for row in raw['trace']:
        kind=row['kind'];origin=row['signal_index']
        if kind=='KR3_PROFIT_ZONE_ARMED_CLOSE':
            need(origin not in state and origin in positions,'GUARD_DUPLICATE_ARM')
            t=positions[origin];cost=row['decision_cost'];parts,total,count=costs_for(binding,t['entry_ts'],row['ts'])
            subset(cost,parts,'ARM_CAUSAL_COST');same(cost['cost_bps'],total,'ARM_COST_TOTAL')
            same(cost['funding_settlements_crossed'],count,'ARM_ELAPSED_FUNDING')
            need(cost['model_accrual_cutoff_ts']==row['ts'] and cost['actual_historical_execution_cost_evidence'] is False,'ARM_COST_EVIDENCE')
            same(row['entry_price'],t['entry_price'],'ARM_ENTRY')
            need(row['observed_close']>row['ema20']>row['ema50'] and row['ema20']>t['entry_price']*(1+total/10000),'ARM_RULE')
            same(row['protected_line'],row['ema20'],'ARM_LINE')
            state[origin]={'index':row['index'],'line':row['ema20'],'last':row['index'],'triggered':False};arms+=1
        elif kind=='KR3_PROFIT_ZONE_LINE_UPDATED_CLOSE':
            need(origin in state,'UPDATE_WITHOUT_ARM');s=state[origin]
            need(row['index']>s['last'] and not s['triggered'],'UPDATE_CLOCK')
            same(row['prior_protected_line'],s['line'],'UPDATE_PRIOR_LINE')
            same(row['protected_line'],max(s['line'],row['ema20']),'UPDATE_RUNNING_MAX')
            s.update(line=row['protected_line'],last=row['index'])
        elif kind=='KR3_PROFIT_ZONE_SUPPORT_LOST_CLOSE':
            need(origin in state,'TRIGGER_WITHOUT_ARM');s=state[origin]
            need(row['index']>s['last'] and row['index']>s['index'] and not s['triggered'],'TRIGGER_CLOCK')
            same(row['prior_protected_line'],s['line'],'TRIGGER_PRIOR_LINE')
            need(row['observed_close']<s['line'],'TRIGGER_STRICT_BELOW')
            s.update(triggered=True,trigger_index=row['index'],trigger_ts=row['ts'])
        elif kind=='KR3_PROFIT_ZONE_SUPPORT_LOST_NEXT_OPEN':
            need(origin in state and state[origin]['triggered'],'EXIT_WITHOUT_TRIGGER');s=state[origin]
            need(row['index']==s['trigger_index']+1 and row['ts']==s['trigger_ts'],'GUARD_NEXT_OPEN_CLOCK')
            same(positions[origin]['exit_price'],row['price'],'GUARD_ACTUAL_NEXT_OPEN_PRICE');exits+=1
    return {'arms':arms,'exits':exits}

def check_raw(raw,result,costs,calendar):
    start,end=calendar['start_ms'],calendar['runoff_end_ms']
    expected={k:[] for k in ('trades','open_observations','events','trace')}
    refs={}
    for symbol,v in sorted(raw.items()):
        need(symbol in costs,'MISSING_SYMBOL_COST')
        check_guard_trace(v,costs[symbol])
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
        'win_rate':len(win)/len(ts) if ts else None,'net_bps':sum(t['net_bps'] for t in ts),
        'gross_bps':sum(t['gross_bps'] for t in ts),'average_win_bps':sum(win)/len(win) if win else None,
        'average_loss_bps':sum(loss)/len(loss) if loss else None,'PF':sum(win)/-sum(loss) if loss else None,
        'realized_payoff':(sum(win)/len(win))/(-sum(loss)/len(loss)) if win and loss else None}
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
    grouped=defaultdict(float)
    for t in ts:grouped[t['exit_ts']]+=t['net_bps']
    longest=length=0;worst=loss_sum=0.
    for _,amount in sorted(grouped.items()):
        if amount<0:length+=1;loss_sum-=amount;longest=max(longest,length);worst=max(worst,loss_sum)
        else:length=0;loss_sum=0.
    subset(m['closed_loss_groups'],{'max_length_groups':longest,'max_loss_trade_sum_bps':worst},'GROUPED_LOSS_STREAK')
    changes=defaultdict(Counter);position_ms=0;maximum_hold=0
    for key,endkey in [('trades','exit_ts'),('open_observations','mark_ts')]:
        for t in result[key]:
            duration=t[endkey]-t['entry_ts'];position_ms+=duration;maximum_hold=max(maximum_hold,duration)
            if duration:changes[t['entry_ts']][t['symbol']]+=1;changes[t[endkey]][t['symbol']]-=1
    active=Counter();max_positions=max_symbols=symbol_ms=any_ms=0;previous_ts=None
    for ts,change in sorted(changes.items()):
        if previous_ts is not None:
            symbol_ms+=(ts-previous_ts)*len(active)
            if active:any_ms+=ts-previous_ts
        active.update(change);need(all(n>=0 for n in active.values()),'NEGATIVE_EXPOSURE')
        active=Counter({symbol:n for symbol,n in active.items() if n})
        max_positions=max(max_positions,sum(active.values()));max_symbols=max(max_symbols,len(active));previous_ts=ts
    need(not active,'EXPOSURE_NOT_CLOSED')
    subset(m['exposure'],{'position_days':position_ms/86400000,'symbol_days_union':symbol_ms/86400000,
        'calendar_days_with_any_exposure':any_ms/86400000,'maximum_holding_days_including_open':maximum_hold/86400000,
        'max_simultaneous_positions':max_positions,'max_simultaneous_symbols':max_symbols},'RAW_EXPOSURE')
    return net

def complete_index(result):
    rows={}
    for kind,key in [('C','trades'),('O','open_observations')]:
        for row in result[key]:
            k=identity(row);need(k not in rows,'DUPLICATE_CLOSED_OPEN_ORIGIN');rows[k]=(kind,row)
    return rows


def values(item,closed_only=False):
    names=('gross_bps','net_bps','cost2x_net_bps','cost_bps','fee_bps','spread_bps','impact_bps','slippage_bps','funding_bps','frozen_floor_reserve_bps')
    if item is None or (closed_only and item[0]=='O'):return dict.fromkeys(names,0.)
    status,t=item
    if status=='C':return {k:t[k] for k in names}
    return {'gross_bps':t['gross_mark_bps'],'net_bps':t['hypothetical_liquidation_net_mark_bps'],
        'cost2x_net_bps':t['hypothetical_liquidation_cost2x_net_mark_bps'],'cost_bps':t['hypothetical_liquidation_cost_bps'],
        **{k:t['hypothetical_cost_components_bps'][k] for k in names[4:]}}


def compare_parent(parent,result,accounting):
    # Exit changes can release occupancy; never equate unchanged entry rule to
    # identical FULL admission sets. Every one of the eight origin groups binds.
    same(parent['reference_states'],result['reference_states'],'PARENT_REFERENCE')
    need(index(parent['events']).keys()==index(result['events']).keys(),'PARENT_SIGNAL_POOL')
    p,c=complete_index(parent),complete_index(result)
    groups={k:[] for k in ('CC','CO','OC','OO','removed_C','removed_O','new_C','new_O')}
    for k in p.keys()|c.keys():
        group=p[k][0]+c[k][0] if k in p and k in c else 'removed_'+p[k][0] if k in p else 'new_'+c[k][0]
        groups[group].append(k)
        if k in p and k in c:
            for field in ('entry_ts','entry_index','entry_price','signal_index','signal_ts','side'):
                same(c[k][1][field],p[k][1][field],'COMMON_ENTRY_RULE')
    names=tuple(values(None));deltas={}
    for group,keys in groups.items():
        saved=accounting['groups'][group];same(saved['T'],len(keys),'GROUP_COUNT:'+group)
        same(accounting['counts'][group],len(keys),'GROUP_COUNTS:'+group)
        for basis,closed in [('marked',False),('closed',True)]:
            pv={field:sum(values(p.get(k),closed)[field] for k in keys) for field in names}
            cv={field:sum(values(c.get(k),closed)[field] for k in keys) for field in names}
            delta={field:cv[field]-pv[field] for field in names}
            same(saved[basis],{'parent':pv,'child':cv,'delta':delta},'GROUP_VALUES:'+group+':'+basis)
            if basis=='marked':deltas[group]=delta['net_bps']
    four={'common_CC_OO':deltas['CC']+deltas['OO'],'removed':deltas['removed_C']+deltas['removed_O'],
        'new':deltas['new_C']+deltas['new_O'],'closed_open_transitions':deltas['CO']+deltas['OC']}
    subset(accounting['four_way_terminal_delta'],four,'FOUR_WAY')
    total=sum(values(x)['net_bps'] for x in c.values())-sum(values(x)['net_bps'] for x in p.values())
    same(sum(four.values()),total,'TOTAL_NET_BRIDGE');same(accounting['marked_delta_bps_not_realized'],total,'SAVED_NET_BRIDGE')
    parts=dict(saved_common_loss_bps=0.,worsened_common_loss_bps=0.,cut_positive_winner_profit_bps=0.,
        additional_loss_on_parent_winners_bps=0.,increased_common_winner_bps=0.,winner_to_loss_T=0)
    flat_delta=0.;loss_to_win=0
    for k in groups['CC']:
        pn,cn=p[k][1]['net_bps'],c[k][1]['net_bps'];delta=cn-pn
        if pn<0:
            if delta>=0:parts['saved_common_loss_bps']+=delta
            else:parts['worsened_common_loss_bps']-=delta
            loss_to_win+=cn>0
        elif pn>0:
            parts['cut_positive_winner_profit_bps']+=max(0,pn-max(cn,0))
            parts['increased_common_winner_bps']+=max(0,cn-pn)
            if cn<0:parts['additional_loss_on_parent_winners_bps']-=cn;parts['winner_to_loss_T']+=1
        else:flat_delta+=cn
    subset(accounting['resolved_common_effects'],parts,'GAIN_HARM_ACCOUNTING')
    same(accounting['resolved_common_effects']['net_delta_bps'],deltas['CC'],'COMMON_GAIN_HARM_TOTAL')
    common_signed=parts['saved_common_loss_bps']-parts['worsened_common_loss_bps']-parts['cut_positive_winner_profit_bps']-parts['additional_loss_on_parent_winners_bps']+parts['increased_common_winner_bps']+flat_delta
    same(common_signed,deltas['CC'],'SIGNED_GAIN_HARM')
    signs={}
    def sign(item):
        if item is None:return 'ABSENT'
        if item[0]=='O':return 'OPEN'
        return 'WIN' if item[1]['net_bps']>0 else 'LOSS' if item[1]['net_bps']<0 else 'FLAT'
    for k in p.keys()|c.keys():
        key=sign(p.get(k))+'->'+sign(c.get(k));signs[key]=signs.get(key,0)+1
    same(accounting['sign_transitions'],signs,'SIGN_TRANSITIONS')
    return {'net_delta':total,'four_way':four,'counts':{k:len(v) for k,v in groups.items()},
        'loss_to_win_T':loss_to_win,'flat_parent_signed_delta':flat_delta,**parts}


def check_summary(parent,result,summary):
    pm=parent['metrics'];cm=result['metrics'];pb=pm['base_cost'];cb=cm['base_cost']
    checks={'WR_up':cb['win_rate']>pb['win_rate'],'terminal_net_up':cm['terminal_net_bps']>pm['terminal_net_bps'],
        'cost2_up':cm['terminal_cost2x_net_bps']>pm['terminal_cost2x_net_bps'],
        'daily_DD_down':cm['marked_DD_trade_sum_bps']<pm['marked_DD_trade_sum_bps']}
    same(summary['checks'],checks,'JOINT_OBJECTIVE')
    for label,m in [('parent',pm),('child',cm)]:
        base=m['base_cost'];saved=summary[label]
        subset(saved,{k:base[k] for k in ('win_rate','average_win_bps','average_loss_bps','realized_payoff','PF')},'SUMMARY_BASE')
        subset(saved,{'terminal_net_bps':m['terminal_net_bps'],'terminal_cost2x_net_bps':m['terminal_cost2x_net_bps'],
            'marked_DD_trade_sum_bps':m['marked_DD_trade_sum_bps']},'SUMMARY_TOTALS')
    same(summary['net_delta'],cm['terminal_net_bps']-pm['terminal_net_bps'],'SUMMARY_DELTA')
    same(summary['cost2_delta'],cm['terminal_cost2x_net_bps']-pm['terminal_cost2x_net_bps'],'SUMMARY_COST2_DELTA')
    same(summary['DD_delta'],cm['marked_DD_trade_sum_bps']-pm['marked_DD_trade_sum_bps'],'SUMMARY_DD_DELTA')
    return checks


def normalize_parent(document):
    result=deepcopy(document['views']['FULL']);stage=document['stages']['FULL'];m=stage['metrics']
    result['metrics']={'base_cost':m['base_cost'],'terminal_net_bps':m['terminal_totals_bps']['net_bps'],
        'terminal_cost2x_net_bps':m['terminal_totals_bps']['cost2x_net_bps'],
        'marked_DD_trade_sum_bps':stage['marked_diagnostics']['marked_DD_trade_sum_bps']}
    return result


def verify(root=HERE,pin=None):
    root=Path(root);repo=root.parents[2];manifest_raw=(root/'FINAL_HASHES.json').read_bytes()
    if pin:need(sha(manifest_raw)==pin,'MANIFEST_DRIFT')
    for name,digest in json.loads(manifest_raw).items():need(sha((root/name).read_bytes())==digest,'FILE_DRIFT:'+name)
    spec=read(root/'SPEC.json');costs=read(root/'COSTS.json')
    need(sha(canonical(costs))==spec['cost_hash'],'FROZEN_COST_DRIFT')
    for name,digest in spec['source_files_sha256'].items():need(sha((repo/name).read_bytes())==digest,'CODE_DRIFT:'+name)
    for period,paths in spec['saved_comparator_paths'].items():
        for name,path in paths.items():
            need(sha((repo/path).read_bytes())==spec['saved_comparator_sha256'][period][name],'COMPARATOR_DRIFT:'+period+':'+name)
    need(sha((repo/PRIOR).read_bytes())==spec['prior_budget_sha256'],'PRIOR_BUDGET_DRIFT')
    budget=read(root/'BUDGET.json');projection=deepcopy(budget);allocation=projection.pop(KEY)
    need((allocation['used'],allocation['completed'],allocation['failed'])==(2,2,0),'INCOMPLETE_ALLOCATION')
    need((projection['cumulative_actual'],projection['cumulative_actual_evaluations'])==(51,82),'FINAL_COUNTS')
    need([x['actual_experiment_ordinal'] for x in projection['trials'][-2:]]==[81,82],'TRIAL_ORDINALS')
    need(projection['candidate_trials'][-1]['ordinal']==51,'CANDIDATE_ORDINAL')
    projection['trials']=projection['trials'][:-2];projection['candidate_trials']=projection['candidate_trials'][:-1]
    projection['cumulative_actual']-=1;projection['cumulative_actual_evaluations']-=2;projection['new_candidate_runs']-=1
    need(projection==read(repo/PRIOR),'OLD_HISTORY_CHANGED')
    summary=read(root/'SUMMARY.json');answer={};all_checks=[]
    for period in PERIODS:
        folder=root/period;receipt=read(folder/'RECEIPT.json');attempt=read(folder/'ATTEMPT.json');started=read(folder/'EXECUTION_STARTED.json')
        need(receipt['status']=='COMPLETED','RUN_NOT_COMPLETE')
        need(started['claim_commit']==started['remote_readback_sha']==receipt['claim_commit'],'RUNTIME_CLAIM')
        need(attempt['time_ns']<started['time_ns']<receipt['finished_ns'],'ATTEMPT_TIME_ORDER')
        need(receipt['spec_sha256']==attempt['spec_sha256']==sha((root/'SPEC.json').read_bytes()),'SPEC_RECEIPT')
        need(sha((folder/'RAW.json.gz').read_bytes())==receipt['raw_sha256'] and sha((folder/'RESULT.json.gz').read_bytes())==receipt['result_sha256'],'RAW_RESULT_RECEIPT')
        pp=repo/PARENT/(period+'.json.gz');need(sha(pp.read_bytes())==spec['baseline_sha256'][period],'PARENT_BYTES_CHANGED')
        raw,result,parent=gz(folder/'RAW.json.gz'),gz(folder/'RESULT.json.gz'),normalize_parent(gz(pp))
        count=check_raw(raw,result,costs,spec['periods'][period]);net=check_metrics(result)
        accounting=read(folder/'ACCOUNTING.json');comparison=compare_parent(parent,result,accounting)
        same(summary['periods'][period]['comparison'],accounting,'SUMMARY_ACCOUNTING')
        checks=check_summary(parent,result,summary['periods'][period]);all_checks.append(checks)
        answer[period]={'raw_bound_rows':count,'net':net,**comparison}
    passed=all(all(c.values()) for c in all_checks)
    rejected=all(not c['terminal_net_up'] and not c['cost2_up'] for c in all_checks)
    verdict='DEVELOPMENT_GOAL_MET' if passed else 'REJECT' if rejected else 'TRADEOFF'
    same(summary['joint_development_goal_met'],passed,'JOINT_GOAL');same(summary['verdict'],verdict,'VERDICT')
    return {'status':'SAVED_RAW_COST_METRICS_ATTRIBUTION_VERIFIED','economic_verdict':verdict,'candidate_total':51,'evaluation_total':82,
            'new_replays':0,'results':answer}
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--manifest-sha256',required=True);x=p.parse_args()
    print(json.dumps(verify(pin=x.manifest_sha256),indent=2))
