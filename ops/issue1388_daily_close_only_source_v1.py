"""Causal UTC-daily CLOSE-only witness from genuine minute observations.

Fail closed for missing terminal 23:59 minute; intraday holes may coexist
with valid observed daily closes, but prohibit OHLC/high-low/ATR/intraday fills.
This is input feasibility only: no signals, economics, fresh claims or orders.
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

MINUTE_MS = 60_000
DAY_MS = 86_400_000
LAST_MINUTE_IN_DAY_MS = DAY_MS - MINUTE_MS
REQUIRED_CLOSE_DAYS = 361  # 360 historical daily CLOSES + current decision day

class CloseOnlyInputBlocked(ValueError):
    pass


def project_close_only_daily(
    minutes: Sequence[Mapping[str, Any]],
    *,
    input_available_ts_ms: int,
    required_days: int = REQUIRED_CLOSE_DAYS,
) -> dict[str, Any]:
    """Verify real minute-grid terminal-close evidence, without synthetic fills.

    Minutes must already be versioned provenance-bound raw BingX minute observations.
    This function is not a replacement for external source-SHA proof.
    """
    if required_days < 2:
        raise CloseOnlyInputBlocked("REQUIRED_WARMUP_INVALID")
    if not minutes:
        raise CloseOnlyInputBlocked("NO_RAW_MINUTE_EVIDENCE")
    if input_available_ts_ms % MINUTE_MS:
        raise CloseOnlyInputBlocked("ASOF_CLOCK_NOT_MINUTE_GRID")
    last_ts = None
    last_daily = {}
    minute_count = {}
    for row in minutes:
        if "timestamp_ms" not in row or "close" not in row:
            raise CloseOnlyInputBlocked("RAW_MINUTE_FIELD_MISSING")
        ts = int(row["timestamp_ms"])
        close = float(row["close"])
        if ts % MINUTE_MS or not math.isfinite(close) or close <= 0:
            raise CloseOnlyInputBlocked("INVALID_MINUTE_GRID_OR_CLOSE")
        if last_ts is not None and ts <= last_ts:
            raise CloseOnlyInputBlocked("UNSORTED_OR_DUPLICATE_MINUTE")
        if ts + MINUTE_MS > input_available_ts_ms:
            raise CloseOnlyInputBlocked("UNOBSERVED_FUTURE_CLOSE")
        last_ts = ts
        day = ts // DAY_MS
        minute_count[day] = minute_count.get(day, 0) + 1
        if ts % DAY_MS == LAST_MINUTE_IN_DAY_MS:
            last_daily[day] = close

    days = sorted(minute_count)
    if len(days) < required_days:
        raise CloseOnlyInputBlocked("INSUFFICIENT_DAILY_CALENDAR_DAYS")
    if any(b - a != 1 for a, b in zip(days, days[1:])):
        raise CloseOnlyInputBlocked("MISSING_DAILY_CALENDAR_COVERAGE")
    if len(last_daily) != len(days):
        missing = [d for d in days if d not in last_daily]
        raise CloseOnlyInputBlocked("MISSING_DIRECT_DAILY_CLOSE:" + str(missing[0]))
    result = [{
        "day_index_utc":d,
        "decision_available_at_ts_ms":(d+1)*DAY_MS,
        "direct_observed_close":last_daily[d],
        "intra_day_1m_count":minute_count[d],
        "intra_day_1m_gap_count":1440-minute_count[d],
        "fully_observed_1m_day":minute_count[d] == 1440,
        "high_low_open_volume_authority":"UNAVAILABLE_CLOSE_ONLY",
    } for d in days]
    return {
        "schema":"zel.issue1388.daily_close_only_source.v1",
        "classification":"CAUSAL_PRICE_CLOSE_ONLY_NO_ECONOMIC_AUTHORITY",
        "source_received_latency_observed":False,
        "gap_filled":False,"volume_unit":"UNKNOWN",
        "eligible_for_donchian_daily_close_only":True,
        "eligible_for_1m_5m_stop_or_intrabar_execution":False,
        "minimum_required_days":required_days,
        "observed_complete_daily_closes":len(result),
        "incomplete_intraday_days":sum(not x["fully_observed_1m_day"] for x in result),
        "calendar":result,
    }
