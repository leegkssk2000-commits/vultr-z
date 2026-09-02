from __future__ import annotations

import unittest

from backend.research.rebuild import g5_data_stale_evidence_v1 as evidence


class DataStaleEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = {
            "source": {
                "interval_ms": 14_400_000,
                "symbols": ["BTC-USDT", "ETH-USDT"],
            },
            "active_strategies": [
                {"strategy_id": "keltner_trend", "child_id": "keltner_range_owner_v1"},
                {"strategy_id": "supertrend_pullback", "child_id": "supertrend_child"},
                {"strategy_id": "break_and_continue", "child_id": "break_child"},
            ],
        }
        self.bar_ts = [1_800_000_000_000, 1_800_014_400_000, 1_800_028_800_000]
        from datetime import datetime, timezone
        def iso(ms: int) -> str:
            return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).isoformat().replace("+00:00", "Z")
        self.shadow = {
            "state": "CLEAN_RUNNER_SHADOW_PASS",
            "shadow_3bar_pass": True,
            "complete_bar_count": 3,
            "consecutive_complete_bar_count": 3,
            "source_parity": True,
            "child_parity": True,
            "duplicate": 0,
            "lookahead": 0,
            "formal_credit": 0,
            "bar1": iso(self.bar_ts[0]),
            "bar2": iso(self.bar_ts[1]),
            "bar3": iso(self.bar_ts[2]),
        }
        self.rows = []
        strategies = {row["strategy_id"]: row["child_id"] for row in self.contract["active_strategies"]}
        for bar in self.bar_ts:
            for symbol in self.contract["source"]["symbols"]:
                for strategy_id, child_id in strategies.items():
                    base = bar + 5_000_000
                    self.rows.append({
                        "status": "EVALUATED",
                        "payload": {
                            "strategy_id": strategy_id,
                            "child_id": child_id,
                            "symbol": symbol,
                            "closed_bar": True,
                            "evaluated": True,
                            "source_seen": True,
                            "correct_child": True,
                            "duplicate": 0,
                            "lookahead": 0,
                            "signal_bar_close_ts": bar,
                            "evaluation_key": f"{strategy_id}|{child_id}|{symbol}|{bar}",
                            "telemetry": {
                                "source_event_ts": bar,
                                "source_received_ts": base,
                                "bar_close_ts": bar,
                                "scheduler_fire_ts": base - 10_000,
                                "evaluation_start_ts": base + 1,
                                "evaluation_end_ts": base + 4,
                                "writer_ts": base + 4,
                                "evaluation_age_ms": 5_000_004,
                                "source_lag_ms": 5_000_000,
                                "scheduler_lag_ms": 4_990_000,
                                "evaluation_duration_ms": 3,
                            },
                        },
                    })

    def test_three_bar_normal_evidence_stays_fail_closed(self) -> None:
        result = evidence.build_evidence(self.contract, self.shadow, self.rows)
        self.assertEqual(result["state"], "AUTHORITY_EVIDENCE_PARTIAL_SYNTHETIC_ONLY")
        self.assertEqual(result["normal_N"], 18)
        self.assertEqual(result["real_failure_N"], 0)
        self.assertEqual(result["synthetic_failure_N"], 18)
        self.assertIsNone(result["authority_value"])
        self.assertFalse(result["authority_created"])
        self.assertFalse(result["ssot_mutated"])
        self.assertEqual(result["fresh_credit"], 0)
        self.assertFalse(result["threshold_surface_allowed"])
        self.assertEqual(result["first_blocker"], "REAL_LABELED_FAILURE_MISSING")

    def test_shadow_pass_is_required(self) -> None:
        bad = dict(self.shadow)
        bad["shadow_3bar_pass"] = False
        with self.assertRaisesRegex(evidence.EvidenceError, "SHADOW_3BAR_PASS_REQUIRED"):
            evidence.build_evidence(self.contract, bad, self.rows)

    def test_duplicate_evaluation_key_fails(self) -> None:
        rows = list(self.rows) + [self.rows[0]]
        with self.assertRaises(evidence.EvidenceError):
            evidence.build_evidence(self.contract, self.shadow, rows)

    def test_missing_telemetry_fails(self) -> None:
        rows = [dict(row) for row in self.rows]
        rows[0] = dict(rows[0])
        rows[0]["payload"] = dict(rows[0]["payload"])
        rows[0]["payload"]["telemetry"] = dict(rows[0]["payload"]["telemetry"])
        rows[0]["payload"]["telemetry"].pop("writer_ts")
        with self.assertRaisesRegex(evidence.EvidenceError, "TELEMETRY_FIELDS_MISSING"):
            evidence.build_evidence(self.contract, self.shadow, rows)

    def test_child_identity_drift_fails(self) -> None:
        rows = [dict(row) for row in self.rows]
        rows[0] = dict(rows[0])
        rows[0]["payload"] = dict(rows[0]["payload"])
        rows[0]["payload"]["child_id"] = "wrong-child"
        with self.assertRaisesRegex(evidence.EvidenceError, "CHILD_IDENTITY_DRIFT"):
            evidence.build_evidence(self.contract, self.shadow, rows)


if __name__ == "__main__":
    unittest.main()
