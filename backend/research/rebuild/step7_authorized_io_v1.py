"""STEP7 production authority boundary and single-use sealed input dispatch.

The immutable PR1209 guard remains a policy calculator, never an authentication
boundary. Production uses only the independently provisioned fixed /etc trust
store below, a non-developer OS identity, and signed exact input bindings. No
trust path/key, runtime principal, approval hash or fixture mode is accepted
from a request. No trust anchor is installed by this development change.

A host administrator remains trusted: Python cannot sandbox a malicious host or
someone allowed to replace this module. Formal operation requires a separately
administered validator account; this module fails closed under root/developer
accounts and when that environment is absent.
"""
from __future__ import annotations

import argparse
import base64
from copy import deepcopy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import time

from backend.research.rebuild import step7_independent_validation_v1 as guard
from backend.research.rebuild.step7_callable_binding_v1 import producer_binding
from backend.research.rebuild import step7_isolated_worker_v1 as isolated

TRUST_PATH = Path('/etc/zel/step7/authority-trust.json')
SIGNATURE_VERIFIER = Path('/usr/bin/openssl')
SCHEMA = 'zel.step7.external_authority.v1'
REQUEST_KEYS = {'identity', 'design', 'roles', 'source', 'registered_ms',
                'data_relpath', 'signed_approval'}
BINDING_KEYS = ('scope', 'identity_sha', 'design_sha', 'roles_sha', 'source_sha',
                'campaign_sha', 'data_relpath', 'data_sha', 'producer_code_sha256',
                'producer_qualname', 'registered_ms', 'max_reads', 'max_dispatches')


class AccessDenied(ValueError):
    """Before protected input IO, or consumed allocation after uncertain IO."""


def _json_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _sha_bytes(value):
    return hashlib.sha256(value).hexdigest()


def _protected(path, *, directory=False):
    """Reject symlinks and any non-root or group/world-writable anchor ancestry."""
    path = Path(path)
    if not path.is_absolute():
        raise AccessDenied('BLOCKED_TRUST_ANCHOR_ABSOLUTE_PATH')
    for component in list(reversed(path.parents)) + [path]:
        try:
            info = component.lstat()
        except FileNotFoundError as exc:
            raise AccessDenied('BLOCKED_TRUST_ANCHOR_MISSING') from exc
        if stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise AccessDenied('BLOCKED_TRUST_ANCHOR_WRITABLE_OR_SYMLINK')
    if directory and not path.is_dir():
        raise AccessDenied('BLOCKED_TRUST_ANCHOR_DIRECTORY')
    return path


def _load_runtime():
    # A caller's env vars and supplied public keys are intentionally irrelevant.
    _protected(TRUST_PATH)
    trust = json.loads(TRUST_PATH.read_bytes())
    if trust.get('schema') != 'zel.step7.trust_store.v1':
        raise AccessDenied('BLOCKED_TRUST_ANCHOR_SCHEMA')
    uid = os.geteuid()
    if uid == 0 or uid != trust.get('validator_uid') or uid in trust.get('developer_uids', []):
        raise AccessDenied('BLOCKED_INDEPENDENT_RUNTIME_IDENTITY')
    if not trust.get('validator_principal') or not trust.get('keys'):
        raise AccessDenied('BLOCKED_TRUST_ANCHOR_NOT_PROVISIONED')
    now_ms = time.time_ns() // 1_000_000
    if trust.get('valid_until_ms', 0) <= now_ms:
        raise AccessDenied('BLOCKED_TRUST_ANCHOR_EXPIRED')
    _protected(Path(trust['source_root']), directory=True)
    # The initial campaign is an independently pinned, immutable budget snapshot.
    # A durable journal under the same fixed runtime account prevents reuse even
    # if this snapshot remains unchanged after an uncertain/crashed attempt.
    _protected(Path(trust['campaign_path']))
    campaign = json.loads(Path(trust['campaign_path']).read_bytes())
    if guard.sha(campaign) != trust.get('campaign_sha'):
        raise AccessDenied('CAMPAIGN_ANCHOR_DRIFT')
    journal = Path(trust['journal_dir'])
    if not journal.is_absolute() or not journal.is_dir() or journal.is_symlink():
        raise AccessDenied('PERSISTENT_JOURNAL_REQUIRED')
    info = journal.stat()
    if info.st_uid != uid or info.st_mode & 0o077:
        raise AccessDenied('PERSISTENT_JOURNAL_PRIVATE_RUNTIME_ONLY')
    if not trust.get('journal_backup_owner') or trust.get('journal_reset_allowed') is not False:
        raise AccessDenied('PERSISTENT_JOURNAL_RETENTION_UNBOUND')
    return trust, campaign, journal, now_ms


def _signature_valid(public_key_pem, payload, signature_b64):
    """OpenSSL Ed25519; no network, credentials, fallback or paid API."""
    try:
        signature = base64.b64decode(signature_b64, validate=True)
    except (TypeError, ValueError) as exc:
        raise AccessDenied('INVALID_EXTERNAL_SIGNATURE') from exc
    if len(signature) != 64:
        raise AccessDenied('INVALID_EXTERNAL_SIGNATURE')
    with tempfile.TemporaryDirectory(prefix='step7-signature-') as temp:
        p = Path(temp)
        (p / 'key.pem').write_text(public_key_pem)
        (p / 'payload').write_bytes(_json_bytes(payload))
        (p / 'signature').write_bytes(signature)
        try:
            verifier = _protected(SIGNATURE_VERIFIER)
            result = subprocess.run([str(verifier), 'pkeyutl', '-verify', '-pubin',
                                     '-inkey', str(p / 'key.pem'), '-rawin',
                                     '-in', str(p / 'payload'), '-sigfile', str(p / 'signature')],
                                    capture_output=True, timeout=5, check=False,
                                    env={'LC_ALL': 'C.UTF-8'}, cwd=p)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise AccessDenied('SIGNATURE_VERIFIER_UNAVAILABLE') from exc
        if result.returncode:
            raise AccessDenied('INVALID_EXTERNAL_SIGNATURE')


def _producer_binding(producer):
    producer_binding(producer, error_type=AccessDenied)
    return isolated.snapshot_identity(isolated.snapshot(producer))


def _authorize(request, producer, trust, campaign, now_ms, *, fixture=False):
    if set(request) != REQUEST_KEYS:
        raise AccessDenied('EXACT_REQUEST_KEYS_NO_TRUST_OR_FIXTURE_INJECTION')
    envelope = request['signed_approval']
    if set(envelope) != {'payload', 'key_id', 'signature_b64'}:
        raise AccessDenied('SIGNED_EXTERNAL_APPROVAL_REQUIRED')
    payload = envelope['payload']
    if payload.get('schema') != SCHEMA or payload.get('status') != 'APPROVED':
        raise AccessDenied('EXPLICIT_EXTERNAL_APPROVAL_REQUIRED')
    if bool(payload.get('fixture_only')) != fixture:
        raise AccessDenied('FIXTURE_AUTHORITY_FORBIDDEN_IN_PRODUCTION')
    key = trust.get('keys', {}).get(envelope['key_id'])
    if not key or key.get('status') != 'ACTIVE':
        raise AccessDenied('UNKNOWN_OR_REVOKED_AUTHORITY_KEY')
    if payload.get('principal') != key.get('principal') or key.get('principal') != trust.get('approval_principal'):
        raise AccessDenied('WRONG_APPROVAL_PRINCIPAL')
    if not payload.get('approval_id') or payload['approval_id'] in trust.get('revoked_approval_ids', []):
        raise AccessDenied('REVOKED_APPROVAL')
    if not (type(payload.get('not_before_ms')) is int and type(payload.get('expires_ms')) is int and
            payload['not_before_ms'] <= now_ms < payload['expires_ms']):
        raise AccessDenied('EXPIRED_OR_NOT_YET_VALID_APPROVAL')
    _signature_valid(key['public_key_pem'], payload, envelope['signature_b64'])
    code_sha, producer_name = _producer_binding(producer)
    expected = {'scope': guard.PURPOSE, 'identity_sha': guard.sha(request['identity']),
                'design_sha': guard.sha(request['design']), 'roles_sha': guard.sha(request['roles']),
                'source_sha': guard.sha(request['source']), 'campaign_sha': guard.sha(campaign),
                'data_relpath': request['data_relpath'], 'data_sha': request['source'].get('data_sha'),
                'producer_code_sha256': code_sha, 'producer_qualname': producer_name,
                'registered_ms': request['registered_ms'], 'max_reads': 1, 'max_dispatches': 1}
    if set(payload.get('binding', {})) != set(BINDING_KEYS) or payload['binding'] != expected:
        raise AccessDenied('APPROVAL_EXACT_BINDING_MISMATCH')
    if request['roles'].get('validator') != trust['validator_principal']:
        raise AccessDenied('RUNTIME_VALIDATOR_PRINCIPAL_MISMATCH')
    # Build legacy policy input only from an already verified external signature.
    authority = guard.seal({'principal': 'USER', 'status': 'APPROVED',
                            'identity_sha': expected['identity_sha'], 'design_sha': expected['design_sha'],
                            'campaign': guard.PURPOSE, 'external_approval_id': payload['approval_id'],
                            'external_signer': key['principal'], 'external_envelope_sha': guard.sha(envelope)})
    plan = guard.preregister(request['identity'], request['design'], request['roles'], campaign,
                             authority, authenticated_authority_sha=guard.sha(authority),
                             registered_ms=request['registered_ms'])
    next_campaign, ticket = guard.reserve_access(plan, campaign, request['source'],
                                                 actor=trust['validator_principal'], now_ms=now_ms)
    return plan, next_campaign, ticket


def _create_durable(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(_json_bytes(value)); f.flush(); os.fsync(f.fileno())
        dirfd = os.open(Path(path).parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dirfd)
        finally:
            os.close(dirfd)
    except BaseException:
        # A partial receipt is deliberately never deleted; it consumes the right.
        raise


def _execute(request, producer, trust, campaign, journal, now_ms, reader, *, fixture=False):
    # Keep the authenticated request stable across the reader callback.
    request = deepcopy(request)
    producer_binding(producer, error_type=AccessDenied)
    prepared = isolated.snapshot(producer)
    plan, next_campaign, ticket = _authorize(request, producer, trust, campaign, now_ms, fixture=fixture)
    approved = request['signed_approval']['payload']['binding']
    expected_producer = (approved['producer_code_sha256'], approved['producer_qualname'])
    if isolated.snapshot_identity(prepared) != expected_producer:
        raise AccessDenied('PRODUCER_SNAPSHOT_CHANGED_BEFORE_AUTHORIZATION')
    journal = Path(journal)
    # Fixed campaign key: changing approval id, data path or request filename does
    # not allocate another run. The journal is never reset by this module.
    prefix = journal / hashlib.sha256(guard.PURPOSE.encode()).hexdigest()
    with open(str(prefix) + '.lock', 'a+b') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            _create_durable(str(prefix) + '.reservation.json', {
                'state': 'RESERVED_BEFORE_SEALED_IO', 'ticket': ticket,
                'campaign_after_reservation': next_campaign, 'plan_sha': plan['receipt_sha256'],
                'approval_envelope_sha': guard.sha(request['signed_approval']), 'fixture_only': fixture})
        except FileExistsError as exc:
            raise AccessDenied('QUERY_RIGHT_ALREADY_RESERVED_NO_RETRY') from exc
    try:
        raw = reader(request, trust)
        if _sha_bytes(raw) != request['source']['data_sha']:
            raise AccessDenied('SEALED_DATA_HASH_MISMATCH_ALLOCATION_CONSUMED')
        # Recheck after IO: a callback mutated while reading must not receive
        # protected bytes. A failed check keeps the already-consumed reservation.
        if _producer_binding(producer) != expected_producer:
            raise AccessDenied('PRODUCER_CHANGED_AFTER_AUTHORIZATION')
        # Never invoke the parent callable or any of its mutable globals. The
        # fresh child imports only the source snapshot captured before approval.
        output = isolated.run(prepared, raw)
        receipt = {'state': 'DISPATCH_COMPLETED', 'ticket_sha': ticket['receipt_sha256'],
                   'output_sha': guard.sha(output), 'bytes_read': len(raw),
                   'formal_credit': 0, 'economic_pass': False, 'fixture_only': fixture,
                   'execution_identity_sha256': expected_producer[0],
                   'execution_mode': 'FRESH_ISOLATED_SOURCE_SNAPSHOT'}
        _create_durable(str(prefix) + '.outcome.json', receipt)
        return {'output': output, 'access_receipt': receipt}
    except BaseException as exc:
        # Includes cancellation, verifier/process errors, bad hashes and producer
        # exceptions. Never roll back the reservation after possibly exposed IO.
        try:
            _create_durable(str(prefix) + '.outcome.json', {
                'state': 'IO_OR_DISPATCH_FAILED_OR_UNKNOWN_NO_RETRY',
                'error_type': type(exc).__name__, 'formal_credit': 0, 'fixture_only': fixture})
        except FileExistsError:
            pass
        raise


def _read_sealed(request, trust):
    rel = Path(request['data_relpath'])
    if rel.is_absolute() or '..' in rel.parts or not rel.parts:
        raise AccessDenied('SOURCE_PATH_ESCAPE')
    path = Path(trust['source_root']) / rel
    _protected(path)
    maximum = trust.get('max_input_bytes')
    if type(maximum) is not int or maximum <= 0:
        raise AccessDenied('SOURCE_BYTE_BUDGET_REQUIRED')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as f:
        info = os.fstat(f.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > maximum:
            raise AccessDenied('SOURCE_SIZE_OR_TYPE_LIMIT')
        raw = f.read(maximum + 1)
    if len(raw) > maximum:
        raise AccessDenied('SOURCE_SIZE_LIMIT')
    return raw


def dispatch(request, producer):
    """Only production sealed-read/dispatch entrypoint; accepts no trust override.

    Request is public metadata. Producer is a top-level bytes -> dict function
    whose source dependency snapshot, worker, runtime identity and qualified name
    were externally approved. Prior file-only signatures need external renewal.
    The actual code object and canonical module namespace must match that source
    before reservation and again before dispatch; metadata alone never suffices.
    Execution occurs in a new -I -S child, never through parent mutable globals.
    """
    if not isinstance(request, dict) or set(request) != REQUEST_KEYS:
        raise AccessDenied('EXACT_REQUEST_KEYS_NO_TRUST_OR_FIXTURE_INJECTION')
    trust, campaign, journal, now_ms = _load_runtime()
    return _execute(request, producer, trust, campaign, journal, now_ms, _read_sealed)


def preflight():
    """Metadata-only availability check. It does not grant authority or read data."""
    try:
        _load_runtime()
    except (AccessDenied, OSError, KeyError, ValueError) as exc:
        return {'state': 'BLOCKED_TRUST_ANCHOR', 'reason': str(exc), 'sealed_reads': 0,
                'dispatches': 0, 'independent_allocations_consumed': 0, 'formal_credit': 0}
    return {'state': 'RUNTIME_PRESENT_APPROVAL_NOT_EVALUATED', 'sealed_reads': 0,
            'dispatches': 0, 'independent_allocations_consumed': 0, 'formal_credit': 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preflight', action='store_true', required=True)
    args = parser.parse_args()
    if args.preflight:
        print(json.dumps(preflight(), sort_keys=True))


if __name__ == '__main__':
    main()
