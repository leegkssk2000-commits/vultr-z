"""KR3 whole-entry structural-failure exit. Single explicitly authorized DEV child.

Only add D2's subsequent-failure predicate to original KR3 anchors. Never import
D's waiting/requalification/shifted entry scheme. No I/O or outcome selectors.
"""
from copy import deepcopy
import math
from unittest.mock import patch
from backend.research.rebuild import keltner_kr3_v1 as parent
m2, d = parent.m2, parent.d
BAR, HOLD = parent.BAR, parent.HOLD
UNCHECKED, SUPPRESSED, ALLOWED = parent.UNCHECKED, parent.SUPPRESSED, parent.ALLOWED
decide, DECISION, TRIGGER, EXIT = parent.decide, parent.DECISION, parent.TRIGGER, parent.EXIT
RULE_ID = 'KR3_WHOLE_ENTRY_POST_SUPPRESSION_FAILURE_EXIT_V1'
FAILURE_TRIGGER = 'KR3_POST_SUPPRESSION_FAILURE_CLOSE'
FAILURE_EXIT = 'KR3_POST_SUPPRESSION_FAILURE_NEXT_OPEN'
RULE = ('Original KR3 signals, next-open entries, reference reservation and exits retained. '
        'After first low breach was suppressed, a strictly later held completed close below '
        'both ORIGINAL signal low and then EMA50 queues next-open exit. '
        'Existing timeout/EMA/allowed-low/runner priority wins. No wait6, recheck or shifted anchor.')

def additional_failure(state, row, index, signal_low, ema50):
    if state.get('status') != SUPPRESSED or index <= state['index']:
        return False
    values = (float(row['close']), float(signal_low), float(ema50))
    if not all(math.isfinite(v) and v > 0 for v in values):
        raise ValueError('INVALID_POST_SUPPRESSION_OBSERVATION')
    return values[0] < values[1] and values[0] < values[2]

def path(rows, signal, ema20, ema50, end, enabled):
    if not enabled:
        return parent.path(rows, signal, ema20, ema50, end, True)
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
        late_failure = additional_failure(state, row, j, signal_low, ema50[j])
        runner_hit = extension['allowed'] and j >= native_exit and float(row['close']) <= ema20[j]
        if not (ema_hit or active_low or runner_hit or late_failure):
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
        if late_failure:
            pending['post_suppression_failure'] = True
        # Existing KR3 priority wins when both conditions become known together.
        reason = 'EMA20_NOT_ABOVE_EMA50_NEXT_OPEN' if ema_hit else m2.EXIT if active_low else EXIT if runner_hit else FAILURE_EXIT
        kind = 'TREND_INVALIDATION_CLOSE' if ema_hit else m2.TRIGGER if active_low else TRIGGER if runner_hit else FAILURE_TRIGGER
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
        raw['runner_extension'] = deepcopy(extension)
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
    raw['runner_extension'] = deepcopy(extension)
    raw['runner_planned_exit_index'] = final_exit
    return None, raw, trace


def replay(rows, bundle, *, eval_start_ms, eval_end_ms, enabled=True,
           reference_checkpoint=None, fixed_signal_indices=None):
    if type(enabled) is not bool:
        raise ValueError('KR3_FAILURE_BOOL_REQUIRED')
    kw = dict(eval_start_ms=eval_start_ms, eval_end_ms=eval_end_ms,
              reference_checkpoint=reference_checkpoint, fixed_signal_indices=fixed_signal_indices)
    if not enabled:
        return parent.replay(rows, bundle, **kw)
    # Same single-owner mechanism as KR3. Reference clock never uses child exits.
    with patch.object(parent.kr, 'path', path):
        out = parent.kr.replay(rows, bundle, **kw)
    out['audit'].update(rule=RULE_ID, mutation='POST_SUPPRESSION_EXIT_ONLY',
        original_KR3_entry_reference=True, wait_bars_added=0,
        prior_suppression_veto_T=sum(t['kind']==DECISION and t.get('m2_state_at_decision')==SUPPRESSED for t in out['trace']),
        additional_failure_exits=sum(t['kind']==FAILURE_EXIT for t in out['trace']))
    return out
