"""KR3 route regression: saved DEV summaries, synthetic store/HTTP, no paid calls."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from backend.research.rebuild import step7_kr3_review_route_v1 as route
from backend.research.rebuild.lifecycle_task_v1 import Registry, GateError, digest
from backend.research.rebuild.test_api_winrate_runtime_v1 import Store


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        registry = Registry(self.root / 'tasks.json')
        for scope in (*route.PRIOR_SCOPES, route.SCOPE):
            registry.register(scope, 'SYNTHETIC_TEST_ONLY')
        self.data = json.loads((self.root / 'tasks.json').read_text())
        self.data.update(budget_scope=route.previous.old.PRIOR, inherited_task_sha256='synthetic')
        for scope in route.PRIOR_SCOPES:
            self.data['tasks'][scope].update(task_status='COMPLETED', report_only=True, further_dispatch_allowed=False)
            self.data['tasks'][scope]['work']['W2'] = {'status': 'NOT_RUN', 'evidence': 'prior frozen'}
        source = self.root / 'used-dev.json'
        source.write_text('{"fact":"KR3 synthetic isolation fixture"}')
        sources = {'used-dev.json': hashlib.sha256(source.read_bytes()).hexdigest()}
        # Copy only already-used DEV summaries to the synthetic transport fixture.
        # No native replay, protected source read or real provider call occurs.
        for name in route.MEASURED_INPUTS:
            rel = route.DEV_OUTPUT / name
            target = self.root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((route.ROOT / rel).read_bytes())
            sources[str(rel)] = hashlib.sha256(target.read_bytes()).hexdigest()
        folder = self.root / route.OUTPUT
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'SOURCE_ALLOWLIST.json').write_text(json.dumps({'source_hashes': sources}))
        self.dossier = {'scope_key': route.SCOPE, 'data_class': 'DEV_USED', 'holdout_access': False,
                        'source_hashes': sources, 'candidate_sha256': route.CANDIDATE,
                        'candidate_mode': 'FULL', 'purpose': route.PURPOSE, 'campaign_key': route.CAMPAIGN,
                        'actual_dev_validation': route.measured_facts(self.root)}
        self.quote = {'provider': 'gemini', 'model': 'gemini-2.5-flash', 'currency': 'USD',
                      'request_semantics_verified': True, 'input_token_upper_bound': 1048576,
                      'output_thinking_upper_bound': 6000, 'input_usd_per_million': .3,
                      'output_usd_per_million': 2.5, 'official_sources': ['SYNTHETIC_ONLY'],
                      'checked_at': datetime.now(timezone.utc).date().isoformat()}
        self.approval = {'scope_key': route.SCOPE, 'approval_id': 'SYNTHETIC_NOT_USER_APPROVAL',
                         'explicit_manual_approval': True, 'template_only': False,
                         'provider': 'gemini', 'model': self.quote['model'], 'price_sha': digest(self.quote),
                         'candidate_sha256': route.CANDIDATE, 'purpose': route.PURPOSE,
                         'dossier_sha': digest(self.dossier), 'unresolved_question_required': True,
                         'tax_fx_upper_bound_usd': 1, 'billing_upper_bound_authority': 'SYNTHETIC_ONLY'}

    def request(self, store, transport):
        prior = {scope: digest(store.data['tasks'][scope]) for scope in route.PRIOR_SCOPES}
        registry = route.bound_owner().DurableRegistry(store, 'synthetic', prior)
        return route.request_once(registry, self.dossier, self.approval, self.quote,
                                  event='workflow_dispatch', key='SYNTHETIC_KEY',
                                  root=self.root, transport=transport)

    def test_proposed_binding_preserves_three_prior_scopes(self):
        prior = deepcopy(self.data)
        task = prior['tasks'].pop(route.SCOPE)
        bound = route.bind_scope(prior, task)
        self.assertEqual(bound, self.data)
        self.assertEqual(set(prior['tasks']), set(route.PRIOR_SCOPES))
        self.assertEqual(route.bind_scope(bound, task), bound)

    def test_previous_provider_attempt_blocks_without_post(self):
        self.data['tasks'][route.previous.SCOPE]['paid_requests']['gemini'] = 1
        calls, store = [], Store(self.data)
        with self.assertRaisesRegex(GateError, 'SHARED_CUMULATIVE_BUDGET'):
            self.request(store, lambda *a, **k: calls.append(a))
        self.assertEqual((calls, store.writes), ([], 0))

    def test_unknown_previous_charge_blocks_other_provider(self):
        self.data['tasks'][route.previous.SCOPE]['billing_status'] = 'UNKNOWN'
        calls, store = [], Store(self.data)
        with self.assertRaisesRegex(GateError, 'UNRECONCILED_SHARED_RESERVATION'):
            self.request(store, lambda *a, **k: calls.append(a))
        self.assertEqual((calls, store.writes), ([], 0))

    def test_candidate_and_purpose_cannot_reuse_other_dossier(self):
        self.dossier['candidate_sha256'] = 'TPQ1'
        with self.assertRaisesRegex(GateError, 'EXACT_KR3_PURPOSE_IDENTITY_REQUIRED'):
            self.request(Store(self.data), None)
        self.dossier['candidate_sha256'] = route.CANDIDATE
        self.approval['purpose'] = 'OLD_CANDIDATE_REVIEW'
        with self.assertRaisesRegex(GateError, 'EXACT_KR3_PURPOSE_IDENTITY_REQUIRED'):
            self.request(Store(self.data), None)

    def test_template_and_stale_price_block_before_reservation(self):
        self.approval['template_only'] = True
        store = Store(self.data)
        with self.assertRaisesRegex(GateError, 'REAL_MANUAL_PACKAGE_REQUIRED'):
            self.request(store, None)
        self.approval['template_only'] = False
        self.quote['checked_at'] = '2025-01-01'
        with self.assertRaisesRegex(GateError, 'CURRENT_OFFICIAL_QUOTE_REQUIRED'):
            self.request(store, None)
        self.assertEqual(store.writes, 0)

    def test_holdout_and_source_mutation_are_denied(self):
        self.dossier['holdout_access'] = True
        with self.assertRaisesRegex(GateError, 'CURRENT_DEV_ISOLATION'):
            self.request(Store(self.data), None)
        self.dossier['holdout_access'] = False
        (self.root / 'used-dev.json').write_text('changed')
        with self.assertRaisesRegex(GateError, 'DEV_SOURCE_BYTES'):
            self.request(Store(self.data), None)

    def test_cas_failure_has_zero_provider_posts(self):
        calls = []
        with self.assertRaisesRegex(GateError, 'DURABLE_WRITE_UNCONFIRMED'):
            self.request(Store(self.data, fail=True), lambda *a, **k: calls.append(a))
        self.assertEqual(calls, [])

    def test_timeout_reserved_once_and_does_not_reset_any_prior_scope(self):
        store, calls = Store(self.data), []
        def timeout(request, **kwargs):
            calls.append(request)
            raise TimeoutError()
        receipt = self.request(store, timeout)
        self.assertEqual(receipt['billing_status'], 'UNKNOWN')
        self.assertEqual(len(calls), 1)
        self.assertEqual(store.data['tasks'][route.SCOPE]['paid_requests']['gemini'], 1)
        for scope in route.PRIOR_SCOPES:
            self.assertEqual(store.data['tasks'][scope], self.data['tasks'][scope])
        prompt = json.loads(json.loads(calls[0].data)['contents'][0]['parts'][0]['text'])
        self.assertEqual(prompt['candidate_sha256'], route.CANDIDATE)
        self.assertEqual(prompt['purpose'], route.PURPOSE)
        self.assertEqual(prompt['actual_dev_validation'], self.dossier['actual_dev_validation'])
        with self.assertRaises(GateError):
            self.request(store, timeout)
        self.assertEqual(len(calls), 1)

    def test_missing_account_cap_is_not_zero(self):
        self.approval['tax_fx_upper_bound_usd'] = None
        store = Store(self.data)
        with self.assertRaisesRegex(GateError, 'BILLING_COMPONENT_UNKNOWN'):
            self.request(store, None)
        self.assertEqual(store.writes, 0)

    def test_previous_namespace_and_canonical_path_unchanged(self):
        owner = route.bound_owner()
        self.assertEqual(owner.bound_runtime().SCOPE, route.SCOPE)
        self.assertEqual(owner.bound_runtime().LEDGER_PATH, route.LEDGER_PATH)
        self.assertEqual(route.previous.SCOPE, 'TOP5_AFTER_PR1206_WINRATE_FIRST_AI_V1')
        self.assertEqual(len(route.previous.PRIOR_SCOPES), 2)

    def assert_blocked_without_reservation(self, reason):
        store, calls = Store(self.data), []
        with self.assertRaisesRegex(GateError, reason):
            self.request(store, lambda *a, **k: calls.append(a))
        self.assertEqual((calls, store.writes), ([], 0))

    def test_missing_actual_results_cannot_consume_provider(self):
        self.dossier.pop('actual_dev_validation')
        self.approval['dossier_sha'] = digest(self.dossier)
        self.assert_blocked_without_reservation('ACTUAL_DEV_PROMPT_MISSING_OR_CHANGED')

    def test_counterexample_omission_cannot_hide_behind_new_prompt_hash(self):
        self.dossier['actual_dev_validation']['rows'].pop(1)
        self.approval['dossier_sha'] = digest(self.dossier)
        self.assert_blocked_without_reservation('ACTUAL_DEV_PROMPT_MISSING_OR_CHANGED')

    def test_edited_counterexample_number_is_denied(self):
        self.dossier['actual_dev_validation']['rows'][1][7] = 0
        self.approval['dossier_sha'] = digest(self.dossier)
        self.assert_blocked_without_reservation('ACTUAL_DEV_PROMPT_MISSING_OR_CHANGED')

    def test_missing_g5a_result_source_is_denied(self):
        self.dossier['source_hashes'].pop(str(route.DEV_OUTPUT / 'G5A_RESULT.json'))
        self.assert_blocked_without_reservation('MEASURED_DEV_SOURCE_BINDING')

    def test_stale_saved_result_bytes_are_denied(self):
        path = self.root / route.DEV_OUTPUT / 'VARIANTS/INDEX.json'
        path.write_bytes(path.read_bytes() + b' ')
        self.assert_blocked_without_reservation('MEASURED_DEV_SOURCE_BINDING')

    def test_regenerated_prompt_still_has_exact_twelve_unique_variants(self):
        facts = self.dossier['actual_dev_validation']
        self.assertEqual(tuple(row[0] for row in facts['rows']), route.VARIANT_IDS)
        self.assertEqual([row[1] for row in facts['rows']], list(range(45, 57)))
        self.assertFalse(facts['independent'])
        self.assertEqual(facts['formal_credit'], 0)
        self.assertEqual(facts['g5a_state'], 'HOLD_ALPHA_PROOF')

    def test_committed_dossier_is_actual_complete_and_within_original_byte_budget(self):
        folder = route.ROOT / route.OUTPUT
        dossier = json.loads((folder / 'DOSSIER.json').read_bytes())
        template = json.loads((folder / 'API_APPROVAL_TEMPLATE.json').read_bytes())
        route.verify_measured(dossier)
        self.assertEqual(template['dossier_sha'], digest(dossier))
        self.assertTrue(template['template_only'])
        self.assertFalse(template['explicit_manual_approval'])
        self.assertEqual(dossier['source_hashes'], json.loads((folder / 'SOURCE_ALLOWLIST.json').read_bytes())['source_hashes'])
        self.assertLessEqual(len(json.dumps(dossier, sort_keys=True, ensure_ascii=False).encode()), 16000)

    def test_openai_actual_outcomes_are_in_transmitted_input(self):
        self.quote.update(provider='openai', model='gpt-4.1-mini-2025-04-14')
        self.approval.update(provider='openai', model=self.quote['model'], price_sha=digest(self.quote))
        store, calls = Store(self.data), []
        def timeout(request, **kwargs):
            calls.append(request)
            raise TimeoutError()
        self.request(store, timeout)
        prompt = json.loads(json.loads(calls[0].data)['input'])
        self.assertEqual(prompt['actual_dev_validation'], self.dossier['actual_dev_validation'])
        self.assertEqual(len(calls), 1)


if __name__ == '__main__':
    unittest.main()
