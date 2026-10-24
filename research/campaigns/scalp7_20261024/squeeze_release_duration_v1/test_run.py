import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import run as model


class Test(unittest.TestCase):
    def test_first_release_valid(self):
        p = dict(squeeze_on=True, momentum=2.0)
        n = dict(
            squeeze_on=False,
            momentum=3.0,
            close=100.0,
            g8=95.0,
            g21=90.0,
            g34=85.0,
            atr20=5.0,
        )
        self.assertTrue(model.eligible_pair(p, n))

    def test_second_fire_block(self):
        p = dict(squeeze_on=False, momentum=2)
        n = dict(
            squeeze_on=False, momentum=3, close=100, g8=95, g21=90, g34=85, atr20=5
        )
        self.assertFalse(model.eligible_pair(p, n))

    def test_negative_mom_block(self):
        p = dict(squeeze_on=True, momentum=-2)
        n = dict(
            squeeze_on=False, momentum=-1, close=100, g8=95, g21=90, g34=85, atr20=5
        )
        self.assertFalse(model.eligible_pair(p, n))

    def test_ma_stack_invalid(self):
        p = dict(squeeze_on=True, momentum=1)
        n = dict(
            squeeze_on=False, momentum=3, close=100, g8=89, g21=90, g34=85, atr20=5
        )
        self.assertFalse(model.eligible_pair(p, n))

    def test_stop_gap_worse(self):
        self.assertEqual(model.stop_fill(80, 79, 90), (80, "OPEN_GAP_STOP"))

    def test_stop_intrabar(self):
        self.assertEqual(model.stop_fill(100, 88, 90), (90, "STOP_FIRST"))

    def test_stop_not_hit(self):
        self.assertEqual(model.stop_fill(100, 95, 90), (None, None))

    def test_no_trade_fabrication(self):
        x = model.metrics([], 0, 86400000)
        self.assertEqual(x["T"], 0)
        self.assertIsNone(x["PF2"])


if __name__ == "__main__":
    unittest.main()
