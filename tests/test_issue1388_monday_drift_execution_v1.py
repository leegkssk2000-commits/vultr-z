"""Artificial-only tests for the frozen Monday-drift execution contract."""
import copy
import unittest
from datetime import datetime, timezone

from ops.issue1388_monday_drift_execution_v1 import (
    DraftError,
    HOUR,
    funding_debit,
    monday_tuesday_decisions,
    replay_monday_drift,
)

BASE = int(datetime(2026, 1, 11, 0, tzinfo=timezone.utc).timestamp() * 1000)


def rows(hours=240):
    return [
        {"open_ts_ms": BASE + i * HOUR, "close_ts_ms": BASE + (i + 1) * HOUR,
         "available_ts_ms": BASE + (i + 1) * HOUR, "segment_id": "ARTIFICIAL",
         "open": 100.0 + i}
        for i in range(hours)
    ]


def funding(stamp, rate, mark=100.0):
    return {"symbol": "BTC-USDT", "fundingTime": stamp,
            "fundingRate": str(rate), "markPrice": str(mark)}


def run(values, funds=(), start=24, end=120):
    return replay_monday_drift(values, funds, start_ms=BASE + start * HOUR,
                               end_ms=BASE + end * HOUR, roundtrip_cost_bps=14.0)


class MondayDriftExecutionTests(unittest.TestCase):
    def test_completed_monday_and_tuesday_close_fill_next_open(self):
        result = run(rows())
        self.assertEqual(result["signals"], 1)
        self.assertEqual([order["execution_ts_ms"] for order in result["orders"]],
                         [BASE + 24 * HOUR, BASE + 48 * HOUR])
        self.assertEqual(result["trades"][0]["entry_price"], 124.0)
        self.assertEqual(result["trades"][0]["exit_price"], 148.0)
        self.assertEqual(result["trades"][0]["cost_bps"], 14.0)
        self.assertEqual(result["disposition"], "COMPLETE")

    def test_decision_is_unchanged_by_future_prices(self):
        original = monday_tuesday_decisions(rows(72))
        changed = copy.deepcopy(rows(72))
        for row in changed[25:]:
            row["open"] *= 99
        self.assertEqual(original, monday_tuesday_decisions(changed))

    def test_late_monday_receipt_fills_earliest_open_before_expiry(self):
        values = rows()
        # Sunday 23:00 bar closes Monday 00:00; receipt arrives Monday 03:00:01.
        values[23]["available_ts_ms"] = BASE + 27 * HOUR + 1
        result = run(values)
        self.assertEqual(result["orders"][0]["execution_ts_ms"], BASE + 28 * HOUR)
        self.assertEqual(result["orders"][1]["execution_ts_ms"], BASE + 48 * HOUR)

    def test_unfilled_monday_entry_expires_without_invented_trade(self):
        values = rows()
        values[23]["available_ts_ms"] = BASE + 49 * HOUR
        result = run(values)
        self.assertEqual(result["trades"], [])
        self.assertEqual(result["orders"], [])
        self.assertEqual(result["missed_entries"][0]["reason"],
                         "MONDAY_ENTRY_UNFILLED_BEFORE_TUESDAY_DECISION")

    def test_occupied_gap_quarantines_position_without_exit(self):
        values = rows()
        values.pop(30)
        result = run(values)
        self.assertEqual(result["disposition"], "BLOCKED_SOURCE_GAP")
        self.assertEqual(result["trades"], [])
        self.assertIsNotNone(result["gap_quarantine"]["position"])
        self.assertEqual(result["paid_trading_cost_bps"], 7.0)

    def test_no_terminal_forced_close_or_after_end_funding(self):
        values = rows(72)
        result = run(values, [funding(BASE + 72 * HOUR, 0.999)], start=24, end=36)
        self.assertEqual(result["trades"], [])
        self.assertEqual(result["disposition"], "BLOCKED_TERMINAL_UNRESOLVED")
        self.assertEqual(result["open_position"]["funding_bps_to_end_exclusive"], 0.0)
        self.assertEqual(result["open_entry_cost_bps"], 7.0)

    def test_funding_preserves_interior_credit_and_adverse_boundaries(self):
        position = {"entry_ts_ms": 100, "entry_price": 100.0}
        funds = [funding(100, -0.001), funding(200, -0.001), funding(300, 0.001)]
        debit, count = funding_debit(position, funds, exit_ms=300, end_ms=400, closed=True)
        self.assertAlmostEqual(debit, 0.0)
        self.assertEqual(count, 2)

    def test_missing_source_coverage_and_bad_funding_fail_closed(self):
        with self.assertRaisesRegex(DraftError, "SOURCE_COVERAGE"):
            run(rows(40), end=72)
        duplicate = [funding(BASE + 32 * HOUR, 0.001), funding(BASE + 32 * HOUR, 0.001)]
        with self.assertRaisesRegex(DraftError, "DUPLICATE"):
            run(rows(), duplicate)

    def test_late_exit_receipt_uses_first_open_after_availability(self):
        values = rows()
        values[47]["available_ts_ms"] = BASE + 51 * HOUR + 1
        result = run(values)
        self.assertEqual(result["orders"][1]["execution_ts_ms"], BASE + 52 * HOUR)


if __name__ == "__main__":
    unittest.main()
