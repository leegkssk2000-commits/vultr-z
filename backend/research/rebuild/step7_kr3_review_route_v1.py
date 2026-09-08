"""Exact KR3 dossier route over the existing one-shot, remotely reserved pilot.

No ledger initialization, secret discovery, automatic dispatch, retry or fallback.
The owner binds the existing successor task into the SAME canonical shared ledger.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess

from backend.research.rebuild import api_winrate_runtime_v1 as previous
from backend.research.rebuild.lifecycle_task_v1 import GateError, digest

SCOPE = 'KR3_G5A_DEV_VALIDATION_AFTER_PR1211_V1'
CAMPAIGN = 'ZEL_PARENT_CLOSURE_TO_G5_SURVIVOR'
CANDIDATE = '298ae6dfe19bed2503eae374c4540ae13beab0374033aa27842f3701d0c609cc'
PURPOSE = 'EXACT_KR3_FULL_G5A_MECHANISM_AND_DEV_VALIDATION_REVIEW'
OUTPUT = Path('research/development_evidence') / CAMPAIGN / 'DEV_VALIDATION' / 'AI'
ROOT, LEDGER_PATH = previous.ROOT, previous.LEDGER_PATH
PRIOR_SCOPES = (*previous.PRIOR_SCOPES, previous.SCOPE)


def bound_owner():
    """Reuse V5 durable CAS/transition checks in a separate, scoped namespace."""
    spec = importlib.util.spec_from_file_location('_kr3_review_owner', previous.__file__)
    owner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(owner)
    owner.SCOPE, owner.OUTPUT, owner.PRIOR_SCOPES = SCOPE, OUTPUT, PRIOR_SCOPES
    return owner


def bind_scope(data, task):
    """Pure proposed owner change; never creates another budget or writes it."""
    if SCOPE in data['tasks']:
        bound_owner().totals(data)
        if data['tasks'][SCOPE]['task_id'] != task['task_id']:
            raise GateError('EXISTING_TASK_MUST_BE_INHERITED')
        return deepcopy(data)
    previous.totals(data)
    if task.get('scope_key') != SCOPE or not task.get('approval_ref'):
        raise GateError('NEW_SCOPE_APPROVAL_REQUIRED')
    if (any(task['paid_requests'].values()) or task['settled_cost'] != 0
            or task['outstanding_reserved_cost'] != 0
            or any(a['kind'] == 'api' for a in task['attempts'].values())):
        raise GateError('UNBOUND_PRIOR_API_ACTIVITY')
    result = deepcopy(data)
    result['tasks'][SCOPE] = deepcopy(task)
    bound_owner().totals(result)
    return result


def verify_exact(dossier, approval, quote):
    if (dossier.get('candidate_sha256') != CANDIDATE
            or dossier.get('candidate_mode') != 'FULL'
            or dossier.get('purpose') != PURPOSE
            or dossier.get('campaign_key') != CAMPAIGN
            or approval.get('candidate_sha256') != CANDIDATE
            or approval.get('purpose') != PURPOSE):
        raise GateError('EXACT_KR3_PURPOSE_IDENTITY_REQUIRED')
    if quote.get('checked_at') != datetime.now(timezone.utc).date().isoformat():
        raise GateError('CURRENT_OFFICIAL_QUOTE_REQUIRED')
    # A template or previous candidate's manual dispatch is not authorization.
    if approval.get('template_only') is not False:
        raise GateError('REAL_MANUAL_PACKAGE_REQUIRED')


def request_once(registry, dossier, approval, quote, *, event, key, transport=None, root=ROOT):
    verify_exact(dossier, approval, quote)
    return bound_owner().bound_runtime().request_once(
        registry, dossier, approval, quote, event=event, key=key,
        transport=transport, root=root)


def verify_runtime_commit(approval, root=ROOT):
    previous.verify_runtime_commit(approval, root)
    path = 'backend/research/rebuild/step7_kr3_review_route_v1.py'
    frozen = subprocess.check_output(['git', 'show', approval['runtime_commit'] + ':' + path],
                                    cwd=root, stderr=subprocess.DEVNULL)
    if frozen != (root / path).read_bytes():
        raise GateError('FROZEN_KR3_REVIEW_ROUTE_BYTES_CHANGED')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--approval', type=Path)
    parser.add_argument('--no-network', action='store_true')
    args = parser.parse_args()
    old = previous.old
    report = {'scope_key': SCOPE, 'candidate_sha256': CANDIDATE, 'purpose': PURPOSE,
              'paid_requests_this_execution': 0, 'billing_status': 'NOT_CALLED',
              'runtime': old.runtime_presence(), 'reason': 'NO_EXPLICIT_PREFLIGHT_PACKAGE',
              'formal_credit': 0, 'canonical_ledger': LEDGER_PATH}
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
            dossier = json.loads((ROOT / OUTPUT / 'DOSSIER.json').read_text())
            quote = json.loads((ROOT / OUTPUT / 'OFFICIAL_PRICING.json').read_text())['providers'][approval['provider']]
            verify_exact(dossier, approval, quote)
            owner = bound_owner()
            runtime = owner.bound_runtime()
            key = os.getenv('GEMINI_API_KEY' if approval['provider'] == 'gemini' else 'OPENAI_API_KEY', '')
            runtime.verify_sources(dossier, approval)
            runtime.preflight(dossier, approval, quote, event='workflow_dispatch', key_present=bool(key))
            inherited_sha = hashlib.sha256((ROOT / old.PRIOR_TASK).read_bytes()).hexdigest()
            if approval.get('inherited_task_sha256') != inherited_sha:
                raise GateError('APPROVED_INHERITED_TASK_BINDING')
            registry = owner.DurableRegistry(old.GitHubContents(os.getenv('GITHUB_TOKEN', '')),
                                             inherited_sha, approval.get('prior_scope_digests'))
            report = request_once(registry, dossier, approval, quote,
                                  event='workflow_dispatch', key=key)
        except Exception as exc:
            report.update(reason=str(exc) if isinstance(exc, GateError) else type(exc).__name__)
    out = ROOT / 'out' / 'step7-kr3-review.json'
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, sort_keys=True, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'response'}))


if __name__ == '__main__':
    main()
