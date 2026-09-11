"""Synthetic saved evidence fixtures; no network, policy, or economic execution."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend.research.rebuild import trendrider_common_saved_verify_v1 as verifier


class SavedVerifierTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.scope = verifier.EVIDENCE
        self.manifest_path = self.root / verifier.MANIFEST_PATH
        self.make_fixture()

    def put(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = value if isinstance(value, bytes) else verifier._canonical(value, newline=True)
        path.write_bytes(raw)
        return verifier._sha(raw)

    def scope_put(self, name, value):
        return self.put(self.scope + "/" + name, value)

    def scope_read(self, name):
        return json.loads((self.root / self.scope / name).read_bytes())

    def seal(self, value):
        return {**value, "receipt_sha256": verifier._sha(verifier._canonical(value, newline=True))}

    def refresh_manifest(self):
        files = {}
        for path in self.root.rglob("*"):
            if path.is_file() and path != self.manifest_path:
                relative = path.relative_to(self.root).as_posix()
                if relative.startswith("backend/research/rebuild/preserved_"):
                    continue
                files[relative] = verifier._sha(path.read_bytes())
        self.manifest_sha = self.put(verifier.MANIFEST_PATH, {"files": files})

    def make_fixture(self):
        preserved = {f"backend/research/rebuild/preserved_{i:02d}.py":
                     self.put(f"backend/research/rebuild/preserved_{i:02d}.py", b"# immutable fixture\n")
                     for i in range(32)}
        preserved_sha = self.scope_put("PRESERVED_TRENDRIDER_HASHES.json", {"files": preserved})
        cost = {"actual_funding": False, "production_grade": False,
                "current_depth_or_funding_fetch": False, "fee_bps": 10.0,
                "spread_bps": 1.0, "impact_bps": 2.0, "funding_proxy_bps": 1.0,
                "round_trip_bps": 14.0, "exact_2x_round_trip_bps": 28.0}
        self.cost_sha = verifier._sha(verifier._canonical(cost))
        contract = {"source": {"endpoint": verifier.ENDPOINT, "symbols": ["BTC-USDT", "ETH-USDT"],
                               "interval": "1h", "cutoff_ms": verifier.CUTOFF_MS,
                               "bars_per_symbol": 1000, "page_limit": 1000, "max_pages_per_symbol": 10},
                    "common_cost": cost, "common_cost_sha256": self.cost_sha}
        self.contract_sha = self.scope_put("COMMON_REPLAY_CONTRACT.json", contract)
        self.scope_put("source_data/SOURCE_CONTRACT.json", contract)
        frozen_files = {f"backend/research/rebuild/frozen_{i:02d}.py":
                        self.put(f"backend/research/rebuild/frozen_{i:02d}.py", b"# frozen fixture\n")
                        for i in range(10)}
        frozen_files.update({self.scope + "/COMMON_REPLAY_CONTRACT.json": self.contract_sha,
                             self.scope + "/PRESERVED_TRENDRIDER_HASHES.json": preserved_sha})
        frozen = {"files": frozen_files, "contract_sha256": self.contract_sha,
                  "dataset_fetch_attempts_at_freeze": 0, "economic_runs_at_freeze": 0}
        self.preexec_sha = self.scope_put("PREEXEC_FREEZE.json", frozen)
        self.scope_put("FREEZE_READBACK.json", {"preexec_manifest_sha256": self.preexec_sha,
                       "contract_sha256": self.contract_sha, "cost_sha256": self.cost_sha,
                       "remote_manifest_readback_exact_match": True})
        attempt = self.seal({"attempt_ordinal": 1, "retry_authorized": False,
                             "contract_sha256": self.contract_sha, "started_at_ms": 1})
        self.scope_put("source_data/ATTEMPT_STARTED.json", attempt)
        params = {"symbol": "BTC-USDT", "interval": "1h", "limit": 1000,
                  "endTime": verifier.CUTOFF_MS - 1}
        request = {"endpoint": verifier.ENDPOINT, "params": params, "page_index": 0,
                   "requested_at_ms": 2, "transport_retry_count": 0}
        self.scope_put("source_data/raw/BTC-USDT_00.request.json", request)
        raw = verifier._canonical({"code": 0, "data": [
            {"time": stamp} for stamp in range(verifier.CUTOFF_MS, verifier.FIRST_OPEN_MS, -verifier.HOUR_MS)
        ]}, newline=True)
        self.raw_sha = self.scope_put("source_data/raw/BTC-USDT_00.bin", raw)
        response = self.seal({**request, "http_status": 200, "received_at_ms": 3,
                              "raw_path": "raw/BTC-USDT_00.bin", "raw_sha256": self.raw_sha,
                              "raw_bytes": len(raw), "saved_before_decode": True})
        self.scope_put("source_data/raw/BTC-USDT_00.response.json", response)
        failure = self.seal({"state": "BLOCKED_DATA", "reason": "SOURCE_TIMESTAMP_GRID_OR_WINDOW",
                            "error_type": "SourceIntegrityError", "contract_sha256": self.contract_sha,
                            "dataset_fetch_attempts": 1, "http_response_count": 1, "normalized": {},
                            "transport_retries": 0, "retry_authorized": False, "economic_runs": 0,
                            "formal_credit": 0, "production_grade": False, "last_attempted_request": request,
                            "requests": [response], "failed_at_ms": 4})
        self.scope_put("source_data/FAILURE_MANIFEST.json", failure)
        budget = {"dataset_freeze_attempts": 1, "control_economic_runs": 0,
                  "DEV_A_screens": 0, "DEV_B_confirmations": 0, "canonical_candidates": 0,
                  "child_FULL_runs": 0, "retry": 0, "FIXED": 0, "Squeeze_v1_v2_data_access": 0,
                  "arbitrary_OOS": 0, "deploy": 0, "live": 0, "orders": 0,
                  "paid_AI": 0, "prospective_ledger_decode": 0, "sweep": 0}
        result = {"state": "BLOCKED_COMMON_SOURCE_DATA", "budget_consumed": budget,
                  "production_grade": False, "formal_credit": 0, "verdict_is_economic_rejection": False,
                  "economic_validation": "NOT_RUN_SOURCE_INTEGRITY_GATE", "prospective_G5A_handoff": 0,
                  "ETH_fetched": False, "normalized_data_sha256": None, "strategy_seal": None,
                  "remaining_usable_economic_budget": 0, "source_HTTP_GETs": 1, "source_http_responses": 1,
                  "retry_authorized": False, "automatic_successor": False,
                  "source_contract_sha256": self.contract_sha, "common_cost_sha256": self.cost_sha,
                  "rejected_raw_sha256": self.raw_sha, "preexec_freeze_sha256": self.preexec_sha,
                  "economic_metrics": {period: {lane: {"metrics": None, "status": "NOT_RUN"}
                                       for lane in ("B_COMMON", "P_COMMON", "U1", "U2")}
                                       for period in ("DEV_A", "DEV_B")}}
        self.scope_put("SCOPE_RESULT.json", result)
        diagnostic = {"state": "SOURCE_CLOCK_WINDOW_MISMATCH", "ETH_request_count": 0,
                      "adjacent_clock_gap_count": 0, "duplicate_count": 0, "api_code": 0,
                      "automatic_repair_or_refetch": 0, "expected_first_open_ms": verifier.FIRST_OPEN_MS,
                      "expected_last_open_ms": verifier.CUTOFF_MS - verifier.HOUR_MS, "http_status": 200,
                      "missing_native_open_ms": [verifier.FIRST_OPEN_MS],
                      "unexpected_native_open_ms": [verifier.CUTOFF_MS], "normalized_dataset_sha256": None,
                      "params": params, "raw_bytes": len(raw), "raw_sha256": self.raw_sha,
                      "response_rows": 1000, "returned_first_open_ms": verifier.FIRST_OPEN_MS + verifier.HOUR_MS,
                      "returned_last_open_ms": verifier.CUTOFF_MS}
        self.scope_put("SOURCE_CLOCK_DIAGNOSTIC.json", diagnostic)
        self.refresh_manifest()

    def run_verify(self):
        with patch.object(verifier, "SAVED_MANIFEST_SHA256", self.manifest_sha), \
                patch.object(verifier, "PREEXEC_SHA256", self.preexec_sha):
            return verifier.verify(self.root)

    def test_full_synthetic_blocked_receipt_passes(self):
        raw = (self.root / self.scope / "source_data/raw/BTC-USDT_00.bin").read_bytes()
        original = verifier._json
        def reject_raw_decode(value):
            self.assertNotEqual(value, raw, "Quarantined prices must not be JSON-decoded")
            return original(value)
        with patch.object(verifier, "_json", side_effect=reject_raw_decode):
            result = self.run_verify()
        self.assertEqual(result["state"], "PASS_SAVED_BLOCKED_SOURCE_VERIFICATION")
        self.assertEqual(result["frozen_files"], 12)
        self.assertEqual(result["preserved_files"], 32)
        self.assertEqual(result["economic_runs"], 0)
        self.assertEqual(result["raw_timestamp_rows"], 1000)

    def test_unsealed_manifest_reads_nothing(self):
        with patch.object(verifier, "SAVED_MANIFEST_SHA256", "UNSEALED"), \
                patch.object(Path, "read_bytes", side_effect=AssertionError("NO_READ")):
            with self.assertRaisesRegex(verifier.VerificationError, "UNSEALED"):
                verifier.verify(self.root)

    def test_bad_manifest_pin_precedes_parse_or_dependency_access(self):
        self.manifest_path.write_bytes(b"not even JSON")
        calls = []
        original = Path.read_bytes
        def read(path):
            calls.append(path)
            return original(path)
        with patch.object(Path, "read_bytes", read):
            with self.assertRaisesRegex(verifier.VerificationError, "MANIFEST_SHA_MISMATCH"):
                self.run_verify()
        self.assertEqual(calls, [self.manifest_path])

    def test_traversal_rejected_before_any_referenced_file_read(self):
        manifest = {"files": {"../outside": "0" * 64}}
        self.manifest_sha = self.put(verifier.MANIFEST_PATH, manifest)
        calls = []
        original = Path.read_bytes
        def read(path):
            calls.append(path)
            return original(path)
        with patch.object(Path, "read_bytes", read):
            with self.assertRaisesRegex(verifier.VerificationError, "PATH_ESCAPE"):
                self.run_verify()
        self.assertEqual(calls, [self.manifest_path])

    def test_symlink_dependency_rejected(self):
        path = self.root / "linked.txt"
        path.symlink_to(self.manifest_path)
        self.manifest_sha = self.put(verifier.MANIFEST_PATH, {"files": {"linked.txt": "0" * 64}})
        with self.assertRaisesRegex(verifier.VerificationError, "SYMLINK_FORBIDDEN"):
            self.run_verify()

    def test_changed_frozen_dependency_fails(self):
        self.put("backend/research/rebuild/preserved_00.py", b"changed\n")
        with self.assertRaisesRegex(verifier.VerificationError, "FROZEN_DEPENDENCY_MISMATCH"):
            self.run_verify()

    def test_altered_saved_raw_fails_before_json_decode(self):
        self.scope_put("source_data/raw/BTC-USDT_00.bin", b"changed raw")
        with self.assertRaisesRegex(verifier.VerificationError, "FILE_SHA_MISMATCH"):
            self.run_verify()

    def test_nonzero_control_budget_or_handoff_fails_with_resealed_manifest(self):
        original = self.scope_read("SCOPE_RESULT.json")
        for field, error in (("control_economic_runs", "SCOPE_BUDGET"),
                             ("prospective_G5A_handoff", "SCOPE_CREDIT")):
            with self.subTest(field=field):
                result = json.loads(json.dumps(original))
                if field == "control_economic_runs":
                    result["budget_consumed"][field] = 1
                else:
                    result[field] = 1
                self.scope_put("SCOPE_RESULT.json", result)
                self.refresh_manifest()
                with self.assertRaisesRegex(verifier.VerificationError, error):
                    self.run_verify()

    def test_economic_metric_invention_rejected(self):
        result = self.scope_read("SCOPE_RESULT.json")
        result["economic_metrics"]["DEV_A"]["B_COMMON"]["metrics"] = {"net": 1}
        self.scope_put("SCOPE_RESULT.json", result)
        self.refresh_manifest()
        with self.assertRaisesRegex(verifier.VerificationError, "ECONOMICS_NOT_NULL"):
            self.run_verify()

    def test_failed_attempt_self_seal_is_independently_required(self):
        attempt = self.scope_read("source_data/ATTEMPT_STARTED.json")
        attempt["started_at_ms"] = 0
        self.scope_put("source_data/ATTEMPT_STARTED.json", attempt)
        self.refresh_manifest()
        with self.assertRaisesRegex(verifier.VerificationError, "ATTEMPT_SEAL"):
            self.run_verify()

    def test_no_new_normalized_or_second_symbol_artifact(self):
        self.scope_put("source_data/sources/ETH-USDT.json", [])
        self.refresh_manifest()
        with self.assertRaisesRegex(verifier.VerificationError, "SOURCE_EXTRA_OUTPUT"):
            self.run_verify()

    def test_unmanifested_economic_file_fails(self):
        self.scope_put("DEV_A/trades.json", [])
        with self.assertRaisesRegex(verifier.VerificationError, "UNMANIFESTED_SCOPE_FILE"):
            self.run_verify()


if __name__ == "__main__":
    unittest.main()
