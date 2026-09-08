"""One KR3 child: protect an established, research-cost-covered EMA20 zone.

No I/O, market loaders, outcome labels, entry changes, or order authority.
The original KR3 path is retained with one additional completed-close intent.
The frozen research proxy is accrued only through each decision timestamp; it
is not historical actual cost evidence or a guaranteed profitable fill.
"""
from copy import deepcopy
from functools import partial
import math
from unittest.mock import patch

from backend.research.architecture_factory import g5a_development_probe_v1 as probe
from backend.research.rebuild import keltner_kr3_v1 as parent

m2, d = parent.m2, parent.d
BAR, HOLD = parent.BAR, parent.HOLD
UNCHECKED, SUPPRESSED, ALLOWED = parent.UNCHECKED, parent.SUPPRESSED, parent.ALLOWED
DECISION, TRIGGER, EXIT = parent.DECISION, parent.TRIGGER, parent.EXIT
RULE_ID = 'KR3_PROFIT_ZONE_PRESERVATION_EXIT_V1'
GUARD_ARM = 'KR3_PROFIT_ZONE_ARMED_CLOSE'
GUARD_UPDATE = 'KR3_PROFIT_ZONE_LINE_UPDATED_CLOSE'
GUARD_TRIGGER = 'KR3_PROFIT_ZONE_SUPPORT_LOST_CLOSE'
GUARD_EXIT = 'KR3_PROFIT_ZONE_SUPPORT_LOST_NEXT_OPEN'
RULE = ('Original KR3 signal, entry, EMA4*n, reference clock and exits retained. '
        'Arm on held completed close>EMA20>EMA50 and EMA20>entry*(1+decision-time '
        'research roundtrip fee/spread/impact/elapsed absolute funding/floor /10000). '
        'No arming-bar exit. Track running max of completed EMA20 after arming. '
        'Later close below the line known through the previous bar queues next open. '
        'Original timeout, EMA, allowed-low and runner exits retain priority. '
        'Next-open gaps are actual path prices; outside-window intents stay pending.')


def decision_cost(entry_ts, decision_ts, cost_model):
    """Existing DEV proxy through now, with unchanged 20 bps floor.

    A frozen research binding can have been collected after the historical bar.
    decision_ts is the accrual cutoff, NOT a claim about actual data availability.
    The model contains no trade final-exit timestamp or realized total cost.
    """
    if type(entry_ts) is not int or type(decision_ts) is not int or decision_ts < entry_ts:
        raise ValueError('PROFIT_ZONE_COST_CLOCK')
    if not isinstance(cost_model, dict):
        raise ValueError('PROFIT_ZONE_RESEARCH_COST_BINDING_REQUIRED')
    required = ('fee_bps', 'spread_bps', 'impact_bps', 'funding_p95_per_settlement_bps')
    for field in required:
        value = cost_model.get(field)
        if (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
            raise ValueError('PROFIT_ZONE_INVALID_COST_BINDING:' + field)
    parts = probe.cost_components(entry_ts, decision_ts, cost_model)
    parts['frozen_floor_reserve_bps'] = max(0., 20. - parts['cost_bps'])
    parts['cost_bps'] += parts['frozen_floor_reserve_bps']
    parts.update(model_accrual_cutoff_ts=decision_ts,
                 actual_historical_execution_cost_evidence=False)
    return parts


def guard_observation(state, *, row, index, ema20, ema50, entry_price, cost):
    """Return new state and an intent boolean; trigger uses the prior line."""
    close = float(row['close'])
    if not all(math.isfinite(v) and v > 0 for v in (close, ema20, ema50, entry_price)):
        raise ValueError('PROFIT_ZONE_INVALID_OBSERVATION')
    if (state['armed_index'] is None) != (state['protected_line'] is None):
        raise ValueError('PROFIT_ZONE_INVALID_STATE')
    if state['last_index'] is not None and index != state['last_index'] + 1:
        raise ValueError('PROFIT_ZONE_NONCONTIGUOUS_OBSERVATION')
    if cost['model_accrual_cutoff_ts'] != row['bar_close_ts']:
        raise ValueError('PROFIT_ZONE_COST_CUTOFF_MISMATCH')
    current = dict(state, last_index=index)
    if state['exit_requested']:
        return current, False
    if state['armed_index'] is None:
        covered = entry_price * (1. + cost['cost_bps'] / 10000.)
        if close > ema20 > ema50 and ema20 > covered:
            current.update(armed_index=index, armed_ts=row['bar_close_ts'],
                           protected_line=ema20, arming_cost=deepcopy(cost))
        return current, False
    if (state['armed_index'] > state['last_index']
            or not math.isfinite(state['protected_line']) or state['protected_line'] <= 0):
        raise ValueError('PROFIT_ZONE_INVALID_ARMED_STATE')
    if close < state['protected_line']:
        current['exit_requested'] = True
        return current, True
    current['protected_line'] = max(state['protected_line'], ema20)
    return current, False


def path(rows, signal, ema20, ema50, end, enabled, *, cost_model):
    if not enabled:
        return parent.path(rows, signal, ema20, ema50, end, True)
    i = signal['signal_index']; ei = i + 1; native_exit = i + HOLD
    signal_low = float(rows[i]['low'])
    entry_price = float(rows[ei]['open'])
    entry_ts = rows[ei]['bar_open_ts']
    extension = {'decided': False, 'allowed': False}
    final_exit = native_exit
    trace = [{'kind': 'ENTRY_NEXT_OPEN', 'signal_index': i, 'index': ei,
              'ts': entry_ts, 'price': rows[ei]['open'],
              'frozen_signal_low': signal_low, 'feature_available_ts': rows[i]['bar_close_ts']}]
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
                           profit_zone_state=deepcopy(guard))
                return raw, None, trace
            break
        ema_hit = ema20[j] <= ema50[j]
        low_hit = float(row['close']) < signal_low
        if not ema_hit and state['status'] == UNCHECKED and low_hit:
            state = parent.decide(state, row, j, signal_low, ema50[j])
            trace.append({'kind': m2.DECISION, 'signal_index': i, **deepcopy(state)})
        active_low = low_hit and state['status'] == ALLOWED
        runner_hit = extension['allowed'] and j >= native_exit and float(row['close']) <= ema20[j]
        guard_hit = False
        prior_line = guard['protected_line']
        # Existing exits are resolved before the new guard, including its arm.
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
        if not (ema_hit or active_low or runner_hit or guard_hit):
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
        reason = 'EMA20_NOT_ABOVE_EMA50_NEXT_OPEN' if ema_hit else m2.EXIT if active_low else EXIT if runner_hit else GUARD_EXIT
        kind = 'TREND_INVALIDATION_CLOSE' if ema_hit else m2.TRIGGER if active_low else TRIGGER if runner_hit else GUARD_TRIGGER
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
                   profit_zone_state=deepcopy(guard))
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
        runner_planned_exit_index=final_exit, profit_zone_state=deepcopy(guard))
    trace.append({'kind':'TERMINAL_MARK', 'signal_index':i, 'index':raw['mark_index'],
        'ts':raw['mark_ts'], 'price':raw['mark_price'], 'censor_reason':raw['censor_reason'],
        'pending_exit_signal_ts':raw['pending_exit_signal_ts']})
    return None, raw, trace


def replay(rows, bundle, *, eval_start_ms, eval_end_ms, cost_model=None,
           enabled=True, reference_checkpoint=None, fixed_signal_indices=None):
    if type(enabled) is not bool:
        raise ValueError('PROFIT_ZONE_BOOL_REQUIRED')
    kw = dict(eval_start_ms=eval_start_ms, eval_end_ms=eval_end_ms,
              reference_checkpoint=reference_checkpoint, fixed_signal_indices=fixed_signal_indices)
    if not enabled:
        return parent.replay(rows, bundle, **kw)
    decision_cost(eval_start_ms, eval_start_ms, cost_model)
    # Same single-owner scoped hook mechanism as KR3. Reservations use the
    # immutable reference clock; no candidate exits are fed to that clock.
    with patch.object(parent.kr, 'path', partial(path, cost_model=deepcopy(cost_model))):
        out = parent.kr.replay(rows, bundle, **kw)
    out['audit'].update(rule=RULE_ID, mutation='PROFIT_ZONE_EXIT_ONLY',
        original_KR3_entry_reference=True, wait_bars_added=0,
        research_model_is_actual_cost_evidence=False,
        prior_suppression_veto_T=sum(t['kind']==DECISION and t.get('m2_state_at_decision')==SUPPRESSED for t in out['trace']),
        profit_zone_arms=sum(t['kind']==GUARD_ARM for t in out['trace']),
        profit_zone_exits=sum(t['kind']==GUARD_EXIT for t in out['trace']))
    return out
