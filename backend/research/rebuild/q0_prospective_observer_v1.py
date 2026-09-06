"""One frozen future Q0 research campaign on the existing collector's payload.

No fetch, strategy search, operational admission or order route. Source journal,
incremental model, locked entry weights and reporting commit together. Historical
prices initialize indicators once; historical economic experiments never run.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from . import q0_prospective_archive_v1 as archive
from . import q0_prospective_capture_v1 as capture
from . import q0_prospective_engine_v1 as engine
from . import q0_prospective_weights_v1 as weights
from . import q0_prospective_accounting_v1 as accounting
from . import q0_b_seen_adapter_v1 as previous

ROOT = previous.old.ROOT
CAMPAIGN = 'Q0_FROZEN_20260907_V1'
OUTPUT = 'research/prospective/' + CAMPAIGN
T0, TEND = 1788739200000, 1799107200000
SEED_END = 1788609600000
SYMBOLS = list(previous.SYMBOLS)
AUTH = {'research_only': True, 'formal_credit': 0, 'operating_adoption': False,
        'independent': False, 'execution': 'NONE', 'order': 'BLOCKED', 'live': 'BLOCKED',
        'G5B_changed': False, 'actual_account_sizing': False, 'paid_external_AI_calls': 0}
BUDGET = {'candidate_cumulative': 26, 'candidate_remaining': 0, 'new_candidates': 0,
          'seen_evaluation_used': 1, 'seen_evaluation_allocated': 1,
          'independent_comparison_used': 0, 'independent_comparison_allocated': 1,
          'independent_comparison_status': 'NOT_RUN', 'automatic_extension': False}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def initialize_model(rows):
    """One-time indicator initialization; historical diagnostic trace is hashed.

    Warmup trace is reproducible from the immutable seed and has no model role.
    Do not copy it into every later checkpoint. Active attempts/indices remain.
    """
    initial = engine.initialize(rows, SYMBOLS, T0, TEND)
    audit = {}
    for symbol, state in initial['by_symbol'].items():
        trace = state['signal_trace']
        audit[symbol] = {'trace_rows': len(trace), 'trace_sha256': archive.digest(trace)}
        state['signal_trace'] = []
    return {'engine': initial, 'weights': weights.initialize(rows, SYMBOLS),
            'observations': {}, 'recordings': [], 'delayed_baskets': [],
            'accounting': None, 'warmup_trace_audit': audit}


def verify(root, *, check_publication=False):
    root = Path(root)
    spec = read(root / 'SPEC.json')
    unsigned = {k: v for k, v in spec.items() if k != 'receipt_sha256'}
    if spec.get('receipt_sha256') != archive.digest(unsigned):
        raise RuntimeError('PROSPECTIVE_SPEC_SEAL')
    if (spec.get('campaign_id') != CAMPAIGN or spec.get('evaluation_interval_ms') != [T0, TEND]
            or spec.get('symbols') != SYMBOLS or spec.get('reference') != previous.REFERENCE
            or spec.get('budget') != BUDGET or spec.get('authority') != AUTH
            or spec.get('seed_end_ms') != SEED_END):
        raise RuntimeError('PROSPECTIVE_FROZEN_SCOPE')
    for path, digest in {**spec['preserved_files_sha256'], **spec['code_files_sha256']}.items():
        if sha(ROOT / path) != digest:
            raise RuntimeError('PROSPECTIVE_FROZEN_BYTES:' + path)
    for name, digest in spec['campaign_files_sha256'].items():
        if sha(root / name) != digest:
            raise RuntimeError('PROSPECTIVE_CAMPAIGN_BYTES:' + name)
    if check_publication:
        relative = str((root / 'SPEC.json').resolve().relative_to(ROOT))
        result = subprocess.run(['git', 'log', '-1', '--format=%H:%ct', '--', relative],
                                cwd=ROOT, capture_output=True, text=True, check=True)
        lines = result.stdout.strip().splitlines()
        if not lines or int(lines[0].split(':')[1]) * 1000 >= T0:
            raise RuntimeError('PROSPECTIVE_PERMANENT_FREEZE_NOT_BEFORE_T0')
        commit = lines[0].split(':')[0]
        saved = subprocess.run(['git', 'show', commit + ':' + relative], cwd=ROOT,
                               capture_output=True, check=True).stdout
        if saved != (root / 'SPEC.json').read_bytes():
            raise RuntimeError('PROSPECTIVE_UNCOMMITTED_SPEC')
        spec['verified_publication_commit'] = commit
    seed = json.loads(gzip.decompress((root / 'warmup.json.gz').read_bytes()))
    boot = json.loads(gzip.decompress((root / 'bootstrap.json.gz').read_bytes()))
    if (seed['purpose'] != 'CAUSAL_WARMUP_ONLY_NO_ECONOMICS'
            or set(seed['rows_by_symbol']) != set(SYMBOLS)
            or boot['engine']['cursor_close_ts'] != SEED_END
            or boot['observations'] or boot['recordings']):
        raise RuntimeError('PROSPECTIVE_BOOTSTRAP_SCOPE')
    for symbol, rows in seed['rows_by_symbol'].items():
        if (len(rows) != 3751 or rows[0]['bar_open_ts'] != previous.SOURCE_START
                or rows[-1]['bar_close_ts'] != SEED_END):
            raise RuntimeError('PROSPECTIVE_WARMUP_PREFIX:' + symbol)
        s = boot['engine']['by_symbol'][symbol]
        if s['position'] or s['pending_entry'] or s['pending_exit'] or s['trades'] or s['events']:
            raise RuntimeError('PROSPECTIVE_INITIAL_NOT_FLAT')
    dev = previous.source.inputs.require_development(previous.old.read(previous.old.probe.STAGE), ROOT)
    if dev['receipt_sha256'] != spec['cost_sha256']:
        raise RuntimeError('PROSPECTIVE_COST_AUTHORITY_DRIFT')
    return spec, seed, boot, dev['cost_by_symbol']


def policy_for(spec):
    policy = previous.old.read(previous.old.POLICY)
    return {**policy, 'batch_id': CAMPAIGN, 'receipt_sha256': spec['receipt_sha256'],
            'combined_data_sha256': spec['data_sha256'],
            'cost_binding_sha256': spec['cost_sha256'],
            'development_interval_ms': [T0, TEND],
            'code_files_sha256': spec['code_files_sha256']}


def validate_packet(packet, recorded_at):
    unsigned = {k: v for k, v in packet.items() if k != 'receipt_sha256'}
    if packet.get('receipt_sha256') != capture.base.sha_json(unsigned):
        raise RuntimeError('PROSPECTIVE_CAPTURE_SEAL')
    if (packet.get('schema_version') != capture.SCHEMA or packet.get('errors')
            or packet.get('original_shadow_exit_code') != 0
            or packet.get('canonical_seed_end_ms') != SEED_END
            or packet.get('source_owner') != archive.SOURCE_OWNER):
        raise RuntimeError('PROSPECTIVE_CAPTURE_FAILED:' + json.dumps(packet.get('errors', [])))
    if (not isinstance(packet.get('generated_at_ms'), int)
            or packet['generated_at_ms'] > recorded_at
            or not isinstance(packet.get('scheduler_fire_ts'), int)
            or packet['scheduler_fire_ts'] > recorded_at):
        raise RuntimeError('PROSPECTIVE_SOURCE_FUTURE_CLOCK')
    for record in packet['records']:
        if (record['observed_at_ms'] > recorded_at
                or record['bar']['bar_close_ts'] > packet['scheduler_fire_ts']):
            raise RuntimeError('PROSPECTIVE_FORMING_OR_FUTURE_BAR')
        if any(record.get(k) != packet.get(k) for k in
               ('source_owner', 'source_commit', 'run_id', 'run_attempt', 'scheduler_fire_ts')):
            raise RuntimeError('PROSPECTIVE_PACKET_RECORD_IDENTITY')
        if (record.get('source_id') != 'bingx_usdtm_public_klines'
                or record.get('stream_id') != 'bingx_swap_4h_closed_v1'):
            raise RuntimeError('PROSPECTIVE_SOURCE_IDENTITY')
        decoded = capture.base.BingxSourceAdapter._decode({'data': [record['raw']]})
        if (len(decoded) != 1 or decoded[0] != record['bar']
                or record.get('source_bar_sha256') != capture.base.sha_json(record['bar'])
                or record.get('raw_row_sha256') != capture.base.sha_json(record['raw'])):
            raise RuntimeError('PROSPECTIVE_RAW_NORMALIZED_PARITY')
        expected_backfill = record['bar']['bar_close_ts'] < (
            packet['scheduler_fire_ts'] // archive.INTERVAL * archive.INTERVAL)
        if record.get('backfill') is not expected_backfill:
            raise RuntimeError('PROSPECTIVE_BACKFILL_CLOCK_CLASSIFICATION')
    return [r for r in packet['records'] if r['bar']['bar_close_ts'] <= TEND]


def verify_source_commit(packet, spec):
    commit = packet.get('source_commit', '')
    if len(commit) != 40 or any(c not in '0123456789abcdef' for c in commit):
        raise RuntimeError('PROSPECTIVE_SOURCE_COMMIT_INVALID')
    sealed = {**spec['preserved_files_sha256'], **spec['code_files_sha256']}
    for name in ('g5_clean_runner_v1.py', 'g5_clean_runner_binding_fix_v1.py',
                 'q0_prospective_capture_v1.py'):
        path = 'backend/research/rebuild/' + name
        result = subprocess.run(['git', 'show', commit + ':' + path], cwd=ROOT,
                                capture_output=True, check=True)
        if hashlib.sha256(result.stdout).hexdigest() != sealed[path]:
            raise RuntimeError('PROSPECTIVE_SOURCE_COMMIT_BYTES:' + path)


def _origin(symbol, signal_ts):
    return previous.source.prior.previous.source_key(
        {'lane_id': previous.source.LANE, 'symbol': symbol, 'signal_ts': signal_ts, 'side': 'long'})


def advance_observer(current, baskets, archive_state, *, seed_rows, costs, policy, recorded_at):
    """Only newly contiguous baskets enter the strategy and rolling window."""
    result = deepcopy(current)
    for basket in baskets:
        old_engine = result['engine']
        new_engine = engine.advance(old_engine, basket['rows_by_symbol'])
        if new_engine['last_daily_bars']:
            result['weights'] = weights.advance(result['weights'], new_engine['last_daily_bars'])
        for symbol in new_engine['symbols']:
            before = old_engine['by_symbol'][symbol]
            after = new_engine['by_symbol'][symbol]
            for signal in after['signals'][len(before['signals']):]:
                if (signal['direction'] == 'UP' and after['pending_entry'] is not None
                        and after['pending_entry']['signal']['signal_ts'] == signal['signal_ts']):
                    key = _origin(symbol, signal['signal_ts'])
                    observation = weights.observation(result['weights'], signal['signal_ts'])
                    observation.update(symbol=symbol, signal_ts=signal['signal_ts'],
                        origin_key=key, entry_ts=signal['signal_ts'],
                        source_observed_at_ms=basket['observed_at_ms'],
                        consumer_recorded_at_ms=recorded_at,
                        source_quality=deepcopy(basket['quality']))
                    if key in result['observations']:
                        raise RuntimeError('PROSPECTIVE_ENTRY_WEIGHT_REASSIGNMENT')
                    result['observations'][key] = observation
            for event in after['trace'][len(before['trace']):]:
                result['recordings'].append({**deepcopy(event), 'symbol': symbol,
                    'source_bar_close_ts': basket['bar_close_ts'],
                    'source_observed_at_ms': basket['source_records'][symbol]['observed_at_ms'],
                    'consumer_recorded_at_ms': recorded_at,
                    'model_event_ts': event.get('ts'),
                    'model_recording_lag_ms': recorded_at - event['ts'] if 'ts' in event else None,
                    'source_run_id': basket['source_records'][symbol]['run_id'],
                    'source_commit': basket['source_records'][symbol]['source_commit'],
                    'quality': deepcopy(basket['quality']), 'actual_fill': False})
        result['engine'] = new_engine
        if basket['quality']['delayed']:
            result['delayed_baskets'].append(basket['bar_close_ts'])
    cursor = result['engine']['cursor_close_ts']
    rows_by = {symbol: seed_rows[symbol] + sorted(
        [r['bar'] for r in archive_state['records'].values()
         if r['symbol'] == symbol and r['bar']['bar_close_ts'] <= cursor],
        key=lambda row: row['bar_open_ts']) for symbol in SYMBOLS}
    view = accounting.build(engine.snapshot(result['engine']), rows_by, costs,
                            result['observations'], SYMBOLS, T0, cursor, TEND, policy=policy)
    previous_view = result.get('accounting') or {}
    # A/B's accepted daily marks never change after the requisite next open.
    for stage in ('A_Q0', 'B_RISK'):
        old_days = previous_view.get('stages', {}).get(stage, {}).get('daily', [])
        new_days = view.get('stages', {}).get(stage, {}).get('daily', [])
        if new_days[:len(old_days)] != old_days:
            raise RuntimeError('PROSPECTIVE_IMMUTABLE_DAILY_MARK_DRIFT:' + stage)
    result['accounting'] = view
    result['last_consumer_recorded_at_ms'] = recorded_at
    return result


def status_of(state, spec):
    model = state['engine_state']
    cursor = state['cursor_ms']
    counts = {'signals': 0, 'closed': 0, 'open': 0, 'pending_entry': 0}
    for s in model['engine']['by_symbol'].values():
        counts['signals'] += len(s['events'])
        counts['closed'] += len(s['trades'])
        counts['open'] += int(s['position'] is not None)
        counts['pending_entry'] += int(s['pending_entry'] is not None)
    integrity = 'CONFLICT_HOLD' if state['quarantine'] else 'GAP_HOLD' if state['unresolved_gaps'] else 'CONTIGUOUS'
    phase = ('WAIT_T0' if cursor < T0 else 'COMPLETE' if cursor == TEND else
             'MODEL_POSITION_OPEN' if counts['open'] else 'OBSERVING_NO_SIGNAL' if not counts['signals'] else 'OBSERVING')
    future = [r for r in state['records'].values() if r['namespace'] == 'FUTURE_OBSERVATION']
    return {'campaign_id': CAMPAIGN, **AUTH, 'budget': BUDGET,
        'spec_sha256': spec['receipt_sha256'], 'T0': T0, 'T_end': TEND,
        'first_eligible_close_ms': T0 + archive.INTERVAL,
        'phase': phase, 'integrity': integrity,
        'source_owner': archive.SOURCE_OWNER, 'archive_generation': state['generation'],
        'archive_sha256': state['head'], 'cursor_ms': cursor,
        'archived_source_records': len(state['records']), 'future_source_records': len(future),
        'first_future_source_saved': bool(future), 'counts': counts,
        'intermediate_6T_reached': counts['closed'] >= 6,
        'intermediate_12T_reached': counts['closed'] >= 12,
        'economic_decision': 'NOT_RUN_WAIT_FUTURE_OBSERVATIONS' if cursor <= T0 else
            'INTEGRITY_HOLD' if integrity != 'CONTIGUOUS' else
            'INSUFFICIENT' if counts['closed'] < 6 else
            'DESCRIPTIVE_FINAL_REQUIRES_REVIEW' if cursor == TEND else 'MONITORING_NOT_ADOPTION',
        'independent_evidence_status': 'NOT_ADJUDICATED',
        'source_observed_at_ms': max((r['observed_at_ms'] for r in state['records'].values()), default=None),
        'last_source_runs': sorted(set(r['run_id'] for r in state['records'].values()
                                      if r['bar']['bar_close_ts'] == cursor)),
        'delayed_baskets': model['delayed_baskets'],
        'warmup_economic_trades': 0, 'cost_model': 'RESEARCH_COST_MODEL',
        'actual_signed_funding': False, 'actual_fills': False,
        'A_primary': 'Q0', 'B_role': 'FROZEN_UNADOPTED_AUXILIARY',
        'C_role': 'EX_POST_ACCOUNTING_ONLY', 'accounting': model.get('accounting')}


def consume(root, packet, *, recorded_at=None, check_publication=True):
    root = Path(root)
    recorded_at = int(time.time() * 1000) if recorded_at is None else recorded_at
    spec, seed, boot, costs = verify(root, check_publication=check_publication)
    envelopes = validate_packet(packet, recorded_at)
    if check_publication:
        verify_source_commit(packet, spec)
    initial = archive.initial_state(SYMBOLS, SEED_END, T0, TEND, boot)
    current = archive.load(root / 'archive', initial)
    state, change = archive.transact(root / 'archive', current['generation'], envelopes,
        lambda m, b, a: advance_observer(m, b, a, seed_rows=seed['rows_by_symbol'],
            costs=costs, policy=policy_for(spec), recorded_at=recorded_at), initial=initial)
    status = status_of(state, spec)
    payload = archive.canonical_bytes(status)
    status_path = root / 'STATUS.json'
    if not status_path.exists() or status_path.read_bytes() != payload:
        archive._atomic(status_path, payload)
    return status, change


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default=OUTPUT)
    parser.add_argument('--consume')
    parser.add_argument('--verify', action='store_true')
    parser.add_argument('--status')
    args = parser.parse_args()
    root = Path(args.root)
    try:
        if args.verify:
            spec, _, boot, _ = verify(root)
            initial = archive.initial_state(SYMBOLS, SEED_END, T0, TEND, boot)
            state = archive.load(root / 'archive', initial)
            status = status_of(state, spec)
            status['verification'] = 'PASS_FROZEN_BYTES_AND_ARCHIVE_CHAIN'
            change = {}
        elif args.consume:
            status, change = consume(root, read(args.consume))
        else:
            parser.error('--verify or --consume is required')
        if args.status:
            capture.write_packet(Path(args.status), {'status': status, 'change': change})
        print(json.dumps({k: v for k, v in status.items() if k != 'accounting'}, sort_keys=True))
        return 0
    except Exception as error:
        failure = {'campaign_id': CAMPAIGN, **AUTH, 'status': 'RESEARCH_CONSUMER_HOLD',
                   'error': str(error), 'error_type': type(error).__name__,
                   'recorded_at_ms': int(time.time() * 1000),
                   'run_id': os.environ.get('GITHUB_RUN_ID'),
                   'run_attempt': os.environ.get('GITHUB_RUN_ATTEMPT'),
                   'positions_preserved': True,
                   'cursor_advanced': 'CHECK_ATOMIC_ARCHIVE_CURRENT; STATUS_WRITE_MAY_FOLLOW_COMMIT'}
        if args.status:
            capture.write_packet(Path(args.status), failure)
        if args.consume and failure['run_id'] and root.exists():
            target = root / 'failures' / (str(failure['run_id']) + '-' + str(failure['run_attempt']) + '.json')
            if not target.exists():
                archive._atomic(target, archive.canonical_bytes(failure))
        print(json.dumps(failure, sort_keys=True))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
