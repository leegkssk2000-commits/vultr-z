"""Read-only source and arithmetic verification. No strategy/evaluator imports.

Validates all saved signal contexts, native safety/occupancy, first exits,
costs/calendar marks and contribution amounts. Does not evaluate alternatives.
"""
from pathlib import Path
from math import fsum,isclose,ceil,isfinite
from collections import defaultdict,Counter
import json,gzip,hashlib,datetime
OUT=Path(__file__).resolve().parent;ROOT=OUT.parents[2];INPUTS=None;B=14_400_000;D=86_400_000
read=lambda p:json.loads(Path(p).read_text())
gz=lambda p:json.loads(gzip.decompress(Path(p).read_bytes()))
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def check(value,label):
    if not value:raise AssertionError(label)
def close(x,y,label):
    if x is None or y is None:check(x is y,label)
    else:check(isclose(x,y,rel_tol=1e-11,abs_tol=1e-7),label)
def key(t):return (t['symbol'],t['signal_index'],t['signal_ts'])
def pos(r):return [('C',t) for t in r['trades']]+[('O',t) for t in r['open_observations']]
def daily_at(rows,i):
    now=rows[i]['bar_close_ts'];by={}
    for row in rows[:i+1]:by.setdefault(row['bar_open_ts']//D,[]).append(row)
    result=[]
    for day,group in sorted(by.items()):
        if len(group)==6 and group[0]['bar_open_ts']==day*D and group[-1]['bar_close_ts']<=now:
            check([r['bar_open_ts'] for r in group]==[day*D+j*B for j in range(6)],'DAILY_GAP')
            result.append(dict(open_ts=day*D,available_at=(day+1)*D,close=group[-1]['close']))
    return result

def expected_context(rows,e):
    i=e['signal_index'];t=e['signal_ts'];check(rows[i]['bar_close_ts']==t,'SIGNAL_CLOCK')
    ds=daily_at(rows,i);ema=None
    if len(ds)>=21:
        ema=fsum(d['close'] for d in ds[:21])/21
        for d in ds[21:]:ema=d['close']/11+(10/11)*ema
    sma=prior=None
    if len(ds)>=6:sma=fsum(d['close'] for d in ds[-5:])/5;prior=fsum(d['close'] for d in ds[-6:-1])/5
    hi=max(r['high'] for r in rows[e['episode_start']:i]);escape=rows[i]['close']>hi
    def efficiency(j):
        if j<14:return None
        prices=[r['close'] for r in rows[j-14:j+1]];travel=fsum(abs(b-a) for a,b in zip(prices,prices[1:]))
        return abs(prices[-1]-prices[0])/travel if travel else 0.
    current,prev=efficiency(i),efficiency(i-1)
    original=current is not None and prev is not None and (current>prev or escape)
    dailygood=ema is not None and rows[i]['close']>ema
    session_start=rows[i]['bar_open_ts']//D*D
    prevrows=[(j,r) for j,r in enumerate(rows[:i+1]) if session_start-D<=r['bar_open_ts']<session_start]
    session=None
    if len(prevrows)==6:
        check([r['bar_open_ts'] for j,r in prevrows]==[session_start-D+j*B for j in range(6)],'PRIOR_SESSION_CONTINUITY')
        session=dict(open_ts=session_start-D,available_at=session_start,high=max(r['high'] for j,r in prevrows),source_highs=[dict(index=j,open_ts=r['bar_open_ts'],high=r['high']) for j,r in prevrows],rule='SESSION_BEFORE_SIGNAL_BAR_OPEN_DATE_NOT_SIGNAL_CLOSE_DATE')
    above_high=session is not None and rows[i]['close']>session['high']
    rescue=bool(original and ema is not None and not dailygood and sma is not None and rows[i]['close']>sma and above_high and escape)
    eligible=bool(original and (dailygood or rescue))
    return dict(days=ds,ema=ema,sma=sma,previous_sma=prior,range_high=hi,escape=escape,original=original,dailygood=dailygood,rescue=rescue,eligible=eligible,session=session,above_high=above_high)

def verify_context(rows,e):
    expected=expected_context(rows,e);ctx=e['er_context'];daily=ctx['daily_context'];r=ctx['recovery_context']
    check(daily['daily_closes']==expected['days'],'DAILY_WITNESS')
    close(daily['value'],expected['ema'],'EMA21_VALUE');close(r['sma'],expected['sma'],'SMA5_VALUE');close(r['previous_sma'],expected['previous_sma'],'SMA5_PREVIOUS')
    check(ctx['eligible']==expected['eligible'],'ELIGIBILITY')
    check(ctx['c63_eligible']==expected['original'],'C63_ELIGIBILITY')
    check(daily['eligible']==expected['dailygood'],'C69_ELIGIBILITY')
    check(r['rescued']==expected['rescue'],'RESCUE_DECISION')
    check(r['strict_prior_squeeze_high_escape']==expected['escape'],'PRIOR_RANGE_ESCAPE')
    check(r['daily_witnesses']==expected['days'][-6:],'SMA5_SIX_WITNESSES')
    check(r['available_at']==e['signal_ts'],'RECOVERY_CLOCK')
    check(r['prior_session']==expected['session'],'SOURCE_PRIOR_SESSION')
    check(r['above_prior_session_high']==expected['above_high'],'SOURCE_HIGH_BREAK')
    check(r['slope_used_for_decision'] is False,'SLOPE_NOT_SIGNAL')
    return expected

def terminal_from_source(rows,e,end):
    ei=e['signal_index']+1;floor=e['floor'];trigger=None
    for j in range(ei,len(rows)):
        price=rows[j]['close'];momentum=price-rows[j-14]['close'];held=j-ei+1
        reason='FIXED_FLOOR_CLOSE' if price<=floor else 'MOMENTUM_NONPOSITIVE_CLOSE' if momentum<=0 else 'FIXED_TIME_CLOSE' if held>=20 else None
        if reason:
            trigger=dict(index=j,reason=reason)
            if j+1<len(rows) and rows[j+1]['bar_open_ts']<end:return 'C',j+1,rows[j+1]['open'],rows[j+1]['bar_open_ts'],trigger
            break
    return 'O',j,rows[j]['close'],rows[j]['bar_close_ts'],trigger

def parts(cost,entry,terminal):
    funding=(terminal//(2*B)-entry//(2*B))*cost['funding_p95_per_settlement_bps']
    base=cost['fee_bps']+cost['spread_bps']+cost['impact_bps']+funding
    return max(20.,base),dict(fee_bps=cost['fee_bps'],spread_bps=cost['spread_bps'],impact_bps=cost['impact_bps'],funding_bps=funding,slippage_bps=0.,frozen_floor_reserve_bps=max(0.,20.-base))

def verify_period(per):
    spec=read(OUT/'SPEC.json');cal=spec['periods'][per];start,end=cal['start_ms'],cal['runoff_end_ms']
    packet=gz(INPUTS/f'{per}.json.gz');raw=gz(OUT/per/'RAW.json.gz');result=gz(OUT/per/'RESULT.json.gz')
    positions={key(t):(s,t) for s,t in pos(result)};check(len(positions)==len(pos(result)),'DUPLICATE_POSITION')
    count=dict(signals=0,positions=0,held_closes=0,calendar_marks=0,rescued=0)
    expected_set=set();individual={};emitted=[]
    for symbol,rr in sorted(raw.items()):
        rows=packet['rows_by'][symbol];last=-1;tail=False
        for bare in rr['events']:
            e=dict(bare,symbol=symbol);count['signals']+=1;x=verify_context(rows,e);count['rescued']+=x['rescue'];i=e['signal_index'];ei=i+1
            if tail or e['signal_ts']<=last:reason='ACTUAL_POSITION_OCCUPIED_AT_DECISION'
            elif e['expiry'] is not None and e['signal_ts']>=e['expiry']:reason='SETUP_EXPIRED_BEFORE_ENTRY'
            elif not x['eligible']:reason=e['er_context']['c63_reason'] if not x['original'] else 'COMPLETED_DAILY_EMA21_HISTORY_UNAVAILABLE' if x['ema'] is None else 'DAILY21_VETO_WITHOUT_PRIOR_SESSION_HIGH_CONFIRMATION'
            elif ei>=len(rows) or rows[ei]['bar_open_ts']>=end:reason='NO_NEXT_OPEN_IN_APPROVED_WINDOW'
            elif rows[ei]['open']<=e['floor'] or e['target'] is not None and rows[ei]['open']>=e['target']:reason='GAP_INVALIDATES_FIXED_SETUP'
            else:reason=None
            check(e['admission']==(reason is None),'ADMISSION');check(e['exclusion_reason']==reason,'EXCLUSION_REASON');emitted.append(key(e))
            check(e['floor']==min(r['low'] for r in rows[e['episode_start']:i+1]),'NATIVE_FLOOR_SOURCE')
            if reason is not None:continue
            k=key(e);check(k in positions,'MISSING_ADMITTED_POSITION');expected_set.add(k);state,t=positions[k]
            expected_state,j,price,ts,trigger=terminal_from_source(rows,e,end)
            check(state==expected_state,'COMPLETION_STATE');check(t['entry_index']==ei,'ENTRY_INDEX');close(t['entry_price'],rows[ei]['open'],'ENTRY_PRICE');check(t['entry_ts']==rows[ei]['bar_open_ts'],'ENTRY_TIME')
            if state=='C':
                check(t['exit_index']==j and t['exit_ts']==ts,'EXIT_CLOCK');close(t['exit_price'],price,'EXIT_PRICE');check(t['exit_reason']==trigger['reason']+'_NEXT_OPEN','EXIT_REASON');last=ts
                count['held_closes']+=j-ei
            else:
                check(t['mark_index']==j and t['mark_ts']==ts==end,'OPEN_MARK_CLOCK');close(t['mark_price'],price,'OPEN_MARK_PRICE');check(t['terminal_liquidation'] is False,'NO_FAKE_EXIT');tail=True;count['held_closes']+=j-ei+1
            check(t['hold_ms']==ts-t['entry_ts'],'HOLD_TIME');check(t['fixed_floor']==e['floor'],'FLOOR_UNCHANGED');check(t['original_protective_sl'] is None and not t['exchange_resident_stop'],'NO_FAKE_STOP')
            gross=(price/rows[ei]['open']-1)*10000;cost,p=parts(packet['costs'][symbol],t['entry_ts'],ts)
            net=gross-cost;net2=gross-2*cost
            if state=='C':
                for name,value in [('gross_bps',gross),('cost_bps',cost),('net_bps',net),('cost2x_net_bps',net2)]:close(t[name],value,'POSITION_'+name)
                for name,v in p.items():close(t[name],v,'COST_'+name)
            else:
                for name,value in [('gross_mark_bps',gross),('hypothetical_liquidation_cost_bps',cost),('hypothetical_liquidation_net_mark_bps',net),('hypothetical_liquidation_cost2x_net_mark_bps',net2)]:close(t[name],value,'OPEN_'+name)
                for name,v in p.items():close(t['hypothetical_cost_components_bps'][name],v,'OPEN_COST_'+name)
            individual[k]=dict(state=state,terminal=ts,net=net,net2=net2,gross=gross);count['positions']+=1
    check(set(positions)==expected_set,'EXTRA_OR_OMITTED_POSITION')
    check(set(emitted)=={key(e) for e in result['events']},'CHARGED_EVENT_SET')
    parent=gz(ROOT/'research/development_evidence/M1_ER_RANGE_RESCUE_AFTER_PR1232_V1'/per/'RESULT.json.gz')
    check(set(emitted)=={key(e) for e in parent['events']},'FULL_ORIGINAL_SIGNAL_POOL')
    ms=list(range((start//D+1)*D,end+1,D))
    if not ms or ms[-1]!=end:ms.append(end)
    price_by={s:{**{r['bar_close_ts']:r['close'] for r in rows},**{r['bar_open_ts']:r['open'] for r in rows if r['bar_open_ts']<end}} for s,rows in packet['rows_by'].items()}
    check([d['mark_ts'] for d in result['metrics']['daily']]==ms,'CALENDAR')
    peak=dd=prev=0.
    for stamp,day in zip(ms,result['metrics']['daily']):
        total=total2=0.
        for k,(state,t) in positions.items():
            if t['entry_ts']>stamp:continue
            if state=='C' and individual[k]['terminal']<=stamp:v,v2=individual[k]['net'],individual[k]['net2']
            else:
                price=price_by[t['symbol']][stamp];g=(price/t['entry_price']-1)*10000;cost,_=parts(packet['costs'][t['symbol']],t['entry_ts'],stamp);v,v2=g-cost,g-2*cost
            total+=v;total2+=v2
        close(day['cumulative_net_mark_bps'],total,'DAILY_NET');close(day['cumulative_cost2x_mark_bps'],total2,'DAILY_COST2');close(day['value'],total-prev,'DAILY_DELTA')
        peak=max(peak,total);dd=max(dd,peak-total);prev=total;count['calendar_marks']+=1
    net=sum(i['net'] for i in individual.values());net2=sum(i['net2'] for i in individual.values());closed=[i['net'] for i in individual.values() if i['state']=='C'];wins=[v for v in closed if v>0];losses=[v for v in closed if v<0]
    m=result['metrics'];close(m['terminal_net_bps'],net,'TOTAL_NET');close(m['terminal_cost2x_net_bps'],net2,'TOTAL_COST2');close(m['marked_DD_trade_sum_bps'],dd,'TOTAL_DD')
    close(m['base_cost']['win_rate'],len(wins)/len(closed) if closed else None,'WR');close(m['base_cost']['PF'],sum(wins)/-sum(losses) if losses else None,'PF')
    close(m['base_cost']['average_win_bps'],sum(wins)/len(wins) if wins else None,'AVG_WIN');close(m['base_cost']['average_loss_bps'],sum(losses)/len(losses) if losses else None,'AVG_LOSS')
    bases=ROOT/'research/development_evidence'
    refs={label:gz(bases/folder/per/'RESULT.json.gz') for label,folder in [('C63','M1_ER_RANGE_RESCUE_AFTER_PR1232_V1'),('C69','C63_DAILY_EMA21_HORTON_TIP_AFTER_PR1241_V1')]}
    imported=read(OUT/'LOCAL_C70_IMPORT.json')['periods'][per];selected={tuple(x) for x in imported['admitted']}
    refs['C70_LOCAL']={k:[t for t in refs['C63'][k] if key(t) in selected] for k in ('trades','open_observations')}
    details={}
    for label,ref in refs.items():
        old={key(t):(s,t) for s,t in pos(ref)};rows=[];by_symbol=defaultdict(float);groups=defaultdict(float);group_counts=Counter()
        for k in sorted(set(old)|set(individual)):
            p=old[k][1]['net_bps'] if k in old and old[k][0]=='C' else old[k][1]['hypothetical_liquidation_net_mark_bps'] if k in old else 0.
            value=individual[k]['net'] if k in individual else 0.
            group='common' if k in old and k in individual else 'removed_loss' if k in old and p<0 else 'removed_winner' if k in old and p>0 else 'removed_flat' if k in old else 'new_loss' if value<0 else 'new_winner' if value>0 else 'new_flat'
            delta=value-p;groups[group]+=delta;group_counts[group]+=1;by_symbol[k[0]]+=delta
            rows.append(dict(origin=k,parent_net_bps=p,child_net_bps=value,delta_net_bps=delta,group=group))
        w=sorted((k for k,(s,t) in old.items() if s=='C' and t['net_bps']>0),key=lambda k:(-old[k][1]['net_bps'],k))
        retention={}
        for name,ks in [('all_winners',w),('large_winners_topdecile',w[:ceil(.1*len(w))])]:
            total=sum(old[k][1]['net_bps'] for k in ks);kept=sum(min(old[k][1]['net_bps'],max(0,individual[k]['net'])) if k in individual and individual[k]['state']=='C' else 0 for k in ks)
            retention[name]=dict(total_bps=total,kept_bps=kept,fraction=kept/total if total else None)
        oldnet=sum(t['net_bps'] if s=='C' else t['hypothetical_liquidation_net_mark_bps'] for s,t in old.values());delta=net-oldnet
        close(sum(groups.values()),delta,'COMPLETE_CONTRIBUTION')
        if label in ('C63','C69'):
            saved=read(OUT/per/('ACCOUNTING_'+label+'.json'))
            close(saved['bridges']['marked']['delta']['net_bps'],delta,'NATIVE_ACCOUNTING_DELTA')
        best=max(rows,key=lambda r:r['delta_net_bps'])
        details[label]=dict(groups=dict(groups),counts=dict(group_counts),by_symbol=dict(by_symbol),rows=rows,retention=retention,delta_net_bps=delta,largest_positive_origin=best,delta_without_largest_positive=delta-max(0,best['delta_net_bps']))
    return dict(counts=count,attribution=details)

def main():
    global INPUTS
    import argparse
    q=argparse.ArgumentParser();q.add_argument('--inputs',type=Path,required=True);q.add_argument('--output',type=Path);args=q.parse_args();INPUTS=args.inputs
    spec=read(OUT/'SPEC.json');ledger=read(OUT/'BUDGET.json');slot=ledger['c70_price_confirmation_successor_allocation']
    check(slot['completed']==slot['started']==slot['reserved']==2 and slot['failed']==slot['remaining']==0,'EXACT_FIRST_FULLS')
    check(ledger['cumulative_actual']==72 and ledger['cumulative_actual_evaluations']==128,'COMPLETE_HISTORY_COUNTS')
    for path,digest in spec['source_files_sha256'].items():check(sha(ROOT/path)==digest,'FROZEN_SOURCE:'+path)
    for name,digest in read(OUT/'EVIDENCE_HASHES.json').items():check(sha(OUT/name)==digest,'EVIDENCE:'+name)
    periods={}
    for per in ('DEV2025','SEEN2026'):
        check(sha(INPUTS/(per+'.json.gz'))==spec['input_packet_sha256'][per],'INPUT_HASH')
        receipt=read(OUT/per/'RECEIPT.json');attempt=read(OUT/per/'ATTEMPT.json');started=read(OUT/per/'EXECUTION_STARTED.json')
        check(spec['frozen_ns']<attempt['time_ns']<started['time_ns'],'PREOUTCOME_FREEZE')
        check(started['claim_commit']==started['remote_readback_sha']==receipt['claim_commit'],'REMOTE_CLAIM_READBACK')
        check(receipt['spec_sha256']==sha(OUT/'SPEC.json'),'SPEC_RECEIPT')
        for kind in ('raw','result'):check(receipt[kind+'_sha256']==sha(OUT/per/(kind.upper()+'.json.gz')),'RESULT_HASH')
        periods[per]=verify_period(per)
    output=dict(status='PASS_SAVED_SOURCE_ARITHMETIC',periods=periods,source_packets_checked=True,new_economic_replays=0,independent_statistical_evidence=False)
    if args.output:
        with args.output.open('x') as f:json.dump(output,f,sort_keys=True,indent=2)
    print(json.dumps({k:v for k,v in output.items() if k!='periods'},indent=2));print(json.dumps({per:x['counts'] for per,x in periods.items()}))
if __name__=='__main__':main()
