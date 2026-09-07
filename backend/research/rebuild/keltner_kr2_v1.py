"""KR2 single-axis repair of frozen KR1; old implementation stays byte-identical."""
from copy import deepcopy
from unittest.mock import patch
from backend.research.rebuild import keltner_kr1_v1 as kr
m2, parent, d = kr.m2, kr.parent, kr.d
BAR, HOLD = kr.BAR, kr.HOLD
UNCHECKED, SUPPRESSED, ALLOWED = kr.UNCHECKED, kr.SUPPRESSED, kr.ALLOWED
decide, DECISION = kr.decide, kr.DECISION
RULE_ID = 'KELTNER_KR2_RUNNER_DECISION_LOW_DEV_V1'
TRIGGER = 'RUNNER_DECISION_LOW_BREACH_CLOSE'
EXIT = 'RUNNER_DECISION_LOW_NEXT_OPEN'

def path(rows, signal, ema20, ema50, end, enabled):
    if not enabled:
        return kr.path(rows, signal, ema20, ema50, end, True)
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
        anchor_hit = extension['allowed'] and j >= native_exit and float(row['close']) < extension['runner_anchor_low']
        if not (ema_hit or active_low or runner_hit or anchor_hit):
            if j == native_exit - 1:
                allowed = float(row['close']) > entry_price and float(row['close']) > ema20[j] > ema50[j]
                extension = {'decided': True, 'allowed': allowed, 'index': j,
                    'ts': row['bar_close_ts'], 'observed_close': row['close'],
                    'entry_price': entry_price, 'ema20': ema20[j], 'ema50': ema50[j]}
                trace.append({'kind': DECISION, 'signal_index': i, **deepcopy(extension)})
                if allowed:
                    extension['runner_anchor_low'] = float(row['low'])
                    trace[-1]['runner_anchor_low'] = extension['runner_anchor_low']
                    final_exit = i + 2 * HOLD
            continue
        pending = {'signal_ts': row['bar_close_ts'], 'signal_index': j,
                   'ema20': ema20[j], 'ema50': ema50[j],
                   'signal_low': signal_low, 'observed_close': row['close'],
                   'low_condition': low_hit, 'ema_condition': ema_hit, 'runner_condition': runner_hit, 'runner_anchor_condition': anchor_hit,
                   'runner_anchor_low': extension.get('runner_anchor_low')}
        # Existing D priority wins when both conditions become known together.
        reason = 'EMA20_NOT_ABOVE_EMA50_NEXT_OPEN' if ema_hit else m2.EXIT if active_low else kr.EXIT if runner_hit else EXIT
        kind = 'TREND_INVALIDATION_CLOSE' if ema_hit else m2.TRIGGER if active_low else kr.TRIGGER if runner_hit else TRIGGER
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


def replay(rows, bundle, *, enabled=True, **kwargs):
    if type(enabled) is not bool:
        raise RuntimeError('KR2_BOOL_REQUIRED')
    if not enabled:
        return kr.replay(rows, bundle, **kwargs)
    with patch.object(kr, 'path', path):
        result = kr.replay(rows, bundle, **kwargs)
    result['audit'].update(rule=RULE_ID,
        anchor_exits=sum(t['kind']==EXIT for t in result['trace']),
        anchor_frozen_at_original_extension_decision=True)
    return result
