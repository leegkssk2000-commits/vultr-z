from __future__ import annotations

import unittest

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ge
from backend.research.rebuild.a1_exact25_policy_adapter_v1 import policy_functions


class PolicyAdapterTests(unittest.TestCase):
    def test_all_exact25_policy_owners_have_evaluator_adapter(self):
        inventory = ge.load_json(ge.INVENTORY_PATH)
        strategies = inventory.get("strategies") or {}
        self.assertEqual(len(strategies), 25)
        for strategy_id in sorted(strategies):
            module, _, _ = ge.load_policy(strategy_id, inventory)
            cfg = ge.config_instance(module)
            ge.interval_for_ms(int(getattr(cfg, "timeframe_ms")))
            compute, build = policy_functions(module, strategy_id)
            self.assertTrue(callable(compute), strategy_id)
            self.assertTrue(callable(build), strategy_id)


if __name__ == "__main__":
    unittest.main()
