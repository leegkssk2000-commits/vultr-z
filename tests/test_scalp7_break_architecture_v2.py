"""Synthetic candle fixtures verify causality / state transitions, not economics."""

from __future__ import annotations

import pandas as pd
import pytest

from backend.research.rebuild import scalp7_break_architecture_v2 as b


def bar(
    i: int,
    o: float = 100,
    h: float = 101,
    low: float = 99,
    c: float = 100,
    **kw: object,
) -> dict:
    row = {
        "open_ts_ms": i * b.TIMEFRAME_MS,
        "close_ts_ms": (i + 1) * b.TIMEFRAME_MS,
        "available_ts_ms": (i + 1) * b.TIMEFRAME_MS,
        "segment_id": "A",
        "open": o,
        "high": h,
        "low": low,
        "close": c,
    }
    row.update(kw)
    return row


def long_setup() -> list[dict]:
    return [bar(i) for i in range(20)] + [
        bar(20, 100, 103, 100, 102),
        bar(21, 102, 102.5, 100.5, 102),
        bar(22, 102, 104, 101.5, 103),
    ]


def signals(rows: list[dict]) -> list[dict]:
    return b.generate_signals({"BTC-USDT": pd.DataFrame(rows)})


def test_separate_break_retest_reclaim_closed_stages() -> None:
    rows = long_setup()
    assert signals(rows[:-1]) == []
    actual = signals(rows)
    assert len(actual) == 1
    signal = actual[0]
    assert signal["side"] == 1
    assert signal["stop_price"] == 100.5
    assert signal["invalidation_price"] == 101
    assert signal["signal_ts_ms"] == rows[-1]["close_ts_ms"]
    assert signal["signal_open_ts_ms"] < signal["signal_ts_ms"]
    assert signal["identity"] == b.IDENTITY
    assert signal["timeframe_min"] == 15
    assert "entry_price" not in signal
    assert signal["meta"]["retest_high"] == 102.5


def test_short_is_price_reflection() -> None:
    rows = long_setup()
    for row in rows:
        high, low = row["high"], row["low"]
        row.update(
            open=200 - row["open"],
            close=200 - row["close"],
            high=200 - low,
            low=200 - high,
        )
    signal = signals(rows)[0]
    assert signal["side"] == -1
    assert signal["stop_price"] == 99.5
    assert signal["invalidation_price"] == 99


def test_no_approximate_retest_or_same_bar_reclaim() -> None:
    rows = long_setup()
    rows[21] = bar(21, 102, 105, 101.01, 104)
    rows[22] = bar(22, 104, 106, 102, 105)
    assert signals(rows) == []


def test_break_bar_wick_is_not_later_retest() -> None:
    rows = long_setup()[:21] + [bar(21, 102, 105, 101.1, 104)]
    assert signals(rows) == []


def test_close_back_inside_cancels_setup_permanently() -> None:
    rows = long_setup()
    rows[21] = bar(21, 102, 103, 100, 101)
    assert signals(rows) == []


def test_post_retest_adverse_breach_beats_reclaim() -> None:
    rows = long_setup()
    rows[22] = bar(22, 102, 104, 100.4, 103)
    assert signals(rows) == []


def test_original_anchor_is_not_rolling_high() -> None:
    signal = signals(long_setup())[0]
    assert signal["meta"]["channel_high"] == 101
    assert signal["invalidation_price"] != 103


def test_setup_has_total_ttl_not_reset_per_stage() -> None:
    rows = long_setup()[:21]
    rows += [bar(i, 102, 103, 101.5, 102) for i in range(21, 31)]
    rows += [bar(31, 102, 103, 100.5, 102), bar(32, 102, 104, 101.5, 103.5)]
    assert signals(rows) == []


@pytest.mark.parametrize("change", ["gap", "segment"])
def test_gap_or_segment_cancels_and_requires_new_warmup(change: str) -> None:
    rows = long_setup()
    if change == "gap":
        rows[-1] = bar(23, 102, 104, 101.5, 103)
    else:
        rows[-1]["segment_id"] = "B"
    assert signals(rows) == []


def test_delayed_available_feature_is_not_backdated() -> None:
    rows = long_setup()
    rows[20]["available_ts_ms"] = 25 * b.TIMEFRAME_MS
    assert signals(rows)[0]["signal_ts_ms"] == 25 * b.TIMEFRAME_MS


def test_append_only_and_no_outcome_feature_dependency() -> None:
    rows = long_setup()
    expected = signals(rows)
    altered = rows + [bar(23, 103, 200, 1, 100)]
    assert signals(altered)[:1] == expected
    for row in rows:
        row.update(future_profit=1e9, winner=True, mfe_R=100)
    assert signals(rows) == expected


@pytest.mark.parametrize(
    "key,value,error",
    [
        ("open_ts_ms", 1, "UTC_15M"),
        ("close_ts_ms", 1000, "EXCLUSIVE_15M"),
        ("available_ts_ms", 0, "CLOSED_BAR"),
        ("close", float("nan"), "FINITE"),
        ("low", 200, "GEOMETRY"),
        ("segment_id", None, "SEGMENT"),
    ],
)
def test_malformed_bar_fails_closed(key: str, value: object, error: str) -> None:
    row = bar(0)
    row[key] = value
    with pytest.raises(ValueError, match=error):
        signals([row])


def test_duplicate_or_reverse_bar_is_rejected() -> None:
    with pytest.raises(ValueError, match="DUPLICATE_OR_REVERSED"):
        signals([bar(0), bar(0)])


def test_thesis_close_exit_is_next_open_request() -> None:
    signal = signals(long_setup())[0]
    position = {"signal": signal, "side": 1}
    result = b.exit_update(position, bar(23, 103, 104, 100, 101), pd.DataFrame())
    assert result == {"exit_next_open": True, "reason": "ANCHORED_BREAKOUT_LEVEL_LOST"}
    assert "exit_price" not in result


def test_gap_exit_has_no_invented_fill() -> None:
    signal = signals(long_setup())[0]
    result = b.exit_update(
        {"signal": signal, "side": 1}, bar(23, segment_id="B"), pd.DataFrame()
    )
    assert result["exit_next_open"] is False
    assert result["reason"] == "GAP_HOLD_ENGINE_OWNS_BOUNDARY"
