from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Any, Mapping, Sequence

LICO_OWNER = "canonical/lico.py"
LICO_MANIFEST = MappingProxyType({
    "component": "Lico",
    "role": "liquidity_cost_context_observer",
    "canonical_owner": LICO_OWNER,
    "observer_only": True,
    "execution_authority": "none",
    "runtime_enabled": False,
    "order_enabled": False,
    "allowed_actions": ("hold", "route_change"),
})
EXECUTION_AUTHORITY = "none"
OBSERVER_ONLY = True
RUNTIME_ENABLED = False
ORDER_ENABLED = False
ALLOWED_ACTIONS = frozenset({"hold", "route_change"})
SOURCE_PREFIXES = ("cf:", "sheets:")


@dataclass(frozen=True)
class SourceObservation:
    source_id: str
    metric_key: str
    value: Any
    observed_at_ms: int
    source_status: str
    source_confidence: Decimal
    source_ref: str


@dataclass(frozen=True)
class SourceConsensusPolicy:
    required_source_prefixes: tuple[str, ...]
    required_metrics: tuple[str, ...]
    max_age_ms: int
    numeric_tolerance_by_metric: Mapping[str, Decimal]
    minimum_source_confidence: Decimal
    policy_refs: tuple[str, ...]
    schema_version: str


@dataclass(frozen=True)
class LicoContextEnvelope:
    state: str
    action: str
    reason_codes: tuple[str, ...]
    source_registry: Mapping[str, tuple[str, ...]]
    source_keys: tuple[str, ...]
    source_refs: tuple[str, ...]
    source_status: str
    source_parity: bool
    source_consensus: bool
    consensus_score: Decimal
    source_confidence: Decimal
    source_disagreement: tuple[str, ...]
    stale: bool
    source_age_ms: int
    fail_closed: bool
    abstain: bool
    observer_only: bool
    execution_authority: str
    runtime_enabled: bool
    order_enabled: bool
    schema_version: str


def _decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float, str)):
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None
    return None


def _hold(
    reasons: Sequence[str],
    *,
    registry: Mapping[str, tuple[str, ...]] | None = None,
    source_keys: Sequence[str] = (),
    source_refs: Sequence[str] = (),
    source_age_ms: int = 0,
    disagreement: Sequence[str] = (),
    confidence: Decimal = Decimal("0"),
    schema_version: str = "unknown",
) -> LicoContextEnvelope:
    return LicoContextEnvelope(
        state="HOLD",
        action="hold",
        reason_codes=tuple(sorted(set(reasons))),
        source_registry=MappingProxyType(dict(registry or {})),
        source_keys=tuple(sorted(set(source_keys))),
        source_refs=tuple(sorted(set(source_refs))),
        source_status="invalid",
        source_parity=False,
        source_consensus=False,
        consensus_score=Decimal("0"),
        source_confidence=confidence,
        source_disagreement=tuple(sorted(set(disagreement))),
        stale="SOURCE_STALE" in reasons,
        source_age_ms=max(0, source_age_ms),
        fail_closed=True,
        abstain=True,
        observer_only=OBSERVER_ONLY,
        execution_authority=EXECUTION_AUTHORITY,
        runtime_enabled=RUNTIME_ENABLED,
        order_enabled=ORDER_ENABLED,
        schema_version=schema_version,
    )


def _validate_policy(policy: SourceConsensusPolicy) -> tuple[str, ...]:
    reasons: list[str] = []
    if tuple(policy.required_source_prefixes) != SOURCE_PREFIXES:
        reasons.append("POLICY_SOURCE_PREFIX_INVALID")
    if not policy.required_metrics or len(set(policy.required_metrics)) != len(policy.required_metrics):
        reasons.append("POLICY_METRICS_INVALID")
    if policy.max_age_ms < 0:
        reasons.append("POLICY_MAX_AGE_INVALID")
    if not Decimal("0") <= policy.minimum_source_confidence <= Decimal("1"):
        reasons.append("POLICY_CONFIDENCE_INVALID")
    if not policy.schema_version:
        reasons.append("POLICY_SCHEMA_VERSION_MISSING")
    if not policy.policy_refs or any(not ref.startswith(SOURCE_PREFIXES) for ref in policy.policy_refs):
        reasons.append("POLICY_REFS_INVALID")
    for metric, tolerance in policy.numeric_tolerance_by_metric.items():
        if metric not in policy.required_metrics or tolerance < 0:
            reasons.append("POLICY_TOLERANCE_INVALID")
    return tuple(sorted(set(reasons)))


def build_source_registry(observations: Sequence[SourceObservation]) -> Mapping[str, tuple[str, ...]]:
    registry: dict[str, list[str]] = {}
    for item in observations:
        registry.setdefault(item.metric_key, []).append(item.source_id)
    return MappingProxyType({
        metric: tuple(sorted(keys))
        for metric, keys in sorted(registry.items())
    })


def _compare_values(metric: str, left: Any, right: Any, policy: SourceConsensusPolicy) -> tuple[bool, Decimal]:
    left_decimal = _decimal(left)
    right_decimal = _decimal(right)
    if left_decimal is None or right_decimal is None:
        return (left == right, Decimal("1") if left == right else Decimal("0"))

    tolerance = policy.numeric_tolerance_by_metric.get(metric)
    if tolerance is None:
        return False, Decimal("0")
    difference = abs(left_decimal - right_decimal)
    if tolerance == 0:
        return (difference == 0, Decimal("1") if difference == 0 else Decimal("0"))
    score = max(Decimal("0"), Decimal("1") - (difference / tolerance))
    return difference <= tolerance, score


def evaluate_source_consensus(
    observations: Sequence[SourceObservation],
    *,
    now_ms: int,
    policy: SourceConsensusPolicy,
) -> LicoContextEnvelope:
    policy_errors = _validate_policy(policy)
    if policy_errors:
        return _hold(policy_errors, schema_version=policy.schema_version)
    if now_ms < 0:
        return _hold(("NOW_TS_INVALID",), schema_version=policy.schema_version)
    if not observations:
        return _hold(("SOURCE_OBSERVATIONS_MISSING",), schema_version=policy.schema_version)

    registry = build_source_registry(observations)
    source_keys = [item.source_id for item in observations]
    source_refs = [item.source_ref for item in observations]
    reasons: list[str] = []
    disagreement: list[str] = []
    ages: list[int] = []
    confidences: list[Decimal] = []
    metric_scores: list[Decimal] = []

    seen_identity: set[tuple[str, str]] = set()
    by_metric: dict[str, dict[str, SourceObservation]] = {}
    for item in observations:
        prefix = next((candidate for candidate in SOURCE_PREFIXES if item.source_id.startswith(candidate)), None)
        if prefix is None:
            reasons.append("SOURCE_ID_INVALID")
            continue
        identity = (item.metric_key, prefix)
        if identity in seen_identity:
            reasons.append("SOURCE_DUPLICATE_PREFIX")
            continue
        seen_identity.add(identity)
        if item.metric_key not in policy.required_metrics:
            reasons.append("SOURCE_METRIC_UNREGISTERED")
        if not item.source_ref or not item.source_ref.startswith(prefix):
            reasons.append("SOURCE_REF_INVALID")
        if item.source_status != "ready":
            reasons.append("SOURCE_STATUS_NOT_READY")
        if not Decimal("0") <= item.source_confidence <= Decimal("1"):
            reasons.append("SOURCE_CONFIDENCE_INVALID")
        else:
            confidences.append(item.source_confidence)
        if item.observed_at_ms < 0 or item.observed_at_ms > now_ms:
            reasons.append("SOURCE_TIMESTAMP_INVALID")
        else:
            age = now_ms - item.observed_at_ms
            ages.append(age)
            if age > policy.max_age_ms:
                reasons.append("SOURCE_STALE")
        by_metric.setdefault(item.metric_key, {})[prefix] = item

    for metric in policy.required_metrics:
        paired = by_metric.get(metric, {})
        if set(paired) != set(SOURCE_PREFIXES):
            reasons.append("SOURCE_PAIR_INCOMPLETE")
            disagreement.append(metric)
            continue
        agreed, score = _compare_values(metric, paired["cf:"].value, paired["sheets:"].value, policy)
        metric_scores.append(score)
        if not agreed:
            reasons.append("SOURCE_DISAGREEMENT")
            disagreement.append(metric)

    source_confidence = min(confidences) if confidences else Decimal("0")
    consensus_score = min(metric_scores) if metric_scores else Decimal("0")
    if source_confidence < policy.minimum_source_confidence:
        reasons.append("SOURCE_CONFIDENCE_BELOW_POLICY")

    if reasons:
        return _hold(
            reasons,
            registry=registry,
            source_keys=source_keys,
            source_refs=source_refs,
            source_age_ms=max(ages) if ages else 0,
            disagreement=disagreement,
            confidence=source_confidence,
            schema_version=policy.schema_version,
        )

    return LicoContextEnvelope(
        state="READY",
        action="hold",
        reason_codes=("SOURCE_CONSENSUS_READY",),
        source_registry=registry,
        source_keys=tuple(sorted(set(source_keys))),
        source_refs=tuple(sorted(set(source_refs))),
        source_status="ready",
        source_parity=True,
        source_consensus=True,
        consensus_score=consensus_score,
        source_confidence=source_confidence,
        source_disagreement=(),
        stale=False,
        source_age_ms=max(ages) if ages else 0,
        fail_closed=True,
        abstain=False,
        observer_only=OBSERVER_ONLY,
        execution_authority=EXECUTION_AUTHORITY,
        runtime_enabled=RUNTIME_ENABLED,
        order_enabled=ORDER_ENABLED,
        schema_version=policy.schema_version,
    )


@dataclass(frozen=True)
class MarketStreamSnapshot:
    venue: str
    symbol: str
    observed_at_ms: int
    sequence: int
    best_bid: Decimal
    best_ask: Decimal
    mark_price: Decimal
    index_price: Decimal
    funding_rate: Decimal
    order_book: tuple[tuple[Decimal, Decimal], ...]
    trade_stream: bool
    venue_status: str
    source_ref: str


@dataclass(frozen=True)
class VenueHealthPolicy:
    venue: str
    max_stream_age_ms: int
    max_sequence_gap: int
    minimum_book_levels: int
    max_mark_index_deviation_bps: Decimal
    allowed_venue_statuses: tuple[str, ...]
    policy_refs: tuple[str, ...]
    schema_version: str


@dataclass(frozen=True)
class VenueHealthEnvelope:
    state: str
    action: str
    reason_codes: tuple[str, ...]
    venue: str
    symbol: str
    market_stream_ready: bool
    venue_health: str
    source_age_ms: int
    sequence_gap: int
    book_level_count: int
    mark_index_deviation_bps: Decimal
    source_ref: str
    fail_closed: bool
    abstain: bool
    observer_only: bool
    execution_authority: str
    runtime_enabled: bool
    order_enabled: bool
    schema_version: str


def _venue_hold(
    reasons: Sequence[str],
    *,
    snapshot: MarketStreamSnapshot | None,
    source_age_ms: int = 0,
    sequence_gap: int = 0,
    mark_index_deviation_bps: Decimal = Decimal("0"),
    schema_version: str = "unknown",
) -> VenueHealthEnvelope:
    return VenueHealthEnvelope(
        state="HOLD",
        action="hold",
        reason_codes=tuple(sorted(set(reasons))),
        venue=snapshot.venue if snapshot else "unknown",
        symbol=snapshot.symbol if snapshot else "unknown",
        market_stream_ready=False,
        venue_health="unhealthy",
        source_age_ms=max(0, source_age_ms),
        sequence_gap=max(0, sequence_gap),
        book_level_count=len(snapshot.order_book) if snapshot else 0,
        mark_index_deviation_bps=max(Decimal("0"), mark_index_deviation_bps),
        source_ref=snapshot.source_ref if snapshot else "",
        fail_closed=True,
        abstain=True,
        observer_only=OBSERVER_ONLY,
        execution_authority=EXECUTION_AUTHORITY,
        runtime_enabled=RUNTIME_ENABLED,
        order_enabled=ORDER_ENABLED,
        schema_version=schema_version,
    )


def _normalize_symbol(symbol: str) -> str:
    return symbol.upper().replace("-", "").replace("_", "").replace("/", "").strip()


def _validate_venue_policy(policy: VenueHealthPolicy) -> tuple[str, ...]:
    reasons: list[str] = []
    if policy.venue != "BingX":
        reasons.append("VENUE_POLICY_NOT_BINGX")
    if policy.max_stream_age_ms < 0:
        reasons.append("VENUE_POLICY_AGE_INVALID")
    if policy.max_sequence_gap < 1:
        reasons.append("VENUE_POLICY_SEQUENCE_INVALID")
    if policy.minimum_book_levels < 1:
        reasons.append("VENUE_POLICY_BOOK_LEVEL_INVALID")
    if policy.max_mark_index_deviation_bps < 0:
        reasons.append("VENUE_POLICY_DEVIATION_INVALID")
    if not policy.allowed_venue_statuses:
        reasons.append("VENUE_POLICY_STATUS_INVALID")
    if not policy.policy_refs or any(not ref.startswith(SOURCE_PREFIXES) for ref in policy.policy_refs):
        reasons.append("VENUE_POLICY_REFS_INVALID")
    if not policy.schema_version:
        reasons.append("VENUE_POLICY_SCHEMA_MISSING")
    return tuple(sorted(set(reasons)))


def evaluate_market_stream(
    snapshot: MarketStreamSnapshot,
    *,
    previous: MarketStreamSnapshot | None,
    consensus: LicoContextEnvelope,
    now_ms: int,
    policy: VenueHealthPolicy,
) -> VenueHealthEnvelope:
    policy_errors = _validate_venue_policy(policy)
    if policy_errors:
        return _venue_hold(policy_errors, snapshot=snapshot, schema_version=policy.schema_version)

    reasons: list[str] = []
    normalized_symbol = _normalize_symbol(snapshot.symbol)
    if not consensus.source_consensus or not consensus.source_parity or consensus.state != "READY":
        reasons.append("SOURCE_CONSENSUS_NOT_READY")
    if snapshot.venue != policy.venue:
        reasons.append("VENUE_MISMATCH")
    if not normalized_symbol.endswith("USDT") or len(normalized_symbol) <= 4:
        reasons.append("SYMBOL_INVALID")
    if not snapshot.source_ref.startswith("cf:"):
        reasons.append("MARKET_SOURCE_REF_INVALID")
    if snapshot.observed_at_ms < 0 or snapshot.observed_at_ms > now_ms:
        reasons.append("MARKET_TIMESTAMP_INVALID")
        source_age_ms = 0
    else:
        source_age_ms = now_ms - snapshot.observed_at_ms
        if source_age_ms > policy.max_stream_age_ms:
            reasons.append("MARKET_STREAM_STALE")
    if snapshot.sequence < 1:
        reasons.append("MARKET_SEQUENCE_INVALID")

    sequence_gap = 0
    if previous is not None:
        if previous.venue != snapshot.venue or _normalize_symbol(previous.symbol) != normalized_symbol:
            reasons.append("MARKET_PREVIOUS_IDENTITY_MISMATCH")
        elif snapshot.sequence <= previous.sequence:
            reasons.append("MARKET_SEQUENCE_NON_MONOTONIC")
        else:
            sequence_gap = snapshot.sequence - previous.sequence
            if sequence_gap > policy.max_sequence_gap:
                reasons.append("MARKET_SEQUENCE_GAP")

    values = (
        snapshot.best_bid,
        snapshot.best_ask,
        snapshot.mark_price,
        snapshot.index_price,
        snapshot.funding_rate,
    )
    if any(not isinstance(value, Decimal) for value in values):
        reasons.append("MARKET_DECIMAL_TYPE_REQUIRED")
    if snapshot.best_bid <= 0 or snapshot.best_ask <= 0 or snapshot.mark_price <= 0 or snapshot.index_price <= 0:
        reasons.append("MARKET_PRICE_INVALID")
    if snapshot.best_bid >= snapshot.best_ask:
        reasons.append("MARKET_BOOK_CROSSED")
    if len(snapshot.order_book) < policy.minimum_book_levels:
        reasons.append("MARKET_BOOK_LEVELS_INSUFFICIENT")
    for price, quantity in snapshot.order_book:
        if price <= 0 or quantity <= 0:
            reasons.append("MARKET_BOOK_LEVEL_INVALID")
            break
    if not snapshot.trade_stream:
        reasons.append("MARKET_TRADE_STREAM_DOWN")
    if snapshot.venue_status not in policy.allowed_venue_statuses:
        reasons.append("VENUE_STATUS_BLOCKED")

    if snapshot.index_price > 0:
        mark_index_deviation_bps = abs(snapshot.mark_price - snapshot.index_price) / snapshot.index_price * Decimal("10000")
    else:
        mark_index_deviation_bps = Decimal("0")
    if mark_index_deviation_bps > policy.max_mark_index_deviation_bps:
        reasons.append("MARK_INDEX_DEVIATION_EXCEEDED")

    if reasons:
        return _venue_hold(
            reasons,
            snapshot=snapshot,
            source_age_ms=source_age_ms,
            sequence_gap=sequence_gap,
            mark_index_deviation_bps=mark_index_deviation_bps,
            schema_version=policy.schema_version,
        )

    return VenueHealthEnvelope(
        state="READY",
        action="hold",
        reason_codes=("MARKET_STREAM_VENUE_HEALTH_READY",),
        venue=snapshot.venue,
        symbol=normalized_symbol,
        market_stream_ready=True,
        venue_health="healthy",
        source_age_ms=source_age_ms,
        sequence_gap=sequence_gap,
        book_level_count=len(snapshot.order_book),
        mark_index_deviation_bps=mark_index_deviation_bps,
        source_ref=snapshot.source_ref,
        fail_closed=True,
        abstain=False,
        observer_only=OBSERVER_ONLY,
        execution_authority=EXECUTION_AUTHORITY,
        runtime_enabled=RUNTIME_ENABLED,
        order_enabled=ORDER_ENABLED,
        schema_version=policy.schema_version,
    )
