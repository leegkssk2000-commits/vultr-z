"""Four frozen source-component predicates; no replay, accounting, I/O or orders.

The caller owns actual fills, native safety/exit priority, costs and next-open
execution.  ``runner_active`` means this lot's profit partial actually filled.
Every call observes one completed bar; state belongs to one entry campaign.
Source numerical periods are not a claim of full source-strategy replication.
"""
from copy import deepcopy
from math import fsum, isfinite

from backend.research.rebuild import chart_mechanism_features_v1 as f

BAR, DAY = f.BAR_MS, f.DAY_MS
REGISTRY = {
    'S1-02': dict(axis='RUNNER_EXIT', mode='REPLACE_RUNNER',
                  mechanism='BASSO_EDUCATIONAL_SMA5_10_RUNNER_V1',
                  reason='BASSO_SMA5_BELOW_SMA10_CLOSE', performance_grade='C',
                  clock='COMPLETED_UTC_DAY', fast_sma=5, slow_sma=10,
                  activation='AFTER_ACTUAL_PROFIT_PARTIAL_FILL',
                  source_grade='C'),
    'S1-03': dict(axis='RUNNER_EXIT', mode='ADD_EXIT',
                  mechanism='RASCHKE_3_10_RUNNER_DIVERGENCE',
                  reason='RASCHKE_NEW_CLOSE_HIGH_LOWER_3_10_OSCILLATOR', performance_grade='C',
                  clock='COMPLETED_NATIVE_4H', fast_sma=3, slow_sma=10,
                  anchor='STRICT_RUNNING_CLOSE_RECORD_SINCE_ACTUAL_ENTRY',
                  activation='AFTER_ACTUAL_PROFIT_PARTIAL_FILL',
                  source_grade='C'),
    'S1-04': dict(axis='INITIAL_FAILURE_EXIT', mode='ADD_EXIT',
                  mechanism='CARTER_INITIAL_THRUST_FAILURE',
                  reason='CARTER_FOUR_BAR_NET_NONPOSITIVE_CLOSE', performance_grade='C',
                  clock='COMPLETED_NATIVE_4H', initial_thrust_bars=4,
                  activation='FOURTH_COMPLETED_ENTRY_BAR_ONCE',
                  source_grade='C'),
    'S1-07': dict(axis='RUNNER_EXIT', mode='REPLACE_RUNNER',
                  mechanism='MARTIN_LUK_DAILY_EMA9_RUNNER_V1',
                  reason='MARTIN_LUK_DAILY_EMA9_CLOSE', performance_grade='A',
                  rule_source='PRIMARY_TRADER_AUTHORED_GUEST_POST',
                  clock='COMPLETED_UTC_DAY', ema_period=9,
                  ema_seed='SMA_FIRST9_COMPLETE_UTC_DAILY_CLOSES_THEN_ALPHA_2_OVER10',
                  activation='AFTER_ACTUAL_PROFIT_PARTIAL_FILL',
                  source_grade='A'),
}
COMPONENTS = REGISTRY


def _prefix(rows, index):
    """Validate only observations already available, never any future row."""
    if type(index) is not int or not 0 <= index < len(rows):
        raise ValueError('COMPONENT_INDEX')
    bars = []
    for row in rows[:index + 1]:
        stamp = row['bar_open_ts']
        if row.get('bar_close_ts', stamp + BAR) != stamp + BAR:
            raise ValueError('COMPONENT_CLOSE_TIMESTAMP')
        bars.append(f.Bar(stamp, row['open'], row['high'], row['low'],
                          row['close'], row['volume']))
    f.validate(bars)
    return bars


def _days(bars):
    stamp = bars[-1].open_ts + BAR
    first = next((j for j, b in enumerate(bars) if b.open_ts % DAY == 0), len(bars))
    days = f.completed_utc_days(bars[first:], stamp) if first < len(bars) else []
    values = [d.close for d in days]
    return values, dict(available_at=stamp, is_daily_close=stamp % DAY == 0,
                       completed_days=len(days), leading_partial_bars=first,
                       last_daily_available_at=days[-1].open_ts + DAY if days else None,
                       day_definition='UTC_00_TO_24_SIX_COMPLETE_NATIVE_4H_BARS')


def _oscillator(bars, index):
    if index < 9:
        return None
    return fsum(b.close for b in bars[index - 2:index + 1]) / 3 - \
        fsum(b.close for b in bars[index - 9:index + 1]) / 10


def observe(slot, rows, index, entry_index, entry_price, runner_active, state,
            net_progress_bps):
    """Return a causal close decision, leaving fills/capacity to the caller.

    ``state`` is namespaced by source slot and bound to this actual entry. Calls
    at an unchanged index are idempotent; backwards observations are rejected.
    Daily-history shortages are exposed, not substituted with shorter periods.
    The caller retains the parent's existing daily-history safety exit.
    """
    if slot not in REGISTRY:
        raise ValueError('UNKNOWN_SOURCE_COMPONENT')
    if type(entry_index) is not int or not 0 <= entry_index <= index:
        raise ValueError('COMPONENT_ENTRY_INDEX')
    if (isinstance(entry_price, bool) or not isinstance(entry_price, (int, float))
            or not isfinite(entry_price) or entry_price <= 0):
        raise ValueError('COMPONENT_ENTRY_PRICE')
    if type(runner_active) is not bool or not isinstance(state, dict):
        raise ValueError('COMPONENT_ACTUAL_RUNNER_STATE')
    if (isinstance(net_progress_bps, bool)
            or not isinstance(net_progress_bps, (int, float))
            or not isfinite(net_progress_bps)):
        raise ValueError('COMPONENT_NET_PROGRESS')
    bars = _prefix(rows, index)
    if entry_price != bars[entry_index].open:
        raise ValueError('COMPONENT_ACTUAL_ENTRY_PRICE_MISMATCH')
    identity = [entry_index, bars[entry_index].open_ts, entry_price]
    own = state.setdefault(slot, {'entry_identity': identity})
    if own['entry_identity'] != identity:
        raise ValueError('COMPONENT_STATE_BELONGS_TO_ANOTHER_LOT')
    if index < own.get('last_index', entry_index - 1):
        raise ValueError('COMPONENT_BACKWARDS_OBSERVATION')
    if index == own.get('last_index'):
        if own['last_inputs'] != [runner_active, net_progress_bps, bars[-1].close]:
            raise ValueError('COMPONENT_REVISED_COMPLETED_OBSERVATION')
        return deepcopy(own['last_result'])

    current = bars[index]
    features = dict(index=index, available_at=current.open_ts + BAR,
                    close=current.close, entry_index=entry_index,
                    actual_partial_filled=runner_active)
    trigger = False
    reason = None
    if slot in ('S1-02', 'S1-07'):
        values, daily = _days(bars)
        features.update(daily)
        if slot == 'S1-02':
            fast = fsum(values[-5:]) / 5 if len(values) >= 5 else None
            slow = fsum(values[-10:]) / 10 if len(values) >= 10 else None
            features.update(sma5=fast, sma10=slow, history_available=slow is not None)
            trigger = bool(runner_active and daily['is_daily_close']
                           and slow is not None and fast < slow)
            reason = 'BASSO_SMA5_BELOW_SMA10_CLOSE' if trigger else None
        else:
            ema = f._average(values, 9, 2 / 10)
            value = ema[-1] if ema else None
            features.update(ema9=value, ema_period=9,
                            ema_seed=REGISTRY[slot]['ema_seed'],
                            history_available=value is not None)
            trigger = bool(runner_active and daily['is_daily_close']
                           and value is not None and current.close < value)
            reason = 'MARTIN_LUK_DAILY_EMA9_CLOSE' if trigger else None
        features['data_safety_required'] = bool(runner_active and daily['is_daily_close']
                                                and not features['history_available'])
    elif slot == 'S1-03':
        # Seed from this actual entry, even when the first call is post-partial.
        # Missing calls only update historical anchors; no late exit is invented.
        for k in range(own.get('last_index', entry_index - 1) + 1, index):
            if 'record_close' not in own or bars[k].close > own['record_close']:
                own.update(record_close=bars[k].close, record_oscillator=_oscillator(bars, k),
                           record_index=k)
        oscillator = _oscillator(bars, index)
        prior_close = own.get('record_close')
        prior_oscillator = own.get('record_oscillator')
        prior_index = own.get('record_index')
        new_record = prior_close is not None and current.close > prior_close
        trigger = bool(runner_active and new_record and oscillator is not None
                       and prior_oscillator is not None and oscillator < prior_oscillator)
        reason = 'RASCHKE_NEW_CLOSE_HIGH_LOWER_3_10_OSCILLATOR' if trigger else None
        features.update(oscillator=oscillator, fast_sma=3, slow_sma=10,
                        prior_record_close=prior_close,
                        prior_record_oscillator=prior_oscillator,
                        prior_record_index=prior_index, new_strict_record=new_record,
                        anchor=REGISTRY[slot]['anchor'],
                        history_available=oscillator is not None and prior_oscillator is not None)
        # Comparison precedes update; equal closing prices never replace anchor.
        if prior_close is None or current.close > prior_close:
            own.update(record_close=current.close, record_oscillator=oscillator,
                       record_index=index)
    else:
        checkpoint = entry_index + 3
        due = index == checkpoint and not own.get('checkpoint_consumed', False)
        if index >= checkpoint:
            own['checkpoint_consumed'] = True
        trigger = bool(due and net_progress_bps <= 0)
        reason = 'CARTER_FOUR_BAR_NET_NONPOSITIVE_CLOSE' if trigger else None
        features.update(held_bars=index - entry_index + 1, checkpoint_index=checkpoint,
                        checkpoint_due=due, checkpoint_consumed=own.get('checkpoint_consumed', False),
                        checkpoint_missed=index > checkpoint and own.get('last_index', entry_index - 1) < checkpoint,
                        net_progress_bps=net_progress_bps, initial_thrust_bars=4)
    result = dict(trigger=trigger, reason=reason, features=features,
                  source_slot=slot, axis=REGISTRY[slot]['axis'])
    own.update(last_index=index, last_inputs=[runner_active, net_progress_bps, current.close],
               last_result=deepcopy(result))
    return result
