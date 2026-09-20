"""Synthetic contract tests; none of these are market/economic observations."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from backend.research.rebuild.scalp7_implementation_contract_v1 import (
    inspect_entry_bar,
    validate_rules,
    value_account_snapshots,
)


def rule(**overrides):
    return {
        "rule_id": "trigger",
        "origin": "SOURCE_DIRECT",
        "expression": "price > level",
        "unit": "quote/base",
        "version": "source_v1",
        "source_id": "fixture-source",
        "source_locator": "synthetic-test-not-original-data",
        "source_mode": "test",
        **overrides,
    }


def order(**overrides):
    return {
        "identity": "synthetic-1",
        "symbol": "BTC-USDT",
        "rule_digest": "test-only",
        "timing_basis": "HISTORICAL_MODEL",
        "decision_tf_min": 15,
        "order_kind": "STOP_MARKET",
        "side": 1,
        "qty_base": 1,
        "feature_available_ts_ms": 900000,
        "order_submit_ts_ms": 900000,
        "order_active_ts_ms": 900000,
        "expires_ts_ms": 1800000,
        "trigger_price": 108,
        "protective_stop": 95,
        **overrides,
    }


def bar(**overrides):
    return {
        "symbol": "BTC-USDT",
        "segment_id": "s1",
        "open_ts_ms": 900000,
        "close_ts_ms": 960000,
        "available_ts_ms": 960000,
        "open": 100,
        "high": 110,
        "low": 99,
        "close": 105,
        **overrides,
    }


def snapshot(ts=1000, price=98, qty=100, entry=100, **overrides):
    return {
        "ts_ms": ts,
        "realized_gross_cum_usdt": 0,
        "fees_cum_usdt": 0,
        "funding_received_cum_usdt": 0,
        "positions": [
            {
                "position_episode_id": "ep1",
                "symbol": "BTC-USDT",
                "side": 1,
                "remaining_qty_base": qty,
                "avg_entry_price": entry,
            }
        ],
        "prices": {
            "BTC-USDT": {
                "ts_ms": ts,
                "price": price,
                "price_basis": "MARK_PRICE",
                "source_ref": "synthetic-fixture",
            }
        },
        **overrides,
    }


def value(rows, basis="MARK_PRICE"):
    return value_account_snapshots(
        rows, initial_cash_usdt=10000, start_ts_ms=0, price_basis=basis
    )


def test_rule_digest_is_stable_and_sensitive():
    assert validate_rules([rule()]) == validate_rules(
        [dict(reversed(list(rule().items())))]
    )
    assert validate_rules([rule()]) != validate_rules(
        [rule(expression="price >= level")]
    )


@pytest.mark.parametrize(
    "field",
    [
        "rule_id",
        "origin",
        "expression",
        "unit",
        "version",
        "source_id",
        "source_locator",
        "source_mode",
    ],
)
def test_each_source_field_required(field):
    r = rule()
    del r[field]
    with pytest.raises(ValueError):
        validate_rules([r])


def test_rule_duplicates_empty_and_unknown_origin():
    for rules in ([], [rule(), rule()], [rule(origin="ORIGINALISH")]):
        with pytest.raises(ValueError):
            validate_rules(rules)


def test_hypothesis_cannot_claim_exact_reproduction():
    r = rule(origin="DECLARED_HYPOTHESIS", hypothesis_id="h1", rationale="fixture")
    assert len(validate_rules([r])) == 64
    with pytest.raises(ValueError, match="HYPOTHESIS_IS_NOT_EXACT_SOURCE"):
        validate_rules([{**r, "exact_source_reproduction": True}])


def test_existing_frozen_rule_requires_code_identity():
    r = rule(origin="EXISTING_FROZEN")
    with pytest.raises(ValueError):
        validate_rules([r])
    assert (
        len(validate_rules([{**r, "code_path": "test.py", "code_sha": "test-sha"}]))
        == 64
    )


def test_intrabar_stop_witness_never_manufactures_exact_fill():
    out = inspect_entry_bar(order(), bar())
    assert out["status"] == "MODEL_STOP_INTERVAL_CANDIDATE"
    assert out["event_interval_ms"] == [900000, 960000]
    assert out["candidate_price"] == 108
    assert out["fill_ts_ms"] is None and out["economic_credit"] is False
    assert out["authority"]["order"] == "BLOCKED"


def test_same_bar_entry_stop_order_stays_unresolved():
    out = inspect_entry_bar(order(), bar(low=90))
    assert out["status"] == "UNRESOLVED_ENTRY_STOP_ORDER"
    assert out["candidate_price"] is None


def test_low_before_activation_is_not_position_stop():
    out = inspect_entry_bar(order(order_active_ts_ms=960000), bar(low=90))
    assert out["status"] == "WAIT"


def test_midbar_activation_cannot_take_that_bar_open():
    out = inspect_entry_bar(order(order_active_ts_ms=930000), bar())
    assert out["status"] == "UNRESOLVED_ACTIVE_INSIDE_BAR"


def test_gap_stop_uses_open_witness_not_trigger_price():
    out = inspect_entry_bar(order(), bar(open=109, high=110, low=106, close=107))
    assert out["candidate_price"] == 109
    assert out["status"] == "MODEL_STOP_OPEN_CANDIDATE"


def test_short_stop_is_symmetric():
    out = inspect_entry_bar(
        order(side=-1, trigger_price=92, protective_stop=105),
        bar(open=100, high=101, low=90, close=91),
    )
    assert out["candidate_price"] == 92
    assert out["status"] == "MODEL_STOP_INTERVAL_CANDIDATE"


def test_limit_touch_is_not_full_maker_fill():
    out = inspect_entry_bar(order(order_kind="LIMIT", trigger_price=99), bar())
    assert out["status"] == "LIMIT_TOUCH_UNCONFIRMED"
    assert out["candidate_price"] is None


def test_nextopen_cannot_roll_forward_after_missing_open():
    o = order(order_kind="NEXT_OPEN")
    assert inspect_entry_bar(o, bar())["candidate_price"] == 100
    assert (
        inspect_entry_bar(
            o, bar(open_ts_ms=960000, close_ts_ms=1020000, available_ts_ms=1020000)
        )["status"]
        == "MISSED_ACTIVATION_OPEN"
    )


@pytest.mark.parametrize("kind", ["STOP_MARKET", "LIMIT"])
def test_intrabar_expiry_not_silently_extended(kind):
    out = inspect_entry_bar(order(order_kind=kind, expires_ts_ms=930000), bar())
    assert out["status"] == "UNRESOLVED_EXPIRY_INSIDE_BAR"


@pytest.mark.parametrize(
    "update",
    [
        {"side": True},
        {"qty_base": 0},
        {"qty_base": float("nan")},
        {"decision_tf_min": 1},
        {"order_kind": "GUARANTEED_MAKER"},
        {"feature_available_ts_ms": 900001},
        {"order_submit_ts_ms": 900001},
        {"expires_ts_ms": 900000},
        {"protective_stop": 109},
        {"order_active_ts_ms": 900000.5},
        {"timing_basis": "FAKE_ACK"},
    ],
)
def test_bad_orders_fail_closed(update):
    with pytest.raises(ValueError):
        inspect_entry_bar(order(**update), bar())


@pytest.mark.parametrize(
    "update",
    [
        {"symbol": "ETH-USDT"},
        {"segment_id": ""},
        {"low": 111},
        {"high": float("inf")},
        {"available_ts_ms": 959999},
        {"close_ts_ms": 1800000, "available_ts_ms": 1800000},
    ],
)
def test_bad_detail_bars_fail_closed(update):
    with pytest.raises(ValueError):
        inspect_entry_bar(order(), bar(**update))


def test_account_dd_is_not_margin_roi():
    out = value([snapshot()])
    assert out["curve"][0]["unrealized_usdt"] == -200
    assert out["curve"][0]["equity_usdt"] == 9800
    assert out["max_drawdown_pct"] == 2
    assert out["liquidation_simulated"] is False


def test_peak_to_trough_uses_peak_not_entry():
    out = value([snapshot(ts=1000, price=110), snapshot(ts=2000, price=105)])
    assert out["max_drawdown_pct"] == pytest.approx(500 / 11000 * 100)


def test_partial_exit_realized_plus_residual_qty_and_costs_once():
    s = snapshot(
        qty=50,
        price=105,
        realized_gross_cum_usdt=500,
        fees_cum_usdt=10,
        funding_received_cum_usdt=-5,
    )
    out = value([s])
    assert out["curve"][0]["cash_usdt"] == 10485
    assert out["curve"][0]["equity_usdt"] == 10735


def test_short_and_simultaneous_hedge_use_actual_quantity():
    s = snapshot(price=98)
    s["positions"].append(
        {**s["positions"][0], "position_episode_id": "ep2", "side": -1}
    )
    assert value([s])["curve"][0]["equity_usdt"] == 10000


def test_price_basis_proxy_is_explicit():
    s = snapshot()
    s["prices"]["BTC-USDT"]["price_basis"] = "LAST_PRICE"
    assert value([s], basis="LAST_PRICE")["price_basis"] == "LAST_PRICE"
    with pytest.raises(ValueError, match="PRICE_BASIS"):
        value([s])


@pytest.mark.parametrize(
    "bad",
    [
        "missing",
        "unsynced",
        "zero",
        "source",
        "leverage",
        "duplicate",
        "side",
        "external_flow",
        "negative_fees",
    ],
)
def test_bad_valuation_evidence_is_not_replaced_with_zero(bad):
    s = snapshot()
    if bad == "missing":
        s["prices"] = {}
    elif bad == "unsynced":
        s["prices"]["BTC-USDT"]["ts_ms"] = 999
    elif bad == "zero":
        s["prices"]["BTC-USDT"]["price"] = 0
    elif bad == "source":
        del s["prices"]["BTC-USDT"]["source_ref"]
    elif bad == "leverage":
        s["positions"][0]["leverage"] = 10
    elif bad == "duplicate":
        s["positions"].append(deepcopy(s["positions"][0]))
    elif bad == "side":
        s["positions"][0]["side"] = True
    elif bad == "external_flow":
        s["external_flow_usdt"] = 100
    elif bad == "negative_fees":
        s["fees_cum_usdt"] = -1
    with pytest.raises(ValueError):
        value([s])


def test_duplicate_timestamps_and_decreasing_cost_total_rejected():
    with pytest.raises(ValueError, match="CHRONOLOGICAL"):
        value([snapshot(), snapshot()])
    with pytest.raises(ValueError, match="CUMULATIVE"):
        value([snapshot(fees_cum_usdt=5), snapshot(ts=2000, fees_cum_usdt=4)])


def test_inputs_not_mutated():
    o, b, s = order(), bar(), snapshot()
    originals = deepcopy((o, b, s))
    inspect_entry_bar(o, b)
    value([s])
    assert (o, b, s) == originals


def test_no_data_no_mtm_claim():
    with pytest.raises(ValueError, match="SNAPSHOTS_REQUIRED"):
        value([])


def test_legacy_metrics_unbound_remains_unbound():
    from backend.research.rebuild import scalp7_metrics_v2

    out = scalp7_metrics_v2.summarize([], 0, 86400000)
    assert out["mark_to_market_DD_bps"] is None
    assert out["mark_to_market_DD_state"] == "UNBOUND_NO_MARK_CURVE"


def test_exact25_manifest_not_counting_extra_lanes_as_complete():
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads(
        (
            root
            / "research/campaigns/scalp7_20260920/implementation_preflight_v1/EXACT25_BINDING.json"
        ).read_text()
    )
    roster = json.loads(
        (
            root / "backend/research/rebuild/benchmark25_donor_native_spec_v1.json"
        ).read_text()
    )
    ids = [r["strategy_id"] for r in manifest["rows"]]
    assert len(ids) == len(set(ids)) == 25
    assert set(ids) == set(roster["children"])
    assert manifest["new_economic_executions"] == 0
    assert all(r["source_reproduction_executed"] is False for r in manifest["rows"])
