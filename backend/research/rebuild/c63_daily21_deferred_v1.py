"""A finite pending-entry adaptation of the public daily21 direction condition.

C63 signals/floor/cost model are not changed. A valid but below-daily21 signal
may wait, not trade, until its first completed-close confirmation. Pending
lifetime and later holding share the ORIGINAL 20-bar clock. No orders or I/O.
"""
from copy import deepcopy
from unittest.mock import patch
from backend.research.rebuild import c63_daily_ema21_entry_v1 as daily

parent=daily.parent
er=parent.er
engine=er.parent
BAR=engine.BAR
RULE_ID='C63_DAILY21_DEFERRED_RECLAIM_V1'


def deferred_position(bars,signal,decision,features,end):
    """Reuse native price/exit path, advancing its time clock by waiting bars."""
    origin=signal['signal_index'];delay=decision-origin
    if delay<0:raise ValueError('NEGATIVE_ENTRY_DELAY')
    executable=deepcopy(signal)
    executable.update(signal_index=decision,signal_ts=bars[decision].open_ts+BAR)
    native=engine.exit_reason
    def reason(variant,close,floor,target,momentum,held):
        return native(variant,close,floor,target,momentum,held+delay)
    with patch.object(engine,'exit_reason',reason):
        trade,opened,trace=engine._position(bars,executable,'M1',features,end)
    for row in (trade,opened):
        if row is not None:
            row.update(signal_index=origin,signal_ts=signal['signal_ts'],
                decision_index=decision,decision_ts=executable['signal_ts'],wait_bars=delay,
                original_clock_end_index=origin+20,entry_clock_reset=False)
    for row in trace:
        row.update(signal_index=origin,decision_index=decision)
        if 'held_bars' in row:row['original_clock_bars']=row['held_bars']+delay
    return trade,opened,trace


def replay(rows,*,eval_start_ms,eval_end_ms):
    bars=engine.to_bars(rows,eval_start_ms,eval_end_ms)
    all_signals,setup_log,features=engine.m1_setups(bars)
    signals=[s for s in all_signals if eval_start_ms<=s['signal_ts']<=eval_end_ms]
    result=dict(trades=[],open_positions=[],events=[],trace=[],setup_events=setup_log,pending_entries=[])
    last_exit,tail=-1,False
    for n,signal in enumerate(signals):
        i=signal['signal_index'];obs=parent.context(bars,signal,er.context)
        day=daily.observation(bars,i)
        event=dict(deepcopy(signal),admission=False,status='EXCLUDED',exclusion_reason=None,
            er_context=obs,initial_daily_context=day,pending_observations=[],decision_index=None,
            decision_ts=None,wait_bars=0)
        decision=None
        if tail or signal['signal_ts']<=last_exit:
            event['exclusion_reason']='ACTUAL_POSITION_OCCUPIED_AT_DECISION'
        elif signal['expiry'] is not None and signal['signal_ts']>=signal['expiry']:
            event['exclusion_reason']='SETUP_EXPIRED_BEFORE_ENTRY'
        elif not obs['eligible']:
            event['exclusion_reason']=obs['reason']
        elif day['value'] is None:
            event['exclusion_reason']=daily.MISSING
        elif day['eligible']:
            decision=i
        elif i+1>=len(bars) or bars[i+1].open_ts>=eval_end_ms:
            event['exclusion_reason']='PENDING_RECLAIM_OUTSIDE_WINDOW'
            result['pending_entries'].append(deepcopy(event))
        elif bars[i+1].open<=signal['floor']:
            # Native original entry gap invalidates setup; waiting cannot bypass it.
            event['exclusion_reason']='GAP_INVALIDATES_FIXED_SETUP'
        else:
            next_signal=signals[n+1]['signal_index'] if n+1<len(signals) else None
            for j in range(i+1,len(bars)):
                stamp=bars[j].open_ts+BAR
                reason=engine.exit_reason('M1',bars[j].close,signal['floor'],None,features[j]['momentum'],j-i)
                if next_signal is not None and j==next_signal:
                    reason='REPLACED_BY_NEW_NATIVE_SIGNAL'
                record=dict(index=j,available_at=stamp,close=bars[j].close,
                    momentum=features[j]['momentum'],original_clock_bars=j-i,invalidation=reason)
                event['pending_observations'].append(record)
                if reason is not None:
                    event['exclusion_reason']='PENDING_CANCEL_'+reason;break
                current=daily.observation(bars,j);record['daily_context']=current
                if current['value'] is None:
                    raise RuntimeError('DAILY_HISTORY_DISAPPEARED')
                if current['eligible']:
                    decision=j;event['reclaim_daily_context']=current;break
            if decision is None and event['exclusion_reason'] is None:
                event['exclusion_reason']='PENDING_RECLAIM_OUTSIDE_WINDOW'
                result['pending_entries'].append(deepcopy(event))
        if decision is not None:
            ei=decision+1;event.update(decision_index=decision,decision_ts=bars[decision].open_ts+BAR,wait_bars=decision-i)
            if ei>=len(bars) or bars[ei].open_ts>=eval_end_ms:
                event['exclusion_reason']='NO_NEXT_OPEN_IN_APPROVED_WINDOW'
                result['pending_entries'].append(deepcopy(event))
            elif bars[ei].open<=signal['floor'] or (signal['target'] is not None and bars[ei].open>=signal['target']):
                event['exclusion_reason']='GAP_INVALIDATES_FIXED_SETUP'
            else:
                trade,opened,trace=deferred_position(bars,signal,decision,features,eval_end_ms)
                event.update(admission=True,status='COMPLETED' if trade else 'CENSORED')
                result['trace'].extend(trace)
                if trade:result['trades'].append(trade);last_exit=trade['exit_ts']
                else:result['open_positions'].append(opened);tail=True
        result['events'].append(event)
    excluded=sum(e['status']=='EXCLUDED' for e in result['events'])
    if len(result['trades'])+len(result['open_positions'])+excluded!=len(signals):
        raise RuntimeError('ORIGINAL_SIGNAL_COVERAGE')
    result['audit']=dict(rule=RULE_ID,direct_parent=parent.RULE_ID,diagnostic_comparator=daily.RULE_ID,
        raw_signals=len(signals),completed=len(result['trades']),open=len(result['open_positions']),excluded=excluded,
        deferred_admitted_T=sum(e['admission'] and e['wait_bars']>0 for e in result['events']),
        immediate_admitted_T=sum(e['admission'] and e['wait_bars']==0 for e in result['events']),
        comparison_mode='FULL_CHRONOLOGICAL',same_symbol_max_positions=1,fresh_flat_start=True,
        original_clock_preserved=True,original_signal_pool_preserved=True,entry_clock_reset=False,
        source_setup_observations=len(setup_log),original_exit_price_rules_unchanged=True,
        new_exchange_orders=0,independent=False,formal_credit=0,source_tip_replication=False,volume_used=False)
    return result
