"""Synthetic raw-price positive/counterexamples; zero market replays."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from backend.research.rebuild import scalp7_exact25_structure_v1 as s
from backend.research.rebuild.scalp7_implementation_contract_v1 import validate_rules


def bars(candles, tf=15, start=0):
    rows = []
    for i, candle in enumerate(candles):
        o, h, low, c, *v = candle
        opened = start + i * tf * 60000
        rows.append(
            {
                "open_ts_ms": opened,
                "close_ts_ms": opened + tf * 60000,
                "available_ts_ms": opened + tf * 60000,
                "segment_id": "a",
                "open": o,
                "high": h,
                "low": low,
                "close": c,
                "volume": v[0] if v else 100.0,
                "volume_unit": "BASE",
                "session_id": "2026-01-05",
            }
        )
    return pd.DataFrame(rows)


def config(strategy, **kwargs):
    return {
        "mode_id": s.MODES[strategy][0],
        "timeframe_min": 15,
        "hypothesis_id": "SYNTHETIC_SPEC_CASE_NOT_ECONOMICS",
        **kwargs,
    }


def fixture(strategy):
    if strategy in ("scalp_snap", "range_fade"):
        x = bars(
            [(10, 10.1, 9.9, 10)] * 30
            + [
                (10, 14, 10, 13.8, 1000),
                (13.8, 13.9, 13, 13.2, 200),
                (13.2, 14.2, 13.1, 14, 800),
            ]
        )
        c = config(
            strategy,
            impulse_lookback_bars=5,
            impulse_range_multiple=3,
            flag_max_retracement_fraction=0.5,
            flag_min_bars=1,
            flag_max_bars=3,
            tick_size=0.01,
        )
        if strategy == "scalp_snap":
            c["pullback_volume_ratio"] = 0.5
        return x, c
    if strategy in ("ema_ribbon_scalp", "pivot_reversal"):
        tail = (
            [
                (100, 110, 99, 105),
                (105, 107, 104, 106),
                (106, 108, 105, 107),
                (107, 107.5, 104, 105.5),
            ]
            if strategy == "ema_ribbon_scalp"
            else [
                (100, 101, 89, 90),
                (90, 94, 90, 93),
                (93, 95, 92, 94),
                (94, 94.5, 92, 93),
            ]
        )
        x = bars([(100, 100.2, 99.8, 100)] * 30 + tail)
        return x, config(
            strategy,
            ema_length=20,
            pivot_left_bars=1,
            pivot_right_bars=1,
            base_bars=3,
            base_range_ratio=0.5,
            watch_extension_fraction=0.05,
            setup_expiry_bars=8,
            tick_size=0.1,
        )
    if strategy == "keltner_trend":
        closes = (
            [100 + (-1) ** i for i in range(35)] + [102 + i for i in range(35)] + [110]
        )
        candles = [
            (
                closes[max(i - 1, 0)],
                max(closes[max(i - 1, 0)], c) + 0.2,
                min(closes[max(i - 1, 0)], c) - 0.2,
                c,
            )
            for i, c in enumerate(closes)
        ]
        return bars(candles, tf=30), config(
            strategy,
            timeframe_min=30,
            requalification_adx_below=20,
            qualification_expiry_bars=40,
            tick_size=0.1,
        )
    x = bars(
        [
            (160, 161, 159, 160),
            (160, 163, 160, 162),
            (162, 162.5, 154, 155),
            (155, 157, 155, 156),
            (156, 156.5, 151, 152),
        ],
        start=4 * 86400000,
    )
    daily = bars(
        [
            (100, 101, 99, 100),
            (100, 111, 100, 110),
            (110, 131, 110, 130),
            (130, 161, 130, 160),
        ],
        tf=1440,
    )
    return x, config(
        strategy,
        extension_sessions=3,
        extension_return_fraction=0.5,
        max_rebound_fraction=0.5,
        tick_size=0.1,
        daily_frames={"X": daily},
        daily_calendar="UTC_24H_DECLARED_ADAPTATION",
    )


@pytest.mark.parametrize("strategy", list(s.MODES))
def test_raw_positive_path_and_partial_risk(strategy):
    x, c = fixture(strategy)
    out = s.evaluate(strategy, {"X": x}, c)
    assert len(out["intents"]) == 1
    intent = out["intents"][0]
    assert intent["side"] * (intent["trigger_price"] - intent["protective_stop"]) > 0
    assert intent["decision_ts_ms"] >= intent["feature_available_ts_ms"]
    assert intent["fill_price"] is None and intent["fill_ts_ms"] is None
    assert intent["qty_base"] is None and intent["expires_ts_ms"] is None
    assert not intent["complete_order"] and not out["complete_strategy"]
    assert out["rule_digest"] == validate_rules(out["rules"])
    assert out["authority"]["live"] == "BLOCKED"


@pytest.mark.parametrize("strategy", list(s.MODES))
def test_every_raw_prefix_is_causal(strategy):
    x, c = fixture(strategy)
    full = s.evaluate(strategy, {"X": x}, c)
    for n in range(1, len(x) + 1):
        cut = x.iloc[:n]
        out = s.evaluate(strategy, {"X": cut}, c)
        ts = int(cut.iloc[-1].available_ts_ms)
        assert out["events"] == [
            e for e in full["events"] if e["available_ts_ms"] <= ts
        ]
        assert out["intents"] == [
            e for e in full["intents"] if e["decision_ts_ms"] <= ts
        ]


@pytest.mark.parametrize("strategy", list(s.MODES))
def test_gap_and_segment_change_do_not_inherit_setup(strategy):
    x, c = fixture(strategy)
    for by_segment in (False, True):
        broken = x.copy()
        if by_segment:
            broken.loc[len(x) - 1, "segment_id"] = "b"
        else:
            for key in ("open_ts_ms", "close_ts_ms", "available_ts_ms"):
                broken.loc[len(x) - 1, key] += int(c["timeframe_min"]) * 60000
        assert not s.evaluate(strategy, {"X": broken}, c)["intents"]


@pytest.mark.parametrize("strategy", ["ema_ribbon_scalp", "pivot_reversal"])
def test_watch_or_ema_cross_without_known_pivot_is_not_entry(strategy):
    x, c = fixture(strategy)
    out = s.evaluate(strategy, {"X": x.iloc[:31]}, c)
    assert any("WATCH_ONLY" in e["kind"] for e in out["events"])
    assert not out["intents"]
    full = s.evaluate(strategy, {"X": x}, c)
    pivot = next(e for e in full["events"] if e["kind"] == "CONFIRMED_SWING_PIVOT")
    assert pivot["pivot_event_ts_ms"] < pivot["pivot_known_ts_ms"]
    assert pivot["reference_type"] == "CONFIRMED_PRICE_SWING_NOT_DAILY_HLC"


@pytest.mark.parametrize("strategy", ["ema_ribbon_scalp", "pivot_reversal"])
def test_kell_support_failure_cancels_watch(strategy):
    x, c = fixture(strategy)
    x.loc[31, "low"] = 80
    assert not s.evaluate(strategy, {"X": x}, c)["intents"]


def test_hg_first_touch_follows_qualification_and_stop_is_future_only():
    x, c = fixture("keltner_trend")
    out = s.evaluate("keltner_trend", {"X": x}, c)
    qualification = next(
        e for e in out["events"] if e["kind"] == "INITIAL_ADX_QUALIFICATION"
    )
    touch = next(
        e for e in out["events"] if e["kind"] == "FIRST_POST_QUALIFICATION_EMA_TOUCH"
    )
    assert qualification["available_ts_ms"] < touch["available_ts_ms"]
    intent = out["intents"][0]
    assert intent["decision_ts_ms"] == touch["available_ts_ms"]
    assert intent["order_kind"] == "STOP_MARKET"
    assert intent["trigger_price"] == float(x.iloc[-1].high) + 0.1
    assert out["components"]["timeframe_min"] == 30


def test_hg_2004_is_separate_mode_with_momentum_requirement():
    x, c = fixture("keltner_trend")
    c["mode_id"] = "HG_2004_MOMENTUM_CASE"
    with pytest.raises(ValueError, match="momentum_lookback"):
        s.evaluate("keltner_trend", {"X": x}, c)
    c["momentum_lookback"] = 10
    out = s.evaluate("keltner_trend", {"X": x}, c)
    assert out["mode_id"] != "HG_1997_CONDITIONAL"
    assert len(out["intents"]) == 1


def test_hg_expiry_is_explicit_hypothesis_not_unlimited_source_default():
    x, c = fixture("keltner_trend")
    del c["qualification_expiry_bars"]
    with pytest.raises(ValueError, match="qualification_expiry_bars"):
        s.evaluate("keltner_trend", {"X": x}, c)
    c["qualification_expiry_bars"] = 1
    assert not s.evaluate("keltner_trend", {"X": x}, c)["intents"]


def test_sma_3_10_16_is_not_ema_macd_and_adx_seed_is_warmed():
    x = bars([(i + 1, i + 1.5, i + 0.5, i + 1) for i in range(30)])
    m = s._measures(x.to_dict("records"))
    assert math.isnan(m[26]["adx14"])
    assert m[27]["adx14"] == pytest.approx(100)
    assert m[9]["osc_3_10_sma"] == pytest.approx(3.5)
    assert m[24]["osc_signal_sma16"] == pytest.approx(3.5)
    assert m[19]["ema"] == pytest.approx(10.5)


def test_anti_continuation_positive_and_boundary_fade_negative():
    x, c = fixture("range_fade")
    out = s.evaluate("range_fade", {"X": x}, c)
    assert out["intents"][0]["side"] == 1
    assert out["mode_id"] == "ANTI_IMPULSE_CONTINUATION_DECLARED"
    flat_range = bars([(10, 11, 9, 10), (10, 11, 9, 9.2), (9.2, 11, 9, 10.8)] * 12)
    assert not s.evaluate("range_fade", {"X": flat_range}, c)["intents"]


def test_anti_short_keeps_original_impulse_direction():
    x, c = fixture("range_fade")
    old = x.copy()
    x["open"], x["close"] = 24 - old["open"], 24 - old["close"]
    x["high"], x["low"] = 24 - old["low"], 24 - old["high"]
    assert s.evaluate("range_fade", {"X": x}, c)["intents"][0]["side"] == -1


def test_gajjala_high_volume_pullback_or_lost_base_rejected():
    x, c = fixture("scalp_snap")
    x.loc[31, "volume"] = 2000
    assert not s.evaluate("scalp_snap", {"X": x}, c)["intents"]
    x, c = fixture("scalp_snap")
    x.loc[31, "low"] = 9
    assert not s.evaluate("scalp_snap", {"X": x}, c)["intents"]


def test_short_skirt_cannot_turn_two_minute_opportunity_into_15m_fill():
    x, c = fixture("scalp_snap")
    c["mode_id"] = "SHORT_SKIRT_NATIVE_UNAVAILABLE"
    with pytest.raises(ValueError, match="SHORT_SKIRT_NATIVE"):
        s.evaluate("scalp_snap", {"X": x}, c)


def test_parabolic_volume_spike_alone_is_not_short():
    x, c = fixture("vol_spike_fade")
    x = x.iloc[:2].copy()
    x["volume"] = 1000000
    assert not s.evaluate("vol_spike_fade", {"X": x}, c)["intents"]


def test_parabolic_future_daily_context_and_rebreak_rejected():
    x, c = fixture("vol_spike_fade")
    delayed = c["daily_frames"]["X"].copy()
    delayed.loc[3, "available_ts_ms"] += 86400000
    c["daily_frames"] = {"X": delayed}
    assert not s.evaluate("vol_spike_fade", {"X": x}, c)["intents"]
    x, c = fixture("vol_spike_fade")
    x.loc[3, "high"] = 165
    assert not s.evaluate("vol_spike_fade", {"X": x}, c)["intents"]


def test_parabolic_needs_daily_sessions_not_intraday_lookback():
    x, c = fixture("vol_spike_fade")
    del c["daily_frames"]
    with pytest.raises(ValueError, match="GENUINE_DAILY_CONTEXT"):
        s.evaluate("vol_spike_fade", {"X": x}, c)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, 0, -1, "3"])
def test_missing_or_invalid_qualitative_threshold_is_not_defaulted(value):
    x, c = fixture("scalp_snap")
    c["impulse_range_multiple"] = value
    with pytest.raises((ValueError, TypeError)):
        s.evaluate("scalp_snap", {"X": x}, c)


@pytest.mark.parametrize(
    "field,value",
    [
        ("open", float("nan")),
        ("volume", -1),
        ("low", 1000),
        ("segment_id", None),
        ("available_ts_ms", 0),
        ("open_ts_ms", 0.5),
    ],
)
def test_invalid_raw_input_rejected(field, value):
    x, c = fixture("scalp_snap")
    x[field] = x[field].astype(object)
    x.loc[3, field] = value
    with pytest.raises(ValueError):
        s.evaluate("scalp_snap", {"X": x}, c)


def test_multi_symbol_inputs_have_separate_causal_state():
    x, c = fixture("scalp_snap")
    out = s.evaluate("scalp_snap", {"X": x, "Y": x.iloc[:31]}, c)
    assert [e["symbol"] for e in out["intents"]] == ["X"]
    assert set(out["components"]["input_sha256"]) == {"X", "Y"}


def test_gajjala_volume_unit_is_explicit_and_stable():
    x, c = fixture("scalp_snap")
    with pytest.raises(ValueError, match="VOLUME_UNIT"):
        s.evaluate("scalp_snap", {"X": x.drop(columns="volume_unit")}, c)
    x.loc[31, "volume_unit"] = "QUOTE"
    with pytest.raises(ValueError, match="VOLUME_UNIT"):
        s.evaluate("scalp_snap", {"X": x}, c)


def test_nonpositive_planned_stop_is_not_emitted():
    x, c = fixture("scalp_snap")
    c["tick_size"] = 20
    out = s.evaluate("scalp_snap", {"X": x}, c)
    assert not out["intents"]
    assert any(e["kind"] == "INVALID_PLANNED_RISK" for e in out["events"])
