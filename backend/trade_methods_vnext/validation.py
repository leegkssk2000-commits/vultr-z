from __future__ import annotations

from dataclasses import replace
from typing import Mapping

from .lineage import profile_sha256
from .manifest import ALLOWED_COMBINATIONS, build_manifest, is_allowed
from .profiles import METHOD_PROFILES
from .resolver import resolve_trade_method
from .types import BlockReason, MethodDecision, MethodProfile, MethodRequest, MethodSubtype, ResolutionDecision, TradeMethod


def validate_profile_registry(profiles: Mapping[tuple[TradeMethod, MethodSubtype], MethodProfile] = METHOD_PROFILES) -> list[str]:
    errors: list[str] = []
    expected = {(method, subtype) for method, subtypes in ALLOWED_COMBINATIONS.items() for subtype in subtypes}
    actual = set(profiles)
    if actual != expected:
        errors.append(f"PROFILE_COMBINATION_MISMATCH:{sorted(actual)!r}!={sorted(expected)!r}")
    manifest = build_manifest(profiles)
    if len(manifest) != len(profiles):
        errors.append("MANIFEST_LENGTH_MISMATCH")
    hashes = [entry.profile_sha256 for entry in manifest]
    if len(hashes) != len(set(hashes)):
        errors.append("DUPLICATE_PROFILE_HASH")
    for key, profile in profiles.items():
        if key != (profile.method, profile.method_subtype):
            errors.append(f"PROFILE_KEY_MISMATCH:{key}")
        if not is_allowed(profile.method, profile.method_subtype):
            errors.append(f"UNSUPPORTED_PROFILE_COMBINATION:{key}")
        if profile_sha256(profile) == "":
            errors.append(f"EMPTY_PROFILE_HASH:{key}")
        if profile.target_r <= 0 or profile.stop_r >= 0:
            errors.append(f"INVALID_R_CONTRACT:{key}")
        if profile.time_stop_seconds <= 0:
            errors.append(f"INVALID_TIME_STOP:{key}")
        if not 0 <= profile.size_multiplier <= 1:
            errors.append(f"INVALID_SIZE_MULTIPLIER:{key}")
        if profile.min_realized_vol_bps > profile.max_realized_vol_bps:
            errors.append(f"INVALID_VOL_RANGE:{key}")
        if profile.min_atr_bps > profile.max_atr_bps:
            errors.append(f"INVALID_ATR_RANGE:{key}")
        if not profile.allowed_regimes:
            errors.append(f"EMPTY_REGIME_SET:{key}")
    return errors


def replay_determinism(request: MethodRequest, *, runs: int = 100) -> MethodDecision:
    if runs < 2:
        raise ValueError("runs must be >= 2")
    first = resolve_trade_method(request)
    expected = first.to_dict()
    for _ in range(runs - 1):
        current = resolve_trade_method(request)
        if current.to_dict() != expected:
            raise AssertionError(BlockReason.RESOLVER_NONDETERMINISM.value)
    return first


def cost_monotonicity_pair(request: MethodRequest, *, increment_bps: float) -> tuple[MethodDecision, MethodDecision]:
    if increment_bps <= 0:
        raise ValueError("increment_bps must be positive")
    baseline = resolve_trade_method(request)
    higher = replace(request, costs=replace(request.costs, slippage_bps=request.costs.slippage_bps + increment_bps))
    stressed = resolve_trade_method(higher)
    if stressed.net_edge_after_cost_bps > baseline.net_edge_after_cost_bps:
        raise AssertionError("COST_MONOTONICITY_VIOLATION")
    if baseline.decision == ResolutionDecision.BLOCK and stressed.decision == ResolutionDecision.ALLOW:
        raise AssertionError("COST_BLOCK_MONOTONICITY_VIOLATION")
    return baseline, stressed


def liquidity_monotonicity_pair(request: MethodRequest, *, lower_depth_factor: float) -> tuple[MethodDecision, MethodDecision]:
    if not 0 < lower_depth_factor < 1:
        raise ValueError("lower_depth_factor must be in (0,1)")
    baseline = resolve_trade_method(request)
    lower = replace(request, market=replace(request.market, available_depth_usdt=request.market.available_depth_usdt * lower_depth_factor))
    stressed = resolve_trade_method(lower)
    if baseline.decision == ResolutionDecision.BLOCK and stressed.decision == ResolutionDecision.ALLOW:
        raise AssertionError("LIQUIDITY_BLOCK_MONOTONICITY_VIOLATION")
    return baseline, stressed


def risk_monotonicity_pair(request: MethodRequest, *, leverage_increment: float) -> tuple[MethodDecision, MethodDecision]:
    if leverage_increment <= 0:
        raise ValueError("leverage_increment must be positive")
    baseline = resolve_trade_method(request)
    higher = replace(request, risk=replace(request.risk, leverage=request.risk.leverage + leverage_increment))
    stressed = resolve_trade_method(higher)
    if baseline.decision == ResolutionDecision.BLOCK and stressed.decision == ResolutionDecision.ALLOW:
        raise AssertionError("RISK_BLOCK_MONOTONICITY_VIOLATION")
    return baseline, stressed
