"""Source-exact no-PnL signal census for Hansen Candlestick Pattern V1.

The donor source is pinned in HANSEN_PRE_SCREEN_THESIS.json. This module only
computes completed-bar entry flags. It never evaluates exits, future outcomes,
PnL, costs, or orders.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


class HansenCensusError(RuntimeError):
    pass


def hansen_entry_census_flags(frame: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Return source-exact entry flags and indicator-ready flags.

    Exact donor quirks are preserved: hopen uses open/close shifted by two
    bars; ABANDONEDBABY is a second CDLEVENINGSTAR computation; and the
    donor-computed INVERTEDHAMMER is not part of entry. Gap-separated segments
    are evaluated independently so indicators never bridge unavailable data.
    """
    import talib

    required = {"open", "high", "low", "close", "open_ts_ms", "segment_id"}
    if not required.issubset(frame.columns):
        raise HansenCensusError("HANSEN_REQUIRED_COLUMNS")
    raw = pd.Series(False, index=frame.index, dtype=bool)
    ready = pd.Series(False, index=frame.index, dtype=bool)
    hour_ms = 3_600_000
    for segment, part in frame.groupby("segment_id", sort=False, dropna=False):
        if pd.isna(segment):
            raise HansenCensusError("HANSEN_SEGMENT_ID_REQUIRED")
        if len(part) > 1 and not part.open_ts_ms.diff().iloc[1:].eq(hour_ms).all():
            raise HansenCensusError("HANSEN_INTRA_SEGMENT_TIME_GAP")
        o = part.open.to_numpy(dtype=float)
        h = part.high.to_numpy(dtype=float)
        l = part.low.to_numpy(dtype=float)
        c = part.close.to_numpy(dtype=float)
        hclose = (o + h + l + c) / 4.0
        hopen = (part.open.shift(2) + part.close.shift(2)).to_numpy(dtype=float) / 2.0
        emac = np.asarray(talib.SMA(hclose, timeperiod=6), dtype=float)
        emao = np.asarray(talib.SMA(hopen, timeperiod=6), dtype=float)
        three_line = np.asarray(talib.CDL3LINESTRIKE(o, h, l, c))
        evening = np.asarray(talib.CDLEVENINGSTAR(o, h, l, c))
        # Donor's ABANDONEDBABY column intentionally duplicates EVENINGSTAR.
        abandoned = np.asarray(talib.CDLEVENINGSTAR(o, h, l, c))
        harami = np.asarray(talib.CDLHARAMI(o, h, l, c))
        # Donor computes this unused indicator; retain the call for exactness.
        talib.CDLINVERTEDHAMMER(o, h, l, c)
        engulfing = np.asarray(talib.CDLENGULFING(o, h, l, c))
        local_ready = np.isfinite(emao) & np.isfinite(emac)
        local_raw = (
            ((three_line < 0) | (evening > 0) | (abandoned > 0)
             | (harami > 0) | (engulfing > 0))
            & (emao < emac) & local_ready
        )
        raw.loc[part.index] = local_raw
        ready.loc[part.index] = local_ready
    return raw, ready
