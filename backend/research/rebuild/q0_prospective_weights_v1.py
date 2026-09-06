"""Bounded incremental state for the unchanged, unadopted B comparator.

Initialization verifies the original 38-return reference through the PR1194
adapter.  Each later update needs only seven new completed daily closes and the
previous 30 basket returns.  No outcomes, exposure-control C, or new parameters
are inputs to this module.
"""
from __future__ import annotations

from copy import deepcopy
import math

from . import q0_b_seen_adapter_v1 as adapter
from . import q0_risk_entry_weights_v1 as frozen

DAY = frozen.DAY
SCHEMA = "zel.q0.prospective.weights.v1"
SYMBOLS = adapter.SYMBOLS
REFERENCE = deepcopy(adapter.REFERENCE)
WINDOW = frozen.WINDOW_RETURNS


def _validate(state):
    if (state.get('schema_version') != SCHEMA
            or state.get('symbols') != list(SYMBOLS)
            or state.get('source_eval_start_ms') != adapter.ORIGINAL_START
            or state.get('reference') != REFERENCE
            or state.get('sigma_ref') != REFERENCE['sigma_ref']
            or state.get('window_returns') != 30 or state.get('ddof') != 1
            or state.get('reference_verified') is not True):
        raise RuntimeError('PROSPECTIVE_B_FROZEN_DEFINITION_DRIFT')
    last = state.get('last_daily_close_ts')
    if type(last) is not int or last % DAY:
        raise RuntimeError('PROSPECTIVE_B_LAST_DAY_INVALID')
    closes = state.get('last_closes', {})
    if set(closes) != set(SYMBOLS):
        raise RuntimeError('PROSPECTIVE_B_CONSTITUENT_SET')
    for symbol in SYMBOLS:
        frozen._positive_finite(closes[symbol], 'PROSPECTIVE_B_LAST_CLOSE_INVALID:' + symbol)
    rows = state.get('returns', [])
    if len(rows) != WINDOW:
        raise RuntimeError('PROSPECTIVE_B_30_RETURN_HISTORY_REQUIRED')
    expected = list(range(last - (WINDOW - 1) * DAY, last + DAY, DAY))
    if [row.get('available_at') for row in rows] != expected:
        raise RuntimeError('PROSPECTIVE_B_RETURN_CALENDAR_INVALID')
    for row in rows:
        constituents = row.get('constituent_returns', {})
        if set(constituents) != set(SYMBOLS):
            raise RuntimeError('PROSPECTIVE_B_RETURN_CONSTITUENTS')
        values = [constituents[symbol] for symbol in SYMBOLS]
        if any(type(value) not in (int, float) or not math.isfinite(value)
               or value <= -1 for value in values):
            raise RuntimeError('PROSPECTIVE_B_RETURN_INVALID')
        if row.get('simple_return') != math.fsum(values) / frozen.BASKET_SIZE:
            raise RuntimeError('PROSPECTIVE_B_RETURN_BASKET_PARITY')


def initialize(rows_by_symbol, symbols, source_eval_start_ms=adapter.ORIGINAL_START):
    """Verify historical prefix once, then retain only the causal daily tail."""
    if list(symbols) != list(SYMBOLS) or source_eval_start_ms != adapter.ORIGINAL_START:
        raise RuntimeError('PROSPECTIVE_B_INITIAL_DEFINITION_DRIFT')
    if set(rows_by_symbol) != set(SYMBOLS) or any(not rows_by_symbol[s] for s in SYMBOLS):
        raise RuntimeError('PROSPECTIVE_B_INITIAL_CONSTITUENTS_MISSING')
    ends = [rows_by_symbol[s][-1]['bar_close_ts'] for s in SYMBOLS]
    if any(type(end) is not int for end in ends) or len(set(ends)) != 1:
        raise RuntimeError('PROSPECTIVE_B_PREFIX_END_MISMATCH')
    end = ends[0] // DAY * DAY
    # This existing adapter verifies original N, endpoint timestamps, ddof and
    # sigma, then pins the exact original scalar instead of re-estimating it
    # from the enlarged prospective warmup.
    market = adapter.frozen_market_state(rows_by_symbol, SYMBOLS,
                                         source_eval_start_ms, end)
    daily = {symbol: frozen.structure.aggregate_daily(rows_by_symbol[symbol],
             split_end_ms=end)['daily'] for symbol in SYMBOLS}
    state = {
        'schema_version': SCHEMA, 'symbols': list(SYMBOLS),
        'source_eval_start_ms': source_eval_start_ms,
        'sigma_ref': REFERENCE['sigma_ref'], 'reference': deepcopy(REFERENCE),
        'reference_verified': True, 'window_returns': WINDOW, 'ddof': 1,
        'last_daily_close_ts': market['audit']['complete_daily_last_close_ts'],
        'last_closes': {symbol: daily[symbol][-1]['close'] for symbol in SYMBOLS},
        'returns': deepcopy(market['returns'][-WINDOW:]),
        'historical_return_count': len(market['returns']), 'incremental_days': 0,
        'reference_reestimated': False,
    }
    _validate(state)
    return state


def advance(state, new_daily_bars):
    """Consume exactly the next complete UTC basket; gaps are never imputed."""
    _validate(state)
    if not isinstance(new_daily_bars, dict) or set(new_daily_bars) != set(SYMBOLS):
        raise RuntimeError('PROSPECTIVE_B_NEXT_DAY_CONSTITUENTS_MISSING')
    open_ts = state['last_daily_close_ts']
    close_ts = open_ts + DAY
    constituents, closes = {}, {}
    for symbol in SYMBOLS:
        bar = new_daily_bars[symbol]
        if (type(bar.get('bar_open_ts')) is not int
                or type(bar.get('bar_close_ts')) is not int
                or bar['bar_open_ts'] != open_ts or bar['bar_close_ts'] != close_ts):
            raise RuntimeError('PROSPECTIVE_B_NEXT_DAY_GAP_OR_INCOMPLETE:' + symbol)
        closes[symbol] = frozen._positive_finite(
            bar.get('close'), 'PROSPECTIVE_B_NEXT_CLOSE_INVALID:' + symbol)
        value = closes[symbol] / state['last_closes'][symbol] - 1.0
        if not math.isfinite(value) or value <= -1:
            raise RuntimeError('PROSPECTIVE_B_NEXT_RETURN_INVALID:' + symbol)
        constituents[symbol] = value
    new_return = {
        'day_open_ts': open_ts, 'available_at': close_ts,
        'simple_return': math.fsum(constituents.values()) / frozen.BASKET_SIZE,
        'constituent_returns': constituents,
    }
    result = deepcopy(state)
    result.update(last_closes=closes, last_daily_close_ts=close_ts,
                  returns=[*deepcopy(state['returns'][1:]), new_return],
                  incremental_days=state['incremental_days'] + 1)
    _validate(result)
    return result


def observation(state, signal_close_ms):
    """Return the exact frozen B decision at the latest available daily close."""
    _validate(state)
    if type(signal_close_ms) is not int or signal_close_ms != state['last_daily_close_ts']:
        raise RuntimeError('PROSPECTIVE_B_SIGNAL_LATEST_COMPLETE_DAY_REQUIRED')
    rows = state['returns']
    sigma = frozen._sample_sigma([row['simple_return'] for row in rows], 'RISK_ENTRY_SIGMA')
    weight = min(1.0, state['sigma_ref'] / sigma)
    if not math.isfinite(weight) or not 0 < weight <= 1:
        raise RuntimeError('RISK_ENTRY_WEIGHT_INVALID')
    return {
        'weight': weight, 'sigma_ref': state['sigma_ref'], 'sigma_t': sigma,
        'available_at': signal_close_ms,
        'window_first_available_at': rows[0]['available_at'],
        'window_last_available_at': rows[-1]['available_at'],
        'window_N': WINDOW, 'ddof': 1, 'fixed_until_exit': True,
    }
