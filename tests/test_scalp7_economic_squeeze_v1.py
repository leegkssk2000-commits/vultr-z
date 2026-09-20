"""Source-first synthetic cases; no historical data or economic-budget execution."""

from copy import deepcopy

import pandas as pd
import pytest

from backend.research.rebuild import scalp7_economic_squeeze_v1 as sq
from backend.research.rebuild import scalp7_execution_v2 as engine

SYMBOL = "BTC-USDT"
COSTS = {SYMBOL: 14.0}


def bars(n=32):
    records = []
    for i in range(n):
        records.append(
            {
                "open_ts_ms": i * sq.TF_MS,
                "close_ts_ms": (i + 1) * sq.TF_MS,
                "available_ts_ms": (i + 1) * sq.TF_MS,
                "segment_id": "actual-a",
                "open": 101.0,
                "high": 103.0,
                "low": 100.0,
                "close": 101.0,
            }
        )
    records[0]["low"] = 90.0
    return pd.DataFrame(records)


def thirty(frame):
    rows = frame.to_dict("records")
    return pd.DataFrame(
        [
            {
                "open_ts_ms": a["open_ts_ms"],
                "close_ts_ms": b["close_ts_ms"],
                "available_ts_ms": max(a["available_ts_ms"], b["available_ts_ms"]),
                "segment_id": "30m-a",
                "open": a["open"],
                "high": max(a["high"], b["high"]),
                "low": min(a["low"], b["low"]),
                "close": b["close"],
            }
            for a, b in zip(rows[::2], rows[1::2])
        ]
    )


def origin(available=None):
    return {
        "identity": sq.parent.SQUEEZE_PARENT,
        "lane": "squeeze_break",
        "symbol": SYMBOL,
        "timeframe_min": 30,
        "signal_open_ts_ms": 0,
        "signal_ts_ms": 2 * sq.TF_MS if available is None else available,
        "segment_id": "30m-a",
        "side": 1,
        "stop_price": 95.0,
        "max_hold_bars": 11,
        "take_profit_r": None,
        "meta": {
            "spec_sha256": sq.parent.SPEC_SHA256,
            "regime": "PANIC_DISPERSION",
            "frozen_cost_bps": 14.0,
            "atr_price": 2.0,
            "entry_cost_gate": {"atr_price": 2.0, "min_ratio": 4.0},
            "fallback_stop_atr_mult": 2.0,
            "be_arm_r": None,
        },
    }


def prepared(monkeypatch, frame=None, fire=None):
    frame = bars() if frame is None else frame
    fire = origin() if fire is None else fire

    def exact_parent(frames, *, costs, identities):
        assert costs == COSTS
        assert identities == (sq.parent.SQUEEZE_PARENT,)
        assert frames[SYMBOL].equals(thirty(frame))
        return [deepcopy(fire)]

    monkeypatch.setattr(sq.parent, "generate_signals", exact_parent)
    return sq.prepare_frames({SYMBOL: frame}, {SYMBOL: thirty(frame)}, COSTS)


def high2_bars():
    frame = bars()
    # Pullback, High1, lower high, High2; High2 deliberately bearish with
    # a close below the prior high. All lows remain above original fire low90.
    observations = [
        (101.0, 102.0, 99.5, 100.5),
        (101.0, 104.0, 100.0, 101.5),
        (101.0, 103.0, 99.8, 101.0),
        (102.0, 104.0, 99.6, 100.5),
    ]
    for index, values in enumerate(observations, start=2):
        frame.loc[index, ["open", "high", "low", "close"]] = values
    return frame


def state():
    fire = origin()
    fire["meta"].update(
        origin_fire_ts_ms=2 * sq.TF_MS,
        origin_fire_available_ts_ms=2 * sq.TF_MS,
        origin_fire_low=90.0,
        origin_execution_segment_id="actual-a",
    )
    return sq.High2State(fire, "actual-a")


def test_exact_parent_call_control_clock_and_origin_metadata(monkeypatch):
    frames = prepared(monkeypatch)
    signals = sq.generate_signals(frames, COSTS, sq.CONTROL)
    assert len(signals) == 1
    signal = signals[0]
    assert signal["signal_open_ts_ms"] == sq.TF_MS
    assert signal["signal_ts_ms"] == 2 * sq.TF_MS
    assert signal["timeframe_min"] == 15 and signal["max_hold_bars"] == 22
    assert signal["stop_price"] == 95
    assert signal["meta"]["origin_fire_ts_ms"] == 2 * sq.TF_MS
    assert signal["meta"]["absolute_deadline_ts_ms"] == 24 * sq.TF_MS
    assert signal["meta"]["be_arm_r"] is None
    engine.validate_signal(signal)


def test_high2_wick_trigger_bearish_close_and_remaining_life(monkeypatch):
    frames = prepared(monkeypatch, high2_bars())
    signals = sq.generate_signals(frames, COSTS, sq.HIGH2)
    assert len(signals) == 1
    signal = signals[0]
    assert signal["signal_ts_ms"] == 6 * sq.TF_MS
    assert signal["stop_price"] == 99.5 and signal["max_hold_bars"] == 18
    assert [x["stage"] for x in signal["meta"]["setup_trace"]] == [
        "PULLBACK",
        "HIGH1",
        "LOWER_HIGH",
        "HIGH2",
    ]
    assert signal["meta"]["origin_fire_ts_ms"] == 2 * sq.TF_MS
    engine.validate_signal(signal)


def test_consecutive_highs_without_lower_high_do_not_emit(monkeypatch):
    frame = high2_bars()
    for i in range(4, len(frame)):
        frame.loc[i, "high"] = 105 + i
    assert sq.generate_signals(prepared(monkeypatch, frame), COSTS, sq.HIGH2) == []


def test_outside_bar_cannot_cascade_and_inside_alone_not_pullback():
    previous = bars().iloc[1].to_dict()
    outside = bars().iloc[2].to_dict()
    outside.update(low=99.0, high=105.0)
    pending = state()
    assert not pending.observe(outside, previous)
    assert pending.stage == 1
    assert not state().observe({**outside, "low": 100.0, "high": 102.0}, previous)


@pytest.mark.parametrize(
    "mutation", ["breach", "gap", "segment", "late", "zero_momentum"]
)
def test_invalidation_precedes_high2_trigger(mutation):
    rows = high2_bars().to_dict("records")
    pending = state()
    for i in range(2, 5):
        assert not pending.observe(rows[i], rows[i - 1])
    trigger = deepcopy(rows[5])
    if mutation == "breach":
        trigger["low"] = 89.0
    elif mutation == "gap":
        trigger["open_ts_ms"] += sq.TF_MS
    elif mutation == "segment":
        trigger["segment_id"] = "different"
    elif mutation == "late":
        trigger["available_ts_ms"] += 1
    else:
        trigger["c30_momentum"] = 0.0
    assert not pending.observe(trigger, rows[4]) and pending.consumed


def test_equal_origin_low_is_not_invalidation():
    rows = high2_bars().to_dict("records")
    pending = state()
    rows[2]["low"] = 90.0
    for i in range(2, 6):
        emitted = pending.observe(rows[i], rows[i - 1])
    assert emitted and pending.pull_low == 90.0
    assert not pending.observe(rows[6], rows[5])


@pytest.mark.parametrize("elapsed,expected", [(20, True), (21, False)])
def test_setup_expiry_exactly_300_minutes(elapsed, expected):
    pending = state()
    pending.stage, pending.pull_low = 3, 99.0
    row = bars().iloc[elapsed + 1].to_dict()
    previous = bars().iloc[elapsed].to_dict()
    row["high"] = 105.0
    assert pending.observe(row, previous) is expected


def test_new_fire_cancels_old_high2_first(monkeypatch):
    frames = prepared(monkeypatch, high2_bars())
    frame = frames[SYMBOL]
    new_fire = deepcopy(frame.iloc[1]["squeeze_visible_fires"][0])
    new_fire["meta"]["origin_fire_ts_ms"] = 6 * sq.TF_MS
    new_fire["meta"]["origin_fire_available_ts_ms"] = 6 * sq.TF_MS
    frame.at[5, "squeeze_visible_fires"] = [new_fire]
    signals = sq.generate_signals(frames, COSTS, sq.HIGH2)
    assert not any(s["signal_ts_ms"] == 6 * sq.TF_MS for s in signals)


def test_delayed_fire_does_not_backcount_setup_or_reset_deadline(monkeypatch):
    frame = high2_bars()
    fire = origin(available=5 * sq.TF_MS + 1)
    frames = prepared(monkeypatch, frame, fire)
    assert frames[SYMBOL].iloc[4]["squeeze_visible_fires"] == []
    assert frames[SYMBOL].iloc[5]["squeeze_visible_fires"]
    assert sq.generate_signals(frames, COSTS, sq.HIGH2) == []
    control = sq.generate_signals(frames, COSTS, sq.CONTROL)[0]
    assert control["signal_ts_ms"] == 5 * sq.TF_MS + 1
    assert control["meta"]["absolute_deadline_ts_ms"] == 24 * sq.TF_MS
    replay = engine.replay(
        [control],
        frames,
        COSTS,
        identity=sq.CONTROL,
        exit_update=sq.exit_update,
        entry_update=sq.entry_update,
    )
    assert replay["rejections"]["LATE_OBSERVATION_NOT_HISTORICAL_OPEN_FILL"] == 1


def test_cost_at_fill_and_wrong_side_structure_no_fallback(monkeypatch):
    frames = prepared(monkeypatch, high2_bars())
    child = sq.generate_signals(frames, COSTS, sq.HIGH2)[0]
    assert sq.entry_update(child, 99.5)["reject"]
    assert sq.entry_update(child, 99.4)["reason"] == "HIGH2_ENTRY_INVALIDATES_STRUCTURE"
    assert sq.entry_update(child, 100.0)["stop_price"] == 99.5
    expensive = deepcopy(child)
    expensive["meta"]["entry_cost_gate"]["atr_price"] = 0.1
    assert sq.entry_update(expensive, 100.0)["reason"] == "ENTRY_ATR_COST_GATE"
    control = sq.generate_signals(frames, COSTS, sq.CONTROL)[0]
    control["stop_price"] = 105.0
    assert sq.entry_update(control, 100.0)["stop_price"] == 96.0


def momentum_bar(opened, entry, *, previous_open=None, values=(3.0, 2.0, 1.0)):
    row = bars().iloc[opened].to_dict()
    row.update(
        c30_close_ts_ms=row["close_ts_ms"],
        c30_feature_available_ts_ms=row["close_ts_ms"],
        c30_previous_open_ts_ms=entry if previous_open is None else previous_open,
        c30_momentum_prev2=values[0],
        c30_momentum_prev1=values[1],
        c30_momentum=values[2],
    )
    pos = {"signal": {"identity": sq.HIGH2}, "entry_ts_ms": entry}
    return pos, row, pd.DataFrame([row])


def test_momentum_needs_two_positive_decreases_and_postentry_complete_bars():
    pos, row, history = momentum_bar(5, 3 * sq.TF_MS, previous_open=2 * sq.TF_MS)
    assert not sq.exit_update(pos, row, history)["exit_next_open"]
    pos, row, history = momentum_bar(7, 3 * sq.TF_MS, previous_open=4 * sq.TF_MS)
    assert sq.exit_update(pos, row, history)["exit_next_open"]
    for values in ((1, 3, 2), (3, 2, 0), (3, 0, -1)):
        pos, row, history = momentum_bar(7, 3 * sq.TF_MS, values=values)
        assert not sq.exit_update(pos, row, history)["exit_next_open"]


def test_repeated_context_is_not_second_observation():
    pos, row, history = momentum_bar(7, 3 * sq.TF_MS)
    assert sq.exit_update(pos, row, history)["exit_next_open"]
    assert not sq.exit_update(pos, row, history)["exit_next_open"]


def test_future_context_and_future_prefix_rejected():
    pos, row, history = momentum_bar(7, 3 * sq.TF_MS)
    row["c30_feature_available_ts_ms"] += 1
    with pytest.raises(ValueError, match="FUTURE_30M"):
        sq.exit_update(pos, row, history)
    row["c30_feature_available_ts_ms"] -= 1
    history.loc[0, "available_ts_ms"] += 1
    with pytest.raises(ValueError, match="FUTURE_EXECUTION_PREFIX"):
        sq.exit_update(pos, row, history)


def test_context_joins_only_after_available_and_uses_complete_halves(monkeypatch):
    frame = bars()
    context = thirty(frame)
    context.loc[1, "available_ts_ms"] += sq.TF_MS + 1
    monkeypatch.setattr(sq.parent, "generate_signals", lambda *a, **k: [])
    out = sq.prepare_frames({SYMBOL: frame}, {SYMBOL: context}, COSTS)[SYMBOL]
    assert out.iloc[3]["c30_close_ts_ms"] == 2 * sq.TF_MS
    assert out.iloc[4]["c30_close_ts_ms"] == 2 * sq.TF_MS
    assert out.iloc[5]["c30_close_ts_ms"] == 6 * sq.TF_MS
    context.loc[0, "high"] += 1
    with pytest.raises(ValueError, match="OHLC_MISMATCH"):
        sq.prepare_frames({SYMBOL: frame}, {SYMBOL: context}, COSTS)


def test_prefix_signals_invariant_to_future_prices(monkeypatch):
    frame = high2_bars()
    before = sq.generate_signals(prepared(monkeypatch, frame), COSTS, sq.HIGH2)
    altered = frame.copy()
    altered.loc[6:, ["open", "high", "low", "close"]] *= 2
    after = sq.generate_signals(prepared(monkeypatch, altered), COSTS, sq.HIGH2)
    assert before == after


def test_engine_absolute_deadline_and_stop_first(monkeypatch):
    frames = prepared(monkeypatch)
    control = sq.generate_signals(frames, COSTS, sq.CONTROL)[0]
    replay = engine.replay(
        [control],
        frames,
        COSTS,
        identity=sq.CONTROL,
        exit_update=sq.exit_update,
        entry_update=sq.entry_update,
    )
    assert replay["trades"][0]["exit_ts_ms"] == 24 * sq.TF_MS
    assert replay["trades"][0]["hold_bars"] == 22
    frames[SYMBOL].loc[2, "low"] = 94.0

    def forbidden_callback(*args):
        raise AssertionError("stop must precede callback")

    replay = engine.replay(
        [control],
        frames,
        COSTS,
        identity=sq.CONTROL,
        exit_update=forbidden_callback,
        entry_update=sq.entry_update,
    )
    assert replay["trades"][0]["reason"] == "STOP_FIRST"


def test_prepared_frame_and_cost_binding_rejected(monkeypatch):
    with pytest.raises(ValueError, match="PREPARED_FRAME"):
        sq.generate_signals({SYMBOL: bars()}, COSTS)
    frames = prepared(monkeypatch)
    with pytest.raises(ValueError, match="PREPARED_COST"):
        sq.generate_signals(frames, {SYMBOL: 15})


@pytest.mark.parametrize("invalidation", ["fire_low", "nonpositive_momentum"])
def test_delayed_activation_cancels_known_invalid_context(monkeypatch, invalidation):
    frame = bars()
    if invalidation == "fire_low":
        frame.loc[5, "low"] = 89.0
    for target, source in zip(range(7, 11), range(2, 6)):
        frame.loc[target, ["open", "high", "low", "close"]] = high2_bars().loc[
            source, ["open", "high", "low", "close"]
        ]
    frames = prepared(monkeypatch, frame, origin(available=5 * sq.TF_MS + 1))
    if invalidation == "nonpositive_momentum":
        frames[SYMBOL].loc[5, "c30_momentum"] = 0.0
    assert sq.generate_signals(frames, COSTS, sq.HIGH2) == []


def test_missing_context_bar_rejected_even_if_15m_complete(monkeypatch):
    frame = bars()
    context = thirty(frame).drop(index=1).reset_index(drop=True)
    monkeypatch.setattr(sq.parent, "generate_signals", lambda *a, **k: [])
    with pytest.raises(ValueError, match="CONTEXT_COVERAGE_MISMATCH"):
        sq.prepare_frames({SYMBOL: frame}, {SYMBOL: context}, COSTS)
