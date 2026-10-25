from __future__ import annotations

import unittest

from backend.research.benchmark import top5_trader_benchmark_multi_ai_v1 as m


class Top5TraderBenchmarkTests(unittest.TestCase):
    def test_boundary_key_transport(self) -> None:
        value, problem = m.boundary_clean_key(" \tAPI_KEY_123\r\n")
        self.assertEqual(value, "API_KEY_123")
        self.assertIsNone(problem)
        for bad in ("a b", "a\tb", "a\nb", "a\x00b", "a\x7fb", "aéb", " \r\n\t "):
            value, problem = m.boundary_clean_key(bad)
            self.assertIsNone(value)
            self.assertIsNotNone(problem)

    def test_source_decision_is_bounded(self) -> None:
        self.assertEqual(len(m.SOURCE_PACKET), 4)
        self.assertEqual(set(m.DECISION_TEMPLATE), set(m.NATIVE_FINGERPRINTS))
        executable = [row for row in m.DECISION_TEMPLATE.values() if row["decision"] == "EXECUTE"]
        self.assertEqual(len(executable), 1)
        self.assertEqual(executable[0]["candidate_id"], "supertrend_pullback__lbr_holy_grail_adx30_ema20_v1")
        self.assertLessEqual(sum(m.RESERVED_USD.values()), 1.50)
        self.assertEqual(sum(m.MAX_NEW_GENERATION_CALLS.values()), 2)

    def test_metrics_include_tail_cost_and_exposure(self) -> None:
        trades = [
            {"entry_ts": 0, "exit_ts": 3_600_000, "net_bps": 120.0, "realized_cost_bps": 4.0},
            {"entry_ts": 3_600_000, "exit_ts": 7_200_000, "net_bps": -30.0, "realized_cost_bps": 5.0},
            {"entry_ts": 7_200_000, "exit_ts": 10_800_000, "net_bps": -20.0, "realized_cost_bps": 6.0},
            {"entry_ts": 10_800_000, "exit_ts": 14_400_000, "net_bps": 80.0, "realized_cost_bps": 4.0},
        ]
        metrics = m.metrics_from_trades(trades)
        self.assertEqual(metrics["trades"], 4)
        self.assertAlmostEqual(metrics["win_rate"], 0.5)
        self.assertEqual(metrics["max_losing_streak"], 2)
        self.assertEqual(metrics["cost_total_bps"], 19.0)
        self.assertGreater(metrics["holding_hours_total"], 0)
        self.assertGreater(metrics["pnl_without_best_trade_bps"], 0)

    def test_adx_is_causal_length_preserving(self) -> None:
        bars = []
        close = 100.0
        for i in range(90):
            op = close
            close += 1.0 if i < 50 else (-0.3 if i < 62 else 0.6)
            bars.append({
                "ts_ms": i * 3_600_000,
                "open": op,
                "high": max(op, close) + 0.4,
                "low": min(op, close) - 0.4,
                "close": close,
            })
        adx, plus_di, minus_di = m.adx_wilder(bars, 14)
        self.assertEqual(len(adx), len(bars))
        self.assertEqual(len(plus_di), len(bars))
        self.assertEqual(len(minus_di), len(bars))
        self.assertTrue(any(x is not None for x in adx[27:]))


if __name__ == "__main__":
    unittest.main()
