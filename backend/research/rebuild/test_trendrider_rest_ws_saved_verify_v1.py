"""Mutate copies of saved evidence only; no acquisition or executor repair."""
import copy
import gzip
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from backend.research.rebuild import trendrider_rest_ws_saved_verify_v1 as saved


class RestWSSavedVerifyTests(unittest.TestCase):
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

    def refresh_calibration_binding(self):
        name = "calibration/REST_WS_TIMESTAMP_SEMANTIC_RECEIPT.json"
        receipt = self.document(name)
        receipt["artifact_sha256"] = {entry: saved._sha((self.root / saved.EVIDENCE / "calibration" / entry).read_bytes())
                                      for entry in receipt["artifact_sha256"]}
        self.write_document(name, receipt)
        digest = saved._sha((self.root / saved.EVIDENCE / name).read_bytes())
        budget = self.document("BUDGET_TERMINAL.json")
        budget["semantic_receipt_sha256"] = digest
        self.write_document("BUDGET_TERMINAL.json", budget)
        postmortem = self.document("ACK_POSTMORTEM.json")
        postmortem["actual_observation"]["semantic_receipt_sha256"] = digest
        self.write_document("ACK_POSTMORTEM.json", postmortem)

    def verify(self):
        return saved.verify(self.root)

    def test_actual_ack_implementation_failure_verifies_without_live_executor(self):
        result = self.verify()
        self.assertEqual(result["failure_class"], "IMPLEMENTATION_ACK_CLASSIFICATION_FAILURE")
        self.assertEqual(result["ws_sessions"], 1)
        self.assertEqual(result["ack_frames"], 1)
        self.assertEqual(result["kline_frames"], 0)
        self.assertEqual(result["diagnostic_rest_requests"], 0)
        self.assertEqual(result["source_acquisition_attempts"], 0)
        self.assertEqual(result["economic_runs"], 0)
        self.assertEqual(result["preserved_files"], 108)
        self.assertEqual(result["preexec_files"], 15)
        self.assertEqual(result["calibration_files"], 9)

    def test_manifest_pin_checked_before_any_json_decoding(self):
        (self.root / saved.MANIFEST_PATH).write_bytes(b'{not valid JSON')
        with patch.object(saved, "_json", side_effect=AssertionError("DECODE_BEFORE_HASH")):
            with self.assertRaisesRegex(saved.VerificationError, "SAVED_MANIFEST_SHA_MISMATCH"):
                self.verify()

    def test_saved_raw_hash_checked_before_gzip_or_ack_inspection(self):
        path = self.root / saved.EVIDENCE / "calibration/raw/ws_0001.bin"
        path.write_bytes(path.read_bytes() + b" ")
        with patch.object(saved, "_classify_stored_ack", side_effect=AssertionError("DECODE_BEFORE_HASH")):
            with self.assertRaisesRegex(saved.VerificationError, "SAVED_FILE_SHA_MISMATCH"):
                self.verify()

    def test_ack_control_classifier_does_not_swallow_failure_or_market_frame(self):
        cases = ({"code": True}, {"code": 1}, {"code": "0"}, {"id": "OTHER"},
                 {"dataType": saved.CHANNEL}, {"data": {"K": {"t": 1, "T": 2}}})
        raw = (self.root / saved.EVIDENCE / "calibration/raw/ws_0001.bin").read_bytes()
        self.assertEqual(saved._classify_stored_ack(raw), saved.EXPECTED_ACK)
        for update in cases:
            message = {**saved.EXPECTED_ACK, **update}
            with self.subTest(update=update), self.assertRaisesRegex(saved.VerificationError, "SAVED_EXACT_SUBSCRIPTION_SUCCESS_ACK_REQUIRED"):
                saved._classify_stored_ack(gzip.compress(saved._canonical(message)))

    def test_gzip_raw_decompression_and_duplicate_json_keys_are_bounded(self):
        for raw, expected in ((b"broken", "SAVED_ACK_GZIP"),
                              (gzip.compress(b" " * 4097), "SAVED_ACK_DECOMPRESSED_LIMIT"),
                              (b"x" * 4097, "SAVED_ACK_RAW_LIMIT"),
                              (gzip.compress(b'{"code":0,"code":1}'), "SAVED_JSON_DUPLICATE_KEY")):
            with self.subTest(expected=expected), self.assertRaisesRegex(saved.VerificationError, expected):
                saved._classify_stored_ack(raw)

    def test_resealed_count_cannot_claim_unobserved_rest_or_kline(self):
        name = "calibration/REST_WS_TIMESTAMP_SEMANTIC_RECEIPT.json"
        value = self.document(name)
        value["actual_rest_requests"] = 1
        value["counts"]["rest_requests"] = 1
        self.write_document(name, value)
        with self.assertRaisesRegex(saved.VerificationError, "SAVED_CALIBRATION_MUST_REMAIN_IMPLEMENTATION_BLOCKED"):
            self.verify()

    def test_resealed_receipt_cannot_invent_semantic_pass_or_source_authority(self):
        name = "calibration/REST_WS_TIMESTAMP_SEMANTIC_RECEIPT.json"
        original = self.document(name)
        for update in ({"state": "PASS"}, {"source_acquisition_authorized": True},
                       {"witness": {"ohlc_exact_match": True}}, {"supported_canonical_lane": "OBJECT_TIME_OPEN"}):
            value = {**copy.deepcopy(original), **update}
            self.write_document(name, value)
            with self.subTest(update=update), self.assertRaisesRegex(saved.VerificationError, "SAVED_CALIBRATION_MUST_REMAIN_IMPLEMENTATION_BLOCKED"):
                self.verify()

    def test_outer_manifest_reseal_does_not_replace_internal_receipt_seal(self):
        name = "calibration/REST_WS_TIMESTAMP_SEMANTIC_RECEIPT.json"
        value = self.document(name)
        value["receipt_sha256"] = "0" * 64
        (self.root / saved.EVIDENCE / name).write_bytes(saved._canonical(value))
        self.rehash()
        with self.assertRaisesRegex(saved.VerificationError, "SAVED_INTERNAL_SEAL"):
            self.verify()

    def test_added_rest_response_and_source_authorization_are_forbidden(self):
        for name in ("calibration/raw/rest_0001.bin", "source_data/DATA_FREEZE_V4.json",
                     "SOURCE_AUTHORIZATION_V4.json"):
            path = self.root / saved.EVIDENCE / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'{}')
            self.names.add(path.relative_to(self.root).as_posix())
            self.rehash()
            with self.subTest(name=name), self.assertRaisesRegex(saved.VerificationError, "SAVED_CALIBRATION_EXACT_NINE_FILES|SAVED_FORBIDDEN_FOLLOWUP_ARTIFACT"):
                self.verify()
            self.names.remove(path.relative_to(self.root).as_posix())
            path.unlink()
            if path.parent.name == "source_data":
                path.parent.rmdir()
            self.rehash()

    def test_postmortem_cannot_misclassify_ack_as_exchange_schema_failure(self):
        value = self.document("ACK_POSTMORTEM.json")
        value["classification"] = "EXCHANGE_KLINE_SCHEMA_FAILURE"
        self.write_document("ACK_POSTMORTEM.json", value)
        with self.assertRaisesRegex(saved.VerificationError, "SAVED_POSTMORTEM_MUST_IDENTIFY_LOCAL_ACK_DEFECT"):
            self.verify()

    def test_not_run_metrics_cannot_be_filled_with_fabricated_economics(self):
        value = self.document("BUDGET_TERMINAL.json")
        value["economic_metrics"]["DEV_A"]["U1"] = {"status": "PASS", "metrics": {"net": 1}}
        self.write_document("BUDGET_TERMINAL.json", value)
        with self.assertRaisesRegex(saved.VerificationError, "SAVED_ECONOMICS_MUST_BE_NOT_RUN"):
            self.verify()

    def test_unused_conditional_budget_never_becomes_actual_execution(self):
        value = self.document("BUDGET_TERMINAL.json")
        value["unused_conditional_budget"] = {"control_runs": 4, "child_FULL_runs": 4}
        self.write_document("BUDGET_TERMINAL.json", value)
        self.assertEqual(self.verify()["economic_runs"], 0)
        value["actual"]["control_runs"] = 1
        self.write_document("BUDGET_TERMINAL.json", value)
        with self.assertRaisesRegex(saved.VerificationError, "SAVED_BUDGET_ONE_WS_ACK_ZERO_REST_SOURCE_ECONOMICS"):
            self.verify()

    def test_no_economic_reject_handoff_or_successor_can_be_claimed(self):
        original = self.document("BUDGET_TERMINAL.json")
        for update in ({"economic_reject": True}, {"prospective_G5A_handoff": 1},
                       {"automatic_successor": True}, {"failure_class": "ECONOMIC_FAILURE"}):
            self.write_document("BUDGET_TERMINAL.json", {**copy.deepcopy(original), **update})
            with self.subTest(update=update), self.assertRaisesRegex(saved.VerificationError, "SAVED_FAILURE_CLASS_CREDIT_OR_CLOSURE"):
                self.verify()

    def test_preserved_dependency_drift_and_postoutcome_executor_patch_fail(self):
        path = self.root / saved.PARENT_CONTRACT_PATH
        original = path.read_bytes()
        path.write_bytes(original + b" ")
        with self.assertRaisesRegex(saved.VerificationError, "SAVED_PRESERVED_FILE_SHA_MISMATCH"):
            self.verify()
        path.write_bytes(original)
        path = self.root / saved.FROZEN_EXECUTOR_PATH
        path.write_bytes(path.read_bytes() + b"\n# forbidden post-outcome repair\n")
        self.rehash()
        with self.assertRaisesRegex(saved.VerificationError, "SAVED_PREEXEC_FILE_BINDING"):
            self.verify()

    def test_remote_readback_and_session_event_order_remain_binding(self):
        value = self.document("FREEZE_READBACK.json")
        original = copy.deepcopy(value)
        value["verified_commit_sha"] = "0" * 40
        self.write_document("FREEZE_READBACK.json", value)
        with self.assertRaisesRegex(saved.VerificationError, "SAVED_PREEXEC_REMOTE_READBACK"):
            self.verify()
        self.write_document("FREEZE_READBACK.json", original)
        name = "calibration/raw/ws_0001.meta.json"
        value = self.document(name)
        value["received_at_ms"] = 0
        self.write_document(name, value)
        self.refresh_calibration_binding()
        with self.assertRaisesRegex(saved.VerificationError, "SAVED_SESSION_EVENT_TIME_ORDER"):
            self.verify()

    def test_path_escape_and_symlink_are_rejected(self):
        for relative in ("../outside", "/outside", "a/../b", "a\\b", "C:/file"):
            with self.subTest(relative=relative), self.assertRaises(saved.VerificationError):
                saved._path(self.root, relative)
        path = self.root / saved.EVIDENCE / "calibration/raw/ws_0001.bin"
        original = path.read_bytes()
        outside = self.root / "outside.bin"
        outside.write_bytes(original)
        path.unlink()
        path.symlink_to(outside)
        with self.assertRaisesRegex(saved.VerificationError, "SAVED_SYMLINK_FORBIDDEN"):
            self.verify()


if __name__ == "__main__":
    unittest.main()
