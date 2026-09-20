"""Hand-computed synthetic cases; no historical signal probe or FULL run."""

import copy

import pytest

from backend.research.rebuild.scalp7_exact25_execution_v1 import (
    MODEL,
    RECEIPT_ONLY,
    DetailExecutionAdapter,
    account_snapshots_from_ledger,
)


def order(**kw):
    return {
        "identity": "fixture",
        "position_episode_id": "episode",
        "symbol": "X",
        "rule_digest": "rules",
        "timing_basis": "HISTORICAL_MODEL",
        "decision_tf_min": 15,
        "feature_available_ts_ms": 0,
        "order_submit_ts_ms": 0,
        "order_active_ts_ms": 0,
        "expires_ts_ms": 1800000,
        "qty_base": 2,
        "side": 1,
        "order_kind": "NEXT_OPEN",
        "protective_stop": 90,
        **kw,
    }


def bar(t=0, **kw):
    return {
        "symbol": "X",
        "open_ts_ms": t,
        "close_ts_ms": t + 60000,
        "available_ts_ms": t + 60000,
        "segment_id": "continuous",
        "open": 100,
        "high": 102,
        "low": 98,
        "close": 101,
        **kw,
    }


def adapter(**kw):
    return DetailExecutionAdapter(order(**kw), fill_model=MODEL, fee_rate="0.001")


def receipt(i="a", **kw):
    return {
        "fill_id": i,
        "type": "FILL",
        "ts_ms": 0,
        "available_ts_ms": kw.get("ts_ms", 0),
        "source_ref": "synthetic_receipt",
        "symbol": "X",
        "effect": "OPEN",
        "qty_base": 1,
        "fill_price": 100,
        "fee_usdt": ".1",
        "side": 1,
        "maker_taker": "UNKNOWN",
        "execution_evidence": "OBSERVED_FILL_RECEIPT",
        "position_episode_id": "episode",
        **kw,
    }


def observed(**kw):
    return DetailExecutionAdapter(
        order(timing_basis="OBSERVED_ORDER", **kw), fill_model=RECEIPT_ONLY, fee_rate=0
    )


def mark(t, p=100, **kw):
    return {
        "ts_ms": t,
        "prices": {
            "X": {
                "ts_ms": t,
                "price": p,
                "price_basis": "MARK_PRICE",
                "source_ref": "synthetic_mark",
                **kw,
            }
        },
    }


def value(ledger, prices, **kw):
    return account_snapshots_from_ledger(
        ledger,
        prices,
        initial_cash_usdt=1000,
        start_ts_ms=0,
        price_basis="MARK_PRICE",
        **kw
    )


def test_model_next_open_then_original_stop_same_minute():
    a = adapter()
    a.process_detail_bar(bar(low=89))
    assert a.state == "CLOSED"
    assert [r["fill_price"] for r in a.ledger] == ["100.0", "90.0"]
    assert a.ledger[0]["ts_ms"] == 0
    assert a.ledger[1]["event_interval_ms"] == [0, 60000]
    assert all(r["execution_evidence"] == "MODEL_NOT_OBSERVED" for r in a.ledger)
    assert a.finish()["authority"]["live"] == "BLOCKED"


def test_pending_stop_retains_original_activation_clock():
    a = adapter(order_kind="STOP_MARKET", trigger_price=105)
    a.process_detail_bar(bar())
    a.process_detail_bar(bar(60000, high=106))
    assert a.order["order_active_ts_ms"] == 0
    assert a.ledger[0]["event_interval_ms"] == [60000, 120000]
    assert a.ledger[0]["ts_ms"] == 120000
    assert a.finish()["state"] == "UNRESOLVED"


def test_same_minute_entry_stop_order_is_unresolved_without_fill():
    a = adapter(order_kind="STOP_MARKET", trigger_price=105)
    assert (
        a.process_detail_bar(bar(high=106, low=89))["status"]
        == "UNRESOLVED_ENTRY_STOP_ORDER"
    )
    assert a.ledger == []


def test_stop_gap_fill_occurs_at_open_not_trigger():
    a = adapter(order_kind="STOP_MARKET", trigger_price=99)
    a.process_detail_bar(bar())
    assert a.ledger[0]["fill_price"] == "100.0"
    assert a.ledger[0]["time_precision"] == "OPEN"


def test_limit_touch_has_no_queue_or_full_fill():
    a = adapter(order_kind="LIMIT", trigger_price=99)
    assert a.process_detail_bar(bar())["status"] == "LIMIT_TOUCH_UNCONFIRMED"
    assert a.position is None and a.ledger == []


@pytest.mark.parametrize("kind", ["gap", "segment"])
def test_gap_preserves_open_position_and_no_synthetic_close(kind):
    a = adapter()
    a.process_detail_bar(bar())
    next_bar = bar(120000) if kind == "gap" else bar(60000, segment_id="different")
    assert a.process_detail_bar(next_bar)["status"] == "DETAIL_GAP_NO_SYNTHETIC_FILL"
    assert a.position is not None and len(a.ledger) == 1
    with pytest.raises(ValueError, match="UNRESOLVED_OWNERSHIP"):
        a.cancel(180000)


def test_before_activation_low_does_not_close_later_position():
    a = adapter(feature_available_ts_ms=0, order_active_ts_ms=60000)
    a.process_detail_bar(bar(low=50))
    a.process_detail_bar(bar(60000))
    assert a.state == "ACTIVE" and len(a.ledger) == 1


def test_first_missing_activation_minute_is_not_next_available_open():
    a = adapter()
    assert a.process_detail_bar(bar(60000))["status"] == "MISSING_ACTIVATION_DETAIL"
    assert a.ledger == []


def test_active_inside_minute_is_unresolved():
    a = adapter(order_active_ts_ms=30000)
    assert a.process_detail_bar(bar())["status"] == "UNRESOLVED_ACTIVE_INSIDE_BAR"


def test_expiry_and_cancel_do_not_refill():
    a = adapter(order_kind="LIMIT", trigger_price=99, expires_ts_ms=60000)
    a.process_detail_bar(bar())
    a.process_detail_bar(bar(60000))
    assert a.state == "EXPIRED" and not a.ledger
    b = adapter()
    b.cancel(0)
    assert b.process_detail_bar(bar())["status"] == "TERMINAL_NO_REPLAY"


def test_partial_observed_fill_remaining_and_cancel_keep_position():
    a = observed(order_kind="LIMIT", trigger_price=100)
    a.record_fill(receipt(qty_base="0.5"))
    assert str(a.remaining) == "1.5"
    a.cancel(0)
    assert a.state == "ACTIVE" and a.position["remaining_qty_base"] == "0.5"
    a.record_fill(receipt("close", effect="CLOSE", qty_base="0.25", fill_price=110))
    assert a.position["remaining_qty_base"] == "0.25"
    with pytest.raises(ValueError, match="ORDER_NOT_FILLABLE"):
        a.record_fill(receipt("late", qty_base="0.5"))


def test_observed_receipt_cannot_fabricate_stop_fill_from_ohlc():
    a = observed()
    a.record_fill(receipt(qty_base=2))
    assert a.process_detail_bar(bar(low=80))["status"] == "STOP_RECEIPT_REQUIRED"
    assert len(a.ledger) == 1


@pytest.mark.parametrize(
    "change, reason",
    [
        ({"qty_base": 3}, "OVERFILL"),
        ({"ts_ms": -1}, "INVALID_TIMESTAMP"),
        ({"execution_evidence": "MODEL_NOT_OBSERVED"}, "FILL_EVIDENCE"),
        ({"slippage_usdt": 1}, "REAPPLICATION"),
        ({"leverage": 20}, "REAPPLICATION"),
    ],
)
def test_bad_receipts_rejected_without_partial_mutation(change, reason):
    a = observed()
    with pytest.raises(ValueError, match=reason):
        a.record_fill(receipt(**change))
    assert not a.ledger and a.position is None and a.remaining == 2


def test_duplicate_and_overclose_rejected():
    a = observed()
    a.record_fill(receipt())
    with pytest.raises(ValueError, match="DUPLICATE"):
        a.record_fill(receipt())
    with pytest.raises(ValueError, match="OVERCLOSE"):
        a.record_fill(receipt("b", effect="CLOSE", qty_base=2))


def test_trailing_uses_completed_decision_then_next_minute_only():
    calls = []

    def trail(position, decision, history):
        calls.append((position, decision, history))
        return {"next_stop": 99}

    a = DetailExecutionAdapter(order(), fill_model=MODEL, fee_rate=0, exit_update=trail)
    rows = [bar(i * 60000) for i in range(15)]
    for row in rows:
        a.process_detail_bar(row)
    decision = bar(0, close_ts_ms=900000, available_ts_ms=900000)
    a.process_decision_bar(decision, [decision])
    assert len(calls) == 1 and a.stop == 90 and len(a.ledger) == 1
    a.process_detail_bar(bar(900000))
    assert a.state == "CLOSED" and a.ledger[-1]["fill_price"] == "99.0"
    assert a.ledger[-1]["event_interval_ms"] == [900000, 960000]


def test_callback_market_exit_next_minute_open():
    a = DetailExecutionAdapter(
        order(),
        fill_model=MODEL,
        fee_rate=0,
        exit_update=lambda p, b, h: {"exit_next_open": True},
    )
    for i in range(15):
        a.process_detail_bar(bar(i * 60000))
    decision = bar(0, close_ts_ms=900000, available_ts_ms=900000)
    a.process_decision_bar(decision, [decision])
    a.process_detail_bar(bar(900000, open=101))
    assert a.ledger[-1]["ts_ms"] == 900000 and a.ledger[-1]["fill_price"] == "101.0"


def test_future_history_and_wrong_aggregate_rejected():
    a = DetailExecutionAdapter(
        order(),
        fill_model=MODEL,
        fee_rate=0,
        exit_update=lambda p, b, h: {"next_stop": 99},
    )
    for i in range(15):
        a.process_detail_bar(bar(i * 60000))
    decision = bar(0, close_ts_ms=900000, available_ts_ms=900000)
    with pytest.raises(ValueError, match="FUTURE"):
        a.process_decision_bar(decision, [bar(900000)])
    with pytest.raises(ValueError, match="OHLC_MISMATCH"):
        a.process_decision_bar({**decision, "low": 99}, [decision])


def test_actual_average_entry_partial_close_fees_and_signed_funding():
    ledger = [
        receipt("one", qty_base=2, fill_price=100, fee_usdt=2),
        receipt("two", ts_ms=1, qty_base=1, fill_price=130, fee_usdt=1),
        receipt(
            "part", ts_ms=2, effect="CLOSE", qty_base=1, fill_price=140, fee_usdt=1
        ),
        {
            "type": "FUNDING",
            "event_id": "fund",
            "ts_ms": 2,
            "settlement_ts_ms": 2,
            "symbol": "X",
            "amount_usdt": -3,
            "source_ref": "synthetic_funding",
        },
        {
            "type": "FEE",
            "event_id": "fee",
            "ts_ms": 2,
            "amount_usdt": 2,
            "source_ref": "synthetic_fee",
        },
    ]
    result = value(ledger, [mark(0, 100), mark(1, 120), mark(2, 100)])
    snap = result["snapshots"][-1]
    assert snap["positions"][0]["avg_entry_price"] == "110"
    assert snap["positions"][0]["remaining_qty_base"] == "2"
    assert snap["realized_gross_cum_usdt"] == "30"
    assert snap["fees_cum_usdt"] == "6"
    assert snap["funding_received_cum_usdt"] == "-3"
    curve = result["valuation"]["curve"]
    assert [r["equity_usdt"] for r in curve] == [998, 1027, 1001]
    assert result["valuation"]["max_drawdown_pct"] == pytest.approx(26 / 1027 * 100)


def test_short_close_gross_actual_qty_and_closed_episode():
    result = value(
        [
            receipt("open", qty_base=3, side=-1, fee_usdt=0),
            receipt(
                "close",
                ts_ms=1,
                effect="CLOSE",
                qty_base=3,
                fill_price=90,
                side=-1,
                fee_usdt=0,
            ),
        ],
        [mark(0), {"ts_ms": 1, "prices": {}}],
    )
    assert result["valuation"]["curve"][-1]["equity_usdt"] == 1030
    assert result["closed_position_episodes"] == ["episode"]


@pytest.mark.parametrize(
    "prices, reason",
    [
        ([{"ts_ms": 0, "prices": {}}], "PRICE_MISSING"),
        ([mark(0, price_basis="LAST_PRICE")], "PRICE_BASIS_MISMATCH"),
        ([mark(0, ts_ms=1)], "UNSYNCHRONIZED"),
        ([mark(0, price=None)], "INVALID_NUMBER"),
    ],
)
def test_missing_or_wrong_mark_never_uses_candle_extrema(prices, reason):
    with pytest.raises(ValueError, match=reason):
        value([receipt()], prices)


def test_model_adapter_ledger_reaches_account_snapshot_path():
    a = adapter()
    a.process_detail_bar(bar(low=89))
    result = value(a.ledger, [mark(0), {"ts_ms": 60000, "prices": {}}])
    assert result["valuation"]["curve"][-1]["equity_usdt"] == pytest.approx(979.62)
    assert len(result["closed_position_episodes"]) == 1


@pytest.mark.parametrize("field", ["leverage", "slippage_usdt"])
def test_account_rejects_multiplier_and_cost_double_subtraction(field):
    with pytest.raises(ValueError, match="REAPPLICATION"):
        value([receipt(**{field: 1})], [mark(0)])


def test_ledger_ending_after_snapshot_and_external_flow_rejected():
    with pytest.raises(ValueError, match="EXTENDS_AFTER"):
        value([receipt(ts_ms=1)], [mark(0)])
    with pytest.raises(ValueError, match="EXTERNAL_FLOW"):
        value(
            [
                {
                    "type": "DEPOSIT",
                    "event_id": "d",
                    "ts_ms": 0,
                    "source_ref": "fixture",
                    "amount_usdt": 10,
                }
            ],
            [mark(0)],
        )


def test_funding_needs_held_symbol_and_actual_settlement_timestamp():
    row = {
        "type": "FUNDING",
        "event_id": "f",
        "ts_ms": 0,
        "settlement_ts_ms": 0,
        "symbol": "X",
        "source_ref": "fixture",
        "amount_usdt": 1,
    }
    with pytest.raises(ValueError, match="WITHOUT_HELD_POSITION"):
        value([row], [mark(0)])
    with pytest.raises(ValueError, match="SETTLEMENT_CLOCK"):
        value([receipt(), {**row, "settlement_ts_ms": 1}], [mark(0)])


def test_account_inputs_are_not_mutated():
    rows, marks = [receipt()], [mark(0)]
    saved = copy.deepcopy((rows, marks))
    value(rows, marks)
    assert (rows, marks) == saved


def test_observed_entry_inside_minute_never_uses_preentry_low():
    a = observed()
    a.record_fill(receipt(ts_ms=30000, available_ts_ms=30000, qty_base=2))
    assert (
        a.process_detail_bar(bar(low=80))["status"]
        == "ENTRY_UPDATED_STOP_ORDER_AMBIGUOUS"
    )
    assert len(a.ledger) == 1


def test_sample_external_flow_is_not_silently_zeroed():
    with pytest.raises(ValueError, match="EXTERNAL_FLOW"):
        value([receipt()], [{**mark(0), "external_flow_usdt": 100}])


def test_no_receipts_is_not_observed_fill_claim():
    result = observed().finish()
    assert result["observed_fill_receipts_supplied"] is False
    assert result["receipt_authenticity_verified"] is False


@pytest.mark.parametrize("tf", [15, 30])
def test_callback_clock_and_nonloosening_stop(tf):
    a = DetailExecutionAdapter(
        order(decision_tf_min=tf),
        fill_model=MODEL,
        fee_rate=0,
        exit_update=lambda p, b, h: {"next_stop": 80},
    )
    for i in range(tf):
        a.process_detail_bar(bar(i * 60000))
    d = bar(0, close_ts_ms=tf * 60000, available_ts_ms=tf * 60000)
    a.process_decision_bar(d, [d])
    a.process_detail_bar(bar(tf * 60000))
    assert a.stop == 90 and a.state == "ACTIVE"
    assert a.position["hold_bars"] == 1


def test_decision_segment_mismatch_rejected():
    a = adapter()
    for i in range(15):
        a.process_detail_bar(bar(i * 60000))
    d = bar(0, close_ts_ms=900000, available_ts_ms=900000, segment_id="other")
    with pytest.raises(ValueError, match="SEGMENT_MISMATCH"):
        a.process_decision_bar(d, [d])


def test_explicit_entry_callback_can_reject_without_fill():
    a = DetailExecutionAdapter(
        order(),
        fill_model=MODEL,
        fee_rate=0,
        entry_update=lambda s, p: {"reject": True},
    )
    with pytest.raises(ValueError, match="ENTRY_CALLBACK_REJECTED"):
        a.process_detail_bar(bar())
    assert a.ledger == [] and a.position is None


def test_nonfinite_fill_price_cannot_mutate_position():
    a = observed()
    with pytest.raises(ValueError, match="FLOAT_RANGE"):
        a.record_fill(receipt(fill_price="1e400"))
    assert a.ledger == [] and a.position is None


def test_interval_entry_exact_expiry_is_unresolved_not_fabricated_earlier_fill():
    a = adapter(order_kind="STOP_MARKET", trigger_price=105, expires_ts_ms=60000)
    assert (
        a.process_detail_bar(bar(high=106))["status"]
        == "ENTRY_TIME_INTERVAL_OVERLAPS_EXPIRY"
    )
    assert a.ledger == []


def test_partial_next_open_invalidation_retains_exposure():
    a = observed()
    a.record_fill(receipt())
    assert (
        a.process_detail_bar(bar(open=89, low=88, high=101, close=90))["status"]
        == "STOP_RECEIPT_REQUIRED"
    )
    assert a.position["remaining_qty_base"] == "1"
    assert a.state == "UNRESOLVED"


def test_observed_intraminute_entry_excludes_preentry_excursion():
    a = observed()
    a.record_fill(receipt(ts_ms=30000, available_ts_ms=30000, qty_base=2))
    a.process_detail_bar(bar(high=200))
    assert a.position["mfe_R"] == 0
    assert a.position["mae_R"] == 0


def test_decision_and_history_symbol_binding():
    a = adapter()
    for i in range(15):
        a.process_detail_bar(bar(i * 60000))
    d = bar(0, close_ts_ms=900000, available_ts_ms=900000)
    with pytest.raises(ValueError, match="SYMBOL_MISMATCH"):
        a.process_decision_bar({**d, "symbol": "OTHER"}, [d])
    with pytest.raises(ValueError, match="HISTORY_SYMBOL_MISMATCH"):
        a.process_decision_bar(d, [{**d, "symbol": "OTHER"}])


def test_none_stop_callback_leaves_previous_stop():
    a = DetailExecutionAdapter(
        order(),
        fill_model=MODEL,
        fee_rate=0,
        exit_update=lambda p, b, h: {"next_stop": None},
    )
    for i in range(15):
        a.process_detail_bar(bar(i * 60000))
    d = bar(0, close_ts_ms=900000, available_ts_ms=900000)
    a.process_decision_bar(d, [d])
    a.process_detail_bar(bar(900000))
    assert a.stop == 90 and a.state == "ACTIVE"


@pytest.mark.parametrize(
    "bad", [{"side": -1}, {"identity": "other"}, {"position_episode_id": "other"}]
)
def test_explicit_fill_binding_mismatch_rejected(bad):
    a = observed()
    with pytest.raises(ValueError, match="FILL_BINDING_MISMATCH"):
        a.record_fill(receipt(**bad))
    assert a.position is None and a.ledger == []


def test_bad_callback_does_not_commit_decision_state():
    a = DetailExecutionAdapter(
        order(),
        fill_model=MODEL,
        fee_rate=0,
        exit_update=lambda p, b, h: {"next_stop": -1},
    )
    for i in range(15):
        a.process_detail_bar(bar(i * 60000))
    d = bar(0, close_ts_ms=900000, available_ts_ms=900000)
    with pytest.raises(ValueError, match="INVALID_NUMBER"):
        a.process_decision_bar(d, [d])
    assert a.position["hold_bars"] == 0 and a.last_decision == -1
    assert a.pending_update is None


def test_truthy_exit_text_is_rejected_without_state_commit():
    a = DetailExecutionAdapter(
        order(),
        fill_model=MODEL,
        fee_rate=0,
        exit_update=lambda p, b, h: {"exit_next_open": "false"},
    )
    for i in range(15):
        a.process_detail_bar(bar(i * 60000))
    d = bar(0, close_ts_ms=900000, available_ts_ms=900000)
    with pytest.raises(ValueError, match="MUST_BE_BOOL"):
        a.process_decision_bar(d, [d])
    assert a.position["hold_bars"] == 0 and a.last_decision == -1


def test_impossible_receipt_clock_rejected_but_delayed_retrospective_receipt_allowed():
    with pytest.raises(ValueError, match="AVAILABLE_BEFORE_EVENT"):
        value([receipt(ts_ms=1, available_ts_ms=0)], [mark(1)])
    result = value([receipt(ts_ms=1, available_ts_ms=2)], [mark(1)])
    assert (
        result["clock_semantics"] == "RETROSPECTIVE_EVENT_TIME_NOT_ASOF_CAUSAL_FEATURE"
    )


@pytest.mark.parametrize("unit", [{"quantity_unit": "CONTRACTS"}, {"cash_unit": "BTC"}])
def test_explicit_wrong_ledger_units_rejected(unit):
    with pytest.raises(ValueError, match="LEDGER_UNIT_MISMATCH"):
        value([receipt(**unit)], [mark(0)])
