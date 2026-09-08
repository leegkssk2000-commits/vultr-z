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
    if approval.get('template_only') is not False:
        raise GateError('REAL_MANUAL_PACKAGE_REQUIRED')


# Bounded saved-result summary. No replay, provider or market access.
DEV_OUTPUT = OUTPUT.parent
MEASURED_INPUTS = ('SPEC.json', 'G5A_RESULT.json', 'VARIANTS/INDEX.json')
VARIANT_IDS = ('direction_flip', 'time_shift_placebo', 'delayed_entry',
               'without_trend_feature', 'without_reclaim_feature', 'without_directional_half',
               'neighbor_19_50_12', 'neighbor_21_50_12', 'neighbor_20_49_12',
               'neighbor_20_51_12', 'neighbor_20_50_11', 'neighbor_20_50_13')


def measured_facts(root=ROOT):
    """Summarize every fixed actual outcome; summaries cannot grant formal credit."""
    docs = [json.loads((Path(root) / DEV_OUTPUT / name).read_bytes()) for name in MEASURED_INPUTS]
    spec, result, index = docs
    rows = index['results']
    if (spec.get('candidate_sha256') != CANDIDATE or result.get('candidate_sha256') != CANDIDATE
            or index.get('specification_sha256') != spec.get('receipt_sha256')
            or result.get('specification_sha256') != spec.get('receipt_sha256')
            or index.get('actual_variants') != 12 or result.get('actual_variants') != 12
            or tuple(r['variant']['id'] for r in rows) != VARIANT_IDS
            or tuple(v['id'] for v in spec['variants']) != VARIANT_IDS
            or any(r.get('status') != 'COMPLETED' for r in rows)):
        raise GateError('EXACT_TWELVE_ACTUAL_DEV_OUTCOMES_REQUIRED')
    observations = []
    for r in rows:
        m = r['metrics']; base = m['base_cost']
        observations.append([r['variant']['id'], r['actual_experiment_ordinal'],
                             m['closed_T'], m['open_T'], base['win_rate'], base['PF'],
                             base['realized_payoff'], m['terminal_net_bps'],
                             m['terminal_cost2x_net_bps'], m['marked_DD_trade_sum_bps']])
    return {'schema': 'zel.step7.kr3.measured_review_input.v1',
            'evidence_kind': 'ACTUAL_REUSED_DEV_VALIDATION', 'independent': False,
            'formal_credit': 0, 'new_candidate_selected': False,
            'specification_sha256': spec['receipt_sha256'],
            'columns': ['variant', 'evaluation_ordinal', 'closed_T', 'open_T', 'win_rate_fraction',
                        'PF', 'net_payoff', 'terminal_net_trade_bps', 'all_cost2_terminal_trade_bps',
                        'marked_DD_trade_bps'],
            'rows': observations,
            'g5a_state': result['alpha_owner_result']['state'],
            'gates': {g['gate']: {'passed': g['passed'],
                       'failure_codes': sorted({f['code'] for f in g['failures']})}
                      for g in result['alpha_owner_result']['gates']},
            'economic_report_states': {k: v['status'] for k, v in result['economic_reports'].items()},
            'limitations': ['All observations are previously used DEV2025, not independent OOS.',
                'Time shifts relatch shifted-bar geometry and regenerate reference/actual occupancy; not timing-only or equal-budget controls.',
                'Observed bars do not guarantee fixed wallclock hours. +1 delay and +6 shift are both included.',
                'Direction flip reflects returns on unchanged long-information exit clock, not a native short strategy.',
                'Costs are inherited modeled proxies; open liquidation marks are hypothetical.',
                'All six measured neighbors and three ablations are reported without choosing a replacement.',
                'Formal report completion remains zero; purged OOS is not executed.']}


def verify_measured(dossier, root=ROOT):
    """Reject missing/stale/edited outcomes before any provider reservation."""
    try:
        for name in MEASURED_INPUTS:
            rel = str(DEV_OUTPUT / name)
            path = Path(root) / rel
            if path.is_symlink() or not path.resolve().is_relative_to(Path(root).resolve()):
                raise GateError('MEASURED_DEV_SOURCE_PATH')
            expected = dossier.get('source_hashes', {}).get(rel)
            if not expected or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise GateError('MEASURED_DEV_SOURCE_BINDING')
        if dossier.get('actual_dev_validation') != measured_facts(root):
            raise GateError('ACTUAL_DEV_PROMPT_MISSING_OR_CHANGED')
    except (KeyError, TypeError, OSError, ValueError) as exc:
        if isinstance(exc, GateError):
            raise
        raise GateError('ACTUAL_DEV_REVIEW_INPUT_INVALID') from exc


def request_once(registry, dossier, approval, quote, *, event, key, transport=None, root=ROOT):
    dossier = deepcopy(dossier)
    verify_exact(dossier, approval, quote)
    verify_measured(dossier, root)
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
            verify_measured(dossier, ROOT)
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
