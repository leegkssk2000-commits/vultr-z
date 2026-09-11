"""Verify Issue 1272's closed Stage-0 evidence; never dispatch economics."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from backend.research.rebuild.trendrider_unified_parent_audit_v1 import SCOPE, build_report

EVIDENCE = 'research/development_evidence/' + SCOPE
# Root of trust is this reviewed code; the manifest deliberately excludes
# this owner to avoid a circular self-hash. It covers all saved scope evidence.
EXPECTED_MANIFEST_SHA256 = '48901189347a4bd283831bae7877eef8ae510ced965ec3e5055126ea294e5129'
ZERO_FIELDS = (
    'gene_screens', 'canonical_candidates', 'child_FULL', 'parent_control_replay',
    'economic_replay', 'retry', 'sweep', 'new_market_data_fetch',
    'new_prospective_decode', 'squeeze_prospective_access', 'paid_AI_calls',
    'orders', 'deploy', 'formal_credit', 'remaining_execution_authority',
)


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def verify(root: Path):
    root = root.resolve()
    evidence = root / EVIDENCE
    read = lambda name: json.loads((evidence / name).read_text(encoding='utf-8'))
    manifest_bytes = (evidence / 'EVIDENCE_MANIFEST.json').read_bytes()
    require(hashlib.sha256(manifest_bytes).hexdigest() == EXPECTED_MANIFEST_SHA256,
            'FROZEN_MANIFEST_HASH_MISMATCH')
    manifest = json.loads(manifest_bytes)
    require(manifest['scope_key'] == SCOPE, 'SCOPE_MISMATCH')
    expected_files = manifest['files_sha256']
    require(all(isinstance(p, str) and not Path(p).is_absolute()
                and '..' not in Path(p).parts for p in expected_files), 'UNSAFE_MANIFEST_PATH')
    for relative, expected_sha in expected_files.items():
        path = (root / relative).resolve()
        require(path.is_relative_to(root), 'MANIFEST_PATH_ESCAPE')
        require(hashlib.sha256(path.read_bytes()).hexdigest() == expected_sha,
                'PRESERVED_FILE_CHANGED:' + relative)
    actual_scope_files = {p.relative_to(root).as_posix() for p in evidence.rglob('*')
                          if p.is_file() and p.name not in {
                              'EVIDENCE_MANIFEST.json', 'EXACT_MERGE_VERIFICATION.json'}}
    require(actual_scope_files == {p for p in expected_files if p.startswith(EVIDENCE + '/')},
            'SCOPE_ARTIFACT_SET_CHANGED')
    rebuilt = build_report(root)
    for name, document in rebuilt.items():
        require(read(name) == document, 'SAVED_AUDIT_DRIFT:' + name)
    audit = rebuilt['PARENT_AUDIT.json']
    require(audit['saved_membership_parity'] == 'PASS', 'PARENT_SAVED_PARITY_FAILED')
    require(audit['state'] == 'BLOCKED_PARENT_PARITY'
            and audit['economic_execution_authorized'] is False, 'STAGE0_GATE_REOPENED')
    budget = read('BUDGET_AND_TERMINAL.json')
    require(budget['scope_key'] == SCOPE and budget['scope_status'] == 'REPORT_ONLY', 'SCOPE_NOT_CLOSED')
    require(budget['terminal'] == 'BLOCKED_PARENT_PARITY'
            and budget['unified_status'] == 'TREND_RIDER_UNIFIED_NOT_EARNED', 'TERMINAL_CHANGED')
    require(all(type(budget[k]) is int and budget[k] == 0 for k in ZERO_FIELDS), 'ECONOMIC_OR_AUTHORITY_NONZERO')
    require(budget['survivor_count'] is None and budget['survivor_status'] == 'NOT_EVALUATED',
            'UNEVALUATED_GENES_RELABELED')
    require(all(budget[k] is None for k in ('strategy_digest', 'qualification_boundary', 'g5b_boundary'))
            and budget['g5a_handoff'] == 'NOT_CREATED' and budget['auto_tuning'] is False
            and budget['g6_authorized'] is False, 'UNAUTHORIZED_HANDOFF')
    screen = read('STAGE1_NOT_RUN.json')
    require(screen['screen_count'] == 0 and screen['survivor_count'] is None
            and len(screen['rows']) == 6, 'SCREEN_COUNTS_CHANGED')
    require(all(r['status'] == 'NOT_RUN_PARENT_PARITY' and r['screen_executed'] is False
                and r['survivor'] is None and r['metrics'] is None for r in screen['rows']),
            'UNEVALUATED_SCREEN_HAS_RESULTS')
    answers = rebuilt['OUTCOME_ANSWERS.json']
    require(answers['runtime_decision_use_forbidden'] is True and len(answers['rows']) == 46,
            'OUTCOME_ISOLATION_FAILED')
    return {'state': 'PASS_SAVED_STAGE0_CLOSURE', 'scope_key': SCOPE,
            'preserved_file_count': len(expected_files), 'unique_opportunities': 31,
            'lane_attribution_rows': 46, 'economic_runs': 0,
            'unified_status': budget['unified_status'], 'terminal': budget['terminal']}


if __name__ == '__main__':
    print(json.dumps(verify(Path(__file__).resolve().parents[3]), sort_keys=True))
