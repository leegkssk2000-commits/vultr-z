from __future__ import annotations

import copy
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from backend.research.rebuild import a1_exact25_controller_v2 as c
from backend.research.rebuild import a1_exact25_generic_evaluator_v2 as ge2
from backend.research.rebuild import a1_exact25_hardening_evidence_adapter_v1 as ha

ROOT = Path(__file__).resolve().parents[3]


def receipt(*, bars: int, intents: int, trades: int) -> dict:
    return {
        "strategy_id": "bb_revert",
        "boundary_utc": "2026-08-01T00:00:00Z",
        "policy_sha": "policy-1",
        "config_sha": "config-1",
        "cost_authority_sha256": "cost-1",
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

    def test_max_budget_negative_economics_routes_instead_of_lingering(self):
        r = receipt(bars=168, intents=6, trades=4)
        r["metrics"] = {
            "net_pnl_bps": -210.0,
            "net_expectancy_bps": -52.5,
            "net_profit_factor": 0.0,
            "net_payoff": None,
        }
        d, reason = c.resource_disposition(r, now=datetime(2026, 8, 8, tzinfo=timezone.utc))
        self.assertEqual(d, "A1_ECONOMIC_FAIL")
        self.assertIn("MAX_RESOURCE_BUDGET_ECONOMIC_GATE_FAIL", reason)
        self.assertIn("net_expectancy_bps", reason)

    def test_max_budget_defined_positive_economics_not_auto_failed(self):
        r = receipt(bars=168, intents=20, trades=10)
        r["metrics"] = {
            "net_pnl_bps": 80.0,
            "net_expectancy_bps": 8.0,
            "net_profit_factor": 1.4,
            "net_payoff": 1.2,
        }
        d, _ = c.resource_disposition(r, now=datetime(2026, 8, 8, tzinfo=timezone.utc))
        self.assertIsNone(d)

    def test_explicit_source_quality_failure_routes_data_blocked(self):
        r = receipt(bars=168, intents=10, trades=4)
        r["source_quality_gate"] = {"state": "FAIL", "defects": ["SOURCE_RECENCY_STALE:BTC-USDT"]}
        d, reason = c.resource_disposition(r, now=datetime(2026, 8, 8, tzinfo=timezone.utc))
        self.assertEqual(d, "A1_DATA_BLOCKED")
        self.assertIn("SOURCE_QUALITY_GATE_FAIL", reason)

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


class Exact25SourceQualityTests(unittest.TestCase):
    def _source_receipt(self, *, observed: int, last_ts_ms: int | None) -> dict:
        return {
            "strategy_id": "ema_ribbon_scalp",
            "boundary_utc": "2026-08-16T18:00:00Z",
            "source": {
                "interval": "5m",
                "symbols": [
                    {
                        "symbol": "BTC-USDT",
                        "bars_post_boundary": observed,
                        "first_post_boundary_ts": 1786903200000,
                        "last_post_boundary_ts": last_ts_ms,
                    },
                    {
                        "symbol": "ETH-USDT",
                        "bars_post_boundary": observed,
                        "first_post_boundary_ts": 1786903200000,
                        "last_post_boundary_ts": last_ts_ms,
                    },
                ],
            },
        }

    def test_37_of_about_576_five_minute_bars_fails(self):
        now = datetime(2026, 8, 18, 18, 0, tzinfo=timezone.utc)
        stale_last = int(datetime(2026, 8, 16, 21, 0, tzinfo=timezone.utc).timestamp() * 1000)
        gate = ge2.source_quality_gate(self._source_receipt(observed=37, last_ts_ms=stale_last), now=now)
        self.assertEqual(gate["state"], "FAIL")
        self.assertTrue(any("SOURCE_CADENCE_MISSING" in x for x in gate["defects"]))
        self.assertTrue(any("SOURCE_RECENCY_STALE" in x for x in gate["defects"]))

    def test_full_recent_window_passes(self):
        now = datetime(2026, 8, 18, 18, 0, tzinfo=timezone.utc)
        recent_last = int(datetime(2026, 8, 18, 17, 55, tzinfo=timezone.utc).timestamp() * 1000)
        gate = ge2.source_quality_gate(self._source_receipt(observed=576, last_ts_ms=recent_last), now=now)
        self.assertEqual(gate["state"], "PASS")
        self.assertEqual(gate["defects"], [])


class Exact25HardeningEvidenceIdentityTests(unittest.TestCase):
    def setUp(self):
        self.r = receipt(bars=168, intents=20, trades=20)

    def test_exact_strategy_policy_identity_matches(self):
        evidence = {
            "strategy_id": "bb_revert",
            "policy_sha": "policy-1",
            "config_sha": "config-1",
            "boundary_utc": "2026-08-01T00:00:00Z",
            "cost_authority_sha256": "cost-1",
            "retention_pct": 70.0,
            "oos": {"net_pnl_bps": 10.0, "net_expectancy_bps": 1.0},
        }
        self.assertTrue(ha.evidence_matches_receipt(evidence, self.r))

    def test_wrong_policy_is_rejected(self):
        evidence = {"strategy_id": "bb_revert", "policy_sha": "wrong", "retention_pct": 70.0}
        self.assertFalse(ha.evidence_matches_receipt(evidence, self.r))

    def test_generic_unbound_evidence_is_rejected(self):
        evidence = {"retention_pct": 70.0, "oos": {"net_pnl_bps": 10.0}}
        self.assertFalse(ha.evidence_matches_receipt(evidence, self.r))


if __name__ == "__main__":
    unittest.main()
