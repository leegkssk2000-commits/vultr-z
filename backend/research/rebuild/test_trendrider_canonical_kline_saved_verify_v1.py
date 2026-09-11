"""Read-only saved-evidence mutation tests; no acquisition or economic runs."""
import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from backend.research.rebuild import trendrider_canonical_kline_saved_verify_v1 as saved


class CanonicalKlineSavedVerifyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        evidence = saved.ROOT / saved.EVIDENCE
        preexec = json.loads((evidence / "PREEXEC_FREEZE.json").read_bytes())
        preserved = json.loads((evidence / "PRESERVED_FILES.json").read_bytes())["files"]
        self.names = {saved.EVIDENCE + "/" + name for name in saved.REQUIRED_DOCUMENTS}
        self.names.update(preexec["files"])
        self.names.update((saved.TEST_PATH, saved.WORKFLOW_PATH))
        for name in self.names | set(preserved):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(saved.ROOT / name, path)
        self.pin = patch.object(saved, "SAVED_MANIFEST_SHA256", "fixture_pending")
        self.pin.start()
        self.addCleanup(self.pin.stop)
        self.rehash()

    def rehash(self):
        manifest = {"schema": saved.MANIFEST_SCHEMA, "scope_key": saved.SCOPE,
                    "files": {name: saved._sha((self.root / name).read_bytes()) for name in sorted(self.names)}}
        raw = saved._canonical(manifest)
        (self.root / saved.MANIFEST_PATH).write_bytes(raw)
        saved.SAVED_MANIFEST_SHA256 = saved._sha(raw)

    def document(self, name):
        return json.loads((self.root / saved.EVIDENCE / name).read_bytes())

    def write_document(self, name, value):
        if "receipt_sha256" in value:
            value.pop("receipt_sha256")
            value["receipt_sha256"] = saved._sha(saved._canonical(value))
        (self.root / saved.EVIDENCE / name).write_bytes(saved._canonical(value))
        self.rehash()

    def change_response(self, label, change):
        name = "calibration/raw/probe_" + label + ".response.json"
        value = self.document(name)
        change(value)
        self.write_document(name, value)
        receipt = self.document("calibration/CANONICAL_KLINE_TIMESTAMP_RECEIPT.json")
        receipt["raw_responses"][0 if label == "A" else 1] = self.document(name)
        self.write_document("calibration/CANONICAL_KLINE_TIMESTAMP_RECEIPT.json", receipt)

    def verify(self):
        return saved.verify(self.root)

    def test_saved_blocker_verifies_without_replaying_or_normalizing(self):
        result = self.verify()
        self.assertEqual(result["state"], "PASS_SAVED_BLOCKED_CANONICAL_KLINE_SCHEMA_VERIFICATION")
        self.assertEqual(result["diagnostic_rest_probes"], 2)
        self.assertEqual(result["calibration_files"], 10)
        self.assertEqual(result["preserved_files"], 80)
        self.assertEqual(result["source_acquisition_attempts"], 0)
        self.assertEqual(result["economic_runs"], 0)

    def test_manifest_pin_checked_before_any_json_decoding(self):
        (self.root / saved.MANIFEST_PATH).write_bytes(b'{not valid JSON')
        with patch.object(saved, "_json", side_effect=AssertionError("DECODE_BEFORE_HASH")):
            with self.assertRaisesRegex(saved.VerificationError, "SAVED_MANIFEST_SHA_MISMATCH"):
                self.verify()

    def test_changed_saved_raw_fails_file_hash_before_raw_inspection(self):
        path = self.root / saved.EVIDENCE / "calibration/raw/probe_A.bin"
        path.write_bytes(path.read_bytes() + b" ")
        with patch.object(saved, "_raw_timestamp_only", side_effect=AssertionError("RAW_INSPECTION_BEFORE_HASH")):
            with self.assertRaisesRegex(saved.VerificationError, "SAVED_FILE_SHA_MISMATCH"):
                self.verify()

    def test_resealed_wrong_timestamp_still_fails_native_timestamp_gate(self):
        path = self.root / saved.EVIDENCE / "calibration/raw/probe_A.bin"
        changed = path.read_bytes().replace(str(saved.PROBE_T_MS).encode(), str(saved.PROBE_T_MS + saved.HOUR_MS).encode())
        path.write_bytes(changed)
        self.change_response("A", lambda value: value.update(raw_sha256=saved._sha(changed)))
        with self.assertRaisesRegex(saved.VerificationError, "SAVED_RAW_TIMESTAMP_OR_OBJECT_SHAPE"):
            self.verify()

    def test_resealed_wrong_actual_call_count_fails(self):
        name = "calibration/CANONICAL_KLINE_TIMESTAMP_RECEIPT.json"
        value = self.document(name)
        value["actual_http_calls"] = 1
        self.write_document(name, value)
        with self.assertRaisesRegex(saved.VerificationError, "SAVED_CALIBRATION_MUST_REMAIN_BLOCKED"):
            self.verify()

    def test_internal_seal_cannot_be_replaced_by_outer_manifest_hash(self):
        name = "calibration/CANONICAL_KLINE_TIMESTAMP_RECEIPT.json"
        value = self.document(name)
        value["receipt_sha256"] = "0" * 64
        (self.root / saved.EVIDENCE / name).write_bytes(saved._canonical(value))
        self.rehash()
        with self.assertRaisesRegex(saved.VerificationError, "SAVED_INTERNAL_SEAL"):
            self.verify()

    def test_resealed_acquisition_authority_cannot_be_claimed(self):
        name = "calibration/CANONICAL_KLINE_TIMESTAMP_RECEIPT.json"
        value = self.document(name)
        value["acquisition_authorized"] = True
        self.write_document(name, value)
        with self.assertRaisesRegex(saved.VerificationError, "SAVED_CALIBRATION_MUST_REMAIN_BLOCKED"):
            self.verify()

    def test_post_blocker_source_artifact_is_forbidden(self):
        path = self.root / saved.EVIDENCE / "source_data_v3/DATA_FREEZE_V3.json"
        path.parent.mkdir()
        path.write_bytes(b'{}')
        self.names.add(path.relative_to(self.root).as_posix())
        self.rehash()
        with self.assertRaisesRegex(saved.VerificationError, "SAVED_FORBIDDEN_FOLLOWUP_ARTIFACT"):
            self.verify()

    def test_remaining_conditional_budget_does_not_become_actual_execution(self):
        value = self.document("BUDGET_TERMINAL.json")
        value["unused_conditional_budget"] = {"control_runs": 4, "child_FULL_runs": 4}
        self.write_document("BUDGET_TERMINAL.json", value)
        result = self.verify()
        self.assertEqual(result["economic_runs"], 0)
        value["actual"]["control_runs"] = 1
        self.write_document("BUDGET_TERMINAL.json", value)
        with self.assertRaisesRegex(saved.VerificationError, "SAVED_BUDGET_ACTUAL_MUST_BE_TWO_PROBES_ONLY"):
            self.verify()

    def test_preserved_dependency_hash_drift_fails(self):
        path = self.root / saved.PARENT_CONTRACT_PATH
        path.write_bytes(path.read_bytes() + b" ")
        with self.assertRaisesRegex(saved.VerificationError, "SAVED_PRESERVED_FILE_SHA_MISMATCH"):
            self.verify()

    def test_readback_mutation_cannot_replace_frozen_remote_commit(self):
        value = self.document("FREEZE_READBACK.json")
        value["verified_commit_sha"] = "0" * 40
        self.write_document("FREEZE_READBACK.json", value)
        with self.assertRaisesRegex(saved.VerificationError, "SAVED_PREEXEC_REMOTE_READBACK"):
            self.verify()

    def test_resealed_response_timestamp_order_fails(self):
        self.change_response("B", lambda value: value.update(received_at_ms=value["requested_at_ms"] - 1))
        with self.assertRaisesRegex(saved.VerificationError, "SAVED_REQUEST_RESPONSE_TIME_ORDER"):
            self.verify()


if __name__ == "__main__":
    unittest.main()
