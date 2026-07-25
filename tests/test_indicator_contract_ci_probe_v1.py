from __future__ import annotations

import unittest

from backend.strategy25.indicator_contract_repair_adapter_v1 import repair_manifest


EXPECTED_CHILDREN = {
    "break_and_continue",
    "fvg_revert",
    "scalp_snap",
    "session_bias",
    "sr_levels",
}


class IndicatorContractCiProbeV1Test(unittest.TestCase):
    def test_repair_manifest_has_five_fail_closed_children(self) -> None:
        rows = repair_manifest()
        self.assertEqual(len(rows), 5)
        self.assertEqual({row["strategy_id"] for row in rows}, EXPECTED_CHILDREN)
        self.assertTrue(all(row["read_only_child"] for row in rows))
        self.assertTrue(all(not row["canonical_mutated"] for row in rows))
        self.assertTrue(all(not row["execution_allowed"] for row in rows))
        self.assertTrue(all(len(row["expected_sha256"]) == 64 for row in rows))


if __name__ == "__main__":
    unittest.main()
