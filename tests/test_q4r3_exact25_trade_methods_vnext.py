from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path

import pytest

from backend.trade_methods_vnext import BlockReason, CostInputs, EntryStyle, HoldHorizon, MarketContext, MethodRequest, MethodSubtype, ResolutionDecision, RiskInputs, RiskMode, TradeMethod, resolve_trade_method
from backend.trade_methods_vnext.manifest import ALLOWED_COMBINATIONS, build_manifest
from backend.trade_methods_vnext.profiles import METHOD_PROFILES
from backend.trade_methods_vnext.validation import cost_monotonicity_pair, liquidity_monotonicity_pair, replay_determinism, risk_monotonicity_pair, validate_profile_registry


def request_for(method: TradeMethod = TradeMethod.SCALP_FIRST, subtype: MethodSubtype = MethodSubtype.REVERT, *, gross_edge_bps: float = 30.0, spread_bps: float = 1.0, slippage_bps: float = 1.0, depth_usdt: float = 100_000.0, requested_notional_usdt: float = 5_000.0, realized_vol_bps: float = 30.0, atr_bps: float = 25.0, regime: str | None = None, leverage: float = 10.0, position_size_pct: float = 5.0, dd_day_pct: float = 1.0, dd_total_pct: float = 2.0, liq_buffer_pct: float = 40.0, signal_age_seconds: int = 10) -> MethodRequest:
    profile = METHOD_PROFILES.get((method, subtype))
    if profile is None:
        entry_style = EntryStyle.OBSERVE_THEN_CONFIRM
        hold_horizon = HoldHorizon.M10_45
        risk_mode = RiskMode.BALANCED
        selected_regime = regime or "trend"
    else:
        entry_style = profile.entry_style
        hold_horizon = profile.hold_horizon
        risk_mode = profile.risk_mode
        selected_regime = regime or profile.allowed_regimes[0]
    evaluation = 1_720_000_000_000
    return MethodRequest(strategy_id="alpha_combo", symbol="BTCUSDT", side="long", signal_ts_epoch_ms=evaluation - signal_age_seconds * 1000, evaluation_ts_epoch_ms=evaluation, reference_price=60_000.0, expected_gross_edge_bps=gross_edge_bps, method=method, method_subtype=subtype, entry_style=entry_style, hold_horizon=hold_horizon, risk_mode=risk_mode, costs=CostInputs(fee_bps_round_trip=2.0, spread_bps=spread_bps, slippage_bps=slippage_bps, funding_bps_horizon=0.5, market_impact_bps=0.5, latency_adverse_selection_bps=0.5), risk=RiskInputs(position_size_pct=position_size_pct, leverage=leverage, dd_day_pct=dd_day_pct, dd_total_pct=dd_total_pct, liq_buffer_pct=liq_buffer_pct), market=MarketContext(available_depth_usdt=depth_usdt, requested_notional_usdt=requested_notional_usdt, realized_vol_bps=realized_vol_bps, atr_bps=atr_bps, regime=selected_regime, session_bucket="eu_open"))


def test_registry_is_complete_and_valid() -> None:
    assert validate_profile_registry() == []
    expected = {(method, subtype) for method, subtypes in ALLOWED_COMBINATIONS.items() for subtype in subtypes}
    assert set(METHOD_PROFILES) == expected
    assert len(METHOD_PROFILES) == 6
    manifest = build_manifest(METHOD_PROFILES)
    assert len(manifest) == 6
    assert len({entry.profile_sha256 for entry in manifest}) == 6


@pytest.mark.parametrize("key", list(METHOD_PROFILES))
def test_each_allowed_profile_can_resolve_allow(key: tuple[TradeMethod, MethodSubtype]) -> None:
    method, subtype = key
    decision = resolve_trade_method(request_for(method, subtype, gross_edge_bps=50.0))
    assert decision.decision == ResolutionDecision.ALLOW
    assert decision.block_reason == BlockReason.NONE
    assert decision.profile_sha256
    assert decision.resolver_trace_id.startswith("tmvnext:")
    assert len(decision.input_sha256) == 64
    assert len(decision.output_sha256) == 64
    assert decision.expected_all_in_cost_bps > 0
    assert decision.net_edge_after_cost_bps > 0


def test_unsupported_combination_fails_closed() -> None:
    decision = resolve_trade_method(request_for(TradeMethod.TACTICAL_SWING, MethodSubtype.RESCUE))
    assert decision.decision == ResolutionDecision.BLOCK
    assert decision.block_reason == BlockReason.UNSUPPORTED_FAMILY_SUBTYPE
    assert decision.size_multiplier == 0.0
    assert "fail_closed" in decision.evidence_flags


def test_cost_gate_blocks_when_edge_is_consumed() -> None:
    decision = resolve_trade_method(request_for(gross_edge_bps=6.0))
    assert decision.decision == ResolutionDecision.BLOCK
    assert BlockReason.NET_EDGE_NOT_ABOVE_COST_MARGIN in decision.block_reasons


def test_negative_cost_input_blocks() -> None:
    request = request_for()
    request = replace(request, costs=replace(request.costs, slippage_bps=-1.0))
    decision = resolve_trade_method(request)
    assert decision.decision == ResolutionDecision.BLOCK
    assert BlockReason.INVALID_COST_INPUT in decision.block_reasons


def test_spread_gate_blocks() -> None:
    decision = resolve_trade_method(request_for(spread_bps=20.0, gross_edge_bps=100.0))
    assert BlockReason.SPREAD_TOO_WIDE in decision.block_reasons


def test_liquidity_gate_blocks() -> None:
    decision = resolve_trade_method(request_for(depth_usdt=5_000.0, requested_notional_usdt=5_000.0, gross_edge_bps=100.0))
    assert BlockReason.INSUFFICIENT_LIQUIDITY in decision.block_reasons


def test_volatility_gate_blocks() -> None:
    decision = resolve_trade_method(request_for(realized_vol_bps=1_000.0, gross_edge_bps=100.0))
    assert BlockReason.VOLATILITY_OUTSIDE_PROFILE in decision.block_reasons


def test_regime_gate_blocks() -> None:
    decision = resolve_trade_method(request_for(regime="unknown_regime", gross_edge_bps=100.0))
    assert BlockReason.REGIME_PROFILE_MISMATCH in decision.block_reasons


def test_signal_staleness_blocks() -> None:
    decision = resolve_trade_method(request_for(signal_age_seconds=10_000, gross_edge_bps=100.0))
    assert BlockReason.STALE_SIGNAL in decision.block_reasons


def test_risk_gates_block() -> None:
    decision = resolve_trade_method(request_for(leverage=50.0, position_size_pct=50.0, dd_day_pct=99.0, dd_total_pct=99.0, liq_buffer_pct=1.0, gross_edge_bps=100.0))
    assert BlockReason.LEVERAGE_LIMIT_EXCEEDED in decision.block_reasons
    assert BlockReason.POSITION_SIZE_LIMIT_EXCEEDED in decision.block_reasons
    assert BlockReason.DRAWDOWN_LIMIT_EXCEEDED in decision.block_reasons
    assert BlockReason.LIQUIDATION_BUFFER_TOO_SMALL in decision.block_reasons


def test_determinism_100_replays() -> None:
    decision = replay_determinism(request_for(gross_edge_bps=50.0), runs=100)
    assert decision.decision == ResolutionDecision.ALLOW


def test_cost_monotonicity() -> None:
    baseline, stressed = cost_monotonicity_pair(request_for(gross_edge_bps=50.0), increment_bps=40.0)
    assert stressed.net_edge_after_cost_bps < baseline.net_edge_after_cost_bps
    assert stressed.decision == ResolutionDecision.BLOCK


def test_liquidity_monotonicity() -> None:
    baseline, stressed = liquidity_monotonicity_pair(request_for(gross_edge_bps=50.0), lower_depth_factor=0.01)
    assert baseline.decision == ResolutionDecision.ALLOW
    assert stressed.decision == ResolutionDecision.BLOCK
    assert BlockReason.INSUFFICIENT_LIQUIDITY in stressed.block_reasons


def test_risk_monotonicity() -> None:
    baseline, stressed = risk_monotonicity_pair(request_for(gross_edge_bps=50.0), leverage_increment=100.0)
    assert baseline.decision == ResolutionDecision.ALLOW
    assert stressed.decision == ResolutionDecision.BLOCK
    assert BlockReason.LEVERAGE_LIMIT_EXCEEDED in stressed.block_reasons


def test_resolution_layer_has_no_network_random_or_wallclock_calls() -> None:
    package = Path(__file__).parents[1] / "backend" / "trade_methods_vnext"
    forbidden_imports = {"requests", "httpx", "aiohttp", "urllib", "websocket", "websockets", "random", "secrets", "time", "datetime", "os"}
    forbidden_calls = {"time", "time_ns", "now", "utcnow", "today", "getenv"}
    violations: list[str] = []
    for path in package.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] in forbidden_imports:
                        violations.append(f"{path.name}:import:{alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.split(".")[0] in forbidden_imports:
                    violations.append(f"{path.name}:from:{node.module}")
            elif isinstance(node, ast.Call):
                name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ""
                if name in forbidden_calls:
                    violations.append(f"{path.name}:call:{name}")
    assert violations == []
