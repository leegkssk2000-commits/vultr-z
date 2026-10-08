"""Artificial Hansen execution fixtures only; no historical archive loading."""
from __future__ import annotations

import copy
import unittest

from ops import issue1388_hansen_execution_v1 as draft

H = draft.HOUR


def bars(count: int = 8, *, segment: str = "A"):
    return [{"open_ts_ms": i * H, "close_ts_ms": (i + 1) * H,
             "available_ts_ms": (i + 1) * H, "segment_id": segment,
             "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0}
            for i in range(count)]


def run(data, entries=(0,), exits=(), *, funding=(), end=None):
    decisions = draft.bind_hansen_decisions(
        data, [i in entries for i in range(len(data))],
        [i in exits for i in range(len(data))])
    return draft.replay_hansen(
        "ETH-USDT", data, decisions, funding, start_ms=0,
        end_ms=len(data) * H if end is None else end, roundtrip_cost_bps=14.0)


class HansenExecutionFixtures(unittest.TestCase):
    def test_completed_signal_uses_first_causal_open(self):
        data = bars()
        data[0]["available_ts_ms"] = 2 * H + 1
        value = run(data)
        self.assertEqual(value["open_position"]["entry_ts_ms"], 3 * H)
        self.assertEqual(value["open_entry_cost_bps"], 7.0)

    def test_source_exit_uses_next_open_and_stop_has_open_priority(self):
        data = bars()
        data[2].update(open=95.0, high=96.0, low=94.0, close=95.0)
        value = run(data, exits=(1,))
        self.assertEqual(value["trades"][0]["exit_reason"], "NEXT_AVAILABLE_OPEN_HANSEN_EXIT")
        self.assertEqual(value["trades"][0]["exit_price"], 95.0)
        data[2].update(open=85.0, high=96.0, low=84.0, close=90.0)
        self.assertEqual(run(data, exits=(1,))["trades"][0]["exit_reason"], "OPEN_STOP")

    def test_source_roi_is_eleven_times_entry_not_disabled_or_ten_percent(self):
        data = bars()
        data[2].update(high=1099.0)
        self.assertEqual(run(data)["trades"], [])
        data[2].update(high=1100.0)
        trade = run(data)["trades"][0]
        self.assertEqual(trade["exit_reason"], "INTRABAR_ROI")
        self.assertEqual(trade["exit_price"], 1100.0)
        self.assertAlmostEqual(trade["gross_bps"], 100000.0)

    def test_ambiguous_intrabar_is_stop_first_at_ten_percent(self):
        data = bars()
        data[2].update(low=80.0, high=1200.0)
        trade = run(data)["trades"][0]
        self.assertEqual((trade["exit_reason"], trade["exit_price"]), ("INTRABAR_STOP_FIRST", 90.0))

    def test_gap_with_position_and_terminal_touch_are_blocked(self):
        data = bars()
        del data[3]
        value = run(data, end=8 * H)
        self.assertEqual(value["disposition"], "BLOCKED_SOURCE_GAP")
        self.assertIsNotNone(value["gap_quarantine"])
        data = bars()
        data[-1].update(low=80.0)
        value = run(data)
        self.assertEqual(value["disposition"], "BLOCKED_TERMINAL_UNRESOLVED")
        self.assertEqual(value["terminal_protective_touch"]["reason"], "INTRABAR_STOP_FIRST")

    def test_signed_funding_and_paid_fee_reconcile(self):
        data = bars()
        funding = [{"symbol": "ETH-USDT", "fundingTime": stamp,
                    "fundingRate": rate, "markPrice": 100.0}
                   for stamp, rate in ((H, -0.001), (2 * H, -0.002), (4 * H, 0.003))]
        value = run(data, exits=(3,), funding=funding)
        trade = value["trades"][0]
        self.assertAlmostEqual(trade["funding_bps"], 10.0)
        self.assertEqual(value["paid_trading_cost_bps"], 14.0)
        self.assertEqual(value["closed_trading_cost_bps"], 14.0)

    def test_decision_and_funding_tamper_fail_closed(self):
        data = bars()
        with self.assertRaises(draft.DraftError):
            draft.bind_hansen_decisions(data, [True] * len(data), [True] * len(data))
        bound = draft.bind_hansen_decisions(data, [True] + [False] * 7, [False] * 8)
        bound[0]["signal_available_ts_ms"] = 0
        with self.assertRaises(draft.DraftError):
            draft.replay_hansen("ETH-USDT", data, bound, [], start_ms=0, end_ms=8 * H,
                                roundtrip_cost_bps=14.0)
        bad = [{"symbol": "BTC-USDT", "fundingTime": H, "fundingRate": 0, "markPrice": 100}]
        with self.assertRaises(draft.DraftError):
            run(data, funding=copy.deepcopy(bad))


if __name__ == "__main__":
    unittest.main()
