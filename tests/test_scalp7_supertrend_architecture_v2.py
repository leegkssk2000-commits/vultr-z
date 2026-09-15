from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd  # type: ignore[import-untyped]
import pytest

from backend.research.rebuild import scalp7_supertrend_architecture_v2 as st


def fixture_frame() -> pd.DataFrame:
    rows = []
    prices = [(99.8 + i, 100.4 + i, 99.4 + i, 100.0 + i) for i in range(10)]
    prices += [
        (109.2, 111.5, 109.2, 111.0),
        (111.0, 111.4, 110.0, 110.8),
        (110.8, 112.4, 110.7, 112.0),
        (112.0, 113.4, 112.0, 113.0),
        (113.0, 113.1, 112.4, 112.8),
        (112.8, 114.4, 112.7, 114.0),
    ]
    for i, (op, hi, lo, cl) in enumerate(prices):
        rows.append(
            {
                "open_ts_ms": i * st.TIMEFRAME_MS,
                "close_ts_ms": (i + 1) * st.TIMEFRAME_MS,
                "available_ts_ms": (i + 1) * st.TIMEFRAME_MS,
                "segment_id": "a",
                "open": op,
                "high": hi,
                "low": lo,
                "close": cl,
                "volume": 10.0,
            }
        )
    return pd.DataFrame(rows)


def signals(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return st.generate_signals({"BTC-USDT": frame})


def test_frozen_spec_hash_and_identity_are_bound() -> None:
    path = (
        Path(__file__).resolve().parents[1]
        / "research/campaigns/scalp7_20260915/broad_v2/supertrend/SUPERTREND_ARCHITECTURE_FREEZE_V2.json"
    )
    assert hashlib.sha256(path.read_bytes()).hexdigest() == st.FREEZE_SHA256
    spec = json.loads(path.read_text())
    assert spec["identity"] == st.IDENTITY
    assert spec["economic_runs_before_freeze"] == 0


def test_requires_separate_impulse_pullback_and_reclaim_bars() -> None:
    f = fixture_frame()
    assert signals(f.iloc[:12]) == []
    result = signals(f)
    assert [s["signal_open_ts_ms"] for s in result] == [
        12 * st.TIMEFRAME_MS,
        15 * st.TIMEFRAME_MS,
    ]
    first = result[0]
    assert first["meta"]["impulse_open_ts_ms"] == 10 * st.TIMEFRAME_MS
    assert first["meta"]["pullback_open_ts_ms"] == 11 * st.TIMEFRAME_MS
    assert first["signal_ts_ms"] == 13 * st.TIMEFRAME_MS
    assert first["stop_price"] == pytest.approx(109.2)
    assert first["timeframe_min"] == 30
    assert first["max_hold_bars"] == 16


def test_distinct_continuations_allowed_in_same_native_trend() -> None:
    result = signals(fixture_frame())
    assert len(result) == 2
    assert {s["side"] for s in result} == {1}
    assert (
        result[0]["meta"]["impulse_open_ts_ms"]
        != result[1]["meta"]["impulse_open_ts_ms"]
    )


def test_short_grammar_is_directionally_symmetric() -> None:
    f = fixture_frame()
    old = f.copy()
    f["open"], f["close"] = 250 - old["open"], 250 - old["close"]
    f["high"], f["low"] = 250 - old["low"], 250 - old["high"]
    result = signals(f)
    assert [s["signal_open_ts_ms"] for s in result] == [
        12 * st.TIMEFRAME_MS,
        15 * st.TIMEFRAME_MS,
    ]
    assert {s["side"] for s in result} == {-1}
    assert result[0]["stop_price"] == pytest.approx(140.8)


def test_future_suffix_cannot_change_frozen_prefix_signals_or_features() -> None:
    f = fixture_frame()
    prefix = signals(f.iloc[:13])
    altered = f.copy()
    altered.loc[13:, ["open", "high", "low", "close"]] *= 2
    assert [
        s for s in signals(altered) if s["signal_open_ts_ms"] <= 12 * st.TIMEFRAME_MS
    ] == prefix
    assert st.indicator_rows(f.iloc[:13]) == st.indicator_rows(altered)[:13]


def test_gap_and_segment_change_reset_warmup_and_pending_setup() -> None:
    f = fixture_frame()
    assert signals(f.drop(index=11)) == []
    f.loc[12:, "segment_id"] = "b"
    assert signals(f) == []


def test_origin_failure_cancels_pending_reclaim() -> None:
    f = fixture_frame()
    f.loc[11, ["open", "high", "low", "close"]] = [111.0, 111.4, 108.8, 109.0]
    result = signals(f.iloc[:13])
    assert result == []


def test_signal_availability_includes_late_prior_feature_bar() -> None:
    f = fixture_frame()
    f.loc[10, "available_ts_ms"] = 14 * st.TIMEFRAME_MS
    assert signals(f)[0]["signal_ts_ms"] == 14 * st.TIMEFRAME_MS


@pytest.mark.parametrize(
    "case",
    [
        "wrong_tf",
        "off_grid",
        "early_available",
        "negative_price",
        "bad_ohlc",
        "duplicate",
        "missing_segment",
        "missing_field",
    ],
)
def test_invalid_input_fails_closed(case: str) -> None:
    f = fixture_frame()
    if case == "wrong_tf":
        f.loc[0, "close_ts_ms"] = 900000
    elif case == "off_grid":
        f.loc[0, "open_ts_ms"] = 1
    elif case == "early_available":
        f.loc[0, "available_ts_ms"] = 1
    elif case == "negative_price":
        f.loc[0, "low"] = -1
    elif case == "bad_ohlc":
        f.loc[0, "high"] = 1
    elif case == "duplicate":
        f.loc[1, "open_ts_ms"] = 0
    elif case == "missing_segment":
        f.loc[0, "segment_id"] = None
    elif case == "missing_field":
        f = f.drop(columns=["available_ts_ms"])
    with pytest.raises(ValueError):
        signals(f)


def make_position() -> tuple[pd.DataFrame, dict[str, Any]]:
    f = fixture_frame()
    signal = signals(f)[0]
    entry = float(f.iloc[13]["open"])
    return f, {
        "signal": deepcopy(signal),
        "entry_price": entry,
        "entry_ts_ms": 13 * st.TIMEFRAME_MS,
        "side": 1,
        "initial_stop": signal["stop_price"],
        "initial_risk": entry - signal["stop_price"],
        "stop_price": signal["stop_price"],
        "hold_bars": 1,
        "mfe_R": 0,
        "mae_R": 0,
    }


def test_exit_native_state_updates_match_closed_prefix_exactly_and_do_not_loosen() -> (
    None
):
    f, p = make_position()
    first = st.exit_update(p, f.iloc[13].to_dict(), f.iloc[:14])
    assert not first["exit_next_open"]
    assert first["next_stop"] >= p["stop_price"]
    assert (
        p["_scalp7_supertrend_state"]
        == st.indicator_rows(f.iloc[:14])[-1]["native_state"]
    )
    p["stop_price"] = first["next_stop"]
    second = st.exit_update(p, f.iloc[14].to_dict(), f.iloc[:15])
    assert second["next_stop"] >= first["next_stop"]
    assert (
        p["_scalp7_supertrend_state"]
        == st.indicator_rows(f.iloc[:15])[-1]["native_state"]
    )


def test_exit_update_is_idempotent_for_same_closed_bar() -> None:
    f, p = make_position()
    before_signal = deepcopy(p["signal"])
    a = st.exit_update(p, f.iloc[13].to_dict(), f.iloc[:14])
    snapshot = deepcopy(p)
    b = st.exit_update(p, f.iloc[13].to_dict(), f.iloc[:14])
    assert a == b and snapshot == p
    assert p["signal"] == before_signal


def test_flip_exit_is_next_open_and_gap_does_not_bridge_state() -> None:
    f, p = make_position()
    row = f.iloc[13].to_dict()
    row.update({"open": 112, "high": 113, "low": 99, "close": 100})
    result = st.exit_update(p, row, pd.DataFrame([row]))
    assert result["exit_next_open"]
    assert result["reason"] == "NATIVE_ST_FLIP"
    assert result["next_stop"] is None
    _, p = make_position()
    gap = st.exit_update(p, f.iloc[14].to_dict(), f.iloc[:15])
    assert gap == {"exit_next_open": True, "reason": "DATA_GAP_HOLD", "next_stop": None}


def test_exit_rejects_future_history_wrong_identity_and_preentry() -> None:
    f, p = make_position()
    with pytest.raises(ValueError, match="FUTURE_HISTORY"):
        st.exit_update(p, f.iloc[13].to_dict(), f)
    p["signal"]["identity"] = "legacy_1h"
    with pytest.raises(ValueError, match="IDENTITY_MISMATCH"):
        st.exit_update(p, f.iloc[13].to_dict(), f.iloc[:14])
    _, p = make_position()
    with pytest.raises(ValueError, match="BEFORE_ENTRY"):
        st.exit_update(p, f.iloc[12].to_dict(), f.iloc[:13])
