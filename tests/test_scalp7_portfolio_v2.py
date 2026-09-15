"""Synthetic clock/capacity tests; no historical economic evidence."""

from __future__ import annotations

from typing import Any

import pytest

from backend.research.rebuild.scalp7_portfolio_v2 import route

PRIMARY = {f"lane{i}": f"identity{i}" for i in range(7)}


def trade(
    lane: int,
    signal_ts: int,
    available: int,
    net: float = 100.0,
    *,
    symbol: str = "BTC-USDT",
) -> dict[str, Any]:
    signal = {
        "identity": PRIMARY[f"lane{lane}"],
        "lane": f"lane{lane}",
        "symbol": symbol,
        "signal_ts_ms": signal_ts,
        "side": 1,
        "timeframe_min": 30,
    }
    return {
        "identity": signal["identity"],
        "signal": signal,
        "signal_ts_ms": signal_ts,
        "entry_ts_ms": signal_ts,
        "exit_ts_ms": available,
        "outcome_available_ts_ms": available,
        "gross_bps": net + 14.0,
        "cost_bps": 14.0,
        "net_bps": net,
    }


def allocations(result: dict[str, Any]) -> list[dict[str, Any]]:
    return [event for event in result["events"] if event["event"] == "ALLOCATE"]


def test_empty_means_cash_without_forced_replacement() -> None:
    result = route([], PRIMARY, 0, 1000)
    assert result["metrics"]["T"] == 0
    assert result["peak_gross_weight"] == 0
    assert result["events"] == []


def test_equal_seven_baseline_never_fills_absent_sleeves() -> None:
    result = route([trade(0, 10, 20)], PRIMARY, 0, 1000, mode="equal7")
    assert allocations(result)[0]["weight"] == pytest.approx(1 / 7)
    assert result["allocated_rows"][0]["gross_bps"] == pytest.approx(114 / 7)
    assert result["allocated_rows"][0]["cost_bps"] == pytest.approx(14 / 7)
    assert result["metrics"]["net_bps"] == pytest.approx(100 / 7)


def test_cold_start_is_half_sleeve_and_keeps_rest_cash() -> None:
    result = route([trade(0, 10, 20)], PRIMARY, 0, 1000)
    assert allocations(result)[0]["weight"] == pytest.approx(1 / 14)
    assert allocations(result)[0]["health"]["completed_shadow_T"] == 0
    cohort = [
        event for event in result["events"] if event["event"] == "COHORT_CAPACITY"
    ][0]
    assert cohort["cash_weight"] == pytest.approx(13 / 14)


def test_same_timestamp_outcome_cannot_unlock_health() -> None:
    result = route([trade(0, 10, 100), trade(0, 100, 200)], PRIMARY, 0, 1000)
    assert [event["weight"] for event in allocations(result)] == pytest.approx(
        [1 / 14, 1 / 14]
    )
    later = route([trade(0, 10, 100), trade(0, 101, 200)], PRIMARY, 0, 1000)
    assert allocations(later)[1]["weight"] == pytest.approx(1.0)
    assert allocations(later)[1]["health"]["completed_shadow_T"] == 1


def test_future_pnl_cannot_change_current_allocation() -> None:
    first = [trade(0, 10, 100), trade(1, 50, 200)]
    second = [trade(0, 10, 100, net=-5000), trade(1, 50, 200)]
    left = allocations(route(first, PRIMARY, 0, 1000))
    right = allocations(route(second, PRIMARY, 0, 1000))
    assert left == right


def test_nonpositive_past_shadow_health_blocks_new_risk() -> None:
    result = route([trade(0, 10, 20, net=-100), trade(0, 30, 40)], PRIMARY, 0, 1000)
    assert len(allocations(result)) == 1
    assert result["no_allocation_count"] == 1
    no = next(event for event in result["events"] if event["event"] == "NO_ALLOCATION")
    assert no["health"]["state"] == "BLOCK_NONPOSITIVE_COMPLETED_SHADOW"


def test_transfer_requires_a_current_signal_in_positive_lane() -> None:
    absent = route([trade(0, 10, 20), trade(1, 30, 40)], PRIMARY, 0, 1000)
    assert allocations(absent)[1]["weight"] == pytest.approx(1 / 14)
    present = route(
        [trade(0, 10, 20), trade(0, 30, 40), trade(1, 30, 40)], PRIMARY, 0, 1000
    )
    cohort = {
        event["lane"]: event["weight"]
        for event in allocations(present)
        if event["decision_ts_ms"] == 30
    }
    assert cohort == pytest.approx({"lane0": 13 / 14, "lane1": 1 / 14})
    assert present["peak_gross_weight"] == pytest.approx(1.0)


def test_multiple_valid_symbols_share_one_lane_budget() -> None:
    result = route(
        [trade(0, 10, 20), trade(0, 10, 20, symbol="ETH-USDT")], PRIMARY, 0, 1000
    )
    assert [event["weight"] for event in allocations(result)] == pytest.approx(
        [1 / 28, 1 / 28]
    )


def test_unresolved_position_holds_capacity_without_future_status_block() -> None:
    source = trade(0, 30, 40)
    unresolved = {
        "identity": source["identity"],
        "entry_ts_ms": 30,
        "state": "UNRESOLVED_PAIR_GAP_OR_END",
        "position": {"signal": source["signal"], "entry_ts_ms": 30},
    }
    result = route([trade(0, 10, 20), unresolved, trade(1, 50, 60)], PRIMARY, 0, 1000)
    assert allocations(result)[1]["weight"] == pytest.approx(1.0)
    assert result["open_allocation_count"] == 1
    assert result["end_reserved_weight"] == pytest.approx(1.0)
    assert result["no_allocation_count"] == 1
    assert result["open_allocations"][0]["realized_pnl"] is None


def test_gap_blocks_only_from_explicit_observed_timestamp() -> None:
    data = [trade(0, 10, 20), trade(0, 30, 40)]
    result = route(
        data,
        PRIMARY,
        0,
        1000,
        source_gap_events=[{"identity": PRIMARY["lane0"], "observed_ts_ms": 25}],
    )
    assert len(allocations(result)) == 1
    assert (
        next(event for event in result["events"] if event["event"] == "NO_ALLOCATION")[
            "health"
        ]["state"]
        == "BLOCK_SOURCE"
    )


def test_equal_time_realized_outcomes_are_one_dd_batch() -> None:
    result = route(
        [trade(0, 10, 20, net=100), trade(1, 10, 20, net=-100)], PRIMARY, 0, 1000
    )
    assert result["metrics"]["net_bps"] == pytest.approx(0.0)
    assert result["metrics"]["DD_bps"] == pytest.approx(0.0)
    assert result["metrics"]["max_loss_batch_streak"] == 0


def test_window_reset_excludes_carryin_and_preserves_carryout() -> None:
    result = route([trade(0, 10, 110), trade(1, 110, 210)], PRIMARY, 100, 200)
    assert result["outside_window_or_carryin_count"] == 1
    assert allocations(result)[0]["health"]["completed_shadow_T"] == 0
    assert result["metrics"]["T"] == 0
    assert result["open_allocation_count"] == 1


def test_duplicate_identity_or_bad_cost_identity_fails() -> None:
    with pytest.raises(ValueError, match="DUPLICATE"):
        route([trade(0, 10, 20), trade(0, 10, 20)], PRIMARY, 0, 1000)
    bad = trade(0, 10, 20)
    bad["net_bps"] = 1000.0
    with pytest.raises(ValueError, match="INCONSISTENT"):
        route([bad], PRIMARY, 0, 1000)
    with pytest.raises(ValueError, match="SEVEN"):
        route([], {"lane0": "id"}, 0, 1000)


def test_raw_identity_cannot_override_different_signal_identity() -> None:
    item = trade(0, 10, 20)
    item["identity"] = PRIMARY["lane1"]
    with pytest.raises(ValueError, match="IDENTITY_MISMATCH"):
        route([item], PRIMARY, 0, 1000)


def test_legacy_timeframe_cannot_enter_portfolio() -> None:
    item = trade(0, 10, 20)
    item["signal"]["timeframe_min"] = 60
    with pytest.raises(ValueError, match="TIMEFRAME"):
        route([item], PRIMARY, 0, 1000)
