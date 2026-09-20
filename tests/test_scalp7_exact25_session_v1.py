"""Synthetic causal source cases, never economic tests."""

import hashlib
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from backend.research.rebuild import scalp7_exact25_session_v1 as m


def bars(n=60, tf=15, start=0):
    return pd.DataFrame(
        [
            dict(
                open_ts_ms=start + i * tf * 60000,
                close_ts_ms=start + (i + 1) * tf * 60000,
                available_ts_ms=start + (i + 1) * tf * 60000,
                segment_id="A",
                open=100.0,
                high=102.0,
                low=98.0,
                close=100.0,
                volume=100.0,
            )
            for i in range(n)
        ]
    )


def sessions(n=16, tf=30, native=False):
    rows = []
    native_dates = []
    stamp = datetime(2026, 3, 1, tzinfo=ZoneInfo("America/New_York"))
    while len(native_dates) < n:
        if stamp.weekday() < 5:
            native_dates.append(stamp)
        stamp += timedelta(days=1)
    for day in range(n):
        if native:
            stamp = native_dates[day]
            start = int(stamp.replace(hour=9, minute=30).timestamp() * 1000)
            end = int(stamp.replace(hour=16, minute=0).timestamp() * 1000)
            count = 390 // tf
        else:
            start = day * 86_400_000
            count = 2
            end = start + count * tf * 60000
        frame = bars(count, tf, start)
        frame["session_id"] = f"d{day}"
        frame["session_index"] = day
        frame["session_open_ts_ms"] = start
        frame["session_close_ts_ms"] = end
        frame["session_known_ts_ms"] = start
        frame["close"] = 101.0
        frame["high"] = 103.0
        rows.extend(frame.to_dict("records"))
    return pd.DataFrame(rows)


def config(tf=30):
    return dict(
        timeframe_min=tf,
        clock_hypothesis_id="SYNTHETIC_SESSION_CASE",
        session_source=dict(
            source_ref="synthetic:calendar", timezone="UTC", market="SYNTHETIC"
        ),
    )


def daily(n=60):
    return pd.DataFrame(
        [
            dict(
                open_ts_ms=i * 86_400_000,
                close_ts_ms=(i + 1) * 86_400_000,
                available_ts_ms=(i + 1) * 86_400_000,
                session_index=i,
                high=102.0,
                low=98.0,
                close=100.0,
                volume=2_000_000.0,
                source_ref="synthetic:daily",
                timeframe_unit="DAY",
            )
            for i in range(n)
        ]
    )


def test_catalog_exact_partition_no_economic_credit():
    assert set(m.catalog()) == {
        "break_and_continue",
        "rbreaker_like",
        "session_bias",
        "squeeze_break",
        "trend_rider",
        "turtle_trend",
    }
    assert all(
        not r["complete_strategy"] and r["new_full_runs"] == 0
        for r in m.catalog().values()
    )


@pytest.mark.parametrize("tf", [1, 5, 60, True, None])
def test_decision_timeframe_is_never_silently_changed(tf):
    with pytest.raises(ValueError, match="TIMEFRAME"):
        m.evaluate("squeeze_break", {"X": bars()}, dict(timeframe_min=tf))


@pytest.mark.parametrize(
    "change,error",
    [
        ("available", "BAR_CLOCK"),
        ("duplicate", "STRICT_BAR"),
        ("nan", "OHLCV"),
        ("negative_volume", "OHLCV"),
        ("geometry", "GEOMETRY"),
    ],
)
def test_invalid_actual_input_rejected(change, error):
    x = bars()
    if change == "available":
        x.loc[0, "available_ts_ms"] = 0
    elif change == "duplicate":
        x.loc[1, "open_ts_ms"] = 0
    elif change == "nan":
        x.loc[0, "close"] = float("nan")
    elif change == "negative_volume":
        x.loc[0, "volume"] = -1
    else:
        x.loc[0, "low"] = 101.0
    with pytest.raises(ValueError, match=error):
        m.evaluate("squeeze_break", {"X": x}, dict(timeframe_min=15))


def test_frozen_squeeze_actual_math_and_prefix():
    x = bars()
    x["close"] = [100 + i * 0.01 for i in range(len(x))]
    full = m.evaluate("squeeze_break", {"X": x}, dict(timeframe_min=15))
    prefix = m.evaluate("squeeze_break", {"X": x.iloc[:50]}, dict(timeframe_min=15))
    assert full["components"][:50] == prefix["components"]
    assert not full["components"][37]["ready"]
    assert full["components"][38]["ready"]
    assert len(full["rules"][0]["code_sha"]) == 64
    assert not full["intents"]


def test_squeeze_gap_restarts_warmup():
    x = bars(80)
    x.loc[40:, "segment_id"] = "B"
    r = m.evaluate("squeeze_break", {"X": x}, dict(timeframe_min=15))
    assert not r["components"][77]["ready"]
    assert r["components"][78]["ready"]


def test_noise_exact14_same_slot_excludes_today_and_lags():
    x = sessions()
    x.loc[len(x) - 2, "close"] = 110.0
    x.loc[len(x) - 2, "high"] = 111.0
    r = m.evaluate("trend_rider", {"SPY": x}, config())
    row = r["components"][-2]
    assert row["reference_sessions"] == 14
    assert row["sigma_open"] == pytest.approx(0.01)
    assert row["upper"] == pytest.approx(102.01)
    assert row["target_after_available"] == 1 and row["exposure_for_current_bar"] == 0
    assert r["components"][-1]["exposure_for_current_bar"] == 1
    assert r["components"][-1]["target_after_available"] == 0
    assert not r["components"][26]["eligible"]


def test_noise_future_suffix_does_not_revise_prefix():
    x = sessions()
    full = m.evaluate("session_bias", {"X": x}, config())
    pre = m.evaluate("session_bias", {"X": x.iloc[:-1]}, config())
    assert full["components"][:-1] == pre["components"]


def test_noise_same_slot_missing_not_substituted_with_other_minutes():
    x = sessions().drop(index=10).reset_index(drop=True)
    r = m.evaluate("trend_rider", {"X": x}, config())
    assert not r["components"][-2]["eligible"]


def test_noise_calendar_forgery_rejected():
    x = sessions()
    x.loc[0, "session_known_ts_ms"] = 100
    with pytest.raises(ValueError, match="CALENDAR_NOT_CAUSAL"):
        m.evaluate("trend_rider", {"X": x}, config())


def test_native_nyse_dst_slots_stay930():
    x = sessions(native=True)
    cfg = dict(
        timeframe_min=30,
        session_source=dict(
            source_ref="synthetic:NYSE",
            timezone="America/New_York",
            market="US_EQUITY_REGULAR",
        ),
    )
    r = m.evaluate("trend_rider", {"SPY": x}, cfg)
    assert r["components"][-1]["slot_min"] == 390
    first = x.groupby("session_id", sort=False).first()
    assert first.session_open_ts_ms.diff().dropna().max() == 72 * 60 * 60 * 1000
    assert 71 * 60 * 60 * 1000 in first.session_open_ts_ms.diff().dropna().tolist()


def test_noise_cannot_use_unlabelled_crypto_clock():
    cfg = config()
    cfg.pop("clock_hypothesis_id")
    with pytest.raises(ValueError, match="DECLARED_HYPOTHESIS"):
        m.evaluate("trend_rider", {"X": sessions()}, cfg)


def test_rbreaker_published_unusual_formulas_preserved():
    lv = m.rbreaker_levels(110, 90, 100)
    assert lv == pytest.approx(
        dict(
            buy_setup=87.5,
            sell_setup=112.5,
            buy_enter=99.3,
            sell_enter=100.7,
            buy_break=92.5,
            sell_break=107.5,
        )
    )


def test_rbreaker_native_requires_observation_and_does_not_fabricate_oco():
    x = bars(30, tf=1)
    prev = dict(
        high=110, low=90, close=100, available_ts_ms=0, source_ref="synthetic:prior"
    )
    r = m.rbreaker_native_plan(x, prev, dict(qty_base=0), session_close_ts_ms=3_600_000)
    assert not r["orders"]
    x.loc[29, "high"] = 114
    r = m.rbreaker_native_plan(x, prev, dict(qty_base=0), session_close_ts_ms=3_600_000)
    assert [o["side"] for o in r["orders"]] == [1, -1]
    assert r["orders"][0]["trigger_price"] == 114
    assert not r["oco_implemented"]
    assert all(o["feature_available_ts_ms"] == 1_800_000 for o in r["orders"])


def test_rbreaker_native_trailing_actual_position_and_eod_limit():
    x = bars(30, tf=1)
    x.loc[29, "high"] = 110
    prev = dict(
        high=110, low=90, close=100, available_ts_ms=0, source_ref="synthetic:prior"
    )
    pos = dict(qty_base=2, fill_id="f1", fill_ts_ms=60_000, intra_trade_high=105)
    r = m.rbreaker_native_plan(x, prev, pos, session_close_ts_ms=3_600_000)
    assert r["orders"][0]["trigger_price"] == pytest.approx(109.56)
    r = m.rbreaker_native_plan(x, prev, pos, session_close_ts_ms=1_900_000)
    assert r["orders"][0]["order_kind"] == "LIMIT"
    assert r["orders"][0]["limit_marketable_not_assumed_filled"]


def test_turtle_n_sma_seed_recursion_and_gap():
    d = daily(22)
    d.loc[20, "high"] = 122
    ns = m.turtle_n(d)
    assert ns[:20] == [None] * 20
    assert ns[20] == 5 and ns[21] == pytest.approx(4.95)
    d.loc[21, "session_index"] = 23
    assert m.turtle_n(d)[-1] is None


def test_turtle_does_not_convert_daily_channels_to15m_bars():
    x = bars(60)
    cfg = dict(timeframe_min=15, daily_frames={"X": daily()})
    r = m.evaluate("turtle_trend", {"X": x}, cfg)
    assert not r["components"]
    x = bars(1, start=60 * 86_400_000)
    r = m.evaluate("turtle_trend", {"X": x}, cfg)
    assert r["components"][0]["entry_high"] == 102
    assert r["components"][0]["source_unit"] == "TRADING_DAY"
    assert not r["intents"]


def test_turtle_future_daily_revision_cannot_change_current_reference():
    x = bars(1, start=55 * 86_400_000)
    d = daily(60)
    cfg = dict(timeframe_min=15, daily_frames={"X": d})
    a = m.evaluate("turtle_trend", {"X": x}, cfg)
    d.loc[55:, "high"] = 999
    b = m.evaluate("turtle_trend", {"X": x}, cfg)
    assert a == b


def test_turtle_system1_requires_virtual_breakout_ledger():
    cfg = dict(
        timeframe_min=15,
        daily_frames={"X": daily()},
        mode_id="turtle_system1_daily_component_v1",
    )
    r = m.evaluate("turtle_trend", {"X": bars(1, start=60 * 86_400_000)}, cfg)
    assert r["events"][0]["kind"] == "SYSTEM1_VIRTUAL_LEDGER_REQUIRED"
    assert not r["components"][0]["entries_enabled"]


def test_turtle_adds_from_actual_fills_and_standard_stops():
    fills = [
        dict(
            fill_id="f1",
            unit_id="u1",
            unit_complete=True,
            state="FILLED",
            fill_ts_ms=1,
            fill_price=100,
            qty_base=1,
        ),
        dict(
            fill_id="f2",
            unit_id="u2",
            unit_complete=True,
            state="FILLED",
            fill_ts_ms=2,
            fill_price=102,
            qty_base=1,
        ),
    ]
    r = m.turtle_filled_units(fills, 2, 1)
    assert r["next_add_trigger"] == 103
    assert r["stop_prices"] == [97, 98]
    fills[1]["unit_complete"] = False
    with pytest.raises(ValueError, match="ACTUAL"):
        m.turtle_filled_units(fills, 2, 1)


def test_turtle_pending_orders_are_not_units():
    with pytest.raises(ValueError, match="ACTUAL"):
        m.turtle_filled_units(
            [
                dict(
                    fill_id="f",
                    unit_id="u",
                    unit_complete=True,
                    state="PENDING",
                    fill_ts_ms=1,
                    fill_price=100,
                    qty_base=1,
                )
            ],
            2,
            1,
        )


def test_flag_requires_named_hypothesis_and_three_distinct_events():
    x = bars(3)
    x.loc[0, ["open", "high", "low", "close", "volume"]] = [100, 110, 100, 109, 100]
    x.loc[1, ["open", "high", "low", "close", "volume"]] = [109, 109, 107, 108, 50]
    x.loc[2, ["open", "high", "low", "close", "volume"]] = [108, 111, 108, 110, 80]
    cfg = dict(
        timeframe_min=15,
        flag_hypothesis=dict(
            hypothesis_id="FLAG_CASE_V1",
            impulse_return_min=0.05,
            pullback_fraction_max=0.5,
        ),
    )
    r = m.evaluate("break_and_continue", {"X": x}, cfg)
    assert [e["kind"] for e in r["events"]] == [
        "IMPULSE",
        "LOW_VOLUME_PULLBACK",
        "CONTINUATION_CLOSE",
    ]
    assert len(r["intents"]) == 1 and r["intents"][0]["order_kind"] == "NEXT_OPEN"
    assert r["rules"][1]["origin"] == "DECLARED_HYPOTHESIS"
    with pytest.raises(ValueError, match="HYPOTHESIS"):
        m.evaluate("break_and_continue", {"X": x}, dict(timeframe_min=15))


def test_flag_gap_prevents_cross_gap_setup():
    x = bars(3)
    x.loc[0, ["open", "high", "low", "close"]] = [100, 110, 100, 109]
    x.loc[1:, "segment_id"] = "B"
    cfg = dict(
        timeframe_min=15,
        flag_hypothesis=dict(
            hypothesis_id="H", impulse_return_min=0.05, pullback_fraction_max=0.5
        ),
    )
    assert not m.evaluate("break_and_continue", {"X": x}, cfg)["intents"]


def test_orb_crypto_clock_is_not_native_us_strategy():
    cfg = config()
    cfg["mode_id"] = "stocks_in_play_orb_v1"
    with pytest.raises(ValueError, match="NATIVE_US"):
        m.evaluate("break_and_continue", {"X": sessions()}, cfg)


def test_noise_entire_missing_session_is_not_fourteen_observed_days():
    x = sessions(17)
    x = x[x.session_index != 5].reset_index(drop=True)
    result = m.evaluate("trend_rider", {"X": x}, config())
    assert not result["components"][-2]["eligible"]


def test_orb_raw_opening_rvol_rank_entry_and_doji():
    x = sessions(15, native=True)
    first = int(x.open_ts_ms.iloc[0])
    d = daily(70)
    for col in ["open_ts_ms", "close_ts_ms", "available_ts_ms"]:
        d[col] += first - 35 * 86_400_000
    cfg = dict(
        timeframe_min=30,
        mode_id="stocks_in_play_orb_v1",
        session_source=dict(
            source_ref="synthetic:NYSE",
            timezone="America/New_York",
            market="US_EQUITY_REGULAR",
        ),
        daily_frames={"X": d},
        universe_snapshot=dict(
            source_ref="synthetic:listed",
            sha256="a" * 64,
            symbols=["X"],
            symbols_sha256=hashlib.sha256(
                json.dumps(["X"], separators=(",", ":")).encode()
            ).hexdigest(),
            volume_unit="SHARES",
            available_ts_ms=0,
        ),
    )
    last = x.index[x.session_index == 14][0]
    x.loc[last, "volume"] = 300
    result = m.evaluate("break_and_continue", {"X": x}, cfg)
    assert len(result["intents"]) == 1
    order = result["intents"][0]
    assert order["trigger_price"] == 103
    assert order["protective_stop"] is None
    assert order["stop_distance_from_actual_fill"] == pytest.approx(0.4)
    assert order["feature_available_ts_ms"] == int(x.loc[last, "close_ts_ms"])
    x.loc[last, "close"] = 100
    assert not m.evaluate("break_and_continue", {"X": x}, cfg)["intents"]


def test_rbreaker_reference_is_fixed_across_midnight_and_current_high():
    x = sessions(1)
    x["open_ts_ms"] += 2 * 86_400_000 + 23 * 3600_000
    x["close_ts_ms"] += 2 * 86_400_000 + 23 * 3600_000
    x["available_ts_ms"] += 2 * 86_400_000 + 23 * 3600_000
    x["session_open_ts_ms"] += 2 * 86_400_000 + 23 * 3600_000
    x["session_close_ts_ms"] += 2 * 86_400_000 + 23 * 3600_000
    d = daily(1)
    cfg = config()
    cfg["daily_frames"] = {"X": d}
    r = m.evaluate("rbreaker_like", {"X": x}, cfg)
    assert r["components"][0]["levels"] == r["components"][1]["levels"]
    assert r["components"][0]["source_bar_timeframe_min"] == 1


def test_noise_delayed_available_has_no_invented_full_bar_exposure():
    x = sessions()
    x.loc[len(x) - 2, "close"] = 110.0
    x.loc[len(x) - 2, "high"] = 111.0
    x.loc[len(x) - 2, "available_ts_ms"] += 1000
    result = m.evaluate("trend_rider", {"X": x}, config())
    assert result["components"][-1]["exposure_for_current_bar"] is None


def test_overlap_is_not_relabelled_as_a_gap():
    x = bars(2)
    x.loc[1, "open_ts_ms"] = 450000
    x.loc[1, "close_ts_ms"] = 1350000
    with pytest.raises(ValueError, match="STRICT_BAR"):
        m.evaluate("squeeze_break", {"X": x}, dict(timeframe_min=15))


@pytest.mark.parametrize("bad", [float("nan"), -1, 1.5, True])
def test_daily_timestamp_must_be_finite_integer(bad):
    d = daily()
    d["available_ts_ms"] = d.available_ts_ms.astype(object)
    d.loc[1, "available_ts_ms"] = bad
    with pytest.raises(ValueError):
        m.evaluate(
            "turtle_trend",
            {"X": bars(1, start=60 * 86_400_000)},
            dict(timeframe_min=15, daily_frames={"X": d}),
        )


@pytest.mark.parametrize("bad", [-1, float("nan"), float("inf")])
def test_daily_volume_invalid_not_selectable(bad):
    d = daily()
    d.loc[0, "volume"] = bad
    with pytest.raises(ValueError):
        m.evaluate(
            "turtle_trend",
            {"X": bars(1, start=60 * 86_400_000)},
            dict(timeframe_min=15, daily_frames={"X": d}),
        )


def test_rbreaker_eod_rejects_missing_or_future_position_proof():
    prev = dict(
        high=110, low=90, close=100, available_ts_ms=0, source_ref="synthetic:prior"
    )
    for position in [
        dict(qty_base=2),
        dict(qty_base=2, fill_id="future", fill_ts_ms=1900000),
    ]:
        with pytest.raises(ValueError):
            m.rbreaker_native_plan(
                bars(30, tf=1), prev, position, session_close_ts_ms=1900000
            )


def test_noise_stop_selection_is_in_rule_digest():
    cfg = config()
    a = m.evaluate("trend_rider", {"X": sessions()}, cfg)
    cfg["noise_stop_mode"] = "OPPOSITE_BAND"
    b = m.evaluate("trend_rider", {"X": sessions()}, cfg)
    assert a["rule_digest"] != b["rule_digest"]
    assert "OPPOSITE_BAND" in b["rules"][0]["expression"]


def test_orb_subset_cannot_claim_snapshot_membership():
    x = sessions(15, native=True)
    first = int(x.open_ts_ms.iloc[0])
    d = daily(70)
    for col in ["open_ts_ms", "close_ts_ms", "available_ts_ms"]:
        d[col] += first - 35 * 86_400_000
    cfg = dict(
        timeframe_min=30,
        mode_id="stocks_in_play_orb_v1",
        session_source=dict(
            source_ref="synthetic:NYSE",
            timezone="America/New_York",
            market="US_EQUITY_REGULAR",
        ),
        daily_frames={"X": d},
        universe_snapshot=dict(
            source_ref="synthetic:PIT",
            sha256="a" * 64,
            volume_unit="SHARES",
            available_ts_ms=0,
            symbols=["X", "OMITTED"],
            symbols_sha256="a" * 64,
        ),
    )
    with pytest.raises(ValueError, match="UNIVERSE_MEMBERSHIP"):
        m.evaluate("break_and_continue", {"X": x}, cfg)


def test_daily_interval_overlap_is_rejected_without_24h_assumption():
    d = daily()
    d.loc[1, "open_ts_ms"] = 1
    with pytest.raises(ValueError, match="DAILY_ORDER"):
        m.evaluate(
            "turtle_trend",
            {"X": bars(1, start=60 * 86_400_000)},
            dict(timeframe_min=15, daily_frames={"X": d}),
        )


def test_fractional_calendar_availability_is_not_truncated():
    x = sessions()
    x["session_known_ts_ms"] = x.session_known_ts_ms.astype(float)
    x.loc[0, "session_known_ts_ms"] = 0.5
    with pytest.raises(ValueError, match="INTEGER_TIMESTAMP"):
        m.evaluate("trend_rider", {"X": x}, config())
