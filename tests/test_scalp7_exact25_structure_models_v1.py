"""Synthetic complete Anti model and raw producer execution checks; no FULL."""

from __future__ import annotations

import copy

import pandas as pd
import pytest

from backend.research.rebuild import scalp7_exact25_structure_models_v1 as m
from backend.research.rebuild.scalp7_exact25_execution_v1 import (
    MODEL,
    DetailExecutionAdapter,
    account_snapshots_from_ledger,
)

M = 60000
TF = 30 * M


def bars(candles, start=0):
    return pd.DataFrame(
        [
            {
                "open_ts_ms": start + i * TF,
                "close_ts_ms": start + (i + 1) * TF,
                "available_ts_ms": start + (i + 1) * TF,
                "segment_id": "a",
                "open": o,
                "high": h,
                "low": low,
                "close": c,
                "volume": 100.0,
            }
            for i, (o, h, low, c) in enumerate(candles)
        ]
    )


def source_bars():
    return bars(
        [(10, 10.1, 9.9, 10)] * 30
        + [(10, 14, 10, 13.8), (13.8, 13.9, 13, 13.2), (13.2, 14.2, 13.1, 14)]
    )


def evaluated():
    return m.evaluate(m.MODEL_ID, {"X": source_bars()}, {"tick_size": 0.01})


def position(side=1):
    return {
        "signal": {
            "model_id": m.MODEL_ID,
            "lifecycle_id": m.LIFECYCLE_ID,
            "tick_size": 0.01,
        },
        "side": side,
        "entry_ts_ms": 0,
        "stop_price": 12 if side == 1 else 20,
    }


def test_original_six_rows_remain_distinct_one_model_selected():
    rows = m.catalog()
    assert set(rows) == {
        "ema_ribbon_scalp",
        "keltner_trend",
        "pivot_reversal",
        "range_fade",
        "scalp_snap",
        "vol_spike_fade",
    }
    assert [r["model_id"] for r in rows.values() if "model_id" in r] == [m.MODEL_ID]
    assert "PARENT_PRESERVED" in rows["keltner_trend"]["status"]


def test_raw_anti_producer_completes_order_without_retroactive_fill():
    out = evaluated()
    assert (
        out["complete_configured_research_model"]
        and not out["exact_source_reproduction"]
    )
    assert not out["economic_execution_performed"]
    assert len(out["plans"]) == 1
    plan = out["plans"][0]
    assert plan["protective_stop"] == pytest.approx(12.99)
    assert plan["reference_entry_price"] == 14
    assert plan["order_active_ts_ms"] == plan["feature_available_ts_ms"] + M
    assert plan["expires_ts_ms"] == plan["order_active_ts_ms"] + M
    assert plan["order_kind"] == "NEXT_OPEN"
    assert "qty_base" not in plan and "identity" not in plan
    assert all(rule["origin"] != "SOURCE_DIRECT" for rule in out["rules"])


def test_all_raw_prefixes_causal():
    x, full = source_bars(), evaluated()
    for n in range(1, len(x) + 1):
        out = m.evaluate(m.MODEL_ID, {"X": x.iloc[:n]}, {"tick_size": 0.01})
        ts = int(x.iloc[n - 1]["available_ts_ms"])
        assert out["plans"] == [
            p for p in full["plans"] if p["feature_available_ts_ms"] <= ts
        ]


@pytest.mark.parametrize(
    "key,value",
    [
        ("timeframe_min", 15),
        ("flag_max_bars", 10),
        ("risk_fraction", 0.01),
        ("max_hold_bars", 10),
        ("take_profit_r", 2),
        ("mode_id", "HG_1997_CONDITIONAL"),
    ],
)
def test_frozen_profile_rejects_retune(key, value):
    with pytest.raises(ValueError, match="CANNOT_BE_RETUNED"):
        m.evaluate(m.MODEL_ID, {"X": source_bars()}, {"tick_size": 0.01, key: value})


@pytest.mark.parametrize("tick", [None, 0, -1, True, float("inf"), float("nan")])
def test_instrument_tick_must_be_explicit_finite(tick):
    with pytest.raises(ValueError, match="POSITIVE_NUMBER"):
        m.profile(tick_size=tick)


def test_tick_map_binds_symbols_and_does_not_change_geometry():
    out = m.evaluate(
        m.MODEL_ID,
        {"X": source_bars(), "Y": source_bars()},
        {"tick_sizes": {"X": 0.01, "Y": 0.1}},
    )
    assert [p["symbol"] for p in out["plans"]] == ["X", "Y"]
    assert [p["protective_stop"] for p in out["plans"]] == pytest.approx([12.99, 12.9])
    with pytest.raises(ValueError, match="TICK_SYMBOL_BINDING"):
        m.evaluate(m.MODEL_ID, {"X": source_bars()}, {"tick_sizes": {"Y": 0.01}})


@pytest.mark.parametrize("by_segment", [False, True])
def test_gap_cannot_inherit_flag(by_segment):
    x = source_bars()
    if by_segment:
        x.loc[len(x) - 1, "segment_id"] = "b"
    else:
        for key in ("open_ts_ms", "close_ts_ms", "available_ts_ms"):
            x.loc[len(x) - 1, key] += TF
    assert not m.evaluate(m.MODEL_ID, {"X": x}, {"tick_size": 0.01})["plans"]


def test_inclusive_close_requires_explicit_upstream_normalization():
    x = source_bars()
    x["close_ts_ms"] -= 1
    with pytest.raises(ValueError, match="EXCLUSIVE_CANONICAL"):
        m.evaluate(m.MODEL_ID, {"X": x}, {"tick_size": 0.01})


def test_size_uses_causal_reference_and_both_finite_caps():
    out = evaluated()
    plan = out["plans"][0]
    order = m.create_order(plan, 10000, "frozen-model", out["rule_digest"])
    assert order["qty_base"] == pytest.approx(25 / 1.01)
    assert order["qty_base"] * 14 <= 2500
    close_stop = copy.deepcopy(plan)
    close_stop["protective_stop"] = 13.999
    capped = m.create_order(close_stop, 10000, "frozen-model", out["rule_digest"])
    assert capped["qty_base"] == pytest.approx(2500 / 14)
    assert plan["signal"]["qty_base"] is None


@pytest.mark.parametrize("capital", [0, -1, True, float("nan"), float("inf")])
def test_invalid_capital_rejected(capital):
    out = evaluated()
    with pytest.raises(ValueError, match="POSITIVE_NUMBER"):
        m.create_order(out["plans"][0], capital, "frozen", out["rule_digest"])


def test_size_policy_and_rule_digest_cannot_be_swapped():
    out = evaluated()
    plan = copy.deepcopy(out["plans"][0])
    plan["quantity_policy"]["risk_fraction"] = 0.5
    with pytest.raises(ValueError, match="QUANTITY_POLICY"):
        m.create_order(plan, 1000, "frozen", out["rule_digest"])
    with pytest.raises(ValueError, match="RULE_DIGEST"):
        m.create_order(out["plans"][0], 1000, "frozen", "different")


def test_new_counter_pivot_waits_for_right_bar_and_tightens_only():
    x = bars([(15, 16, 14.5, 15.5), (15.5, 16, 14.4, 15), (15, 16, 14.7, 15.6)])
    rows = x.to_dict("records")
    assert "next_stop" not in m.exit_update(position(), rows[1], x.iloc[:2])
    assert m.exit_update(position(), rows[2], x)["next_stop"] == pytest.approx(14.39)
    pos = position()
    pos["stop_price"] = 14.6
    assert "next_stop" not in m.exit_update(pos, rows[2], x)


def test_short_counter_pivot_is_symmetric():
    x = bars([(15, 16, 14, 15), (15, 16.5, 14, 15), (15, 16.2, 14, 15)])
    assert m.exit_update(position(-1), x.iloc[-1].to_dict(), x)[
        "next_stop"
    ] == pytest.approx(16.51)


def test_equal_lows_are_not_strict_pivot_and_preentry_low_cannot_trail():
    x = bars([(15, 16, 14, 15), (15, 16, 14, 15), (15, 16, 14.5, 15)])
    assert "next_stop" not in m.exit_update(position(), x.iloc[-1].to_dict(), x)
    x.loc[1, "low"] = 13.5
    pos = position()
    pos["entry_ts_ms"] = TF
    assert "next_stop" not in m.exit_update(pos, x.iloc[-1].to_dict(), x)


def test_future_and_cross_gap_exit_history_rejected():
    x = bars([(15, 16, 14, 15), (15, 16, 13.5, 15), (15, 16, 14.5, 15)])
    with pytest.raises(ValueError, match="CONTAINS_FUTURE"):
        m.exit_update(position(), x.iloc[1].to_dict(), x)
    x.loc[2, "segment_id"] = "b"
    with pytest.raises(ValueError, match="GAP_UNRESOLVED"):
        m.exit_update(position(), x.iloc[-1].to_dict(), x)


def minute(opened, o, h, low, c):
    return {
        "open_ts_ms": opened,
        "close_ts_ms": opened + M,
        "available_ts_ms": opened + M,
        "segment_id": "a",
        "symbol": "X",
        "open": o,
        "high": h,
        "low": low,
        "close": c,
    }


def test_raw_producer_to_adapter_trailing_fill_and_account():
    out = evaluated()
    order = m.create_order(out["plans"][0], 10000, "anti-synthetic", out["rule_digest"])
    adapter = DetailExecutionAdapter(
        order, fill_model=MODEL, fee_rate=0.001, exit_update=m.exit_update
    )
    active = order["order_active_ts_ms"]
    boundary = (active // TF + 1) * TF
    for opened in range(active, boundary, M):
        adapter.process_detail_bar(minute(opened, 14, 14.6, 14, 14.6))
    candles = [(14.6, 15.5, 14.5, 15), (15, 15.3, 14.4, 14.9), (14.9, 15.6, 14.7, 15.4)]
    decisions = bars(candles, start=boundary)
    decisions["symbol"] = "X"
    for i, row in enumerate(decisions.to_dict("records")):
        adapter.process_detail_bar(
            minute(
                row["open_ts_ms"], row["open"], row["high"], row["low"], row["close"]
            )
        )
        for opened in range(row["open_ts_ms"] + M, row["close_ts_ms"], M):
            adapter.process_detail_bar(
                minute(opened, row["close"], row["close"], row["close"], row["close"])
            )
        adapter.process_decision_bar(row, decisions.iloc[: i + 1])
    closed_at = boundary + 3 * TF
    adapter.process_detail_bar(minute(closed_at, 15.4, 15.4, 14.3, 14.4))
    result = adapter.finish()
    assert result["state"] == "CLOSED"
    assert [r["effect"] for r in result["ledger"]] == ["OPEN", "CLOSE"]
    assert float(result["ledger"][1]["fill_price"]) == pytest.approx(14.39)
    assert all(
        r["execution_evidence"] == "MODEL_NOT_OBSERVED" for r in result["ledger"]
    )
    # Exact synchronized price witnesses are model last prices, never alleged mark.
    snapshots = [
        {
            "ts_ms": closed_at + M,
            "available_ts_ms": closed_at + M,
            "prices": {
                "X": {
                    "price": 14.4,
                    "price_basis": "LAST_PRICE",
                    "ts_ms": closed_at + M,
                    "source_ref": "SYNTHETIC_LAST_PRICE",
                }
            },
            "source_ref": "SYNTHETIC_LAST_PRICE",
        }
    ]
    account = account_snapshots_from_ledger(
        result["ledger"],
        snapshots,
        initial_cash_usdt=10000,
        start_ts_ms=active,
        price_basis="LAST_PRICE",
    )
    assert account
    qty = order["qty_base"]
    expected_net = qty * (14.39 - 14) - qty * (14.39 + 14) * 0.001
    assert expected_net > 0
    assert account["valuation"]["curve"][-1]["equity_usdt"] == pytest.approx(
        10000 + expected_net
    )


def test_no_terminal_liquidation_or_default_max_hold():
    out = evaluated()
    order = m.create_order(out["plans"][0], 10000, "anti-end", out["rule_digest"])
    assert "max_hold_bars" not in order and "take_profit_r" not in order
    adapter = DetailExecutionAdapter(
        order, fill_model=MODEL, fee_rate=0.001, exit_update=m.exit_update
    )
    adapter.process_detail_bar(minute(order["order_active_ts_ms"], 14, 14.1, 13.9, 14))
    result = adapter.finish()
    assert result["state"] == "UNRESOLVED"
    assert [r["effect"] for r in result["ledger"]] == ["OPEN"]


def test_rule_identity_does_not_depend_on_checkout_absolute_path(tmp_path, monkeypatch):
    from pathlib import Path

    original = evaluated()
    copy_path = tmp_path / "scalp7_exact25_structure_v1.py"
    copy_path.write_bytes(Path(m.source.__file__).read_bytes())
    monkeypatch.setattr(m.source, "__file__", str(copy_path))
    other_checkout = evaluated()
    assert other_checkout["rule_digest"] == original["rule_digest"]
    assert other_checkout["plans"] == original["plans"]


def test_non_aligned_30m_source_cannot_create_unexecutable_decision_clock():
    x = source_bars()
    for key in ("open_ts_ms", "close_ts_ms", "available_ts_ms"):
        x[key] += M
    with pytest.raises(ValueError, match="EXCLUSIVE_CANONICAL"):
        m.evaluate(m.MODEL_ID, {"X": x}, {"tick_size": 0.01})


def test_common_runner_envelope_keeps_policy_complete_and_data_readiness_separate():
    x = source_bars()
    compiled = m.compile_model(m.MODEL_ID, {"X": x}, {"tick_size": 0.01})
    assert compiled["complete"] and compiled["execution_mode"] == "DETAIL_CONDITIONAL"
    assert compiled["genuine_economic_readiness"] == "CONDITIONAL_DATA_BLOCKED"
    assert not compiled["genuine_tick_receipt_verified"]
    assert compiled["plans"] == evaluated()["plans"]
    assert set(compiled["decisions"]["X"]["symbol"]) == {"X"}
    compiled["decisions"]["X"].loc[0, "close"] = 999
    assert x.loc[0, "close"] == 10
