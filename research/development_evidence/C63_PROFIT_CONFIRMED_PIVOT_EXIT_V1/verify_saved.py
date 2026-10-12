"""Source/record check only. No candidate engine import or economic replay."""
import argparse,hashlib,importlib.util,json,math
from copy import deepcopy
from pathlib import Path
HERE=Path(__file__).resolve().parent;REPO=HERE.parents[2]
BASE='research/development_evidence/KR3_PROFIT_ZONE_PRESERVATION_AFTER_PR1223_V1'
PAR='research/development_evidence/M1_ER_RANGE_RESCUE_AFTER_PR1232_V1'
LATEST='research/development_evidence/C63_PARTIAL_REALIZATION_AFTER_PR1238_V1'
sp=importlib.util.spec_from_file_location('original_saved_checker',REPO/BASE/'verify_saved.py');v=importlib.util.module_from_spec(sp);sp.loader.exec_module(v)
read,gz,need,same,subset=v.read,v.gz,v.need,v.same,v.subset
BAR=14400000;REASON='CONFIRMED_PROFIT_PIVOT_CLOSE';PERIODS=('DEV2025','SEEN2026')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def native(close,floor,mom,n):
    return 'FIXED_FLOOR_CLOSE' if close<=floor else 'MOMENTUM_NONPOSITIVE_CLOSE' if mom<=0 else 'FIXED_TIME_CLOSE' if n>=20 else None

def path_check(t,trace,binding,end,rows=None):
    i=t['signal_index'];ei=t['entry_index'];need(ei==i+1,'ENTRY_INDEX')
    obs=[x for x in trace if x['signal_index']==i and x['kind']=='PROFIT_PIVOT_OBSERVATION']
    held=[x for x in trace if x['signal_index']==i and x['kind']=='HELD_CLOSE_OBSERVATION']
    need(obs and len(obs)==len(held),'EVERY_HELD_CLOSE_CHECKED')
    active=known=None;first=None;updates=0
    if rows is not None:need(rows[ei]['open']==t['entry_price'] and rows[ei]['bar_open_ts']==t['entry_ts'],'ORIGINAL_ENTRY')
    for n,(o,h) in enumerate(zip(obs,held),1):
        j=i+n;ts=t['entry_ts']+n*BAR
        need(first is None,'EARLIER_TRIGGER_MISSED')
        need(o['index']==h['index']==j and o['ts']==h['ts']==ts and o['held_bars']==h['held_bars']==n,'HELD_CLOCK')
        c=v.costs_for(binding,t['entry_ts'],ts)[1];be=t['entry_price']*(1+c/10000)
        nr=native(h['close'],t['fixed_floor'],h['momentum'],n)
        broken=active is not None and known<j and h['close']<active
        reason=nr if nr is not None else REASON if broken else None
        subset(o,dict(close=h['close'],cost_bps=c,break_even=be,previous_level=active,previous_level_broken=broken,native_reason=nr,selected_reason=reason),'PIVOT_DECISION')
        need(h['exit_reason']==reason and h['floor']==t['fixed_floor'],'NATIVE_DECISION')
        q=o['newly_confirmed_low']
        if q is not None:
            need(q['kind']=='LOW' and q['known_index']==j and q['index']==j-2 and q['available_at']==ts,'PIVOT_CONFIRMATION_CLOCK')
        if rows is not None:
            need(h['close']==rows[j]['close'] and ts==rows[j]['bar_close_ts'],'SOURCE_HELD')
            same(h['momentum'],rows[j]['close']-rows[j-14]['close'],'SOURCE_MOMENTUM')
            k=j-2;is_pivot=k>=2 and all(rows[k]['low']<rows[z]['low'] for z in (k-2,k-1,k+1,k+2))
            need((q is not None)==is_pivot,'SOURCE_PIVOT_PRESENCE_ABSENCE')
            if q is not None:need(q['price']==rows[k]['low'],'SOURCE_PIVOT_PRICE')
        update=q if reason is None and q is not None and q['index']>=ei and q['price']>be and (active is None or q['price']>active) else None
        same(o['activated'],update,'ACTIVATION')
        if update is not None:active=q['price'];known=j;updates+=1
        subset(o,dict(active_after=active,active_known_index=known),'RATCHET')
        if reason is not None:first=dict(signal_index=j,signal_ts=ts,observed_close=h['close'],reason=reason)
    need(t['profit_pivot_radius']==2 and t['profit_pivot_last_level']==active and t['profit_pivot_available_index']==known,'FINAL_PROTECTION')
    if 'exit_ts' in t:
        need(first is not None and t['exit_trigger']==first,'FIRST_EXIT_TRIGGER')
        need(t['exit_index']==first['signal_index']+1 and t['exit_ts']==first['signal_ts']<end,'ACTUAL_NEXT_OPEN_CLOCK')
        need(t['exit_reason']==first['reason']+'_NEXT_OPEN','FINAL_REASON')
        if rows is not None:need(t['exit_price']==rows[t['exit_index']]['open'],'ACTUAL_NEXT_OPEN_PRICE')
    else:
        need(t['mark_ts']==end==held[-1]['ts'] and t['pending_exit_trigger']==first,'OPEN_PENDING')
        if first:need(first['signal_ts']==end,'EXECUTABLE_TRIGGER_LEFT_OPEN')
        if rows is not None:need(t['mark_price']==rows[t['mark_index']]['close'],'ORIGINAL_OPEN_MARK')
    need(t['original_protective_sl'] is None and not t['exchange_resident_stop'] and not t['protection_is_guaranteed_profit'],'FALSE_PROTECTION_CREDIT')
    return dict(held_closes=len(held),activations=updates,extra_exits=int(first is not None and first['reason']==REASON))

def daily(r,rows_by,costs):
    op={s:{x['bar_open_ts']:x['open'] for x in rows} for s,rows in rows_by.items()};cl={s:{x['bar_close_ts']:x['close'] for x in rows} for s,rows in rows_by.items()}
    for day in r['metrics']['daily']:
        ts=day['mark_ts'];g=n=n2=0.;num=0
        for kind,key in [('C','trades'),('O','open_observations')]:
            for t in r[key]:
                if t['entry_ts']>ts:continue
                if kind=='C' and t['exit_ts']<=ts:g+=t['gross_bps'];n+=t['net_bps'];n2+=t['cost2x_net_bps'];continue
                num+=1;price=op[t['symbol']].get(ts,cl[t['symbol']].get(ts));need(price is not None,'SOURCE_DAILY_PRICE')
                gross=(price/t['entry_price']-1)*10000;cost=v.costs_for(costs[t['symbol']],t['entry_ts'],ts)[1];g+=gross;n+=gross-cost;n2+=gross-2*cost
        same([g,n,n2],[day['cumulative_gross_mark_bps'],day['cumulative_net_mark_bps'],day['cumulative_cost2x_mark_bps']],'SOURCE_DAILY_MARK')
        need(num==day['active_marked_positions'],'DAILY_OCCUPANCY')

def detail(parent,r,account):
    p,c=v.complete_index(parent),v.complete_index(r);win=[(k,t[1]['net_bps']) for k,t in p.items() if t[0]=='C' and t[1]['net_bps']>0]
    large=sorted(win,key=lambda x:(-x[1],x[0]))[:max(1,math.ceil(.1*len(win)))]
    def retention(group):return sum(min(amount,max(0,v.values(c.get(k))['net_bps'])) for k,amount in group)/sum(amount for k,amount in group)
    deltas={k:v.values(c.get(k))['net_bps']-v.values(p.get(k))['net_bps'] for k in p.keys()|c.keys()}
    symbols={s:math.fsum(amount for k,amount in deltas.items() if k[0]==s) for s in {k[0] for k in deltas}}
    return dict(net_delta=math.fsum(deltas.values()),by_symbol=symbols,largest_positive_contribution=max(deltas.values()),smallest_contribution=min(deltas.values()),winner_amount_retention=retention(win),topdecile_retention=retention(large),child_worst_loss=min(t['net_bps'] for t in r['trades']),parent_worst_loss=min(t['net_bps'] for t in parent['trades']),four_way=account['four_way_terminal_delta'],common_gain_harm={k:value for k,value in account['resolved_common_effects'].items() if k not in ('origins','matching_basis')},sign_transitions=account['sign_transitions'])

def cell(per,view,packet=None):
    d=HERE/per/view;spec=read(HERE/'SPEC.json');end=spec['periods'][per]['runoff_end_ms'];r=gz(d/'RESULT.json.gz');raw=gz(d/'RAW.json.gz');pr=gz(REPO/PAR/per/'RAW.json.gz');parent=gz(REPO/PAR/per/'RESULT.json.gz');costs=read(REPO/BASE/'COSTS.json')
    expected={k:[] for k in ('trades','open_observations','events','trace')};counts=dict(positions=0,held_closes=0,activations=0,extra_exits=0,signals=0)
    for sym,x in sorted(raw.items()):
        rows=None if packet is None else packet['rows_by'][sym]
        oldevents={e['signal_index']:e for e in pr[sym]['events']};fixed={t['signal_index'] for key in ('trades','open_positions') for t in pr[sym][key]}
        need([e['signal_index'] for e in x['events']]==[e['signal_index'] for e in pr[sym]['events'] if view=='FULL' or e['signal_index'] in fixed],'SIGNAL_POOL')
        need(x['setup_events']==pr[sym]['setup_events'],'SETUP_RULE_CHANGED')
        positions={t['signal_index']:t for key in ('trades','open_positions') for t in x[key]};last=-1;tail=False
        if view=='FIXED':need(set(positions)==fixed,'FIXED_ADMISSIONS')
        for e in x['events']:
            i=e['signal_index'];counts['signals']+=1
            subset(e,{k:value for k,value in oldevents[i].items() if k not in ('admission','status','exclusion_reason')},'PARENT_ENTRY_FIELDS')
            need((i in positions)==e['admission'],'ADMISSION_RECORD')
            reason=None
            if tail or e['signal_ts']<=last:reason='ACTUAL_POSITION_OCCUPIED_AT_DECISION'
            elif e['expiry'] is not None and e['signal_ts']>=e['expiry']:reason='SETUP_EXPIRED_BEFORE_ENTRY'
            elif not e['er_context']['eligible']:reason=e['er_context']['reason']
            elif e['signal_ts']>=end:reason='NO_NEXT_OPEN_IN_APPROVED_WINDOW'
            elif rows is not None and rows[i+1]['open']<=e['floor']:reason='GAP_INVALIDATES_FIXED_SETUP'
            elif rows is None and e['exclusion_reason']=='GAP_INVALIDATES_FIXED_SETUP':reason='GAP_INVALIDATES_FIXED_SETUP'
            need(e['exclusion_reason']==reason and e['admission']==(reason is None),'ENTRY_OCCUPANCY_PRECEDENCE')
            if i in positions:
                t=positions[i];counts['positions']+=1;stats=path_check(t,x['trace'],costs[sym],end,rows)
                for k,value in stats.items():counts[k]+=value
                if 'exit_ts' in t:last=t['exit_ts']
                else:tail=True
        for source,target in [('trades','trades'),('open_positions','open_observations'),('events','events'),('trace','trace')]:expected[target].extend(dict(t,symbol=sym) for t in x[source])
    for key in ('events','trace'):
        need(len(expected[key])==len(r[key]),'TRACE_COUNT')
        for src,out in zip(expected[key],r[key]):subset(out,src,'RAW_TRACE')
    for kind in ('trades','open_observations'):
        src,out=v.index(expected[kind]),v.index(r[kind]);need(src.keys()==out.keys(),'RAW_CHARGED_ORIGINS')
        for key,t in out.items():
            subset(t,src[key],'RAW_GEOMETRY');closed=kind=='trades';ts=t['exit_ts'] if closed else t['mark_ts'];price=t['exit_price'] if closed else t['mark_price'];g=(price/t['entry_price']-1)*10000;parts,c,n=v.costs_for(costs[t['symbol']],t['entry_ts'],ts)
            need(t['entry_ts']==t['signal_ts'] and ts<=end and t['entry_ts']<ts,'TRADE_TIMING')
            if closed:
                subset(t,parts,'COSTS');same([t['gross_bps'],t['net_bps'],t['cost2x_net_bps'],t['cost_bps']],[g,g-c,g-2*c,c],'TRADE_PRICES_COST')
            else:
                need(not t['actual_exit'] and not t['terminal_liquidation'],'OPEN_NOT_FILL');same(t['hypothetical_cost_components_bps'],parts,'OPEN_COST');same(t['hypothetical_liquidation_net_mark_bps'],g-c,'OPEN_NET');same(t['hypothetical_liquidation_cost2x_net_mark_bps'],g-2*c,'OPEN_COST2')
            need(t['formal_credit']==0 and not t['independent'] and not t['exchange_order_submitted'],'AUTHORITY')
    v.check_metrics(r);account=read(d/'ACCOUNTING_C63.json');p=deepcopy(parent)
    if view=='FIXED':p['events']=[e for e in p['events'] if e['admission']]
    v.compare_parent(p,r,account)
    if packet is not None:need(packet['costs']==costs,'PACKET_COSTS');daily(r,packet['rows_by'],costs)
    return dict(counts=counts,detail=detail(parent,r,account),raw_sha256=sha(d/'RAW.json.gz'),result_sha256=sha(d/'RESULT.json.gz'))

def verify(inputs=None,derived_sha=None):
    spec=read(HERE/'SPEC.json');manifest=read(HERE/'EVIDENCE_HASHES.json')
    need(sha(HERE/'EVIDENCE_HASHES.json')=='f64e26882304c884065e007a45af62f6b97eb4af98b89e5001b6ac6b96af8f52','EVIDENCE_MANIFEST_PIN')
    for n,digest in manifest.items():need(sha(HERE/n)==digest,'EVIDENCE_CHANGED:'+n)
    for n,digest in spec['source_files_sha256'].items():need(sha(REPO/n)==digest,'FROZEN_SOURCE_CHANGED:'+n)
    b=read(HERE/'BUDGET.json');need((b['cumulative_actual'],b['cumulative_actual_evaluations'])==(67,118),'TOTAL_COUNTS')
    slot=b['c63_profit_pivot_allocation'];need([slot[k] for k in ('reserved','started','completed','failed','remaining')]==[4,4,4,0,0],'SCOPE_BUDGET')
    need([t['actual_experiment_ordinal'] for t in b['trials'][-6:]]==list(range(113,119)),'IMPORTED_AND_NEW_ORDINALS')
    old=deepcopy(b);old.pop('c63_profit_pivot_allocation');old.pop('local_prior_import_receipt_sha256');old['candidate_trials']=old['candidate_trials'][:-2];old['trials']=old['trials'][:-6];old['cumulative_actual']-=2;old['cumulative_actual_evaluations']-=6;old['new_candidate_runs']-=2
    need(old==read(REPO/LATEST/'BUDGET.json'),'PREVIOUS_FULL_HISTORY_CHANGED')
    need(sha(REPO/LATEST/'BUDGET.json')==spec['prior_budget_sha256'],'PRIOR_BUDGET_HASH')
    for per,files in spec['parent_results_sha256'].items():
        for name,digest in files.items():need(sha(REPO/PAR/per/name)==digest,'C63_CHANGED')
    result={}
    for per in PERIODS:
        packet=None
        if inputs is not None:
            pp=Path(inputs)/(per+'.json.gz');need(sha(pp)==spec['input_packet_sha256'][per],'SOURCE_PACKET');packet=gz(pp)
        for view in ('FIXED','FULL'):
            d=HERE/per/view;at,start,receipt=[read(d/n) for n in ('ATTEMPT.json','EXECUTION_STARTED.json','RECEIPT.json')]
            need(spec['frozen_ns']<at['time_ns']<start['time_ns'],'PRE_OUTCOME_FREEZE')
            need(at['spec_sha256']==receipt['spec_sha256']==sha(HERE/'SPEC.json'),'SPEC_ID')
            need(start['claim_commit']==start['remote_readback_sha']==receipt['claim_commit'],'DURABLE_CLAIM')
            result[per+'/'+view]=cell(per,view,packet)
    if derived_sha:
        need(sha(HERE/'DERIVED.json')==derived_sha,'DERIVED_HASH');same(read(HERE/'DERIVED.json')['cells'],result,'DERIVED_CONTENT')
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--inputs');p.add_argument('--derived-sha256');args=p.parse_args();print(json.dumps(verify(args.inputs,args.derived_sha256),indent=2))
