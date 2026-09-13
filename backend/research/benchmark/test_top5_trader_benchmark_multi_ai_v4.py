from __future__ import annotations

import unittest

from backend.research.benchmark import top5_trader_benchmark_multi_ai_v4 as m


class Top5TraderBenchmarkEntryBarStopTests(unittest.TestCase):
    def test_long_ambiguous_entry_bar_uses_sealed_stop(self) -> None:
        child = {"trades": [{
            "reason": "CONSERVATIVE_INTRABAR_STOP", "side": "long", "entry": 105.0,
            "initial_stop": 95.0, "exit": 90.0, "entry_ts": 1, "exit_ts": 1,
            "gross_bps": -1.0, "realized_cost_bps": 10.0, "net_bps": -11.0,
        }]}
        out = m.repair_entry_bar_intrabar_stops(child)
        trade = out["trades"][0]
        self.assertEqual(trade["exit"], 95.0)
        self.assertEqual(out["entry_bar_intrabar_stop_repairs"], 1)
        self.assertEqual(trade["entry_bar_stop_price_authority"], "SEALED_PROTECTIVE_STOP_POST_FILL")

    def test_short_ambiguous_entry_bar_uses_sealed_stop(self) -> None:
        child = {"trades": [{
            "reason": "CONSERVATIVE_INTRABAR_STOP", "side": "short", "entry": 95.0,
            "initial_stop": 105.0, "exit": 110.0, "entry_ts": 2, "exit_ts": 2,
            "gross_bps": -1.0, "realized_cost_bps": 10.0, "net_bps": -11.0,
        }]}
        out = m.repair_entry_bar_intrabar_stops(child)
        self.assertEqual(out["trades"][0]["exit"], 105.0)
        self.assertEqual(out["entry_bar_intrabar_stop_repairs"], 1)

    def test_non_ambiguous_exit_is_untouched(self) -> None:
        child = {"trades": [{
            "reason": "INITIAL_SWING_STOP", "side": "long", "entry": 100.0,
            "initial_stop": 95.0, "exit": 95.0, "entry_ts": 1, "exit_ts": 2,
            "gross_bps": -500.0, "realized_cost_bps": 10.0, "net_bps": -510.0,
        }]}
        out = m.repair_entry_bar_intrabar_stops(child)
        self.assertEqual(out["trades"][0]["exit"], 95.0)
        self.assertEqual(out["entry_bar_intrabar_stop_repairs"], 0)


if __name__ == "__main__":
    unittest.main()
