from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backend.research.rebuild.scalp7_source_data_v2 import (
    SourceDataError,
    aggregate_minutes,
    verify_time_witness,
)


def minutes(n=90, start=0):
    ts = np.arange(start, start + n * 60_000, 60_000, dtype="int64")
    return pd.DataFrame(
        {
            "timestamp_ms": ts,
            "open": 10.0,
            "high": 12.0,
            "low": 9.0,
            "close": 11.0,
            "volume": 3.0,
        }
    )


@pytest.mark.parametrize("tf", [15, 30])
def test_missing_minute_removes_whole_bucket_and_resets_segment(tf):
    frame = minutes(120)
    frame = frame.drop(index=[32, 33, 34, 35]).reset_index(drop=True)
    result = aggregate_minutes(frame, tf)
    assert 30 * 60_000 not in result.open_ts_ms.tolist()
    assert result.segment_id.nunique() == 2
    assert result.attrs["minute_gaps"] == [
        {"start_ms": 32 * 60_000, "end_exclusive_ms": 36 * 60_000, "missing_minutes": 4}
    ]
    assert result.attrs["source_minutes"] == 116
    assert len(result) == 120 // tf - 1


def test_utc_alignment_not_array_block_alignment():
    result = aggregate_minutes(minutes(60, 20 * 60_000), 30)
    assert result.open_ts_ms.tolist() == [30 * 60_000]
    assert result.close_ts_ms.tolist() == [60 * 60_000]
    assert result.attrs["incomplete_buckets"] == [0, 60 * 60_000]


@pytest.mark.parametrize(
    "kind",
    [
        "duplicate",
        "order",
        "off_grid",
        "fractional",
        "nonfinite",
        "high",
        "negative_volume",
    ],
)
def test_corrupt_minute_source_is_rejected(kind):
    frame = minutes()
    if kind == "duplicate":
        frame.loc[1, "timestamp_ms"] = 0
    elif kind == "order":
        frame = frame.iloc[::-1]
    elif kind == "off_grid":
        frame.loc[1, "timestamp_ms"] = 60_001
    elif kind == "fractional":
        frame["timestamp_ms"] = frame["timestamp_ms"].astype(float)
        frame.loc[1, "timestamp_ms"] = 60_000.5
    elif kind == "nonfinite":
        frame.loc[1, "close"] = np.inf
    elif kind == "high":
        frame.loc[1, "high"] = 8
    else:
        frame.loc[1, "volume"] = -1
    with pytest.raises(SourceDataError):
        aggregate_minutes(frame, 15)


def test_fresh_uses_slowest_actual_constituent_receipt():
    frame = minutes(30)
    frame["received_at_ms"] = frame.timestamp_ms + 60_000
    frame.loc[3, "received_at_ms"] = 31 * 60_000
    result = aggregate_minutes(frame, 30, observed=True)
    assert result.available_ts_ms.iloc[0] == 31 * 60_000
    assert result.close_ts_ms.iloc[0] == 30 * 60_000
    assert result.attrs["availability_basis"] == "ACTUAL_CONSTITUENT_RECEIPTS"


def test_fresh_refuses_unclosed_and_unreceipted_rows():
    frame = minutes()
    with pytest.raises(SourceDataError, match="FRESH_RECEIPT_TIME_REQUIRED"):
        aggregate_minutes(frame, 15, observed=True)
    frame["received_at_ms"] = frame.timestamp_ms + 1
    with pytest.raises(SourceDataError, match="FRESH_UNCLOSED"):
        aggregate_minutes(frame, 15, observed=True)


def test_historical_availability_model_is_explicit():
    frame = aggregate_minutes(minutes(), 15)
    assert (frame.available_ts_ms == frame.close_ts_ms).all()
    assert frame.attrs["volume_units"] == "UNKNOWN"
    assert (
        frame.attrs["availability_basis"]
        == "BAR_CLOSE_MODEL_NOT_OBSERVED_HISTORICAL_DELIVERY"
    )


@pytest.mark.parametrize("tf", [1, 5, 60, 240])
def test_only_current_decision_timeframes(tf):
    with pytest.raises(SourceDataError, match="15M_OR_30M"):
        aggregate_minutes(minutes(), tf)


def test_committed_actual_time_witness():
    witness_dir = (
        Path(__file__).resolve().parents[1]
        / "research/campaigns/scalp7_20260915/source_time_v2"
    )
    result = verify_time_witness(witness_dir)
    assert len(result["witnesses"]) == 6
    assert result["state"] == "OBSERVED_OBJECT_TIME_OPEN"
    assert result["historical_delivery_latency"] == "UNOBSERVED"
