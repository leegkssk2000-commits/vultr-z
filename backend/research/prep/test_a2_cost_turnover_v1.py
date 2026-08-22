from __future__ import annotations

import json
import unittest
from pathlib import Path

from backend.research.prep.a2_cost_turnover_calculator_v1 import (
    CostInput,
    compute_cost,
    expected_move_cost_ratio,
    p95,
    turnover_summary,
)

ROOT = Path(__file__).resolve().parents[3]


class A2CostTurnoverPrepTests(unittest.TestCase):
    def fixture(self) -> CostInput:
        return CostInput(
            best_bid=99.95,
            best_ask=100.05,
            bids=[[99.95, 60.0], [99.90, 60.0], [99.80, 60.0]],
            asks=[[100.05, 60.0], [100.10, 60.0], [100.20, 60.0]],
            funding_abs_bps_history=[float(i % 7) / 10.0 for i in range(100)],
            reference_notional_usdt=10000.0,
        )

    def test_contract_is_research_only_receipt_gated_and_authority_blocked(self):
        s = json.loads((ROOT / "backend/research/prep/a2_cost_turnover_ssot_v1.json").read_text())
        self.assertEqual(s["state"], "A2_PREP_READY")
        self.assertTrue(s["research_only"])
        self.assertTrue(s["gates"]["actual_survivor_evaluation_allowed"])
        self.assertTrue(s["gates"]["actual_evaluation_requires_a1_receipt"])
        self.assertFalse(s["gates"]["old_or_pre_rebuild_pnl_used"])
        self.assertFalse(s["gates"]["selection_allowed"])
        self.assertFalse(s["gates"]["promotion_allowed"])
        self.assertTrue(s["fee"]["maker_reference_only"])
        self.assertFalse(s["fee"]["maker_fill_model_verified"])
        self.assertFalse(s["fee"]["maker_may_reduce_cost"])
        activation = s["activation"]
        self.assertGreaterEqual(int(activation["minimum_completed_trades_for_actual_a2_pass"]), 25)
        self.assertGreaterEqual(int(activation["minimum_h4_control_trades_for_actual_a2_pass"]), 25)
        self.assertEqual(s["turnover"]["pass_role"], "DIAGNOSTIC_ONLY")
        self.assertTrue(s["turnover"]["positive_turnover_is_not_economic_edge"])
        a = s["authority"]
        self.assertFalse(a["selection_authority"])
        self.assertFalse(a["promotion_authority"])
        self.assertEqual(a["execution_authority"], "NONE")
        self.assertEqual(a["order_authority"], "BLOCKED")
        self.assertEqual(a["live_trade_authority"], "BLOCKED")
        self.assertEqual(a["protected_mutations"], 0)

    def test_deterministic_cost_recompute(self):
        a = compute_cost(self.fixture())
        b = compute_cost(self.fixture())
        self.assertEqual(a, b)
        self.assertEqual(a["fee_bps"], 10.0)
        self.assertGreaterEqual(a["spread_charged_bps"], 1.0)
        self.assertGreaterEqual(a["depth_impact_charged_bps"], 2.0)
        self.assertEqual(a["two_x_cost_bps"], 2.0 * a["one_x_cost_bps"])
        self.assertFalse(a["maker_cost_used"])

    def test_independent_formula_recompute_matches(self):
        result = compute_cost(self.fixture())
        expected = (
            result["fee_bps"]
            + result["spread_charged_bps"]
            + result["depth_impact_charged_bps"]
            + result["funding_p95_abs_bps"]
            + result["verified_penalty_bps"]
        )
        self.assertAlmostEqual(result["one_x_cost_bps"], expected, places=12)

    def test_p95_contract(self):
        self.assertEqual(p95([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]), 10.0)
        with self.assertRaises(ValueError):
            p95([])

    def test_depth_unfilled_fails_closed(self):
        x = self.fixture()
        broken = CostInput(
            best_bid=x.best_bid,
            best_ask=x.best_ask,
            bids=[[99.95, 0.001]],
            asks=[[100.05, 0.001]],
            funding_abs_bps_history=x.funding_abs_bps_history,
            reference_notional_usdt=10000.0,
        )
        with self.assertRaisesRegex(ValueError, "DEPTH_REFERENCE_NOTIONAL_UNFILLED"):
            compute_cost(broken
            )

    def test_expected_move_cost_ratio_has_no_selection_authority(self):
        result = compute_cost(self.fixture())
        ratio = expected_move_cost_ratio(50.0, result["one_x_cost_bps"])
        self.assertGreater(ratio, 0.0)

    def test_turnover_summary(self):
        x = turnover_summary([12.0, 14.0, 13.0], [1000.0, 1200.0, 900.0], 1.5)
        self.assertEqual(x["round_trips"], 3.0)
        self.assertEqual(x["round_trips_per_day"], 2.0)
        self.assertEqual(x["gross_turnover_notional_usdt"], 3100.0)
        self.assertEqual(x["cost_bps_total"], 39.0)
        self.assertEqual(x["cost_bps_per_trade"], 13.0)


if __name__ == "__main__":
    unittest.main()
