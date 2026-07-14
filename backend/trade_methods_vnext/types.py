from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from math import isfinite
from typing import Any


class StrEnum(str, Enum):
    def __str__(self) -> str:
        return self.value


class TradeMethod(StrEnum):
    SCALP_FIRST = "scalp_first"
    INTRADAY = "intraday"
    TACTICAL_SWING = "tactical_swing"
    BLOCKED = "blocked"


class MethodSubtype(StrEnum):
    REVERT = "revert"
    CONTINUATION = "continuation"
    LIQUIDITY_RECLAIM = "liquidity_reclaim"
    BREAKOUT_PROBE = "breakout_probe"
    RESCUE = "rescue"


class EntryStyle(StrEnum):
    PULLBACK_CONFIRM = "pullback_confirm"
    BREAK_RECLAIM = "break_reclaim"
    RANGE_REVERT = "range_revert"
    OBSERVE_THEN_CONFIRM = "observe_then_confirm"


class HoldHorizon(StrEnum):
    M3_15 = "3-15m"
    M10_45 = "10-45m"
    H2_6 = "2-6h"
    BLOCKED = "blocked"


class RiskMode(StrEnum):
    TIGHT = "tight"
    BALANCED = "balanced"
    DEFENSIVE = "defensive"
    BLOCKED = "blocked"


class ResolutionDecision(StrEnum):
    ALLOW = "allow"
    BLOCK = "block"


class BlockReason(StrEnum):
    NONE = "none"
    MISSING_REQUIRED_INPUT = "missing_required_input"
    NON_FINITE_NUMERIC_INPUT = "non_finite_numeric_input"
    UNSUPPORTED_FAMILY_SUBTYPE = "unsupported_family_subtype"
    STALE_SIGNAL = "stale_signal"
    NET_EDGE_NOT_ABOVE_COST_MARGIN = "net_edge_not_above_cost_margin"
    INSUFFICIENT_LIQUIDITY = "insufficient_liquidity"
    SPREAD_TOO_WIDE = "spread_too_wide"
    VOLATILITY_OUTSIDE_PROFILE = "volatility_outside_profile"
    REGIME_PROFILE_MISMATCH = "regime_profile_mismatch"
    DRAWDOWN_LIMIT_EXCEEDED = "drawdown_limit_exceeded"
    LIQUIDATION_BUFFER_TOO_SMALL = "liquidation_buffer_too_small"
    INVALID_RISK_CONTRACT = "invalid_risk_contract"
    PROFILE_HASH_MISMATCH = "profile_hash_mismatch"
    RESOLVER_NONDETERMINISM = "resolver_nondeterminism"
    INVALID_COST_INPUT = "invalid_cost_input"
    LEVERAGE_LIMIT_EXCEEDED = "leverage_limit_exceeded"
    POSITION_SIZE_LIMIT_EXCEEDED = "position_size_limit_exceeded"


@dataclass(frozen=True, slots=True)
class CostInputs:
    fee_bps_round_trip: float
    spread_bps: float
    slippage_bps: float
    funding_bps_horizon: float
    market_impact_bps: float
    latency_adverse_selection_bps: float

    def values(self) -> tuple[float, ...]:
        return (
            self.fee_bps_round_trip,
            self.spread_bps,
            self.slippage_bps,
            self.funding_bps_horizon,
            self.market_impact_bps,
            self.latency_adverse_selection_bps,
        )


@dataclass(frozen=True, slots=True)
class RiskInputs:
    position_size_pct: float
    leverage: float
    dd_day_pct: float
    dd_total_pct: float
    liq_buffer_pct: float

    def values(self) -> tuple[float, ...]:
        return (
            self.position_size_pct,
            self.leverage,
            self.dd_day_pct,
            self.dd_total_pct,
            self.liq_buffer_pct,
        )


@dataclass(frozen=True, slots=True)
class MarketContext:
    available_depth_usdt: float
    requested_notional_usdt: float
    realized_vol_bps: float
    atr_bps: float
    regime: str
    session_bucket: str

    def numeric_values(self) -> tuple[float, ...]:
        return (
            self.available_depth_usdt,
            self.requested_notional_usdt,
            self.realized_vol_bps,
            self.atr_bps,
        )


@dataclass(frozen=True, slots=True)
class MethodRequest:
    strategy_id: str
    symbol: str
    side: str
    signal_ts_epoch_ms: int
    evaluation_ts_epoch_ms: int
    reference_price: float
    expected_gross_edge_bps: float
    method: TradeMethod
    method_subtype: MethodSubtype
    entry_style: EntryStyle
    hold_horizon: HoldHorizon
    risk_mode: RiskMode
    costs: CostInputs
    risk: RiskInputs
    market: MarketContext

    def numeric_values(self) -> tuple[float, ...]:
        return (
            float(self.signal_ts_epoch_ms),
            float(self.evaluation_ts_epoch_ms),
            self.reference_price,
            self.expected_gross_edge_bps,
            *self.costs.values(),
            *self.risk.values(),
            *self.market.numeric_values(),
        )

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["method"] = self.method.value
        value["method_subtype"] = self.method_subtype.value
        value["entry_style"] = self.entry_style.value
        value["hold_horizon"] = self.hold_horizon.value
        value["risk_mode"] = self.risk_mode.value
        return value


@dataclass(frozen=True, slots=True)
class MethodProfile:
    method: TradeMethod
    method_subtype: MethodSubtype
    profile_version: str
    label: str
    entry_style: EntryStyle
    hold_horizon: HoldHorizon
    risk_mode: RiskMode
    target_r: float
    stop_r: float
    time_stop_seconds: int
    size_multiplier: float
    execution_overlays: tuple[str, ...]
    min_net_edge_bps: float
    safety_margin_bps: float
    max_spread_bps: float
    min_depth_ratio: float
    min_realized_vol_bps: float
    max_realized_vol_bps: float
    min_atr_bps: float
    max_atr_bps: float
    allowed_regimes: tuple[str, ...]
    max_signal_age_seconds: int
    max_position_size_pct: float
    max_leverage: float
    max_dd_day_pct: float
    max_dd_total_pct: float
    min_liq_buffer_pct: float

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["method"] = self.method.value
        value["method_subtype"] = self.method_subtype.value
        value["entry_style"] = self.entry_style.value
        value["hold_horizon"] = self.hold_horizon.value
        value["risk_mode"] = self.risk_mode.value
        value["execution_overlays"] = list(self.execution_overlays)
        value["allowed_regimes"] = list(self.allowed_regimes)
        return value


@dataclass(frozen=True, slots=True)
class CostBreakdown:
    round_trip_fee_bps: float
    spread_bps: float
    slippage_bps: float
    funding_horizon_bps: float
    market_impact_bps: float
    latency_adverse_selection_bps: float
    total_bps: float

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class MethodDecision:
    method: TradeMethod
    method_subtype: MethodSubtype
    profile_version: str
    profile_sha256: str
    entry_style: EntryStyle
    hold_horizon: HoldHorizon
    risk_mode: RiskMode
    target_r: float
    stop_r: float
    time_stop_seconds: int
    size_multiplier: float
    execution_overlays: tuple[str, ...]
    resolver_trace_id: str
    block_reason: BlockReason
    block_reasons: tuple[BlockReason, ...]
    expected_all_in_cost_bps: float
    net_edge_after_cost_bps: float
    decision: ResolutionDecision
    evidence_flags: tuple[str, ...]
    input_sha256: str
    output_sha256: str
    cost_breakdown: CostBreakdown

    def to_dict(self, *, include_output_hash: bool = True) -> dict[str, Any]:
        value = asdict(self)
        for key in (
            "method",
            "method_subtype",
            "entry_style",
            "hold_horizon",
            "risk_mode",
            "block_reason",
            "decision",
        ):
            value[key] = getattr(self, key).value
        value["block_reasons"] = [item.value for item in self.block_reasons]
        value["execution_overlays"] = list(self.execution_overlays)
        value["evidence_flags"] = list(self.evidence_flags)
        if not include_output_hash:
            value.pop("output_sha256", None)
        return value


def all_finite(values: tuple[float, ...]) -> bool:
    return all(isfinite(float(value)) for value in values)
