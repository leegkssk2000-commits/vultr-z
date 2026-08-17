from __future__ import annotations

import unittest
from datetime import datetime, timezone

from backend.research.rebuild import a1_exact25_parallel_evidence_scheduler_v1 as v1
from backend.research.rebuild import a1_exact25_parallel_evidence_scheduler_v2 as s
from backend.research.rebuild.test_a1_exact25_parallel_evidence_scheduler_v1 import base_ledger, clock_for


class ParallelSchedulerV2Tests(unittest.TestCase):
    def _trading_heavy(self) -> tuple[dict, dict]:
        ledger = base_ledger()
        clock = clock_for(ledger)
        row = ledger["strategies"]["bb_revert"]
        row.update({
            "intent_count": 5,
            "completed_trades": 3,
            "net_expectancy_bps": -51.17,
            "profit_factor": 0.0,
            "payoff": None,
            "receipt_sha": "preserve-me",
            "last_evaluated_utc": "2026-08-17T11:45:35Z",
        })
        clock["strategies"]["bb_revert"].update({
            "last_probe_utc": "2026-08-17T11:45:35Z",
            "probe_count": 17,
            "timeframe_ms": 3_600_000,
        })
        return ledger, clock

    def test_prepare_releases_trading_heavy_before_next_closed_bar(self):
        ledger, clock = self._trading_heavy()
        boundary = clock["strategies"]["bb_revert"]["boundary_utc"]
        metrics = {
            "completed_trades": ledger["strategies"]["bb_revert"]["completed_trades"],
            "net_expectancy_bps": ledger["strategies"]["bb_revert"]["net_expectancy_bps"],
            "receipt_sha": ledger["strategies"]["bb_revert"]["receipt_sha"],
        }
        sid, changed = s.route_prepare(
            ledger,
            clock,
            now=datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc),
        )
        self.assertTrue(changed)
        self.assertEqual(sid, "fast_a")
        self.assertEqual(clock["strategies"]["bb_revert"]["state"], "WAITING_EVIDENCE")
        self.assertEqual(clock["strategies"]["bb_revert"]["next_probe_utc"], "2026-08-17T12:45:35Z")
        self.assertEqual(clock["strategies"]["bb_revert"]["boundary_utc"], boundary)
        self.assertEqual(ledger["strategies"]["bb_revert"]["completed_trades"], metrics["completed_trades"])
        self.assertEqual(ledger["strategies"]["bb_revert"]["net_expectancy_bps"], metrics["net_expectancy_bps"])
        self.assertEqual(ledger["strategies"]["bb_revert"]["receipt_sha"], metrics["receipt_sha"])
        v1.refresh_counts(clock)
        self.assertEqual(clock["heavy_active_count"], 1)

    def test_after_receipt_with_trades_routes_same_cycle_without_economic_scheduling(self):
        ledger, clock = self._trading_heavy()
        receipt = {
            "strategy_id": "bb_revert",
            "state": "A1_REBUILT_ECONOMICS_ACTIVE",
            "completed_trades": 3,
            "receipt_sha256": "new-receipt",
            "source": {"symbols": [{"bars_post_boundary": 17}, {"bars_post_boundary": 17}]},
        }
        sid, changed = s.route_after_receipt(
            ledger,
            clock,
            receipt,
            now=datetime(2026, 8, 17, 11, 45, 35, tzinfo=timezone.utc),
        )
        self.assertTrue(changed)
        self.assertEqual(sid, "fast_a")
        self.assertEqual(clock["strategies"]["bb_revert"]["state"], "WAITING_EVIDENCE")
        self.assertEqual(clock["strategies"]["bb_revert"]["next_probe_utc"], "2026-08-17T12:45:35Z")
        self.assertEqual(clock["strategies"]["bb_revert"]["last_receipt_sha"], "new-receipt")
        self.assertEqual(clock["strategies"]["bb_revert"]["probe_count"], 18)
        self.assertEqual(clock["strategies"]["fast_a"]["state"], "HEAVY_ACTIVE")
        self.assertEqual(ledger["strategies"]["bb_revert"]["net_expectancy_bps"], -51.17)
        self.assertEqual(ledger["strategies"]["fast_a"].get("profit_factor"), None)
        v1.refresh_counts(clock)
        self.assertEqual(clock["heavy_active_count"], 1)


if __name__ == "__main__":
    unittest.main()
