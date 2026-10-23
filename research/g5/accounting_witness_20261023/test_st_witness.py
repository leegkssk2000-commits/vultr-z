import unittest
from st_witness import classify_records


class CensoredAndUnknownTest(unittest.TestCase):
    def row(self, index, kind="SIGNAL_CAPTURED", censored=True):
        return {"event_id": str(index) + kind, "campaign_id": str(index),
                "rule_id": "FROZEN", "signal_ts": 100, "entry_ts": 100,
                "kind": kind, "censored": censored, "unknown_exit": False,
                "symbol": "BTC-USDT", "side": "long", "component": "C54_B_DONOR",
                "cost_model_sha256": "COST", "exit_ts": 200}

    def test_six_censored_are_not_zero_open_or_closed(self):
        rows = [self.row(i) for i in range(9)]
        rows += [self.row(i, "LIFECYCLE_FINALIZED", False) for i in range(3)]
        value = classify_records(rows, "squeeze", "FROZEN", 100)
        self.assertEqual(value["stored_finalized_T"], 3)
        self.assertEqual(value["unresolved_censored_T"], 6)
        self.assertEqual(value["unresolved_signal_T"], 6)
        self.assertIsNone(value["actual_open_T"])

    def test_missing_trend_open_is_unknown(self):
        row = self.row(1)
        row["lifecycle_state"] = "SIGNAL_CAPTURED_AWAIT_ECONOMIC_COMPLETION"
        value = classify_records([row], "trend", "FROZEN", 100)
        self.assertIsNone(value["actual_open_T"])
        self.assertIsNone(value["unresolved_censored_T"])
        self.assertEqual(value["stored_finalized_T"], 0)

    def test_identity_mismatch_rejected(self):
        row = self.row(1); row["rule_id"] = "OTHER"
        with self.assertRaisesRegex(ValueError, "RULE_ID_MISMATCH"):
            classify_records([row], "squeeze", "FROZEN", 100)

    def test_censored_cannot_be_finalized(self):
        with self.assertRaisesRegex(ValueError, "CENSORED_OR_UNKNOWN_FINALIZED"):
            classify_records([self.row(1), self.row(1, "LIFECYCLE_FINALIZED")], "squeeze", "FROZEN", 100)

    def test_preboundary_is_not_fresh(self):
        with self.assertRaisesRegex(ValueError, "PRE_BOUNDARY_ROW"):
            classify_records([self.row(1)], "squeeze", "FROZEN", 101)

    def test_signal_and_final_side_mismatch_rejected(self):
        final = self.row(1, "LIFECYCLE_FINALIZED", False); final["side"] = "short"
        with self.assertRaisesRegex(ValueError, "SIGNAL_FINALIZED_IDENTITY_MISMATCH:side"):
            classify_records([self.row(1), final], "squeeze", "FROZEN", 100)


if __name__ == "__main__":
    unittest.main()
