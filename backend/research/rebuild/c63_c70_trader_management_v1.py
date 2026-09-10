"""Frozen Qullamaggie management component on unchanged C63 / reg71 entries.

Pure DEV simulation; no I/O, orders, allocator or executable CLI. Unit position
quantity is split into lots, never into additional win-rate observations.
"""
from copy import deepcopy
from math import fsum
from unittest.mock import patch
from backend.research.rebuild import m1_er_range_rescue_v1 as c63
from backend.research.rebuild import c63_daily_ema21_entry_v1 as daily
from backend.research.rebuild import chart_mechanism_execution_v1 as native
from backend.research.rebuild import chart_mechanism_features_v1 as f

BAR, DAY = native.BAR, native.DAY
SCOPE = 'C63_C70_TRADER_PROFIT_LIFECYCLE_AFTER_PR1258_V1'
C70_RULE = 'C69_DAILY21_OR_NONFALLING_SMA5_STRICT_RANGE_ESCAPE_V1'
RULES = {'C63_TM': 'C63_QULLAMAGGIE_D3_THIRD_SMA10_V1',
         'C70_TM': 'C70_REG71_QULLAMAGGIE_D3_THIRD_SMA10_V1'}


def c70_context(original, obs):
    """Exact imported reg71 rule, independently verified by saved event export."""
    days = obs['daily_closes']
    sma = previous = None
    if len(days) >= 6:
        sma = fsum(d['close'] for d in days[-5:]) / 5
        previous = fsum(d['close'] for d in days[-6:-1]) / 5
    rescue = (obs['value'] is not None and sma is not None and
              obs['signal_close'] > sma and sma >= previous and
              original['range_context']['strict_escape'])
    eligible = bool(original['eligible'] and (obs['eligible'] or rescue))
    reason = original['reason'] if not original['eligible'] else None if eligible else (
        daily.MISSING if obs['value'] is None else 'DAILY21_VETO_WITHOUT_SMA5_RANGE_CONFIRMATION')
    return dict(original, eligible=eligible, reason=reason, daily_context=obs,
                reg71_context=dict(sma=sma, previous_sma=previous, rescue=bool(rescue),
                                   available_at=obs['available_at'], rule=C70_RULE))


def parent_replay(rows, *, parent, eval_start_ms, eval_end_ms):
    if parent not in ('C63', 'C70_LOCAL'):
        raise ValueError('EXACT_PARENT_REQUIRED')
    if parent == 'C63':
        return c63.replay(rows, eval_start_ms=eval_start_ms, eval_end_ms=eval_end_ms)
    original = c63.context
    def context(bars, signal, er_context):
        return c70_context(original(bars, signal, er_context),
                           daily.observation(bars, signal['signal_index']))
    with patch.object(c63, 'context', context):
        result = c63.replay(rows, eval_start_ms=eval_start_ms, eval_end_ms=eval_end_ms)
    result['audit']['rule'] = C70_RULE
    return result


def cost_at(cost, entry_ts, stamp):
    funding = (stamp // (2*BAR) - entry_ts // (2*BAR)) * cost['funding_p95_per_settlement_bps']
    return max(20., cost['fee_bps'] + cost['spread_bps'] + cost['impact_bps'] + funding)


def daily_observation(bars, i):
    """Only complete six-bar UTC sessions; no incomplete first or final day."""
    prefix = bars[:i+1]
    first = next((j for j,b in enumerate(prefix) if b.open_ts % DAY == 0), len(prefix))
    days = f.completed_utc_days(prefix[first:], bars[i].open_ts+BAR) if first < len(prefix) else []
    return dict(available_at=bars[i].open_ts+BAR,
                is_daily_close=(bars[i].open_ts+BAR) % DAY == 0,
                sma10=fsum(d.close for d in days[-10:])/10 if len(days)>=10 else None,
                witnesses=[dict(open_ts=d.open_ts, available_at=d.open_ts+DAY, close=d.close)
                           for d in days[-10:]])


def position(bars, signal, variant, features, end, cost):
    if variant != 'M1':
        raise ValueError('NATIVE_M1_ONLY')
    i = signal['signal_index']; ei = i+1; entry = bars[ei]
    legs = []; trace = []; qty = 1.; pending = None; managed = False; runner = False
    daily_count = 0; closed = False; final_reason = None; partial_count = 0
    trace.append(dict(kind='ENTRY_NEXT_OPEN', ts=entry.open_ts, index=ei, price=entry.open,
                      qty=1., floor=signal['floor'], signal_index=i))

    def leg(j, fraction, reason, status='C'):
        b = bars[j]; px = b.open if status=='C' else b.close
        stamp = b.open_ts if status=='C' else b.open_ts+BAR
        return dict(status=status, qty=fraction, index=j, ts=stamp, price=px, reason=reason)

    for j in range(ei, len(bars)):
        row = bars[j]
        # Execute the prior completed-close decision before inspecting this bar.
        if pending is not None and row.open_ts < end:
            if pending['action']=='PARTIAL':
                legs.append(leg(j, 1/3, 'D3_PROFIT_PARTIAL_NEXT_OPEN'))
                qty -= 1/3; runner = True; partial_count += 1
                trace.append(dict(kind='PARTIAL_FILL', ts=row.open_ts, index=j, price=row.open,
                                  qty=1/3, remaining_qty=qty, decision=deepcopy(pending),
                                  slot_released=False,signal_index=i))
                if pending.get('exit_remainder'):
                    final_reason = pending['exit_remainder']+'_NEXT_OPEN'
                    legs.append(leg(j, qty, final_reason)); qty=0.; closed=True
                    trace.append(dict(kind='FINAL_FILL',ts=row.open_ts,index=j,price=row.open,
                                      remaining_qty=0.,decision=deepcopy(pending),slot_released=True,signal_index=i))
                    break
            else:
                legs.append(leg(j, qty, pending['reason']+'_NEXT_OPEN'))
                qty = 0.; closed = True; final_reason = legs[-1]['reason']
                trace.append(dict(kind='FINAL_FILL', ts=row.open_ts, index=j, price=row.open,
                                  remaining_qty=0., decision=deepcopy(pending), slot_released=True,signal_index=i))
                break
            pending = None
        stamp = row.open_ts+BAR
        obs = daily_observation(bars, j)
        if obs['is_daily_close'] and stamp > entry.open_ts:
            daily_count += 1
        # Native floor remains close-confirmed/next-open, not an invented stop fill.
        reason = 'FIXED_FLOOR_CLOSE' if row.close <= signal['floor'] else None
        if reason is None and runner and row.close <= entry.open:
            reason = 'RUNNER_BREAKEVEN_CLOSE'
        if reason is None and not runner and features[j]['momentum'] <= 0:
            reason = 'MOMENTUM_NONPOSITIVE_CLOSE'
        first_management = obs['is_daily_close'] and daily_count == 3 and not managed
        net_progress = (row.close/entry.open-1)*10000 - cost_at(cost, entry.open_ts, stamp)
        if first_management:
            managed = True
        # A profitable D3 partial arms the source runner at its actual next-open fill.
        # Failed/no-profit campaigns keep the native momentum failure exit.
        if reason is None and runner and obs['is_daily_close']:
            if obs['sma10'] is None:
                reason = 'RUNNER_DAILY_HISTORY_SAFETY_CLOSE'
            elif row.close < obs['sma10']:
                reason = 'RUNNER_SMA10_CLOSE'
        if reason is not None:
            pending = dict(action='FINAL', reason=reason, signal_index=j, signal_ts=stamp)
        elif first_management and net_progress > 0:
            pending = dict(action='PARTIAL', reason='D3_PROFIT', signal_index=j, signal_ts=stamp)
            # Both orders derive from this same completed day, never fill-time data.
            if obs['sma10'] is None or row.close < obs['sma10']:
                pending['exit_remainder'] = 'D3_SMA10_SAFETY_CLOSE'
        trace.append(dict(kind='HELD_CLOSE_OBSERVATION', ts=stamp, index=j, close=row.close,
                          floor=signal['floor'], momentum=features[j]['momentum'],
                          held_bars=j-ei+1, daily_count=daily_count, first_management=first_management,
                          net_progress_bps=net_progress, runner=runner, remaining_qty=qty,
                          daily=obs, pending=deepcopy(pending), signal_index=i))
    if not closed:
        legs.append(leg(j, qty, 'TERMINAL_MARK', 'O'))
        trace.append(dict(kind='TERMINAL_MARK', ts=bars[j].open_ts+BAR, index=j,
                          price=bars[j].close, remaining_qty=qty, slot_released=False,signal_index=i))
    last = legs[-1]; held = bars[ei:j if closed else j+1]
    gross = fsum(l['qty']*(l['price']/entry.open-1)*10000 for l in legs)
    raw = dict(signal_index=i, signal_ts=signal['signal_ts'], entry_index=ei,
               entry_ts=entry.open_ts, entry_price=entry.open, side='long', hold_ms=last['ts']-entry.open_ts,
               mfe_bps=max([0., (last['price']/entry.open-1)*10000]+[(b.high/entry.open-1)*10000 for b in held]),
               mae_bps=min([0., (last['price']/entry.open-1)*10000]+[(b.low/entry.open-1)*10000 for b in held]),
               setup_id=signal['setup_id'], fixed_floor=signal['floor'], fixed_target=signal['target'],
               original_protective_sl=None, exchange_resident_stop=False,
               excursion_semantics='UNDERLYING_UNSCALED_PATH_NOT_WEIGHTED_CAMPAIGN_RETURN',
               tm_legs=legs, assembled_qty=1., remaining_qty=qty, partial_count=partial_count,
               runner_activated=runner, exit_trigger=deepcopy(pending))
    if closed:
        raw.update(exit_index=last['index'], exit_ts=last['ts'], exit_price=last['price'],
                   gross_bps=gross, exit_reason=final_reason, exit_timestamp_semantics='OBSERVED_4H_OPEN')
        return raw, None, trace
    raw.update(mark_index=last['index'], mark_ts=last['ts'], mark_price=last['price'],
               gross_mark_bps=gross, status='CENSORED', terminal_liquidation=False,
               censor_reason='PENDING_EXIT_OUTSIDE_WINDOW' if pending else 'HOLD_UNFINISHED',
               pending_exit_trigger=deepcopy(pending))
    return None, raw, trace


def replay(rows, *, parent, eval_start_ms, eval_end_ms, cost, enabled=True):
    if type(enabled) is not bool:
        raise ValueError('MANAGEMENT_ENABLED_BOOL')
    kwargs = dict(parent=parent, eval_start_ms=eval_start_ms, eval_end_ms=eval_end_ms)
    if not enabled:
        return parent_replay(rows, **kwargs)
    def managed(bars, signal, variant, features, end):
        return position(bars, signal, variant, features, end, cost)
    with patch.object(native, '_position', managed):
        result = parent_replay(rows, **kwargs)
    result['audit'].update(rule=RULES['C63_TM' if parent=='C63' else 'C70_TM'],
                           management=True, partial_releases_slot=False,
                           native_time20_replaced=True,
                           native_momentum_replaced_only_after_partial_fill=True)
    return result
