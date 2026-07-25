from __future__ import annotations

import copy
import unittest

from backend.strategy25.fvg_trend_nonbeam_child_v1 import (
    CHILD_MANIFEST,
    POLICY_ID,
    apply_fvg_trend_nonbeam,
)


class FvgTrendNonbeamChildV1Test(unittest.TestCase):
    def _result(self, *, trend_long: bool, long_beam: bool, side: str | None = "long", action: str = "enter") -> dict:
        return {
            "side": side,
            "action": action,
            "size": 0.44,
            "entry": 100.0,
            "sl": 99.0,
            "tp": 102.0,
            "why": "fvg_down_fill_long",
            "skill": "gap_fill_revert",
            "confidence": 0.62,
            "tags": ["fvg", "long"],
            "indicators": {
                "trend_long": trend_long,
                "long_beam": long_beam,
                "gap_dir": "down",
            },
        }

    def test_passes_only_trend_aligned_nonbeam_long_entry(self) -> None:
        output = apply_fvg_trend_nonbeam(self._result(trend_long=True, long_beam=False))
        self.assertEqual(output["side"], "long")
        self.assertEqual(output["action"], "enter")
        self.assertEqual(output["size"], 0.44)
        self.assertFalse(output["indicators"]["trend_nonbeam_gate_blocked"])

    def test_blocks_unaligned_entry(self) -> None:
        source = self._result(trend_long=False, long_beam=False)
        before = copy.deepcopy(source)
        output = apply_fvg_trend_nonbeam(source)
        self.assertEqual(source, before)
        self.assertIsNone(output["side"])
        self.assertEqual(output["action"], "hold")
        self.assertEqual(output["why"], "fvg_trend_nonbeam_gate")
        self.assertTrue(output["indicators"]["trend_nonbeam_gate_blocked"])

    def test_blocks_beam_even_when_trend_aligned(self) -> None:
        output = apply_fvg_trend_nonbeam(self._result(trend_long=True, long_beam=True))
        self.assertIsNone(output["side"])
        self.assertEqual(output["action"], "hold")
        self.assertTrue(output["indicators"]["trend_nonbeam_gate_blocked"])
        self.assertEqual(output["indicators"]["policy_id"], POLICY_ID)

    def test_does_not_block_short_or_hold(self) -> None:
        short_output = apply_fvg_trend_nonbeam(
            self._result(trend_long=False, long_beam=True, side="short")
        )
        hold_output = apply_fvg_trend_nonbeam(
            self._result(trend_long=False, long_beam=True, side=None, action="hold")
        )
        self.assertEqual(short_output["side"], "short")
        self.assertEqual(short_output["action"], "enter")
        self.assertIsNone(hold_output["side"])
        self.assertEqual(hold_output["action"], "hold")

    def test_manifest_has_no_authority(self) -> None:
        self.assertTrue(CHILD_MANIFEST["read_only_child"])
        self.assertFalse(CHILD_MANIFEST["canonical_mutated"])
        self.assertFalse(CHILD_MANIFEST["registry_mutated"])
        self.assertFalse(CHILD_MANIFEST["route_allowed"])
        self.assertFalse(CHILD_MANIFEST["execution_allowed"])
        self.assertIn("incremental beam-veto", CHILD_MANIFEST["lineage"])


if __name__ == "__main__":
    unittest.main()
