"""Secret-free failure classification and a strictly offline saved-attempt diagnostic.

Never retries a request, changes a credential, releases a reservation or infers
historical transmission/billing from the current credential configuration.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from urllib.error import HTTPError

PHASES = frozenset(('CREDENTIAL_PREFLIGHT', 'REQUEST_BUILD', 'HTTP_OPEN', 'HTTP_READ',
    'SOURCE_CAPTURE', 'CODE_BINDING', 'PROMPT_BUILD', 'RESPONSE_JSON',
    'RESPONSE_ENVELOPE', 'RESPONSE_DECODE', 'RECEIPT_PERSIST', 'UNKNOWN'))
CODES = frozenset(('KEY_MISSING', 'KEY_INVALID_TYPE', 'KEY_CONTROL_CHARACTER',
    'KEY_WHITESPACE', 'KEY_NON_ASCII', 'REDIRECT_NOT_AUTHORIZED', 'RESPONSE_LIMIT',
    'INPUT_BOUND_EXCEEDED', 'BOUNDED_MODEL', 'INCOMPLETE_GEMINI', 'INCOMPLETE_OPENAI',
    'USAGE_BOUND', 'MODEL_SCHEMA', 'MODEL_SCHEMA_KEYS', 'RESULT_OBJECT',
    'RESULT_BOOLEAN', 'RESULT_EVIDENCE_CLASS', 'RESULT_RULES_LIST', 'RESULT_PROVIDER',
    'RESULT_RECOMMENDATION', 'RESULT_MISMATCH_LIST', 'RESULT_ITEM_SCHEMA',
    'RESULT_SOURCE_ID', 'RESULT_STATUS', 'NEGATIVE_USAGE_COST',
    'RESULT_STRING_LIST:unresolved', 'RESULT_STRING_LIST:portability_limits',
    'RESULT_STRING_LIST:counterexample_tests', 'SOURCE_SECTION_START_MISSING',
    'SOURCE_SECTION_END_MISSING', 'SOURCE_SECTION_SIZE', 'HTTP_ERROR',
    'JSON_DECODE_ERROR', 'TIMEOUT', 'TRANSPORT_ERROR', 'VALUE_ERROR_REDACTED',
    'UNCLASSIFIED_REDACTED', 'SAVED_RECEIPT_MISMATCH', 'SAVED_STATE_MISMATCH'))


def credential_problem(key: object) -> str | None:
    """Validate header safety only. Do not strip, log, hash or return key bytes."""
    if not isinstance(key, str):
        return 'KEY_INVALID_TYPE'
    if not key:
        return 'KEY_MISSING'
    if any(ord(c) < 32 or ord(c) == 127 for c in key):
        return 'KEY_CONTROL_CHARACTER'
    if any(c.isspace() for c in key):
        return 'KEY_WHITESPACE'
    if not key.isascii():
        return 'KEY_NON_ASCII'
    return None


class SafeFailure(ValueError):
    def __init__(self, code: str, phase: str, http_status: int | None = None):
        self.code = code if code in CODES else 'UNCLASSIFIED_REDACTED'
        self.phase = phase if phase in PHASES else 'UNKNOWN'
        self.http_status = http_status if type(http_status) is int and 100 <= http_status <= 599 else None
        super().__init__(self.code)


def failure_details(exc: Exception, phase: str, http_status: int | None = None) -> dict:
    """No exception message, repr, request headers, payload or traceback locals."""
    phase = phase if phase in PHASES else 'UNKNOWN'
    if isinstance(exc, SafeFailure):
        code, phase = exc.code, exc.phase
        if exc.http_status is not None:
            http_status = exc.http_status
    elif isinstance(exc, HTTPError):
        code, http_status = 'HTTP_ERROR', exc.code
        phase = getattr(exc, 'audit_phase', phase)
    elif isinstance(exc, json.JSONDecodeError):
        code = 'JSON_DECODE_ERROR'
    elif isinstance(exc, TimeoutError):
        code = 'TIMEOUT'
    elif isinstance(exc, ValueError):
        arg = exc.args[0] if exc.args else None
        code = arg if type(arg) is str and arg in CODES else 'VALUE_ERROR_REDACTED'
    elif isinstance(exc, OSError):
        code = 'TRANSPORT_ERROR'
    else:
        code = 'UNCLASSIFIED_REDACTED'
    return {'error_phase': phase if phase in PHASES else 'UNKNOWN', 'error_code': code,
            'http_status': http_status if type(http_status) is int and 100 <= http_status <= 599 else None}


PRIOR_COMMIT = '735cdefad4310fc9c1d7923571f1ef3ca9901021'
PRIOR_RUN = '34361265053'
PINS = {
    'APPROVAL.json': 'a28acd21460ab4ebe51cda0005ebb0cc36c8372d0d9a2d21951ff12ce729d831',
    'API_LEDGER.json': '8cd82fe659462b94c151dfae587c43a6feedd5ef91687340bb79016233fd830f',
    'SOURCE_RECEIPTS.json': '24ed6afaf3b99969a8f6cab736a120096d41d575aea6f30414c380a731824a82',
    'gemini_REQUEST.json': '9ce32c7454487acb9321b9fc2e8e62a05e3f7e5a8596bd34a8bc74fdc6fa31dd',
    'gemini_RESPONSE.json': '7c76e7ad1ab24a9c1cd556f4ad55225beae3c2dfb4944d2774e041e9d47a05d3',
}


def diagnose_saved(directory: Path, env: dict) -> dict:
    """Reads exactly the five pinned receipts; makes zero network calls."""
    saved = {}
    for name, digest in PINS.items():
        data = (directory / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise SafeFailure('SAVED_RECEIPT_MISMATCH', 'UNKNOWN')
        saved[name] = json.loads(data)
    ledger = saved['API_LEDGER.json']
    if ledger['owner_run'] != PRIOR_RUN or ledger['status'] != 'BLOCKED' or ledger['further_dispatch_allowed'] is not False:
        raise SafeFailure('SAVED_STATE_MISMATCH', 'UNKNOWN')
    checks = {provider: credential_problem(env.get(key, '')) for provider, key in
              (('gemini', 'GEMINI_API_KEY'), ('openai', 'OPENAI_API_KEY'))}
    return {'mode': 'OFFLINE_CREDENTIAL_SHAPE_AND_SAVED_RECEIPT_ONLY',
        'prior_receipt_commit': PRIOR_COMMIT, 'prior_owner_run': PRIOR_RUN,
        'receipt_hashes_match': True, 'current_credential_checks': checks,
        'current_format_ok_is_authentication_or_quota_proof': False,
        'historical_root_cause': 'NOT_RECONSTRUCTABLE_FROM_SAVED_ERROR_TYPE',
        'historical_transmission': 'UNKNOWN', 'historical_billing': 'UNKNOWN',
        'historical_attempts': {p: x['attempts'] for p, x in ledger['slots'].items()},
        'outstanding_reserved_usd': sum(x['reserved_usd'] for x in ledger['slots'].values()),
        'settled_cost_usd': None, 'provider_requests_this_diagnostic': 0,
        'source_fetches_this_diagnostic': 0, 'economic_evaluations': 0,
        'secret_mutations': 0, 'original_receipt_mutations': 0,
        'report_only': True, 'further_dispatch_allowed': False}


def deny_network_and_process(event, args):
    if event.startswith('socket.') or event in ('subprocess.Popen', 'os.system', 'os.exec', 'os.posix_spawn'):
        raise RuntimeError('OFFLINE_DIAGNOSTIC_NO_NETWORK_OR_PROCESS')


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--saved-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    sys.addaudithook(deny_network_and_process)
    result = diagnose_saved(args.saved_dir, os.environ)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as target:
        json.dump(result, target, sort_keys=True, indent=2)
    # Only bounded, non-secret fields are printed. Key values never enter result.
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps(failure_details(exc, 'UNKNOWN')))
        raise SystemExit(2) from None
