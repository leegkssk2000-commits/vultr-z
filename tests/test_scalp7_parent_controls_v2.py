from __future__ import annotations

from copy import deepcopy
import importlib
import math
from typing import Any

import pandas as pd  # type: ignore[import-untyped]
import pytest

from backend.research.rebuild import scalp7_parent_controls_v2 as control


def frame(tf: int = 15, n: int = 180) -> pd.DataFrame:
    rows = []
    for i in range(n):
        c = 100 + i * 0.1 + math.sin(i * 0.8) * 0.4
        rows.append(
            {
                "open_ts_ms": i * tf * 60000,
                "close_ts_ms": (i + 1) * tf * 60000,
                "available_ts_ms": (i + 1) * tf * 60000,
                "segment_id": "a",
                "open": c - 0.1,
                "high": c + 1,
                "low": c - 1,
                "close": c,
                "volume": 10 + i % 5,
            }
        )
    return pd.DataFrame(rows)


@pytest.mark.parametrize("lane", list(control.TIMEFRAMES))
def test_binding_and_original_event_grammar_identity(lane: str) -> None:
    f = frame(control.TIMEFRAMES[lane])
    actual = control.generate_signals({"BTC-USDT": f}, lane)
    spec = deepcopy(control._freeze()["lanes"][lane]["source_spec"])
    spec["child_id"] = control.IDENTITIES[lane]
    x = control._features(control._validate(f, control.TIMEFRAMES[lane] * 60000))
    state = control.sm.MachineState()
    expected = []
    for i in range(101, len(x)):
        emitted = control.sm.step_machine(lane, state, x, i, spec)
        if emitted is not None:
            expected.append(emitted.signal_ts)
    assert [s["signal_open_ts_ms"] for s in actual] == expected
    for s in actual:
        assert s["identity"] == control.IDENTITIES[lane]
        assert s["timeframe_min"] in (15, 30)
        assert s["meta"]["control_kind"] == control.CONTROL_KIND
        assert s["meta"]["opportunity_state_advances_while_engine_busy"]
        assert s["max_hold_bars"] == spec["lifecycle"]["timeout_bars"] + 1


def test_minimal_price_features_match_original_definitions() -> None:
    legacy: Any = importlib.import_module(
        "backend.research.rebuild.a1_benchmark25_donor_native_replay_v1"
    )
    f = frame()
    inherited = legacy.enrich(f.assign(ts_ms=f.open_ts_ms))
    actual = control._features(f)
    for key in [
        "atr",
        "ema8",
        "ema21",
        "ema50",
        "ema55",
        "ema100",
        "hi20",
        "lo20",
        "hi50",
        "lo50",
        "mean20",
        "sd20",
        "bb_width_atr",
        "bb_prev_width_atr",
    ]:
        pd.testing.assert_series_equal(actual[key], inherited[key], check_names=False)


def test_no_volume_or_outcome_features_affect_opportunities() -> None:
    f = frame()
    before = control.generate_signals({"BTC-USDT": f})
    assert before
    f["volume"] = float("nan")
    f["net_bps"] = 1000000
    f["future_return"] = -1000000
    assert control.generate_signals({"BTC-USDT": f}) == before


def test_gap_resets_full_warmup_and_never_bridges_pending_machine() -> None:
    f = frame(n=180)
    f.loc[90:, "segment_id"] = "b"
    assert control.generate_signals({"BTC-USDT": f}) == []
    f = frame(n=180).drop(index=90)
    assert control.generate_signals({"BTC-USDT": f}) == []


def test_unseen_suffix_cannot_change_prefix_and_late_data_delays_availability() -> None:
    f = frame()
    prefix = control.generate_signals({"BTC-USDT": f.iloc[:150]})
    altered = f.copy()
    altered.loc[150:, ["open", "high", "low", "close"]] *= 2
    result = control.generate_signals({"BTC-USDT": altered})
    assert [s for s in result if s["signal_open_ts_ms"] < 150 * 900000] == prefix
    f.loc[90, "available_ts_ms"] = 500 * 900000
    assert all(
        s["signal_ts_ms"] == 500 * 900000
        for s in control.generate_signals({"BTC-USDT": f})
    )


@pytest.mark.parametrize("lane", list(control.TIMEFRAMES))
def test_actual_entry_price_controls_original_stop_risk_and_partial(lane: str) -> None:
    bound = control._freeze()["lanes"][lane]
    signal = {
        "identity": control.IDENTITIES[lane],
        "side": 1,
        "invalidation_price": 99.0,
        "take_profit_r": bound["source_spec"]["lifecycle"]["target_r"],
        "partial_take_profit_r": bound["partial_take_profit_r"],
        "partial_fraction": bound["partial_fraction"],
        "meta": {"atr_at_signal": 2.0, "source_spec": bound["source_spec"]},
    }
    result = control.entry_update(signal, 110)
    expected = (
        98.6
        if lane == "break_and_continue"
        else 110 - 2 * bound["source_spec"]["risk"]["stop_atr_mult"]
    )
    assert result["stop_price"] == pytest.approx(expected)
    assert result["initial_risk"] == pytest.approx(110 - expected)
    assert result["partial_fraction"] == (0.25 if lane == "break_and_continue" else 0.2)
    if lane == "break_and_continue":
        fallback = control.entry_update(signal, 98)
        assert fallback["stop_price"] == 96


def position(
    lane: str = "trend_rider", side: int = 1
) -> tuple[dict[str, Any], dict[str, Any]]:
    bound = control._freeze()["lanes"][lane]
    tf = control.TIMEFRAMES[lane] * 60000
    signal = {
        "identity": control.IDENTITIES[lane],
        "signal_open_ts_ms": 100 * tf,
        "side": side,
        "segment_id": "a",
        "invalidation_price": 90 if side == 1 else 110,
        "partial_take_profit_r": bound["partial_take_profit_r"],
        "partial_fraction": bound["partial_fraction"],
        "meta": {
            "atr_at_signal": 2.0,
            "close_at_signal": 100.0,
            "source_spec": deepcopy(bound["source_spec"]),
        },
    }
    pos = {
        "signal": signal,
        "entry_ts_ms": 101 * tf,
        "entry_price": 100.0,
        "initial_risk": 2.0,
        "side": side,
        "stop_price": 98 if side == 1 else 102,
        "hold_bars": 1,
        "mfe_R": 2.5,
    }
    bar = {
        "open_ts_ms": 101 * tf,
        "close_ts_ms": 102 * tf,
        "available_ts_ms": 102 * tf,
        "segment_id": "a",
        "open": 100.0,
        "high": 105.0,
        "low": 99.0,
        "close": 104.0,
    }
    return pos, bar


def test_partial_is_predeclared_once_and_trail_does_not_loosen() -> None:
    p, b = position()
    result = control.exit_update(p, b, pd.DataFrame([b]))
    assert result["partial_fraction"] == 0.2
    assert result["partial_price"] == 104
    assert result["next_stop"] >= p["stop_price"]
    p["stop_price"] = result["next_stop"]
    b = {
        **b,
        "open_ts_ms": b["open_ts_ms"] + 900000,
        "close_ts_ms": b["close_ts_ms"] + 900000,
        "available_ts_ms": b["available_ts_ms"] + 900000,
    }
    second = control.exit_update(p, b, pd.DataFrame([b]))
    assert "partial_fraction" not in second
    assert second["next_stop"] >= result["next_stop"]


def test_resting_partial_crossed_at_gap_uses_declared_target() -> None:
    p, b = position()
    b.update({"open": 105.0, "high": 106.0, "low": 104.5, "close": 105.5})
    result = control.exit_update(p, b, pd.DataFrame([b]))
    assert result["partial_price"] == 104


def test_structure_failure_precedes_partial_and_scratch_is_next_open() -> None:
    p, b = position()
    p["signal"]["invalidation_price"] = 102
    b["close"] = 100.0
    result = control.exit_update(p, b, pd.DataFrame([b]))
    assert result["exit_next_open"]
    assert result["reason"] == "STRUCTURE_INVALIDATION_NEXT_OPEN"
    assert "partial_fraction" not in result
    p, b = position()
    p["mfe_R"] = 0.2
    p["hold_bars"] = 8
    result = control.exit_update(p, b, pd.DataFrame([b]))
    assert result["exit_next_open"]
    assert result["reason"] == "NO_PROGRESS_SCRATCH_NEXT_OPEN"


def test_exit_atr_matches_full_prefix_and_future_gap_rejected() -> None:
    f = frame()
    signal = control.generate_signals({"BTC-USDT": f})[0]
    i = int(signal["signal_open_ts_ms"] // 900000) + 1
    entry = float(f.iloc[i].open)
    geometry = control.entry_update(signal, entry)
    p = {
        "signal": signal,
        "entry_ts_ms": i * 900000,
        "entry_price": entry,
        "initial_risk": geometry["initial_risk"],
        "stop_price": geometry["stop_price"],
        "side": signal["side"],
        "hold_bars": 1,
        "mfe_R": 0.1,
    }
    b = f.iloc[i].to_dict()
    with pytest.raises(ValueError, match="FUTURE_HISTORY"):
        control.exit_update(p, b, f)
    control.exit_update(p, b, f.iloc[: i + 1])
    assert p["_parent_control_state"]["atr"] == pytest.approx(
        control._features(f).iloc[i].atr
    )
    b = f.iloc[i + 2].to_dict()
    assert control.exit_update(p, b, f.iloc[: i + 3])["reason"] == "DATA_GAP_HOLD"


@pytest.mark.parametrize("identity", ["legacy_active5_1h", "micro_edge", "break_5m"])
def test_legacy_and_wrong_control_identity_rejected(identity: str) -> None:
    with pytest.raises(ValueError, match="UNKNOWN_CURRENT_LANE"):
        control.generate_signals({"BTC-USDT": frame()}, identity)


def test_wrong_timeframe_and_noncausal_timestamp_rejected() -> None:
    with pytest.raises(ValueError, match="WRONG_UTC_TIMEFRAME"):
        control.generate_signals({"BTC-USDT": frame(60)})
    f = frame()
    f.loc[0, "available_ts_ms"] = 0
    with pytest.raises(ValueError, match="UNAVAILABLE"):
        control.generate_signals({"BTC-USDT": f})
