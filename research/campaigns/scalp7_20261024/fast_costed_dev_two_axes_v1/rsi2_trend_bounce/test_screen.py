import unittest
import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from screen import exit_fill, validate, features, signal, H


class Test(unittest.TestCase):
    def test_collision_stop_first(self):
        self.assertEqual(exit_fill(100, 105, 95, 97, 103, True), (97.0, "STOP_FIRST"))

    def test_bad_stop_gap(self):
        self.assertEqual(exit_fill(90, 110, 89, 97, 103), (90.0, "STOP_GAP"))

    def test_target_gap_cap(self):
        self.assertEqual(
            exit_fill(110, 112, 100, 97, 103), (103.0, "TARGET_GAP_CAPPED")
        )

    def test_target_only(self):
        self.assertEqual(exit_fill(100, 104, 99, 97, 103, True), (103.0, "TARGET"))

    def test_none(self):
        self.assertEqual(exit_fill(100, 101, 99, 97, 103, True), (None, None))

    def test_duplicate_fail(self):
        with self.assertRaisesRegex(ValueError, "INCOMPLETE"):
            validate([x * H for x in range(250)] + [249 * H])

    def test_gap_fail(self):
        with self.assertRaisesRegex(ValueError, "INCOMPLETE"):
            validate([x * H for x in range(250) if x != 100])

    def test_min_warmup_required(self):
        df = pd.DataFrame(
            {"close": [100.0] * 250, "high": [100.0] * 250, "low": [100.0] * 250}
        )
        f = features(df)
        self.assertFalse(signal(1, df, f))

    def test_prefix_invariant(self):
        c = [100 + i * 0.1 for i in range(300)]

        def make(v):
            return pd.DataFrame(
                {"close": v, "high": [x + 1 for x in v], "low": [x - 1 for x in v]}
            )

        a = features(make(c))
        b = features(make(c + [999, 1]))
        self.assertAlmostEqual(a.iloc[-1].ema200, b.iloc[299].ema200)
        self.assertAlmostEqual(a.iloc[-1].rsi2, b.iloc[299].rsi2)
        self.assertAlmostEqual(a.iloc[-1].atr14, b.iloc[299].atr14)


if __name__ == "__main__":
    unittest.main()
