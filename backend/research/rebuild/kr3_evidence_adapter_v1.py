"""INACTIVE candidate-local KR3 stored-DEV adapter. No market IO or boundary writes.

A binding PASS means stored bytes, row identities and arithmetic agree. It never
means G5A/G5B PASS. Source tape and signed execution lineage are not inferred.
"""
from __future__ import annotations
import argparse
import ast
from collections import Counter
import gzip
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BASE = 'research/development_evidence/FOCUSED_REPAIR_20260907_V1'
DRAFT = 'research/development_evidence/TOP5_LIFECYCLE_AI_G5_AFTER_PR1204/KR3_FORMAL_APPLICATION_DRAFT.json'
SPEC = BASE + '/SPEC.json'
RECEIPT = BASE + '/KR3/receipt.json'
ARTIFACT = BASE + '/KR3/DEV2025.json.gz'
REBUILD = 'backend/research/rebuild/'
CONTROLLER = REBUILD + 'g5_g14_generation_controller_v1.py'
TERMINAL = REBUILD + 'g5b_operational_terminal_v1.py'
CONTRACT = REBUILD + 'g5_g14_shared_validation_contract_v1.json'
ALPHA = 'backend/research/alpha_proof/a1_alpha_proof_gate_v1.py'
CANDIDATE = 'KELTNER_KR3_PRIOR_SUPPRESSED_BREACH_EXTENSION_VETO_DEV_V1'
DRAFT_AUTHORITY_SHA256 = 'd7bc9d8465c5798562732e1db1e05eb0e1ccecd1662593bbeebeeb073a18c7cd'
SCOPE = 'TOP5_AFTER_PR1205_CUMULATIVE_DEV_G5_SUBAGENTS_V1'
OUTPUT = 'research/development_evidence/' + SCOPE + '/KR3'
OWNERS = {
    REBUILD+'focused_repair_v1.py': ['run', 'replay'],
    REBUILD+'keltner_kr3_v1.py': ['path', 'replay'],
    REBUILD+'parallel_exit_dev_v1.py': ['charge_result'],
    REBUILD+'top5_development_repair_v1.py': ['charge'],
    REBUILD+'parallel_exit_metrics_v1.py': ['build_stage', 'same_calendar_windows'],
    REBUILD+'break_channel_metrics_v1.py': ['summarize', 'period_metrics'],
    REBUILD+'top5_sprint_metrics_v1.py': ['effects'],
    TERMINAL: ['freeze_boundary', 'independence'],
    CONTROLLER: ['lane_terminal_errors', 'terminal_receipt_passes', 'independence_audit_passes'],
    ALPHA: ['evaluate_bundle', 'evaluate_p4'],
}


def sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def byte_sha(value):
    return hashlib.sha256(value).hexdigest()


def read_inputs(root=ROOT):
    """Allowlisted stored DEV only; never reads SEEN2026 artifact or raw tape."""
    paths = {DRAFT, SPEC, RECEIPT, ARTIFACT, CONTRACT, *OWNERS}
    blobs = {}
    for path in (DRAFT, SPEC):
        if (root/path).is_file():
            blobs[path] = (root/path).read_bytes()
    if DRAFT in blobs:
        paths.update(json.loads(blobs[DRAFT])['development_binding']['files_sha256'])
    if SPEC in blobs:
        paths.update(json.loads(blobs[SPEC])['code_files_sha256'])
    for path in sorted(paths):
        # All discovered paths must be repository code or the pinned focused inputs.
        if not (path.startswith(REBUILD) or path in {DRAFT, SPEC, RECEIPT, ARTIFACT, CONTRACT, ALPHA}):
            raise ValueError('INPUT_PATH_OUTSIDE_APPROVED_SCOPE:' + path)
        if (root/path).is_file():
            blobs[path] = (root/path).read_bytes()
    return blobs


def _same(a, b):
    return isinstance(a, (int, float)) and not isinstance(a, bool) and math.isfinite(a) and math.isclose(a, b, rel_tol=1e-11, abs_tol=1e-8)


def verify_binding(blobs):
    errors, checks = [], []
    def check(name, ok):
        checks.append({'check': name, 'pass': bool(ok)})
        if not ok:
            errors.append(name)
    required = {DRAFT, SPEC, RECEIPT, ARTIFACT, CONTRACT, *OWNERS}
    missing = sorted(required - blobs.keys())
    if missing:
        return {'status': 'MISSING', 'errors': ['MISSING:'+p for p in missing], 'checks': checks}
    try:
        draft, spec, receipt, contract = [json.loads(blobs[p]) for p in (DRAFT, SPEC, RECEIPT, CONTRACT)]
        artifact = json.loads(gzip.decompress(blobs[ARTIFACT]))
        binding = draft['development_binding']
        check('draft_authority_bytes', byte_sha(blobs[DRAFT]) == DRAFT_AUTHORITY_SHA256)
        for name, doc in [('spec', spec), ('receipt', receipt)]:
            check(name+'_self_seal', doc['receipt_sha256'] == sha({k:v for k,v in doc.items() if k != 'receipt_sha256'}))
        file_pins = {**binding['files_sha256'], **spec['code_files_sha256']}
        file_pins.update({p: spec['preserved_files_sha256'][p] for p in OWNERS if p in spec['preserved_files_sha256']})
        for path, expected in sorted(file_pins.items()):
            check('file:'+path, path in blobs and byte_sha(blobs[path]) == expected)
        check('candidate_FULL_identity', draft['candidate_id'] == CANDIDATE and receipt['candidate'] == artifact['candidate'] == 'KR3' and draft['native']['formal_candidate'] == 'FULL' and artifact['period'] == 'DEV2025')
        check('lane_identity', draft['lane_id'] == 'keltner_trend_main')
        check('spec_result_link', binding['spec_seal'] == spec['receipt_sha256'] == receipt['spec_seal'])
        check('result_seal_link', binding['result_seal'] == receipt['receipt_sha256'])
        check('frozen_commit_link', binding['frozen_commit'] == receipt['frozen_commit'])
        check('artifact_bytes', receipt['artifacts']['DEV2025']['path'] == ARTIFACT and receipt['artifacts']['DEV2025']['file_sha256'] == byte_sha(blobs[ARTIFACT]))
        check('data_metadata_link', binding['data_sha']['DEV2025'] == spec['period_data_sha256']['DEV2025'])
        check('cost_metadata_link', binding['cost_sha'] == spec['cost_sha256'])
        check('no_SL_invention', draft['native']['initial_protective_sl'] is None)
        view = artifact['views']['FULL']
        code_sha = sha(spec['code_files_sha256'])
        identities = dict(code_sha256=code_sha, config_sha256=spec['receipt_sha256'], data_sha256=spec['period_data_sha256']['DEV2025'], cost_sha256=spec['cost_sha256'], lane_id=draft['lane_id'], scenario='KR3', comparison_stage='KR3')
        rows = view['trades'] + view['open_observations']
        check('nonempty_stored_FULL', bool(rows))
        check('unique_origins', len({t['origin_key'] for t in rows}) == len(rows))
        start, end = spec['calendars']['DEV2025']
        for i, row in enumerate(rows):
            check(f'row_identity:{i}', all(row.get(k) == v for k,v in identities.items()))
            field = 'trade_sha256' if i < len(view['trades']) else 'observation_sha256'
            check(f'row_hash:{i}', row[field] == sha({k:v for k,v in row.items() if k != field}))
            check(f'row_DEV_only:{i}', row.get('independent') is False and row.get('formal_credit') == 0 and row.get('production_grade') is not True and row.get('execution_authority') == 'NONE' and row.get('evidence_type') == 'REUSED_DEV_EXIT_COMPARISON')
            terminal = row.get('exit_ts', row.get('mark_ts'))
            check(f'row_time:{i}', start <= row['signal_ts'] <= row['entry_ts'] <= terminal <= end)
        components = ('fee_bps','spread_bps','impact_bps','slippage_bps','funding_bps','frozen_floor_reserve_bps')
        for i, row in enumerate(view['trades']):
            check(f'cost_components:{i}', _same(row['cost_bps'], sum(row[k] for k in components)))
            check(f'net_identity:{i}', _same(row['net_bps'], row['gross_bps'] - row['cost_bps']))
            check(f'cost2_identity:{i}', _same(row['cost2x_net_bps'], row['gross_bps'] - 2*row['cost_bps']))
        for i, row in enumerate(view['open_observations']):
            cost = row['hypothetical_liquidation_cost_bps']
            check(f'open_cost:{i}', _same(cost, sum(row['hypothetical_cost_components_bps'].values())))
            check(f'open_net:{i}', _same(row['hypothetical_liquidation_net_mark_bps'], row['gross_mark_bps']-cost))
            check(f'open_cost2:{i}', _same(row['hypothetical_liquidation_cost2x_net_mark_bps'], row['gross_mark_bps']-2*cost))
            check(f'open_not_realized:{i}', row['actual_exit'] is False and row['terminal_liquidation'] is False)
        values = artifact['values']['FULL']
        check('receipt_values_exact', values == receipt['results']['DEV2025']['values']['FULL'])
        check('closed_count', values['closed_T'] == len(view['trades']))
        check('open_count', values['open_T'] == len(view['open_observations']))
        for target, field in [('closed_net_bps','net_bps'),('closed_cost2x_net_bps','cost2x_net_bps'),('closed_cost_bps','cost_bps'),('closed_gross_bps','gross_bps')]:
            check('ledger_sum:'+target, _same(values[target], sum(t[field] for t in view['trades'])))
        # Existing producer executed only on stored rows; no price path is replayed.
        from backend.research.rebuild.top5_sprint_metrics_v1 import effects
        retention = effects(artifact['views']['KR1_FULL'], view)
        check('existing_retention_producer_exact', retention == artifact['effects']['KR1_FULL'])
        check('zero_integrity_authority', contract['g5_terminal_gate']['integrity_equals'] == {'errors':0,'duplicate':0,'censored_open':0,'unknown_exit':0})
        owner_map = {}
        for path, names in OWNERS.items():
            parsed = ast.parse(blobs[path].decode())
            found = {n.name:n.lineno for n in ast.walk(parsed) if isinstance(n, ast.FunctionDef)}
            check('owner_functions:'+path, all(n in found for n in names))
            owner_map[path] = {'sha256':byte_sha(blobs[path]), 'functions':{n:found.get(n) for n in names}}
        return {'status':'INVALID' if errors else 'VALID_DEV_BINDING', 'errors':errors, 'checks':checks,
                'identity':{'candidate_id':CANDIDATE,'mode':'FULL',**identities,'result_receipt_sha256':receipt['receipt_sha256'],'source_artifact_file_sha256':byte_sha(blobs[ARTIFACT]),'frozen_commit':receipt['frozen_commit']},
                'values':values,'retention_vs_KR1':{k:retention[k] for k in ('ordinary_winners','large_winners')},'owner_map':owner_map,
                'raw_source_bytes_verified':False,'signed_funding_or_fill_lineage_verified':False,
                'source_verification_limit':'Stored DEV artifact bytes and row/spec metadata bindings verified; raw price/cost source bytes not loaded or independently certified.'}
    except (ValueError, TypeError, KeyError, OSError, EOFError, RuntimeError, AttributeError) as exc:
        return {'status':'INVALID','errors':errors+['MALFORMED:'+str(exc)],'checks':checks}


def report_bindings(result):
    """Actual available producers; absent experiment producers remain absent."""
    rows = {
        'base_replay':('focused_repair_v1.py:replay -> keltner_kr3_v1.py:replay/path -> parallel_exit_metrics_v1.py:build_stage','views.FULL; stages.FULL; values.FULL','closed/open counts; net/expectancy in trade-bps; PF/payoff dimensionless','DEV arithmetic verified; stored market replay reused; no independent validation'),
        'realistic_cost':('parallel_exit_dev_v1.py:charge_result -> top5_development_repair_v1.py:charge','trades cost components; open hypothetical cost components','fee/spread/impact/slippage/funding/floor in trade-bps','DEV proxy components verified; signed settlements, quotes, fill timestamps absent'),
        'cost2x':('parallel_exit_metrics_v1.py:build_stage -> break_channel_metrics_v1.py:summarize','values.FULL.closed_cost2x_net_bps; terminal_cost2x_net_bps_hypothetical','gross_bps - 2*all_cost_components_bps','Stored DEV all-cost arithmetic verified; formal fresh stress not performed'),
        'purged_oos':(None,None,'UTC ms; closed net and expectancy trade-bps; PF dimensionless','No KR3 purged OOS producer/result; DEV cannot be relabeled OOS'),
        'chronological_split':('break_channel_metrics_v1.py:period_metrics; parallel_exit_metrics_v1.py:same_calendar_windows','stages.FULL.metrics.by_exit_month; comparisons.FULL','UTC month; trade-bps; position-days','DEV descriptive periods only; approved W1/W2/W3 execution absent'),
        'symbol_decomposition':('break_channel_metrics_v1.py:summarize','stages.FULL.metrics.by_symbol','symbol; counts; trade-bps; PF dimensionless','DEV decomposition exists; formal matching calendar/source required'),
        'regime_decomposition':(None,None,'causal regime_id and market_shock_id; timestamp UTC ms; trade-bps','No KR3 reviewed regime producer or labeled formal source'),
        'parameter_neighbor_stability':(None,None,'frozen parameter neighborhood; effect trade-bps; uncertainty units explicit','No KR3 neighbor replay producer/result; new economic experiments require authorization'),
        'negative_controls':(None,None,'matched calendar/cost controls; effect trade-bps','alpha_proof.evaluate_p4 is a consumer/checker, not a control-result producer; absent KR3 controls'),
    }
    return {name:{'producer':p,'stored_schema_pointer':s,'required_units':u,'applicability':a,
                  'consumer':TERMINAL+':freeze_boundary; '+CONTROLLER+':terminal_receipt_passes/lane_terminal_errors',
                  'required_report_schema':{'receipt_sha256':'nonempty exact receipt digest','candidate_sha256':'alpha-proof candidate digest','data_sha':'same identity digest','cost_sha':'same identity digest','complete':'true only after full applicable economic evidence'},
                  'evidence_tag':'DEV_USED' if s else 'UNEVALUATED','complete':False,'formal_eligible':False,
                  'stored_binding_valid':result['status']=='VALID_DEV_BINDING' if s else False}
            for name,(p,s,u,a) in rows.items()}


def approval_bundle(contract):
    owner = CONTROLLER + '; explicit KR3 candidate formal-contract approver (not identified in supplied authority)'
    items = {
      'initial_risk_R_denominator': {'proposal':'Statistical volatility-normalized R only: d_i=10000*ATR20(signal_close_i)/entry_open_i; R_i=net_bps_i/d_i; NetR_W=sum(R_i). ATR20 uses completed native4h bars through signal close, Wilder seed=mean first20 true ranges; TR=max(H-L,abs(H-prevC),abs(L-prevC)). Reject missing/nonpositive d_i. Freeze definition before new outcomes.', 'units':'d_i trade-bps; R dimensionless; not an account-risk multiple or stop distance','impact':'No SL order added. Requires authority to accept this statistical R in the existing net_r field; otherwise field remains unavailable.'},
      'protective_SL_operating_contract':{'proposal':'Retain initial_protective_sl=null. Approver must determine whether the formal lane permits a no-SL candidate. If actual protective SL required, KR3 is inapplicable and a separately authorized strategy-change experiment is necessary.','units':'order existence/operating requirement','impact':'Statistical denominator cannot satisfy an operating SL requirement.'},
      'retention_denominator_baseline':{'proposal':'Use frozen KR1_FULL matching origin set B with closed parent net b_i>0: D=sum_B b_i; retention=100*sum_B min(b_i,max(0,child_closed_net_i))/D. Missing child contributes zero retained profit, never a zero-return trade. Child still open gives lower bound above and upper bound adding b_i; D=0 -> unavailable. Report all parent winners; separately preserve existing top-decile/ordinary DEV diagnostics.','units':'D trade-bps; retention percent','impact':'Requires explicit baseline/calendar and all-winner versus ordinary/large-window acceptance. Existing 60% formal gate preserved, never substituted with DEV ratio.'},
      'W1_W2_W3_windows':{'proposal':'Before new outcomes approve UTC start S and duration L (native4h aligned): Wk=[S+(k-1)L,S+kL), k=1..3; entry attribution by signal-close time. Freeze candidate selection through W3. No retrospective endpoint selection.','units':'S,L UTC ms; L unresolved','impact':'No authorized concrete dates/duration in prior draft; no windows created.'},
      'purge_embargo_runoff':{'proposal':'For each fold, purge any fitting label interval [entry_ts,max_possible_exit_ts] intersecting evaluation label intervals. Conservative embargo E=24*4h=96h inherited maximum horizon, plus observed next-open delay if later. Stop new evaluation entries at right edge minus approved max horizon/delay; carry existing positions to observed exit within authorized runoff, otherwise censored_open remains nonzero. Warmup past bars is feature-only.','units':'ms/hours, closed/open counts','impact':'96h is a proposed conservative data-separation rule derived from existing cap; not approved window policy. Gaps cannot be filled or forced liquidated.'},
      'market_shock_and_regime_owner':{'proposal':'Source owner must supply causal regime_id, market_shock_id, availability_ts<=decision_ts, method/code/source hashes. Existing independence() groups same signal timestamp, then merges groups connected by any common reviewed shock ID.','units':'group identities; UTC ms','impact':'No post-outcome winner/loser or final-MFE labels allowed as execution features; missing labels => unvalidated audit.'},
      'N_effective_terminal_threshold':{'proposal':'N_effective=count(connected components of same-signal-window/shared-reviewed-shock graph). Approve terminal sample rule before observation; candidate power proposal N_min=ceil(((z_(1-alpha*/2)+z_(1-beta))*sigma_cluster/delta_min)^2), with sigma from approved DEV cluster estimator. Do not set N_min until alpha*, beta, delta_min and cluster authority are approved.','units':'clusters; sigma and delta same net effect units','impact':'Raw trades never treated as independent N. Existing controller has no approved numerical terminal N; no 100/200T invented.'},
      'minimum_economic_effect':{'proposal':'Approve delta_min>0 in mean net trade-bps per independent cluster (and paired baseline if incremental claim); test lower confidence bound>delta_min while retaining every existing absolute window gate.','units':'trade-bps per declared cluster estimand','impact':'No unseen results used to pick delta; candidate-specific value absent.'},
      'review_schedule_multiple_testing':{'proposal':'Freeze one terminal look after W3 and complete authorized runoff. T6/T12 are existing continuation reviews, never terminal claims. If K economic claims are authorized, preallocate familywise alpha across claims (e.g. alpha*=alpha/K) and use no unscheduled efficacy looks. Approve alpha,beta,K and sequential error spending if any early efficacy look is wanted.','units':'probabilities; number of tests/looks','impact':'Preserve historical candidate multiplicity; new filename is not a fresh testing family.'},
      'source_specific_stale_authority':{'proposal':'For each concrete source approve threshold T_source in ms and source clock/availability semantics; freshness=0<=as_of_ms-last_verified_source_close_ms<T_source; missing approval fails closed.','units':'UTC ms','impact':'Historical receipt freshness is never inferred from recent file timestamps.'},
      'threshold_authority':{'proposal':'Bind the exact shared contract digest and existing economic_window_thresholds/integrity_equals to KR3; approve only missing candidate-specific units, baselines, windows, effective N and testing policy.','existing_authority':contract['g5_terminal_gate'],'units':'as declared per metric','impact':'Shared thresholds unchanged; a code owner is not evidence of a human approval.'},
    }
    return {'status':'PROPOSED_NOT_APPROVED','approver':owner,'single_bundle_required':True,
            'items':{k:{'owner':owner,'approved':False,**v} for k,v in items.items()}}


def unresolved_transitions(draft, binding, approval):
    status = {k:'NEEDS_AUTHORITY' for k in draft['unresolved']}
    status.update(error_tolerance='ACTUAL_RESOLVED_BINDING' if binding['status']=='VALID_DEV_BINDING' else 'CODE_PREPARED',
                  P0_P6_bundle='CODE_PREPARED',fresh_source_receipt='NEEDS_REAL_MARKET_SOURCE',
                  signed_funding_and_execution_lineage='NEEDS_REAL_MARKET_SOURCE',formal_economic_receipt='UNEVALUATED')
    return {k:{'previous':v,'current_class':status[k],
               'implementation':('Exact shared integrity_equals bound and checked against candidate DEV counts; allowed formal errors/duplicate/censored_open/unknown_exit all 0.' if k=='error_tolerance' else
                                 'Existing alpha.evaluate_bundle invoked on bound candidate-local incomplete evidence; blockers returned without inventing support.' if k=='P0_P6_bundle' else
                                 approval['items'][k] if k in approval['items'] else
                                 'No fresh source/settlement/fill collection or formal economic evaluation performed.'),
               'evidence':{'binding_status':binding['status'],'result_receipt_sha256':binding.get('identity',{}).get('result_receipt_sha256')},
               'formal_satisfied':False} for k,v in draft['unresolved'].items()}


def dry_run(blobs):
    binding = verify_binding(blobs)
    result = {'schema':'kr3.evidence.adapter.dryrun.v1','scope_key':SCOPE,'mode':'INACTIVE',
              'binding':binding,'formal_credit':0,'production_grade':False,'formal_admission':False,
              'boundary_created':False,'market_replays':0,'activation_authority':False,
              'input_paths_and_sha':{p:byte_sha(b) for p,b in sorted(blobs.items())},
              'reports':report_bindings(binding)}
    if DRAFT in blobs and CONTRACT in blobs:
        try:
            draft, contract = json.loads(blobs[DRAFT]),json.loads(blobs[CONTRACT])
            if not isinstance(draft, dict) or not isinstance(contract, dict) or 'unresolved' not in draft or 'g5_terminal_gate' not in contract:
                return result
        except (ValueError, TypeError):
            return result
        approval = approval_bundle(contract)
        result['approval_bundle'] = approval
        result['unresolved_transitions'] = unresolved_transitions(draft,binding,approval)
        result['transition_counts'] = dict(Counter(v['current_class'] for v in result['unresolved_transitions'].values()))
    if binding['status']=='VALID_DEV_BINDING':
        from backend.research.alpha_proof import a1_alpha_proof_gate_v1 as alpha
        candidate = {'candidate_id':CANDIDATE,'research_only':True,'development_identity':binding['identity']}
        candidate['candidate_sha256'] = alpha.sha(candidate)
        result['P0_P6_preflight'] = alpha.evaluate_bundle({'candidate':candidate})
    return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=ROOT/OUTPUT/'DRY_RUN.json');args=parser.parse_args()
    result=dry_run(read_inputs())
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,sort_keys=True,allow_nan=False)+'\n')
    print(json.dumps({'status':result['binding']['status'],'errors':result['binding']['errors'],'transition_counts':result.get('transition_counts'),'formal_credit':0,'market_replays':0}))
    return 0 if result['binding']['status']=='VALID_DEV_BINDING' else 1


if __name__=='__main__':
    raise SystemExit(main())
