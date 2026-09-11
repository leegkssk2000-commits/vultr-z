"""Validate the saved zero-survivor sprint closure; never import trading code.

Only JSON metadata and opaque file hashes are read. No market/result packet is
decoded, no lifecycle is replayed, and no registry, authority or file is written.
The frozen Stage1 verifier separately owns saved causal and cash validation.
"""
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCOPE = 'SQUEEZE_CONTINUATION_BENCHMARK_SPRINT_AFTER_PR1266_V1'
REL = Path('research/development_evidence') / SCOPE
PARENT = Path('research/development_evidence/C70_TM_PARTIAL_CAPACITY_REUSE_AFTER_PR1260_V1')
PARENT_SHA = '73b1277b218a1f178e424790271aa161d8ee9365'
RULE = 'C70_TM_CAPREUSE_V1'
PERIODS = ('DEV2025', 'SEEN2026')
SLOTS = ('S1-02', 'S1-03', 'S1-04', 'S1-07')
CORE = ('ARCHITECTURE_SEAL.json', 'G5B_HANDOFF.json', 'STAGE2_SELECTION.json',
        'STAGE3_DECISION.json', 'COST_SEMANTICS.json', 'V2_BACKLOG.json',
        'STAGE1_TABLE.json', 'STAGE1_SELECTION.json', 'BUDGET.json', 'STATUS.json', 'SPEC.json')
CLOSURE_SOURCES = {
    'backend/research/rebuild/squeeze_sprint_closure_verify_v1.py',
    'backend/research/rebuild/test_squeeze_sprint_closure_verify_v1.py',
    '.github/workflows/squeeze-continuation-closure-verify-v1.yml',
}


def canonical_digest(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                             separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def read(path):
    assert Path(path).suffix == '.json', 'ONLY_JSON_METADATA_DECODE'
    return json.loads(Path(path).read_text(encoding='utf-8'))


def file_digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def bound_path(root, name):
    root = Path(root).resolve()
    assert isinstance(name, str) and not Path(name).is_absolute(), 'RELATIVE_REFERENCE_REQUIRED'
    path = (root / name).resolve()
    assert path.is_relative_to(root) and path.is_file(), 'BOUND_REFERENCE_REQUIRED:' + name
    return path


def verify_files(root, values):
    assert isinstance(values, dict) and values, 'NONEMPTY_HASH_MANIFEST_REQUIRED'
    for name, digest in values.items():
        assert file_digest(bound_path(root, name)) == digest, 'FILE_HASH:' + name
    return len(values)


def expect(record, values, label):
    for key, value in values.items():
        assert key in record and type(record[key]) is type(value) and record[key] == value, label + ':' + key


def screen_gate(metric):
    def finite_positive(key):
        value = metric[key]
        assert type(value) in (int, float) and isfinite(value), 'FINITE_SCREEN_METRIC:' + key
        return value > 0

    def retention(key):
        value = metric[key]
        assert value is None or (type(value) in (int, float) and isfinite(value)), 'FINITE_RETENTION:' + key
        return value is not None and value >= .6

    normal = finite_positive('normal_increment_bps')
    return dict(source=metric['source_conformance'] == 'PASS',
                causal=metric['causal_integrity'] == 'PASS', normal_positive=normal,
                cost2_positive=finite_positive('cost2_increment_bps'),
                ordinary_retained=retention('ordinary_winner_retention'),
                top_decile_retained=retention('top_decile_winner_retention'),
                positive_after_winner_cuts=normal)


def verify(root=ROOT, require_evidence_manifest=False):
    root = Path(root).resolve()
    out = root / REL
    documents = {name: read(out / name) for name in CORE}
    spec, seal, handoff = (documents[name] for name in ('SPEC.json', 'ARCHITECTURE_SEAL.json', 'G5B_HANDOFF.json'))
    identity = seal['identity']
    expect(spec, dict(scope=SCOPE, stage1_slots=list(SLOTS), prior_candidates=84,
                      prior_evaluations=152, challenge='NOT_AVAILABLE'), 'FROZEN_SCOPE')
    # All runtime/evidence dependencies belong to the original pre-screen seal.
    frozen_counts = {group: verify_files(root, spec[group]) for group in
                     ('source_files_sha256', 'preserved_files_sha256')}
    implementation = {name: digest for name, digest in spec['preserved_files_sha256'].items()
                      if name.endswith('.py') and not Path(name).name.startswith('test_')}
    assert len(implementation) == 65 and identity['implementation_files_sha256'] == implementation, 'EXACT_PARENT_DEPENDENCY_SET'
    verify_files(root, implementation)
    sources = {name: digest for name, digest in spec['source_files_sha256'].items()
               if str(REL / 'SOURCES') + '/' in name}
    assert identity['benchmark_source_receipts_sha256'] == sources, 'EXACT_SOURCE_RECEIPTS'
    expect(identity, dict(canonical_candidate_ordinal=82, parent_exact_merge_sha=PARENT_SHA,
                          implementation_rule=RULE, strategy_family='SQUEEZE_CONTINUATION',
                          strategy_name='Squeeze Continuation v1',
                          implementation_entrypoint='backend.research.rebuild.c70_tm_capreuse_v1.replay'), 'EXACT_PARENT_IDENTITY')
    module, function = identity['implementation_entrypoint'].rsplit('.', 1)
    code = bound_path(root, module.replace('.', '/') + '.py').read_text()
    assert '\ndef ' + function + '(' in code, 'REAL_IMPLEMENTATION_ENTRYPOINT'
    assert identity['parent_spec_sha256'] == file_digest(root / PARENT / 'SPEC.json'), 'PARENT_SPEC_BINDING'
    assert file_digest(bound_path(root, identity['parent_source_binding_path'])) == identity['parent_source_binding_sha256'], 'PARENT_RULE_SOURCE_BINDING'
    freeze = read(out / 'REMOTE_FREEZE.json')
    assert identity['source_freeze_commit'] == identity['code_sha'] == freeze['commit_sha'] == freeze['remote_readback_sha'], 'REMOTE_SOURCE_FREEZE'
    assert freeze['spec_sha256'] == file_digest(out / 'SPEC.json'), 'REMOTE_SPEC_BINDING'
    rules = identity['exact_rules']
    expect(rules, dict(components_added=[], failed_comparators_only=[
        'candidate83 group-PROFITLOCK', 'candidate84 LOTLOCK']), 'NO_FAILED_COMPONENT_ADOPTION')
    assert rules['entry']['authoritative_functions'] == [
        'chart_mechanism_execution_v1.m1_setups', 'm1_er_range_rescue_v1.context',
        'c63_c70_trader_management_v1.c70_context'], 'REAL_ENTRY_FUNCTION_LOCATORS'
    assert identity['mechanism_sha'] == canonical_digest(rules), 'MECHANISM_DIGEST'
    for field, parts in (
        ('entry_sha', ('chart_mechanism', 'm1_er_range', 'c63_daily_ema21', 'c63_c70_trader_management')),
        ('exit_sha', ('c70_tm_capreuse', 'c63_c70_trader_management'))):
        selected = {name: digest for name, digest in implementation.items() if any(part in name for part in parts)}
        assert identity[field] == canonical_digest(selected), 'CODE_COMPONENT_DIGEST:' + field
    digest = canonical_digest(identity)
    assert seal['strategy_digest'] == digest, 'ARCHITECTURE_IDENTITY_DIGEST'
    expect(seal, dict(status='ARCHITECTURE_FROZEN', selected_by='STAGE1_ZERO_SURVIVORS_FALLBACK_EXACT_PARENT',
                      operating_adoption=False, formal_credit=0, g5b_terminal_pass=False,
                      g6_allowed=False, used_dev_automatic_tuning=False, next_ideas='v2_backlog'), 'ARCHITECTURE_AUTHORITY')

    table, selection = documents['STAGE1_TABLE.json'], documents['STAGE1_SELECTION.json']
    assert set(table) == set(selection['decisions']) == set(SLOTS), 'ALL_FOUR_SCREEN_ITEMS_REQUIRED'
    expect(selection, dict(stage='STAGE1', survivors=[], hard_gate_passed=[],
                           pareto_or_deterministic_cap_excluded=[], per_window_gate='BOTH_SEPARATELY',
                           FULL=0, canonical_candidates=0), 'ZERO_SURVIVOR_SELECTION')
    starts = documents['BUDGET.json']['squeeze_sprint_allocation']['screen_window_starts']
    assert len(starts) == 8 and {(s['slot'], s['period']) for s in starts} == {
        (slot, per) for slot in SLOTS for per in PERIODS}, 'EIGHT_UNIQUE_SCREEN_STARTS'
    for slot in SLOTS:
        assert set(table[slot]) == set(selection['decisions'][slot]) == set(PERIODS), 'BOTH_WINDOWS_REQUIRED'
        passed = []
        for per in PERIODS:
            folder = out / 'STAGE1' / slot / per
            metric = read(folder / 'SCREEN_METRICS.json')
            assert metric == table[slot][per], 'SCREEN_TABLE_BOUND_TO_SAVED_METRICS'
            checks = screen_gate(metric)
            assert selection['decisions'][slot][per] == dict(checks=checks, passed=all(checks.values())), 'INDEPENDENT_GATE_DECISION'
            passed.append(all(checks.values()))
            receipt, attempt = read(folder / 'RECEIPT.json'), read(folder / 'ATTEMPT.json')
            verify_files(folder, receipt['files'])
            expect(receipt, dict(status='PASS', FULL=0, canonical_candidates=0), 'SCREEN_RECEIPT')
            expect(attempt, dict(status='COMPLETED', slot=slot, period=per, FULL=0,
                                 canonical_candidate_number=None, retry=False), 'SCREEN_COMPLETED_ONCE')
            assert attempt == next(s for s in starts if (s['slot'], s['period']) == (slot, per)), 'BUDGET_SCREEN_ATTEMPT_BINDING'
            assert receipt['spec_sha256'] == attempt['spec_sha256'] == freeze['spec_sha256'], 'SCREEN_FROZEN_SPEC'
            assert receipt['freeze_commit'] == attempt['freeze_commit'] == identity['code_sha'], 'SCREEN_FROZEN_CODE'
        assert not all(passed), 'ZERO_SURVIVOR_FALLBACK_REQUIRES_FAILED_WINDOW'
    assert seal['stage1_selection_sha256'] == file_digest(out / 'STAGE1_SELECTION.json'), 'SEALED_SELECTION_BINDING'
    assert seal['architecture_frozen_at_ns'] > max(s['finished_ns'] for s in starts), 'ARCHITECTURE_AFTER_SCREEN_COMPLETION'
    expect(documents['STAGE2_SELECTION.json'], dict(stage='STAGE2', status='NOT_RUN_NO_STAGE1_SURVIVORS',
           FULL=0, candidates=0, survivors=[], table=[]), 'NO_STAGE2_EXECUTION')
    expect(documents['STAGE3_DECISION.json'], dict(stage='STAGE3', status='NO_BUNDLE_FREEZE_EXACT_PARENT',
           B1='EXACT_CANDIDATE82_CAPREUSE', B2=None, FULL=0, new_bundles=0, interaction_delta=None,
           interaction_status='NOT_APPLICABLE_NO_ORTHOGONAL_SURVIVORS', strategy_digest=digest), 'NO_STAGE3_EXECUTION')
    for stage in ('STAGE2', 'STAGE3', 'CHALLENGE'):
        assert not (out / stage).exists() or not any(p.is_file() for p in (out / stage).rglob('*')), 'UNDECLARED_ECONOMIC_STAGE:' + stage

    prior, budget = read(out / 'HISTORY_PRIOR.json'), documents['BUDGET.json']
    assert {k: v for k, v in budget.items() if k != 'squeeze_sprint_allocation'} == prior, 'ALL_PRIOR_HISTORY_UNCHANGED'
    allocation = budget['squeeze_sprint_allocation']
    expect(allocation, dict(scope=SCOPE, status='CLOSED_NO_SURVIVORS', FULL_completed=0, FULL_failed=0,
           FULL_started=0, new_canonical_candidates=0, remaining_authorized_FULL=0,
           remaining_authorized_candidates=0, stage2_trials=[], stage3_trials=[], challenge_trials=[],
           screen_items_completed=4, screen_windows_completed=8, screen_failed=0, retry=False,
           unused_FULL_closed=10, unused_candidates_closed=4, FIXED=0, sweep=0, arbitrary_OOS=0,
           paid_AI_calls=0, parent_replays=0, live=0, orders=0, deploy=0), 'CLOSED_ECONOMIC_AUTHORITY')
    expect(budget, dict(cumulative_actual=84, cumulative_actual_evaluations=152), 'UNCHANGED_CUMULATIVE_TOTALS')
    challenge = read(out / 'CHALLENGE_WINDOW_SEALED.json')
    assert file_digest(out / 'CHALLENGE_WINDOW_SEALED.json') == spec['challenge_sha256'], 'PRESTAGE1_CHALLENGE_HASH'
    expect(challenge, dict(status='NOT_AVAILABLE', sealed_window=None,
           challenge_FULL_authorized_for_dispatch=0, challenge_economic_outcomes_decoded=0,
           formal_G5B_credit=0, new_historical_window_collection=0), 'NO_NEW_CHALLENGE')

    costs = documents['COST_SEMANTICS.json']
    assert file_digest(out / 'COST_SEMANTICS.json') == identity['cost_semantics_sha256'], 'COST_SEMANTICS_BINDING'
    assert costs['source_packets_sha256'] == spec['input_packet_sha256'], 'SAME_FROZEN_COST_PACKETS'
    expect(costs, dict(evidence_type='USED_DEV_PROXY_NOT_PRODUCTION_GRADE', formal_credit=0,
           return_unit='NORMALIZED_INITIAL_FULL_ENTRY_NOTIONAL_WEIGHTED_TRADE_BPS_NOT_ACCOUNT_RETURN'), 'DEV_COST_LIMITS')
    expect(handoff, dict(status='PREPARED_NOT_ACTIVE', candidate_id=RULE, candidate_ordinal=82,
           strategy_name='Squeeze Continuation v1', strategy_digest=digest, formal_fresh_T=0,
           preboundary_formal_credit=0, activation_id=None, cohort_id=None, boundary_ms=None,
           fresh_collection_started=False, g5a_formal_pass=False, g5b_terminal_pass=False,
           g6_allowed=False, historical_backfill=False, promotion_authority=False,
           selection_authority=False, runtime_registered=False, execution_authority='NONE',
           order_authority='BLOCKED', live_trade_authority='BLOCKED',
           g5a_status='UNCONFIRMED_NO_BOUND_RECEIPT'), 'G5B_PREPARED_AUTHORITY')
    assert handoff['architecture_seal_path'] == str(REL / 'ARCHITECTURE_SEAL.json'), 'G5B_EXACT_SEAL_PATH'
    assert handoff['architecture_seal_sha256'] == file_digest(out / 'ARCHITECTURE_SEAL.json'), 'G5B_SEAL_HASH'
    for field in ('code_sha', 'entry_sha', 'exit_sha', 'mechanism_sha'):
        assert handoff[field] == identity[field], 'G5B_IDENTITY:' + field
    assert handoff['dev_cost_semantics_sha256'] == identity['cost_semantics_sha256'], 'G5B_DEV_COST_HASH'
    assert handoff['source_receipts_sha256'] == sources, 'G5B_SOURCE_RECEIPTS'
    expect(handoff['handoff_issue'], dict(number=1268,
           url='https://github.com/leegkssk2000-commits/vultr-z/issues/1268'), 'BOUND_G5B_HANDOFF_ISSUE')
    expect(handoff['checkpoints'], dict(T6='EARLY_KILL_OR_CONTINUE_DIAGNOSTIC',
           T12='PROVISIONAL_NOT_TERMINAL', terminal='EXPLICIT_REVIEWED_SAME_LANE_RECEIPT_REQUIRED'), 'FORMAL_TERMINAL_BOUNDARY')
    assert {b['code'] for b in handoff['activation_blockers']} == {
        'LIFECYCLE_RUNTIME_NOT_SUPPORTED', 'G5A_EXACT_IDENTITY_PASS_RECEIPT_UNCONFIRMED',
        'FRESH_SOURCE_RECEIPT_AND_BOUNDARY_NOT_CREATED', 'PRODUCTION_GRADE_LOT_COST_PROVENANCE_REQUIRED'}, 'ALL_ACTIVATION_BLOCKERS'
    for blocker in handoff['activation_blockers']:
        bound_path(root, blocker['source'].split('::')[0])
    for field in ('runtime_registry', 'runtime_freeze_registry'):
        name, anchor = handoff[field].split('#')
        assert anchor in read(bound_path(root, name)), 'VALID_RUNTIME_REGISTRY_REFERENCE'
    expect(documents['V2_BACKLOG.json'], dict(status='BACKLOG_ONLY_NO_EXECUTION_AUTHORITY',
           automatic_successor=False, items=[], version1_strategy_digest=digest), 'NO_AUTOMATIC_V2')
    status = documents['STATUS.json']
    expect(status, dict(scope=SCOPE, architecture_status='FROZEN', automatic_successor=False,
           challenge='NOT_AVAILABLE', cumulative_candidates=84, cumulative_evaluations=152,
           deploy=0, economic_FULL=0, economics_status='CLOSED_NO_SURVIVORS', formal_credit=0,
           g5b_handoff='PREPARED_NOT_ACTIVE', new_canonical_candidates=0,
           order_authority='BLOCKED', remaining_economic_authority=0), 'CLOSED_SCOPE_STATUS')
    expect(status['funnel'], dict(final_architectures=1, source_eligible=4, sources_reviewed=8,
           stage1_screened=4, stage1_survivors=0, stage2_survivors=0), 'ACTUAL_FUNNEL')
    assert status['status'] in ('IMPLEMENTATION_COMPLETE_PENDING_CI_REVIEW_MERGE', 'REPORT_ONLY'), 'REVIEW_OR_FINAL_CLOSURE_ONLY'
    source_manifest = out / 'CLOSURE_SOURCE_HASHES.json'
    manifest = out / 'EVIDENCE_HASHES.json'
    if require_evidence_manifest:
        assert manifest.is_file(), 'CLOSURE_EVIDENCE_MANIFEST_REQUIRED'
        assert source_manifest.is_file(), 'CLOSURE_SOURCE_MANIFEST_REQUIRED'
    closure_source_count = 0
    if source_manifest.is_file():
        closure_sources = read(source_manifest)
        expect(closure_sources, dict(schema_version='zel.squeeze_continuation.closure_sources.v1'), 'CLOSURE_SOURCE_SCHEMA')
        assert set(closure_sources['files']) == CLOSURE_SOURCES, 'EXACT_CLOSURE_SOURCE_SET'
        closure_source_count = verify_files(root, closure_sources['files'])
    manifest_count = 0
    if manifest.is_file():
        hashes = read(manifest)
        assert set(CORE) | {'CLOSURE_SOURCE_HASHES.json'} <= set(hashes), 'CLOSURE_EVIDENCE_MANIFEST_COVERAGE'
        manifest_count = verify_files(out, hashes)
    return dict(status='PASS_SAVED_CLOSURE', strategy_digest=digest, selected_candidate=82,
                implementation_files=len(implementation), frozen_files=frozen_counts,
                evidence_manifest_files=manifest_count, closure_source_files=closure_source_count,
                screen_items=4, screen_windows=8,
                new_candidates=0, economic_FULL=0, economic_replays=0, market_packets_decoded=0,
                result_packets_decoded=0, g5b_status='PREPARED_NOT_ACTIVE', formal_fresh_T=0,
                new_orders=0, file_writes=0)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--require-evidence-manifest', action='store_true')
    print(json.dumps(verify(require_evidence_manifest=parser.parse_args().require_evidence_manifest),
                     sort_keys=True, indent=2, allow_nan=False))
