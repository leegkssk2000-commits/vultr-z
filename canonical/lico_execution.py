from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

from canonical.lico import (
    EXECUTION_AUTHORITY,
    OBSERVER_ONLY,
    ORDER_ENABLED,
    RUNTIME_ENABLED,
    MarketStreamSnapshot,
    VenueHealthEnvelope,
)

MODEL_OWNER = "canonical/lico.py"
MODEL_COMPONENT = "Lico"
MODEL_STAGE = "R4.4"
ALLOWED_SIDES = frozenset({"buy", "sell"})
ALLOWED_ORDER_TYPES = frozenset({"market", "limit"})


@dataclass(frozen=True)
class DepthLevel:
    price: Decimal
    quantity: Decimal


@dataclass(frozen=True)
class ExecutionBook:
    venue: str
    symbol: str
    observed_at_ms: int
    bids: tuple[DepthLevel, ...]
    asks: tuple[DepthLevel, ...]
    source_ref: str


@dataclass(frozen=True)
class ExecutionRequest:
    request_id: str
    side: str
    order_type: str
    quantity: Decimal
    submitted_at_ms: int
    limit_price: Decimal | None = None
    queue_ahead_qty: Decimal = Decimal("0")
    observed_trade_qty: Decimal = Decimal("0")


@dataclass(frozen=True)
class ExecutionCostPolicy:
    max_book_age_ms: int
    max_walk_levels: int
    max_slippage_bps: Decimal
    max_market_impact_bps: Decimal
    minimum_fill_ratio: Decimal
    base_latency_ms: int
    per_level_latency_ms: int
    max_fill_latency_ms: int
    policy_refs: tuple[str, ...]
    schema_version: str


@dataclass(frozen=True)
class ExecutionFillEnvelope:
    state: str
    action: str
    reason_codes: tuple[str, ...]
    request_id: str
    symbol: str
    side: str
    order_type: str
    fill_status: str
    requested_qty: Decimal
    filled_qty: Decimal
    unfilled_qty: Decimal
    fill_ratio: Decimal
    average_fill_price: Decimal
    first_fill_price: Decimal
    last_fill_price: Decimal
    reference_mid_price: Decimal
    spread_bps: Decimal
    slippage_bps: Decimal
    market_impact_bps: Decimal
    execution_cost_bps: Decimal
    walked_level_count: int
    queue_ahead_qty: Decimal
    first_fill_ts: int
    final_fill_ts: int
    fill_latency_ms: int
    no_fill: bool
    partial_fill: bool
    order_book_walking: bool
    queue_model: bool
    execution_cost_ready: bool
    realistic_fill_model: bool
    accepted: bool
    fail_closed: bool
    abstain: bool
    observer_only: bool
    execution_authority: str
    runtime_enabled: bool
    order_enabled: bool
    source_ref: str
    schema_version: str


def _zero() -> Decimal:
    return Decimal("0")


def _normalize_symbol(symbol: str) -> str:
    return symbol.upper().replace("-", "").replace("_", "").replace("/", "").strip()


def _hold(
    reasons: Sequence[str],
    *,
    request: ExecutionRequest | None,
    book: ExecutionBook | None,
    schema_version: str,
) -> ExecutionFillEnvelope:
    quantity = request.quantity if request and request.quantity > 0 else _zero()
    return ExecutionFillEnvelope(
        state="HOLD",
        action="hold",
        reason_codes=tuple(sorted(set(reasons))),
        request_id=request.request_id if request else "",
        symbol=_normalize_symbol(book.symbol) if book else "",
        side=request.side if request else "",
        order_type=request.order_type if request else "",
        fill_status="invalid",
        requested_qty=quantity,
        filled_qty=_zero(),
        unfilled_qty=quantity,
        fill_ratio=_zero(),
        average_fill_price=_zero(),
        first_fill_price=_zero(),
        last_fill_price=_zero(),
        reference_mid_price=_zero(),
        spread_bps=_zero(),
        slippage_bps=_zero(),
        market_impact_bps=_zero(),
        execution_cost_bps=_zero(),
        walked_level_count=0,
        queue_ahead_qty=request.queue_ahead_qty if request else _zero(),
        first_fill_ts=0,
        final_fill_ts=0,
        fill_latency_ms=0,
        no_fill=True,
        partial_fill=False,
        order_book_walking=False,
        queue_model=False,
        execution_cost_ready=False,
        realistic_fill_model=False,
        accepted=False,
        fail_closed=True,
        abstain=True,
        observer_only=OBSERVER_ONLY,
        execution_authority=EXECUTION_AUTHORITY,
        runtime_enabled=RUNTIME_ENABLED,
        order_enabled=ORDER_ENABLED,
        source_ref=book.source_ref if book else "",
        schema_version=schema_version,
    )


def _policy_errors(policy: ExecutionCostPolicy) -> tuple[str, ...]:
    reasons: list[str] = []
    if policy.max_book_age_ms < 0:
        reasons.append("EXECUTION_POLICY_BOOK_AGE_INVALID")
    if policy.max_walk_levels < 1:
        reasons.append("EXECUTION_POLICY_WALK_LEVELS_INVALID")
    if policy.max_slippage_bps < 0 or policy.max_market_impact_bps < 0:
        reasons.append("EXECUTION_POLICY_COST_INVALID")
    if not Decimal("0") <= policy.minimum_fill_ratio <= Decimal("1"):
        reasons.append("EXECUTION_POLICY_FILL_RATIO_INVALID")
    if policy.base_latency_ms < 0 or policy.per_level_latency_ms < 0 or policy.max_fill_latency_ms < 0:
        reasons.append("EXECUTION_POLICY_LATENCY_INVALID")
    if not policy.policy_refs or any(not ref.startswith(("cf:", "sheets:")) for ref in policy.policy_refs):
        reasons.append("EXECUTION_POLICY_REFS_INVALID")
    if not policy.schema_version:
        reasons.append("EXECUTION_POLICY_SCHEMA_MISSING")
    return tuple(sorted(set(reasons)))


def _book_errors(
    book: ExecutionBook,
    market: MarketStreamSnapshot,
    venue_health: VenueHealthEnvelope,
    *,
    now_ms: int,
    max_book_age_ms: int,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if venue_health.state != "READY" or not venue_health.market_stream_ready or venue_health.venue_health != "healthy":
        reasons.append("VENUE_HEALTH_NOT_READY")
    if book.venue != market.venue or book.venue != venue_health.venue:
        reasons.append("EXECUTION_BOOK_VENUE_MISMATCH")
    if _normalize_symbol(book.symbol) != _normalize_symbol(market.symbol):
        reasons.append("EXECUTION_BOOK_SYMBOL_MISMATCH")
    if not book.source_ref.startswith("cf:"):
        reasons.append("EXECUTION_BOOK_SOURCE_INVALID")
    if book.observed_at_ms < 0 or book.observed_at_ms > now_ms:
        reasons.append("EXECUTION_BOOK_TIMESTAMP_INVALID")
    elif now_ms - book.observed_at_ms > max_book_age_ms:
        reasons.append("EXECUTION_BOOK_STALE")
    if not book.bids or not book.asks:
        reasons.append("EXECUTION_BOOK_SIDE_MISSING")
        return tuple(sorted(set(reasons)))
    if any(level.price <= 0 or level.quantity <= 0 for level in (*book.bids, *book.asks)):
        reasons.append("EXECUTION_BOOK_LEVEL_INVALID")
    if any(book.bids[index].price < book.bids[index + 1].price for index in range(len(book.bids) - 1)):
        reasons.append("EXECUTION_BIDS_NOT_DESCENDING")
    if any(book.asks[index].price > book.asks[index + 1].price for index in range(len(book.asks) - 1)):
        reasons.append("EXECUTION_ASKS_NOT_ASCENDING")
    if book.bids[0].price >= book.asks[0].price:
        reasons.append("EXECUTION_BOOK_CROSSED")
    if book.bids[0].price != market.best_bid or book.asks[0].price != market.best_ask:
        reasons.append("EXECUTION_BBO_PARITY_FAILED")
    return tuple(sorted(set(reasons)))


def _request_errors(request: ExecutionRequest, *, now_ms: int) -> tuple[str, ...]:
    reasons: list[str] = []
    if not request.request_id:
        reasons.append("EXECUTION_REQUEST_ID_MISSING")
    if request.side not in ALLOWED_SIDES:
        reasons.append("EXECUTION_SIDE_INVALID")
    if request.order_type not in ALLOWED_ORDER_TYPES:
        reasons.append("EXECUTION_ORDER_TYPE_INVALID")
    if request.quantity <= 0:
        reasons.append("EXECUTION_QUANTITY_INVALID")
    if request.submitted_at_ms < 0 or request.submitted_at_ms > now_ms:
        reasons.append("EXECUTION_SUBMIT_TIMESTAMP_INVALID")
    if request.order_type == "limit" and (request.limit_price is None or request.limit_price <= 0):
        reasons.append("EXECUTION_LIMIT_PRICE_INVALID")
    if request.queue_ahead_qty < 0 or request.observed_trade_qty < 0:
        reasons.append("EXECUTION_QUEUE_INPUT_INVALID")
    return tuple(sorted(set(reasons)))


def _marketable_levels(book: ExecutionBook, request: ExecutionRequest) -> tuple[DepthLevel, ...]:
    levels = book.asks if request.side == "buy" else book.bids
    if request.order_type == "market":
        return levels
    assert request.limit_price is not None
    if request.side == "buy":
        return tuple(level for level in levels if level.price <= request.limit_price)
    return tuple(level for level in levels if level.price >= request.limit_price)


def _walk_book(
    levels: Sequence[DepthLevel],
    *,
    quantity: Decimal,
    max_levels: int,
) -> tuple[Decimal, Decimal, Decimal, int]:
    remaining = quantity
    notional = _zero()
    first_price = _zero()
    last_price = _zero()
    walked = 0
    for level in levels[:max_levels]:
        if remaining <= 0:
            break
        take = min(remaining, level.quantity)
        if take <= 0:
            continue
        if first_price == 0:
            first_price = level.price
        last_price = level.price
        notional += take * level.price
        remaining -= take
        walked += 1
    filled = quantity - remaining
    average = notional / filled if filled > 0 else _zero()
    return filled, average, first_price if filled > 0 else _zero(), last_price if filled > 0 else _zero(), walked


def simulate_execution(
    book: ExecutionBook,
    request: ExecutionRequest,
    *,
    market: MarketStreamSnapshot,
    venue_health: VenueHealthEnvelope,
    now_ms: int,
    policy: ExecutionCostPolicy,
) -> ExecutionFillEnvelope:
    errors = list(_policy_errors(policy))
    errors.extend(_book_errors(book, market, venue_health, now_ms=now_ms, max_book_age_ms=policy.max_book_age_ms))
    errors.extend(_request_errors(request, now_ms=now_ms))
    if request.submitted_at_ms < book.observed_at_ms:
        errors.append("EXECUTION_REQUEST_BEFORE_BOOK")
    if errors:
        return _hold(errors, request=request, book=book, schema_version=policy.schema_version)

    levels = _marketable_levels(book, request)
    queue_model = request.order_type == "limit" and not levels
    order_book_walking = bool(levels)
    if levels:
        filled_qty, average_fill, first_price, last_price, walked_levels = _walk_book(
            levels,
            quantity=request.quantity,
            max_levels=policy.max_walk_levels,
        )
    else:
        assert request.limit_price is not None
        passive_available = max(_zero(), request.observed_trade_qty - request.queue_ahead_qty)
        filled_qty = min(request.quantity, passive_available)
        average_fill = request.limit_price if filled_qty > 0 else _zero()
        first_price = average_fill
        last_price = average_fill
        walked_levels = 1 if filled_qty > 0 else 0

    unfilled_qty = request.quantity - filled_qty
    fill_ratio = filled_qty / request.quantity if request.quantity > 0 else _zero()
    no_fill = filled_qty == 0
    partial_fill = Decimal("0") < filled_qty < request.quantity
    fill_status = "no_fill" if no_fill else "partial_fill" if partial_fill else "filled"

    midpoint = (book.bids[0].price + book.asks[0].price) / Decimal("2")
    spread_bps = (book.asks[0].price - book.bids[0].price) / midpoint * Decimal("10000")
    touch = book.asks[0].price if request.side == "buy" else book.bids[0].price
    if filled_qty > 0:
        if request.side == "buy":
            slippage_bps = max(_zero(), (average_fill - touch) / touch * Decimal("10000"))
            market_impact_bps = max(_zero(), (last_price - touch) / touch * Decimal("10000"))
            execution_cost_bps = max(_zero(), (average_fill - midpoint) / midpoint * Decimal("10000"))
        else:
            slippage_bps = max(_zero(), (touch - average_fill) / touch * Decimal("10000"))
            market_impact_bps = max(_zero(), (touch - last_price) / touch * Decimal("10000"))
            execution_cost_bps = max(_zero(), (midpoint - average_fill) / midpoint * Decimal("10000"))
    else:
        slippage_bps = _zero()
        market_impact_bps = _zero()
        execution_cost_bps = _zero()

    first_fill_ts = request.submitted_at_ms + policy.base_latency_ms if filled_qty > 0 else 0
    final_fill_ts = (
        first_fill_ts + max(0, walked_levels - 1) * policy.per_level_latency_ms
        if filled_qty > 0
        else 0
    )
    fill_latency_ms = final_fill_ts - request.submitted_at_ms if filled_qty > 0 else 0

    reasons: list[str] = []
    action = "hold"
    accepted = True
    if no_fill:
        reasons.append("NO_FILL")
        accepted = False
    elif partial_fill:
        reasons.append("PARTIAL_FILL")
    else:
        reasons.append("FULL_FILL")
    if fill_ratio < policy.minimum_fill_ratio:
        reasons.append("FILL_RATIO_BELOW_POLICY")
        action = "route_change"
        accepted = False
    if slippage_bps > policy.max_slippage_bps:
        reasons.append("SLIPPAGE_LIMIT_EXCEEDED")
        action = "route_change"
        accepted = False
    if market_impact_bps > policy.max_market_impact_bps:
        reasons.append("MARKET_IMPACT_LIMIT_EXCEEDED")
        action = "route_change"
        accepted = False
    if fill_latency_ms > policy.max_fill_latency_ms:
        reasons.append("FILL_LATENCY_LIMIT_EXCEEDED")
        action = "route_change"
        accepted = False

    return ExecutionFillEnvelope(
        state="READY",
        action=action,
        reason_codes=tuple(sorted(set(reasons))),
        request_id=request.request_id,
        symbol=_normalize_symbol(book.symbol),
        side=request.side,
        order_type=request.order_type,
        fill_status=fill_status,
        requested_qty=request.quantity,
        filled_qty=filled_qty,
        unfilled_qty=unfilled_qty,
        fill_ratio=fill_ratio,
        average_fill_price=average_fill,
        first_fill_price=first_price,
        last_fill_price=last_price,
        reference_mid_price=midpoint,
        spread_bps=spread_bps,
        slippage_bps=slippage_bps,
        market_impact_bps=market_impact_bps,
        execution_cost_bps=execution_cost_bps,
        walked_level_count=walked_levels,
        queue_ahead_qty=request.queue_ahead_qty,
        first_fill_ts=first_fill_ts,
        final_fill_ts=final_fill_ts,
        fill_latency_ms=fill_latency_ms,
        no_fill=no_fill,
        partial_fill=partial_fill,
        order_book_walking=order_book_walking,
        queue_model=queue_model,
        execution_cost_ready=True,
        realistic_fill_model=True,
        accepted=accepted,
        fail_closed=True,
        abstain=False,
        observer_only=OBSERVER_ONLY,
        execution_authority=EXECUTION_AUTHORITY,
        runtime_enabled=RUNTIME_ENABLED,
        order_enabled=ORDER_ENABLED,
        source_ref=book.source_ref,
        schema_version=policy.schema_version,
    )
