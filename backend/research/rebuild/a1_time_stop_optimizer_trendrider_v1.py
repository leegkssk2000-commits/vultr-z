#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_rr_exit_optimizer_trendrider_v1 as rr_opt
from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild import a1_top5_fixed_rr_payoff_shadow_v1 as rr

ROOT = Path(__file__).resolve().parents[3]
PREV = ROOT / 'backend/research/prep/rr_exit_optimizer_latest.json'
OUT_DEFAULT = Path('out/time_stop_optimizer.json')
SCHEMA = 'zel.exit_optimizer.trendrider.time_stop.v1'
FAMILY = 'TIMEOUT_TIME_STOP'
SOURCE_ARTIFACT_ID = 9446790894
CONTROL_TIMEOUT_BARS = 48
MAX_CANDIDATES = 12
REQUIRED_T = 25


def read(p: Path) -> dict[str, Any]:
    x = json.loads(p.read_text())
    if not isinstance(x, dict):
        raise RuntimeError(f'OBJECT_REQUIRED:{p}')
    return x


def stable(v: Any) -> str:
    return hashlib.sha256(json.dumps(v, sort_keys=True, separators=(',', ':'), allow_nan=False, default=str).encode()).hexdigest()


def q(xs: list[float], p: float) -> float:
    ys = sorted(float(x) for x in xs)
    if not ys:
        raise RuntimeError('EMPTY_QUANTILE')
    i = (len(ys) - 1) * p
    lo, hi = int(math.floor(i)), int(math.ceil(i))
    if lo == hi:
        return ys[lo]
    w = i - lo
    return ys[lo] * (1.0 - w) + ys[hi] * w


def bars_held(row: Mapping[str, Any]) -> int:
    return max(1, int(round((int(row['exit_ts']) - int(row['entry_ts'])) / 3_600_000.0)))


def timeout_candidates(rows: list[dict[str, Any]]) -> tuple[list[int], dict[str, Any]]:
    held = [bars_held(x) for x in rows]
    qs = {str(p): q(held, p) for p in (0.20, 0.35, 0.50, 0.65, 0.80, 0.90)}
    raw = [int(round(v / 3.0) * 3) for v in qs.values()]
    vals = sorted({max(6, min(96, int(v))) for v in raw if int(v) != CONTROL_TIMEOUT_BARS})
    if not vals:
        vals = [36, 60]
    if len(vals) > MAX_CANDIDATES:
        vals = vals[:MAX_CANDIDATES]
    return vals, {
        'method': 'DEVELOPMENT_ONLY_BARS_HELD_QUANTILES',
        'bars_held_quantiles': qs,
        'candidate_timeout_bars': vals,
        'control_timeout_bars': CONTROL_TIMEOUT_BARS,
        'historical_fixed_rr_cells_used': False,
    }


def simulate_timeout(rows: list[dict[str, Any]], timeout_bars: int,
                     bars_by: Mapping[str, list[dict[str, Any]]], snaps: Mapping[str, Any],
                     cost_mult: float = 1.0, plus_one_bar: bool = False) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        sym = str(row['symbol'])
        bars = list(bars_by[sym])
        idx = {int(b['ts_ms']): i for i, b in enumerate(bars)}
        si, ei = idx.get(int(row['signal_ts'])), idx.get(int(row['entry_ts']))
        if si is None or ei is None:
            raise RuntimeError(f'ROW_BAR_MISSING:{sym}:{row.get("signal_ts")}')
        entry = float(row.get('entry') or bars[ei]['open'])
        side = str(row['side'])
        geo = row.get('intent_geometry') if isinstance(row.get('intent_geometry'), Mapping) else {}
        stop = geo.get('sl') if isinstance(geo, Mapping) else None
        if stop is None:
            one_r = rr.native_r(row, bars, si, entry)
            stop = entry - one_r if side == 'long' else entry + one_r
        stop = float(stop)
        last = min(len(bars) - 1, ei + int(timeout_bars))
        px = ts = reason = None
        hit_index = None
        for j in range(ei, last + 1):
            lo, hi = float(bars[j]['low']), float(bars[j]['high'])
            hit = lo <= stop if side == 'long' else hi >= stop
            if hit:
                px, ts, reason, hit_index = stop, int(bars[j]['ts_ms']), 'SL', j
                break
        if px is None:
            px, ts, reason, hit_index = float(bars[last]['close']), int(bars[last]['ts_ms']), 'TIMEOUT', last
        if plus_one_bar and hit_index is not None and hit_index + 1 < len(bars):
            hit_index += 1
            px, ts = float(bars[hit_index]['open']), int(bars[hit_index]['ts_ms'])
            reason += '_PLUS1'
        snap = snaps[sym]
        funding = ev.funding_cost(int(row['entry_ts']), int(ts), list(snap['funding_rows']))
        base_cost = float(snap['fee_bps']) + float(snap['spread_bps']) + float(snap['impact_bps']) + funding
        cost = cost_mult * base_cost
        gross = (float(px) - entry) / entry * 10000.0 if side == 'long' else (entry - float(px)) / entry * 10000.0
        out.append({
            **{k: row.get(k) for k in ('symbol', 'signal_ts', 'entry_ts', 'side')},
            'exit_ts': int(ts), 'entry': entry, 'exit': float(px), 'reason': reason,
            'gross_bps': gross, 'realized_cost_bps': cost, 'net_bps': gross - cost,
        })
    return out


def evaluate(rows: list[dict[str, Any]], bars_by: Mapping[str, list[dict[str, Any]]], snaps: Mapping[str, Any]) -> dict[str, Any]:
    vals, search_space = timeout_candidates(rows)
    if len(vals) > MAX_CANDIDATES:
        raise RuntimeError('SEARCH_BUDGET_EXCEEDED')
    base_rows = simulate_timeout(rows, CONTROL_TIMEOUT_BARS, bars_by, snaps)
    base = rr_opt.mset(base_rows)
    base2 = rr_opt.mset(simulate_timeout(rows, CONTROL_TIMEOUT_BARS, bars_by, snaps, cost_mult=2.0))
    base1 = rr_opt.mset(simulate_timeout(rows, CONTROL_TIMEOUT_BARS, bars_by, snaps, plus_one_bar=True))
    cells: list[dict[str, Any]] = []
    for i, timeout in enumerate(vals):
        crows = simulate_timeout(rows, timeout, bars_by, snaps)
        cm = rr_opt.mset(crows)
        rel = rr_opt.relation(cm, base)
        c2 = rr_opt.mset(simulate_timeout(rows, timeout, bars_by, snaps, cost_mult=2.0))
        c1 = rr_opt.mset(simulate_timeout(rows, timeout, bars_by, snaps, plus_one_bar=True))
        stress = {
            'COST_2X': {'candidate': c2, 'control': base2, 'positive': c2['Net_bps'] > 0, 'nonworse_net': c2['Net_bps'] > base2['Net_bps']},
            'PLUS_ONE_BAR': {'candidate': c1, 'control': base1, 'positive': c1['Net_bps'] > 0, 'nonworse_net': c1['Net_bps'] > base1['Net_bps']},
        }
        cells.append({
            'timeout_bars': timeout, 'metrics': cm, 'relation': rel,
            'base_pass': rr_opt.pass_relation(rel),
            'stress': stress,
            'stress_pass': all(v['positive'] and v['nonworse_net'] for v in stress.values()),
            'objective': rr_opt.objective(cm, base), 'index': i,
        })
    for cell in cells:
        i = int(cell['index'])
        neigh = [x for x in cells if x is not cell and abs(int(x['index']) - i) <= 1]
        pos = [x for x in neigh if x['metrics']['Net_bps'] > base['Net_bps']]
        frac = len(pos) / len(neigh) if neigh else 0.0
        cell['neighbor_stability'] = {
            'neighbors': [{'timeout_bars': x['timeout_bars'], 'net_delta_bps': x['metrics']['Net_bps'] - base['Net_bps']} for x in neigh],
            'positive_fraction': frac,
            'plateau_pass': bool(neigh) and frac >= 0.50,
        }
        cell['robust_pass'] = bool(cell['base_pass'] and cell['stress_pass'] and cell['neighbor_stability']['plateau_pass'])
    good = [x for x in cells if x['robust_pass']]
    if not good:
        return {
            'state': 'NO_ROBUST_TIME_STOP_OPTIMUM', 'reason': 'DEVELOPMENT_PLATEAU_OR_STRESS_FAIL',
            'search_space': search_space, 'candidate_count': len(cells), 'control': base, 'cells': cells,
        }
    best_obj = max(float(x['objective']) for x in good)
    near = [x for x in good if float(x['objective']) >= best_obj - 0.02]
    near.sort(key=lambda x: (x['neighbor_stability']['positive_fraction'], -abs(int(x['timeout_bars']) - CONTROL_TIMEOUT_BARS), x['objective']), reverse=True)
    chosen = near[0]
    return {
        'state': 'PASS_DEVELOPMENT_ONLY_ROBUST_TIME_STOP_PLATEAU',
        'search_space': search_space, 'candidate_count': len(cells), 'control': base,
        'chosen': chosen, 'robust_count': len(good), 'cells': cells,
    }


def run(source: Path, out: Path) -> dict[str, Any]:
    src = read(source)
    prev = read(PREV)
    rows = [dict(x) for x in src.get('trades') or []]
    if len(rows) < REQUIRED_T:
        raise RuntimeError(f'SSOT_MIN_T_NOT_MET:{len(rows)}')
    if list(src.get('integrity_defects') or []) or int(src.get('duplicate_count') or 0) != 0 or int(src.get('leakage_lookahead_count') or 0) != 0:
        raise RuntimeError('INELIGIBLE_SOURCE_INTEGRITY')
    if prev.get('state') != 'NO_ROBUST_RR_OPTIMUM' or prev.get('next_axis') != FAMILY:
        raise RuntimeError('RR_GEOMETRY_NOT_CLOSED_OR_WRONG_NEXT_AXIS')
    anti = prev.get('anti_stagnation') if isinstance(prev.get('anti_stagnation'), Mapping) else {}
    if int(anti.get('same_insufficiency_observed_consecutively') or 0) < 2:
        raise RuntimeError('ANTI_STAGNATION_ROTATION_NOT_AUTHORIZED')
    syms = sorted({str(x['symbol']) for x in rows})
    bars_by = {s: ev.fetch_bars(s, '1h', 1000) for s in syms}
    authority = read(rr_opt.COST)
    snaps = {s: ev.fetch_execution_snapshot(s, authority) for s in syms}
    result = evaluate(rows, bars_by, snaps)
    parent_sha = str(src.get('receipt_sha256') or stable(src))
    generation = stable({
        'schema': SCHEMA, 'parent_sha': parent_sha, 'family': FAMILY,
        'source_artifact': SOURCE_ARTIFACT_ID, 'search_space': result.get('search_space'),
        'objective': 'ROBUST_REALISTIC_COST_NET_EXPECTANCY_NET_DAY_PARETO',
        'control_timeout_bars': CONTROL_TIMEOUT_BARS,
    })
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')
    base: dict[str, Any] = {
        'schema_version': SCHEMA, 'strategy_id': 'trend_rider', 'strategy_role': 'G4_ECONOMIC_SURVIVOR',
        'parent_sha': parent_sha, 'exit_family': FAMILY, 'search_generation_sha': generation,
        'source_artifact_id': SOURCE_ARTIFACT_ID, 'T': len(rows),
        'development_scheme': 'FULL_G4_BROAD30_DEVELOPMENT_ONLY_AFTER_HISTORICAL_INTERNAL_OOS_DECLARED_STRUCTURALLY_INSUFFICIENT',
        'validation_scheme': 'TRUE_PROSPECTIVE_FIRST_N_REQUIRED_NO_RETUNE',
        'historical_internal_oos_reused': False, 'g5_w2_w3_used_for_search': False, 'fresh_prospective_used_for_search': False,
        'entry_logic_frozen': True, 'stop_geometry_frozen': True, 'rr_geometry_frozen': True,
        'execution_authority': 'NONE', 'order_authority': 'BLOCKED', 'live_trade_authority': 'BLOCKED',
        'selection_authority': False, 'promotion_authority': False, 'protected_mutations': 0,
        'duplicate': 0, 'leakage': 0, 'integrity': 0,
        'search_method': 'DEVELOPMENT_ONLY_BARS_HELD_QUANTILES_PLUS_NEIGHBOR_PLATEAU',
        'search_budget': MAX_CANDIDATES, 'result': result,
    }
    if result.get('state') == 'PASS_DEVELOPMENT_ONLY_ROBUST_TIME_STOP_PLATEAU':
        ch = result['chosen']
        params = {'timeout_bars': int(ch['timeout_bars']), 'control_timeout_bars': CONTROL_TIMEOUT_BARS, 'BE': None, 'partial': None, 'trailing': None, 'runner': None}
        child_sha = stable({'parent_sha': parent_sha, 'family': FAMILY, 'params': params, 'generation': generation})
        base.update({
            'state': 'PREREGISTERED_TRUE_PROSPECTIVE_TIME_STOP', 'action': 'hold',
            'exact_params': params, 'exit_child_sha': child_sha, 'boundary_ts': now,
            'control_metrics': result['control'], 'candidate_metrics': ch['metrics'],
            'neighbor_stability': ch['neighbor_stability'], 'stress': ch['stress'],
            'overfit_guard': {'pass_for_promotion': False, 'development_plateau_pass': True, 'true_prospective_required': True, 'candidate_count': result['candidate_count']},
            'Pareto_relation': 'DEVELOPMENT_ONLY_ROBUST_PLATEAU_FROZEN_NOT_PROMOTION_EVIDENCE',
            'next_axis': 'TRUE_PROSPECTIVE_FIRST_N_TIME_STOP_NO_RETUNE',
        })
    else:
        base.update({
            'state': 'NO_ROBUST_TIME_STOP_OPTIMUM', 'action': 'route_change', 'exact_params': None, 'exit_child_sha': None,
            'boundary_ts': None, 'control_metrics': result.get('control'), 'candidate_metrics': None,
            'neighbor_stability': None, 'stress': None,
            'overfit_guard': {'pass_for_promotion': False, 'development_plateau_pass': False, 'true_prospective_required': False, 'candidate_count': result.get('candidate_count')},
            'Pareto_relation': 'NO_ADOPTABLE_ROBUST_TIME_STOP_PLATEAU', 'next_axis': 'BREAKEVEN',
        })
    base['artifact_sha'] = stable(base)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(base, indent=2, sort_keys=True, allow_nan=False) + '\n')
    return base


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--source', type=Path)
    ap.add_argument('--out', type=Path, default=OUT_DEFAULT)
    ap.add_argument('--self-test', action='store_true')
    a = ap.parse_args()
    if a.self_test:
        assert stable({'b': 1, 'a': 2}) == stable({'a': 2, 'b': 1})
        assert CONTROL_TIMEOUT_BARS == 48 and MAX_CANDIDATES == 12
        print('PASS_TIME_STOP_OPTIMIZER_SELF_TEST')
        return 0
    if a.source is None:
        raise SystemExit('--source required')
    r = run(a.source, a.out)
    print(json.dumps({'state': r['state'], 'exact_params': r.get('exact_params'), 'boundary_ts': r.get('boundary_ts'), 'child': r.get('exit_child_sha')}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
