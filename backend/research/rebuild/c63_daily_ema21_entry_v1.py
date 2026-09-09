"""One public trader-tip adaptation: C63 close must be above completed-day EMA21.

Native four-hour signals/fills/exits/costs unchanged. The EMA uses only complete
UTC days already available at the signal, no live partial-day estimate. No I/O.
"""
from unittest.mock import patch
from backend.research.rebuild import m1_er_range_rescue_v1 as parent
from backend.research.rebuild import chart_mechanism_features_v1 as f
BAR,DAY=f.BAR_MS,f.DAY_MS
PERIOD=21
RULE_ID='C63_COMPLETED_DAILY_EMA21_ENTRY_V1'
VETO='PRICE_NOT_ABOVE_COMPLETED_DAILY_EMA21'
MISSING='COMPLETED_DAILY_EMA21_HISTORY_UNAVAILABLE'


def observation(bars,i):
    if type(i) is not int or not 0<=i<len(bars):raise ValueError('DAILY_SIGNAL_INDEX')
    prefix=bars[:i+1];f.validate(prefix);stamp=prefix[-1].open_ts+BAR
    first=next((j for j,b in enumerate(prefix) if b.open_ts%DAY==0),len(prefix))
    days=f.completed_utc_days(prefix[first:],stamp) if first<len(prefix) else []
    values=f._average([d.close for d in days],PERIOD,2/(PERIOD+1))
    value=values[-1] if values else None
    good=value is not None and prefix[-1].close>value
    return dict(period=PERIOD,day_definition='UTC_00_TO_24_SIX_COMPLETE_NATIVE_4H_BARS',
        seed='SMA_FIRST21_COMPLETE_UTC_DAILY_CLOSES_THEN_ALPHA_2_OVER22',
        signal_index=i,available_at=stamp,leading_partial_bars=first,completed_days=len(days),
        last_daily_available_at=days[-1].open_ts+DAY if days else None,
        value=value,signal_close=prefix[-1].close,eligible=good,
        reason=None if good else MISSING if value is None else VETO,
        daily_closes=[dict(open_ts=d.open_ts,available_at=d.open_ts+DAY,close=d.close) for d in days])


def combine(original,obs):
    result=dict(original)
    result.update(c63_eligible=original['eligible'],c63_reason=original['reason'],daily_context=obs,
        eligible=original['eligible'] and obs['eligible'],
        reason=original['reason'] if not original['eligible'] else obs['reason'])
    return result


def replay(rows,*,eval_start_ms,eval_end_ms,enabled=True):
    if type(enabled) is not bool:raise ValueError('DAILY_ENABLED_BOOL')
    if not enabled:return parent.replay(rows,eval_start_ms=eval_start_ms,eval_end_ms=eval_end_ms)
    original=parent.context
    def context(bars,signal,er_context):
        return combine(original(bars,signal,er_context),observation(bars,signal['signal_index']))
    with patch.object(parent,'context',context):
        result=parent.replay(rows,eval_start_ms=eval_start_ms,eval_end_ms=eval_end_ms)
    result['audit'].update(rule=RULE_ID,direct_parent=parent.RULE_ID,change_axis='COMPLETED_DAILY_EMA21_ENTRY_ELIGIBILITY',
        original_exit_unchanged=True,C63_signal_pool_unchanged=True,source_tip_replication=False,
        daily_veto_T=sum(e['exclusion_reason']==VETO for e in result['events']),
        daily_history_unavailable_T=sum(e['exclusion_reason']==MISSING for e in result['events']))
    return result
