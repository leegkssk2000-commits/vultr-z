"""Manual current-DEV adapter for the existing pilot and Registry, never an auto trigger.

GitHub Contents SHA-CAS is the durable transaction boundary. A lost CAS reply
burns the reservation conservatively: no provider POST and no automatic retry.
The canonical file must already exist; this adapter cannot initialize a budget.
"""
import argparse
import base64
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
import urllib.parse
import urllib.request

from backend.research.rebuild.lifecycle_task_v1 import Registry, SCOPE as PRIOR, GateError, digest, utc
from backend.research.rebuild.g5_exit_ai_pilot_v1 import NoRedirect, ROUTES

SCOPE = 'TOP5_AFTER_PR1205_CUMULATIVE_DEV_G5_SUBAGENTS_V1'
ROOT = Path(__file__).resolve().parents[3]
OUTPUT = Path('research/development_evidence') / SCOPE / 'API'
REPOSITORY = 'leegkssk2000-commits/vultr-z'
LEDGER_PATH = str(OUTPUT / 'SHARED_TASK.json')
LEDGER_BRANCH = 'master'
PRIOR_TASK = OUTPUT / 'INHERITED_TASK.json'
MODELS = {'gemini': 'gemini-2.5-flash', 'openai': 'gpt-4.1-mini-2025-04-14'}


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise GateError('INVALID_MONEY')
    value = Decimal(str(value))
    if not value.is_finite() or value < 0:
        raise GateError('INVALID_MONEY')
    return value


def totals(data):
    if set(data['tasks']) != {PRIOR, SCOPE}:
        raise GateError('BOTH_SHARED_SCOPES_REQUIRED')
    amount = Decimal(0)
    counts = {'gemini': 0, 'openai': 0}
    unknown = False
    for task in data['tasks'].values():
        for provider in counts:
            count = task['paid_requests'][provider]
            if type(count) is not int or count < 0:
                raise GateError('INVALID_PROVIDER_COUNT')
            counts[provider] += count
        amount += number(task['settled_cost']) + number(task['outstanding_reserved_cost'])
        unknown |= task['billing_status'] == 'UNKNOWN'
        unknown |= any(a['kind'] == 'api' and a['status'] in ('RESERVED', 'UNKNOWN')
                       for a in task['attempts'].values())
    if amount > 5 or any(v > 1 for v in counts.values()):
        raise GateError('SHARED_CUMULATIVE_BUDGET')
    return amount, counts, unknown


def validate_transition(before, after):
    """Guard existing Registry mutations across both scopes, without a second budget."""
    old_amount, old_counts, unknown = totals(before)
    new_amount, new_counts, _ = totals(after)
    if before.get('budget_scope') != PRIOR or after.get('budget_scope') != PRIOR:
        raise GateError('BUDGET_SCOPE_RESET_FORBIDDEN')
    if after.get('inherited_task_sha256') != before.get('inherited_task_sha256'):
        raise GateError('INHERITED_SOURCE_CHANGED')
    if after['tasks'][PRIOR] != before['tasks'][PRIOR]:
        raise GateError('PRIOR_SCOPE_FROZEN')
    if any(new_counts[p] < old_counts[p] for p in old_counts):
        raise GateError('PROVIDER_COUNTER_RESET')
    if sum(new_counts.values()) > sum(old_counts.values()) and unknown:
        raise GateError('UNRECONCILED_SHARED_RESERVATION')
    for scope, task in before['tasks'].items():
        if not set(task['attempts']).issubset(after['tasks'][scope]['attempts']):
            raise GateError('ATTEMPT_REMOVAL_FORBIDDEN')


class GitHubContents:
    """Fixed repository/path; exact HTTP operations, no redirects or retries."""
    def __init__(self, token, transport=None):
        if not token:
            raise GateError('GITHUB_CONTENTS_WRITE_TOKEN_UNAVAILABLE')
        self._token = token
        self._open = transport or urllib.request.build_opener(NoRedirect()).open
        self.url = 'https://api.github.com/repos/' + REPOSITORY + '/contents/' + LEDGER_PATH

    def _call(self, method, url, body=None):
        headers = {'Authorization': 'Bearer ' + self._token,
                   'Accept': 'application/vnd.github+json',
                   'X-GitHub-Api-Version': '2022-11-28', 'Content-Type': 'application/json'}
        request = urllib.request.Request(url, method=method, headers=headers,
                                         data=None if body is None else json.dumps(body).encode())
        with self._open(request, timeout=20) as response:
            payload = response.read(1_000_001)
            if len(payload) > 1_000_000:
                raise GateError('LEDGER_RESPONSE_TOO_LARGE')
            return json.loads(payload)

    def read(self):
        payload = self._call('GET', self.url + '?ref=' + urllib.parse.quote(LEDGER_BRANCH))
        if payload.get('type') != 'file' or payload.get('encoding') != 'base64':
            raise GateError('CANONICAL_LEDGER_MISSING')
        return payload['sha'], json.loads(base64.b64decode(payload['content']))

    def compare_and_swap(self, sha, data):
        raw = (json.dumps(data, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
        reply = self._call('PUT', self.url, {'branch': LEDGER_BRANCH, 'sha': sha,
            'content': base64.b64encode(raw).decode(),
            'message': 'Record manually authorized shared pilot reservation [skip ci]'})
        read_sha, read_data = self.read()
        if read_sha != reply['content']['sha'] or read_data != data:
            raise GateError('DURABLE_WRITE_UNCONFIRMED')
        return reply['commit']['sha']


class DurableRegistry(Registry):
    def __init__(self, store, inherited_sha, inherited_task=None):
        self.store, self.inherited_sha = store, inherited_sha
        self.inherited_task = inherited_task
        self.last_commit = None

    @contextmanager
    def transaction(self):
        sha, data = self.store.read()  # 404 or access failure is never initialization.
        if data.get('budget_scope') != PRIOR or data.get('inherited_task_sha256') != self.inherited_sha:
            raise GateError('INHERITED_BUDGET_BINDING')
        totals(data)
        if self.inherited_task is not None and data['tasks'][PRIOR] != self.inherited_task:
            raise GateError('INHERITED_TASK_BYTES_CHANGED')
        before = deepcopy(data)
        yield data
        if data != before:
            validate_transition(before, data)
            self.last_commit = self.store.compare_and_swap(sha, data)


def verify_sources(dossier, approval, root=ROOT):
    if dossier.get('scope_key') != SCOPE or dossier.get('data_class') != 'DEV_USED' or dossier.get('holdout_access') is not False:
        raise GateError('CURRENT_DEV_ISOLATION')
    if approval.get('dossier_sha') != digest(dossier) or not dossier.get('source_hashes'):
        raise GateError('CURRENT_DOSSIER_BINDING')
    # Paths are an independently frozen allowlist, not arbitrary dossier input.
    frozen = json.loads((root / OUTPUT / 'SOURCE_ALLOWLIST.json').read_text())
    if dossier['source_hashes'] != frozen['source_hashes']:
        raise GateError('SOURCE_ALLOWLIST_MISMATCH')
    for name, sha in frozen['source_hashes'].items():
        p = (root / name).resolve()
        if not p.is_relative_to(root.resolve()) or hashlib.sha256(p.read_bytes()).hexdigest() != sha:
            raise GateError('DEV_SOURCE_BYTES')


def preflight(dossier, approval, quote, *, event, key_present):
    if event != 'workflow_dispatch' or approval.get('explicit_manual_approval') is not True:
        raise GateError('MANUAL_ONLY')
    if approval.get('scope_key') != SCOPE or not approval.get('approval_id'):
        raise GateError('APPROVAL_SCOPE')
    if not key_present:
        raise GateError('PROVIDER_KEY_UNAVAILABLE')
    provider = approval.get('provider')
    if provider not in MODELS or approval.get('model') != MODELS[provider] or quote.get('model') != MODELS[provider]:
        raise GateError('EXACT_ALLOWLISTED_MODEL')
    if approval.get('price_sha') != digest(quote) or quote.get('provider') != provider:
        raise GateError('PRICE_BINDING')
    if quote.get('currency') != 'USD' or quote.get('request_semantics_verified') is not True:
        raise GateError('TOKEN_LIMIT_SEMANTICS_UNVERIFIED')
    minimum_input = 1048576 if provider == 'gemini' else 1047576
    if number(quote.get('input_token_upper_bound')) < minimum_input or number(quote.get('output_thinking_upper_bound')) < 6000:
        raise GateError('TOKEN_BOUND_BELOW_DOCUMENTED_RESERVATION')
    if not quote.get('official_sources') or not quote.get('checked_at'):
        raise GateError('PRICE_AUTHORITY')
    if approval.get('unresolved_question_required') is not True:
        raise GateError('NO_NECESSARY_UNRESOLVED_QUESTION')
    if approval.get('tax_fx_upper_bound_usd') is None or not approval.get('billing_upper_bound_authority'):
        raise GateError('BILLING_COMPONENT_UNKNOWN')
    # Full documented accepted context is a deliberately loose billing bound.
    # UTF-8 bytes are only a payload-size gate, never a fabricated token count.
    prompt = json.dumps(dossier, sort_keys=True, ensure_ascii=False)
    if len(prompt.encode()) > 16000:
        raise GateError('DOSSIER_BYTE_LIMIT')
    maximum = (number(quote['input_token_upper_bound']) * number(quote['input_usd_per_million'])
               + number(quote['output_thinking_upper_bound']) * number(quote['output_usd_per_million'])) / 1000000
    maximum += number(approval['tax_fx_upper_bound_usd'])
    if not 0 < maximum <= 5:
        raise GateError('USD_RESERVATION_LIMIT')
    return {'provider': provider, 'model': MODELS[provider], 'prompt': prompt,
            'prompt_sha': hashlib.sha256(prompt.encode()).hexdigest(),
            'maximum_reserved_usd': float(maximum), 'dossier_sha': digest(dossier), 'price_sha': digest(quote)}


def request_once(registry, dossier, approval, quote, *, event, key, transport=None, root=ROOT):
    verify_sources(dossier, approval, root)
    plan = preflight(dossier, approval, quote, event=event, key_present=bool(key))
    provider = plan['provider']
    body = ({'contents': [{'role': 'user', 'parts': [{'text': plan['prompt']}]}],
             'generationConfig': {'maxOutputTokens': 6000, 'candidateCount': 1,
                                  'thinkingConfig': {'thinkingBudget': 0}, 'responseMimeType': 'application/json'}}
            if provider == 'gemini' else
            {'model': plan['model'], 'input': plan['prompt'], 'max_output_tokens': 6000,
             'store': False, 'tools': [], 'tool_choice': 'none', 'service_tier': 'default'})
    route = ROUTES[provider] + ('/models/' + plan['model'] + ':generateContent' if provider == 'gemini' else '')
    identity = {'provider': provider, 'model': plan['model'], 'dossier': plan['dossier_sha'], 'prompt': plan['prompt_sha']}
    # No provider network until reservation is remotely committed and read back.
    attempt = registry.reserve(SCOPE, 'W2', 'api', identity, provider=provider, reserve_usd=plan['maximum_reserved_usd'])
    receipt = {'scope_key': SCOPE, 'attempt_id': attempt, 'provider': provider, 'model': plan['model'],
               'route': route, 'dossier_sha': plan['dossier_sha'], 'price_sha': plan['price_sha'],
               'reservation_commit': registry.last_commit, 'reserved_usd': plan['maximum_reserved_usd'],
               'settled_usd': None, 'billing_status': 'UNKNOWN', 'retry': 0, 'fallback': 0, 'formal_credit': 0,
               'started_at': utc()}
    headers = {'Content-Type': 'application/json', **({'x-goog-api-key': key} if provider == 'gemini' else {'Authorization': 'Bearer ' + key})}
    req = urllib.request.Request(route, data=json.dumps(body).encode(), headers=headers, method='POST')
    status = 'UNKNOWN'
    try:
        with (transport or urllib.request.build_opener(NoRedirect()).open)(req, timeout=45) as response:
            raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise GateError('PROVIDER_RESPONSE_TOO_LARGE')
            payload = json.loads(raw)
            receipt.update(http_status=response.status, response_sha=digest(payload),
                           usage=payload.get('usage', payload.get('usageMetadata')), response=payload)
            status = 'DONE'
    except Exception as exc:
        receipt['error_type'] = type(exc).__name__  # never stringify request/key-bearing exceptions
    try:
        registry.finish_attempt(SCOPE, attempt, status, evidence={k: v for k, v in receipt.items() if k != 'response'})
    except Exception as exc:
        receipt['reservation_finish_error_type'] = type(exc).__name__
    receipt['ended_at'] = utc()
    return receipt  # Usage is not an invoice: unsettled reservation remains locked.


def verify_runtime_commit(approval, root=ROOT):
    # Code is frozen first; the later approval commit may refer to that SHA.
    # Every executed owner module must still be byte-identical to that commit.
    sha = approval.get('runtime_commit', '')
    if not re.fullmatch(r'[0-9a-f]{40}', sha):
        raise GateError('FROZEN_RUNTIME_COMMIT')
    modules = ('api_pilot_runtime_v2.py', 'g5_exit_ai_pilot_v1.py', 'lifecycle_task_v1.py')
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    if head != os.getenv('GITHUB_SHA'):
        raise GateError('CHECKOUT_EVENT_SHA_MISMATCH')
    if subprocess.run(['git', 'merge-base', '--is-ancestor', sha, head], cwd=root, capture_output=True).returncode:
        raise GateError('CODE_FREEZE_NOT_ANCESTOR')
    for name in modules:
        path = 'backend/research/rebuild/' + name
        frozen = subprocess.check_output(['git', 'show', sha + ':' + path], cwd=root, stderr=subprocess.DEVNULL)
        if frozen != (root / path).read_bytes():
            raise GateError('FROZEN_RUNTIME_BYTES_CHANGED')


def runtime_presence():
    return {'environment': 'github_actions' if os.getenv('GITHUB_ACTIONS') == 'true' else 'work_local',
            'key_presence': {p: bool(os.getenv(p)) for p in ('GEMINI_API_KEY', 'OPENAI_API_KEY', 'GITHUB_TOKEN')},
            'remote_secret_presence': 'UNKNOWN' if os.getenv('GITHUB_ACTIONS') != 'true' else 'RUNTIME_BINDINGS_ONLY'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--approval', type=Path)
    parser.add_argument('--no-network', action='store_true')
    args = parser.parse_args()
    report = {'scope_key': SCOPE, 'paid_requests_this_execution': 0, 'billing_status': 'NOT_CALLED',
              'runtime': runtime_presence(), 'reason': 'NO_EXPLICIT_PREFLIGHT_PACKAGE'}
    if args.approval and not args.no_network:
        try:
            if os.getenv('GITHUB_EVENT_NAME') != 'workflow_dispatch' or os.getenv('GITHUB_RUN_ATTEMPT') != '1':
                raise GateError('FIRST_MANUAL_ATTEMPT_ONLY')
            if os.getenv('GITHUB_REPOSITORY') != REPOSITORY:
                raise GateError('RUNTIME_REPOSITORY_BINDING')
            if args.approval.resolve().parent != (ROOT / OUTPUT).resolve():
                raise GateError('APPROVAL_PATH_OUTSIDE_SCOPE')
            approval = json.loads(args.approval.read_text())
            verify_runtime_commit(approval)
            dossier = json.loads((ROOT / OUTPUT / 'DOSSIER.json').read_text())
            prices = json.loads((ROOT / OUTPUT / 'OFFICIAL_PRICING.json').read_text())
            quote = prices['providers'][approval['provider']]
            # Presence and all free gates precede opening the remote owner.
            key = os.getenv('GEMINI_API_KEY' if approval['provider'] == 'gemini' else 'OPENAI_API_KEY', '')
            verify_sources(dossier, approval)
            preflight(dossier, approval, quote, event='workflow_dispatch', key_present=bool(key))
            inherited_bytes = (ROOT / PRIOR_TASK).read_bytes()
            inherited_sha = hashlib.sha256(inherited_bytes).hexdigest()
            if approval.get('inherited_task_sha256') != inherited_sha:
                raise GateError('APPROVED_INHERITED_TASK_BINDING')
            inherited_task = json.loads(inherited_bytes)['tasks'][PRIOR]
            registry = DurableRegistry(GitHubContents(os.getenv('GITHUB_TOKEN', '')), inherited_sha, inherited_task)
            report = request_once(registry, dossier, approval, quote, event='workflow_dispatch', key=key)
        except Exception as exc:
            report.update(reason=str(exc) if isinstance(exc, GateError) else type(exc).__name__)
    out = ROOT / 'out' / 'top5-cumulative-api-v4.json'
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, sort_keys=True, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'response'}))


if __name__ == '__main__':
    main()
