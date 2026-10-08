"""Artificial OHLC fixtures only. No market loading or economic evaluation."""

import numpy as np
import pandas as pd
import pytest

from ops.issue1388_inverted_hammer_v1 import HOUR_MS, inverted_hammer_flags
from ops import issue1388_alpha_screen_v1 as screen


def artificial(n=170):
    close = 1000.0 - np.arange(n)
    frame = pd.DataFrame({"open": close + 2, "high": close + 3,
                          "low": close - 1, "close": close,
                          "open_ts_ms": np.arange(n, dtype="int64") * HOUR_MS,
                          "segment_id": "A"})
    frame["close_ts_ms"] = frame.open_ts_ms + HOUR_MS
    frame["available_ts_ms"] = frame.close_ts_ms
    return frame


def hammer(frame, t=160, bullish=True):
    frame = frame.copy()
    # Prior bodies are 2; prior ranges are 4; candidate body .25,
    # upper shadow 1, lower shadow 0, with mandatory strict body gap.
    bottom = float(frame.loc[t - 1, "close"]) - 1
    top = bottom + 0.25
    frame.loc[t, ["open", "high", "low", "close"]] = [
        bottom if bullish else top, top + 1, bottom, top if bullish else bottom]
    return frame


def test_common_density_end_to_end_cannot_call_economics_or_create_claim(monkeypatch, tmp_path):
    frame = hammer(artificial())
    for field in ("open_ts_ms", "close_ts_ms", "available_ts_ms"):
        frame[field] += screen.START_MS
    market = {"frames": {s: frame.copy() for s in screen.SYMBOLS},
              "costs": {s: 14.0 for s in screen.SYMBOLS}}
    monkeypatch.setattr(screen, "load_market", lambda *args: market)
    def forbidden(*args, **kwargs):
        pytest.fail("ECONOMIC_OR_CLAIM_FUNCTION_IN_LIGHT_CENSUS")
    for name in ("screen", "execute", "summarize", "create_record", "replay_symbol", "audit_bband_result", "audit_eth_result"):
        monkeypatch.setattr(screen, name, forbidden)
    value = screen.execute_density(tmp_path, [screen.INVERTED_HAMMER_ID], tmp_path / "artificial-output")
    candidate = value["candidates"][screen.INVERTED_HAMMER_ID]
    assert candidate["raw_signal_bars"] == 6
    assert candidate["pinned_translation_events"] == 6
    assert candidate["source_exact_episodes"] is None and candidate["source_replication"] is False
    assert candidate["warmup_ready_bars_by_symbol"] == {s: 21 for s in screen.SYMBOLS}
    saved = screen.read_json(tmp_path / "artificial-output" / "DENSITY.json")
    assert saved["economic_screen_consumed"] == 0
    assert saved["exchange_order_submitted"] is False
    assert saved["classification"] == "NO_PNL_NO_EXIT_NO_FUTURE_OUTCOME_DISCLOSED_PINNED_TRANSLATION_CENSUS"
    assert set((tmp_path / "artificial-output").iterdir()) == {tmp_path / "artificial-output" / "DENSITY.json"}


def test_density_profile_rejects_economic_activation_before_claim(tmp_path):
    path = tmp_path / "activation.json"
    screen.write_once(path, {"candidate_id": screen.INVERTED_HAMMER_ID})
    with pytest.raises(screen.ScreenError, match="DENSITY_ONLY_PROFILE_NO_ECONOMIC_ACTIVATION"):
        screen.validate_activation(path, "a" * 40)


def test_light_workflow_does_not_change_economic_global_lock():
    text = (screen.ROOT / ".github/workflows/issue1388-internet-alpha-v1.yml").read_text()
    assert "issue1388-contract-${{ github.event.pull_request.number || github.sha }}" in text
    assert text.count("group: a1-global-heavy-economic-evaluator-v1") == 3
    density = text.split("  density-preflight-003:", 1)[1].split("  cheap-screen-003:", 1)[0]
    assert "    concurrency:" not in density
    assert "--density-candidates" in density and "--activation" not in density
    assert "['R_MOSER_INVERTED_HAMMER_1H_V1']" in density


def test_both_colors_and_input_unchanged():
    for bullish in (True, False):
        frame = hammer(artificial(), bullish=bullish)
        original = frame.copy(deep=True)
        flags = inverted_hammer_flags(frame)
        assert flags.dtype == bool and flags.iloc[160]
        pd.testing.assert_frame_equal(frame, original)


@pytest.mark.parametrize("change", ["body_equal", "upper_equal", "lower_equal", "gap_equal", "gap_overlap"])
def test_all_strict_pattern_thresholds(change):
    frame = hammer(artificial())
    bottom = frame.loc[160, "low"]
    if change == "body_equal":
        frame.loc[160, ["open", "close", "high"]] = [bottom - 2, bottom, bottom + 3]
        frame.loc[160, "low"] = bottom - 2
    elif change == "upper_equal":
        frame.loc[160, "high"] = frame.loc[160, "close"] + 0.25
    elif change == "lower_equal":
        # Exact binary arithmetic: prior high-low mean 5 -> lower threshold .5.
        frame.loc[150:159, "high"] = frame.loc[150:159, "low"] + 5
        frame.loc[160, "low"] = bottom - 0.5
    else:
        top = frame.loc[159, "close"] + (0.25 if change == "gap_overlap" else 0)
        frame.loc[160, ["open", "close", "low", "high"]] = [top - 0.25, top, top - 0.25, top + 1]
    assert not inverted_hammer_flags(frame).iloc[160]


def test_current_bar_excluded_from_threshold_means():
    frame = hammer(artificial())
    # Prior bodies [4, 1, ..., 1] have mean 1.3. Candidate body 1.125
    # must pass; a current-inclusive ten-bar mean would be only 1.0125.
    frame.loc[150:159, "open"] = frame.loc[150:159, "close"] + 1
    frame.loc[150, "open"] = frame.loc[150, "close"] + 4
    frame.loc[150, "high"] = frame.loc[150, "open"] + 1
    bottom = frame.loc[159, "close"] - 3
    frame.loc[160, ["open", "close", "low", "high"]] = [bottom, bottom + 1.125, bottom, bottom + 5]
    assert inverted_hammer_flags(frame).iloc[160]


def test_first_trend_ready_row_is_index_149():
    assert not inverted_hammer_flags(hammer(artificial(), t=148)).iloc[148]
    assert inverted_hammer_flags(hammer(artificial(), t=149)).iloc[149]


@pytest.mark.parametrize("offset", range(6))
def test_each_of_six_trend_decreases_is_required(offset):
    frame = hammer(artificial())
    t = 155 + offset
    # SMA_t - SMA_(t-1) = (close_t - close_(t-144))/144.
    # Make exactly one of the six transitions flat, while leaving the
    # pattern's previous-ten means untouched when modifying the old bar.
    frame.loc[t - 144, ["open", "high", "low", "close"]] = [
        frame.loc[t, "close"] + 2, frame.loc[t, "close"] + 3,
        frame.loc[t, "close"] - 1, frame.loc[t, "close"]]
    assert not inverted_hammer_flags(frame).iloc[160]


def test_prefix_future_invariance_and_duplicate_index():
    frame = hammer(artificial(250))
    prefix = frame.iloc[:161].copy()
    flags = inverted_hammer_flags(frame)
    pd.testing.assert_series_equal(flags.iloc[:161], inverted_hammer_flags(prefix))
    frame.loc[161:, ["open", "high", "low", "close"]] = [100, 102, 99, 101]
    pd.testing.assert_series_equal(flags.iloc[:161], inverted_hammer_flags(frame).iloc[:161])
    prefix.index = [0] * len(prefix)
    assert inverted_hammer_flags(prefix).iloc[-1]


@pytest.mark.parametrize("boundary", ["segment", "gap", "repeated_segment"])
def test_boundaries_reset_full_warmup(boundary):
    frame = artificial(340)
    if boundary == "segment":
        frame.loc[170:, "segment_id"] = "B"
    elif boundary == "gap":
        frame.loc[170:, ["open_ts_ms", "close_ts_ms", "available_ts_ms"]] += HOUR_MS
    else:
        frame.loc[100:169, "segment_id"] = "B"
    frame = hammer(hammer(frame, t=318), t=319)
    # Consecutive candidates have valid gaps and sizes. Local index 148
    # is too early; index 149 has seven SMA samples over 150 bars.
    flags = inverted_hammer_flags(frame)
    assert not flags.iloc[318]
    assert flags.iloc[319]


def test_later_historical_availability_cannot_leak_into_row():
    frame = hammer(artificial())
    frame.loc[20, "available_ts_ms"] = frame.loc[160, "available_ts_ms"] + 1
    assert not inverted_hammer_flags(frame).iloc[160]
    frame.loc[160, "available_ts_ms"] += 1
    assert inverted_hammer_flags(frame).iloc[160]


def test_close_time_fallback_and_empty():
    frame = hammer(artificial()).drop(columns="available_ts_ms")
    assert inverted_hammer_flags(frame).iloc[160]
    assert inverted_hammer_flags(frame.iloc[:0]).empty


@pytest.mark.parametrize("column,value,error", [
    ("high", float("inf"), "FINITE"), ("close", float("nan"), "FINITE"),
    ("high", 1, "ENVELOPE"), ("low", 2000, "ENVELOPE"),
    ("open_ts_ms", 1, "MONOTONIC"), ("open_ts_ms", 0, "MONOTONIC"),
    ("close_ts_ms", 1, "ONE_HOUR"), ("available_ts_ms", 0, "BEFORE_CLOSE"),
    ("open_ts_ms", 0.5, "INTEGER"), ("segment_id", None, "SEGMENT"),
])
def test_invalid_records_fail_closed(column, value, error):
    frame = hammer(artificial())
    frame[column] = frame[column].astype(object) if value is None else frame[column]
    if column.endswith("_ts_ms") and isinstance(value, float):
        frame[column] = frame[column].astype(float)
    frame.loc[160, column] = value
    with pytest.raises(ValueError, match=error):
        inverted_hammer_flags(frame)


def test_missing_schema():
    with pytest.raises(ValueError, match="REQUIRED"):
        inverted_hammer_flags(artificial().drop(columns="segment_id"))
