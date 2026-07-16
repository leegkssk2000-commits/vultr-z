from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

from canonical.lico import (
    EXECUTION_AUTHORITY,
    OBSERVER_ONLY,
    ORDER_ENABLED,
    RUNTIME_ENABLED,
)
from canonical.lico_execution import ExecutionFillEnvelope

MODEL_OWNER = "canonical/lico.py"
MODEL_COMPONENT = "Lico"
MODEL_STAGE = "R4.5"
ALLOWED_SIDES = frozenset({"long", "short"})
ALLOWED_LIQUIDITY = frozenset({"maker", "taker"})
REQUIRED_STRESS_SCENARIOS = frozenset({
    "capital_stress",
    "liquidity_stress",
    "execution_degradation",
    "volatility_shock",
})
ZERO = Decimal("0")
ONE = Decimal("1")
HUNDRED = Decimal("100")
BPS = Decimal("10000")


@dataclass(frozen=True)
class PositionRiskSnapshot:
    position_id: str
    venue: str
    symbol: str
    side: str
    quantity: Decimal
    entry_price: Decimal
    mark_price: Decimal
    liquidation_price: Decimal
    leverage: Decimal
    margin_balance: Decimal
    maintenance_margin: Decimal
    opened_at_ms: int
    observed_at_ms: int
    funding_rate_8h: Decimal
    funding_intervals: int
    entry_liquidity: str
    exit_liquidity: str
    source_ref: str


@dataclass(frozen=True)
class StressScenario:
    name: str
    adverse_mark_move_pct: Decimal
    spread_multiplier: Decimal
    slippage_add_bps: Decimal
    funding_multiplier: Decimal
    margin_haircut_pct: Decimal


@dataclass(frozen=True)
class RiskCostPolicy:
    maker_fee_rate: Decimal
    taker_fee_rate: Decimal
    max_abs_funding_rate_8h: Decimal
    minimum_liq_buffer_pct: Decimal
    minimum_margin_buffer_pct: Decimal
    max_total_cost_bps: Decimal
    max_stress_cost_bps: Decimal
    max_snapshot_age_ms: int
    max_funding_intervals: int
    required_stress_scenarios: tuple[str, ...]
    policy_refs: tuple[str, ...]
    schema_version: str


@dataclass(frozen=True)
class LicoRiskEnvelope:
    state: str
    action: str
    reason_codes: tuple[str, ...]
    position_id: str
    venue: str
    symbol: str
    side: str
    notional: Decimal
    entry_fee: Decimal
    exit_fee: Decimal
    execution_cost: Decimal
    funding_pnl: Decimal
    funding_cost: Decimal
    total_cost: Decimal
    total_cost_bps: Decimal
    liq_buffer_pct: Decimal
    margin_buffer_pct: Decimal
    stress_scenario_count: int
    worst_stress_name: str
    worst_stress_mark_price: Decimal
    worst_stress_liq_buffer_pct: Decimal
    worst_stress_margin_buffer_pct: Decimal
    worst_stress_cost_bps: Decimal
    liquidation_breached: bool
    fee_funding_liquidation_model: bool
    stress_scenarios: bool
    accepted: bool
    fail_closed: bool
    abstain: bool
    observer_only: bool
    execution_authority: str
    runtime_enabled: bool
    order_enabled: bool
    source_ref: str
    schema_version: str


def _normalize_symbol(symbol: str) -> str:
    return symbol.upper().replace("-", "").replace("_", "").replace("/", "").strip()


def _fee_rate(liquidity: str, policy: RiskCostPolicy) -> Decimal:
    return policy.maker_fee_rate if liquidity == "maker" else policy.taker_fee_rate


def _liq_buffer_pct(side: str, mark_price: Decimal, liquidation_price: Decimal) -> Decimal:
    if mark_price <= 0 or liquidation_price <= 0:
        return ZERO
    if side == "long":
        return (mark_price - liquidation_price) / mark_price * HUNDRED
    return (liquidation_price - mark_price) / mark_price * HUNDRED


def _margin_buffer_pct(margin_balance: Decimal, maintenance_margin: Decimal) -> Decimal:
    if margin_balance <= 0:
        return ZERO
    return (margin_balance - maintenance_margin) / margin_balance * HUNDRED


def _hold(
    reasons: Sequence[str],
    *,
    snapshot: PositionRiskSnapshot | None,
    schema_version: str,
) -> LicoRiskEnvelope:
    return LicoRiskEnvelope(
        state="HOLD",
        action="hold",
        reason_codes=tuple(sorted(set(reasons))),
        position_id=snapshot.position_id if snapshot else "",
        venue=snapshot.venue if snapshot else "",
        symbol=_normalize_symbol(snapshot.symbol) if snapshot else "",
        side=snapshot.side if snapshot else "",
        notional=ZERO,
        entry_fee=ZERO,
        exit_fee=ZERO,
        execution_cost=ZERO,
        funding_pnl=ZERO,
        funding_cost=ZERO,
        total_cost=ZERO,
        total_cost_bps=ZERO,
        liq_buffer_pct=ZERO,
        margin_buffer_pct=ZERO,
        stress_scenario_count=0,
        worst_stress_name="",
        worst_stress_mark_price=ZERO,
        worst_stress_liq_buffer_pct=ZERO,
        worst_stress_margin_buffer_pct=ZERO,
        worst_stress_cost_bps=ZERO,
        liquidation_breached=False,
        fee_funding_liquidation_model=False,
        stress_scenarios=False,
        accepted=False,
        fail_closed=True,
        abstain=True,
        observer_only=OBSERVER_ONLY,
        execution_authority=EXECUTION_AUTHORITY,
        runtime_enabled=RUNTIME_ENABLED,
        order_enabled=ORDER_ENABLED,
        source_ref=snapshot.source_ref if snapshot else "",
        schema_version=schema_version,
    )


def _policy_errors(policy: RiskCostPolicy) -> tuple[str, ...]:
    reasons: list[str] = []
    rates = (
        policy.maker_fee_rate,
        policy.taker_fee_rate,
        policy.max_abs_funding_rate_8h,
        policy.minimum_liq_buffer_pct,
        policy.minimum_margin_buffer_pct,
        policy.max_total_cost_bps,
        policy.max_stress_cost_bps,
    )
    if any(value < 0 for value in rates):
        reasons.append("RISK_POLICY_NEGATIVE_THRESHOLD")
    if policy.max_snapshot_age_ms < 0 or policy.max_funding_intervals < 0:
        reasons.append("RISK_POLICY_WINDOW_INVALID")
    if set(policy.required_stress_scenarios) != REQUIRED_STRESS_SCENARIOS:
        reasons.append("RISK_POLICY_STRESS_SET_INVALID")
    if not policy.policy_refs or any(not ref.startswith(("cf:", "sheets:")) for ref in policy.policy_refs):
        reasons.append("RISK_POLICY_REFS_INVALID")
    if not policy.schema_version:
        reasons.append("RISK_POLICY_SCHEMA_MISSING")
    return tuple(sorted(set(reasons)))


def _snapshot_errors(
    snapshot: PositionRiskSnapshot,
    fill: ExecutionFillEnvelope,
    *,
    now_ms: int,
    policy: RiskCostPolicy,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if not snapshot.position_id:
        reasons.append("POSITION_ID_MISSING")
    if snapshot.venue != "BingX":
        reasons.append("POSITION_VENUE_NOT_BINGX")
    if not _normalize_symbol(snapshot.symbol).endswith("USDT"):
        reasons.append("POSITION_SYMBOL_INVALID")
    if snapshot.side not in ALLOWED_SIDES:
        reasons.append("POSITION_SIDE_INVALID")
    if snapshot.entry_liquidity not in ALLOWED_LIQUIDITY or snapshot.exit_liquidity not in ALLOWED_LIQUIDITY:
        reasons.append("POSITION_LIQUIDITY_ROLE_INVALID")
    if any(value <= 0 for value in (
        snapshot.quantity,
        snapshot.entry_price,
        snapshot.mark_price,
        snapshot.liquidation_price,
        snapshot.leverage,
        snapshot.margin_balance,
    )):
        reasons.append("POSITION_NUMERIC_INPUT_INVALID")
    if snapshot.maintenance_margin < 0 or snapshot.maintenance_margin >= snapshot.margin_balance:
        reasons.append("POSITION_MAINTENANCE_MARGIN_INVALID")
    if snapshot.opened_at_ms < 0 or snapshot.observed_at_ms < snapshot.opened_at_ms or snapshot.observed_at_ms > now_ms:
        reasons.append("POSITION_TIMESTAMP_INVALID")
    elif now_ms - snapshot.observed_at_ms > policy.max_snapshot_age_ms:
        reasons.append("POSITION_SNAPSHOT_STALE")
    if snapshot.funding_intervals < 0 or snapshot.funding_intervals > policy.max_funding_intervals:
        reasons.append("POSITION_FUNDING_INTERVAL_INVALID")
    if not snapshot.source_ref.startswith("cf:"):
        reasons.append("POSITION_SOURCE_REF_INVALID")
    if fill.state != "READY" or not fill.execution_cost_ready or not fill.realistic_fill_model:
        reasons.append("EXECUTION_FILL_NOT_READY")
    if fill.venue if hasattr(fill, "venue") else False:
        reasons.append("UNEXPECTED_EXECUTION_FILL_SCHEMA")
    if _normalize_symbol(fill.symbol) != _normalize_symbol(snapshot.symbol):
        reasons.append("EXECUTION_POSITION_SYMBOL_MISMATCH")
    if fill.filled_qty <= 0 or fill.average_fill_price <= 0:
        reasons.append("EXECUTION_FILL_QUANTITY_INVALID")
    expected_fill_side = "buy" if snapshot.side == "long" else "sell"
    if fill.side != expected_fill_side:
        reasons.append("EXECUTION_POSITION_SIDE_MISMATCH")
    return tuple(sorted(set(reasons)))


def _scenario_errors(scenarios: Sequence[StressScenario], policy: RiskCostPolicy) -> tuple[str, ...]:
    reasons: list[str] = []
    names = [scenario.name for scenario in scenarios]
    if len(names) != len(set(names)):
        reasons.append("STRESS_SCENARIO_DUPLICATE")
    if set(names) != set(policy.required_stress_scenarios):
        reasons.append("STRESS_SCENARIO_SET_INCOMPLETE")
    for scenario in scenarios:
        if scenario.adverse_mark_move_pct < 0 or scenario.adverse_mark_move_pct >= HUNDRED:
            reasons.append("STRESS_SCENARIO_MARK_MOVE_INVALID")
        if scenario.spread_multiplier < ONE or scenario.slippage_add_bps < 0:
            reasons.append("STRESS_SCENARIO_LIQUIDITY_INVALID")
        if scenario.funding_multiplier < 0:
            reasons.append("STRESS_SCENARIO_FUNDING_INVALID")
        if scenario.margin_haircut_pct < 0 or scenario.margin_haircut_pct >= HUNDRED:
            reasons.append("STRESS_SCENARIO_MARGIN_INVALID")
    return tuple(sorted(set(reasons)))


def evaluate_fee_funding_liquidation_stress(
    snapshot: PositionRiskSnapshot,
    fill: ExecutionFillEnvelope,
    *,
    scenarios: Sequence[StressScenario],
    now_ms: int,
    policy: RiskCostPolicy,
) -> LicoRiskEnvelope:
    errors = list(_policy_errors(policy))
    errors.extend(_snapshot_errors(snapshot, fill, now_ms=now_ms, policy=policy))
    errors.extend(_scenario_errors(scenarios, policy))
    if errors:
        return _hold(errors, snapshot=snapshot, schema_version=policy.schema_version)

    notional = snapshot.quantity * snapshot.entry_price
    mark_notional = snapshot.quantity * snapshot.mark_price
    entry_fee = notional * _fee_rate(snapshot.entry_liquidity, policy)
    exit_fee = mark_notional * _fee_rate(snapshot.exit_liquidity, policy)
    execution_cost = notional * fill.execution_cost_bps / BPS
    direction = ONE if snapshot.side == "long" else Decimal("-1")
    funding_pnl = -direction * mark_notional * snapshot.funding_rate_8h * Decimal(snapshot.funding_intervals)
    funding_cost = max(ZERO, -funding_pnl)
    total_cost = entry_fee + exit_fee + execution_cost + funding_cost
    total_cost_bps = total_cost / notional * BPS if notional > 0 else ZERO
    liq_buffer_pct = _liq_buffer_pct(snapshot.side, snapshot.mark_price, snapshot.liquidation_price)
    margin_buffer_pct = _margin_buffer_pct(snapshot.margin_balance, snapshot.maintenance_margin)

    worst_name = ""
    worst_mark = snapshot.mark_price
    worst_liq_buffer = liq_buffer_pct
    worst_margin_buffer = margin_buffer_pct
    worst_cost_bps = total_cost_bps
    liquidation_breached = liq_buffer_pct <= 0

    for scenario in scenarios:
        move = scenario.adverse_mark_move_pct / HUNDRED
        stressed_mark = (
            snapshot.mark_price * (ONE - move)
            if snapshot.side == "long"
            else snapshot.mark_price * (ONE + move)
        )
        stressed_liq_buffer = _liq_buffer_pct(snapshot.side, stressed_mark, snapshot.liquidation_price)
        stressed_margin = snapshot.margin_balance * (ONE - scenario.margin_haircut_pct / HUNDRED)
        stressed_margin_buffer = _margin_buffer_pct(stressed_margin, snapshot.maintenance_margin)
        funding_component_bps = funding_cost / notional * BPS if notional > 0 else ZERO
        stressed_cost_bps = (
            total_cost_bps
            + fill.spread_bps * (scenario.spread_multiplier - ONE)
            + fill.slippage_bps * (scenario.spread_multiplier - ONE)
            + scenario.slippage_add_bps
            + funding_component_bps * max(ZERO, scenario.funding_multiplier - ONE)
        )
        scenario_liquidated = stressed_liq_buffer <= 0
        if scenario_liquidated:
            liquidation_breached = True
        severity = (
            ONE if scenario_liquidated else ZERO,
            -stressed_liq_buffer,
            -stressed_margin_buffer,
            stressed_cost_bps,
        )
        current = (
            ONE if worst_liq_buffer <= 0 else ZERO,
            -worst_liq_buffer,
            -worst_margin_buffer,
            worst_cost_bps,
        )
        if severity > current:
            worst_name = scenario.name
            worst_mark = stressed_mark
            worst_liq_buffer = stressed_liq_buffer
            worst_margin_buffer = stressed_margin_buffer
            worst_cost_bps = stressed_cost_bps

    reasons: list[str] = ["FEE_FUNDING_LIQUIDATION_STRESS_READY"]
    action = "hold"
    accepted = True
    if abs(snapshot.funding_rate_8h) > policy.max_abs_funding_rate_8h:
        reasons.append("FUNDING_RATE_LIMIT_EXCEEDED")
        action = "route_change"
        accepted = False
    if liq_buffer_pct < policy.minimum_liq_buffer_pct:
        reasons.append("LIQ_BUFFER_BELOW_POLICY")
        action = "route_change"
        accepted = False
    if margin_buffer_pct < policy.minimum_margin_buffer_pct:
        reasons.append("MARGIN_BUFFER_BELOW_POLICY")
        action = "route_change"
        accepted = False
    if total_cost_bps > policy.max_total_cost_bps:
        reasons.append("TOTAL_COST_LIMIT_EXCEEDED")
        action = "route_change"
        accepted = False
    if worst_cost_bps > policy.max_stress_cost_bps:
        reasons.append("STRESS_COST_LIMIT_EXCEEDED")
        action = "route_change"
        accepted = False
    if worst_liq_buffer < policy.minimum_liq_buffer_pct:
        reasons.append("STRESS_LIQ_BUFFER_BELOW_POLICY")
        action = "route_change"
        accepted = False
    if worst_margin_buffer < policy.minimum_margin_buffer_pct:
        reasons.append("STRESS_MARGIN_BUFFER_BELOW_POLICY")
        action = "route_change"
        accepted = False
    if liquidation_breached:
        reasons.append("LIQUIDATION_STRESS_BREACH")
        action = "route_change"
        accepted = False

    return LicoRiskEnvelope(
        state="READY",
        action=action,
        reason_codes=tuple(sorted(set(reasons))),
        position_id=snapshot.position_id,
        venue=snapshot.venue,
        symbol=_normalize_symbol(snapshot.symbol),
        side=snapshot.side,
        notional=notional,
        entry_fee=entry_fee,
        exit_fee=exit_fee,
        execution_cost=execution_cost,
        funding_pnl=funding_pnl,
        funding_cost=funding_cost,
        total_cost=total_cost,
        total_cost_bps=total_cost_bps,
        liq_buffer_pct=liq_buffer_pct,
        margin_buffer_pct=margin_buffer_pct,
        stress_scenario_count=len(scenarios),
        worst_stress_name=worst_name,
        worst_stress_mark_price=worst_mark,
        worst_stress_liq_buffer_pct=worst_liq_buffer,
        worst_stress_margin_buffer_pct=worst_margin_buffer,
        worst_stress_cost_bps=worst_cost_bps,
        liquidation_breached=liquidation_breached,
        fee_funding_liquidation_model=True,
        stress_scenarios=True,
        accepted=accepted,
        fail_closed=True,
        abstain=False,
        observer_only=OBSERVER_ONLY,
        execution_authority=EXECUTION_AUTHORITY,
        runtime_enabled=RUNTIME_ENABLED,
        order_enabled=ORDER_ENABLED,
        source_ref=snapshot.source_ref,
        schema_version=policy.schema_version,
    )
