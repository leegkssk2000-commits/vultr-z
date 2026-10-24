import sys
import unittest
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from run import signal, metrics


def bars():
    a = deque(maxlen=65)
    for i in range(61):
        a.append({"close": 100.0 if i < 60 else 98.5, "volume": 1.0 if i < 60 else 4.0})
    return a


class SafetyTests(unittest.TestCase):
    def test_causal_late_downside(self):
        self.assertTrue(signal(bars(), -0.01, 3.0, 60))

    def test_low_volume_no_signal(self):
        a = bars()
        a[-1]["volume"] = 1.0
        self.assertFalse(signal(a, -0.01, 3.0, 60))

    def test_zero_price_drill_refused_by_loader(self):
        a = bars()
        a[-1]["close"] = 100
        self.assertFalse(signal(a, -0.01, 3.0, 60))

    def test_no_history(self):
        self.assertFalse(signal(deque(maxlen=65), -0.01, 3.0, 60))

    def test_three_min_cost_and_zero_trade_handling(self):
        m = metrics(
            [
                {
                    "net2_bps": -20,
                    "net1_bps": 0,
                    "gross_bps": 20,
                    "exit_ts_ms": 3000,
                    "entry_ts_ms": 0,
                    "symbol": "SOL-USDT",
                }
            ],
            1,
        )
        self.assertEqual(m["Gross_per_T_bps"], 20)
        self.assertEqual(m["MaxLossStreak2"], 1)
        self.assertEqual(m["cost2_net_sum_trade_bps"], -20)
        self.assertIsNone(metrics([], 1)["PF2"])


if __name__ == "__main__":
    unittest.main()
