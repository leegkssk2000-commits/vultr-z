from __future__ import annotations

import unittest

from backend.research.rebuild.g4_scalp_intraday_round0_v1 import (
    EXPECTED_DONOR_ONLY,
    EXPECTED_FAST_CHILD,
    EXPECTED_SCALP_NATIVE,
    build_result,
)


class G4ScalpIntradayRound0Tests(unittest.TestCase):
    def test_exact25_census_and_buckets(self) -> None:
        result = build_result()
        self.assertEqual(result["counts"]["exact25"], 25)
        self.assertEqual(result["counts"]["scalp_native_round1_eligible"], 15)
        self.assertEqual(result["counts"]["daytrade_native_round1_eligible"], 0)
        self.assertEqual(result["counts"]["fast_child_required_before_round1"], 9)
        self.assertEqual(result["counts"]["donor_only_current"], 1)
        self.assertEqual(set(result["buckets"]["SCALP_NATIVE_ROUND1_ELIGIBLE"]), EXPECTED_SCALP_NATIVE)
        self.assertEqual(set(result["buckets"]["FAST_CHILD_REQUIRED_BEFORE_ROUND1"]), EXPECTED_FAST_CHILD)
        self.assertEqual(set(result["buckets"]["DONOR_ONLY_CURRENT"]), EXPECTED_DONOR_ONLY)

    def test_round0_never_uses_old_pnl(self) -> None:
        result = build_result()
        for row in result["strategies"].values():
            self.assertFalse(row["round0_economics_used"])
            self.assertFalse(row["old_pnl_used_for_classification"])

    def test_native_scalp_hard_timeout(self) -> None:
        result = build_result()
        for sid in result["buckets"]["SCALP_NATIVE_ROUND1_ELIGIBLE"]:
            row = result["strategies"][sid]
            self.assertLessEqual(row["timeframe_ms"], 300000)
            self.assertLessEqual(row["hard_timeout_minutes"], 180.0)

    def test_slow_current_policies_do_not_leak_into_round1(self) -> None:
        result = build_result()
        for sid in result["buckets"]["FAST_CHILD_REQUIRED_BEFORE_ROUND1"]:
            row = result["strategies"][sid]
            self.assertGreater(row["hard_timeout_minutes"], 720.0)
            self.assertIn("fast_child_authorization", row)

    def test_authority_remains_blocked(self) -> None:
        result = build_result()
        authority = result["authority"]
        self.assertFalse(authority["selection_authority"])
        self.assertFalse(authority["promotion_authority"])
        self.assertEqual(authority["execution_authority"], "NONE")
        self.assertEqual(authority["order_authority"], "BLOCKED")
        self.assertEqual(authority["live_trade_authority"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()
