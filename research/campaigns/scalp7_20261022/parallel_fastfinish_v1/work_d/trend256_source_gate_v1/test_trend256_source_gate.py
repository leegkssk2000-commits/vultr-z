import json
import shutil
import tempfile
import unittest
from pathlib import Path

import trend256_source_gate as gate


class SourceGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parent
        cls.receipt = cls.root / "inputs/long_only_prospective.json"
        cls.archive = cls.root / "inputs/long256.zip"
        cls.result = gate.run(cls.receipt, cls.archive, cls.root)

    def test_seven_original_files_have_hashes_not_feature_preimages(self):
        r = self.result
        self.assertEqual(len(r["archive_inventory"]), 7)
        self.assertEqual(sum(x["native_feature_bodies"] for x in r["archive_inventory"]), 0)
        self.assertEqual(sum(x["ohlc_objects"] for x in r["archive_inventory"]), 0)
        self.assertEqual(r["row_audit"]["rows_with_feature_hash"], 256)

    def test_failure_is_executable_terminal_not_candidate_or_economic_pass(self):
        r = self.result
        self.assertEqual((r["state"], r["first_blocker"]), ("NO_CAUSAL_CHILD", "SOURCE_FEATURE_BLOCKED"))
        self.assertIsNone(r["child_adapter"])
        self.assertIsNone(r["changed_axis"])
        self.assertEqual(r["new_candidate_count"], 0)
        self.assertIsNone(r["row_audit"]["recovery_winner_count"])
        self.assertEqual(r["preservation"]["rows_deleted"], 0)
        self.assertEqual(r["preservation"]["rows_repriced"], 0)

    def test_exact_four_delayed_entries_below_original_stop_are_retained(self):
        rows = self.result["row_audit"]["entry_below_sealed_stop"]
        self.assertEqual(len(rows), 4)
        self.assertEqual({r["symbol"] for r in rows}, {"APE-USDT", "HYPE-USDT", "1000PEPE-USDT"})
        self.assertTrue(all(r["entry"] < r["sealed_sl"] == r["saved_exit"] for r in rows))

    def test_inherited_parent_ownership_is_not_child_opportunity_count(self):
        r = self.result["row_audit"]
        self.assertEqual((r["inherited_parent_open_intents"], r["inherited_parent_rejected_intents"]), (1, 1889))
        self.assertFalse(r["child_opportunity_chronology_complete"])
        self.assertIsNone(self.result["independent_opportunities"])

    def test_feature_shape_scan_detects_nested_counterexample(self):
        fake = {"trades": [{"nested": {"open": 1, "high": 2, "low": 0, "close": 1}}],
                "snapshot": {"strategy_id": "trend_rider", "symbol": "BTC-USDT", "signal_ts": 1,
                             "close": 1, "atr": 1, "values": {"chase_atr": 1}, "available_ts_ms": 2}}
        self.assertEqual(gate.content_inventory(fake)["ohlc_objects"], 1)
        self.assertEqual(gate.content_inventory(fake)["native_feature_bodies"], 1)
        self.assertEqual(gate.content_inventory(fake)["explicit_available_timestamps"], 1)

    def test_appended_feature_or_outcome_cannot_bypass_archive_binding(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "forged.json"
            receipt = json.loads(self.receipt.read_text())
            receipt["trades"][0]["feature_values"] = {"MFE": 999, "month": "October"}
            path.write_text(json.dumps(receipt))
            with self.assertRaisesRegex(ValueError, "RAW_FILE_IDENTITY_MISMATCH"):
                gate.run(path, self.archive, self.root)

    def test_changed_artifact_or_native_source_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "bad.zip").write_bytes(self.archive.read_bytes() + b" ")
            with self.assertRaisesRegex(ValueError, "ORIGINAL_ARTIFACT_CHANGED"):
                gate.inspect_archive(root / "bad.zip", self.receipt)
            shutil.copyfile(self.root / "SOURCE_BINDINGS.json", root / "SOURCE_BINDINGS.json")
            shutil.copytree(self.root / "frozen_source", root / "frozen_source")
            native = root / "frozen_source/trend_policy_batch_v1.py"
            native.write_bytes(native.read_bytes() + b"\n")
            with self.assertRaisesRegex(ValueError, "NATIVE_SOURCE_CHANGED"):
                gate.verify_sources(root)


if __name__ == "__main__":
    unittest.main()
