"""One causal rescue of M1 ER-vetoed range breaks, not outcome-selected trades.

Preserve original M1 setups/next-open fills/exits and C62 ER arithmetic. The
strict prior squeeze-high escape can override only an available nonincreasing
ER, never unavailable history or execution safety. No I/O or live authority.
"""
from copy import deepcopy
from math import isfinite
from unittest.mock import patch
from backend.research.rebuild import m1_er14_entry_v1 as er

BAR=er.BAR
RULE_ID='SQUEEZE_M1_ER_OR_PRIOR_RANGE_ESCAPE_V1'


def context(bars, signal, original_er_context):
    i=signal['signal_index'];start=signal['episode_start']
    if type(i) is not int or type(start) is not int or not 0<=start<i<len(bars):
        raise ValueError('RANGE_EPISODE_INDEX')
    if signal['signal_ts']!=bars[i].open_ts+BAR:
        raise ValueError('RANGE_SIGNAL_CLOCK')
    prefix=bars[start:i]
    values=[b.high for b in prefix]+[bars[i].close]
    if any(type(x) not in (float,int) or not isfinite(x) or x<=0 for x in values):
        raise ValueError('RANGE_SOURCE_PRICE')
    high=max(b.high for b in prefix)
    original=deepcopy(original_er_context(bars,i))
    available=original['current'] is not None and original['previous'] is not None
    escape=bars[i].close>high
    rescued=available and not original['eligible'] and escape
    original.update(er_increase=original['eligible'],eligible=original['eligible'] or rescued,
        reason=None if original['eligible'] or rescued else original['reason'],
        range_context=dict(episode_start=start,episode_end=i-1,prior_high=high,
            signal_close=bars[i].close,strict_escape=escape,rescued=rescued,
            available_at=bars[i].open_ts+BAR,prior_available_at=bars[i-1].open_ts+BAR,
            source_highs=[dict(index=j,ts=bars[j].open_ts+BAR,high=bars[j].high) for j in range(start,i)]))
    return original


def replay(rows,*,eval_start_ms,eval_end_ms,enabled=True):
    if type(enabled) is not bool:raise ValueError('RANGE_ENABLED_BOOL')
    if not enabled:
        return er.replay(rows,eval_start_ms=eval_start_ms,eval_end_ms=eval_end_ms,enabled=False)
    original_context=er.context;original_setups=er.parent.m1_setups;signals={}
    def observe_setups(bars):
        result=original_setups(bars)
        signals.update({s['signal_index']:s for s in result[0]})
        return result
    def observe_context(bars,i):return context(bars,signals[i],original_context)
    with patch.object(er.parent,'m1_setups',observe_setups),patch.object(er,'context',observe_context):
        result=er.replay(rows,eval_start_ms=eval_start_ms,eval_end_ms=eval_end_ms)
    result['audit'].update(rule=RULE_ID,direct_parent=er.parent.RULES['M1'],
        diagnostic_comparator=er.RULE_ID,change_axis='AVAILABLE_ER_OR_PRE_RELEASE_RANGE_ESCAPE',
        range_rescue_signal_T=sum(e['er_context']['range_context']['rescued'] for e in result['events']),
        range_rescue_admitted_T=sum(e['admission'] and e['er_context']['range_context']['rescued'] for e in result['events']),
        original_M1_exits_unchanged=True,volume_used=False)
    return result
