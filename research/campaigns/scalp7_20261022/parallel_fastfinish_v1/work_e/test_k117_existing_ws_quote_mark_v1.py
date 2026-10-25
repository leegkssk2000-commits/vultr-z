"""No-order WS quote as-of audit, never a fabricated virtual fill."""

from __future__ import annotations

import importlib
import json
import tempfile
import unittest
from pathlib import Path

quote = importlib.import_module("k117_existing_ws_quote_mark_v1")


def source_fixture(tmp: Path, unsafe: bool = False) -> tuple[Path, Path]:
    hb = {
        "order_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "execution_authority": "NONE",
        "symbols": ["BTC-USDT", "ETH-USDT"],
        "updated_at_ms": 15_900,
        "streams": {"depth": {"connected": not unsafe}},
    }
    hp = tmp / "heartbeat.json"
    hp.write_text(json.dumps(hb))
    file = tmp / "quote.jsonl"
    lines = [
        {
            "symbol": "BTC-USDT",
            "bucket_end_ms": ts,
            "best_bid_last": 100,
            "best_ask_last": 101,
            "order_authority": "BLOCKED",
            "execution_authority": "NONE",
            "exchange_order_submitted": False,
            "depth_messages": 5,
        }
        for ts in (10_000, 15_000)
    ]
    file.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    return file, hp


class ReadonlyWsQuote(unittest.TestCase):
    def test_existing_quote_only_never_fill(self):
        with tempfile.TemporaryDirectory() as directory:
            p, h = source_fixture(Path(directory))
            d = quote.observe(
                "BTC-USDT",
                decision_ts_ms=13_000,
                read_at_ms=16_000,
                history=p,
                heartbeat=h,
            )
            self.assertTrue(d["state"].startswith("PASS_REAL_EXISTING"))
            self.assertEqual(d["source_bucket_end_ms"], 15_000)
            self.assertFalse(d["hypothetical_virtual_fill"])
            self.assertEqual(d["order_calls"], 0)
            self.assertEqual(d["best_ask_observed"], 101)

    def test_earlier_than_decision_not_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            p, h = source_fixture(Path(directory))
            d = quote.observe(
                "BTC-USDT",
                decision_ts_ms=15_500,
                read_at_ms=16_000,
                history=p,
                heartbeat=h,
            )
            self.assertEqual(
                d["state"], "HOLD_NO_TIMESTAMPED_WS_QUOTE_AFTER_NATIVE_SIGNAL"
            )

    def test_missing_quote_for_sol_not_faked(self):
        d = quote.observe("SOL-USDT", decision_ts_ms=1000, read_at_ms=1100)
        self.assertEqual(d["state"], "HOLD_SYMBOL_HAS_NO_APPROVED_WS_BOOK")
        self.assertFalse(d["hypothetical_virtual_fill"])

    def test_stale_heartbeat_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            p, h = source_fixture(Path(directory))
            d = quote.observe(
                "BTC-USDT",
                decision_ts_ms=13000,
                read_at_ms=30000,
                history=p,
                heartbeat=h,
            )
            self.assertEqual(d["state"], "HOLD_WS_HEARTBEAT_NOT_LIVE_OR_ORDER_ISOLATED")

    def test_depth_disconnected_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            p, h = source_fixture(Path(directory), unsafe=True)
            d = quote.observe(
                "ETH-USDT",
                decision_ts_ms=13000,
                read_at_ms=16000,
                history=p,
                heartbeat=h,
            )
            self.assertEqual(d["state"], "HOLD_WS_HEARTBEAT_NOT_LIVE_OR_ORDER_ISOLATED")

    def test_future_quote_not_used(self):
        with tempfile.TemporaryDirectory() as directory:
            p, h = source_fixture(Path(directory))
            state = json.loads(h.read_text())
            state["updated_at_ms"] = 10500
            h.write_text(json.dumps(state))
            d = quote.observe(
                "BTC-USDT",
                decision_ts_ms=9000,
                read_at_ms=11000,
                history=p,
                heartbeat=h,
            )
            self.assertEqual(d["source_bucket_end_ms"], 10000)
            self.assertFalse(d["hypothetical_virtual_fill"])

    def test_crossed_bid_ask_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            p, h = source_fixture(Path(directory))
            contents = [json.loads(x) for x in p.read_text().splitlines()]
            for item in contents:
                item["best_bid_last"] = 102
                item["best_ask_last"] = 101
            p.write_text("\n".join(json.dumps(x) for x in contents) + "\n")
            d = quote.observe(
                "BTC-USDT",
                decision_ts_ms=13000,
                read_at_ms=16000,
                history=p,
                heartbeat=h,
            )
            self.assertEqual(
                d["state"], "HOLD_NO_TIMESTAMPED_WS_QUOTE_AFTER_NATIVE_SIGNAL"
            )

    def test_unblocked_exchange_order_row_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            p, h = source_fixture(Path(directory))
            contents = [json.loads(x) for x in p.read_text().splitlines()]
            for item in contents:
                item["exchange_order_submitted"] = True
            p.write_text("\n".join(json.dumps(x) for x in contents) + "\n")
            d = quote.observe(
                "BTC-USDT",
                decision_ts_ms=13000,
                read_at_ms=16000,
                history=p,
                heartbeat=h,
            )
            self.assertEqual(
                d["state"], "HOLD_NO_TIMESTAMPED_WS_QUOTE_AFTER_NATIVE_SIGNAL"
            )


if __name__ == "__main__":
    unittest.main()
