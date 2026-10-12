from __future__ import annotations

import unittest

from backend.research.benchmark import top5_trader_benchmark_multi_ai_v2 as m


class Top5TraderBenchmarkTimingRepairTests(unittest.TestCase):
    def test_long_stop_entry_uses_trigger_or_gap_open(self) -> None:
        pending = {"side": "long", "trigger": 101.0}
        fill, px = m.stop_entry_fill(pending, {"open": 100.0, "high": 102.0, "low": 99.0})
        self.assertTrue(fill)
        self.assertEqual(px, 101.0)
        fill, px = m.stop_entry_fill(pending, {"open": 103.0, "high": 104.0, "low": 102.0})
        self.assertTrue(fill)
        self.assertEqual(px, 103.0)

    def test_short_stop_entry_uses_trigger_or_gap_open(self) -> None:
        pending = {"side": "short", "trigger": 99.0}
        fill, px = m.stop_entry_fill(pending, {"open": 100.0, "high": 101.0, "low": 98.0})
        self.assertTrue(fill)
        self.assertEqual(px, 99.0)
        fill, px = m.stop_entry_fill(pending, {"open": 97.0, "high": 98.0, "low": 96.0})
        self.assertTrue(fill)
        self.assertEqual(px, 97.0)

    def test_unfilled_order_expires_in_that_bar(self) -> None:
        fill, px = m.stop_entry_fill(
            {"side": "long", "trigger": 101.0},
            {"open": 100.0, "high": 100.9, "low": 99.0},
        )
        self.assertFalse(fill)
        self.assertIsNone(px)

    def test_bad_side_rejected(self) -> None:
        with self.assertRaises(RuntimeError):
            m.stop_entry_fill({"side": "flat", "trigger": 100.0}, {"open": 100.0, "high": 101.0, "low": 99.0})


if __name__ == "__main__":
    unittest.main()
