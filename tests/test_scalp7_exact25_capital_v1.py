from copy import deepcopy

import pytest

from backend.research.rebuild import scalp7_exact25_capital_v1 as capital


def signal(component="A", **changes):
    row = dict(
        component_id=component,
        signal_id=component + ":1",
        symbol="BTCUSDT",
        producer_code_sha256="a" * 64,
        rule_digest="b" * 64,
        available_ts_ms=10,
        valid_until_ts_ms=30,
    )
    return {**row, **changes}


def allocation(signals, **changes):
    kwargs = dict(
        weights={"A": 0.6, "B": 0.4}, decision_ts_ms=20, available_risk_fraction=0.5
    )
    return capital.allocate_existing_signals(signals, **{**kwargs, **changes})


def fill(fill_id, side, qty, price, ts, fee):
    return dict(
        fill_id=fill_id,
        symbol="BTCUSDT",
        side=side,
        qty_base=qty,
        price=price,
        fee_usdt=fee,
        fee_currency="USDT",
        fill_ts_ms=ts,
        available_ts_ms=ts,
        source_ref="synthetic:hand-account",
        execution_evidence="DECLARED_MODEL_FILL",
    )


def ledger(fills, **changes):
    kwargs = dict(
        initial_cash_usdt=1000,
        initial_qty_base=0,
        initial_avg_entry=0,
        symbol="BTCUSDT",
        final_price=dict(
            ts_ms=40,
            available_ts_ms=40,
            symbol="BTCUSDT",
            price_basis="LAST_PRICE",
            price=130,
            source_ref="synthetic:last",
        ),
    )
    return capital.value_spot_fill_ledger(fills, **{**kwargs, **changes})


def test_allocation_preserves_empty_component_cash_and_does_not_renormalize():
    result = allocation([signal()])
    assert result["allocations"][0]["risk_fraction"] == 0.3
    assert result["cash_risk_fraction"] == 0.2
    assert result["composition_authorized"] is False
    both = allocation([signal(), signal("B")])
    assert both["cash_risk_fraction"] == 0


@pytest.mark.parametrize(
    "signals", [[], [signal(available_ts_ms=21)], [signal(valid_until_ts_ms=20)]]
)
def test_no_valid_signal_means_cash(signals):
    assert allocation(signals)["allocations"] == []
    assert allocation(signals)["cash_risk_fraction"] == 0.5


@pytest.mark.parametrize(
    "changes", [dict(future_pnl=1), dict(rule_digest=""), dict(producer_code_sha256="")]
)
def test_unbound_or_outcome_selected_components_rejected(changes):
    with pytest.raises(ValueError):
        allocation([signal(**changes)])


@pytest.mark.parametrize("weights", [{"A": 1.1}, {"A": -0.1}, {}, {"A": True}])
def test_invalid_weight_budget_rejected(weights):
    with pytest.raises(ValueError):
        allocation([], weights=weights)


def test_duplicate_component_has_no_implicit_tiebreaker():
    with pytest.raises(ValueError, match="DUPLICATE_OR_UNBOUND"):
        allocation([signal(), signal(signal_id="A:2")])


def test_partial_spot_sale_average_cost_and_fees_hand_reconcile():
    result = ledger(
        [
            fill("a", "BUY", 1, 100, 10, 1),
            fill("b", "BUY", 1, 120, 20, 1),
            fill("c", "SELL", 1, 150, 30, 2),
        ]
    )
    assert result["cash_usdt"] == 926
    assert result["remaining_qty_base"] == 1
    assert result["avg_entry_price"] == 110
    assert result["realized_gross_usdt"] == 40
    assert result["unrealized_usdt"] == 20
    assert result["fees_usdt"] == 4
    assert result["equity_usdt"] == 1056
    assert result["net_usdt"] == 56
    assert result["fill_count"] == 3
    assert result["trade_episode_T"] is None


@pytest.mark.parametrize(
    "fills,reason",
    [
        ([fill("a", "BUY", 11, 100, 10, 0)], "INSUFFICIENT_FINITE_CASH"),
        ([fill("a", "SELL", 1, 100, 10, 0)], "SPOT_INVENTORY_EXCEEDED"),
        ([fill("a", "BUY", 1, 100, 10, 0)] * 2, "DUPLICATE_OR_MISSING_FILL_ID"),
    ],
)
def test_spot_cannot_create_cash_inventory_or_duplicate_fills(fills, reason):
    with pytest.raises(ValueError, match=reason):
        ledger(fills)


@pytest.mark.parametrize(
    "changes",
    [
        dict(execution_evidence="LIMIT_TOUCH"),
        dict(fee_currency="BTC"),
        dict(leverage=20),
        dict(available_ts_ms=9),
        dict(fee_usdt=-1),
    ],
)
def test_spot_fill_evidence_cost_and_clock_guards(changes):
    row = {**fill("a", "BUY", 1, 100, 10, 0), **changes}
    with pytest.raises(ValueError):
        ledger([row])


def test_observed_and_model_fills_remain_separate():
    a, b = fill("a", "BUY", 1, 100, 10, 0), fill("b", "BUY", 1, 100, 20, 0)
    b["execution_evidence"] = "OBSERVED_FILL"
    with pytest.raises(ValueError, match="MIXED_MODEL"):
        ledger([a, b])


def test_initial_inventory_basis_is_not_new_profit():
    result = ledger([], initial_qty_base=2, initial_avg_entry=120)
    assert result["net_usdt"] == 20
    assert result["equity_usdt"] == 1260


def test_inputs_are_not_mutated_and_source_status_not_promoted():
    rows = [fill("a", "BUY", 1, 100, 10, 1)]
    before = deepcopy(rows)
    result = ledger(rows)
    assert rows == before
    assert not result["full_DGT_reproduction"]
    assert result["authority"]["live"] == "BLOCKED"


def test_catalog_and_rule_contract_cover_both_original_ids():
    assert set(capital.catalog()) == {"alpha_combo", "grid_rebalance"}
    out = capital.evaluate(
        "alpha_combo",
        {},
        dict(
            timeframe_min=15,
            component_signals=[signal()],
            weights={"A": 1},
            decision_ts_ms=20,
            available_risk_fraction=0.2,
        ),
    )
    assert len(out["rule_digest"]) == 64
    assert not out["complete_strategy"] and out["intents"] == []


def test_float_overflow_cannot_be_published():
    with pytest.raises(ValueError, match="OUTPUT_NOT_FINITE"):
        ledger([], initial_cash_usdt="1e1000")


def test_sell_fee_cannot_create_negative_cash():
    with pytest.raises(ValueError, match="INSUFFICIENT_FINITE_CASH_FOR_SELL_FEE"):
        ledger(
            [fill("fee", "SELL", 1, 1, 10, 3)],
            initial_cash_usdt=1,
            initial_qty_base=1,
            initial_avg_entry=10,
        )


def test_valuation_waits_for_all_receipts_and_explicit_price_availability():
    row = {**fill("late", "BUY", 1, 100, 10, 1), "available_ts_ms": 100}
    with pytest.raises(ValueError, match="VALUATION_BEFORE_ALL_INPUTS_AVAILABLE"):
        ledger([row])
    price = dict(
        ts_ms=40,
        available_ts_ms=100,
        symbol="BTCUSDT",
        price_basis="LAST_PRICE",
        price=130,
        source_ref="synthetic:late-known",
    )
    result = ledger([row], final_price=price)
    assert result["valuation_available_ts_ms"] == 100
    assert result["valuation_price_ts_ms"] == 40
    assert result["state_trace"][0]["available_ts_ms"] == 100
    del price["available_ts_ms"]
    with pytest.raises(ValueError):
        ledger([], final_price=price)


def test_net_basis_and_unverified_allocation_provenance_are_explicit():
    assert (
        ledger([])["net_basis"] == "INITIAL_INVENTORY_AVERAGE_COST_NOT_INITIAL_MARK_NAV"
    )
    out = allocation([signal()])
    assert out["weight_freeze_status"] == "CALLER_SUPPLIED_NOT_INDEPENDENTLY_VERIFIED"
    assert (
        out["signal_provenance_status"]
        == "IDENTIFIERS_PRESENT_SOURCE_BYTES_NOT_CHECKED"
    )
    assert out["allocations"][0]["signal_available_ts_ms"] == 10
