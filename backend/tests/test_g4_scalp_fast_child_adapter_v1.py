from __future__ import annotations

import unittest
from dataclasses import asdict

from backend.research.rebuild import g4_scalp_fast_child_adapter_v1 as m


class FastChildAdapterTest(unittest.TestCase):
    def test_freeze_parity(self) -> None:
        m.assert_freeze_parity()
        self.assertEqual(len(m.SPECS), 9)

    def test_only_timeframe_and_timeout_change(self) -> None:
        for child_id, spec in m.SPECS.items():
            parent = asdict(m._default_config(spec))
            child = asdict(m.config_for(child_id))
            changed = {k for k in parent if parent[k] != child[k]}
            self.assertEqual(changed, {"timeframe_ms", "timeout_bars"}, child_id)
            self.assertEqual(child["timeframe_ms"], spec.timeframe_ms)
            self.assertEqual(child["timeout_bars"], spec.timeout_bars)

    def test_all_children_build_distinct_identity(self) -> None:
        for child_id, spec in m.SPECS.items():
            step = spec.timeframe_ms
            bars = []
            price = 100.0
            for i in range(320):
                drift = 0.02 if (i // 16) % 2 == 0 else -0.01
                o = price
                c = max(1.0, o + drift)
                h = max(o, c) + 0.08
                l = min(o, c) - 0.08
                bars.append({"ts_ms": 1_700_000_000_000 + i * step, "open": o, "high": h, "low": l, "close": c, "volume": 1000.0 + i})
                price = c
            feature = m.compute_child_feature(child_id, bars, symbol="BTC-USDT", now_ts_ms=bars[-1]["ts_ms"])
            intent = m.build_child_intent(child_id, feature, policy_source_sha="test-source", verified_round_trip_cost_bps=14.0)
            self.assertEqual(intent.strategy_id, child_id)
            self.assertEqual(intent.schema_version, f"zel.{child_id}.policy.v1")
            self.assertEqual(int(intent.timeout["bars"]), spec.timeout_bars)
            self.assertIn("FAST_CHILD_TIME_COMPRESSION_V1", intent.reason_codes)
            self.assertEqual(intent.config_sha, m.config_for(child_id).sha)


if __name__ == "__main__":
    unittest.main()
