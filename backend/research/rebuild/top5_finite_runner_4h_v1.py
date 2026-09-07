"""SR1/BR1 timeout-only runner over exact frozen V2 signals and ownership.

Neither host has an executable SL/TP. FULL keeps native exit-bar ownership;
FIXED independently evaluates parent entries and can overlap.
"""
from copy import deepcopy
from unittest.mock import patch
from backend.research.rebuild import parallel_exit_keltner_v1 as base

RULES = {'SR1': 'SUPERTREND_V2_FINITE_RUNNER_SR1_DEV_V1',
         'BR1': 'BREAK_V2_FINITE_RUNNER_BR1_DEV_V1'}
PARENTS = {'SR1': 'supertrend_replacement_highvol_mom_long_4h_h12_v2',
           'BR1': 'break_replacement_breakout50_long_4h_h6_v2'}
DECISION = 'RUNNER_T_MINUS_ONE_DECISION'
EXIT = 'RUNNER_TREND_LOSS_NEXT_OPEN'


def specification(kind):
    return next(c for c in base.old.read(base.old.FREEZE)['children']
                if c['child_id'] == PARENTS[kind])


def build_bundle(rows, spec, start, end):
    base._validate_rows(rows, start, end)
    arrays, engine = base.old.dsl._features(
        [dict(r, ts=r['bar_open_ts']) for r in rows], spec)
    signals = [{'signal_index': i, 'signal_ts': rows[i]['bar_close_ts']}
               for i in range(239, len(rows))
               if start <= rows[i]['bar_close_ts'] < end
               and bool(engine.eval(spec['entry_rule'], i))]
    return {'signals': signals, 'ema20': arrays['ema20'], 'ema50': arrays['ema50']}


def path(rows, signal, ema20, ema50, end, enabled):
    i = signal['signal_index']; ei = i + 1; native = i + base.HOLD
    final = native; extension = {'decided': False, 'allowed': False}
    trace = [{'kind': 'ENTRY_NEXT_OPEN', 'signal_index': i, 'index': ei,
              'ts': rows[ei]['bar_open_ts'], 'price': rows[ei]['open']}]
    pending = None
    for j in range(ei, min(i + 2*base.HOLD, len(rows)-1)+1):
        row = rows[j]
        if j == final:
            if row['bar_close_ts'] < end:
                raw = base._geometry(rows, i, j, end)
                trace.append({'kind': 'RUNNER_FINAL_TIME_STOP_CLOSE' if extension['allowed']
                              else 'ORIGINAL_TIME_STOP_CLOSE', 'signal_index': i,
                              'index': j, 'ts': raw['exit_ts'], 'price': raw['exit_price']})
                if enabled: raw['runner_extension'] = deepcopy(extension)
                return raw, None, trace
            break
        if not enabled:
            continue
        if j == native-1:
            allowed = row['close'] > rows[ei]['open'] and row['close'] > ema20[j] > ema50[j]
            extension = {'decided': True, 'allowed': allowed, 'index': j,
                         'ts': row['bar_close_ts'], 'observed_close': row['close'],
                         'entry_price': rows[ei]['open'], 'ema20': ema20[j], 'ema50': ema50[j]}
            trace.append({'kind': DECISION, 'signal_index': i, **extension})
            if allowed: final = native + base.HOLD
        if not (extension['allowed'] and j >= native
                and (row['close'] <= ema20[j] or ema20[j] <= ema50[j])):
            continue
        pending = {'signal_ts': row['bar_close_ts'], 'signal_index': j,
                   'observed_close': row['close'], 'ema20': ema20[j], 'ema50': ema50[j]}
        trace.append({'kind': 'RUNNER_TREND_LOSS_CLOSE', 'signal_index': i,
                      'index': j, 'ts': row['bar_close_ts'], 'observation': deepcopy(pending)})
        xi = j+1
        if xi >= len(rows) or rows[xi]['bar_open_ts'] >= end: break
        raw = base._geometry(rows, i, j, end); price = float(rows[xi]['open'])
        gross = (price/raw['entry_price']-1)*10000
        raw.update(exit_index=xi, exit_ts=rows[xi]['bar_open_ts'], exit_price=price,
                   gross_bps=gross, hold_ms=rows[xi]['bar_open_ts']-raw['entry_ts'],
                   mfe_bps=max(raw['mfe_bps'], gross, 0.), mae_bps=min(raw['mae_bps'], gross, 0.),
                   exit_reason=EXIT, exit_timestamp_semantics='OBSERVED_4H_OPEN',
                   excursion_semantics='HELD_COMPLETE_BARS_PLUS_EXIT_OPEN_ONLY',
                   exit_trigger=deepcopy(pending), runner_extension=deepcopy(extension))
        trace.append({'kind': EXIT, 'signal_index': i, 'index': xi,
                      'ts': raw['exit_ts'], 'price': price})
        return raw, None, trace
    raw = base._geometry(rows, i, len(rows)-1, end)
    for a,b in (('exit_index','mark_index'), ('exit_ts','mark_ts'),
                ('exit_price','mark_price'), ('gross_bps','gross_mark_bps')):
        raw[b] = raw.pop(a)
    raw.update(status='CENSORED', terminal_liquidation=False, native_hold_bars=base.HOLD,
               native_planned_exit_ts=rows[ei]['bar_open_ts']+base.HOLD*base.BAR,
               original_protective_sl=None, native_geometry_scope='FROZEN_V2_FIXED_HOLD_NO_NATIVE_SL_SPECIFIED',
               censor_reason='ORIGINAL_STRICT_END_TIMEOUT_AT_BOUNDARY' if final==len(rows)-1 else 'NATIVE_HOLD_UNFINISHED',
               pending_exit_signal_ts=pending['signal_ts'] if pending else None,
               pending_exit_trigger=deepcopy(pending), runner_extension=deepcopy(extension),
               runner_planned_exit_index=final)
    trace.append({'kind':'TERMINAL_MARK','signal_index':i,'index':raw['mark_index'],
                  'ts':raw['mark_ts'],'price':raw['mark_price']})
    return None, raw, trace


def replay(rows, bundle, *, kind, eval_start_ms, eval_end_ms, enabled=True,
           fixed_signal_indices=None):
    if type(enabled) is not bool: raise RuntimeError('FINITE_RUNNER_BOOL_REQUIRED')
    hold = 12 if kind == 'SR1' else 6
    if kind not in RULES: raise RuntimeError('UNKNOWN_FROZEN_HOST')
    with patch.object(base, 'HOLD', hold), patch.object(base, '_path', path):
        out = base.replay(rows, bundle, eval_start_ms=eval_start_ms, eval_end_ms=eval_end_ms,
                          enable_change=enabled, fixed_signal_indices=fixed_signal_indices)
    out['audit'].update(rule=RULES[kind], parent_id=PARENTS[kind], original_max_hold_bars=hold,
        maximum_hold_bars=2*hold if enabled else hold,
        extension_decisions=sum(t['kind']==DECISION for t in out['trace']),
        extension_allowed_T=sum(t['kind']==DECISION and t['allowed'] for t in out['trace']),
        native_SL=None, native_TP=None, reference_clock='NATIVE_EXIT_BAR_OWNERSHIP',
        signal_preparation_changed=False)
    return out
