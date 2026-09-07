"""G5A scope regressions on existing gate code. Every proof here is a TEST FIXTURE.

No candidate receipt, provider response, source access, economic pass or approval
is produced. These tests prevent confusion between development eligibility,
independent OOS, fresh-source activation and G5B terminal rules.
"""
from copy import deepcopy
import unittest
from backend.research.alpha_proof import a1_alpha_proof_gate_v1 as gate


def control_fixture():
    return {'feature_causal_map': {'features': [{'name': 'fixture_feature'}]},
            'negative_controls_and_ablation': {
                'controls': [{'kind': kind, 'applicable': True, 'passed': True}
                             for kind in sorted(gate.REQUIRED_CONTROL_KINDS)],
                'feature_ablations': [{'feature': 'fixture_feature', 'passed': True}],
                'holdout_outcomes_used': False}}


def development_fixture():
    return {'candidate': {'required_sources': ['fixture_ohlcv']},
            'source_implementation_reality': {
                'admission_stage': 'G5A_DEVELOPMENT',
                'immutable_history_verified': True, 'split_frozen_before_outcomes': True,
                'development_cost_model_bound': True, 'development_data_sha': 'fixture-data',
                'formal_production_credit': 0,
                'sources': [{'name': 'fixture_ohlcv', 'available': True, 'fresh': False,
                             'historical_immutable': True, 'semantic_valid': True,
                             'source_sha': 'fixture-data', 'proxy': False}],
                'duplicate_count': 0, 'leakage_count': 0,
                'timestamp_order_error_count': 0, 'integrity_defect_count': 0,
                'verified_round_trip_cost_bps': 20.0, 'cost_authority_sha': 'fixture-cost'}}


def review_fixture(providers):
    # Artificial test metadata, never saved as reviews or used for candidate credit.
    return {'multi_ai_adversarial_review': {
        'controller_review_sha': 'TEST_ONLY_controller',
        'provider_reviews': [{'provider': p, 'successful': True, 'decision': 'PASS',
                             'model': 'TEST_ONLY', 'input_sha': 'TEST_ONLY_input',
                             'prompt_sha': 'TEST_ONLY_prompt', 'response_sha': 'TEST_ONLY_response'}
                            for p in providers]}}


class G5AContractScopeTests(unittest.TestCase):
    def test_p4_explained_nonapplicable_kind_is_existing_route_not_fake_pass(self):
        value = control_fixture()
        row = next(r for r in value['negative_controls_and_ablation']['controls']
                   if r['kind'] == 'regime_permutation')
        row.update(applicable=False, passed=False,
                   not_applicable_reason='TEST_ONLY: fixture has no regime-conditioned rule')
        self.assertTrue(gate.evaluate_p4(value)['passed'])
        self.assertFalse(row['passed'])

    def test_p4_empty_nonapplicability_reason_is_rejected(self):
        value = control_fixture()
        value['negative_controls_and_ablation']['controls'][0].update(applicable=False, passed=False)
        self.assertFalse(gate.evaluate_p4(value)['passed'])

    def test_p4_omitting_required_kind_is_still_rejected(self):
        value = control_fixture()
        value['negative_controls_and_ablation']['controls'].pop()
        self.assertFalse(gate.evaluate_p4(value)['passed'])

    def test_p4_other_applicable_failure_is_not_excused(self):
        value = control_fixture()
        value['negative_controls_and_ablation']['controls'][0]['passed'] = False
        self.assertFalse(gate.evaluate_p4(value)['passed'])

    def test_p4_holdout_is_not_development_control_evidence(self):
        value = control_fixture()
        value['negative_controls_and_ablation']['holdout_outcomes_used'] = True
        self.assertFalse(gate.evaluate_p4(value)['passed'])

    def test_p5_zero_provider_reviews_cannot_pass(self):
        self.assertFalse(gate.evaluate_p5(review_fixture([]))['passed'])

    def test_p5_same_provider_twice_is_not_two_independent_reviews(self):
        self.assertFalse(gate.evaluate_p5(review_fixture(['fixture_a', 'FIXTURE_A']))['passed'])

    def test_p5_two_distinct_complete_test_reviews_check_structure_only(self):
        self.assertTrue(gate.evaluate_p5(review_fixture(['fixture_a', 'fixture_b']))['passed'])

    def test_p5_missing_real_lineage_fields_remains_failure(self):
        value = review_fixture(['fixture_a', 'fixture_b'])
        del value['multi_ai_adversarial_review']['provider_reviews'][0]['response_sha']
        self.assertFalse(gate.evaluate_p5(value)['passed'])

    def test_p6_development_history_does_not_require_current_tick_freshness(self):
        value = development_fixture()
        self.assertTrue(gate.evaluate_p6(value)['passed'])
        self.assertEqual(value['source_implementation_reality']['formal_production_credit'], 0)

    def test_p6_development_missing_prefrozen_split_still_fails(self):
        value = development_fixture()
        value['source_implementation_reality']['split_frozen_before_outcomes'] = False
        self.assertFalse(gate.evaluate_p6(value)['passed'])

    def test_p6_live_source_mode_still_requires_fresh_source(self):
        value = development_fixture()
        value['source_implementation_reality']['admission_stage'] = 'FRESH_ONLY'
        self.assertFalse(gate.evaluate_p6(value)['passed'])

    def test_p6_unvalidated_cost_or_source_proxy_cannot_pass(self):
        value = development_fixture()
        value['source_implementation_reality']['sources'][0]['proxy'] = True
        self.assertFalse(gate.evaluate_p6(value)['passed'])

    def test_actual_kr3_callback_binds_without_loading_market_data(self):
        from backend.research.rebuild.step7_callable_binding_v1 import producer_binding
        from backend.research.rebuild.step7_kr3_execution_v1 import execute_sealed_bytes
        digest, name = producer_binding(execute_sealed_bytes)
        self.assertEqual(len(digest), 64)
        self.assertEqual(name, 'backend.research.rebuild.step7_kr3_execution_v1:execute_sealed_bytes')


if __name__ == '__main__':
    unittest.main()
