from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.research.prep import g5_production_economic_ssot_v1 as econ
from backend.research.prep.g5_trendrider_broad30_product_oos_v1 import stable


class G5ProductionEconomicSsotTest(unittest.TestCase):
    def replay_row(self) -> dict:
        return {
            "symbol": "BTC-USDT",
            "signal_ts": 10,
            "entry_ts": 20,
            "exit_ts": 30,
            "side": "long",
            "entry": 100.0,
            "exit": 101.0,
            "gross_bps": 100.0,
            "realized_cost_bps": 10.0,
            "net_bps": 90.0,
            "intent_sha": "intent-a",
            "cost_snapshot_sha": "current-snapshot",
        }

    def base_result(self, t: int) -> dict:
        value = {
            "schema_version": "zel.g5.trendrider_broad30.product_oos.v1",
            "stage": "G5",
            "state": "WAIT_G5_W2_12",
            "strategy_id": "trend_rider",
            "lane_id": "trend_rider_broad_wr7000",
            "postlock_closed_T": t,
            "policy_retune": False,
            "threshold_retune": False,
            "old_history_union": False,
            "selection_authority": False,
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "live_trade_authority": "BLOCKED",
            "protected_mutations": 0,
            "action": "hold",
        }
        value["receipt_sha256"] = stable(value)
        return value

    def test_current_snapshot_historical_replay_is_proxy(self) -> None:
        row = econ.classify_trade(self.replay_row(), source_receipt_sha256="raw")
        self.assertFalse(row["production_grade"])
        self.assertIn("CURRENT_DEPTH_OR_COST_SNAPSHOT_APPLIED_TO_HISTORICAL_REPLAY", row["production_fail_closed_reasons"])
        self.assertIn("SIGNED_FUNDING_SETTLEMENT_LINEAGE_MISSING", row["production_fail_closed_reasons"])
        self.assertIn("INTRABAR_EXECUTION_ORDER_NOT_OBSERVED", row["production_fail_closed_reasons"])

    def test_forward_real_requires_all_three_provenance_domains(self) -> None:
        row = self.replay_row()
        row.update({
            "economic_origin": "FORWARD_REAL",
            "cost_provenance": {"point_in_time_at_trade": True},
            "fee_provenance": {"point_in_time_at_trade": True},
            "funding_provenance": {"signed_settlement_lineage": True},
            "execution_provenance": {"intrabar_order_observed": True},
        })
        classified = econ.classify_trade(row, source_receipt_sha256="raw-real")
        self.assertTrue(classified["production_grade"])
        self.assertEqual(classified["production_fail_closed_reasons"], [])

    def test_8_runtime_vs_6_durable_fails_closed(self) -> None:
        obs = econ.durable_observation({"postlock_closed_T": 6, "receipt_sha256": "old"}, [str(i) for i in range(8)])
        self.assertEqual(obs["runtime_trade_count"], 8)
        self.assertEqual(obs["durable_trade_count"], 6)
        self.assertFalse(obs["durable_matches_runtime"])

    def test_count_only_match_is_not_enough(self) -> None:
        obs = econ.durable_observation({"postlock_closed_T": 8, "receipt_sha256": "old"}, [str(i) for i in range(8)])
        self.assertFalse(obs["durable_matches_runtime"])
        self.assertTrue(obs["count_only_match_is_insufficient"])

    def test_append_only_ledger_is_idempotent(self) -> None:
        proxy = econ.classify_trade(self.replay_row(), source_receipt_sha256="raw")
        with tempfile.TemporaryDirectory(prefix="g5-ledger-test-") as td:
            root = Path(td)
            missing = root / "missing.jsonl"
            first = root / "first.jsonl"
            second = root / "second.jsonl"
            info1 = econ.merge_ledger(missing, [proxy], first)
            info2 = econ.merge_ledger(first, [proxy], second)
            self.assertEqual(info1["appended_rows"], 1)
            self.assertEqual(info2["appended_rows"], 0)
            self.assertEqual(first.read_text(), second.read_text())

    def test_ai_gate_denies_proxy_only_runtime(self) -> None:
        proxy = econ.classify_trade(self.replay_row(), source_receipt_sha256="raw")
        durable = {
            "postlock_closed_T": 1,
            "receipt_sha256": "old",
            "economic_ssot": {"runtime_trade_set_sha256": econ.stable([proxy["trade_id"]])},
        }
        result = econ.harden(
            self.base_result(1),
            [proxy],
            durable,
            {"existing_rows": 0, "appended_rows": 1, "total_rows": 1, "ledger_sha256": "ledger"},
        )
        self.assertEqual(result["state"], "WAIT_G5_FORWARD_REAL_ECONOMICS")
        self.assertFalse(result["ai_gate"]["production_grade_claim_eligible"])
        self.assertTrue(result["ai_gate"]["g6_promotion_forbidden"])


if __name__ == "__main__":
    unittest.main()
