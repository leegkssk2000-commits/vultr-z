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
MEMORY = ROOT / 'backend/research/architecture_factory/a1_c_pair_deterministic_compiler_latest.json'
NURSERY = ROOT / 'backend/research/architecture_factory/a1_c_grade_pair_nursery_latest.json'
SCHEMA = 'zel.a1.c_pair_deterministic_compiler.v2'

# Ordered, preregistered semantic kernels. No outcome-dependent ordering, no threshold sweep.
KERNELS = (
    {
        'pair_id':'CPAIR__bb_revert__X__squeeze_break__compression_expansion',
        'child_id':'CMAT__BB_REVERT__X__SQUEEZE_BREAK__MR_VOL_V1',
        'parents':('bb_revert','squeeze_break'),
        'roles':('MEAN_REVERSION_HOST_CONCEPT','COMPRESSION_EXPANSION_DONOR_CONCEPT'),
        'changed_axis':'C_PAIR__SQUEEZE_BREAK__COMPRESSION_EXPANSION__ONLY',
        'mechanism':'standardized mean-reversion return toward center gated by a local volatility-width trough turning upward',
        'expected':'retain mean-reversion geometry while importing only the qualitative compression-to-expansion transition',
        'kernel':'C_PAIR_STANDARDIZED_MR_VOL_V1',
        'features':[
            {'name':'mean24','formula':'sma(close,24)'},
            {'name':'sd24','formula':'std(close,24)'},
            {'name':'z24','formula':'(close-mean24)/max(sd24,0.00000001)'},
            {'name':'vol24','formula':'sd24/max(mean24,0.00000001)'},
            {'name':'z_prev','formula':'lag(z24,1)'},
            {'name':'vol_prev','formula':'lag(vol24,1)'},
            {'name':'vol_prev2','formula':'lag(vol24,2)'},
        ],
        'entry_rule':'((z_prev < -1.0 and z24 > z_prev) or (z_prev > 1.0 and z24 < z_prev)) and vol24 > vol_prev and vol_prev <= vol_prev2',
        'side_rule':'long if z24 < 0 else short',
    },
    {
        'pair_id':'CPAIR__turtle_trend__X__bb_revert__band_mean_reversion',
        'child_id':'CMAT__TURTLE_TREND__X__BB_REVERT__TREND_PULLBACK_V1',
        'parents':('turtle_trend','bb_revert'),
        'roles':('TREND_HOST_CONCEPT','MEAN_REVERSION_DONOR_CONCEPT'),
        'changed_axis':'C_PAIR__BB_REVERT__BAND_MEAN_REVERSION__ONLY',
        'mechanism':'trade only a pullback reclaim in the direction of a two-speed trend',
        'expected':'retain trend direction while importing only a mean-reversion-to-trend reclaim mechanism',
        'kernel':'C_PAIR_TREND_PULLBACK_RECLAIM_V1',
        'features':[
            {'name':'ema20','formula':'ema(close,20)'},
            {'name':'ema50','formula':'ema(close,50)'},
            {'name':'prev_close','formula':'lag(close,1)'},
            {'name':'prev_ema20','formula':'lag(ema20,1)'},
        ],
        'entry_rule':'((ema20 > ema50 and close > ema20 and prev_close <= prev_ema20) or (ema20 < ema50 and close < ema20 and prev_close >= prev_ema20))',
        'side_rule':'long if ema20 > ema50 else short',
    },
    {
        'pair_id':'CPAIR__turtle_trend__X__squeeze_break__compression_expansion',
        'child_id':'CMAT__TURTLE_TREND__X__SQUEEZE_BREAK__TREND_VOL_V1',
        'parents':('turtle_trend','squeeze_break'),
        'roles':('TREND_HOST_CONCEPT','COMPRESSION_EXPANSION_DONOR_CONCEPT'),
        'changed_axis':'C_PAIR__SQUEEZE_BREAK__COMPRESSION_EXPANSION__ONLY',
        'mechanism':'directional trend ownership gated by a local volatility-width trough turning upward',
        'expected':'retain trend ownership while importing only the qualitative compression-to-expansion timing gate',
        'kernel':'C_PAIR_TREND_VOL_EXPANSION_V1',
        'features':[
            {'name':'ema20','formula':'ema(close,20)'},
            {'name':'ema50','formula':'ema(close,50)'},
            {'name':'mean24','formula':'sma(close,24)'},
            {'name':'sd24','formula':'std(close,24)'},
            {'name':'vol24','formula':'sd24/max(mean24,0.00000001)'},
            {'name':'vol_prev','formula':'lag(vol24,1)'},
            {'name':'vol_prev2','formula':'lag(vol24,2)'},
        ],
        'entry_rule':'((ema20 > ema50 and close > ema20) or (ema20 < ema50 and close < ema20)) and vol24 > vol_prev and vol_prev <= vol_prev2',
        'side_rule':'long if ema20 > ema50 else short',
    },
)


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
        str(row['strategy_id']) for row in state.get('rows') or []
        if isinstance(row, Mapping) and str(row.get('material_grade') or '') == 'C' and row.get('strategy_id')
    }


def attempted_pair_ids() -> set[str]:
    out: set[str] = set()
    for path in (NURSERY, MEMORY):
        if not path.exists():
            continue
        doc = read(path)
        out.update(str(x) for x in doc.get('attempted_pair_ids') or [] if x)
        if doc.get('pair_id'):
            out.add(str(doc['pair_id']))
    return out


def select_kernel(grades: set[str], attempted: set[str]) -> Mapping[str, Any] | None:
    for k in KERNELS:
        if str(k['pair_id']) in attempted:
            continue
        if set(k['parents']).issubset(grades):
            return k
    return None


def candidate(k: Mapping[str, Any]) -> dict[str, Any]:
    return {
        'candidate_id': k['pair_id'],
        'strategy_id': k['child_id'],
        'provider': 'deterministic_c_pair_compiler_v2',
        'candidate_type': 'REPAIR',
        'changed_axis': k['changed_axis'],
        'required_sources': ['ohlcv'],
        'source_refs': [],
        'mechanism_summary': k['mechanism'],
        'expected_effect': k['expected'],
        'risk': 'fixed semantic kernel can remain economically weak; fail closed and rotate without threshold tuning',
        'executable_spec': {
            'bar_interval': '1h',
            'features': list(k['features']),
            'entry_rule': k['entry_rule'],
            'side_rule': k['side_rule'],
            'exit_rule': 'time_stop',
            'max_hold_bars': 24,
            'entry_timing': 'next_bar_open',
            'cost_model': 'fixed_verified_round_trip_14bps',
            'development_data_rule': 'strictly_pre_gen1_boundary_only',
            'parameter_provenance': {
                'kernel': k['kernel'],
                'optimized_on_outcomes': False,
                'donor_numeric_thresholds_copied': False,
                'grid_search': False,
                'rotation_order_outcome_selected': False,
                'notes': 'All constants are fixed nursery-kernel constants; pair selection uses only preregistered order and attempted identity memory.'
            },
        },
    }


def run(out: Path) -> dict[str, Any]:
    grades = c_grade_ids()
    attempted = attempted_pair_ids()
    k = select_kernel(grades, attempted)
    if k is None:
        result = {
            'schema_version': SCHEMA,
            'state': 'HOLD_DETERMINISTIC_C_PAIR_ROTATION_EXHAUSTED',
            'attempted_pair_ids': sorted(attempted),
            'preregistered_pair_ids': [str(x['pair_id']) for x in KERNELS],
            'current_c_grade_ids': sorted(grades),
            'c_to_b_upgrade_pass': False,
            'provider_request_count': 0,
            'next': 'PREREGISTER_DISTINCT_C_PAIR_KERNEL_BEFORE_NEXT_RUN',
        }
    else:
        c = candidate(k)
        dev = econ.evaluate_queue([c])
        row = (dev.get('rows') or [{}])[0]
        m = row.get('metrics') if isinstance(row.get('metrics'), Mapping) else {}
        payoff = m.get('payoff'); dd = m.get('drawdown_bps')
        absolute_b = bool(
            row.get('economic_pass') is True
            and int(m.get('trades') or 0) >= 12
            and float(m.get('net_pnl_bps') or 0.0) > 0.0
            and float(m.get('net_expectancy_bps') or 0.0) > 0.0
            and float(m.get('profit_factor') or 0.0) > 1.0
            and payoff is not None and float(payoff) >= 1.0
            and dd is not None and math.isfinite(float(dd))
        )
        attempted_after = sorted(attempted | {str(k['pair_id'])})
        remaining = [str(x['pair_id']) for x in KERNELS if str(x['pair_id']) not in set(attempted_after) and set(x['parents']).issubset(grades)]
        result = {
            'schema_version': SCHEMA,
            'state': 'PASS_C_TO_B_MATERIAL_CHILD' if absolute_b else 'HOLD_C_PAIR_NO_ABSOLUTE_ECONOMIC_PASS',
            'pair_id': k['pair_id'],
            'child_material_id': k['child_id'],
            'attempted_pair_ids': attempted_after,
            'remaining_preregistered_pair_ids': remaining,
            'source_materials': [
                {'strategy_id':k['parents'][0],'grade':'C','role':k['roles'][0]},
                {'strategy_id':k['parents'][1],'grade':'C','role':k['roles'][1]},
            ],
            'compiler_mode': 'DETERMINISTIC_PREREGISTERED_ROTATION',
            'provider_request_count': 0,
            'candidate': c,
            'development_state': row.get('state'),
            'metrics': m,
            'c_to_b_upgrade_pass': absolute_b,
            'material_grade': 'B' if absolute_b else 'C_PAIR_FAILED',
            'fresh_validation_required_before_top5_use': True,
            'no_threshold_sweep': True,
            'donor_numeric_threshold_copy': False,
            'failed_pair_retest_same_identity_allowed': False,
            'verified_cost_bps': 14.0,
            'next': 'REGISTER_B_CHILD_AS_VALIDATED_DONOR' if absolute_b else ('NEXT_DETERMINISTIC_C_PAIR_KERNEL' if remaining else 'PREREGISTER_DISTINCT_C_PAIR_KERNEL_BEFORE_NEXT_RUN'),
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
    ids = [str(x['pair_id']) for x in KERNELS]
    assert len(ids) == len(set(ids)) == 3
    grades = {'bb_revert','squeeze_break','turtle_trend'}
    k = select_kernel(grades, {ids[0], ids[1]})
    assert k is not None and k['pair_id'] == ids[2]
    assert select_kernel(grades, set(ids)) is None
    c = candidate(KERNELS[2])
    p = c['executable_spec']['parameter_provenance']
    assert p['optimized_on_outcomes'] is False and p['donor_numeric_thresholds_copied'] is False and p['grid_search'] is False
    print('PASS_A1_C_PAIR_DETERMINISTIC_COMPILER_V2_ROTATION_SELF_TEST')
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', type=Path, default=Path('out/a1_c_pair_deterministic_compiler_v1.json'))
    ap.add_argument('--self-test', action='store_true')
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = run(args.out)
    print(json.dumps({'state':r['state'],'pair_id':r.get('pair_id'),'child':r.get('child_material_id'),'metrics':r.get('metrics',{}),'upgrade':r.get('c_to_b_upgrade_pass'),'next':r['next'],'receipt':r['receipt_sha256']}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
