import copy
import unittest

from backend.research.prep.g4_improvement_prep_v1 import (
    build_index,
    build_ready_receipt,
    load,
    CONTRACT,
    validate_contract,
)


class G4ImprovementPrepTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = load(CONTRACT)
        cls.index = build_index()

    def test_exact25_index_complete_and_non_economic(self):
        self.assertEqual(self.index["identity_count"], 25)
        self.assertEqual(len(self.index["strategies"]), 25)
        self.assertFalse(self.index["economic_outcomes_consumed"])
        for sid, item in self.index["strategies"].items():
            self.assertTrue(item["policy_file_sha256"], sid)
            self.assertTrue(item["config_sha"], sid)
            self.assertTrue(item["evidence_packet_sha256"], sid)
            self.assertTrue(item["evidence_authority_sha"], sid)
            self.assertTrue(item["source_ids"], sid)

    def test_all_failure_fingerprints_route_to_declared_axes(self):
        validate_contract(self.contract)
        axes = self.contract["causal_axes"]
        for fp, allowed in self.contract["failure_fingerprints"].items():
            self.assertGreater(len(allowed), 0, fp)
            self.assertTrue(all(axis in axes for axis in allowed), fp)

    def test_attempt_and_semantic_dedup_budget_frozen(self):
        b = self.contract["attempt_budget"]
        self.assertEqual(b["same_strategy_axis_data_sha_max"], 1)
        self.assertEqual(float(b["semantic_duplicate_cosine_gt"]), 0.85)

    def test_incumbent_pass_only_and_rollback(self):
        c = self.contract["incumbent_contract"]
        self.assertTrue(c["promote_new_incumbent_only_after_deterministic_pass"])
        self.assertTrue(c["failed_attempt_retains_previous_incumbent"])
        self.assertTrue(c["rollback_to_previous_incumbent_on_fail"])
        self.assertTrue(c["cumulative_improvement_not_restart_from_legacy"])

    def test_meta_audit_triggers(self):
        b = self.contract["attempt_budget"]
        self.assertEqual(b["meta_audit_after_distinct_strategies_failed"], 3)
        self.assertEqual(b["meta_audit_after_architecture_attempts_failed"], 6)

    def test_generation2_and_sealed_outcome_guards(self):
        self.assertEqual(self.contract["a1_authority"]["generation2_before_25_terminal"], "FORBIDDEN")
        self.assertFalse(self.contract["external_evidence"]["sealed_a1_economics_may_be_exposed"])
        receipt = build_ready_receipt(self.index, self.contract)
        self.assertEqual(receipt["state"], "G4_IMPROVEMENT_PREP_READY")
        self.assertFalse(receipt["generation2_evaluator_created"])
        self.assertFalse(receipt["a1_mutated"])
        self.assertFalse(receipt["economic_outcomes_consumed"])

    def test_bad_attempt_budget_fails_closed(self):
        bad = copy.deepcopy(self.contract)
        bad["attempt_budget"]["same_strategy_axis_data_sha_max"] = 2
        with self.assertRaises(AssertionError):
            validate_contract(bad)


if __name__ == "__main__":
    unittest.main()
