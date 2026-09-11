"""Read-only closure verification for Issue1270's rejected qualification.

Never calls a strategy replay, alpha qualification, boundary constructor, source
provider, registry writer or collector. Rejection is an outcome, not authority
to retune candidate82 or to activate a lane.
"""
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path

from backend.research.rebuild import squeeze_g5a_qualification_v1 as qualification

ROOT = Path(__file__).resolve().parents[3]
REL = Path('research/development_evidence') / qualification.SCOPE
REGISTRY = 'backend/research/rebuild/g5_clean_runner_contract_effective_v1.json'
FREEZE = 'backend/research/rebuild/g5_clean_runner_strategy_freeze_effective_v1.json'
LANES = {'break_and_continue', 'keltner_trend', 'supertrend_pullback'}
AUTH = dict(runtime_registered=False, fresh_collection_started=False,
            activation_id=None, cohort_id=None, boundary_ms=None, boundary_utc=None,
            formal_fresh_T=0, open_T=0, preboundary_formal_credit=0,
            historical_backfill=False, selection_authority=False, promotion_authority=False,
            execution_authority='NONE', order_authority='BLOCKED', live_trade_authority='BLOCKED',
            exchange_order_submitted=False, g5b_terminal_pass=False, g6_allowed=False,
            boundary_constructor_called=False, collector_provider_calls=0)


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def typed_equal(record, expected, label):
    for key, value in expected.items():
        if type(record.get(key)) is not type(value) or record.get(key) != value:
            raise ValueError(label + ':' + key)


def verify_hashes(root, mapping):
    if not mapping:
        raise ValueError('NONEMPTY_HASH_MANIFEST_REQUIRED')
    for name, expected in mapping.items():
        path = qualification.bound_path(root, name)
        if digest(path) != expected:
            raise ValueError('SAVED_FILE_HASH:' + name)
    return len(mapping)


def source_diagnostic(snapshot):
    records = snapshot['records']
    prefix = 'backend/research/rebuild/'
    stale = records[prefix + 'g5_data_stale_evidence_v1.json']['content']
    cutover = records[prefix + 'g5_clean_runner_post_cutover_3bar_v1.json']['content']
    latest = records[prefix + 'g5_clean_runner_run_latest_v1.json']['content']
    authority = stale['authority_value']
    last = max(int(datetime.fromisoformat(x.replace('Z', '+00:00')).timestamp()*1000)
               for x in stale['bars'])
    age = snapshot['observed_at_ms'] - last
    return dict(observation_only=True, latest_stored_run_utc=latest['generated_at_utc'],
                stale_authority_ms=authority, latest_stored_bar_ms=last,
                stored_bar_age_ms=age, stored_source_fresh=0 <= age < authority,
                durable_cutover_pass=cutover['post_cutover_3bar_pass'],
                squeeze_fresh_source_receipt=None, production_grade_ready=False,
                source_provider_calls=0)


def verify(root=ROOT):
    root = Path(root).resolve()
    folder = root / REL
    spec = read(folder / 'SPEC.json')
    typed_equal(spec, dict(scope_key=qualification.SCOPE, authorization_issue=1270,
                exact_candidate='C70_TM_CAPREUSE_V1', candidate_ordinal=82,
                qualification_attempts_authorized=1, retries_authorized=0,
                new_candidates_authorized=0, parameter_or_window_changes_authorized=0,
                prior_candidates=84, prior_evaluations=152,
                stop_on_g5a_or_parity_failure=True, qualification_economics_in_CI=False,
                new_collector_schedule=False), 'SPEC_AUTHORITY')
    preserved = verify_hashes(root, spec['preserved_files_sha256'])
    implementation = verify_hashes(root, read(folder / 'IMPLEMENTATION_HASHES.json')['files'])
    evidence = verify_hashes(folder, read(folder / 'EVIDENCE_HASHES.json')['files'])
    checked = qualification.verify_only(root)
    q = read(folder / 'G5A_QUALIFICATION.json')
    status = read(folder / 'STATUS.json')
    qualification.verify_seal(status)
    typed_equal(status, AUTH, 'STATUS_AUTHORITY')
    typed_equal(status, dict(scope_key=qualification.SCOPE,
                state='G5A_FAIL_NO_G5B_ACTIVATION', verdict=q['verdict'],
                candidate_id='C70_TM_CAPREUSE_V1', candidate_ordinal=82,
                strategy_digest=qualification.EXPECTED['strategy_digest'],
                qualification_attempts=1, qualification_remaining=0,
                economic_replays=0, new_candidates=0, cumulative_candidates=84,
                cumulative_evaluations=152, retry=False,
                qualification_receipt_sha256=q['receipt_sha256']), 'STATUS_QUALIFICATION')
    if status['p0_p6'] != q['p0_p6'] or status['report_complete_count'] != 0:
        raise ValueError('STATUS_G5A_REPORT_PARITY')
    if status['source_readiness'] != source_diagnostic(read(folder / 'SOURCE_STATE_SNAPSHOT.json')):
        raise ValueError('STORED_SOURCE_READINESS_PARITY')
    active = read(root / REGISTRY)['active_strategies']
    assets = read(root / FREEZE)['active_runner_assets']
    if {x['strategy_id'] for x in active} != LANES or len(active) != 3:
        raise ValueError('EXISTING_THREE_LANES_OR_UNAUTHORIZED_SQUEEZE_REGISTRATION')
    if {x['strategy_id'] for x in assets.values()} != LANES or len(assets) != 3:
        raise ValueError('EXISTING_THREE_FREEZE_ASSETS')
    parity = read(folder / 'ADAPTER_PARITY.json')
    typed_equal(parity, dict(status='PASS', formal_credit=0, economic_replays=0,
                saved_parent_campaigns=105, saved_parent_trace_events=3328), 'ADAPTER_PARITY')
    if any(value != 'PASS' for value in parity['checks'].values()):
        raise ValueError('ADAPTER_PARITY_GATE_FAILED')
    if status['adapter_parity_sha256'] != digest(folder / 'ADAPTER_PARITY.json'):
        raise ValueError('STATUS_PARITY_RECEIPT_BINDING')
    if status['production_evidence_ready'] is not False:
        raise ValueError('NO_GENUINE_SQUEEZE_PRODUCTION_EVIDENCE')
    return dict(status='PASS_SAVED_BLOCKED_SCOPE_VERIFIED', verdict=status['verdict'],
                preserved_files=preserved, implementation_files=implementation,
                evidence_files=evidence, qualification_reexecuted=False,
                economics_reexecuted=False, existing_three_lanes_preserved=True,
                qualification_receipt_sha256=checked['receipt_sha256'], **AUTH)


if __name__ == '__main__':
    print(json.dumps(verify(), sort_keys=True, indent=2))
