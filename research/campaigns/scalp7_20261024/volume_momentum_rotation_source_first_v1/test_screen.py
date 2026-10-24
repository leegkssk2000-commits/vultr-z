import unittest
import numpy as np
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import screen as r


class Guard(unittest.TestCase):
    def test_price_positive_required(self):
        p = np.full(300, 100.0, dtype=float)
        v = np.full(300, 100.0, dtype=float)
        self.assertEqual(r.weights_at(250, p, v), (-float("inf"), -float("inf")))

    def test_positive_24h(self):
        p = np.arange(300, dtype=float) + 100
        v = np.full(300, 100.0, dtype=float)
        score, baseline = r.weights_at(250, p, v)
        self.assertAlmostEqual(score, baseline)
        self.assertGreater(score, 0)

    def test_volume_factor(self):
        p = np.arange(300, dtype=float) + 100
        v = np.full(300, 100.0, dtype=float)
        v[226:250] = 200
        score, baseline = r.weights_at(250, p, v)
        self.assertAlmostEqual(score, baseline * 2)

    def test_volume_factor_cap(self):
        p = np.arange(300, dtype=float) + 100
        v = np.full(300, 100.0, dtype=float)
        v[226:250] = 1000
        score, baseline = r.weights_at(250, p, v)
        self.assertAlmostEqual(score, baseline * 3)

    def test_current_bar_not_seen(self):
        p = np.arange(300, dtype=float) + 100
        v = np.full(300, 100.0, dtype=float)
        a = r.weights_at(250, p, v)
        p[250] = 1e9
        v[250] = 1e9
        b = r.weights_at(250, p, v)
        self.assertEqual(a, b)

    def test_stop_gap_worse(self):
        self.assertEqual(r.stop_fill(89, 88, 90), 89)

    def test_stop_touch(self):
        self.assertEqual(r.stop_fill(100, 89, 90), 90)

    def test_stop_no_touch(self):
        self.assertIsNone(r.stop_fill(100, 91, 90))

    def test_warmup(self):
        with self.assertRaisesRegex(ValueError, "WARMUP"):
            r.weights_at(190, np.ones(300), np.ones(300))

    def test_zero_past_volume(self):
        p = np.arange(300, dtype=float) + 100
        self.assertEqual(
            r.weights_at(250, p, np.zeros(300)), (-float("inf"), -float("inf"))
        )

    def test_price_return_not_forward(self):
        p = np.arange(300, dtype=float) + 100
        v = np.ones(300)
        self.assertGreater(r.weights_at(250, p, v)[1], 0)
        p[249] = p[225] * 0.98
        self.assertEqual(r.weights_at(250, p, v), (-float("inf"), -float("inf")))


if __name__ == "__main__":
    unittest.main()
