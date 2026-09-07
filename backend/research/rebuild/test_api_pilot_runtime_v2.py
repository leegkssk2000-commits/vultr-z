"""Free synthetic regression: no provider network, no market replay."""
from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend.research.rebuild.lifecycle_task_v1 import Registry, GateError, digest
from backend.research.rebuild import api_pilot_runtime_v2 as api


class Store:
    def __init__(self, data):
        self.data = deepcopy(data)
        self.version = 1
        self.lose_reply = False
        self.conflict = False
    def read(self):
        return str(self.version), deepcopy(self.data)
    def compare_and_swap(self, sha, data):
        if sha != str(self.version) or self.conflict:
            raise GateError('CONFLICT')
        self.data = deepcopy(data)
        self.version += 1
        if self.lose_reply:
            raise TimeoutError()
        return 'commit-' + str(self.version)


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        path = Path(self.temp.name) / 'task.json'
        registry = Registry(path)
        registry.register(api.PRIOR, 'fixture')
        registry.register(api.SCOPE, 'fixture')
        data = json.loads(path.read_text())
        data.update(budget_scope=api.PRIOR, inherited_task_sha256='old-source')
        data['tasks'][api.PRIOR].update(task_status='COMPLETED', report_only=True, further_dispatch_allowed=False)
        self.store = Store(data)
        self.registry = api.DurableRegistry(self.store, 'old-source')

    def reserve(self, provider='gemini', identity=None, amount=1):
        return self.registry.reserve(api.SCOPE, 'W2', 'api', identity or {'provider': provider}, provider=provider, reserve_usd=amount)

    def package(self):
        dossier = {'scope_key': api.SCOPE, 'data_class': 'DEV_USED', 'holdout_access': False,
                   'source_hashes': {'fixture': 'sha'}, 'purpose': 'synthetic unresolved counterexample'}
        quote = {'provider': 'openai', 'model': api.MODELS['openai'], 'currency': 'USD',
                 'request_semantics_verified': True, 'official_sources': ['fixture-only'], 'checked_at': 'fixture',
                 'input_token_upper_bound': 1047576, 'output_thinking_upper_bound': 6000,
                 'input_usd_per_million': 0.4, 'output_usd_per_million': 1.6}
        approval = {'scope_key': api.SCOPE, 'approval_id': 'fixture', 'explicit_manual_approval': True,
                    'provider': 'openai', 'model': api.MODELS['openai'], 'price_sha': digest(quote),
                    'dossier_sha': digest(dossier), 'unresolved_question_required': True,
                    'tax_fx_upper_bound_usd': 0, 'billing_upper_bound_authority': 'synthetic-only'}
        return dossier, approval, quote

    def test_restart_same_identity_never_reissues(self):
        self.reserve()
        self.registry = api.DurableRegistry(self.store, 'old-source')
        with self.assertRaisesRegex(GateError, 'IDENTITY_ALREADY'):
            self.reserve()
        self.assertEqual(self.store.data['tasks'][api.SCOPE]['paid_requests']['gemini'], 1)

    def test_lost_cas_reply_preserves_burned_reservation(self):
        self.store.lose_reply = True
        with self.assertRaises(TimeoutError):
            self.reserve()
        self.store.lose_reply = False
        with self.assertRaises(GateError):
            self.reserve()
        self.assertEqual(self.store.data['tasks'][api.SCOPE]['outstanding_reserved_cost'], 1)

    def test_concurrent_stale_cas_no_commit(self):
        self.store.conflict = True
        with self.assertRaisesRegex(GateError, 'CONFLICT'):
            self.reserve()
        self.assertEqual(self.store.data['tasks'][api.SCOPE]['paid_requests']['gemini'], 0)

    def test_interleaved_transactions_have_one_winner(self):
        # Both readers hold version 1; the inner transaction wins version 2.
        with self.assertRaisesRegex(GateError, 'CONFLICT'):
            with self.registry.transaction() as stale:
                stale['tasks'][api.SCOPE]['last_real_progress_at'] = 'stale'
                self.reserve()
        self.assertEqual(self.store.version, 2)
        self.assertEqual(self.store.data['tasks'][api.SCOPE]['paid_requests']['gemini'], 1)

    def test_actual_inherited_task_cannot_be_forged_by_hash_label(self):
        inherited = deepcopy(self.store.data['tasks'][api.PRIOR])
        self.registry = api.DurableRegistry(self.store, 'old-source', inherited)
        self.store.data['tasks'][api.PRIOR]['settled_cost'] = 0.1
        with self.assertRaisesRegex(GateError, 'INHERITED_TASK_BYTES_CHANGED'):
            self.reserve()

    def test_previous_scope_provider_count_cannot_reset(self):
        self.store.data['tasks'][api.PRIOR]['paid_requests']['gemini'] = 1
        with self.assertRaisesRegex(GateError, 'SHARED_CUMULATIVE_BUDGET'):
            self.reserve()

    def test_previous_scope_money_is_cumulative(self):
        self.store.data['tasks'][api.PRIOR]['settled_cost'] = 4.5
        with self.assertRaisesRegex(GateError, 'SHARED_CUMULATIVE_BUDGET'):
            self.reserve(amount=1)

    def test_unknown_prior_billing_blocks_other_provider(self):
        self.store.data['tasks'][api.PRIOR]['billing_status'] = 'UNKNOWN'
        with self.assertRaisesRegex(GateError, 'UNRECONCILED_SHARED'):
            self.reserve()

    def test_reserved_first_provider_blocks_concurrent_second(self):
        self.reserve()
        with self.assertRaisesRegex(GateError, 'UNRECONCILED_SHARED'):
            self.reserve('openai')

    def test_settlement_requires_existing_registry_proof_not_usage(self):
        key = self.reserve()
        self.registry.finish_attempt(api.SCOPE, key, 'DONE', evidence={'usage': {'tokens': 1}})
        task = self.store.data['tasks'][api.SCOPE]
        self.assertEqual(task['billing_status'], 'UNKNOWN')
        self.assertEqual(task['outstanding_reserved_cost'], 1)

    def test_missing_old_scope_and_bad_seed_fail_closed(self):
        del self.store.data['tasks'][api.PRIOR]
        with self.assertRaisesRegex(GateError, 'BOTH_SHARED_SCOPES'):
            self.reserve()

    def test_free_preflight_token_bound_and_blockers(self):
        d, a, q = self.package()
        plan = api.preflight(d, a, q, event='workflow_dispatch', key_present=True)
        self.assertAlmostEqual(plan['maximum_reserved_usd'], .4286304)
        for event, key in [('push', True), ('pull_request', True), ('workflow_dispatch', False)]:
            with self.assertRaises(GateError):
                api.preflight(d, a, q, event=event, key_present=key)
        q['request_semantics_verified'] = False
        a['price_sha'] = digest(q)
        with self.assertRaisesRegex(GateError, 'TOKEN_LIMIT'):
            api.preflight(d, a, q, event='workflow_dispatch', key_present=True)

    def test_provider_timeout_no_retry_unknown_and_reserved(self):
        d, a, q = self.package()
        calls = []
        def timeout(req, **kwargs):
            calls.append(json.loads(req.data))
            raise TimeoutError('do not expose keys')
        with patch.object(api, 'verify_sources'):
            receipt = api.request_once(self.registry, d, a, q, event='workflow_dispatch', key='fixture', transport=timeout)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]['max_output_tokens'], 6000)
        self.assertEqual(calls[0]['tools'], [])
        self.assertEqual(receipt['billing_status'], 'UNKNOWN')
        self.assertEqual(receipt['error_type'], 'TimeoutError')
        self.assertNotIn('do not expose', str(receipt))
        self.assertGreater(self.store.data['tasks'][api.SCOPE]['outstanding_reserved_cost'], 0)

    def test_provider_not_called_after_cas_failure(self):
        d, a, q = self.package()
        self.store.lose_reply = True
        with patch.object(api, 'verify_sources'), patch.object(api.urllib.request, 'build_opener') as network:
            with self.assertRaises(TimeoutError):
                api.request_once(self.registry, d, a, q, event='workflow_dispatch', key='fixture')
            network.assert_not_called()

    def test_prior_scope_bytes_unchanged(self):
        before = deepcopy(self.store.data['tasks'][api.PRIOR])
        self.reserve()
        self.assertEqual(before, self.store.data['tasks'][api.PRIOR])


if __name__ == '__main__':
    unittest.main()
