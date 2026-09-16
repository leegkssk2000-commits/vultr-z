from copy import deepcopy

import pandas as pd
import pytest

from backend.research.rebuild import scalp7_source_components_v1 as mod
from backend.research.rebuild import scalp7_execution_v2 as engine

TF = 1_800_000


def bar(i, o=101.0, h=103.0, low=100.0, c=102.0):
    return dict(
        open_ts_ms=i * TF,
        close_ts_ms=(i + 1) * TF,
        available_ts_ms=(i + 1) * TF,
        feature_available_ts_ms=(i + 1) * TF,
        segment_id=0,
        open=o,
        high=h,
        low=low,
        close=c,
    )


def signal(variant="PB"):
    return dict(
        identity=mod.IDENTITIES[variant],
        lane="squeeze_break",
        symbol="X",
        timeframe_min=30,
        signal_open_ts_ms=0,
        signal_ts_ms=TF,
        segment_id=0,
        side=1,
        stop_price=80.0,
        max_hold_bars=11,
        meta=dict(
            component_variant=variant,
            component="UNCHANGED_PARENT_EVENT",
            be_arm_r=None,
            frozen_cost_bps=14.0,
            fallback_stop_atr_mult=2.0,
            entry_cost_gate=dict(atr_price=10.0, min_ratio=4.0),
        ),
    )


def sequence():
    return [
        bar(0, h=110, low=95, c=108),
        bar(1, h=109, low=100, c=105),
        bar(2, o=107, h=112, low=105, c=111),
        bar(3, o=106, h=111, low=101, c=105),
        bar(4, o=108, h=113, low=104, c=112),
    ]


def test_two_attempts_required_and_one_signal_only():
    rows = sequence()
    state = mod.SecondSignal(dict(signal_ts_ms=TF, segment_id=0), 95)
    emitted = [state.observe(row, rows[i - 1]) for i, row in enumerate(rows) if i]
    assert emitted == [0, 0, 0, 4]
    assert state.pull_low == 100
    assert state.observe(bar(5, h=120, c=118), rows[-1]) == 0


@pytest.mark.parametrize("failure", ["gap", "segment", "floor", "expiry"])
def test_invalid_context_cannot_emit(failure):
    state = mod.SecondSignal(dict(signal_ts_ms=TF, segment_id=0), 95, stage=3)
    row, prev = bar(4, h=120, c=119), bar(3)
    if failure == "gap":
        prev["close_ts_ms"] -= TF
    if failure == "segment":
        row["segment_id"] = 1
    if failure == "floor":
        row.update(low=90, close=94)
    if failure == "expiry":
        row.update(open_ts_ms=12 * TF, close_ts_ms=13 * TF)
    assert state.observe(row, prev) == 0
    assert state.consumed


def test_stop_gap_rejects_supplement_not_invents_wider_stop():
    sig = signal("PA")
    sig["meta"]["component"] = "BROOKS_SECOND_SIGNAL_TRANSLATION"
    assert mod.entry_update(sig, 79)["reject"]


def test_fee_guard_not_relaxed_and_identity_not_mutated():
    sig = signal()
    before = deepcopy(sig)
    assert mod.entry_update(sig, 100)["stop_price"] == 80
    assert mod.entry_update(sig, 10000)["reject"]
    assert sig == before


def test_thrust_failure_exits_next_open_not_decision_close():
    rows = [bar(i, o=100, h=101, low=99.5, c=100) for i in range(7)]
    rows[5].update(open=99, low=98)
    result = engine.replay(
        [signal()],
        {"X": pd.DataFrame(rows)},
        {"X": 14.0},
        exit_update=mod.exit_update,
        entry_update=mod.entry_update,
    )
    trade = result["trades"][0]
    assert trade["exit_ts_ms"] == 5 * TF
    assert trade["exit_prices"]["X"] == 99
    assert trade["reason"] == "CARTER_THRUST4_NET_FAILURE"
    assert trade["net_bps"] == pytest.approx(-114)


@pytest.mark.parametrize(
    "variant,close,expected",
    [("PA", 100, False), ("PB", 100, True), ("PAB", 102, False)],
)
def test_thrust_is_variant_scoped(variant, close, expected):
    hist = pd.DataFrame([bar(i, c=close) for i in range(5)])
    pos = dict(
        signal=signal(variant),
        side=1,
        entry_ts_ms=TF,
        entry_price=100.0,
        initial_risk=20.0,
        hold_bars=4,
        mfe_R=0.1,
        cost_bps=14.0,
    )
    before = deepcopy(pos)
    out = mod.exit_update(pos, hist.iloc[-1].to_dict(), hist)
    assert out["exit_next_open"] == expected
    assert pos == before


def test_stop_precedes_thrust():
    rows = [bar(i, o=100, h=101, low=99, c=100) for i in range(7)]
    rows[4]["low"] = 70
    result = engine.replay(
        [signal()],
        {"X": pd.DataFrame(rows)},
        {"X": 14.0},
        exit_update=mod.exit_update,
        entry_update=mod.entry_update,
    )
    assert result["trades"][0]["reason"] == "STOP_FIRST"


def test_future_data_does_not_change_prior_sequence():
    rows = sequence()

    def collect(xs):
        st = mod.SecondSignal(dict(signal_ts_ms=TF, segment_id=0), 95)
        return [st.observe(r, xs[i - 1]) for i, r in enumerate(xs) if i]

    assert collect(rows) == collect(rows + [bar(5, h=200, c=190)])[:4]
