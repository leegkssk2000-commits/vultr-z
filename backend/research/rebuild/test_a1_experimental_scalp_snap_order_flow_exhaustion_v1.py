from __future__ import annotations

import unittest

from backend.research.rebuild.a1_experimental_scalp_snap_order_flow_exhaustion_evaluator_v1 import exhaustion_confirmation


def row(start: int, flow: float, book: float):
    return {
        "schema_version": "zel.production_bingx_ws_microstructure_row.v1",
        "symbol": "BTC-USDT",
        "bucket_start_ms": start,
        "bucket_end_ms": start + 5000,
        "mid_last": 100.0,
        "spread_bps_mean": 1.0,
        "trade_quote_notional": 1000.0,
        "trade_imbalance": flow,
        "imbalance_top20_mean": book,
        "bid_qty_top20_last": 10.0,
        "ask_qty_top20_last": 10.0,
        "depth_messages": 1,
    }


class ExhaustionConfirmationTests(unittest.TestCase):
    def index(self, rows):
        ends = [x["bucket_end_ms"] for x in rows]
        return {"BTC-USDT": (ends, rows)}

    def test_long_requires_down_flow_then_up_flow_and_up_book(self):
        rows = [row(0, -0.8, -0.3), row(5000, 0.6, 0.4)]
        result = exhaustion_confirmation(self.index(rows), "BTC-USDT", 10000, "long")
        self.assertTrue(result["passed"])
        self.assertEqual(result["reason"], "ORDER_FLOW_EXHAUSTION_CONFIRMED")

    def test_short_requires_up_flow_then_down_flow_and_down_book(self):
        rows = [row(0, 0.8, 0.3), row(5000, -0.6, -0.4)]
        self.assertTrue(exhaustion_confirmation(self.index(rows), "BTC-USDT", 10000, "short")["passed"])

    def test_no_flow_flip_fails(self):
        rows = [row(0, -0.8, -0.3), row(5000, -0.6, 0.4)]
        self.assertFalse(exhaustion_confirmation(self.index(rows), "BTC-USDT", 10000, "long")["passed"])

    def test_book_not_aligned_fails(self):
        rows = [row(0, -0.8, -0.3), row(5000, 0.6, -0.4)]
        self.assertFalse(exhaustion_confirmation(self.index(rows), "BTC-USDT", 10000, "long")["passed"])

    def test_stale_or_nonconsecutive_micro_data_fails_closed(self):
        stale = [row(0, -0.8, -0.3), row(5000, 0.6, 0.4)]
        self.assertEqual(exhaustion_confirmation(self.index(stale), "BTC-USDT", 16000, "long")["reason"], "PREENTRY_MICRO_BUCKET_STALE")
        gap = [row(0, -0.8, -0.3), row(10000, 0.6, 0.4)]
        self.assertEqual(exhaustion_confirmation(self.index(gap), "BTC-USDT", 15000, "long")["reason"], "MICRO_BUCKETS_NOT_CONSECUTIVE")


if __name__ == "__main__":
    unittest.main()
