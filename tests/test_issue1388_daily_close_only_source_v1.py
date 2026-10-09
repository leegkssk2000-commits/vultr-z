"""Negative and positive deterministic source cases, NO economic replay."""
from __future__ import annotations
import unittest
from ops.issue1388_daily_close_only_source_v1 import (
    DAY_MS,MINUTE_MS,CloseOnlyInputBlocked,project_close_only_daily
)

DAY0 = 20000

def witness_days(n=361, hole_day=150, missing_terminal=False):
    rows=[]
    for i in range(n):
        day=(DAY0+i)*DAY_MS
        rows.append({"timestamp_ms":day+12*60*MINUTE_MS,"close":100+i*.05})
        if not (missing_terminal and i==hole_day):
            rows.append({"timestamp_ms":day+DAY_MS-MINUTE_MS,"close":100+i*.05+1})
    return rows

class CloseOnlySourceTest(unittest.TestCase):
    def test_intraday_gap_does_not_invent_ohlc_or_break_close_only(self):
        rows=witness_days()
        result=project_close_only_daily(rows,input_available_ts_ms=rows[-1]["timestamp_ms"]+MINUTE_MS)
        self.assertEqual(result["observed_complete_daily_closes"],361)
        self.assertTrue(result["eligible_for_donchian_daily_close_only"])
        self.assertFalse(result["eligible_for_1m_5m_stop_or_intrabar_execution"])
        self.assertEqual(result["incomplete_intraday_days"],361)
        self.assertFalse(result["gap_filled"])
        self.assertEqual(result["calendar"][150]["intra_day_1m_gap_count"],1438)
        self.assertEqual(result["calendar"][150]["high_low_open_volume_authority"],"UNAVAILABLE_CLOSE_ONLY")

    def test_missing_actual_daily_close_fails_closed(self):
        rows=witness_days(missing_terminal=True)
        with self.assertRaisesRegex(CloseOnlyInputBlocked,"MISSING_DIRECT_DAILY_CLOSE"):
            project_close_only_daily(rows,input_available_ts_ms=(DAY0+361)*DAY_MS)

    def test_future_close_is_not_exposed_to_signal(self):
        rows=witness_days()
        with self.assertRaisesRegex(CloseOnlyInputBlocked,"UNOBSERVED_FUTURE_CLOSE"):
            project_close_only_daily(rows,input_available_ts_ms=rows[-1]["timestamp_ms"])

    def test_missing_calendar_date_fails_closed(self):
        rows=[r for r in witness_days() if r["timestamp_ms"]//DAY_MS != DAY0+200]
        with self.assertRaisesRegex(CloseOnlyInputBlocked,"MISSING_DAILY_CALENDAR_COVERAGE"):
            project_close_only_daily(rows,input_available_ts_ms=(DAY0+361)*DAY_MS,required_days=360)

    def test_minimum_360_history_and_decision_day(self):
        rows=witness_days(360)
        with self.assertRaisesRegex(CloseOnlyInputBlocked,"INSUFFICIENT_DAILY_CALENDAR_DAYS"):
            project_close_only_daily(rows,input_available_ts_ms=(DAY0+360)*DAY_MS)

    def test_duplicate_and_order_rejected(self):
        rows=witness_days()
        rows.append(dict(rows[-1]))
        with self.assertRaisesRegex(CloseOnlyInputBlocked,"UNSORTED_OR_DUPLICATE_MINUTE"):
            project_close_only_daily(rows,input_available_ts_ms=(DAY0+361)*DAY_MS)

if __name__=="__main__":
    unittest.main()
