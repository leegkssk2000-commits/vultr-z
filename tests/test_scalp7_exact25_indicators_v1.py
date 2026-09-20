"""Synthetic source cases only. No market-data file or economic runner is used."""

import copy
import json
import math

import pandas as pd
import pytest

from backend.research.rebuild import scalp7_exact25_indicators_v1 as mod


def bars(close, *, volumes=None, width=1.0, start=0):
    rows = []
    for i, c in enumerate(close):
        c = float(c)
        ts = start + i * 900000
        rows.append(
            dict(
                open_ts_ms=ts,
                close_ts_ms=ts + 900000,
                available_ts_ms=ts + 900000,
                segment_id="a",
                open=c,
                high=c + width,
                low=c - width,
                close=c,
                volume=volumes[i] if volumes is not None else 10.0,
            )
        )
    return pd.DataFrame(rows)


def config(strategy, **overrides):
    value = {
        "mode_id": mod.MODES[strategy][0],
        "timeframe_min": 15,
        "volume_unit": "base",
        "price_type": "last",
    }
    value.update(
        {
            "bb_revert": dict(
                bb_length=3,
                bb_multiplier=1.0,
                ii_period=1,
                ii_version="ROLLING_NORMALIZED_HLC_VOLUME_V1",
                confirmation="CLOSE_BEYOND_ALERT_EXTREME",
                alert_expiry_bars=3,
                invalidation="ALERT_EXTREME",
            ),
            "mfi_rsi_div": dict(oscillator_period=3, pivot_left=1, pivot_right=1),
            "supertrend_pullback": dict(atr_length=3, multiplier=1.0),
        }.get(strategy, {})
    )
    value.update(overrides)
    return value


def run(strategy, frame, **overrides):
    return mod.evaluate(strategy, {"TEST": frame}, config(strategy, **overrides))


def test_exact_six_component_catalog_and_no_strategy_claim():
    assert len(mod.catalog()) == 6
    for strategy in mod.catalog():
        result = run(strategy, bars([100 + i % 5 for i in range(80)]))
        assert result["rule_digest"] == mod.validate_rules(result["rules"])
        assert not result["complete_strategy"]
        assert result["economic_runs"] == 0
        assert result["order"] == result["live"] == "BLOCKED"
        json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("strategy", list(mod.MODES))
def test_raw_caller_prefix_invariance_and_future_mutation(strategy):
    frame = bars([100 + math.sin(i / 2) * 5 + i * 0.05 for i in range(90)])
    a = run(strategy, frame.iloc[:60])
    b = run(strategy, frame)
    for key in ("events", "components", "intents"):
        assert a[key] == [x for x in b[key] if x["available_ts_ms"] <= 60 * 900000]
    mutated = frame.copy()
    mutated.loc[60:, ["open", "high", "low", "close"]] *= 2
    c = run(strategy, mutated)
    for key in ("events", "components", "intents"):
        assert a[key] == [x for x in c[key] if x["available_ts_ms"] <= 60 * 900000]


@pytest.mark.parametrize("strategy", list(mod.MODES))
def test_physical_gap_resets_as_fresh_suffix(strategy):
    frame = bars([100 + math.sin(i) * 5 for i in range(100)])
    frame.loc[50:, ["open_ts_ms", "close_ts_ms", "available_ts_ms"]] += 900000
    result = run(strategy, frame)
    suffix = run(strategy, frame.iloc[50:])
    for key in ("events", "components", "intents"):
        lhs = [
            {k: v for k, v in x.items() if k != "local_segment"}
            for x in result[key]
            if x["bar_open_ts_ms"] >= 51 * 900000
        ]
        rhs = [
            {k: v for k, v in x.items() if k != "local_segment"} for x in suffix[key]
        ]
        assert lhs == rhs


@pytest.mark.parametrize(
    "change,message",
    [
        (dict(volume_unit="quote"), "EXPLICIT_BASE"),
        (dict(price_type="mark"), "EXPLICIT_BASE"),
        (dict(timeframe_min=5), "SCALP7_TIMEFRAME"),
        (dict(timeframe_min=30), "TIMEFRAME_MISMATCH"),
    ],
)
def test_units_and_clock_rejected(change, message):
    with pytest.raises(ValueError, match=message):
        run("obv_trend", bars([10, 11]), **change)


@pytest.mark.parametrize(
    "column,value",
    [
        ("close", float("nan")),
        ("volume", -1),
        ("low", 0),
        ("available_ts_ms", 1),
        ("open_ts_ms", 0.5),
    ],
)
def test_invalid_raw_observation_rejected(column, value):
    frame = bars([10, 11])
    frame[column] = frame[column].astype(object)
    frame.loc[0, column] = value
    with pytest.raises(ValueError):
        run("obv_trend", frame)


def test_duplicate_timestamp_and_mixed_volume_units_rejected():
    frame = bars([10, 11])
    frame.loc[1, ["open_ts_ms", "close_ts_ms", "available_ts_ms"]] = frame.loc[
        0, ["open_ts_ms", "close_ts_ms", "available_ts_ms"]
    ]
    with pytest.raises(ValueError, match="NON_CHRONOLOGICAL"):
        run("obv_trend", frame)
    frame = bars([10, 11])
    frame["volume_unit"] = ["base", "quote"]
    with pytest.raises(ValueError, match="ROW_UNIT"):
        run("mfi_rsi_div", frame)


def bb_example():
    frame = bars([10, 10, 9, 11, 12], width=0.2)
    frame.loc[2, ["open", "high", "low", "close"]] = [8.8, 9.1, 8.0, 9.0]
    return frame


def test_bbiii_alert_then_same_day_price_confirmation_no_backdated_fill():
    result = run("bb_revert", bb_example())
    alert = next(x for x in result["events"] if x["kind"] == "REVERSAL_ALERT")
    confirm = next(x for x in result["events"] if x["kind"] == "PRICE_CONFIRMED")
    assert alert["side"] == confirm["side"] == 1
    assert confirm["bar_open_ts_ms"] > alert["bar_open_ts_ms"]
    assert confirm["bar_open_ts_ms"] // 86400000 == alert["bar_open_ts_ms"] // 86400000
    intent = result["intents"][0]
    assert intent["earliest_submit_ts_ms"] == confirm["available_ts_ms"]
    assert intent["quantity"] is None and intent["initial_stop"] is None


def test_bb_tag_only_does_not_enter_and_mfi_cannot_replace_ii():
    result = run("bb_revert", bars([10, 10, 9, 8, 7], width=0.2))
    assert result["intents"] == []
    with pytest.raises(ValueError, match="UNSUPPORTED_BBIII"):
        run("bb_revert", bb_example(), ii_version="MFI")


def test_bb_invalidated_alert_not_resurrected_by_later_recovery():
    frame = bb_example()
    frame.loc[3, ["open", "high", "low", "close"]] = [8, 8.4, 7.8, 8]
    result = run("bb_revert", frame)
    assert any(x["kind"] == "ALERT_CANCELLED" for x in result["events"])
    assert result["intents"] == []


def test_bb_expiry_precedes_late_confirmation():
    frame = bb_example()
    frame.loc[3, ["open", "high", "low", "close"]] = [9, 9.1, 8.9, 9]
    result = run("bb_revert", frame, alert_expiry_bars=1)
    assert result["intents"] == []
    assert any(x.get("reason") == "EXPIRED" for x in result["events"])


def test_rsi_seed_manual_arithmetic_and_flat_limit():
    assert mod.rsi_values([10, 11, 10, 12], 3) == [None, None, None, 75.0]
    assert mod.rsi_values([10, 10, 10, 10], 3)[-1] == 50
    assert mod.rsi_values([10, 11, 12, 13], 3)[-1] == 100


def test_mfi_hand_computed_flow_and_zero_flow_undefined():
    frame = bars([10, 12, 11, 13], volumes=[1, 2, 3, 4])
    assert mod.mfi_values(frame.to_dict("records"), 3)[-1] == pytest.approx(
        100 * (24 + 52) / (24 + 33 + 52)
    )
    assert mod.mfi_values(bars([10] * 5).to_dict("records"), 3)[-1] is None


def test_divergence_two_same_price_pivots_confirmed_after_right_bar():
    # Weakened second upswing yields higher price high / lower RSI at that HIGH.
    frame = bars([10, 11, 12, 14, 13, 12, 13, 14.5, 14, 13, 12], width=0.1)
    result = run("mfi_rsi_div", frame)
    warnings = [
        e
        for e in result["events"]
        if e["kind"] == "DIVERGENCE_WARNING" and e["oscillator"] == "rsi"
    ]
    assert len(warnings) == 1
    event = warnings[0]
    assert event["first_pivot_ts_ms"] == 3 * 900000
    assert event["second_pivot_ts_ms"] == 7 * 900000
    assert event["available_ts_ms"] == 9 * 900000
    assert event["second_price"] > event["first_price"]
    assert event["second_oscillator"] < event["first_oscillator"]
    assert result["intents"] == []


def test_divergence_no_future_right_bar_and_equal_pivots_rejected():
    frame = bars([10, 11, 12, 14, 13, 12, 13, 14.5], width=0.1)
    assert not any(
        x["kind"] == "DIVERGENCE_WARNING" for x in run("mfi_rsi_div", frame)["events"]
    )
    frame = bars([10, 11, 12, 14, 14, 12, 13, 14.5, 14.5, 13], width=0.1)
    assert not any(
        x["kind"] == "DIVERGENCE_WARNING" for x in run("mfi_rsi_div", frame)["events"]
    )


def test_obv_unchanged_close_and_separate_raw_participation():
    result = run("obv_trend", bars([10, 11, 11, 9], volumes=[5, 7, 100, 4]))
    assert [x["obv"] for x in result["components"]] == [0, 7, 7, 3]
    assert result["components"][2]["base_volume"] == 100
    assert result["events"] == result["intents"] == []


def test_existing_rsi_state_machine_is_called_from_actual_prices(monkeypatch):
    observed = []
    real = mod.existing_rsi.oscillator_step

    def recording(state, value, index):
        observed.append(value)
        return real(state, value, index)

    monkeypatch.setattr(mod.existing_rsi, "oscillator_step", recording)
    result = run(
        "rsi_swing_fail",
        bars([100 + i for i in range(16)] + [114, 116, 115, 118, 115, 120]),
    )
    assert observed[14] == 100
    assert any(x["kind"] == "RSI_FAILURE_SWING_COMPONENT" for x in result["events"])
    rule = next(x for x in result["rules"] if x["rule_id"] == "RSI_EXISTING_SEQUENCE")
    assert rule["origin"] == "EXISTING_FROZEN"
    assert "8bar" in rule["expression"]
    assert result["intents"] == []


def test_supertrend_manual_atr_seed_bands_close_flip_and_availability():
    result = run("supertrend_pullback", bars([10, 10, 10, 14, 15], width=1))
    a, b = result["components"][:2]
    assert (a["atr"], a["upper"], a["lower"], a["direction"]) == (2, 12, 8, -1)
    assert b["atr"] == 3
    assert (b["upper"], b["lower"], b["direction"], b["line"]) == (12, 11, 1, 11)
    assert b["applicable_not_before_ts_ms"] == 4 * 900000
    assert result["intents"] == []


def test_supertrend_exact_band_touch_is_not_flip():
    result = run("supertrend_pullback", bars([10, 10, 10, 12], width=1))
    assert result["components"][-1]["direction"] == -1


def test_raschke_uses_simple_averages_and_signal_of_oscillator():
    close = [100 + i * i / 20 for i in range(40)]
    result = run("trend_ma_macd", bars(close))
    rows = result["components"]
    assert rows[8]["oscillator"] is None and rows[23]["signal"] is None
    assert rows[24]["oscillator"] == pytest.approx(
        sum(close[22:25]) / 3 - sum(close[15:25]) / 10
    )
    expected = (
        sum(
            sum(close[j - 2 : j + 1]) / 3 - sum(close[j - 9 : j + 1]) / 10
            for j in range(9, 25)
        )
        / 16
    )
    assert rows[24]["signal"] == pytest.approx(expected)
    assert rows[24]["signal"] != pytest.approx(sum(close[9:25]) / 16)
    assert rows[24]["oscillator"] != pytest.approx(
        mod._ema(close, 3)[24] - mod._ema(close, 10)[24]
    )


def test_gmma_reuses_frozen_full_groups_and_does_not_emit_old_entries():
    result = run(
        "trend_ma_macd",
        bars(list(range(100, 165))),
        mode_id=mod.MODES["trend_ma_macd"][1],
    )
    rows = result["components"]
    assert len(rows[-1]["short"]) == len(rows[-1]["long"]) == 6
    assert not rows[58]["ready"] and rows[59]["ready"]
    assert result["events"] == result["intents"] == []


def test_ema_macd_requires_explicit_periods_and_separate_mode():
    with pytest.raises(ValueError):
        run("trend_ma_macd", bars([100] * 40), mode_id=mod.MODES["trend_ma_macd"][2])
    result = run(
        "trend_ma_macd",
        bars(list(range(100, 140))),
        mode_id=mod.MODES["trend_ma_macd"][2],
        fast_period=3,
        slow_period=10,
        signal_period=16,
    )
    assert result["components"][23]["signal"] is None
    assert result["components"][24]["signal"] is not None


def test_dependency_availability_is_cumulative_not_backdated():
    frame = bars([10, 11, 12])
    frame.loc[0, "available_ts_ms"] = 4000000
    result = run("obv_trend", frame)
    assert all(x["available_ts_ms"] == 4000000 for x in result["components"])


def test_input_frames_and_config_are_not_mutated():
    frame = bars([10, 11, 12])
    original = frame.copy(deep=True)
    cfg = config("obv_trend")
    before = copy.deepcopy(cfg)
    mod.evaluate("obv_trend", {"TEST": frame}, cfg)
    pd.testing.assert_frame_equal(frame, original)
    assert cfg == before


def test_bb_zero_range_cannot_hide_pending_invalidation():
    frame = bb_example()
    frame.loc[3, ["open", "high", "low", "close"]] = [7.0, 7.0, 7.0, 7.0]
    result = run("bb_revert", frame)
    assert any(
        e.get("reason") == "INVALIDATED" and e["bar_open_ts_ms"] == 2700000
        for e in result["events"]
    )
    assert result["intents"] == []


def test_bb_short_alert_and_confirmation_are_mirrored():
    frame = bb_example()
    old_high = frame["high"].copy()
    old_low = frame["low"].copy()
    frame["high"] = 30 - old_low
    frame["low"] = 30 - old_high
    frame["open"] = 30 - frame["open"]
    frame["close"] = 30 - frame["close"]
    result = run("bb_revert", frame)
    assert result["intents"][0]["side"] == -1
    assert result["intents"][0]["setup_ts_ms"] == 1800000


@pytest.mark.parametrize("strategy", list(mod.MODES))
def test_thirty_minute_component_decision_clock(strategy):
    frame = bars([100 + math.sin(i) * 5 for i in range(80)])
    frame[["open_ts_ms", "close_ts_ms", "available_ts_ms"]] *= 2
    result = run(strategy, frame, timeframe_min=30)
    assert result["components"]
    assert all(e["available_ts_ms"] % 1800000 == 0 for e in result["components"])


def test_overlapping_bar_intervals_are_not_missing_data_segments():
    frame = pd.DataFrame(
        [
            dict(
                open_ts_ms=0,
                close_ts_ms=900000,
                available_ts_ms=900000,
                segment_id="A",
                open=100,
                high=101,
                low=99,
                close=100,
                volume=1,
            ),
            dict(
                open_ts_ms=60000,
                close_ts_ms=960000,
                available_ts_ms=960000,
                segment_id="B",
                open=100,
                high=101,
                low=99,
                close=100,
                volume=1,
            ),
        ]
    )
    with pytest.raises(ValueError, match="OVERLAPPING_BAR_INTERVALS"):
        mod.evaluate(
            "obv_trend",
            {"X": frame},
            {
                "timeframe_min": 15,
                "mode_id": mod.MODES["obv_trend"][0],
                "volume_unit": "base",
                "price_type": "last",
            },
        )
