from __future__ import annotations

import unittest

from backend.research.rebuild.a1_trend_rider_delayed_fill_evaluator_v1 import (
    enforce_policy_execution,
)
from backend.research.rebuild.trend_policy_batch_v1 import TrendPolicyConfig


class TrendRiderPolicyExecutionTest(unittest.TestCase):
    def test_transition_pyramiding_and_cooldown_are_fail_closed(self) -> None:
        hour = 3_600_000
        rows = [
            {"symbol": "BTC-USDT", "side": "long", "signal_ts": 0, "entry_ts": hour, "exit_ts": 3 * hour},
            {"symbol": "BTC-USDT", "side": "long", "signal_ts": hour, "entry_ts": 2 * hour, "exit_ts": 4 * hour},
            {"symbol": "BTC-USDT", "side": "short", "signal_ts": 2 * hour, "entry_ts": 3 * hour, "exit_ts": 5 * hour},
            {"symbol": "BTC-USDT", "side": "long", "signal_ts": 8 * hour, "entry_ts": 9 * hour, "exit_ts": 10 * hour},
        ]
        accepted, rejected = enforce_policy_execution(rows, TrendPolicyConfig())
        self.assertEqual([row["signal_ts"] for row in accepted], [0, 8 * hour])
        self.assertEqual(
            [row["reason"] for row in rejected],
            ["DUPLICATE_TRANSITION_FORBIDDEN", "PYRAMIDING_OR_COOLDOWN_BLOCKED"],
        )


if __name__ == "__main__":
    unittest.main()
