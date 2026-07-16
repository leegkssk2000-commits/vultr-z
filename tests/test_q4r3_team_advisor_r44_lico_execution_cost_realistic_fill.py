from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

from canonical import lico
from canonical import lico_execution as model

ROOT = Path(__file__).parents[1]


def consensus_ready():
    policy = lico.SourceConsensusPolicy(
        required_source_prefixes=("cf:", "sheets:"),
        required_metrics=("mark_price",),
        max_age_ms=1000,
        numeric_tolerance_by_metric={"mark_price": Decimal("0")},
        minimum_source_confidence=Decimal("0.8"),
        policy_refs=("cf:r44", "sheets:r44"),
        schema_version="r44-test",
    )
    observations = (
        lico.SourceObservation("cf:market", "mark_price", Decimal("100"), 9900, "ready", Decimal("0.9"), "cf:market:mark"),
        lico.SourceObservation("sheets:market", "mark_price", Decimal("100"), 9900, "ready", Decimal("0.9"), "sheets:market:mark"),
    )
    return lico.evaluate_source_consensus(observations, now_ms=10000, policy=policy)


def market():
    return lico.MarketStreamSnapshot(
        venue="BingX",
        symbol="BTC-USDT",
        observed_at_ms=9950,
        sequence=100,
        best_bid=Decimal("99.9"),
        best_ask=Decimal("100.1"),
        mark_price=Decimal("100"),
        index_price=Decimal("100"),
        funding_rate=Decimal("0"),
        order_book=((Decimal("99.9"), Decimal("5")), (Decimal("100.1"), Decimal("5"))),
        trade_stream=True,
        venue_status="online",
        source_ref="cf:bingx:public",
    )


def venue_ready():
    policy = lico.VenueHealthPolicy(
        venue="BingX",
        max_stream_age_ms=1000,
        max_sequence_gap=5,
        minimum_book_levels=2,
        max_mark_index_deviation_bps=Decimal("10"),
        allowed_venue_statuses=("online",),
        policy_refs=("cf:r44", "sheets:r44"),
        schema_version="r44-test",
    )
    return lico.evaluate_market_stream(
        market(),
        previous=None,
        consensus=consensus_ready(),
        now_ms=10000,
        policy=policy,
    )


def book():
    return model.ExecutionBook(
        venue="BingX",
        symbol="BTC-USDT",
        observed_at_ms=9950,
        bids=(
            model.DepthLevel(Decimal("99.9"), Decimal("1")),
            model.DepthLevel(Decimal("99.8"), Decimal("2")),
        ),
        asks=(
            model.DepthLevel(Decimal("100.1"), Decimal("1")),
            model.DepthLevel(Decimal("100.2"), Decimal("2")),
        ),
        source_ref="cf:bingx:depth",
    )


def policy(**changes):
    values = {
        "max_book_age_ms": 1000,
        "max_walk_levels": 5,
        "max_slippage_bps": Decimal("20"),
        "max_market_impact_bps": Decimal("20"),
        "minimum_fill_ratio": Decimal("0.5"),
        "base_latency_ms": 10,
        "per_level_latency_ms": 5,
        "max_fill_latency_ms": 100,
        "policy_refs": ("cf:r44", "sheets:r44"),
        "schema_version": "r44-test",
    }
    values.update(changes)
    return model.ExecutionCostPolicy(**values)


def simulate(request, *, execution_book=None, venue=None, execution_policy=None):
    return model.simulate_execution(
        execution_book or book(),
        request,
        market=market(),
        venue_health=venue or venue_ready(),
        now_ms=10000,
        policy=execution_policy or policy(),
    )


def test_market_buy_walks_book_and_fills() -> None:
    result = simulate(model.ExecutionRequest("r1", "buy", "market", Decimal("2"), 9960))
    assert result.state == "READY"
    assert result.fill_status == "filled"
    assert result.filled_qty == Decimal("2")
    assert result.walked_level_count == 2
    assert result.order_book_walking is True
    assert result.average_fill_price == Decimal("100.15")
    assert result.execution_cost_ready is True
    assert result.realistic_fill_model is True
    assert result.execution_authority == "none"


def test_market_sell_partial_fill_is_preserved() -> None:
    result = simulate(model.ExecutionRequest("r2", "sell", "market", Decimal("5"), 9960))
    assert result.state == "READY"
    assert result.fill_status == "partial_fill"
    assert result.filled_qty == Decimal("3")
    assert result.unfilled_qty == Decimal("2")
    assert result.partial_fill is True
    assert result.action == "hold"


def test_passive_limit_queue_can_no_fill() -> None:
    request = model.ExecutionRequest(
        "r3", "buy", "limit", Decimal("2"), 9960,
        limit_price=Decimal("99.9"),
        queue_ahead_qty=Decimal("2"),
        observed_trade_qty=Decimal("1"),
    )
    result = simulate(request)
    assert result.state == "READY"
    assert result.fill_status == "no_fill"
    assert result.no_fill is True
    assert result.queue_model is True
    assert result.accepted is False
    assert "NO_FILL" in result.reason_codes


def test_passive_limit_queue_can_partial_fill() -> None:
    request = model.ExecutionRequest(
        "r4", "buy", "limit", Decimal("2"), 9960,
        limit_price=Decimal("99.9"),
        queue_ahead_qty=Decimal("2"),
        observed_trade_qty=Decimal("3"),
    )
    result = simulate(request)
    assert result.fill_status == "partial_fill"
    assert result.filled_qty == Decimal("1")
    assert result.queue_model is True
    assert result.first_fill_price == Decimal("99.9")


def test_excess_cost_routes_change_without_order_authority() -> None:
    result = simulate(
        model.ExecutionRequest("r5", "buy", "market", Decimal("2"), 9960),
        execution_policy=policy(max_slippage_bps=Decimal("1"), max_market_impact_bps=Decimal("1")),
    )
    assert result.state == "READY"
    assert result.action == "route_change"
    assert result.accepted is False
    assert "SLIPPAGE_LIMIT_EXCEEDED" in result.reason_codes
    assert result.order_enabled is False


def test_unhealthy_venue_fails_closed() -> None:
    unhealthy = replace(venue_ready(), state="HOLD", market_stream_ready=False, venue_health="unhealthy")
    result = simulate(model.ExecutionRequest("r6", "buy", "market", Decimal("1"), 9960), venue=unhealthy)
    assert result.state == "HOLD"
    assert result.abstain is True
    assert result.fail_closed is True
    assert "VENUE_HEALTH_NOT_READY" in result.reason_codes


def test_stale_execution_book_fails_closed() -> None:
    stale = replace(book(), observed_at_ms=1)
    result = simulate(model.ExecutionRequest("r7", "buy", "market", Decimal("1"), 9960), execution_book=stale)
    assert result.state == "HOLD"
    assert "EXECUTION_BOOK_STALE" in result.reason_codes


def test_crossed_execution_book_fails_closed() -> None:
    crossed = replace(
        book(),
        bids=(model.DepthLevel(Decimal("100.2"), Decimal("1")),),
        asks=(model.DepthLevel(Decimal("100.1"), Decimal("1")),),
    )
    result = simulate(model.ExecutionRequest("r8", "buy", "market", Decimal("1"), 9960), execution_book=crossed)
    assert result.state == "HOLD"
    assert "EXECUTION_BOOK_CROSSED" in result.reason_codes


def test_contract_is_ssot_bound_and_fee_stage_is_not_implemented() -> None:
    contract = json.loads((ROOT / "config/q4r3_lico_execution_cost_realistic_fill_contract_v1.json").read_text(encoding="utf-8"))
    execution = contract["execution_policy"]
    assert execution["max_slippage_bps"] == "SSOT.LICO.MAX_SLIPPAGE_BPS"
    assert execution["max_market_impact_bps"] == "SSOT.LICO.MAX_MARKET_IMPACT_BPS"
    assert execution["minimum_fill_ratio"] == "SSOT.LICO.MIN_FILL_RATIO"
    assert contract["authority"]["execution_authority"] == "none"
    assert "fee_model" in contract["forbidden"]
    assert contract["next_stage"] == "R4.5"
