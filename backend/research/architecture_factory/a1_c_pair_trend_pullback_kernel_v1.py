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
SCHEMA = 'zel.a1.c_pair.trend_pullback_kernel.v1'
PAIR_ID = 'CPAIR__turtle_trend__X__bb_revert__band_mean_reversion'
CHILD_ID = 'CMAT__TURTLE_TREND__X__BB_REVERT__TREND_PULLBACK_V1'


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
    # Distinct fixed semantic kernel. No donor numeric thresholds and no outcome/grid tuning.
    # Host concept: directional trend ownership. Donor concept: pullback/mean-reversion reclaim.
    return {
        'candidate_id': PAIR_ID,
        'strategy_id': CHILD_ID,
        'provider': 'deterministic_c_pair_compiler_v1',
        'candidate_type': 'REPAIR',
        'changed_axis': 'C_PAIR__BB_REVERT__BAND_MEAN_REVERSION__ONLY',
        'required_sources': ['ohlcv'],
        'source_refs': [],
        'mechanism_summary': 'trade only a pullback reclaim in the direction of a two-speed EMA trend',
        'expected_effect': 'retain trend direction while importing only a mean-reversion-to-trend reclaim mechanism',
        'risk': 'reclaims can whipsaw in flat transitions; fail closed without threshold tuning',
        'executable_spec': {
            'bar_interval': '1h',
            'features': [
                {'name':'ema20','formula':'ema(close,20)'},
                {'name':'ema50','formula':'ema(close,50)'},
                {'name':'prev_close','formula':'lag(close,1)'},
                {'name':'prev_ema20','formula':'lag(ema20,1)'},
            ],
            'entry_rule': '((ema20 > ema50 and close > ema20 and prev_close <= prev_ema20) or (ema20 < ema50 and close < ema20 and prev_close >= prev_ema20))',
            'side_rule': 'long if ema20 > ema50 else short',
            'exit_rule': 'time_stop',
            'max_hold_bars': 24,
            'entry_timing': 'next_bar_open',
            'cost_model': 'fixed_verified_round_trip_14bps',
            'development_data_rule': 'strictly_pre_gen1_boundary_only',
            'parameter_provenance': {
                'kernel': 'C_PAIR_TREND_PULLBACK_RECLAIM_V1',
                'optimized_on_outcomes': False,
                'donor_numeric_thresholds_copied': False,
                'grid_search': False,
                'notes': '20/50 EMA and 24-bar hold are fixed nursery-kernel constants; the donor contributes only the qualitative pullback-reclaim concept.'
            },
        },
    }


def run(out: Path) -> dict[str, Any]:
    grades = c_grade_ids()
    parents_ready = {'turtle_trend', 'bb_revert'}.issubset(grades)
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
                {'strategy_id':'bb_revert','grade':'C','role':'MEAN_REVERSION_DONOR_CONCEPT'},
            ],
            'compiler_mode': 'DETERMINISTIC_FIXED_KERNEL',
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
            'next': 'REGISTER_B_CHILD_AS_VALIDATED_DONOR' if absolute_b else 'NEXT_DETERMINISTIC_C_PAIR_KERNEL',
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
    print('PASS_A1_C_PAIR_TREND_PULLBACK_KERNEL_V1_SELF_TEST')
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', type=Path, default=Path('out/a1_c_pair_trend_pullback_kernel_v1.json'))
    ap.add_argument('--self-test', action='store_true')
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = run(args.out)
    print(json.dumps({'state':r['state'],'pair_id':r['pair_id'],'child':r['child_material_id'],'metrics':r.get('metrics',{}),'upgrade':r['c_to_b_upgrade_pass'],'next':r['next'],'receipt':r['receipt_sha256']}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
