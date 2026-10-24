import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from replay import signal, fills, stats


class C(unittest.TestCase):
    def test_sweep_reclaim(self):
        self.assertTrue(signal(95, 94, 101, 93, 100))

    def test_sweep_no_reclaim(self):
        self.assertFalse(signal(95, 94, 101, 93, 94))

    def test_bearish_block(self):
        self.assertFalse(signal(95, 101, 102, 93, 99))

    def test_no_lower_low(self):
        self.assertFalse(signal(95, 94, 101, 95, 100))

    def test_weak_close(self):
        self.assertFalse(signal(95, 94, 101, 93, 96))

    def test_stop_gap(self):
        self.assertEqual(fills(80, 104, 79, 90, 103), (80, "STOP_GAP"))

    def test_stop_wins(self):
        self.assertEqual(fills(100, 104, 80, 90, 103), (90, "STOP_FIRST"))

    def test_target_capped(self):
        self.assertEqual(fills(105, 107, 104, 90, 103), (103, "TARGET_GAP_CAPPED"))

    def test_target(self):
        self.assertEqual(fills(100, 104, 95, 90, 103), (103, "TARGET"))

    def test_none(self):
        self.assertEqual(fills(100, 102, 95, 90, 103), (None, None))

    def test_empty(self):
        self.assertIsNone(stats([], 0, 86400000)["PF2"])


if __name__ == "__main__":
    unittest.main()
