"""V5 approval binding over the frozen V4 request implementation and shared ledger.

The owner commits bind_scope() output to the existing canonical ledger before
manual dispatch. This adapter cannot create or reset a remote budget. Old scope
tasks remain immutable; only this distinct unresolved question uses new W2.
"""
import argparse
from contextlib import contextmanager
from copy import deepcopy
from decimal import Decimal
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess

from backend.research.rebuild import api_pilot_runtime_v2 as old
from backend.research.rebuild.lifecycle_task_v1 import Registry, GateError, digest

SCOPE = 'TOP5_AFTER_PR1206_WINRATE_FIRST_AI_V1'
OUTPUT = Path('research/development_evidence') / SCOPE / 'API'
PRIOR_SCOPES = (old.PRIOR, old.SCOPE)
LEDGER_PATH = old.LEDGER_PATH
ROOT = old.ROOT


def totals(data):
    if set(data['tasks']) != {*PRIOR_SCOPES, SCOPE}:
        raise GateError('THREE_SHARED_SCOPES_REQUIRED')
    amount, counts, unknown = Decimal(0), {'gemini': 0, 'openai': 0}, False
    for task in data['tasks'].values():
        for provider in counts:
            value = task['paid_requests'][provider]
            if type(value) is not int or value < 0:
                raise GateError('INVALID_PROVIDER_COUNT')
            counts[provider] += value
        amount += old.number(task['settled_cost']) + old.number(task['outstanding_reserved_cost'])
        unknown |= task['billing_status'] == 'UNKNOWN'
        unknown |= any(a['kind'] == 'api' and a['status'] in ('RESERVED', 'UNKNOWN')
                       for a in task['attempts'].values())
    if amount > 5 or any(value > 1 for value in counts.values()):
        raise GateError('SHARED_CUMULATIVE_BUDGET')
    return amount, counts, unknown


def bind_scope(data, task):
    """Return a proposed owner commit, never write or reinitialize the ledger."""
    if SCOPE in data['tasks']:
        totals(data)
        if data['tasks'][SCOPE]['task_id'] != task['task_id']:
            raise GateError('EXISTING_TASK_MUST_BE_INHERITED')
        return deepcopy(data)
    old.totals(data)
    if task.get('scope_key') != SCOPE or not task.get('approval_ref'):
        raise GateError('NEW_SCOPE_APPROVAL_REQUIRED')
    if (any(task['paid_requests'].values()) or task['settled_cost'] != 0
            or task['outstanding_reserved_cost'] != 0
            or any(a['kind'] == 'api' for a in task['attempts'].values())):
        raise GateError('UNBOUND_PRIOR_API_ACTIVITY')
    result = deepcopy(data)
    result['tasks'][SCOPE] = deepcopy(task)
    totals(result)
    return result


def validate_transition(before, after):
    _, before_counts, unknown = totals(before)
    _, after_counts, _ = totals(after)
    if before.get('budget_scope') != old.PRIOR or after.get('budget_scope') != old.PRIOR:
        raise GateError('BUDGET_SCOPE_RESET_FORBIDDEN')
    if after.get('inherited_task_sha256') != before.get('inherited_task_sha256'):
        raise GateError('INHERITED_SOURCE_CHANGED')
    for scope in PRIOR_SCOPES:
        if before['tasks'][scope] != after['tasks'][scope]:
            raise GateError('PRIOR_SCOPE_FROZEN')
    if any(after_counts[p] < before_counts[p] for p in before_counts):
        raise GateError('PROVIDER_COUNTER_RESET')
    if sum(after_counts.values()) > sum(before_counts.values()) and unknown:
        raise GateError('UNRECONCILED_SHARED_RESERVATION')
    if not set(before['tasks'][SCOPE]['attempts']).issubset(after['tasks'][SCOPE]['attempts']):
        raise GateError('ATTEMPT_REMOVAL_FORBIDDEN')


class DurableRegistry(Registry):
    def __init__(self, store, inherited_sha, prior_scope_digests):
        self.store = store
        self.inherited_sha = inherited_sha
        self.prior_scope_digests = prior_scope_digests
        self.last_commit = None

    @contextmanager
    def transaction(self):
        sha, data = self.store.read()
        if data.get('budget_scope') != old.PRIOR or data.get('inherited_task_sha256') != self.inherited_sha:
            raise GateError('INHERITED_BUDGET_BINDING')
        totals(data)
        if self.prior_scope_digests != {scope: digest(data['tasks'][scope]) for scope in PRIOR_SCOPES}:
            raise GateError('PRIOR_SCOPE_APPROVAL_BINDING')
        before = deepcopy(data)
        yield data
        if data != before:
            validate_transition(before, data)
            self.last_commit = self.store.compare_and_swap(sha, data)


def bound_runtime():
    """Load an isolated namespace; never mutate the imported old module or file.

    All request, model, cap, source, and reservation-before-POST behavior is the
    existing implementation. Only the authorized scope and source folder vary.
    """
    spec = importlib.util.spec_from_file_location('_winrate_v5_reused_runtime', old.__file__)
    runtime = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runtime)
    runtime.SCOPE, runtime.OUTPUT = SCOPE, OUTPUT
    return runtime


def verify_runtime_commit(approval, root=ROOT):
    old.verify_runtime_commit(approval, root)
    for path in ('backend/research/rebuild/api_winrate_runtime_v1.py',
                 '.github/workflows/top5-cumulative-api-v4.yml'):
        frozen = subprocess.check_output(['git', 'show', approval['runtime_commit'] + ':' + path],
                                         cwd=root, stderr=subprocess.DEVNULL)
        if frozen != (root / path).read_bytes():
            raise GateError('FROZEN_V5_RUNTIME_BYTES_CHANGED')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--approval', type=Path)
    parser.add_argument('--no-network', action='store_true')
    args = parser.parse_args()
    report = {'scope_key': SCOPE, 'paid_requests_this_execution': 0,
              'billing_status': 'NOT_CALLED', 'runtime': old.runtime_presence(),
              'reason': 'NO_EXPLICIT_PREFLIGHT_PACKAGE'}
    if args.approval and not args.no_network:
        try:
            if os.getenv('GITHUB_EVENT_NAME') != 'workflow_dispatch' or os.getenv('GITHUB_RUN_ATTEMPT') != '1':
                raise GateError('FIRST_MANUAL_ATTEMPT_ONLY')
            if os.getenv('GITHUB_REPOSITORY') != old.REPOSITORY:
                raise GateError('RUNTIME_REPOSITORY_BINDING')
            if args.approval.resolve().parent != (ROOT / OUTPUT).resolve():
                raise GateError('APPROVAL_PATH_OUTSIDE_SCOPE')
            approval = json.loads(args.approval.read_text())
            verify_runtime_commit(approval)
            runtime = bound_runtime()
            dossier = json.loads((ROOT / OUTPUT / 'DOSSIER.json').read_text())
            quote = json.loads((ROOT / OUTPUT / 'OFFICIAL_PRICING.json').read_text())['providers'][approval['provider']]
            key = os.getenv('GEMINI_API_KEY' if approval['provider'] == 'gemini' else 'OPENAI_API_KEY', '')
            runtime.verify_sources(dossier, approval)
            runtime.preflight(dossier, approval, quote, event='workflow_dispatch', key_present=bool(key))
            inherited_sha = hashlib.sha256((ROOT / old.PRIOR_TASK).read_bytes()).hexdigest()
            if approval.get('inherited_task_sha256') != inherited_sha:
                raise GateError('APPROVED_INHERITED_TASK_BINDING')
            registry = DurableRegistry(old.GitHubContents(os.getenv('GITHUB_TOKEN', '')),
                                       inherited_sha, approval.get('prior_scope_digests'))
            report = runtime.request_once(registry, dossier, approval, quote,
                                          event='workflow_dispatch', key=key)
        except Exception as exc:
            report.update(reason=str(exc) if isinstance(exc, GateError) else type(exc).__name__)
    out = ROOT / 'out' / 'top5-winrate-api-v5.json'
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, sort_keys=True, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'response'}))


if __name__ == '__main__':
    main()
