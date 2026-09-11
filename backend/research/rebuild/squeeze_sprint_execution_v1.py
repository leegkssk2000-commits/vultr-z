"""Squeeze Continuation single-axis/bounded orthogonal component execution.

Stage2/3 pure simulation only; no CLI, network, order or automatic dispatch.
Original CAPREUSE admission remains imported unchanged. CONTROL has exact
parent identity; candidate changes only registered lifecycle components.
"""
from copy import deepcopy
from math import fsum
from unittest.mock import patch
from backend.research.rebuild import c70_tm_capreuse_v1 as cap
from backend.research.rebuild import squeeze_sprint_components_v1 as components

tm=cap.tm;BAR=tm.BAR;DAY=tm.DAY
cost_at=tm.cost_at;daily_observation=tm.daily_observation
SCOPE='SQUEEZE_CONTINUATION_BENCHMARK_SPRINT_AFTER_PR1266_V1'


def validate_slots(slots):
    slots=tuple(slots)
    if not slots or len(slots)>2 or slots!=tuple(sorted(set(slots))):
        raise ValueError('ONE_COMPONENT_OR_TWO_ORTHOGONAL_COMPONENTS')
    if any(s not in components.REGISTRY for s in slots):raise ValueError('UNREGISTERED_SOURCE_COMPONENT')
    axes=[components.REGISTRY[s]['axis'] for s in slots]
    if len(axes)!=len(set(axes)):raise ValueError('DUPLICATE_LIFECYCLE_AXIS')
    if sum(components.REGISTRY[s]['mode']=='REPLACE_RUNNER' for s in slots)>1:raise ValueError('ONE_RUNNER_REPLACEMENT')
    return slots


def candidate_name(slots):
    return 'SQUEEZE_CONTINUATION_'+'_'.join(s.replace('-','_') for s in slots)+'_V1'


def assert_authorized(scope,status):
    if scope!=SCOPE or status not in ('FROZEN_STAGE2_FIRST_FULL','FROZEN_STAGE3_FIRST_FULL','FROZEN_CHALLENGE_FIRST_FULL'):
        raise ValueError('SCOPE_OR_STAGE_NOT_AUTHORIZED')


def position(bars, signal, variant, features, end, cost, slots=()):
    if not slots:return tm.position(bars,signal,variant,features,end,cost)
    slots=validate_slots(slots)
    rows=[dict(bar_open_ts=b.open_ts,bar_close_ts=b.open_ts+BAR,open=b.open,high=b.high,low=b.low,close=b.close,volume=b.volume) for b in bars]
    component_state={}
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
        net_progress = (row.close/entry.open-1)*10000 - cost_at(cost,entry.open_ts,stamp)
        component_obs=[components.observe(slot,rows,j,ei,entry.open,runner,component_state,net_progress) for slot in slots]
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
            elif any(components.REGISTRY[s]['mode']=='REPLACE_RUNNER' for s in slots):
                replacement=next(o for o in component_obs if components.REGISTRY[o['source_slot']]['mode']=='REPLACE_RUNNER')
                if replacement['trigger']:reason=replacement['reason']
            elif row.close < obs['sma10']:
                reason = 'RUNNER_SMA10_CLOSE'
        if reason is None:
            added=next((o for o in component_obs if components.REGISTRY[o['source_slot']]['mode']=='ADD_EXIT' and o['trigger']),None)
            if added is not None:reason=added['reason']
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
                          daily=obs, pending=deepcopy(pending), signal_index=i,component_observations=component_obs))
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
               runner_activated=runner, exit_trigger=deepcopy(pending),component_slots=list(slots))
    if closed:
        raw.update(exit_index=last['index'], exit_ts=last['ts'], exit_price=last['price'],
                   gross_bps=gross, exit_reason=final_reason, exit_timestamp_semantics='OBSERVED_4H_OPEN')
        return raw, None, trace
    raw.update(mark_index=last['index'], mark_ts=last['ts'], mark_price=last['price'],
               gross_mark_bps=gross, status='CENSORED', terminal_liquidation=False,
               censor_reason='PENDING_EXIT_OUTSIDE_WINDOW' if pending else 'HOLD_UNFINISHED',
               pending_exit_trigger=deepcopy(pending))
    return None, raw, trace


def replay(rows,*,slots,eval_start_ms,eval_end_ms,cost):
    if not slots:
        return cap.replay(rows,eval_start_ms=eval_start_ms,eval_end_ms=eval_end_ms,cost=cost)
    slots=validate_slots(slots)
    def managed(bars,signal,variant,features,end,unit_cost):
        return position(bars,signal,variant,features,end,unit_cost,slots)
    with patch.object(tm,'position',managed):
        result=cap.replay(rows,eval_start_ms=eval_start_ms,eval_end_ms=eval_end_ms,cost=cost)
    result['audit'].update(rule=candidate_name(slots),scope=SCOPE,component_slots=list(slots),
        change_axis=[components.REGISTRY[s]['axis'] for s in slots],source_control='EXACT_PR1262_CAPREUSE',
        comparison_mode='FULL_CHRONOLOGICAL',formal_credit=0,independent=False)
    return result
