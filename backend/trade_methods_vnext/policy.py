from __future__ import annotations

from .cost_model import compute_all_in_cost, net_edge_after_cost
from .types import BlockReason, MethodProfile, MethodRequest, all_finite


def _dedupe(reasons: list[BlockReason]) -> tuple[BlockReason, ...]:
    seen: set[BlockReason] = set()
    ordered: list[BlockReason] = []
    for reason in reasons:
        if reason not in seen:
            seen.add(reason)
            ordered.append(reason)
    return tuple(ordered)


def evaluate_policy(request: MethodRequest, profile: MethodProfile, *, expected_profile_sha256: str, actual_profile_sha256: str) -> tuple[tuple[BlockReason, ...], float, float, tuple[str, ...]]:
    reasons: list[BlockReason] = []
    evidence: list[str] = []
    if not request.strategy_id.strip() or not request.symbol.strip() or not request.side.strip():
        reasons.append(BlockReason.MISSING_REQUIRED_INPUT)
    if not all_finite(request.numeric_values()):
        reasons.append(BlockReason.NON_FINITE_NUMERIC_INPUT)
    if expected_profile_sha256 != actual_profile_sha256:
        reasons.append(BlockReason.PROFILE_HASH_MISMATCH)
    if request.method != profile.method or request.method_subtype != profile.method_subtype or request.entry_style != profile.entry_style or request.hold_horizon != profile.hold_horizon or request.risk_mode != profile.risk_mode:
        reasons.append(BlockReason.INVALID_RISK_CONTRACT)
    try:
        cost = compute_all_in_cost(request.costs)
    except ValueError:
        reasons.append(BlockReason.INVALID_COST_INPUT)
        total_cost_bps = float("inf")
        net_edge_bps = float("-inf")
    else:
        total_cost_bps = cost.total_bps
        net_edge_bps = net_edge_after_cost(expected_gross_edge_bps=request.expected_gross_edge_bps, breakdown=cost)
        evidence.append("all_in_cost_computed")
    age_ms = request.evaluation_ts_epoch_ms - request.signal_ts_epoch_ms
    if age_ms < 0 or age_ms > profile.max_signal_age_seconds * 1000:
        reasons.append(BlockReason.STALE_SIGNAL)
    else:
        evidence.append("signal_fresh")
    if request.reference_price <= 0:
        reasons.append(BlockReason.MISSING_REQUIRED_INPUT)
    if request.costs.spread_bps > profile.max_spread_bps:
        reasons.append(BlockReason.SPREAD_TOO_WIDE)
    else:
        evidence.append("spread_within_profile")
    requested = request.market.requested_notional_usdt
    depth = request.market.available_depth_usdt
    depth_ratio = depth / requested if requested > 0 else 0.0
    if requested <= 0 or depth_ratio < profile.min_depth_ratio:
        reasons.append(BlockReason.INSUFFICIENT_LIQUIDITY)
    else:
        evidence.append("liquidity_sufficient")
    vol = request.market.realized_vol_bps
    atr = request.market.atr_bps
    if not (profile.min_realized_vol_bps <= vol <= profile.max_realized_vol_bps and profile.min_atr_bps <= atr <= profile.max_atr_bps):
        reasons.append(BlockReason.VOLATILITY_OUTSIDE_PROFILE)
    else:
        evidence.append("volatility_within_profile")
    if request.market.regime not in profile.allowed_regimes:
        reasons.append(BlockReason.REGIME_PROFILE_MISMATCH)
    else:
        evidence.append("regime_match")
    if request.risk.position_size_pct > profile.max_position_size_pct:
        reasons.append(BlockReason.POSITION_SIZE_LIMIT_EXCEEDED)
    else:
        evidence.append("position_size_within_profile")
    if request.risk.leverage > profile.max_leverage:
        reasons.append(BlockReason.LEVERAGE_LIMIT_EXCEEDED)
    else:
        evidence.append("leverage_within_profile")
    if request.risk.dd_day_pct > profile.max_dd_day_pct or request.risk.dd_total_pct > profile.max_dd_total_pct:
        reasons.append(BlockReason.DRAWDOWN_LIMIT_EXCEEDED)
    else:
        evidence.append("drawdown_within_profile")
    if request.risk.liq_buffer_pct < profile.min_liq_buffer_pct:
        reasons.append(BlockReason.LIQUIDATION_BUFFER_TOO_SMALL)
    else:
        evidence.append("liquidation_buffer_sufficient")
    if not (profile.target_r > 0 and profile.stop_r < 0 and profile.time_stop_seconds > 0 and 0.0 <= profile.size_multiplier <= 1.0):
        reasons.append(BlockReason.INVALID_RISK_CONTRACT)
    else:
        evidence.append("risk_contract_valid")
    required_net = profile.min_net_edge_bps + profile.safety_margin_bps
    if net_edge_bps <= required_net:
        reasons.append(BlockReason.NET_EDGE_NOT_ABOVE_COST_MARGIN)
    else:
        evidence.append("net_edge_above_cost_margin")
    return _dedupe(reasons), total_cost_bps, net_edge_bps, tuple(sorted(set(evidence)))
