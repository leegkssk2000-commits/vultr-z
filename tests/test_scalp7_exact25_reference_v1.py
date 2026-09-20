"""Hand-computed source/causality examples. No market or economic execution."""

from copy import deepcopy

import pandas as pd
import pytest

from backend.research.rebuild import scalp7_exact25_reference_v1 as ref

STEP = 900000


def bars(values, start=0, step=STEP):
    return pd.DataFrame(
        [
            {
                "open_ts_ms": start + i * step,
                "close_ts_ms": start + (i + 1) * step,
                "available_ts_ms": start + (i + 1) * step,
                "segment_id": "s1",
                "open": o,
                "high": h,
                "low": low,
                "close": c,
                "volume": 1.0,
                "volume_base": 1.0,
                "volume_quote": c,
            }
            for i, (o, h, low, c) in enumerate(values)
        ]
    )


def config(mode, **extra):
    return {
        "timeframe_min": 15,
        "source_clock": "SYNTHETIC_TEST_COMPLETED_BAR",
        "symbol": "TEST-USDT",
        "mode_id": mode,
        "hypothesis_id": "HAND_COMPUTED_FIXTURE",
        "rationale": "Explicit nonmarket test choices, not source defaults",
        **extra,
    }


def avconfig(mode="FIXED_AVWAP_COMPONENT", **extra):
    return config(
        mode,
        anchor_event_ts_ms=0,
        anchor_known_ts_ms=STEP,
        anchor_id="fixed-event",
        volume_basis="BASE_QUOTE_SUMS",
        volume_unit="BASE",
        intent_ttl_bars=2,
        **extra
    )


def evaluate(strategy, frame, conf):
    return ref.evaluate(strategy, {"TEST-USDT": frame}, conf)


def test_exact_five_catalog_and_no_promotion():
    assert set(ref.catalog()) == {
        "anchor_vwap_trend",
        "fvg_revert",
        "liquidity_sweep",
        "sr_levels",
        "vwap_revert",
    }
    assert all(not x["complete_strategy"] for x in ref.catalog().values())


def test_quote_base_true_accumulation_hand_arithmetic():
    frame = bars([(10, 12, 8, 10), (12, 14, 10, 12)])
    frame.loc[1, ["volume_base", "volume_quote"]] = [3, 36]
    out = evaluate("anchor_vwap_trend", frame, avconfig())
    assert [x["value"] for x in out["components"]] == [10, 11.5]
    assert out["rule_digest"] and not out["intents"]


def test_anchor_known_time_hides_past_and_suffix_no_repaint():
    frame = bars([(10, 12, 8, 10), (12, 14, 10, 12), (14, 16, 12, 14)])
    conf = avconfig()
    conf["anchor_known_ts_ms"] = 2 * STEP
    out = evaluate("anchor_vwap_trend", frame, conf)
    assert out["components"][0]["available_ts_ms"] == 2 * STEP
    assert out["components"][0]["value"] == 11
    prefix = evaluate("anchor_vwap_trend", frame.iloc[:2], conf)
    assert prefix["components"] == out["components"][:1]


def test_anchor_lookup_window_invariant_and_no_window_anchor_substitution():
    frame = bars([(8, 10, 6, 8), (10, 12, 8, 10), (12, 14, 10, 12)])
    conf = avconfig()
    conf.update(anchor_event_ts_ms=STEP, anchor_known_ts_ms=2 * STEP)
    full = evaluate("anchor_vwap_trend", frame, conf)
    sliced = evaluate("anchor_vwap_trend", frame.iloc[1:], conf)
    assert full["components"] == sliced["components"]
    missing = evaluate("anchor_vwap_trend", frame.iloc[2:], conf)
    assert missing["status"].startswith("BLOCKED")


def test_hlc3_proxy_not_trade_vwap_and_zero_volume_no_fill():
    frame = bars([(10, 14, 8, 11), (10, 12, 8, 10)])
    conf = avconfig()
    conf["volume_basis"] = "HLC3_BASE_PROXY"
    frame.loc[0, "volume"] = 0
    out = evaluate("anchor_vwap_trend", frame, conf)
    assert out["components"][0]["value"] is None
    assert out["components"][1]["value"] == 10
    assert not out["components"][1]["trade_vwap_claim"]


@pytest.mark.parametrize(
    "change",
    [
        {"volume_unit": "QUOTE"},
        {"volume_basis": "ROLLING_HLC3"},
        {"anchor_known_ts_ms": 0},
    ],
)
def test_vwap_bad_units_basis_recognition_blocks(change):
    conf = avconfig()
    conf.update(change)
    assert evaluate("anchor_vwap_trend", bars([(10, 12, 8, 10)]), conf)[
        "status"
    ].startswith("BLOCKED")


def test_vwap_mixed_units_and_numerator_validation():
    frame = bars([(10, 12, 8, 10)])
    frame["volume_unit"] = "QUOTE"
    assert not evaluate("anchor_vwap_trend", frame, avconfig())["components"]
    frame["volume_unit"] = "BASE"
    frame["volume_quote"] = 999
    assert not evaluate("anchor_vwap_trend", frame, avconfig())["components"]


def test_vwap_gap_does_not_bridge_fixed_anchor():
    frame = bars([(10, 12, 8, 10)] * 3).drop(index=1)
    out = evaluate("anchor_vwap_trend", frame, avconfig())
    assert len(out["components"]) == 1
    assert out["events"][0]["event"] == "ANCHOR_CUMULATION_GAP_BLOCKED"


def test_reclaim_numerical_entry_follows_below_state():
    frame = bars([(10, 12, 8, 10), (9, 10, 8, 9), (10, 12, 9, 11)])
    out = evaluate("anchor_vwap_trend", frame, avconfig("AVWAP_RECLAIM"))
    assert len(out["intents"]) == 1
    intent = out["intents"][0]
    assert intent["feature_available_ts_ms"] == 3 * STEP
    assert intent["protective_stop"] == 8
    assert intent["order_kind"] == "NEXT_OPEN"
    assert intent["lifecycle_gap"]


def test_failed_retest_is_sequence_not_distance():
    frame = bars([(10, 12, 8, 10), (12, 14, 10, 12), (10, 11, 8, 9), (9, 11, 8, 9)])
    conf = avconfig("VWAP_FAILED_RETEST_SHORT")
    out = evaluate("vwap_revert", frame, conf)
    assert [x["event"] for x in out["events"]] == [
        "VWAP_BREAKDOWN",
        "VWAP_RETEST_FAILURE_CONFIRMED",
    ]
    assert len(out["intents"]) == 1 and out["intents"][0]["side"] == -1
    assert not evaluate("vwap_revert", frame.iloc[:3], conf)["intents"]
    trend = bars([(10, 12, 8, 10), (20, 22, 18, 20), (30, 32, 28, 30)])
    assert not evaluate("vwap_revert", trend, conf)["intents"]


@pytest.mark.parametrize(
    "values,side,lower,upper",
    [
        ([(10, 11, 9, 10), (11, 14, 10, 13), (14, 16, 12, 15)], 1, 11, 12),
        ([(14, 15, 13, 14), (12, 14, 10, 11), (10, 12, 8, 9)], -1, 12, 13),
    ],
)
def test_fvg_source_geometry_and_third_completion(values, side, lower, upper):
    frame = bars(values)
    conf = config("THREE_BAR_GEOMETRY")
    out = evaluate("fvg_revert", frame, conf)
    assert out["components"][0]["side"] == side
    assert (out["components"][0]["lower"], out["components"][0]["upper"]) == (
        lower,
        upper,
    )
    assert out["components"][0]["available_ts_ms"] == 3 * STEP
    assert not out["intents"]
    assert not evaluate("fvg_revert", frame.iloc[:2], conf)["components"]


def test_fvg_overlap_or_gap_not_geometry():
    frame = bars([(10, 12, 8, 10)] * 3)
    conf = config("THREE_BAR_GEOMETRY")
    assert not evaluate("fvg_revert", frame, conf)["components"]
    frame = bars([(10, 11, 9, 10), (11, 14, 10, 13), (14, 16, 12, 15)])
    frame.loc[1:, "segment_id"] = "s2"
    assert not evaluate("fvg_revert", frame, conf)["components"]


def fvg_config():
    return config(
        "SWEEP_MSS_FVG_REVISIT",
        swing_left=1,
        swing_right=1,
        setup_expiry_bars=8,
        displacement_min_body_fraction=0.5,
    )


def fvg_path():
    return bars(
        [
            (10, 11, 9, 10),
            (11, 13, 10, 12),
            (10, 12, 8, 9),
            (10, 12, 9, 11),
            (9, 11, 7, 9),
            (10, 15, 9, 14),
            (15, 17, 14, 16),
            (15, 16, 13, 14),
        ]
    )


def test_fvg_actual_sweep_mss_grammar_and_future_touch_not_fill():
    out = evaluate("fvg_revert", fvg_path(), fvg_config())
    events = [r["event"] for r in out["events"]]
    assert "PRIOR_LEVEL_SWEEP" in events and "MSS_DISPLACEMENT_CONFIRMED" in events
    assert "ZONE_TOUCH_NOT_OBSERVED_FILL" in events
    assert len(out["intents"]) == 1
    order = out["intents"][0]
    assert order["order_kind"] == "LIMIT" and order["trigger_price"] == 14
    assert (
        order["protective_stop"] == 7 and order["feature_available_ts_ms"] == 7 * STEP
    )
    assert not out["complete_strategy"]


def test_gap_only_does_not_pass_full_fvg_and_future_suffix_stable():
    frame = bars([(10, 11, 9, 10), (11, 14, 10, 13), (14, 16, 12, 15)])
    assert not evaluate("fvg_revert", frame, fvg_config())["intents"]
    whole = evaluate("fvg_revert", fvg_path(), fvg_config())
    prefix = evaluate("fvg_revert", fvg_path().iloc[:7], fvg_config())
    assert prefix["intents"] == whole["intents"]


def test_fvg_missing_displacement_choice_item_only_block():
    conf = fvg_config()
    del conf["displacement_min_body_fraction"]
    assert evaluate("fvg_revert", fvg_path(), conf)["status"].startswith("BLOCKED")


def box_config():
    return config(
        "BOX_RETEST_RECLAIM",
        reference_start_ts_ms=0,
        reference_end_ts_ms=2 * STEP,
        reference_known_ts_ms=2 * STEP,
        reference_id="box-fixed",
        reference_type="DECLARED_PRIOR_BOX",
        intent_ttl_bars=2,
    )


def test_fixed_box_current_breakout_excluded_and_future_retest():
    frame = bars([(10, 12, 8, 10), (10, 11, 9, 10), (13, 15, 12, 14), (13, 14, 11, 13)])
    out = evaluate("sr_levels", frame, box_config())
    assert out["components"][0]["upper"] == 12
    assert [r["event"] for r in out["events"]] == [
        "FIXED_REFERENCE_BREAKOUT",
        "FIXED_REFERENCE_RETEST_RECLAIM",
    ]
    assert out["intents"][0]["protective_stop"] == 8
    assert out["intents"][0]["feature_available_ts_ms"] == 4 * STEP
    assert not evaluate("sr_levels", frame.iloc[:3], box_config())["intents"]


def test_box_failure_keeps_original_box_and_no_scratch():
    frame = bars(
        [
            (10, 12, 8, 10),
            (10, 11, 9, 10),
            (13, 15, 12, 14),
            (12, 14, 9, 10),
            (13, 20, 12, 19),
        ]
    )
    out = evaluate("sr_levels", frame, box_config())
    assert not out["intents"]
    assert out["events"][-1]["event"] == "BOX_REENTRY_FAILURE"
    assert out["components"][0]["upper"] == 12


def test_box_incomplete_reference_or_unknown_level_blocks():
    frame = bars([(10, 12, 8, 10)] * 4)
    conf = box_config()
    conf["reference_known_ts_ms"] = STEP
    assert evaluate("sr_levels", frame, conf)["status"].startswith("BLOCKED")
    assert evaluate("sr_levels", frame.drop(index=1), box_config())[
        "status"
    ].startswith("BLOCKED")


def soup_inputs(age=5):
    day = 86400000
    values = [(100, 105, 95, 100)] * 20
    values[20 - age] = (95, 100, 90, 95)
    daily = bars(values, step=day)
    daily["session_index"] = range(20)
    start = 20 * day
    intraday = bars([(92, 93, 89, 91), (92, 93, 90, 92)], start=start)
    conf = config(
        "TURTLE_SOUP_DAILY_LONG",
        source_timeframe="1d",
        daily_calendar="EXPLICIT_SESSIONS",
        daily_frames={"TEST-USDT": daily},
        tick_size=0.1,
        entry_offset_ticks=5,
        stop_buffer_ticks=1,
        session_bounds=[
            {"session_id": "today", "open_ts_ms": start, "close_ts_ms": start + day}
        ],
    )
    return intraday, conf


def test_soup_native_daily_age_and_tick_order_same_day_cancel():
    frame, conf = soup_inputs()
    out = evaluate("liquidity_sweep", frame, conf)
    assert out["components"][0]["age_daily_sessions"] == 5
    assert len(out["intents"]) == 1
    intent = out["intents"][0]
    assert intent["trigger_price"] == 90.5 and intent["protective_stop"] == 88.9
    assert intent["expires_ts_ms"] == 21 * 86400000
    assert intent["order_kind"] == "STOP_MARKET"
    assert intent["feature_available_ts_ms"] == 20 * 86400000 + STEP


@pytest.mark.parametrize("age,eligible", [(3, False), (4, True), (20, True)])
def test_soup_extreme_age_days_not_intraday_bars(age, eligible):
    frame, conf = soup_inputs(age)
    assert bool(evaluate("liquidity_sweep", frame, conf)["intents"]) == eligible


def test_soup_recent_tied_extreme_invalidates_old_age():
    frame, conf = soup_inputs()
    daily = conf["daily_frames"]["TEST-USDT"]
    daily.loc[19, "low"] = 90
    out = evaluate("liquidity_sweep", frame, conf)
    assert out["components"][0]["age_daily_sessions"] == 1
    assert not out["intents"]


def test_soup_does_not_silently_use_twenty_intraday_bars():
    frame, conf = soup_inputs()
    del conf["daily_frames"]
    assert evaluate("liquidity_sweep", frame, conf)["status"].startswith("BLOCKED")
    frame, conf = soup_inputs()
    conf["source_timeframe"] = "15m"
    assert evaluate("liquidity_sweep", frame, conf)["status"].startswith("BLOCKED")


def test_soup_missing_daily_session_no_signal():
    frame, conf = soup_inputs()
    conf["daily_frames"]["TEST-USDT"].loc[10, "session_index"] = 9
    assert evaluate("liquidity_sweep", frame, conf)["status"].startswith("BLOCKED")


def test_soup_last_session_bar_cannot_retroactively_submit():
    frame, conf = soup_inputs()
    conf["session_bounds"][0]["close_ts_ms"] = int(frame.iloc[0].close_ts_ms)
    out = evaluate("liquidity_sweep", frame.iloc[:1], conf)
    assert not out["intents"]
    assert out["events"][-1]["event"] == "ORDER_EXPIRED_BEFORE_KNOWN"


def bbo():
    return pd.DataFrame(
        [
            {
                "ts_ms": i,
                "available_ts_ms": i,
                "sequence": i,
                "segment_id": "bbo1",
                "bid": bid,
                "ask": ask,
                "bid_size": bs,
                "ask_size": qs,
            }
            for i, (bid, ask, bs, qs) in enumerate(
                [(100, 102, 5, 4), (100, 102, 7, 3), (101, 103, 2, 6)]
            )
        ]
    )


def ofconfig():
    return config(
        "GENUINE_BBO_OFI_COMPONENT",
        genuine_bbo=True,
        source_receipt_sha256="a" * 64,
        volume_unit="BASE",
    )


def test_cont_ofi_hand_arithmetic_and_no_trade_claim():
    out = ref.evaluate("liquidity_sweep", {"bbo": bbo()}, ofconfig())
    assert [x["value"] for x in out["components"]] == [3, 5]
    assert not out["intents"] and not out["complete_strategy"]


def test_ofi_sequence_gap_no_synthetic_bridge():
    frame = bbo()
    frame.loc[2, "sequence"] = 5
    out = ref.evaluate("liquidity_sweep", {"bbo": frame}, ofconfig())
    assert len(out["components"]) == 1
    assert out["events"][-1]["event"] == "BBO_SEQUENCE_RESET_NO_BRIDGE"


def test_ofi_ohlc_and_unproven_input_block():
    conf = ofconfig()
    conf["genuine_bbo"] = False
    assert ref.evaluate("liquidity_sweep", {"bbo": bbo()}, conf)["status"].startswith(
        "BLOCKED"
    )
    assert ref.evaluate(
        "liquidity_sweep", {"decision": bars([(10, 12, 8, 10)])}, ofconfig()
    )["status"].startswith("BLOCKED")


@pytest.mark.parametrize(
    "field,value",
    [("open_ts_ms", -0.5), ("available_ts_ms", 1), ("high", float("nan")), ("low", 50)],
)
def test_integrity_invalid_data_no_partial_intents(field, value):
    frame = bars([(10, 12, 8, 10)] * 2).astype(object)
    frame.loc[1, field] = value
    out = evaluate("anchor_vwap_trend", frame, avconfig())
    assert out["status"].startswith("BLOCKED") and not out["intents"]


def test_symbol_isolation_and_no_mutation():
    frame = bars([(10, 12, 8, 10)])
    before = deepcopy(frame)
    conf = avconfig()
    conf["symbol_configs"] = {"BAD": {"volume_unit": "QUOTE"}}
    out = ref.evaluate("anchor_vwap_trend", {"GOOD": frame, "BAD": frame}, conf)
    pd.testing.assert_frame_equal(frame, before)
    assert out["status"] == "PARTIAL_SYMBOLS_BLOCKED"
    assert [x["symbol"] for x in out["components"]] == ["GOOD"]


def test_soup_daily_label_cannot_disguise_intraday_bar_duration():
    frame, conf = soup_inputs()
    daily = conf["daily_frames"]["TEST-USDT"]
    daily["close_ts_ms"] = daily["open_ts_ms"] + STEP
    daily["available_ts_ms"] = daily["close_ts_ms"]
    result = evaluate("liquidity_sweep", frame, conf)
    assert result["status"].startswith("BLOCKED")
    assert not result["intents"]
