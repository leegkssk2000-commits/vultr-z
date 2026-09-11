"""Synthetic trust-boundary regressions; no market source or economic execution."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from backend.research.rebuild import trendrider_source_repair_saved_verify_v1 as verifier
from backend.research.rebuild import trendrider_common_source_v2 as collector


class SourceRepairSavedVerifierTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manifest_path = self.root / verifier.MANIFEST_PATH
        self.preserved_path = "backend/research/rebuild/preserved_fixture.py"
        self.make_fixture()

    def put(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = value if isinstance(value, bytes) else verifier._canonical(value)
        path.write_bytes(raw)
        return verifier._sha(raw)

    def scope_put(self, name, value):
        return self.put(verifier.EVIDENCE + "/" + name, value)

    def scope_read(self, name):
        return json.loads((self.root / verifier.EVIDENCE / name).read_bytes())

    def seal_semantic(self, value):
        unsigned = {key: item for key, item in value.items() if key != "receipt_sha256"}
        return {**unsigned, "receipt_sha256": verifier._sha(verifier._canonical(unsigned))}

    def refresh_manifest(self):
        files = {}
        for path in (self.root / verifier.EVIDENCE).rglob("*"):
            if path.is_file() and path != self.manifest_path:
                files[path.relative_to(self.root).as_posix()] = verifier._sha(path.read_bytes())
        manifest = {"schema": verifier.MANIFEST_SCHEMA, "scope_key": verifier.SCOPE, "files": files}
        self.manifest_sha = self.put(verifier.MANIFEST_PATH, manifest)

    def make_fixture(self):
        parent = {field: {"synthetic_frozen_rule": field} for field in verifier.FROZEN_ECONOMIC_FIELDS}
        parent["formal_credit"] = 0
        parent["production_grade"] = False
        parent_sha = self.put(verifier.PARENT_CONTRACT_PATH, parent)
        first, cutoff, hour = verifier.SOURCE_RULES["first_open_ms"], verifier.SOURCE_RULES["cutoff_ms"], 3_600_000
        raw_parent = verifier._canonical({"code": 0, "data": [
            {"time": stamp, "open": "UNINTERPRETED_SYNTHETIC_VALUE"}
            for stamp in range(first + hour, cutoff + hour, hour)]})
        raw_parent_sha = self.put(verifier.PARENT_RAW_PATH, raw_parent)
        preserved_sha = self.put(self.preserved_path, b"# immutable synthetic dependency\n")
        self.scope_put("PRESERVED_FILES.json", {"files": {
            verifier.PARENT_CONTRACT_PATH: parent_sha, self.preserved_path: preserved_sha,
            verifier.PARENT_RAW_PATH: raw_parent_sha,
        }})
        semantic = {
            "schema": collector.SEMANTIC_SCHEMA, "state": "BLOCKED_TIMESTAMP_SEMANTIC",
            "scope_key": verifier.SCOPE,
            "canonical_transform": None, "native_timestamp_meaning": "UNRESOLVED_OPEN_VS_CLOSE",
            "canonical_bar_timestamp": "OPEN_TIME_MS", "proposed_rules": collector.SEMANTIC_RULES,
            "request_cursor_rule": None, "acquisition_authorized": False,
            "proposed_rules_active": False, "new_market_api_requests": 0, "economic_runs": 0,
            "raw_evidence_path": verifier.PARENT_RAW_PATH, "raw_evidence_sha256": raw_parent_sha,
            "observed_raw_continuity": {
                "adjacent_gap_count": 0, "adjacent_interval_ms": hour, "duplicate_timestamp_count": 0,
                "expected_target_first_ms": first, "expected_target_last_ms": cutoff - hour,
                "extra_native_timestamps": [cutoff], "missing_target_timestamps": [first],
                "native_first_ms": first + hour, "native_last_ms": cutoff,
                "ohlc_values_interpreted": False, "raw_max_minus_request_endTime_ms": 1,
                "raw_rows": 1000, "request_endTime_ms": cutoff - 1, "unique_timestamps": 1000,
            },
        }
        semantic_sha = self.scope_put("TIMESTAMP_SEMANTIC_RECEIPT.json", self.seal_semantic(semantic))
        source_contract = {**copy.deepcopy(parent),
                           "schema_version": "trendrider.source_repair_contract.v1",
                           "scope_key": verifier.SCOPE, "authorization_issue": 1276,
                           "prior_contract": {"path": verifier.PARENT_CONTRACT_PATH, "sha256": parent_sha},
                           "source": {
            **verifier.SOURCE_RULES, "timestamp_semantic_receipt_sha256": semantic_sha,
        }}
        self.scope_put("SOURCE_REPAIR_CONTRACT.json", source_contract)
        budget = {
            "schema": "trendrider.source_repair.budget_terminal.v1", "scope_key": verifier.SCOPE,
            "state": "BLOCKED_TIMESTAMP_SEMANTIC", "actual": dict.fromkeys(verifier.ZERO_BUDGET_KEYS, 0),
            "economic_metrics": {
                period: {lane: {"status": "NOT_RUN", "metrics": None}
                         for lane in ("P_COMMON", "B_COMMON", "U1", "U2")}
                for period in ("DEV_A", "DEV_B")
            },
            "formal_credit": 0, "production_grade": False, "prospective_G5A_handoff": 0,
            "strategy_seal": None, "normalized_data_sha256": None, "completion": "REPORT_ONLY",
        }
        self.scope_put("BUDGET_TERMINAL.json", budget)
        self.scope_put("REPORT_KO.md", b"SYNTHETIC BLOCKED_TIMESTAMP_SEMANTIC\n")
        self.scope_put("DOCUMENTARY_EVIDENCE.json", {
            "schema": "trendrider.source_repair.documentary_evidence.v1", "scope_key": verifier.SCOPE,
            "local_preflight_network_calls": 0, "new_market_api_requests": 0,
            "subsequent_optional_official_document_lookup_performed": True,
            "official_document_network_reads_zero": False, "authority": "Issue1276 synthetic lookup fixture",
            "sources": [{"direct_object_open_semantic_proof": False,
                         "url": "https://github.com/BingX-API/synthetic-test-only",
                         "source_sha256": "0" * 64}],
        })
        self.scope_put("AUTHORIZATION_ISSUE.json", {"number": 1276, "synthetic": True})
        self.scope_put("WORK_NEXT.txt", b"Synthetic authorization fixture\n")
        self.refresh_manifest()

    def run_verify(self):
        with patch.object(verifier, "MANIFEST_FILE_SHA256", self.manifest_sha):
            return verifier.verify(self.root)

    def test_blocked_saved_fixture_passes_without_writes(self):
        with patch.object(Path, "write_bytes", side_effect=AssertionError("READ_ONLY")):
            result = self.run_verify()
        self.assertEqual(result["state"], "PASS_SAVED_BLOCKED_TIMESTAMP_SEMANTIC_VERIFICATION")
        self.assertEqual(result["source_acquisition_attempts"], 0)
        self.assertEqual(result["economic_runs"], 0)
        self.assertEqual(result["preserved_files"], 3)

    def test_unsealed_manifest_reads_nothing(self):
        with patch.object(verifier, "MANIFEST_FILE_SHA256", "UNSEALED"), \
                patch.object(Path, "read_bytes", side_effect=AssertionError("NO_READ")):
            with self.assertRaisesRegex(verifier.VerificationError, "MANIFEST_UNSEALED"):
                verifier.verify(self.root)

    def test_bad_manifest_hash_blocks_parse_and_dependency_read(self):
        self.manifest_path.write_bytes(b"not JSON")
        reads = []
        original = Path.read_bytes
        def observing(path):
            reads.append(path)
            return original(path)
        with patch.object(Path, "read_bytes", observing), \
                patch.object(verifier, "_json", side_effect=AssertionError("NO_PARSE")):
            with self.assertRaisesRegex(verifier.VerificationError, "MANIFEST_SHA_MISMATCH"):
                self.run_verify()
        self.assertEqual(reads, [self.manifest_path])

    def test_all_paths_checked_before_any_dependency_read(self):
        for unsafe, error in (("../outside", "PATH_ESCAPE"),
                              ("research/squeeze/forbidden.json", "SQUEEZE_PATH_FORBIDDEN")):
            with self.subTest(unsafe=unsafe):
                files = {verifier.EVIDENCE + "/WORK_NEXT.txt": "0" * 64, unsafe: "0" * 64}
                self.manifest_sha = self.put(verifier.MANIFEST_PATH, {
                    "schema": verifier.MANIFEST_SCHEMA, "scope_key": verifier.SCOPE, "files": files,
                })
                reads = []
                original = Path.read_bytes
                def observing(path):
                    reads.append(path)
                    return original(path)
                with patch.object(Path, "read_bytes", observing):
                    with self.assertRaisesRegex(verifier.VerificationError, error):
                        self.run_verify()
                self.assertEqual(reads, [self.manifest_path])

    def test_symlink_dependency_is_rejected(self):
        link = self.root / verifier.EVIDENCE / "linked.txt"
        link.symlink_to(self.root / self.preserved_path)
        self.refresh_manifest()
        with self.assertRaisesRegex(verifier.VerificationError, "SYMLINK_FORBIDDEN"):
            self.run_verify()

    def test_saved_bytes_rejected_before_semantic_parse(self):
        self.scope_put("TIMESTAMP_SEMANTIC_RECEIPT.json", b"not JSON")
        with self.assertRaisesRegex(verifier.VerificationError, "FILE_SHA_MISMATCH"):
            self.run_verify()

    def test_changed_preserved_dependency_blocks_semantic_interpretation(self):
        self.put(self.preserved_path, b"changed dependency\n")
        semantic_raw = (self.root / verifier.EVIDENCE / "TIMESTAMP_SEMANTIC_RECEIPT.json").read_bytes()
        original = verifier._json
        def forbid_semantic(raw):
            self.assertNotEqual(raw, semantic_raw)
            return original(raw)
        with patch.object(verifier, "_json", side_effect=forbid_semantic):
            with self.assertRaisesRegex(verifier.VerificationError, "PRESERVED_FILE_SHA_MISMATCH"):
                self.run_verify()

    def test_nonzero_missing_or_boolean_budget_is_rejected_even_resealed(self):
        original = self.scope_read("BUDGET_TERMINAL.json")
        cases = (("control_runs", 1), ("source_acquisition_attempts", 1), ("http_pages_ETH", 1),
                 ("control_runs", False), ("remove", None))
        for key, value in cases:
            item = copy.deepcopy(original)
            if key == "remove":
                del item["actual"]["source_acquisition_attempts"]
            else:
                item["actual"][key] = value
            self.scope_put("BUDGET_TERMINAL.json", item)
            self.refresh_manifest()
            with self.subTest(key=key, value=value), self.assertRaisesRegex(verifier.VerificationError, "BUDGET_NONZERO_OR_INCOMPLETE"):
                self.run_verify()

    def test_semantic_pass_transform_or_cursor_cannot_be_invented(self):
        original = self.scope_read("TIMESTAMP_SEMANTIC_RECEIPT.json")
        cases = ({"state": "PASS"}, {"canonical_transform": "IDENTITY_NATIVE_OPEN_MS"},
                 {"canonical_transform": "SHIFT_MINUS_ONE_HOUR"}, {"request_cursor_rule": "U_MINUS_ONE"},
                 {"acquisition_authorized": True})
        for update in cases:
            item = {**original, **update}
            self.scope_put("TIMESTAMP_SEMANTIC_RECEIPT.json", self.seal_semantic(item))
            self.refresh_manifest()
            with self.subTest(update=update), self.assertRaisesRegex(verifier.VerificationError, "TIMESTAMP_SEMANTIC"):
                self.run_verify()

    def test_forged_semantic_raw_diagnostic_fails_even_with_updated_outer_seal(self):
        item = self.scope_read("TIMESTAMP_SEMANTIC_RECEIPT.json")
        item["observed_raw_continuity"]["native_first_ms"] -= 3_600_000
        self.scope_put("TIMESTAMP_SEMANTIC_RECEIPT.json", self.seal_semantic(item))
        self.refresh_manifest()
        with self.assertRaisesRegex(verifier.VerificationError, "SEMANTIC_RAW_DIAGNOSTIC"):
            self.run_verify()

    def test_quarantined_prices_never_json_decoded(self):
        raw_parent = (self.root / verifier.PARENT_RAW_PATH).read_bytes()
        original = verifier._json
        def reject_parent_price_decode(raw):
            self.assertNotEqual(raw, raw_parent)
            return original(raw)
        with patch.object(verifier, "_json", side_effect=reject_parent_price_decode):
            self.run_verify()

    def test_contract_economic_fields_cannot_change(self):
        original = self.scope_read("SOURCE_REPAIR_CONTRACT.json")
        for field in ("common_cost", "execution", "genes", "partitions", "stage1", "stage3"):
            item = copy.deepcopy(original)
            item[field] = {"unauthorized_repair": True}
            self.scope_put("SOURCE_REPAIR_CONTRACT.json", item)
            self.refresh_manifest()
            with self.subTest(field=field), self.assertRaisesRegex(verifier.VerificationError, "ECONOMIC_RULE_CHANGED:" + field):
                self.run_verify()

    def test_semantic_sha_binding_and_max_pages_are_enforced(self):
        original = self.scope_read("SOURCE_REPAIR_CONTRACT.json")
        for key, value, error in (("timestamp_semantic_receipt_sha256", "0" * 64, "SEMANTIC_BINDING"),
                                   ("max_pages_per_symbol", 4, "CONTRACT_MISMATCH")):
            item = copy.deepcopy(original)
            item["source"][key] = value
            self.scope_put("SOURCE_REPAIR_CONTRACT.json", item)
            self.refresh_manifest()
            with self.subTest(key=key), self.assertRaisesRegex(verifier.VerificationError, error):
                self.run_verify()

    def test_economic_metrics_credit_and_handoff_must_remain_unexecuted(self):
        original = self.scope_read("BUDGET_TERMINAL.json")
        for field, value, error in (("formal_credit", 1, "CREDIT_OR_CLOSURE"),
                                    ("prospective_G5A_handoff", 1, "CREDIT_OR_CLOSURE"),
                                    ("strategy_seal", {"fake": "digest"}, "CREDIT_OR_CLOSURE"),
                                    ("normalized_data_sha256", "0" * 64, "CREDIT_OR_CLOSURE"),
                                    ("economic_metrics", {}, "METRICS_MUST_BE_NOT_RUN")):
            item = copy.deepcopy(original)
            item[field] = value
            self.scope_put("BUDGET_TERMINAL.json", item)
            self.refresh_manifest()
            with self.subTest(field=field), self.assertRaisesRegex(verifier.VerificationError, error):
                self.run_verify()

    def test_execution_artifacts_forbidden_even_if_empty_or_manifested(self):
        for name in ("source_data", "owner", "results", "ATTEMPT_STARTED_V2.json", "DATA_FREEZE_V2.json"):
            path = self.root / verifier.EVIDENCE / name
            if "." in name:
                path.write_bytes(b"{}\n")
            else:
                path.mkdir()
            self.refresh_manifest()
            with self.subTest(name=name), self.assertRaisesRegex(verifier.VerificationError, "FORBIDDEN_EXECUTION_ARTIFACT"):
                self.run_verify()
            if path.is_dir():
                path.rmdir()
            else:
                path.unlink()

    def test_unmanifested_evidence_rejected_but_later_exact_receipt_allowed(self):
        unknown = self.root / verifier.EVIDENCE / "unknown_result.json"
        unknown.write_bytes(b"{}\n")
        with self.assertRaisesRegex(verifier.VerificationError, "UNMANIFESTED_SCOPE_FILE"):
            self.run_verify()
        unknown.unlink()
        self.scope_put("EXACT_MERGE_VERIFICATION.json", {"separate_later_receipt": True})
        self.run_verify()

    def test_blocked_semantic_actually_prevents_collector_attempt_and_transport(self):
        output = self.root / "synthetic_attempt_forbidden"
        transport = Mock(side_effect=AssertionError("NO_GET"))
        with self.assertRaisesRegex(collector.SourceIntegrityError, "BLOCKED_TIMESTAMP_SEMANTIC"):
            collector.collect(self.root / verifier.EVIDENCE / "SOURCE_REPAIR_CONTRACT.json",
                              self.root / verifier.EVIDENCE / "TIMESTAMP_SEMANTIC_RECEIPT.json",
                              output, transport=transport)
        transport.assert_not_called()
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
