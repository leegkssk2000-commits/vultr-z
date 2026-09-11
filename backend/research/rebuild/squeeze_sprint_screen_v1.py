"""Exit-only Stage1 common-trade proxy on saved CAPREUSE admissions.

No signal generator, source lifecycle, admission/capacity replay, dispatcher,
files, network, or candidate allocation. Replacement exits inspect only the
fixed campaign's runner suffix, never a new entry opportunity. Exposures may
overlap beyond capacity because all parent allocations remain fixed: this is
explicitly not a FULL executable portfolio result.
"""
from copy import deepcopy
from math import fsum, isclose

from backend.research.rebuild import c70_tm_capreuse_v1 as cap
from backend.research.rebuild import squeeze_sprint_components_v1 as comp

tm = cap.tm
SCOPE = 'SQUEEZE_CONTINUATION_BENCHMARK_SPRINT_AFTER_PR1266_V1'
MODE = 'COMMON_TRADE_PROXY_NO_OCCUPANCY_REPLAY'
PARTIAL = 'D3_PROFIT_PARTIAL_NEXT_OPEN'
OPEN_FIELDS = ('mark_index', 'mark_ts', 'mark_price', 'gross_mark_bps', 'status',
               'terminal_liquidation', 'censor_reason', 'pending_exit_trigger')
CLOSED_FIELDS = ('exit_index', 'exit_ts', 'exit_price', 'gross_bps', 'exit_reason',
                 'exit_timestamp_semantics')


def _decision(reason, j, bars, slot):
    return dict(action='FINAL', reason=reason, signal_index=j,
                signal_ts=bars[j].open_ts + tm.BAR, screen_slot=slot)


def _rebuild(source, legs, bars, pending, slot, component_exit=False):
    """Recompute cash-path metadata; allocations and campaign identity survive."""
    raw = deepcopy(source)
    if not legs or not isclose(fsum(l['qty'] for l in legs), 1., abs_tol=1e-12):
        raise AssertionError('SCREEN_UNIT_QUANTITY_CONSERVATION')
    if any(l['qty'] <= 0 for l in legs):
        raise AssertionError('SCREEN_NONPOSITIVE_LEG')
    last = legs[-1]
    closed = last['status'] == 'C'
    for field in OPEN_FIELDS + CLOSED_FIELDS:
        raw.pop(field, None)
    ei, entry = raw['entry_index'], raw['entry_price']
    j = last['index']
    held = bars[ei:j if closed else j + 1]
    gross = fsum(l['qty'] * (l['price'] / entry - 1) * 10000 for l in legs)
    actual_partials = [l for l in legs if l['status'] == 'C' and l['reason'] == PARTIAL]
    raw.update(tm_legs=deepcopy(legs), assembled_qty=1.,
               remaining_qty=0. if closed else last['qty'],
               partial_count=len(actual_partials), runner_activated=bool(actual_partials),
               hold_ms=last['ts'] - raw['entry_ts'],
               mfe_bps=max([0., (last['price'] / entry - 1) * 10000] +
                           [(b.high / entry - 1) * 10000 for b in held]),
               mae_bps=min([0., (last['price'] / entry - 1) * 10000] +
                           [(b.low / entry - 1) * 10000 for b in held]),
               exit_trigger=deepcopy(pending), screen_slot=slot,
               component_exit=bool(component_exit), comparison_mode=MODE)
    if closed:
        raw.update(exit_index=j, exit_ts=last['ts'], exit_price=last['price'],
                   exit_reason=last['reason'], gross_bps=gross,
                   exit_timestamp_semantics='OBSERVED_4H_OPEN')
    else:
        raw.update(mark_index=j, mark_ts=last['ts'], mark_price=last['price'],
                   gross_mark_bps=gross, status='CENSORED', terminal_liquidation=False,
                   censor_reason='PENDING_EXIT_OUTSIDE_WINDOW' if pending else 'HOLD_UNFINISHED',
                   pending_exit_trigger=deepcopy(pending))
    raw['screen_changed'] = raw['tm_legs'] != source['tm_legs']
    return raw


def _normalize_trace(trace, raw):
    q = float(cap.allocation(raw))
    for event in trace:
        event['allocation_numerator'] = raw['allocation_numerator']
        event['allocation_denominator'] = raw['allocation_denominator']
        if 'qty' in event:
            event['normalized_fill_qty'] = q * event['qty']
        if 'remaining_qty' in event:
            event['remaining_normalized_qty'] = q * event['remaining_qty']
    return trace


def _observation(slot, rows, j, raw, runner, state, cost):
    net = (rows[j]['close'] / raw['entry_price'] - 1) * 10000 - tm.cost_at(
        cost, raw['entry_ts'], rows[j]['bar_close_ts'])
    result = comp.observe(slot, rows, j, raw['entry_index'], raw['entry_price'],
                          runner, state, net)
    return dict(kind='COMPONENT_CLOSE_OBSERVATION', index=j,
                ts=rows[j]['bar_close_ts'], signal_index=raw['signal_index'],
                entry_ts=raw['entry_ts'], **result)


def _add_exit(source, trace, rows, bars, cost, end, slot):
    state, observations = {}, []
    actual = deepcopy(trace)
    raw = deepcopy(source)
    for held in trace:
        if held['kind'] != 'HELD_CLOSE_OBSERVATION':
            continue
        j = held['index']
        runner = any(l['status'] == 'C' and l['reason'] == PARTIAL and
                     l['ts'] < held['ts'] for l in source['tm_legs'])
        obs = _observation(slot, rows, j, source, runner, state, cost)
        # Existing conservative final-close decisions outrank this additive exit.
        pending = held.get('pending')
        priority = bool(pending and pending['action'] == 'FINAL')
        obs.update(source_exit_priority=priority,
                   selected=bool(obs['trigger'] and not priority))
        observations.append(obs)
        if not obs['selected']:
            continue
        decision = _decision(obs['reason'], j, bars, slot)
        if j + 1 >= len(bars) or bars[j + 1].open_ts >= end:
            raw = _rebuild(source, source['tm_legs'], bars, decision, slot)
            raw['pending_component_exit'] = deepcopy(decision)
            for event in actual:
                if event['kind'] == 'HELD_CLOSE_OBSERVATION' and event['index'] == j:
                    event['pending'] = deepcopy(decision)
            break
        k, stamp = j + 1, bars[j + 1].open_ts
        # An actual source partial due at this open executes first. A source
        # full exit due here is already protected by the prior-close priority.
        legs = [deepcopy(l) for l in source['tm_legs'] if l['status'] == 'C' and l['ts'] <= stamp]
        qty = 1. - fsum(l['qty'] for l in legs)
        if qty <= 1e-12:
            obs.update(selected=False, source_exit_priority=True)
            break
        legs.append(dict(status='C', qty=qty, index=k, ts=stamp,
                         price=bars[k].open, reason=obs['reason'] + '_NEXT_OPEN'))
        actual = [deepcopy(t) for t in trace if t['index'] < k or
                  t['index'] == k and t['kind'] == 'PARTIAL_FILL']
        for event in actual:
            if event['kind'] == 'HELD_CLOSE_OBSERVATION' and event['index'] == j:
                event['pending'] = deepcopy(decision)
        actual.append(dict(kind='FINAL_FILL', ts=stamp, index=k, price=bars[k].open,
                           remaining_qty=0., decision=deepcopy(decision),
                           slot_released=True, signal_index=source['signal_index'],
                           component_exit=True))
        raw = _rebuild(source, legs, bars, decision, slot, True)
        break
    raw.setdefault('screen_slot', slot)
    raw.setdefault('screen_changed', False)
    raw.setdefault('component_exit', False)
    raw['comparison_mode'] = MODE
    return raw, actual, observations


def _replace_runner(source, trace, rows, bars, cost, end, slot):
    partials = [l for l in source['tm_legs'] if l['status'] == 'C' and l['reason'] == PARTIAL]
    # No actual partial, or source partial+residual safety at the same open:
    # the replacement has no runner interval in which to act.
    if not partials or source.get('exit_ts') == partials[0]['ts']:
        raw = deepcopy(source)
        raw.update(screen_slot=slot, screen_changed=False, component_exit=False, comparison_mode=MODE)
        return raw, deepcopy(trace), []
    partial = partials[0]
    if len(partials) != 1:
        raise AssertionError('SCREEN_FROZEN_SINGLE_SOURCE_PARTIAL_REQUIRED')
    k = partial['index']
    legs = [deepcopy(l) for l in source['tm_legs'] if l['status'] == 'C' and l['ts'] <= partial['ts']]
    qty = 1. - fsum(l['qty'] for l in legs)
    actual = [deepcopy(t) for t in trace if t['index'] < k or
              t['index'] == k and t['kind'] == 'PARTIAL_FILL']
    source_held = {t['index']: t for t in trace if t['kind'] == 'HELD_CLOSE_OBSERVATION'}
    state, observations, pending, component_exit = {}, [], None, False
    for j in range(k, len(bars)):
        row = bars[j]
        if pending is not None and row.open_ts < end:
            reason = pending['reason'] + '_NEXT_OPEN'
            legs.append(dict(status='C', qty=qty, index=j, ts=row.open_ts,
                             price=row.open, reason=reason))
            actual.append(dict(kind='FINAL_FILL', ts=row.open_ts, index=j, price=row.open,
                               remaining_qty=0., decision=deepcopy(pending), slot_released=True,
                               signal_index=source['signal_index'], component_exit=component_exit))
            break
        daily = tm.daily_observation(bars, j)
        reason = 'FIXED_FLOOR_CLOSE' if row.close <= source['fixed_floor'] else None
        if reason is None and row.close <= source['entry_price']:
            reason = 'RUNNER_BREAKEVEN_CLOSE'
        if reason is None and daily['is_daily_close'] and daily['sma10'] is None:
            reason = 'RUNNER_DAILY_HISTORY_SAFETY_CLOSE'
        obs = _observation(slot, rows, j, source, True, state, cost)
        if reason is None and obs['features'].get('data_safety_required'):
            reason = 'RUNNER_DAILY_HISTORY_SAFETY_CLOSE'
        obs.update(source_exit_priority=reason is not None,
                   selected=bool(obs['trigger'] and reason is None),
                   saved_source_observation_available=j in source_held)
        observations.append(obs)
        component_exit = obs['selected']
        if component_exit:
            reason = obs['reason']
        pending = _decision(reason, j, bars, slot) if reason else None
        if j in source_held:
            held = deepcopy(source_held[j])
            held.update(pending=deepcopy(pending), runner=True, remaining_qty=qty)
        else:
            stamp = row.open_ts + tm.BAR
            held = dict(kind='HELD_CLOSE_OBSERVATION', ts=stamp, index=j, close=row.close,
                        floor=source['fixed_floor'],
                        momentum=row.close - bars[j - 14].close if j >= 14 else None,
                        held_bars=j - source['entry_index'] + 1,
                        daily_count=sum(b.open_ts + tm.BAR > source['entry_ts'] and
                                        (b.open_ts + tm.BAR) % tm.DAY == 0
                                        for b in bars[source['entry_index']:j + 1]),
                        first_management=False, net_progress_bps=(row.close / source['entry_price'] - 1) * 10000 -
                        tm.cost_at(cost, source['entry_ts'], stamp), runner=True, remaining_qty=qty,
                        daily=daily, pending=deepcopy(pending), signal_index=source['signal_index'])
            held['screen_fixed_trade_exit_suffix'] = True
        actual.append(held)
    else:
        j = len(bars) - 1
        stamp = bars[j].open_ts + tm.BAR
        legs.append(dict(status='O', qty=qty, index=j, ts=stamp,
                         price=bars[j].close, reason='TERMINAL_MARK'))
        actual.append(dict(kind='TERMINAL_MARK', ts=stamp, index=j, price=bars[j].close,
                           remaining_qty=qty, slot_released=False, signal_index=source['signal_index']))
        component_exit = False
    raw = _rebuild(source, legs, bars, pending, slot, component_exit)
    if legs[-1]['status'] == 'O' and pending and observations[-1]['selected']:
        raw['pending_component_exit'] = deepcopy(pending)
    return raw, actual, observations


def screen_symbol(parent_rr, rows, cost, end, slot):
    """Apply one source component to saved entries at their exact allocations."""
    if slot not in comp.REGISTRY:
        raise ValueError('SCREEN_UNKNOWN_SOURCE_SLOT')
    if not rows:
        raise ValueError('SCREEN_EMPTY_ROWS')
    bars = tm.native.to_bars(rows, rows[0]['bar_open_ts'], end)
    campaigns = parent_rr['trades'] + parent_rr['open_positions']
    origins = [r['signal_index'] for r in campaigns]
    if len(set(origins)) != len(origins):
        raise ValueError('SCREEN_DUPLICATE_SAVED_CAMPAIGN')
    traces = {i: [] for i in origins}
    for event in parent_rr['trace']:
        if event['signal_index'] not in traces:
            raise ValueError('SCREEN_TRACE_UNKNOWN_ORIGIN')
        traces[event['signal_index']].append(event)
    out = deepcopy(parent_rr)
    out.update(trades=[], open_positions=[], trace=[], screen_trace=[])
    out.pop('capacity_timeline', None)
    out['saved_parent_capacity_timeline'] = deepcopy(parent_rr.get('capacity_timeline', []))
    for source in campaigns:
        ei = source['entry_index']
        if (not 0 <= ei < len(bars) or source['entry_ts'] != bars[ei].open_ts or
                source['entry_price'] != bars[ei].open):
            raise ValueError('SCREEN_SAVED_ENTRY_BINDING')
        if not 0 < cap.allocation(source) <= 1:
            raise ValueError('SCREEN_SAVED_ALLOCATION')
        trace = traces[source['signal_index']]
        if not trace or trace[0]['kind'] != 'ENTRY_NEXT_OPEN':
            raise ValueError('SCREEN_SAVED_ENTRY_TRACE_REQUIRED')
        held_indices = [t['index'] for t in trace if t['kind'] == 'HELD_CLOSE_OBSERVATION']
        terminal = source.get('exit_index', source.get('mark_index'))
        expected = list(range(ei, terminal if 'exit_index' in source else terminal + 1))
        if held_indices != expected:
            raise ValueError('SCREEN_COMPLETE_SAVED_HELD_PREFIX_REQUIRED')
        execute = _add_exit if comp.REGISTRY[slot]['mode'] == 'ADD_EXIT' else _replace_runner
        raw, actual, observations = execute(source, trace, rows, bars, cost, end, slot)
        out['trades' if 'exit_ts' in raw else 'open_positions'].append(raw)
        out['trace'].extend(_normalize_trace(actual, raw))
        out['screen_trace'].extend(observations)
    # Keep events byte-for-byte in value, including original admission, status,
    # capacity and exclusions. They are parent entry evidence, not screen fills.
    out['audit'] = dict(scope=SCOPE, slot=slot, mechanism=comp.REGISTRY[slot]['mechanism'],
                        comparison_mode=MODE, saved_parent_events_preserved=True,
                        parent_entry_status_is_historical=True, fixed_admissions=True,
                        fixed_allocations=True, source_lifecycle_replays=0,
                        signal_generation_calls=0, occupancy_replays=0,
                        completed=len(out['trades']), open=len(out['open_positions']),
                        component_exit_count=sum(r['component_exit'] for r in out['trades']),
                        changed_campaigns=sum(r['screen_changed'] for r in out['trades'] + out['open_positions']),
                        component_trigger_count=sum(t['trigger'] for t in out['screen_trace']),
                        selected_component_trigger_count=sum(t['selected'] for t in out['screen_trace']),
                        new_exchange_orders=0, independent=False, formal_credit=0,
                        production_compatibility=False, canonical_candidate_number=None)
    assert out['events'] == parent_rr['events']
    assert {r['signal_index']: cap.allocation(r) for r in out['trades'] + out['open_positions']} == {
        r['signal_index']: cap.allocation(r) for r in campaigns}
    return out
