"""Verify saved prices, decisions, quantities, costs and daily marks. No replay."""
from collections import Counter
from math import fsum, isclose
import json
from backend.research.rebuild import c63_c70_trader_account_v1 as a

B,D=a.tm.BAR,a.tm.DAY


def close(x,y,label):
    if not isclose(x,y,rel_tol=1e-11,abs_tol=1e-7):raise AssertionError(label)


def independent_cost(cost,entry,stamp):
    funding=(stamp//(2*B)-entry//(2*B))*cost['funding_p95_per_settlement_bps']
    components=dict(fee_bps=cost['fee_bps'],spread_bps=cost['spread_bps'],impact_bps=cost['impact_bps'],
                    funding_bps=funding,slippage_bps=0.)
    components['frozen_floor_reserve_bps']=max(0.,20.-fsum(components.values()))
    return components


def daily(rows,j):
    groups={}
    for row in rows[:j+1]:groups.setdefault(row['bar_open_ts']//D,[]).append(row)
    days=[]
    for day,group in sorted(groups.items()):
        if len(group)==6 and [r['bar_open_ts'] for r in group]==[day*D+k*B for k in range(6)]:
            days.append(dict(open_ts=day*D,available_at=(day+1)*D,close=group[-1]['close']))
    return dict(available_at=rows[j]['bar_close_ts'],is_daily_close=rows[j]['bar_close_ts']%D==0,
                sma10=fsum(d['close'] for d in days[-10:])/10 if len(days)>=10 else None,witnesses=days[-10:])


def verify_campaign(raw, trace, rows, cost, end):
    ei=raw['entry_index'];entry=rows[ei]['open'];entry_ts=rows[ei]['bar_open_ts']
    assert raw['entry_price']==entry and raw['entry_ts']==entry_ts
    assert raw['assembled_qty']==1. and raw['original_protective_sl'] is None and raw['exchange_resident_stop'] is False
    qty=1.;runner=False;managed=False;count=0;pending=None;fills=[];last_held=ei-1
    for event in trace:
        j=event['index'];kind=event['kind'];row=rows[j]
        if kind=='ENTRY_NEXT_OPEN':
            assert j==ei and event['ts']==entry_ts and event['price']==entry
        elif kind=='HELD_CLOSE_OBSERVATION':
            assert j==last_held+1,'MISSING_HELD_OBSERVATION';last_held=j
            assert event['ts']==row['bar_close_ts'] and event['close']==row['close']
            obs=daily(rows,j);assert event['daily']==obs,'DAILY_CAUSAL_BINDING'
            assert all(x['available_at']<=event['ts'] for x in obs['witnesses'])
            momentum=row['close']-rows[j-14]['close'];close(event['momentum'],momentum,'NATIVE_MOMENTUM')
            if obs['is_daily_close'] and event['ts']>entry_ts:count+=1
            assert event['daily_count']==count and event['runner']==runner
            close(event['remaining_qty'],qty,'TRACE_REMAINING_QTY')
            reason='FIXED_FLOOR_CLOSE' if row['close']<=raw['fixed_floor'] else None
            if reason is None and runner and row['close']<=entry:reason='RUNNER_BREAKEVEN_CLOSE'
            if reason is None and not runner and momentum<=0:reason='MOMENTUM_NONPOSITIVE_CLOSE'
            first=obs['is_daily_close'] and count==3 and not managed
            assert event['first_management']==first
            if first:managed=True
            parts=independent_cost(cost,entry_ts,event['ts'])
            net=(row['close']/entry-1)*10000-fsum(parts.values())
            close(event['net_progress_bps'],net,'PROFIT_CONDITION_COST')
            if reason is None and runner and obs['is_daily_close']:
                if obs['sma10'] is None:reason='RUNNER_DAILY_HISTORY_SAFETY_CLOSE'
                elif row['close']<obs['sma10']:reason='RUNNER_SMA10_CLOSE'
            pending=None
            if reason:pending=dict(action='FINAL',reason=reason,signal_index=j,signal_ts=event['ts'])
            elif first and net>0:
                pending=dict(action='PARTIAL',reason='D3_PROFIT',signal_index=j,signal_ts=event['ts'])
                if obs['sma10'] is None or row['close']<obs['sma10']:pending['exit_remainder']='D3_SMA10_SAFETY_CLOSE'
            assert event['pending']==pending,'SOURCE_DECISION_CONFORMANCE'
        elif kind in ('PARTIAL_FILL','FINAL_FILL'):
            assert pending is not None and event['decision']==pending
            assert j==pending['signal_index']+1 and row['bar_open_ts']==pending['signal_ts']
            assert event['ts']==row['bar_open_ts']<end and event['price']==row['open'],'OBSERVABLE_NEXT_OPEN'
            if kind=='PARTIAL_FILL':
                assert pending['action']=='PARTIAL' and not runner and not event['slot_released']
                close(event['qty'],1/3,'PARTIAL_QTY');qty-=1/3;runner=True
                fills.append(dict(status='C',qty=1/3,index=j,ts=event['ts'],price=row['open'],reason='D3_PROFIT_PARTIAL_NEXT_OPEN'))
                if not pending.get('exit_remainder'):pending=None
            else:
                assert pending['action']=='FINAL' or pending.get('exit_remainder')
                reason=pending.get('exit_remainder',pending['reason'])+'_NEXT_OPEN'
                fills.append(dict(status='C',qty=qty,index=j,ts=event['ts'],price=row['open'],reason=reason))
                qty=0.;assert event['slot_released'];pending=None
        elif kind=='TERMINAL_MARK':
            assert event['ts']==row['bar_close_ts']==end and event['price']==row['close']
            assert not event['slot_released'];close(event['remaining_qty'],qty,'TERMINAL_QTY')
            fills.append(dict(status='O',qty=qty,index=j,ts=end,price=row['close'],reason='TERMINAL_MARK'))
        else:raise AssertionError('UNKNOWN_TRACE_EVENT')
    assert raw['tm_legs']==fills,'ALL_LEGS_FROM_CAUSAL_TRACE'
    close(fsum(x['qty'] for x in fills),1.,'QUANTITY_CONSERVATION')
    close(raw['remaining_qty'],qty,'RESIDUAL_QTY')
    assert raw['partial_count']==sum(x['reason']=='D3_PROFIT_PARTIAL_NEXT_OPEN' for x in fills)
    return len(trace)


def verify_period(label,per,spec):
    folder=a.OUT/label/per;packet=a.gz(a.INPUTS/(per+'.json.gz'));cal=spec['periods'][per]
    raw=a.gz(folder/'RAW.json.gz');result=a.gz(folder/'RESULT.json.gz')
    positions={a.key(t):(status,t) for status,ts in [('C',result['trades']),('O',result['open_observations'])] for t in ts}
    expected_origins=set();trace_count=0
    ctrl=a.parents(per,packet,cal);parent=ctrl['C63' if label=='C63_TM' else 'C70_LOCAL']
    parent_events={a.key(x):x for x in ctrl['C63']['events']}
    assert {a.key(x) for x in result['events']}==set(parent_events),'UNCHANGED_SIGNAL_POOL'
    for symbol,rr in raw.items():
        rows=packet['rows_by'][symbol];last=-1;tail=False
        by={t['signal_index']:t for t in rr['trades']+rr['open_positions']}
        for event in rr['events']:
            k=(symbol,event['signal_index'],event['signal_ts']);i=event['signal_index'];old=parent_events[k]
            for name in ('signal_ts','signal_index','episode_start','floor','target','expiry'):
                assert event[name]==old[name],'ENTRY_SIGNAL_CHANGED:'+name
            if label=='C63_TM':assert event['er_context']==old['er_context'],'C63_ELIGIBILITY_CHANGED'
            else:
                bars=a.tm.native.to_bars(rows,cal['start_ms'],cal['runoff_end_ms'])
                expected=a.tm.c70_context(old['er_context'],a.tm.daily.observation(bars,i))
                assert event['er_context']==expected,'REG71_ELIGIBILITY_CHANGED'
            if tail or event['signal_ts']<=last:reason='ACTUAL_POSITION_OCCUPIED_AT_DECISION'
            elif event['expiry'] is not None and event['signal_ts']>=event['expiry']:reason='SETUP_EXPIRED_BEFORE_ENTRY'
            elif not event['er_context']['eligible']:reason=event['er_context']['reason']
            elif i+1>=len(rows) or rows[i+1]['bar_open_ts']>=cal['runoff_end_ms']:reason='NO_NEXT_OPEN_IN_APPROVED_WINDOW'
            elif rows[i+1]['open']<=event['floor'] or event['target'] is not None and rows[i+1]['open']>=event['target']:reason='GAP_INVALIDATES_FIXED_SETUP'
            else:reason=None
            assert event['admission']==(reason is None) and event['exclusion_reason']==reason,'FULL_OCCUPANCY_ADMISSION'
            if reason is not None:continue
            expected_origins.add(k);status,row=positions[k];bare=by[i]
            trace=[x for x in rr['trace'] if x['signal_index']==i]
            trace_count+=verify_campaign(bare,trace,rows,packet['costs'][symbol],cal['runoff_end_ms'])
            assert row['entry_ts']==bare['entry_ts'] and row['entry_price']==bare['entry_price']
            if status=='C':last=row['exit_ts']
            else:tail=True
            assert (status=='C')==(bare['remaining_qty']==0.)
            totals=dict.fromkeys(a.bridge.VALUE_FIELDS,0.)
            for leg,weighted in zip(bare['tm_legs'],row['weighted_legs'],strict=True):
                assert leg['qty']==weighted['qty']==weighted['numerator'] and weighted['denominator']==1.
                parts=independent_cost(packet['costs'][symbol],bare['entry_ts'],leg['ts']);cost=fsum(parts.values())
                gross=(leg['price']/bare['entry_price']-1)*10000
                vals=dict(gross_bps=gross,cost_bps=cost,net_bps=gross-cost,cost2x_net_bps=gross-2*cost,**parts)
                unit=a.bridge._values((weighted['status'],weighted['row']))
                for name,value in vals.items():
                    close(unit[name],value,'LEG_MONEY:'+name);totals[name]+=value*leg['qty']
            aggregate=a.bridge._values((status,row))
            for name,value in totals.items():close(aggregate[name],value,'CAMPAIGN_MONEY:'+name)
    assert expected_origins==set(positions),'CAMPAIGN_COVERAGE'
    # Existing independently implemented daily cash-flow engine; no signal replay.
    recalculated=a.metrics(result,packet,cal)
    assert recalculated==result['metrics'],'METRIC_AND_DAILY_MARK_RECONCILIATION'
    decomposition=a.decomposition(parent,result)
    assert decomposition==a.read(folder/'DECOMPOSITION.json'),'DECOMPOSITION_SAVED_PARITY'
    return dict(status='PASS',campaigns=len(positions),trace_events=trace_count,source_conformance='PASS',
                terminal_net_bps=result['metrics']['terminal_net_bps'],decomposition_residual_bps=decomposition['residual_bps'])


def verify():
    spec=a.read(a.OUT/'SPEC.json')
    for name,digest in spec['source_files_sha256'].items():assert a.h(a.ROOT/name)==digest,'FROZEN_CODE:'+name
    for name,digest in spec['preserved_files_sha256'].items():assert a.h(a.ROOT/name)==digest,'PRESERVED:'+name
    for per,digest in spec['input_packet_sha256'].items():assert a.h(a.INPUTS/(per+'.json.gz'))==digest,'INPUT_HASH'
    if (a.OUT/'EVIDENCE_HASHES.json').exists():
        for name,digest in a.read(a.OUT/'EVIDENCE_HASHES.json').items():assert a.h(a.OUT/name)==digest,'EVIDENCE_HASH:'+name
    results={label:{per:verify_period(label,per,spec) for per in a.PERIODS} for label in ('C63_TM','C70_TM')}
    b=a.read(a.OUT/'BUDGET.json');q=b['c63_c70_tm_allocation']
    assert q['completed']==q['started']==q['reserved']==4 and q['failed']==0 and q['remaining']==0
    assert (b['cumulative_actual'],b['cumulative_actual_evaluations'])==(81,146)
    prior=a.read(a.OUT/'HISTORY_PRIOR.json')
    assert b['candidate_trials'][:len(prior['candidate_trials'])]==prior['candidate_trials']
    assert b['trials'][:len(prior['trials'])]==prior['trials']
    return dict(status='PASS_SAVED_ONLY',periods=results,economic_replays=0,history_preserved=True)


if __name__=='__main__':print(json.dumps(verify(),indent=2))
