from __future__ import annotations

import copy
import unittest

from backend.strategy25.fvg_trend_alignment_child_v1 import (
    CHILD_MANIFEST,
    POLICY_ID,
    apply_fvg_trend_alignment,
)


class FvgTrendAlignmentChildV1Test(unittest.TestCase):
    def _result(self, *, trend_long: bool, side: str | None = "long", action: str = "enter") -> dict:
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
            "indicators": {"trend_long": trend_long, "gap_dir": "down"},
        }

    def test_blocks_unaligned_long_entry_fail_closed(self) -> None:
        source = self._result(trend_long=False)
        before = copy.deepcopy(source)
        output = apply_fvg_trend_alignment(source)

        self.assertEqual(source, before)
        self.assertIsNone(output["side"])
        self.assertEqual(output["action"], "hold")
        self.assertEqual(output["size"], 0.0)
        self.assertEqual(output["why"], "fvg_trend_alignment_gate")
        self.assertTrue(output["indicators"]["trend_alignment_gate_blocked"])
        self.assertEqual(output["indicators"]["policy_id"], POLICY_ID)

    def test_passes_aligned_long_entry(self) -> None:
        output = apply_fvg_trend_alignment(self._result(trend_long=True))
        self.assertEqual(output["side"], "long")
        self.assertEqual(output["action"], "enter")
        self.assertEqual(output["size"], 0.44)
        self.assertFalse(output["indicators"]["trend_alignment_gate_blocked"])

    def test_does_not_block_short_or_hold(self) -> None:
        short_output = apply_fvg_trend_alignment(self._result(trend_long=False, side="short"))
        hold_output = apply_fvg_trend_alignment(self._result(trend_long=False, side=None, action="hold"))
        self.assertEqual(short_output["action"], "enter")
        self.assertEqual(short_output["side"], "short")
        self.assertEqual(hold_output["action"], "hold")
        self.assertIsNone(hold_output["side"])

    def test_manifest_is_child_only_and_no_authority(self) -> None:
        self.assertTrue(CHILD_MANIFEST["read_only_child"])
        self.assertFalse(CHILD_MANIFEST["canonical_mutated"])
        self.assertFalse(CHILD_MANIFEST["registry_mutated"])
        self.assertFalse(CHILD_MANIFEST["route_allowed"])
        self.assertFalse(CHILD_MANIFEST["execution_allowed"])
        self.assertEqual(CHILD_MANIFEST["scope"], "LONG_ENTER_ONLY")

    def test_non_mapping_fails_closed(self) -> None:
        with self.assertRaises(TypeError):
            apply_fvg_trend_alignment(None)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
