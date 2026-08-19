from __future__ import annotations

import copy
import unittest
from datetime import datetime, timezone

from backend.research.rebuild import a1_exact25_parallel_evidence_scheduler_v1 as s


def base_ledger() -> dict:
    order = ["bb_revert", "fast_a", "fast_b"] + [f"s{i}" for i in range(22)]
    strategies = {sid: {"status": "UNTESTED", "generation": 1} for sid in order}
    strategies["bb_revert"].update({
        "status": "ACTIVE",
        "prospective_boundary_utc": "2026-08-16T07:06:00Z",
        "intent_count": 0,
        "completed_trades": 0,
        "last_evaluated_utc": "2026-08-16T17:29:09Z",
    })
    return {
        "strategy_order": order,
        "strategies": strategies,
        "active_strategy_id": "bb_revert",
        "one_heavy_evaluator_at_a_time": True,
        "authority": {
            "selection_authority": False,
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "live_trade_authority": "BLOCKED",
            "protected_mutations": 0,
        },
    }


def clock_for(ledger: dict) -> dict:
    c = s._new_clock(ledger)
    for i, sid in enumerate(ledger["strategy_order"]):
        tf = 3_600_000 if sid == "bb_revert" else (60_000 if sid == "fast_a" else 300_000 + i)
        c["strategies"][sid] = {
            "state": "HEAVY_ACTIVE" if sid == "bb_revert" else "READY_FOR_HEAVY",
            "source_ready": True,
            "boundary_utc": ledger["strategies"][sid].get("prospective_boundary_utc") or "2026-08-16T18:00:00Z",
            "timeframe_ms": tf,
            "probe_count": 0,
        }
    return c


class ParallelSchedulerTests(unittest.TestCase):
    def test_sparse_bb_cannot_block_faster_strategy(self):
        ledger = base_ledger()
        clock = clock_for(ledger)
        sid, changed = s.route_prepare(ledger, clock, now=datetime(2026, 8, 16, 18, 40, tzinfo=timezone.utc))
        self.assertTrue(changed)
        self.assertEqual(sid, "fast_a")
        self.assertEqual(clock["strategies"]["bb_revert"]["state"], "WAITING_EVIDENCE")
        self.assertEqual(ledger["strategies"]["bb_revert"]["prospective_boundary_utc"], "2026-08-16T07:06:00Z")

    def test_newly_activated_heavy_consumes_one_real_evaluation_before_stale_ledger_can_route_it(self):
        ledger = base_ledger()
        clock = clock_for(ledger)
        ledger["strategies"]["bb_revert"]["status"] = "UNTESTED"
        ledger["active_strategy_id"] = None
        clock["strategies"]["bb_revert"].update({
            "state": "WAITING_EVIDENCE",
            "next_probe_utc": "2026-08-17T18:40:00Z",
        })
        ledger["strategies"]["fast_a"].update({
            "intent_count": 0,
            "completed_trades": 0,
            "last_evaluated_utc": "2026-08-16T17:00:00Z",
        })
        s._activate("fast_a", ledger, clock)
        self.assertTrue(clock["strategies"]["fast_a"]["awaiting_heavy_evaluation"])
        sid, changed = s.route_prepare(ledger, clock, now=datetime(2026, 8, 16, 18, 40, tzinfo=timezone.utc))
        self.assertFalse(changed)
        self.assertEqual(sid, "fast_a")
        self.assertEqual(ledger["active_strategy_id"], "fast_a")
        self.assertEqual(clock["strategies"]["fast_a"]["state"], "HEAVY_ACTIVE")

    def test_after_receipt_clears_awaiting_heavy_evaluation(self):
        ledger = base_ledger()
        clock = clock_for(ledger)
        ledger["strategies"]["bb_revert"]["status"] = "UNTESTED"
        ledger["active_strategy_id"] = None
        s._activate("fast_a", ledger, clock)
        receipt = {
            "strategy_id": "fast_a",
            "state": "WAIT_FRESH_PROSPECTIVE_DATA",
            "completed_trades": 0,
            "receipt_sha256": "fresh",
            "source": {"symbols": [{"bars_post_boundary": 12}, {"bars_post_boundary": 12}]},
        }
        s.route_after_receipt(ledger, clock, receipt, now=datetime(2026, 8, 16, 18, 40, tzinfo=timezone.utc))
        self.assertFalse(clock["strategies"]["fast_a"]["awaiting_heavy_evaluation"])
        self.assertEqual(clock["strategies"]["fast_a"]["last_observed_bars_per_symbol"], [12, 12])

    def test_one_heavy_invariant(self):
        ledger = base_ledger()
        clock = clock_for(ledger)
        s.route_prepare(ledger, clock, now=datetime(2026, 8, 16, 18, 40, tzinfo=timezone.utc))
        s.refresh_counts(clock)
        self.assertEqual(clock["heavy_active_count"], 1)

    def test_all_25_have_clock_or_blocker(self):
        ledger = base_ledger()
        clock = clock_for(ledger)
        clock["strategies"]["s0"].update({"source_ready": False, "source_blocker": "TEST", "boundary_utc": None})
        s.refresh_counts(clock)
        self.assertEqual(clock["clocks_started_count"] + clock["source_blocked_count"], 25)

    def test_route_away_back_preserves_boundary(self):
        ledger = base_ledger()
        clock = clock_for(ledger)
        original = clock["strategies"]["bb_revert"]["boundary_utc"]
        s.route_prepare(ledger, clock, now=datetime(2026, 8, 16, 18, 40, tzinfo=timezone.utc))
        clock["strategies"]["fast_a"]["state"] = "WAITING_EVIDENCE"
        clock["strategies"]["fast_a"]["next_probe_utc"] = "2026-08-17T18:40:00Z"
        for sid in ledger["strategy_order"]:
            if sid not in {"bb_revert", "fast_a"}:
                clock["strategies"][sid]["state"] = "TERMINAL"
        clock["strategies"]["bb_revert"]["next_probe_utc"] = "2026-08-16T18:41:00Z"
        ledger["strategies"]["fast_a"]["status"] = "UNTESTED"
        ledger["active_strategy_id"] = None
        sid, _ = s.route_prepare(ledger, clock, now=datetime(2026, 8, 16, 18, 42, tzinfo=timezone.utc))
        self.assertEqual(sid, "bb_revert")
        self.assertEqual(clock["strategies"]["bb_revert"]["boundary_utc"], original)

    def test_ordering_ignores_economic_fields(self):
        ledger = base_ledger()
        clock = clock_for(ledger)
        for sid in ledger["strategy_order"]:
            clock["strategies"][sid].update({"pnl": 10**9, "win_rate": 1.0, "profit_factor": 999.0, "payoff": 999.0})
        ranked = s._rank(ledger["strategy_order"], clock, now=datetime(2026, 8, 16, 18, 40, tzinfo=timezone.utc), exclude={"bb_revert"})
        self.assertEqual(ranked[0], "fast_a")
        self.assertFalse(s._new_clock(ledger)["scheduling_policy"]["old_or_pre_rebuild_pnl_used"])

    def test_after_wait_routes_same_cycle(self):
        ledger = base_ledger()
        clock = clock_for(ledger)
        receipt = {"strategy_id": "bb_revert", "state": "WAIT_FRESH_PROSPECTIVE_DATA", "completed_trades": 0, "receipt_sha256": "abc", "source": {"symbols": []}}
        sid, changed = s.route_after_receipt(ledger, clock, receipt, now=datetime(2026, 8, 16, 18, 40, tzinfo=timezone.utc))
        self.assertTrue(changed)
        self.assertEqual(sid, "fast_a")
        self.assertEqual(clock["strategies"]["fast_a"]["state"], "HEAVY_ACTIVE")
        self.assertTrue(clock["strategies"]["fast_a"]["awaiting_heavy_evaluation"])

    def test_terminal_state_is_not_reactivated(self):
        ledger = base_ledger()
        clock = clock_for(ledger)
        ledger["strategies"]["fast_a"]["status"] = "A1_ECONOMIC_FAIL"
        clock["strategies"]["fast_a"]["state"] = "TERMINAL"
        ranked = s._rank(ledger["strategy_order"], clock, now=datetime(2026, 8, 16, 18, 40, tzinfo=timezone.utc), exclude={"bb_revert"})
        self.assertNotIn("fast_a", ranked)


if __name__ == "__main__":
    unittest.main()
