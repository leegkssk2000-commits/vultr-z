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
    trades = [{"symbol": "BTC-USDT" if i % 2 == 0 else "ETH-USDT", "net_bps": 5.0} for i in range(25)]
    return {
        "schema_version": "zel.a1_exact25_generic_economics.v1",
        "completed_trades": 25,
        "trades": trades,
        "metrics": {
            "net_pnl_bps": 125.0, "net_expectancy_bps": 5.0,
            "net_profit_factor": 1.4, "net_payoff": 1.2, "gross_expectancy_bps": 19.0,
        },
        "execution_snapshots": {
            "BTC-USDT": {"pretrade_verified_cost_bps": 14.0},
            "ETH-USDT": {"pretrade_verified_cost_bps": 14.0},
        },
        "integrity_defects": [], "leakage_lookahead": 0, "intent_count": 25,
        "source": {"symbols": [
            {"symbol": "BTC-USDT", "bars_post_boundary": 100},
            {"symbol": "ETH-USDT", "bars_post_boundary": 100},
        ], "interval": "5m"},
    }


def valid_hardening():
    controls = {name: {"state": "PASS"} for name in POLICY["h4_placebo_negative_controls"]["required_controls"]}
    return {
        "retention_pct": 75.0,
        "oos": {"net_pnl_bps": 30.0, "net_expectancy_bps": 2.0},
        "negative_control": {
            "state": "PASS_DETERMINISTIC_REPLAY_RESULT", "p_value": 0.01,
            "candidate_minus_control_ci_low_R": 0.2, "equal_trade_budget": True,
            "identical_cost_model_sha": True, "identical_window_sha": True, "controls": controls,
        },
    }


class SurvivorGateTests(unittest.TestCase):
    def no_pass(self, receipt, evidence):
        gate = build_survivor_gate(receipt, evidence, POLICY)
        self.assertFalse(gate["passed"])
        self.assertNotEqual(gate["state"], "PASS")
        return gate

    def test_missing_hardening_is_pending(self):
        gate = self.no_pass(valid_receipt(), None)
        self.assertEqual(gate["state"], "PENDING")
        for name in ("retention_positive", "oos_positive", "negative_control_superiority"):
            self.assertIn(name, gate["pending_checks"])

    def test_below_25_trades_never_passes(self):
        r = valid_receipt(); r["completed_trades"] = 24; r["trades"] = r["trades"][:24]
        self.assertIn("tier_a_completed_trades", self.no_pass(r, valid_hardening())["failed_checks"])

    def test_one_symbol_never_passes(self):
        r = valid_receipt(); r["trades"] = [dict(x, symbol="BTC-USDT") for x in r["trades"]]
        self.assertIn("tier_a_completed_symbols", self.no_pass(r, valid_hardening())["failed_checks"])

    def test_bad_economics_never_passes(self):
        cases = [
            ("net_pnl_bps", 0.0, "net_pnl_positive"),
            ("net_expectancy_bps", 0.0, "net_expectancy_positive"),
            ("net_profit_factor", 0.99, "profit_factor"),
            ("net_payoff", 0.99, "payoff"),
        ]
        for metric, value, check in cases:
            with self.subTest(metric=metric):
                r = valid_receipt(); r["metrics"][metric] = value
                self.assertIn(check, self.no_pass(r, valid_hardening())["failed_checks"])

    def test_pending_or_failed_negative_control_never_passes(self):
        ev = valid_hardening(); ev["negative_control"].pop("p_value")
        self.assertIn("negative_control_superiority", self.no_pass(valid_receipt(), ev)["pending_checks"])
        ev = valid_hardening(); ev["negative_control"]["p_value"] = 0.20
        self.assertIn("negative_control_superiority", self.no_pass(valid_receipt(), ev)["failed_checks"])

    def test_retention_or_oos_fail_never_passes(self):
        ev = valid_hardening(); ev["retention_pct"] = 59.9
        self.assertIn("retention_positive", self.no_pass(valid_receipt(), ev)["failed_checks"])
        ev = valid_hardening(); ev["oos"]["net_expectancy_bps"] = 0.0
        self.assertIn("oos_positive", self.no_pass(valid_receipt(), ev)["failed_checks"])

    def test_valid_fixture_reaches_controller_survivor(self):
        r = valid_receipt(); gate = build_survivor_gate(r, valid_hardening(), POLICY)
        self.assertTrue(gate["passed"]); self.assertEqual(gate["state"], "PASS")
        r["survivor_gate"] = gate; r["negative_control_gate"] = "PASS_H4_NEGATIVE_CONTROL_SUPERIORITY"
        disposition, reason = terminal_disposition(r, POLICY)
        self.assertEqual(disposition, "A1_SURVIVOR")
        self.assertEqual(reason, "PROSPECTIVE_COST_ADJUSTED_SSOT_SURVIVOR_GATE_PASS")

    def test_gate_does_not_mutate_inputs(self):
        r = valid_receipt(); r0 = copy.deepcopy(r); p0 = copy.deepcopy(POLICY)
        build_survivor_gate(r, valid_hardening(), POLICY)
        self.assertEqual(r, r0); self.assertEqual(POLICY, p0)


if __name__ == "__main__":
    unittest.main()
