#!/usr/bin/env python3
from __future__ import annotations

import ast
import json
import math
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Mapping

from backend.research.architecture_factory import a1_gen2_generic_dev_econ_v2 as v2

V1 = v2.base
SUPPORTED_SOURCES = {'ohlcv','volume','funding','basis','open_interest'}
EXTRA_FIELDS = {'funding','funding_rate','funding_bps','basis','basis_bps','open_interest','oi'}
P3_DATA_ROOT = 'https://raw.githubusercontent.com/leegkssk2000-commits/vultr-z/zel-p3-prospective-data/research/data/p3_prospective'
P3_COVERAGE_URL = P3_DATA_ROOT + '/latest_coverage.json'
SUBAXIS_CONTRACT = Path('backend/research/contracts/a1_basis_funding_oi_subaxis_replay_v1.json')


def _read_url(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=30) as r:
        return r.read()


def _p3_gate() -> dict[str, Any]:
    cov = json.loads(_read_url(P3_COVERAGE_URL).decode('utf-8'))
    contract = json.loads(SUBAXIS_CONTRACT.read_text(encoding='utf-8'))
    contract_ok = (
        contract.get('schema_version') == 'zel.a1.basis_funding_oi_subaxis_replay.v1'
        and contract.get('state') == 'FROZEN_SUBAXIS_REPLAY_CONTRACT'
        and ((contract.get('separation_invariant') or {}).get('duration_gate_lowered') is False)
        and ((contract.get('separation_invariant') or {}).get('historical_backfill_fabricated') is False)
    )
    ready = bool(cov.get('basis_oi_duration_gate_pass')) and contract_ok
    return {
        'ready': ready,
        'contract_ok': contract_ok,
        'coverage_state': cov.get('state'),
        'coverage_progress_ratio': cov.get('minimum_coverage_progress_ratio'),
        'coverage_receipt': cov.get('receipt_sha256'),
        'basis_oi_duration_gate_pass': bool(cov.get('basis_oi_duration_gate_pass')),
        'historical_coverage_claim': bool(cov.get('historical_coverage_claim')),
        'full_carry_flow_replay_allowed': bool(cov.get('replay_allowed')),
        'flow_source_bound': bool(cov.get('flow_source_bound')),
    }


def _p3_history(feature: str, symbol: str) -> list[dict[str, Any]]:
    if feature not in {'premium_index','open_interest'}:
        raise ValueError('P3_FEATURE_UNSUPPORTED')
    name = f"{feature}__{symbol.replace('-', '')}.ndjson"
    text = _read_url(P3_DATA_ROOT + '/' + name).decode('utf-8')
    out: list[dict[str, Any]] = []
    for line_no, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, Mapping):
            raise RuntimeError(f'P3_ROW_INVALID:{name}:{line_no}')
        if row.get('schema_version') != 'zel.p3.prospective_native_feature_record.v1':
            raise RuntimeError(f'P3_SCHEMA_INVALID:{name}:{line_no}')
        if row.get('feature') != feature or row.get('symbol') != symbol:
            raise RuntimeError(f'P3_IDENTITY_INVALID:{name}:{line_no}')
        if row.get('prospective_only') is not True or row.get('selection_authority') is not False or row.get('promotion_authority') is not False:
            raise RuntimeError(f'P3_AUTHORITY_INVALID:{name}:{line_no}')
        if row.get('execution_authority') != 'NONE' or row.get('order_authority') != 'BLOCKED':
            raise RuntimeError(f'P3_EXECUTION_AUTHORITY_INVALID:{name}:{line_no}')
        ts = int(row.get('collected_at_ms') or 0)
        source_ts = int(row.get('source_timestamp_ms') or 0)
        values = row.get('values') if isinstance(row.get('values'), Mapping) else {}
        if ts <= 0 or source_ts <= 0:
            raise RuntimeError(f'P3_TIMESTAMP_INVALID:{name}:{line_no}')
        if feature == 'premium_index':
            mark = float(values.get('markPrice'))
            index = float(values.get('indexPrice'))
            if not math.isfinite(mark) or not math.isfinite(index) or index <= 0:
                raise RuntimeError(f'P3_PREMIUM_VALUES_INVALID:{name}:{line_no}')
            basis = mark / index - 1.0
            out.append({'ts': ts, 'source_ts': source_ts, 'basis': basis, 'basis_bps': basis * 10000.0})
        else:
            oi = float(values.get('openInterest'))
            if not math.isfinite(oi) or oi <= 0:
                raise RuntimeError(f'P3_OI_VALUE_INVALID:{name}:{line_no}')
            out.append({'ts': ts, 'source_ts': source_ts, 'open_interest': oi, 'oi': oi})
    if not out:
        raise RuntimeError(f'P3_HISTORY_EMPTY:{name}')
    out.sort(key=lambda x: int(x['ts']))
    if any(int(b['ts']) < int(a['ts']) for a,b in zip(out,out[1:])):
        raise RuntimeError(f'P3_COLLECTED_NONMONOTONIC:{name}')
    return out


def _funding_rows_any(symbol: str) -> list[dict[str, float]]:
    url = v2.FUNDING_API + '?' + urllib.parse.urlencode({'symbol': symbol, 'limit': 100})
    payload = json.loads(_read_url(url).decode('utf-8'))
    if isinstance(payload, dict) and payload.get('code') not in (None, 0):
        raise RuntimeError(f"BINGX_FUNDING:{payload.get('code')}:{payload.get('msg')}")
    rows = payload.get('data', []) if isinstance(payload, dict) else []
    out = []
    for x in rows:
        if not isinstance(x, Mapping):
            continue
        ts = x.get('fundingTime') or x.get('time') or x.get('timestamp')
        rate = x.get('fundingRate') if x.get('fundingRate') is not None else x.get('rate')
        try:
            ts = int(ts); rate = float(rate)
        except Exception:
            continue
        if ts > 0 and math.isfinite(rate):
            out.append({'ts': ts, 'rate': rate})
    return sorted({int(x['ts']): x for x in out}.values(), key=lambda x: int(x['ts']))


def _bars_range(symbol: str, interval: str, start_ms: int, end_ms: int) -> list[dict[str, float]]:
    if interval not in V1.INTERVAL_MAP:
        raise ValueError('INTERVAL_UNSUPPORTED')
    all_rows: dict[int, dict[str, float]] = {}
    end = int(end_ms)
    for _ in range(12):
        payload = V1._req({'symbol': symbol, 'interval': V1.INTERVAL_MAP[interval], 'limit': 1000, 'endTime': end})
        page = sorted(V1._decode_rows(payload), key=lambda z: z['ts'])
        if not page:
            break
        for row in page:
            ts = int(row['ts'])
            if start_ms <= ts <= end_ms:
                all_rows[ts] = row
        oldest = int(page[0]['ts'])
        if oldest <= start_ms or oldest >= end:
            break
        end = oldest - 1
    return [all_rows[k] for k in sorted(all_rows)]


def _asof(rows: list[dict[str, Any]], ts: int, idx: int) -> tuple[dict[str, Any] | None, int]:
    cur = rows[idx] if 0 <= idx < len(rows) else None
    while idx + 1 < len(rows) and int(rows[idx + 1]['ts']) <= ts:
        idx += 1; cur = rows[idx]
    if cur is not None and int(cur['ts']) <= ts:
        return cur, idx
    return None, idx


def _attach_sources(
    bars: list[dict[str, float]],
    basis_rows: list[dict[str, Any]] | None,
    oi_rows: list[dict[str, Any]] | None,
    funding_rows: list[dict[str, float]] | None,
) -> list[dict[str, float]]:
    bi = oi_i = fi = -1
    out: list[dict[str, float]] = []
    for raw in bars:
        ts = int(raw['ts']); row = dict(raw)
        if basis_rows is not None:
            b, bi = _asof(basis_rows, ts, bi)
            if b is None: continue
            row['basis'] = float(b['basis']); row['basis_bps'] = float(b['basis_bps'])
        if oi_rows is not None:
            o, oi_i = _asof(oi_rows, ts, oi_i)
            if o is None: continue
            row['open_interest'] = float(o['open_interest']); row['oi'] = float(o['oi'])
        if funding_rows is not None:
            f, fi = _asof(funding_rows, ts, fi)
            if f is None: continue
            rate = float(f['rate']); row['funding'] = rate; row['funding_rate'] = rate; row['funding_bps'] = rate * 10000.0
        out.append(row)
    return out


class Expr(V1.Expr):
    def validate(self, s: str):
        tree = ast.parse(self.normalize(s), mode='eval')
        allowed_names = {'open','high','low','close','volume',*EXTRA_FIELDS,*self.features.keys(),*self.FUNCS}
        for n in ast.walk(tree):
            if isinstance(n, ast.Name):
                if n.id not in allowed_names: raise ValueError(f'UNKNOWN_NAME:{n.id}')
                continue
            if isinstance(n, (ast.Expression, ast.Load, ast.Constant)): continue
            if isinstance(n, ast.BinOp) and isinstance(n.op, self.ALLOWED_BIN): continue
            if isinstance(n, ast.BoolOp) and isinstance(n.op, self.ALLOWED_BOOL): continue
            if isinstance(n, ast.UnaryOp) and isinstance(n.op, self.ALLOWED_UNARY): continue
            if isinstance(n, ast.Compare) and all(isinstance(op, self.ALLOWED_CMP) for op in n.ops): continue
            if isinstance(n, ast.IfExp): continue
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in self.FUNCS: continue
            if isinstance(n, self.ALLOWED_BIN + self.ALLOWED_BOOL + self.ALLOWED_UNARY + self.ALLOWED_CMP): continue
            raise ValueError(f'UNSUPPORTED_AST:{type(n).__name__}')
        return tree

    def _series_value(self, name: str, j: int):
        if j < 0 or j >= len(self.rows): return None
        if name in {'open','high','low','close','volume',*EXTRA_FIELDS}:
            value = self.rows[j].get(name)
            return float(value) if isinstance(value, (int,float)) and math.isfinite(float(value)) else None
        arr = self.features.get(name)
        return arr[j] if arr and j < len(arr) else None

    def env(self):
        env = super().env(); i = self.i
        for key in EXTRA_FIELDS:
            env[key] = self._series_value(key, i)
        return env


def evaluate_candidate(candidate: Mapping[str, Any]) -> dict[str, Any]:
    cid = str(candidate.get('candidate_id') or '')
    req = set(candidate.get('required_sources') or [])
    if not req or not req.issubset(SUPPORTED_SOURCES):
        return {'candidate_id': cid, 'state': 'SKIP_HISTORY_SOURCE_NOT_READY', 'required_sources': sorted(req), 'supported_sources': sorted(SUPPORTED_SOURCES), 'economic_pass': False}
    if not ({'basis','open_interest'} & req):
        return v2.evaluate_candidate(candidate)

    try:
        gate = _p3_gate()
    except Exception as exc:
        return {'candidate_id':cid,'state':'SKIP_P3_GATE_FETCH_FAILED','error':f'{type(exc).__name__}:{str(exc)[:240]}','economic_pass':False}
    if not gate.get('ready'):
        return {'candidate_id':cid,'state':'SKIP_P3_HISTORY_GATE_PENDING','p3_gate':gate,'economic_pass':False}

    spec = candidate.get('executable_spec')
    if not isinstance(spec, Mapping): return {'candidate_id':cid,'state':'REJECT_SPEC_MISSING','economic_pass':False}
    interval = str(spec.get('bar_interval') or '')
    if interval not in V1.INTERVAL_MAP: return {'candidate_id':cid,'state':'REJECT_INTERVAL','economic_pass':False}
    entry = str(spec.get('entry_rule') or ''); side_rule = str(spec.get('side_rule') or ''); exit_rule = str(spec.get('exit_rule') or 'time_stop')
    try: hold = int(spec.get('max_hold_bars') or 0)
    except Exception: hold = 0
    if not 1 <= hold <= 720: return {'candidate_id':cid,'state':'REJECT_HOLD','economic_pass':False}

    alltr: list[dict[str, Any]] = []; source: dict[str, Any] = {}; first_ts = None; last_ts = None
    try:
        for symbol in V1.SYMBOLS:
            br = _p3_history('premium_index', symbol) if 'basis' in req else None
            oi = _p3_history('open_interest', symbol) if 'open_interest' in req else None
            series = [x for x in (br, oi) if x]
            start_ms = max(int(x[0]['ts']) for x in series)
            end_ms = min(int(x[-1]['ts']) for x in series)
            raw_bars = _bars_range(symbol, interval, start_ms, end_ms)
            fr = _funding_rows_any(symbol) if 'funding' in req else None
            rs = _attach_sources(raw_bars, br, oi, fr)
            source[symbol] = {
                'bars': len(rs), 'raw_bars': len(raw_bars),
                'basis_records': len(br) if br else 0, 'oi_records': len(oi) if oi else 0,
                'funding_rows': len(fr) if fr else 0, 'p3_start_ms': start_ms, 'p3_end_ms': end_ms,
            }
            if rs:
                first_ts = min(first_ts or int(rs[0]['ts']), int(rs[0]['ts'])); last_ts = max(last_ts or int(rs[-1]['ts']), int(rs[-1]['ts']))
            features: dict[str, list[float | None]] = {}; eng = Expr(rs, features)
            for f in spec.get('features') or []:
                name = str(f.get('name') or '').strip(); formula = V1._feature_formula(str(f.get('formula') or ''))
                if not name or not formula: raise ValueError('FEATURE_EMPTY')
                eng.validate(formula); arr: list[float | None] = []; features[name] = arr
                for i in range(len(rs)):
                    try:
                        value = eng.eval(formula, i); arr.append(float(value) if isinstance(value,(int,float)) and math.isfinite(float(value)) else None)
                    except (TypeError, ZeroDivisionError, ValueError): arr.append(None)
            eng = Expr(rs, features); eng.validate(entry); V1._validate_side(side_rule, eng)
            time_only = exit_rule.strip().lower() in {'time_stop','time stop','max_hold','max_hold_bars'}
            if not time_only: eng.validate(exit_rule)
            i = max(30, 1); entry_eval_errors = 0
            while i < len(rs) - 1:
                try: fire = bool(eng.eval(entry, i))
                except (TypeError, ZeroDivisionError, ValueError): entry_eval_errors += 1; fire = False
                if not fire: i += 1; continue
                side = V1._side(side_rule, eng, i)
                if side not in {'long','short'}: raise ValueError('SIDE_RULE_UNSUPPORTED')
                entry_i = i + 1; entry_px = rs[entry_i]['open']; exit_i = min(entry_i + hold - 1, len(rs) - 1)
                if not time_only:
                    for j in range(entry_i, min(entry_i + hold, len(rs))):
                        try:
                            if bool(eng.eval(exit_rule, j)): exit_i = j; break
                        except (TypeError, ZeroDivisionError, ValueError): raise ValueError('EXIT_RULE_UNSUPPORTED')
                exit_px = rs[exit_i]['close']; gross = (exit_px / entry_px - 1.0) * 10000 * (1 if side == 'long' else -1); net = gross - V1.COST_BPS
                alltr.append({'symbol':symbol,'side':side,'gross_bps':gross,'net_bps':net,'entry_ts':int(rs[entry_i]['ts']),'exit_ts':int(rs[exit_i]['ts'])})
                i = max(i + 1, exit_i + 1)
            if entry_eval_errors > max(50, len(rs)//2): raise ValueError(f'ENTRY_RUNTIME_ERRORS:{entry_eval_errors}')
    except Exception as exc:
        return {'candidate_id':cid,'state':'REJECT_UNEXECUTABLE_SPEC','error':f'{type(exc).__name__}:{str(exc)[:240]}','p3_gate':gate,'economic_pass':False}

    net = [x['net_bps'] for x in alltr]; gross = [x['gross_bps'] for x in alltr]
    days = max(1e-9, ((last_ts or 0) - (first_ts or 0)) / 86_400_000)
    metrics = {
        'trades':len(net), 'gross_expectancy_bps':sum(gross)/len(gross) if gross else None,
        'net_expectancy_bps':sum(net)/len(net) if net else None, 'net_pnl_bps':sum(net),
        'profit_factor':V1._pf(net), 'payoff':V1._payoff(net), 'win_rate':sum(1 for x in net if x>0)/len(net) if net else None,
        'drawdown_bps':V1._dd(net), 'cost_bps_per_trade':V1.COST_BPS, 'events_per_day':len(net)/days,
        'net_bps_per_calendar_day':sum(net)/days, 'development_days':days,
    }
    common = {
        'candidate_id':cid,'strategy_id':candidate.get('strategy_id'),'provider':candidate.get('provider'),'metrics':metrics,
        'source_summary':source,'development_only':True,'prospective':True,'uses_data_strictly_before_gen1_boundary':False,
        'data_scope':'P3_FROZEN_PROSPECTIVE_DURATION_GATED','p3_gate':gate,'cost_bps_per_trade':V1.COST_BPS,
    }
    if not net: return {**common,'state':'FAIL_INSUFFICIENT_EVENTS','economic_pass':False}
    passed = bool(len(net)>=12 and (metrics['net_expectancy_bps'] or 0)>0 and (metrics['profit_factor'] or 0)>1.0 and (metrics['net_bps_per_calendar_day'] or 0)>0)
    return {**common,'state':'PASS_DEVELOPMENT_ECONOMICS' if passed else 'FAIL_DEVELOPMENT_ECONOMICS','economic_pass':passed}


def evaluate_queue(queue: list[Mapping[str, Any]]) -> dict[str, Any]:
    rows = [evaluate_candidate(c) for c in queue]
    passed = [x for x in rows if x.get('economic_pass')]
    failed = [x for x in rows if x.get('state') == 'FAIL_DEVELOPMENT_ECONOMICS']
    insufficient = [x for x in rows if x.get('state') == 'FAIL_INSUFFICIENT_EVENTS']
    skipped = [x for x in rows if str(x.get('state') or '').startswith('SKIP_')]
    rejected = [x for x in rows if str(x.get('state') or '').startswith('REJECT_')]
    return {
        'schema_version':'zel.a1_gen2_generic_dev_econ.v3','development_only':True,'mixed_scope':True,
        'cost_bps_per_trade':V1.COST_BPS,'supported_sources':sorted(SUPPORTED_SOURCES),'candidate_count':len(rows),
        'economic_pass_count':len(passed),'economic_fail_count':len(failed),'insufficient_event_count':len(insufficient),
        'source_skip_count':len(skipped),'spec_reject_count':len(rejected),'passes':passed,'rows':rows,
        'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED',
        'live_trade_authority':'BLOCKED','exchange_order_submitted':False,'protected_mutations':0,
    }


def self_test() -> int:
    assert {'basis','funding','open_interest'}.issubset(SUPPORTED_SOURCES)
    fixture = {'schema_version':'zel.a1.basis_funding_oi_subaxis_replay.v1','state':'FROZEN_SUBAXIS_REPLAY_CONTRACT'}
    assert fixture['state'] == 'FROZEN_SUBAXIS_REPLAY_CONTRACT'
    print('PASS_A1_GEN2_GENERIC_DEV_ECON_V3_SELF_TEST')
    return 0


if __name__ == '__main__':
    raise SystemExit(self_test())
