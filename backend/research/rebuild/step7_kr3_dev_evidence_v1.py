"""Exact existing KR3 DEV byte lineage and descriptive statistics, no replay.

Only canonical already-used DEV2025 prefixes are decoded. Full canonical file
checksums are opaque; no validation/OOS rows, observers or source archives load.
Numeric provenance is an inventory, not retrospective design justification.
"""
from __future__ import annotations
import argparse
import ast
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path
import statistics

from backend.research.alpha_proof import a1_alpha_proof_gate_v1 as alpha
from backend.research.architecture_factory import g5a_development_probe_v1 as probe
from backend.research.architecture_factory import g5a_source_admission_v1 as admission
from backend.research.rebuild import step7_kr3_g5a_evidence_v1 as previous

ROOT = Path(__file__).resolve().parents[3]
CAMPAIGN = previous.CAMPAIGN
OUT = CAMPAIGN + '/DEV_VALIDATION/EVIDENCE'
SPEC_PATH = OUT + '/SPEC.json'
DEV_START, DEV_END, BAR, COUNT = 1734595200000, 1766995200000, 14400000, 2250
DATA_REF = '6d6335d1c9ad7ecb1e9597da85c2eb87635561e1'
POLICY = 'backend/research/contracts/top5_development_repair_v1.json'
PROBE_POLICY = probe.POLICY
STAGE = probe.STAGE
REBUILD = 'backend/research/rebuild/'
FACTORY = 'backend/research/architecture_factory/'
# Whole source files are inventoried conservatively, including unused numeric
# literals. No claim that every literal is a tuned strategy parameter is made.
NUMERIC_SOURCES = (*previous.NATIVE,
 REBUILD+'top5_development_repair_v1.py', REBUILD+'parallel_exit_dev_v1.py',
 REBUILD+'a1_top5_replacement_child_prospective_v1.py',
 FACTORY+'a1_gen2_generic_dev_econ_v1.py', FACTORY+'g5a_development_probe_v1.py',
 FACTORY+'g5a_stage_candidate_v1.py', REBUILD+'a1_rebuilt_bb_revert_evaluator_v1.py',
 REBUILD+'supertrend_flip_ab_v1.py')
METRIC_OWNER = FACTORY+'a1_gen2_alpha_proof_e2e_v1.py'
LINEAGE_FILES = (POLICY, PROBE_POLICY, STAGE, previous.DEV+'/SPEC.json',
 previous.DEV+'/KR3/receipt.json', previous.DEV+'/KR3/DEV2025.json.gz',
 CAMPAIGN+'/SELECTION.json', CAMPAIGN+'/CONTRACT/APPLICATION.json',
 CAMPAIGN+'/G5A_READINESS/KR3_G5A_EVIDENCE.json', METRIC_OWNER)


def file_sha(path):
    with path.open('rb') as stream:
        digest = hashlib.sha256()
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def seal(value):
    return {**value, 'receipt_sha256': alpha.sha(value)}


def freeze(root=ROOT):
    """Finite whitelist declared before extraction; not a user approval."""
    files = sorted(set((*NUMERIC_SOURCES, *LINEAGE_FILES)))
    return seal({'schema':'zel.step7.kr3.dev.evidence.spec.v1',
      'candidate_sha256':previous.CANDIDATE, 'data_ref':DATA_REF,
      'files_sha256':{name:file_sha(root/name) for name in files},
      'source_scope':'CANONICAL_OPAQUE_HASH_THEN_DEV2025_PREFIX_ONLY',
      'calendar_ms':[DEV_START,DEV_END], 'rows_per_symbol':COUNT,
      'first_eligible_signal_index':239,
      'statistics_scope':'202 COMPLETED KR3 FULL TRADES; OPEN TAIL SEPARATE',
      'native_held_median_semantics':{'mfe':'nonnegative held-bar highs plus eligible exit open',
          'mae':'nonpositive held-bar lows plus eligible exit open',
          'gross':'signed long exit/entry move; variable native holding horizon'},
      'P3_mapping':'NO_FIXED_HORIZON_RENAMING; GENERIC_OWNER_USES_HOLD_HORIZON_AND_POSITIVE_MAE',
      'strategy_replay_allowed':False,'new_collection_allowed':False,'unseen_oos_allowed':False})


def verify_spec(spec, root=ROOT):
    if spec.get('receipt_sha256') != alpha.sha({k:v for k,v in spec.items() if k!='receipt_sha256'}):
        raise ValueError('KR3_DEV_EVIDENCE_SPEC_SEAL')
    if spec != freeze(root):
        raise ValueError('KR3_DEV_EVIDENCE_FROZEN_BYTES_OR_SCOPE_DRIFT')


def numeric_occurrences(text, path, digest):
    """All Python numeric constants plus formulas encoded in string literals."""
    tree = ast.parse(text)
    parents = {child:node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    rows = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and type(node.value) in (int,float):
            rows.append({'name':f'{path}:{node.lineno}:{node.col_offset}',
                'value':(-node.value if isinstance(parents.get(node),ast.UnaryOp) and isinstance(parents[node].op,ast.USub) else node.value), 'location':'PYTHON_LITERAL',
                'source_path':path,'source_or_test_sha':digest,
                'provenance':'PURE_DESIGN_PRIOR','development_justification_sha':None,
                'selected_using_holdout':False,
                'prior_explanation':'Inherited implementation literal; code provenance only, not empirical justification'})
        elif isinstance(node, ast.Constant) and isinstance(node.value,str):
            # Parse only executable expression strings, never dates/IDs/prose.
            if not any(op in node.value for op in ('ema(', 'lag(', 'sma(', 'close >', 'close <')):
                continue
            try:
                formula = ast.parse(node.value, mode='eval')
            except SyntaxError:
                continue
            for offset, literal in enumerate(ast.walk(formula)):
                if isinstance(literal,ast.Constant) and type(literal.value) in (int,float):
                    rows.append({'name':f'{path}:{node.lineno}:{node.col_offset}:formula:{offset}',
                        'value':literal.value,'location':'EXECUTABLE_FORMULA_LITERAL',
                        'source_path':path,'source_or_test_sha':digest,
                        'provenance':'PURE_DESIGN_PRIOR','development_justification_sha':None,
                        'selected_using_holdout':False,'formula':node.value,
                        'prior_explanation':'Inherited EMA/reclaim design; selected in reused DEV, not independent evidence'})
    return sorted(rows,key=lambda r:r['name'])


def numeric_inventory(spec, root=ROOT):
    records=[]
    for name in NUMERIC_SOURCES:
        records.extend(numeric_occurrences((root/name).read_text(),name,spec['files_sha256'][name]))
    return {'numeric_parameter_inventory_complete':True,'parameters':records,
        'coverage':'Conservative full-file numeric superset of six native modules, bounded DSL, feature builder, held geometry and complete fee/funding/mark charging chain.',
        'selection_history':'V2→D→N→M→M2→KR1→KR3; selection from reused DEV; historical TRADEOFF retained',
        'source_derived_empirical_priors_added':0,
        'design_prior_justification_missing':True,
        'literals_are_not_all_independent_tunable_parameters':True,
        'native_design_values':{'ema_fast':20,'ema_slow':50,'bounded_ema_windows_in_n':4,
            'ema_alpha':'2/(n+1)','first_eligible_signal_index':239,'hold_observed_bars':12,
            'extension_factor':2,'midpoint_divisor':2,'initial_SL':None,'TP':None,
            'roundtrip_floor_bps':20,'funding_settlement_hours':8,'cost2_multiplier':2}}


def stored_medians(document):
    if document.get('candidate')!='KR3' or document.get('period')!='DEV2025':
        raise ValueError('KR3_DEV_METRIC_IDENTITY')
    view = document['views']['FULL']; trades=view['trades']
    if not trades or any(t['side']!='long' or t['mae_bps']>0 or t['mfe_bps']<0 for t in trades):
        raise ValueError('KR3_DEV_MEDIAN_SIGN_OR_POPULATION')
    return {'population':'STORED_KR3_FULL_COMPLETED_NATIVE_POSITIONS',
       'completed_trades':len(trades),'open_tail_count':len(view['open_observations']),
       'event_count':len(view['events']), 'data_sha256':trades[0]['data_sha256'],
       'mfe_bps_median':statistics.median(t['mfe_bps'] for t in trades),
       'mae_bps_median_signed':statistics.median(t['mae_bps'] for t in trades),
       'mae_bps_median_magnitude':statistics.median(-t['mae_bps'] for t in trades),
       'gross_bps_median_variable_horizon':statistics.median(t['gross_bps'] for t in trades),
       'forward_move_bps_median':None,
       'P3_owner_definition':METRIC_OWNER+':_simulate/_p3',
       'P3_owner_semantic_delta':'GEN2 owner uses fixed max_hold horizon and positive MAE; native KR3 stored excursions stop at actual exit. Fixed-horizon forward values absent. Native medians remain descriptive, not relabelled owner inputs.',
       'launch_gate_pass':False,'launch_blocker':'NO_KR3_P3_REGISTERED_LAUNCH_DECISION',
       'strategy_replay_executed':False,'new_independent_observations':0}


def load_dev_slice(data_dir, root=ROOT):
    """Return exact DEV rows, reusable cost metadata and byte lineage; no signals."""
    data_dir=Path(data_dir)
    policy=json.loads((root/POLICY).read_text())
    probe_policy=json.loads((root/PROBE_POLICY).read_text())
    stage=json.loads((root/STAGE).read_text())
    dev=admission.require_development(stage,root)
    if (policy['data_ref']!=DATA_REF or policy['development_interval_ms']!=[DEV_START,DEV_END]
        or probe_policy['development_interval_ms']!=[DEV_START,DEV_END]
        or policy['cost_binding_sha256']!=dev['receipt_sha256']):
        raise ValueError('KR3_DEV_SOURCE_SCOPE')
    manifest=json.loads((data_dir/'development_manifest.json').read_text())
    # Same prior approved prefix reader; no full economic decode and no replay.
    rows, access=probe.load_development(data_dir,probe_policy,dev)
    if any(len(v)!=COUNT for v in rows.values()):
        raise ValueError('KR3_DEV_PREFIX_COUNT')
    prefix_sha=alpha.sha({s:alpha.sha(v) for s,v in sorted(rows.items())})
    costs={s:dev['cost_by_symbol'][s] for s in sorted(rows)}
    lineage=seal({'data_ref':DATA_REF,'manifest_file_sha256':file_sha(data_dir/'development_manifest.json'),
      'manifest_receipt_sha256':manifest['receipt_sha256'],
      'opaque_source_files_sha256':{f'ohlcv/{s}.json':manifest['dataset_files'][f'ohlcv/{s}.json'] for s in sorted(rows)},
      'cost_file_sha256':{s:manifest['cost_snapshots'][s]['sha256'] for s in sorted(rows)},
      'decoded_prefix_by_symbol':access,'actual_prefix_map_sha256':prefix_sha,
      'legacy_combined_dataset_label':policy['combined_data_sha256'],
      'legacy_label_is_not_claimed_as_prefix_byte_digest':True,
      'calendar_ms':[DEV_START,DEV_END],'warmup':{
          'rows_before_calendar_start':0,'first_eligible_signal_index':239,
          'initial_feature_only_observations':239,
          'EMA_seed':'each index uses at most4*n prior/current observations, seed first value'},
      'historical_result_file_sha256':file_sha(root/(previous.DEV+'/KR3/DEV2025.json.gz')),
      'historical_spec_sha256':previous.HISTORICAL_SPEC,
      'candidate_sha256':previous.CANDIDATE,'cost_sha256':dev['receipt_sha256'],
      'immutable_history_verified':True,'split_frozen_before_KR3_outcomes':False,
      'cost_proxy_validated_against_contemporaneous_fills':False,
      'decoded_OOS_rows':0,'decoded_validation_rows':0,'new_collection_calls':0,
      'connection_proof':'canonical full-file bytes verified against sealed original manifest; exact original DEV prefix reader; existing producer selected same prefix through end; stored result and native code separately pinned',
      'existing_producer_source':'parallel_exit_dev_v1.load_inputs -> prefix end1766995200000 -> focused_repair_v1 -> KR3 FULL'})
    policy = {**policy, "development_interval_ms":[DEV_START,DEV_END]}
    return rows,policy,costs,lineage


def build(spec, root=ROOT, lineage=None):
    verify_spec(spec,root)
    old=json.loads((root/(CAMPAIGN+'/G5A_READINESS/KR3_G5A_EVIDENCE.json')).read_text())
    document=json.loads(gzip.decompress((root/(previous.DEV+'/KR3/DEV2025.json.gz')).read_bytes()))
    stats=stored_medians(document)
    bundle=deepcopy(old['alpha_bundle'])
    old_inventory = bundle['parameter_provenance']
    bundle['parameter_provenance']={**numeric_inventory(spec,root),
        'stored_cost_values_by_symbol':old_inventory['stored_cost_values_by_symbol'],
        'cost_source_metadata_sha256':old_inventory['cost_source_metadata_sha256'],
        'stored_evaluation_constants':old_inventory['evaluation_constants_preserved']}
    bundle['development_feasibility']['native_held_medians']=stats
    if lineage:
        if (lineage.get('receipt_sha256') != alpha.sha({k:v for k,v in lineage.items() if k!='receipt_sha256'})
            or lineage['candidate_sha256']!=previous.CANDIDATE or lineage['decoded_OOS_rows']!=0
            or lineage['decoded_validation_rows']!=0 or lineage['calendar_ms'] != [DEV_START,DEV_END]):
            raise ValueError('KR3_DEV_LINEAGE_IDENTITY')
        reality=bundle['source_implementation_reality']
        reality['immutable_history_verified']=True
        reality['DEV2025_slice_receipt_sha256']=lineage['receipt_sha256']
        for source in reality['sources']:
            if source['name']=='native_4h_OHLCV':
                source['historical_immutable']=True
                source['meaning']='Verified canonical bytes and original DEV2025 prefix; not a preregistered KR3 OOS split.'
    return seal({'schema':'zel.step7.kr3.actual.dev.evidence.v1',
       'candidate_sha256':previous.CANDIDATE,'spec_sha256':spec['receipt_sha256'],
       'stored_native_medians':stats,'lineage':lineage,
       'alpha_bundle':bundle,'alpha_owner_result':alpha.evaluate_bundle(bundle),
       'new_strategy_replays':0,'G5A_qualified':False,'formal_production_credit':0})


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--freeze',action='store_true')
    parser.add_argument('--data-dir',type=Path);parser.add_argument('--out-dir',type=Path,default=ROOT/OUT)
    args=parser.parse_args();args.out_dir.mkdir(parents=True,exist_ok=True)
    if args.freeze:
        path=args.out_dir/'SPEC.json'
        if path.exists():raise SystemExit('SPEC_EXISTS_DO_NOT_REFREEZE')
        path.write_text(json.dumps(freeze(),sort_keys=True,indent=2)+'\n');print(path);return
    spec=json.loads((args.out_dir/'SPEC.json').read_text());lineage=None
    if args.data_dir:
        _,_,_,lineage=load_dev_slice(args.data_dir)
    result=build(spec,lineage=lineage)
    (args.out_dir/'RESULT.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
    print(json.dumps({'native_medians':result['stored_native_medians'],
        'gates':[(r['gate'],r['passed']) for r in result['alpha_owner_result']['gates']],
        'receipt_sha256':result['receipt_sha256']}))


if __name__=='__main__':main()
