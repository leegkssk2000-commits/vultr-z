from __future__ import annotations

import unittest

from backend.strategy25.indicator_contract_repair_adapter_v1 import repair_manifest


class IndicatorContractCiProbeV1Test(unittest.TestCase):
    def test_repair_manifest_has_four_fail_closed_children(self) -> None:
        rows = repair_manifest()
        self.assertEqual(len(rows), 4)
        self.assertEqual(
            {row["strategy_id"] for row in rows},
            {"break_and_continue", "fvg_revert", "session_bias", "sr_levels"},
        )
        self.assertTrue(all(row["read_only_child"] for row in rows))
        self.assertTrue(all(not row["canonical_mutated"] for row in rows))
        self.assertTrue(all(not row["execution_allowed"] for row in rows))
        self.assertTrue(all(len(row["expected_sha256"]) == 64 for row in rows))


if __name__ == "__main__":
    unittest.main()
