from __future__ import annotations

import unittest
from fuse_and_recover import (
    H,
    SCALE,
    atr_14,
    bailout_close_candidate,
    entry_loss_streak_circuit,
    make_leg,
    new_short_leg,
    short_confirmation,
    metrics_stage,
    epoch,
    last_confirmed_closed_1h_open,
)


def candles(n=100, price=100.0):
    return [
        {
            "ts_ms": j * H,
            "open": price,
            "high": price + 2.0,
            "low": price - 2.0,
            "close": price,
            "volume": 1,
        }
        for j in range(n)
    ]


def trade():
    return {
        "canonical_key": "BTC-USDT|long|0",
        "source_lane": "Liquid6",
        "symbol": "BTC-USDT",
        "signal_ts": 0,
        "entry_ts": 25 * H,
        "exit_ts": 73 * H,
        "entry": 100.0,
        "exit": 105.0,
        "reason": "TIMEOUT",
        "side": "long",
        "intent_geometry": {"sl": 95.0},
        "instrument_source_cost_bps": 14.0,
        "realized_cost_bps": 14 * SCALE,
        "gross_bps": 500 * SCALE,
        "net2_bps": (500 - 28) * SCALE,
    }


class FrozenRiskTests(unittest.TestCase):
    def test_long_normalized_factor(self):
        t = trade()
        cost = 14 * SCALE
        leg = make_leg(
            side="long",
            original=t,
            entry_ts=25 * H,
            terminal_open_ms=73 * H,
            terminal_effective_ms=74 * H,
            entry_px=100.0,
            exit_px=105.0,
            cost_bps=cost,
            reason="TIMEOUT",
            kind="PRIMARY_LONG",
        )
        self.assertAlmostEqual(leg["gross_bps"], 500 * SCALE)
        self.assertAlmostEqual(leg["Net2_bps"], (500 - 28) * SCALE)

    def test_short_new_leg_no_double_size(self):
        t = trade()
        bars = candles(120)
        bars[26]["open"] = 100.0
        leg = new_short_leg(
            trade=t, market=bars, trigger_j=25, latest_closed_open_ms=119 * H
        )
        self.assertIsNotNone(leg)
        self.assertEqual(leg["side"], "short")
        self.assertEqual(leg["kind"], "REVERSAL_SHORT")
        self.assertGreater(leg["short_initial_r_bps"], 0)
        self.assertLess(leg["modeled_cost_bps"], 30)

    def test_short_gap_worse_than_stop(self):
        t = trade()
        bars = candles(120)
        bars[26] = {
            "ts_ms": 26 * H,
            "open": 100.0,
            "high": 100.0,
            "low": 99,
            "close": 99,
            "volume": 1,
        }
        bars[27] = {
            "ts_ms": 27 * H,
            "open": 116.0,
            "high": 117.0,
            "low": 114,
            "close": 114,
            "volume": 1,
        }
        leg = new_short_leg(
            trade=t, market=bars, trigger_j=25, latest_closed_open_ms=119 * H
        )
        self.assertIsNotNone(leg)
        self.assertEqual(leg["exit"], 116)
        self.assertEqual(leg["reason"], "SHORT_STOP_GAP_OPEN")
        self.assertLess(leg["Net2_bps"], 0)

    def test_unobserved_future_short_is_rejected(self):
        t = trade()
        bars = candles(41)
        leg = new_short_leg(
            trade=t, market=bars, trigger_j=25, latest_closed_open_ms=34 * H
        )
        self.assertIsNone(leg)

    def test_atr_not_using_later_future(self):
        bars = candles(100)
        a = atr_14(bars, 25)
        bars[26]["high"] = 10_000.0
        self.assertEqual(atr_14(bars, 25), a)

    def test_short_confirm_requires_bearish_known_closes(self):
        bars = candles(80)
        ema = [100.0] * 80
        ema[24] = 99.8
        ema[25] = 99.6
        bars[24]["close"] = 99.7
        bars[25]["close"] = 99.5
        self.assertTrue(short_confirmation(last_completed_idx=25, bars=bars, ema=ema))
        bars[25]["close"] = 100.0
        self.assertFalse(short_confirmation(last_completed_idx=25, bars=bars, ema=ema))

    def test_bailout_requires_two_closed_bars(self):
        t = trade()
        bars = candles(95)
        bars[26]["low"] = 98
        bars[26]["close"] = 99.0
        bars[27]["low"] = 96
        bars[27]["close"] = 97.0
        ema = [100.0] * 95
        ema[26] = 99.5
        ema[27] = 99.3
        t["intent_geometry"]["sl"] = 95
        m = {x["ts_ms"]: i for i, x in enumerate(bars)}
        result = bailout_close_candidate(t, bars, ema, m)
        self.assertIsNotNone(result)
        self.assertEqual(result["exit_index"], 28)
        self.assertEqual(result["effective_closed_at"], 28 * H)

    def test_original_stop_has_higher_priority_than_bailout(self):
        t = trade()
        t["reason"] = "SL"
        t["exit_ts"] = 27 * H
        t["exit"] = 95.0
        bars = candles(95)
        bars[26]["low"] = 98
        bars[26]["close"] = 99.0
        bars[27]["low"] = 94
        bars[27]["close"] = 93.0
        ema = [100.0] * 95
        ema[26] = 99.5
        ema[27] = 99.3
        m = {x["ts_ms"]: i for i, x in enumerate(bars)}
        self.assertIsNone(bailout_close_candidate(t, bars, ema, m))

    def test_circuit_needs_three_finished_losses(self):
        done = [{"key": str(i), "end_ms": i * H, "Net2_bps": -10.0} for i in (2, 3, 4)]
        self.assertFalse(entry_loss_streak_circuit(at=4 * H, completed=done))
        self.assertTrue(entry_loss_streak_circuit(at=5 * H, completed=done))
        self.assertTrue(entry_loss_streak_circuit(at=6 * H, completed=done))
        self.assertFalse(entry_loss_streak_circuit(at=10 * H, completed=done))
        self.assertFalse(entry_loss_streak_circuit(at=12 * H, completed=done))

    def test_circuit_ignores_future_known_outcomes(self):
        done = [
            {"key": str(i), "end_ms": i * H, "Net2_bps": -10.0} for i in (2, 3, 100)
        ]
        self.assertFalse(entry_loss_streak_circuit(at=6 * H, completed=done))

    def test_no_circuit_after_win(self):
        done = [
            {"key": str(i), "end_ms": i * H, "Net2_bps": (-1 if i != 3 else 10)}
            for i in (2, 3, 4)
        ]
        self.assertFalse(entry_loss_streak_circuit(at=6 * H, completed=done))

    def test_no_fake_double_profit_from_two_legs(self):
        a = make_leg(
            side="long",
            original=trade(),
            entry_ts=25 * H,
            terminal_open_ms=26 * H,
            terminal_effective_ms=27 * H,
            entry_px=100.0,
            exit_px=95.0,
            cost_bps=4.0,
            reason="SL",
            kind="PRIMARY_LONG",
        )
        b = make_leg(
            side="short",
            original=trade(),
            entry_ts=27 * H,
            terminal_open_ms=39 * H,
            terminal_effective_ms=40 * H,
            entry_px=95.0,
            exit_px=75.0,
            cost_bps=8.0,
            reason="SHORT_TIME24_CLOSED",
            kind="REVERSAL_SHORT",
        )
        o = {
            "key": "BTC-USDT|long|0",
            "source_lane": "Liquid6",
            "symbol": "BTC-USDT",
            "signal_ts": 0,
            "entry_ts": 25 * H,
            "initial_long_r_bps": 150.0,
            "Net2_bps": a["Net2_bps"] + b["Net2_bps"],
            "end_ms": 40 * H,
            "legs": [a, b],
            "original_native_net2_bps": -180,
        }
        m = metrics_stage({"admitted": [o]})
        self.assertEqual(m["accepted_opportunities"], 1)
        self.assertEqual(m["total_legs"], 2)
        self.assertEqual(m["reverse_short_legs"], 1)
        self.assertAlmostEqual(m["Net2_sum_trade_bps"], a["Net2_bps"] + b["Net2_bps"])

    def test_short_24h_time_limit_not_25th_candle(self):
        t = trade()
        bars = candles(120)
        bars[50]["open"] = 100
        bars[50]["high"] = 9999  # the forbidden 25th hourly candle
        leg = new_short_leg(
            trade=t, market=bars, trigger_j=25, latest_closed_open_ms=119 * H
        )
        self.assertIsNotNone(leg)
        self.assertEqual(leg["reason"], "SHORT_TIME24_CLOSED")
        self.assertEqual(leg["short_held_bar_count"], 24)
        self.assertEqual(leg["entry_ts"], 26 * H)
        self.assertEqual(leg["effective_closed_at"], 50 * H)
        self.assertLessEqual(leg["effective_closed_at"] - leg["entry_ts"], 24 * H)

    def test_short_requires_last_24th_bar_closed(self):
        t = trade()
        bars = candles(120)
        self.assertIsNone(
            new_short_leg(
                trade=t, market=bars, trigger_j=25, latest_closed_open_ms=48 * H
            )
        )
        self.assertIsNotNone(
            new_short_leg(
                trade=t, market=bars, trigger_j=25, latest_closed_open_ms=49 * H
            )
        )

    def test_no_unfinished_source_candle(self):
        self.assertEqual(
            last_confirmed_closed_1h_open("2026-10-25T08:01:20.410374Z"),
            1792911600000,
        )
        self.assertEqual(last_confirmed_closed_1h_open("1970-01-01T01:00:00Z"), 0)

    def test_no_future_availability_epoch_conversion(self):
        self.assertEqual(epoch("1970-01-01T01:00:00Z"), H)


if __name__ == "__main__":
    unittest.main()
