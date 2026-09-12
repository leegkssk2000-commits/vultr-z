#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import time
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild import squeeze_kr3_future_dual_generator_v1 as generator
from backend.research.rebuild import squeeze_kr3_native_sleeve_v1 as arbiter

ROOT = Path(__file__).resolve().parents[3]
CONTRACT_PATH = ROOT / 'backend/research/contracts/squeeze_kr3_unified_g5a_collector_v1.json'
STATE_PATH = ROOT / 'backend/research/rebuild/g5_squeeze_kr3_unified_state_v1.json'
EVENTS_PATH = ROOT / 'backend/research/rebuild/g5_squeeze_kr3_unified_events_v1.jsonl'
COST_PATH = ROOT / 'backend/research/rebuild/a1_rebuilt_bb_revert_cost_authority_v1.json'
GENERATOR_PATH = ROOT / 'backend/research/rebuild/squeeze_kr3_future_dual_generator_v1.py'
SOURCE_PATH = ROOT / 'backend/research/rebuild/a1_exact25_generic_evaluator_v1.py'
SCHEMA = 'zel.g5a.squeeze_kr3_unified.completed_campaign.v1'
STATE_SCHEMA = 'zel.g5a.squeeze_kr3_unified.state.v1'
BAR_MS = 14_400_000
AUTHORITY = dict(selection_authority=False, promotion_authority=False,
                 execution_authority='NONE', order_authority='BLOCKED',
                 live_trade_authority='BLOCKED', formal_credit=0)


def now_ms() -> int:
    return int(time.time() * 1000)


def stable(v: Any) -> str:
    return hashlib.sha256(json.dumps(v, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False, allow_nan=False,
                                     default=str).encode()).hexdigest()


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise RuntimeError('JSON_OBJECT_REQUIRED:' + str(path))
    return value


def read_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2,
                               ensure_ascii=False) + '\n')


def write_events(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(x, sort_keys=True, separators=(',', ':'),
                                       ensure_ascii=False) + '\n' for x in rows))


def seal_state(value: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(value)
    out.pop('state_sha256', None)
    out['state_sha256'] = stable(out)
    return out


def validate_contract(c: Mapping[str, Any]) -> None:
    if c['rule_id'] != generator.RULE_ID:
        raise RuntimeError('SQUEEZE_G5A_RULE_ID_DRIFT')
    if c['timeframe'] != '4h' or int(c['bar_ms']) != BAR_MS:
        raise RuntimeError('SQUEEZE_G5A_TIMEFRAME_DRIFT')
    if c['historical_backfill'] is not False or c['pre_boundary_credit'] != 0:
        raise RuntimeError('SQUEEZE_G5A_BOUNDARY_POLICY_DRIFT')
    if c['authority']['order_authority'] != 'BLOCKED':
        raise RuntimeError('SQUEEZE_G5A_ORDER_AUTHORITY_DRIFT')
    if list(c['symbols']) != ['1000PEPE-USDT','BCH-USDT','BTC-USDT','ETH-USDT','HYPE-USDT','LINK-USDT','SOL-USDT']:
        raise RuntimeError('SQUEEZE_G5A_SYMBOL_UNIVERSE_DRIFT')


def validate_chain(rows: list[dict[str, Any]]) -> None:
    prev = None
    seen: set[str] = set()
    for i, row in enumerate(rows):
        if row['schema_version'] != SCHEMA or row['seq'] != i or row['prev_sha256'] != prev:
            raise RuntimeError('SQUEEZE_G5A_EVENT_CHAIN')
        if row['event_id'] in seen:
            raise RuntimeError('SQUEEZE_G5A_EVENT_DUP')
        core = dict(row)
        supplied = core.pop('record_sha256')
        if stable(core) != supplied:
            raise RuntimeError('SQUEEZE_G5A_EVENT_HASH')
        seen.add(row['event_id'])
        prev = supplied


def append(rows: list[dict[str, Any]], payload: Mapping[str, Any]) -> dict[str, Any]:
    row = dict(payload, schema_version=SCHEMA, seq=len(rows),
               prev_sha256=rows[-1]['record_sha256'] if rows else None)
    row['record_sha256'] = stable(row)
    rows.append(row)
    return row


def normalize_closed_bars(symbol: str, current_ms: int) -> list[dict[str, Any]]:
    raw = [dict(x) for x in ev.fetch_bars(symbol, '4h', 1000)]
    rows = []
    for x in raw:
        open_ts = int(x['ts_ms'])
        if open_ts + BAR_MS > current_ms:
            continue
        rows.append(dict(bar_open_ts=open_ts, bar_close_ts=open_ts + BAR_MS,
                         open=float(x['open']), high=float(x['high']),
                         low=float(x['low']), close=float(x['close']),
                         volume=float(x.get('volume', 0))))
    rows.sort(key=lambda x: int(x['bar_open_ts']))
    if len({int(x['bar_open_ts']) for x in rows}) != len(rows):
        raise RuntimeError('SQUEEZE_G5A_SOURCE_DUPLICATE_BAR')
    for a, b in zip(rows, rows[1:]):
        if int(b['bar_open_ts']) - int(a['bar_open_ts']) != BAR_MS:
            raise RuntimeError('SQUEEZE_G5A_SOURCE_GAP')
    return rows


def freeze_cost_models(c: Mapping[str, Any], current_ms: int) -> dict[str, Any]:
    boundary = int(c['qualification_boundary_ms'])
    if current_ms >= boundary + BAR_MS:
        raise RuntimeError('SQUEEZE_G5A_COST_FREEZE_TOO_LATE_FOR_FIRST_BOUNDARY_BAR')
    authority = ev.load_json(COST_PATH)
    if authority.get('state') != 'FROZEN_REALISTIC_PUBLIC_BINGX_COST_AUTHORITY':
        raise RuntimeError('SQUEEZE_G5A_COST_AUTHORITY_INVALID')
    models: dict[str, Any] = {}
    for symbol in c['symbols']:
        snap = ev.fetch_execution_snapshot(symbol, dict(authority))
        model = dict(fee_bps=float(snap['fee_bps']),
                     spread_bps=float(snap['spread_bps']),
                     impact_bps=float(snap['impact_bps']),
                     funding_p95_per_settlement_bps=float(snap['funding_p95_abs_bps']))
        models[symbol] = dict(model=model, model_sha256=stable(model),
                              observed_snapshot_sha256=str(snap['snapshot_sha256']))
    return dict(frozen_at_ms=current_ms, cost_authority_sha256=sha(COST_PATH),
                models=models, freeze_sha256=stable(models))


def make_state(c: Mapping[str, Any], current_ms: int) -> dict[str, Any]:
    cost_freeze = freeze_cost_models(c, current_ms)
    return seal_state(dict(schema_version=STATE_SCHEMA,
        state='SQUEEZE_KR3_UNIFIED_G5A_COLLECTOR_READY_FUTURE_ONLY',
        rule_id=generator.RULE_ID, architecture=generator.ARCHITECTURE,
        boundary_ms=int(c['qualification_boundary_ms']),
        boundary_utc=c['qualification_boundary_utc'], historical_backfill=False,
        symbols=list(c['symbols']), last_scanned_closed_4h_ms=0,
        generator_sha256=sha(GENERATOR_PATH), source_owner_sha256=sha(SOURCE_PATH),
        contract_sha256=sha(CONTRACT_PATH), cost_freeze=cost_freeze,
        completed_campaign_T=0, duplicate_T=0, unknown_exit_T=0,
        censored_open_T=0, g5a_economic_completed_T=0, **AUTHORITY))


def validate_state(s: Mapping[str, Any], c: Mapping[str, Any]) -> None:
    if s['schema_version'] != STATE_SCHEMA or s['rule_id'] != generator.RULE_ID:
        raise RuntimeError('SQUEEZE_G5A_STATE_IDENTITY_DRIFT')
    if int(s['boundary_ms']) != int(c['qualification_boundary_ms']):
        raise RuntimeError('SQUEEZE_G5A_STATE_BOUNDARY_DRIFT')
    if s['historical_backfill'] is not False:
        raise RuntimeError('SQUEEZE_G5A_STATE_BACKFILL_DRIFT')
    core = dict(s)
    supplied = core.pop('state_sha256')
    if stable(core) != supplied:
        raise RuntimeError('SQUEEZE_G5A_STATE_HASH')
    for symbol in c['symbols']:
        if symbol not in s['cost_freeze']['models']:
            raise RuntimeError('SQUEEZE_G5A_COST_MODEL_MISSING:' + symbol)


def _key(row: Mapping[str, Any]) -> tuple[str, int, str]:
    return (str(row['symbol']), int(row['signal_ts']), str(row.get('side', 'long')))


def completed_unified_rows(generated: Mapping[str, Any], bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    core_completed = [dict(r) for r in generated['core_campaigns'] if 'exit_ts' in r]
    donor_completed = {_key(r): dict(r) for r in generated['donor_campaigns'] if 'exit_ts' in r}
    out = list(core_completed)
    plan = generated['arbitration_plan']
    for item in plan['accepted_natural']:
        key = tuple(item['key'])
        if key in donor_completed:
            out.append(donor_completed[key])
    for item in plan['accepted_preempt']:
        raw = dict(item['row'])
        if int(raw['entry_ts']) >= int(item['preempt_ts']):
            raise RuntimeError('SQUEEZE_G5A_INVALID_PREEMPT_ORDER')
        out.append(arbiter.preempt_raw(raw, bars, int(item['preempt_ts'])))
    unique: dict[tuple[str, int, str, str], dict[str, Any]] = {}
    for row in out:
        component = str(row.get('unified_component', 'UNKNOWN'))
        k = (str(row['symbol']), int(row['signal_ts']), str(row.get('side','long')), component)
        if k in unique:
            raise RuntimeError('SQUEEZE_G5A_DUPLICATE_UNIFIED_CAMPAIGN')
        unique[k] = row
    return sorted(unique.values(), key=lambda r: (int(r['entry_ts']), str(r['symbol']), str(r.get('unified_component',''))))


def event_payload(row: Mapping[str, Any], *, source_packet_sha: str,
                  frozen_cost: Mapping[str, Any], observed_at_ms: int,
                  boundary_ms: int) -> dict[str, Any]:
    if int(row['signal_ts']) < boundary_ms or int(row['entry_ts']) < boundary_ms:
        raise RuntimeError('SQUEEZE_G5A_PREBOUNDARY_CAMPAIGN')
    if 'exit_ts' not in row or row.get('exit_reason') is None:
        raise RuntimeError('SQUEEZE_G5A_COMPLETED_CAMPAIGN_EXIT_REQUIRED')
    component = str(row.get('unified_component', 'UNKNOWN'))
    event_id = stable(dict(rule_id=generator.RULE_ID, symbol=row['symbol'],
                           component=component, signal_ts=int(row['signal_ts']),
                           entry_ts=int(row['entry_ts']), exit_ts=int(row['exit_ts']),
                           exit_reason=str(row['exit_reason'])))
    return dict(event_id=event_id, rule_id=generator.RULE_ID,
        component=component, symbol=str(row['symbol']), side=str(row.get('side','long')),
        signal_ts=int(row['signal_ts']), entry_ts=int(row['entry_ts']),
        exit_ts=int(row['exit_ts']), exit_reason=str(row['exit_reason']),
        entry_price=float(row['entry_price']), exit_price=float(row['exit_price']),
        gross_bps=float(row.get('gross_bps', 0.0)),
        source_packet_sha256=source_packet_sha,
        frozen_cost_model_sha256=str(frozen_cost['model_sha256']),
        cost_snapshot_sha256=str(frozen_cost['observed_snapshot_sha256']),
        observed_at_ms=observed_at_ms, duplicate=False, censored=False,
        unknown_exit=False, lifecycle_state='COMPLETED_AWAIT_G5A_ECONOMIC_ACCOUNTING',
        g5a_economic_credit=False, **AUTHORITY)


def run(state: dict[str, Any] | None, events: list[dict[str, Any]], current_ms: int):
    c = read(CONTRACT_PATH)
    validate_contract(c)
    validate_chain(events)
    if state is None:
        state = make_state(c, current_ms)
    else:
        validate_state(state, c)
    known = {x['event_id'] for x in events}
    boundary = int(c['qualification_boundary_ms'])
    new = 0
    max_closed = int(state['last_scanned_closed_4h_ms'])
    open_count = 0
    for symbol in c['symbols']:
        bars = normalize_closed_bars(symbol, current_ms)
        if not bars:
            continue
        max_closed = max(max_closed, int(bars[-1]['bar_close_ts']))
        if int(bars[-1]['bar_close_ts']) <= boundary:
            continue
        cost = deepcopy(state['cost_freeze']['models'][symbol]['model'])
        generated = generator.generate_symbol_campaigns(
            bars, symbol=symbol, eval_start_ms=boundary,
            eval_end_ms=int(bars[-1]['bar_close_ts']), cost_model=cost)
        open_count += len(generated['core_raw'].get('open_positions', [])) + len(generated['donor_raw'].get('open_positions', []))
        packet_sha = stable(bars)
        for row in completed_unified_rows(generated, bars):
            payload = event_payload(row, source_packet_sha=packet_sha,
                                    frozen_cost=state['cost_freeze']['models'][symbol],
                                    observed_at_ms=current_ms, boundary_ms=boundary)
            if payload['event_id'] in known:
                continue
            append(events, payload)
            known.add(payload['event_id'])
            new += 1
    state['last_scanned_closed_4h_ms'] = max_closed
    state['completed_campaign_T'] = len(events)
    state['censored_open_T'] = open_count
    state['duplicate_T'] = 0
    state['unknown_exit_T'] = 0
    state['g5a_economic_completed_T'] = sum(1 for x in events if x.get('g5a_economic_credit') is True)
    state = seal_state(state)
    status = dict(state=state['state'], boundary_ms=boundary,
                  boundary_utc=c['qualification_boundary_utc'], new_completed_campaigns=new,
                  completed_campaign_T=len(events), censored_open_T=open_count,
                  historical_backfill=False, formal_credit=0,
                  g5a_economic_completed_T=state['g5a_economic_completed_T'],
                  next='ACCUMULATE_FUTURE_ONLY_COMPLETED_CAMPAIGNS_AND_BIND_G5A_ECONOMIC_ACCOUNTING',
                  execution_authority='NONE', order_authority='BLOCKED', live_trade_authority='BLOCKED')
    return state, events, status


def self_test() -> int:
    c = read(CONTRACT_PATH)
    validate_contract(c)
    rows: list[dict[str, Any]] = []
    append(rows, dict(event_id='x', rule_id=generator.RULE_ID,
                      component='CAPREUSE82_CORE', symbol='BTC-USDT', side='long',
                      signal_ts=int(c['qualification_boundary_ms']),
                      entry_ts=int(c['qualification_boundary_ms']) + BAR_MS,
                      exit_ts=int(c['qualification_boundary_ms']) + 2 * BAR_MS,
                      exit_reason='TEST', entry_price=1.0, exit_price=1.1,
                      gross_bps=1000.0, source_packet_sha256='s',
                      frozen_cost_model_sha256='c', cost_snapshot_sha256='k',
                      observed_at_ms=1, duplicate=False, censored=False,
                      unknown_exit=False,
                      lifecycle_state='COMPLETED_AWAIT_G5A_ECONOMIC_ACCOUNTING',
                      g5a_economic_credit=False, **AUTHORITY))
    validate_chain(rows)
    inv = generator.invariant_receipt()
    assert inv['saved_campaign_membership_input'] is False
    assert inv['core_priority'] and inv['donor_requires_core_flat'] and inv['later_core_entry_preempts_donor']
    assert int(c['qualification_boundary_ms']) == 1789228800000
    print('PASS_SQUEEZE_KR3_UNIFIED_G5A_COLLECTOR_V1')
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--self-test', action='store_true')
    ap.add_argument('--out-dir')
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    state = read(STATE_PATH) if STATE_PATH.exists() else None
    events = read_events(EVENTS_PATH)
    state, events, status = run(state, events, now_ms())
    out = Path(args.out_dir or ROOT / 'out')
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / 'g5_squeeze_kr3_unified_state_v1.json', state)
    write_events(out / 'g5_squeeze_kr3_unified_events_v1.jsonl', events)
    write_json(out / 'g5_squeeze_kr3_unified_status_v1.json', status)
    print(json.dumps(status, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
