"""One entry-only Squeeze M1 child. Price path efficiency rises at release.

No I/O, volume features, outcome labels, sizing or extra exit rules. Existing
M1 signal generator and position path are reused; full actual slots replayed.
"""
from copy import deepcopy
from math import fsum, isfinite
from backend.research.rebuild import chart_mechanism_execution_v1 as parent

BAR=parent.BAR
RULE_ID='SQUEEZE_M1_ER14_INCREASE_AFTER_PR1231_V1'
LENGTH=14
VETO='ER14_NOT_INCREASING'


def er_observation(closes, i):
    """N changes = N+1 completed closes. Missing is not a zero ER."""
    if type(i) is not int or i < 0 or i >= len(closes):
        raise ValueError('ER_INDEX')
    if i < LENGTH:
        return None
    x=closes[i-LENGTH:i+1]
    if any(type(v) not in (float,int) or not isfinite(v) or v <= 0 for v in x):
        raise ValueError('INVALID_ER_PRICE')
    displacement=abs(x[-1]-x[0])
    path=fsum(abs(b-a) for a,b in zip(x,x[1:]))
    return dict(displacement=displacement,path_length=path,
                value=displacement/path if path>0 else 0.,start_index=i-LENGTH,end_index=i)


def context(bars, i):
    # 16 closes cover BOTH adjacent 14-change windows; no later value is read.
    closes=[b.close for b in bars[:i+1]]
    now=er_observation(closes,i)
    prior=er_observation(closes,i-1) if i>0 else None
    eligible=now is not None and prior is not None and now['value']>prior['value']
    return dict(signal_index=i,available_at=bars[i].open_ts+BAR,
                previous_available_at=bars[i-1].open_ts+BAR if i else None,
                current=now,previous=prior,eligible=eligible,
                source_closes=[dict(index=j,ts=bars[j].open_ts+BAR,close=bars[j].close) for j in range(max(0,i-LENGTH-1),i+1)],
                reason=None if eligible else 'ER14_HISTORY_UNAVAILABLE' if now is None or prior is None else VETO)


def replay(rows, *, eval_start_ms, eval_end_ms, enabled=True):
    if type(enabled) is not bool:
        raise ValueError('ER_ENABLED_BOOL')
    if not enabled:
        return parent.replay_independent(rows,eval_start_ms=eval_start_ms,eval_end_ms=eval_end_ms,variant='M1')
    bars=parent.to_bars(rows,eval_start_ms,eval_end_ms)
    original,setup_log,features=parent.m1_setups(bars)
    signals=[s for s in original if eval_start_ms<=s['signal_ts']<=eval_end_ms]
    result=dict(trades=[],open_positions=[],events=[],trace=[],setup_events=setup_log,pending_entries=[])
    last_exit,tail=-1,False
    for signal in signals:
        i=signal['signal_index'];ei=i+1
        obs=context(bars,i)
        event=dict(deepcopy(signal),admission=False,status='EXCLUDED',exclusion_reason=None,er_context=obs)
        # Preserve parent decision-time occupancy and window/cancellation rules.
        if tail or signal['signal_ts']<=last_exit:
            event['exclusion_reason']='ACTUAL_POSITION_OCCUPIED_AT_DECISION'
        elif signal['expiry'] is not None and signal['signal_ts']>=signal['expiry']:
            event['exclusion_reason']='SETUP_EXPIRED_BEFORE_ENTRY'
        elif not obs['eligible']:
            event['exclusion_reason']=obs['reason']
        elif ei>=len(bars) or bars[ei].open_ts>=eval_end_ms:
            event['exclusion_reason']='NO_NEXT_OPEN_IN_APPROVED_WINDOW';result['pending_entries'].append(deepcopy(event))
        elif bars[ei].open<=signal['floor'] or (signal['target'] is not None and bars[ei].open>=signal['target']):
            event['exclusion_reason']='GAP_INVALIDATES_FIXED_SETUP'
        else:
            trade,opened,trace=parent._position(bars,signal,'M1',features,eval_end_ms)
            event.update(admission=True,status='COMPLETED' if trade else 'CENSORED');result['trace'].extend(trace)
            if trade:
                result['trades'].append(trade);last_exit=trade['exit_ts']
            else:
                result['open_positions'].append(opened);tail=True
        result['events'].append(event)
    excluded=sum(e['status']=='EXCLUDED' for e in result['events'])
    if len(result['trades'])+len(result['open_positions'])+excluded!=len(signals):
        raise RuntimeError('ER_SIGNAL_ACCOUNTING')
    result['audit']=dict(rule=RULE_ID,direct_parent=parent.RULES['M1'],raw_signals=len(signals),
        completed=len(result['trades']),open=len(result['open_positions']),excluded=excluded,
        er_veto_T=sum(e['exclusion_reason']==VETO for e in result['events']),
        comparison_mode='FULL_CHRONOLOGICAL',same_symbol_max_positions=1,fresh_flat_start=True,
        new_exchange_orders=0,exit_model='COMPLETED_CLOSE_THEN_REAL_NEXT_OPEN',independent=False,formal_credit=0,
        source_setup_observations=len(setup_log),original_exit_unchanged=True,volume_used=False)
    return result
