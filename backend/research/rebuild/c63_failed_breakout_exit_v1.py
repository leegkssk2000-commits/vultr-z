"""C63 entry preserved; one completed-close failed-breakout exit.

No indicator, outcome label, sizing, source I/O, or exchange-resident stop.
One serial replay owner only: inherited scoped hooks are always restored.
"""
from copy import deepcopy
from math import isfinite
from unittest.mock import patch
from backend.research.rebuild import m1_er_range_rescue_v1 as parent

engine=parent.er.parent
BAR=engine.BAR
RULE_ID='C63_FIXED_RANGE_RETURN_NONPOSITIVE_EXIT_V1'
REASON='FAILED_BREAKOUT_NONPOSITIVE_CLOSE'


def observed_cost(entry_ts, stamp, cost_model):
    from backend.research.rebuild.kr3_profit_zone_exit_v1 import decision_cost
    return decision_cost(entry_ts,stamp,cost_model)['cost_bps']


def predicate(*,escaped,close,upper,net_mark):
    if type(escaped) is not bool:raise ValueError('ESCAPED_BOOL')
    if any(type(x) not in (int,float) or not isfinite(x) for x in (close,upper,net_mark)):
        raise ValueError('NONFINITE_FAILED_BREAKOUT')
    if close<=0 or upper<=0:raise ValueError('NONPOSITIVE_PRICE')
    return escaped and close<upper and net_mark<=0


def position(bars,signal,variant,features,end,cost_model,original_path,original_exit):
    if variant!='M1':raise ValueError('C63_EXIT_VARIANT')
    i=signal['signal_index'];start=signal['episode_start'];entry=bars[i+1]
    if not 0<=start<i<len(bars)-1:raise ValueError('C63_RANGE_CLOCK')
    upper=max(b.high for b in bars[start:i]);escaped=bars[i].close>upper
    observations=[]
    def decide(v,close,floor,target,momentum,held):
        stamp=entry.open_ts+held*BAR
        cost=observed_cost(entry.open_ts,stamp,cost_model)
        net=(close/entry.open-1.)*10000-cost
        native=original_exit(v,close,floor,target,momentum,held)
        met=predicate(escaped=escaped,close=close,upper=upper,net_mark=net)
        reason=native if native is not None else REASON if met else None
        observations.append(dict(kind='FAILED_BREAKOUT_OBSERVATION',signal_index=i,
            index=i+held,ts=stamp,held_bars=held,close=close,fixed_upper=upper,
            entry_breakout=escaped,cost_bps=cost,net_mark_bps=net,
            native_reason=native,predicate=met,selected_reason=reason))
        return reason
    with patch.object(engine,'exit_reason',decide):
        trade,opened,trace=original_path(bars,signal,variant,features,end)
    raw=trade if trade is not None else opened
    raw.update(failed_breakout_upper=upper,entry_broke_prior_range=escaped,
        failed_breakout_source_start=start,failed_breakout_source_end=i-1,
        failed_breakout_source_available_at=bars[i-1].open_ts+BAR)
    return trade,opened,trace+observations


def replay(rows,*,eval_start_ms,eval_end_ms,cost_model,enabled=True,fixed_signal_indices=None):
    if type(enabled) is not bool:raise ValueError('C63_EXIT_ENABLED_BOOL')
    if not enabled:
        if fixed_signal_indices is not None:raise ValueError('DISABLED_FIXED_UNSUPPORTED')
        return parent.replay(rows,eval_start_ms=eval_start_ms,eval_end_ms=eval_end_ms)
    original_path,original_exit,original_setups=engine._position,engine.exit_reason,engine.m1_setups
    fixed=None if fixed_signal_indices is None else set(fixed_signal_indices)
    if fixed is not None and len(fixed)!=len(fixed_signal_indices):raise ValueError('DUPLICATE_FIXED_ORIGINS')
    def path(b,s,v,f,e):return position(b,s,v,f,e,deepcopy(cost_model),original_path,original_exit)
    def setups(bars):
        signals,log,features=original_setups(bars)
        if fixed is not None:
            if not fixed<={s['signal_index'] for s in signals}:raise ValueError('UNKNOWN_FIXED_ORIGIN')
            signals=[s for s in signals if s['signal_index'] in fixed]
        return signals,log,features
    with patch.object(engine,'_position',path),patch.object(engine,'m1_setups',setups):
        result=parent.replay(rows,eval_start_ms=eval_start_ms,eval_end_ms=eval_end_ms)
    if fixed is not None:
        actual={x['signal_index'] for k in ('trades','open_positions') for x in result[k]}
        if actual!=fixed:raise RuntimeError('FIXED_ENTRY_PARITY')
    result['audit'].update(rule=RULE_ID,direct_parent=parent.RULE_ID,
        comparison_mode='FULL_CHRONOLOGICAL' if fixed is None else 'FIXED_C63_ADMITTED_ORIGINS',
        change_axis='EXIT_ONLY_FIXED_RANGE_RETURN_NONPOSITIVE',original_M1_exits_unchanged=False,
        original_exit_unchanged=False,original_exit_priority_preserved=True,
        C63_signal_predicate_unchanged=True,exchange_resident_stop=False,
        extra_exit_T=sum(t['exit_reason']==REASON+'_NEXT_OPEN' for t in result['trades']))
    return result
