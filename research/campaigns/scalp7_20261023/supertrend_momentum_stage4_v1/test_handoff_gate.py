"""Integrity/authority tests use synthetic receipts, no market input."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from handoff_gate import REQUIRED, inspect_binding


class HandoffGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "INPUT_BINDING.json"
        self.artifact = self.path.parent / "prepared.py"
        self.artifact.write_bytes(b"# synthetic preparation\n")
        self.value = {
            "schema": "zel.supertrend4h.stage4.input_binding.v1",
            "policy_id": "SYNTHETIC_ONLY",
            "market_bindings": dict.fromkeys(REQUIRED),
            "pinned_artifacts": [{"path": self.artifact.name,
                                  "sha256": hashlib.sha256(self.artifact.read_bytes()).hexdigest()}],
        }

    def save(self):
        self.path.write_text(json.dumps(self.value))
        return hashlib.sha256(self.path.read_bytes()).hexdigest()

    def test_missing_market_never_issues_economic_command(self):
        result = inspect_binding(self.path, self.save())
        self.assertEqual(result["first_missing"], REQUIRED[0])
        self.assertEqual(result["eligible_candidate_count"], 0)
        self.assertIsNone(result["economic_command"])
        self.assertEqual(result["economic_runs"], 0)

    def test_changed_binding_or_prepared_code_fails_integrity(self):
        expected = self.save()
        self.path.write_bytes(self.path.read_bytes() + b" ")
        with self.assertRaisesRegex(ValueError, "INPUT_BINDING_SHA_MISMATCH"):
            inspect_binding(self.path, expected)
        expected = self.save()
        self.artifact.write_bytes(b"# changed preparation\n")
        with self.assertRaisesRegex(ValueError, "PREPARED_ARTIFACT_CHANGED"):
            inspect_binding(self.path, expected)

    def test_caller_filled_hashes_do_not_self_grant_owner_authority(self):
        self.value["market_bindings"] = {key: "a" * 64 for key in REQUIRED}
        result = inspect_binding(self.path, self.save())
        self.assertEqual(result["state"], "HOLD_OWNER_SOURCE_REVALIDATION_REQUIRED")
        self.assertFalse(result["source_readiness_granted"])
        self.assertEqual(result["eligible_candidate_count"], 0)
        self.assertIsNone(result["economic_command"])


if __name__ == "__main__":
    unittest.main()
