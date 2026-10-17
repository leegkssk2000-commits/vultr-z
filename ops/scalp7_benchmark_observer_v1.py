"""Read-only H01/H02 observations; not a strategy, filter, or economic evaluator.

Call observers AFTER the native functions. They never return order decisions or
alter the native state. A malformed/missing observation is UNKNOWN, never zero.
Outcome labels remain in a separate namespace and never enter indicator logic.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
import hashlib
import math
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import scalp7_positive_lanes_v2 as native

NATIVE_SHA256 = 'b0919c9e3542d6d2e14ab8f545179c7bfc43d661379bc1f6d0714a6603ea9aa2'
TF = 1_800_000


def verify_native() -> str:
    found = hashlib.sha256(Path(native.__file__).read_bytes()).hexdigest()
    if found != NATIVE_SHA256:
        raise ValueError('OBSERVER_NATIVE_SOURCE_CHANGED')
    return found


def _stamp(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError('OBSERVER_INTEGER_CLOCK_REQUIRED')
    number = float(value)
    if not math.isfinite(number) or number != int(number) or number < 0:
        raise ValueError('OBSERVER_INTEGER_CLOCK_REQUIRED')
    return int(number)


def _number(value: Any) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError('OBSERVER_FINITE_VALUE_REQUIRED')
    return number


def _row_clock(row: Mapping[str, Any]) -> int:
    opening, closing, available = (_stamp(row[k]) for k in
                                   ('open_ts_ms', 'close_ts_ms', 'available_ts_ms'))
    if opening % TF or closing != opening + TF or available < closing:
        raise ValueError('OBSERVER_COMPLETE_UTC_30M_REQUIRED')
    return available


def _state_view(state: Mapping[str, Any]) -> dict[str, Any]:
    return {k: (None if k in {'pull_low', 'pull_high'} and not math.isfinite(float(v)) else deepcopy(v))
            for k, v in state.items()}


def momentum_flags(values: Any) -> dict[str, Any]:
    """The existing predicate, plus an OBSERVATION of sign crossing; no exit."""
    if len(values) != 3:
        raise ValueError('OBSERVER_THREE_MOMENTA_REQUIRED')
    a, b, c = map(_number, values)
    return {'momenta': [a, b, c],
            'positive_weak_predicate': bool(c > 0 and b > 0 and c < b < a),
            'negative_now': bool(c < 0),
            'negative_cross': bool(b >= 0 and c < 0)}


def squeeze_observation(position: Mapping[str, Any], bar: Mapping[str, Any], history: Any,
                        native_result: Mapping[str, Any], *, signal_low: float | None = None
                        ) -> dict[str, Any]:
    """Inspect a genuine completed callback prefix, using the pinned native momentum.

    This may only be called for a position still open AFTER the engine's stop
    check. It does not simulate a replacement exit, a fill, or freed occupancy.
    """
    verify_native()
    entry = _stamp(position['entry_ts_ms'])
    asof = _row_clock(bar)
    if _stamp(bar['open_ts_ms']) < entry:
        raise ValueError('OBSERVER_BEFORE_ENTRY')
    if history.empty or len(history) < 41:
        raise ValueError('OBSERVER_WARMUP_MISSING')
    x = native._validated(history.iloc[-41:].copy())
    if int(x.iloc[-1].open_ts_ms) != _stamp(bar['open_ts_ms']):
        raise ValueError('OBSERVER_PREFIX_BAR_MISMATCH')
    if len(set(x.segment_id)) != 1 or not (x.open_ts_ms.diff().iloc[1:] == TF).all():
        raise ValueError('OBSERVER_PATH_GAP')
    if (x.available_ts_ms > asof).any():
        raise ValueError('OBSERVER_FUTURE_AVAILABILITY')
    for key in ('open', 'high', 'low', 'close', 'close_ts_ms', 'available_ts_ms', 'segment_id'):
        if x.iloc[-1][key] != bar[key]:
            raise ValueError('OBSERVER_PREFIX_BAR_MISMATCH')
    if int(position['side']) != 1:
        raise ValueError('OBSERVER_SQUEEZE_LONG_ONLY')
    sig = position['signal']
    flags = momentum_flags(native._last_momenta(x))
    if signal_low is not None and _number(signal_low) <= 0:
        raise ValueError('OBSERVER_POSITIVE_SIGNAL_LOW_REQUIRED')
    return {
        'kind': 'SQUEEZE_CALLBACK',
        'symbol': str(sig['symbol']), 'identity': str(sig['identity']),
        'signal_ts_ms': _stamp(sig['signal_ts_ms']),
        'signal_open_ts_ms': _stamp(sig['signal_open_ts_ms']),
        'bar_open_ts_ms': _stamp(bar['open_ts_ms']), 'asof_ts_ms': asof,
        'features_asof': {
            **flags,
            'native_weak_exit_eligible': bool(flags['positive_weak_predicate'] and
                                            int(x.iloc[-2].open_ts_ms) >= entry),
            'close': _number(bar['close']),
            'signal_low': None if signal_low is None else _number(signal_low),
            'below_signal_low': None if signal_low is None else bool(bar['close'] < signal_low),
        },
        'native_decision_observed': deepcopy(dict(native_result)),
        'source_sha256': NATIVE_SHA256,
        'scope': 'OBSERVATION_NOT_EXIT_OR_PNL',
    }


@dataclass
class HGObserver:
    """One observer per symbol and chronological segment; native state is external."""
    symbol: str
    touch_ts_ms: int | None = None
    weak_bars_since_touch: int = 0
    last_open_ts_ms: int | None = None
    segment_id: Any = None

    def observe(self, before: Mapping[str, Any], after: Mapping[str, Any],
                row: Mapping[str, Any], previous: Mapping[str, Any],
                native_event: Any) -> dict[str, Any]:
        verify_native()
        asof, prior_available = _row_clock(row), _row_clock(previous)
        opening = _stamp(row['open_ts_ms'])
        if _stamp(previous['close_ts_ms']) != opening or prior_available > asof:
            raise ValueError('OBSERVER_NONCAUSAL_PREVIOUS_BAR')
        if previous['segment_id'] != row['segment_id']:
            raise ValueError('OBSERVER_PATH_GAP')
        if self.last_open_ts_ms is not None:
            if opening <= self.last_open_ts_ms:
                raise ValueError('OBSERVER_UNORDERED_TRANSITION')
            if opening != self.last_open_ts_ms + TF or self.segment_id != row['segment_id']:
                self.touch_ts_ms, self.weak_bars_since_touch = None, 0
                self.last_open_ts_ms, self.segment_id = opening, row['segment_id']
                raise ValueError('OBSERVER_TRACE_COVERAGE_GAP')
        values = [_number(row[f'g{n}']) for n in native.LONG_GMMA]
        long = all(a > b for a, b in zip(values, values[1:])) and row['g60'] > previous['g60']
        short = all(a < b for a, b in zip(values, values[1:])) and row['g60'] < previous['g60']
        side = 1 if long else -1 if short else 0
        adx, slope = _number(row['adx14']), _number(row['g20']) - _number(previous['g20'])
        strong = bool(side and adx >= 30 and side * slope > 0)
        if not before['stage'] or before['side'] != after['side']:
            self.touch_ts_ms, self.weak_bars_since_touch = None, 0
        if not before['stage'] and after['stage'] == 1:
            self.touch_ts_ms = asof
        retained = bool(not strong and before['stage'] == after['stage'] == 1
                        and not before['episode_traded'] and not after['episode_traded']
                        and side == before['side'] == after['side'] and side != 0)
        if retained:
            self.weak_bars_since_touch += 1
        known = self.touch_ts_ms is not None
        result = {
            'kind': 'KELTNER_TRANSITION', 'symbol': self.symbol,
            'signal_open_ts_ms': opening, 'signal_ts_ms': max(asof, _stamp(row.get('feature_available_ts_ms', asof))),
            'features_asof': {'adx': adx, 'ema20_slope': slope, 'strong': strong,
                              'weak_state_retained': retained,
                              'touch_ts_ms': self.touch_ts_ms,
                              'weak_bars_since_touch': self.weak_bars_since_touch if known else None,
                              'event_after_weak_retention': bool(native_event is not None and self.weak_bars_since_touch) if known else None},
            'native_event_observed': deepcopy(native_event),
            'native_state_before': _state_view(before),
            'native_state_after': _state_view(after),
            'coverage': 'OBSERVED_FROM_TOUCH' if known else 'TOUCH_NOT_OBSERVED',
            'source_sha256': NATIVE_SHA256, 'scope': 'OBSERVATION_NOT_ADMISSION_OR_PNL',
        }
        if not after['stage']:
            self.touch_ts_ms, self.weak_bars_since_touch = None, 0
        self.last_open_ts_ms, self.segment_id = opening, row['segment_id']
        return result


def observed_hg_call(observer: HGObserver, state: Any, row: Mapping[str, Any],
                     previous: Mapping[str, Any]) -> tuple[Any, dict[str, Any]]:
    """Fixture/adapter hook: call the original once, then inspect copies. No reset."""
    before = asdict(state)
    event = native._hg_event(state, row, previous)
    record = observer.observe(before, asdict(state), row, previous, event)
    return event, record


def observation_key(row: Mapping[str, Any]) -> tuple[str, int, int]:
    return str(row['symbol']), _stamp(row['signal_ts_ms']), _stamp(row['signal_open_ts_ms'])


def join_saved_squeeze(trades: list[dict[str, Any]], observations: list[dict[str, Any]],
                       coverage: Mapping[tuple[str, int, int], bool]) -> dict[str, Any]:
    """Attach observations to ALL supplied saved trades without revaluing any trade.

    Only caller-verified COMPLETE callback paths can yield NO_OBSERVED_EVENT.
    Missing prefixes and missing source are UNKNOWN. No early-exit savings are
    estimated here; such savings require the existing full chronological replay.
    """
    keys = [observation_key(t) for t in trades]
    if len(set(keys)) != len(keys):
        raise ValueError('OBSERVER_DUPLICATE_SAVED_TRADE')
    groups: dict[Any, list[dict[str, Any]]] = {k: [] for k in keys}
    seen = set()
    for o in observations:
        key = observation_key(o)
        stamp = _stamp(o['asof_ts_ms'])
        if key not in groups or (key, stamp) in seen:
            raise ValueError('OBSERVER_UNKNOWN_OR_DUPLICATE_OBSERVATION')
        seen.add((key, stamp)); groups[key].append(deepcopy(o))
    rows = []
    for trade, key in zip(trades, keys):
        entry, exit_at = _stamp(trade['entry_ts_ms']), _stamp(trade['exit_ts_ms'])
        if exit_at < entry or _stamp(trade['outcome_available_ts_ms']) < exit_at:
            raise ValueError('OBSERVER_SAVED_TRADE_CLOCK_INVALID')
        path = sorted(groups[key], key=lambda o: o['asof_ts_ms'])
        if any(o['asof_ts_ms'] < entry or o['asof_ts_ms'] > exit_at for o in path):
            raise ValueError('OBSERVER_OUTSIDE_HELD_PATH')
        complete = coverage.get(key) is True
        earlier = [o for o in path if o['asof_ts_ms'] < exit_at]
        negative = [o for o in earlier if o['features_asof']['negative_cross']]
        low = [o for o in earlier if o['features_asof']['below_signal_low'] is True]
        rows.append({
            'symbol': key[0], 'signal_ts_ms': key[1], 'signal_open_ts_ms': key[2],
            'regime': trade.get('regime'),
            'signal_low_policy_applies': trade.get('regime') == 'TREND_DISPERSED',
            'coverage': 'COMPLETE_CALLBACK_PATH' if complete else 'UNKNOWN_INCOMPLETE_CALLBACK_PATH',
            'negative_cross_before_exit_ts_ms': negative[0]['asof_ts_ms'] if negative else None,
            'signal_low_break_before_exit_ts_ms': low[0]['asof_ts_ms'] if low else None,
            'negative_cross_status': 'OBSERVED' if negative else 'NOT_OBSERVED_COMPLETE' if complete else 'UNKNOWN',
            'outcomes_not_features': {k: deepcopy(trade[k]) for k in
                                     ('gross_bps', 'cost_bps', 'net_bps', 'reason',
                                      'exit_ts_ms', 'outcome_available_ts_ms')},
            'saved_result_label': 'WIN' if trade['net_bps'] > 0 else 'LOSS' if trade['net_bps'] < 0 else 'ZERO',
            'profit_improvement': 'NOT_MEASURED',
        })
    return {'schema': 'zel.benchmark.saved_trade_observation_join.v1',
            'rows': rows, 'saved_trade_count': len(rows),
            'new_economic_runs': 0, 'selection_or_promotion': False,
            'scope': 'SAVED_OUTCOMES_PLUS_OBSERVATIONS_NOT_CAUSAL_EFFECT'}


def scan_saved_squeeze_paths(frames: Mapping[str, Any], saved_report: Mapping[str, Any]) -> dict[str, Any]:
    """Source-bound diagnostic of stored 57T, not regeneration of its strategy.

    Reuse the approved scan's source/receipt checks, then inspect ALL saved
    winners and losers up to their recorded exits. No counterfactual PnL/fills.
    Missing history aborts, rather than masquerading as no crossing.
    """
    from ops import scalp7_squeeze_signal_low_successor_v1 as policy
    from backend.research.rebuild import scalp7_execution_v2 as execution
    scan = policy.scan_saved_trend_triggers(frames, saved_report)
    trades, observations, coverage = saved_report['trade_rows'], [], {}
    for trade in trades:
        if trade['identity'] != policy.SAVED_OVERLAY or int(trade['side']) != 1:
            raise ValueError('OBSERVER_SAVED_SQUEEZE_IDENTITY_DRIFT')
        symbol = str(trade['symbol']); frame = frames[symbol]
        records, indexes = execution._frame_records(frame, 30)
        signal = deepcopy(trade['signal']); signal['identity'] = native.SQUEEZE_PARENT
        source_i, entry_i = indexes.get(int(signal['signal_open_ts_ms'])), indexes.get(int(trade['entry_ts_ms']))
        if source_i is None or entry_i is None or entry_i != source_i + 1:
            raise ValueError('OBSERVER_SAVED_ENTRY_CLOCK_UNBOUND')
        signal_bar = records[source_i]
        if (_row_clock(signal_bar) > _stamp(signal['signal_ts_ms']) or
                signal_bar['segment_id'] != signal['segment_id']):
            raise ValueError('OBSERVER_SIGNAL_LOW_UNBOUND')
        entry = float(trade['entry_prices'][symbol])
        if float(records[entry_i]['open']) != entry:
            raise ValueError('OBSERVER_SAVED_ENTRY_PRICE_UNBOUND')
        admission = native.entry_update(signal, entry)
        if admission.get('reject'):
            raise ValueError('OBSERVER_SAVED_ENTRY_REJECTED')
        stop = float(admission.get('stop_price', signal['stop_price']))
        cutoff = int(trade['exit_ts_ms']); previous = signal_bar
        complete = False
        for i in range(entry_i, len(records)):
            bar = records[i]
            if not execution._can_follow(previous, bar):
                raise ValueError('OBSERVER_SAVED_PATH_GAP')
            if int(bar['open_ts_ms']) >= cutoff:
                complete = True; break
            if _row_clock(bar) != int(bar['close_ts_ms']):
                raise ValueError('OBSERVER_SAVED_PATH_LATE_AVAILABILITY')
            if float(bar['low']) <= stop:
                stop_time = int(bar['open_ts_ms'] if float(bar['open']) < stop else bar['close_ts_ms'])
                if stop_time < cutoff:
                    raise ValueError('OBSERVER_EARLIER_STOP_CONFLICT')
                complete = True; break
            if int(bar['close_ts_ms']) >= cutoff:
                complete = True; break
            pos = {'entry_ts_ms': trade['entry_ts_ms'], 'side': 1, 'signal': signal}
            record = squeeze_observation(pos, bar, frame.iloc[:i+1],
                {'state': 'NOT_REPLAYED_SAVED_EXIT_RETAINED'}, signal_low=float(signal_bar['low']))
            record['identity'] = trade['identity']
            record['signal_low_policy_applies'] = trade['regime'] == 'TREND_DISPERSED'
            observations.append(record)
            previous = bar
        if not complete:
            raise ValueError('OBSERVER_SAVED_EXIT_SOURCE_NOT_COVERED')
        coverage[observation_key(trade)] = True
    joined = join_saved_squeeze(trades, observations, coverage)
    joined.update(saved_receipt_sha256=policy.SAVED_RECEIPT,
                  source_inventory_sha256=policy.INVENTORY,
                  approved_signal_low_scan=scan, callback_observations=observations)
    return joined
