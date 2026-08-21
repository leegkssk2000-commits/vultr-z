from __future__ import annotations

import copy
import unittest

from backend.research.architecture_factory import a1_external_research_exact8_source_audit_v1 as audit


class Exact8SourceRealityAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.spec = audit.read(audit.DEFAULT_SPEC)
        self.now_ms = 2_000_000_000_000
        self.streams = audit.deterministic_streams(self.now_ms)

    def test_six_candidates_pass_source_only_without_boundary(self) -> None:
        receipt = audit.build_receipt(self.spec, self.streams, now_ms=self.now_ms)
        self.assertEqual(receipt["source_ready_candidate_count"], 6)
        self.assertEqual(receipt["stream_count"], 4)
        self.assertFalse(receipt["fresh_boundary_assigned"])
        self.assertFalse(receipt["boundary_assignment_authority"])
        self.assertFalse(receipt["replay_performed"])
        self.assertEqual(receipt["effect_verified_count"], 0)

    def test_duplicate_and_gap_fail_closed(self) -> None:
        streams = copy.deepcopy(self.streams)
        key = ("BTC-USDT", 300_000)
        streams[key].append(copy.deepcopy(streams[key][-1]))
        receipt = audit.build_receipt(self.spec, streams, now_ms=self.now_ms)
        row = next(x for x in receipt["stream_rows"] if x["symbol"] == key[0] and x["timeframe_ms"] == key[1])
        self.assertIn("DUPLICATE_TIMESTAMP", row["blockers"])

        streams = copy.deepcopy(self.streams)
        del streams[key][50]
        receipt = audit.build_receipt(self.spec, streams, now_ms=self.now_ms)
        row = next(x for x in receipt["stream_rows"] if x["symbol"] == key[0] and x["timeframe_ms"] == key[1])
        self.assertIn("INTERVAL_DISCONTINUITY", row["blockers"])

    def test_bad_ohlc_and_zero_volume_fail_closed(self) -> None:
        streams = copy.deepcopy(self.streams)
        key = ("ETH-USDT", 3_600_000)
        streams[key][-2]["high"] = streams[key][-2]["low"] - 1
        streams[key][-3]["volume"] = 0
        receipt = audit.build_receipt(self.spec, streams, now_ms=self.now_ms)
        row = next(x for x in receipt["stream_rows"] if x["symbol"] == key[0] and x["timeframe_ms"] == key[1])
        self.assertIn("OHLC_INTEGRITY_FAILURE", row["blockers"])
        self.assertIn("NONPOSITIVE_VOLUME", row["blockers"])

    def test_in_progress_bar_is_excluded(self) -> None:
        streams = copy.deepcopy(self.streams)
        key = ("BTC-USDT", 300_000)
        streams[key].append(
            {
                "time": self.now_ms - 1,
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.5,
                "volume": 12.0,
            }
        )
        receipt = audit.build_receipt(self.spec, streams, now_ms=self.now_ms)
        row = next(x for x in receipt["stream_rows"] if x["symbol"] == key[0] and x["timeframe_ms"] == key[1])
        self.assertEqual(row["in_progress_bar_count_excluded"], 1)
        self.assertEqual(row["state"], "PASS_SOURCE_STREAM_INTEGRITY")

    def test_authority_remains_blocked(self) -> None:
        receipt = audit.build_receipt(self.spec, self.streams, now_ms=self.now_ms)
        self.assertFalse(receipt["selection_authority"])
        self.assertFalse(receipt["promotion_authority"])
        self.assertEqual(receipt["execution_authority"], "NONE")
        self.assertEqual(receipt["order_authority"], "BLOCKED")
        self.assertEqual(receipt["live_trade_authority"], "BLOCKED")
        self.assertFalse(receipt["threshold_search"])
        self.assertFalse(receipt["holdout_outcomes_accessed"])
        self.assertFalse(receipt["synthetic_market_evidence_used"])


if __name__ == "__main__":
    unittest.main()
