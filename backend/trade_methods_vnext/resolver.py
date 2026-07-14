from __future__ import annotations

from dataclasses import replace
from math import isfinite
from typing import Mapping

from .cost_model import compute_all_in_cost
from .lineage import input_sha256, output_sha256, profile_sha256, resolver_trace_id
from .manifest import is_allowed, manifest_index
from .policy import evaluate_policy
from .profiles import METHOD_PROFILES
from .types import BlockReason, CostBreakdown, EntryStyle, HoldHorizon, MethodDecision, MethodProfile, MethodRequest, MethodSubtype, ResolutionDecision, RiskMode, TradeMethod


def _zero_cost_breakdown() -> CostBreakdown:
    return CostBreakdown(round_trip_fee_bps=0.0, spread_bps=0.0, slippage_bps=0.0, funding_horizon_bps=0.0, market_impact_bps=0.0, latency_adverse_selection_bps=0.0, total_bps=0.0)


def _blocked_decision(request: MethodRequest, *, reasons: tuple[BlockReason, ...], profile: MethodProfile | None, profile_hash: str, total_cost_bps: float, net_edge_bps: float, evidence_flags: tuple[str, ...]) -> MethodDecision:
    request_hash = input_sha256(request)
    primary_reason = reasons[0] if reasons else BlockReason.UNSUPPORTED_FAMILY_SUBTYPE
    trace = resolver_trace_id(request_hash=request_hash, profile_hash=profile_hash, decision_code=f"block:{primary_reason.value}")
    breakdown = _zero_cost_breakdown()
    try:
        breakdown = compute_all_in_cost(request.costs)
    except ValueError:
        pass
    base = MethodDecision(method=profile.method if profile else TradeMethod.BLOCKED, method_subtype=profile.method_subtype if profile else request.method_subtype, profile_version=profile.profile_version if profile else "unresolved", profile_sha256=profile_hash, entry_style=profile.entry_style if profile else EntryStyle.OBSERVE_THEN_CONFIRM, hold_horizon=HoldHorizon.BLOCKED, risk_mode=RiskMode.BLOCKED, target_r=0.0, stop_r=0.0, time_stop_seconds=0, size_multiplier=0.0, execution_overlays=("observer_only", "fail_closed"), resolver_trace_id=trace, block_reason=primary_reason, block_reasons=reasons or (primary_reason,), expected_all_in_cost_bps=total_cost_bps if isfinite(total_cost_bps) else 0.0, net_edge_after_cost_bps=net_edge_bps if isfinite(net_edge_bps) else 0.0, decision=ResolutionDecision.BLOCK, evidence_flags=tuple(sorted(set(evidence_flags + ("fail_closed",)))), input_sha256=request_hash, output_sha256="", cost_breakdown=breakdown)
    return replace(base, output_sha256=output_sha256(base.to_dict(include_output_hash=False)))


def resolve_trade_method(request: MethodRequest, *, profiles: Mapping[tuple[TradeMethod, MethodSubtype], MethodProfile] = METHOD_PROFILES) -> MethodDecision:
    if not is_allowed(request.method, request.method_subtype):
        return _blocked_decision(request, reasons=(BlockReason.UNSUPPORTED_FAMILY_SUBTYPE,), profile=None, profile_hash="", total_cost_bps=0.0, net_edge_bps=0.0, evidence_flags=())
    profile = profiles.get((request.method, request.method_subtype))
    if profile is None:
        return _blocked_decision(request, reasons=(BlockReason.UNSUPPORTED_FAMILY_SUBTYPE,), profile=None, profile_hash="", total_cost_bps=0.0, net_edge_bps=0.0, evidence_flags=())
    manifest = manifest_index(profiles)
    entry = manifest.get((request.method, request.method_subtype))
    actual_hash = profile_sha256(profile)
    expected_hash = entry.profile_sha256 if entry else ""
    reasons, total_cost_bps, net_edge_bps, evidence = evaluate_policy(request, profile, expected_profile_sha256=expected_hash, actual_profile_sha256=actual_hash)
    if reasons:
        return _blocked_decision(request, reasons=reasons, profile=profile, profile_hash=actual_hash, total_cost_bps=total_cost_bps, net_edge_bps=net_edge_bps, evidence_flags=evidence)
    request_hash = input_sha256(request)
    trace = resolver_trace_id(request_hash=request_hash, profile_hash=actual_hash, decision_code="allow")
    breakdown = compute_all_in_cost(request.costs)
    base = MethodDecision(method=profile.method, method_subtype=profile.method_subtype, profile_version=profile.profile_version, profile_sha256=actual_hash, entry_style=profile.entry_style, hold_horizon=profile.hold_horizon, risk_mode=profile.risk_mode, target_r=profile.target_r, stop_r=profile.stop_r, time_stop_seconds=profile.time_stop_seconds, size_multiplier=profile.size_multiplier, execution_overlays=profile.execution_overlays, resolver_trace_id=trace, block_reason=BlockReason.NONE, block_reasons=(), expected_all_in_cost_bps=total_cost_bps, net_edge_after_cost_bps=net_edge_bps, decision=ResolutionDecision.ALLOW, evidence_flags=evidence, input_sha256=request_hash, output_sha256="", cost_breakdown=breakdown)
    return replace(base, output_sha256=output_sha256(base.to_dict(include_output_hash=False)))
