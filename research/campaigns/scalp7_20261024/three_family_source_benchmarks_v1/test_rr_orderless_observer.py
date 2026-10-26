"""No historical fill, no order, causal RR protection and native parity fences."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import rr_orderless_observer as r


def signal(family: str = r.TSMOM) -> dict:
    return {
        "rule_id": family,
        "symbol": "BTC-USDT",
        "decision_ms": 1000,
        "risk_bps": 100,
        "max_hold_ms": r.FOUR * 24,
        "original_signal_digest": "signal123",
    }


def quote(bid: float, ask: float, ts: int) -> dict:
    return {
        "state": "OBSERVED_REAL_POST_DECISION_BOOK_ONLY_NO_FILL",
        "best_bid": bid,
        "best_ask": ask,
        "source_quote_ts_ms": ts,
        "source_quote_sha256": "qsha256",
    }


class RROrderless(unittest.TestCase):
    def test_no_predecision_entry(self):
        self.assertIsNone(r.quote_entry(signal(), quote(100, 100, 999)))
        self.assertIsNotNone(r.quote_entry(signal(), quote(100, 100, 1001)))

    def test_no_unsupported_book_fill(self):
        self.assertIsNone(
            r.quote_entry(signal(), {"state": "HOLD_NO_POST_DECISION_QUOTE"})
        )

    def test_native_long_risk_distance_is_quote_anchored_and_no_real_fill(self):
        p = r.quote_entry(signal(), quote(100, 100, 1001))
        self.assertIsNotNone(p)
        self.assertEqual(p["entry_ask_price"], 100)
        self.assertAlmostEqual(p["base_stop_price"], 99)
        self.assertFalse(p["real_broker_fill"])
        self.assertFalse(p["original_next_open_fill_verified"])

    def test_2r_only_arms_for_subsequent_quote(self):
        p = r.quote_entry(signal(), quote(100, 100, 1001))
        p, terminal = r.sample_position(p, quote(102.2, 102.25, 1100))
        self.assertIsNone(terminal)
        self.assertEqual(p["active_floor_stop_price"], 99)
        self.assertEqual(p["floor_pending_after_ts_ms"], 1100)
        p, terminal = r.sample_position(p, quote(102, 102.1, 1200))
        self.assertIsNone(terminal)
        self.assertEqual(p["active_floor_stop_price"], 100.5)
        self.assertIsNone(p["floor_pending_after_ts_ms"])
        p, terminal = r.sample_position(p, quote(100.4, 100.5, 1300))
        self.assertIsNotNone(terminal)
        self.assertEqual(terminal["reason"], "OBSERVED_BID_TOUCH_STOP")
        self.assertFalse(terminal["real_trade"])

    def test_initial_stop_is_not_weakened(self):
        p = r.quote_entry(signal(), quote(100, 100, 1001))
        p, terminal = r.sample_position(p, quote(98.9, 99, 1200))
        self.assertIsNotNone(terminal)
        self.assertLess(terminal["observational_net_bps_at_40bp"], 0)

    def test_big_winner_is_not_hard_capped(self):
        p = r.quote_entry(signal(), quote(100, 100, 1001))
        p, terminal = r.sample_position(p, quote(117, 117.01, 1200))
        self.assertIsNone(terminal)
        self.assertGreater(p["last_observed_R"], 16)

    def test_no_stale_or_repeated_quote_accounting(self):
        p = r.quote_entry(signal(), quote(100, 100, 1001))
        q = quote(98, 99, 1001)
        p2, term = r.sample_position(p, q)
        self.assertIsNone(term)
        self.assertEqual(p, p2)

    def test_k117_signal_no_last_decision_context_is_ignored(self):
        fake = {
            "order_calls": 0,
            "virtual_fills": 0,
            "formal_shadow": False,
            "signals": [],
        }
        k = {
            "order_calls": 0,
            "virtual_fills": 0,
            "signals": [
                {
                    "status": "SIGNAL",
                    "symbol": "BTC-USDT",
                    "close_ts_ms": 2000,
                    "signal": {"side": 1, "stop_price": 80},
                }
            ],
        }
        self.assertEqual(r.native_events(fake, k), [])
        k["last_complete_30m_close_ms"] = 2000
        k["last_native_decision_ms"] = 2500
        a = r.native_events(fake, k)
        self.assertEqual(len(a), 1)
        self.assertEqual(a[0]["signal_stop_px"], 80)

    def test_4h_frozen_parent_rules_are_only_read(self):
        g = {
            "order_calls": 0,
            "virtual_fills": 0,
            "formal_shadow": False,
            "signals": [
                {
                    "state": "SIGNAL_ONLY_NO_ORDER_NO_FILL",
                    "rule_id": r.GMMA,
                    "symbol": "ETH-USDT",
                    "decision_ts_ms": 2000,
                    "native_stop_distance_reference_bps": 350,
                }
            ],
        }
        k = {"order_calls": 0, "virtual_fills": 0, "signals": []}
        a = r.native_events(g, k)
        self.assertEqual(len(a), 1)
        self.assertEqual(a[0]["max_hold_ms"], 48 * r.FOUR)

    def test_original_observer_orders_forbidden(self):
        g = {"order_calls": 1, "virtual_fills": 0, "formal_shadow": False}
        k = {"order_calls": 0, "virtual_fills": 0}
        with self.assertRaisesRegex(RuntimeError, "AUTHORITY"):
            r.native_events(g, k)

    def test_shadow_status_cannot_claim_orders_or_formal_shadow(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = {"order_calls": 0, "real_broker_fills": 0, "formal_shadow": False}
            r.persist(root, base)
            self.assertTrue((root / "STATUS.json").exists())
            for name, bad in (
                ("order_calls", 1),
                ("real_broker_fills", 1),
                ("formal_shadow", True),
            ):
                with self.assertRaisesRegex(RuntimeError, "AUTHORITY"):
                    r.persist(root, {**base, name: bad})


if __name__ == "__main__":
    unittest.main()
