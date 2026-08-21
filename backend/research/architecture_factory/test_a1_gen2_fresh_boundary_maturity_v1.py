from __future__ import annotations

import unittest

from backend.research.architecture_factory.a1_gen2_fresh_boundary_replay_v1 import (
    DAY_MS,
    split_mature_fresh,
)


class FreshBoundaryMaturityTest(unittest.TestCase):
    def test_twelve_day_horizon_must_be_complete(self) -> None:
        boundary = 100 * DAY_MS
        rows = [
            {"signal_ts": boundary + DAY_MS, "exit_ts": boundary + 12 * DAY_MS},
            {"signal_ts": boundary + 2 * DAY_MS, "exit_ts": boundary + 14 * DAY_MS},
            {"signal_ts": boundary, "exit_ts": boundary + 20 * DAY_MS},
        ]
        mature, immature = split_mature_fresh(rows, boundary_ms=boundary, hold_days=12)
        self.assertEqual(mature, [rows[1]])
        self.assertEqual(immature, [rows[0]])


if __name__ == "__main__":
    unittest.main()
