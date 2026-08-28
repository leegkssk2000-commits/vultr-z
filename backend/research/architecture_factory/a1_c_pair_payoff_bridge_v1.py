#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from backend.research.architecture_factory import a1_gen2_generic_dev_econ_v3 as econ

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / 'backend/research/architecture_factory/a1_c_pair_deterministic_compiler_latest.json'
SCHEMA = 'zel.a1.c_pair_payoff_bridge.v1'


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise RuntimeError(f'OBJECT_REQUIRED:{path}')
    return value


def stable(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False, default=str).encode()).hexdigest()


def grade_b(metrics: Mapping[str, Any], economic_pass: bool) -> dict[str, bool]:
    payoff = metrics.get('payoff')
    dd = metrics.get('drawdown_bps')
    return {
        'economic_pass': economic_pass is True,
        'trades_ge_12': int(metrics.get('trades') or 0) >= 12,
        'net_pnl_positive': float(metrics.get('net_pnl_bps') or 0.0) > 0.0,
        'net_expectancy_positive': float(metrics.get('net_expectancy_bps') or 0.0) > 0.0,
        'profit_factor_gt_1': float(metrics.get('profit_factor') or 0.0) > 1.0,
        'payoff_ge_1': payoff is not None and float(payoff) >= 1.0,
        'finite_drawdown': dd is not None and math.isfinite(float(dd)),
    }


def payoff_only_near_pass(source: Mapping[str, Any]) -> tuple[bool, dict[str, bool]]:
    metrics = source.get('metrics') if isinstance(source.get('metrics'), Mapping) else {}
    checks = grade_b(metrics, source.get('development_state') == 'PASS_DEVELOPMENT_ECONOMICS')
    failed = [k for k, ok in checks.items() if not ok]
    return failed == ['payoff_ge_1'], checks


def child_candidate(source: Mapping[str, Any]) -> dict[str, Any]:
    base = source.get('candidate')
    if not isinstance(base, Mapping):
        raise RuntimeError('SOURCE_CANDIDATE_MISSING')
    child = deepcopy(dict(base))
    spec = child.get('executable_spec')
    if not isinstance(spec, dict):
        raise RuntimeError('SOURCE_SPEC_MISSING')
    names = {str(x.get('name') or '') for x in (spec.get('features') or []) if isinstance(x, Mapping)}
    if not {'z24', 'z_prev'}.issubset(names):
        raise RuntimeError('PAYOFF_BRIDGE_REQUIRES_Z24_ZPREV')
    old_exit = str(spec.get('exit_rule') or '')
    # Single preregistered causal exit axis: leave an excursion when standardized
    # distance crosses its mean center. Existing max-hold remains the fallback.
    new_exit = '(z24 >= 0 and z_prev < 0) or (z24 <= 0 and z_prev > 0)'
    spec['exit_rule'] = new_exit
    provenance = spec.get('parameter_provenance') if isinstance(spec.get('parameter_provenance'), dict) else {}
    provenance = deepcopy(provenance)
    provenance.update({
        'payoff_bridge': 'CENTER_CROSS_EXIT_V1',
        'payoff_bridge_preregistered': True,
        'payoff_bridge_grid_search': False,
        'payoff_bridge_best_horizon_selection': False,
        'payoff_bridge_changed_axis': 'EXIT_RULE_ONLY',
    })
    spec['parameter_provenance'] = provenance
    child['candidate_id'] = str(source.get('pair_id') or child.get('candidate_id') or '') + '__PAYOFF_CENTER_EXIT_V1'
    child['strategy_id'] = str(source.get('child_material_id') or child.get('strategy_id') or '') + '__PAYOFF_CENTER_EXIT_V1'
    child['changed_axis'] = 'PAYOFF_BRIDGE__CENTER_CROSS_EXIT__ONLY'
    child['provider'] = 'deterministic_c_pair_payoff_bridge_v1'
    child['mechanism_summary'] = str(child.get('mechanism_summary') or '') + '; exit when standardized mean-reversion excursion causally crosses center'
    child['expected_effect'] = 'raise realized winner/loss asymmetry without changing entry, side, horizon cap, source, or cost'
    child['payoff_bridge_parent_exit_rule'] = old_exit
    return child


def structural_diff(parent: Mapping[str, Any], child: Mapping[str, Any]) -> dict[str, Any]:
    p = parent.get('executable_spec') if isinstance(parent.get('executable_spec'), Mapping) else {}
    c = child.get('executable_spec') if isinstance(child.get('executable_spec'), Mapping) else {}
    invariant_keys = ['bar_interval','features','entry_rule','side_rule','max_hold_bars','entry_timing','cost_model','development_data_rule']
    changed = [k for k in invariant_keys if p.get(k) != c.get(k)]
    return {
        'invariant_field_changes': changed,
        'exit_rule_changed': p.get('exit_rule') != c.get('exit_rule'),
        'single_axis_exit_only': not changed and p.get('exit_rule') != c.get('exit_rule'),
    }


def run(out: Path, source_path: Path = SOURCE) -> dict[str, Any]:
    source = read(source_path)
    near, parent_checks = payoff_only_near_pass(source)
    base = {
        'schema_version': SCHEMA,
        'source_receipt': str(source_path),
        'source_receipt_sha256': source.get('receipt_sha256'),
        'source_state': source.get('state'),
        'parent_grade_b_checks': parent_checks,
        'verified_cost_bps': source.get('verified_cost_bps'),
        'production_mutated': False,
        'selection_authority': False,
        'promotion_authority': False,
        'execution_authority': 'NONE',
        'order_authority': 'BLOCKED',
        'live_trade_authority': 'BLOCKED',
        'action': 'hold',
    }
    if not near:
        result = {**base, 'state':'HOLD_NOT_PAYOFF_ONLY_NEAR_PASS','payoff_bridge_executed':False,'c_to_b_upgrade_pass':False,'next':'RETURN_TO_C_PAIR_COMPILER_OR_DIAGNOSE_OTHER_GATE'}
    else:
        parent = source.get('candidate') if isinstance(source.get('candidate'), Mapping) else {}
        child = child_candidate(source)
        diff = structural_diff(parent, child)
        if not diff['single_axis_exit_only']:
            raise RuntimeError(f'EXIT_ONLY_INVARIANT_BROKEN:{diff}')
        dev = econ.evaluate_queue([child])
        row = (dev.get('rows') or [{}])[0]
        metrics = row.get('metrics') if isinstance(row.get('metrics'), Mapping) else {}
        checks = grade_b(metrics, row.get('economic_pass') is True)
        passed = all(checks.values())
        result = {
            **base,
            'state': 'PASS_B_MATERIAL_PAYOFF_BRIDGE' if passed else 'HOLD_PAYOFF_BRIDGE_NO_ABSOLUTE_B_PASS',
            'payoff_bridge_executed': True,
            'pair_id': source.get('pair_id'),
            'parent_child_material_id': source.get('child_material_id'),
            'child_material_id': child.get('strategy_id'),
            'changed_axis': 'EXIT_RULE_ONLY',
            'structural_diff': diff,
            'parent_metrics': source.get('metrics') or {},
            'child_metrics': metrics,
            'development_state': row.get('state'),
            'development_error': row.get('error'),
            'child_grade_b_checks': checks,
            'c_to_b_upgrade_pass': passed,
            'material_grade': 'B' if passed else 'C_PAIR_FAILED',
            'candidate': child,
            'no_threshold_sweep': True,
            'best_horizon_selection': False,
            'fresh_validation_required_before_top5_use': True,
            'next': 'VALIDATE_B_MATERIAL_FRESH_AS_DONOR' if passed else 'NEXT_DISTINCT_C_PAIR_KERNEL',
        }
    result['receipt_sha256'] = stable(result)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + '\n', encoding='utf-8')
    return result


def self_test() -> int:
    source = {
        'pair_id':'p','child_material_id':'c','development_state':'PASS_DEVELOPMENT_ECONOMICS','verified_cost_bps':14.0,
        'metrics':{'trades':55,'net_pnl_bps':1.0,'net_expectancy_bps':0.1,'profit_factor':1.01,'payoff':0.98,'drawdown_bps':10.0},
        'candidate':{'candidate_id':'p','strategy_id':'c','required_sources':['ohlcv'],'executable_spec':{
            'bar_interval':'1h','features':[{'name':'z24','formula':'ret(1)'},{'name':'z_prev','formula':'lag(z24,1)'}],
            'entry_rule':'z24 > 0','side_rule':'long','exit_rule':'time_stop','max_hold_bars':24,'entry_timing':'next_bar_open',
            'cost_model':'14bps','development_data_rule':'pre','parameter_provenance':{}
        }}
    }
    near, checks = payoff_only_near_pass(source)
    assert near and checks['payoff_ge_1'] is False
    child = child_candidate(source)
    diff = structural_diff(source['candidate'], child)
    assert diff['single_axis_exit_only'] is True
    assert child['executable_spec']['parameter_provenance']['payoff_bridge_grid_search'] is False
    print('PASS_A1_C_PAIR_PAYOFF_BRIDGE_V1_SELF_TEST')
    return 0


def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument('--out',type=Path,default=Path('out/a1_c_pair_payoff_bridge_v1.json'))
    ap.add_argument('--source',type=Path,default=SOURCE)
    ap.add_argument('--self-test',action='store_true')
    a=ap.parse_args()
    if a.self_test:return self_test()
    r=run(a.out,a.source)
    print(json.dumps({'state':r['state'],'upgrade':r['c_to_b_upgrade_pass'],'child_metrics':r.get('child_metrics',{}),'next':r['next'],'receipt':r['receipt_sha256']},sort_keys=True))
    return 0

if __name__=='__main__':
    raise SystemExit(main())
