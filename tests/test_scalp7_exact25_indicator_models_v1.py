"""Synthetic-only model closure checks; no genuine history or economics."""

import copy
from decimal import Decimal

import pandas as pd
import pytest

from backend.research.rebuild import scalp7_exact25_indicator_models_v1 as model
from backend.research.rebuild.scalp7_exact25_execution_v1 import (
    MODEL,
    DetailExecutionAdapter,
)


def fixture_frame():
    prices = [(100, 101, 99, 100)] * 10 + [
        (100, 111, 100, 110),
        (110, 115, 109, 114),
        (114, 114, 108, 111),
        (111, 116, 110, 115),
    ]
    return pd.DataFrame(
        [
            {
                "open_ts_ms": i * model.TF,
                "close_ts_ms": (i + 1) * model.TF,
                "available_ts_ms": (i + 1) * model.TF,
                "segment_id": "synthetic-0",
                "open": o,
                "high": h,
                "low": low,
                "close": c,
            }
            for i, (o, h, low, c) in enumerate(prices)
        ]
    )


def compile_frame(frame=None, profile=model.TRAIL):
    return model.compile_model(
        profile,
        {"SYNTHETIC": fixture_frame() if frame is None else frame},
        model.CONFIG,
    )


def plan_order(profile=model.TRAIL, capital=10000):
    result = compile_frame(profile=profile)
    plan = result["plans"][0]
    return model.create_order(
        plan, capital, "synthetic-identity", result["rule_digest"]
    )


def test_raw_price_sequence_produces_complete_declared_plan_without_volume():
    result = compile_frame()
    assert result["complete"] and not result["source_original"]
    assert len(result["plans"]) == 1
    plan = result["plans"][0]
    assert plan["protective_stop"] == 108
    assert plan["reference_entry_price"] == 115
    assert plan["order_active_ts_ms"] == 14 * model.TF
    assert plan["signal"]["flip_ts_ms"] < plan["signal"]["pullback_ts_ms"]
    assert plan["signal"]["pullback_ts_ms"] < plan["signal"]["confirmation_ts_ms"]
    assert result["new_full_authority"] is False


def test_profiles_share_entry_structure_and_size():
    one = plan_order(model.CONTROL)
    two = plan_order(model.TRAIL)
    for row in (one, two):
        row.pop("model_id")
        row.pop("rule_digest")
        row["signal"].pop("model_id")
    assert one == two


def test_appending_future_prices_does_not_rewrite_past_plans():
    frame = fixture_frame()
    extended = pd.concat(
        [
            frame,
            pd.DataFrame(
                [
                    dict(
                        open_ts_ms=14 * model.TF,
                        close_ts_ms=15 * model.TF,
                        available_ts_ms=15 * model.TF,
                        segment_id="synthetic-0",
                        open=115,
                        high=130,
                        low=90,
                        close=95,
                    )
                ]
            ),
        ],
        ignore_index=True,
    )
    assert compile_frame(extended)["plans"][:1] == compile_frame(frame)["plans"]


def test_flip_without_later_sequence_is_not_entry():
    assert compile_frame(fixture_frame().iloc[:11])["plans"] == []
    assert compile_frame(fixture_frame().iloc[:13])["plans"] == []


@pytest.mark.parametrize("gap_kind", ["physical", "segment"])
def test_gap_discards_pending_pattern(gap_kind):
    frame = fixture_frame()
    if gap_kind == "physical":
        frame = frame.drop(index=12)
    else:
        frame.loc[12:, "segment_id"] = "synthetic-1"
    assert compile_frame(frame)["plans"] == []


def test_future_or_unknown_volume_cannot_change_price_model():
    frame = fixture_frame()
    frame["volume"] = float("nan")
    frame["volume_unit"] = "UNKNOWN"
    result = compile_frame(frame)
    assert result["plans"] == compile_frame()["plans"]
    assert "volume" not in result["decisions"]["SYNTHETIC"].columns


def test_delayed_knowledge_defers_activation_and_cannot_cross_session_end():
    frame = fixture_frame()
    frame.loc[12, "available_ts_ms"] = 14 * model.TF + 1
    plan = compile_frame(frame)["plans"][0]
    assert plan["feature_available_ts_ms"] == 14 * model.TF + 1
    assert plan["order_active_ts_ms"] == 14 * model.TF + model.MINUTE
    frame.loc[12, "available_ts_ms"] = model.DAY
    assert compile_frame(frame)["plans"] == []


def test_utc_day_change_cancels_previous_day_setup():
    frame = fixture_frame()
    for key in ("open_ts_ms", "close_ts_ms", "available_ts_ms"):
        frame[key] += 35 * model.TF
    assert compile_frame(frame)["plans"] == []


@pytest.mark.parametrize("capital", [0, -1, True, float("nan"), float("inf"), "1e1000"])
def test_invalid_available_capital_rejected(capital):
    with pytest.raises(ValueError):
        plan_order(capital=capital)


def test_size_uses_known_capital_and_rejects_adverse_fill_gap():
    order = plan_order(capital=10000)
    quantity = float(order["qty_base"])
    assert quantity * 7 == pytest.approx(25)
    assert quantity * 115 <= 2500
    assert model.entry_update(order["signal"], 115) == {"stop_price": 108}
    assert model.entry_update(order["signal"], 116)["reject"]
    assert model.entry_update(order["signal"], 108)["reject"]
    assert model.entry_update(order["signal"], 114) == {"stop_price": 108}


def test_notional_cap_applies_when_structural_stop_is_close():
    result = compile_frame()
    plan = result["plans"][0]
    plan["protective_stop"] = 114.99
    plan["signal"]["structural_stop"] = 114.99
    order = model.create_order(plan, 10000, "test", result["rule_digest"])
    assert float(order["qty_base"]) * 115 == pytest.approx(2500)
    assert model.entry_update(order["signal"], 115.01)["reject"]


def position_bar(profile=model.TRAIL):
    order = plan_order(profile)
    position = {"signal": order["signal"], "side": 1, "stop_price": 108}
    bar = {
        "available_ts_ms": 15 * model.TF,
        "close_ts_ms": 15 * model.TF,
        "st_available_ts_ms": 15 * model.TF,
        "st_direction": 1,
        "st_line": 110,
    }
    return position, bar


def test_one_changed_lifecycle_axis_and_monotonic_stop():
    control, bar = position_bar(model.CONTROL)
    child, _ = position_bar(model.TRAIL)
    assert model.exit_update(control, bar, []) == {}
    assert model.exit_update(child, bar, [])["next_stop"] == 110
    bar["st_line"] = 100
    assert model.exit_update(child, bar, [])["next_stop"] == 108


@pytest.mark.parametrize("profile", list(model.MODELS))
def test_flip_and_session_exit_are_identical(profile):
    position, bar = position_bar(profile)
    bar["st_direction"] = -1
    assert (
        model.exit_update(position, bar, [])["reason"]
        == "COMPLETED_DIRECTION_INVALIDATION"
    )
    bar["close_ts_ms"] = model.DAY
    bar["available_ts_ms"] = model.DAY
    bar["st_available_ts_ms"] = model.DAY
    assert model.exit_update(position, bar, [])["reason"] == "DECLARED_UTC_2330_FLATTEN"


def test_future_band_is_never_used():
    position, bar = position_bar()
    bar["st_available_ts_ms"] += 1
    with pytest.raises(ValueError, match="FUTURE_BAND"):
        model.exit_update(position, bar, [])


def minute(opened, o, h, low, c):
    return dict(
        symbol="SYNTHETIC",
        open_ts_ms=opened,
        close_ts_ms=opened + model.MINUTE,
        available_ts_ms=opened + model.MINUTE,
        segment_id="synthetic-0",
        open=o,
        high=h,
        low=low,
        close=c,
    )


def test_actual_producer_order_reaches_model_adapter_protective_close():
    order = plan_order()
    adapter = DetailExecutionAdapter(
        order,
        fill_model=MODEL,
        fee_rate="0.001",
        entry_update=model.entry_update,
        exit_update=model.exit_update,
    )
    start = order["order_active_ts_ms"]
    adapter.process_detail_bar(minute(start, 115, 116, 114, 115))
    assert adapter.state == "ACTIVE"
    adapter.process_detail_bar(minute(start + model.MINUTE, 114, 114, 107, 108))
    assert adapter.state == "CLOSED"
    assert [row["effect"] for row in adapter.ledger] == ["OPEN", "CLOSE"]
    assert Decimal(adapter.ledger[-1]["fill_price"]) == Decimal("108.0")
    assert all(
        row["execution_evidence"] == "MODEL_NOT_OBSERVED" for row in adapter.ledger
    )


def test_gap_in_detail_never_manufactures_exit():
    order = plan_order()
    adapter = DetailExecutionAdapter(
        order,
        fill_model=MODEL,
        fee_rate=0,
        entry_update=model.entry_update,
        exit_update=model.exit_update,
    )
    start = order["order_active_ts_ms"]
    adapter.process_detail_bar(minute(start, 115, 116, 114, 115))
    adapter.process_detail_bar(minute(start + 2 * model.MINUTE, 114, 114, 107, 108))
    assert adapter.state == "UNRESOLVED"
    assert [row["effect"] for row in adapter.ledger] == ["OPEN"]


@pytest.mark.parametrize(
    "change", [{"timeframe_min": 15}, {"atr_length": 12}, {"volume_unit": "base"}]
)
def test_no_hidden_config_or_threshold_grid(change):
    config = {**model.CONFIG, **change}
    with pytest.raises(ValueError, match="FROZEN_CONFIG_MISMATCH"):
        model.compile_model(model.TRAIL, {"SYNTHETIC": fixture_frame()}, config)


def test_other_five_are_not_fake_complete_strategies():
    catalog = model.catalog()
    assert len(catalog) == 6
    assert catalog["rsi_swing_fail"]["status"] == "COMPLETED_FAILURE_PRESERVED"
    assert (
        sum(
            row["status"] == "COMPLETE_DECLARED_RESEARCH_PAIR"
            for row in catalog.values()
        )
        == 1
    )
    catalog["bb_revert"]["status"] = "CHANGED"
    assert model.catalog()["bb_revert"]["status"] == "DATA_AND_POLICY_BLOCKED"


def test_bad_clock_and_mutated_quantity_policy_rejected():
    frame = fixture_frame()
    frame.loc[0, "close_ts_ms"] -= 1
    with pytest.raises(ValueError, match="EXCLUSIVE_30M_CLOCK_REQUIRED"):
        compile_frame(frame)
    result = compile_frame()
    plan = copy.deepcopy(result["plans"][0])
    plan["quantity_policy"]["price_risk_fraction"] = 1
    with pytest.raises(ValueError, match="FROZEN_QUANTITY_POLICY_MISMATCH"):
        model.create_order(plan, 10000, "id", result["rule_digest"])


def test_raw_short_sequence_and_short_trailing():
    frame = fixture_frame().iloc[:10].copy()
    prices = [
        (100, 111, 100, 110),
        (110, 110, 89, 90),
        (90, 91, 85, 86),
        (88, 92, 87, 89),
        (89, 90, 84, 85),
    ]
    rows = []
    for index, (o, h, low, c) in enumerate(prices, 10):
        rows.append(
            dict(
                open_ts_ms=index * model.TF,
                close_ts_ms=(index + 1) * model.TF,
                available_ts_ms=(index + 1) * model.TF,
                segment_id="synthetic-0",
                open=o,
                high=h,
                low=low,
                close=c,
            )
        )
    result = compile_frame(pd.concat([frame, pd.DataFrame(rows)], ignore_index=True))
    plan = result["plans"][0]
    assert plan["side"] == -1 and plan["protective_stop"] == 92
    order = model.create_order(plan, 10000, "short-test", result["rule_digest"])
    assert model.entry_update(order["signal"], 85) == {"stop_price": 92}
    assert model.entry_update(order["signal"], 84)["reject"]
    position = {"signal": order["signal"], "side": -1, "stop_price": 92}
    bar = dict(
        available_ts_ms=16 * model.TF,
        close_ts_ms=16 * model.TF,
        st_available_ts_ms=16 * model.TF,
        st_direction=-1,
        st_line=90,
    )
    assert model.exit_update(position, bar, [])["next_stop"] == 90
    bar["st_line"] = 95
    assert model.exit_update(position, bar, [])["next_stop"] == 92


def test_completed_band_is_applied_to_future_detail_only():
    """A callback fixture checks sequencing, not a new genuine-source benchmark."""
    for profile in model.MODELS:
        order = plan_order(profile)
        adapter = DetailExecutionAdapter(
            order,
            fill_model=MODEL,
            fee_rate=0,
            entry_update=model.entry_update,
            exit_update=model.exit_update,
        )
        start = order["order_active_ts_ms"]
        parts = []
        for index in range(30):
            row = minute(start + index * model.MINUTE, 115, 116, 114, 115)
            adapter.process_detail_bar(row)
            parts.append(row)
        decision = dict(
            symbol="SYNTHETIC",
            open_ts_ms=start,
            close_ts_ms=start + model.TF,
            available_ts_ms=start + model.TF,
            segment_id="synthetic-0",
            open=115,
            high=116,
            low=114,
            close=115,
            st_direction=1,
            st_line=114.5,
            st_available_ts_ms=start + model.TF,
        )
        adapter.process_decision_bar(decision, [decision])
        assert adapter.state == "ACTIVE"
        assert adapter.stop == 108
        adapter.process_detail_bar(minute(start + model.TF, 115, 116, 114, 115))
        assert adapter.state == ("CLOSED" if profile == model.TRAIL else "ACTIVE")
        if profile == model.TRAIL:
            assert float(adapter.ledger[-1]["fill_price"]) == 114.5


def test_price_type_contradiction_and_nonpositive_loose_band():
    frame = fixture_frame()
    frame["price_type"] = "mark"
    with pytest.raises(ValueError, match="ROW_PRICE_TYPE_MISMATCH"):
        compile_frame(frame)
    position, bar = position_bar()
    bar["st_line"] = -5
    assert model.exit_update(position, bar, [])["next_stop"] == 108


def test_delayed_last_session_entry_cannot_escape_daily_flatten():
    frame = fixture_frame()
    shift = 31 * model.TF
    for key in ("open_ts_ms", "close_ts_ms", "available_ts_ms"):
        frame[key] += shift
    frame.loc[13, "available_ts_ms"] = model.DAY - 61 * model.MINUTE
    for profile in model.MODELS:
        result = compile_frame(frame, profile)
        order = model.create_order(
            result["plans"][0], 10000, "late-synthetic", result["rule_digest"]
        )
        assert order["order_active_ts_ms"] == model.DAY - 61 * model.MINUTE
        adapter = DetailExecutionAdapter(
            order,
            fill_model=MODEL,
            fee_rate=0,
            entry_update=model.entry_update,
            exit_update=model.exit_update,
        )
        start = order["order_active_ts_ms"]
        for index in range(31):
            adapter.process_detail_bar(
                minute(start + index * model.MINUTE, 115, 116, 114, 115)
            )
        decision_open = model.DAY - 2 * model.TF
        decision = dict(
            symbol="SYNTHETIC",
            open_ts_ms=decision_open,
            close_ts_ms=model.DAY - model.TF,
            available_ts_ms=model.DAY - model.TF,
            segment_id="synthetic-0",
            open=115,
            high=116,
            low=114,
            close=115,
            st_direction=1,
            st_line=102,
            st_available_ts_ms=model.DAY - model.TF,
        )
        adapter.process_decision_bar(decision, [decision])
        adapter.process_detail_bar(minute(model.DAY - model.TF, 115, 116, 114, 115))
        assert adapter.state == "CLOSED"
        assert adapter.ledger[-1]["ts_ms"] == model.DAY - model.TF
    frame.loc[13, "available_ts_ms"] = model.DAY - 55 * model.MINUTE
    assert compile_frame(frame)["plans"] == []


def test_canonical_integer_segments_keep_original_type_and_price_plan():
    frame = fixture_frame()
    frame["segment_id"] = 0
    result = compile_frame(frame)
    assert result["plans"] == compile_frame()["plans"]
    assert result["decisions"]["SYNTHETIC"].segment_id.tolist() == [0] * len(frame)


@pytest.mark.parametrize("after", [1, "0"])
def test_changed_or_mixed_segment_type_resets_pending_setup(after):
    frame = fixture_frame()
    frame["segment_id"] = pd.Series([0] * len(frame), dtype=object)
    frame.loc[12:, "segment_id"] = after
    assert compile_frame(frame)["plans"] == []


@pytest.mark.parametrize(
    "segment", [True, False, -1, 0.0, 0.5, float("nan"), float("inf"), "", " "]
)
def test_invalid_segment_types_or_values_are_rejected(segment):
    frame = fixture_frame()
    frame["segment_id"] = pd.Series([segment] * len(frame), dtype=object)
    with pytest.raises(ValueError, match="INVALID_SEGMENT"):
        compile_frame(frame)
