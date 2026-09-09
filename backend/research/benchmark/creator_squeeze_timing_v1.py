"""Source-described order/management sequencing, NOT a trading strategy.

No I/O, provider calls, signal discovery, fills, PnL or production binding.
S1 means Carter's specific BEST_TIME_TO_BUY_OPTIONS description; not the
separate general plan, Dirty Squeeze, Squeeze Pro formula or ZEL M1/C63.
Caller-supplied resolved levels and actual acknowledgements are required.
Tests are artificial event sequences, never claimed historical trader cases.
"""
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from typing import Mapping, Sequence

SOURCE_ID = 'S1/BEST_TIME_TO_BUY_OPTIONS'
SCOPE = 'CREATOR_TIMING_CONFORMANCE_AFTER_PR1237_V1'


class Unresolved(ValueError):
    """Missing source/adapter semantics must not receive a silent default."""


def price(value: object) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise ValueError('EXACT_DECIMAL_REQUIRED')
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError('EXACT_DECIMAL_REQUIRED') from exc
    if not result.is_finite() or result <= 0:
        raise ValueError('POSITIVE_FINITE_PRICE_REQUIRED')
    return result


def integer(value: object, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(name)
    return value


@dataclass(frozen=True)
class Fact:
    value: object
    observed_at: int
    available_at: int
    source_ref: str

    def at(self, decision_at: int) -> object:
        for t in (self.observed_at, self.available_at, decision_at):
            integer(t, 'TIMESTAMP')
        if not self.source_ref or not self.observed_at <= self.available_at <= decision_at:
            raise Unresolved('FACT_NOT_KNOWN_AT_DECISION')
        return self.value


def entry_readiness(facts: Mapping[str, Fact], decision_at: int) -> dict:
    """Only the explicit S1 gates; qualitative context is NOT invented here."""
    required = ('source_variant', 'primary_timeframe', 'red_dots', 'close',
                'ema21', 'high_context', 'cup_handle_context')
    missing = [k for k in required if k not in facts]
    if missing:
        return {'status': 'UNRESOLVED', 'missing': missing, 'place_order': False}
    x = {k: facts[k].at(decision_at) for k in required}
    if x['source_variant'] != SOURCE_ID or x['primary_timeframe'] != 'SOURCE_DAILY_SESSION':
        raise Unresolved('SOURCE_VERSION_OR_TIMEFRAME_SUBSTITUTION')
    if type(x['high_context']) is not bool or type(x['cup_handle_context']) is not bool:
        raise Unresolved('QUALITATIVE_CONTEXT_NOT_RESOLVED')
    dots = integer(x['red_dots'], 'RED_DOT_COUNT')
    passed = dots >= 3 and price(x['close']) > price(x['ema21']) and x['high_context'] and x['cup_handle_context']
    # Weekly context is optional in S1; no M1 release, ER or BB-close gate added.
    return {'status': 'PREPARE_ONLY' if passed else 'WAIT', 'missing': [],
            'place_order': False, 'decision_at': decision_at,
            'source_variant': SOURCE_ID, 'qualitative_inputs_supplied_externally': True}


class EntryAllocation:
    """Conserves one entry cap. Source's 3/4/3 split is an example, not a default.

Cancellation acknowledgement is an explicit conservative adapter convention.
This class never places an order or claims a limit touch was a fill.
"""
    def __init__(self, total: int, ema8: int, ema21: int, breakout: int):
        for q in (total, ema8, ema21, breakout):
            integer(q, 'QUANTITY')
        if total <= 0 or ema8 + ema21 + breakout != total:
            raise ValueError('ENTRY_ALLOCATION_SUM')
        self.cap = total
        self.remaining = {'EMA8': ema8, 'EMA21': ema21, 'BREAKOUT': breakout}
        self.filled = 0
        self.cancel_pending: set[str] = set()
        self.cancelled: set[str] = set()
        self.breakout_requested = False
        self.breakout_activated = False
        self.last_at = -1
        self.fill_ids: set[str] = set()

    def _clock(self, at: int) -> None:
        integer(at, 'TIMESTAMP')
        if at < self.last_at:
            raise ValueError('OUT_OF_ORDER_EVENT')

    def fill(self, leg: str, quantity: int, at: int, fill_id: str) -> None:
        self._clock(at)
        integer(quantity, 'QUANTITY')
        if not fill_id or fill_id in self.fill_ids:
            raise ValueError('DUPLICATE_OR_EMPTY_FILL_ID')
        if leg not in self.remaining or leg in self.cancelled:
            raise ValueError('INACTIVE_ENTRY_LEG')
        if leg == 'BREAKOUT' and not self.breakout_activated:
            raise ValueError('BREAKOUT_NOT_ACTIVATED')
        if quantity <= 0 or quantity > self.remaining[leg] or self.filled + quantity > self.cap:
            raise ValueError('ENTRY_OVERFILL')
        # A real fill may arrive while cancellation is pending; reconcile it.
        self.remaining[leg] -= quantity
        self.filled += quantity
        self.fill_ids.add(fill_id)
        self.last_at = at

    def request_breakout(self, at: int) -> tuple[str, ...]:
        self._clock(at)
        if self.breakout_requested:
            raise ValueError('BREAKOUT_REQUEST_DUPLICATE')
        self.breakout_requested = True
        self.cancel_pending = {k for k in ('EMA8', 'EMA21') if self.remaining[k] > 0}
        self.last_at = at
        return tuple(sorted(self.cancel_pending))

    def acknowledge_cancel(self, leg: str, at: int) -> None:
        self._clock(at)
        if leg not in self.cancel_pending:
            raise ValueError('UNEXPECTED_CANCEL_ACK')
        self.cancel_pending.remove(leg)
        self.cancelled.add(leg)
        self.remaining[leg] = 0
        self.last_at = at

    def activate_breakout(self, at: int) -> int:
        self._clock(at)
        if not self.breakout_requested or self.breakout_activated or self.cancel_pending:
            raise Unresolved('PULLBACK_CANCELLATIONS_NOT_RECONCILED')
        # Do not place the original full cap on top of already-filled pullbacks.
        quantity = self.cap - self.filled
        self.remaining['BREAKOUT'] = quantity
        self.breakout_activated = True
        self.last_at = at
        return quantity


@dataclass(frozen=True)
class DailyLow:
    calendar_id: str
    session_index: int
    low: Decimal
    available_at: int


def runner_level(lows: Sequence[DailyLow], *, calendar_id: str,
                 current_session: int, decision_at: int,
                 offset: object, current_protection: object) -> Decimal:
    """Prior THREE source sessions, not three4h bars or today's eventual low.

Offset and nonloosening ratchet are declared adapter semantics, not inferred
from source prose. Breakeven here means underlying entry, not cost-net flat.
"""
    integer(current_session, 'SESSION_INDEX')
    integer(decision_at, 'TIMESTAMP')
    if current_session < 3 or not calendar_id or len(lows) != 3 or [d.session_index for d in lows] != list(range(current_session - 3, current_session)):
        raise Unresolved('EXACT_THREE_PRIOR_SOURCE_SESSIONS_REQUIRED')
    if [d.available_at for d in lows] != sorted(set(d.available_at for d in lows)):
        raise Unresolved('SESSION_CLOCK_ORDER')
    if any(d.calendar_id != calendar_id or type(d.available_at) is not int or not 0 <= d.available_at < decision_at for d in lows):
        raise Unresolved('RUNNER_LOW_NOT_AVAILABLE')
    proposed = min(price(d.low) for d in lows) - price(offset)
    if proposed <= 0:
        raise ValueError('NONPOSITIVE_TRAIL_LEVEL')
    return max(price(current_protection), proposed)


def early_failure(*, elapsed_trading_sessions: int, mark: Fact,
                  mark_basis: str, decision_at: int) -> bool:
    """S1's directional-option loss predicate, not an underlying-price proxy."""
    integer(elapsed_trading_sessions, 'SESSION_COUNT')
    if mark_basis != 'DIRECTIONAL_OPTION_NET_PNL':
        raise Unresolved('OPTION_PNL_CANNOT_BE_REPLACED_WITH_UNDERLYING')
    raw = mark.at(decision_at)
    if isinstance(raw, bool) or not isinstance(raw, (str, int, Decimal)):
        raise ValueError('OPTION_MARK_REQUIRED')
    net = Decimal(raw)
    if not net.is_finite():
        raise ValueError('OPTION_MARK_REQUIRED')
    # Only the declared third-session checkpoint, not a new recurring timer.
    # Source prose says both 'not profitable' and 'down money'; zero is unresolved.
    if elapsed_trading_sessions != 3:
        return False
    if net == 0:
        raise Unresolved('ZERO_PROFIT_SOURCE_WORDING_AMBIGUOUS')
    return net < 0


class ExitSequence:
    """Three reference-fraction tranches; not exchange lot rounding or fills.

Target events are external observations. No OHLC touch-to-fill inference.
A management stop changes only after its associated tranche is fully filled.
The fixed entry ATR and stop ratchet are explicit conformance-test choices.
"""
    def __init__(self, entry: object, entry_atr21: object):
        self.entry = price(entry)
        self.atr = price(entry_atr21)
        if self.entry - 2 * self.atr <= 0:
            raise ValueError('NONPOSITIVE_INITIAL_STOP')
        self.stop = self.entry - 2 * self.atr
        self.remaining = Fraction(1)
        self.stage = 0
        self.pending: str | None = None
        self.pending_remaining = Fraction(0)
        self.last_at = -1
        self.fill_ids: set[str] = set()

    def _clock(self, at: int) -> None:
        integer(at, 'TIMESTAMP')
        if at < self.last_at:
            raise ValueError('OUT_OF_ORDER_EVENT')

    def request_target(self, target: str, at: int, evidence: Fact) -> Fraction:
        self._clock(at)
        if evidence.at(at) is not True:
            raise Unresolved('TARGET_OBSERVATION_REQUIRED')
        expected = ('FIRST_HIGH', 'EXTENSION_1272', 'EXTENSION_1618')
        if self.stage >= 3 or self.pending is not None or target != expected[self.stage]:
            raise ValueError('TARGET_ORDER_OR_PENDING')
        self.pending = target
        self.pending_remaining = Fraction(1, 3)
        self.last_at = at
        return self.pending_remaining

    def acknowledge_fill(self, fraction: Fraction, at: int, fill_id: str) -> None:
        self._clock(at)
        if not isinstance(fraction, Fraction) or not 0 < fraction <= self.pending_remaining:
            raise ValueError('EXIT_FRACTION_OVERFILL')
        if not fill_id or fill_id in self.fill_ids or self.pending is None:
            raise ValueError('UNREQUESTED_OR_DUPLICATE_EXIT_FILL')
        self.pending_remaining -= fraction
        self.remaining -= fraction
        self.fill_ids.add(fill_id)
        self.last_at = at
        if not self.pending_remaining:
            self.stage += 1
            self.pending = None
            if self.stage == 1:
                self.stop = max(self.stop, self.entry - self.atr)
            elif self.stage == 2:
                self.stop = max(self.stop, self.entry)

    def update_runner(self, lows: Sequence[DailyLow], *, calendar_id: str,
                      current_session: int, decision_at: int, offset: object) -> Decimal:
        self._clock(decision_at)
        if self.stage != 2 or self.pending is not None:
            raise Unresolved('RUNNER_NOT_ACTIVE')
        value = runner_level(lows, calendar_id=calendar_id, current_session=current_session,
                             decision_at=decision_at, offset=offset, current_protection=self.stop)
        self.stop = value
        self.last_at = decision_at
        return value

    def quantity_for_fraction(self, filled_quantity: object, fraction: Fraction,
                              lot_step: object) -> Decimal:
        if not isinstance(fraction, Fraction) or not 0 < fraction <= 1:
            raise ValueError('REFERENCE_FRACTION')
        q = price(filled_quantity) * Decimal(fraction.numerator) / Decimal(fraction.denominator)
        step = price(lot_step)
        if q % step:
            raise Unresolved('LOT_ROUNDING_POLICY_REQUIRED')
        return q


UNRESOLVED_SOURCE_TO_CRYPTO = (
    'verified_squeeze_version_and_formula', 'causal_high_and_cup_handle_definition',
    'fib_anchor_selection', 'entry_expiry_and_gap_trigger_semantics',
    'source_daily_session_calendar', 'option_to_perpetual_loss_predicate',
    'atr_sampling_and_initial_stop_execution', 'target_offsets_and_lot_rounding',
    'partial_fill_cancel_replace_and_same_bar_priority',
    'partial_entry_exit_interleaving', 'residual_exit_branch_choice',
    'per_fill_cost_funding_and_unfinished_residual_accounting',
)


def economic_replay_authority() -> dict:
    return {'allowed': False, 'status': 'NOT_AN_ECONOMIC_ADAPTER',
            'missing': list(UNRESOLVED_SOURCE_TO_CRYPTO),
            'complete_observed_trader_cases': 0, 'audited_trader_returns': False,
            'new_strategy_candidates': 0, 'formal_credit': 0}
