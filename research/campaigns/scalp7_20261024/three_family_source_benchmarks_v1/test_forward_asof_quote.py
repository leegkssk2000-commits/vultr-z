"""Fixed source-clock and no-order constraints for 4h candidate quote marks."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import forward_asof_quote as q


class ForwardQuoteTests(unittest.TestCase):
    def fixture(self, p: Path, *, connected: bool = True) -> tuple[Path, Path]:
        hb = {
            "order_authority": "BLOCKED",
            "execution_authority": "NONE",
            "exchange_order_submitted": False,
            "symbols": ["BTC-USDT", "ETH-USDT"],
            "updated_at_ms": 12000,
            "streams": {"depth": {"connected": connected}},
        }
        h = p / "heartbeat.json"
        h.write_text(json.dumps(hb))
        ledger = p / "quote.jsonl"
        rows = [
            {
                "symbol": "BTC-USDT",
                "bucket_end_ms": stamp,
                "best_bid_last": 99.5,
                "best_ask_last": 100.0,
                "depth_messages": 20,
                "order_authority": "BLOCKED",
                "execution_authority": "NONE",
                "exchange_order_submitted": False,
            }
            for stamp in (7000, 11000, 13000)
        ]
        ledger.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
        return ledger, h

    def test_exact_postdecision_quote_mark_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p, h = self.fixture(Path(tmp))
            result = q.observe(
                "BTC-USDT",
                decision_ts_ms=10000,
                read_at_ms=14000,
                history=p,
                heartbeat=h,
            )
            self.assertEqual(
                result["state"], "OBSERVED_REAL_POST_DECISION_BOOK_ONLY_NO_FILL"
            )
            self.assertEqual(result["source_quote_ts_ms"], 13000)
            self.assertFalse(result["original_next_open_fill_verified"])
            self.assertFalse(result["virtual_fill"])
            self.assertFalse(result["real_trade"])
            self.assertEqual(result["order_calls"], 0)
            self.assertGreater(result["spread_bps"], 0)

    def test_predecision_not_backfilled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p, h = self.fixture(Path(tmp))
            result = q.observe(
                "BTC-USDT",
                decision_ts_ms=13500,
                read_at_ms=14000,
                history=p,
                heartbeat=h,
            )
            self.assertEqual(result["state"], "HOLD_NO_POST_DECISION_QUOTE")

    def test_no_out_of_window_quote(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p, h = self.fixture(Path(tmp))
            result = q.observe(
                "BTC-USDT",
                decision_ts_ms=12000,
                read_at_ms=14000,
                history=p,
                heartbeat=h,
            )
            self.assertEqual(result["source_quote_ts_ms"], 13000)

    def test_unapproved_symbol_never_credited(self) -> None:
        result = q.observe("SOL-USDT", decision_ts_ms=10000, read_at_ms=14000)
        self.assertEqual(result["state"], "HOLD_NO_EXISTING_WS_QUOTE_FOR_SYMBOL")

    def test_future_decision_rejected(self) -> None:
        result = q.observe("BTC-USDT", decision_ts_ms=14001, read_at_ms=14000)
        self.assertEqual(result["state"], "HOLD_INVALID_DECISION_CLOCK")

    def test_stale_or_disconnected_heartbeat_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p, h = self.fixture(Path(tmp), connected=False)
            result = q.observe(
                "BTC-USDT",
                decision_ts_ms=10000,
                read_at_ms=14000,
                history=p,
                heartbeat=h,
            )
            self.assertIn("HOLD_WS_NOT_LIVE", result["state"])
            hb = json.loads(h.read_text())
            hb["streams"]["depth"]["connected"] = True
            hb["updated_at_ms"] = 1
            h.write_text(json.dumps(hb))
            result = q.observe(
                "BTC-USDT",
                decision_ts_ms=10000,
                read_at_ms=14000,
                history=p,
                heartbeat=h,
            )
            self.assertIn("HOLD_WS_NOT_LIVE", result["state"])

    def test_unguarded_ledger_order_row_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p, h = self.fixture(Path(tmp))
            rows = [json.loads(x) for x in p.read_text().splitlines()]
            for row in rows:
                row["exchange_order_submitted"] = True
            p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
            result = q.observe(
                "BTC-USDT",
                decision_ts_ms=10000,
                read_at_ms=14000,
                history=p,
                heartbeat=h,
            )
            self.assertEqual(result["state"], "HOLD_NO_POST_DECISION_QUOTE")

    def test_crossed_book_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p, h = self.fixture(Path(tmp))
            rows = [json.loads(x) for x in p.read_text().splitlines()]
            for row in rows:
                row["best_bid_last"] = 110
            p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
            result = q.observe(
                "BTC-USDT",
                decision_ts_ms=10000,
                read_at_ms=14000,
                history=p,
                heartbeat=h,
            )
            self.assertEqual(result["state"], "HOLD_NO_POST_DECISION_QUOTE")

    def test_missing_ledger_is_hold_not_trade(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p, h = self.fixture(Path(tmp))
            p.unlink()
            result = q.observe(
                "BTC-USDT",
                decision_ts_ms=10000,
                read_at_ms=14000,
                history=p,
                heartbeat=h,
            )
            self.assertEqual(result["state"], "HOLD_WS_SOURCE_UNAVAILABLE_OR_MALFORMED")


if __name__ == "__main__":
    unittest.main()
