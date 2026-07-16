from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

from canonical.lico_execution import ExecutionFillEnvelope
from canonical.lico_risk import (
    ALLOWED_LIQUIDITY,
    MODEL_OWNER,
    REQUIRED_STRESS_SCENARIOS,
    LicoRiskEnvelope,
    PositionRiskSnapshot,
    RiskCostPolicy,
    StressScenario,
    evaluate_fee_funding_liquidation_stress,
)

ROOT = Path(__file__).parents[1]
D = Decimal


def valid_fill(**changes) -> ExecutionFillEnvelope:
    values = {
        "state": "READY",
        "action": "hold",
        "reason_codes": ("FULL_FILL",),
        "request_id": "req-r45",
        "symbol": "BTCUSDT",
        "side": "buy",
        "order_type": "market",
        "fill_status": "filled",
        "requested_qty": D("1"),
        "filled_qty": D("1"),
        "unfilled_qty": D("0"),
        "fill_ratio": D("1"),
        "average_fill_price": D("100"),
        "first_fill_price": D("100"),
        "last_fill_price": D("100.01"),
        "reference_mid_price": D("99.99"),
        "spread_bps": D("2"),
        "slippage_bps": D("0.5"),
        "market_impact_bps": D("1"),
        "execution_cost_bps": D("1"),
        "walked_level_count": 2,
        "queue_ahead_qty": D("0"),
        "first_fill_ts": 9001,
        "final_fill_ts": 9002,
        "fill_latency_ms": 2,
        "no_fill": False,
        "partial_fill": False,
        "order_book_walking": True,
        "queue_model": False,
        "execution_cost_ready": True,
        "realistic_fill_model": True,
        "accepted": True,
        "fail_closed": True,
        "abstain": False,
        "observer_only": True,
        "execution_authority": "none",
        "runtime_enabled": False,
        "order_enabled": False,
        "source_ref": "cf:bingx:depth",
        "schema_version": "r45-test",
    }
    values.update(changes)
    return ExecutionFillEnvelope(**values)


def valid_snapshot(**changes) -> PositionRiskSnapshot:
    values = {
        "position_id": "paper.r45.001",
        "venue": "BingX",
        "symbol": "BTCUSDT",
        "side": "long",
        "quantity": D("1"),
        "entry_price": D("100"),
        "mark_price": D("102"),
        "liquidation_price": D("80"),
        "leverage": D("10"),
        "margin_balance": D("20"),
        "maintenance_margin": D("2"),
        "opened_at_ms": 8000,
        "observed_at_ms": 9900,
        "funding_rate_8h": D("0.0001"),
        "funding_intervals": 1,
        "entry_liquidity": "maker",
        "exit_liquidity": "taker",
        "source_ref": "cf:paper:position",
    }
    values.update(changes)
    return PositionRiskSnapshot(**values)


def valid_policy(**changes) -> RiskCostPolicy:
    values = {
        "maker_fee_rate": D("0.0002"),
        "taker_fee_rate": D("0.0005"),
        "max_abs_funding_rate_8h": D("0.001"),
        "minimum_liq_buffer_pct": D("10"),
        "minimum_margin_buffer_pct": D("20"),
        "max_total_cost_bps": D("20"),
        "max_stress_cost_bps": D("30"),
        "max_snapshot_age_ms": 1000,
        "max_funding_intervals": 8,
        "required_stress_scenarios": tuple(sorted(REQUIRED_STRESS_SCENARIOS)),
        "policy_refs": ("cf:lico:risk_policy", "sheets:lico:risk_policy"),
        "schema_version": "r45-test",
    }
    values.update(changes)
    return RiskCostPolicy(**values)


def valid_scenarios(*, volatility_move: str = "5") -> tuple[StressScenario, ...]:
    return (
        StressScenario("capital_stress", D("1"), D("1"), D("0"), D("1"), D("10")),
        StressScenario("liquidity_stress", D("1"), D("1.5"), D("1"), D("1"), D("0")),
        StressScenario("execution_degradation", D("1"), D("2"), D("2"), D("1"), D("0")),
        StressScenario("volatility_shock", D(volatility_move), D("1"), D("0"), D("2"), D("0")),
    )


def evaluate(snapshot=None, fill=None, scenarios=None, policy=None, now_ms=10000) -> LicoRiskEnvelope:
    return evaluate_fee_funding_liquidation_stress(
        snapshot or valid_snapshot(),
        fill or valid_fill(),
        scenarios=scenarios or valid_scenarios(),
        now_ms=now_ms,
        policy=policy or valid_policy(),
    )


def assert_hold(result: LicoRiskEnvelope, reason: str) -> None:
    assert result.state == "HOLD"
    assert result.action == "hold"
    assert result.fail_closed is True
    assert result.abstain is True
    assert result.execution_authority == "none"
    assert reason in result.reason_codes


def test_authority_and_identity_are_locked() -> None:
    assert MODEL_OWNER == "canonical/lico.py"
    assert ALLOWED_LIQUIDITY == frozenset({"maker", "taker"})
    result = evaluate()
    assert result.observer_only is True
    assert result.execution_authority == "none"
    assert result.runtime_enabled is False
    assert result.order_enabled is False


def test_fee_funding_liquidation_and_stress_are_ready() -> None:
    result = evaluate()
    assert result.state == "READY"
    assert result.action == "hold"
    assert result.accepted is True
    assert result.fee_funding_liquidation_model is True
    assert result.stress_scenarios is True
    assert result.stress_scenario_count == 4
    assert result.entry_fee > 0
    assert result.exit_fee > 0
    assert result.funding_cost > 0
    assert result.total_cost_bps > 0
    assert result.liq_buffer_pct > D("10")
    assert result.margin_buffer_pct > D("20")
    assert result.liquidation_breached is False


def test_excessive_funding_routes_change() -> None:
    result = evaluate(snapshot=valid_snapshot(funding_rate_8h=D("0.01")))
    assert result.state == "READY"
    assert result.action == "route_change"
    assert result.accepted is False
    assert "FUNDING_RATE_LIMIT_EXCEEDED" in result.reason_codes


def test_low_current_liquidation_buffer_routes_change() -> None:
    result = evaluate(snapshot=valid_snapshot(liquidation_price=D("95")))
    assert result.state == "READY"
    assert result.action == "route_change"
    assert "LIQ_BUFFER_BELOW_POLICY" in result.reason_codes


def test_volatility_stress_liquidation_routes_change() -> None:
    result = evaluate(
        snapshot=valid_snapshot(liquidation_price=D("95")),
        scenarios=valid_scenarios(volatility_move="10"),
    )
    assert result.state == "READY"
    assert result.action == "route_change"
    assert result.liquidation_breached is True
    assert "LIQUIDATION_STRESS_BREACH" in result.reason_codes


def test_stale_position_fails_closed() -> None:
    result = evaluate(snapshot=valid_snapshot(observed_at_ms=8000))
    assert_hold(result, "POSITION_SNAPSHOT_STALE")


def test_observation_before_open_fails_as_invalid_timestamp() -> None:
    result = evaluate(snapshot=valid_snapshot(observed_at_ms=7999))
    assert_hold(result, "POSITION_TIMESTAMP_INVALID")
    assert "POSITION_SNAPSHOT_STALE" not in result.reason_codes


def test_invalid_position_side_fails_closed() -> None:
    result = evaluate(snapshot=valid_snapshot(side="flat"))
    assert_hold(result, "POSITION_SIDE_INVALID")


def test_unready_execution_fill_fails_closed() -> None:
    result = evaluate(fill=valid_fill(state="HOLD", execution_cost_ready=False, realistic_fill_model=False))
    assert_hold(result, "EXECUTION_FILL_NOT_READY")


def test_missing_stress_scenario_fails_closed() -> None:
    result = evaluate(scenarios=valid_scenarios()[:-1])
    assert_hold(result, "STRESS_SCENARIO_SET_INCOMPLETE")


def test_contract_uses_ssot_and_preserves_scope() -> None:
    contract = json.loads(
        (ROOT / "config/q4r3_lico_fee_funding_liquidation_stress_contract_v1.json").read_text(encoding="utf-8")
    )
    policy = contract["fee_funding_liquidation_policy"]
    assert policy["maker_fee_rate"] == "SSOT.LICO.BINGX_MAKER_FEE_RATE"
    assert policy["taker_fee_rate"] == "SSOT.LICO.BINGX_TAKER_FEE_RATE"
    assert policy["minimum_liq_buffer_pct"] == "SSOT.LICO.MIN_LIQ_BUFFER_PCT"
    assert policy["max_snapshot_age_ms"] == "SSOT.DATA_STALE_MS"
    assert set(contract["stress_policy"]["required_scenarios"]) == REQUIRED_STRESS_SCENARIOS
    assert contract["authority"]["execution_authority"] == "none"
    assert contract["authority"]["runtime_enabled"] is False
    assert contract["next_stage"] == "R4.6"
