"""Incremental, research-only continuation of the sealed Q0 state machine.

No source acquisition, costs, sizing, persistence or economic decision occurs
here. Only the consumer may publish the returned state atomically. Daily OHLCV,
channel formulas and held-bar geometry reuse the original Q0 helpers. Explicit
transition code mirrors generate_signals/replay and has synthetic batch parity.
Warmup initializes channel attempts without carrying a position or an order.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy

from backend.research.rebuild import break_channel_structure_v1 as q0

DAY, BAR = q0.DAY, q0.INTERVAL
SCHEMA = 'Q0_PROSPECTIVE_ENGINE_V1'


def _record(s, kind, index, **extra):
    s['trace'].append({'kind': kind, 'index': index, **extra})


def _day(s, row, start, end):
    """One causal daily transition; completed/failed attempts never restart."""
    i = s['daily_count']
    previous = s['previous_days']
    if previous and previous[-1]['bar_close_ts'] != row['bar_open_ts']:
        raise RuntimeError('OBSERVER_DAILY_CONTINUITY')
    signals = []

    def record(kind, **extra):
        s['signal_trace'].append({'kind': kind, 'daily_index': i,
                                 'signal_index': row['source_last_index'],
                                 'ts': row['bar_close_ts'], **extra})

    if len(previous) == q0.LOOKBACK_DAYS and row['bar_close_ts'] < end:
        current = q0.channel([r['close'] for r in previous])
        current.update(anchor_daily_index=i,
                       anchor_signal_index=row['source_last_index'],
                       anchor_ts=row['bar_close_ts'],
                       prior_start_ts=previous[0]['bar_open_ts'],
                       prior_end_ts=previous[-1]['bar_close_ts'])
        close = float(row['close'])
        for direction in ('UP', 'DOWN'):
            attempt = s['attempts'][direction]
            if attempt is not None:
                beyond = (close > attempt['upper'] if direction == 'UP'
                          else close < attempt['lower'])
                conflict = direction == 'UP' and close < attempt['lower']
                if not beyond or conflict:
                    record('ATTEMPT_CANCELLED', direction=direction,
                           reason='CROSSED_BAND_CONFLICT' if conflict else 'CONFIRMATION_FAILED',
                           anchor_ts=attempt['anchor_ts'], close=close)
                    s['attempts'][direction] = None
                    continue
                confirmed = dict(attempt, direction=direction,
                                 daily_index=i, signal_index=row['source_last_index'],
                                 signal_ts=row['bar_close_ts'],
                                 confirmation_days=q0.CONFIRMATION_DAYS,
                                 confirmation_close=close)
                record('CONFIRMED', direction=direction,
                       anchor_ts=attempt['anchor_ts'], close=close)
                if start <= row['bar_close_ts']:
                    signals.append(confirmed)
                s['attempts'][direction] = None
                continue
            beyond = close > current['upper'] if direction == 'UP' else close < current['lower']
            if not beyond:
                continue
            if direction == 'UP' and close < current['lower']:
                record('UP_START_REJECTED', reason='CROSSED_BAND_CONFLICT', **current)
                continue
            if direction == 'UP' and not current['preparation']:
                record('UP_START_REJECTED', reason='PREPARATION_ABSENT', **current)
                continue
            s['attempts'][direction] = current
            record('ATTEMPT_STARTED', direction=direction, close=close, **current)
    signals.sort(key=lambda item: (item['signal_ts'], 0 if item['direction'] == 'DOWN' else 1))
    s['signals'].extend(signals)
    s['previous_days'] = [*previous, row][-q0.LOOKBACK_DAYS:]
    s['daily_count'] += 1
    return signals


def _assemble(s, row, start, end):
    index = s['next_index']
    stamp = row['bar_open_ts'] // DAY * DAY
    if s['partial_day'] and s['partial_day'][0]['bar_open_ts'] // DAY * DAY != stamp:
        # Only the initial partial edge can occur; no interior gaps are allowed.
        s['partial_day'] = []
    s['partial_day'].append(deepcopy(row))
    if row['bar_close_ts'] % DAY:
        return [], None
    parts = s['partial_day']
    s['partial_day'] = []
    if len(parts) != 6 or parts[0]['bar_open_ts'] != stamp:
        return [], None
    daily = q0.aggregate_daily(parts)['daily'][0]
    daily['source_first_index'] = index - 5
    daily['source_last_index'] = index
    return _day(s, daily, start, end), daily


def _geometry(pos):
    rows = pos['geometry_rows']
    result = q0.old.common.evaluate_development_events(
        rows, [0], split_start_ms=rows[0]['bar_open_ts'],
        split_end_ms=rows[-1]['bar_close_ts'] + BAR,
        interval_ms=BAR, hold_bars=len(rows) - 1)
    if len(result['trades']) != 1 or result['exclusions']:
        raise RuntimeError('OBSERVER_SHARED_GEOMETRY_UNAVAILABLE')
    raw = dict(result['trades'][0])
    offset = pos['signal']['signal_index']
    for field in ('signal_index', 'entry_index', 'exit_index'):
        raw[field] += offset
    raw.update(entry_stop_price=pos['stop'],
               channel_anchor_ts=pos['signal'].get('anchor_ts'),
               channel_upper=pos['signal']['upper'],
               channel_lower=pos['signal']['lower'],
               preparation=pos['signal'].get('preparation'),
               holding_limit=None, initial_risk_design='LATCHED_LOWER_CHANNEL_SL',
               entry_signal_metadata=deepcopy(pos['signal']))
    return raw


def _close(s, index, price, stamp, reason, intrabar=False):
    pos = s['position']
    raw = _geometry(pos)
    gross = (price / raw['entry_price'] - 1.0) * 10_000.0
    raw.update(exit_index=index, exit_ts=stamp, exit_price=price,
               gross_bps=gross, hold_ms=stamp - raw['entry_ts'],
               mfe_bps=max(raw['mfe_bps'], gross, 0.0),
               mae_bps=min(raw['mae_bps'], gross, 0.0), exit_reason=reason,
               exit_timestamp_semantics=('CLOSED_EXIT_BAR_UPPER_BOUND' if intrabar else 'OBSERVED_4H_OPEN'),
               excursion_semantics=('FULL_EXIT_BAR_BOUND_POSSIBLY_POST_STOP_DIAGNOSTIC_ONLY' if intrabar
                                    else 'HELD_COMPLETED_BARS_AND_EXIT_OPEN_ONLY'),
               intrabar_stop_timing_unknown=intrabar)
    s['trades'].append(raw)
    s['events'][pos['event_index']].update(status='COMPLETED', exclusion_reason=None)
    s['counts'][reason] = s['counts'].get(reason, 0) + 1
    _record(s, reason, index, ts=stamp, price=price,
            signal_index=raw['signal_index'], entry_stop_price=pos['stop'])
    s['position'] = s['pending_exit'] = None


def _execute_bar(s, row, signals):
    index, stamp, price = s['next_index'], row['bar_open_ts'], float(row['open'])
    exited_at_open = False
    if s['position'] is not None:
        if price <= s['position']['stop']:
            _close(s, index, price, stamp, 'PROTECTIVE_STOP_GAP_OPEN')
            exited_at_open = True
        elif s['pending_exit'] is not None:
            _close(s, index, price, stamp, 'BEARISH_CONFIRMED_NEXT_OPEN')
            exited_at_open = True
    if s['pending_entry'] is not None:
        pending = s['pending_entry']
        signal, event = pending['signal'], s['events'][pending['event_index']]
        if s['position'] is not None or exited_at_open:
            event.update(status='EXCLUDED', exclusion_reason='SAME_OPEN_EXIT_OR_OCCUPANCY')
        elif price <= signal['lower']:
            event.update(status='EXCLUDED', exclusion_reason='ENTRY_OPEN_NOT_ABOVE_PROTECTIVE_STOP')
            s['counts']['entry_open_stop_cancellations'] = s['counts'].get('entry_open_stop_cancellations', 0) + 1
        else:
            s['position'] = {'signal': signal, 'event_index': pending['event_index'],
                             'entry_index': index, 'stop': float(signal['lower']),
                             'geometry_rows': [deepcopy(s['last_bar'])]}
            _record(s, 'ENTRY_NEXT_OPEN', index, ts=stamp, price=price,
                    signal_index=signal['signal_index'], entry_stop_price=float(signal['lower']))
        if event['status'] == 'EXCLUDED':
            _record(s, 'ENTRY_CANCELLED', index, ts=stamp,
                    signal_index=signal['signal_index'], reason=event['exclusion_reason'])
        s['pending_entry'] = None
    if s['position'] is not None:
        s['position']['geometry_rows'].append(deepcopy(row))
        if float(row['low']) <= s['position']['stop']:
            _close(s, index, s['position']['stop'], row['bar_close_ts'],
                   'PROTECTIVE_STOP_INTRABAR', intrabar=True)
    bearish = next((item for item in signals if item['direction'] == 'DOWN'), None)
    bullish = next((item for item in signals if item['direction'] == 'UP'), None)
    if bearish is not None:
        _record(s, 'BEARISH_CLOSE_CONFIRMED', index, ts=bearish['signal_ts'],
                occupied=s['position'] is not None, signal_index=index)
        if s['position'] is not None:
            s['pending_exit'] = bearish
    if bullish is not None:
        event = {'direction': 'UP', 'signal_index': index,
                 'signal_ts': bullish['signal_ts'], 'admission': True,
                 'status': 'PENDING', 'exclusion_reason': None, 'features': deepcopy(bullish)}
        if bearish is not None:
            event.update(status='EXCLUDED', exclusion_reason='OPPOSITE_SIGNAL_PRIORITY')
            s['counts']['simultaneous_confirmation_conflicts'] = s['counts'].get('simultaneous_confirmation_conflicts', 0) + 1
        elif s['position'] is not None:
            event.update(status='EXCLUDED', exclusion_reason='SIGNAL_DURING_OPEN')
        else:
            s['pending_entry'] = {'signal': bullish, 'event_index': len(s['events'])}
        s['events'].append(event)
        _record(s, 'BULLISH_CLOSE_CONFIRMED', index, ts=bullish['signal_ts'],
                status=event['status'], reason=event['exclusion_reason'], signal_index=index)


def _empty_symbol():
    return {'next_index': 0, 'daily_count': 0, 'previous_days': [], 'partial_day': [],
            'attempts': {'UP': None, 'DOWN': None}, 'signals': [], 'signal_trace': [],
            'trades': [], 'events': [], 'trace': [], 'counts': {},
            'position': None, 'pending_entry': None, 'pending_exit': None, 'last_bar': None}


def initialize(rows_by_symbol, symbols, start, end):
    """Consume a verified causal warmup prefix once; never replay warmup PnL.

    Caller verifies original prefix identity and B reference. Symbols may be a
    reduced synthetic fixture here; the production consumer seals all seven.
    Warmup must end strictly before T0. T0's closing confirmation is processed
    by advance, so no pre-T0 pending order or position can enter the campaign.
    """
    if (not symbols or len(set(symbols)) != len(symbols)
            or set(rows_by_symbol) != set(symbols)
            or type(start) is not int or type(end) is not int
            or start < 0 or start >= end or start % DAY or end % DAY):
        raise RuntimeError('OBSERVER_INITIAL_SCOPE')
    cursor = None
    initial_open = None
    states = {}
    for symbol in symbols:
        rows = rows_by_symbol[symbol]
        q0._validate_rows(rows)
        if rows[-1]['bar_close_ts'] >= start:
            raise RuntimeError('OBSERVER_WARMUP_MUST_PRECEDE_T0')
        if cursor is not None and (rows[-1]['bar_close_ts'] != cursor
                                  or rows[0]['bar_open_ts'] != initial_open):
            raise RuntimeError('OBSERVER_WARMUP_CALENDAR_MISMATCH')
        cursor, initial_open = rows[-1]['bar_close_ts'], rows[0]['bar_open_ts']
        s = _empty_symbol()
        for row in rows:
            signals, _ = _assemble(s, row, start, end)
            if signals:
                raise RuntimeError('OBSERVER_WARMUP_SIGNAL_LEAK')
            s['last_bar'] = deepcopy(row)
            s['next_index'] += 1
        states[symbol] = s
    return {'schema': SCHEMA, 'symbols': list(symbols), 'start': start, 'end': end,
            'cursor_close_ts': cursor, 'initial_source_open_ts': initial_open,
            'by_symbol': states, 'last_daily_bars': {},
            'formal_credit': 0, 'operating_adoption': False, 'execution': 'NONE'}


def advance(state, bars_by_symbol):
    """One aligned completed 4h batch; failure leaves the caller state intact.

    Duplicate/conflict quarantine and observed-at closure proof belong to the
    archive consumer. This core requires exactly the next batch and rejects
    gaps, replayed batches and prices after the frozen terminal close.
    """
    if (state.get('schema') != SCHEMA or set(bars_by_symbol) != set(state['symbols'])
            or state.get('formal_credit') != 0 or state.get('execution') != 'NONE'
            or state.get('operating_adoption') is not False):
        raise RuntimeError('OBSERVER_STATE_SCOPE')
    expected = state['cursor_close_ts']
    if expected + BAR > state['end']:
        raise RuntimeError('OBSERVER_AFTER_FROZEN_END')
    for row in bars_by_symbol.values():
        q0._validate_rows([row])
        if row['bar_open_ts'] != expected:
            raise RuntimeError('OBSERVER_GAP_DUPLICATE_OR_ORDER')
    result = deepcopy(state)
    result['last_daily_bars'] = {}
    for symbol in result['symbols']:
        s, row = result['by_symbol'][symbol], bars_by_symbol[symbol]
        signals, daily = _assemble(s, row, result['start'], result['end'])
        _execute_bar(s, row, signals)
        s['last_bar'] = deepcopy(row)
        s['next_index'] += 1
        if daily is not None:
            result['last_daily_bars'][symbol] = daily
    result['cursor_close_ts'] = expected + BAR
    return result


def snapshot(state):
    """Current raw ledger, with symmetric unfinished marks and no forced exit.

    Interim open event status is observational only: live state remains open.
    Pending next-open entries remain PENDING until a source bar proves its open.
    """
    output = {}
    for symbol in state['symbols']:
        s = state['by_symbol'][symbol]
        events, trace, opened = deepcopy(s['events']), deepcopy(s['trace']), []
        if s['position'] is not None:
            pos = s['position']
            raw = _geometry(pos)
            for old, new in (('exit_index', 'mark_index'), ('exit_ts', 'mark_ts'),
                             ('exit_price', 'mark_price'), ('gross_bps', 'gross_mark_bps')):
                raw[new] = raw.pop(old)
            raw.update(status='CENSORED', terminal_liquidation=False,
                       pending_exit_signal_ts=(s['pending_exit']['signal_ts'] if s['pending_exit'] else None),
                       excursion_semantics='COMPLETED_HELD_4H_BARS_TO_COMMON_END')
            opened.append(raw)
            events[pos['event_index']].update(status='CENSORED', exclusion_reason='COMMON_END_POSITION_OPEN',
                                              censor_reason='COMMON_END_POSITION_OPEN')
            trace.append({'kind': 'TERMINAL_MARK', 'index': s['next_index'] - 1,
                          'ts': raw['mark_ts'], 'price': raw['mark_price'],
                          'signal_index': raw['signal_index']})
        audit = {'up_confirmed': sum(x['direction'] == 'UP' for x in s['signals']),
                 'down_confirmed': sum(x['direction'] == 'DOWN' for x in s['signals']),
                 'completed': len(s['trades']), 'open': len(opened),
                 'excluded': sum(e['status'] == 'EXCLUDED' for e in events),
                 'exit_and_cancel_counts': dict(sorted(s['counts'].items())),
                 'common_end_mark_ts': state['cursor_close_ts'], 'same_symbol_max_positions': 1,
                 'forced_terminal_liquidations': 0, 'future_economic_rows': 0, 'short_entries': 0}
        bundle = {'signals': deepcopy(s['signals']), 'trace': deepcopy(s['signal_trace']),
                  'audit': {'up_confirmed': audit['up_confirmed'], 'down_confirmed': audit['down_confirmed'],
                            'require_preparation': True, 'pending_attempts_at_end': deepcopy(s['attempts']),
                            'trace_counts': dict(sorted(Counter(t['kind'] for t in s['signal_trace']).items())),
                            'signal_close_at_end_allowed': False}}
        output[symbol] = {'trades': deepcopy(s['trades']), 'open_positions': opened,
                          'events': events, 'trace': trace, 'audit': audit, 'bundle': bundle}
    return output
