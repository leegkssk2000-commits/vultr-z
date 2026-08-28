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
SCHEMA = 'zel.a1.c_pair_deterministic_compiler.v1'
PAIR_ID = 'CPAIR__bb_revert__X__squeeze_break__compression_expansion'
CHILD_ID = 'CMAT__BB_REVERT__X__SQUEEZE_BREAK__MR_VOL_V1'


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise RuntimeError(f'OBJECT_REQUIRED:{path}')
    return value


def stable(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False, default=str).encode()).hexdigest()


def c_grade_ids() -> set[str]:
    state = material.evaluate(read(LEDGER), read(INVENTORY), read(SSOT))
    out: set[str] = set()
    for row in state.get('rows') or []:
        if isinstance(row, Mapping) and str(row.get('material_grade') or '') == 'C' and row.get('strategy_id'):
            out.add(str(row['strategy_id']))
    return out


def candidate() -> dict[str, Any]:
    # Fixed synthesis kernel, preregistered before outcomes. Host/donor numeric thresholds are not copied.
    # Host concept: band mean reversion. Donor concept: local compression -> expansion transition.
    return {
        'candidate_id': PAIR_ID,
        'strategy_id': CHILD_ID,
        'provider': 'deterministic_c_pair_compiler_v1',
        'candidate_type': 'REPAIR',
        'changed_axis': 'C_PAIR__SQUEEZE_BREAK__COMPRESSION_EXPANSION__ONLY',
        'required_sources': ['ohlcv'],
        'source_refs': [],
        'mechanism_summary': 'standardized mean-reversion return toward center gated by a local volatility-width trough turning upward',
        'expected_effect': 'retain mean-reversion geometry while importing only the qualitative compression-to-expansion transition',
        'risk': 'fixed standardized kernel can remain economically weak; fail closed with no threshold sweep',
        'executable_spec': {
            'bar_interval': '1h',
            'features': [
                {'name':'mean24','formula':'sma(close,24)'},
                {'name':'sd24','formula':'std(close,24)'},
                {'name':'z24','formula':'(close-mean24)/max(sd24,0.00000001)'},
                {'name':'vol24','formula':'sd24/max(mean24,0.00000001)'},
                {'name':'z_prev','formula':'lag(z24,1)'},
                {'name':'vol_prev','formula':'lag(vol24,1)'},
                {'name':'vol_prev2','formula':'lag(vol24,2)'},
            ],
            'entry_rule': '((z_prev < -1.0 and z24 > z_prev) or (z_prev > 1.0 and z24 < z_prev)) and vol24 > vol_prev and vol_prev <= vol_prev2',
            'side_rule': 'long if z24 < 0 else short',
            'exit_rule': 'time_stop',
            'max_hold_bars': 24,
            'entry_timing': 'next_bar_open',
            'cost_model': 'fixed_verified_round_trip_14bps',
            'development_data_rule': 'strictly_pre_gen1_boundary_only',
            'parameter_provenance': {
                'kernel': 'C_PAIR_STANDARDIZED_MR_VOL_V1',
                'optimized_on_outcomes': False,
                'donor_numeric_thresholds_copied': False,
                'grid_search': False,
                'notes': '24-bar normalization and 1-sigma standardized excursion are nursery-kernel constants, not copied from either donor strategy.'
            },
        },
    }


def run(out: Path) -> dict[str, Any]:
    grades = c_grade_ids()
    parents_ready = {'bb_revert', 'squeeze_break'}.issubset(grades)
    if not parents_ready:
        result = {
            'schema_version': SCHEMA,
            'state': 'HOLD_C_PAIR_PARENT_GRADE_CHANGED',
            'pair_id': PAIR_ID,
            'child_material_id': CHILD_ID,
            'current_c_grade_ids': sorted(grades),
            'c_to_b_upgrade_pass': False,
            'provider_request_count': 0,
            'next': 'RESELECT_C_PAIR',
        }
    else:
        c = candidate()
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
                {'strategy_id':'bb_revert','grade':'C','role':'MEAN_REVERSION_HOST_CONCEPT'},
                {'strategy_id':'squeeze_break','grade':'C','role':'COMPRESSION_EXPANSION_DONOR_CONCEPT'},
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
    assert c['provider'] == 'deterministic_c_pair_compiler_v1'
    assert c['executable_spec']['parameter_provenance']['optimized_on_outcomes'] is False
    assert c['executable_spec']['parameter_provenance']['donor_numeric_thresholds_copied'] is False
    assert c['required_sources'] == ['ohlcv']
    print('PASS_A1_C_PAIR_DETERMINISTIC_COMPILER_V1_SELF_TEST')
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', type=Path, default=Path('out/a1_c_pair_deterministic_compiler_v1.json'))
    ap.add_argument('--self-test', action='store_true')
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = run(args.out)
    print(json.dumps({'state':r['state'],'pair_id':r['pair_id'],'child':r['child_material_id'],'metrics':r.get('metrics',{}),'upgrade':r['c_to_b_upgrade_pass'],'next':r['next'],'receipt':r['receipt_sha256']}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
