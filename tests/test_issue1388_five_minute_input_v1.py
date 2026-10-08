import numpy as np
import pandas as pd
import pytest

from backend.research.rebuild.issue1388_five_minute_input_v1 import (
    aggregate_five_minute,
)
from backend.research.rebuild.scalp7_source_data_v2 import SourceDataError


def minutes(count=60):
    timestamp = np.arange(0, count * 60_000, 60_000, dtype="int64")
    return pd.DataFrame(
        {
            "timestamp_ms": timestamp,
            "open": 10.0,
            "high": 12.0,
            "low": 9.0,
            "close": 11.0,
            "volume": 3.0,
        }
    )


def test_known_four_minute_gap_omits_both_touched_buckets_and_resets_segment():
    frame = minutes().drop(index=[32, 33, 34, 35]).reset_index(drop=True)
    result = aggregate_five_minute(frame)
    assert 30 * 60_000 not in result.open_ts_ms.tolist()
    assert 35 * 60_000 not in result.open_ts_ms.tolist()
    assert result.segment_id.nunique() == 2
    assert result.attrs["minute_gaps"] == [
        {
            "start_ms": 32 * 60_000,
            "end_exclusive_ms": 36 * 60_000,
            "missing_minutes": 4,
        }
    ]
    assert result.attrs["source_minutes"] == 56
    assert len(result) == 10
    assert (result.available_ts_ms == result.close_ts_ms).all()


@pytest.mark.parametrize("kind", ["duplicate", "off_grid", "nonfinite", "range"])
def test_corrupt_minute_source_is_rejected(kind):
    frame = minutes()
    if kind == "duplicate":
        frame.loc[1, "timestamp_ms"] = 0
    elif kind == "off_grid":
        frame.loc[1, "timestamp_ms"] = 60_001
    elif kind == "nonfinite":
        frame.loc[1, "close"] = np.inf
    else:
        frame.loc[1, "high"] = 8
    with pytest.raises(SourceDataError):
        aggregate_five_minute(frame)
