"""No-network regressions for the PR1236 failure-observability continuation."""
import copy
import http.client
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError, URLError
from backend.research.benchmark import creator_squeeze_audit_v1 as a
from backend.research.benchmark import creator_squeeze_reviewed_v1 as r
from backend.research.benchmark import creator_squeeze_diagnostics_v1 as d


class DiagnosticTests(unittest.TestCase):
    def test_key_missing(self):
        self.assertEqual(d.credential_problem(''), 'KEY_MISSING')

    def test_key_control_characters(self):
        for c in ('\n', '\r', '\t', '\0', '\x7f'):
            with self.subTest(character=ord(c)):
                self.assertEqual(d.credential_problem('FAKE' + c), 'KEY_CONTROL_CHARACTER')

    def test_key_spaces_are_not_trimmed(self):
        for key in (' FAKE', 'FAKE ', 'FA KE'):
            self.assertEqual(d.credential_problem(key), 'KEY_WHITESPACE')

    def test_key_nonascii(self):
        self.assertEqual(d.credential_problem('FAKEé'), 'KEY_NON_ASCII')

    def test_key_wrong_type(self):
        self.assertEqual(d.credential_problem(None), 'KEY_INVALID_TYPE')

    def test_format_ok_does_not_prove_key_authentication(self):
        self.assertIsNone(d.credential_problem('synthetic-not-a-valid-provider-key'))

    def test_real_http_header_valueerror_without_network(self):
        # Exercise the real stdlib serializer, not a guessed provider error.
        con = http.client.HTTPConnection('unused.invalid')
        with patch.object(con, 'connect', side_effect=AssertionError('NETWORK')):
            con.putrequest('POST', '/')
            with self.assertRaises(ValueError):
                con.putheader('x-goog-api-key', 'SYNTHETIC\n')

    def test_preflight_prevents_opener_and_secret_repr(self):
        with patch.object(a, 'build_opener') as opener:
            with self.assertRaises(d.SafeFailure) as result:
                a.request('https://generativelanguage.googleapis.com/x', body={}, provider='gemini', key='SYNTHETIC\n')
        opener.assert_not_called()
        self.assertEqual(result.exception.phase, 'CREDENTIAL_PREFLIGHT')
        self.assertNotIn('SYNTHETIC', str(result.exception))

    def test_unknown_valueerror_is_redacted(self):
        info = d.failure_details(ValueError("Invalid header value b'PRIVATE_KEY\n'"), 'HTTP_OPEN')
        self.assertEqual(info['error_code'], 'VALUE_ERROR_REDACTED')
        self.assertNotIn('PRIVATE_KEY', json.dumps(info))

    def test_known_guard_code_is_preserved(self):
        self.assertEqual(d.failure_details(ValueError('USAGE_BOUND'), 'RESPONSE_DECODE')['error_code'], 'USAGE_BOUND')

    def test_json_error_does_not_emit_document(self):
        info = d.failure_details(json.JSONDecodeError('PRIVATE', 'PRIVATE', 0), 'RESPONSE_JSON', 200)
        self.assertEqual(info['error_code'], 'JSON_DECODE_ERROR')
        self.assertEqual(info['http_status'], 200)
        self.assertNotIn('PRIVATE', json.dumps(info))

    def test_http_error_retains_status_without_url_body(self):
        info = d.failure_details(HTTPError('https://private.invalid/key', 429, 'PRIVATE', {}, None), 'HTTP_OPEN')
        self.assertEqual(info['http_status'], 429)
        self.assertNotIn('private', json.dumps(info).lower())

    def test_timeout_is_not_zero_usage(self):
        self.assertEqual(d.failure_details(TimeoutError('PRIVATE'), 'HTTP_OPEN')['error_code'], 'TIMEOUT')

    def test_network_error_is_redacted(self):
        self.assertEqual(d.failure_details(URLError('PRIVATE'), 'HTTP_OPEN')['error_code'], 'TRANSPORT_ERROR')

    def test_untrusted_phase_and_code_are_redacted(self):
        info = d.failure_details(d.SafeFailure('PRIVATE', 'PRIVATE', 'PRIVATE'), 'PRIVATE')
        self.assertNotIn('PRIVATE', json.dumps(info))

    def test_http422_is_still_caught_as_http_error(self):
        exc = HTTPError('https://api.github.com', 422, 'exists', {}, None)
        with patch.object(a, 'build_opener') as opener:
            opener.return_value.open.side_effect = exc
            with self.assertRaises(HTTPError) as result:
                a.request('https://api.github.com/x', body={})
        self.assertIs(result.exception, exc)
        self.assertEqual(exc.audit_phase, 'HTTP_OPEN')

    def test_transport_valueerror_is_sanitized(self):
        with patch.object(a, 'build_opener') as opener:
            opener.return_value.open.side_effect = ValueError('PRIVATE')
            with self.assertRaises(d.SafeFailure) as result:
                a.request('https://generativelanguage.googleapis.com/x', body={}, provider='gemini', key='FAKE')
        self.assertEqual(result.exception.phase, 'HTTP_OPEN')
        self.assertNotIn('PRIVATE', str(result.exception))

    def test_oversize_body_retains_200_and_http_read_phase(self):
        response = MagicMock(); response.status = 200; response.read.return_value = b'x' * 2000001
        with patch.object(a, 'build_opener') as opener:
            opener.return_value.open.return_value.__enter__.return_value = response
            with self.assertRaises(d.SafeFailure) as result:
                a.request('https://unused.invalid')
        self.assertEqual((result.exception.code, result.exception.phase, result.exception.http_status), ('RESPONSE_LIMIT', 'HTTP_READ', 200))

    def test_redirect_reason_retained(self):
        with patch.object(a, 'build_opener') as opener:
            opener.return_value.open.side_effect = ValueError('REDIRECT_NOT_AUTHORIZED')
            with self.assertRaises(d.SafeFailure) as result:
                a.request('https://unused.invalid')
        self.assertEqual(result.exception.code, 'REDIRECT_NOT_AUTHORIZED')

    def test_terminal_and_unknown_slots_cannot_start(self):
        for state in ('COMPLETED', 'BLOCKED', 'CHECKPOINTED', 'REPORT_ONLY'):
            with self.assertRaises(ValueError):
                a.can_start({'status': state}, 'gemini')
        with self.assertRaises(ValueError):
            a.can_start({'status': 'ACTIVE', 'slots': {'gemini': {'state': 'FAILED_OR_UNKNOWN_CONSUMED'}}}, 'gemini')

    def test_openai_not_a_fallback(self):
        ledger = {'status': 'ACTIVE', 'slots': {'gemini': {'state': 'FAILED_OR_UNKNOWN_CONSUMED', 'reserved_usd': 2.5}, 'openai': {'state': 'RESERVED_NOT_STARTED', 'reserved_usd': 2.5}}}
        with self.assertRaisesRegex(ValueError, 'PRIOR_REQUEST_UNRESOLVED'):
            a.can_start(ledger, 'openai')

    def test_audit_hook_denies_network_process(self):
        for event in ('socket.__new__', 'socket.connect', 'socket.getaddrinfo', 'subprocess.Popen', 'os.system'):
            with self.assertRaises(RuntimeError):
                d.deny_network_and_process(event, ())
        self.assertIsNone(d.deny_network_and_process('open', ()))

    def test_saved_hash_mismatch_rejected_before_keys(self):
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / 'APPROVAL.json').write_text('{}')
            with self.assertRaisesRegex(d.SafeFailure, 'SAVED_RECEIPT_MISMATCH'):
                d.diagnose_saved(Path(root), {'GEMINI_API_KEY': 'PRIVATE'})

    def _run_fixture(self, payload=b'{}', error=None, key='FAKE'):
        context = tempfile.TemporaryDirectory(); self.addCleanup(context.cleanup)
        root = Path(context.name); out = root / a.OUT; out.mkdir(parents=True)
        config = {'scope': a.SCOPE, 'max_requests': 2, 'max_reserved_usd': 5, 'code_blobs': {n: 'hash' for n in ('backend/research/rebuild/chart_mechanism_features_v1.py', 'backend/research/rebuild/chart_mechanism_execution_v1.py')}}
        (out / 'APPROVAL.json').write_text(json.dumps(config))
        for name in config['code_blobs']:
            target = root / name; target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text('def squeeze_features():pass\ndef completed_utc_days():pass\ndef exit_reason():pass\ndef _position():pass')
        event = root / 'event.json'; event.write_text(json.dumps({'issue': {'number': 1236}}))
        calls = []
        def request(url, **kwargs):
            if kwargs.get('provider'):
                calls.append(kwargs['provider'])
                if error: raise error
                return payload, 200
            return b'{}', 200
        env = {'GITHUB_EVENT_PATH': str(event), 'GITHUB_RUN_ID': 'SYNTHETIC', 'GEMINI_API_KEY': key, 'OPENAI_API_KEY': 'FAKE'}
        with patch.dict(os.environ, env, clear=True), patch.object(a, 'ROOT', root), patch.object(a, 'authentication'), patch.object(a, 'authorize', return_value={'merge_sha': 'merge'}), patch.object(a, 'git', side_effect=lambda *args: 'hash' if args[0] == 'hash-object' else ''), patch.object(a, 'persist', return_value='SYNTHETIC_COMMIT'), patch.object(a, 'request', side_effect=request), patch.object(a, 'section', return_value=('SOURCE_SYNTHETIC', {})), patch.object(a, 'make_prompt', return_value='SYNTHETIC_PROMPT'):
            result = a.run()
        response = out / 'gemini_RESPONSE.json'
        return result, json.loads(response.read_text()) if response.exists() else None, calls

    def test_full_handler_preserves_http_before_bad_json(self):
        ledger, receipt, calls = self._run_fixture(payload=b'not-json')
        self.assertEqual(calls, ['gemini'])
        self.assertEqual(receipt['http_status'], 200)
        self.assertEqual(receipt['error_phase'], 'RESPONSE_JSON')
        self.assertIsNotNone(receipt['response_sha256'])
        self.assertEqual(ledger['status'], 'BLOCKED')
        self.assertFalse(ledger['further_dispatch_allowed'])

    def test_full_handler_stores_safe_failure_phase(self):
        ledger, receipt, calls = self._run_fixture(error=d.SafeFailure('RESPONSE_LIMIT', 'HTTP_READ', 200))
        self.assertEqual((receipt['error_code'], receipt['error_phase'], receipt['http_status']), ('RESPONSE_LIMIT', 'HTTP_READ', 200))
        self.assertEqual(ledger['slots']['gemini']['attempts'], 1)
        self.assertEqual(ledger['slots']['openai']['attempts'], 0)
        self.assertIsNone(receipt['settled_cost_usd'])

    def test_full_handler_invalid_key_no_attempt_no_source_model(self):
        ledger, receipt, calls = self._run_fixture(key='PRIVATE\n')
        self.assertEqual(calls, [])
        self.assertIsNone(receipt)
        self.assertEqual(ledger['slots']['gemini']['attempts'], 0)
        self.assertEqual(ledger['blocking_error']['error_code'], 'KEY_CONTROL_CHARACTER')
        self.assertNotIn('PRIVATE', json.dumps(ledger))
        self.assertEqual(sum(x['reserved_usd'] for x in ledger['slots'].values()), 5)

    def test_full_handler_usage_survives_output_validation(self):
        payload = {'candidates': [{'finishReason': 'MAX_TOKENS'}], 'usageMetadata': {'promptTokenCount': 20, 'candidatesTokenCount': 1, 'thoughtsTokenCount': 2}, 'responseId': 'SYNTHETIC_ID'}
        ledger, receipt, calls = self._run_fixture(payload=json.dumps(payload).encode())
        self.assertEqual(receipt['usage'], payload['usageMetadata'])
        self.assertEqual(receipt['error_code'], 'INCOMPLETE_GEMINI')
        self.assertEqual(receipt['error_phase'], 'RESPONSE_DECODE')
        self.assertEqual(calls, ['gemini'])
        self.assertIsNone(receipt['settled_cost_usd'])

    def test_returned_status_reaches_reviewed_cli(self):
        with patch.object(a, 'run', return_value={'status': 'BLOCKED'}):
            self.assertEqual(r.run()['status'], 'BLOCKED')
        self.assertIn("if outcome and outcome['status']!='COMPLETED':raise SystemExit(2)", Path(r.__file__).read_text())


if __name__ == '__main__':
    unittest.main()
