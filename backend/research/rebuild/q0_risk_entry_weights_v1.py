"""Causal, bounded entry notional weights for the single approved Q0 study.

This module neither runs a strategy nor reads outcomes. All prices supplied by
the existing DEV loader remain subject to its original data boundary. Completed
UTC days reuse the original six-bar aggregator; no basket member is dropped.
The 30-return window and full pre-evaluation reference are fixed design priors.
"""
from __future__ import annotations

from bisect import bisect_right
import math
import statistics

from backend.research.rebuild import break_channel_structure_v1 as structure
from backend.research.rebuild import top5_diverse_batch_execution_v1 as previous

DAY = structure.DAY
WINDOW_RETURNS = 30
BASKET_SIZE = 7
ORIGIN = previous.source_key


def _positive_finite(value, label):
    if (isinstance(value, bool) or not isinstance(value, (float, int))
            or not math.isfinite(value) or value <= 0):
        raise RuntimeError(label)
    return float(value)


def _sample_sigma(values, label):
    if len(values) < 2:
        raise RuntimeError(label + '_INSUFFICIENT_RETURNS')
    if any(isinstance(value, bool) or not isinstance(value, (float, int))
           or not math.isfinite(value) for value in values):
        raise RuntimeError(label + '_NONFINITE_RETURN')
    return _positive_finite(statistics.stdev(values), label + '_ZERO_OR_INVALID')


def market_state(rows_by_symbol, symbols, eval_start_ms, eval_end_ms):
    """Return the complete fixed-universe daily basket and causal reference.

    A return ending at time t first becomes available at t. Reference returns
    require t < eval_start_ms; entry windows separately allow t == signal_ts,
    matching Q0's already-closed confirmation followed by next-open execution.
    Partial edge days are audited and excluded by the shared aggregator. A
    missing interior day or a differing constituent calendar is fatal.
    """
    if (not isinstance(symbols, (list, tuple)) or len(symbols) != BASKET_SIZE
            or any(not isinstance(symbol, str) or not symbol for symbol in symbols)
            or len(set(symbols)) != BASKET_SIZE):
        raise RuntimeError('RISK_FIXED_SEVEN_SYMBOLS_REQUIRED')
    symbols = tuple(symbols)
    if not isinstance(rows_by_symbol, dict) or set(rows_by_symbol) != set(symbols):
        raise RuntimeError('RISK_BASKET_CONSTITUENT_SET_MISMATCH')
    if (type(eval_start_ms) is not int or type(eval_end_ms) is not int
            or eval_start_ms < 0 or eval_start_ms >= eval_end_ms
            or eval_start_ms % DAY or eval_end_ms % DAY):
        raise RuntimeError('RISK_EVALUATION_BOUNDS_INVALID')

    daily_by_symbol, audits, calendar = {}, {}, None
    for symbol in symbols:
        aggregated = structure.aggregate_daily(rows_by_symbol[symbol],
                                                split_end_ms=eval_end_ms)
        daily = aggregated['daily']
        stamps = [row['bar_close_ts'] for row in daily]
        if len(stamps) < 2:
            raise RuntimeError('RISK_DAILY_HISTORY_INSUFFICIENT:' + symbol)
        if any(b - a != DAY for a, b in zip(stamps, stamps[1:])):
            raise RuntimeError('RISK_DAILY_CALENDAR_GAP:' + symbol)
        if calendar is not None and stamps != calendar:
            raise RuntimeError('RISK_BASKET_CALENDAR_MISMATCH:' + symbol)
        calendar = stamps
        for row in daily:
            _positive_finite(row['close'], 'RISK_DAILY_CLOSE_INVALID:' + symbol)
        daily_by_symbol[symbol] = daily
        audits[symbol] = aggregated['audit']

    returns = []
    for index in range(1, len(calendar)):
        constituents = {}
        for symbol in symbols:
            daily = daily_by_symbol[symbol]
            value = daily[index]['close'] / daily[index - 1]['close'] - 1.0
            if not math.isfinite(value) or value <= -1.0:
                raise RuntimeError('RISK_SIMPLE_RETURN_INVALID:' + symbol)
            constituents[symbol] = value
        returns.append({
            'day_open_ts': calendar[index] - DAY,
            'available_at': calendar[index],
            'simple_return': math.fsum(constituents.values()) / BASKET_SIZE,
            'constituent_returns': constituents,
        })

    warmup = [row for row in returns if row['available_at'] < eval_start_ms]
    reference = _sample_sigma([row['simple_return'] for row in warmup],
                              'RISK_REFERENCE_SIGMA')
    return {
        'symbols': list(symbols), 'eval_start_ms': eval_start_ms,
        'eval_end_ms': eval_end_ms, 'returns': returns, 'sigma_ref': reference,
        'reference': {
            'N': len(warmup), 'first_available_at': warmup[0]['available_at'],
            'last_available_at': warmup[-1]['available_at'], 'ddof': 1,
            'available_at_rule': 'STRICTLY_BEFORE_EVALUATION_START',
            'return_definition': 'ARITHMETIC_MEAN_OF_SEVEN_SIMPLE_CLOSE_RETURNS',
        },
        'audit': {
            'aggregation_by_symbol': audits,
            'complete_daily_calendar_identical': True,
            'complete_daily_first_close_ts': calendar[0],
            'complete_daily_last_close_ts': calendar[-1],
            'basket_return_count': len(returns),
            'returns_available_at_eval_start': sum(
                row['available_at'] <= eval_start_ms for row in returns),
            'window_returns': WINDOW_RETURNS, 'ddof': 1,
            'imputed_rows': 0, 'dropped_constituents': 0,
            'future_universe_selection': False,
        },
    }


def entry_weights(state, trades, opened=()):
    """Map original signal origins to immutable-in-position entry weights.

    Only origin fields, signal_ts and entry_ts are read from ledger rows. Exit
    times, holding periods, PnL and eventual status cannot influence the weight.
    The eventual constant-exposure comparison scalar is deliberately absent.
    """
    rows = state['returns']
    stamps = [row['available_at'] for row in rows]
    if (not stamps or any(type(stamp) is not int or stamp % DAY for stamp in stamps)
            or any(b - a != DAY for a, b in zip(stamps, stamps[1:]))):
        raise RuntimeError('RISK_STATE_RETURN_CALENDAR_INVALID')
    reference = _positive_finite(state['sigma_ref'], 'RISK_REFERENCE_SIGMA_INVALID')
    if state['reference']['last_available_at'] >= state['eval_start_ms']:
        raise RuntimeError('RISK_REFERENCE_TIME_LEAK')
    result = {}
    for trade in (*trades, *opened):
        if trade.get('symbol') not in state['symbols'] or trade.get('side') != 'long':
            raise RuntimeError('RISK_ENTRY_SYMBOL_OR_SIDE_INVALID')
        signal, entry = trade.get('signal_ts'), trade.get('entry_ts')
        if (type(signal) is not int or type(entry) is not int
                or signal % DAY or entry % structure.INTERVAL
                or not state['eval_start_ms'] <= signal <= entry < state['eval_end_ms']):
            raise RuntimeError('RISK_ENTRY_DECISION_TIME_INVALID')
        key = ORIGIN(trade)
        if key in result:
            raise RuntimeError('RISK_DUPLICATE_ENTRY_ORIGIN')
        if trade.get('origin_key', key) != key:
            raise RuntimeError('RISK_ENTRY_ORIGIN_DRIFT')
        end_index = bisect_right(stamps, signal)
        window = rows[max(0, end_index - WINDOW_RETURNS):end_index]
        if len(window) != WINDOW_RETURNS:
            raise RuntimeError('RISK_ENTRY_30_RETURN_HISTORY_INSUFFICIENT:' + key)
        if window[-1]['available_at'] != signal:
            raise RuntimeError('RISK_ENTRY_LATEST_COMPLETED_DAY_MISSING:' + key)
        current = _sample_sigma([row['simple_return'] for row in window],
                                'RISK_ENTRY_SIGMA')
        weight = min(1.0, reference / current)
        if not math.isfinite(weight) or not 0 < weight <= 1:
            raise RuntimeError('RISK_ENTRY_WEIGHT_INVALID')
        result[key] = {
            'origin_key': key, 'symbol': trade['symbol'],
            'signal_ts': signal, 'entry_ts': entry,
            'weight': weight, 'sigma_ref': reference, 'sigma_t': current,
            'available_at': window[-1]['available_at'],
            'window_first_available_at': window[0]['available_at'],
            'window_last_available_at': window[-1]['available_at'],
            'window_N': WINDOW_RETURNS, 'ddof': 1,
            'fixed_until_exit': True,
        }
    return result
