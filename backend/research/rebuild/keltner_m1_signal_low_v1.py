"""Research-only signal-low exit overlay on the immutable M reference clock.

One synchronous economic writer owns the scoped D path hook. The unmodified M
clock selects admissions before any path is evaluated; actual exits cannot feed
back into its reservations. No I/O, cost model, sizing or operating authority.
"""
from copy import deepcopy
from unittest.mock import patch

from backend.research.rebuild import keltner_opportunity_reservation_adapter_v1 as parent

d = parent.previous
BAR, HOLD = d.BAR, d.HOLD
RULE_ID = 'KELTNER_M1_SIGNAL_LOW_CLOSE_EXIT_DEV_V1'
TRIGGER = 'SIGNAL_LOW_INVALIDATION_CLOSE'
EXIT = 'SIGNAL_LOW_INVALIDATION_NEXT_OPEN'
ORIGINAL_PATH = d._path


def path(rows, signal, ema20, ema50, end, enabled):
    if not enabled:
        return ORIGINAL_PATH(rows, signal, ema20, ema50, end, enabled)
    i = signal['signal_index']; ei = i + 1; native_exit = i + HOLD
    signal_low = float(rows[i]['low'])
    trace = [{'kind': 'ENTRY_NEXT_OPEN', 'signal_index': i, 'index': ei,
              'ts': rows[ei]['bar_open_ts'], 'price': rows[ei]['open'],
              'frozen_signal_low': signal_low, 'feature_available_ts': rows[i]['bar_close_ts']}]
    pending = None
    for j in range(ei, min(native_exit, len(rows) - 1) + 1):
        row = rows[j]
        # A pending prior-close order is filled at the next open below, before
        # consulting that next bar's high/low/close or its later timeout.
        if j == native_exit:
            if row['bar_close_ts'] < end:
                raw = d._geometry(rows, i, j, end)
                trace.append({'kind': 'ORIGINAL_TIME_STOP_CLOSE', 'signal_index': i,
                              'index': j, 'ts': raw['exit_ts'], 'price': raw['exit_price']})
                return raw, None, trace
            break
        ema_hit = ema20[j] <= ema50[j]
        low_hit = float(row['close']) < signal_low
        if not (ema_hit or low_hit):
            continue
        pending = {'signal_ts': row['bar_close_ts'], 'signal_index': j,
                   'ema20': ema20[j], 'ema50': ema50[j],
                   'signal_low': signal_low, 'observed_close': row['close'],
                   'low_condition': low_hit, 'ema_condition': ema_hit}
        # Existing D priority wins when both conditions become known together.
        reason = 'EMA20_NOT_ABOVE_EMA50_NEXT_OPEN' if ema_hit else EXIT
        kind = 'TREND_INVALIDATION_CLOSE' if ema_hit else TRIGGER
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
        return raw, None, trace
    raw = d._geometry(rows, i, len(rows)-1, end)
    for a, b in (('exit_index','mark_index'), ('exit_ts','mark_ts'),
                 ('exit_price','mark_price'), ('gross_bps','gross_mark_bps')):
        raw[b] = raw.pop(a)
    raw.update(status='CENSORED', terminal_liquidation=False, native_hold_bars=HOLD,
        native_planned_exit_ts=rows[ei]['bar_open_ts'] + HOLD*BAR,
        original_protective_sl=None,
        native_geometry_scope='FROZEN_V2_FIXED_HOLD_NO_NATIVE_SL_SPECIFIED',
        censor_reason='ORIGINAL_STRICT_END_TIMEOUT_AT_BOUNDARY' if native_exit==len(rows)-1 else 'NATIVE_HOLD_UNFINISHED',
        pending_exit_signal_ts=pending['signal_ts'] if pending else None,
        pending_exit_trigger=deepcopy(pending), frozen_signal_low=signal_low)
    trace.append({'kind':'TERMINAL_MARK', 'signal_index':i, 'index':raw['mark_index'],
        'ts':raw['mark_ts'], 'price':raw['mark_price'], 'censor_reason':raw['censor_reason'],
        'pending_exit_signal_ts':raw['pending_exit_signal_ts']})
    return None, raw, trace


def replay(rows, bundle, *, eval_start_ms, eval_end_ms, enabled=True,
           reference_checkpoint=None, fixed_signal_indices=None):
    if type(enabled) is not bool:
        raise RuntimeError('M1_BOOL_REQUIRED')
    if not enabled:
        if fixed_signal_indices is not None:
            raise RuntimeError('M1_DISABLED_FIXED_UNSUPPORTED')
        return parent.replay(rows, bundle, eval_start_ms=eval_start_ms,
                             eval_end_ms=eval_end_ms, reference_checkpoint=reference_checkpoint)
    with patch.object(d, '_path', path):
        if fixed_signal_indices is not None:
            result = d.replay(rows, bundle, eval_start_ms=eval_start_ms, eval_end_ms=eval_end_ms,
                              fixed_signal_indices=fixed_signal_indices)
        else:
            result = parent.replay(rows, bundle, eval_start_ms=eval_start_ms,
                eval_end_ms=eval_end_ms, reference_checkpoint=reference_checkpoint)
    result['audit'].update(rule=RULE_ID, comparison_type='EXIT_CHANGE',
        change_axis='FROZEN_SIGNAL_LOW_COMPLETED_CLOSE_NEXT_OPEN',
        reference_released_by_actual_M1_exit=False,
        original_entry_predicate_unchanged=True, base_D_exits_preserved=True,
        original_exit_rule_unchanged=False, additional_protective_exchange_order=False,
        forced_terminal_liquidations=0, historical_trade_or_exit_inputs=False)
    return result
