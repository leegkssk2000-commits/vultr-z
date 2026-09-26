"""Independent Anti caller and causal lifecycle checks on fabricated bars."""

from copy import deepcopy

import pandas as pd
import pytest

from backend.research.rebuild import scalp7_exact25_structure_models_v1 as model

M = 60_000
TF = 30 * M


def raw():
    prices = [(10, 10.1, 9.9, 10)] * 30
    prices += [(10, 14, 10, 13.8), (13.8, 13.9, 13, 13.2), (13.2, 14.2, 13.1, 14)]
    return pd.DataFrame(
        [
            {
                "open_ts_ms": i * TF,
                "close_ts_ms": (i + 1) * TF,
                "available_ts_ms": (i + 1) * TF,
                "segment_id": "fixture",
                "open": o,
                "high": h,
                "low": low,
                "close": c,
                "volume": 1,
            }
            for i, (o, h, low, c) in enumerate(prices)
        ]
    )


def test_actual_frozen_producer_called_and_structural_stop_preserved(monkeypatch):
    original = model.source.evaluate
    calls = []

    def observe(strategy_id, frames, config):
        out = original(strategy_id, frames, config)
        calls.append((strategy_id, deepcopy(config), deepcopy(out["intents"])))
        return out

    monkeypatch.setattr(model.source, "evaluate", observe)
    result = model.evaluate(model.MODEL_ID, {"X": raw()}, {"tick_size": 0.01})
    assert len(calls) == 1 and calls[0][0] == "range_fade"
    assert calls[0][1]["mode_id"] == "ANTI_IMPULSE_CONTINUATION_DECLARED"
    assert len(calls[0][2]) == len(result["plans"]) == 1
    source_intent, plan = calls[0][2][0], result["plans"][0]
    assert plan["protective_stop"] == source_intent["protective_stop"] == 12.99
    assert plan["side"] == source_intent["side"] == 1
    assert plan["order_active_ts_ms"] > source_intent["feature_available_ts_ms"]


def test_plan_and_sizing_are_immutable_inputs_not_entry_price_rewrites():
    result = model.evaluate(model.MODEL_ID, {"X": raw()}, {"tick_size": 0.01})
    plan = result["plans"][0]
    saved = deepcopy(plan)
    order = model.create_order(plan, 1000, "review-identity", result["rule_digest"])
    assert plan == saved
    assert order["qty_base"] == pytest.approx(2.5 / (14 - 12.99))
    assert order["signal"]["known_risk_cash_usdt"] == pytest.approx(2.5)


def test_counter_pivot_entire_three_bar_window_must_be_after_entry():
    signal = {
        "model_id": model.MODEL_ID,
        "lifecycle_id": model.LIFECYCLE_ID,
        "tick_size": 0.01,
    }
    rows = [
        {
            "open_ts_ms": i * TF,
            "close_ts_ms": (i + 1) * TF,
            "available_ts_ms": (i + 1) * TF,
            "segment_id": "fixture",
            "open": 15,
            "high": 16,
            "low": low,
            "close": 15,
        }
        for i, low in enumerate([14, 13.5, 14.5])
    ]
    pos = {"signal": signal, "side": 1, "entry_ts_ms": M, "stop_price": 12}
    assert "next_stop" not in model.exit_update(pos, rows[-1], rows)
    pos["entry_ts_ms"] = 0
    assert model.exit_update(pos, rows[-1], rows)["next_stop"] == pytest.approx(13.49)


def test_delayed_right_witness_cannot_backdate_trailing_stop():
    signal = {
        "model_id": model.MODEL_ID,
        "lifecycle_id": model.LIFECYCLE_ID,
        "tick_size": 0.01,
    }
    rows = [
        {
            "open_ts_ms": i * TF,
            "close_ts_ms": (i + 1) * TF,
            "available_ts_ms": (i + 1) * TF,
            "segment_id": "fixture",
            "open": 15,
            "high": 16,
            "low": low,
            "close": 15,
        }
        for i, low in enumerate([14, 13.5, 14.5])
    ]
    rows[-1]["available_ts_ms"] += M
    bar = {**rows[-1], "available_ts_ms": rows[-1]["close_ts_ms"]}
    pos = {"signal": signal, "side": 1, "entry_ts_ms": 0, "stop_price": 12}
    with pytest.raises(ValueError, match="CONTAINS_FUTURE"):
        model.exit_update(pos, bar, rows)


def test_common_runner_envelope_preserves_tick_data_block():
    frame = raw()
    compiled = model.compile_model(model.MODEL_ID, {"X": frame}, {"tick_size": 0.01})
    assert compiled["complete"] is True
    assert compiled["execution_mode"] == "DETAIL_CONDITIONAL"
    assert "symbol" not in frame
    assert set(compiled["decisions"]["X"]["symbol"]) == {"X"}
    assert compiled["plans"]
    assert not compiled["genuine_tick_receipt_verified"]
