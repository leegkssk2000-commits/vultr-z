"""Hand constructed candles only; no genuine history or economic execution."""

from copy import deepcopy

import pandas as pd
import pytest

from backend.research.rebuild import scalp7_exact25_execution_v1 as execution
from backend.research.rebuild import scalp7_exact25_reference_models_v1 as models

DAY = models.DAY
MINUTE = 60_000
SYMBOL = "TEST-USDT"


def bars(values, start=0, tf=30):
    step = tf * MINUTE
    return pd.DataFrame(
        [
            {
                "open_ts_ms": start + i * step,
                "close_ts_ms": start + (i + 1) * step,
                "available_ts_ms": start + (i + 1) * step,
                "segment_id": "fixture",
                "open": o,
                "high": h,
                "low": low,
                "close": c,
                "symbol": SYMBOL,
            }
            for i, (o, h, low, c) in enumerate(values)
        ]
    )


def sr_frame():
    return pd.concat(
        [
            bars([(100, 110, 90, 100)] * 48),
            bars(
                [(100, 112, 99, 111), (111, 113, 109, 112), (112, 113, 107, 108)], DAY
            ),
        ],
        ignore_index=True,
    )


def compile_sr(frame=None):
    return models.compile_model(
        models.SR, {SYMBOL: sr_frame() if frame is None else frame}, {}
    )


def soup_frame():
    values = [(100, 101, 95, 100)] * (20 * 96)
    values[3 * 96] = (100, 101, 90, 100)
    values.append((95, 96, 89, 90))
    return bars(values, tf=15)


def tick_config():
    return {
        "tick_evidence": {
            SYMBOL: {
                "tick_size": 0.1,
                "available_ts_ms": 0,
                "valid_from_ms": 0,
                "source_ref": "SYNTHETIC_TEST_ONLY_NOT_A_MARKET_RECEIPT",
                "source_receipt_sha256": "a" * 64,
            }
        }
    }


def test_registry_three_research_models_and_seven_dispositions():
    assert set(models.catalog()) == {models.SR_CONTROL, models.SR, models.SOUP}
    assert len(models.dispositions()) == 7
    assert all(not x["source_exact"] for x in models.catalog().values())
    assert models.dispositions()["alpha_combo"]["status"] == "FUSION_BLOCKED"


def test_real_frozen_box_producer_compiles_complete_order_plan():
    result = compile_sr()
    assert result["complete"] and result["execution_mode"] == "DETAIL_CONDITIONAL"
    assert result["economics"] == "NOT_RUN"
    assert len(result["plans"]) == 1
    plan = result["plans"][0]
    assert plan["reference_edge"] == 110 and plan["protective_stop"] == 90
    assert plan["order_active_ts_ms"] == DAY + 60 * MINUTE
    assert plan["expires_ts_ms"] == DAY + 90 * MINUTE
    assert plan["reference_entry_price"] == 112
    assert plan["producer_rule_digest"] and plan["lifecycle_gap"] is None


def test_breakout_alone_is_not_retest_entry_and_future_suffix_cannot_repaint():
    frame = sr_frame()
    assert not compile_sr(frame.iloc[:49])["plans"]
    prefix = compile_sr(frame.iloc[:50])["plans"]
    assert prefix == compile_sr(frame)["plans"]
    frame.loc[50, ["high", "close"]] = [999, 999]
    assert prefix == compile_sr(frame)["plans"]


def test_missing_or_segment_broken_reference_not_filled_or_shortened():
    frame = sr_frame().drop(index=17)
    assert not compile_sr(frame)["plans"]
    frame = sr_frame()
    frame.loc[17:, "segment_id"] = "gap"
    assert not compile_sr(frame)["plans"]


def test_delayed_reference_or_intraday_gap_blocks():
    frame = sr_frame()
    frame.loc[47, "available_ts_ms"] = DAY + MINUTE
    assert not compile_sr(frame)["plans"]
    frame = sr_frame().drop(index=48)
    assert not compile_sr(frame)["plans"]


def test_late_utc_session_setup_does_not_enter_reserved_exit_interval():
    prior = [(100, 110, 90, 100)] * 48
    current = [(100, 109, 91, 100)] * 44 + [(100, 112, 99, 111), (111, 113, 109, 112)]
    result = compile_sr(bars(prior + current))
    assert not result["plans"]
    assert any(
        x["status"] == "SESSION_CUTOFF_OR_INTRAMINUTE_ACTIVATION"
        for x in result["events"]
        if "status" in x
    )


def test_source_soup_daily_20_age_and_tick_completion():
    result = models.compile_model(models.SOUP, {SYMBOL: soup_frame()}, tick_config())
    assert len(result["plans"]) == 1
    plan = result["plans"][0]
    assert plan["trigger_price"] == pytest.approx(90.5)
    assert plan["protective_stop"] == pytest.approx(88.9)
    assert plan["reference_edge"] == 90
    assert plan["order_kind"] == "STOP_MARKET"
    assert not result["tick_receipt_authenticity_verified_by_this_module"]


@pytest.mark.parametrize("mutation", ["missing", "late", "invalid_hash"])
def test_soup_tick_receipt_and_pit_required(mutation):
    config = tick_config()
    if mutation == "missing":
        config = {}
    elif mutation == "late":
        config["tick_evidence"][SYMBOL]["available_ts_ms"] = 21 * DAY
    else:
        config["tick_evidence"][SYMBOL]["source_receipt_sha256"] = "wrong"
    if mutation == "invalid_hash":
        with pytest.raises(ValueError, match="TICK_SOURCE_RECEIPT"):
            models.compile_model(models.SOUP, {SYMBOL: soup_frame()}, config)
    else:
        result = models.compile_model(models.SOUP, {SYMBOL: soup_frame()}, config)
        assert not result["plans"]
        assert any(
            x.get("status") == "PIT_TICK_EVIDENCE_MISSING" for x in result["events"]
        )


def test_soup_missing_daily_bar_never_becomes_synthetic_twentieth_day():
    result = models.compile_model(
        models.SOUP, {SYMBOL: soup_frame().drop(index=100)}, tick_config()
    )
    assert not result["plans"]


def test_soup_most_recent_tied_low_too_young_blocks():
    frame = soup_frame()
    frame.loc[19 * 96, "low"] = 90
    assert not models.compile_model(models.SOUP, {SYMBOL: frame}, tick_config())[
        "plans"
    ]


def test_quantity_is_real_base_units_with_risk_and_notional_constraints():
    plan = compile_sr()["plans"][0]
    order = models.create_order(plan, 1000, "fixture-id", "digest")
    assert order["qty_base"] == pytest.approx(2.5 / 22)
    assert order["reserved_notional_usdt"] == 100
    assert order["planned_stop_risk_usdt"] == pytest.approx(2.5)
    assert order["signal"] == plan
    plan = deepcopy(plan)
    plan["protective_stop"] = 111.99
    assert models.create_order(plan, 1000, "fixture-id", "digest")[
        "qty_base"
    ] == pytest.approx(100 / 112)


@pytest.mark.parametrize("capital", [0, -1, float("nan"), float("inf"), True])
def test_invalid_capital_does_not_create_quantity(capital):
    with pytest.raises(ValueError):
        models.create_order(compile_sr()["plans"][0], capital, "fixture-id", "digest")


def test_unknown_config_cannot_silently_retune_frozen_lifecycle():
    with pytest.raises(ValueError, match="UNREGISTERED"):
        models.compile_model(models.SR, {SYMBOL: sr_frame()}, {"take_profit_r": 2})


def test_sr_exit_and_soup_trail_are_causal_explicit_completions():
    plan = compile_sr()["plans"][0]
    position = {"signal": plan, "side": 1, "entry_price": 112}
    bar = {
        "close_ts_ms": DAY + 90 * MINUTE,
        "available_ts_ms": DAY + 90 * MINUTE,
        "close": 109,
        "low": 108,
    }
    assert (
        models.exit_update(position, bar, [])["reason"]
        == "REFERENCE_RECOVERY_THESIS_FAILED"
    )
    bar.update(
        close_ts_ms=plan["liquidation_decision_close_ms"],
        available_ts_ms=plan["liquidation_decision_close_ms"],
    )
    assert (
        models.exit_update(position, bar, [])["reason"]
        == "DECLARED_UTC_SESSION_LIQUIDATION"
    )
    soup = models.compile_model(models.SOUP, {SYMBOL: soup_frame()}, tick_config())[
        "plans"
    ][0]
    position = {"signal": soup, "side": 1, "entry_price": 90.5}
    bar = {
        "close_ts_ms": 20 * DAY + 30 * MINUTE,
        "available_ts_ms": 20 * DAY + 30 * MINUTE,
        "close": 92,
        "low": 91,
    }
    assert models.exit_update(position, bar, [])["next_stop"] == pytest.approx(90.9)


def test_source_to_model_fill_lifecycle_and_account_snapshot_integration():
    compiled = compile_sr()
    plan = compiled["plans"][0]
    order = models.create_order(plan, 1000, "synthetic-sr-e2e", compiled["rule_digest"])
    adapter = execution.DetailExecutionAdapter(
        order,
        fill_model=execution.MODEL,
        fee_rate=0.0005,
        exit_update=models.exit_update,
    )
    start = plan["order_active_ts_ms"]
    for minute in range(30):
        values = (
            (112, 113, 112, 112)
            if minute == 0
            else ((112, 112, 107, 108) if minute == 29 else (112, 112, 112, 112))
        )
        row = bars([values], start + minute * MINUTE, tf=1).iloc[0].to_dict()
        adapter.process_detail_bar(row)
    decision = compiled["decisions"][SYMBOL].iloc[-1].to_dict()
    adapter.process_decision_bar(decision, compiled["decisions"][SYMBOL])
    final = bars([(108, 108, 108, 108)], start + 30 * MINUTE, tf=1).iloc[0].to_dict()
    adapter.process_detail_bar(final)
    result = adapter.finish()
    assert result["state"] == "CLOSED"
    assert [x["effect"] for x in result["ledger"]] == ["OPEN", "CLOSE"]
    assert all(
        x["execution_evidence"] == "MODEL_NOT_OBSERVED" for x in result["ledger"]
    )
    stamp = int(final["close_ts_ms"])
    account = execution.account_snapshots_from_ledger(
        result["ledger"],
        [
            {
                "ts_ms": stamp,
                "prices": {
                    SYMBOL: {
                        "price": 108,
                        "ts_ms": stamp,
                        "available_ts_ms": stamp,
                        "source_ref": "SYNTHETIC_LAST_PRICE",
                    }
                },
            }
        ],
        initial_cash_usdt=1000,
        start_ts_ms=start,
        price_basis="LAST_PRICE",
    )
    quantity = 2.5 / 22
    expected = 1000 - 4 * quantity - (112 + 108) * quantity * 0.0005
    assert account["valuation"]["curve"][-1]["equity_usdt"] == pytest.approx(expected)
    assert not result["economic_execution_performed"]


def test_sr_pair_changes_only_entry_confirmation_rule_and_timing():
    frame = sr_frame()
    control = models.compile_model(models.SR_CONTROL, {SYMBOL: frame}, {})
    child = models.compile_model(models.SR, {SYMBOL: frame}, {})
    assert len(control["plans"]) == len(child["plans"]) == 1
    p, c = control["plans"][0], child["plans"][0]
    assert p["order_active_ts_ms"] == DAY + 30 * MINUTE
    assert c["order_active_ts_ms"] == DAY + 60 * MINUTE
    for key in (
        "protective_stop",
        "reference_edge",
        "qty_policy",
        "session_end_ms",
        "liquidation_decision_close_ms",
        "order_kind",
    ):
        assert p[key] == c[key]
    old = {r["rule_id"]: r for r in control["rules"]}
    new = {r["rule_id"]: r for r in child["rules"]}
    assert {key for key in old if old[key] != new[key]} == {"entry_confirmation_axis"}
    assert (
        models.compile_model(models.SR_CONTROL, {SYMBOL: frame.iloc[:49]}, {})["plans"]
        == control["plans"]
    )


def test_matched_pair_short_uses_same_upper_edge_and_failure_lifecycle():
    frame = pd.concat(
        [
            bars([(100, 110, 90, 100)] * 48),
            bars([(100, 101, 88, 89), (89, 91, 87, 88)], DAY),
        ]
    )
    for model_id in (models.SR_CONTROL, models.SR):
        plan = models.compile_model(model_id, {SYMBOL: frame}, {})["plans"][0]
        assert plan["side"] == -1 and plan["protective_stop"] == 110
        assert plan["reference_edge"] == 90
        position = {"signal": plan, "side": -1, "entry_price": 88}
        row = {
            "close_ts_ms": DAY + 90 * MINUTE,
            "available_ts_ms": DAY + 90 * MINUTE,
            "close": 91,
            "low": 89,
        }
        assert models.exit_update(position, row, [])["exit_next_open"]


def test_boundary_exit_needs_actual_detail_and_never_synthetic_close():
    plan = compile_sr()["plans"][0]
    order = models.create_order(plan, 1000, "missing-tail-fixture", "digest")
    adapter = execution.DetailExecutionAdapter(
        order, fill_model=execution.MODEL, fee_rate=0, exit_update=models.exit_update
    )
    adapter.process_detail_bar(
        bars([(112, 112, 112, 112)], plan["order_active_ts_ms"], tf=1).iloc[0].to_dict()
    )
    result = adapter.finish()
    assert result["state"] == "UNRESOLVED"
    assert [r["effect"] for r in result["ledger"]] == ["OPEN"]
