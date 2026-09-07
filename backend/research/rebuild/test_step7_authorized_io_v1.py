"""New P1 tests only. All approvals/inputs are synthetic and fixture-only."""
import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from backend.research.rebuild import step7_authorized_io_v1 as io
from backend.research.rebuild import step7_independent_validation_v1 as old


def producer(raw):
    return {'rows': len(json.loads(raw)), 'formal_credit': 0}


class AuthorizedIOTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.keys = tempfile.TemporaryDirectory(prefix='step7-fixture-keys-')
        cls.key_path = Path(cls.keys.name) / 'key.pem'
        subprocess.run(['openssl', 'genpkey', '-algorithm', 'ED25519', '-out', str(cls.key_path)],
                       check=True, capture_output=True)
        cls.public = subprocess.run(['openssl', 'pkey', '-in', str(cls.key_path), '-pubout'],
                                    check=True, capture_output=True).stdout.decode()

    @classmethod
    def tearDownClass(cls):
        cls.keys.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='step7-fixture-journal-')
        self.addCleanup(self.temp.cleanup)
        self.journal = Path(self.temp.name)
        self.calls = {'read': 0, 'dispatch': 0}
        self.raw = b'[{"synthetic":true}]'
        self.identity = {key: 'a'*64 for key in old.IDENTITY}
        self.identity['candidate_id'] = old.CANDIDATE
        self.roles = {'developers': ['root', 'S1', 'S2', 'S3', 'S4'],
                      'validator': 'independent-fixture-only',
                      'validator_may_propose_hypotheses': False, 'ai_holdout_access': False}
        self.design = {'status': 'APPROVED', 'candidate_count': 1, 'bundle_count': 1,
                       'reports': list(old.REPORTS), 'source_class': 'FORWARD_UNCOLLECTED',
                       'windows': [{'name': 'W'+str(i+1), 'start_ms': 100+i*100,
                                    'end_ms': 200+i*100} for i in range(3)],
                       'review_ms': 500, 'terminal_looks': 1}
        for key in ('purge_rule_sha', 'runoff_rule_sha', 'regime_rule_sha', 'control_rule_sha',
                    'neighbor_rule_sha', 'statistics_rule_sha', 'source_authority_sha',
                    'retention_baseline_sha', 'shared_gate_sha'):
            self.design[key] = 'b'*64
        self.campaign = {'logical_purpose': old.PURPOSE, 'old_candidates': 44,
                         'independent_validation': {'max_bundles': 1, 'used': 0,
                                                    'reservations': [], 'exposed_data_shas': []}}
        self.trust = {'approval_principal': 'EXTERNAL_FIXTURE_SIGNER',
                      'validator_principal': self.roles['validator'],
                      'keys': {'fixture-ed25519': {'principal': 'EXTERNAL_FIXTURE_SIGNER',
                                                   'status': 'ACTIVE', 'public_key_pem': self.public}},
                      'revoked_approval_ids': []}
        self.source = old.seal({'source_definition_sha': 'a'*64, 'cost_sha': 'a'*64,
                                'data_sha': hashlib.sha256(self.raw).hexdigest(),
                                'classification': 'HOLDOUT_SEALED', 'unused_history_verified': True,
                                'prior_performance_exposures': 0, 'windows': self.design['windows'],
                                'complete': True})
        self.request = {'identity': self.identity, 'design': self.design, 'roles': self.roles,
                        'source': self.source, 'registered_ms': 100, 'data_relpath': 'fixture.json'}
        code_sha, qualname = io._producer_binding(producer)
        binding = {'scope': old.PURPOSE, 'identity_sha': old.sha(self.identity),
                   'design_sha': old.sha(self.design), 'roles_sha': old.sha(self.roles),
                   'source_sha': old.sha(self.source), 'campaign_sha': old.sha(self.campaign),
                   'data_relpath': 'fixture.json', 'data_sha': self.source['data_sha'],
                   'producer_code_sha256': code_sha, 'producer_qualname': qualname,
                   'registered_ms': 100, 'max_reads': 1, 'max_dispatches': 1}
        self.payload = {'schema': io.SCHEMA, 'status': 'APPROVED', 'fixture_only': True,
                        'principal': 'EXTERNAL_FIXTURE_SIGNER', 'approval_id': 'fixture-001',
                        'not_before_ms': 0, 'expires_ms': 1000, 'binding': binding}
        self.sign()

    def sign(self):
        path = self.journal / 'payload-for-signing'
        path.write_bytes(io._json_bytes(self.payload))
        signature = subprocess.run(['openssl', 'pkeyutl', '-sign', '-inkey', str(self.key_path),
                                    '-rawin', '-in', str(path)], check=True, capture_output=True).stdout
        self.request['signed_approval'] = {'payload': deepcopy(self.payload), 'key_id': 'fixture-ed25519',
                                          'signature_b64': base64.b64encode(signature).decode()}

    def reader(self, request, trust):
        self.calls['read'] += 1
        reservations = list(self.journal.glob('*.reservation.json'))
        self.assertEqual(len(reservations), 1)
        saved = json.loads(reservations[0].read_text())
        self.assertEqual(saved['campaign_after_reservation']['independent_validation']['used'], 1)
        return self.raw

    def execute(self):
        return io._execute(self.request, producer, self.trust, self.campaign, self.journal,
                           500, self.reader, fixture=True)

    def reject_before_read(self, reason):
        with self.assertRaisesRegex(ValueError, reason):
            self.execute()
        self.assertEqual(self.calls['read'], 0)
        self.assertFalse(list(self.journal.glob('*.reservation.json')))

    def test_normal_signed_fixture_reserves_before_io_and_dispatches(self):
        result = self.execute()
        self.assertEqual(result['output']['rows'], 1)
        self.assertEqual(result['access_receipt']['formal_credit'], 0)
        self.assertTrue(result['access_receipt']['fixture_only'])
        self.assertEqual(self.calls['read'], 1)
        self.assertEqual(self.campaign['independent_validation']['used'], 0)

    def test_self_hash_authority_cannot_authenticate(self):
        forged = old.seal({'principal': 'USER', 'status': 'APPROVED', 'design_sha': old.sha(self.design)})
        self.request['signed_approval'] = {'payload': forged, 'authenticated_authority_sha': old.sha(forged)}
        self.reject_before_read('SIGNED_EXTERNAL_APPROVAL_REQUIRED')

    def test_matching_forged_payload_digest_does_not_replace_signature(self):
        self.request['signed_approval']['payload']['binding']['scope'] = 'ATTACKER'
        self.request['signed_approval']['signature_b64'] = base64.b64encode(b'x'*64).decode()
        self.reject_before_read('INVALID_EXTERNAL_SIGNATURE')

    def test_another_approver_even_valid_signature_is_rejected(self):
        self.payload['principal'] = 'OTHER_USER'
        self.sign()
        self.reject_before_read('WRONG_APPROVAL_PRINCIPAL')

    def test_candidate_design_scope_code_cost_and_budget_are_bound(self):
        for field, value in [('scope', 'OTHER_SCOPE'), ('identity_sha', 'c'*64),
                             ('design_sha', 'c'*64), ('producer_code_sha256', 'c'*64),
                             ('source_sha', 'c'*64), ('campaign_sha', 'c'*64), ('max_reads', 2)]:
            with self.subTest(field=field):
                original = deepcopy(self.payload)
                self.payload['binding'][field] = value
                self.sign()
                self.reject_before_read('APPROVAL_EXACT_BINDING_MISMATCH')
                self.payload = original

    def test_expired_approval_is_rejected(self):
        self.payload['expires_ms'] = 500
        self.sign()
        self.reject_before_read('EXPIRED_OR_NOT_YET_VALID_APPROVAL')

    def test_revoked_approval_and_revoked_key_are_rejected(self):
        self.trust['revoked_approval_ids'] = ['fixture-001']
        self.reject_before_read('REVOKED_APPROVAL')
        self.trust['revoked_approval_ids'] = []
        self.trust['keys']['fixture-ed25519']['status'] = 'REVOKED'
        self.reject_before_read('UNKNOWN_OR_REVOKED_AUTHORITY_KEY')

    def test_right_reuse_with_new_approval_id_stays_consumed(self):
        self.execute()
        self.payload['approval_id'] = 'fixture-renamed'
        self.sign()
        with self.assertRaisesRegex(ValueError, 'QUERY_RIGHT_ALREADY_RESERVED'):
            self.execute()
        self.assertEqual(self.calls['read'], 1)

    def test_cancel_after_reservation_cannot_retry(self):
        def cancelled(request, trust):
            raise KeyboardInterrupt('fixture interruption')
        with self.assertRaises(KeyboardInterrupt):
            io._execute(self.request, producer, self.trust, self.campaign, self.journal,
                        500, cancelled, fixture=True)
        with self.assertRaisesRegex(ValueError, 'QUERY_RIGHT_ALREADY_RESERVED'):
            self.execute()
        self.assertEqual(self.calls['read'], 0)
        outcome = json.loads(next(self.journal.glob('*.outcome.json')).read_text())
        self.assertEqual(outcome['state'], 'IO_OR_DISPATCH_FAILED_OR_UNKNOWN_NO_RETRY')

    def test_data_hash_error_consumes_right_and_never_returns_output(self):
        self.raw = b'[{"wrong":true}]'
        with self.assertRaisesRegex(ValueError, 'SEALED_DATA_HASH_MISMATCH'):
            self.execute()
        with self.assertRaisesRegex(ValueError, 'QUERY_RIGHT_ALREADY_RESERVED'):
            self.execute()
        self.assertEqual(self.calls['read'], 1)

    def test_fixture_approval_is_denied_at_public_production_entry_before_io(self):
        # Only the external environment is mocked; production must still reject
        # this fixture signature. No normal fixture approval grants production IO.
        runtime = (self.trust, self.campaign, self.journal, 500)
        with patch.object(io, '_load_runtime', return_value=runtime), patch.object(io, '_read_sealed') as read:
            with self.assertRaisesRegex(ValueError, 'FIXTURE_AUTHORITY_FORBIDDEN'):
                io.dispatch(self.request, producer)
            read.assert_not_called()

    def test_public_entry_rejects_caller_trust_store_and_fixture_switch(self):
        for key in ('trust_path', 'public_key', 'fixture', 'principal'):
            request = {**self.request, key: 'attacker'}
            with self.subTest(key=key), patch.object(io, '_read_sealed') as read:
                with self.assertRaisesRegex(ValueError, 'EXACT_REQUEST_KEYS'):
                    io.dispatch(request, producer)
                read.assert_not_called()

    def test_unprovisioned_real_runtime_sealed_reads_zero(self):
        # The check must not rely on the machine being root or having a real key.
        with patch.object(io, '_protected', side_effect=io.AccessDenied('BLOCKED_TRUST_ANCHOR_MISSING')):
            with patch.object(io, '_read_sealed') as read:
                with self.assertRaisesRegex(ValueError, 'BLOCKED_TRUST_ANCHOR'):
                    io.dispatch(self.request, producer)
                read.assert_not_called()


if __name__ == '__main__':
    unittest.main()
