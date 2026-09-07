"""Bind existing KR3 FULL evidence to the unchanged Alpha Proof owner.

This is an evidence projection, never a market replay or a formal approval.
The only decoded economic inputs are the two already-used, pinned DEV results.
No network, prospective paths, raw source archives, provider calls or gate edits.
"""
from __future__ import annotations
import argparse
import gzip
import hashlib
import json
from copy import deepcopy
from pathlib import Path
from backend.research.alpha_proof import a1_alpha_proof_gate_v1 as alpha
from backend.research.rebuild import g5b_operational_terminal_v1 as terminal

ROOT = Path(__file__).resolve().parents[3]
CAMPAIGN = 'research/development_evidence/ZEL_PARENT_CLOSURE_TO_G5_SURVIVOR'
DEV = 'research/development_evidence/FOCUSED_REPAIR_20260907_V1'
SPEC = CAMPAIGN + '/G5A_READINESS/KR3_EVIDENCE_INPUTS.json'
CANDIDATE = '298ae6dfe19bed2503eae374c4540ae13beab0374033aa27842f3701d0c609cc'
SELECTION = 'f63177df5c4720924ad1718ad7d50dde64697c0a8b2409413d94f44f5dddcf7d'
RESULT = '359a7b676a2dd95f0f17970cef363c40eada47d5f795ef4b1129b04a2b64efc7'
HISTORICAL_SPEC = 'a80f32afd72b25a1f2a7332096fa3874e8f9c2613765ec866673e68a878d4691'
CODE = 'backend/research/rebuild/'
NATIVE = tuple(CODE + n + '_v1.py' for n in (
    'parallel_exit_keltner', 'keltner_cumulative_entry_adapter',
    'keltner_opportunity_reservation_adapter', 'keltner_m2_context',
    'keltner_kr1', 'keltner_kr3'))
FILES = (CAMPAIGN+'/SELECTION.json', CAMPAIGN+'/CONTRACT/APPLICATION.json',
         DEV+'/SPEC.json', DEV+'/KR3/receipt.json', DEV+'/KR3/DEV2025.json.gz',
         DEV+'/KR3/SEEN2026.json.gz',
         CAMPAIGN+'/EXECUTION_PATH/PRODUCER/INTEGRATION_RECEIPT.json',
         CAMPAIGN+'/G5A_READINESS/SOURCE_API_STATUS.json',
         CODE+'step7_kr3_execution_v1.py', CODE+'g5b_operational_terminal_v1.py',
         'backend/research/alpha_proof/a1_alpha_proof_gate_v1.py',
         CODE+'top5_development_repair_v1.py', CODE+'parallel_exit_dev_v1.py',
         *NATIVE)


def byte_sha(value):
    return hashlib.sha256(value).hexdigest()


def sealed(value, expected=None):
    digest = value.get('receipt_sha256')
    if digest != alpha.sha({k:v for k,v in value.items() if k != 'receipt_sha256'}):
        raise ValueError('EVIDENCE_RECEIPT_HASH')
    if expected and digest != expected:
        raise ValueError('EVIDENCE_HISTORICAL_ANCHOR')
    return value


def read_inputs(root=ROOT, manifest=None):
    """Explicit finite whitelist and immutable bytes; no discovery or replay."""
    manifest = manifest or json.loads((root/SPEC).read_text())
    sealed(manifest)
    if manifest.get('candidate_sha256') != CANDIDATE:
        raise ValueError('EVIDENCE_CANDIDATE_IDENTITY')
    pins = manifest.get('files_sha256', {})
    if set(pins) != set(FILES):
        raise ValueError('EVIDENCE_INPUT_WHITELIST')
    inputs = {}
    for name in FILES:
        path = root/name
        if path.is_symlink() or not path.is_file():
            raise ValueError('EVIDENCE_FILE_MISSING_OR_SYMLINK:' + name)
        raw = path.read_bytes()
        if byte_sha(raw) != pins[name]:
            raise ValueError('EVIDENCE_BYTES_CHANGED:' + name)
        if name.endswith('.gz'):
            value = json.loads(gzip.decompress(raw))
        elif name.endswith('.json'):
            value = json.loads(raw)
        else:
            value = raw.decode()
        inputs[name] = value
    selection = sealed(inputs[CAMPAIGN+'/SELECTION.json'], SELECTION)
    application = sealed(inputs[CAMPAIGN+'/CONTRACT/APPLICATION.json'])
    receipt = sealed(inputs[DEV+'/KR3/receipt.json'], RESULT)
    spec = sealed(inputs[DEV+'/SPEC.json'], HISTORICAL_SPEC)
    candidate = application['candidate']
    if (candidate.get('candidate_sha256') != CANDIDATE or
        alpha.sha({k:v for k,v in candidate.items() if k!='candidate_sha256'}) != CANDIDATE or
        candidate['candidate_id'] != selection['candidate_id'] or
        candidate['direct_parent_id'] != 'KR1_FULL' or selection['view'] != 'FULL' or
        receipt['candidate'] != 'KR3' or receipt['spec_seal'] != HISTORICAL_SPEC):
        raise ValueError('EVIDENCE_CANDIDATE_IDENTITY')
    for name in NATIVE:
        expected = spec['code_files_sha256'].get(name, spec['preserved_files_sha256'].get(name))
        if pins[name] != expected:
            raise ValueError('EVIDENCE_NATIVE_OWNER_DRIFT:' + name)
    if selection['cost_sha256'] != spec['cost_sha256']:
        raise ValueError('EVIDENCE_COST_IDENTITY')
    for period in ('DEV2025','SEEN2026'):
        data = inputs[DEV+'/KR3/'+period+'.json.gz']
        artifact = receipt['artifacts'][period]
        if (artifact['file_sha256'] != pins[artifact['path']] or
            data['candidate'] != 'KR3' or data['period'] != period or
            data['values']['FULL'] != receipt['results'][period]['values']['FULL'] or
            selection['data_sha256'][period] != spec['period_data_sha256'][period]):
            raise ValueError('EVIDENCE_RESULT_LINEAGE:' + period)
    return manifest, inputs


def feature_map(pins):
    descriptions = (
        ('trend_order', 'EMA20 > EMA50', 'EMA20 and EMA50 from completed signal close',
         'long only while fast EMA exceeds slow EMA', 'EMA20 <= EMA50 invalidates at a held completed close', NATIVE[0], 'without_trend_feature'),
        ('reclaim', "lag(close,1) <= lag(EMA20,1) and close > EMA20", 'completed current and prior close/EMA20',
         'long on upward reclaim of fast trend', 'no reclaim means no original signal', NATIVE[0], 'without_reclaim_feature'),
        ('directional_half', 'close >= (high + low) / 2', 'completed signal high, low and close',
         'long only when close retains upper half of signal range', 'close below midpoint vetoes entry before occupancy', NATIVE[1], 'without_directional_half'),
    )
    features = []
    for name, mechanism, observable, direction, invalidation, path, ablation in descriptions:
        features.append(dict(name=name, mechanism=mechanism, observable=observable,
            direction=direction, invalidation=invalidation, entry_time_observable=True,
            availability='COMPLETED_SIGNAL_CLOSE; EXECUTION_NEXT_OBSERVED_OPEN',
            source_path=path, source_sha256=pins[path], ablation=ablation))
    return {'features':features, 'redundant_pairs':[], 'ablation_plan_complete':True,
        'execution_state_not_mislabelled_entry_feature':[
            {'name':'D_reference_reservation', 'owner':NATIVE[2], 'meaning':'causal reference occupancy persists independently of actual exit'},
            {'name':'actual_symbol_slot', 'owner':NATIVE[4], 'meaning':'signal close must be after actual exit; open tail blocks new entry'},
            {'name':'M2_first_breach', 'owner':NATIVE[3], 'meaning':'latched once on first held completed close below frozen signal low; EMA50 decides suppressed/permitted'},
            {'name':'KR3_veto', 'owner':NATIVE[5], 'meaning':'at signal+11 close only, prior SUPPRESSED state vetoes otherwise profitable/trending extension to signal+24'},
        ],
        'regime_feature_absent_proof':{
            'native_files_sha256':{p:pins[p] for p in NATIVE},
            'entry_features':['trend_order','reclaim','directional_half'],
            'economic_state':['D_reference_reservation','actual_symbol_slot','M2_first_breach','KR3_veto'],
            'annotation_owner':CODE+'step7_kr3_execution_v1.py:native_replay',
            'annotation_after_native_replay':True,
            'reason':'Native KR3 receives rows/signals/EMA arrays only. Regime labels are assigned after owner.replay returns; fixed label bijection cannot alter native signals, paths, reservations, fills or costs.'}}


def inventory(pins, spec):
    params = []
    for name, value, source, reason in (
        ('EMA_fast',20,NATIVE[0],'inherited original V2 bounded EMA period; sensitivity evidence not yet real'),
        ('EMA_slow',50,NATIVE[0],'inherited original V2 trend period; sensitivity evidence not yet real'),
        ('reclaim_lag',1,NATIVE[0],'previous completed bar'),
        ('native_hold_observed_bars',12,NATIVE[0],'original H12 design prior'),
        ('extension_multiple',2,NATIVE[5],'KR1 one finite extension; not fitted again for KR3'),
        ('extension_decision_offset',11,NATIVE[5],'derived native_hold - 1'),
        ('extended_cap_offset',24,NATIVE[5],'derived native_hold * extension_multiple'),
        ('first_signal_index',239,NATIVE[0],'original 240-observation warmup; retained bounded EMA seed'),
        ('native_interval_ms',14400000,NATIVE[0],'original 4h research timeframe'),
        ('signal_range_midpoint_divisor',2,NATIVE[1],'existing directional-half geometry'),
        ('actual_symbol_slots',1,NATIVE[4],'FULL native occupancy contract'),
        ('minimum_modeled_roundtrip_bps',20.0,CODE+'top5_development_repair_v1.py','research cost floor, not observed execution'),
        ('cost2_multiplier',2,CODE+'top5_development_repair_v1.py','doubles every cost component'),
        ('funding_period_hours',8,CODE+'parallel_exit_dev_v1.py','inherited modeled settlement grid; historical funding proxy'),
    ):
        params.append({'name':name,'value':value,'provenance':'PURE_DESIGN_PRIOR',
            'source_or_test_sha':pins[source], 'source_path':source,
            'development_justification_sha':None, 'prior_explanation':reason,
            'selected_using_holdout':False, 'selection_history':'V2→D→N→M→M2→KR1→KR3; reused DEV selected, not unseen validation'})
    return {'numeric_parameter_inventory_complete':False,'parameters':params,
        'remaining_inventory':'transitive DSL numeric seed/bounds and all inherited proxy-policy derivation constants; supplied seven-symbol values are separately bound',
        'semantic_nulls':{'initial_protective_sl':None,'tp':None,'risk_R':None},
        'evaluation_constants_preserved':spec['goals'],
        'unjustified_prior_does_not_become_evidence_by_hashing_code':True}


def exact_history_verified(authority, data_sha):
    """A different dataset needs an explicit slice receipt, not transitive labels."""
    return (authority.get('immutable_history_verified') is True and
            authority.get('dataset_sha256') == data_sha)


def build_projection(manifest, inputs):
    pins = manifest['files_sha256']
    selection = inputs[CAMPAIGN+'/SELECTION.json']
    application = inputs[CAMPAIGN+'/CONTRACT/APPLICATION.json']
    receipt = inputs[DEV+'/KR3/receipt.json']
    spec = inputs[DEV+'/SPEC.json']
    fmap = feature_map(pins)
    source_meta = inputs[CAMPAIGN+'/G5A_READINESS/SOURCE_API_STATUS.json']['development_source_cost']
    general = source_meta['general_stored_authority']
    if (source_meta['candidate_sha256'] != CANDIDATE or
        source_meta['cost_sha256'] != selection['cost_sha256'] or
        source_meta['period_data_sha256'] != selection['data_sha256'] or
        general['receipt_sha256'] != selection['cost_sha256'] or
        general['dataset_sha256'] != selection['data_sha256']['SEEN2026']):
        raise ValueError('EVIDENCE_SOURCE_COST_METADATA_PARITY')
    values = {p:deepcopy(receipt['results'][p]['values']['FULL']) for p in ('DEV2025','SEEN2026')}
    metrics = {p:inputs[DEV+'/KR3/'+p+'.json.gz']['stages']['FULL']['metrics'] for p in values}
    m = metrics['DEV2025']; base = m['base_cost']
    controls = [{'kind':k,'applicable':True,'passed':False,'status':'NO_ACTUAL_KR3_DEV_CONTROL_RESULT'}
                for k in ('direction_flip','time_shift_placebo','delayed_entry')]
    controls.append({'kind':'regime_permutation','applicable':False,'passed':False,
        'not_applicable_reason':fmap['regime_feature_absent_proof']['reason'],
        'proof_sha256':alpha.sha(fmap['regime_feature_absent_proof']),
        'status':'ECONOMICALLY_DEGENERATE_NATIVE_FEATURE_MAP'})
    ablations = [{'feature':f['name'],'applicable':True,'passed':False,
        'specification':f['ablation'],'status':'SYNTHETIC_INTEGRATION_ONLY; REAL_DEV_UNEXECUTED'} for f in fmap['features']]
    bundle = {
      'candidate':deepcopy(application['candidate']),
      'primary_evidence':{'supports':[{'kind':'NATIVE_EMPIRICAL','source_id':RESULT,
         'independent_key':'KR3_REUSED_DEV_SAME_CAMPAIGN','supports_mechanism':True,
         'scope':'matched KR1_FULL versus KR3_FULL prior-suppressed-breach veto effects; TRADEOFF retained'}],
         'missing':'No independent primary source specifically supports KR3 veto; native periods are not two independent supports.'},
      'feature_causal_map':fmap,
      'parameter_provenance':{**inventory(pins,spec),
          'stored_cost_values_by_symbol':source_meta['cost_by_symbol'],
          'cost_source_metadata_sha256':pins[CAMPAIGN+'/G5A_READINESS/SOURCE_API_STATUS.json']},
      'development_feasibility':{
          'separated_from_prospective_holdout':True,'holdout_outcomes_used':False,
          'development_data_sha':selection['data_sha256']['DEV2025'],
          'metrics':{'event_count':m['raw_signals'],'completed_trades':base['completed_T'],
            'forward_move_bps_median':None,'mfe_bps_median':None,'mae_bps_median':None,
            'gross_expectancy_bps':base['gross_expectancy_bps'],
            'realistic_cost_bps':sum(base['mean_cost_components_bps'].values()),
            'event_rate_per_day':m['raw_signals']/m['frequency']['calendar_days']},
          'stored_means_not_substituted_for_medians':{k:base[k] for k in ('mean_mae_bps','mean_mfe_bps','mean_cost_components_bps','completed_trade_rate_per_day')},
          'launch_gate_source':'SSOT:backend/research/rebuild/g5b_operational_terminal_v1.py:freeze_boundary',
          'launch_gate_pass':False,
          'specific_P3_launch_authority':'NO_KR3_P3_REGISTERED_LAUNCH_DECISION; downstream freeze_boundary numeric conditions are necessary only',
          'projection_only_arithmetic':['sum stored mean cost components','stored raw signal count / stored calendar days'],
          'launch_economic_thresholds':{'net_expectancy_bps':'>0','profit_factor':'>1','cost2x_net_bps':'>0'},
          'necessary_numeric_conditions_by_period':{p:dict(net_expectancy_positive=v['net_expectancy_bps_per_closed_trade']>0,profit_factor_above_one=v['PF']>1,cost2_closed_positive=v['closed_cost2x_net_bps']>0) for p,v in values.items()},
          'launch_blockers':['NO_ACTUAL_PURGED_OOS','NEGATIVE_CONTROL_SUPERIORITY_UNEXECUTED','UNRESOLVED_OPEN_POSITIONS','P0_P2_P5_P6_REMAIN'],
          'not_a_new_universal_g5a_sample_threshold':True},
      'negative_controls_and_ablation':{'controls':controls,'feature_ablations':ablations,
          'holdout_outcomes_used':False,
          'stored_kr3_veto_parent_comparison':{p:receipt['results'][p]['decisions']['FULL'] for p in values},
          'other_feature_ablation_success_not_inferred_from_exit_repair':True},
      'multi_ai_adversarial_review':{'controller_review_sha':None,'provider_reviews':[],
          'status':'NO_MATCHED_KR3_PROVIDER_CALL_RECEIPT; SAME_PROVIDER_SUBAGENTS_NOT_P5'},
      'source_implementation_reality':{
          'admission_stage':'G5A_DEVELOPMENT','immutable_history_verified':exact_history_verified(general, selection['data_sha256']['DEV2025']),
          'general_historical_authority_reused':general,
          'period_slice_binding':source_meta['period_data_sha256'],
          'KR3_split_limitation':source_meta['original_split_limitation'],
          'split_frozen_before_outcomes':False,'development_cost_model_bound':True,
          'development_data_sha':selection['data_sha256']['DEV2025'],
          'formal_production_credit':0,
          'sources':[{'name':'native_4h_OHLCV','available':True,'proxy':False,
              'historical_immutable':exact_history_verified(general, selection['data_sha256']['DEV2025']),'semantic_valid':True,
              'source_sha':selection['data_sha256']['DEV2025'],
              'meaning':'General history receipt is bound to SEEN2026/full hash; explicit full-to-DEV2025 slice verification receipt is absent. Stored DEV result bytes are pinned, not independent KR3 OOS.'},
              {'name':'historical_execution_cost','available':False,'proxy':True,
               'proxy_declared':True,'proxy_validated':False,'historical_immutable':False,
               'semantic_valid':False,'source_sha':selection['data_sha256']['DEV2025'],
               'meaning':spec['rules']['accounting']}],
          'duplicate_count':None,'leakage_count':None,'timestamp_order_error_count':None,'integrity_defect_count':None,
          'integrity_counts_are_no_new_scan_not_new_proof':True,
          'verified_round_trip_cost_bps':None,'cost_authority_sha':selection['cost_sha256'],
          'used_data_is_independent_oos':False,'current_quotes_are_historical_fills':False,
          'original_partition_exposure':receipt['source_access'],
          'remaining':'KR3-specific preregistered split/purge adequacy and proxy validation; general history metadata retained but exact DEV2025 slice verification remains unknown; fresh G5B source remains separate'},
    }
    proof = alpha.evaluate_bundle(bundle)
    integration = inputs[CAMPAIGN+'/EXECUTION_PATH/PRODUCER/INTEGRATION_RECEIPT.json']
    pointers = {'base_replay':'values.FULL; stages.FULL.metrics.base_cost',
        'realistic_cost':'stages.FULL.metrics.closed_cost_totals_bps; open_observations',
        'cost2x':'values.FULL.closed_cost2x_net_bps; terminal_cost2x_net_bps_hypothetical',
        'chronological_split':'stages.FULL.metrics.by_exit_month (descriptive only, not frozen OOS)',
        'symbol_decomposition':'stages.FULL.metrics.by_symbol'}
    reports = {}
    for name in terminal.ECONOMIC_REPORTS:
        stored = name in pointers
        reports[name] = {'status':'REUSED_ACTUAL_DEV_COMPONENT' if stored else 'SYNTHETIC_ONLY_REAL_UNEXECUTED',
          'formal_complete':False,'actual_new_economic_execution':False,
          'stored_pointer':pointers.get(name),'candidate_sha256':CANDIDATE,
          'period_data_sha256':selection['data_sha256'],'cost_sha256':selection['cost_sha256'],
          'historical_spec_sha256':HISTORICAL_SPEC,'historical_execution_receipt':RESULT,
          'historical_producer':'focused_repair_v1.py -> keltner_kr3_v1.replay -> parallel_exit_metrics_v1',
          'artifact_files_sha256':{p:receipt['artifacts'][p]['file_sha256'] for p in values},
          'synthetic_integration_only_sha256':integration['reports_sha256'][name],
          'synthetic_producer_bundle':integration['bundle_sha256'],
          'same_as_new_sealed_producer_receipt':False,
          'blocker':'Historical modeled DEV component is not independent formal producer completion' if stored else 'No actual candidate-bound result; sealed independent authorization/data absent'}
    output = {'schema':'zel.step7.kr3.g5a.evidence.projection.v1',
        'scope_key':'ZEL_PARENT_CLOSURE_TO_G5_SURVIVOR','task_id':'task-c28e09b57c612762',
        'manifest_sha256':manifest['receipt_sha256'],'candidate_sha256':CANDIDATE,
        'alpha_bundle':bundle,'alpha_owner_result':proof,'economic_reports':reports,
        'stored_FULL_economics_by_period':values,'new_economic_executions':0,
        'source_accesses':0,'sealed_accesses':0,'provider_calls':0,
        'formal_admission':False,'G5A_qualified':False,'G5B_terminal':False,
        'market_replay_executed':False,'read_kind':'PINNED_EXISTING_DEV_RESULT_PROJECTION',
        'regime_nonapplicability_changes_other_required_controls':False}
    output['receipt_sha256'] = alpha.sha(output)
    return output


def evaluate(root=ROOT, manifest=None):
    return build_projection(*read_inputs(root,manifest))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out-dir', type=Path, required=True)
    args = parser.parse_args()
    result = evaluate()
    args.out_dir.mkdir(parents=True,exist_ok=True)
    (args.out_dir/'KR3_G5A_EVIDENCE.json').write_text(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
    print(json.dumps({'state':result['alpha_owner_result']['state'],
        'gates':{g['gate']:g['passed'] for g in result['alpha_owner_result']['gates']},
        'actual_new_economic_executions':0,'report':str(args.out_dir/'KR3_G5A_EVIDENCE.json')}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
