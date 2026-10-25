"""Read-only prospective signals do not authorize speculative fills."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

import signal_shadow as s


class ProspectiveSafeSignalTests(unittest.TestCase):
    def test_default_off_is_documented(self):
        text = Path(s.__file__).read_text()
        self.assertIn("if not args.enable_signal_only", text)
        self.assertIn('print("DEFAULT_OFF")', text)

    def test_no_source_path_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "SOURCE_PATH_TRAVERSAL"):
                s.under(Path(directory), "../../etc/passwd")

    def test_fake_order_status_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            z = {
                "schema": s.SCHEMA,
                "formal_shadow": False,
                "order_calls": 1,
                "virtual_fills": 0,
            }
            with self.assertRaisesRegex(RuntimeError, "FORBIDDEN_EXECUTION_AUTHORITY"):
                s.append_status(Path(directory), z)

    def test_price_signal_only_records_no_fill(self):
        frame = pd.DataFrame(
            [
                {
                    "ts_ms": i * s.HOUR,
                    "open": 100 - i * 0.03,
                    "high": 101 - i * 0.03,
                    "low": 99 - i * 0.03,
                    "close": 100 - i * 0.03,
                    "received_at_ms": (i + 1) * s.HOUR + 12_000,
                }
                for i in range(120)
            ]
        )
        result = s.emit_signals(
            {"BTC-USDT": frame}, actual_decision_ms=121 * s.HOUR, close_ms=120 * s.HOUR
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["source_bar_close_ts_ms"], 120 * s.HOUR)
        self.assertEqual(result[0]["virtual_executions"], 0)
        self.assertFalse(result[0]["next_open_fill_authorized"])
        self.assertIn(
            result[0]["decision"],
            {
                "NO_SIGNAL",
                "SIGNAL_INTENT_ONLY_NO_FILL",
                "EXIT_INTENT_ONLY_NO_FILL",
                "HOLD_SIGNAL_NEAR_SOURCE_THRESHOLD",
            },
        )

    def test_unavailable_next_future_source_rejected(self):
        frame = pd.DataFrame(
            [
                {
                    "ts_ms": i * s.HOUR,
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 100.0,
                    "received_at_ms": (i + 1) * s.HOUR + 12_000,
                }
                for i in range(120)
            ]
        )
        with self.assertRaisesRegex(RuntimeError, "SIGNAL_SOURCE_NOT_OBSERVED"):
            s.emit_signals(
                {"BTC-USDT": frame},
                actual_decision_ms=120 * s.HOUR,
                close_ms=120 * s.HOUR,
            )

    def test_shifted_signal_close_rejected(self):
        frame = pd.DataFrame(
            [
                {
                    "ts_ms": i * s.HOUR,
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 100.0,
                    "received_at_ms": (i + 1) * s.HOUR + 12_000,
                }
                for i in range(120)
            ]
        )
        with self.assertRaisesRegex(RuntimeError, "SIGNAL_SOURCE_CLOCK_WRONG"):
            s.emit_signals(
                {"BTC-USDT": frame},
                actual_decision_ms=121 * s.HOUR,
                close_ms=119 * s.HOUR,
            )


if __name__ == "__main__":
    unittest.main()
