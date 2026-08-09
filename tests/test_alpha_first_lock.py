import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ci" / "alpha_first_lock.py"
SPEC = importlib.util.spec_from_file_location("alpha_first_lock", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class AlphaFirstLockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with (ROOT / "config" / "zel_alpha_engine_vnext.json").open("r", encoding="utf-8") as fh:
            cls.policy = json.load(fh)

    def test_policy_has_exact_three_families_and_g0(self):
        self.assertEqual([], MODULE.validate_policy(self.policy))
        self.assertEqual(["trend_momentum", "carry_flow", "relative_value_psa"], self.policy["alpha_engine"]["allowlist"])
        self.assertTrue(self.policy["g0_installation_certification"]["required_before_destructive_cleanup"])

    def test_zero_survivor_allows_g0_and_alpha_research(self):
        violations = MODULE.path_violations([
            "backend/research/eaf_stage3_costed_replay.py",
            "research/evidence/example.json",
            "strategies/alpha_engine/registry.py",
            "scripts/ci/g0_installation_census.py",
            ".github/workflows/zel-g0-installation-census.yml",
            "policies/zel/g0_installation_certification_v1.json",
        ], self.policy)
        self.assertEqual([], violations)

    def test_zero_survivor_blocks_downstream_expansion(self):
        violations = MODULE.path_violations([
            "frontend/new_panel.tsx",
            "engine/new_portfolio_allocator.py",
            "ensemble/new_meta_router.py",
            "shadow/new_writer.py",
        ], self.policy)
        self.assertEqual([
            "engine/new_portfolio_allocator.py",
            "ensemble/new_meta_router.py",
            "frontend/new_panel.tsx",
            "shadow/new_writer.py",
        ], violations)

    def test_win_rate_is_not_pass_gate(self):
        passed, failures = MODULE.objective_verdict({
            "integrity_ok": True,
            "oos_net_pnl": 1.0,
            "oos_expectancy": 0.01,
            "dd_within_ssot": True,
            "win_rate": 0.20,
        })
        self.assertTrue(passed)
        self.assertEqual([], failures)

    def test_nonpositive_edge_holds(self):
        passed, failures = MODULE.objective_verdict({
            "integrity_ok": True,
            "oos_net_pnl": 0.0,
            "oos_expectancy": -0.01,
            "dd_within_ssot": True,
            "win_rate": 0.90,
        })
        self.assertFalse(passed)
        self.assertEqual(["oos_net_pnl_positive", "oos_expectancy_positive"], failures)


if __name__ == "__main__":
    unittest.main()
