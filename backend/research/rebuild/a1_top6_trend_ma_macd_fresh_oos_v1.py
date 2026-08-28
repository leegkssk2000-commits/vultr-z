#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild import a1_exact25_generic_evaluator_v2 as ev2

ROOT = Path(__file__).resolve().parents[3]
LEDGER = ROOT / 'backend/research/rebuild/a1_exact25_disposition_ledger_v1.json'
QUALIFIER = ROOT / 'backend/research/rebuild/a1_top6_trend_ma_macd_rebound_qualifier_latest.json'
REBOUND = ROOT / 'backend/research/rebuild/a1_top6_trend_ma_macd_long_rebound_latest.json'
SCHEMA = 'zel.a1.top6.trend_ma_macd.fresh_oos.v1'
BOUNDARY_UTC = '2026-08-28T04:49:33Z'
TARGET_T = 12
SYMBOLS = 'BTC-USDT,ETH-USDT,SOL-USDT,XRP-USDT,1INCH-USDT,ETHFI-USDT,HYPE-USDT,BCH-USDT,APE-USDT,1000PEPE-USDT,DOGE-USDT,LINK-USDT'
EPS = 1e-12


def stable(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False, default=str).encode()).hexdigest()


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise RuntimeError(f'OBJECT_REQUIRED:{path}')
    return value


def trade_key(row: Mapping[str, Any]) -> tuple[str, int, int, str]:
    return str(row['symbol']), int(row['signal_ts']), int(row['entry_ts']), str(row['side'])


def metrics(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    vals = [float(x.get('net_bps') or 0.0) for x in rows]
    wins = [x for x in vals if x > 0]
    losses = [-x for x in vals if x < 0]
    gp, gl = sum(wins), sum(losses)
    eq = peak = dd = 0.0
    for value in vals:
        eq += value
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    avgw = gp / len(wins) if wins else 0.0
    avgl = gl / len(losses) if losses else 0.0
    return {
        'trades': len(vals),
        'symbols': len({str(x.get('symbol')) for x in rows}),
        'wins': len(wins),
        'win_rate': len(wins) / len(vals) if vals else 0.0,
        'net_pnl_bps': sum(vals),
        'net_expectancy_bps': sum(vals) / len(vals) if vals else 0.0,
        'profit_factor': gp / gl if gl > 0 else ('INF' if gp > 0 else None),
        'payoff': avgw / avgl if avgl > 0 else ('INF' if avgw > 0 else None),
        'drawdown_bps': dd,
    }


def gt_one(value: Any) -> bool:
    if value == 'INF':
        return True
    return isinstance(value, (int, float)) and math.isfinite(float(value)) and float(value) > 1.0 + EPS


def ge_one(value: Any) -> bool:
    if value == 'INF':
        return True
    return isinstance(value, (int, float)) and math.isfinite(float(value)) and float(value) + EPS >= 1.0


def current_policy_replay(out_path: Path) -> dict[str, Any]:
    canonical = LEDGER.read_bytes()
    ledger_sha = hashlib.sha256(canonical).hexdigest()
    ledger = json.loads(canonical.decode('utf-8'))
    row = (ledger.get('strategies') or {}).get('trend_ma_macd')
    if not isinstance(row, dict):
        raise RuntimeError('TREND_MA_MACD_LEDGER_ROW_MISSING')
    shadow = json.loads(json.dumps(ledger))
    shadow['active_strategy_id'] = 'trend_ma_macd'
    shadow['strategies']['trend_ma_macd']['status'] = 'ACTIVE'
    shadow['strategies']['trend_ma_macd']['prospective_boundary_utc'] = BOUNDARY_UTC
    with tempfile.TemporaryDirectory(prefix='top6-trendma-fresh-') as td:
        shadow_path = Path(td) / 'ledger.json'
        shadow_path.write_text(json.dumps(shadow, indent=2, sort_keys=True) + '\n', encoding='utf-8')
        old_ledger, old_argv = ev.LEDGER_PATH, sys.argv[:]
        try:
            ev.LEDGER_PATH = shadow_path
            sys.argv = [old_argv[0], '--strategy-id', 'trend_ma_macd', '--symbols', SYMBOLS, '--out', str(out_path)]
            ev.main()
        finally:
            ev.LEDGER_PATH = old_ledger
            sys.argv = old_argv
    if hashlib.sha256(LEDGER.read_bytes()).hexdigest() != ledger_sha:
        raise RuntimeError('CANONICAL_LEDGER_MUTATED')
    receipt = read(out_path)
    receipt['source_quality_gate'] = ev2.source_quality_gate(receipt)
    return receipt


def evaluate(receipt: Mapping[str, Any]) -> dict[str, Any]:
    q = read(QUALIFIER)
    rb = read(REBOUND)
    if q.get('state') != 'QUEUE_TOP6_FRESH_OOS_VALIDATION' or q.get('eligible_for_fresh_validation') is not True:
        raise RuntimeError('TOP6_REBOUND_NOT_ELIGIBLE_FOR_FRESH_OOS')
    if q.get('lineage_comparator_pass') is not True or int(q.get('parent_T') or 0) != int(q.get('rebound_native_T') or -1):
        raise RuntimeError('TOP6_REBOUND_LINEAGE_NOT_FROZEN')
    if str(receipt.get('strategy_id')) != 'trend_ma_macd':
        raise RuntimeError('FRESH_RECEIPT_STRATEGY_MISMATCH')
    if list(receipt.get('integrity_defects') or []):
        raise RuntimeError('FRESH_RECEIPT_INTEGRITY_DEFECT')
    if int(receipt.get('leakage_lookahead') or 0) != 0:
        raise RuntimeError('FRESH_RECEIPT_LOOKAHEAD_DEFECT')

    boundary_ms = int(datetime.fromisoformat(BOUNDARY_UTC.replace('Z', '+00:00')).timestamp() * 1000)
    native_rows = [dict(x) for x in (receipt.get('trades') or []) if int(x.get('signal_ts') or 0) > boundary_ms and int(x.get('exit_ts') or 0) > boundary_ms]
    dedup: dict[tuple[str, int, int, str], dict[str, Any]] = {}
    for row in sorted(native_rows, key=lambda x: (int(x['signal_ts']), str(x['symbol']), str(x['side']))):
        dedup[trade_key(row)] = row
    native_rows = list(dedup.values())
    child_rows = [x for x in native_rows if str(x.get('side')).lower() == 'long']
    pilot = child_rows[:TARGET_T]
    native_m, pilot_m = metrics(native_rows), metrics(pilot)
    historical = (rb.get('candidate') or {}).get('metrics') or {}

    ready = len(pilot) >= TARGET_T
    checks = {
        'fresh_child_T_ge_12': ready,
        'fresh_symbols_ge_2': int(pilot_m['symbols']) >= 2 if ready else False,
        'fresh_net_pnl_positive': float(pilot_m['net_pnl_bps']) > 0 if ready else False,
        'fresh_expectancy_positive': float(pilot_m['net_expectancy_bps']) > 0 if ready else False,
        'fresh_pf_gt_1': gt_one(pilot_m['profit_factor']) if ready else False,
        'fresh_payoff_ge_1': ge_one(pilot_m['payoff']) if ready else False,
        'fresh_wr_not_below_historical_native': float(pilot_m['win_rate']) + EPS >= float((rb.get('native') or {}).get('metrics', {}).get('win_rate') or 0.0) if ready else False,
        'fresh_dd_finite': math.isfinite(float(pilot_m['drawdown_bps'])) if ready else False,
    }
    if not ready:
        state = 'WAIT_TOP6_FRESH_OOS_12'
    elif all(checks.values()):
        state = 'PASS_TOP6_FRESH_OOS_PILOT'
    else:
        state = 'HOLD_TOP6_FRESH_OOS_FAIL'

    result = {
        'schema_version': SCHEMA,
        'state': state,
        'strategy_id': 'trend_ma_macd',
        'candidate_axis': 'LONG_ONLY_ENTRY_SIDE_QUALIFIER',
        'prospective_boundary_utc': BOUNDARY_UTC,
        'target_fresh_closed_T': TARGET_T,
        'post_boundary_native_T': len(native_rows),
        'post_boundary_long_child_T': len(child_rows),
        'pilot_metrics': pilot_m,
        'native_fresh_metrics': native_m,
        'historical_candidate_metrics_reference': historical,
        'checks': checks,
        'next': 'QUEUE_TOP6_G4_FRESH_25' if state == 'PASS_TOP6_FRESH_OOS_PILOT' else ('WAIT_MORE_FRESH_CLOSED_TRADES' if not ready else 'ROUTE_TREND_MA_MACD_TO_C_MATERIAL'),
        'payoff_optimized_here': False,
        'old_history_union': False,
        'policy_retune': False,
        'threshold_retune': False,
        'production_mutated': False,
        'selection_authority': False,
        'promotion_authority': False,
        'execution_authority': 'NONE',
        'order_authority': 'BLOCKED',
        'live_trade_authority': 'BLOCKED',
        'action': 'hold',
    }
    result['receipt_sha256'] = stable(result)
    return result


def self_test() -> int:
    rows = [
        {'symbol':'BTC-USDT','signal_ts':1,'entry_ts':2,'side':'long','net_bps':100.0},
        {'symbol':'ETH-USDT','signal_ts':3,'entry_ts':4,'side':'long','net_bps':-20.0},
    ]
    m = metrics(rows)
    assert m['trades'] == 2 and m['symbols'] == 2 and abs(m['net_pnl_bps'] - 80.0) < EPS
    assert TARGET_T == 12 and BOUNDARY_UTC.endswith('Z')
    print('PASS_A1_TOP6_TREND_MA_MACD_FRESH_OOS_V1_SELF_TEST')
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', type=Path, default=Path('out/a1_top6_trend_ma_macd_fresh_oos_v1.json'))
    ap.add_argument('--self-test', action='store_true')
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    with tempfile.TemporaryDirectory(prefix='top6-trendma-current-') as td:
        receipt = current_policy_replay(Path(td) / 'receipt.json')
    result = evaluate(receipt)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps({'state':result['state'],'native_T':result['post_boundary_native_T'],'child_T':result['post_boundary_long_child_T'],'pilot':result['pilot_metrics'],'next':result['next'],'receipt':result['receipt_sha256']},sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
