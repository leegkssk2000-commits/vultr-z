"""Post-run saved-only verifier. Never dispatches or retries an economic run.

The original verifier compared an in-memory tuple with its JSON list. Keep
the frozen executor and evidence unchanged; normalize only JSON containers
at the accounting boundary, without tolerances or numeric coercion.
"""
import json
from unittest.mock import patch
from backend.research.rebuild import c63_r_b20_study_v1 as study


def verify():
    closure = study.ROOT / (study.OUT + '_CLOSURE')
    notes = study.read(closure / 'TRANSPORT_NOTES.json')
    for note in notes['notes']:
        original = study.ROOT / note['original_preserved_at']
        frozen = study.ROOT / note['path']
        study.need(study.h(original) == note['original_sha256'], 'ORIGINAL_ATTACHMENT_BYTES')
        study.need(study.h(frozen) == note['frozen_repository_sha256'], 'FROZEN_DIAGNOSTIC_BYTES')
        study.need(original.read_bytes().replace(b'\r\n', b'\n') == frozen.read_bytes(),
                   'NON_NEWLINE_TRANSPORT_CHANGE')
        manifest = study.read(study.ROOT / study.OUT / 'HANDOFF_INPUT' / 'SHA256.json')
        study.need(manifest[original.name] == study.h(original), 'DIAGNOSTIC_ARCHIVE_BINDING')
    workflow = (study.ROOT / '.github/workflows/c63-r-b20-v1.yml').read_text()
    study.need('contents: read' in workflow and 'contents: write' not in workflow and
               'persist-credentials: false' in workflow and 'workflow_dispatch' not in workflow and
               'c63_r_b20_study_v1 execute' not in workflow, 'ECONOMIC_DISPATCH_NOT_RETIRED')
    original = study.a.compare

    def json_compare(*args, **kwargs):
        return json.loads(study.p.canonical(original(*args, **kwargs)))

    with patch.object(study.a, 'compare', json_compare):
        study.verify()
    summary = study.read(study.ROOT / study.OUT / 'SUMMARY.json')
    results = {}
    for per in study.PERIODS:
        results[per] = {label:study.baseline(label, per) for label in ('C63','R')}
        results[per]['R_B20'] = study.gz(study.ROOT / study.OUT / per / 'RESULT.json.gz')
        snapshots = {label:study.a.snapshot(result) for label,result in results[per].items()}
        study.need(snapshots == summary['periods'][per]['snapshots'], 'ALL_COMPARATOR_SNAPSHOTS')
        for label in ('C63','R'):
            checks = study.prior.d.prior.previous.checks(snapshots[label], snapshots['R_B20'])
            study.need(checks == summary['periods'][per]['checks_vs_'+label], 'ORIGINAL_OBJECTIVES')
        risk = {label:study.closed_risk(result) for label,result in results[per].items()}
        study.need(risk == summary['periods'][per]['risk_by_rule'], 'LOSS_TAIL_PARITY')
    combined = {label:study.aggregate([results[per][label] for per in study.PERIODS])
                for label in ('C63','R','R_B20')}
    study.need(combined == summary['disjoint_arithmetic'], 'WEIGHTED_DISJOINT_AGGREGATE')
    goal = all(all(summary['periods'][per]['checks_vs_C63'].values()) for per in study.PERIODS)
    gain = all(summary['periods'][per]['checks_vs_C63']['net_up'] and
               summary['periods'][per]['checks_vs_C63']['cost2_up'] for per in study.PERIODS)
    expected = 'DEVELOPMENT_GOAL_MET' if goal else 'PARTIAL_IMPROVEMENT' if gain else 'REJECT_KEEP_C63'
    study.need(summary['status'] == expected, 'FROZEN_JUDGMENT_PARITY')
    print('JSON_CONTAINER_PARITY_AND_ORIGINAL_JUDGMENT_PASS_NO_REPLAY')


if __name__ == '__main__':
    verify()
