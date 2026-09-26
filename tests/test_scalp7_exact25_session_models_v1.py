"""Synthetic contract tests, never historical strategy economics."""

from decimal import Decimal

import pandas as pd
import pytest

from backend.research.rebuild.scalp7_exact25_execution_v1 import (
    account_snapshots_from_ledger,
)
from backend.research.rebuild.scalp7_exact25_session_models_v1 import (
    DAY,
    MINUTE,
    MODEL_ID,
    SessionTargetModel,
    model_spec,
    noise_config,
    noise_schedule,
    utc_sessions,
)


def frame(days=15):
    rows = []
    for i in range(days * 48):
        stamp = i * 30 * MINUTE
        close = 101 if i == 14 * 48 else 99 if i == 14 * 48 + 1 else 100
        rows.append(
            {
                "open_ts_ms": stamp,
                "close_ts_ms": stamp + 30 * MINUTE,
                "available_ts_ms": stamp + 30 * MINUTE,
                "segment_id": "s0",
                "open": 100,
                "high": max(100, close),
                "low": min(100, close),
                "close": close,
                "volume": 0,
            }
        )
    return pd.DataFrame(rows)


def scheduled():
    return noise_schedule({"X": frame()}, noise_config("X"))


def decision(offset=30, *, close=101, lower=100, upper=100, start=14 * DAY, **kw):
    return {
        "symbol": "X",
        "setup_ts_ms": start + offset * MINUTE,
        "feature_available_ts_ms": start + offset * MINUTE,
        "session_id": str(start),
        "session_open_ts_ms": start,
        "session_close_ts_ms": start + DAY,
        "session_open_price": 100,
        "session_complete_prefix": True,
        "eligible": True,
        "close": close,
        "upper": upper,
        "lower": lower,
        "source_ref": "synthetic_fixture",
        **kw,
    }


def model():
    return SessionTargetModel(noise_config("X"), 1000)


def receipt(order, price=101, fee="0.1", **kw):
    stamp = order["order_active_ts_ms"]
    return {
        "order_id": order["order_id"],
        "fill_id": order["order_id"] + ":fill",
        "symbol": "X",
        "effect": order["effect"],
        "side": order["side"],
        "position_episode_id": order["position_episode_id"],
        "ts_ms": stamp,
        "available_ts_ms": stamp + MINUTE,
        "qty_base": order["qty_base"],
        "fill_price": price,
        "fee_usdt": fee,
        "source_ref": "SYNTHETIC_MARKET_MODEL_FIXTURE",
        "execution_evidence": "MODEL_NOT_OBSERVED",
        "maker_taker": "TAKER",
        **kw,
    }


def opened():
    m = model()
    order = m.on_decision(decision())[0]
    m.record_fill(receipt(order))
    return m


def test_frozen_spec_alias_is_one_model_and_not_native_certification():
    spec = model_spec()
    assert spec["model_id"] == MODEL_ID and spec["aliases"] == ["session_bias"]
    assert spec["complete_configured_model"] is True
    assert spec["native_source_strategy_certified"] is False
    assert spec["generic_max_hold"] is None and spec["hard_intrabar_stop"] is None
    assert spec["new_full_runs"] == 0 and spec["authority"]["live"] == "BLOCKED"
    assert {r["origin"] for r in spec["rules"]} == {
        "SOURCE_DIRECT",
        "DECLARED_HYPOTHESIS",
    }


def test_real_price_producer_14_prior_sessions_zero_volume_allowed():
    rows = scheduled()
    assert len(rows) == 15 * 48
    assert not any(r["eligible"] for r in rows[: 14 * 48])
    assert all(r["eligible"] for r in rows[14 * 48 :])
    first = rows[14 * 48]
    assert first["upper"] == first["lower"] == 100
    assert first["session_open_price"] == 100
    m = model()
    assert m.on_decision(first)[0]["side"] == 1


def test_price_features_are_prefix_causal():
    f = frame()
    cut = 14 * 48 + 1
    prefix = noise_schedule({"X": f.iloc[:cut]}, noise_config("X"))
    full = noise_schedule({"X": f}, noise_config("X"))
    assert prefix == full[:cut]
    changed = f.copy()
    changed.loc[cut:, ["open", "high", "low", "close"]] = 10000
    assert noise_schedule({"X": changed}, noise_config("X"))[:cut] == prefix


@pytest.mark.parametrize("missing", [0, 300, 14 * 48 + 1])
def test_gap_not_filled_and_reference_incomplete(missing):
    f = frame().drop(index=missing)
    rows = noise_schedule({"X": f}, noise_config("X"))
    assert len(rows) == 719
    if missing < 14 * 48:
        assert not any(
            r["eligible"] for r in rows if r["session_open_ts_ms"] == 14 * DAY
        )
    else:
        later = [r for r in rows if r["setup_ts_ms"] > (missing + 1) * 30 * MINUTE]
        assert not any(r["eligible"] for r in later)


def test_absent_day_does_not_turn14_records_into14_consecutive_days():
    f = frame(17)
    f = f[(f.open_ts_ms < DAY) | (f.open_ts_ms >= 2 * DAY)]
    rows = noise_schedule({"X": f}, noise_config("X"))
    assert not any(r["eligible"] for r in rows if r["session_open_ts_ms"] == 14 * DAY)
    assert all(r["eligible"] for r in rows if r["session_open_ts_ms"] == 16 * DAY)


def test_prior_session_late_availability_blocks_new_day():
    f = frame()
    f.loc[f.open_ts_ms < 14 * DAY, "available_ts_ms"] += DAY
    with pytest.raises(ValueError, match="AVAILABILITY"):
        noise_schedule({"X": f}, noise_config("X"))


def test_gap_adjusted_boundaries_use_prior_session_close():
    f = frame()
    f.loc[14 * 48 - 1, ["close", "high"]] = 110
    row = noise_schedule({"X": f}, noise_config("X"))[14 * 48]
    assert row["upper"] == 110
    assert row["lower"] == 100


@pytest.mark.parametrize(
    "key,value",
    [
        ("timeframe_min", 15),
        ("noise_stop_mode", "CURRENT_BAND_VWAP"),
        ("qty_policy", "ATR"),
    ],
)
def test_undeclared_parameter_mutations_rejected(key, value):
    cfg = noise_config("X")
    cfg[key] = value
    with pytest.raises(ValueError, match="FIXED_NOISE"):
        SessionTargetModel(cfg, 1000)


def test_multi_symbol_pooling_rejected():
    with pytest.raises(ValueError, match="ONE_SYMBOL"):
        noise_schedule({"X": frame(), "Y": frame()}, noise_config("X"))


def test_fractional_session_open_quantity_not_entry_price_resized():
    m = model()
    order = m.on_decision(decision(session_open_price=300))[0]
    assert Decimal(order["qty_base"]) == Decimal(1000) / Decimal(300)
    m.record_fill(receipt(order, price=310))
    assert m.position["qty"] == Decimal(1000) / Decimal(300)
    assert m.cash == Decimal("999.9")


def test_no_intrabar_stop_or_current_band_exit():
    m = opened()
    assert m.on_decision(decision(60, close=100, lower=99, upper=102)) == []
    assert m.position["side"] == 1
    assert m.on_clock(14 * DAY + 75 * MINUTE) == []


def test_reversal_close_ack_then_new_open_no_instant_virtual_flip():
    m = opened()
    close_order = m.on_decision(decision(60, close=99))[0]
    assert close_order["effect"] == "CLOSE" and m.position["side"] == 1
    new_orders = m.record_fill(receipt(close_order, 99))
    assert m.position is None
    assert len(new_orders) == 1 and new_orders[0]["side"] == -1
    assert (
        new_orders[0]["order_active_ts_ms"]
        == close_order["order_active_ts_ms"] + MINUTE
    )
    m.record_fill(receipt(new_orders[0], 99))
    assert m.position["side"] == -1
    assert m.position["qty"] == 10


def test_eod_scheduled_flat_without_final_candle_signal():
    m = opened()
    order = m.on_clock(15 * DAY)[0]
    assert order["reason"] == "SCHEDULED_EOD"
    assert order["feature_available_ts_ms"] == 15 * DAY
    assert m.record_fill(receipt(order, 102)) == []
    assert m.finish()["state"] == "FLAT"


def test_eod_cancels_unfilled_entry_and_never_invents_fill():
    m = model()
    order = m.on_decision(decision(1410))[0]
    assert m.on_clock(15 * DAY) == []
    assert m.pending_orders == {} and m.ledger == []
    with pytest.raises(ValueError, match="CANCELLED"):
        m.record_fill(receipt(order))


def test_missing_eod_retains_ownership_unresolved():
    m = opened()
    assert m.on_clock(15 * DAY + MINUTE) == []
    assert m.state == "UNRESOLVED"
    assert m.position is not None and len(m.ledger) == 1
    assert m.on_decision(decision(start=15 * DAY)) == []


def test_gap_with_ownership_is_never_reset_flat():
    m = opened()
    m.mark_gap()
    assert m.finish()["state"] == "UNRESOLVED"
    assert m.finish()["unclosed_position"] is not None
    assert m.on_clock(15 * DAY) == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("qty_base", "1"),
        ("side", -1),
        ("effect", "CLOSE"),
        ("symbol", "Y"),
        ("fee_usdt", "-1"),
        ("execution_evidence", "TOUCH"),
    ],
)
def test_receipt_binding_rejection_does_not_mutate_state(field, value):
    m = model()
    order = m.on_decision(decision())[0]
    before = m.finish()
    with pytest.raises(ValueError):
        m.record_fill(receipt(order, **{field: value}))
    assert m.finish() == before


def test_duplicate_and_out_of_window_receipts_rejected():
    m = model()
    order = m.on_decision(decision())[0]
    with pytest.raises(ValueError, match="ACTIVATION"):
        m.record_fill(receipt(order, ts_ms=order["expires_ts_ms"]))
    fill = receipt(order)
    m.record_fill(fill)
    with pytest.raises(ValueError, match="UNKNOWN"):
        m.record_fill(fill)


def test_funding_is_signed_and_affects_next_session_quantity():
    m = opened()
    m.record_cash_event(
        {
            "type": "FUNDING",
            "event_id": "f0",
            "symbol": "X",
            "ts_ms": 14 * DAY + 45 * MINUTE,
            "available_ts_ms": 14 * DAY + 45 * MINUTE,
            "settlement_ts_ms": 14 * DAY + 45 * MINUTE,
            "amount_usdt": "-2",
            "source_ref": "synthetic_funding_fixture",
        }
    )
    close_order = m.on_clock(15 * DAY)[0]
    m.record_fill(receipt(close_order, 101))
    new_order = m.on_decision(decision(start=15 * DAY))[0]
    assert Decimal(new_order["qty_base"]) == Decimal("9.978")
    assert m.cash == Decimal("997.8")


def test_funding_without_position_or_unknown_provenance_rejected():
    m = model()
    with pytest.raises(ValueError, match="FUNDING"):
        m.record_cash_event(
            {
                "type": "FUNDING",
                "event_id": "f0",
                "symbol": "X",
                "ts_ms": 0,
                "available_ts_ms": 0,
                "settlement_ts_ms": 0,
                "amount_usdt": 2,
            }
        )


def test_synthetic_price_producer_to_reversal_fills_to_shared_account():
    rows = scheduled()
    m = model()
    first = m.on_decision(rows[14 * 48])[0]
    m.record_fill(receipt(first, 101))
    close = m.on_decision(rows[14 * 48 + 1])[0]
    short = m.record_fill(receipt(close, 99))[0]
    m.record_fill(receipt(short, 99))
    end = m.on_clock(15 * DAY)[0]
    m.record_fill(receipt(end, 98))
    report = m.finish()
    value = account_snapshots_from_ledger(
        report["ledger"],
        [
            {
                "ts_ms": 15 * DAY + MINUTE,
                "prices": {
                    "X": {
                        "ts_ms": 15 * DAY + MINUTE,
                        "price": 98,
                        "price_basis": "MARK_PRICE",
                        "source_ref": "synthetic_mark",
                    }
                },
            }
        ],
        initial_cash_usdt=1000,
        start_ts_ms=0,
        price_basis="MARK_PRICE",
    )
    assert report["cash_usdt"] == "989.6"
    assert value["snapshots"][-1]["realized_gross_cum_usdt"] == "-10"
    assert value["snapshots"][-1]["fees_cum_usdt"] == "0.4"
    assert value["unclosed_position_episodes"] == []
    assert len(value["closed_position_episodes"]) == 2
    assert value["input_execution_evidence"] == ["MODEL_NOT_OBSERVED"]


def test_source_alias_has_no_second_economic_identity():
    assert model_spec()["aliases"] == ["session_bias"]
    assert model_spec()["strategy_id"] == "trend_rider"


def test_calendar_attachment_preserves_gaps_prices_and_segments():
    f = frame().drop(index=42)
    x = utc_sessions(f)
    assert len(x) == len(f)
    assert x.open_ts_ms.tolist() == f.open_ts_ms.tolist()
    assert x.close.tolist() == f.close.tolist()
    assert x.segment_id.tolist() == f.segment_id.tolist()


def test_actual_entry_notional_can_exceed_source_session_start_notional():
    m = model()
    order = m.on_decision(decision())[0]
    m.record_fill(receipt(order, price=110))
    assert m.ledger[0]["entry_notional_usdt"] == "1100"
    assert m.finish()["max_entry_notional_equity_ratio"] == "1.1"
    assert m.finish()["broker_margin_liquidation"] == "UNKNOWN_NOT_SIMULATED"


def test_unresolved_report_json_serializable():
    import json

    m = opened()
    m.mark_gap()
    json.dumps(m.finish())


def test_late_funding_before_entry_rejected_without_cash_change():
    m = opened()
    before = m.cash
    with pytest.raises(ValueError, match="FUNDING"):
        m.record_cash_event(
            {
                "type": "FUNDING",
                "event_id": "retro",
                "symbol": "X",
                "ts_ms": 14 * DAY,
                "settlement_ts_ms": 14 * DAY,
                "available_ts_ms": 14 * DAY + 45 * MINUTE,
                "amount_usdt": "1",
                "source_ref": "synthetic_funding_fixture",
            }
        )
    assert m.cash == before


def test_portfolio_simultaneous_signals_keep_independent_capital_and_next_day_size():
    from backend.research.rebuild.scalp7_exact25_session_models_v1 import (
        NoisePortfolioTargetModel,
        noise_portfolio_config,
    )

    m = NoisePortfolioTargetModel(noise_portfolio_config(["X", "Y"]), 1000)
    x = m.on_decision(decision())[0]
    y = m.on_decision({**decision(), "symbol": "Y"})[0]
    assert Decimal(x["qty_base"]) == Decimal(y["qty_base"]) == 5
    m.record_fill(receipt(x, 101))
    m.record_fill(receipt(y, 101, symbol="Y"))
    closes = m.on_clock(15 * DAY)
    assert len(closes) == 2
    for order in closes:
        price = 99 if order["symbol"] == "X" else 102
        m.record_fill(receipt(order, price, symbol=order["symbol"]))
    report = m.finish()
    assert report["sleeves"]["X"]["cash_usdt"] == "489.8"
    assert report["sleeves"]["Y"]["cash_usdt"] == "504.8"
    new_x = m.on_decision(decision(start=15 * DAY))[0]
    new_y = m.on_decision({**decision(start=15 * DAY), "symbol": "Y"})[0]
    assert Decimal(new_x["qty_base"]) == Decimal("4.898")
    assert Decimal(new_y["qty_base"]) == Decimal("5.048")
    assert report["cash_usdt"] == "994.6"


def test_portfolio_requires_all_frozen_symbols_and_schedules_simultaneous_decisions():
    from backend.research.rebuild.scalp7_exact25_session_models_v1 import (
        noise_portfolio_config,
        noise_portfolio_schedule,
    )

    cfg = noise_portfolio_config(["Y", "X"])
    with pytest.raises(ValueError, match="ENTIRE_FROZEN"):
        noise_portfolio_schedule({"X": frame()}, cfg)
    schedule = noise_portfolio_schedule({"X": frame(), "Y": frame()}, cfg)
    assert len(schedule) == 2 * 720
    assert [r["symbol"] for r in schedule[:2]] == ["X", "Y"]
    assert (
        schedule[0]["feature_available_ts_ms"] == schedule[1]["feature_available_ts_ms"]
    )


def test_portfolio_gap_retains_affected_symbol_only_and_does_not_redistribute_cash():
    from backend.research.rebuild.scalp7_exact25_session_models_v1 import (
        NoisePortfolioTargetModel,
        noise_portfolio_config,
    )

    m = NoisePortfolioTargetModel(noise_portfolio_config(["X", "Y"]), 1000)
    x = m.on_decision(decision())[0]
    m.record_fill(receipt(x, 101))
    m.mark_gap("X_GAP", symbol="X")
    y = m.on_decision({**decision(), "symbol": "Y"})[0]
    assert Decimal(y["qty_base"]) == 5
    assert m.state == "UNRESOLVED"
    assert m.models["X"].state == "UNRESOLVED"
    assert m.models["Y"].state == "FLAT"
    assert m.finish()["unclosed_position"]["X"] is not None


def test_canonical_noise_portfolio_is_one_identity_across_six_symbols():
    from backend.research.rebuild.scalp7_exact25_session_models_v1 import (
        CANONICAL_SYMBOLS,
        PORTFOLIO_MODEL_ID,
        NoisePortfolioTargetModel,
        noise_portfolio_config,
        portfolio_spec,
    )

    config = noise_portfolio_config(CANONICAL_SYMBOLS)
    model = NoisePortfolioTargetModel(config, 6000)
    assert len(model.models) == 6
    assert all(m.cash == 1000 for m in model.models.values())
    assert model.identity == PORTFOLIO_MODEL_ID
    assert portfolio_spec()["aliases"] == ["session_bias"]
    assert config["fusion_classification"] == "SAME_MODEL_MULTI_SYMBOL_NOT_B_BY_B"
