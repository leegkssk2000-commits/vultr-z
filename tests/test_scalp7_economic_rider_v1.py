from __future__ import annotations

from copy import deepcopy
from typing import Any

import pandas as pd
import pytest

from backend.research.rebuild import scalp7_economic_rider_v1 as rider


def bars(prices: list[tuple[float, float, float, float]], tf: int = 15) -> pd.DataFrame:
    step = tf * 60_000
    return pd.DataFrame(
        [
            {
                "open_ts_ms": i * step,
                "close_ts_ms": (i + 1) * step,
                "available_ts_ms": (i + 1) * step,
                "segment_id": "A",
                "open": o,
                "high": h,
                "low": low,
                "close": c,
                "volume": 1.0,
            }
            for i, (o, h, low, c) in enumerate(prices)
        ]
    )


def prepared() -> pd.DataFrame:
    frame = bars(
        [
            (103, 106, 101, 104),
            (104, 105, 100, 102),
            (102, 104, 99, 103),
            (103, 107, 100, 106),
            (106, 109, 105, 108),
        ]
    )
    frame["ctx_usable"] = True
    frame["ctx_order"] = 1
    frame["ctx_episode_ts_ms"] = 0
    frame["ctx_event_origin_ts_ms"] = 0
    frame["ctx_event_available_ts_ms"] = 2 * rider.TIMEFRAME_MS
    frame["ctx_event_low"] = 100.0
    frame["ctx_event_high"] = 106.0
    frame.loc[0, "ctx_usable"] = False
    return frame


def context_prices() -> pd.DataFrame:
    values: list[tuple[float, float, float, float]] = [
        (99 + i, 101 + i, 98 + i, 100 + i) for i in range(62)
    ]
    values += [(161, 162, 158.5, 160.5), (160.5, 162, 158, 160)]
    return bars(values, 30)


def test_source_case_short_compression_with_stable_long_bundle() -> None:
    rows = rider._features(context_prices())
    assert all(r["ctx_event_origin_ts_ms"] is None for r in rows[:62])
    assert rows[62]["ctx_order"] == 1
    assert rows[62]["ctx_event_origin_ts_ms"] == 62 * rider.CONTEXT_MS
    assert rows[63]["ctx_event_origin_ts_ms"] is None


def test_source_case_joint_compression_does_not_create_event() -> None:
    frame = context_prices()
    frame.loc[62, ["open", "high", "low", "close"]] = [161, 162, 90, 91]
    assert rider._features(frame)[62]["ctx_event_origin_ts_ms"] is None


def test_warmup_gap_and_segment_reset_context() -> None:
    frame = context_prices()
    for column in ("open_ts_ms", "close_ts_ms", "available_ts_ms"):
        frame.loc[61:, column] += rider.CONTEXT_MS
    rows = rider._features(frame)
    assert all(r["ctx_order"] == 0 for r in rows[61:])
    frame = context_prices()
    frame.loc[61:, "segment_id"] = "B"
    assert all(r["ctx_order"] == 0 for r in rider._features(frame)[61:])


def test_same_entries_real_pullback_stop_and_distinct_exit_identity() -> None:
    left = rider.generate_signals({"BTC": prepared()}, identity=rider.IDENTITY)
    right = rider.generate_signals({"BTC": prepared()}, identity=rider.IDENTITY30)
    assert len(left) == len(right) == 1
    assert left[0]["signal_open_ts_ms"] == 3 * rider.TIMEFRAME_MS
    assert left[0]["stop_price"] == 99
    assert left[0]["max_hold_bars"] == right[0]["max_hold_bars"] == 36
    for key in ("signal_ts_ms", "stop_price", "side"):
        assert left[0][key] == right[0][key]
    assert left[0]["meta"]["opportunity_id"] == right[0]["meta"]["opportunity_id"]
    assert left[0]["meta"]["exit_timeframe_min"] == 15
    assert right[0]["meta"]["exit_timeframe_min"] == 30


def test_no_same_context_close_trigger_or_repeated_event() -> None:
    frame = prepared()
    frame.loc[1, ["high", "close"]] = [110, 109]
    assert rider.generate_signals({"BTC": frame.iloc[:2]}) == []
    assert len(rider.generate_signals({"BTC": prepared()})) == 1


def test_short_is_exact_price_mirror() -> None:
    frame = prepared()
    source = frame.copy()
    for column in ("open", "close"):
        frame[column] = 200 - source[column]
    frame["high"], frame["low"] = 200 - source["low"], 200 - source["high"]
    frame["ctx_order"] = -1
    frame["ctx_event_low"], frame["ctx_event_high"] = 94.0, 100.0
    signal = rider.generate_signals({"BTC": frame})[0]
    assert signal["side"] == -1
    assert signal["stop_price"] == 101


def test_setup_boundary_eight_allowed_nine_expired() -> None:
    for age, expected in ((8, 1), (9, 0)):
        frame = prepared()
        padding = pd.concat([frame.iloc[[2]]] * age, ignore_index=True)
        padding.loc[:, ["open", "high", "low", "close"]] = [102, 104, 99, 103]
        combined = pd.concat([frame.iloc[:2], padding], ignore_index=True)
        for column, delta in (
            ("open_ts_ms", 0),
            ("close_ts_ms", 1),
            ("available_ts_ms", 1),
        ):
            combined[column] = [
                (i + delta) * rider.TIMEFRAME_MS for i in range(len(combined))
            ]
        combined.loc[len(combined) - 1, ["high", "close"]] = [107, 106]
        assert len(rider.generate_signals({"BTC": combined})) == expected


@pytest.mark.parametrize("kind", ["gap", "order", "unusable", "episode"])
def test_context_failure_cancels_pending_setup(kind: str) -> None:
    frame = prepared()
    if kind == "gap":
        for column in ("open_ts_ms", "close_ts_ms", "available_ts_ms"):
            frame.loc[3:, column] += rider.TIMEFRAME_MS
    elif kind == "order":
        frame.loc[3:, "ctx_order"] = 0
    elif kind == "unusable":
        frame.loc[3:, "ctx_usable"] = False
    else:
        frame.loc[3:, "ctx_episode_ts_ms"] = 99
    assert rider.generate_signals({"BTC": frame}) == []


def test_signal_prefix_is_unchanged_by_future_prices() -> None:
    frame = prepared()
    earlier = rider.generate_signals({"BTC": frame.iloc[:4]})
    frame.loc[4, ["open", "high", "low", "close"]] = [106, 190, 1, 180]
    assert rider.generate_signals({"BTC": frame}) == earlier


def test_prepare_uses_actual_availability_and_never_future_context() -> None:
    fifteen = bars([(100, 102, 98, 101)] * 6)
    thirty = bars([(100, 102, 98, 101)] * 3, 30)
    thirty.loc[1, "available_ts_ms"] += rider.TIMEFRAME_MS
    result = rider.prepare_frames({"BTC": fifteen}, {"BTC": thirty})["BTC"]
    assert not result.iloc[0]["ctx_usable"]
    assert result.iloc[3]["ctx_open_ts_ms"] == 0
    assert result.iloc[4]["ctx_open_ts_ms"] == rider.CONTEXT_MS
    prefix = rider.prepare_frames({"BTC": fifteen.iloc[:4]}, {"BTC": thirty.iloc[:2]})[
        "BTC"
    ]
    pd.testing.assert_frame_equal(result.iloc[:4].reset_index(drop=True), prefix)
    thirty.loc[2, ["high", "close"]] = [200, 199]
    changed = rider.prepare_frames({"BTC": fifteen}, {"BTC": thirty})["BTC"]
    pd.testing.assert_frame_equal(result.iloc[:5], changed.iloc[:5])


def test_prepare_fifteen_gap_cannot_reuse_pre_gap_context() -> None:
    fifteen = bars([(100, 102, 98, 101)] * 6).drop(index=2).reset_index(drop=True)
    thirty = bars([(100, 102, 98, 101)] * 3, 30)
    result = rider.prepare_frames({"BTC": fifteen}, {"BTC": thirty})["BTC"]
    assert not result.iloc[2]["ctx_usable"]
    assert not result.iloc[3]["ctx_usable"]
    assert result.iloc[4]["ctx_usable"]


def test_delayed_context_stop_includes_already_observed_intermediate_extreme() -> None:
    frame = prepared()
    frame.loc[1:2, "ctx_usable"] = False
    frame["ctx_event_available_ts_ms"] = 4 * rider.TIMEFRAME_MS
    frame.loc[2, "low"] = 95.0
    signal = rider.generate_signals({"BTC": frame})[0]
    assert signal["signal_ts_ms"] == 5 * rider.TIMEFRAME_MS
    assert signal["stop_price"] == 95


def pivot_history() -> pd.DataFrame:
    return bars([(103, 106, 102, 104), (104, 105, 101, 103), (103, 107, 102, 106)])


def position(identity: str = rider.IDENTITY) -> dict[str, Any]:
    return {
        "signal": {"identity": identity},
        "entry_ts_ms": 0,
        "stop_price": 99,
        "side": 1,
    }


def test_exit15_confirmed_pivot_next_bar_only_and_no_loosen() -> None:
    history = pivot_history()
    pos = position()
    before = deepcopy(pos)
    assert (
        rider.exit_update(pos, history.iloc[-1].to_dict(), history)["next_stop"] == 101
    )
    assert pos == before
    pos["stop_price"] = 102
    assert "next_stop" not in rider.exit_update(
        pos, history.iloc[-1].to_dict(), history
    )


def test_exit30_complete_source_triplet_and_midbar_entry() -> None:
    thirty = pivot_history()
    for column in ("open_ts_ms", "close_ts_ms", "available_ts_ms"):
        thirty[column] *= 2
    fifteen = bars(
        [
            (103, 106, 102, 104),
            (104, 106, 102, 104),
            (104, 105, 101, 103),
            (103, 105, 102, 103),
            (103, 105, 102, 104),
            (104, 107, 102, 106),
        ]
    )
    joined = rider.prepare_frames({"BTC": fifteen}, {"BTC": thirty})["BTC"]
    pos = position(rider.IDENTITY30)
    pos["entry_ts_ms"] = rider.CONTEXT_MS
    assert "next_stop" not in rider.exit_update(
        pos, joined.iloc[4].to_dict(), joined.iloc[:5]
    )
    assert rider.exit_update(pos, joined.iloc[-1].to_dict(), joined)["next_stop"] == 101
    pos["entry_ts_ms"] = rider.CONTEXT_MS + rider.TIMEFRAME_MS
    assert "next_stop" not in rider.exit_update(pos, joined.iloc[-1].to_dict(), joined)


def test_exit30_gapped_triplet_and_delayed_right_are_ineligible() -> None:
    thirty = pivot_history()
    for column in ("open_ts_ms", "close_ts_ms", "available_ts_ms"):
        thirty[column] *= 2
        thirty.loc[2, column] += rider.CONTEXT_MS
    assert rider._features(thirty)[-1]["ctx_pivot_low"] is None
    history = pivot_history()
    row = history.iloc[-1].to_dict()
    row.update(
        ctx_usable=True,
        ctx_pivot_open_ts_ms=0,
        ctx_pivot_low=101,
        ctx_pivot_available_ts_ms=row["available_ts_ms"] + 1,
    )
    assert "next_stop" not in rider.exit_update(
        position(rider.IDENTITY30), row, history
    )


def test_exit30_short_mirror_and_never_loosen() -> None:
    history = pivot_history()
    row = history.iloc[-1].to_dict()
    row.update(
        close=94,
        ctx_usable=True,
        ctx_pivot_open_ts_ms=0,
        ctx_pivot_high=99,
        ctx_pivot_available_ts_ms=row["available_ts_ms"],
    )
    pos = position(rider.IDENTITY30)
    pos.update(side=-1, stop_price=101)
    assert rider.exit_update(pos, row, history)["next_stop"] == 99
    pos["stop_price"] = 98
    assert "next_stop" not in rider.exit_update(pos, row, history)


def test_invalid_identity_and_unprepared_context_fail_closed() -> None:
    with pytest.raises(ValueError, match="IDENTITY"):
        rider.generate_signals({"BTC": prepared()}, identity="unknown")
    with pytest.raises(ValueError, match="PREPARED"):
        rider.generate_signals({"BTC": pivot_history()})
    with pytest.raises(ValueError, match="SYMBOL"):
        rider.prepare_frames({"BTC": pivot_history()}, {})


def test_later_compression_replaces_pending_setup_with_own_origin() -> None:
    frame = prepared()
    frame.loc[3:, "ctx_event_origin_ts_ms"] = 2 * rider.TIMEFRAME_MS
    frame.loc[3:, "ctx_event_available_ts_ms"] = 4 * rider.TIMEFRAME_MS
    frame.loc[3:, "ctx_event_low"] = 98.0
    signal = rider.generate_signals({"BTC": frame})[0]
    assert signal["signal_open_ts_ms"] == 4 * rider.TIMEFRAME_MS
    assert signal["meta"]["compression_origin_ts_ms"] == 2 * rider.TIMEFRAME_MS
    assert signal["stop_price"] == 98


def test_context_staleness_exact_thirty_minutes_is_boundary() -> None:
    fifteen = bars([(100, 102, 98, 101)] * 5)
    thirty = bars([(100, 102, 98, 101)], 30)
    frame = rider.prepare_frames({"BTC": fifteen}, {"BTC": thirty})["BTC"]
    assert frame.iloc[3]["ctx_usable"]
    assert not frame.iloc[4]["ctx_usable"]


def test_previous_ema_source_availability_propagates_to_later_context() -> None:
    fifteen = bars([(100, 102, 98, 101)] * 6)
    thirty = bars([(100, 102, 98, 101)] * 3, 30)
    thirty.loc[0, "available_ts_ms"] = 5 * rider.TIMEFRAME_MS
    frame = rider.prepare_frames({"BTC": fifteen}, {"BTC": thirty})["BTC"]
    assert not frame.iloc[3]["ctx_usable"]
    assert frame.iloc[4]["ctx_open_ts_ms"] == rider.CONTEXT_MS


def test_complete_source_context_to_paired_entry_call_path() -> None:
    thirty = context_prices()
    values = [
        (float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]))
        for r in thirty.to_dict("records")
    ]
    values.append((160.0, 164.0, 159.0, 163.0))
    thirty = bars(values, 30)
    fifteen = bars([value for value in values for _ in range(2)])
    prepared_frames = rider.prepare_frames({"BTC": fifteen}, {"BTC": thirty})
    a = rider.generate_signals(prepared_frames, identity=rider.IDENTITY)
    b = rider.generate_signals(prepared_frames, identity=rider.IDENTITY30)
    assert len(a) == len(b) == 1
    assert a[0]["meta"]["compression_origin_ts_ms"] == 62 * rider.CONTEXT_MS
    assert a[0]["stop_price"] == 158.0
    assert a[0]["meta"]["opportunity_id"] == b[0]["meta"]["opportunity_id"]
    prefix = rider.prepare_frames({"BTC": fifteen.iloc[:-1]}, {"BTC": thirty.iloc[:-1]})
    assert rider.generate_signals(prefix)[0] == a[0]
