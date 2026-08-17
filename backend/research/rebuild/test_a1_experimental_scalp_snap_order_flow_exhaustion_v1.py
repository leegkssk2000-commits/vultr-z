from __future__ import annotations

import json
import unittest
from pathlib import Path

from backend.research.rebuild.a1_experimental_scalp_snap_order_flow_exhaustion_evaluator_v1 import confirmation_for_entry
from backend.research.rebuild.microstructure_policy_batch_v1 import MicroPolicyConfig

ROOT = Path(__file__).resolve().parents[3]


def row(start: int, flow: float, book: float, *, complete: bool = True) -> dict:
    return {
        "schema_version": "zel.production_bingx_ws_microstructure_row.v1",
        "symbol": "BTC-USDT",
        "bucket_start_ms": start,
        "bucket_end_ms": start + 5000,
        "trade_imbalance": flow,
        "imbalance_top20_mean": book,
        "mid_last": 100.0,
        "trade_quote_notional": 1000.0,
        "spread_bps_mean": 1.0,
        "bid_qty_top20_last": 10.0,
        "ask_qty_top20_last": 10.0,
        "depth_messages": 1 if complete else 0,
    }


class ScalpExhaustionContractTest(unittest.TestCase):
    def test_long_requires_drive_then_reversal_and_book_alignment(self) -> None:
        rows = [row(0, -0.8, -0.3), row(5000, 0.7, 0.4)]
        got = confirmation_for_entry(rows, symbol="BTC-USDT", entry_ts_ms=10_000, side="long")
        self.assertTrue(got["pass"])
        self.assertEqual(got["source_entry_cutoff_ms"], 10_000)

    def test_short_inverse_contract(self) -> None:
        rows = [row(0, 0.8, 0.3), row(5000, -0.7, -0.4)]
        self.assertTrue(confirmation_for_entry(rows, symbol="BTC-USDT", entry_ts_ms=10_000, side="short")["pass"])

    def test_future_bucket_is_never_used(self) -> None:
        rows = [row(0, -0.8, -0.3), row(5000, -0.7, -0.4), row(10_000, 0.9, 0.9)]
        got = confirmation_for_entry(rows, symbol="BTC-USDT", entry_ts_ms=10_000, side="long")
        self.assertFalse(got["pass"])
        self.assertEqual(got["reason"], "ORDER_FLOW_EXHAUSTION_NOT_CONFIRMED")

    def test_missing_or_stale_fails_closed(self) -> None:
        self.assertFalse(confirmation_for_entry([row(0, -1, -1)], symbol="BTC-USDT", entry_ts_ms=5000, side="long")["pass"])
        stale = [row(0, -1, -1), row(5000, 1, 1)]
        got = confirmation_for_entry(stale, symbol="BTC-USDT", entry_ts_ms=30_000, side="long")
        self.assertFalse(got["pass"])
        self.assertEqual(got["reason"], "STALE_MICRO_CONFIRMATION")

    def test_nonconsecutive_and_incomplete_fail_closed(self) -> None:
        nonconsecutive = [row(0, -1, -1), row(10_000, 1, 1)]
        self.assertEqual(confirmation_for_entry(nonconsecutive, symbol="BTC-USDT", entry_ts_ms=15_000, side="long")["reason"], "NON_CONSECUTIVE_MICRO_BUCKETS")
        incomplete = [row(0, -1, -1), row(5000, 1, 1, complete=False)]
        self.assertFalse(confirmation_for_entry(incomplete, symbol="BTC-USDT", entry_ts_ms=10_000, side="long")["pass"])

    def test_baseline_geometry_and_cost_authority_unchanged(self) -> None:
        cfg = MicroPolicyConfig()
        exp = json.loads((ROOT / "backend/research/rebuild/a1_experimental_scalp_snap_order_flow_exhaustion_config_v1.json").read_text())
        policy = json.loads((ROOT / "backend/research/rebuild/a1_experimental_scalp_snap_order_flow_exhaustion_policy_v1.json").read_text())
        self.assertEqual(cfg.timeframe_ms, 300_000)
        self.assertEqual(cfg.timeout_bars, 18)
        self.assertEqual(cfg.risk_fraction_of_equity, 0.0035)
        self.assertEqual(cfg.max_notional_fraction_of_equity, 0.10)
        self.assertEqual(exp["verified_pretrade_cost_bps_reference"], 14.0)
        self.assertFalse(exp["baseline_clock_reset"])
        self.assertFalse(exp["parameter_search"])
        self.assertFalse(exp["best_horizon_selection"])
        self.assertFalse(exp["threshold_tuning"])
        self.assertFalse(policy["frozen_constraints"]["tp_sl_timeout_risk_change"])
        self.assertFalse(policy["frozen_constraints"]["baseline_policy_mutation"])
        self.assertEqual(policy["selected_axis"], "ORDER_FLOW_EXHAUSTION_CONFIRMATION")


if __name__ == "__main__":
    unittest.main()
