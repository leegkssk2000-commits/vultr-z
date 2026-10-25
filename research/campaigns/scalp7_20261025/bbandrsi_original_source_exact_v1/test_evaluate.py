"""Costed source-rule and adverse accounting checks. Not formal future OOS."""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

import evaluate as e


def frame(
    open_prices,
    high_prices,
    low_prices,
    closes,
    *,
    forced_signal=None,
    forced_exit=None,
):
    n = len(closes)
    f = pd.DataFrame(
        {
            "ts_ms": [i * e.HOUR for i in range(n)],
            "open": open_prices,
            "high": high_prices,
            "low": low_prices,
            "close": closes,
            "signal_long": (
                forced_signal if forced_signal is not None else [False] * n
            ),
            "signal_exit": (forced_exit if forced_exit is not None else [False] * n),
        }
    )
    return f


class SourceExactRisk(unittest.TestCase):
    def test_wilder_uptrend_reaches_100(self):
        x = e.wilder_rsi_talib_seeded(np.arange(40, dtype=float) + 10.0)
        self.assertTrue(np.isnan(x[:14]).all())
        self.assertAlmostEqual(float(x[14]), 100.0)
        self.assertAlmostEqual(float(x[-1]), 100.0)

    def test_wilder_downtrend_reaches_zero(self):
        x = e.wilder_rsi_talib_seeded(100.0 - np.arange(40, dtype=float))
        self.assertTrue(np.isnan(x[:14]).all())
        self.assertAlmostEqual(float(x[-1]), 0.0)

    def test_first_rsi_seed_simple_14_gains_losses(self):
        prices = np.array(
            [
                100,
                101,
                100,
                101,
                100,
                101,
                100,
                101,
                100,
                101,
                100,
                101,
                100,
                101,
                100.0,
            ]
        )
        x = e.wilder_rsi_talib_seeded(prices)
        expected = 100.0 * 7.0 / 14.0
        self.assertAlmostEqual(float(x[14]), expected)

    def test_bollinger_uses_sample_std_not_old_population(self):
        closes = [
            101.0,
            100.0,
            100.0,
            100.0,
            99.0,
            99.0,
            99.0,
            99.0,
            99.0,
            99.0,
            99.0,
            99.0,
            99.0,
            99.0,
            99.0,
            99.0,
            99.0,
            99.0,
            99.0,
            99.0,
        ]
        x = pd.DataFrame(
            {"open": closes, "high": closes, "low": closes, "close": closes}
        )
        new = e.indicators(x)
        typical = pd.Series(closes)
        exp = typical.rolling(20, min_periods=1).mean() - 2 * typical.rolling(
            20, min_periods=1
        ).std(ddof=1)
        old = typical.rolling(20, min_periods=1).mean() - 2 * typical.rolling(
            20, min_periods=1
        ).std(ddof=0)
        self.assertAlmostEqual(float(new.iloc[-1].boll_lower), float(exp.iloc[-1]))
        self.assertNotAlmostEqual(float(new.iloc[-1].boll_lower), float(old.iloc[-1]))

    def test_next_open_not_same_signal_close(self):
        f = frame(
            [100.0, 100.0, 90.0, 90.0],
            [100.0, 100.0, 90.0, 90.0],
            [100.0, 100.0, 90.0, 90.0],
            [100.0, 100.0, 90.0, 90.0],
            forced_signal=[False, True, False, False],
        )
        v = e.simulate_symbol(f, 40)
        self.assertEqual(v["entered_T"], 1)
        self.assertEqual(v["still_open_T"], 1)
        self.assertEqual(v["open_at_end"]["entry_ts_ms"], 2 * e.HOUR)
        self.assertEqual(v["open_at_end"]["entry_price"], 90.0)

    def test_stop_first_when_both_hit_same_candle(self):
        f = frame(
            [100.0, 100.0, 100.0],
            [100.0, 100.0, 115.0],
            [100.0, 100.0, 70.0],
            [100.0, 100.0, 100.0],
            forced_signal=[True, False, False],
        )
        v = e.simulate_symbol(f, 40)
        self.assertEqual(v["closed_T"], 1)
        self.assertEqual(v["trades"][0]["reason"], "STOP_FIRST")
        self.assertAlmostEqual(v["trades"][0]["net_bps"], -2540.0)

    def test_gap_stop_worse_actual_open(self):
        f = frame(
            [100.0, 100.0, 70.0],
            [100.0, 100.0, 75.0],
            [100.0, 100.0, 65.0],
            [100.0, 100.0, 70.0],
            forced_signal=[True, False, False],
        )
        v = e.simulate_symbol(f, 40)
        self.assertEqual(v["trades"][0]["reason"], "STOP_GAP_ACTUAL_OPEN")
        self.assertLess(v["trades"][0]["net_bps"], -2500)

    def test_original_roi_cap_at_10pct_and_cost(self):
        f = frame(
            [100.0, 100.0, 100.0],
            [100.0, 112.0, 100.0],
            [100.0, 99.0, 100.0],
            [100.0, 110.0, 100.0],
            forced_signal=[True, False, False],
        )
        v = e.simulate_symbol(f, 40)
        self.assertEqual(v["trades"][0]["reason"], "ROI_10PCT")
        self.assertAlmostEqual(v["trades"][0]["net_bps"], 960.0)

    def test_exit_signal_is_next_candle_open(self):
        f = frame(
            [100.0, 100.0, 106.0, 104.0],
            [100.0, 102.0, 106.0, 104.0],
            [100.0, 98.0, 106.0, 104.0],
            [100.0, 100.0, 106.0, 104.0],
            forced_signal=[True, False, False, False],
            forced_exit=[False, True, False, False],
        )
        v = e.simulate_symbol(f, 40)
        self.assertEqual(v["closed_T"], 1)
        self.assertEqual(v["trades"][0]["reason"], "RSI_GT70_NEXT_OPEN")
        self.assertEqual(v["trades"][0]["exit_ts_ms"], 2 * e.HOUR)
        self.assertAlmostEqual(v["trades"][0]["net_bps"], 560.0)

    def test_unfinished_trade_mark_is_included_not_fake_closed(self):
        f = frame(
            [100.0, 100.0, 80.0],
            [100.0, 100.0, 80.0],
            [100.0, 100.0, 80.0],
            [100.0, 100.0, 80.0],
            forced_signal=[False, True, False],
        )
        v = e.simulate_symbol(f, 40)
        self.assertEqual(v["closed_T"], 0)
        self.assertEqual(v["still_open_T"], 1)
        self.assertEqual(v["open_at_end"]["not_realized"], True)
        self.assertAlmostEqual(v["terminal_equity_unit"], 1 - 20 / 10000)

    def test_extra_one_candle_delay_is_only_stress(self):
        f = frame(
            [100.0, 100.0, 90.0, 80.0, 70.0],
            [100.0, 100.0, 90.0, 80.0, 70.0],
            [100.0, 100.0, 90.0, 80.0, 70.0],
            [100.0, 100.0, 90.0, 80.0, 70.0],
            forced_signal=[False, True, False, False, False],
        )
        a = e.simulate_symbol(f, 40, 0)
        b = e.simulate_symbol(f, 40, 1)
        self.assertEqual(a["open_at_end"]["entry_ts_ms"], 2 * e.HOUR)
        self.assertEqual(b["open_at_end"]["entry_ts_ms"], 3 * e.HOUR)
        self.assertNotEqual(a["terminal_equity_unit"], b["terminal_equity_unit"])

    def test_no_future_signal_entry_at_final_bar(self):
        f = frame(
            [100.0, 100.0, 100.0],
            [100.0, 100.0, 100.0],
            [100.0, 100.0, 100.0],
            [100.0, 100.0, 100.0],
            forced_signal=[False, False, True],
        )
        v = e.simulate_symbol(f, 40)
        self.assertEqual(v["entered_T"], 0)
        self.assertEqual(v["signals_T"], 1)
        self.assertIsNone(v["open_at_end"])

    def test_strategy_rejects_unbounded_cost_or_delay(self):
        f = frame([100.0] * 3, [100.0] * 3, [100.0] * 3, [100.0] * 3)
        with self.assertRaises(AssertionError):
            e.simulate_symbol(f, 400)
        with self.assertRaises(AssertionError):
            e.simulate_symbol(f, 40, 2)


if __name__ == "__main__":
    unittest.main()
