from __future__ import annotations

import copy
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from backend.research.rebuild import a1_exact25_controller_v2 as c

ROOT = Path(__file__).resolve().parents[3]


def receipt(*, bars: int, intents: int, trades: int) -> dict:
    return {
        "strategy_id": "bb_revert",
        "boundary_utc": "2026-08-01T00:00:00Z",
        "source": {
            "interval": "1h",
            "symbols": [
                {"symbol": "BTC-USDT", "bars_post_boundary": bars},
                {"symbol": "ETH-USDT", "bars_post_boundary": bars},
            ],
        },
        "intent_count": intents,
        "completed_trades": trades,
        "integrity_defects": [],
        "leakage_lookahead": 0,
        "metrics": {},
        "negative_control_gate": "PENDING",
    }


class Exact25ResourceBudgetTests(unittest.TestCase):
    def test_zero_intent_eventually_routes(self):
        r = receipt(bars=72, intents=0, trades=0)
        d, reason = c.resource_disposition(r, now=datetime(2026, 8, 4, tzinfo=timezone.utc))
        self.assertEqual(d, "A1_SPARSE_EVENT_FUTILITY")
        self.assertIn("ZERO_INTENT", reason)

    def test_nonzero_incomplete_trades_do_not_disappear_early(self):
        r = receipt(bars=100, intents=2, trades=0)
        d, _ = c.resource_disposition(r, now=datetime(2026, 8, 5, tzinfo=timezone.utc))
        self.assertIsNone(d)
        self.assertEqual(r["intent_count"], 2)
        self.assertEqual(r["completed_trades"], 0)

    def test_no_auto_survivor(self):
        r = receipt(bars=200, intents=20, trades=20)
        r["metrics"] = {
            "net_pnl_bps": 100.0,
            "net_expectancy_bps": 5.0,
            "net_profit_factor": 2.0,
            "net_payoff": 1.5,
            "gross_expectancy_bps": 20.0,
        }
        d, _ = c.terminal_disposition(r, {"survivor_gate": {}})
        self.assertNotEqual(d, "A1_SURVIVOR")

    def test_one_heavy_and_exact25_cannot_be_skipped(self):
        ledger = json.loads((ROOT / "backend/research/rebuild/a1_exact25_disposition_ledger_v1.json").read_text())
        c.validate_ledger_contract(ledger)
        broken = copy.deepcopy(ledger)
        broken["strategy_order"] = broken["strategy_order"][:-1]
        with self.assertRaises(RuntimeError):
            c.validate_ledger_contract(broken)
        broken2 = copy.deepcopy(ledger)
        other = next(x for x in broken2["strategy_order"] if x != broken2["active_strategy_id"])
        broken2["strategies"][other]["status"] = "ACTIVE"
        with self.assertRaises(RuntimeError):
            c.validate_ledger_contract(broken2)

    def test_terminal_report_once_and_next_launch_same_cycle_contract_present(self):
        source = (ROOT / "backend/research/rebuild/a1_exact25_controller_v1.py").read_text()
        self.assertIn('entry["reported_terminal_receipt_sha"] = receipt.get("receipt_sha256")', source)
        self.assertIn('if ledger["strategies"][candidate].get("status") == "UNTESTED"', source)
        self.assertIn('nxt.update({', source)
        self.assertIn('ledger["active_strategy_id"] = next_sid', source)


if __name__ == "__main__":
    unittest.main()
