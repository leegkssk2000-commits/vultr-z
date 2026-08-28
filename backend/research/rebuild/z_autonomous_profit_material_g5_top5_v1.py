#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

from backend.research.architecture_factory import a1_c_pair_payoff_bridge_v1 as payoff_bridge

ROOT = Path(__file__).resolve().parents[3]
NURSERY = ROOT / 'backend/research/architecture_factory/a1_c_grade_pair_nursery_latest.json'
C_COMPILER = ROOT / 'backend/research/architecture_factory/a1_c_pair_deterministic_compiler_latest.json'
PAYOFF_LATEST = ROOT / 'backend/research/architecture_factory/a1_c_pair_payoff_bridge_latest.json'
RR = ROOT / 'backend/research/rebuild/a1_top5_fixed_rr_payoff_shadow_latest.json'
G5 = ROOT / 'backend/research/prep/g5_trendrider_broad30_product_latest.json'
TOP5 = ROOT / 'backend/research/rebuild/a1_top5_latest_only_ssot_v1.json'
SCHEMA = 'zel.autonomous_profit_material_g5_top5.v1'

SAFE_EXECUTION = {
    'selection_authority': False,
    'promotion_authority': False,
    'execution_authority': 'NONE',
    'order_authority': 'BLOCKED',
    'live_trade_authority': 'BLOCKED',
}


def read(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding='utf-8'))
    return value if isinstance(value, dict) else {}


def stable(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False, default=str).encode()).hexdigest()


def authority_safe(value: Mapping[str, Any]) -> bool:
    return (
        value.get('selection_authority') in {None, False}
        and value.get('promotion_authority') in {None, False}
        and value.get('execution_authority') in {None, 'NONE'}
        and value.get('order_authority') in {None, 'BLOCKED'}
        and value.get('live_trade_authority') in {None, 'BLOCKED'}
    )


def source_stage(name: str, path: Path, schema_prefix: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    value = read(path)
    if not value:
        return ({'state':'HOLD_SOURCE_MISSING','path':str(path)}, [{'stage':name,'class':'BINDING_ARTIFACT','state':'HOLD','reason':'authoritative source missing'}])
    schema = str(value.get('schema_version') or '')
    if not schema.startswith(schema_prefix):
        return ({'state':'HOLD_SCHEMA_MISMATCH','path':str(path),'schema_version':schema}, [{'stage':name,'class':'SOFTWARE_CONTRACT','state':'HOLD','reason':'source schema mismatch'}])
    if not authority_safe(value):
        return ({'state':'HOLD_UNSAFE_AUTHORITY','path':str(path),'schema_version':schema}, [{'stage':name,'class':'SOFTWARE_CONTRACT','state':'HOLD','reason':'research source exposes unsafe authority'}])
    return ({'state':value.get('state'),'path':str(path),'schema_version':schema,'receipt_sha256':value.get('receipt_sha256')}, [])


def payoff_stage(out_dir: Path, compiler: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], bool]:
    blockers: list[dict[str, Any]] = []
    latest = read(PAYOFF_LATEST)
    source_sha = compiler.get('receipt_sha256')
    reused = bool(latest and latest.get('source_receipt_sha256') == source_sha and authority_safe(latest))
    if reused:
        value = latest
    else:
        out = out_dir / 'c_pair_payoff_bridge.json'
        try:
            value = payoff_bridge.run(out, C_COMPILER)
        except Exception as exc:
            return ({
                'state':'HOLD_PAYOFF_BRIDGE_SOFTWARE_OR_SOURCE_ERROR',
                'error':f'{type(exc).__name__}:{str(exc)[:320]}',
                'source_receipt_sha256':source_sha,
                'reused':False,
            }, [{'stage':'c_payoff_bridge','class':'SOFTWARE_CONTRACT','state':'HOLD','reason':f'{type(exc).__name__}:{str(exc)[:240]}'}], False)
    state = str(value.get('state') or '')
    if state == 'PASS_B_MATERIAL_PAYOFF_BRIDGE':
        cls = 'PASS_B_MATERIAL'
    elif state == 'HOLD_PAYOFF_BRIDGE_NO_ABSOLUTE_B_PASS':
        cls = 'ECONOMIC_QUALITY'
        blockers.append({'stage':'c_payoff_bridge','class':cls,'state':'HOLD','reason':'single preregistered exit-axis repair did not clear absolute Grade-B economics'})
    elif state == 'HOLD_NOT_PAYOFF_ONLY_NEAR_PASS':
        cls = 'ECONOMIC_QUALITY'
        blockers.append({'stage':'c_payoff_bridge','class':cls,'state':'HOLD','reason':'C child is not an exact payoff-only near-pass; do not force this repair axis'})
    else:
        cls = 'UNKNOWN'
        blockers.append({'stage':'c_payoff_bridge','class':cls,'state':'HOLD','reason':state or 'unknown payoff bridge state'})
    return ({
        'state':state,
        'classification':cls,
        'source_receipt_sha256':value.get('source_receipt_sha256'),
        'receipt_sha256':value.get('receipt_sha256'),
        'parent_metrics':value.get('parent_metrics'),
        'child_metrics':value.get('child_metrics'),
        'c_to_b_upgrade_pass':bool(value.get('c_to_b_upgrade_pass')),
        'material_grade':value.get('material_grade'),
        'changed_axis':value.get('changed_axis'),
        'next':value.get('next'),
        'reused':reused,
        'artifact':str(PAYOFF_LATEST if reused else out_dir / 'c_pair_payoff_bridge.json'),
    }, blockers, not reused)


def rr_stage(value: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    lanes = value.get('lanes') if isinstance(value.get('lanes'), list) else []
    pass_count = sum(int(x.get('pass_count') or 0) for x in lanes if isinstance(x, Mapping))
    cells = int(value.get('cells') or 0)
    out = {
        'state':value.get('state'),
        'cells':cells,
        'lane_count':len(lanes),
        'strict_pass_count':pass_count,
        'strict_upgrade_present':pass_count > 0,
        'diagnostic_grid_only':True,
        'retrospective_best_cell_is_promotion_authority':False,
        'best_cell_selection_performed':False,
        'next':'INDEPENDENT_PREREGISTERED_PAYOFF_AXIS_ONLY' if pass_count == 0 else 'FRESH_VALIDATE_STRICT_PASS_BEFORE_ANY_USE',
    }
    blockers = [] if pass_count else [{'stage':'fixed_rr','class':'ECONOMIC_QUALITY','state':'HOLD','reason':'fixed-RR grid has zero strict upgrade cells; no retrospective best-cell promotion'}]
    return out, blockers


def g5_stage(value: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    windows = value.get('windows') if isinstance(value.get('windows'), Mapping) else {}
    w2 = windows.get('W2') if isinstance(windows.get('W2'), Mapping) else {}
    w3 = windows.get('W3') if isinstance(windows.get('W3'), Mapping) else {}
    m2 = w2.get('metrics') if isinstance(w2.get('metrics'), Mapping) else {}
    m3 = w3.get('metrics') if isinstance(w3.get('metrics'), Mapping) else {}
    t2 = int(m2.get('trades') or 0); target2 = int(w2.get('target_T') or 12)
    t3 = int(m3.get('trades') or 0); target3 = int(w3.get('target_T') or 12)
    strict_target = 25
    state = str(value.get('state') or '')
    waiting = t2 < target2 or t3 < target3 or state.startswith('WAIT_')
    out = {
        'state':state,
        'postlock_closed_T':int(value.get('postlock_closed_T') or 0),
        'W2_T':t2,'W2_target_T':target2,
        'W3_T':t3,'W3_target_T':target3,
        'strict_target_T':strict_target,
        'target_lowered':False,
        'old_history_union':bool(value.get('old_history_union')),
        'threshold_retune':bool(value.get('threshold_retune')),
        'policy_retune':bool(value.get('policy_retune')),
        'classification':'TIME_SAMPLE' if waiting else 'ECONOMIC_QUALITY' if not bool((value.get('checks') or {}).get('combined_economics_nonfail')) else 'READY_OR_PASS',
    }
    blockers: list[dict[str, Any]] = []
    if target2 < 12 or target3 < 12 or out['old_history_union'] or out['threshold_retune'] or out['policy_retune']:
        blockers.append({'stage':'g5','class':'SOFTWARE_CONTRACT','state':'HOLD','reason':'G5 frozen sample/retune invariant violated'})
        out['state'] = 'HOLD_G5_INTEGRITY'
    elif waiting:
        blockers.append({'stage':'g5','class':'TIME_SAMPLE','state':'WAIT','reason':f'fresh G5 W2/W3 sample incomplete ({t2}/{target2}, {t3}/{target3}); no backfill or target lowering'})
    elif out['classification'] == 'ECONOMIC_QUALITY':
        blockers.append({'stage':'g5','class':'ECONOMIC_QUALITY','state':'HOLD','reason':'fresh G5 sample exists but combined economics/stress gate is not nonfail'})
    return out, blockers


def top5_stage(value: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    policy = value.get('record_policy') if isinstance(value.get('record_policy'), Mapping) else {}
    rows = value.get('top5') if isinstance(value.get('top5'), list) else []
    integrity = (
        value.get('state') == 'CURRENT_TOP5_ONLY'
        and policy.get('use_only_this_file_for_current_top5_reporting') is True
        and policy.get('old_history_union') is False
    )
    lanes = []
    blockers: list[dict[str, Any]] = []
    for raw in rows:
        if not isinstance(raw, Mapping):
            continue
        fresh = raw.get('fresh_to_25') if isinstance(raw.get('fresh_to_25'), Mapping) else {}
        g5 = raw.get('g5') if isinstance(raw.get('g5'), Mapping) else {}
        lane = {
            'rank':raw.get('rank'),'strategy':raw.get('strategy'),'strategy_id':raw.get('strategy_id'),
            'current_role':raw.get('current_role'),'survivor':bool(raw.get('survivor')),
            'T_needed_to_25':fresh.get('T_needed'),
            'g5_state':g5.get('state'),
        }
        lanes.append(lane)
        need = fresh.get('T_needed')
        if isinstance(need, (int,float)) and int(need) > 0:
            blockers.append({'stage':f"top5_rank_{raw.get('rank')}",'class':'TIME_SAMPLE_OR_QUALITY','state':'WAIT','reason':f"fresh T to 25 still needs {int(need)}; historical strict ceiling is diagnostic only"})
        if str(g5.get('state') or '').startswith('WAIT_'):
            blockers.append({'stage':f"top5_rank_{raw.get('rank')}",'class':'TIME_SAMPLE','state':'WAIT','reason':str(g5.get('state'))})
    if not integrity:
        blockers.insert(0, {'stage':'top5','class':'SOFTWARE_CONTRACT','state':'HOLD','reason':'latest-only Top5 SSOT integrity failed'})
    return {
        'state':value.get('state') if integrity else 'HOLD_TOP5_SSOT_INTEGRITY',
        'authority':value.get('authority'),
        'latest_only_integrity':integrity,
        'old_history_union':policy.get('old_history_union'),
        'lane_count':len(lanes),
        'lanes':lanes,
        'historical_ceiling_promotion_forbidden':True,
        'quality_attribution_required_before_entry_relaxation':True,
    }, blockers


def self_test() -> int:
    assert authority_safe(SAFE_EXECUTION)
    g = {'state':'WAIT_G5_W2_12','old_history_union':False,'threshold_retune':False,'policy_retune':False,'windows':{'W2':{'target_T':12,'metrics':{'trades':0}},'W3':{'target_T':12,'metrics':{'trades':0}}},'checks':{}}
    gs, gb = g5_stage(g)
    assert gs['classification'] == 'TIME_SAMPLE' and gb[0]['state'] == 'WAIT' and gs['W2_target_T'] == 12
    rr, rb = rr_stage({'state':'HOLD_NO_FIXED_RR_UPGRADE','cells':45,'lanes':[{'pass_count':0}]})
    assert rr['best_cell_selection_performed'] is False and rb[0]['class'] == 'ECONOMIC_QUALITY'
    top, tb = top5_stage({'state':'CURRENT_TOP5_ONLY','record_policy':{'use_only_this_file_for_current_top5_reporting':True,'old_history_union':False},'top5':[{'rank':1,'strategy':'x','fresh_to_25':{'T_needed':2}}]})
    assert top['latest_only_integrity'] is True and tb[0]['state'] == 'WAIT'
    print('PASS_Z_AUTONOMOUS_PROFIT_MATERIAL_G5_TOP5_V1_SELF_TEST')
    return 0


def run(out: Path, out_dir: Path) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stages: dict[str, Any] = {}
    blockers: list[dict[str, Any]] = []

    nursery = read(NURSERY)
    ns, nb = source_stage('nursery_v2', NURSERY, 'zel.a1.c_grade_pair_nursery')
    if nursery:
        ns.update({
            'provider':nursery.get('provider'),
            'eligible_c_material_count':nursery.get('eligible_c_material_count'),
            'pair_count_this_run':nursery.get('pair_count_this_run'),
            'c_to_b_upgrade_count':nursery.get('c_to_b_upgrade_count'),
            'dsl_preflight':nursery.get('dsl_preflight'),
        })
    stages['nursery_v2'] = ns; blockers.extend(nb)

    compiler = read(C_COMPILER)
    cs, cb = source_stage('c_pair_compiler', C_COMPILER, 'zel.a1.c_pair_deterministic_compiler')
    if compiler:
        cs.update({'development_state':compiler.get('development_state'),'metrics':compiler.get('metrics'),'grade':compiler.get('material_grade'),'next':compiler.get('next')})
        # Exact payoff-only near-pass is a safe deterministic repair trigger.
        near, checks = payoff_bridge.payoff_only_near_pass(compiler)
        cs['grade_b_checks'] = checks; cs['payoff_only_near_pass'] = near
    stages['c_pair_compiler'] = cs; blockers.extend(cb)

    payoff_written = False
    if compiler and authority_safe(compiler):
        ps, pb, payoff_written = payoff_stage(out_dir, compiler)
    else:
        ps, pb = ({'state':'HOLD_PAYOFF_BRIDGE_SOURCE_UNAVAILABLE'}, [{'stage':'c_payoff_bridge','class':'BINDING_ARTIFACT','state':'HOLD','reason':'C compiler source unavailable or unsafe'}])
    stages['c_payoff_bridge'] = ps; blockers.extend(pb)

    rr = read(RR)
    rs0, rb0 = source_stage('fixed_rr', RR, 'zel.a1.top5.fixed_rr_payoff_shadow')
    if rr and not rb0:
        rs, rb = rr_stage(rr); rs.update({'receipt_sha256':rr.get('receipt_sha256')})
    else:
        rs, rb = rs0, rb0
    stages['fixed_rr'] = rs; blockers.extend(rb)

    g5 = read(G5)
    gs0, gb0 = source_stage('g5', G5, 'zel.g5.trendrider_broad30.product_oos')
    if g5 and not gb0:
        gs, gb = g5_stage(g5); gs.update({'receipt_sha256':g5.get('receipt_sha256')})
    else:
        gs, gb = gs0, gb0
    stages['g5'] = gs; blockers.extend(gb)

    top5 = read(TOP5)
    ts0, tb0 = source_stage('top5', TOP5, 'zel.a1.top5.latest_only_ssot')
    if top5 and not tb0:
        ts, tb = top5_stage(top5)
    else:
        ts, tb = ts0, tb0
    stages['top5'] = ts; blockers.extend(tb)

    # De-duplicate blocker records while retaining stage-specific truth.
    seen: set[str] = set(); uniq: list[dict[str, Any]] = []
    for b in blockers:
        key = json.dumps(b, sort_keys=True, separators=(',', ':'))
        if key not in seen:
            seen.add(key); uniq.append(b)

    software = [b for b in uniq if b.get('class') in {'SOFTWARE_CONTRACT','BINDING_ARTIFACT','WRITER_CONFLICT'}]
    waits = [b for b in uniq if b.get('state') == 'WAIT']
    economics = [b for b in uniq if b.get('class') == 'ECONOMIC_QUALITY']
    result = {
        'schema_version':SCHEMA,
        'state':'HOLD_SOFTWARE_BLOCKER' if software else 'COMPLETE_WITH_HOLDS' if uniq else 'PASS_ALL_RESEARCH_GATES',
        'latest_only_ssot_required':True,
        'old_history_union_allowed':False,
        'paid_ai_requests_by_controller':0,
        'automatic_safe_repair_policy':{
            'software_contract':'repair only when deterministic bounded patch is encoded',
            'binding_artifact':'repair only authoritative receipt binding; never fabricate source',
            'writer_conflict':'single-writer only',
            'payoff_only_one_axis':'one preregistered exit-axis bridge',
            'time_sample':'WAIT; never lower target or backfill',
            'economic_quality':'HOLD; never weaken economic gate',
            'unknown':'HOLD_UNKNOWN',
        },
        'stages':stages,
        'blocker_ledger':uniq,
        'blocker_counts':{'total':len(uniq),'software':len(software),'wait':len(waits),'economic':len(economics)},
        'safe_autorepair_executed':payoff_written,
        'safe_autorepair_count':1 if payoff_written else 0,
        'next':'REPAIR_SOFTWARE_BLOCKERS_ONLY' if software else 'WAIT_OR_RUN_NEXT_PREREGISTERED_ECONOMIC_AXIS',
        'production_mutated':False,
        **SAFE_EXECUTION,
        'action':'hold',
    }
    result['receipt_sha256'] = stable(result)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + '\n', encoding='utf-8')
    return result


def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument('--out',type=Path,default=Path('out/z_autonomous_profit_material_g5_top5_v1.json'))
    ap.add_argument('--out-dir',type=Path,default=Path('out/z_autonomous_profit_material_g5_top5'))
    ap.add_argument('--self-test',action='store_true')
    a=ap.parse_args()
    if a.self_test:return self_test()
    r=run(a.out,a.out_dir)
    print(json.dumps({'state':r['state'],'blockers':r['blocker_counts'],'autorepair':r['safe_autorepair_count'],'next':r['next'],'receipt':r['receipt_sha256']},sort_keys=True))
    return 0

if __name__=='__main__':
    raise SystemExit(main())
