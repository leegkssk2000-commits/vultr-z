"""Artificial qualification metadata; no repository qualification or economics."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend.research.rebuild import squeeze_g5a_qualification_v1 as q


def metadata_fixture(root):
    """Deliberately synthetic tiny calendars and nonmarket fixture source."""
    contract = {"source_interval_ms": 10, "receipt_sha256": "synthetic-contract",
                "cost_authority_path": "synthetic-cost.json",
                "split": {"embargo_rule": "synthetic-existing-embargo"}}
    root.joinpath(q.CONTRACT).parent.mkdir(parents=True, exist_ok=True)
    root.joinpath(q.CONTRACT).write_text(json.dumps(contract))
    root.joinpath(q.SPEC).parent.mkdir(parents=True, exist_ok=True)
    root.joinpath(q.SPEC).write_text('{"synthetic":true}')
    dev = dict(dataset_sha256="synthetic-dataset", receipt_sha256="synthetic-cost-binding",
               development_cost_model="SYNTHETIC_ONLY", splits={"purged_OOS": [100, 200]})
    identity = dict(exact_rules={"entry": {"rule": "synthetic completed-close rule",
                    "authoritative_functions": ["synthetic_entry"]}},
                    benchmark_source_receipts_sha256={})
    docs = {
        q.PRIOR + "ARCHITECTURE_SEAL.json": {"identity": identity},
        q.PARENT + "SPEC.json": {"periods": {"SEEN2026": {"start_ms": 120, "runoff_end_ms": 190}}},
        q.PRIOR + "CHALLENGE_WINDOW_SEALED.json": {"reason": "SYNTHETIC_UNUSED_PROVENANCE_ABSENT"},
        q.ADMISSION: {"development": dev}, q.CONTRACT: contract,
    }
    pins = {q.SPEC: q.file_sha(root / q.SPEC)}
    for relative, doc in docs.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc))
        pins[relative] = q.file_sha(path)
    root.joinpath(q.ALPHA).parent.mkdir(parents=True, exist_ok=True)
    root.joinpath(q.ALPHA).write_text('# synthetic owner fixture bytes')
    pins[q.ALPHA] = q.file_sha(root / q.ALPHA)
    manifest = dict(path=q.MANIFEST, exists=False, sha256=None,
                    contents_decoded=False, authenticity_verified=False)
    return docs, pins, manifest


class ExposureTests(unittest.TestCase):
    def test_half_open_equal_edge_is_not_overlap(self):
        r = q.interval_overlap([10, 50], [50, 100], 10)
        self.assertEqual(r["overlap_bars"], 0)
        self.assertIsNone(r["intersection"])

    def test_full_partial_and_nested_overlap(self):
        for used, expected in (([0, 100], 10), ([20, 90], 7), ([90, 120], 1)):
            r = q.interval_overlap([0, 100], used, 10)
            self.assertEqual(r["overlap_bars"], expected)
            self.assertEqual(r["canonical_bars"], 10)
            self.assertEqual(r["overlap_percent"], expected * 10)

    def test_no_rounding_of_unaligned_windows(self):
        with self.assertRaisesRegex(ValueError, "NOT_BAR_ALIGNED"):
            q.interval_overlap([0, 100], [21, 90], 10)

    def test_boolean_timestamps_are_not_numbers(self):
        with self.assertRaisesRegex(ValueError, "INVALID_FROZEN_INTERVAL"):
            q.interval_overlap([False, 100], [20, 90], 10)


class OneShotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fixture = metadata_fixture(self.root)

    def issue(self):
        with patch.object(q, "load_inputs", return_value=deepcopy(self.fixture)):
            return q.qualify_once(self.root, issued_at_ms=1_000)

    def replace_saved(self, result):
        result.pop("receipt_sha256", None)
        result = q.seal(result)
        (self.root / q.OUT).write_text(json.dumps(result))

    def test_real_alpha_owner_called_once_with_truthful_failures(self):
        with patch.object(q.alpha, "evaluate_bundle", wraps=q.alpha.evaluate_bundle) as gate:
            result = self.issue()
        self.assertEqual(gate.call_count, 1)
        self.assertEqual(result["p0_p6"], {"P0": "FAIL", "P1": "PASS", "P2": "FAIL",
            "P3": "FAIL", "P4": "FAIL", "P5": "FAIL", "P6": "FAIL"})
        self.assertEqual(result["used_dev_oos_overlap"]["overlap_bars"], 7)
        self.assertEqual(result["economic_replays"], 0)
        self.assertEqual(result["provider_calls"], 0)
        self.assertFalse(result["caller_integrity_exact_zero_pass"])
        self.assertIsNone(result["alpha_bundle"]["source_implementation_reality"]["duplicate_count"])
        self.assertEqual(result["original_identity"], q.EXPECTED)
        self.assertFalse(result["report_hash_parity"])
        self.assertEqual(result["report_complete_count"], 0)
        self.assertEqual(set(result["economics"]["reports"]), set(q.REPORTS))
        self.assertTrue(all(r["complete"] is False and r["metrics"] is None and r["receipt_sha256"] is None
                            for r in result["economics"]["reports"].values()))

    def test_repeat_issuance_rejected_without_gate_or_overwrite(self):
        self.issue()
        before = (self.root / q.OUT).read_bytes()
        with patch.object(q.alpha, "evaluate_bundle") as gate:
            with self.assertRaisesRegex(ValueError, "NO_RETRY"):
                q.qualify_once(self.root, issued_at_ms=2_000)
        gate.assert_not_called()
        self.assertEqual((self.root / q.OUT).read_bytes(), before)

    def test_failed_attempt_is_consumed_not_retried(self):
        with patch.object(q, "load_inputs", side_effect=ValueError("fixture source missing")):
            with self.assertRaisesRegex(ValueError, "fixture source missing"):
                q.qualify_once(self.root, issued_at_ms=1_000)
        self.assertTrue((self.root / q.ATTEMPT).is_file())
        self.assertFalse((self.root / q.OUT).exists())
        with self.assertRaisesRegex(ValueError, "NO_RETRY"):
            self.issue()

    def test_verification_never_evaluates_alpha_or_repeats_qualification(self):
        self.issue()
        with patch.object(q.alpha, "evaluate_bundle", side_effect=AssertionError("no replay")), \
                patch.object(q, "_qualification", side_effect=AssertionError("no qualification")):
            result = q.verify_only(self.root)
        self.assertEqual(result["status"], "PASS_SAVED_QUALIFICATION_REJECTION_VERIFIED")
        self.assertFalse(result["qualification_reexecuted"])

    def test_postqualification_source_mutation_is_rejected(self):
        self.issue()
        (self.root / q.CONTRACT).write_text('{"tampered":true}')
        with self.assertRaisesRegex(ValueError, "SOURCE_BYTES_DRIFT"):
            q.verify_only(self.root)

    def test_unexecuted_report_cannot_be_resealed_as_complete(self):
        result = self.issue()
        economics = result["economics"]
        economics["reports"]["purged_oos"]["complete"] = True
        economics.pop("receipt_sha256")
        result["economics"] = q.seal(economics)
        self.replace_saved(result)
        with self.assertRaisesRegex(ValueError, "FALSE_REPORT_COMPLETION"):
            q.verify_only(self.root)

    def test_null_metric_cannot_be_resealed_as_zero(self):
        result = self.issue()
        economics = result["economics"]
        economics["duplicate"] = 0
        economics.pop("receipt_sha256")
        result["economics"] = q.seal(economics)
        self.replace_saved(result)
        with self.assertRaisesRegex(ValueError, "UNEXECUTED_METRIC"):
            q.verify_only(self.root)

    def test_resealed_overlap_uses_source_calendars_not_supplied_values(self):
        result = self.issue()
        result['used_dev_oos_overlap'] = q.interval_overlap([100, 200], [100, 200], 10)
        self.replace_saved(result)
        with self.assertRaisesRegex(ValueError, "EXPOSURE_ARITHMETIC"):
            q.verify_only(self.root)

    def test_changed_bundle_cannot_reuse_alpha_call_receipt(self):
        result = self.issue()
        result['alpha_bundle']['primary_evidence']['supports'] = [{'fake': True}]
        self.replace_saved(result)
        with self.assertRaisesRegex(ValueError, "ALPHA_CALL_BINDING"):
            q.verify_only(self.root)

    def test_receipt_cannot_authorize_runtime(self):
        result = self.issue()
        result["runtime_registered"] = True
        self.replace_saved(result)
        with self.assertRaisesRegex(ValueError, "AUTHORITY_DRIFT"):
            q.verify_only(self.root)

    def test_no_alpha_call_when_exposure_premise_changes(self):
        docs, pins, manifest = self.fixture
        docs[q.PARENT + "SPEC.json"]["periods"]["SEEN2026"] = {"start_ms": 200, "runoff_end_ms": 300}
        with patch.object(q, "load_inputs", return_value=(docs, pins, manifest)), \
                patch.object(q.alpha, "evaluate_bundle") as gate:
            with self.assertRaisesRegex(ValueError, "PREMISE_CHANGED"):
                q.qualify_once(self.root, issued_at_ms=1_000)
        gate.assert_not_called()

    def test_symlink_destination_is_rejected(self):
        outside = self.root / "outside.json"
        outside.write_text("unchanged")
        (self.root / q.OUT).symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "PATH_ESCAPE"):
            q.qualify_once(self.root)
        self.assertEqual(outside.read_text(), "unchanged")

    def test_cli_requires_explicit_mode(self):
        with self.assertRaises(SystemExit) as caught:
            q.main(["--root", str(self.root)])
        self.assertEqual(caught.exception.code, 2)
        self.assertFalse((self.root / q.ATTEMPT).exists())


if __name__ == "__main__":
    unittest.main()
