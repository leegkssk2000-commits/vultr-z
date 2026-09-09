"""One C54 child: completed-close failure of its original whole pullback.

Research-only next-open intent, NOT an exchange resident protective SL.
Original C54 entry/reservations and C51 guard/exit priorities remain intact.
Only the pre-arm holding state gains a full-pullback-floor failure intent.
"""
from copy import deepcopy
from unittest.mock import patch
import math
from backend.research.rebuild import kr3_c51_entry_context_v1 as entry_parent
from backend.research.rebuild import kr3_profit_zone_exit_v1 as c51

kr3=c51.parent
m2,d=c51.m2,c51.d
BAR,HOLD=c51.BAR,c51.HOLD
UNCHECKED,SUPPRESSED,ALLOWED=c51.UNCHECKED,c51.SUPPRESSED,c51.ALLOWED
DECISION,TRIGGER,EXIT=c51.DECISION,c51.TRIGGER,c51.EXIT
GUARD_ARM,GUARD_UPDATE,GUARD_TRIGGER,GUARD_EXIT=c51.GUARD_ARM,c51.GUARD_UPDATE,c51.GUARD_TRIGGER,c51.GUARD_EXIT
ORIGINAL_C51_PATH=c51.path
decision_cost=c51.decision_cost
guard_observation=c51.guard_observation
RULE_ID='KR3_C54_ORIGINAL_PULLBACK_FLOOR_FAILURE_V1'
RULES={'B':RULE_ID}
FLOOR_TRIGGER='C54_ORIGINAL_PULLBACK_FLOOR_LOST_CLOSE'
FLOOR_EXIT='C54_ORIGINAL_PULLBACK_FLOOR_LOST_NEXT_OPEN'


def original_pullback_floor(rows, signal, ema20):
    """All observations fixed no later than original recovery signal close."""
    i=signal['signal_index']
    if type(i) is not int or not 0<=i<len(rows) or len(ema20)<i+1:
        raise ValueError('PULLBACK_ORIGIN_INDEX')
    q=i-1
    while q>=0 and float(rows[q]['close'])<=ema20[q]:q-=1
    if q<0 or q>=i-1:
        return dict(available=False,reason='NO_PREENTRY_PULLBACK',signal_index=i)
    source=[dict(index=j,bar_close_ts=rows[j]['bar_close_ts'],low=rows[j]['low']) for j in range(q+1,i+1)]
    if any(type(x['low']) not in (int,float) or not math.isfinite(x['low']) or x['low']<=0 for x in source):
        raise ValueError('PULLBACK_ORIGIN_LOW_INVALID')
    return dict(available=True,price=min(x['low'] for x in source),trend_index=q,
                start_index=q+1,end_index=i,available_at=rows[i]['bar_close_ts'],source=source)


def path(rows, signal, ema20, ema50, end, enabled, *, cost_model):
    if not enabled:
        return ORIGINAL_C51_PATH(rows, signal, ema20, ema50, end, True, cost_model=cost_model)
    i = signal['signal_index']; ei = i + 1; native_exit = i + HOLD
    floor_state = original_pullback_floor(rows, signal, ema20)
    signal_low = float(rows[i]['low'])
    entry_price = float(rows[ei]['open'])
    entry_ts = rows[ei]['bar_open_ts']
    extension = {'decided': False, 'allowed': False}
    final_exit = native_exit
    trace = [{'kind': 'ENTRY_NEXT_OPEN', 'signal_index': i, 'index': ei,
              'ts': entry_ts, 'price': rows[ei]['open'],
              'frozen_signal_low': signal_low, 'feature_available_ts': rows[i]['bar_close_ts'],
              'original_pullback_floor': deepcopy(floor_state)}]
    pending = None
    state = {'status': UNCHECKED}
    guard = dict(armed_index=None, armed_ts=None, protected_line=None,
                 last_index=None, exit_requested=False)
    for j in range(ei, min(i + 2 * HOLD, len(rows) - 1) + 1):
        row = rows[j]
        if j == final_exit:
            if row['bar_close_ts'] < end:
                raw = d._geometry(rows, i, j, end)
                trace.append({'kind': 'RUNNER_FINAL_TIME_STOP_CLOSE' if extension['allowed'] else 'ORIGINAL_TIME_STOP_CLOSE',
                              'signal_index': i, 'index': j, 'ts': raw['exit_ts'], 'price': raw['exit_price']})
                raw.update(low_exit_state=deepcopy(state), runner_extension=deepcopy(extension),
                           profit_zone_state=deepcopy(guard), original_pullback_floor=deepcopy(floor_state))
                return raw, None, trace
            break
        ema_hit = ema20[j] <= ema50[j]
        low_hit = float(row['close']) < signal_low
        if not ema_hit and state['status'] == UNCHECKED and low_hit:
            state = kr3.decide(state, row, j, signal_low, ema50[j])
            trace.append({'kind': m2.DECISION, 'signal_index': i, **deepcopy(state)})
        active_low = low_hit and state['status'] == ALLOWED
        runner_hit = extension['allowed'] and j >= native_exit and float(row['close']) <= ema20[j]
        guard_hit = False
        prior_line = guard['protected_line']
        if not (ema_hit or active_low or runner_hit):
            cost = decision_cost(entry_ts, row['bar_close_ts'], cost_model)
            before = guard
            guard, guard_hit = guard_observation(guard, row=row, index=j,
                ema20=ema20[j], ema50=ema50[j], entry_price=entry_price, cost=cost)
            if before['armed_index'] is None and guard['armed_index'] is not None:
                trace.append(dict(kind=GUARD_ARM, signal_index=i, index=j,
                    ts=row['bar_close_ts'], observed_close=row['close'], ema20=ema20[j],
                    ema50=ema50[j], entry_price=entry_price, protected_line=guard['protected_line'],
                    decision_cost=deepcopy(cost)))
            elif not guard_hit and guard['protected_line'] != before['protected_line']:
                trace.append(dict(kind=GUARD_UPDATE, signal_index=i, index=j,
                    ts=row['bar_close_ts'], prior_protected_line=prior_line,
                    protected_line=guard['protected_line'], ema20=ema20[j]))
        floor_hit = (not (ema_hit or active_low or runner_hit or guard_hit)
                     and guard['armed_index'] is None and floor_state['available']
                     and float(row['close']) < floor_state['price'])
        if not (ema_hit or active_low or runner_hit or guard_hit or floor_hit):
            if j == native_exit - 1:
                allowed = state['status'] != SUPPRESSED and float(row['close']) > entry_price and float(row['close']) > ema20[j] > ema50[j]
                extension = {'decided': True, 'allowed': allowed, 'index': j,
                    'ts': row['bar_close_ts'], 'observed_close': row['close'],
                    'entry_price': entry_price, 'ema20': ema20[j], 'ema50': ema50[j],
                    'm2_state_at_decision': state['status']}
                trace.append({'kind': DECISION, 'signal_index': i, **deepcopy(extension)})
                if allowed:
                    final_exit = i + 2 * HOLD
            continue
        pending = {'signal_ts': row['bar_close_ts'], 'signal_index': j,
                   'ema20': ema20[j], 'ema50': ema50[j],
                   'signal_low': signal_low, 'observed_close': row['close'],
                   'low_condition': low_hit, 'ema_condition': ema_hit, 'runner_condition': runner_hit}
        if guard_hit:
            pending.update(profit_zone_condition=True, prior_protected_line=prior_line,
                           armed_index=guard['armed_index'], armed_ts=guard['armed_ts'])
        if floor_hit:
            pending.update(original_pullback_floor_condition=True,
                           original_pullback_floor=deepcopy(floor_state))
        reason = 'EMA20_NOT_ABOVE_EMA50_NEXT_OPEN' if ema_hit else m2.EXIT if active_low else EXIT if runner_hit else GUARD_EXIT if guard_hit else FLOOR_EXIT
        kind = 'TREND_INVALIDATION_CLOSE' if ema_hit else m2.TRIGGER if active_low else TRIGGER if runner_hit else GUARD_TRIGGER if guard_hit else FLOOR_TRIGGER
        trace.append({'kind': kind, 'signal_index': i, 'index': j,
                      'ts': row['bar_close_ts'], **pending})
        trace[-1]['signal_index'] = i
        xi = j + 1
        if xi >= len(rows) or rows[xi]['bar_open_ts'] >= end:
            break
        raw = d._geometry(rows, i, j, end)
        price = float(rows[xi]['open'])
        gross = (price / raw['entry_price'] - 1.) * 10000.
        raw.update(exit_index=xi, exit_ts=rows[xi]['bar_open_ts'], exit_price=price,
                   gross_bps=gross, hold_ms=rows[xi]['bar_open_ts'] - raw['entry_ts'],
                   mfe_bps=max(raw['mfe_bps'], gross, 0.), mae_bps=min(raw['mae_bps'], gross, 0.),
                   exit_reason=reason, exit_timestamp_semantics='OBSERVED_4H_OPEN',
                   excursion_semantics='HELD_COMPLETE_BARS_PLUS_EXIT_OPEN_ONLY',
                   exit_trigger=deepcopy(pending), frozen_signal_low=signal_low,
                   low_exit_state=deepcopy(state), runner_extension=deepcopy(extension),
                   profit_zone_state=deepcopy(guard), original_pullback_floor=deepcopy(floor_state))
        trace.append({'kind': reason, 'signal_index': i, 'index': xi,
                      'ts': raw['exit_ts'], 'price': price})
        return raw, None, trace
    raw = d._geometry(rows, i, len(rows)-1, end)
    for a, b in (('exit_index','mark_index'), ('exit_ts','mark_ts'),
                 ('exit_price','mark_price'), ('gross_bps','gross_mark_bps')):
        raw[b] = raw.pop(a)
    raw.update(status='CENSORED', terminal_liquidation=False, native_hold_bars=HOLD,
        native_planned_exit_ts=rows[ei]['bar_open_ts'] + HOLD*BAR,
        original_protective_sl=None,
        native_geometry_scope='FROZEN_V2_FIXED_HOLD_NO_NATIVE_SL_SPECIFIED',
        censor_reason='ORIGINAL_STRICT_END_TIMEOUT_AT_BOUNDARY' if final_exit==len(rows)-1 else 'NATIVE_HOLD_UNFINISHED',
        pending_exit_signal_ts=pending['signal_ts'] if pending else None,
        pending_exit_trigger=deepcopy(pending), frozen_signal_low=signal_low,
        low_exit_state=deepcopy(state), runner_extension=deepcopy(extension),
        runner_planned_exit_index=final_exit, profit_zone_state=deepcopy(guard), original_pullback_floor=deepcopy(floor_state))
    trace.append({'kind':'TERMINAL_MARK', 'signal_index':i, 'index':raw['mark_index'],
        'ts':raw['mark_ts'], 'price':raw['mark_price'], 'censor_reason':raw['censor_reason'],
        'pending_exit_signal_ts':raw['pending_exit_signal_ts']})
    return None, raw, trace


def replay(rows,bundle,*,eval_start_ms,eval_end_ms,cost_model,mode='B',enabled=True,reference_checkpoint=None):
    if mode!='B' or type(enabled) is not bool:raise ValueError('PULLBACK_FAILURE_MODE')
    kw=dict(eval_start_ms=eval_start_ms,eval_end_ms=eval_end_ms,cost_model=cost_model,mode='B',reference_checkpoint=reference_checkpoint)
    if not enabled:return entry_parent.replay(rows,bundle,**kw)
    with patch.object(c51,'path',path):
        result=entry_parent.replay(rows,bundle,**kw)
    result['audit'].update(rule=RULE_ID,direct_parent=entry_parent.RULES['B'],
        original_C51_exit_unchanged=False,C51_original_rules_preserved=True,
        change_axis='PREARM_WHOLE_PULLBACK_FAILURE',C54_entry_unchanged=True,
        initial_protective_sl_added=False,
        pullback_floor_exits=sum(t['kind']==FLOOR_EXIT for t in result['trace']))
    return result
