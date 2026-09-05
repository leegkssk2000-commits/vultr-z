import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.research.alpha_proof import a1_alpha_proof_gate_v1 as alpha
from backend.research.architecture_factory import g5a_source_admission_v1 as admission
from backend.research.architecture_factory import a1_strategy_architecture_factory_v1 as factory
from backend.research import p3_prospective_native_feature_collector as native
from backend.research.rebuild import g5b_operational_terminal_v1 as op


class SourceAdmissionTests(unittest.TestCase):
    def test_native_request_time_cannot_stand_for_receipt_time(self):
        payload = {"openInterest": "1", "time": 1_700_000_000_100}
        with self.assertRaisesRegex(RuntimeError, "POINT_IN_TIME"):
            native.make_record("open_interest", "BTC-USDT", payload, "test", 100, 1_700_000_000_000)
        result = native.make_record("open_interest", "BTC-USDT", payload, "test", 100, 1_700_000_000_200)
        self.assertLessEqual(result["source_timestamp_ms"], result["collected_at_ms"])

    def test_old_clock_inversions_remain_rejected(self):
        rows = [{"source_timestamp_ms": 2, "collected_at_ms": 1, "source_payload_sha256": "test", "prospective_only": True}]
        self.assertFalse(admission.audit_native_rows(rows)["point_in_time"])

    def test_duplicate_native_timestamp_rejected(self):
        row = {"source_timestamp_ms": 1, "collected_at_ms": 2, "source_payload_sha256": "test", "prospective_only": True}
        self.assertIn("NONMONOTONIC:source_timestamp_ms", admission.audit_native_rows([row, row])["errors"])

    def test_expired_registry_cannot_generate(self):
        registry = admission.read("backend/research/architecture_factory/g5a_source_capability_registry_v1.json")
        with self.assertRaisesRegex(RuntimeError, "NOT_READY_BEFORE_GENERATION"):
            admission.generation_sources(registry, now_ms=registry["as_of_ms"] + 86_400_000)

    def test_modified_registry_cannot_generate(self):
        registry = admission.read("backend/research/architecture_factory/g5a_source_capability_registry_v1.json")
        registry["candidate_cost_binding"] = "BOUND"
        with self.assertRaisesRegex(RuntimeError, "RECEIPT_DRIFT"):
            admission.generation_sources(registry, now_ms=registry["as_of_ms"])

    def test_input_drift_blocks_generation_even_with_valid_receipt(self):
        registry = admission.read("backend/research/architecture_factory/g5a_source_capability_registry_v1.json")
        registry.pop("receipt_sha256")
        registry["source_files_sha256"][admission.STATE_PATH] = "changed"
        with self.assertRaisesRegex(RuntimeError, "INPUT_PARITY"):
            admission.generation_sources(admission.seal(registry), now_ms=registry["as_of_ms"])

    def test_no_paid_generation_when_cost_source_unbound(self):
        with patch.object(factory, "read_json", return_value={"candidate_cost_binding": "NOT_BOUND"}), patch.object(admission, "generation_sources", return_value=["ohlcv", "volume"]), patch.object(factory, "call_openai_generator") as paid:
            with self.assertRaisesRegex(RuntimeError, "P6_CANDIDATE_COST"):
                factory.run(Path("unused"))
            paid.assert_not_called()

    def test_ma001_terminal_keeps_original_bytes_and_historical_hold(self):
        registry = admission.read("backend/research/architecture_factory/g5a_source_capability_registry_v1.json")
        path = admission.DIR / "g5a_alpha_factory_latest.json"; before = path.read_bytes()
        result = admission.terminalize(registry)
        self.assertEqual(result["semantic_classification"], "MIXED_OR_UNRESOLVED")
        self.assertEqual(result["original_state"], "G5A_SOURCE_BLOCKED_REJECT")
        self.assertFalse(result["mutated_in_place"])
        self.assertIsNone(result["successor_candidate"])
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(json.loads(before)["next_experiment_candidate"]["cross_reviews"]["openai"]["decision"], "HOLD")
        self.assertTrue(all(not r["deterministic_replay_authorized"] for r in result["candidates"]))
        self.assertFalse(result["family_budget_exhausted"])


class OperationalTests(unittest.TestCase):
    def test_alpha_reject_cannot_create_boundary(self):
        with self.assertRaisesRegex(RuntimeError, "ALPHA_PROOF_REQUIRED"):
            op.freeze_boundary({}, {}, {}, now_ms=1)

    def good_inputs(self):
        bundle = alpha._fixture_bundle(); proof = alpha.evaluate_bundle(bundle)
        economics = admission.seal({"state": "G5A_DEVELOPMENT_PASS_READY_FOR_G5B", "candidate_sha256": proof["candidate_sha256"],
                    "alpha_proof_receipt_sha": proof["receipt_sha256"], "purged_oos_pass": True, "negative_controls_superior": True,
                    "no_leakage": True, "no_cherry_pick": True, "duplicate": 0, "net_expectancy_bps": 1, "profit_factor": 1.1, "cost2x_net_bps": 1,
                    "reports": {name: {"receipt_sha256": "fixture-only", "candidate_sha256": proof["candidate_sha256"], "data_sha": "test-only", "cost_sha": "test-only", "complete": True} for name in op.ECONOMIC_REPORTS}})
        identity = {k: "test-only" for k in op.BOUNDARY_KEYS}; identity.update(candidate_id=proof["candidate_id"], source_receipt_sha=economics["receipt_sha256"])
        return bundle, economics, identity

    def test_synthetic_complete_path_starts_zero_without_order_authority(self):
        b,e,i = self.good_inputs(); r = op.freeze_boundary(b,e,i,now_ms=1_700_000_000_000)
        self.assertEqual(r["formal_fresh_T"], 0)
        self.assertEqual(r["preboundary_formal_credit"], 0)
        self.assertFalse(r["historical_backfill"])
        self.assertEqual(r["order_authority"], "BLOCKED")
        self.assertFalse(r["exchange_order_submitted"])

    def test_economic_failure_blocks_even_with_alpha_pass(self):
        b,e,i = self.good_inputs(); e["cost2x_net_bps"] = -1; e.pop("receipt_sha256"); e = admission.seal(e)
        i["source_receipt_sha"] = e["receipt_sha256"]
        with self.assertRaisesRegex(RuntimeError, "ECONOMIC_FAIL"):
            op.freeze_boundary(b,e,i,now_ms=1)

    def test_identity_mismatch_blocks_boundary(self):
        b,e,i = self.good_inputs(); i["candidate_id"] = "other"
        with self.assertRaisesRegex(RuntimeError, "IDENTITY"):
            op.freeze_boundary(b,e,i,now_ms=1)

    def test_missing_chronological_or_decomposition_report_blocks_boundary(self):
        for name in op.ECONOMIC_REPORTS:
            b,e,i = self.good_inputs(); e.pop("receipt_sha256"); del e["reports"][name]
            e = admission.seal(e); i["source_receipt_sha"] = e["receipt_sha256"]
            with self.assertRaisesRegex(RuntimeError, "REPORT_MISSING_OR_UNBOUND"):
                op.freeze_boundary(b,e,i,now_ms=1)

    def test_t6_and_t12_are_not_terminal(self):
        for n in (6,12,30):
            rows = [{"symbol":"S"+str(k),"trade":{"signal_ts":1_700_000_000_000},"regime":"same_shock"} for k in range(n)]
            r = op.checkpoints(rows)
            self.assertFalse(r["g6_allowed"])
            self.assertFalse(r["T12_is_terminal"])
            self.assertEqual(r["independence_audit"]["N_effective"], 1)

    def test_unidentified_regime_cannot_claim_independence_audit(self):
        self.assertFalse(op.independence([{"symbol":"BTC", "trade":{"signal_ts":1}}])["validated"])

    def test_zero_close_state_classification(self):
        args = dict(stale=False, signals=0, eligible=0, opens=0, closes=0, rejected=0)
        self.assertEqual(op.zero_state(**args), "NO_SIGNAL")
        self.assertEqual(op.zero_state(**{**args,"stale":True}), "SOURCE_STALE")
        self.assertEqual(op.zero_state(**{**args,"opens":1}), "OPEN_PENDING_CLOSE")
        self.assertEqual(op.zero_state(**{**args,"signals":1,"rejected":1}), "SIGNAL_REJECTED")
        self.assertEqual(op.zero_state(**{**args,"signals":1,"eligible":1}), "NORMAL_WAIT")
        self.assertEqual(op.zero_state(**args,ledger_error=True), "LEDGER_WRITE_FAIL")

    def test_bridge_trigger_waits_for_durable_cutover_owner(self):
        text = (op.ROOT / ".github/workflows/g5-forward-real-evidence-v1.yml").read_text()
        self.assertIn("workflows: ['G5 Cutover Post3 Progress V1']", text)
        self.assertIn("github.event.workflow_run.head_branch == 'master'", text)

    def test_read_only_current_ledger_and_receipt_parity(self):
        paths = [op.ROOT / "backend/research/rebuild/g5_clean_runner_state_events_v1.jsonl", op.ROOT / "backend/research/prep/g5_economic_evidence_ledger_v1.jsonl"]
        before = [admission.file_sha(p) for p in paths]
        r = op.derive(as_of_ms=admission.read("backend/research/architecture_factory/g5a_source_capability_registry_v1.json")["as_of_ms"])
        self.assertEqual(before, [admission.file_sha(p) for p in paths])
        self.assertFalse(r["new_boundary_created"])
        self.assertGreaterEqual(r["production_grade_ledger_rows"], r["formal_fresh_T"])
        self.assertFalse(r["old_history_union"])


if __name__ == "__main__":
    unittest.main()
