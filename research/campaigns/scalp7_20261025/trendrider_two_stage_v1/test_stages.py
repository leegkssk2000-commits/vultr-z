import unittest
from stages import (
    extension_winner_rule,
    trailing_extension,
    loss_risk_factor,
    risk_of,
    metrics,
    H,
)


def row(reason="TIMEOUT", gross=10000, stop=99, entry=100, exit=101, exit_ts=25 * H):
    return {
        "reason": reason,
        "gross_bps": gross,
        "net_bps": gross - 10,
        "entry": entry,
        "exit": exit,
        "intent_geometry": {"sl": stop},
        "entry_ts": 1 * H,
        "exit_ts": exit_ts,
        "side": "long",
        "realized_cost_bps": 10,
        "net2_bps": gross - 20,
        "symbol": "BTC-USDT",
    }


class CausalGates(unittest.TestCase):
    def test_initial_r(self):
        self.assertEqual(risk_of(row()), 1)

    def test_loser_not_extended(self):
        x = row(exit=99.5)
        bars = [
            {"ts_ms": i * H, "open": 100, "high": 102, "low": 99.5, "close": 101}
            for i in range(45)
        ]
        self.assertFalse(extension_winner_rule(x, bars, 25, [100] * 45, 43 * H))

    def test_timeout_positive_trend_required(self):
        x = row(exit=102)
        bars = [
            {"ts_ms": i * H, "open": 101, "high": 103, "low": 100, "close": 102}
            for i in range(45)
        ]
        ema = [100] * 44 + [100.1]
        self.assertFalse(extension_winner_rule(x, bars, 25, ema, 44 * H))
        ema[24] = 100
        ema[25] = 101
        self.assertTrue(extension_winner_rule(x, bars, 25, ema, 44 * H))

    def test_low_before_high_stop_first(self):
        x = row(exit=102)
        bars = [
            {"ts_ms": i * H, "open": 102, "low": 101, "high": 104, "close": 103}
            for i in range(45)
        ]
        bars[26] = {"ts_ms": 26 * H, "open": 102, "low": 100, "high": 200, "close": 198}
        e = [100] * 45
        e[25] = 101
        res = trailing_extension(x, bars, 25, e, 44 * H)
        self.assertTrue(res["attempted"])
        self.assertEqual(res["reason"], "EXT_STOP_FIRST")
        self.assertEqual(res["exit"], 100.75)

    def test_gap_stop_worse_than_floor(self):
        x = row(exit=102)
        bars = [
            {"ts_ms": i * H, "open": 102, "low": 101, "high": 104, "close": 103}
            for i in range(45)
        ]
        bars[26] = {"ts_ms": 26 * H, "open": 99, "low": 98, "high": 102, "close": 101}
        e = [100] * 45
        e[25] = 101
        res = trailing_extension(x, bars, 25, e, 44 * H)
        self.assertEqual(res["reason"], "EXT_GAP_STOP")
        self.assertEqual(res["exit"], 99)

    def test_incomplete_future_cannot_claim_extension(self):
        x = row(exit=102)
        bars = [
            {"ts_ms": i * H, "open": 102, "low": 101, "high": 103, "close": 102}
            for i in range(28)
        ]
        e = [100] * 28
        e[25] = 101
        res = trailing_extension(x, bars, 25, e, 26 * H)
        self.assertFalse(res["attempted"])

    def test_two_past_losses_soft_reduction(self):
        a = row(gross=-50, exit_ts=2 * H)
        b = row(gross=-100, exit_ts=3 * H)
        self.assertEqual(loss_risk_factor(8 * H, [a, b]), 0.75)

    def test_future_close_not_available(self):
        a = row(gross=-50, exit_ts=9 * H)
        b = row(gross=-100, exit_ts=10 * H)
        self.assertEqual(loss_risk_factor(10 * H, [a, b]), 1.0)

    def test_consecutive_two_not_one(self):
        a = row(gross=-50, exit_ts=2 * H)
        b = row(gross=100, exit_ts=3 * H)
        self.assertEqual(loss_risk_factor(8 * H, [a, b]), 1.0)

    def test_old_streak_expiry(self):
        a = row(gross=-50, exit_ts=2 * H)
        b = row(gross=-50, exit_ts=3 * H)
        self.assertEqual(loss_risk_factor(30 * H, [a, b]), 1.0)

    def test_no_forged_pf_with_empty_rows(self):
        x = metrics([])
        self.assertEqual(x["T"], 0)
        self.assertIsNone(x["Net2_profit_factor"])


class StageSafetyAdditional(unittest.TestCase):
    def test_stage2_never_discards_trades_or_creates_cost(self):
        from stages import stage2_soft_risk

        a = row(gross=-100, exit_ts=2 * H)
        b = row(gross=-150, exit_ts=3 * H)
        c = row(gross=200, exit_ts=8 * H)
        a.update({"symbol": "BTC-USDT", "signal_ts": 0, "entry_ts": 0})
        b.update({"symbol": "ETH-USDT", "signal_ts": H, "entry_ts": H})
        c.update({"symbol": "SOL-USDT", "signal_ts": 7 * H, "entry_ts": 8 * H})
        original = [a, b, c]
        out, stats = stage2_soft_risk(original)
        self.assertEqual(len(out), len(original))
        self.assertEqual(stats["reduce25_executions"], 1)
        chosen = next(z for z in out if z["symbol"] == "SOL-USDT")
        self.assertEqual(chosen["stage2_risk_factor"], 0.75)
        self.assertAlmostEqual(chosen["gross_bps"], 150)
        self.assertAlmostEqual(original[-1]["gross_bps"], 200)

    def test_timeout_exit_never_if_stop_or_not_trending(self):
        bars = [
            {"ts_ms": i * H, "open": 100, "high": 102, "low": 99, "close": 101}
            for i in range(45)
        ]
        e = [100.0] * 45
        self.assertFalse(
            trailing_extension(row(reason="SL"), bars, 25, e, 44 * H)["attempted"]
        )

    def test_lagged_trail_ignores_same_candle_high_for_stop(self):
        x = row(exit=102)
        bars = [
            {"ts_ms": i * H, "open": 102, "low": 101.8, "high": 102.1, "close": 102}
            for i in range(45)
        ]
        bars[26] = {
            "ts_ms": 26 * H,
            "open": 102,
            "low": 101.8,
            "high": 500,
            "close": 102.5,
        }
        bars[27] = {
            "ts_ms": 27 * H,
            "open": 102.5,
            "low": 101.8,
            "high": 103,
            "close": 102.0,
        }
        e = [100] * 45
        e[25] = 101
        res = trailing_extension(x, bars, 25, e, 44 * H)
        self.assertTrue(res["attempted"])
        self.assertEqual(res["exit_index"], 27)
        self.assertEqual(res["reason"], "EXT_GAP_STOP")

    def test_source_end_must_not_be_future_spliced(self):
        x = row(exit=102)
        bars = [
            {"ts_ms": i * H, "open": 102, "low": 101.8, "high": 103, "close": 102}
            for i in range(29)
        ]
        e = [100] * 29
        e[25] = 101
        res = trailing_extension(x, bars, 25, e, 28 * H)
        self.assertEqual(res["reason"], "UNOBSERVED_12H_EXTENSION_INELIGIBLE")


if __name__ == "__main__":
    unittest.main()
