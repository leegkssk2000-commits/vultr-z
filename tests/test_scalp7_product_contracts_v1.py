"""Synthetic product-boundary regressions; no genuine-history probe or FULL run."""

import hashlib
import json
from copy import deepcopy

import pandas as pd
import pytest

from backend.research.rebuild import scalp7_hg_closure_v1 as hg
from backend.research.rebuild import scalp7_kell_gajjala_closure_v1 as kg
from backend.research.rebuild import scalp7_product_contracts_v1 as contracts
from backend.research.rebuild.scalp7_volume_contract_v1 import VERSION as VOLUME_VERSION


def grid_bytes(**changes):
    row = dict(
        kind="PRICE_GRID",
        symbol="BTC-USDT",
        venue="BINGX",
        product="PERPETUAL",
        price_increment="0.1",
        valid_from_ms=0,
        valid_to_ms=100,
        available_ts_ms=0,
        source_ref="synthetic:historical-contract-metadata",
        evidence_class="SYNTHETIC_FIXTURE",
    )
    return json.dumps({**row, **changes}, sort_keys=True).encode()


def bind_grid(payload=None, **changes):
    payload = grid_bytes() if payload is None else payload
    args = dict(
        expected_sha256=hashlib.sha256(payload).hexdigest(),
        symbol="BTC-USDT",
        venue="BINGX",
        product="PERPETUAL",
        at_ts_ms=50,
        evidence_class="SYNTHETIC_FIXTURE",
    )
    return contracts.bind_price_grid(payload, **{**args, **changes})


def fvg_order(**changes):
    row = dict(
        identity="synthetic-fvg",
        position_episode_id="episode",
        symbol="X",
        rule_digest="synthetic-rules",
        timing_basis="OBSERVED_ORDER",
        decision_tf_min=15,
        feature_available_ts_ms=0,
        order_submit_ts_ms=0,
        order_active_ts_ms=0,
        expires_ts_ms=1_800_000,
        qty_base=2,
        side=1,
        order_kind="LIMIT",
        trigger_price=99,
        protective_stop=90,
    )
    return {**row, **changes}


def detail(ts=0, **changes):
    row = dict(
        symbol="X",
        open_ts_ms=ts,
        close_ts_ms=ts + 60_000,
        available_ts_ms=ts + 60_000,
        segment_id="continuous",
        open=100,
        high=102,
        low=98,
        close=101,
    )
    return {**row, **changes}


def fvg_receipt(fill_id="partial", **changes):
    row = dict(
        fill_id=fill_id,
        type="FILL",
        ts_ms=0,
        available_ts_ms=0,
        source_ref="synthetic:explicit-receipt",
        symbol="X",
        effect="OPEN",
        qty_base="0.5",
        fill_price=99,
        fee_usdt="0.05",
        side=1,
        maker_taker="UNKNOWN",
        execution_evidence="OBSERVED_FILL_RECEIPT",
        position_episode_id="episode",
    )
    return {**row, **changes}


def turtle_fill(fill_id="unit1", **changes):
    row = dict(
        fill_id=fill_id,
        unit_id=fill_id,
        state="FILLED",
        unit_complete=True,
        fill_ts_ms=10,
        available_ts_ms=10,
        source_ref="synthetic:filled-unit",
        execution_evidence="DECLARED_MODEL_FILL",
        fill_price=100,
        qty_base=1,
    )
    return {**row, **changes}


def turtle_state(fills=None, **changes):
    args = dict(
        n=2,
        side=1,
        reference=dict(
            source_unit="TRADING_DAY",
            system="SYSTEM2_55_20",
            available_ts_ms=0,
            source_ref="synthetic:native-daily-reference",
            entry_days=55,
            exit_days=20,
            N=2,
        ),
    )
    return contracts.turtle_daily_filled_units(
        [turtle_fill()] if fills is None else fills, **{**args, **changes}
    )


def spot_fill(fill_id, side, qty, price, ts, fee, **changes):
    row = dict(
        fill_id=fill_id,
        symbol="BTCUSDT",
        venue="BINGX",
        product="SPOT",
        market_type="SPOT",
        side=side,
        qty_base=qty,
        price=price,
        fee_usdt=fee,
        fee_currency="USDT",
        fill_ts_ms=ts,
        available_ts_ms=ts,
        source_ref="synthetic:finite-spot-fill",
        execution_evidence="DECLARED_MODEL_FILL",
    )
    return {**row, **changes}


def spot_ledger(fills=None, **changes):
    args = dict(
        product_contract=dict(
            market_type="SPOT",
            product="SPOT",
            venue="BINGX",
            symbol="BTCUSDT",
            quote_currency="USDT",
            external_cash_flows="NONE",
            available_ts_ms=0,
            source_ref="synthetic:native-spot-contract",
        ),
        symbol="BTCUSDT",
        initial_cash_usdt=1000,
        initial_qty_base=0,
        initial_avg_entry=0,
        final_price=dict(
            market_type="SPOT",
            product="SPOT",
            venue="BINGX",
            symbol="BTCUSDT",
            ts_ms=40,
            available_ts_ms=40,
            price_basis="LAST_PRICE",
            price=130,
            source_ref="synthetic:spot-last",
        ),
    )
    return contracts.value_native_spot_ledger(
        [] if fills is None else fills, **{**args, **changes}
    )


def test_price_increment_is_not_tape_or_authenticity_credit():
    out = bind_grid()
    assert out["tick_size"] == pytest.approx(0.1)
    assert out["price_increment_decimal"] == "0.1"
    assert out["kind"] == "PRICE_GRID"
    assert out["unit"] == "QUOTE_PRICE_INCREMENT"
    assert out["valid_from_ts_ms"] == out["valid_from_ms"] == 0
    assert out["valid_to_ts_ms"] == out["valid_to_ms"] == 100
    assert not out["trade_tape_available"]
    assert not out["provider_authenticity_independently_verified"]
    assert not out["economic_credit"]
    assert out["evidence_class"] == "SYNTHETIC_FIXTURE"


@pytest.mark.parametrize(
    "payload",
    [
        grid_bytes(kind="TRADE_TAPE"),
        grid_bytes(unit="TRADE_COUNT"),
        grid_bytes(valid_from_ts_ms=1),
        grid_bytes(valid_to_ts_ms=101),
        grid_bytes(valid_from_ts_ms=False),
        grid_bytes(available_ts_ms=51),
        grid_bytes(valid_to_ms=50),
        grid_bytes(valid_from_ms=51),
        grid_bytes(price_increment="NaN"),
        grid_bytes(price_increment="1e1000"),
        grid_bytes(price_increment="1e-1000"),
        grid_bytes(price_increment=0),
        grid_bytes(source_ref=" "),
        grid_bytes(evidence_class="OBSERVED_METADATA"),
    ],
)
def test_historical_grid_missing_wrong_kind_or_unavailable_rejected(payload):
    with pytest.raises(ValueError):
        bind_grid(payload)


@pytest.mark.parametrize(
    "changes",
    [
        dict(expected_sha256="0" * 64),
        dict(venue="OTHER"),
        dict(product="SPOT"),
        dict(symbol="ETH-USDT"),
        dict(at_ts_ms=True),
    ],
)
def test_grid_digest_identity_and_strict_clock_binding(changes):
    with pytest.raises(ValueError):
        bind_grid(**changes)


def test_fvg_touch_has_no_fill_partial_cancel_retains_inventory():
    a = contracts.fvg_receipt_adapter(fvg_order(), fee_rate=0)
    assert a.process_detail_bar(detail())["status"] == "LIMIT_TOUCH_UNCONFIRMED"
    assert a.ledger == [] and a.position is None
    b = contracts.fvg_receipt_adapter(fvg_order(), fee_rate=0)
    b.record_fill(fvg_receipt())
    b.cancel(0)
    assert b.order_state == "CANCELLED"
    assert b.position["remaining_qty_base"] == "0.5"
    b.record_fill(
        fvg_receipt(
            "close",
            effect="CLOSE",
            fill_price=110,
            ts_ms=10,
            available_ts_ms=10,
        )
    )
    assert b.state == "CLOSED"
    assert len(b.ledger) == 2


def test_fvg_gap_preserves_partial_ownership_and_rejects_late_fill():
    a = contracts.fvg_receipt_adapter(fvg_order(), fee_rate=0)
    a.record_fill(fvg_receipt())
    a.process_detail_bar(detail())
    assert (
        a.process_detail_bar(detail(120_000))["status"]
        == "DETAIL_GAP_NO_SYNTHETIC_FILL"
    )
    assert a.state == "UNRESOLVED"
    assert a.position["remaining_qty_base"] == "0.5"
    assert len(a.ledger) == 1
    with pytest.raises(ValueError, match="UNRESOLVED_OWNERSHIP"):
        a.cancel(180_000)


@pytest.mark.parametrize(
    "changes",
    [dict(order_kind="NEXT_OPEN"), dict(timing_basis="HISTORICAL_MODEL")],
)
def test_fvg_wrapper_does_not_turn_a_modeled_order_into_observed_limit(changes):
    with pytest.raises(ValueError):
        contracts.fvg_receipt_adapter(fvg_order(**changes), fee_rate=0)


def test_turtle_daily_fill_units_use_realized_fill_prices():
    fills = [
        turtle_fill(),
        turtle_fill("unit2", fill_ts_ms=20, available_ts_ms=20, fill_price=101.4),
    ]
    before = deepcopy(fills)
    out = turtle_state(fills)
    assert out["units"] == 2
    assert out["stop_prices"] == pytest.approx([97, 97.4])
    assert out["next_add_trigger"] == pytest.approx(102.4)
    assert out["native_timeframe"] == "DAILY"
    assert out["execution_evidence"] == ["DECLARED_MODEL_FILL"]
    assert out["state_available_ts_ms"] == 20
    assert not out["provider_authenticity_independently_verified"]
    assert not out["full_strategy_caller_complete"]
    assert fills == before


@pytest.mark.parametrize(
    "changes",
    [
        dict(source_unit="30M"),
        dict(system="SYSTEM1_20_10"),
        dict(available_ts_ms=11),
        dict(entry_days=20),
        dict(N=3),
    ],
)
def test_turtle_native_daily_reference_and_frozen_n_guards(changes):
    ref = dict(
        source_unit="TRADING_DAY",
        system="SYSTEM2_55_20",
        available_ts_ms=0,
        source_ref="synthetic:daily",
        entry_days=55,
        exit_days=20,
        N=2,
    )
    with pytest.raises(ValueError):
        turtle_state(reference={**ref, **changes})


@pytest.mark.parametrize(
    "changes",
    [
        dict(state="PENDING"),
        dict(unit_complete=False),
        dict(fill_ts_ms=10.5),
        dict(fill_ts_ms=True),
        dict(available_ts_ms=9),
        dict(source_ref=""),
        dict(execution_evidence="LIMIT_TOUCH"),
    ],
)
def test_turtle_pending_unit_missing_evidence_or_bad_clock_is_not_a_filled_unit(
    changes,
):
    with pytest.raises(ValueError):
        turtle_state([turtle_fill(**changes)])


def test_turtle_no_add_below_half_n_and_no_mixed_evidence():
    with pytest.raises(ValueError, match="HALF_N"):
        turtle_state(
            [
                turtle_fill(),
                turtle_fill(
                    "unit2", fill_ts_ms=20, available_ts_ms=20, fill_price=100.5
                ),
            ]
        )
    with pytest.raises(ValueError):
        turtle_state(
            [
                turtle_fill(),
                turtle_fill(
                    "unit2",
                    fill_ts_ms=20,
                    available_ts_ms=20,
                    fill_price=101,
                    execution_evidence="OBSERVED_FILL",
                ),
            ]
        )


def test_native_spot_partial_sale_accounting_is_independently_hand_computed():
    fills = [
        spot_fill("a", "BUY", 1, 100, 10, 1),
        spot_fill("b", "BUY", 1, 120, 20, 1),
        spot_fill("c", "SELL", 1, 150, 30, 2),
    ]
    before = deepcopy(fills)
    out = spot_ledger(fills)
    assert out["cash_usdt"] == 926
    assert out["remaining_qty_base"] == 1
    assert out["avg_entry_price"] == 110
    assert out["realized_gross_usdt"] == 40
    assert out["unrealized_usdt"] == 20
    assert out["fees_usdt"] == 4
    assert out["equity_usdt"] == 1056
    assert out["net_usdt"] == 56
    assert not out["DGT_order_reset_caller_complete"]
    assert not out["full_DGT_reproduction"]
    assert fills == before


@pytest.mark.parametrize(
    "changes",
    [
        dict(market_type="PERPETUAL"),
        dict(venue="OTHER"),
        dict(product="PERPETUAL"),
        dict(symbol="ETHUSDT"),
    ],
)
def test_perpetual_or_cross_product_fill_cannot_enter_spot_inventory(changes):
    with pytest.raises(ValueError):
        spot_ledger([spot_fill("a", "BUY", 1, 100, 10, 0, **changes)])


@pytest.mark.parametrize(
    "changes",
    [dict(market_type="PERPETUAL"), dict(venue="OTHER"), dict(product="PERPETUAL")],
)
def test_perpetual_or_cross_venue_price_cannot_mark_native_spot(changes):
    price = dict(
        market_type="SPOT",
        product="SPOT",
        venue="BINGX",
        symbol="BTCUSDT",
        ts_ms=40,
        available_ts_ms=40,
        price_basis="LAST_PRICE",
        price=130,
        source_ref="synthetic:spot-last",
    )
    with pytest.raises(ValueError):
        spot_ledger(final_price={**price, **changes})


def test_finite_spot_cannot_sell_unowned_inventory_or_get_implicit_cash_topups():
    with pytest.raises(ValueError, match="SPOT_INVENTORY_EXCEEDED"):
        spot_ledger([spot_fill("a", "SELL", 1, 100, 10, 0)])
    with pytest.raises(ValueError, match="INSUFFICIENT_FINITE_CASH"):
        spot_ledger([spot_fill("a", "BUY", 11, 100, 10, 0)])


def integration_bars(values, minutes, start=0):
    """Hand drawn candles for the real compile paths, never market history."""
    rows = []
    for i, (opened, high, low, close, volume) in enumerate(values):
        ts = start + i * minutes * kg.MINUTE
        rows.append(
            dict(
                open_ts_ms=ts,
                close_ts_ms=ts + minutes * kg.MINUTE,
                available_ts_ms=ts + minutes * kg.MINUTE,
                segment_id="synthetic-grid-integration",
                open=opened,
                high=high,
                low=low,
                close=close,
                volume=volume,
                volume_unit="BASE",
                source_base=volume,
                source_base_available_ts_ms=ts + minutes * kg.MINUTE,
            )
        )
    frame = pd.DataFrame(rows)
    frame.attrs.update(
        data_kind="SYNTHETIC_FIXTURE",
        fixture_label="SYNTHETIC_UNIT_TEST_ONLY",
        volume_units="BASE",
        source_revision_sha256="1" * 64,
        source_schema_sha256="2" * 64,
        source_unit_authority_sha256="3" * 64,
        volume_field_units={"source_base": "BASE"},
    )
    return frame


def integration_grid(tick, valid_to_ms=100 * kg.HOUR):
    payload = grid_bytes(price_increment=str(tick), valid_to_ms=valid_to_ms)
    return bind_grid(payload, at_ts_ms=0)


def integration_kg_inputs(model, receipt):
    symbol, benchmark = "BTC-USDT", "BENCH-USDT"
    if model == kg.KELL:
        values = [(100, 100.2, 99.8, 100, 100)] * 30 + [
            (100, 110, 99, 105, 100),
            (105, 107, 104, 106, 100),
            (106, 108, 105, 107, 100),
            (107, 107.5, 104, 105.5, 100),
        ]
        level = 95
    else:
        values = [(10, 10.1, 9.9, 10, 100)] * 30 + [
            (10, 14, 10, 13.8, 1000),
            (13.8, 13.9, 13, 13.2, 200),
            (13.2, 13.7, 13.1, 13.4, 200),
            (13.4, 14.2, 13.2, 14, 800),
        ]
        level = 9
    context = [
        (
            level + i * 0.001,
            level + 1 + i * 0.001,
            level - 1,
            level + 0.0005 + i * 0.001,
            100,
        )
        for i in range(30)
    ]
    binding = dict(
        schema=VOLUME_VERSION,
        venue="SYNTHETIC",
        instrument=symbol,
        product="SYNTHETIC",
        base_asset="BTC",
        quote_asset="USDT",
        price_unit="USDT",
        source_revision_sha256="1" * 64,
        source_schema_sha256="2" * 64,
        source_unit_authority_sha256="3" * 64,
        source_unit_authority_locator="synthetic integration fixture recipe",
        evidence_kind="SYNTHETIC_TEST_ONLY",
        fields={
            "base": dict(
                value="source_base",
                available="source_base_available_ts_ms",
                unit="BASE",
                asset="BTC",
                observed=True,
            )
        },
    )
    return {symbol: integration_bars(values, 15, start=6 * kg.HOUR)}, {
        "tick_evidence": {symbol: receipt},
        "context_frames": {
            symbol: integration_bars(context, 60),
            benchmark: integration_bars(
                [(level, level + 1, level - 1, level, 100)] * 30, 60
            ),
        },
        "benchmark_symbol": benchmark,
        "volume_bindings": {symbol: binding},
    }


@pytest.mark.parametrize("model", kg.MODEL_IDS)
def test_bound_grid_receipt_feeds_actual_kell_gajjala_compile_and_pit_gate(model):
    tick = 0.1 if model == kg.KELL else 0.01
    receipt = integration_grid(tick)
    frames, config = integration_kg_inputs(model, receipt)
    out = kg.compile_model(model, frames, config)
    assert len(out["plans"]) == 1
    plan = out["plans"][0]
    assert plan["tick_size"] == pytest.approx(tick)
    assert plan["tick_receipt_sha256"] == receipt["source_receipt_sha256"]
    assert not out["genuine_execution_ready"] and out["new_full_runs"] == 0
    assert receipt["evidence_class"] == "SYNTHETIC_FIXTURE"
    assert not receipt["trade_tape_available"] and not receipt["economic_credit"]
    # Valid when bound at t=0 does not imply valid at a later setup or entry.
    config["tick_evidence"]["BTC-USDT"] = integration_grid(tick, kg.HOUR)
    blocked = kg.compile_model(model, frames, config)
    assert blocked["plans"] == []
    assert any(e["kind"] == "BLOCKED_PIT_TICK_GRID" for e in blocked["events"])


def test_bound_grid_numeric_field_feeds_actual_hg_scalar_compile_contract():
    candles = [(100, 100.2, 99.8, 100, 100)] * 35
    candles += [
        (100 + i + 0.2, 101 + i + 0.2, 100 + i, 101 + i, 100) for i in range(12)
    ] + [(112, 112.2, 103, 108, 100)]
    frame = integration_bars(candles, 30)
    known = int(frame.iloc[-1]["available_ts_ms"])
    receipt = bind_grid(grid_bytes(valid_to_ms=100 * kg.HOUR), at_ts_ms=known)
    out = hg.compile_model(
        hg.MODEL_ID,
        {"BTC-USDT": frame},
        {"tick_sizes": {"BTC-USDT": receipt["tick_size"]}},
    )
    assert len(out["plans"]) == 1
    assert out["plans"][0]["signal"]["tick_size"] == pytest.approx(0.1)
    assert not out["genuine_tick_receipt_verified"]
    assert not out["economic_execution_performed"]
    assert not receipt["provider_authenticity_independently_verified"]
