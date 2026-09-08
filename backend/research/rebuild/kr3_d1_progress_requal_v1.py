"""D1: retain exact PR1213 D; add a sixth-close trend-progress recheck only.

Research candidate, not operating admission. Original half, delay6, shifted
reference/exit anchors and all exits/costs remain D. No earlier-entry E rule,
no symbol/date/outcome feature, no cancellation of past fills.
"""
from __future__ import annotations
from collections import Counter
from copy import deepcopy
from dataclasses import asdict
import math
from unittest.mock import patch
from backend.research.rebuild import step7_kr3_mechanism_separation_v1 as p

d, reservation, anchored_path, HOLD = p.d, p.reservation, p.anchored_path, p.HOLD
CANDIDATE = 'KR3_D1_SIXTH_CLOSE_PROGRESS_REQUAL_V1'
ORIGINAL_D = {'id':'W6_RECHECK_SHIFTED_EXIT_ANCHOR','delay':6,'recheck':True,
              'reference_anchor':'SHIFTED','exit_anchor':'SHIFTED','require_origin_half':True}
RULE = 'origin_half AND (delayed_half OR (close6 > origin_high AND close6 > ema20_6 > ema50_6)); next open; exact D reference and exit anchors'


def progress_confirmed(origin, current, ema20, ema50):
    """Only the original completed high and current completed-close observations."""
    values = (origin['high'], current['close'], ema20, ema50)
    if any(isinstance(v, bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<=0 for v in values):
        raise ValueError('RECHECK_OBSERVATIONS_INVALID')
    if current['bar_close_ts'] <= origin['bar_close_ts']:
        raise ValueError('RECHECK_MUST_FOLLOW_ORIGIN')
    return current['close'] > origin['high'] and current['close'] > ema20 > ema50


def replay_symbol(rows, bundle, *, start, end):
    """All raw origins, streamed reference clock and next-open actual position.

    Exact D shifted reference: no reservation during waiting. At the sixth
    observed close, allow the old half predicate OR structural price progress.
    Reference lifecycle remains unchanged even on rejection; actual positions
    never overlap, and past entry decisions are never reversed.
    """
    mode = p.MODES[3]
    if asdict(mode) != ORIGINAL_D:
        raise ValueError("EXACT_D_PARENT_REQUIRED")
    d.replay(rows, bundle, eval_start_ms=start, eval_end_ms=end,
             enable_change=True, fixed_signal_indices=[])
    if mode.delay < 0 or mode.delay >= HOLD-1:
        raise ValueError('DELAY_BEFORE_EXTENSION_DECISION_REQUIRED')
    originals = {s['signal_index']:s for s in bundle['signals']}
    scheduled, events, traces = {}, {}, []
    trades, opened = [], []
    clock = reservation.initial_clock(eval_start_ms=start, eval_end_ms=end)
    last_actual_exit = -1
    tail_open = False
    original_observer = reservation.n.entry_observation
    for j, row in enumerate(rows):
        # Known source signals are latched on this completed bar, not selected
        # from the baseline's admitted trades or subsequent profit labels.
        if j in originals:
            original_half = original_observer(row)[reservation.n.FEATURE]
            ev = {**originals[j], 'original_signal_index':j,
                  'origin_half':original_half, 'origin_known_at':row['bar_close_ts'],
                  'decision_index':j+mode.delay, 'decision_ts':None,
                  'admission':False, 'status':'WAITING', 'exclusion_reason':None,
                  'reference_created':False}
            events[j] = ev
            scheduled[j+mode.delay] = j
        ready_origin = scheduled.get(j)
        clock_signal = originals.get(j) if mode.reference_anchor == 'ORIGIN' else (
            {'signal_index':j, 'signal_ts':row['bar_close_ts']}
            if ready_origin is not None and row['bar_close_ts'] < end else None)
        if mode.reference_anchor == 'SHIFTED' and clock_signal is not None:
            origin_pass = events[ready_origin]['origin_half'] or not mode.require_origin_half
            progress = progress_confirmed(rows[ready_origin], row, bundle['ema20'][j], bundle['ema50'][j])
            events[ready_origin]['progress_confirmation'] = progress
            events[ready_origin]['recheck_observation'] = {'origin_high': rows[ready_origin]['high'], 'close': row['close'], 'ema20': bundle['ema20'][j], 'ema50': bundle['ema50'][j], 'available_at': row['bar_close_ts']}
            def observer(current):
                value = original_observer(current)
                value[reservation.n.FEATURE] = origin_pass and (
                    value[reservation.n.FEATURE] or progress)
                return value
            with patch.object(reservation.n, 'entry_observation', observer):
                reservation.advance_clock(clock,row,index=j,ema20=bundle['ema20'][j],
                                          ema50=bundle['ema50'][j],signal=clock_signal)
        else:
            reservation.advance_clock(clock,row,index=j,ema20=bundle['ema20'][j],
                                      ema50=bundle['ema50'][j],signal=clock_signal)
        if mode.reference_anchor == 'ORIGIN' and j in originals:
            known = clock['opportunity_events'][-1]
            ev = events[j]
            ev['reference_created'] = known['reservation_created']
            ev['origin_reference_admitted'] = known['admission']
            if not known['admission']:
                ev.update(status='EXCLUDED', exclusion_reason=known['exclusion_reason'],
                          exclusion_known_at=row['bar_close_ts'])
        if ready_origin is None:
            continue
        ev = events[ready_origin]
        if ev['status'] != 'WAITING':
            continue
        ev['decision_ts'] = row['bar_close_ts']
        ev['recheck_half'] = original_observer(row)[reservation.n.FEATURE]
        ev['recheck_known_at'] = row['bar_close_ts']
        reason = None
        if row['bar_close_ts'] >= end or j+1 >= len(rows):
            reason = 'NO_DELAYED_NEXT_OPEN_IN_CALENDAR'
        elif mode.reference_anchor == 'ORIGIN':
            k = clock['active_opportunity_offset']
            active = None if k is None else clock['reference_opportunities'][k]
            if active is None or active['reference_signal_index'] != ready_origin:
                reason = 'WAIT_REFERENCE_EXPIRED'
            elif active['phase'] not in ('HELD','PENDING_ENTRY_NEXT_OPEN'):
                reason = 'WAIT_REFERENCE_EXIT_ALREADY_OBSERVED'
            elif mode.recheck and not ev['recheck_half']:
                reason = 'DELAYED_HALF_RECHECK_FAILED'
        else:
            known = clock['opportunity_events'][-1]
            ev['reference_created'] = known['reservation_created']
            ev['shifted_reference_signal_index'] = j
            if not known['admission']:
                reason = known['exclusion_reason']
                if reason == reservation.n.VETO_REASON:
                    reason = ('ORIGIN_HALF_FAILED' if mode.require_origin_half and not ev['origin_half']
                              else 'DELAYED_HALF_RECHECK_FAILED')
        if reason is None and (tail_open or row['bar_close_ts'] <= last_actual_exit):
            reason = 'RUNNER_OCCUPIED_AT_DELAYED_DECISION'
        if reason is not None:
            ev.update(status='EXCLUDED',exclusion_reason=reason,
                      exclusion_known_at=row['bar_close_ts'])
            continue
        ev['admission_path'] = 'D_ORIGINAL_HALF' if ev['recheck_half'] else 'D1_PROGRESS_CONFIRMED_AT_SIXTH_CLOSE'
        signal = {'origin_index':ready_origin, 'decision_index':j,
                  'exit_anchor_index':ready_origin if mode.exit_anchor == 'ORIGIN' else j}
        closed, censored, trace = anchored_path(rows,signal,bundle['ema20'],bundle['ema50'],end)
        for t in trace:
            t.update(original_signal_index=ready_origin,decision_index=j,
                     exit_anchor_index=signal['exit_anchor_index'])
        traces.extend(trace)
        value = closed if closed is not None else censored
        value.update(initial_protective_sl=None,tp=None,risk_R=None,
                     waiting_observed_bars=mode.delay,
                     waiting_elapsed_ms=row['bar_close_ts']-rows[ready_origin]['bar_close_ts'])
        ev.update(admission=True,status='COMPLETED' if closed is not None else 'CENSORED')
        if closed is not None:
            trades.append(closed);last_actual_exit=closed['exit_ts']
        else:
            opened.append(censored);tail_open=True
    for ev in events.values():
        if ev['status']=='WAITING':
            ev.update(status='EXCLUDED',exclusion_reason='PENDING_WAIT_AT_END',
                      exclusion_known_at=end)
    rows_events = [events[k] for k in sorted(events)]
    excluded = sum(e['status']=='EXCLUDED' for e in rows_events)
    if len(trades)+len(opened)+excluded != len(originals):
        raise ValueError('ORIGINAL_SIGNAL_DENOMINATOR_PARITY')
    return {'trades':trades,'open_positions':opened,'events':rows_events,'trace':traces,
            'reference_opportunities':deepcopy(clock['reference_opportunities']),
            'reference_events':deepcopy(clock['reference_events']),
            'audit':{'raw_signals':len(originals),'completed':len(trades),'open':len(opened),
                     'excluded':excluded,'same_symbol_max_positions':1,
                     'exclusion_counts':dict(Counter(e['exclusion_reason'] for e in rows_events if e['status']=='EXCLUDED')),
                     'mode':asdict(mode),'candidate_id':CANDIDATE,'future_outcomes_as_features':False,
                     'reference_released_by_actual_exit':False}}
