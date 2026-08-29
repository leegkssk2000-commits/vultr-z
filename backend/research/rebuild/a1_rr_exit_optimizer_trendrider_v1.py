#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild import a1_top5_fixed_rr_payoff_shadow_v1 as rr
from backend.research.rebuild.a1_trend_rider_exact_parent_repair_batch_v1 import metrics

ROOT = Path(__file__).resolve().parents[3]
COST = ROOT / 'backend/research/rebuild/a1_rebuilt_bb_revert_cost_authority_v1.json'
TOP5 = ROOT / 'backend/research/rebuild/a1_top5_latest_only_ssot_v1.json'
PREP = ROOT / 'backend/research/prep/rr_exit_optimizer_latest.json'
SCHEMA = 'zel.rr_exit_optimizer.trendrider.v1'
FAMILY = 'RR_GEOMETRY'
TIMEOUT_BARS = 48
MAX_CANDIDATES = 36


def read(p: Path) -> dict[str, Any]:
    x = json.loads(p.read_text())
    if not isinstance(x, dict):
        raise RuntimeError(f'OBJECT_REQUIRED:{p}')
    return x


def stable(v: Any) -> str:
    return hashlib.sha256(json.dumps(v, sort_keys=True, separators=(',', ':'), allow_nan=False, default=str).encode()).hexdigest()


def quantile(xs: list[float], p: float) -> float:
    ys = sorted(float(x) for x in xs)
    if not ys:
        raise RuntimeError('EMPTY_QUANTILE')
    i = (len(ys) - 1) * p
    lo, hi = int(math.floor(i)), int(math.ceil(i))
    if lo == hi:
        return ys[lo]
    w = i - lo
    return ys[lo] * (1 - w) + ys[hi] * w


def payoff(rows: list[Mapping[str, Any]]) -> float | None:
    wins = [float(x['net_bps']) for x in rows if float(x['net_bps']) > 0]
    losses = [-float(x['net_bps']) for x in rows if float(x['net_bps']) < 0]
    if not wins or not losses:
        return None
    return (sum(wins) / len(wins)) / (sum(losses) / len(losses))


def net_day(rows: list[Mapping[str, Any]]) -> float:
    if not rows:
        return 0.0
    start = min(int(x['entry_ts']) for x in rows)
    end = max(int(x['exit_ts']) for x in rows)
    days = max((end - start) / 86400000.0, 1.0 / 24.0)
    return sum(float(x['net_bps']) for x in rows) / days


def positive_windows(rows: list[Mapping[str, Any]], n: int = 3) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda x: (int(x['entry_ts']), str(x.get('symbol') or '')))
    if not ordered:
        return {'positive': 0, 'total': 0, 'nets': []}
    chunks = []
    for k in range(n):
        lo = round(k * len(ordered) / n)
        hi = round((k + 1) * len(ordered) / n)
        if hi > lo:
            chunks.append(ordered[lo:hi])
    nets = [sum(float(x['net_bps']) for x in c) for c in chunks]
    return {'positive': sum(v > 0 for v in nets), 'total': len(nets), 'nets': nets}


def mset(rows: list[dict[str, Any]]) -> dict[str, Any]:
    m = metrics(rows)
    return {
        'T': int(m.get('trades') or 0),
        'WR': float(m.get('win_rate') or 0.0),
        'Gross_bps': float(m.get('gross_pnl_bps') or 0.0),
        'Net_bps': float(m.get('net_pnl_bps') or 0.0),
        'Net_expectancy_bps': float(m.get('net_expectancy_bps') or 0.0),
        'Net_day_bps': float(net_day(rows)),
        'PF': float(m.get('profit_factor') or 0.0),
        'payoff': payoff(rows),
        'DD_bps': float(m.get('drawdown_bps') or 0.0),
        'worst_loss_bps': min([float(x['net_bps']) for x in rows] or [0.0]),
        'positive_windows': positive_windows(rows),
    }


def row_path(src: Mapping[str, Any], bars: list[dict[str, Any]]) -> dict[str, Any]:
    idx = {int(b['ts_ms']): i for i, b in enumerate(bars)}
    si, ei, xi = idx.get(int(src['signal_ts'])), idx.get(int(src['entry_ts'])), idx.get(int(src['exit_ts']))
    if si is None or ei is None or xi is None:
        raise RuntimeError(f'ROW_BAR_MISSING:{src.get("symbol")}:{src.get("signal_ts")}')
    entry = float(src.get('entry') or bars[ei]['open'])
    one_r = rr.native_r(src, bars, si, entry)
    if one_r <= 0:
        raise RuntimeError('NONPOSITIVE_NATIVE_R')
    side = str(src['side'])
    mfe = mae = 0.0
    for j in range(ei, xi + 1):
        hi, lo = float(bars[j]['high']), float(bars[j]['low'])
        if side == 'long':
            mfe = max(mfe, hi - entry)
            mae = max(mae, entry - lo)
        else:
            mfe = max(mfe, entry - lo)
            mae = max(mae, hi - entry)
    return {'mfe_r': max(0.0, mfe / one_r), 'mae_r': max(0.0, mae / one_r)}


def simulate_control(rows: list[dict[str, Any]], bars_by: Mapping[str, list[dict[str, Any]]], snaps: Mapping[str, Any], cost_mult: float = 1.0, plus_one_bar: bool = False) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        sym = str(row['symbol']); bars = list(bars_by[sym]); idx = {int(b['ts_ms']): i for i, b in enumerate(bars)}
        ei = idx.get(int(row['entry_ts']))
        if ei is None:
            raise RuntimeError(f'ENTRY_BAR_MISSING:{sym}:{row["entry_ts"]}')
        entry = float(row.get('entry') or bars[ei]['open']); side = str(row['side'])
        geo = row.get('intent_geometry') if isinstance(row.get('intent_geometry'), Mapping) else {}
        stop = geo.get('sl') if isinstance(geo, Mapping) else None
        if stop is None:
            si = idx.get(int(row['signal_ts']))
            if si is None: raise RuntimeError('SIGNAL_BAR_MISSING')
            r = rr.native_r(row, bars, si, entry)
            stop = entry - r if side == 'long' else entry + r
        stop = float(stop)
        last = min(len(bars) - 1, ei + TIMEOUT_BARS)
        px = ts = reason = None; hit_index = None
        for j in range(ei, last + 1):
            lo, hi = float(bars[j]['low']), float(bars[j]['high'])
            hit = lo <= stop if side == 'long' else hi >= stop
            if hit:
                px, ts, reason, hit_index = stop, int(bars[j]['ts_ms']), 'SL', j
                break
        if px is None:
            px, ts, reason, hit_index = float(bars[last]['close']), int(bars[last]['ts_ms']), 'TIMEOUT', last
        if plus_one_bar and hit_index is not None and hit_index + 1 < len(bars):
            hit_index += 1; px = float(bars[hit_index]['open']); ts = int(bars[hit_index]['ts_ms']); reason += '_PLUS1'
        snap = snaps[sym]
        funding = ev.funding_cost(int(row['entry_ts']), int(ts), list(snap['funding_rows']))
        base_cost = float(snap['fee_bps']) + float(snap['spread_bps']) + float(snap['impact_bps']) + funding
        cost = cost_mult * base_cost
        gross = (float(px) - entry) / entry * 10000.0 if side == 'long' else (entry - float(px)) / entry * 10000.0
        out.append({**{k: row.get(k) for k in ('symbol','signal_ts','entry_ts','side')}, 'exit_ts': int(ts), 'entry': entry, 'exit': float(px), 'reason': reason, 'gross_bps': gross, 'realized_cost_bps': cost, 'net_bps': gross - cost})
    return out


def simulate_candidate(rows: list[dict[str, Any]], tp_r: float, sl_r: float, bars_by: Mapping[str, list[dict[str, Any]]], snaps: Mapping[str, Any], cost_mult: float = 1.0, plus_one_bar: bool = False) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        sym = str(row['symbol']); bars = list(bars_by[sym]); idx = {int(b['ts_ms']): i for i, b in enumerate(bars)}
        si, ei = idx.get(int(row['signal_ts'])), idx.get(int(row['entry_ts']))
        if si is None or ei is None: raise RuntimeError(f'ROW_BAR_MISSING:{sym}:{row["signal_ts"]}')
        entry = float(row.get('entry') or bars[ei]['open']); side = str(row['side']); one_r = rr.native_r(row, bars, si, entry)
        stop = entry - sl_r * one_r if side == 'long' else entry + sl_r * one_r
        target = entry + tp_r * one_r if side == 'long' else entry - tp_r * one_r
        last = min(len(bars) - 1, ei + TIMEOUT_BARS)
        px = ts = reason = None; hit_index = None
        for j in range(ei, last + 1):
            lo, hi = float(bars[j]['low']), float(bars[j]['high'])
            hit_sl = lo <= stop if side == 'long' else hi >= stop
            hit_tp = hi >= target if side == 'long' else lo <= target
            # Conservative same-bar ordering: adverse stop wins ties.
            if hit_sl:
                px, ts, reason, hit_index = stop, int(bars[j]['ts_ms']), 'SL', j; break
            if hit_tp:
                px, ts, reason, hit_index = target, int(bars[j]['ts_ms']), 'TP', j; break
        if px is None:
            px, ts, reason, hit_index = float(bars[last]['close']), int(bars[last]['ts_ms']), 'TIMEOUT', last
        if plus_one_bar and hit_index is not None and hit_index + 1 < len(bars):
            hit_index += 1; px = float(bars[hit_index]['open']); ts = int(bars[hit_index]['ts_ms']); reason += '_PLUS1'
        snap = snaps[sym]
        funding = ev.funding_cost(int(row['entry_ts']), int(ts), list(snap['funding_rows']))
        base_cost = float(snap['fee_bps']) + float(snap['spread_bps']) + float(snap['impact_bps']) + funding
        cost = cost_mult * base_cost
        gross = (float(px) - entry) / entry * 10000.0 if side == 'long' else (entry - float(px)) / entry * 10000.0
        out.append({**{k: row.get(k) for k in ('symbol','signal_ts','entry_ts','side')}, 'exit_ts': int(ts), 'entry': entry, 'exit': float(px), 'reason': reason, 'gross_bps': gross, 'realized_cost_bps': cost, 'net_bps': gross - cost})
    return out


def bounds_from_development(dev: list[dict[str, Any]], bars_by: Mapping[str, list[dict[str, Any]]]) -> tuple[list[float], list[float], dict[str, Any]]:
    paths = []
    for row in dev:
        paths.append(row_path(row, list(bars_by[str(row['symbol'])])))
    mfe = [x['mfe_r'] for x in paths if x['mfe_r'] > 0]
    mae = [x['mae_r'] for x in paths if x['mae_r'] > 0]
    # Development-only, quantile-derived. Historical fixed-RR examples are not injected.
    sl_raw = [quantile(mae, p) for p in (0.35, 0.50, 0.65, 0.80)]
    tp_raw = [quantile(mfe, p) for p in (0.55, 0.70, 0.82, 0.92)]
    sl = sorted({round(max(0.35, min(2.50, x)), 3) for x in sl_raw})
    tp = sorted({round(max(1.0, min(100.0, x)), 3) for x in tp_raw})
    return tp, sl, {
        'method': 'DEVELOPMENT_ONLY_MFE_MAE_QUANTILES',
        'mfe_r_quantiles': {str(p): quantile(mfe, p) for p in (0.25,0.50,0.75,0.90,0.95)},
        'mae_r_quantiles': {str(p): quantile(mae, p) for p in (0.25,0.50,0.75,0.90,0.95)},
        'tp_candidates': tp, 'sl_candidates': sl,
    }


def split_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    ordered = sorted(rows, key=lambda x: (int(x['signal_ts']), str(x.get('symbol') or '')))
    cut = max(18, min(len(ordered)-8, int(math.floor(len(ordered)*0.70))))
    raw_dev, raw_val = ordered[:cut], ordered[cut:]
    val_start = min(int(x['signal_ts']) for x in raw_val)
    # Purge any development trade whose realized horizon reaches the validation start.
    dev = [x for x in raw_dev if int(x['exit_ts']) < val_start]
    val = raw_val
    if len(dev) < 12 or len(val) < 6:
        raise RuntimeError(f'INSUFFICIENT_PURGED_SPLIT:{len(dev)}:{len(val)}')
    return dev, val, {'ordered_T': len(ordered), 'raw_cut': cut, 'purged_dev_T': len(dev), 'validation_T': len(val), 'validation_start_ts': val_start, 'scheme': 'CHRONOLOGICAL_70_30_PURGED_BY_REALIZED_EXIT'}


def relation(c: dict[str, Any], b: dict[str, Any]) -> dict[str, bool]:
    cp, bp = c.get('payoff'), b.get('payoff')
    return {
        'net_improved': c['Net_bps'] > b['Net_bps'],
        'expectancy_improved': c['Net_expectancy_bps'] > b['Net_expectancy_bps'],
        'net_day_improved': c['Net_day_bps'] > b['Net_day_bps'],
        'wr_retention': c['WR'] + 1e-12 >= 0.80 * b['WR'],
        'pf_no_hard_regression': c['PF'] + 1e-12 >= 0.95 * b['PF'],
        'payoff_no_hard_regression': cp is not None and bp is not None and cp + 1e-12 >= 0.95 * bp,
        'dd_no_hard_regression': c['DD_bps'] <= 1.05 * b['DD_bps'] + 1e-12,
        'one_secondary_improved': (c['PF'] > b['PF']) or (cp is not None and bp is not None and cp > bp) or (c['DD_bps'] < b['DD_bps']),
        'positive_windows_nonworse': c['positive_windows']['positive'] >= b['positive_windows']['positive'],
    }


def pass_relation(r: Mapping[str, bool]) -> bool:
    return all(bool(v) for v in r.values())


def objective(c: dict[str, Any], b: dict[str, Any]) -> float:
    # Net/expectancy/net-day dominate; PF/payoff/DD only break near ties.
    dn = (c['Net_bps'] - b['Net_bps']) / max(abs(b['Net_bps']), 1.0)
    de = (c['Net_expectancy_bps'] - b['Net_expectancy_bps']) / max(abs(b['Net_expectancy_bps']), 1.0)
    dd = (c['Net_day_bps'] - b['Net_day_bps']) / max(abs(b['Net_day_bps']), 1.0)
    sec = math.log1p(max(c['PF'],0.0)) + math.log1p(max(float(c.get('payoff') or 0),0.0)) - math.log1p(max(c['DD_bps'],0.0))/10.0
    return 0.45*dn + 0.35*de + 0.20*dd + 1e-3*sec


def choose(rows: list[dict[str, Any]], bars_by: Mapping[str, list[dict[str, Any]]], snaps: Mapping[str, Any]) -> dict[str, Any]:
    dev, val, split = split_rows(rows)
    tp_vals, sl_vals, search_space = bounds_from_development(dev, bars_by)
    if len(tp_vals)*len(sl_vals) > MAX_CANDIDATES:
        raise RuntimeError('SEARCH_BUDGET_EXCEEDED')
    base_dev_rows = simulate_control(dev,bars_by,snaps); base_val_rows = simulate_control(val,bars_by,snaps); base_full_rows = simulate_control(rows,bars_by,snaps)
    base_dev, base_val, base_full = mset(base_dev_rows), mset(base_val_rows), mset(base_full_rows)
    cells = []
    for ti,tp in enumerate(tp_vals):
        for si,sl in enumerate(sl_vals):
            drows=simulate_candidate(dev,tp,sl,bars_by,snaps); dm=mset(drows); dr=relation(dm,base_dev)
            cells.append({'tp_r':tp,'sl_r':sl,'RR':tp/sl,'dev':dm,'dev_relation':dr,'dev_pass':pass_relation(dr),'objective':objective(dm,base_dev),'ti':ti,'si':si})
    eligible = sorted([x for x in cells if x['dev_pass']], key=lambda x:(x['objective'],x['dev']['Net_bps']), reverse=True)
    if not eligible:
        return {'state':'NO_ROBUST_RR_OPTIMUM','reason':'NO_DEVELOPMENT_PARETO_CELL','split':split,'search_space':search_space,'candidate_count':len(cells),'control':{'development':base_dev,'validation':base_val,'full':base_full},'cells':cells}
    # Validate development-ranked cells without using validation to alter numeric search bounds.
    validated=[]
    for cell in eligible:
        tp,sl=cell['tp_r'],cell['sl_r']; vrows=simulate_candidate(val,tp,sl,bars_by,snaps); frows=simulate_candidate(rows,tp,sl,bars_by,snaps)
        vm,fm=mset(vrows),mset(frows); vr,fr=relation(vm,base_val),relation(fm,base_full)
        c2=mset(simulate_candidate(rows,tp,sl,bars_by,snaps,cost_mult=2.0)); b2=mset(simulate_control(rows,bars_by,snaps,cost_mult=2.0))
        p1=mset(simulate_candidate(rows,tp,sl,bars_by,snaps,plus_one_bar=True)); bp1=mset(simulate_control(rows,bars_by,snaps,plus_one_bar=True))
        stress={'COST_2X':{'candidate':c2,'control':b2,'positive':c2['Net_bps']>0,'nonworse_net':c2['Net_bps']>b2['Net_bps']},'PLUS_ONE_BAR':{'candidate':p1,'control':bp1,'positive':p1['Net_bps']>0,'nonworse_net':p1['Net_bps']>bp1['Net_bps']}}
        # Neighborhood is defined in the predeclared quantile grid; no post-hoc bounds.
        neigh=[]
        for other in cells:
            if abs(int(other['ti'])-int(cell['ti']))<=1 and abs(int(other['si'])-int(cell['si']))<=1 and other is not cell:
                of=mset(simulate_candidate(rows,other['tp_r'],other['sl_r'],bars_by,snaps)); neigh.append({'tp_r':other['tp_r'],'sl_r':other['sl_r'],'net_delta_bps':of['Net_bps']-base_full['Net_bps'],'positive_direction':of['Net_bps']>base_full['Net_bps']})
        plateau = bool(neigh) and sum(1 for x in neigh if x['positive_direction'])/len(neigh) >= 0.60
        guard = pass_relation(vr) and pass_relation(fr) and plateau and all(v['positive'] and v['nonworse_net'] for v in stress.values()) and len(cells)<=MAX_CANDIDATES
        validated.append({**cell,'validation':vm,'validation_relation':vr,'full':fm,'full_relation':fr,'stress':stress,'neighbor_stability':{'neighbors':neigh,'positive_fraction':(sum(1 for x in neigh if x['positive_direction'])/len(neigh) if neigh else 0.0),'plateau_pass':plateau},'overfit_guard':{'pass':guard,'candidate_count':len(cells),'development_rank_precedes_validation':True,'validation_not_used_for_bounds':True}})
    good=[x for x in validated if x['overfit_guard']['pass']]
    if not good:
        return {'state':'NO_ROBUST_RR_OPTIMUM','reason':'INTERNAL_VALIDATION_OR_STABILITY_FAIL','split':split,'search_space':search_space,'candidate_count':len(cells),'control':{'development':base_dev,'validation':base_val,'full':base_full},'validated':validated}
    # Preserve development ranking; among near-tied valid cells choose simpler plateau center (larger neighborhood fraction, then middle indices).
    best_dev=max(x['objective'] for x in good); near=[x for x in good if x['objective']>=best_dev-0.02]
    near.sort(key=lambda x:(x['neighbor_stability']['positive_fraction'],-abs(x['ti']-(len(tp_vals)-1)/2)-abs(x['si']-(len(sl_vals)-1)/2),x['objective']),reverse=True)
    chosen=near[0]
    return {'state':'PASS_INTERNAL_ROBUST_OPTIMUM','split':split,'search_space':search_space,'candidate_count':len(cells),'control':{'development':base_dev,'validation':base_val,'full':base_full},'chosen':chosen,'validated_count':len(good)}


def run(source: Path, out: Path) -> dict[str, Any]:
    src=read(source); top5=read(TOP5); prep=read(PREP) if PREP.exists() else {}
    rows=[dict(x) for x in src.get('trades') or []]
    if len(rows)<25: raise RuntimeError(f'SSOT_MIN_T_NOT_MET:{len(rows)}')
    defects=list(src.get('integrity_defects') or [])
    if defects or int(src.get('duplicate_count') or 0)!=0 or int(src.get('leakage_lookahead_count') or 0)!=0:
        raise RuntimeError('INELIGIBLE_SOURCE_INTEGRITY')
    syms=sorted({str(x['symbol']) for x in rows}); bars_by={s:ev.fetch_bars(s,'1h',1000) for s in syms}; authority=read(COST); snaps={s:ev.fetch_execution_snapshot(s,authority) for s in syms}
    result=choose(rows,bars_by,snaps)
    parent_sha=str(src.get('receipt_sha256') or prep.get('parent_receipt_sha256') or stable(src))
    search_generation_sha=stable({'schema':SCHEMA,'parent_sha':parent_sha,'family':FAMILY,'source_artifact':9446790894,'split':result.get('split'),'search_space':result.get('search_space'),'objective':'ROBUST_NET_EXPECTANCY_NET_DAY_PARETO'})
    now=datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00','Z')
    base={
      'schema_version':SCHEMA,'strategy_id':'trend_rider','strategy_role':'G4_ECONOMIC_SURVIVOR','parent_sha':parent_sha,'exit_family':FAMILY,
      'search_generation_sha':search_generation_sha,'search_method':'DETERMINISTIC_QUANTILE_COARSE_GRID_PLUS_PREDECLARED_NEIGHBOR_STABILITY','search_budget':MAX_CANDIDATES,
      'development_window':result.get('split'),'validation_scheme':'CHRONOLOGICAL_PURGED_INTERNAL_VALIDATION','source_artifact_id':9446790894,
      'g5_w2_w3_used_for_search':False,'fresh_prospective_used_for_search':False,'old_history_union':False,'entry_logic_frozen':True,'timeout_bars_frozen':TIMEOUT_BARS,
      'execution_authority':'NONE','order_authority':'BLOCKED','live_trade_authority':'BLOCKED','selection_authority':False,'promotion_authority':False,'protected_mutations':0,
      'duplicate':0,'leakage':0,'integrity':0,'result':result
    }
    if result.get('state')=='PASS_INTERNAL_ROBUST_OPTIMUM':
        ch=result['chosen']; params={'TP_R':ch['tp_r'],'SL_R':-ch['sl_r'],'RR':ch['RR'],'timeout':TIMEOUT_BARS,'BE':None,'partial':None,'trailing':None,'runner':None}
        child_sha=stable({'parent_sha':parent_sha,'family':FAMILY,'params':params,'search_generation_sha':search_generation_sha})
        base.update({'state':'PREREGISTERED_FRESH_PROSPECTIVE','action':'hold','exact_params':params,'rr_child_sha':child_sha,'boundary_ts':now,'Pareto_relation':'DEVELOPMENT_AND_PURGED_INTERNAL_VALIDATION_ROBUST_PARETO_PASS','next_axis':'FRESH_PROSPECTIVE_RR_GEOMETRY_ONLY_NO_RETUNE'})
    else:
        base.update({'state':'NO_ROBUST_RR_OPTIMUM','action':'route_change','exact_params':None,'rr_child_sha':None,'boundary_ts':None,'Pareto_relation':'NO_ADOPTABLE_INTERNAL_ROBUST_PLATEAU','next_axis':'TIMEOUT_AFTER_RR_GEOMETRY_FALSIFIED_OR_MORE_DEVELOPMENT_DATA'})
    base['artifact_sha']=stable(base); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(base,indent=2,sort_keys=True,allow_nan=False)+'\n'); return base


def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument('--source',type=Path); ap.add_argument('--out',type=Path,default=Path('out/rr_exit_optimizer.json')); ap.add_argument('--self-test',action='store_true'); a=ap.parse_args()
    if a.self_test:
        assert stable({'b':1,'a':2})==stable({'a':2,'b':1}); assert MAX_CANDIDATES==36; print('PASS_RR_EXIT_OPTIMIZER_SELF_TEST'); return 0
    if a.source is None: raise SystemExit('--source required')
    r=run(a.source,a.out); print(json.dumps({'state':r['state'],'exact_params':r.get('exact_params'),'boundary_ts':r.get('boundary_ts'),'child':r.get('rr_child_sha'),'candidate_count':r['result'].get('candidate_count')},sort_keys=True)); return 0

if __name__=='__main__': raise SystemExit(main())
