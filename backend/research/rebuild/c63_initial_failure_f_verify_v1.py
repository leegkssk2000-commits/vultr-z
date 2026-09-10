"""Saved-only metadata boundary repair; no native economic dispatch.

Frozen charge_and_mark returns variant=M1 (engine lane). The executor then
labels the saved result F_ONLY/B20_F (candidate). Validate both exact namespaces
from raw audits before comparing all fields. No numerical tolerance or omission.
"""
from unittest.mock import patch
from backend.research.rebuild import c63_initial_failure_f_study_v1 as study


def bind_candidate_metadata(charged, raw, lane):
    study.need(lane == 'M1' and charged['variant'] == 'M1', 'NATIVE_LANE_METADATA')
    variants = {r['audit']['variant'] for r in raw.values()}
    study.need(len(variants) == 1 and variants <= set(study.VARIANTS), 'RAW_CANDIDATE_METADATA')
    variant = next(iter(variants))
    study.need(all(r['audit']['rule'] == study.child.RULES[variant] for r in raw.values()), 'RAW_RULE_METADATA')
    return dict(charged, variant=variant)


def verify():
    w=(study.ROOT/'.github/workflows/c63-initial-failure-f-v1.yml').read_text()
    study.need('contents: read' in w and 'contents: write' not in w and
        'persist-credentials: false' in w and 'workflow_dispatch' not in w and
        'study_v1 execute' not in w, 'ECONOMIC_DISPATCH_NOT_RETIRED')
    original = study.integration.charge_and_mark
    def charge(raw, lane, packet, calendar):
        return bind_candidate_metadata(original(raw,lane,packet,calendar),raw,lane)
    # Frozen report was rendered before canonical JSON sorted mapping keys.
    # Reconstruct its original deterministic presentation order from saved data;
    # require identical summary values before checking exact report bytes.
    derived = study.derive_summary()
    original_render = study.render
    def render(summary):
        study.need(summary == derived, 'REPORT_SUMMARY_VALUES')
        return original_render(derived)
    with patch.object(study.integration,'charge_and_mark',charge), patch.object(study,'render',render):
        study.verify()
    print('EXACT_ENGINE_LANE_AND_CANDIDATE_METADATA_BOUNDARY_PASS')


if __name__=='__main__':verify()
