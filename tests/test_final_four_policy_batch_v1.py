from __future__ import annotations

import unittest

from backend.research.rebuild.final_four_policy_batch_v1 import (
    FinalFourConfig,
    FeatureSnapshot,
    SUPPORTED,
    features,
    intent_from_snapshot,
    evaluate,
)
from backend.research.rebuild.policy_kernel_v1 import (
    control_delayed_entry,
    control_direction_flip,
    control_time_placebo,
    evaluator_adapter_sha,
)


class FinalFourPolicyR2T(unittest.TestCase):
    def _snap(self, sid: str, *, side: str = "long", fresh: bool = True, atr_value: float = 2.0, rr: float = 2.0) -> FeatureSnapshot:
        values = {"fixture": sid, "side": side, "fresh": fresh, "atr": atr_value}
        return FeatureSnapshot(
            strategy_id=sid,
            symbol="BTC-USDT",
            signal_ts=1_786_840_000_000,
            fresh=fresh,
            close=100.0,
            atr=atr_value,
            side=side,
            regime="planted_edge",
            strength=0.8,
            entry_rule="planted_structural_fixture",
            stop_mult=1.0,
            rr=rr,
            values=values,
            feature_sha="f" * 64,
        )

    def test_planted_edge_and_parity_for_all_four(self):
        for sid in SUPPORTED:
            with self.subTest(sid=sid):
                intent = intent_from_snapshot(self._snap(sid), policy_source_sha="a" * 64, verified_round_trip_cost_bps=10.0)
                self.assertFalse(intent.no_trade)
                self.assertEqual(intent.side, "long")
                self.assertGreaterEqual(intent.cost_budget_ratio, 1.25)
                self.assertEqual(evaluator_adapter_sha(intent), intent.sha)
                self.assertEqual(intent.pyramiding, {"enabled": False, "adverse_add": False})
                self.assertFalse(intent.partial["enabled"])
                self.assertFalse(intent.trailing["enabled"])

    def test_negative_controls_are_structurally_distinct(self):
        for sid in SUPPORTED:
            intent = intent_from_snapshot(self._snap(sid), policy_source_sha="b" * 64, verified_round_trip_cost_bps=10.0)
            controls = (
                control_direction_flip(intent),
                control_time_placebo(intent, 900_000),
                control_delayed_entry(intent, 1, 300_000),
            )
            self.assertEqual(len({c.sha for c in controls}), 3)
            self.assertTrue(all(c.sha != intent.sha for c in controls))

    def test_verified_cost_authority_is_mandatory(self):
        for sid in SUPPORTED:
            with self.assertRaises(ValueError):
                intent_from_snapshot(self._snap(sid), policy_source_sha="c" * 64, verified_round_trip_cost_bps=0.0)

    def test_cost_budget_fails_closed(self):
        for sid in SUPPORTED:
            intent = intent_from_snapshot(self._snap(sid, atr_value=0.01, rr=1.0), policy_source_sha="d" * 64, verified_round_trip_cost_bps=10.0)
            self.assertTrue(intent.no_trade)
            self.assertIn("COST_BUDGET_FAIL", intent.reason_codes)

    def test_stale_snapshot_fails_closed(self):
        for sid in SUPPORTED:
            intent = intent_from_snapshot(self._snap(sid, fresh=False), policy_source_sha="e" * 64, verified_round_trip_cost_bps=10.0)
            self.assertTrue(intent.no_trade)
            self.assertIn("STALE_INPUT", intent.reason_codes)

    def _bars(self, n: int = 130):
        base_ts = 1_786_800_000_000
        out = []
        price = 100.0
        for i in range(n):
            price += 0.02
            out.append({
                "ts_ms": base_ts + i * 300_000,
                "open": price - 0.05,
                "high": price + 0.15,
                "low": price - 0.15,
                "close": price,
                "volume": 100.0 + (i % 7),
            })
        return out

    def test_duplicate_timestamp_fails_closed(self):
        bars = self._bars()
        bars[-1] = dict(bars[-1], ts_ms=bars[-2]["ts_ms"])
        for sid in SUPPORTED:
            intent = evaluate(sid, bars, symbol="BTC-USDT", now_ms=bars[-1]["ts_ms"], policy_source_sha="f" * 64, verified_round_trip_cost_bps=10.0)
            self.assertTrue(intent.no_trade)
            self.assertIn("BAR_TS_NON_MONOTONIC_OR_DUPLICATE", intent.reason_codes)

    def test_rbreaker_and_sr_levels_exclude_current_bar_from_levels(self):
        bars = self._bars()
        now = bars[-1]["ts_ms"]
        for sid, key in (("rbreaker_like", "prior_hi"), ("sr_levels", "prior_hi")):
            before = features(sid, bars, symbol="BTC-USDT", now_ms=now)
            mutated = [dict(x) for x in bars]
            mutated[-1]["high"] = mutated[-1]["high"] + 50.0
            after = features(sid, mutated, symbol="BTC-USDT", now_ms=now)
            self.assertEqual(before.values[key], after.values[key])

    def test_session_regime_is_timestamp_deterministic(self):
        bars = self._bars()
        snap1 = features("session_bias", bars, symbol="BTC-USDT", now_ms=bars[-1]["ts_ms"])
        snap2 = features("session_bias", [dict(x) for x in bars], symbol="BTC-USDT", now_ms=bars[-1]["ts_ms"])
        self.assertEqual(snap1.values["session"], snap2.values["session"])
        self.assertEqual(snap1.feature_sha, snap2.feature_sha)

    def test_independent_risk_recompute(self):
        cfg = FinalFourConfig()
        for sid in SUPPORTED:
            intent = intent_from_snapshot(self._snap(sid, atr_value=2.0, rr=2.0), policy_source_sha="1" * 64, verified_round_trip_cost_bps=10.0, config=cfg)
            stop_bps = abs(intent.sl - 100.0) / 100.0 * 10_000.0
            expected_notional = min(cfg.max_notional_fraction_of_equity, cfg.risk_fraction_of_equity / (stop_bps / 10_000.0))
            self.assertAlmostEqual(intent.risk_size["stop_distance_bps"], stop_bps, places=9)
            self.assertAlmostEqual(intent.exposure["notional_fraction_of_equity"], expected_notional, places=9)


if __name__ == "__main__":
    unittest.main()
