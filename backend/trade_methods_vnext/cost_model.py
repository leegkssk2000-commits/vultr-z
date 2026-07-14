from __future__ import annotations

from .types import CostBreakdown, CostInputs, all_finite


def compute_all_in_cost(costs: CostInputs) -> CostBreakdown:
    if not all_finite(costs.values()):
        raise ValueError("NON_FINITE_COST_INPUT")
    if any(value < 0 for value in costs.values()):
        raise ValueError("NEGATIVE_COST_INPUT")
    total = sum(costs.values())
    return CostBreakdown(round_trip_fee_bps=costs.fee_bps_round_trip, spread_bps=costs.spread_bps, slippage_bps=costs.slippage_bps, funding_horizon_bps=costs.funding_bps_horizon, market_impact_bps=costs.market_impact_bps, latency_adverse_selection_bps=costs.latency_adverse_selection_bps, total_bps=round(total, 10))


def net_edge_after_cost(*, expected_gross_edge_bps: float, breakdown: CostBreakdown) -> float:
    return round(expected_gross_edge_bps - breakdown.total_bps, 10)
