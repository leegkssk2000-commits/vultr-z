"""GitHub-owned one-shot Issue1358 internal EMA21 limit hypothesis.

Only the explicit activation commit can run. A permanent per-batch Git ref is
created atomically BEFORE signals. Retries fail, including changed outputs,
new workflow runs and changed contracts. This script has no SSH/order API.
"""
from __future__ import annotations
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from urllib.request import Request, urlopen
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from ops import issue1358_ema21_limit_v1 as model
from ops.kp_committed_cursor_snapshot_v1 import load, require, sha, SYMBOLS
from ops.kp_connected_research_validation_v1 import bounded_gunzip, encoded, write_once, START, END, PRICE_SHA, CONFIG_SHA, INPUT_FIELDS

REPO = 'leegkssk2000-commits/vultr-z'
BRANCH = 'codex/issue1358-ema21-limit-v1-20261005'
CAMPAIGN = 'research/campaigns/scalp7_20261005/issue1358_ema21_limit_v1'
CLAIM_REF = 'refs/heads/research-execution-claims/issue1358-ema21-limit-20261005-v1'
JOB = 'economic-comparison'
APPROVAL_REF = 'heads/research-approvals/issue1358-ema21-limit-20261005-v1'
HEAVY_GROUP = 'a1-global-heavy-economic-evaluator-v1'
MAX_PRECLAIM_RECOVERIES = 2
CLAIM_STEP = 'Independent approval then permanent one-shot claim before signals'


def github(method, route, value=None):
    require(route.startswith('/'), 'RELATIVE_GITHUB_API_ONLY')
    token = os.environ.get('GH_TOKEN', '')
    require(bool(token), 'GITHUB_TOKEN_REQUIRED')
    req = Request('https://api.github.com/repos/' + REPO + route,
                  data=encoded(value) if value is not None else None, method=method,
                  headers={'Authorization': 'Bearer ' + token,
                           'Accept': 'application/vnd.github+json',
                           'X-GitHub-Api-Version': '2026-03-10',
                           'Content-Type': 'application/json'})
    try:
        with urlopen(req, timeout=30) as response:
            require(response.geturl().startswith('https://api.github.com/repos/' + REPO + '/'), 'GITHUB_REDIRECT_REJECTED')
            return json.load(response)
    except HTTPError as exc:
        # Do not dump response bodies, headers or credentials.
        raise RuntimeError('GITHUB_' + method + '_HTTP_' + str(exc.code)) from None


def _claim_ref_absent(api):
    """Prove absence on the exact fixed ref after another authenticated read.

    execution_identity has already authenticated and read this repository's run.
    Only the exact missing-ref response is absence; permission, transport and
    malformed-response failures remain unknown and fail closed.
    """
    route = '/git/ref/' + CLAIM_REF.removeprefix('refs/')
    try:
        api('GET', route)
    except RuntimeError as exc:
        require(str(exc) == 'GITHUB_GET_HTTP_404', 'CLAIM_ABSENCE_UNVERIFIED')
        return route
    require(False, 'EXISTING_CLAIM_NO_REPLAY')


def _preclaim_recovery_evidence(api, run_id, attempt):
    """Verify every earlier economic attempt was cancelled before a runner.

    This deliberately implements only the narrow pending-queue replacement
    case. A started/cancelled job is not recoverable here even if a later ref
    read is absent: operator/admin cancellation after runner assignment is a
    separate trust boundary and must not become an economic retry credit.
    """
    require(2 <= attempt <= 1 + MAX_PRECLAIM_RECOVERIES,
            'PRECLAIM_RECOVERY_LIMIT')
    evidence = []
    for prior in range(1, attempt):
        jobs = api('GET', '/actions/runs/' + str(run_id) + '/attempts/'
                   + str(prior) + '/jobs?per_page=100')
        require(jobs['total_count'] == len(jobs['jobs']),
                'PRIOR_ATTEMPT_JOBS_TRUNCATED')
        matches = [j for j in jobs['jobs'] if j.get('name') == JOB]
        require(len(matches) == 1, 'PRIOR_ECONOMIC_JOB_IDENTITY')
        job = matches[0]
        require(job.get('status') == 'completed'
                and job.get('conclusion') == 'cancelled',
                'PRIOR_ATTEMPT_NOT_CANCELLED')
        # GitHub records a timestamp and runner_id=0 for a queued job that was
        # cancelled before assignment. Real repository examples also have an
        # empty runner name and no steps. A positive runner id or any step is
        # therefore started/unknown and not eligible for this narrow recovery.
        require({'id','runner_id','runner_name','steps'}.issubset(job)
                and type(job['id']) is int
                and (job['runner_id'] is None
                     or (type(job['runner_id']) is int and job['runner_id'] == 0))
                and type(job['runner_name']) is str and job['runner_name'] == ''
                and type(job['steps']) is list and len(job['steps']) == 0,
                'PRIOR_ATTEMPT_STARTED_NO_REPLAY')
        evidence.append({'attempt': prior, 'job_id': job['id'],
                         'status': 'completed', 'conclusion': 'cancelled',
                         'runner_started': False, 'claim_step_seen': False})
    missing_route = _claim_ref_absent(api)
    return {'kind': 'SAME_RUN_PRECLAIM_QUEUE_CANCELLATION',
            'recoveries_used': attempt - 1,
            'max_recoveries': MAX_PRECLAIM_RECOVERIES,
            'claim_absence_route': missing_route,
            'prior_attempts': evidence}


def execution_identity(env, api):
    require(env.get('GITHUB_ACTIONS') == 'true' and env.get('GITHUB_REPOSITORY') == REPO,
            'GITHUB_OWNER_REQUIRED')
    require(env.get('GITHUB_EVENT_NAME') == 'push' and env.get('GITHUB_REF') == 'refs/heads/' + BRANCH,
            'EXPLICIT_BRANCH_PUSH_ONLY')
    attempt_raw = env.get('GITHUB_RUN_ATTEMPT', '')
    require(attempt_raw.isdigit() and str(int(attempt_raw)) == attempt_raw
            and env.get('GITHUB_JOB') == JOB, 'RUN_ATTEMPT_OR_JOB_IDENTITY')
    attempt = int(attempt_raw)
    require(1 <= attempt <= 1 + MAX_PRECLAIM_RECOVERIES,
            'PRECLAIM_RECOVERY_LIMIT')
    run_id = env.get('GITHUB_RUN_ID', '')
    head = env.get('GITHUB_SHA', '')
    require(run_id.isdigit() and bool(re.fullmatch('[0-9a-f]{40}', head)), 'GITHUB_RUN_IDENTITY')
    run = api('GET', '/actions/runs/' + run_id)
    require(run['head_sha'] == head and run['head_branch'] == BRANCH
            and run['event'] == 'push' and run['run_attempt'] == attempt
            and run['status'] == 'in_progress'
            and run['path'] == '.github/workflows/issue1358-ema21-limit-v1.yml',
            'API_RUN_IDENTITY_MISMATCH')
    recovery = None if attempt == 1 else _preclaim_recovery_evidence(
        api, int(run_id), attempt)
    return {'run_id': int(run_id), 'head_sha': head, 'job': JOB,
            'attempt': attempt, 'preclaim_recovery': recovery}



def verify_published_approval(parent, contract, activation, api):
    """Independent maintainer publication, never a caller-supplied approval.

    A fixed approval ref must already point to an immutable approval commit with
    APPROVED.json. The execution job never creates/updates that approval ref.
    Ref administration and deliberate workflow edits remain trusted-maintainer
    powers; this is an execution gate, not an isolation boundary against admins.
    """
    ref = api('GET', '/git/ref/' + APPROVAL_REF)
    require(ref['ref'] == 'refs/' + APPROVAL_REF and ref['object']['type'] == 'commit',
            'APPROVAL_REF_PROFILE')
    approval_sha = ref['object']['sha']
    obj = api('GET', '/git/commits/' + approval_sha)
    require(len(obj['parents']) == 1 and obj['parents'][0]['sha'] == parent,
            'APPROVAL_PARENT_LINK_REQUIRED')
    tree = api('GET', '/git/trees/' + obj['tree']['sha'])
    entries = tree['tree']
    require(len(entries) == 1 and entries[0]['path'] == 'APPROVED.json'
            and entries[0]['type'] == 'blob', 'APPROVAL_TREE_PROFILE')
    blob = api('GET', '/git/blobs/' + entries[0]['sha'])
    require(blob['encoding'] == 'base64', 'APPROVAL_BLOB_ENCODING')
    raw = base64.b64decode(blob['content'], validate=False)
    git_sha = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
    require(git_sha == entries[0]['sha'], 'APPROVAL_BLOB_HASH')
    approval = load(raw)
    require(approval['batch_id'] == model.BATCH and approval['approved_parent_sha'] == parent,
            'PARENT_NOT_INDEPENDENTLY_APPROVED')
    require(approval['contract_sha256'] == activation['contract_sha256']
            and approval['max_lane_executions'] == 1, 'INDEPENDENT_CONTRACT_APPROVAL_MISMATCH')
    required = {'ops/issue1358_ema21_owner_v1.py', 'ops/issue1358_ema21_limit_v1.py',
                '.github/workflows/issue1358-ema21-limit-v1.yml',
                CAMPAIGN + '/CONTRACT_GITHUB.json'}
    require(required.issubset(approval['source_sha256']), 'APPROVAL_SOURCE_SCOPE')
    for path, expected in approval['source_sha256'].items():
        full = (ROOT/path).resolve(strict=True)
        require(full.is_relative_to(ROOT) and sha(full.read_bytes()) == expected,
                'INDEPENDENT_APPROVAL_SOURCE_CHANGED:' + path)
    return approval_sha


def claim_batch(contract, activation, output, api=github, env=os.environ):
    require(contract.get('shared_producer_policy') == 'READY_V4_PRECLAIM_RECOVERY_ATOMIC_CLAIM',
            'SHARED_PRODUCER_POLICY_HOLD_BEFORE_CLAIM')
    require(contract['batch_id'] == model.BATCH == activation['batch_id'], 'BATCH_CHANGED')
    require(contract['claim_ref'] == CLAIM_REF and contract['execution_owner'] == 'GITHUB_ATOMIC_REF_V1',
            'OWNER_CHANGED')
    identity = execution_identity(env, api)
    commit = api('GET', '/git/commits/' + identity['head_sha'])
    require(len(commit['parents']) == 1, 'ACTIVATION_MUST_BE_SINGLE_PARENT')
    parent = commit['parents'][0]['sha']
    require(parent == activation['reviewed_parent_sha'], 'ACTIVATION_PARENT_CHANGED')
    approval_sha = verify_published_approval(parent, contract, activation, api)
    comparison = api('GET', '/compare/' + parent + '...' + identity['head_sha'])
    files = comparison.get('files', [])
    require(comparison['total_commits'] == 1 and len(files) == 1
            and files[0]['filename'] == CAMPAIGN + '/RUN_GITHUB.json'
            and files[0]['status'] == 'added', 'ACTIVATION_ONLY_ONE_NEW_FILE')
    # Query the actual shared group, not unrelated repository CI. The reviewed
    # job's platform lease must be its sole ACTIVE member; other pending owners
    # retain their places under queue:max. Endpoint/access errors fail closed.
    group = api('GET', '/actions/concurrency_groups/' + HEAVY_GROUP)
    require(group['group_name'] == HEAVY_GROUP
            and group['total_count'] == len(group['group_members']), 'HEAVY_GROUP_PROFILE')
    require(all(r['status'] in ('in_progress','pending') for r in group['group_members']),
            'HEAVY_GROUP_UNKNOWN_STATE')
    active = [r for r in group['group_members'] if r['status'] == 'in_progress']
    require(len(active) == 1 and active[0]['run_id'] == identity['run_id']
            and active[0].get('job_name') == JOB and type(active[0].get('job_id')) is int,
            'HEAVY_GROUP_NOT_OWN_EXCLUSIVE_JOB')
    jobs = api('GET', '/actions/runs/' + str(identity['run_id']) + '/jobs?per_page=100')
    require(jobs['total_count'] == len(jobs['jobs']) and any(
        j['id'] == active[0]['job_id'] and j['name'] == JOB and j['status'] == 'in_progress'
        for j in jobs['jobs']), 'HEAVY_JOB_API_MISMATCH')
    receipt = {**identity, 'batch_id': model.BATCH, 'claim_ref': CLAIM_REF,
               'contract_sha256': activation['contract_sha256'],
               'activation_sha256': sha(encoded(activation)),
               'state': 'RESERVED_NONRETRYABLE', 'max_lane_executions': 1,
               'independent_approval_commit_sha': approval_sha,
               'shared_heavy_clearance': group,
               'output': str(output), 'utc': datetime.now(timezone.utc).isoformat()}
    # The object can be orphaned after a lost race; only ref creation owns execution.
    blob = api('POST', '/git/blobs', {'content': encoded(receipt).decode(), 'encoding': 'utf-8'})
    tree = api('POST', '/git/trees', {'tree': [{'path': 'CLAIM.json', 'mode': '100644',
                                             'type': 'blob', 'sha': blob['sha']}]})
    claim_commit = api('POST', '/git/commits', {'message': 'Reserve ' + model.BATCH,
                                             'tree': tree['sha'], 'parents': []})
    created = api('POST', '/git/refs', {'ref': CLAIM_REF, 'sha': claim_commit['sha']})
    require(created['ref'] == CLAIM_REF and created['object']['sha'] == claim_commit['sha'],
            'CLAIM_RESPONSE_MISMATCH')
    receipt['claim_commit_sha'] = claim_commit['sha']
    return receipt


def execute(data, contract, activation, output, api=github, env=os.environ, run=None):
    # Creating/writing/fsyncing output must succeed before claiming the batch.
    output.mkdir(parents=True, exist_ok=False)
    prepared = output / 'OUTPUT_PREPARED.json'
    with prepared.open('xb') as f:
        f.write(encoded({'model_started': False, 'contract_sha256': activation['contract_sha256']}))
        f.flush(); os.fsync(f.fileno())
    stage = 'CLAIM_ATTEMPT'
    receipt = None
    try:
        receipt = claim_batch(contract, activation, output, api, env)
        stage = 'CLAIM_EXPORT'
        write_once(output, 'RESERVATION.json', receipt)
        stage = 'STARTED_EXPORT'
        write_once(output, 'STARTED.json', {'max_lane_executions': 1, **receipt})
        stage = 'ECONOMIC_EXECUTION'
        summary = (run or model.run_lanes)(data, contract, output)
        stage = 'COMPLETION_EXPORT'
        write_once(output, 'COMPLETED.json', {'summary_sha256': sha((output/'SUMMARY.json').read_bytes()),
                                             'lane_executions': 1, **receipt})
        return summary
    except BaseException as exc:
        try:
            write_once(output, 'FAILED.json', {'stage': stage, 'error_type': type(exc).__name__,
                                              'error': str(exc), 'automatic_retry': False,
                                              'claim_state': 'ACQUIRED' if receipt else 'UNKNOWN_INSPECT_GITHUB_REF'})
        except BaseException as secondary:
            exc.add_note('FAILED_RECEIPT_NOT_SAVED:' + repr(secondary))
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for k in ('input', 'contract', 'activation', 'output'):
        parser.add_argument('--' + k, type=Path, required=True)
    args = parser.parse_args()
    require(not (ROOT/CAMPAIGN/'COMPLETION.json').exists(), 'COMPLETED_BATCH_NO_REPLAY')
    raw = args.contract.read_bytes(); contract = load(raw); activation = load(args.activation.read_bytes())
    require(activation['contract_sha256'] == sha(raw), 'CONTRACT_CHANGED')
    require(contract['mode'] == model.MODE and tuple(contract['identities']) == model.IDENTITIES
            and contract['max_lane_executions'] == 1, 'MODEL_SCOPE_CHANGED')
    require(contract['window'] == {'start_ms': START, 'end_exclusive_ms': END}
            and contract['unused_oos_certified'] is False, 'WINDOW_CREDIT_CHANGED')
    require(contract['driver_sha256'] == sha(Path(__file__).read_bytes()), 'DRIVER_CHANGED')
    require(contract['script_sha256'] == sha((ROOT/'ops/issue1358_ema21_limit_v1.py').read_bytes()), 'RUNNER_CHANGED')
    for path, expected in contract['source_pins'].items():
        full = (ROOT/path).resolve(strict=True)
        require(full.is_relative_to(ROOT) and sha(full.read_bytes()) == expected, 'SOURCE_PIN:' + path)
    model.saved_parent()  # Verify immutable baseline before claiming; no replay.
    data_raw = bounded_gunzip(args.input.read_bytes(), 64*1024*1024)
    require(sha(data_raw) == PRICE_SHA == contract['input_sha256'], 'INPUT_CHANGED')
    data = load(data_raw)
    require(data['configured_sources_verified'] is True and data['price_bodies_verified'] is True, 'INPUT_UNVERIFIED')
    require(data['config_source']['sha256'] == CONFIG_SHA and data['fields'] == INPUT_FIELDS
            and set(data['minutes']) == set(SYMBOLS), 'INPUT_SCHEMA')
    require(data['config_projection']['regime_fit'] == contract['frozen_regime_fit'], 'FIT_CHANGED')
    result = execute(data, contract, activation, args.output)
    print(encoded(result).decode())

if __name__ == '__main__':
    main()
