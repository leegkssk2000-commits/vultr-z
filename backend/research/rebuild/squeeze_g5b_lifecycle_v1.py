"""Pure, additive exact-v1 lifecycle capability; no runtime or order authority.

``observe_completed`` derives entry and daily observations from the unchanged
C70/reg71 functions. All completed-close decisions must precede equal-clock
``observe_depth`` calls. A depth accounting fill is not an exchange order or
confirmation. Production evidence, qualification and boundary authorization are
separate gates; this module never grants formal credit.

The private observation method is also used for saved-trace conformance: that
checks the new transition engine against recorded decisions without replaying
strategy economics. Missing depth leaves an intent pending, and missing closes
fail closed instead of inventing historical decisions.
"""
from copy import deepcopy
from fractions import Fraction
from hashlib import sha256
import json
from math import fsum, isfinite

from backend.research.rebuild import c63_c70_trader_management_v1 as tm

LANE_ID = 'SQUEEZE_CONTINUATION_V1_G5B_FRESH'
ADAPTER_ID = 'SQUEEZE_CAPREUSE_EXACT_LIFECYCLE_V1'
STRATEGY_DIGEST = '5c63d3a69e1398dd1fae1076c9e8bdc29b8252a3188ac6b6a79571b363b22a16'
BAR, DAY = tm.BAR, tm.DAY


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                             allow_nan=False).encode()).hexdigest()


def select_adapter(lane_id, adapter_id, legacy_handler):
    """Capability selector only; does not register, activate or run a lane."""
    if lane_id != LANE_ID:
        return legacy_handler
    if adapter_id != ADAPTER_ID:
        raise ValueError('EXACT_SQUEEZE_ADAPTER_REQUIRED')
    return LifecycleAdapter


def _number(value, name, positive=False):
    if type(value) not in (int, float) or not isfinite(value) or (positive and value <= 0):
        raise ValueError(name)
    return float(value)


def _timestamp(value, name):
    if type(value) is not int or value < 0:
        raise ValueError(name)
    return value


def canonical_observation(bars):
    """Use only the supplied complete, contiguous prefix; never next-bar data."""
    tm.f.validate(bars)
    if not bars:
        raise ValueError('COMPLETED_PREFIX_REQUIRED')
    signals, _, features = tm.native.m1_setups(bars)
    i = len(bars)-1
    stamp = bars[i].open_ts+BAR
    candidates = [s for s in signals if s['signal_ts'] == stamp]
    entries = []
    for signal in candidates:
        context = tm.c70_context(tm.c63.context(bars, signal, tm.c63.er.context),
                                 tm.daily.observation(bars, i))
        entries.append(dict(signal=deepcopy(signal), context=context,
                            source_signal_sha=digest(signal)))
    momentum = features[i]['momentum'] if features[i] is not None else None
    return dict(close_ts=stamp, close=bars[i].close, momentum=momentum,
                daily=tm.daily_observation(bars, i), entries=entries)


def _book(levels, side):
    if not isinstance(levels, list) or not levels:
        raise ValueError('OBSERVED_DEPTH_REQUIRED')
    out = []
    for row in levels:
        if not isinstance(row, (list, tuple)) or len(row) != 2:
            raise ValueError('DEPTH_PRICE_QUANTITY_PAIR')
        out.append([_number(row[0], 'DEPTH_PRICE', True),
                    _number(row[1], 'DEPTH_QUANTITY', True)])
    prices = [p for p, _ in out]
    if prices != sorted(prices, reverse=(side == 'bid')) or len(prices) != len(set(prices)):
        raise ValueError('DEPTH_SORT_ORDER')
    return out


def _take(book, quantity):
    """Full intent only; insufficient book produces no pretend partial fill."""
    if fsum(q for _, q in book) < quantity:
        return None
    left, cash = quantity, 0.
    updated = deepcopy(book)
    for row in updated:
        take = min(left, row[1])
        cash += take*row[0]
        row[1] -= take
        left -= take
        if left <= 0:
            break
    price = book[0][0] if book[0][1] >= quantity else cash/quantity
    return price, [row for row in updated if row[1] > 0]


class LifecycleAdapter:
    """In-memory pure accounting state. Caller must persist/checkpoint its events.

    This capability intentionally has no network, runner registry or boundary
    writer. ``unit_quantity`` is the base asset quantity for normalized size 1;
    callers must bind its production provenance outside this class.
    """
    def __init__(self):
        self.lots = {}
        self.events = []
        self._seen = set()
        self._clock = (-1, -1)
        self._last_close = {}

    def _event(self, kind, **fields):
        row = dict(kind=kind, strategy_digest=STRATEGY_DIGEST,
                   execution='NONE', formal_credit=0, **fields)
        self.events.append(deepcopy(row))
        return row

    def _clock_check(self, observed_ms, phase, key):
        _timestamp(observed_ms, 'OBSERVATION_CLOCK')
        if key in self._seen:
            raise ValueError('DUPLICATE_OBSERVATION')
        if (observed_ms, phase) < self._clock:
            raise ValueError('CAUSAL_PHASE_ORDER_CLOSE_BEFORE_EQUAL_FILL')
        self._seen.add(key)
        self._clock = (observed_ms, phase)

    def capacity(self, symbol):
        active = sum((lot['remaining'] for lot in self.lots.values()
                      if lot['symbol'] == symbol), Fraction(0))
        reserved = sum((lot['allocation'] for lot in self.lots.values()
                        if lot['symbol'] == symbol and lot['status'] == 'PENDING_ENTRY'), Fraction(0))
        if not 0 <= active+reserved <= 1:
            raise AssertionError('SAME_SYMBOL_CAPACITY_OVERBOOKED')
        return active, reserved, 1-active-reserved

    def observe_completed(self, symbol, bars, *, observed_ms, checkpoint_costs=None,
                          unit_quantity=1.):
        observation = canonical_observation(bars)
        return self._observe_close(symbol, observation, observed_ms=observed_ms,
                                   checkpoint_costs=checkpoint_costs or {},
                                   unit_quantity=unit_quantity)

    def _observe_close(self, symbol, observation, *, observed_ms, checkpoint_costs=None,
                       unit_quantity=1.):
        """Trusted canonical observations or explicitly synthetic/saved fixtures.

        Reject malformed inputs atomically: an error cannot consume a day,
        signal, reservation or exactly-once key before the caller repairs it.
        """
        prior = (deepcopy(self.lots), set(self._seen), self._clock,
                 dict(self._last_close), len(self.events))
        try:
            return self._apply_close(symbol, observation, observed_ms=observed_ms,
                                     checkpoint_costs=checkpoint_costs,
                                     unit_quantity=unit_quantity)
        except (ValueError, KeyError, TypeError):
            blocks = [row for row in self.events[prior[4]:]
                      if row['kind'] == 'MISSING_CLOSE_BLOCK']
            self.lots, self._seen, self._clock, self._last_close = prior[:4]
            self.events[prior[4]:] = blocks
            raise

    def _apply_close(self, symbol, observation, *, observed_ms, checkpoint_costs=None,
                     unit_quantity=1.):
        obs = deepcopy(observation)
        stamp = _timestamp(obs['close_ts'], 'COMPLETED_CLOSE_CLOCK')
        _timestamp(observed_ms, 'OBSERVATION_CLOCK')
        if stamp % BAR or observed_ms < stamp:
            raise ValueError('INCOMPLETE_OR_FUTURE_CLOSE')
        close = _number(obs['close'], 'CLOSE_PRICE', True)
        unit_quantity = _number(unit_quantity, 'BASE_UNIT_QUANTITY', True)
        daily = obs['daily']
        if daily['available_at'] != stamp or daily['is_daily_close'] != (stamp % DAY == 0):
            raise ValueError('CAUSAL_DAILY_CLOCK')
        witnesses = daily.get('witnesses', [])
        if any(w['available_at'] > stamp for w in witnesses):
            raise ValueError('FUTURE_DAILY_WITNESS')
        previous = self._last_close.get(symbol)
        if previous is not None and stamp != previous+BAR:
            self._event('MISSING_CLOSE_BLOCK', symbol=symbol, close_ts=stamp,
                        prior_close_ts=previous, observed_ms=observed_ms,
                        missing_intervals=max(0, (stamp-previous)//BAR-1))
            raise ValueError('MISSING_OR_UNORDERED_COMPLETED_CLOSE')
        self._clock_check(observed_ms, 0, ('close', symbol, stamp))
        self._last_close[symbol] = stamp
        costs = checkpoint_costs or {}
        for lot in self.lots.values():
            if lot['symbol'] != symbol or lot['status'] != 'OPEN' or stamp <= lot['entry_ts']:
                continue
            if obs['momentum'] is None:
                raise ValueError('NATIVE_MOMENTUM_HISTORY_UNAVAILABLE')
            momentum = _number(obs['momentum'], 'MOMENTUM')
            if daily['is_daily_close']:
                lot['daily_count'] += 1
            first = daily['is_daily_close'] and lot['daily_count'] == 3 and not lot['managed']
            if first:
                lot['managed'] = True
            reason = 'FIXED_FLOOR_CLOSE' if close <= lot['signal']['floor'] else None
            if reason is None and lot['runner'] and close <= lot['entry_price']:
                reason = 'RUNNER_BREAKEVEN_CLOSE'
            if reason is None and not lot['runner'] and momentum <= 0:
                reason = 'MOMENTUM_NONPOSITIVE_CLOSE'
            if reason is None and lot['runner'] and daily['is_daily_close']:
                if daily['sma10'] is None:
                    reason = 'RUNNER_DAILY_HISTORY_SAFETY_CLOSE'
                elif close < daily['sma10']:
                    reason = 'RUNNER_SMA10_CLOSE'
            cost = costs.get(lot['lot_id'])
            progress = None
            if cost is not None:
                if cost.get('as_of_ms') != stamp or cost.get('entry_ts') != lot['entry_ts'] or not cost.get('cost_sha'):
                    raise ValueError('CHECKPOINT_COST_LINEAGE')
                progress = (close/lot['entry_price']-1)*10000-_number(cost['round_trip_bps'], 'CHECKPOINT_COST')
            pending = lot['pending']
            if reason is not None:
                # A not-yet-filled partial never owns the exit; native protection
                # may supersede it while depth is unavailable.
                if pending is None or pending['action'] == 'PARTIAL':
                    if pending is not None:
                        self._event('UNFILLED_PARTIAL_CANCELLED', lot_id=lot['lot_id'],
                                    close_ts=stamp, reason=reason)
                    lot['pending'] = self._intent('FINAL', reason, stamp, observed_ms)
            elif first and progress is not None and progress > 0 and pending is None:
                lot['pending'] = self._intent('PARTIAL', 'D3_PROFIT', stamp, observed_ms)
                if daily['sma10'] is None or close < daily['sma10']:
                    lot['pending']['exit_remainder'] = 'D3_SMA10_SAFETY_CLOSE'
            elif first and progress is None:
                self._event('CHECKPOINT_COST_MISSING_BLOCK', lot_id=lot['lot_id'], close_ts=stamp)
            lot['last_mark'] = dict(mark_ts=stamp, observed_ms=observed_ms, price=close,
                                    remaining_cost=deepcopy(cost))
            self._event('HELD_CLOSE_OBSERVATION', lot_id=lot['lot_id'], symbol=symbol,
                        close_ts=stamp, observed_ms=observed_ms,
                        observation_delay_ms=observed_ms-stamp,
                        daily_count=lot['daily_count'], first_management=first,
                        runner=lot['runner'], remaining_qty=float(lot['remaining']),
                        net_progress_bps=progress, pending=deepcopy(lot['pending']))
        decisions = []
        for entry in obs.get('entries', []):
            signal = deepcopy(entry['signal'])
            if signal['signal_ts'] != stamp or entry['source_signal_sha'] != digest(signal):
                raise ValueError('EXACT_SIGNAL_CLOCK_OR_HASH')
            active, reserved, available = self.capacity(symbol)
            reason = None
            if available <= 0:
                reason = 'ACTUAL_POSITION_OCCUPIED_AT_DECISION'
            elif signal['expiry'] is not None and stamp >= signal['expiry']:
                reason = 'SETUP_EXPIRED_BEFORE_ENTRY'
            elif not entry['context']['eligible']:
                reason = entry['context']['reason']
            lot_id = symbol+':'+entry['source_signal_sha']
            if reason is None:
                if lot_id in self.lots:
                    raise ValueError('DUPLICATE_SOURCE_SIGNAL')
                self.lots[lot_id] = dict(lot_id=lot_id, campaign_id=lot_id, symbol=symbol,
                    signal=signal, source_signal_sha=entry['source_signal_sha'],
                    allocation=available, remaining=Fraction(0), unit_quantity=unit_quantity,
                    status='PENDING_ENTRY', entry_ts=None, entry_price=None,
                    decision_ts=stamp, decision_observed_ts=observed_ms,
                    due_open_ts=stamp, capacity_reuse_entry=active+reserved > 0,
                    daily_count=0, managed=False, runner=False, partial_count=0,
                    pending=None, legs=[], last_mark=None)
            decisions.append(self._event('ENTRY_DECISION', lot_id=lot_id, symbol=symbol,
                close_ts=stamp, observed_ms=observed_ms,
                available_qty=float(available), active_qty=float(active),
                reserved_qty=float(reserved), admitted=reason is None, reason=reason,
                allocated_qty=float(available) if reason is None else 0.,
                source_signal_sha=entry['source_signal_sha']))
        self.capacity(symbol)
        return decisions

    @staticmethod
    def _intent(action, reason, stamp, observed_ms):
        return dict(action=action, reason=reason, decision_ts=stamp,
                    decision_observed_ts=observed_ms, due_open_ts=stamp)

    def observe_depth(self, symbol, depth):
        """Consume one actually observed book, once, across all pending lots.

        A pending quantity fills in full only if the supplied side covers it.
        Insufficient depth is visible and remains pending. Older snapshots never
        backfill a missed open. All prices are book VWAP, including gaps.
        """
        observed = _timestamp(depth['observed_ms'], 'DEPTH_OBSERVED_CLOCK')
        source = _timestamp(depth['source_ts'], 'DEPTH_SOURCE_CLOCK')
        if source > observed or not depth.get('snapshot_id'):
            raise ValueError('FUTURE_OR_UNIDENTIFIED_DEPTH')
        bids, asks = _book(depth['bids'], 'bid'), _book(depth['asks'], 'ask')
        if bids[0][0] > asks[0][0]:
            raise ValueError('CROSSED_DEPTH')
        self._clock_check(observed, 1, ('depth', symbol, depth['snapshot_id']))
        output = []
        lots = [lot for lot in self.lots.values() if lot['symbol'] == symbol]
        # Existing fills precede reserved new entries, whose size stays frozen.
        for lot in sorted(lots, key=lambda x: x['status'] == 'PENDING_ENTRY'):
            entry = lot['status'] == 'PENDING_ENTRY'
            intent = lot if entry else lot['pending']
            if intent is None or lot['status'] in ('CLOSED', 'GAP_CANCELLED'):
                continue
            if source < max(intent['due_open_ts'], intent['decision_observed_ts']):
                self._event('STALE_DEPTH_NO_FILL', lot_id=lot['lot_id'], source_ts=source,
                            observed_ms=observed, due_open_ts=intent['due_open_ts'])
                continue
            qty = lot['allocation'] if entry else (lot['allocation']/3 if intent['action'] == 'PARTIAL' else lot['remaining'])
            taken = _take(asks if entry else bids, float(qty)*lot['unit_quantity'])
            if taken is None:
                self._event('INSUFFICIENT_DEPTH_NO_FILL', lot_id=lot['lot_id'],
                            source_ts=source, observed_ms=observed, required_qty=float(qty))
                continue
            price, book = taken
            if entry:
                signal = lot['signal']
                if price <= signal['floor'] or signal['target'] is not None and price >= signal['target']:
                    lot['status'] = 'GAP_CANCELLED'
                    output.append(self._event('GAP_INVALIDATES_FIXED_SETUP', lot_id=lot['lot_id'],
                                              source_ts=source, observed_ms=observed, price=price))
                    continue
                asks = book
                lot.update(status='OPEN', remaining=qty, entry_ts=source, entry_price=price)
                kind, reason = 'ENTRY_FILL', 'ENTRY_NEXT_OPEN'
            else:
                bids = book
                lot['remaining'] -= qty
                partial = intent['action'] == 'PARTIAL'
                kind = 'PARTIAL_FILL' if partial else 'FINAL_FILL'
                reason = 'D3_PROFIT_PARTIAL_NEXT_OPEN' if partial else intent['reason']+'_NEXT_OPEN'
                if partial:
                    lot['runner'] = True
                    lot['partial_count'] += 1
                else:
                    lot['status'] = 'CLOSED'
                lot['pending'] = None
            fill = self._event(kind, lot_id=lot['lot_id'], campaign_id=lot['campaign_id'],
                symbol=symbol, side='BUY' if entry else 'SELL', price=price,
                qty=float(qty), remaining_qty=float(lot['remaining']),
                quantity_fraction=[qty.numerator, qty.denominator],
                base_qty=float(qty)*lot['unit_quantity'], notional=price*float(qty)*lot['unit_quantity'],
                reason=reason, decision_ts=intent['decision_ts'], due_open_ts=intent['due_open_ts'],
                decision_observed_ts=intent['decision_observed_ts'], source_ts=source,
                observed_ms=observed, execution_delay_ms=source-intent['due_open_ts'],
                observation_delay_ms=observed-source, snapshot_id=depth['snapshot_id'],
                bid=depth['bids'][0][0], ask=depth['asks'][0][0],
                mid=(depth['bids'][0][0]+depth['asks'][0][0])/2,
                source_signal_sha=lot['source_signal_sha'],
                fill_semantics='OBSERVED_DEPTH_ACCOUNTING_FILL_NO_EXCHANGE_ORDER')
            lot['legs'].append(deepcopy(fill)); output.append(fill)
            # The safety decision was already made at D3 close. It may execute
            # the remainder at this same observed book, with no duplicate qty.
            if not entry and kind == 'PARTIAL_FILL' and intent.get('exit_remainder'):
                remainder = lot['remaining']
                taken = _take(bids, float(remainder)*lot['unit_quantity'])
                next_intent = dict(intent, action='FINAL', reason=intent['exit_remainder'])
                next_intent.pop('exit_remainder', None)
                lot['pending'] = next_intent
                if taken is not None:
                    px, bids = taken
                    lot['remaining'] = Fraction(0); lot['status'] = 'CLOSED'; lot['pending'] = None
                    final = dict(fill, kind='FINAL_FILL', price=px, qty=float(remainder),
                        remaining_qty=0., quantity_fraction=[remainder.numerator, remainder.denominator],
                        base_qty=float(remainder)*lot['unit_quantity'],
                        notional=px*float(remainder)*lot['unit_quantity'],
                        reason=intent['exit_remainder']+'_NEXT_OPEN')
                    self.events.append(deepcopy(final)); lot['legs'].append(deepcopy(final)); output.append(final)
                else:
                    self._event('INSUFFICIENT_DEPTH_NO_FILL', lot_id=lot['lot_id'],
                                source_ts=source, observed_ms=observed, required_qty=float(remainder))
            self.capacity(symbol)
        return deepcopy(output)

    def snapshot(self):
        result = []
        for source in self.lots.values():
            lot = deepcopy(source)
            for field in ('allocation', 'remaining'):
                fraction = lot[field]
                lot[field+'_fraction'] = [fraction.numerator, fraction.denominator]
                lot[field] = float(fraction)
            mark = lot['last_mark']
            lot['terminal_liquidation'] = False
            lot['formal_credit'] = 0
            lot['final_net_bps'] = None  # actual per-leg fee/funding authority is external
            if lot['status'] == 'OPEN':
                lot['censor_reason'] = 'PENDING_EXIT_OUTSIDE_OBSERVATIONS' if lot['pending'] else 'HOLD_UNFINISHED'
                lot['remaining_mark_gross_bps'] = (lot['remaining']*(mark['price']/lot['entry_price']-1)*10000
                                                  if mark else None)
                cost = mark['remaining_cost'] if mark else None
                lot['remaining_mark_cost_bps'] = lot['remaining']*cost['round_trip_bps'] if cost else None
            lot['realized_partial_gross_bps'] = fsum(
                leg['qty']*(leg['price']/lot['entry_price']-1)*10000
                for leg in lot['legs'] if leg['kind'] == 'PARTIAL_FILL')
            result.append(lot)
        return dict(adapter_id=ADAPTER_ID, lots=result, events=deepcopy(self.events),
                    execution='NONE', runtime_registered=False, formal_credit=0)


def verify_saved_campaign(raw, trace, cost):
    """Compare new lifecycle transitions with one saved v1 campaign; no economics.

    Entry admission and portfolio scheduling are checked separately. This audit
    starts from the already-admitted saved entry and consumes its recorded close
    observations, costs and observed open fills. It does not regenerate trades,
    tune parameters, compute performance or create production-grade evidence.
    """
    adapter = LifecycleAdapter()
    first = trace[0]
    assert first['kind'] == 'ENTRY_NEXT_OPEN'
    signal = dict(signal_ts=raw['signal_ts'], signal_index=raw['signal_index'],
                  floor=raw['fixed_floor'], target=raw['fixed_target'], expiry=None,
                  setup_id=raw['setup_id'])
    qty = Fraction(raw.get('allocation_numerator', 1), raw.get('allocation_denominator', 1))
    lot_id = 'SAVED:'+str(raw['signal_index'])
    adapter.lots[lot_id] = dict(lot_id=lot_id, campaign_id=lot_id, symbol='SAVED',
        signal=signal, source_signal_sha=digest(signal), allocation=qty, remaining=qty,
        unit_quantity=1., status='OPEN', entry_ts=raw['entry_ts'], entry_price=raw['entry_price'],
        daily_count=0, managed=False, runner=False, partial_count=0, pending=None,
        legs=[], last_mark=None, capacity_reuse_entry=raw.get('capacity_reuse_entry', False))
    compared_observations, compared_fills = 0, 0
    i = 1
    while i < len(trace):
        row = trace[i]
        if row['kind'] == 'HELD_CLOSE_OBSERVATION':
            cost_obs = dict(as_of_ms=row['ts'], entry_ts=raw['entry_ts'],
                            round_trip_bps=tm.cost_at(cost, raw['entry_ts'], row['ts']),
                            cost_sha=digest(cost), basis='SAVED_DEV_PROXY_FORMAL_CREDIT_ZERO')
            adapter._observe_close('SAVED', dict(close_ts=row['ts'], close=row['close'],
                momentum=row['momentum'], daily=row['daily'], entries=[]),
                observed_ms=row['ts'], checkpoint_costs={lot_id:cost_obs})
            lot = adapter.lots[lot_id]
            assert abs(adapter.events[-1]['net_progress_bps']-row['net_progress_bps']) < 1e-9, 'SAVED_COST_CHECKPOINT'
            assert lot['daily_count'] == row['daily_count'], 'SAVED_DAILY_COUNT'
            assert lot['runner'] == row['runner'], 'SAVED_EXIT_OWNERSHIP'
            assert abs(float(lot['remaining'])-float(qty)*row['remaining_qty']) < 1e-12, 'SAVED_REMAINING_QTY'
            pending = lot['pending']; original = row['pending']
            assert (pending is None) == (original is None), 'SAVED_PENDING_PRESENCE'
            if pending:
                for name in ('action', 'reason', 'exit_remainder'):
                    assert pending.get(name) == original.get(name), 'SAVED_PENDING_'+name
                assert pending['decision_ts'] == original['signal_ts'], 'SAVED_DECISION_CLOCK'
            compared_observations += 1
        elif row['kind'] in ('PARTIAL_FILL', 'FINAL_FILL'):
            price = row['price']; stamp = row['ts']
            filled = adapter.observe_depth('SAVED', dict(observed_ms=stamp, source_ts=stamp,
                snapshot_id='SAVED:'+str(stamp), bids=[[price, 100.]], asks=[[price, 100.]]))
            expected = [row]
            if row['kind'] == 'PARTIAL_FILL' and i+1 < len(trace) and trace[i+1]['kind'] == 'FINAL_FILL' and trace[i+1]['ts'] == stamp:
                expected.append(trace[i+1]); i += 1
            assert len(filled) == len(expected), 'SAVED_FILL_COUNT'
            for actual, previous in zip(filled, expected):
                assert actual['kind'] == previous['kind'], 'SAVED_FILL_KIND'
                assert actual['source_ts'] == previous['ts'] and actual['price'] == previous['price'], 'SAVED_FILL_CLOCK_PRICE'
                assert abs(actual['remaining_qty']-float(qty)*previous['remaining_qty']) < 1e-12, 'SAVED_FILL_REMAINING'
            compared_fills += len(filled)
        elif row['kind'] == 'TERMINAL_MARK':
            lot = adapter.lots[lot_id]
            assert lot['status'] == 'OPEN' and lot['last_mark']['price'] == row['price'], 'SAVED_CENSOR_MARK'
        else:
            raise AssertionError('UNEXPECTED_SAVED_TRACE_KIND')
        i += 1
    lot = adapter.lots[lot_id]
    assert lot['partial_count'] == raw['partial_count'], 'SAVED_PARTIAL_COUNT'
    assert lot['runner'] == raw['runner_activated'], 'SAVED_RUNNER_ACTIVATION'
    assert abs(float(lot['remaining'])-float(qty)*raw['remaining_qty']) < 1e-12, 'SAVED_TERMINAL_QUANTITY'
    expected_legs = [leg for leg in raw['tm_legs'] if leg['status'] == 'C']
    assert len(lot['legs']) == len(expected_legs), 'SAVED_LEG_COUNT'
    for actual, expected in zip(lot['legs'], expected_legs):
        assert actual['reason'] == expected['reason'], 'SAVED_LEG_REASON'
        assert abs(actual['qty']-float(qty)*expected['qty']) < 1e-12, 'SAVED_LEG_QUANTITY'
    return dict(status='PASS', close_observations=compared_observations,
                fills=compared_fills, campaigns=1, economic_replays=0, formal_credit=0,
                mode='NEW_ADAPTER_SAVED_ADMITTED_CAMPAIGN_TRANSITIONS')
