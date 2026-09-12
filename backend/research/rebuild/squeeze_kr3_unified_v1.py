"""Squeeze/KR3 component synthesis for Issue #1291.

Core: exact C70_TM_CAPREUSE_V1 lifecycle/occupancy.
K1: C54 lagged-ATR entry-location quality, transplanted unchanged in meaning.
K2: C51 EMA20 profit-zone protection, conservatively limited to post-partial residual.

Pure USED_DEV research. No I/O, orders, network, threshold search, or production authority.
"""
from copy import deepcopy
from fractions import Fraction
from math import fsum, isfinite

from backend.research.rebuild import c70_tm_capreuse_v1 as core
from backend.research.rebuild import c63_c70_trader_management_v1 as tm
from backend.research.rebuild import chart_mechanism_features_v1 as cf
from backend.research.rebuild import kr3_profit_zone_exit_v1 as kz

SCOPE = 'SQUEEZE_KR3_TRUE_COMPONENT_UNIFIED_AFTER_TOP6_V1'
VARIANTS = ('U1', 'U2', 'U3')
RULES = {
    'U1': 'SQUEEZE_CAPREUSE_PLUS_C54_ATR_ENTRY_V1',
    'U2': 'SQUEEZE_CAPREUSE_PLUS_C51_POSTPARTIAL_PROFIT_ZONE_V1',
    'U3': 'SQUEEZE_CAPREUSE_PLUS_C54_ATR_ENTRY_PLUS_C51_POSTPARTIAL_PROFIT_ZONE_V1',
}
K1_VETO = 'C54_LAGGED_ATR_ENTRY_LOCATION_VETO'
K2_ARM = 'C51_PROFIT_ZONE_ARMED_POSTPARTIAL_CLOSE'
K2_UPDATE = 'C51_PROFIT_ZONE_LINE_UPDATED_POSTPARTIAL_CLOSE'
K2_TRIGGER = 'C51_PROFIT_ZONE_SUPPORT_LOST_POSTPARTIAL_CLOSE'
K2_EXIT = 'C51_PROFIT_ZONE_SUPPORT_LOST_POSTPARTIAL_NEXT_OPEN'


def _averages(bars):
    close = [b.close for b in bars]
    ema20 = cf._average(close, 20, 2 / 21)
    ema50 = cf._average(close, 50, 2 / 51)
    tr = [max(b.high - b.low, abs(b.high - bars[i - 1].close), abs(b.low - bars[i - 1].close))
          for i, b in enumerate(bars) if i]
    atr14 = [None] + cf._average(tr, 14, 1 / 14) if bars else []
    return ema20, ema50, atr14


def k1_values(signal_close, ema20, atr_previous):
    if any(v is None for v in (signal_close, ema20, atr_previous)):
        return dict(available=False, eligible=False, extension_atr=None)
    values = (float(signal_close), float(ema20), float(atr_previous))
    if not all(isfinite(v) for v in values) or values[2] <= 0:
        return dict(available=False, eligible=False, extension_atr=None)
    extension = (values[0] - values[1]) / values[2]
    return dict(available=True, eligible=bool(0 < extension <= 1), extension_atr=extension,
                signal_close=values[0], ema20=values[1], atr_previous=values[2],
                rule='0<(signal_close-EMA20)/previous_bar_Wilder_ATR14<=1')


def k1_observation(bars, index, averages=None):
    ema20, _, atr14 = averages or _averages(bars)
    prior = atr14[index - 1] if index > 0 and index - 1 < len(atr14) else None
    out = k1_values(bars[index].close, ema20[index] if index < len(ema20) else None, prior)
    out.update(signal_index=index, available_at=bars[index].open_ts + tm.BAR,
               atr_available_at=bars[index - 1].open_ts + tm.BAR if index > 0 else None)
    return out


def _new_guard():
    return dict(armed_index=None, armed_ts=None, protected_line=None,
                last_index=None, exit_requested=False, arming_cost=None)


def k2_step(state, *, bar, index, ema20, ema50, entry_price, entry_ts, cost):
    """C51 guard semantics on a post-partial residual only; trigger uses prior line."""
    current = deepcopy(state)
    current['last_index'] = index
    if current['exit_requested']:
        return current, False, None
    if ema20 is None or ema50 is None:
        return current, False, None
    close = float(bar.close)
    if not all(isfinite(v) and v > 0 for v in (close, ema20, ema50, entry_price)):
        raise ValueError('SQUEEZE_KR3_INVALID_PROFIT_ZONE_OBSERVATION')
    stamp = bar.open_ts + tm.BAR
    decision_cost = kz.decision_cost(entry_ts, stamp, cost)
    if current['armed_index'] is None:
        covered = entry_price * (1 + decision_cost['cost_bps'] / 10000)
        if close > ema20 > ema50 and ema20 > covered:
            current.update(armed_index=index, armed_ts=stamp, protected_line=ema20,
                           arming_cost=deepcopy(decision_cost))
            return current, False, K2_ARM
        return current, False, None
    prior = current['protected_line']
    if prior is None or not isfinite(prior) or prior <= 0:
        raise ValueError('SQUEEZE_KR3_INVALID_PROFIT_ZONE_STATE')
    if close < prior:
        current['exit_requested'] = True
        return current, True, K2_TRIGGER
    current['protected_line'] = max(prior, ema20)
    return current, False, K2_UPDATE if current['protected_line'] != prior else None


def position(bars, signal, variant, features, end, cost, *, enable_k2=False):
    """Exact source manager plus optional post-partial residual K2 guard."""
    if not enable_k2:
        return tm.position(bars, signal, variant, features, end, cost)
    if variant != 'M1':
        raise ValueError('NATIVE_M1_ONLY')
    ema20, ema50, _ = _averages(bars)
    i = signal['signal_index']; ei = i + 1; entry = bars[ei]
    legs = []; trace = []; qty = 1.; pending = None; managed = False; runner = False
    daily_count = 0; closed = False; final_reason = None; partial_count = 0
    guard = _new_guard()
    trace.append(dict(kind='ENTRY_NEXT_OPEN', ts=entry.open_ts, index=ei, price=entry.open,
                      qty=1., floor=signal['floor'], signal_index=i))

    def leg(j, fraction, reason, status='C'):
        b = bars[j]; px = b.open if status == 'C' else b.close
        stamp = b.open_ts if status == 'C' else b.open_ts + tm.BAR
        return dict(status=status, qty=fraction, index=j, ts=stamp, price=px, reason=reason)

    for j in range(ei, len(bars)):
        row = bars[j]
        if pending is not None and row.open_ts < end:
            if pending['action'] == 'PARTIAL':
                legs.append(leg(j, 1 / 3, 'D3_PROFIT_PARTIAL_NEXT_OPEN'))
                qty -= 1 / 3; runner = True; partial_count += 1
                trace.append(dict(kind='PARTIAL_FILL', ts=row.open_ts, index=j, price=row.open,
                                  qty=1 / 3, remaining_qty=qty, decision=deepcopy(pending),
                                  slot_released=False, signal_index=i))
                if pending.get('exit_remainder'):
                    final_reason = pending['exit_remainder'] + '_NEXT_OPEN'
                    legs.append(leg(j, qty, final_reason)); qty = 0.; closed = True
                    trace.append(dict(kind='FINAL_FILL', ts=row.open_ts, index=j, price=row.open,
                                      remaining_qty=0., decision=deepcopy(pending), slot_released=True,
                                      signal_index=i))
                    break
            else:
                legs.append(leg(j, qty, pending['reason'] + '_NEXT_OPEN'))
                qty = 0.; closed = True; final_reason = legs[-1]['reason']
                trace.append(dict(kind='FINAL_FILL', ts=row.open_ts, index=j, price=row.open,
                                  remaining_qty=0., decision=deepcopy(pending), slot_released=True,
                                  signal_index=i))
                break
            pending = None
        stamp = row.open_ts + tm.BAR
        obs = tm.daily_observation(bars, j)
        if obs['is_daily_close'] and stamp > entry.open_ts:
            daily_count += 1
        reason = 'FIXED_FLOOR_CLOSE' if row.close <= signal['floor'] else None
        if reason is None and runner and row.close <= entry.open:
            reason = 'RUNNER_BREAKEVEN_CLOSE'
        if reason is None and not runner and features[j]['momentum'] <= 0:
            reason = 'MOMENTUM_NONPOSITIVE_CLOSE'
        first_management = obs['is_daily_close'] and daily_count == 3 and not managed
        net_progress = (row.close / entry.open - 1) * 10000 - tm.cost_at(cost, entry.open_ts, stamp)
        if first_management:
            managed = True
        if reason is None and runner and obs['is_daily_close']:
            if obs['sma10'] is None:
                reason = 'RUNNER_DAILY_HISTORY_SAFETY_CLOSE'
            elif row.close < obs['sma10']:
                reason = 'RUNNER_SMA10_CLOSE'
        k2_event = None; k2_hit = False; prior_line = guard['protected_line']
        if reason is None and runner:
            guard, k2_hit, k2_event = k2_step(guard, bar=row, index=j,
                ema20=ema20[j], ema50=ema50[j], entry_price=entry.open,
                entry_ts=entry.open_ts, cost=cost)
            if k2_event is not None:
                trace.append(dict(kind=k2_event, ts=stamp, index=j, close=row.close,
                                  ema20=ema20[j], ema50=ema50[j], signal_index=i,
                                  prior_protected_line=prior_line,
                                  protected_line=guard['protected_line']))
            if k2_hit:
                reason = K2_TRIGGER
        if reason is not None:
            pending = dict(action='FINAL', reason=K2_EXIT[:-10] if reason == K2_TRIGGER else reason,
                           signal_index=j, signal_ts=stamp)
        elif first_management and net_progress > 0:
            pending = dict(action='PARTIAL', reason='D3_PROFIT', signal_index=j, signal_ts=stamp)
            if obs['sma10'] is None or row.close < obs['sma10']:
                pending['exit_remainder'] = 'D3_SMA10_SAFETY_CLOSE'
        trace.append(dict(kind='HELD_CLOSE_OBSERVATION', ts=stamp, index=j, close=row.close,
                          floor=signal['floor'], momentum=features[j]['momentum'],
                          held_bars=j - ei + 1, daily_count=daily_count,
                          first_management=first_management, net_progress_bps=net_progress,
                          runner=runner, remaining_qty=qty, daily=obs,
                          profit_zone=deepcopy(guard), pending=deepcopy(pending), signal_index=i))
    if not closed:
        legs.append(leg(j, qty, 'TERMINAL_MARK', 'O'))
        trace.append(dict(kind='TERMINAL_MARK', ts=bars[j].open_ts + tm.BAR, index=j,
                          price=bars[j].close, remaining_qty=qty, slot_released=False,
                          signal_index=i))
    last = legs[-1]; held = bars[ei:j if closed else j + 1]
    gross = fsum(l['qty'] * (l['price'] / entry.open - 1) * 10000 for l in legs)
    raw = dict(signal_index=i, signal_ts=signal['signal_ts'], entry_index=ei,
               entry_ts=entry.open_ts, entry_price=entry.open, side='long',
               hold_ms=last['ts'] - entry.open_ts,
               mfe_bps=max([0., (last['price'] / entry.open - 1) * 10000] +
                           [(b.high / entry.open - 1) * 10000 for b in held]),
               mae_bps=min([0., (last['price'] / entry.open - 1) * 10000] +
                           [(b.low / entry.open - 1) * 10000 for b in held]),
               setup_id=signal['setup_id'], fixed_floor=signal['floor'], fixed_target=signal['target'],
               original_protective_sl=None, exchange_resident_stop=False,
               excursion_semantics='UNDERLYING_UNSCALED_PATH_NOT_WEIGHTED_CAMPAIGN_RETURN',
               tm_legs=legs, assembled_qty=1., remaining_qty=qty, partial_count=partial_count,
               runner_activated=runner, exit_trigger=deepcopy(pending),
               profit_zone_state=deepcopy(guard))
    if closed:
        raw.update(exit_index=last['index'], exit_ts=last['ts'], exit_price=last['price'],
                   gross_bps=gross, exit_reason=final_reason,
                   exit_timestamp_semantics='OBSERVED_4H_OPEN')
        return raw, None, trace
    raw.update(mark_index=last['index'], mark_ts=last['ts'], mark_price=last['price'],
               gross_mark_bps=gross, status='CENSORED', terminal_liquidation=False,
               censor_reason='PENDING_EXIT_OUTSIDE_WINDOW' if pending else 'HOLD_UNFINISHED',
               pending_exit_trigger=deepcopy(pending))
    return None, raw, trace


def replay(rows, *, eval_start_ms, eval_end_ms, cost, variant='U3', enabled=True):
    if variant not in VARIANTS:
        raise ValueError('SQUEEZE_KR3_VARIANT')
    if type(enabled) is not bool:
        raise ValueError('SQUEEZE_KR3_ENABLED_BOOL')
    if not enabled:
        return core.replay(rows, eval_start_ms=eval_start_ms, eval_end_ms=eval_end_ms,
                           cost=cost, enabled=True)
    use_k1 = variant in ('U1', 'U3'); use_k2 = variant in ('U2', 'U3')
    bars = tm.native.to_bars(rows, eval_start_ms, eval_end_ms)
    original, setup_log, features = tm.native.m1_setups(bars)
    averages = _averages(bars)
    signals = [s for s in original if eval_start_ms <= s['signal_ts'] <= eval_end_ms]
    if [s['signal_ts'] for s in signals] != sorted(set(s['signal_ts'] for s in signals)):
        raise ValueError('ORIGINAL_SIGNAL_CLOCK_NOT_STRICTLY_ORDERED')
    result = dict(trades=[], open_positions=[], events=[], trace=[], setup_events=setup_log,
                  pending_entries=[])
    campaigns = []
    for signal in signals:
        i = signal['signal_index']; ei = i + 1; stamp = signal['signal_ts']
        obs = tm.c70_context(tm.c63.context(bars, signal, tm.c63.er.context),
                             tm.daily.observation(bars, i))
        k1 = k1_observation(bars, i, averages)
        active, available = core.capacity(campaigns, stamp)
        event = dict(deepcopy(signal), admission=False, status='EXCLUDED', exclusion_reason=None,
                     er_context=obs, c54_entry_context=k1,
                     active_normalized_qty=float(active), available_capacity=float(available),
                     available_fraction=[available.numerator, available.denominator],
                     decision_phase='CLOSE_BEFORE_EQUAL_TIMESTAMP_OPEN_FILLS',
                     capacity_reuse_entry=False, entry_normalized_qty=0.)
        if available <= 0:
            reason = core.OCCUPIED
        elif signal['expiry'] is not None and stamp >= signal['expiry']:
            reason = 'SETUP_EXPIRED_BEFORE_ENTRY'
        elif not obs['eligible']:
            reason = obs['reason']
        elif use_k1 and not k1['eligible']:
            reason = K1_VETO
        elif ei >= len(bars) or bars[ei].open_ts >= eval_end_ms:
            reason = 'NO_NEXT_OPEN_IN_APPROVED_WINDOW'
        elif bars[ei].open <= signal['floor'] or signal['target'] is not None and bars[ei].open >= signal['target']:
            reason = 'GAP_INVALIDATES_FIXED_SETUP'
        else:
            reason = None
        event['exclusion_reason'] = reason
        if reason is None:
            qty = min(Fraction(1), available)
            before_open, _ = core.capacity(campaigns, stamp, include_equal=True)
            if before_open + qty > 1:
                raise AssertionError('ENTRY_EXCEEDS_ACTUAL_AVAILABLE_CAPACITY')
            trade, opened, trace = position(bars, signal, 'M1', features, eval_end_ms, cost,
                                             enable_k2=use_k2)
            raw = trade if trade is not None else opened
            raw.update(allocation_numerator=qty.numerator, allocation_denominator=qty.denominator,
                       allocated_normalized_qty=float(qty), capacity_reuse_entry=active > 0,
                       squeeze_kr3_variant=variant)
            for t in trace:
                t['allocation_numerator'] = qty.numerator
                t['allocation_denominator'] = qty.denominator
                if 'qty' in t:
                    t['normalized_fill_qty'] = float(qty) * t['qty']
                if 'remaining_qty' in t:
                    t['remaining_normalized_qty'] = float(qty) * t['remaining_qty']
            result['trades' if trade is not None else 'open_positions'].append(raw)
            result['trace'].extend(trace); campaigns.append(raw)
            event.update(admission=True, status='COMPLETED' if trade is not None else 'CENSORED',
                         entry_normalized_qty=float(qty), capacity_reuse_entry=active > 0,
                         active_after_entry=float(before_open + qty))
        elif reason == 'NO_NEXT_OPEN_IN_APPROVED_WINDOW':
            result['pending_entries'].append(deepcopy(event))
        result['events'].append(event)
    stamps = sorted({r['entry_ts'] for r in campaigns} |
                    {l['ts'] for r in campaigns for l in r['tm_legs'] if l['status'] == 'C'})
    result['capacity_timeline'] = [dict(ts=t, active_after_open=float(core.capacity(campaigns, t, include_equal=True)[0]))
                                   for t in stamps]
    excluded = sum(not e['admission'] for e in result['events'])
    if len(campaigns) + excluded != len(signals):
        raise AssertionError('SIGNAL_ACCOUNTING')
    result['audit'] = dict(rule=RULES[variant], scope=SCOPE,
        core_rule=core.RULE, entry_rule=tm.C70_RULE, use_k1=use_k1, use_k2=use_k2,
        raw_signals=len(signals), completed=len(result['trades']), open=len(result['open_positions']),
        excluded=excluded, k1_veto_T=sum(e['exclusion_reason'] == K1_VETO for e in result['events']),
        k2_arm_T=sum(t['kind'] == K2_ARM for t in result['trace']),
        k2_trigger_T=sum(t['kind'] == K2_TRIGGER for t in result['trace']),
        capacity_reuse_entries=sum(r['capacity_reuse_entry'] for r in campaigns),
        same_symbol_max_normalized_qty=1., comparison_mode='FULL_CHRONOLOGICAL',
        fresh_flat_start=True, independent=False, formal_credit=0,
        new_exchange_orders=0, production_compatibility=False)
    return result
