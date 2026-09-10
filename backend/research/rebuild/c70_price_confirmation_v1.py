"""One C70-local rescue-confirmation replacement, not an adopted strategy.

Keep C69, price>SMA5 and C63 strict range escape. Replace SMA5 slope with a
strict close above the high of the session BEFORE the signal candle's session.
No deferred entry, new signals, changed exits or future/partial daily levels.
"""
from math import fsum,isfinite
from unittest.mock import patch
from backend.research.rebuild import c63_daily_ema21_entry_v1 as daily
RULE_ID='C69_DAILY21_OR_SMA5_PRIOR_SESSION_HIGH_ESCAPE_V1'
VETO='DAILY21_VETO_WITHOUT_PRIOR_SESSION_HIGH_CONFIRMATION'
MISSING=daily.MISSING


def prior_session(bars,i):
    if type(i) is not int or not 0<=i<len(bars):raise ValueError('SIGNAL_INDEX')
    start=bars[i].open_ts//daily.DAY*daily.DAY
    selected=[(j,b) for j,b in enumerate(bars[:i+1]) if start-daily.DAY<=b.open_ts<start]
    if len(selected)!=6:return None
    if [b.open_ts for j,b in selected]!=[start-daily.DAY+k*daily.BAR for k in range(6)]:raise ValueError('PRIOR_DAY_GAP')
    return dict(open_ts=start-daily.DAY,available_at=start,high=max(b.high for j,b in selected),
        source_highs=[dict(index=j,open_ts=b.open_ts,high=b.high) for j,b in selected],
        rule='SESSION_BEFORE_SIGNAL_BAR_OPEN_DATE_NOT_SIGNAL_CLOSE_DATE')


def recovery_observation(original,obs,session):
    days=obs['daily_closes'];sma=previous=None
    if len(days)>=6:
        values=[d['close'] for d in days[-6:]]
        if any(type(x) not in (float,int) or not isfinite(x) or x<=0 for x in values):raise ValueError('SMA_SOURCE')
        if any(d['available_at']>obs['available_at'] for d in days[-6:]):raise ValueError('FUTURE_SMA')
        sma=fsum(values[-5:])/5;previous=fsum(values[:5])/5
    if session is not None:
        if session['available_at']>obs['available_at']:raise ValueError('FUTURE_PRIOR_DAY')
        if not isfinite(session['high']) or session['high']<=0:raise ValueError('PRIOR_DAY_PRICE')
    escape=original['range_context']['strict_escape']
    above=sma is not None and obs['signal_close']>sma
    above_high=session is not None and obs['signal_close']>session['high']
    confirmation=bool(obs['value'] is not None and above and escape and above_high)
    rescued=bool(original['eligible'] and not obs['eligible'] and confirmation)
    return dict(sma_period=5,sma=sma,previous_sma=previous,above_sma=above,
        nonfalling_sma=sma is not None and sma>=previous,slope_used_for_decision=False,
        strict_prior_squeeze_high_escape=escape,prior_session=session,above_prior_session_high=above_high,
        confirmation=confirmation,rescued=rescued,available_at=obs['available_at'],daily_witnesses=days[-6:])


def combine(original,obs,session):
    recovery=recovery_observation(original,obs,session)
    eligible=bool(original['eligible'] and (obs['eligible'] or recovery['rescued']))
    reason=original['reason'] if not original['eligible'] else None if eligible else MISSING if obs['value'] is None else VETO
    return dict(original,c63_eligible=original['eligible'],c63_reason=original['reason'],
                daily_context=obs,recovery_context=recovery,eligible=eligible,reason=reason)


def replay(rows,*,eval_start_ms,eval_end_ms,enabled=True):
    if type(enabled) is not bool:raise ValueError('ENABLED_BOOL')
    if not enabled:return daily.replay(rows,eval_start_ms=eval_start_ms,eval_end_ms=eval_end_ms)
    original=daily.parent.context
    def context(bars,signal,er_context):
        return combine(original(bars,signal,er_context),daily.observation(bars,signal['signal_index']),prior_session(bars,signal['signal_index']))
    with patch.object(daily.parent,'context',context):
        result=daily.parent.replay(rows,eval_start_ms=eval_start_ms,eval_end_ms=eval_end_ms)
    result['audit'].update(rule=RULE_ID,direct_parent='C70_LOCAL_SMA5_RESCUE',preserved_reference=daily.parent.RULE_ID,
        original_exit_unchanged=True,C63_signal_pool_unchanged=True,source_tip_replication=False,
        change_axis='SMA5_SLOPE_REPLACED_BY_PRIOR_SESSION_HIGH',formal_credit=0,
        rescued_signal_T=sum(e['er_context']['recovery_context']['rescued'] for e in result['events']))
    return result
