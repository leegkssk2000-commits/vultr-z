"""Synthetic numeric boundaries; no market data, strategy changes or replay."""

import json
import math

import pytest

from backend.research.rebuild.scalp7_implementation_contract_v1 import (
    inspect_entry_bar,
    value_account_snapshots,
)


def entry(kind="NEXT_OPEN", *, opening=100, high=110, trigger=108):
    order = {
        "identity": "synthetic-numeric",
        "symbol": "BTC-USDT",
        "rule_digest": "synthetic-only",
        "timing_basis": "HISTORICAL_MODEL",
        "decision_tf_min": 15,
        "order_kind": kind,
        "side": 1,
        "qty_base": 1,
        "feature_available_ts_ms": 0,
        "order_submit_ts_ms": 0,
        "order_active_ts_ms": 0,
        "expires_ts_ms": 600000,
        "protective_stop": 95,
        "trigger_price": trigger,
    }
    bar = {
        "symbol": "BTC-USDT",
        "segment_id": "fixture",
        "open_ts_ms": 0,
        "close_ts_ms": 60000,
        "available_ts_ms": 60000,
        "open": opening,
        "high": high,
        "low": 99,
        "close": 100,
    }
    return inspect_entry_bar(order, bar)


def snapshot(**updates):
    return {
        "ts_ms": 1000,
        "realized_gross_cum_usdt": 0,
        "fees_cum_usdt": 0,
        "funding_received_cum_usdt": 0,
        "positions": [],
        "prices": {},
        **updates,
    }


def position_snapshot(qty, price, entry_price=1, **updates):
    return snapshot(
        positions=[
            {
                "position_episode_id": "fixture-1",
                "symbol": "BTC-USDT",
                "side": 1,
                "remaining_qty_base": qty,
                "avg_entry_price": entry_price,
            }
        ],
        prices={
            "BTC-USDT": {
                "ts_ms": 1000,
                "price": price,
                "price_basis": "MARK_PRICE",
                "source_ref": "synthetic-numeric-fixture",
            }
        },
        **updates,
    )


def value(rows, initial=10000):
    return value_account_snapshots(
        rows, initial_cash_usdt=initial, start_ts_ms=0, price_basis="MARK_PRICE"
    )


@pytest.mark.parametrize(
    "kind,opening,trigger",
    [
        ("NEXT_OPEN", "1e1000", 108),
        ("STOP_MARKET", "1e1000", 108),
        ("STOP_MARKET", 100, "1e1000"),
    ],
)
def test_entry_output_rejects_finite_decimal_that_overflows_float(
    kind, opening, trigger
):
    with pytest.raises(ValueError, match="NONFINITE_OUTPUT:candidate_price"):
        entry(kind, opening=opening, high="1e1000", trigger=trigger)


@pytest.mark.parametrize(
    "field,amount",
    [
        ("realized_gross_cum_usdt", "1e1000"),
        ("realized_gross_cum_usdt", "-1e1000"),
        ("fees_cum_usdt", "1e1000"),
        ("funding_received_cum_usdt", "1e1000"),
        ("funding_received_cum_usdt", "-1e1000"),
    ],
)
def test_cumulative_cash_output_rejects_float_overflow(field, amount):
    with pytest.raises(ValueError, match="NONFINITE_OUTPUT:cash_usdt"):
        value([snapshot(**{field: amount})])


@pytest.mark.parametrize("price,entry_price", [("1e200", 1), (1, "1e200")])
def test_quantity_price_product_rejected_even_when_each_input_fits_float(
    price, entry_price
):
    assert all(math.isfinite(float(x)) for x in ("1e200", price, entry_price))
    with pytest.raises(ValueError, match="NONFINITE_OUTPUT:unrealized_usdt"):
        value([position_snapshot("1e200", price, entry_price)])


def test_cash_sum_overflow_with_individually_finite_inputs():
    with pytest.raises(ValueError, match="NONFINITE_OUTPUT:cash_usdt"):
        value([snapshot(realized_gross_cum_usdt="1e308")], initial="1e308")


def test_equity_sum_overflow_with_finite_cash_and_unrealized():
    with pytest.raises(ValueError, match="NONFINITE_OUTPUT:equity_usdt"):
        value([position_snapshot("1e154", "1e154")], initial="1e308")


def test_peak_overflow_not_hidden_by_cash_offset():
    with pytest.raises(ValueError, match="NONFINITE_OUTPUT:peak_equity_usdt"):
        value([snapshot(realized_gross_cum_usdt="-1e1000")], initial="1e1000")


def test_drawdown_ratio_overflow_with_finite_cash_and_peak():
    with pytest.raises(ValueError, match="NONFINITE_OUTPUT:drawdown_pct"):
        value([snapshot(realized_gross_cum_usdt="-1e308")], initial="1e-308")


@pytest.mark.parametrize("amount", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite_input_never_becomes_json_number(amount):
    with pytest.raises(ValueError, match="INVALID_NUMBER"):
        value([snapshot(realized_gross_cum_usdt=amount)])


@pytest.mark.parametrize(
    "kind,opening,expected",
    [
        ("NEXT_OPEN", 100, 100),
        ("STOP_MARKET", 109, 109),
        ("STOP_MARKET", 100, 108),
    ],
)
def test_ordinary_entry_outputs_and_time_precision_are_unchanged(
    kind, opening, expected
):
    out = entry(kind, opening=opening)
    assert out["candidate_price"] == expected
    assert out["fill_ts_ms"] is None
    assert out["economic_credit"] is False
    assert out["witness_available_ts_ms"] == 60000
    assert out["event_interval_ms"] == ([0, 60000] if expected == 108 else [0, 0])
    json.dumps(out, allow_nan=False)


def test_ordinary_decimal_valuation_keeps_units_costs_and_peak():
    first = position_snapshot(
        50,
        105,
        100,
        realized_gross_cum_usdt=500,
        fees_cum_usdt=10,
        funding_received_cum_usdt=-5,
    )
    second = snapshot(
        ts_ms=2000,
        realized_gross_cum_usdt=0,
        fees_cum_usdt=20,
        funding_received_cum_usdt=-10,
    )
    out = value([first, second])
    assert out["curve"][0]["cash_usdt"] == 10485
    assert out["curve"][0]["unrealized_usdt"] == 250
    assert out["curve"][0]["equity_usdt"] == 10735
    assert out["curve"][1]["equity_usdt"] == 9970
    assert out["max_drawdown_pct"] == pytest.approx(765 / 10735 * 100)
    assert out["initial_cash_usdt"] == 10000
    json.dumps(out, allow_nan=False)
