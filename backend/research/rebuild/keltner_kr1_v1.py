"""KR1: one prospective finite extension of M2, with immutable D reservations.

Only completed closes decide orders. FULL uses the actual symbol slot; FIXED
is an independent path diagnostic that may overlap. No I/O or authority.
"""
from copy import deepcopy
from unittest.mock import patch
from backend.research.rebuild import keltner_m2_context_v1 as m2

parent, d = m2.parent, m2.d
BAR, HOLD = m2.BAR, m2.HOLD
UNCHECKED, SUPPRESSED, ALLOWED = m2.UNCHECKED, m2.SUPPRESSED, m2.ALLOWED
decide = m2.decide
RULE_ID = 'KELTNER_KR1_FINITE_RUNNER_DEV_V1'
DECISION = 'RUNNER_T_MINUS_ONE_DECISION'
TRIGGER = 'RUNNER_CLOSE_NOT_ABOVE_EMA20'
EXIT = 'RUNNER_EMA20_NEXT_OPEN'


def path(rows, signal, ema20, ema50, end, enabled):
    if not enabled:
        return m2.path(rows, signal, ema20, ema50, end, True)
    i = signal['signal_index']; ei = i + 1; native_exit = i + HOLD
    signal_low = float(rows[i]['low'])
    entry_price = float(rows[ei]['open'])
    extension = {'decided': False, 'allowed': False}
    final_exit = native_exit
    trace = [{'kind': 'ENTRY_NEXT_OPEN', 'signal_index': i, 'index': ei,
              'ts': rows[ei]['bar_open_ts'], 'price': rows[ei]['open'],
              'frozen_signal_low': signal_low, 'feature_available_ts': rows[i]['bar_close_ts']}]
    pending = None
    state = {"status": UNCHECKED}
    for j in range(ei, min(i + 2 * HOLD, len(rows) - 1) + 1):
        row = rows[j]
        # A pending prior-close order is filled at the next open below, before
        # consulting that next bar's high/low/close or its later timeout.
        if j == final_exit:
            if row['bar_close_ts'] < end:
                raw = d._geometry(rows, i, j, end)
                trace.append({'kind': 'RUNNER_FINAL_TIME_STOP_CLOSE' if extension['allowed'] else 'ORIGINAL_TIME_STOP_CLOSE', 'signal_index': i,
                              'index': j, 'ts': raw['exit_ts'], 'price': raw['exit_price']})
                raw["low_exit_state"] = deepcopy(state)
                raw['runner_extension'] = deepcopy(extension)
                return raw, None, trace
            break
        ema_hit = ema20[j] <= ema50[j]
        low_hit = float(row['close']) < signal_low
        if not ema_hit and state['status'] == UNCHECKED and low_hit:
            state = decide(state, row, j, signal_low, ema50[j])
            trace.append({'kind': m2.DECISION, 'signal_index': i, **deepcopy(state)})
        active_low = low_hit and state['status'] == ALLOWED
        runner_hit = extension['allowed'] and j >= native_exit and float(row['close']) <= ema20[j]
        if not (ema_hit or active_low or runner_hit):
            if j == native_exit - 1:
                allowed = float(row['close']) > entry_price and float(row['close']) > ema20[j] > ema50[j]
                extension = {'decided': True, 'allowed': allowed, 'index': j,
                    'ts': row['bar_close_ts'], 'observed_close': row['close'],
                    'entry_price': entry_price, 'ema20': ema20[j], 'ema50': ema50[j]}
                trace.append({'kind': DECISION, 'signal_index': i, **deepcopy(extension)})
                if allowed:
                    final_exit = i + 2 * HOLD
            continue
        pending = {'signal_ts': row['bar_close_ts'], 'signal_index': j,
                   'ema20': ema20[j], 'ema50': ema50[j],
                   'signal_low': signal_low, 'observed_close': row['close'],
                   'low_condition': low_hit, 'ema_condition': ema_hit, 'runner_condition': runner_hit}
        # Existing D priority wins when both conditions become known together.
        reason = 'EMA20_NOT_ABOVE_EMA50_NEXT_OPEN' if ema_hit else m2.EXIT if active_low else EXIT
        kind = 'TREND_INVALIDATION_CLOSE' if ema_hit else m2.TRIGGER if active_low else TRIGGER
        trace.append({'kind': kind, 'signal_index': i, 'index': j,
                      'ts': row['bar_close_ts'], **pending})
        # Preserve original entry origin separately from trigger source index.
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
                   exit_trigger=deepcopy(pending), frozen_signal_low=signal_low)
        trace.append({'kind': reason, 'signal_index': i, 'index': xi,
                      'ts': raw['exit_ts'], 'price': price})
        raw["low_exit_state"] = deepcopy(state)
        raw["runner_extension"] = deepcopy(extension)
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
        pending_exit_trigger=deepcopy(pending), frozen_signal_low=signal_low)
    trace.append({'kind':'TERMINAL_MARK', 'signal_index':i, 'index':raw['mark_index'],
        'ts':raw['mark_ts'], 'price':raw['mark_price'], 'censor_reason':raw['censor_reason'],
        'pending_exit_signal_ts':raw['pending_exit_signal_ts']})
    raw["low_exit_state"] = deepcopy(state)
    raw["runner_extension"] = deepcopy(extension)
    raw["runner_planned_exit_index"] = final_exit
    return None, raw, trace


def replay(rows, bundle, *, eval_start_ms, eval_end_ms, enabled=True,
           reference_checkpoint=None, fixed_signal_indices=None):
    if type(enabled) is not bool:
        raise RuntimeError('KR1_BOOL_REQUIRED')
    if not enabled:
        return m2.replay(rows, bundle, eval_start_ms=eval_start_ms,
            eval_end_ms=eval_end_ms, reference_checkpoint=reference_checkpoint,
            fixed_signal_indices=fixed_signal_indices)
    # Validate once without evaluating a market path; then replay accepted
    # paths using the inherited geometry and actual slot at signal close.
    clock = parent.causal_clock(rows, bundle, eval_start_ms=eval_start_ms,
        eval_end_ms=eval_end_ms, checkpoint=reference_checkpoint)
    selected = set(clock['admitted_signal_indices'])
    if fixed_signal_indices is not None and not set(fixed_signal_indices) <= selected:
        raise RuntimeError('KR1_FIXED_NOT_M2_ELIGIBLE')
    with patch.object(d, '_path', path):
        if fixed_signal_indices is not None:
            result = d.replay(rows, bundle, eval_start_ms=eval_start_ms,
                eval_end_ms=eval_end_ms, fixed_signal_indices=fixed_signal_indices)
        else:
            result = d.replay(rows, bundle, eval_start_ms=eval_start_ms,
                eval_end_ms=eval_end_ms, fixed_signal_indices=[])
            last_exit_ts, tail_open = -1, False
            for signal in bundle['signals']:
                i = signal['signal_index']
                if i not in selected:
                    continue
                if tail_open or signal['signal_ts'] <= last_exit_ts:
                    result['events'].append(dict(signal, admission=False,
                        status='EXCLUDED', exclusion_reason='RUNNER_OCCUPIED'))
                    continue
                one = d.replay(rows, bundle, eval_start_ms=eval_start_ms,
                    eval_end_ms=eval_end_ms, fixed_signal_indices=[i])
                for key in ('trades', 'open_positions', 'events', 'trace'):
                    result[key].extend(one[key])
                if one['trades']:
                    last_exit_ts = one['trades'][0]['exit_ts']
                tail_open = bool(one['open_positions'])
            executed = {e['signal_index']: e for e in result['events']}
            result['events'] = deepcopy(clock['opportunity_events'])
            for event in result['events']:
                if event['signal_index'] in executed:
                    event.update(executed[event['signal_index']])
    result.update(reference_events=deepcopy(clock['reference_events']),
        reference_opportunities=deepcopy(clock['reference_opportunities']),
        reference_checkpoint=clock)
    excluded = sum(e['status'] == 'EXCLUDED' for e in result['events'])
    assert len(result['trades']) + len(result['open_positions']) + excluded == len(result['events'])
    result['audit'].update(rule=RULE_ID, comparison_type='EXIT_CHANGE',
        comparison_mode='FIXED_INDEPENDENT_PATH_DIAGNOSTIC' if fixed_signal_indices is not None else 'FULL_ACTUAL_SLOT_AND_D_REFERENCE',
        same_symbol_max_positions=None if fixed_signal_indices is not None else 1,
        fixed_origins_independent_diagnostic_positions=fixed_signal_indices is not None,
        completed=len(result['trades']), open=len(result['open_positions']), excluded=excluded,
        raw_signals=len(result['events']), reference_original_signal_count=len(bundle['signals']),
        reference_released_by_actual_exit=False, original_D_reference_unchanged=True,
        original_signal_exit_bar_ownership_preserved=False,
        actual_slot_order='SIGNAL_CLOSE_MUST_BE_AFTER_ACTUAL_EXIT; REFERENCE_EXIT_BAR_OWNERSHIP_UNCHANGED',
        runner_occupied_T=sum(e['exclusion_reason']=='RUNNER_OCCUPIED' for e in result['events']),
        maximum_hold_bars=2*HOLD, extension_decisions=sum(t['kind']==DECISION for t in result['trace']),
        extension_allowed_T=sum(t['kind']==DECISION and t['allowed'] for t in result['trace']),
        pending_exit_at_end=sum(o['pending_exit_signal_ts'] is not None for o in result['open_positions']),
        strict_boundary_timeout_marks=sum(o['censor_reason']=='ORIGINAL_STRICT_END_TIMEOUT_AT_BOUNDARY' for o in result['open_positions']),
        forced_terminal_liquidations=0, execution_authority='NONE')
    return result
