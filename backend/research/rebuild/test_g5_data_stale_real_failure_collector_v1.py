from __future__ import annotations

import unittest

from backend.research.rebuild import g5_data_stale_real_failure_collector_v1 as collector


class RealFailureCollectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = {
            "source": {
                "source_id": "bingx_usdtm_public_klines",
                "interval_ms": 14_400_000,
                "symbols": ["BTC-USDT"],
            },
            "active_strategies": [
                {"strategy_id": "keltner_trend", "child_id": "keltner_range_owner_v1"},
            ],
        }

    def row(self, bar_close_ts: int, evaluation_age_ms: int = 5_000_000) -> dict:
        received = bar_close_ts + max(1, evaluation_age_ms - 1000)
        fire = bar_close_ts + max(1, evaluation_age_ms - 500)
        start = bar_close_ts + evaluation_age_ms - 5
        end = bar_close_ts + evaluation_age_ms
        return {
            "status": "EVALUATED",
            "payload": {
                "strategy_id": "keltner_trend",
                "child_id": "keltner_range_owner_v1",
                "symbol": "BTC-USDT",
                "source_id": "bingx_usdtm_public_klines",
                "closed_bar": True,
                "evaluated": True,
                "source_seen": True,
                "correct_child": True,
                "duplicate": 0,
                "lookahead": 0,
                "formal_credit": 0,
                "signal_bar_close_ts": bar_close_ts,
                "evaluation_key": f"keltner_trend|keltner_range_owner_v1|BTC-USDT|{bar_close_ts}",
                "telemetry": {
                    "source_event_ts": bar_close_ts,
                    "source_received_ts": received,
                    "bar_close_ts": bar_close_ts,
                    "scheduler_fire_ts": fire,
                    "evaluation_start_ts": start,
                    "evaluation_end_ts": end,
                    "writer_ts": end,
                    "evaluation_age_ms": evaluation_age_ms,
                    "source_lag_ms": received - bar_close_ts,
                    "scheduler_lag_ms": fire - bar_close_ts,
                    "evaluation_duration_ms": 5,
                },
            },
        }

    def test_no_real_failure_keeps_collection_active(self) -> None:
        base = 1_800_000_000_000
        rows = [self.row(base + i * 14_400_000) for i in range(3)]
        result = collector.collect_real_failures(self.contract, rows)
        self.assertEqual(result["state"], "REAL_FAILURE_COLLECTION_ACTIVE_NO_EVENTS")
        self.assertEqual(result["evaluated_N"], 3)
        self.assertEqual(result["real_failure_N"], 0)
        self.assertEqual(result["threshold_eligible_failure_N"], 0)
        self.assertIsNone(result["authority_value"])
        self.assertEqual(result["fresh_credit"], 0)

    def test_late_evaluation_is_real_threshold_eligible_failure(self) -> None:
        base = 1_800_000_000_000
        rows = [
            self.row(base),
            self.row(base + 14_400_000, 14_400_001),
            self.row(base + 28_800_000),
        ]
        result = collector.collect_real_failures(self.contract, rows)
        self.assertEqual(result["state"], "REAL_FAILURE_EVIDENCE_AVAILABLE")
        self.assertEqual(result["real_failure_N"], 1)
        self.assertEqual(result["threshold_eligible_failure_N"], 1)
        event = result["events"][0]
        self.assertEqual(event["event_type"], "LATE_EVALUATION")
        self.assertTrue(event["observed_not_synthetic"])
        self.assertTrue(event["threshold_eligible"])

    def test_gap_is_real_incident_but_not_threshold_eligible(self) -> None:
        base = 1_800_000_000_000
        rows = [self.row(base), self.row(base + 28_800_000)]
        result = collector.collect_real_failures(self.contract, rows)
        self.assertEqual(result["state"], "REAL_FAILURE_INCIDENT_OBSERVED_NO_THRESHOLD_TELEMETRY")
        self.assertEqual(result["real_failure_N"], 1)
        self.assertEqual(result["threshold_eligible_failure_N"], 0)
        self.assertEqual(result["missing_evaluation_gap_N"], 1)
        self.assertEqual(result["events"][0]["event_type"], "MISSING_EVALUATION_GAP")

    def test_timestamp_inversion_fails_closed(self) -> None:
        row = self.row(1_800_000_000_000)
        row["payload"]["telemetry"]["writer_ts"] = row["payload"]["telemetry"]["evaluation_end_ts"] - 1
        with self.assertRaisesRegex(collector.FailureEvidenceError, "WRITER_TIMESTAMP_INVERSION"):
            collector.collect_real_failures(self.contract, [row])


if __name__ == "__main__":
    unittest.main()
