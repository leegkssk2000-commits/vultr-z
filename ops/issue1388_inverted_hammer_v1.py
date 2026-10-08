"""Frozen proposed hourly Inverted Hammer flags, for a no-PnL census only.

TA-Lib v0.4.0 default CDLInvertedHammer formula translation; see
research/campaigns/scalp7_20261007/issue1388_internet_alpha_v1/
INVERTED_HAMMER_SOURCE_ATTRIBUTION.json and TA_LIB_LICENSE.txt. This is not a bit-identical
TA-Lib binary claim. The additional trend gate uses SMA(close, 144), where
144 is derived from six days of hourly data, and seven observations t-6..t.
Only pandas/numpy already used by the proposed caller are required.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

HOUR_MS = 3_600_000
PATTERN_LOOKBACK = 11  # Official max(10, 0, 10) + 1; first index is 11.
SMA_PERIOD = 144
TREND_OBSERVATIONS = 7
RULE_HISTORY_BARS = SMA_PERIOD + TREND_OBSERVATIONS - 1  # 150 inclusive.


def inverted_hammer_census_flags(frame: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Return one bool per completed row without modifying ``frame``.

    Required columns: open/high/low/close, open_ts_ms/close_ts_ms, segment_id.
    Times are integer UTC milliseconds; opens must be hourly aligned and
    strictly increasing, and each close must be exactly one hour after open.
    A clock gap or change of segment_id starts a fresh contiguous run, even
    if a segment label later repeats. No rolling history crosses either.

    Optional available_ts_ms must be >= close_ts_ms. A row is evaluated at
    its availability time (close time if omitted). All 150 rows needed for
    its pattern/trend must be available by then; otherwise its flag is False.
    Window/cutoff/coverage and the existing caller's 90-day load warmup remain
    caller responsibilities. The function neither sorts nor fills missing bars.
    """
    required = {"open", "high", "low", "close", "open_ts_ms", "close_ts_ms", "segment_id"}
    if not isinstance(frame, pd.DataFrame) or not required.issubset(frame.columns):
        raise ValueError("REQUIRED_OHLC_CLOCK_SEGMENT_COLUMNS")
    if frame.columns.duplicated().any():
        raise ValueError("DUPLICATE_COLUMNS")
    if frame.segment_id.isna().any():
        raise ValueError("SEGMENT_ID_REQUIRED")
    # Use positional indices internally, preserving even duplicate input labels.
    work = frame.reset_index(drop=True)
    numeric_columns = ["open", "high", "low", "close", "open_ts_ms", "close_ts_ms"]
    if "available_ts_ms" in work:
        numeric_columns.append("available_ts_ms")
    for name in numeric_columns:
        if not pd.api.types.is_numeric_dtype(work[name]) or pd.api.types.is_bool_dtype(work[name]):
            raise ValueError("NUMERIC_COLUMNS_REQUIRED")
    values = work[numeric_columns].to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("FINITE_OHLC_CLOCK_REQUIRED")
    work = work.astype({name: float for name in ("open", "high", "low", "close")})
    for name in numeric_columns[4:]:
        times = work[name].to_numpy(dtype=float)
        if np.any(times != np.floor(times)) or np.any(np.abs(times) > 2**53 - 1):
            raise ValueError("EXACT_INTEGER_MILLISECOND_CLOCK_REQUIRED")
    clock = work.open_ts_ms.astype("int64")
    close_clock = work.close_ts_ms.astype("int64")
    if not clock.mod(HOUR_MS).eq(0).all() or not clock.diff().iloc[1:].gt(0).all():
        raise ValueError("MONOTONIC_HOURLY_OPEN_CLOCK_REQUIRED")
    if not close_clock.eq(clock + HOUR_MS).all():
        raise ValueError("EXACT_ONE_HOUR_BAR_REQUIRED")
    available = work.get("available_ts_ms", close_clock).astype("int64")
    if not available.ge(close_clock).all():
        raise ValueError("AVAILABILITY_BEFORE_CLOSE")
    upper_body = work[["open", "close"]].max(axis=1)
    lower_body = work[["open", "close"]].min(axis=1)
    if not (work.high.ge(upper_body) & work.low.le(lower_body)).all():
        raise ValueError("INVALID_OHLC_ENVELOPE")
    body = (work.close - work.open).abs()
    high_low = work.high - work.low
    if not np.isfinite(body).all() or not np.isfinite(high_low).all():
        raise ValueError("FINITE_OHLC_RANGES_REQUIRED")
    boundary = work.segment_id.ne(work.segment_id.shift()) | clock.diff().ne(HOUR_MS)
    flags = pd.Series(False, index=work.index, dtype=bool)
    readiness = pd.Series(False, index=work.index, dtype=bool)
    for _, part in work.groupby(boundary.cumsum(), sort=False):
        idx = part.index
        local_body = body.loc[idx]
        small_body = local_body.lt(local_body.shift(1).rolling(10, min_periods=10).mean())
        long_upper = (part.high - upper_body.loc[idx]).gt(local_body)
        tiny_lower = (lower_body.loc[idx] - part.low).lt(
            0.1 * high_low.loc[idx].shift(1).rolling(10, min_periods=10).mean()
        )
        gap_down = upper_body.loc[idx].lt(lower_body.loc[idx].shift(1))
        pattern_ready = pd.Series(np.arange(len(part)) >= PATTERN_LOOKBACK, index=idx)
        sma = part.close.rolling(SMA_PERIOD, min_periods=SMA_PERIOD).mean()
        # Exactly six strict decreases connect seven completed SMA samples.
        trend = sma.diff().lt(0).rolling(TREND_OBSERVATIONS - 1, min_periods=6).sum().eq(6)
        known = available.loc[idx].rolling(RULE_HISTORY_BARS, min_periods=RULE_HISTORY_BARS).max().le(available.loc[idx])
        readiness.loc[idx] = (sma.notna() & sma.shift(6).notna() & known).fillna(False)
        flags.loc[idx] = (pattern_ready & small_body & long_upper & tiny_lower & gap_down & trend & known).fillna(False)
    return (pd.Series(flags.to_numpy(), index=frame.index, name="inverted_hammer", dtype=bool),
            pd.Series(readiness.to_numpy(), index=frame.index, name="warmup_ready", dtype=bool))


def inverted_hammer_flags(frame: pd.DataFrame) -> pd.Series:
    return inverted_hammer_census_flags(frame)[0]
