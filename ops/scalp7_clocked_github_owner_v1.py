"""GitHub-owned first Squeeze comparison, never a claim-volume recreation.

Only the explicit activation commit can run. A permanent per-batch Git ref is
created atomically BEFORE signals. Retries fail, including changed outputs,
new workflow runs and changed contracts. This script has no SSH/order API.
"""
from __future__ import annotations
import argparse
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
from ops import scalp7_clocked_execution_v1 as model
from ops.kp_committed_cursor_snapshot_v1 import load, require, sha, SYMBOLS
from ops.kp_connected_research_validation_v1 import bounded_gunzip, encoded, write_once, START, END, PRICE_SHA, CONFIG_SHA, INPUT_FIELDS

REPO = 'leegkssk2000-commits/vultr-z'
BRANCH = 'codex/scalp7-clocked-lanes-20261004'
CAMPAIGN = 'research/campaigns/scalp7_20261004/clocked_lanes_v1'
CLAIM_REF = 'refs/heads/research-execution-claims/scalp7-squeeze-clocked-20261004-v1'
JOB = 'economic-comparison'


def github(method, route, value=None):
    require(route.startswith('/'), 'RELATIVE_GITHUB_API_ONLY')
    token = os.environ.get('GH_TOKEN', '')
    require(bool(token), 'GITHUB_TOKEN_REQUIRED')
    req = Request('https://api.github.com/repos/' + REPO + route,
                  data=encoded(value) if value is not None else None, method=method,
                  headers={'Authorization': 'Bearer ' + token,
                           'Accept': 'application/vnd.github+json',
                           'Content-Type': 'application/json'})
    try:
        with urlopen(req, timeout=30) as response:
            require(response.geturl().startswith('https://api.github.com/repos/' + REPO + '/'), 'GITHUB_REDIRECT_REJECTED')
            return json.load(response)
    except HTTPError as exc:
        # Do not dump response bodies, headers or credentials.
        raise RuntimeError('GITHUB_' + method + '_HTTP_' + str(exc.code)) from None


def execution_identity(env, api):
    require(env.get('GITHUB_ACTIONS') == 'true' and env.get('GITHUB_REPOSITORY') == REPO,
            'GITHUB_OWNER_REQUIRED')
    require(env.get('GITHUB_EVENT_NAME') == 'push' and env.get('GITHUB_REF') == 'refs/heads/' + BRANCH,
            'EXPLICIT_BRANCH_PUSH_ONLY')
    require(env.get('GITHUB_RUN_ATTEMPT') == '1' and env.get('GITHUB_JOB') == JOB,
            'NO_RETRY_OR_ALTERNATE_JOB')
    run_id = env.get('GITHUB_RUN_ID', '')
    head = env.get('GITHUB_SHA', '')
    require(run_id.isdigit() and bool(re.fullmatch('[0-9a-f]{40}', head)), 'GITHUB_RUN_IDENTITY')
    run = api('GET', '/actions/runs/' + run_id)
    require(run['head_sha'] == head and run['head_branch'] == BRANCH
            and run['event'] == 'push' and run['run_attempt'] == 1
            and run['status'] == 'in_progress'
            and run['path'] == '.github/workflows/scalp7-clocked-lanes-20261004.yml',
            'API_RUN_IDENTITY_MISMATCH')
    return {'run_id': int(run_id), 'head_sha': head, 'job': JOB, 'attempt': 1}


def claim_batch(contract, activation, output, api=github, env=os.environ):
    require(contract['batch_id'] == model.BATCH == activation['batch_id'], 'BATCH_CHANGED')
    require(contract['claim_ref'] == CLAIM_REF and contract['execution_owner'] == 'GITHUB_ATOMIC_REF_V1',
            'OWNER_CHANGED')
    identity = execution_identity(env, api)
    commit = api('GET', '/git/commits/' + identity['head_sha'])
    require(len(commit['parents']) == 1, 'ACTIVATION_MUST_BE_SINGLE_PARENT')
    parent = commit['parents'][0]['sha']
    require(parent == activation['reviewed_parent_sha'], 'ACTIVATION_PARENT_CHANGED')
    comparison = api('GET', '/compare/' + parent + '...' + identity['head_sha'])
    files = comparison.get('files', [])
    require(comparison['total_commits'] == 1 and len(files) == 1
            and files[0]['filename'] == CAMPAIGN + '/RUN_GITHUB.json'
            and files[0]['status'] == 'added', 'ACTIVATION_ONLY_ONE_NEW_FILE')
    receipt = {**identity, 'batch_id': model.BATCH, 'claim_ref': CLAIM_REF,
               'contract_sha256': activation['contract_sha256'],
               'activation_sha256': sha(encoded(activation)),
               'state': 'RESERVED_NONRETRYABLE', 'max_lane_executions': 2,
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
        write_once(output, 'STARTED.json', {'max_lane_executions': 2, **receipt})
        stage = 'ECONOMIC_EXECUTION'
        summary = (run or model.run_lanes)(data, contract, output)
        stage = 'COMPLETION_EXPORT'
        write_once(output, 'COMPLETED.json', {'summary_sha256': sha((output/'SUMMARY.json').read_bytes()),
                                             'lane_executions': 2, **receipt})
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
            and contract['max_lane_executions'] == 2, 'MODEL_SCOPE_CHANGED')
    require(contract['window'] == {'start_ms': START, 'end_exclusive_ms': END}
            and contract['unused_oos_certified'] is False, 'WINDOW_CREDIT_CHANGED')
    require(contract['driver_sha256'] == sha(Path(__file__).read_bytes()), 'DRIVER_CHANGED')
    require(contract['script_sha256'] == sha((ROOT/'ops/scalp7_clocked_execution_v1.py').read_bytes()), 'RUNNER_CHANGED')
    for path, expected in contract['source_pins'].items():
        full = (ROOT/path).resolve(strict=True)
        require(full.is_relative_to(ROOT) and sha(full.read_bytes()) == expected, 'SOURCE_PIN:' + path)
    require(contract['owner_transfer_sha256'] == sha((ROOT/CAMPAIGN/'OWNER_TRANSFER.json').read_bytes()), 'TRANSFER_CHANGED')
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
