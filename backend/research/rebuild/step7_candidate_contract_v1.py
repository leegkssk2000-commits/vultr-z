"""Candidate-specific producer bindings; never an economic or formal gate.

No source loading, market replay, source authorization, boundary write or default
approval. Existing G5 owners retain every economic decision. Supplied bytes are
hash checked; their real-world authenticity requires the independent source owner.
"""
from __future__ import annotations
import ast
from copy import deepcopy
import hashlib
import json

REPORTS = ('base_replay', 'realistic_cost', 'cost2x', 'purged_oos',
           'chronological_split', 'symbol_decomposition', 'regime_decomposition',
           'parameter_neighbor_stability', 'negative_controls')
CONSUMER = 'backend/research/rebuild/g5b_operational_terminal_v1.py:freeze_boundary'
PROFILES = {
    'KR3': {
        'implementation': 'backend/research/rebuild/keltner_kr3_v1.py',
        'candidate_id': 'KELTNER_KR3_PRIOR_SUPPRESSED_BREACH_EXTENSION_VETO_DEV_V1',
        'interval_ms': 14400000, 'entry': 'NEXT_OBSERVED_OPEN',
        'initial_protective_sl': None, 'tp': None,
        'native_cap_signal_index_offset': 12, 'extended_cap_signal_index_offset': 24,
        'cap_clock': 'OBSERVED_BAR_INDEX_NOT_WALLCLOCK_GUARANTEE',
        'exit_priority': ['FINAL_CAP_CLOSE', 'EMA20_NOT_ABOVE_EMA50_NEXT_OPEN',
                          'M2_PERMITTED_LOW_BREACH_NEXT_OPEN', 'RUNNER_INVALIDATION_NEXT_OPEN'],
        'ownership': 'CAUSAL_D_REFERENCE_RESERVATION_AND_ONE_ACTUAL_SYMBOL_SLOT',
        'open_end': 'CENSORED_MARK_NOT_LIQUIDATION',
        'risk_R': None,
    },
    'Q0': {
        'implementation': 'backend/research/rebuild/break_channel_structure_v1.py',
        'candidate_id': None,  # exact frozen caller identity is required, never invented
        'interval_ms': 14400000, 'entry': 'NEXT_OBSERVED_OPEN_STRICTLY_ABOVE_LATCHED_LOWER_SL',
        'initial_protective_sl': 'LATCHED_ENTRY_UP_LOWER_CHANNEL', 'tp': None,
        'native_cap_signal_index_offset': None, 'extended_cap_signal_index_offset': None,
        'cap_clock': None,
        'exit_priority': ['PROTECTIVE_STOP_GAP_OPEN', 'BEARISH_CONFIRMED_NEXT_OPEN',
                          'PROTECTIVE_STOP_INTRABAR'],
        'ownership': 'ONE_ACTUAL_SYMBOL_SLOT_NO_SAME_OPEN_REENTRY',
        'open_end': 'CENSORED_MARK_NOT_LIQUIDATION',
        'intrabar_timestamp': 'CLOSED_EXIT_BAR_UPPER_BOUND_NOT_EXACT_FILL',
        'trigger_stream': None,
        'risk_R': None,
    },
}
PAYLOAD_FIELDS = {
    'base_replay': {'closed', 'open', 'events', 'net_expectancy_bps', 'profit_factor'},
    'realistic_cost': {'components', 'provenance', 'unknown_components'},
    'cost2x': {'gross_bps', 'all_cost_bps', 'cost2x_net_bps', 'open_marks'},
    'purged_oos': {'folds', 'purged_origin_ids', 'unresolved_intervals', 'metrics'},
    'chronological_split': {'windows', 'open_marks', 'metrics'},
    'symbol_decomposition': {'symbols', 'metrics'},
    'regime_decomposition': {'label_method_sha256', 'availability_audit', 'metrics'},
    'parameter_neighbor_stability': {'frozen_neighbors', 'all_results', 'exposure_log'},
    'negative_controls': {'frozen_controls', 'all_results', 'exposure_log'},
}


def sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def byte_sha(value):
    return hashlib.sha256(value).hexdigest()


def seal(value):
    return {**deepcopy(value), 'receipt_sha256': sha(value)}


def check_seal(value):
    return isinstance(value, dict) and value.get('receipt_sha256') == sha(
        {k:v for k,v in value.items() if k != 'receipt_sha256'})


def _digest(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def _require(ok, error):
    if not ok:
        raise ValueError(error)


def _function_pin(blobs, owner):
    _require(isinstance(owner, dict) and set(owner) == {'path', 'function'}, 'OWNER_REQUIRED')
    path, name = owner['path'], owner['function']
    _require(path in blobs, 'OWNER_BYTES_MISSING:' + path)
    tree = ast.parse(blobs[path].decode('utf-8'))
    functions = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name]
    _require(len(functions) == 1, 'OWNER_FUNCTION_MISSING:' + name)
    # Full file binds imports/constants too; function AST records exact entrypoint.
    return {'path':path, 'function':name, 'file_sha256':byte_sha(blobs[path]),
            'function_ast_sha256':sha(ast.dump(functions[0], include_attributes=False))}


def candidate_contract(profile, *, candidate_id, direct_parent_id, code_blobs,
                       config_blob, entry_owner, exit_owner, mechanism_blob):
    """Seal exact provided definitions without assigning formal ID or credit."""
    _require(profile in PROFILES, 'UNKNOWN_NATIVE_PROFILE')
    native = deepcopy(PROFILES[profile])
    _require(isinstance(candidate_id, str) and bool(candidate_id.strip()), 'EXACT_CANDIDATE_ID_REQUIRED')
    _require(native['candidate_id'] in (None, candidate_id), 'CANDIDATE_PROFILE_MISMATCH')
    _require(isinstance(direct_parent_id, str) and bool(direct_parent_id.strip()), 'EXACT_DIRECT_PARENT_REQUIRED')
    _require(native['implementation'] in code_blobs, 'NATIVE_IMPLEMENTATION_BYTES_REQUIRED')
    _require(code_blobs and all(isinstance(v, bytes) for v in code_blobs.values()), 'CODE_BYTES_REQUIRED')
    _require(isinstance(config_blob, bytes) and config_blob and isinstance(mechanism_blob, bytes) and mechanism_blob,
             'FROZEN_CONFIGURATION_AND_MECHANISM_BYTES_REQUIRED')
    entry = _function_pin(code_blobs, entry_owner)
    exit_ = _function_pin(code_blobs, exit_owner)
    pins = {path:byte_sha(value) for path,value in sorted(code_blobs.items())}
    native['candidate_id'] = candidate_id
    candidate = {'candidate_id':candidate_id, 'direct_parent_id':direct_parent_id,
                 'profile':profile, 'native':native, 'code_files_sha256':pins,
                 'code_sha':sha(pins), 'config_sha':byte_sha(config_blob),
                 'entry_sha':sha(entry), 'exit_sha':sha(exit_),
                 'entry_owner':entry, 'exit_owner':exit_,
                 'mechanism_sha':byte_sha(mechanism_blob), 'research_only':True}
    return {**candidate, 'candidate_sha256':sha(candidate)}


def require_compatible(candidate, bridge):
    """Reject time-only substitution for both conditional native strategies."""
    _require(candidate.get('profile') in PROFILES, 'UNKNOWN_NATIVE_PROFILE')
    _require(bridge.get('exit_model') != 'TIME_STOP_ONLY', 'CONDITIONAL_NATIVE_EXIT_REQUIRED')
    _require(bridge.get('native_profile_sha256') == sha(candidate['native']), 'NATIVE_SEMANTICS_UNBOUND')
    if candidate['profile'] == 'Q0':
        _require(bridge.get('holding_limit') is None, 'Q0_UNLIMITED_HOLD_MUST_BE_PRESERVED')
        _require(bridge.get('intrabar_timestamp_is_exact_fill') is False, 'Q0_PROXY_TIME_NOT_EXACT_FILL')
    return True


def producer_contract(candidate, *, data_sha, cost_sha, preregistration_sha,
                      report_specs, producer_blobs):
    """Bind declared producers before execution; missing producers remain blocked.

    preregistration_sha refers to the independent role/access/approval owner.
    This function does not approve that preregistration or load its holdout.
    """
    _require(candidate.get('candidate_sha256') == sha({k:v for k,v in candidate.items() if k != 'candidate_sha256'}),
             'CANDIDATE_SEAL_INVALID')
    _require(all(_digest(v) for v in (data_sha, cost_sha, preregistration_sha)), 'IDENTITY_DIGEST_REQUIRED')
    _require(set(report_specs) == set(REPORTS), 'ALL_NINE_REPORT_SPECS_REQUIRED')
    reports = {}
    for name in REPORTS:
        spec = deepcopy(report_specs[name])
        if spec.get('producer') is None:
            _require(isinstance(spec.get('missing_reason'), str) and spec['missing_reason'], 'MISSING_PRODUCER_REASON_REQUIRED:' + name)
            reports[name] = {**spec, 'status':'PRODUCER_MISSING', 'complete':False}
            continue
        pin = _function_pin(producer_blobs, spec['producer'])
        _require(isinstance(spec.get('command'), list) and spec['command'] and
                 all(isinstance(x, str) and x for x in spec['command']), 'EXACT_ARGV_REQUIRED:' + name)
        _require(_digest(spec.get('evaluation_spec_sha256')), 'FROZEN_EVALUATION_SPEC_REQUIRED:' + name)
        _require(spec.get('input_identity') == {'candidate_sha256':candidate['candidate_sha256'],
                 'data_sha':data_sha, 'cost_sha':cost_sha}, 'PRODUCER_INPUT_IDENTITY:' + name)
        reports[name] = {**spec, 'producer_pin':pin, 'status':'PRODUCER_BOUND_UNEXECUTED', 'complete':False}
    return seal({'schema':'zel.step7.producer.contract.v1', 'candidate':candidate,
                 'data_sha':data_sha, 'cost_sha':cost_sha, 'preregistration_sha':preregistration_sha,
                 'reports':reports, 'consumer':CONSUMER,
                 'formal_eligible':False, 'boundary_created':False,
                 'status':'BOUND_UNEXECUTED' if all(x['status']=='PRODUCER_BOUND_UNEXECUTED' for x in reports.values()) else 'BLOCKED_MISSING_PRODUCERS'})


def bind_economic_reports(contract, executions, artifact_blobs):
    """Validate actual producer receipts and bytes, without declaring economics PASS.

    This output can populate existing economics.reports; the existing alpha,
    economics, source and boundary owners must still accept the complete bundle.
    Synthetic receipts stay ineligible. No supplied report is silently omitted.
    """
    _require(check_seal(contract), 'PRODUCER_CONTRACT_SEAL_INVALID')
    _require(set(executions) <= set(REPORTS), 'UNKNOWN_REPORT')
    bound, missing = {}, []
    for name in REPORTS:
        receipt = executions.get(name)
        if receipt is None:
            missing.append(name)
            continue
        spec = contract['reports'][name]
        _require(spec['status'] == 'PRODUCER_BOUND_UNEXECUTED', 'PRODUCER_NOT_PREREGISTERED:' + name)
        _require(check_seal(receipt), 'EXECUTION_RECEIPT_SEAL_INVALID:' + name)
        _require(receipt.get('status') == 'COMPLETED' and receipt.get('exit_code') == 0
                 and type(receipt.get('exit_code')) is int, 'ACTUAL_COMPLETION_REQUIRED:' + name)
        _require(receipt.get('evidence_class') == 'INDEPENDENT_ECONOMIC_EXECUTION', 'FORMAL_REPORT_CLASS_REQUIRED:' + name)
        _require(receipt.get('contract_sha256') == contract['receipt_sha256'], 'EXECUTION_CONTRACT_MISMATCH:' + name)
        for key, expected in {**spec['input_identity'], 'report':name,
                              'command':spec['command'], 'producer_pin':spec['producer_pin'],
                              'evaluation_spec_sha256':spec['evaluation_spec_sha256'],
                              'preregistration_sha':contract['preregistration_sha']}.items():
            _require(receipt.get(key) == expected, 'EXECUTION_BINDING_MISMATCH:' + name + ':' + key)
        _require(_digest(receipt.get('source_execution_receipt_sha256')), 'SOURCE_EXECUTION_RECEIPT_REQUIRED:' + name)
        path = receipt.get('artifact_path')
        _require(path in artifact_blobs and receipt.get('artifact_sha256') == byte_sha(artifact_blobs[path]),
                 'ARTIFACT_BYTES_MISMATCH:' + name)
        try:
            artifact = json.loads(artifact_blobs[path])
        except (ValueError, TypeError):
            raise ValueError('ECONOMIC_PAYLOAD_REQUIRED:' + name) from None
        _require(isinstance(artifact, dict) and artifact.get('report') == name and
                 isinstance(artifact.get('payload'), dict) and PAYLOAD_FIELDS[name] <= set(artifact['payload']),
                 'ECONOMIC_PAYLOAD_REQUIRED:' + name)
        _require(artifact.get('input_identity') == spec['input_identity'], 'ARTIFACT_IDENTITY_MISMATCH:' + name)
        bound[name] = {'receipt_sha256':receipt['receipt_sha256'], **spec['input_identity'],
                       'complete':True, 'producer_contract_sha256':contract['receipt_sha256']}
    return {'status':'ALL_REPORT_BYTES_BOUND_NOT_ECONOMIC_PASS' if not missing else 'INCOMPLETE',
            'reports':bound, 'missing':missing, 'formal_admission':False, 'boundary_created':False,
            'source_authenticity_certified':False, 'consumer':CONSUMER}


def prepare_application(root, selection_path, authority_path=None):
    """One metadata-only application run; no old row audit or market decoding."""
    from pathlib import Path
    root = Path(root)
    def read_repo(path):
        path = Path(path)
        absolute = path if path.is_absolute() else root/path
        absolute = absolute.resolve()
        _require(absolute.is_relative_to(root.resolve()), 'APPLICATION_INPUT_OUTSIDE_REPOSITORY')
        return absolute.read_bytes()
    selection_blob = read_repo(selection_path)
    selection = json.loads(selection_blob)
    _require(check_seal(selection), 'SELECTION_SEAL_INVALID')
    _require(selection.get('candidate') == 'KR3' and selection.get('view') == 'FULL', 'EXACT_SELECTED_KR3_FULL_REQUIRED')
    _require(selection.get('unused_performance_viewed_before_selection') is False,
             'PRESELECTION_EXPOSURE_UNRESOLVED')
    spec_blob = read_repo(selection['source_spec'])
    spec = json.loads(spec_blob)
    _require(check_seal(spec) and spec['receipt_sha256'] == selection['config_sha256'], 'SELECTED_CONFIGURATION_MISMATCH')
    receipt_blob = read_repo(selection['source_receipt'])
    receipt = json.loads(receipt_blob)
    _require(check_seal(receipt) and receipt['receipt_sha256'] == selection['source_receipt_sha256'],
             'STORED_RESULT_RECEIPT_MISMATCH')
    # Only newly missing entry/exit owner byte/function links. Existing 203 rows
    # and 1,469 old checks are not loaded or recalculated.
    entry_path = 'backend/research/rebuild/keltner_kr1_v1.py'
    exit_path = PROFILES['KR3']['implementation']
    code_blobs = {path:read_repo(path) for path in (entry_path,exit_path)}
    known_pins = {**spec['preserved_files_sha256'], **spec['code_files_sha256']}
    for path, raw in code_blobs.items():
        _require(byte_sha(raw) == known_pins[path], 'NATIVE_OWNER_BYTES_CHANGED:' + path)
    candidate = candidate_contract('KR3', candidate_id=selection['candidate_id'],
        direct_parent_id=selection['parent_id'], code_blobs=code_blobs,
        config_blob=spec_blob, mechanism_blob=selection['original_rule'].encode(),
        entry_owner={'path':entry_path,'function':'replay'}, exit_owner={'path':exit_path,'function':'path'})
    # Binding the full historical config bytes retains its transitive preserved
    # dependency pins, without re-running that completed full audit.
    authority = json.loads(read_repo(authority_path)) if authority_path else None
    old_path = 'research/development_evidence/TOP5_AFTER_PR1205_CUMULATIVE_DEV_G5_SUBAGENTS_V1/KR3/DRY_RUN.json'
    old = json.loads(read_repo(old_path))
    report_specs = {}
    for name in REPORTS:
        prior = old['reports'][name]
        report_specs[name] = {
            'producer':None,
            'missing_reason':'INDEPENDENT_PRODUCER_EXECUTION_NOT_PREREGISTERED; reviewed evaluation/source authority required',
            'reused_DEV_producer':prior.get('producer'),
            'reused_DEV_schema_pointer':prior.get('stored_schema_pointer'),
            'reused_DEV_evidence_receipt':selection['source_receipt_sha256'],
            'DEV_is_independent':False,
        }
    # The selection digest is an intent anchor, explicitly NOT an approved
    # independent preregistration. This draft cannot be consumed as an execution.
    bound = producer_contract(candidate, data_sha=selection['data_sha256']['DEV2025'],
        cost_sha=selection['cost_sha256'], preregistration_sha=selection['receipt_sha256'],
        report_specs=report_specs, producer_blobs={})
    return seal({'schema':'zel.step7.application.prepared.v1', 'candidate':candidate,
        'selection_sha256':selection['receipt_sha256'],
        'historical_configuration_seal':spec['receipt_sha256'],
        'historical_result_seal':receipt['receipt_sha256'],
        'previous_DEV_binding_reused':{'path':old_path,'file_sha256':byte_sha(read_repo(old_path)),
                                      'row_audit_repeated':False},
        'authority_input_sha256':sha(authority) if authority is not None else None,
        'authority_input_is_authorization':False,
        'independent_preregistration_status':'NOT_ACTIVATED_PENDING_AUTHORITY_AND_SOURCE',
        'producer_contract':bound,
        'new_bindings_resolved':['EXACT_SELECTED_FULL_IDENTITY','ENTRY_FUNCTION_AND_FILE_SHA',
                                 'EXIT_FUNCTION_AND_FILE_SHA','NATIVE_CONDITIONAL_EXIT_PROFILE',
                                 'NINE_REPORT_INPUT_OUTPUT_CONTRACT'],
        'source_required':['SIGNED_FUNDING','ENTRY_EXIT_QUOTES','SOURCE_AVAILABILITY_AND_CURSOR',
                           'INDEPENDENT_DATA_PROVENANCE'],
        'remaining_execution':['APPROVED_INDEPENDENT_PRODUCER_SPECS','ONE_INDEPENDENT_ECONOMIC_BUNDLE',
                               'EXISTING_P0_P6_AND_G5A_CONSUMER','FRESH_FORMAL_COHORT_IF_ELIGIBLE'],
        'status':'IMPLEMENTED_APPLICATION_BLOCKED_BEFORE_INDEPENDENT_EXECUTION',
        'G5A_qualified':False,'formal_admission':False,'G5B_terminal':False,
        'old_economic_verdict':selection['prior_verdict'], 'formal_credit':0,
        'market_replays':0, 'independent_accesses':0, 'protected_mutations':0})


def main():
    import argparse
    from pathlib import Path
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',default=str(Path(__file__).resolve().parents[3]))
    parser.add_argument('--selection',required=True)
    parser.add_argument('--authority')
    parser.add_argument('--output',required=True)
    parser.add_argument('--verify',action='store_true')
    args=parser.parse_args()
    result=prepare_application(args.root,args.selection,args.authority)
    out=Path(args.output)
    if not out.is_absolute():
        out=Path(args.root)/out
    payload=(json.dumps(result,sort_keys=True,indent=2,ensure_ascii=False,allow_nan=False)+'\n').encode()
    if args.verify:
        _require(out.read_bytes()==payload,'APPLICATION_REPRODUCTION_MISMATCH')
    else:
        out.parent.mkdir(parents=True,exist_ok=True)
        _require(not out.exists() or out.read_bytes()==payload,'APPLICATION_OUTPUT_ALREADY_DIFFERENT')
        out.write_bytes(payload)
    print(json.dumps({'status':result['status'],'receipt_sha256':result['receipt_sha256'],
                     'market_replays':0,'independent_accesses':0,'formal_admission':False,
                     'output':str(out)},sort_keys=True))


if __name__ == '__main__':
    main()
