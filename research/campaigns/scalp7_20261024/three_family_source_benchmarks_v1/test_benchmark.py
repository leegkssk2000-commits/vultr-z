import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import numpy as np
import pandas as pd
import benchmark as b


class BenchTests(unittest.TestCase):
    def test_gmma_true_transition(self):
        first = {"gmma_short_min": 9, "gmma_long_max": 10, "ema_60": 9}
        now = {"gmma_short_min": 11, "gmma_long_max": 10, "ema_60": 10}
        self.assertTrue(b.signal_for(b.TREND, [first, now], 1) is False)
        records = [first] * 239 + [first, now]
        self.assertTrue(b.signal_for(b.TREND, records, 240))

    def test_gmma_no_repeat(self):
        x = {"gmma_short_min": 11, "gmma_long_max": 10, "ema_60": 11}
        self.assertFalse(b.signal_for(b.TREND, [x] * 241, 240))

    def test_momentum_sign_flip(self):
        a = {"mom_score": -0.01}
        z = {"mom_score": 0.1}
        self.assertTrue(b.signal_for(b.MOM, [a] * 240 + [z], 240))
        self.assertFalse(b.signal_for(b.MOM, [z] * 241, 240))

    def test_connors_7_low_filter(self):
        s = {"sma200": 100, "close7_min": 104, "close": 104}
        self.assertTrue(b.signal_for(b.COUNTER, [s] * 241, 240))
        s2 = {"sma200": 110, "close7_min": 104, "close": 104}
        self.assertFalse(b.signal_for(b.COUNTER, [s2] * 241, 240))

    def test_exit_checks(self):
        self.assertTrue(b.take_exit_on_close(b.TREND, {"ema_15": 9, "ema_30": 10}))
        self.assertTrue(b.take_exit_on_close(b.MOM, {"mom_score": -1}))
        self.assertTrue(
            b.take_exit_on_close(b.COUNTER, {"close": 10, "close7_max": 10})
        )

    def test_stop_gap_priority(self):
        self.assertEqual(b.exit_at_open(80, 90, True), (80, "STOP_GAP"))
        self.assertEqual(b.exit_at_open(100, 90, True), (100, "SCHEDULED_NEXT_OPEN"))

    def test_four_hour_group_only_full(self):
        n = 11
        frame = pd.DataFrame(
            {
                "timestamp_ms": np.arange(n, dtype=np.int64) * b.ONE_HOUR,
                "open": np.arange(n) + 10,
                "high": np.arange(n) + 12,
                "low": np.arange(n) + 9,
                "close": np.arange(n) + 11,
                "volume": np.ones(n),
            }
        )
        # two complete four-hour candles and one partial, rejected by main min sample
        with self.assertRaisesRegex(ValueError, "FOUR_HOUR_AGGREGATION_GAP"):
            b.to_actual_4h(frame)

    def test_duplicate_stale_source_gap_fail(self):
        df = pd.DataFrame(
            {"timestamp_ms": np.arange(1000, dtype=np.int64) * b.ONE_HOUR}
        )
        arr = df.timestamp_ms.to_numpy()
        self.assertFalse(np.all(np.diff(np.delete(arr, 800)) == b.ONE_HOUR))

    def test_fees_and_unexecuted(self):
        self.assertIsNone(b.metrics([], 0, b.DAY)["PF2x"])
        self.assertEqual(b.metrics([], 0, b.DAY)["T"], 0)

    def test_avoids_holdout_lookahead_when_source_cut(self):
        f = pd.DataFrame({"close": np.arange(500, dtype=float) + 100})
        a = b.enrich(
            pd.DataFrame(
                {
                    "close": f.close,
                    "open": f.close,
                    "high": f.close + 1,
                    "low": f.close - 1,
                    "open_ts_ms": np.arange(500) * b.FOUR_HOURS,
                    "close_ts_ms": (np.arange(500) + 1) * b.FOUR_HOURS,
                    "volume": np.ones(500),
                }
            )
        )
        future = f.close.to_numpy().copy()
        future[499] = 1000000
        cp = pd.DataFrame(
            {
                "close": future,
                "open": future,
                "high": future + 1,
                "low": future - 1,
                "open_ts_ms": np.arange(500) * b.FOUR_HOURS,
                "close_ts_ms": (np.arange(500) + 1) * b.FOUR_HOURS,
                "volume": np.ones(500),
            }
        )
        newer = b.enrich(cp)
        self.assertAlmostEqual(a.ema_60.iloc[498], newer.ema_60.iloc[498])
        self.assertAlmostEqual(a.mom_score.iloc[498], newer.mom_score.iloc[498])


if __name__ == "__main__":
    unittest.main()
