from __future__ import annotations

import unittest

from backend.research.rebuild import g5_clean_runner_cutover_progress_v1 as progress


class CutoverProgressTests(unittest.TestCase):
    def setUp(self) -> None:
        self.shadow = {
            "state": "CLEAN_RUNNER_SHADOW_PASS",
            "shadow_3bar_pass": True,
            "consecutive_complete_bar_count": 3,
            "source_parity": True,
            "child_parity": True,
            "duplicate": 0,
            "lookahead": 0,
            "binding_epoch": "KELTNER_V2_BINDING_FIX_V1",
            "binding_gate_current_child_only": True,
            "bar1": "2026-09-03T12:00:00Z",
            "bar2": "2026-09-03T16:00:00Z",
            "bar3": "2026-09-03T20:00:00Z",
        }
        self.stale = {
            "authority_created": True,
            "data_stale_authority_allowed": True,
            "timestamp_integrity": "PASS",
            "authority_value": 14_400_000,
            "authority_unit": "ms",
        }
        self.cutover = {"automatic_cutover": False, "eligible": True}

    def test_first_execution_freezes_anchor_and_waits(self) -> None:
        anchor, cutover, post = progress.derive(self.shadow, self.stale, self.cutover, None)
        self.assertEqual(anchor["anchor_bar_close_utc"], "2026-09-03T20:00:00Z")
        self.assertTrue(cutover["executed"])
        self.assertTrue(cutover["clean_runner_authority"])
        self.assertFalse(cutover["production_ready"])
        self.assertEqual(post["post_cutover_bars"], 0)
        self.assertFalse(post["post_cutover_3bar_pass"])
        self.assertEqual(cutover["execution_authority"], "NONE")
        self.assertEqual(cutover["order_authority"], "BLOCKED")
        self.assertEqual(cutover["live_trade_authority"], "BLOCKED")

    def test_three_new_bars_pass(self) -> None:
        anchor, _, _ = progress.derive(self.shadow, self.stale, self.cutover, None)
        later = dict(self.shadow)
        later.update({
            "bar1": "2026-09-04T00:00:00Z",
            "bar2": "2026-09-04T04:00:00Z",
            "bar3": "2026-09-04T08:00:00Z",
        })
        _, cutover, post = progress.derive(later, self.stale, self.cutover, anchor)
        self.assertEqual(post["post_cutover_bars"], 3)
        self.assertTrue(post["post_cutover_3bar_pass"])
        self.assertTrue(post["production_ready"])
        self.assertTrue(cutover["production_ready"])
        self.assertEqual(cutover["state"], "CLEAN_RUNNER_PRODUCTION_READY")

    def test_no_stale_authority_fails_closed(self) -> None:
        bad = dict(self.stale)
        bad["authority_created"] = False
        with self.assertRaisesRegex(progress.CutoverProgressError, "DATA_STALE_AUTHORITY_REQUIRED"):
            progress.derive(self.shadow, bad, self.cutover, None)


if __name__ == "__main__":
    unittest.main()
