"""Mutate copies of saved evidence only; no acquisition or executor repair."""
import ast
import copy
import gzip
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from backend.research.rebuild import trendrider_ack_saved_verify_v1 as saved


class AckSavedVerifyTests(unittest.TestCase):
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
        name = "calibration/REST_WS_TIMESTAMP_SEMANTIC_RECEIPT_V2.json"
        receipt = self.document(name)
        receipt["artifact_sha256"] = {entry: saved._sha((self.root / saved.EVIDENCE / "calibration" / entry).read_bytes())
                                      for entry in receipt["artifact_sha256"]}
        self.write_document(name, receipt)
        digest = saved._sha((self.root / saved.EVIDENCE / name).read_bytes())
        budget = self.document("BUDGET_TERMINAL.json")
        budget["semantic_receipt_sha256"] = digest
        self.write_document("BUDGET_TERMINAL.json", budget)

    def verify(self):
        return saved.verify(self.root)

    def test_actual_saved_two_frames_and_zero_downstream(self):
        result = self.verify()
        self.assertEqual(result["failure_class"], "WS_KLINE_SCHEMA_CONTRACT_MISMATCH")
        self.assertEqual([result[k] for k in ("ws_sessions", "ack_frames", "kline_channel_frames")], [1, 1, 1])
        self.assertEqual([result[k] for k in ("accepted_kline_frames", "diagnostic_rest_requests",
                                            "source_acquisition_attempts", "economic_runs")], [0, 0, 0, 0])
        self.assertEqual([result[k] for k in ("preserved_files", "preexec_files", "calibration_files")], [149, 23, 12])

    def test_manifest_hash_checked_before_json(self):
        (self.root / saved.MANIFEST_PATH).write_bytes(b"not JSON")
        with patch.object(saved, "_json", side_effect=AssertionError("premature JSON")):
            with self.assertRaisesRegex(saved.VerificationError, "SAVED_MANIFEST_SHA_MISMATCH"):
                self.verify()

    def test_both_raw_frames_hashed_before_inspection(self):
        for ordinal in (1, 2):
            path = self.root / saved.EVIDENCE / f"calibration/raw/ws_{ordinal:04d}.bin"
            original = path.read_bytes()
            path.write_bytes(original + b" ")
            with self.subTest(ordinal=ordinal), patch.object(saved, "_classify_stored_ack", side_effect=AssertionError("premature decode")):
                with self.assertRaisesRegex(saved.VerificationError, "SAVED_FILE_SHA_MISMATCH"):
                    self.verify()
            path.write_bytes(original)

    def test_missing_or_unexpected_scope_artifact_rejected(self):
        path = self.root / saved.EVIDENCE / "REPORT_KO.md"
        original = path.read_bytes()
        path.unlink()
        with self.assertRaisesRegex(saved.VerificationError, "SAVED_FILE_MISSING"):
            self.verify()
        path.write_bytes(original)
        extra = self.root / saved.EVIDENCE / "unregistered.json"
        extra.write_bytes(b"{}")
        with self.assertRaisesRegex(saved.VerificationError, "SAVED_UNMANIFESTED_SCOPE_FILE"):
            self.verify()

    def test_manifested_extra_rest_or_source_still_forbidden(self):
        for relative in ("calibration/raw/rest_1.bin", "source_data/DATA_FREEZE_V5.json"):
            path = self.root / saved.EVIDENCE / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"{}")
            name = path.relative_to(self.root).as_posix()
            self.names.add(name)
            self.rehash()
            with self.subTest(relative=relative), self.assertRaisesRegex(saved.VerificationError,
                    "SAVED_CALIBRATION_EXACT_TWELVE_FILES|SAVED_FORBIDDEN_FOLLOWUP_ARTIFACT"):
                self.verify()
            self.names.remove(name)
            path.unlink()
            if path.parent.name == "source_data":
                path.parent.rmdir()
            self.rehash()

    def test_resealed_false_semantic_pass_or_budget_fails(self):
        name = "calibration/REST_WS_TIMESTAMP_SEMANTIC_RECEIPT_V2.json"
        original = self.document(name)
        for update in ({"state": "PASS"}, {"source_acquisition_authorized": True}, {"actual_rest_requests": 1},
                       {"witness": {"ohlc_exact_match": True}}):
            self.write_document(name, {**copy.deepcopy(original), **update})
            with self.subTest(update=update), self.assertRaisesRegex(saved.VerificationError, "SAVED_CALIBRATION_MUST_REMAIN_SCHEMA_BLOCKED"):
                self.verify()
        self.write_document(name, original)
        value = self.document("BUDGET_TERMINAL.json")
        value["actual"]["control_runs"] = 1
        self.write_document("BUDGET_TERMINAL.json", value)
        with self.assertRaisesRegex(saved.VerificationError, "SAVED_BUDGET_ACK_REPAIRED_ZERO_REST_SOURCE_ECONOMICS"):
            self.verify()

    def test_strategy_rejection_metrics_or_handoff_cannot_be_fabricated(self):
        name = "BUDGET_TERMINAL.json"
        original = self.document(name)
        for update in ({"economic_reject": True}, {"unified_created": True},
                       {"prospective_G5A_handoff": 1}, {"automatic_successor": True},
                       {"failure_class": "ECONOMIC_FAILURE"}):
            self.write_document(name, {**copy.deepcopy(original), **update})
            with self.subTest(update=update), self.assertRaisesRegex(saved.VerificationError, "SAVED_FAILURE_CLASS_NO_STRATEGY_REJECT_OR_SUCCESSOR"):
                self.verify()
        value = copy.deepcopy(original)
        value["economic_metrics"]["DEV_A"]["U1"] = {"status": "PASS", "metrics": {"net": 1}}
        self.write_document(name, value)
        with self.assertRaisesRegex(saved.VerificationError, "SAVED_ECONOMICS_MUST_BE_NOT_RUN"):
            self.verify()

    def test_preserved_and_frozen_executor_changes_fail(self):
        path = self.root / saved.PARENT_CONTRACT_PATH
        original = path.read_bytes()
        path.write_bytes(original + b" ")
        with self.assertRaisesRegex(saved.VerificationError, "SAVED_PRESERVED_FILE_SHA_MISMATCH"):
            self.verify()
        path.write_bytes(original)
        path = self.root / saved.FROZEN_EXECUTOR_PATH
        path.write_bytes(path.read_bytes() + b"\n# post-outcome change forbidden\n")
        self.rehash()
        with self.assertRaisesRegex(saved.VerificationError, "SAVED_PREEXEC_FILE_BINDING"):
            self.verify()

    def test_ack_decision_and_frame_chronology_recomputed(self):
        name = "calibration/raw/ws_0001.ack.json"
        value = self.document(name)
        value["decision"]["classification"] = "SUBSCRIPTION_ACK_FAILED"
        self.write_document(name, value)
        self.refresh_calibration_binding()
        with self.assertRaisesRegex(saved.VerificationError, "SAVED_ACK_DECISION_BINDING"):
            self.verify()

    def test_frame2_lone_T_cannot_be_changed_to_canonical_K(self):
        path = self.root / saved.EVIDENCE / "calibration/raw/ws_0002.bin"
        frame = saved._inspect_unaccepted_market_frame(path.read_bytes())
        self.assertEqual(frame["dataType"], saved.CHANNEL)
        frame["data"][0]["t"] = frame["data"][0]["T"]
        with self.assertRaisesRegex(saved.VerificationError, "SAVED_FRAME2_NO_K_t_K_T_WITNESS"):
            saved._inspect_unaccepted_market_frame(gzip.compress(saved._canonical(frame)))

    def test_remote_prereg_readback_cannot_be_replaced(self):
        value = self.document("FREEZE_READBACK.json")
        value["verified_commit_sha"] = "0" * 40
        self.write_document("FREEZE_READBACK.json", value)
        with self.assertRaisesRegex(saved.VerificationError, "SAVED_PREEXEC_REMOTE_READBACK"):
            self.verify()

    def test_no_network_collector_or_economic_imports(self):
        source = (saved.ROOT / saved.VERIFIER_PATH).read_text()
        tree = ast.parse(source)
        forbidden = {"socket", "subprocess", "requests", "urllib", "http", "aiohttp", "websockets", "backend"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                self.assertFalse(any(alias.name.split(".")[0] in forbidden for alias in node.names))
            elif isinstance(node, ast.ImportFrom):
                self.assertNotIn((node.module or "").split(".")[0], forbidden)
        self.assertEqual(self.verify()["economic_runs"], 0)


if __name__ == "__main__":
    unittest.main()
