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
        "metrics": {"net_pnl_bps": 125.0, "net_expectancy_bps": 5.0, "net_profit_factor": 1.4, "net_payoff": 1.2, "gross_expectancy_bps": 19.0},
        "execution_snapshots": {"BTC-USDT": {"pretrade_verified_cost_bps": 14.0}, "ETH-USDT": {"pretrade_verified_cost_bps": 14.0}},
        "integrity_defects": [],
        "leakage_lookahead": 0,
        "intent_count": 25,
        "source": {"symbols": [{"symbol": "BTC-USDT", "bars_post_boundary": 100}, {"symbol": "ETH-USDT", "bars_post_boundary": 100}], "interval": "5m"},
    }


def valid_hardening():
    controls = {name: {"state": "PASS"} for name in POLICY["h4_placebo_negative_controls"]["required_controls"]}
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
    def test_missing_hardening_evidence_is_pending_never_pass(self):
        gate = build_survivor_gate(valid_receipt(), None, POLICY)
        self.assertEqual(gate["state"], "PENDING")
        self.assertFalse(gate["passed"])
        self.assertIn("retention_positive", gate["pending_checks"])
        self.assertIn("oos_positive", gate["pending_checks"])
        self.assertIn("negative_control_superiority", gate["pending_checks"])

    def test_bad_negative_control_fails_closed(self):
        ev = valid_hardening()
        ev["negative_control"]["p_value"] = 0.20
        gate = build_survivor_gate(valid_receipt(), ev, POLICY)
        self.assertEqual(gate["state"], "FAIL")
        self.assertFalse(gate["passed"])
        self.assertIn("negative_control_superiority", gate["failed_checks"])

    def test_valid_synthetic_fixture_is_only_pass_case_and_controller_accepts(self):
        receipt = valid_receipt()
        gate = build_survivor_gate(receipt, valid_hardening(), POLICY)
        self.assertEqual(gate["state"], "PASS")
        self.assertTrue(gate["passed"])
        receipt["survivor_gate"] = gate
        receipt["negative_control_gate"] = "PASS_H4_NEGATIVE_CONTROL_SUPERIORITY"
        disposition, reason = terminal_disposition(receipt, POLICY)
        self.assertEqual(disposition, "A1_SURVIVOR")
        self.assertEqual(reason, "PROSPECTIVE_COST_ADJUSTED_SSOT_SURVIVOR_GATE_PASS")

    def test_under_25_or_one_symbol_never_passes(self):
        receipt = valid_receipt()
        receipt["completed_trades"] = 24
        receipt["trades"] = [{"symbol": "BTC-USDT", "net_bps": 5.0} for _ in range(24)]
        gate = build_survivor_gate(receipt, valid_hardening(), POLICY)
        self.assertEqual(gate["state"], "FAIL")
        self.assertFalse(gate["passed"])
        self.assertIn("tier_a_completed_trades", gate["failed_checks"])
        self.assertIn("tier_a_completed_symbols", gate["failed_checks"])


if __name__ == "__main__":
    unittest.main()
