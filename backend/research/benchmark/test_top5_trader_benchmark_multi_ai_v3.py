from __future__ import annotations

import unittest

from backend.research.benchmark import top5_trader_benchmark_multi_ai_v3 as m


class Top5TraderBenchmarkRiskPathTests(unittest.TestCase):
    def test_symbol_append_order_does_not_define_drawdown(self) -> None:
        trades = [
            {"symbol": "BTC-USDT", "entry_ts": 0, "exit_ts": 2, "net_bps": 100.0, "realized_cost_bps": 1.0},
            {"symbol": "BTC-USDT", "entry_ts": 2, "exit_ts": 4, "net_bps": -120.0, "realized_cost_bps": 1.0},
            {"symbol": "ETH-USDT", "entry_ts": 0, "exit_ts": 1, "net_bps": -100.0, "realized_cost_bps": 1.0},
            {"symbol": "ETH-USDT", "entry_ts": 1, "exit_ts": 3, "net_bps": 150.0, "realized_cost_bps": 1.0},
        ]
        metrics = m.chronological_metrics(trades)
        self.assertEqual(metrics["drawdown_bps"], 120.0)
        self.assertEqual(metrics["max_losing_streak"], 1)
        self.assertEqual(metrics["drawdown_authority"], "EXIT_TIMESTAMP_BUCKET_ASC")
        self.assertEqual(metrics["exit_bucket_count"], 4)

    def test_simultaneous_exits_are_netted_before_risk_path(self) -> None:
        trades = [
            {"symbol": "BTC-USDT", "entry_ts": 0, "exit_ts": 10, "net_bps": 200.0, "realized_cost_bps": 1.0},
            {"symbol": "ETH-USDT", "entry_ts": 0, "exit_ts": 10, "net_bps": -180.0, "realized_cost_bps": 1.0},
            {"symbol": "SOL-USDT", "entry_ts": 10, "exit_ts": 11, "net_bps": -10.0, "realized_cost_bps": 1.0},
        ]
        metrics = m.chronological_metrics(trades)
        self.assertEqual(metrics["drawdown_bps"], 10.0)
        self.assertEqual(metrics["max_losing_streak"], 1)
        self.assertEqual(metrics["exit_bucket_count"], 2)
        self.assertEqual(metrics["simultaneous_exit_ordering"], "NET_PNL_AGGREGATED_PER_EXIT_TS")


if __name__ == "__main__":
    unittest.main()
