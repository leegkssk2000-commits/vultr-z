from __future__ import annotations

import copy
import unittest

from backend.research.rebuild.a1_exact25_survivor_gate_v1 import build_survivor_gate
from backend.research.rebuild.a1_exact25_controller_v2 import terminal_disposition


POLICY = {
    "schema_version": "zel.economic_hardening.policy.v2",
    "survivor_gate": {
        "minimum_expectancy_R": 0.0,
        "minimum_net_R": 0.0,
        "minimum_payoff_ratio": 1.0,
        "minimum_profit_factor": 1.0,
        "minimum_retention_pct": 60.0,
    },
    "h4_placebo_negative_controls": {
        "maximum_p_value": 0.05,
        "minimum_candidate_minus_control_ci_low_R": 0.0,
        "require_equal_trade_budget": True,
        "require_identical_cost_model_sha": True,
        "require_identical_window_sha": True,
        "required_controls": ["same_count_random_entry", "one_bar_delay", "direction_inversion", "timestamp_shuffle", "indicator_removal"],
        "required_source_receipt_state": "PASS_DETERMINISTIC_REPLAY_RESULT",
    },
}


def valid_receipt():
    trades = []
    for i in range(25):
        trades.append({"symbol": "BTC-USDT" if i % 2 == 0 else "ETH-USDT", "net_bps": 5.0})
    return {
        "schema_version": "zel.a1_exact25_generic_economics.v1",
        "completed_trades": 25,
        "trades": trades,
        "metrics": {
            "net_pnl_bps": 125.0,
            "net_expectancy_bps": 5.0,
            "net_profit_factor": 1.4,
            "net_payoff": 1.2,
            "gross_expectancy_bps": 19.0,
        },
        "execution_snapshots": {
            "BTC-USDT": {"pretrade_verified_cost_bps": 14.0},
            "ETH-USDT": {"pretrade_verified_cost_bps": 14.0},
        },
        "integrity_defects": [],
        "leakage_lookahead": 0,
        "intent_count": 25,
        "source": {
            "symbols": [
                {"symbol": "BTC-USDT", "bars_post_boundary": 100},
                {"symbol": "ETH-USDT", "bars_post_boundary": 100},
            ],
            "interval": "5m",
        },
    }


def valid_hardening():
    controls = {
        name: {"state": "PASS"}
        for name in POLICY["h4_placebo_negative_controls"]["required_controls"]
    }
    return {
        "retention_pct": 75.0,
        "oos": {"net_pnl_bps": 30.0, "net_expectancy_bps": 2.0},
        "negative_control": {
            "state": "PASS_DETERMINISTIC_REPLAY_RESULT",
            "p_value": 0.01,
            "candidate_minus_control_ci_low_R": 0.2,
            "equal_trade_budget": True,
            "identical_cost_model_sha": True,
            "identical_window_sha": True,
            "controls": controls,
        },
    }


class SurvivorGateTests(unittest.TestCase):
    def assert_no_pass(self, receipt, evidence):
        gate = build_survivor_gate(receipt, evidence, POLICY)
        self.assertFalse(gate["passed"])
        self.assertNotEqual(gate["state"], "PASS")
        return gate

    def test_missing_hardening_evidence_is_pending_never_pass(self):
        gate = build_survivor_gate(valid_receipt(), None, POLICY)
        self.assertEqual(gate["state"], "PENDING")
        self.assertFalse(gate["passed"])
        self.assertIn("retention_positive", gate["pending_checks"])
        self.assertIn("oos_positive", gate["pending_checks"])
        self.assertIn("negative_control_superiority", gate["pending_checks"])

    def test_no_survivor_below_25_trades(self):
        receipt = valid_receipt()
        receipt["completed_trades"] = 24
        receipt["trades"] = receipt["trades"][:24]
        gate = self.assert_no_pass(receipt, valid_hardening())
        self.assertIn("tier_a_completed_trades", gate["failed_checks"])

    def test_no_survivor_on_one_symbol(self):
        receipt = valid_receipt()
        receipt["trades"] = [dict(x, symbol="BTC-USDT") for x in receipt["trades"]]
        gate = self.assert_no_pass(receipt, valid_hardening())
        self.assertIn("tier_a_completed_symbols", gate["failed_checks"])

    def test_no_survivor_on_nonpositive_net_or_pf_or_payoff(self):
        cases = [
            ("net_pnl_bps", 0.0, "net_pnl_positive"),
            ("net_expectancy_bps", 0.0, "net_expectancy_positive"),
            ("net_profit_factor", 0.99, "profit_factor"),
            ("net_payoff", 0.99, "payoff"),
        ]
        for metric, value, check in cases:
            with self.subTest(metric=metric):
                receipt = valid_receipt()
                receipt["metrics"][metric] = value
                gate = self.assert_no_pass(receipt, valid_hardening())
                self.assertIn(check, gate["failed_checks"])

    def test_no_survivor_with_pending_or_failed_negative_control(self):
        pending = valid_hardening()
        pending["negative_control"].pop("p_value")
        gate = self.assert_no_pass(valid_receipt(), pending)
        self.assertIn("negative_control_superiority", gate["pending_checks"])

        failed = valid_hardening()
        failed["negative_control"]["p_value"] = 0.20
        gate = self.assert_no_pass(valid_receipt(), failed)
        self.assertIn("negative_control_superiority", gate["failed_checks"])

    def test_no_survivor_with_retention_or_oos_fail(self):
        retention = valid_hardening()
        retention["retention_pct"] = 59.9
        gate = self.assert_no_pass(valid_receipt(), retention)
        self.assertIn("retention_positive", gate["failed_checks"])

        oos = valid_hardening()
        oos["oos"]["net_expectancy_bps"] = 0.0
        gate = self.assert_no_pass(valid_receipt(), oos)
        self.assertIn("oos_positive", gate["failed_checks"])

    def test_valid_synthetic_fixture_reaches_gate_and_controller_survivor(self):
        receipt = valid_receipt()
        gate = build_survivor_gate(receipt, valid_hardening(), POLICY)
        self.assertEqual(gate["state"], "PASS")
        self.assertTrue(gate["passed"])
        receipt["survivor_gate"] = gate
        receipt["negative_control_gate"] = "PASS_H4_NEGATIVE_CONTROL_SUPERIORITY"
        disposition, reason = terminal_disposition(receipt, POLICY)
        self.assertEqual(disposition, "A1_SURVIVOR")
        self.assertEqual(reason, "PROSPECTIVE_COST_ADJUSTED_SSOT_SURVIVOR_GATE_PASS")

    def test_gate_does_not_mutate_frozen_policy_or_receipt(self):
        receipt = valid_receipt()
        policy_before = copy.deepcopy(POLICY)
        receipt_before = copy.deepcopy(receipt)
        build_survivor_gate(receipt, valid_hardening(), POLICY)
        self.assertEqual(POLICY, policy_before)
        self.assertEqual(receipt, receipt_before)


if __name__ == "__main__":
    unittest.main()
