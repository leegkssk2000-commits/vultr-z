from __future__ import annotations

import copy
import unittest

from backend.research.architecture_factory import a1_external_research_exact8_replay_router_v1 as router


class Exact8ReplayRouterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.spec = router.read(router.DEFAULT_SPEC)
        cls.manifest = router.read(router.DEFAULT_MANIFEST)

    def test_exact_lanes_and_no_boundary(self) -> None:
        plan = router.build_plan(self.spec, self.manifest)
        self.assertEqual(
            plan["counts"],
            {
                "post_merge_source_audit": 6,
                "hold_history_8640_returns": 1,
                "hold_preentry_l2_trades_history": 1,
            },
        )
        self.assertFalse(plan["fresh_boundary_assigned"])
        self.assertFalse(plan["boundary_assignment_authority"])
        self.assertFalse(plan["replay_performed"])
        self.assertEqual(plan["effect_verified_count"], 0)

    def test_each_child_is_unique_and_not_run(self) -> None:
        rows = router.build_plan(self.spec, self.manifest)["rows"]
        self.assertEqual(len({x["child_id"] for x in rows}), 8)
        self.assertTrue(all(x["replay_state"] == "NOT_RUN" for x in rows))
        self.assertTrue(all(x["effect_verified"] is False for x in rows))

    def test_boundary_and_effect_claims_fail_closed(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        manifest["fresh_boundary_assigned"] = True
        with self.assertRaisesRegex(RuntimeError, "PREMERGE_BOUNDARY_FORBIDDEN"):
            router.build_plan(self.spec, manifest)
        spec = copy.deepcopy(self.spec)
        spec["effect_verified_count"] = 1
        with self.assertRaisesRegex(RuntimeError, "UNVERIFIED_EFFECT_REQUIRED"):
            router.build_plan(spec, self.manifest)

    def test_authority_remains_blocked(self) -> None:
        plan = router.build_plan(self.spec, self.manifest)
        self.assertFalse(plan["selection_authority"])
        self.assertFalse(plan["promotion_authority"])
        self.assertEqual(plan["execution_authority"], "NONE")
        self.assertEqual(plan["order_authority"], "BLOCKED")
        self.assertEqual(plan["live_trade_authority"], "BLOCKED")
        self.assertEqual(plan["protected_mutations"], 0)


if __name__ == "__main__":
    unittest.main()
