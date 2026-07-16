from __future__ import annotations

import importlib.util
import json
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).parents[1]
MODULE_PATH = ROOT / "canonical/lico.py"
spec = importlib.util.spec_from_file_location("canonical_lico_r43_test", MODULE_PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def consensus_ready():
    policy = module.SourceConsensusPolicy(
        required_source_prefixes=("cf:", "sheets:"),
        required_metrics=("mark_price",),
        max_age_ms=1000,
        numeric_tolerance_by_metric={"mark_price": Decimal("0")},
        minimum_source_confidence=Decimal("0.8"),
        policy_refs=("cf:lico_policy", "sheets:lico_policy"),
        schema_version="r43-test",
    )
    observations = (
        module.SourceObservation("cf:market", "mark_price", Decimal("100"), 9900, "ready", Decimal("0.9"), "cf:market:mark"),
        module.SourceObservation("sheets:market", "mark_price", Decimal("100"), 9900, "ready", Decimal("0.9"), "sheets:market:mark"),
    )
    return module.evaluate_source_consensus(observations, now_ms=10000, policy=policy)


def venue_policy(**changes):
    values = {
        "venue": "BingX",
        "max_stream_age_ms": 1000,
        "max_sequence_gap": 5,
        "minimum_book_levels": 2,
        "max_mark_index_deviation_bps": Decimal("20"),
        "allowed_venue_statuses": ("normal", "degraded"),
        "policy_refs": ("cf:lico_venue_policy", "sheets:lico_venue_policy"),
        "schema_version": "r43-test",
    }
    values.update(changes)
    return module.VenueHealthPolicy(**values)


def snapshot(**changes):
    values = {
        "venue": "BingX",
        "symbol": "BTC-USDT",
        "observed_at_ms": 9950,
        "sequence": 101,
        "best_bid": Decimal("99.9"),
        "best_ask": Decimal("100.1"),
        "mark_price": Decimal("100"),
        "index_price": Decimal("100"),
        "funding_rate": Decimal("0.0001"),
        "order_book": ((Decimal("99.9"), Decimal("2")), (Decimal("100.1"), Decimal("3"))),
        "trade_stream": True,
        "venue_status": "normal",
        "source_ref": "cf:bingx_public:BTCUSDT",
    }
    values.update(changes)
    return module.MarketStreamSnapshot(**values)


def assert_hold(result, reason: str) -> None:
    assert result.state == "HOLD"
    assert result.action == "hold"
    assert result.fail_closed is True
    assert result.abstain is True
    assert result.execution_authority == "none"
    assert reason in result.reason_codes


def test_market_stream_venue_health_ready() -> None:
    previous = snapshot(sequence=100, observed_at_ms=9900)
    result = module.evaluate_market_stream(
        snapshot(),
        previous=previous,
        consensus=consensus_ready(),
        now_ms=10000,
        policy=venue_policy(),
    )
    assert result.state == "READY"
    assert result.action == "hold"
    assert result.market_stream_ready is True
    assert result.venue_health == "healthy"
    assert result.symbol == "BTCUSDT"
    assert result.sequence_gap == 1
    assert result.book_level_count == 2
    assert result.abstain is False


def test_source_consensus_is_mandatory() -> None:
    bad_consensus = module._hold(("SOURCE_DISAGREEMENT",), schema_version="r43-test")
    result = module.evaluate_market_stream(
        snapshot(), previous=None, consensus=bad_consensus, now_ms=10000, policy=venue_policy()
    )
    assert_hold(result, "SOURCE_CONSENSUS_NOT_READY")


def test_stale_stream_holds() -> None:
    result = module.evaluate_market_stream(
        snapshot(observed_at_ms=1), previous=None, consensus=consensus_ready(), now_ms=10000, policy=venue_policy()
    )
    assert_hold(result, "MARKET_STREAM_STALE")


def test_non_monotonic_sequence_holds() -> None:
    result = module.evaluate_market_stream(
        snapshot(sequence=100),
        previous=snapshot(sequence=100, observed_at_ms=9900),
        consensus=consensus_ready(),
        now_ms=10000,
        policy=venue_policy(),
    )
    assert_hold(result, "MARKET_SEQUENCE_NON_MONOTONIC")


def test_large_sequence_gap_holds() -> None:
    result = module.evaluate_market_stream(
        snapshot(sequence=110),
        previous=snapshot(sequence=100, observed_at_ms=9900),
        consensus=consensus_ready(),
        now_ms=10000,
        policy=venue_policy(),
    )
    assert_hold(result, "MARKET_SEQUENCE_GAP")


def test_crossed_book_holds() -> None:
    result = module.evaluate_market_stream(
        snapshot(best_bid=Decimal("101"), best_ask=Decimal("100")),
        previous=None,
        consensus=consensus_ready(),
        now_ms=10000,
        policy=venue_policy(),
    )
    assert_hold(result, "MARKET_BOOK_CROSSED")


def test_dead_trade_stream_holds() -> None:
    result = module.evaluate_market_stream(
        snapshot(trade_stream=False), previous=None, consensus=consensus_ready(), now_ms=10000, policy=venue_policy()
    )
    assert_hold(result, "MARKET_TRADE_STREAM_DOWN")


def test_blocked_venue_status_holds() -> None:
    result = module.evaluate_market_stream(
        snapshot(venue_status="maintenance"), previous=None, consensus=consensus_ready(), now_ms=10000, policy=venue_policy()
    )
    assert_hold(result, "VENUE_STATUS_BLOCKED")


def test_mark_index_deviation_holds() -> None:
    result = module.evaluate_market_stream(
        snapshot(mark_price=Decimal("101"), index_price=Decimal("100")),
        previous=None,
        consensus=consensus_ready(),
        now_ms=10000,
        policy=venue_policy(max_mark_index_deviation_bps=Decimal("20")),
    )
    assert_hold(result, "MARK_INDEX_DEVIATION_EXCEEDED")


def test_public_cf_source_is_required() -> None:
    result = module.evaluate_market_stream(
        snapshot(source_ref="sheets:market:BTCUSDT"),
        previous=None,
        consensus=consensus_ready(),
        now_ms=10000,
        policy=venue_policy(),
    )
    assert_hold(result, "MARKET_SOURCE_REF_INVALID")


def test_contract_keeps_authority_and_ssot_boundaries() -> None:
    contract = json.loads((ROOT / "config/q4r3_lico_market_stream_venue_health_contract_v1.json").read_text(encoding="utf-8"))
    assert contract["canonical_owner"] == "canonical/lico.py"
    assert contract["venue"] == "BingX"
    assert contract["authority"]["execution_authority"] == "none"
    assert contract["authority"]["runtime_enabled"] is False
    assert contract["authority"]["order_enabled"] is False
    assert contract["market_policy"]["max_stream_age_ms"] == "SSOT.DATA_STALE_MS"
    assert contract["market_policy"]["max_sequence_gap"] == "SSOT.LICO.MAX_MARKET_SEQUENCE_GAP"
