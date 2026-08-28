#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

from backend.research.prep import strategy_material_grade_v1 as material
from backend.research.architecture_factory import a1_gen2_generic_dev_econ_v3 as econ

ROOT = Path(__file__).resolve().parents[3]
LEDGER = ROOT / 'backend/research/rebuild/a1_exact25_disposition_ledger_v1.json'
INVENTORY = ROOT / 'backend/research/rebuild/strategy25_structural_inventory_v2.json'
SSOT = ROOT / 'backend/research/prep/strategy_synthesis_material_ssot_v1.json'
SCHEMA = 'zel.a1.c_pair.trend_breakout_kernel.v1'
PAIR_ID = 'CPAIR__turtle_trend__X__squeeze_break__trend_aligned_breakout'
CHILD_ID = 'CMAT__TURTLE_TREND__X__SQUEEZE_BREAK__TREND_BREAKOUT_V1'


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise RuntimeError(f'OBJECT_REQUIRED:{path}')
    return value


def stable(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False, default=str).encode()).hexdigest()


def c_grade_ids() -> set[str]:
    state = material.evaluate(read(LEDGER), read(INVENTORY), read(SSOT))
    return {
        str(row['strategy_id'])
        for row in state.get('rows') or []
        if isinstance(row, Mapping) and str(row.get('material_grade') or '') == 'C' and row.get('strategy_id')
    }


def candidate() -> dict[str, Any]:
    # Third and final bounded semantic rotation for this roadmap pass.
    # Host concept: trend ownership. Donor concept: breakout/expansion confirmation.
    # No thresholds are copied from source strategies and no outcomes are used to tune the kernel.
    return {
        'candidate_id': PAIR_ID,
        'strategy_id': CHILD_ID,
        'provider': 'deterministic_c_pair_compiler_v1',
        'candidate_type': 'REPAIR',
        'changed_axis': 'C_PAIR__SQUEEZE_BREAK__BREAKOUT_CONFIRMATION__ONLY',
        'required_sources': ['ohlcv'],
        'source_refs': [],
        'mechanism_summary': 'accept a fresh channel breakout only when the two-speed EMA trend agrees with breakout direction',
        'expected_effect': 'combine trend persistence with expansion confirmation while avoiding counter-trend breakouts',
        'risk': 'breakouts can fail in choppy regimes; fail closed without threshold tuning',
        'executable_spec': {
            'bar_interval': '1h',
            'features': [
                {'name':'ema20','formula':'ema(close,20)'},
                {'name':'ema50','formula':'ema(close,50)'},
                {'name':'prior_high20','formula':'lag(highest(high,20),1)'},
                {'name':'prior_low20','formula':'lag(lowest(low,20),1)'},
            ],
            'entry_rule': '((ema20 > ema50 and close > prior_high20) or (ema20 < ema50 and close < prior_low20))',
            'side_rule': 'long if close > prior_high20 else short',
            'exit_rule': 'time_stop',
            'max_hold_bars': 24,
            'entry_timing': 'next_bar_open',
            'cost_model': 'fixed_verified_round_trip_14bps',
            'development_data_rule': 'strictly_pre_gen1_boundary_only',
            'parameter_provenance': {
                'kernel': 'C_PAIR_TREND_ALIGNED_BREAKOUT_V1',
                'optimized_on_outcomes': False,
                'donor_numeric_thresholds_copied': False,
                'grid_search': False,
                'notes': '20/50 EMA, 20-bar prior channel and 24-bar hold are fixed nursery-kernel constants, not copied from either C material.'
            },
        },
    }


def run(out: Path) -> dict[str, Any]:
    grades = c_grade_ids()
    parents_ready = {'turtle_trend', 'squeeze_break'}.issubset(grades)
    c = candidate()
    if not parents_ready:
        result = {
            'schema_version': SCHEMA,
            'state': 'HOLD_C_PAIR_PARENT_GRADE_CHANGED',
            'pair_id': PAIR_ID,
            'child_material_id': CHILD_ID,
            'current_c_grade_ids': sorted(grades),
            'candidate': c,
            'c_to_b_upgrade_pass': False,
            'provider_request_count': 0,
            'next': 'RESELECT_C_PAIR',
        }
    else:
        dev = econ.evaluate_queue([c])
        row = (dev.get('rows') or [{}])[0]
        m = row.get('metrics') if isinstance(row.get('metrics'), Mapping) else {}
        payoff = m.get('payoff')
        dd = m.get('drawdown_bps')
        absolute_b = bool(
            row.get('economic_pass') is True
            and int(m.get('trades') or 0) >= 12
            and float(m.get('net_pnl_bps') or 0.0) > 0.0
            and float(m.get('net_expectancy_bps') or 0.0) > 0.0
            and float(m.get('profit_factor') or 0.0) > 1.0
            and payoff is not None and float(payoff) >= 1.0
            and dd is not None and math.isfinite(float(dd))
        )
        result = {
            'schema_version': SCHEMA,
            'state': 'PASS_C_TO_B_MATERIAL_CHILD' if absolute_b else 'HOLD_C_PAIR_NO_ABSOLUTE_ECONOMIC_PASS',
            'pair_id': PAIR_ID,
            'child_material_id': CHILD_ID,
            'source_materials': [
                {'strategy_id':'turtle_trend','grade':'C','role':'TREND_HOST_CONCEPT'},
                {'strategy_id':'squeeze_break','grade':'C','role':'BREAKOUT_EXPANSION_DONOR_CONCEPT'},
            ],
            'compiler_mode': 'DETERMINISTIC_FIXED_KERNEL',
            'bounded_rotation_index': 3,
            'bounded_rotation_final_for_this_pass': True,
            'provider_request_count': 0,
            'candidate': c,
            'development_state': row.get('state'),
            'metrics': m,
            'c_to_b_upgrade_pass': absolute_b,
            'material_grade': 'B' if absolute_b else 'C_PAIR_FAILED',
            'fresh_validation_required_before_top5_use': True,
            'no_threshold_sweep': True,
            'donor_numeric_threshold_copy': False,
            'verified_cost_bps': 14.0,
            'next': 'REGISTER_B_CHILD_AS_VALIDATED_DONOR' if absolute_b else 'CLASSIFY_C_PAIR_AS_ECONOMIC_BOTTLENECK_AND_CONTINUE_RR_PARALLEL',
        }
    result.update({
        'production_mutated': False,
        'selection_authority': False,
        'promotion_authority': False,
        'execution_authority': 'NONE',
        'order_authority': 'BLOCKED',
        'live_trade_authority': 'BLOCKED',
        'action': 'hold',
    })
    result['receipt_sha256'] = stable(result)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + '\n', encoding='utf-8')
    return result


def self_test() -> int:
    c = candidate()
    assert c['candidate_id'] == PAIR_ID
    assert c['executable_spec']['parameter_provenance']['optimized_on_outcomes'] is False
    assert c['executable_spec']['parameter_provenance']['donor_numeric_thresholds_copied'] is False
    assert c['provider'] == 'deterministic_c_pair_compiler_v1'
    print('PASS_A1_C_PAIR_TREND_BREAKOUT_KERNEL_V1_SELF_TEST')
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', type=Path, default=Path('out/a1_c_pair_trend_breakout_kernel_v1.json'))
    ap.add_argument('--self-test', action='store_true')
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = run(args.out)
    print(json.dumps({'state':r['state'],'pair_id':r['pair_id'],'child':r['child_material_id'],'metrics':r.get('metrics',{}),'upgrade':r['c_to_b_upgrade_pass'],'next':r['next'],'receipt':r['receipt_sha256']}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
