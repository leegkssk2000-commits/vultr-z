"""Free counterexamples for V5 scope binding; all HTTP transports are fake."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from backend.research.rebuild import api_winrate_runtime_v1 as v5
from backend.research.rebuild.lifecycle_task_v1 import Registry, GateError, digest


class Store:
    def __init__(self, data, fail=False):
        self.data, self.fail, self.writes = deepcopy(data), fail, 0

    def read(self):
        return str(self.writes), deepcopy(self.data)

    def compare_and_swap(self, sha, data):
        if self.fail:
            raise GateError('DURABLE_WRITE_UNCONFIRMED')
        self.writes += 1
        self.data = deepcopy(data)
        return 'fake-reservation-commit'


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        path = self.root / 'tasks.json'
        registry = Registry(path)
        for scope in (*v5.PRIOR_SCOPES, v5.SCOPE):
            registry.register(scope, 'TEST_ONLY')
        self.data = json.loads(path.read_text())
        self.data.update(budget_scope=v5.old.PRIOR, inherited_task_sha256='inherited-test-sha')
        for scope in v5.PRIOR_SCOPES:
            self.data['tasks'][scope].update(task_status='COMPLETED', report_only=True, further_dispatch_allowed=False)
            self.data['tasks'][scope]['work']['W2'] = {'status': 'NOT_RUN', 'evidence': 'prior frozen'}
        self.task = deepcopy(self.data['tasks'][v5.SCOPE])
        self.prior_digests = {scope: digest(self.data['tasks'][scope]) for scope in v5.PRIOR_SCOPES}

    def registry(self, store):
        return v5.DurableRegistry(store, 'inherited-test-sha', self.prior_digests)

    def package(self):
        runtime = v5.bound_runtime()
        source = self.root / 'current-dev.json'
        source.write_text('{"diagnosis":"unresolved entry quality"}')
        sources = {'current-dev.json': hashlib.sha256(source.read_bytes()).hexdigest()}
        folder = self.root / v5.OUTPUT
        folder.mkdir(parents=True)
        (folder / 'SOURCE_ALLOWLIST.json').write_text(json.dumps({'source_hashes': sources}))
        dossier = {'scope_key': v5.SCOPE, 'data_class': 'DEV_USED', 'holdout_access': False,
                   'source_hashes': sources, 'question': 'Distinct low-win-rate question'}
        quote = {'provider': 'gemini', 'model': 'gemini-2.5-flash', 'currency': 'USD',
                 'request_semantics_verified': True, 'input_token_upper_bound': 1048576,
                 'output_thinking_upper_bound': 6000, 'input_usd_per_million': .3,
                 'output_usd_per_million': 2.5, 'official_sources': ['TEST_FIXTURE_ONLY'],
                 'checked_at': 'TEST_FIXTURE_ONLY'}
        approval = {'scope_key': v5.SCOPE, 'approval_id': 'TEST_ONLY', 'explicit_manual_approval': True,
                    'provider': 'gemini', 'model': quote['model'], 'price_sha': digest(quote),
                    'dossier_sha': digest(dossier), 'unresolved_question_required': True,
                    'tax_fx_upper_bound_usd': 1, 'billing_upper_bound_authority': 'TEST_FIXTURE_ONLY'}
        return runtime, dossier, approval, quote

    def test_binding_keeps_prior_and_existing_task(self):
        before = deepcopy(self.data)
        del before['tasks'][v5.SCOPE]
        bound = v5.bind_scope(before, self.task)
        for scope in v5.PRIOR_SCOPES:
            self.assertEqual(before['tasks'][scope], bound['tasks'][scope])
        stale = deepcopy(self.task)
        stale['work']['W2']['status'] = 'DONE'
        self.assertEqual(bound, v5.bind_scope(bound, stale))

    def test_new_binding_cannot_import_unbound_paid_activity(self):
        before = deepcopy(self.data)
        del before['tasks'][v5.SCOPE]
        self.task['paid_requests']['gemini'] = 1
        with self.assertRaisesRegex(GateError, 'UNBOUND_PRIOR_API_ACTIVITY'):
            v5.bind_scope(before, self.task)

    def test_prior_work_cannot_reopen(self):
        after = deepcopy(self.data)
        after['tasks'][v5.old.SCOPE]['work']['W2']['status'] = 'PENDING'
        with self.assertRaisesRegex(GateError, 'PRIOR_SCOPE_FROZEN'):
            v5.validate_transition(self.data, after)

    def test_shared_provider_count_cannot_reset(self):
        self.data['tasks'][v5.old.PRIOR]['paid_requests']['gemini'] = 1
        self.prior_digests = {scope: digest(self.data['tasks'][scope]) for scope in v5.PRIOR_SCOPES}
        store = Store(self.data)
        with self.assertRaisesRegex(GateError, 'SHARED_CUMULATIVE_BUDGET'):
            self.registry(store).reserve(v5.SCOPE, 'W2', 'api', {'question': 'new'}, provider='gemini', reserve_usd=1)
        self.assertEqual(store.writes, 0)

    def test_prior_unknown_reservation_blocks_new_provider(self):
        prior = self.data['tasks'][v5.old.PRIOR]
        prior['billing_status'] = 'UNKNOWN'
        prior['outstanding_reserved_cost'] = 1
        self.prior_digests = {scope: digest(self.data['tasks'][scope]) for scope in v5.PRIOR_SCOPES}
        with self.assertRaisesRegex(GateError, 'UNRECONCILED_SHARED_RESERVATION'):
            self.registry(Store(self.data)).reserve(v5.SCOPE, 'W2', 'api', {'question': 'new'}, provider='openai', reserve_usd=1)

    def test_shared_dollar_budget_is_cumulative(self):
        self.data['tasks'][v5.old.PRIOR]['settled_cost'] = 4.5
        self.prior_digests = {scope: digest(self.data['tasks'][scope]) for scope in v5.PRIOR_SCOPES}
        with self.assertRaisesRegex(GateError, 'SHARED_CUMULATIVE_BUDGET'):
            self.registry(Store(self.data)).reserve(v5.SCOPE, 'W2', 'api', {'question': 'new'}, provider='gemini', reserve_usd=1)

    def test_binding_does_not_mutate_frozen_runtime(self):
        runtime = v5.bound_runtime()
        self.assertNotEqual(runtime.SCOPE, v5.old.SCOPE)
        self.assertEqual(runtime.LEDGER_PATH, v5.old.LEDGER_PATH)
        self.assertEqual(v5.old.SCOPE, 'TOP5_AFTER_PR1205_CUMULATIVE_DEV_G5_SUBAGENTS_V1')

    def test_unknown_billing_blocks_before_transport(self):
        runtime, dossier, approval, quote = self.package()
        approval['tax_fx_upper_bound_usd'] = None
        with self.assertRaisesRegex(GateError, 'BILLING_COMPONENT_UNKNOWN'):
            runtime.preflight(dossier, approval, quote, event='workflow_dispatch', key_present=True)

    def test_failed_reservation_never_reaches_provider(self):
        runtime, dossier, approval, quote = self.package()
        seen = []
        with self.assertRaisesRegex(GateError, 'DURABLE_WRITE_UNCONFIRMED'):
            runtime.request_once(self.registry(Store(self.data, fail=True)), dossier, approval, quote,
                                 event='workflow_dispatch', key='FAKE_TEST_KEY', root=self.root,
                                 transport=lambda *args, **kwargs: seen.append(args))
        self.assertEqual(seen, [])

    def test_timeout_counts_once_and_preserves_prior_work(self):
        runtime, dossier, approval, quote = self.package()
        store, seen = Store(self.data), []
        def timeout(request, **kwargs):
            seen.append(request)
            raise TimeoutError()
        result = runtime.request_once(self.registry(store), dossier, approval, quote,
                                      event='workflow_dispatch', key='FAKE_TEST_KEY', root=self.root, transport=timeout)
        self.assertEqual(len(seen), 1)
        self.assertEqual(result['billing_status'], 'UNKNOWN')
        self.assertIsNone(result['settled_usd'])
        self.assertEqual(store.data['tasks'][v5.SCOPE]['paid_requests']['gemini'], 1)
        self.assertEqual(store.data['tasks'][v5.SCOPE]['work']['W2']['status'], 'RUNNING')
        for scope in v5.PRIOR_SCOPES:
            self.assertEqual(store.data['tasks'][scope], self.data['tasks'][scope])
        body = json.loads(seen[0].data)
        self.assertEqual(seen[0].full_url, 'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent')
        self.assertEqual(body['generationConfig']['thinkingConfig']['thinkingBudget'], 0)
        self.assertEqual(body['generationConfig']['maxOutputTokens'], 6000)
        self.assertEqual(body['generationConfig']['candidateCount'], 1)


if __name__ == '__main__':
    unittest.main()
