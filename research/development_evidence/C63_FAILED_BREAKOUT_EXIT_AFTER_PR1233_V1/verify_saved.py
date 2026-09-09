"""Independent saved/source checks. No strategy execution or alternative PnL.
Every recorded held close is checked, including non-triggering positions.
Optional original packets also validate prices, excursions and daily marks.
"""
import argparse,hashlib,importlib.util,json,math
from collections import defaultdict
from copy import deepcopy
from pathlib import Path
HERE=Path(__file__).resolve().parent
PARENT='research/development_evidence/M1_ER_RANGE_RESCUE_AFTER_PR1232_V1'
C51='research/development_evidence/KR3_PROFIT_ZONE_PRESERVATION_AFTER_PR1223_V1'
KEY='c63_failed_breakout_exit_allocation';BAR=14400000
REASON='FAILED_BREAKOUT_NONPOSITIVE_CLOSE'
EVIDENCE_SHA='d3e4245ad1c42624689258a71e1d2a55376e4941dbad9164c627a1e333dd1460'

def module(path,name):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
rescue=module(HERE.parents[2]/PARENT/'verify_saved.py','rescue_saved_check')
v=rescue.v
read,gz,sha,canon,need=rescue.read,rescue.gz,rescue.sha,rescue.canon,rescue.need
PERIODS=rescue.PERIODS

def decision(close,floor,momentum,held,escaped,upper,net):
    if close<=floor:return 'FIXED_FLOOR_CLOSE'
    if momentum<=0:return 'MOMENTUM_NONPOSITIVE_CLOSE'
    if held>=20:return 'FIXED_TIME_CLOSE'
    if escaped and close<upper and net<=0:return REASON
    return None

def check_path(t,event,trace,binding,end,rows=None):
    i=t['signal_index'];ei=i+1;rc=event['er_context']['range_context'];upper=rc['prior_high'];escape=rc['strict_escape']
    held=[z for z in trace if z['signal_index']==i and z['kind']=='HELD_CLOSE_OBSERVATION']
    guards=[z for z in trace if z['signal_index']==i and z['kind']=='FAILED_BREAKOUT_OBSERVATION']
    need(held and len(held)==len(guards),'HELD_GUARD_COVERAGE')
    need(t['entry_index']==ei and t['entry_ts']==event['signal_ts'],'ENTRY_CLOCK')
    need(t['failed_breakout_upper']==upper and t['entry_broke_prior_range']==escape,'FIXED_RANGE_CHANGED')
    need(t['failed_breakout_source_start']==event['episode_start'] and t['failed_breakout_source_end']==i-1 and t['failed_breakout_source_available_at']==event['signal_ts']-BAR,'FIXED_RANGE_AVAILABILITY')
    if rows is not None:
        need(t['entry_price']==rows[ei]['open'] and t['entry_ts']==rows[ei]['bar_open_ts'],'SOURCE_ENTRY')
        need(upper==max(x['high'] for x in rows[event['episode_start']:i]) and escape==(rows[i]['close']>upper),'SOURCE_RANGE')
        need(t['fixed_floor']==min(x['low'] for x in rows[event['episode_start']:i+1]),'SOURCE_FLOOR')
    first=None
    for n,(h,g) in enumerate(zip(held,guards),1):
        j=i+n;stamp=t['entry_ts']+n*BAR
        need(h['index']==g['index']==j and h['ts']==g['ts']==stamp and h['held_bars']==g['held_bars']==n,'HELD_CLOSE_CONTINUITY')
        need(first is None,'MISSED_FIRST_EXIT')
        cost=v.costs_for(binding,t['entry_ts'],stamp)[1];net=(h['close']/t['entry_price']-1)*10000-cost
        native=decision(h['close'],t['fixed_floor'],h['momentum'],n,False,upper,net)
        expected=decision(h['close'],t['fixed_floor'],h['momentum'],n,escape,upper,net)
        v.subset(g,dict(close=h['close'],fixed_upper=upper,entry_breakout=escape,cost_bps=cost,net_mark_bps=net,native_reason=native,predicate=escape and h['close']<upper and net<=0,selected_reason=expected),'GUARD_ARITHMETIC')
        need(h['floor']==t['fixed_floor'] and h['exit_reason']==expected,'FIRST_EXIT_REASON')
        if rows is not None:
            need(h['close']==rows[j]['close'] and stamp==rows[j]['bar_close_ts'],'SOURCE_HELD_CLOSE')
            v.same(h['momentum'],rows[j]['close']-rows[j-14]['close'],'SOURCE_MOMENTUM')
        if expected is not None:first=dict(signal_index=j,signal_ts=stamp,observed_close=h['close'],reason=expected)
    closed='exit_ts' in t
    if closed:
        need(first is not None and t['exit_trigger']==first,'MISSING_FIRST_TRIGGER')
        need(t['exit_index']==first['signal_index']+1 and t['exit_ts']==first['signal_ts']<end,'NEXT_OPEN_CLOCK')
        need(t['exit_reason']==first['reason']+'_NEXT_OPEN','WRONG_EXIT_REASON')
        if rows is not None:need(t['exit_price']==rows[t['exit_index']]['open'],'SOURCE_EXIT_PRICE')
    else:
        need(t['mark_ts']==end==held[-1]['ts'] and not t['terminal_liquidation'],'TRUNCATED_OR_FAKE_OPEN')
        need(t['pending_exit_trigger']==first,'WRONG_PENDING_EXIT')
        if first is not None:need(first['signal_ts']==end,'MISSED_EXECUTABLE_EXIT')
        if rows is not None:need(t['mark_price']==rows[t['mark_index']]['close'],'SOURCE_MARK')
    need(t['original_protective_sl'] is None and not t['exchange_resident_stop'],'FAKE_RESIDENT_STOP')
    if rows is not None:
        last=held[-1]['index'];tail=t['exit_price'] if closed else t['mark_price'];entry=t['entry_price'];g=(tail/entry-1)*10000
        v.same(t['mfe_bps'],max(0,g,max((r['high']/entry-1)*10000 for r in rows[ei:last+1])),'SOURCE_MFE')
        v.same(t['mae_bps'],min(0,g,min((r['low']/entry-1)*10000 for r in rows[ei:last+1])),'SOURCE_MAE')
    return len(held),int(closed and first['reason']==REASON)

def check_cell(root,per,view,rows_by=None):
    root=Path(root);repo=root.parents[2];d=root/per/view;spec=read(root/'SPEC.json');cal=spec['periods'][per]
    raw=gz(d/'RAW.json.gz');r=gz(d/'RESULT.json.gz');pr=gz(repo/PARENT/per/'RAW.json.gz');parent=gz(repo/PARENT/per/'RESULT.json.gz');costs=read(repo/C51/'COSTS.json')
    count=observed=extra=signal_count=0;expected={k:[] for k in ('trades','open_observations','events','trace')}
    for symbol,x in sorted(raw.items()):
        original={e['signal_index']:e for e in pr[symbol]['events']};entries={t['signal_index']:t for k in ('trades','open_positions') for t in x[k]}
        need(len(entries)==sum(len(x[k]) for k in ('trades','open_positions')),'DUPLICATE_POSITION')
        fixed={t['signal_index'] for k in ('trades','open_positions') for t in pr[symbol][k]}
        need([e['signal_index'] for e in x['events']]==[e['signal_index'] for e in pr[symbol]['events'] if view=='FULL' or e['signal_index'] in fixed],'SIGNAL_POOL')
        need(x['setup_events']==pr[symbol]['setup_events'],'NATIVE_SETUP_LOG_CHANGED')
        if view=='FIXED':need(set(entries)==fixed,'FIXED_ORIGIN_PARITY')
        last_exit=-1;tail=False;pending=[]
        rows=None if rows_by is None else rows_by[symbol]
        for e in x['events']:
            i=e['signal_index'];signal_count+=1
            for k,value in original[i].items():
                if k not in ('admission','status','exclusion_reason'):v.same(e[k],value,'ORIGINAL_SIGNAL')
            source={str(z['index']):dict(close=z['close'],bar_close_ts=z['ts']) for z in e['er_context']['source_closes']}
            good=rescue.feature(e,source,v)
            reason=None
            if tail or e['signal_ts']<=last_exit:reason='ACTUAL_POSITION_OCCUPIED_AT_DECISION'
            elif e['expiry'] is not None and e['signal_ts']>=e['expiry']:reason='SETUP_EXPIRED_BEFORE_ENTRY'
            elif not good:reason=e['er_context']['reason']
            elif e['signal_ts']>=cal['runoff_end_ms']:reason='NO_NEXT_OPEN_IN_APPROVED_WINDOW';pending.append(e)
            elif rows is not None and rows[i+1]['open']<=e['floor']:reason='GAP_INVALIDATES_FIXED_SETUP'
            elif rows is None and e['exclusion_reason']=='GAP_INVALIDATES_FIXED_SETUP':reason='GAP_INVALIDATES_FIXED_SETUP'
            if rows is not None:
                for z in e['er_context']['source_closes']:need(z['close']==rows[z['index']]['close'] and z['ts']==rows[z['index']]['bar_close_ts'],'SOURCE_ER')
                for z in e['er_context']['range_context']['source_highs']:need(z['high']==rows[z['index']]['high'],'SOURCE_RANGE_HIGH')
            need(e['exclusion_reason']==reason and e['admission']==(reason is None),'ENTRY_PRECEDENCE')
            need((i in entries)==e['admission'],'ADMISSION_PARITY')
            if i in entries:
                t=entries[i];n,ex=check_path(t,e,x['trace'],costs[symbol],cal['runoff_end_ms'],rows);observed+=n;extra+=ex;count+=1
                if 'exit_ts' in t:last_exit=t['exit_ts'];need(e['status']=='COMPLETED','CLOSED_STATUS')
                else:tail=True;need(e['status']=='CENSORED','OPEN_STATUS')
        need(x['pending_entries']==pending,'PENDING_ENTRY_PARITY')
        for src,dst in [('trades','trades'),('open_positions','open_observations'),('events','events'),('trace','trace')]:expected[dst].extend(dict(t,symbol=symbol) for t in x[src])
    need(r['reference_states']=={},'NEW_REFERENCE_STATE')
    for key in ('events','trace'):
        need(len(r[key])==len(expected[key]),'TRACE_COUNT')
        for out,src in zip(r[key],expected[key]):v.subset(out,src,'CHARGED_TRACE')
    for key in ('trades','open_observations'):
        source,charged=v.index(expected[key]),v.index(r[key]);need(source.keys()==charged.keys(),'CHARGED_ORIGINS')
        for k,t in charged.items():
            v.subset(t,source[k],'RAW_GEOMETRY');closed=key=='trades';end=t['exit_ts'] if closed else t['mark_ts'];price=t['exit_price'] if closed else t['mark_price'];gross=(price/t['entry_price']-1)*10000
            parts,cost,num=v.costs_for(costs[t['symbol']],t['entry_ts'],end)
            need(cal['start_ms']<=t['entry_ts']<end<=cal['runoff_end_ms'],'POSITION_CALENDAR');v.same(t['hold_ms'],end-t['entry_ts'],'HOLD_TIME')
            if closed:
                v.subset(t,parts,'COST_COMPONENTS');v.same(t['cost_bps'],cost,'COST');v.same(t['gross_bps'],gross,'GROSS');v.same(t['net_bps'],gross-cost,'NET');v.same(t['cost2x_net_bps'],gross-2*cost,'COST2')
            else:
                need(not t['actual_exit'] and not t['terminal_liquidation'],'FALSE_TAIL_EXIT');v.same(t['hypothetical_cost_components_bps'],parts,'OPEN_COST');v.same(t['hypothetical_liquidation_net_mark_bps'],gross-cost,'OPEN_NET');v.same(t['hypothetical_liquidation_cost2x_net_mark_bps'],gross-2*cost,'OPEN_COST2')
            need(not t['exchange_order_submitted'] and t['formal_credit']==0 and not t['independent'],'AUTHORITY_CHANGED')
    v.check_metrics(r)
    comp_parent=deepcopy(parent)
    if view=='FIXED':comp_parent['events']=[e for e in parent['events'] if e['admission']]
    attribution=v.compare_parent(comp_parent,r,read(d/'ACCOUNTING_C63.json'))
    if view=='FULL':v.compare_parent(gz(repo/rescue.old.OLD/'M1'/per/'RESULT.json.gz'),r,read(d/'ACCOUNTING_M1.json'))
    if rows_by is not None:check_daily(r,rows_by,costs)
    detail=rescue.old.detail(parent,r,v)
    detail.update(attribution=attribution,parent_worst_loss_bps=min(t['net_bps'] for t in parent['trades']),child_worst_loss_bps=min(t['net_bps'] for t in r['trades']),extra_exit_T=extra,held_close_observations=observed)
    return dict(positions=count,signals=signal_count,held_closes=observed,extra_exits=extra,details=detail)

def check_daily(result,rows_by,costs):
    by_open={s:{z['bar_open_ts']:z['open'] for z in rows} for s,rows in rows_by.items()}
    by_close={s:{z['bar_close_ts']:z['close'] for z in rows} for s,rows in rows_by.items()}
    for day in result['metrics']['daily']:
        stamp=day['mark_ts'];g=n=n2=0.;active=0
        for kind,key in [('C','trades'),('O','open_observations')]:
            for t in result[key]:
                if t['entry_ts']>stamp:continue
                if kind=='C' and t['exit_ts']<=stamp:
                    g+=t['gross_bps'];n+=t['net_bps'];n2+=t['cost2x_net_bps'];continue
                active+=1;price=by_open[t['symbol']].get(stamp,by_close[t['symbol']].get(stamp));need(price is not None,'MISSING_MARK_SOURCE')
                gross=(price/t['entry_price']-1)*10000;cost=v.costs_for(costs[t['symbol']],t['entry_ts'],stamp)[1]
                g+=gross;n+=gross-cost;n2+=gross-2*cost
        v.same([g,n,n2],[day['cumulative_gross_mark_bps'],day['cumulative_net_mark_bps'],day['cumulative_cost2x_mark_bps']],'ORIGINAL_SOURCE_DAILY_MARK')
        need(active==day['active_marked_positions'],'DAILY_ACTIVE_COUNT')

def originals(inputs,root=HERE):
    s=read(root/'SPEC.json');out={}
    for per in PERIODS:
        path=Path(inputs)/f'{per}.json.gz';need(sha(path)==s['input_packet_sha256'][per],'INPUT_HASH');packet=gz(path)
        need(packet['costs']==read(root.parents[2]/C51/'COSTS.json'),'ORIGINAL_COST_BINDING')
        for view in ('FIXED','FULL'):
            proof=check_cell(root,per,view,packet['rows_by']);proof.pop('details')
            out[per+'/'+view]=dict(proof,input_sha256=sha(path),raw_sha256=sha(root/per/view/'RAW.json.gz'),result_sha256=sha(root/per/view/'RESULT.json.gz'),original_daily_marks_checked=len(gz(root/per/view/'RESULT.json.gz')['metrics']['daily']),new_economic_replays=0)
    return out

def verify(root=HERE,derived_sha=None):
    root=Path(root);repo=root.parents[2]
    need(sha(root/'EVIDENCE_HASHES.json')==EVIDENCE_SHA,'EVIDENCE_MANIFEST')
    for name,d in read(root/'EVIDENCE_HASHES.json').items():need(sha(root/name)==d,'EXECUTED_EVIDENCE_CHANGED:'+name)
    if derived_sha:need(sha(root/'DERIVED.json')==derived_sha,'DERIVED_PIN')
    spec=read(root/'SPEC.json');b=deepcopy(read(root/'BUDGET.json'));slot=b.pop(KEY)
    need((slot['reserved'],slot['started'],slot['completed'],slot['failed'],slot['remaining'])==(4,4,4,0,0),'SCOPE_INCOMPLETE')
    need((b['cumulative_actual'],b['cumulative_actual_evaluations'])==(64,110) and b['candidate_trials'][-1]['ordinal']==64 and [x['actual_experiment_ordinal'] for x in b['trials'][-4:]]==[107,108,109,110],'COUNTS')
    b['candidate_trials']=b['candidate_trials'][:-1];b['trials']=b['trials'][:-4];b['cumulative_actual']-=1;b['cumulative_actual_evaluations']-=4;b['new_candidate_runs']-=1
    need(b==read(repo/PARENT/'BUDGET.json') and b['chart_allocation']['remaining']==6,'PRIOR_HISTORY')
    need(sha(repo/PARENT/'BUDGET.json')==spec['prior_budget_sha256'] and sha(repo/PARENT/'SPEC.json')==spec['prior_spec_sha256'],'PARENT_BYTES')
    for name,d in spec['source_files_sha256'].items():need(sha(repo/name)==d,'FROZEN_SOURCE:'+name)
    for per,files in spec['parent_results_sha256'].items():
        for name,d in files.items():need(sha(repo/PARENT/per/name)==d,'PARENT_RESULT')
    meta=read(root/'DERIVED.json');summary=read(root/'SUMMARY.json');totals={};allflags=[]
    for per in PERIODS:
        parent=gz(repo/PARENT/per/'RESULT.json.gz');full=gz(root/per/'FULL/RESULT.json.gz')
        flags=rescue.old.checks(parent,full,v);need(flags==summary['periods'][per]['checks'],'SUMMARY_FLAGS');allflags.append(flags)
        for view in ('FIXED','FULL'):
            d=root/per/view;cell=check_cell(root,per,view);proof=meta['source_proof'][per+'/'+view];totals[per+'/'+view]=cell
            receipt,at,start=[read(d/n) for n in ('RECEIPT.json','ATTEMPT.json','EXECUTION_STARTED.json')]
            need(receipt['raw_sha256']==proof['raw_sha256']==sha(d/'RAW.json.gz') and receipt['result_sha256']==proof['result_sha256']==sha(d/'RESULT.json.gz'),'RESULT_SOURCE_RECEIPT')
            need(proof['input_sha256']==spec['input_packet_sha256'][per],'SOURCE_INPUT')
            need(receipt['claim_commit']==start['claim_commit']==start['remote_readback_sha'] and at['owner_run']==start['owner_run'],'REMOTE_CLAIM')
            need(spec['frozen_ns']<at['time_ns']<start['time_ns'] and at['spec_sha256']==receipt['spec_sha256']==sha(root/'SPEC.json'),'PRE_OUTCOME_FREEZE')
            v.same(meta['details'][per+'/'+view],cell['details'],'DERIVED_DETAILS')
            for k in ('positions','signals','held_closes','extra_exits'):need(cell[k]==proof[k],'SOURCE_COUNTS')
        for label,r in [('C63',parent)]+[(z,gz(root/per/z/'RESULT.json.gz')) for z in ('FIXED','FULL')]:
            m=r['metrics'];base=m['base_cost'];snap=summary['periods'][per]['snapshots'][label]
            need(snap['closed']==len(r['trades']) and snap['open']==len(r['open_observations']),'SNAPSHOT_COUNTS')
            v.subset(snap,{k:base[k] for k in ('win_rate','average_win_bps','average_loss_bps','realized_payoff','PF')},'SNAPSHOT');v.subset(snap,{k:m[k] for k in ('terminal_net_bps','terminal_cost2x_net_bps','marked_DD_trade_sum_bps')},'TOTALS')
            fmt=lambda x:'NA' if x is None else f'{x:.2f}'
            row='|'+ '|'.join([per,label,f"{len(r['trades'])}/{len(r['open_observations'])}",fmt(None if base['win_rate'] is None else base['win_rate']*100)]+[fmt(base[k]) for k in ('average_win_bps','average_loss_bps','realized_payoff','PF')]+[fmt(m[k]) for k in ('terminal_net_bps','terminal_cost2x_net_bps','marked_DD_trade_sum_bps')])+'|'
            need(row in (root/'REPORT.md').read_text(),'REPORT_TABLE')
    goal=all(all(f.values()) for f in allflags);gain=all(f['net_up'] and f['cost2_up'] for f in allflags)
    need(summary['status']==('DEVELOPMENT_GOAL_MET' if goal else 'PARTIAL_IMPROVEMENT' if gain else 'REJECT_KEEP_C63'),'GOAL_CLASSIFICATION')
    return dict(status=summary['status'],positions=sum(x['positions'] for x in totals.values()),held_closes=sum(x['held_closes'] for x in totals.values()),signals=sum(x['signals'] for x in totals.values()),candidates=64,evaluations=110,new_economic_replays=0)

if __name__=='__main__':
    q=argparse.ArgumentParser();q.add_argument('--derived-sha256',required=True);q.add_argument('--inputs');args=q.parse_args()
    if args.inputs:need(originals(Path(args.inputs))==read(HERE/'DERIVED.json')['source_proof'],'ORIGINAL_SOURCE_PROOF')
    print(json.dumps(verify(derived_sha=args.derived_sha256),indent=2))
