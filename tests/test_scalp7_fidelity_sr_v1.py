"""Source-derived SR cases; every numerical candle below is a logical fixture."""

from __future__ import annotations

import importlib
import inspect
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

sr: Any = importlib.import_module("backend.research.rebuild.scalp7_fidelity_sr_v1")
engine: Any = importlib.import_module("backend.research.rebuild.scalp7_execution_v2")


def candles(*, short: bool = False, volume: float = 110.0) -> pd.DataFrame:
    rows = [
        {"open": 99.0, "high": 100.0, "low": 98.0, "close": 99.0, "volume": 100.0}
        for _ in range(122)
    ]
    rows.extend(
        [
            {"open": 99.0, "high": 103.0, "low": 99.0, "close": 102.0, "volume": 100.0},
            {
                "open": 102.0,
                "high": 102.5,
                "low": 99.5,
                "close": 101.0,
                "volume": volume,
            },
        ]
    )
    if short:
        for row in rows:
            row.update(
                open=200 - row["open"],
                high=200 - row["low"],
                low=200 - row["high"],
                close=200 - row["close"],
            )
    for i, row in enumerate(rows):
        row.update(
            open_ts_ms=i * sr.TF_MS,
            close_ts_ms=(i + 1) * sr.TF_MS,
            available_ts_ms=(i + 1) * sr.TF_MS,
            segment_id=1,
        )
    return pd.DataFrame(rows)


@pytest.mark.parametrize("short", [False, True])
def test_frozen_prior_level_reclaim_source_case(short):
    x = candles(short=short)
    assert sr.generate_signals({"TEST": x}, identity=sr.CONTROL) == []
    signals = sr.generate_signals({"TEST": x}, identity=sr.CHILD)
    assert len(signals) == 1
    event = signals[0]
    assert event["side"] == (-1 if short else 1)
    assert event["meta"]["mode"] == "BREAK_RECLAIM"
    assert event["meta"]["reference"] == 100.0
    assert event["meta"]["reference_open_ts_ms"] == int(x.iloc[-2].open_ts_ms)
    assert event["signal_ts_ms"] == int(x.iloc[-1].available_ts_ms)


def test_actual_native_control_masks_match_without_invoking_economics():
    raw = candles()
    raw.loc[123, ["high", "close", "volume"]] = [104.0, 103.5, 150.0]
    prepared = sr._prepare(raw)
    actual = sr.native.signal_masks("sr_levels", prepared)
    control = sr.signal_masks(prepared, False)
    for parent, translated in zip(actual, control):
        pd.testing.assert_series_equal(parent, translated, check_names=False)
    a = sr.generate_signals({"TEST": raw}, identity=sr.CONTROL)
    b = sr.generate_signals({"TEST": raw}, identity=sr.CHILD)
    # Keep current low above prebreak level so this is solely continuation.
    raw.loc[123, "low"] = 100.5
    a = sr.generate_signals({"TEST": raw}, identity=sr.CONTROL)
    b = sr.generate_signals({"TEST": raw}, identity=sr.CHILD)
    assert a[0]["meta"]["mode"] == b[0]["meta"]["mode"] == "CONTINUATION"
    for key in ("side", "stop_price", "signal_ts_ms", "take_profit_r", "max_hold_bars"):
        assert a[0][key] == b[0][key]


@pytest.mark.parametrize("short", [False, True])
def test_touch_without_recovery_is_not_reclaim(short):
    x = candles(short=short)
    x.loc[123, "close"] = 100.0
    assert sr.generate_signals({"TEST": x}, identity=sr.CHILD) == []


def test_missing_participation_and_noncanonical_volume_block():
    assert sr.generate_signals({"TEST": candles(volume=50)}, identity=sr.CHILD) == []
    with pytest.raises(ValueError, match="REAL_CANONICAL_VOLUME_REQUIRED"):
        sr.generate_signals(
            {"TEST": candles().drop(columns="volume")}, identity=sr.CHILD
        )
    raw = candles()
    raw.loc[123, "volume"] = float("nan")
    with pytest.raises(ValueError, match="SR_VOLUME_INVALID"):
        sr.generate_signals({"TEST": raw}, identity=sr.CHILD)


def test_event_order_and_gap_causality():
    raw = candles()
    swapped = raw.copy()
    fields = ["open", "high", "low", "close", "volume"]
    swapped.loc[[122, 123], fields] = raw.loc[[123, 122], fields].to_numpy()
    assert sr.generate_signals({"TEST": swapped}, identity=sr.CHILD) == []
    gap = raw.copy()
    for key in ("open_ts_ms", "close_ts_ms", "available_ts_ms"):
        gap.loc[123, key] += sr.TF_MS
    assert sr.generate_signals({"TEST": gap}, identity=sr.CHILD) == []


def test_prefix_independence_preparation_and_late_availability():
    raw = candles()
    expected = sr.generate_signals({"TEST": raw}, identity=sr.CHILD)
    extra = raw.iloc[-1].copy()
    extra["open_ts_ms"] += sr.TF_MS
    extra["close_ts_ms"] += sr.TF_MS
    extra["available_ts_ms"] += sr.TF_MS
    full = pd.concat([raw, pd.DataFrame([extra])], ignore_index=True)
    assert [
        s
        for s in sr.generate_signals({"TEST": full}, identity=sr.CHILD)
        if s["signal_open_ts_ms"] <= int(raw.iloc[-1].open_ts_ms)
    ] == expected
    prepared = sr.prepare_frames({"TEST": raw})
    assert (
        sr.generate_signals(prepared, costs={"TEST": 14}, identity=sr.CHILD) == expected
    )
    raw.loc[122, "available_ts_ms"] = int(raw.iloc[-1].close_ts_ms) + 1
    late = sr.generate_signals({"TEST": raw}, identity=sr.CHILD)
    assert late[0]["signal_ts_ms"] > int(raw.iloc[-1].close_ts_ms)


def position(mfe=0.5):
    return {
        "signal": {"identity": sr.CHILD, "segment_id": 1},
        "entry_price": 100.0,
        "entry_ts_ms": 0,
        "side": 1,
        "initial_risk": 2.0,
        "mfe_R": mfe,
    }


def closed_bar(minutes):
    return {
        "segment_id": 1,
        "close_ts_ms": minutes * 60_000,
        "available_ts_ms": minutes * 60_000,
    }


def test_elapsed_lifecycle_observation_not_bar_multiplication():
    assert not sr.exit_update(position(0.1), closed_bar(24), pd.DataFrame())[
        "exit_next_open"
    ]
    scratch = sr.exit_update(position(0.1), closed_bar(30), pd.DataFrame())
    assert scratch == {"exit_next_open": True, "reason": "SR_SCRATCH_ELAPSED_25M"}
    assert not sr.exit_update(position(), closed_bar(90), pd.DataFrame())[
        "exit_next_open"
    ]
    assert sr.exit_update(position(), closed_bar(120), pd.DataFrame()) == {
        "exit_next_open": True,
        "reason": "SR_TIMEOUT_ELAPSED_95M",
    }
    trail = sr.exit_update(position(1.1), closed_bar(30), sr._prepare(candles()))
    assert "next_stop" in trail
    assert not trail["exit_next_open"]


@pytest.mark.parametrize(
    ("old", "new", "fixture_volume", "expect_long"),
    [
        ('frame["prebreak_hi50"] if child else high', "high", 110.0, True),
        ("& (rv >= 1.0)", "& True", 50.0, False),
        ("& (c > reclaim_high)", "& True", 110.0, False),
    ],
)
def test_critical_rule_mutations_are_killed(old, new, fixture_volume, expect_long):
    raw = candles(volume=fixture_volume)
    if old == "& (c > reclaim_high)":
        raw.loc[123, "close"] = 100.0
    prepared = sr._prepare(raw)
    original = sr.signal_masks(prepared, True)[0].iloc[-1]
    assert bool(original) is expect_long
    source = inspect.getsource(sr.signal_masks)
    assert old in source
    namespace = dict(sr.__dict__)
    exec(source.replace(old, new), namespace)
    mutant = namespace["signal_masks"](prepared, True)[0].iloc[-1]
    assert bool(mutant) is not expect_long


def test_shared_engine_scratch_is_next_open_and_stop_is_causal():
    raw = candles()
    signal = sr.generate_signals({"TEST": raw}, identity=sr.CHILD)[0]
    entry = raw.iloc[-1].to_dict()
    entry.update(
        open_ts_ms=124 * sr.TF_MS,
        close_ts_ms=125 * sr.TF_MS,
        available_ts_ms=125 * sr.TF_MS,
        open=101.0,
        high=101.1,
        low=100.8,
        close=101.0,
    )
    later = entry.copy()
    later.update(
        open_ts_ms=125 * sr.TF_MS,
        close_ts_ms=126 * sr.TF_MS,
        available_ts_ms=126 * sr.TF_MS,
        open=100.9,
        high=101.1,
        low=100.8,
        close=101.0,
    )
    full = pd.concat([raw, pd.DataFrame([entry, later])], ignore_index=True)
    out = engine.replay(
        [signal],
        sr.prepare_frames({"TEST": full}),
        {"TEST": 14.0},
        identity=sr.CHILD,
        exit_update=sr.exit_update,
    )
    assert len(out["trades"]) == 1
    row = out["trades"][0]
    assert row["exit_ts_ms"] == int(later["open_ts_ms"])
    assert row["reason"] == "SR_SCRATCH_ELAPSED_25M"


def test_expected_cases_file_frozen_before_implementation():
    path = Path(__file__).resolve().parents[1] / (
        "research/campaigns/scalp7_20260917/source_fidelity_v1/"
        "audits/SOURCE_EXPECTED_CASES_SR.json"
    )
    import hashlib

    assert hashlib.sha256(path.read_bytes()).hexdigest() == (
        "2e0bd5b1c86b0b5d19c62c63e8f5023f3045ab9fb55b55db0892f8b1c8a7716a"
    )


@pytest.mark.parametrize("short", [False, True])
def test_frozen_new_trail_applies_only_next_bar(short):
    raw = candles()
    event = raw.iloc[-1].to_dict()
    event.update(
        open_ts_ms=124 * sr.TF_MS,
        close_ts_ms=125 * sr.TF_MS,
        available_ts_ms=125 * sr.TF_MS,
        open=101.0,
        high=104.5,
        low=99.5,
        close=103.0,
    )
    later = dict(event)
    later.update(
        open_ts_ms=125 * sr.TF_MS,
        close_ts_ms=126 * sr.TF_MS,
        available_ts_ms=126 * sr.TF_MS,
        open=101.5,
        high=101.7,
        low=100.0,
        close=101.0,
    )
    full = pd.concat([raw, pd.DataFrame([event, later])], ignore_index=True)
    if short:
        old_high = full.high.copy()
        full["open"] = 200 - full.open
        full["high"] = 200 - full.low
        full["low"] = 200 - old_high
        full["close"] = 200 - full.close
    prepared = sr.prepare_frames({"TEST": full})
    signal = sr.generate_signals({"TEST": full.iloc[:124]}, identity=sr.CHILD)[0]
    side = signal["side"]
    entry_bar = prepared["TEST"].iloc[124]
    peak = entry_bar.high if side == 1 else entry_bar.low
    trail = peak - side * 1.7 * entry_bar.atr
    # The arming bar crosses this new stop; it must nevertheless survive.
    assert entry_bar.low < trail < entry_bar.high
    out = engine.replay(
        [signal],
        prepared,
        {"TEST": 14.0},
        identity=sr.CHILD,
        exit_update=sr.exit_update,
    )
    assert len(out["trades"]) == 1
    trade = out["trades"][0]
    assert trade["reason"] == "STOP_FIRST"
    assert trade["exit_ts_ms"] == 126 * sr.TF_MS
    assert trade["exit_prices"]["TEST"] == pytest.approx(trail)
    assert trade["hold_bars"] == 2


@pytest.mark.parametrize("mutation", ["FUTURE_REFERENCE", "CARRY_ACROSS_GAP"])
def test_frozen_causality_mutations_are_killed(monkeypatch, mutation):
    raw = candles()
    source = inspect.getsource(sr._prepare)
    if mutation == "FUTURE_REFERENCE":
        old = 'g["prebreak_hi50"] = g["hi50"].shift(1)'
        new = 'g["prebreak_hi50"] = g["hi50"].shift(-1)'
        assert len(sr.generate_signals({"TEST": raw}, identity=sr.CHILD)) == 1
        expected_count = 1
    else:
        for key in ("open_ts_ms", "close_ts_ms", "available_ts_ms"):
            raw.loc[123, key] += sr.TF_MS
        old = "x = material._prepare(frame)"
        new = old + '\n    x["_local_segment"] = 0'
        assert sr.generate_signals({"TEST": raw}, identity=sr.CHILD) == []
        expected_count = 0
    assert old in source
    namespace = dict(sr.__dict__)
    exec(source.replace(old, new), namespace)
    monkeypatch.setattr(sr, "_prepare", namespace["_prepare"])
    assert len(sr.generate_signals({"TEST": raw}, identity=sr.CHILD)) != expected_count


@pytest.mark.parametrize(
    ("old", "new", "volume", "recover", "expected"),
    [
        ('frame["prebreak_lo50"] if child else low', "low", 110.0, True, True),
        ("& (rv >= 1.0)", "& True", 50.0, True, False),
        ("& (c < reclaim_low)", "& True", 110.0, False, False),
    ],
)
def test_short_critical_rule_mutations_are_killed(old, new, volume, recover, expected):
    raw = candles(short=True, volume=volume)
    if not recover:
        raw.loc[123, "close"] = 100.0
    prepared = sr._prepare(raw)
    assert bool(sr.signal_masks(prepared, True)[1].iloc[-1]) is expected
    source = inspect.getsource(sr.signal_masks)
    assert old in source
    namespace = dict(sr.__dict__)
    exec(source.replace(old, new), namespace)
    assert bool(namespace["signal_masks"](prepared, True)[1].iloc[-1]) is not expected


@pytest.mark.parametrize("short", [False, True])
def test_native_mode_override_order_is_preserved(short):
    raw = candles()
    raw.loc[123, ["high", "close", "volume"]] = [104.5, 104.0, 150.0]
    if short:
        old_high = raw.high.copy()
        raw["open"] = 200 - raw.open
        raw["high"] = 200 - raw.low
        raw["low"] = 200 - old_high
        raw["close"] = 200 - raw.close
    control = sr.generate_signals({"TEST": raw}, identity=sr.CONTROL)[0]
    child = sr.generate_signals({"TEST": raw}, identity=sr.CHILD)[0]
    assert control["meta"]["mode"] == "CONTINUATION"
    assert child["meta"]["mode"] == "BREAK_RECLAIM"
    assert child["meta"]["reference"] == 100.0
    for key in ("stop_price", "side", "take_profit_r", "max_hold_bars", "exit_policy"):
        assert control[key] == child[key]


def test_ambiguous_side_masks_are_rejected(monkeypatch):
    def ambiguous(frame, child):
        mask = pd.Series(False, index=frame.index)
        mask.iloc[-1] = True
        return mask, mask.copy(), pd.Series("BREAK_RECLAIM", index=frame.index)

    monkeypatch.setattr(sr, "signal_masks", ambiguous)
    assert sr.generate_signals({"TEST": candles()}, identity=sr.CHILD) == []


@pytest.mark.parametrize("identity", sr.IDENTITIES)
def test_shared_zero_volume_denominator_is_undefined_not_infinite_signal(identity):
    # Pre-execution input integrity case authorized after independent review;
    # not an author example, threshold change, or altered frozen source case.
    raw = candles()
    raw["volume"] = 0.0
    raw.loc[122, "volume"] = 1.0
    prepared = sr._prepare(raw)
    assert prepared.loc[121, "volume"] == 0.0
    assert prepared.loc[122, "rel_vol50"] == float("inf")
    assert sr.generate_signals({"TEST": raw}, identity=identity) == []
