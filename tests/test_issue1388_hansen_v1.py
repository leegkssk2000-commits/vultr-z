from __future__ import annotations

import sys
import types

import numpy as np
import pandas as pd
import pytest

from ops.issue1388_hansen_v1 import HansenCensusError, hansen_entry_census_flags


def frame(segment_ids=None):
    n = 12
    return pd.DataFrame({
        "open_ts_ms": np.arange(n) * 3_600_000,
        "open": np.linspace(100, 111, n),
        "high": np.linspace(102, 113, n),
        "low": np.linspace(98, 109, n),
        "close": np.linspace(101, 112, n),
        "segment_id": segment_ids if segment_ids is not None else [1] * n,
    })


class FakeTalib:
    def __init__(self):
        self.sma_calls = 0
        self.evening_calls = 0
        self.inverted_calls = 0

    def SMA(self, values, timeperiod):
        self.sma_calls += 1
        out = np.ones(len(values)) if self.sma_calls % 2 else np.zeros(len(values))
        out[:2] = np.nan
        return out

    def CDL3LINESTRIKE(self, o, h, l, c):
        out = np.zeros(len(o), dtype=int)
        out[5] = -100
        return out

    def CDLEVENINGSTAR(self, o, h, l, c):
        self.evening_calls += 1
        return np.zeros(len(o), dtype=int)

    def CDLHARAMI(self, o, h, l, c):
        return np.zeros(len(o), dtype=int)

    def CDLINVERTEDHAMMER(self, o, h, l, c):
        self.inverted_calls += 1
        return np.zeros(len(o), dtype=int)

    def CDLENGULFING(self, o, h, l, c):
        return np.zeros(len(o), dtype=int)


def test_source_quirks_are_preserved_and_output_is_no_pnl(monkeypatch):
    fake = FakeTalib()
    monkeypatch.setitem(sys.modules, "talib", fake)
    raw, ready = hansen_entry_census_flags(frame())
    assert list(raw[raw].index) == [5]
    assert ready.sum() == 10
    assert fake.evening_calls == 2
    assert fake.inverted_calls == 1


def test_gap_must_be_encoded_as_a_new_segment(monkeypatch):
    fake = FakeTalib()
    monkeypatch.setitem(sys.modules, "talib", fake)
    broken = frame()
    broken.loc[7:, "open_ts_ms"] += 3_600_000
    with pytest.raises(HansenCensusError, match="INTRA_SEGMENT_TIME_GAP"):
        hansen_entry_census_flags(broken)
